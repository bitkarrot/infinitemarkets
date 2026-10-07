"""Public checkout — spec sections 8.1, 8.2, 4.15, 11.4, 15.

The intake/claim/invoice pipeline:

1. ``Idempotency-Key`` validation + ``idempotency_records`` unique-insert
   claim BEFORE any order row exists (§4.15). Replay returns the stored
   (AEAD-encrypted) response; concurrent in-flight requests get 409
   ``request-in-progress``; key reuse with a different body gets 409
   ``idempotency-conflict``.
2. Intake validation (§8.1/§15): bounded items, merchant active, products
   purchasable, address required iff physical, ``email_opt_in`` requires
   ``email``, shipping option valid for the destination.
3. Server-side totals only — client-sent amounts are never trusted.
4. Intake transaction: orders(received) + items + fx snapshots + audit
   event + token material + ``order_received`` email intents.
5. Claim transaction (§8.2 step 1): sorted-product-id conditional stock
   updates + held reservations + CAS ``received -> invoice_pending`` + the
   ``payments`` projection with deterministic ``core_external_id`` and
   ``status='creating'`` — all BEFORE the LNbits call.
6. ``create_invoice`` outside any transaction; ``InvoiceError.status``
   drives the outcome split — ``failed`` is definitive, ``pending``/other
   exceptions are ``creation_unknown`` (never a second invoice).
7. Attach transaction: projection fields persisted regardless of commerce
   state; ``awaiting_payment`` only for a still-``invoice_pending`` order.

Public tokens (§11.4): minted once at intake; only the SHA-256 lookup hash
plus an AEAD copy (for eligible delayed email rendering) are stored.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from decimal import Decimal, InvalidOperation

from .. import crypto
from ..db import DomainTransaction, db, table
from ..security import ProblemError, conflict, not_found, unprocessable
from ..settings import ExtSettings, ext_settings
from . import fx
from . import orders as order_service

IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
EXTERNAL_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
REGION_RE = re.compile(r"^[A-Z]{2}-[A-Z0-9]{1,3}$")

MAX_ITEMS = 64
MAX_QTY = 10_000
MAX_OPEN_ORDERS_PER_SCOPE = 10
MAX_HELD_PER_PRODUCT = 100
IDEMPOTENCY_LEASE_S = 120
IDEMPOTENCY_TTL_S = 30 * 86400
TOKEN_TTL_S = 30 * 86400
INVOICE_MEMO = "Infinitemarkets order"


def _now() -> int:
    return int(time.time())


# --- idempotency (section 4.15) -------------------------------------------


def _scope_hash(merchant_id: str, route: str, key: str) -> str:
    """SHA-256 of merchant + method + normalized route + idempotency key.

    IP is never part of idempotency identity (§4.15).
    """
    return hashlib.sha256(
        f"{merchant_id}|POST|{route}|{key}".encode()
    ).hexdigest()


def _request_hash(payload: dict) -> str:
    """Canonical immutable request hash for conflict detection."""
    canonical = json.dumps(
        {
            "merchant_pubkey": payload.get("merchant_pubkey"),
            "items": payload.get("items"),
            "shipping_option_d": payload.get("shipping_option_d"),
            "address": payload.get("address"),
            "email": payload.get("email"),
            "phone": payload.get("phone"),
            "email_opt_in": payload.get("email_opt_in"),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


async def _claim_idempotency(
    scope: str, request_hash: str, *, now: int
) -> dict:
    """Claim a fenced idempotency record, replaying completed responses.

    Raises 409 ``request-in-progress`` while a lease is live and 409
    ``idempotency-conflict`` on key reuse with a different request hash.
    An expired lease is reclaimed (state flips back to in_progress with a
    fresh lease) — the linked order, if any, resumes through the saga.
    """
    async with DomainTransaction() as tx:
        claimed = await tx.execute(
            f"INSERT INTO {tx.table('idempotency_records')} "
            "(scope_hash, request_hash, state, lease_until, created_at, expires_at, claim_token) "
            "VALUES (:s, :r, 'in_progress', :l, :n, :e, 1) "
            "ON CONFLICT (scope_hash) DO NOTHING",
            {
                "s": scope, "r": request_hash, "l": now + IDEMPOTENCY_LEASE_S,
                "n": now, "e": now + IDEMPOTENCY_TTL_S,
            },
        )
        if claimed == 1:
            return {"state": "in_progress", "claim_token": 1}
        row = await tx.fetch_one(
            f"SELECT * FROM {tx.table('idempotency_records')} "
            "WHERE scope_hash = :s" + tx.for_update,
            {"s": scope},
        )
        if row["request_hash"] != request_hash:
            raise conflict(
                "idempotency-conflict", "Idempotency conflict",
                "this key was already used with a different request",
            )
        if row["state"] == "completed" and row["response_enc"] is not None:
            return dict(row)
        if (
            row["state"] == "in_progress"
            and row["lease_until"]
            and row["lease_until"] > now
        ):
            raise conflict(
                "request-in-progress", "Request in progress",
                "an identical request is still being processed",
            )
        # Expired lease or failed attempt — reclaim with the same hash.
        rc = await tx.execute(
            f"UPDATE {tx.table('idempotency_records')} "
            "SET state = 'in_progress', lease_until = :l, claim_token = claim_token + 1"
            " WHERE scope_hash = :s",
            {"s": scope, "l": now + IDEMPOTENCY_LEASE_S},
        )
        if rc != 1:
            raise conflict(
                "request-in-progress", "Request in progress",
                "an identical request is still being processed",
            )
        record = dict(row) | {
            "state": "in_progress", "claim_token": row["claim_token"] + 1,
            "lease_until": now + IDEMPOTENCY_LEASE_S,
        }
        if row["order_id"]:
            # A crashed lease with a linked order resumes through the saga —
            # never restart the intake blindly (§4.15).
            return {"_resume_order_id": row["order_id"], **record}
        return record


async def _complete_idempotency(
    scope: str, *, order_id: str, status_code: int, response_body: dict,
    settings: ExtSettings, now: int, claim_token: int,
) -> None:
    enc = crypto.encrypt(
        json.dumps(response_body).encode(),
        settings.master_keys[settings.active_key_version],
        record_id=scope, table="idempotency_records",
        column="response_enc", key_version=settings.active_key_version,
    )
    async with DomainTransaction() as tx:
        await tx.execute(
            f"UPDATE {tx.table('idempotency_records')} "
            "SET state = 'completed', status_code = :c, response_enc = :r, lease_until = 0"
            " WHERE scope_hash = :s AND order_id = :o AND claim_token = :t"
            " AND state = 'in_progress' AND lease_until > :n",
            {"s": scope, "o": order_id, "c": status_code, "r": enc,
             "t": claim_token, "n": await tx.now()},
        )


async def _fail_idempotency(scope: str, claim_token: int) -> None:
    async with DomainTransaction() as tx:
        await tx.execute(
            f"UPDATE {tx.table('idempotency_records')} "
            "SET state = 'failed', lease_until = 0 WHERE scope_hash = :s"
            " AND claim_token = :t AND state = 'in_progress' AND lease_until > :n",
            {"s": scope, "t": claim_token, "n": await tx.now()},
        )


async def replay_response(record: dict) -> dict | None:
    """Decrypt a stored idempotent response (§4.15)."""
    if record.get("response_enc") is None:
        return None
    settings = ext_settings()
    ver = crypto.envelope_version(record["response_enc"])
    raw = crypto.decrypt(
        record["response_enc"], settings.master_keys[ver],
        record_id=record["scope_hash"], table="idempotency_records",
        column="response_enc", key_version=ver,
    )
    return json.loads(raw)


# --- intake validation (sections 8.1, 15) ----------------------------------


def validate_idempotency_key(key: str | None) -> str:
    """§5.4: checkout without a valid Idempotency-Key is a 400."""
    if not key or not IDEMPOTENCY_KEY_RE.match(key):
        raise ProblemError(
            400, "idempotency-key-required", "Bad Request",
            "Idempotency-Key must match [A-Za-z0-9_-]{32,128}",
        )
    return key


async def _merchant_for_checkout(pubkey: str) -> dict:
    from .nip89 import merchant_by_pubkey

    merchant = await merchant_by_pubkey(pubkey)
    if not merchant or merchant["state"] != "active":
        raise unprocessable(
            "merchant-inactive", "Merchant unavailable",
            "merchant is not accepting orders",
        )
    return merchant


async def _resolve_items(
    merchant_id: str, items: list[dict],
) -> list[dict]:
    """Resolve each ``{d_tag, quantity}`` to a purchasable product."""
    if not isinstance(items, list) or not items or len(items) > MAX_ITEMS:
        raise unprocessable(
            "invalid-content", "Invalid items",
            f"items must be a non-empty list of at most {MAX_ITEMS}",
        )
    resolved = []
    seen = set()
    async with db.connect() as conn:
        for entry in items:
            if not isinstance(entry, dict):
                raise unprocessable("invalid-content", "Invalid item")
            d_tag = entry.get("d_tag")
            qty = entry.get("quantity")
            if not isinstance(d_tag, str) or not isinstance(qty, int) or isinstance(qty, bool):
                raise unprocessable("invalid-content", "Invalid item")
            if qty < 1 or qty > MAX_QTY:
                raise unprocessable(
                    "invalid-content", "Invalid quantity",
                    f"quantity must be 1..{MAX_QTY}",
                )
            if d_tag in seen:
                raise unprocessable("invalid-content", "Duplicate cart item")
            seen.add(d_tag)
            row = await conn.fetchone(
                f"SELECT * FROM {table('products')} "
                "WHERE merchant_id = :m AND d_tag = :d",
                {"m": merchant_id, "d": d_tag},
            )
            if not row or row["deleted_at"] is not None:
                raise not_found("product not found")
            product = dict(row)
            _assert_purchasable(product)
            resolved.append({"product": product, "qty": qty})
    # A variation's parent must remain variable and on-sale.
    async with db.connect() as conn:
        for entry in resolved:
            p = entry["product"]
            if p["product_type"] == "variation":
                parent = await conn.fetchone(
                    f"SELECT product_type, visibility, deleted_at FROM"
                    f" {table('products')} WHERE id = :i",
                    {"i": p["parent_product_id"]},
                )
                if (
                    not parent
                    or parent["product_type"] != "variable"
                    or parent["visibility"] != "on-sale"
                    or parent["deleted_at"] is not None
                ):
                    raise unprocessable(
                        "product-inactive", "Product unavailable",
                        "variation parent is not on-sale",
                    )
    return resolved


def _assert_purchasable(product: dict) -> None:
    """Section 8.1 step 5: v1 purchasability rules."""
    if product["draft"] or (
        product["import_source_kind"] is not None and not product["import_authorized"]
    ):
        raise unprocessable("product-inactive", "Product unavailable")
    if product["visibility"] != "on-sale":
        raise unprocessable(
            "product-inactive", "Product unavailable",
            "only on-sale products are purchasable in v1",
        )
    if product["nip99_status"] != "active":
        raise unprocessable("product-inactive", "Product unavailable")
    if product["recurring_frequency"] is not None:
        raise unprocessable(
            "product-inactive", "Product unavailable",
            "subscriptions are not supported in v1",
        )
    if product["product_type"] == "variable":
        raise unprocessable(
            "product-inactive", "Product unavailable",
            "a variable parent is never directly purchasable",
        )
    if product["product_type"] not in ("simple", "variation"):
        raise unprocessable("product-inactive", "Product unavailable")


async def _resolve_shipping(
    merchant_id: str, d_tag: str, address: dict,
) -> dict:
    """Resolve + coverage-check one active same-merchant shipping option."""
    async with db.connect() as conn:
        row = await conn.fetchone(
            f"SELECT * FROM {table('shipping_options')} "
            "WHERE merchant_id = :m AND d_tag = :d AND deleted_at IS NULL",
            {"m": merchant_id, "d": d_tag},
        )
    if not row or not row["active"]:
        raise unprocessable(
            "invalid-shipping-destination", "Shipping unavailable",
            "shipping option not found or inactive",
        )
    option = dict(row)
    country = address.get("country")
    if not isinstance(country, str) or not COUNTRY_RE.fullmatch(country.upper()):
        raise unprocessable(
            "invalid-shipping-destination", "Invalid destination",
            "address.country must be ISO 3166-1 alpha-2",
        )
    country = country.upper()
    region = address.get("region")
    if region is not None:
        if (
            not isinstance(region, str) or not REGION_RE.fullmatch(region.upper())
            or not region.upper().startswith(country + "-")
        ):
            raise unprocessable(
                "invalid-shipping-destination", "Invalid destination",
                "address.region must be ISO 3166-2 within the selected country",
            )
        region = region.upper()
    countries = json.loads(option["countries"]) if option["countries"] else []
    if not countries or country not in countries:
        raise unprocessable(
            "invalid-shipping-destination", "Invalid destination",
            "shipping option does not cover this country",
        )
    regions = json.loads(option["regions"]) if option["regions"] else []
    if regions and region not in regions:
        raise unprocessable(
            "invalid-shipping-destination", "Invalid destination",
            "shipping option does not cover this region",
        )
    if not option["currency"] or option["base_price_minor"] is None:
        raise unprocessable("invalid-shipping-destination", "Shipping price unavailable")
    return option


WEIGHT_FACTORS = {
    "mg": "0.000001", "g": "0.001", "kg": "1", "t": "1000",
    "lb": "0.45359237", "oz": "0.028349523125",
}
LENGTH_FACTORS = {"mm": "0.001", "cm": "0.01", "m": "1", "in": "0.0254", "ft": "0.3048"}


def _measurement(value, unit: str | None, factors: dict[str, str]) -> Decimal:
    if value is None or not isinstance(unit, str) or unit not in factors:
        raise unprocessable("invalid-shipping-destination", "Missing or unsupported measurement")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise unprocessable("invalid-shipping-destination", "Invalid measurement") from exc
    if not number.is_finite() or number < 0:
        raise unprocessable("invalid-shipping-destination", "Invalid measurement")
    return number * Decimal(factors[unit])


def _check_shipping_constraints(option: dict, resolved: list[dict]) -> None:
    """Weight/dimension bounds across the whole cart (§8.1 step 7)."""
    physical = [entry for entry in resolved if entry["product"]["format"] == "physical"]
    if option.get("weight_min") is not None or option.get("weight_max") is not None:
        weight = sum(
            _measurement(e["product"].get("weight_value"), e["product"].get("weight_unit"),
                         WEIGHT_FACTORS) * e["qty"]
            for e in physical
        )
        for bound in ("min", "max"):
            value = option.get(f"weight_{bound}")
            if value is None:
                continue
            limit = _measurement(value, option.get("weight_unit"), WEIGHT_FACTORS)
            if (bound == "min" and weight < limit) or (bound == "max" and weight > limit):
                raise unprocessable("invalid-shipping-destination", "Cart weight outside limits")
    for entry in physical:
        product = entry["product"]
        for axis in ("l", "w", "h"):
            for bound in ("min", "max"):
                value = option.get(f"dim_{bound}_{axis}")
                if value is None:
                    continue
                size = _measurement(product.get(f"dim_{axis}"), product.get("dim_unit"),
                                    LENGTH_FACTORS)
                limit = _measurement(value, option.get("dim_unit"), LENGTH_FACTORS)
                if (bound == "min" and size < limit) or (bound == "max" and size > limit):
                    raise unprocessable(
                        "invalid-shipping-destination", "Item dimensions outside limits",
                    )


def _volume_factor(unit: str | None) -> Decimal:
    unit = (unit or "").replace("³", "3").replace("^3", "3").lower()
    if unit in ("l", "ml"):
        return Decimal("0.001" if unit == "l" else "0.000001")
    if unit.endswith("3") and unit[:-1] in LENGTH_FACTORS:
        return Decimal(LENGTH_FACTORS[unit[:-1]]) ** 3
    raise unprocessable("invalid-shipping-destination", "Unsupported volume unit")


async def _shipping_components(
    option: dict, resolved: list[dict],
) -> list[tuple[str, int, Decimal]]:
    currency = option["currency"]
    decimals = option["currency_decimals"]
    components = [(currency, decimals, Decimal(option["base_price_minor"]))]
    physical = [entry for entry in resolved if entry["product"]["format"] == "physical"]
    if option.get("price_weight_minor") is not None:
        weight = sum(
            _measurement(e["product"].get("weight_value"), e["product"].get("weight_unit"),
                         WEIGHT_FACTORS) * e["qty"]
            for e in physical
        ) / _measurement(1, option.get("price_weight_unit"), WEIGHT_FACTORS)
        components.append((currency, decimals, weight * option["price_weight_minor"]))
    if option.get("price_volume_minor") is not None:
        volume = Decimal(0)
        for entry in physical:
            product = entry["product"]
            dimensions = [
                _measurement(product.get(f"dim_{axis}"), product.get("dim_unit"), LENGTH_FACTORS)
                for axis in ("l", "w", "h")
            ]
            volume += dimensions[0] * dimensions[1] * dimensions[2] * entry["qty"]
        volume /= _volume_factor(option.get("price_volume_unit"))
        components.append((currency, decimals, volume * option["price_volume_minor"]))
    async with db.connect() as conn:
        for entry in physical:
            product = entry["product"]
            refs = await conn.fetchall(
                f"SELECT extra_cost_minor FROM {table('product_shipping_options')}"
                " WHERE product_id = :p AND shipping_option_id = :s",
                {"p": product["id"], "s": option["id"]},
            )
            if not refs:
                refs = await conn.fetchall(
                    f"SELECT psc.extra_cost_minor FROM {table('product_shipping_collections')} psc"
                    f" JOIN {table('collections')} c ON c.id = psc.collection_id"
                    f" JOIN {table('collection_shipping')} cs ON cs.collection_id = c.id"
                    " WHERE psc.product_id = :p AND cs.shipping_option_id = :s"
                    " AND c.merchant_id = :m AND c.deleted_at IS NULL",
                    {"p": product["id"], "s": option["id"], "m": product["merchant_id"]},
                )
            extras = {row["extra_cost_minor"] or 0 for row in refs}
            if len(extras) != 1:
                raise unprocessable(
                    "invalid-shipping-destination", "Shipping option does not apply unambiguously",
                )
            extra = extras.pop()
            if not isinstance(extra, int) or extra < 0:
                raise unprocessable("invalid-shipping-destination", "Invalid shipping surcharge")
            components.append((
                product["currency"], product["currency_decimals"] or 0,
                Decimal(extra * entry["qty"]),
            ))
    return components


async def _open_order_count(merchant_id: str, scope_hash: str) -> int:
    async with db.connect() as conn:
        row = await conn.fetchone(
            f"SELECT COUNT(*) AS n FROM {table('orders')} "
            "WHERE merchant_id = :m AND protocol = 'web'"
            " AND checkout_scope_hash = :s"
            " AND state IN ('received', 'invoice_pending',"
            " 'awaiting_payment')",
            {"m": merchant_id, "s": scope_hash},
        )
    return int(row["n"]) if row else 0


async def _held_reservation_count(product_id: str) -> int:
    async with db.connect() as conn:
        row = await conn.fetchone(
            f"SELECT COUNT(*) AS n FROM {table('inventory_reservations')} "
            "WHERE product_id = :p AND state = 'held'",
            {"p": product_id},
        )
    return int(row["n"]) if row else 0


# --- the checkout pipeline --------------------------------------------------


async def _resolve_cart(
    merchant_id: str, payload: dict,
) -> tuple[list[dict], dict | None, dict | None]:
    resolved = await _resolve_items(merchant_id, payload.get("items") or [])
    any_physical = any(e["product"]["format"] == "physical" for e in resolved)
    address = payload.get("address")
    if any_physical and not isinstance(address, dict):
        raise unprocessable(
            "invalid-shipping-destination", "Address required",
            "a structured address is required for physical items",
        )
    shipping_option = None
    if any_physical:
        d_tag = payload.get("shipping_option_d")
        if not isinstance(d_tag, str) or not d_tag:
            raise unprocessable(
                "invalid-shipping-destination", "Shipping required",
                "physical items require shipping_option_d",
            )
        shipping_option = await _resolve_shipping(merchant_id, d_tag, address)
        _check_shipping_constraints(shipping_option, resolved)
    return resolved, address, shipping_option


async def _price_cart(resolved: list[dict], shipping_option: dict | None, now: int) -> tuple:
    # --- server-side totals (§3.4/§8.1 step 6) ---
    quotes: dict[str, fx.FxQuote] = {}
    components: list[int] = []
    line_rows: list[dict] = []
    subtotal_sat = 0
    for entry in resolved:
        p = entry["product"]
        currency = p["currency"] or "SAT"
        if currency not in quotes:
            try:
                quotes[currency] = (
                    fx.sat_quote() if currency == "SAT"
                    else await fx.quote_currency(currency)
                )
            except fx.FxRejection as exc:
                raise unprocessable(
                    "fx-unavailable", "Price conversion unavailable",
                    f"cannot price {currency}: {exc}",
                ) from exc
        quote = quotes[currency]
        unit_minor = p["amount_minor"] or 0
        line_minor = unit_minor * entry["qty"]
        try:
            line_sat = fx.convert_line(
                quote, currency=currency, amount_minor=line_minor,
                currency_decimals=p["currency_decimals"] or 0, now=now,
            )
        except fx.FxRejection as exc:
            raise unprocessable(
                "fx-unavailable", "Price conversion unavailable", str(exc),
            ) from exc
        components.append(line_sat)
        subtotal_sat += line_sat
        line_rows.append(
            {"product": p, "qty": entry["qty"], "unit_minor": unit_minor,
             "currency": currency,
             "decimals": p["currency_decimals"] or 0,
             "line_sat": line_sat}
        )
    shipping_sat = 0
    if shipping_option is not None:
        for cur, decimals, minor in await _shipping_components(shipping_option, resolved):
            try:
                if cur not in quotes:
                    quotes[cur] = fx.sat_quote() if cur == "SAT" else await fx.quote_currency(cur)
                scale = max(0, -minor.as_tuple().exponent)
                amount = fx.convert_line(
                    quotes[cur], currency=cur, amount_minor=int(minor.scaleb(scale)),
                    currency_decimals=decimals + scale, now=_now(),
                )
            except fx.FxRejection as exc:
                raise unprocessable(
                    "fx-unavailable", "Price conversion unavailable", str(exc),
                ) from exc
            shipping_sat += amount
            components.append(amount)
    try:
        now = _now()
        for quote in quotes.values():
            fx.require_usable_quote(quote, now=now)
        total_sat = fx.checked_total_sat(components)
    except fx.FxRejection as exc:
        raise unprocessable(
            "invalid-total", "Invalid order total", str(exc),
        ) from exc
    return line_rows, quotes, subtotal_sat, shipping_sat, total_sat, now


async def quote_preview(payload: dict) -> dict:
    from . import storefront_mode
    from .readiness import assert_database_compatible

    await assert_database_compatible()
    merchant = await _merchant_for_checkout(payload.get("merchant_pubkey") or "")
    mode = await storefront_mode.get_mode(merchant["id"])
    if not storefront_mode.checkout_allowed(mode):
        raise unprocessable(
            "storefront-mode-unavailable",
            "Online checkout unavailable",
            storefront_mode.checkout_blocked_detail(mode),
        )
    resolved, _, shipping_option = await _resolve_cart(merchant["id"], payload)
    _, _, subtotal_sat, shipping_sat, total_sat, _ = await _price_cart(
        resolved, shipping_option, _now(),
    )
    return {"subtotal_sat": subtotal_sat, "shipping_sat": shipping_sat, "total_sat": total_sat}


async def checkout(
    *,
    payload: dict,
    idempotency_key: str,
    client_scope: str,
    buyer_session: dict | None = None,
    now: int | None = None,
) -> dict:
    """Run the §8.1/§8.2 checkout pipeline; returns the §5.4 201 body.

    ``buyer_session`` (D-04): a resolved NIP-07 session — the order is
    attributed to its buyer pubkey only when the session's merchant is
    THIS merchant (sessions are merchant-scoped).
    """
    from .readiness import assert_database_compatible

    await assert_database_compatible()
    settings = ext_settings()
    now = _now() if now is None else now
    route = "/api/v1/public/checkout"

    merchant = await _merchant_for_checkout(payload.get("merchant_pubkey") or "")
    from . import storefront_mode

    mode = await storefront_mode.get_mode(merchant["id"])
    if not storefront_mode.checkout_allowed(mode):
        raise unprocessable(
            "storefront-mode-unavailable",
            "Online checkout unavailable",
            storefront_mode.checkout_blocked_detail(mode),
        )
    scope = _scope_hash(merchant["id"], route, idempotency_key)
    request_hash = _request_hash(payload)
    record = await _claim_idempotency(scope, request_hash, now=now)
    if record["state"] == "completed":
        body = await replay_response(record)
        if body is not None:
            return body
        raise not_found("checkout response expired")
    claim_token = record["claim_token"]
    # D-03/D-04: the session account's resolved identities attribute the
    # order — pubkey binds buyer_pubkey_*, the verified email binds
    # buyer_email_hash (the unverified form email never wins over it).
    buyer_pubkey = None
    buyer_email = None
    if (
        buyer_session
        and buyer_session.get("merchant_id") == merchant["id"]
    ):
        buyer_pubkey = buyer_session["buyer_pubkey"]
        buyer_email = buyer_session.get("email")
    try:
        if "_resume_order_id" in record:
            response = await _resume_order(record, now=now)
            order_id = record["_resume_order_id"]
        else:
            body = await _run_checkout(
                merchant=merchant, payload=payload, client_scope=client_scope,
                settings=settings, now=now, scope=scope, claim_token=claim_token,
                buyer_pubkey=buyer_pubkey, buyer_email=buyer_email,
            )
            response, order_id = body["response"], body["_order_id"]
    except Exception:
        await _fail_idempotency(scope, claim_token)
        raise
    await _complete_idempotency(
        scope, order_id=order_id, status_code=201, response_body=response,
        settings=settings, now=_now(), claim_token=claim_token,
    )
    return response


async def _run_checkout(
    *,
    merchant: dict,
    payload: dict,
    client_scope: str,
    scope: str,
    claim_token: int,
    settings: ExtSettings,
    now: int,
    buyer_pubkey: str | None = None,
    buyer_email: str | None = None,
) -> dict:
    """Intake -> totals -> tx1 order -> saga -> response."""
    # Open-order cap (§15): ≤10 unpaid web orders per IP scope.
    scope_hash = crypto.hmac_index(
        settings.privacy_key, crypto.PURPOSE_CLIENT_IP,
        merchant["id"], client_scope,
    )
    if await _open_order_count(merchant["id"], scope_hash) >= (
        MAX_OPEN_ORDERS_PER_SCOPE
    ):
        raise ProblemError(
            429, "rate-limited", "Rate Limited",
            "too many open orders — complete or wait for expiry",
        )

    resolved, address, shipping_option = await _resolve_cart(merchant["id"], payload)

    email = payload.get("email")
    email_opt_in = bool(payload.get("email_opt_in"))
    if email_opt_in and not email:
        raise unprocessable(
            "invalid-content", "email_opt_in requires email"
        )

    # Held-reservation row cap (§15) — checked before the claim tx; the
    # conditional stock guard remains the authoritative race arbiter.
    for entry in resolved:
        if await _held_reservation_count(
            entry["product"]["id"]
        ) >= MAX_HELD_PER_PRODUCT:
            raise unprocessable(
                "insufficient-stock", "Insufficient stock",
                "product is fully reserved",
            )

    line_rows, quotes, subtotal_sat, shipping_sat, total_sat, now = await _price_cart(
        resolved, shipping_option, now,
    )
    expected = payload.get("expected_total_sat")
    if expected is not None and (type(expected) is not int or expected != total_sat):
        raise unprocessable(
            "quote-changed", "Price changed", "review the updated total before paying",
        )

    order_id = uuid.uuid4().hex
    token = crypto.generate_public_token()
    external_id = uuid.uuid4().hex  # generated UUID for web (§3.3)
    await _insert_order_intake(
        merchant=merchant, resolved=line_rows,
        shipping_option=shipping_option, address=address,
        email=email, phone=payload.get("phone"),
        email_opt_in=email_opt_in, quotes=quotes,
        subtotal_sat=subtotal_sat, shipping_sat=shipping_sat,
        total_sat=total_sat, order_id=order_id,
        external_id=external_id, token=token,
        buyer_amount_sat=(
            max(0, int(payload["buyer_amount"]))
            if payload.get("buyer_amount") is not None else None
        ),
        buyer_pubkey=buyer_pubkey, buyer_email=buyer_email,
        client_scope=client_scope, settings=settings, now=now, scope=scope,
        claim_token=claim_token,
    )

    result = await begin_saga(order_id=order_id, settings=settings, now=now)
    state = result.get("state", "awaiting_payment")
    if (
        buyer_pubkey
        and state == "awaiting_payment"
        and result.get("bolt11")
    ):
        # D-04: attributed web orders receive the same kind-16 type-2
        # payment request gamma orders do — routed to the buyer's
        # declared inbox relays via the order_msg dual-copy path
        # (no_inbox_relays parked state applies when none are declared).
        from . import order_messages

        async with DomainTransaction() as tx:
            live = await tx.fetch_one(
                f"SELECT * FROM {tx.table('orders')} WHERE id = :i"
                + tx.for_update,
                {"i": order_id},
            )
            if live and live["state"] == "awaiting_payment":
                await order_messages.enqueue_payment_request(
                    tx, dict(live), bolt11=result["bolt11"],
                    expiration=result.get("expires_at"),
                )
    response = {
        "public_token": token,
        "order": {
            "state": state,
            "total_sat": total_sat,
            "bolt11": result.get("bolt11"),
            "expires_at": result.get("expires_at"),
        },
    }
    return {"_order_id": order_id, "response": response}


async def _insert_order_intake(
    *,
    merchant: dict,
    resolved: list[dict],
    shipping_option: dict | None,
    address: dict | None,
    email: str | None,
    phone: str | None,
    email_opt_in: bool,
    quotes: dict[str, fx.FxQuote],
    subtotal_sat: int,
    shipping_sat: int,
    total_sat: int,
    order_id: str,
    external_id: str,
    token: str,
    buyer_amount_sat: int | None,
    client_scope: str,
    scope: str,
    claim_token: int,
    settings: ExtSettings,
    now: int,
    buyer_pubkey: str | None = None,
    buyer_email: str | None = None,
) -> None:
    """§8.1 step 8: orders(received) + items + fx + audit + token, one tx."""
    key = settings.master_keys[settings.active_key_version]
    ver = settings.active_key_version

    def _enc(plaintext: bytes, column: str) -> bytes:
        return crypto.encrypt(
            plaintext, key, record_id=order_id, table="orders",
            column=column, key_version=ver,
        )

    contact = json.dumps(
        {"email": email, "phone": phone}, separators=(",", ":")
    )
    # D-03: buyer_email_hash binds the order to the session account's
    # VERIFIED email when the checkout is attributed; the unverified
    # form email seeds the auto-bind only for anonymous checkouts.
    # The plaintext email still lands in contact_enc unchanged
    # (notification opt-in semantics unchanged).
    bind_email = (
        buyer_email
        if isinstance(buyer_email, str) and crypto.normalize(buyer_email)
        else email
        if isinstance(email, str) and crypto.normalize(email)
        else None
    )
    token_enc = _enc(token.encode(), "public_token_enc")
    scope_hash = crypto.hmac_index(
        settings.privacy_key, crypto.PURPOSE_CLIENT_IP,
        merchant["id"], client_scope,
    )
    shipping_state = (
        "pending" if shipping_option is not None else "not_required"
    )
    async with DomainTransaction() as tx:
        await tx.fetch_one(
            f"SELECT id FROM {tx.table('merchants')} WHERE id = :m" + tx.for_update,
            {"m": merchant["id"]},
        )
        count = await tx.fetch_one(
            f"SELECT COUNT(*) AS n FROM {tx.table('orders')}"
            " WHERE merchant_id = :m AND checkout_scope_hash = :s"
            " AND state IN ('received', 'invoice_pending', 'awaiting_payment')",
            {"m": merchant["id"], "s": scope_hash},
        )
        if count["n"] >= MAX_OPEN_ORDERS_PER_SCOPE:
            raise ProblemError(429, "rate-limited", "Rate Limited", "too many open orders")
        await tx.execute(
            f"INSERT INTO {tx.table('orders')} "
            "(id, merchant_id, protocol, external_id_enc, external_id_hash,"
            " request_hash, currency, subtotal_sat, shipping_sat, total_sat,"
            " buyer_amount_sat,"
            " state, shipping_state, contact_enc, address_enc,"
            " shipping_option_id, public_token_hash, public_token_enc,"
            " public_token_expires_at, checkout_scope_hash, email_opt_in,"
            " created_at, updated_at) "
            "VALUES (:i, :m, 'web', :eie, :eih, :rh, 'SAT', :ss, :shs, :ts,"
            " :ba,"
            " 'received', :shst, :ce, :ae, :so, :pth, :pte, :ptx, :csh, :eoi,"
            " :n, :n)",
            {
                "i": order_id,
                "m": merchant["id"],
                "eie": _enc(external_id.encode(), "external_id_enc"),
                "eih": crypto.hmac_index(
                    settings.privacy_key, crypto.PURPOSE_ORDER_ID,
                    merchant["id"], crypto.normalize(external_id),
                ),
                "rh": None,
                "ba": buyer_amount_sat,
                "ss": subtotal_sat,
                "shs": shipping_sat,
                "ts": total_sat,
                "shst": shipping_state,
                "ce": _enc(contact.encode(), "contact_enc"),
                "ae": (
                    _enc(json.dumps(address).encode(), "address_enc")
                    if address is not None else None
                ),
                "so": shipping_option["id"] if shipping_option else None,
                "pth": crypto.token_lookup_hash(token),
                "pte": token_enc,
                "ptx": now + TOKEN_TTL_S,
                "csh": scope_hash,
                "eoi": email_opt_in,
                "n": now,
            },
        )
        if buyer_pubkey:
            # D-04: signed-in web buyers persist buyer_pubkey_enc/hash —
            # identical custody to gamma intake (PURPOSE_BUYER_PUBKEY).
            await tx.execute(
                f"UPDATE {tx.table('orders')} SET buyer_pubkey_enc = :be,"
                " buyer_pubkey_hash = :bh WHERE id = :o",
                {
                    "be": _enc(buyer_pubkey.encode(), "buyer_pubkey_enc"),
                    "bh": crypto.hmac_index(
                        settings.privacy_key, crypto.PURPOSE_BUYER_PUBKEY,
                        merchant["id"], crypto.normalize(buyer_pubkey),
                    ),
                    "o": order_id,
                },
            )
        if bind_email is not None:
            # D-03: hash-only binding — PURPOSE_BUYER_EMAIL is the same
            # domain as buyer_accounts.email_hash so hash equality drives
            # the /nostr/orders union.
            await tx.execute(
                f"UPDATE {tx.table('orders')} SET buyer_email_hash = :eh"
                " WHERE id = :o",
                {
                    "eh": crypto.hmac_index(
                        settings.privacy_key, crypto.PURPOSE_BUYER_EMAIL,
                        merchant["id"], crypto.normalize(bind_email),
                    ),
                    "o": order_id,
                },
            )
        linked = await tx.execute(
            f"UPDATE {tx.table('idempotency_records')} SET order_id = :o"
            " WHERE scope_hash = :s AND order_id IS NULL AND state = 'in_progress'"
            " AND claim_token = :t AND lease_until > :n",
            {"o": order_id, "s": scope, "t": claim_token, "n": await tx.now()},
        )
        if linked != 1:
            raise conflict("request-in-progress", "Request in progress")
        for line in resolved:
            p = line["product"]
            await tx.execute(
                f"INSERT INTO {tx.table('order_items')} "
                "(id, order_id, product_id, product_d, title, quantity,"
                " unit_price_minor, currency, currency_decimals,"
                " line_total_sat) "
                "VALUES (:i, :o, :p, :pd, :t, :q, :up, :c, :cd, :ls)",
                {
                    "i": uuid.uuid4().hex,
                    "o": order_id,
                    "p": p["id"],
                    "pd": p["d_tag"],
                    "t": p["title"],
                    "q": line["qty"],
                    "up": line["unit_minor"],
                    "c": line["currency"],
                    "cd": line["decimals"],
                    "ls": line["line_sat"],
                },
            )
        for quote in quotes.values():
            if quote.source == "identity":
                continue  # same-currency orders persist no fx quote row
            await fx.persist_quote(tx, order_id, quote)
        await tx.execute(
            f"INSERT INTO {tx.table('order_events')} "
            "(id, order_id, from_state, to_state, actor, detail_json,"
            " created_at) "
            "VALUES (:i, :o, NULL, 'received', 'buyer', NULL, :n)",
            {"i": uuid.uuid4().hex, "o": order_id, "n": now},
        )
        # §8.8 order_received — merchant alerts only (customer sends omit
        # order_received; placed+paid is one combined event).
        notify_emails = json.loads(merchant["notify_emails"]) if (
            merchant["notify_emails"]
        ) else []
        notify_events = json.loads(merchant["notify_events"]) if (
            merchant["notify_events"]
        ) else {}
        order_stub = {
            "id": order_id, "merchant_id": merchant["id"],
            "email_opt_in": email_opt_in,
        }
        await order_service.enqueue_email_intents(
            tx, order=order_stub, event_type="order_received",
            merchant_notify_emails=notify_emails,
            merchant_notify_events=notify_events,
            customer_email=None, now=now,
        )


# --- section 8.2 saga --------------------------------------------------------


def core_external_id(order_id: str) -> str:
    """The deterministic recovery key (§4.8)."""
    return f"infinitemarkets:{order_id}"


def decrypt_merchant_wallet(merchant: dict, settings: ExtSettings) -> str:
    """Decrypt the merchant's wallet_id_enc (record_id = merchant id)."""
    ver = crypto.envelope_version(merchant["wallet_id_enc"])
    raw = crypto.decrypt(
        merchant["wallet_id_enc"], settings.master_keys[ver],
        record_id=merchant["id"], table="merchants",
        column="wallet_id_enc", key_version=ver,
    )
    return raw.decode()


