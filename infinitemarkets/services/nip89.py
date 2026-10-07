"""NIP-89 naddr resolution + public-catalog read surface — spec §5.4.

The naddr handler decodes bech32, requires kind 30402, a LOCAL merchant
pubkey, and a valid ``d`` identifier, and ignores embedded relay hints for
server-side fetching (T-202-06 — parsed but never contacted). Malformed,
wrong-kind, and foreign-merchant references fail with the UI-SPEC
invalid-link response; resolution is purely local.
"""

from __future__ import annotations

import re
import time
from decimal import Decimal

from ..db import (
    db,
    released_product_clause,
    released_product_select,
    table,
)
from ..security import ProblemError
from .catalog import D_TAG_RE

INVALID_LINK = ProblemError(
    404, "invalid-link", "This product link is not valid here."
)




def decode_product_naddr(naddr: str) -> tuple[str, str]:
    """Decode a NIP-89 naddr -> (merchant_pubkey_hex, d_tag).

    Raises INVALID_LINK for malformed bech32, non-30402 kinds, or invalid
    d identifiers. Relay hints are parsed by the SDK and discarded —
    never fetched.
    """
    from nostr_sdk import Nip19Coordinate

    try:
        coord = Nip19Coordinate.from_bech32(naddr).coordinate()
    except Exception:
        raise INVALID_LINK from None
    if coord.kind().as_u16() != 30402:
        raise INVALID_LINK
    d_tag = coord.identifier()
    if not d_tag or not D_TAG_RE.match(d_tag):
        raise INVALID_LINK
    return coord.public_key().to_hex(), d_tag


async def merchant_by_pubkey(pubkey_hex: str) -> dict | None:
    async with db.connect() as conn:
        row = await conn.fetchone(
            f"SELECT * FROM {table('merchants')} WHERE pubkey = :p",
            {"p": pubkey_hex},
        )
    return dict(row) if row else None


async def product_by_address(pubkey_hex: str, d_tag: str) -> dict | None:
    """Local product lookup for a 30402 address; foreign merchants and
    unknown d_tags both resolve to the invalid-link response."""
    merchant = await merchant_by_pubkey(pubkey_hex)
    if not merchant:
        return None
    async with db.connect() as conn:
        row = await conn.fetchone(
            f"SELECT *, {released_product_select('products', table)} "
            f"FROM {table('products')} "
            "WHERE merchant_id = :m AND d_tag = :d",
            {"m": merchant["id"], "d": d_tag},
        )
    if not row:
        return None
    product = dict(row)
    product["_merchant"] = merchant
    return product


async def product_detail(product: dict) -> dict:
    """Attach images/specs/categories/variations/shipping for rendering —
    mirrors the admin read, minus internals."""
    pid = product["id"]
    async with db.connect() as conn:
        images = await conn.fetchall(
            f"SELECT url, dimensions, sort_order FROM {table('product_images')} "
            "WHERE product_id = :p ORDER BY sort_order, url",
            {"p": pid},
        )
        specs = await conn.fetchall(
            f"SELECT key, value FROM {table('product_specs')} "
            "WHERE product_id = :p",
            {"p": pid},
        )
        shipping = await conn.fetchall(
            f"SELECT so.title, so.base_price_minor, so.currency,"
            " so.currency_decimals, pso.extra_cost_minor, so.d_tag, so.service "
            f"FROM {table('product_shipping_options')} pso "
            f"JOIN {table('shipping_options')} so "
            "ON so.id = pso.shipping_option_id "
            "WHERE pso.product_id = :p AND so.deleted_at IS NULL AND so.active",
            {"p": pid},
        )
        variations = await conn.fetchall(
            f"SELECT d_tag, title, amount_minor, currency, currency_decimals,"
            " stock_on_hand, stock_reserved, nip99_status "
            f"FROM {table('products')} "
            "WHERE parent_product_id = :p AND deleted_at IS NULL"
            " AND NOT draft AND visibility != 'hidden'"
            f" AND {released_product_clause('products', table)}",
            {"p": pid},
        )
    return {
        "images": [dict(i) for i in images],
        "specs": {s["key"]: s["value"] for s in specs},
        "shipping": [dict(s) for s in shipping],
        "variations": [dict(v) for v in variations],
    }


# --- public availability states (UI-SPEC A1) -------------------------------------


def availability_state(product: dict) -> str:
    """available|sold|hidden|preorder|unavailable — drives page copy.

    Draft or soft-deleted products and products on inactive merchants
    surface as unavailable (the invalid/not-available copy, never a leak
    of merchant internals).
    """
    merchant = product.get("_merchant") or {}
    if merchant.get("state") in ("deactivating", "inactive"):
        return "inactive"
    if (product.get("deleted_at") is not None or product.get("draft")
            or (product.get("import_source_kind") is not None
                and not product.get("import_released"))):
        return "unavailable"
    if product.get("visibility") == "hidden":
        return "hidden"
    if product.get("visibility") == "pre-order":
        return "preorder"
    if product.get("nip99_status") == "sold":
        return "sold"
    on_hand = product.get("stock_on_hand")
    if on_hand is not None and on_hand - product.get("stock_reserved", 0) <= 0:
        return "sold"
    return "available"


def price_label(amount_minor, currency, decimals) -> str:
    """Buyer-facing price in major units: ``2,500 sats`` / ``15.00 USD``."""
    if amount_minor is None:
        return ""
    code = (currency or "SAT").upper()
    if code in ("SAT", "SATS"):
        return f"{int(amount_minor):,} sats"
    places = 2 if decimals is None else int(decimals)
    return f"{Decimal(int(amount_minor)).scaleb(-places):,.{places}f} {code}"