async def begin_saga(
    *, order_id: str, settings: ExtSettings | None = None,
    now: int | None = None,
) -> dict:
    """§8.2 steps 1–3: claim tx -> create_invoice -> attach tx.

    Idempotent by construction: the received->invoice_pending CAS means a
    second begin on a resumed order is a no-op SagaConflict; the caller
    (reconciliation) treats that as already-begun.
    """
    settings = settings or ext_settings()
    now = _now() if now is None else now
    async with db.connect() as conn:
        order = await conn.fetchone(
            f"SELECT * FROM {table('orders')} WHERE id = :i", {"i": order_id}
        )
        items = await conn.fetchall(
            f"SELECT product_id, quantity FROM {table('order_items')} "
            "WHERE order_id = :o",
            {"o": order_id},
        )
        merchant = await conn.fetchone(
            f"SELECT * FROM {table('merchants')} WHERE id = :m",
            {"m": order["merchant_id"]},
        )
    order, items, merchant = dict(order), [dict(r) for r in items], dict(merchant)

    wallet_id = decrypt_merchant_wallet(merchant, settings)
    ext_id = core_external_id(order_id)
    expires_at = now + settings.reservation_ttl

    # Step 1: conditional claim + CAS + held reservations + projection.
    try:
        async with DomainTransaction() as tx:
            await order_service.transition_order(
                tx, order_id=order_id, from_state="received",
                to_state="invoice_pending", actor="system", now=now,
            )
            for item in sorted(items, key=lambda i: i["product_id"]):
                rc = await tx.execute(
                    f"UPDATE {tx.table('products')}"
                    " SET stock_reserved = stock_reserved + :q"
                    " WHERE id = :p AND deleted_at IS NULL"
                    " AND (import_source_kind IS NULL OR import_authorized = TRUE)"
                    " AND (stock_on_hand IS NULL"
                    " OR stock_on_hand - stock_reserved >= :q)",
                    {"q": item["quantity"], "p": item["product_id"]},
                )
                if rc != 1:
                    raise unprocessable(
                        "insufficient-stock", "Insufficient stock",
                        "requested quantity is not available",
                    )
                held = await tx.fetch_one(
                    f"SELECT COUNT(*) AS n FROM {tx.table('inventory_reservations')}"
                    " WHERE product_id = :p AND state = 'held'", {"p": item["product_id"]},
                )
                if held["n"] >= MAX_HELD_PER_PRODUCT:
                    raise unprocessable(
                        "insufficient-stock", "Insufficient stock", "product is fully reserved",
                    )
            for item in items:
                await tx.execute(
                    f"INSERT INTO {tx.table('inventory_reservations')} "
                    "(id, product_id, order_id, quantity, state, expires_at,"
                    " created_at, updated_at) "
                    "VALUES (:i, :p, :o, :q, 'held', :e, :n, :n)",
                    {
                        "i": uuid.uuid4().hex,
                        "p": item["product_id"],
                        "o": order_id,
                        "q": item["quantity"],
                        "e": expires_at,
                        "n": now,
                    },
                )
            await tx.execute(
                f"INSERT INTO {tx.table('payments')} "
                "(id, order_id, core_external_id, wallet_refs_enc,"
                " wallet_id_hash, source_wallet_id_hash, amount_sat, status,"
                " created_at) "
                "VALUES (:i, :o, :e, :wre, :wh, :swh, :a, 'creating', :n)",
                {
                    "i": uuid.uuid4().hex,
                    "o": order_id,
                    "e": ext_id,
                    "wre": crypto.encrypt(
                        f"{wallet_id}|{wallet_id}".encode(),
                        settings.master_keys[settings.active_key_version],
                        record_id=order_id, table="payments",
                        column="wallet_refs_enc",
                        key_version=settings.active_key_version,
                    ),
                    "wh": crypto.hmac_index(
                        settings.privacy_key, crypto.PURPOSE_WALLET_ID,
                        merchant["id"], crypto.normalize(wallet_id),
                    ),
                    "swh": crypto.hmac_index(
                        settings.privacy_key, crypto.PURPOSE_SOURCE_WALLET_ID,
                        merchant["id"], crypto.normalize(wallet_id),
                    ),
                    "a": order["total_sat"],
                    "n": now,
                },
            )
    except ProblemError:
        await _mark_rejection(order_id, now=now, expected_state="received")
        raise

    # Step 2: the external call — outside any transaction.
    from lnbits.core.services.payments import InvoiceError, create_invoice

    try:
        payment = await create_invoice(
            wallet_id=wallet_id,
            amount=order["total_sat"],
            currency="sat",
            memo=INVOICE_MEMO,
            expiry=settings.reservation_ttl,
            extension="infinitemarkets",
            external_id=ext_id,
            extra={"tag": "infinitemarkets", "order_id": order_id},
        )
    except InvoiceError as exc:
        if exc.status == "failed":
            await _mark_rejection(order_id, now=_now())
            return {"order_id": order_id, "state": "rejected"}
        await _mark_unknown(order_id, now=_now())
        return {"order_id": order_id, "state": "invoice_pending"}
    except Exception:
        # Timeouts/network/unknown outcomes — never a second invoice.
        await _mark_unknown(order_id, now=_now())
        return {"order_id": order_id, "state": "invoice_pending"}

    # Step 3: attach.
    return await attach_payment(order_id=order_id, payment=payment, now=_now())


async def _invoice_delivery_mismatch(order_id: str, payment) -> bool:
    from bolt11 import decode as bolt11_decode

    from .settlement import _verify_settlement

    try:
        async with db.connect() as conn:
            order = await conn.fetchone(
                f"SELECT * FROM {table('orders')} WHERE id = :o", {"o": order_id},
            )
            projection = await conn.fetchone(
                f"SELECT * FROM {table('payments')} WHERE order_id = :o", {"o": order_id},
            )
        if not order or not projection:
            return True
        if projection["status"] not in ("creating", "creation_unknown"):
            return False
        if await _verify_settlement(dict(order), dict(projection), payment):
            return True
        invoice = bolt11_decode(payment.bolt11)
        if invoice.payment_hash != payment.payment_hash:
            return True
        if invoice.amount_msat != order["total_sat"] * 1000:
            return True
        return bool(
            payment.expiry and invoice.expiry_date
            and int(payment.expiry.timestamp()) != int(invoice.expiry_date.timestamp())
        )
    except Exception:
        return True


async def attach_payment(*, order_id: str, payment, now: int) -> dict:
    """§8.2 step 3: persist the invoice to the projection regardless of
    commerce state; enter awaiting_payment only for invoice_pending."""
    from bolt11 import decode as bolt11_decode

    if await _invoice_delivery_mismatch(order_id, payment):
        await _mark_unknown(order_id, now=now, reason="invoice-correlation-failed")
        return {
            "order_id": order_id, "state": "invoice_pending",
            "bolt11": None, "expires_at": None,
        }

    settings = ext_settings()
    key = settings.master_keys[settings.active_key_version]
    ver = settings.active_key_version

    invoice = bolt11_decode(payment.bolt11)
    expiry_dt = payment.expiry or getattr(invoice, "expiry_date", None)
    expiry_epoch = int(expiry_dt.timestamp()) if expiry_dt else None

    def _enc(plaintext: bytes, column: str) -> bytes:
        return crypto.encrypt(
            plaintext, key, record_id=order_id, table="payments",
            column=column, key_version=ver,
        )

    wallet_refs = f"{payment.wallet_id}|{payment.wallet_id}"
    async with DomainTransaction() as tx:
        order = await tx.fetch_one(
            f"SELECT * FROM {tx.table('orders')} WHERE id = :i" + tx.for_update,
            {"i": order_id},
        )
        if not order:
            raise order_service.TransitionConflict(
                f"order {order_id!r} does not exist"
            )
        rc = await tx.execute(
            f"UPDATE {tx.table('payments')} "
            "SET payment_hash = :ph, checking_id_enc = :ci,"
            " bolt11_enc = :b11, wallet_refs_enc = :wr, status = 'pending'"
            " WHERE order_id = :o AND core_external_id = :e"
            " AND status IN ('creating', 'creation_unknown')",
            {
                "ph": payment.payment_hash,
                "ci": _enc(payment.checking_id.encode(), "checking_id_enc"),
                "b11": _enc(payment.bolt11.encode(), "bolt11_enc"),
                "wr": _enc(wallet_refs.encode(), "wallet_refs_enc"),
                "o": order_id,
                "e": core_external_id(order_id),
            },
        )
        if rc != 1:
            projection = await tx.fetch_one(
                f"SELECT payment_hash FROM {tx.table('payments')} WHERE order_id = :o",
                {"o": order_id},
            )
            if projection and projection["payment_hash"] == payment.payment_hash:
                return {
                    "order_id": order_id, "state": order["state"],
                    "bolt11": None, "expires_at": order["invoice_expiry"],
                }
            raise order_service.TransitionConflict(
                f"attach failed: no creating projection for {order_id!r}"
            )
        await tx.execute(
            f"UPDATE {tx.table('orders')} "
            "SET payment_hash = :ph, invoice_expiry = :ie, updated_at = :n"
            " WHERE id = :i",
            {
                "ph": payment.payment_hash,
                "ie": expiry_epoch,
                "n": now,
                "i": order_id,
            },
        )
        if order["state"] == "invoice_pending":
            if expiry_epoch:
                await tx.execute(
                    f"UPDATE {tx.table('inventory_reservations')}"
                    " SET expires_at = :e, updated_at = :n"
                    " WHERE order_id = :o AND state = 'held'",
                    {"e": expiry_epoch, "n": now, "o": order_id},
                )
            await order_service.transition_order(
                tx, order_id=order_id, from_state="invoice_pending",
                to_state="awaiting_payment", actor="system",
                detail={"payment_hash": payment.payment_hash}, now=now,
            )
            return {
                "order_id": order_id, "state": "awaiting_payment",
                "bolt11": payment.bolt11, "expires_at": expiry_epoch,
            }
        # Cancelled or other state: keep the projection for late-settlement
        # detection; never deliver BOLT11.
        return {
            "order_id": order_id, "state": order["state"],
            "bolt11": None, "expires_at": expiry_epoch,
        }