def public_product_json(product: dict, detail: dict) -> dict:
    """The §5.4 read contract — no internals, no ids, no reserved counts."""
    on_hand = product.get("stock_on_hand")
    available = (
        on_hand - product.get("stock_reserved", 0)
        if on_hand is not None
        else None
    )
    return {
        "d_tag": product["d_tag"],
        "merchant_pubkey": product["_merchant"]["pubkey"],
        "title": product.get("title") or "",
        "summary": product.get("summary") or "",
        "description_md": product.get("description_md") or "",
        "price": {
            "amount_minor": product.get("amount_minor"),
            "currency": product.get("currency"),
            "decimals": product.get("currency_decimals"),
        },
        "availability": availability_state(product),
        "stock": available,  # NULL (unlimited) -> omitted as None
        "images": [
            {"url": i["url"], "dimensions": i["dimensions"]}
            for i in detail["images"]
        ],
        "specs": detail["specs"],
        "shipping": [
            {
                "d_tag": s["d_tag"],
                "title": s["title"],
                "base_price_minor": s["base_price_minor"],
                "extra_cost_minor": s["extra_cost_minor"],
                "currency": s["currency"],
                "currency_decimals": s["currency_decimals"],
                "service": s["service"],
            }
            for s in detail["shipping"]
        ],
        "variations": [
            {
                "d_tag": v["d_tag"],
                "title": v["title"],
                "amount_minor": v["amount_minor"],
                "currency": v["currency"],
                "currency_decimals": v["currency_decimals"],
                "available": (
                    v["stock_on_hand"] - v["stock_reserved"]
                    if v["stock_on_hand"] is not None
                    else None
                ),
                "sold": v["nip99_status"] == "sold",
            }
            for v in detail["variations"]
        ],
        "product_type": product.get("product_type"),
        "format": product.get("format"),
    }


# --- §15 public rate limit (120 GET/min/IP, HMAC'd scope — never raw IP) ---------


async def check_public_rate_limit(request, *, bucket: str = "public-get",
                                  limit: int = 120, window_s: int = 60) -> None:
    """Fixed-window limiter over ``rate_limit_buckets``; the scope is an
    HMAC of the client IP — raw IPs are never persisted (§11.4 posture)."""
    from ..crypto import hmac_index
    from ..settings import ext_settings

    client = request.client.host if request.client else "unknown"
    scope = hmac_index(ext_settings().privacy_key, "rate-limit", "", client)
    now = int(time.time())
    window = now - (now % window_s)
    async with db.connect() as conn:
        await conn.execute(
            f"INSERT INTO {table('rate_limit_buckets')} "
            "(scope_hash, bucket, window_start, count, expires_at) "
            "VALUES (:s, :b, :w, 1, :e) "
            "ON CONFLICT (scope_hash, bucket, window_start) "
            "DO UPDATE SET count = rate_limit_buckets.count + 1",
            {"s": scope, "b": bucket, "w": window, "e": window + window_s * 2},
        )
        row = await conn.fetchone(
            f"SELECT count FROM {table('rate_limit_buckets')} "
            "WHERE scope_hash = :s AND bucket = :b AND window_start = :w",
            {"s": scope, "b": bucket, "w": window},
        )
    if row["count"] > limit:
        raise ProblemError(
            429, "rate-limited", "Rate Limited",
            "too many requests — slow down",
        )


# --- minimal allowlist markdown renderer ----------------------------------------

_INLINE_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC = re.compile(r"(?<!\w)\*([^*\n]+)\*(?!\w)")
_LINK = re.compile(r"\[([^\]]+)\]\((https://[^\s)]+)\)")
_HEADING = re.compile(r"^(#{1,4})\s+(.*)$")


def render_markdown(text: str | None) -> str:
    """Allowlist markdown -> HTML for public pages. Input is already
    ``sanitize_markdown``-cleaned (raw HTML stripped at write); we escape
    everything again and re-emit only the safe subset (belt + suspenders —
    public docs carry a restrictive CSP regardless)."""
    import html

    if not text:
        return ""
    out = []
    for raw_line in text.split("\n"):
        line = html.escape(raw_line)
        heading = _HEADING.match(line)
        if heading:
            level = min(len(heading.group(1)) + 2, 6)
            out.append(f"<h{level}>{heading.group(2)}</h{level}>")
            continue
        line = _INLINE_CODE.sub(r"<code>\1</code>", line)
        line = _BOLD.sub(r"<strong>\1</strong>", line)
        line = _ITALIC.sub(r"<em>\1</em>", line)
        line = _LINK.sub(
            r'<a href="\2" rel="noopener noreferrer nofollow">\1</a>', line
        )
        out.append(f"<p>{line}</p>" if line.strip() else "")
    return "\n".join(out)


def collection_json(collection: dict, members: list[dict]) -> dict:
    return {
        "d_tag": collection["d_tag"],
        "title": collection.get("title") or "",
        "description_md": collection.get("description") or "",
        "products": [
            {
                "d_tag": p["d_tag"],
                "title": p["title"] or "",
                "amount_minor": p["amount_minor"],
                "currency": p["currency"],
                "currency_decimals": p["currency_decimals"],
                "availability": availability_state(p),
            }
            for p in members
        ],
    }