async def _mark_rejection(
    order_id: str, *, now: int, expected_state: str = "invoice_pending",
) -> None:
    """Definitive rejection: projection failed; release/reject only the
    expected received or invoice_pending order (§8.2 step 4)."""
    async with DomainTransaction() as tx:
        order = await tx.fetch_one(
            f"SELECT state FROM {tx.table('orders')} WHERE id = :i" + tx.for_update,
            {"i": order_id},
        )
        if not order or order["state"] != expected_state:
            return
        await tx.execute(
            f"UPDATE {tx.table('payments')} SET status = 'failed'"
            " WHERE order_id = :o"
            " AND status IN ('creating', 'creation_unknown')",
            {"o": order_id},
        )
        await order_service.transition_order(
            tx, order_id=order_id, from_state=expected_state,
            to_state="rejected", actor="system",
            reason=("intake-rejected" if expected_state == "received"
                    else "invoice-creation-rejected"), now=now,
        )
        await order_service.release_reservations(
            tx, order_id=order_id, to_state="released", now=now
        )


async def _mark_unknown(
    order_id: str, *, now: int, reason: str = "invoice-creation-unknown",
) -> None:
    """Timeout/unknown: status=creation_unknown + payment_exception — never
    a second invoice; reconciliation recovers by exact external id."""
    async with DomainTransaction() as tx:
        changed = await tx.execute(
            f"UPDATE {tx.table('payments')} SET status = 'creation_unknown'"
            " WHERE order_id = :o AND status IN ('creating', 'creation_unknown')",
            {"o": order_id},
        )
        if changed != 1:
            return
        await tx.execute(
            f"UPDATE {tx.table('orders')} "
            "SET payment_exception = TRUE,"
            " payment_exception_reason = :r,"
            " updated_at = :n WHERE id = :i",
            {"r": reason, "n": now, "i": order_id},
        )


async def _resume_order(record: dict, *, now: int) -> dict:
    """Resume a crashed-lease order through the saga (§4.15).

    The order row exists, so a same-body retry rebuilds the original 201
    from the durable projection: the AEAD ``public_token_enc`` copy (kept
    while the token is live) and the persisted ``bolt11_enc``. A still-
    ``received`` order resumes the saga idempotently first.
    """
    order_id = record["_resume_order_id"]
    settings = ext_settings()
    order = await order_service.get_order(order_id)
    if order["state"] == "received":
        await begin_saga(order_id=order_id, now=now)
        order = await order_service.get_order(order_id)

    ver = crypto.envelope_version(order["public_token_enc"])
    token = crypto.decrypt(
        order["public_token_enc"], settings.master_keys[ver],
        record_id=order_id, table="orders", column="public_token_enc",
        key_version=ver,
    ).decode()
    bolt11 = None
    async with db.connect() as conn:
        payment = await conn.fetchone(
            f"SELECT bolt11_enc FROM {table('payments')} WHERE order_id = :o",
            {"o": order_id},
        )
    if payment and payment["bolt11_enc"] is not None:
        bver = crypto.envelope_version(payment["bolt11_enc"])
        bolt11 = crypto.decrypt(
            payment["bolt11_enc"], settings.master_keys[bver],
            record_id=order_id, table="payments", column="bolt11_enc",
            key_version=bver,
        ).decode()
    return {
        "public_token": token,
        "order": {
            "state": order["state"],
            "total_sat": order["total_sat"],
            "bolt11": bolt11 if order["state"] == "awaiting_payment" else None,
            "expires_at": order["invoice_expiry"],
        },
    }


# --- Gamma (NIP-17) intake ------------------------------------------------------
#
# The wrapped kind-16 type-1 path feeds the SAME _resolve_cart/_price_cart/
# begin_saga pipeline as web checkout (GAM-02, §8.1 Gamma profile):
# server-recalculated totals, identical reservation/invoice/settlement
# services. The differences are intake-shaped only: buyer keying replaces
# the IP scope, the buyer's kind-10050 set resolves BEFORE any order row or
# stock reservation (§8.1 step 3), dedupe rides ix_orders_nostr_external_id,
# no public token is minted (gamma orders get NIP-17 replies, not links),
# and ``awaiting_payment`` enqueues a type-2 order_msg payment request
# instead of returning a bolt11 to a caller.


async def _open_order_count_buyer(merchant_id: str, buyer_hash: str) -> int:
    """§15: ≤10 concurrent open orders per buyer_pubkey per merchant."""
    async with db.connect() as conn:
        row = await conn.fetchone(
            f"SELECT COUNT(*) AS n FROM {table('orders')} "
            "WHERE merchant_id = :m AND buyer_pubkey_hash = :h"
            " AND state IN ('received', 'invoice_pending',"
            " 'awaiting_payment')",
            {"m": merchant_id, "h": buyer_hash},
        )
    return int(row["n"]) if row else 0


def _gamma_request_hash(payload: dict) -> str:
    """Immutable request hash over items+qty — the dedupe compare key."""
    items = [
        {"d_tag": i.get("d_tag"), "quantity": i.get("quantity")}
        for i in (payload.get("items") or [])
        if isinstance(i, dict)
    ]
    canonical = json.dumps(
        {
            "items": sorted(items, key=lambda i: str(i["d_tag"])),
            "shipping_option_d": payload.get("shipping_option_d"),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


async def gamma_order_intake(
    *,
    merchant: dict,
    payload: dict,
    buyer_pubkey: str,
    rumor_id: str,
    now: int | None = None,
) -> dict:
    """§8.1 Gamma intake — returns ``{action, order_id, state}``.

    Bounded ``ProblemError`` codes drive the rejected-intake path; a
    ``duplicate-order-conflict`` re-uses the web vocabulary. On
    ``awaiting_payment`` the type-2 payment request is enqueued as an
    ``order_msg`` intent (the buyer never sees a public token or a bolt11
    response body).
    """
    from .readiness import assert_database_compatible

    await assert_database_compatible()
    settings = ext_settings()
    now = _now() if now is None else now
    if merchant["state"] != "active":
        raise unprocessable(
            "merchant-inactive", "Merchant unavailable",
            "merchant is not accepting orders",
        )
    merchant_id = merchant["id"]
    buyer_pubkey_hash = crypto.hmac_index(
        settings.privacy_key, crypto.PURPOSE_BUYER_PUBKEY,
        merchant_id, crypto.normalize(buyer_pubkey),
    )

    # §8.1 step 3 — the buyer's kind-10050 set must resolve BEFORE any
    # order row, reservation, or invoice exists; no source-relay fallback.
    from . import peer_relays

    routes = await peer_relays.resolve_buyer_inbox_relays(
        merchant_id, buyer_pubkey, settings=settings,
    )
    if routes == peer_relays.NO_INBOX_RELAYS:
        raise unprocessable(
            "no-inbox-relays", "Buyer inbox unavailable",
            "buyer has no reachable declared inbox relays",
        )

    if await _open_order_count_buyer(merchant_id, buyer_pubkey_hash) >= (
        MAX_OPEN_ORDERS_PER_SCOPE
    ):
        raise ProblemError(
            429, "rate-limited", "Rate Limited",
            "too many open orders — complete or wait for expiry",
        )

    resolved, address, shipping_option = await _resolve_cart(merchant_id, payload)
    for entry in resolved:
        if await _held_reservation_count(
            entry["product"]["id"]
        ) >= MAX_HELD_PER_PRODUCT:
            raise unprocessable(
                "insufficient-stock", "Insufficient stock",
                "product is fully reserved",
            )
    line_rows, quotes, subtotal_sat, shipping_sat, total_sat, now = (
        await _price_cart(resolved, shipping_option, now)
    )

    order_id = uuid.uuid4().hex
    request_hash = _gamma_request_hash(payload)
    existing = await _insert_gamma_order_intake(
        merchant=merchant, resolved=line_rows,
        shipping_option=shipping_option, address=address,
        quotes=quotes, subtotal_sat=subtotal_sat,
        shipping_sat=shipping_sat, total_sat=total_sat,
        order_id=order_id,
        external_id=payload["external_id"],
        buyer_pubkey=buyer_pubkey, buyer_pubkey_hash=buyer_pubkey_hash,
        request_hash=request_hash, rumor_id=rumor_id,
        buyer_amount_sat=payload.get("buyer_amount_sat"),
        email=payload.get("email"), phone=payload.get("phone"),
        settings=settings, now=now,
    )
    if existing is not None:
        return {
            "action": "existing", "order_id": existing["id"],
            "state": existing["state"],
        }

    result = await begin_saga(order_id=order_id, settings=settings, now=now)
    state = result.get("state", "awaiting_payment")
    if state == "awaiting_payment" and result.get("bolt11"):
        # §8.2 step 3 (Gamma profile): the payment request rides the
        # NIP-17 order_msg channel instead of a token-gated HTTP body.
        from . import order_messages

        async with DomainTransaction() as tx:
            order = await tx.fetch_one(
                f"SELECT * FROM {tx.table('orders')} WHERE id = :i",
                {"i": order_id},
            )
            await order_messages.enqueue_payment_request(
                tx, dict(order), bolt11=result["bolt11"],
                expiration=result.get("expires_at"),
            )
    return {"action": "created", "order_id": order_id, "state": state}


async def _insert_gamma_order_intake(
    *,
    merchant: dict,
    resolved: list[dict],
    shipping_option: dict | None,
    address: dict | None,
    quotes: dict[str, fx.FxQuote],
    subtotal_sat: int,
    shipping_sat: int,
    total_sat: int,
    order_id: str,
    external_id: str,
    buyer_pubkey: str,
    buyer_pubkey_hash: str,
    request_hash: str,
    rumor_id: str,
    buyer_amount_sat: int | None,
    email: str | None,
    phone: str | None,
    settings: ExtSettings,
    now: int,
) -> dict | None:
    """§8.1 step 8 (Gamma): orders(received) + items + fx + audit in one
    tx; ``ix_orders_nostr_external_id`` dedupes — ON CONFLICT returns the
    existing order only on a matching request_hash else
    ``duplicate-order-conflict``. Returns the conflicting/existing row or
    None when a fresh order was inserted."""
    key = settings.master_keys[settings.active_key_version]
    ver = settings.active_key_version
    merchant_id = merchant["id"]

    def _enc(plaintext: bytes, column: str) -> bytes:
        return crypto.encrypt(
            plaintext, key, record_id=order_id, table="orders",
            column=column, key_version=ver,
        )

    try:
        from nostr_sdk import PublicKey

        npub = PublicKey.parse(buyer_pubkey).to_bech32()
    except Exception:  # noqa: BLE001 — display-only fallback
        npub = buyer_pubkey
    contact = json.dumps(
        {"email": email, "phone": phone, "npub": npub},
        separators=(",", ":"),
    )
    # D-03: a non-empty payload email binds the order by hash too —
    # same PURPOSE_BUYER_EMAIL domain as web intake and the m008 backfill.
    buyer_email_hash = (
        crypto.hmac_index(
            settings.privacy_key, crypto.PURPOSE_BUYER_EMAIL,
            merchant_id, crypto.normalize(email),
        )
        if isinstance(email, str) and crypto.normalize(email)
        else None
    )
    shipping_state = (
        "pending" if shipping_option is not None else "not_required"
    )
    async with DomainTransaction() as tx:
        await tx.fetch_one(
            f"SELECT id FROM {tx.table('merchants')} WHERE id = :m" + tx.for_update,
            {"m": merchant_id},
        )
        count = await tx.fetch_one(
            f"SELECT COUNT(*) AS n FROM {tx.table('orders')}"
            " WHERE merchant_id = :m AND buyer_pubkey_hash = :h"
            " AND state IN ('received', 'invoice_pending', 'awaiting_payment')",
            {"m": merchant_id, "h": buyer_pubkey_hash},
        )
        if count["n"] >= MAX_OPEN_ORDERS_PER_SCOPE:
            raise ProblemError(
                429, "rate-limited", "Rate Limited", "too many open orders"
            )
        inserted = await tx.execute(
            f"INSERT INTO {tx.table('orders')} "
            "(id, merchant_id, protocol, buyer_pubkey_enc, buyer_pubkey_hash,"
            " buyer_email_hash, external_id_enc, external_id_hash, request_hash,"
            " source_event_id, currency, subtotal_sat, shipping_sat,"
            " total_sat, buyer_amount_sat, state, shipping_state,"
            " contact_enc, address_enc, shipping_option_id,"
            " email_opt_in, created_at, updated_at) "
            "VALUES (:i, :m, 'gamma', :bpe, :bph, :beh, :eie, :eih, :rh, :sei,"
            " 'SAT', :ss, :shs, :ts, :ba, 'received', :shst, :ce, :ae,"
            " :so, FALSE, :n, :n) ON CONFLICT DO NOTHING",
            {
                "i": order_id,
                "m": merchant_id,
                "bpe": _enc(buyer_pubkey.encode(), "buyer_pubkey_enc"),
                "bph": buyer_pubkey_hash,
                "beh": buyer_email_hash,
                "eie": _enc(external_id.encode(), "external_id_enc"),
                "eih": crypto.hmac_index(
                    settings.privacy_key, crypto.PURPOSE_ORDER_ID,
                    merchant_id, crypto.normalize(external_id),
                ),
                "rh": request_hash,
                "sei": rumor_id,
                "ss": subtotal_sat,
                "shs": shipping_sat,
                "ts": total_sat,
                "ba": buyer_amount_sat,
                "shst": shipping_state,
                "ce": _enc(contact.encode(), "contact_enc"),
                "ae": (
                    _enc(json.dumps(address).encode(), "address_enc")
                    if address is not None else None
                ),
                "so": shipping_option["id"] if shipping_option else None,
                "n": now,
            },
        )
        if inserted != 1:
            row = await tx.fetch_one(
                f"SELECT id, state, request_hash FROM {tx.table('orders')} "
                "WHERE merchant_id = :m AND buyer_pubkey_hash = :bh"
                " AND external_id_hash = :eh",
                {"m": merchant_id, "bh": buyer_pubkey_hash,
                 "eh": crypto.hmac_index(
                     settings.privacy_key, crypto.PURPOSE_ORDER_ID,
                     merchant_id, crypto.normalize(external_id),
                 )},
            )
            if row and row["request_hash"] == request_hash:
                return dict(row)
            raise conflict(
                "duplicate-order-conflict", "Duplicate order",
                "external_id already used with different items",
            )
        for line in resolved:
            p = line["product"]
            await tx.execute(
                f"INSERT INTO {tx.table('order_items')} "
                "(id, order_id, product_id, product_d, title, quantity,"
                " unit_price_minor, currency, currency_decimals,"
                " line_total_sat) "
                "VALUES (:i, :o, :p, :pd, :t, :q, :up, :c, :cd, :ls)",
                {
                    "i": uuid.uuid4().hex,
                    "o": order_id,
                    "p": p["id"],
                    "pd": p["d_tag"],
                    "t": p["title"],
                    "q": line["qty"],
                    "up": line["unit_minor"],
                    "c": line["currency"],
                    "cd": line["decimals"],
                    "ls": line["line_sat"],
                },
            )
        for quote in quotes.values():
            if quote.source == "identity":
                continue
            await fx.persist_quote(tx, order_id, quote)
        await tx.execute(
            f"INSERT INTO {tx.table('order_events')} "
            "(id, order_id, from_state, to_state, actor, detail_json,"
            " created_at) "
            "VALUES (:i, :o, NULL, 'received', 'buyer', NULL, :n)",
            {"i": uuid.uuid4().hex, "o": order_id, "n": now},
        )
        notify_emails = json.loads(merchant["notify_emails"]) if (
            merchant["notify_emails"]
        ) else []
        notify_events = json.loads(merchant["notify_events"]) if (
            merchant["notify_events"]
        ) else {}
        order_stub = {
            "id": order_id, "merchant_id": merchant_id,
            "email_opt_in": False,
        }
        await order_service.enqueue_email_intents(
            tx, order=order_stub, event_type="order_received",
            merchant_notify_emails=notify_emails,
            merchant_notify_events=notify_events,
            customer_email=None, now=now,
        )
    return None
