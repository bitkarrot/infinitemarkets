"""Merchant domain — section 5.1 semantics over the m001 tables.

- 1:1 merchant per LNbits user (``merchants.user_id`` UNIQUE).
- Wallet binding verified against the host wallet table (exists, belongs to
  the user, ``can_receive_payments``); the stored value is AEAD-encrypted
  with an HMAC equality index — never plaintext.
- Activation state machine: ``draft -> publication_pending -> active ->
  deactivating -> inactive``.
- Every mutation that changes published state enqueues an outbox intent in
  the same domain transaction (section 8.6); publication itself is 02-02.
"""

from __future__ import annotations

import json
import time
import uuid

from nostr_sdk import PublicKey

from .. import crypto
from ..db import (
    DomainTransaction,
    db,
    released_product_clause,
    table,
    topology_supported,
)
from ..security import (
    ProblemError,
    audit_capture_warnings,
    conflict,
    not_found,
    unprocessable,
)
from ..settings import ExtSettings, ext_settings

MERCHANT_STATES = ("draft", "publication_pending", "active", "deactivating", "inactive")
NONTERMINAL_ORDER_STATES = ("received", "invoice_pending", "awaiting_payment",
                            "confirmed", "processing")

MAX_NOTIFY_EMAILS = 5
TEST_SEND_HOURLY_LIMIT = 5


def _now() -> int:
    return int(time.time())


def _keystore(settings: ExtSettings):
    from ..keystore import MerchantKeyStore

    return MerchantKeyStore(settings)


async def _wallet_for_user(wallet_id: str, user_id: str):
    """Host wallet lookup + ownership/receive capability checks."""
    from lnbits.core.crud import get_wallet

    wallet = await get_wallet(wallet_id)
    if not wallet or wallet.user != user_id:
        raise conflict(
            "wallet-mismatch",
            "Wallet mismatch",
            "wallet_id does not belong to the authenticated user",
        )
    if not wallet.can_receive_payments:
        raise conflict(
            "wallet-mismatch",
            "Wallet mismatch",
            "wallet cannot receive payments",
        )
    return wallet


async def _orders_table_exists() -> bool:
    """orders lands in m002 (plan 02-03); absent -> no open orders possible."""
    from lnbits.db import POSTGRES

    async with db.connect() as conn:
        if db.type == POSTGRES:
            row = await conn.fetchone(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'infinitemarkets' AND table_name = 'orders'"
            )
        else:
            row = await conn.fetchone(
                "SELECT name FROM infinitemarkets.sqlite_master "
                "WHERE type = 'table' AND name = 'orders'"
            )
    return row is not None


async def _blocking_orders(merchant_id: str) -> int:
    if not await _orders_table_exists():
        return 0
    async with db.connect() as conn:
        placeholders = ",".join(f"'{s}'" for s in NONTERMINAL_ORDER_STATES)
        row = await conn.fetchone(
            f"SELECT COUNT(*) AS n FROM {table('orders')} "
            f"WHERE merchant_id = :m AND state IN ({placeholders})",
            {"m": merchant_id},
        )
    return int(row["n"]) if row else 0


def _encrypt_wallet_id(
    settings: ExtSettings, merchant_id: str, wallet_id: str
) -> tuple[bytes, str]:
    enc = crypto.encrypt(
        wallet_id.encode(),
        settings.master_keys[settings.active_key_version],
        record_id=merchant_id,
        table="merchants",
        column="wallet_id_enc",
        key_version=settings.active_key_version,
    )
    digest = crypto.hmac_index(
        settings.privacy_key, crypto.PURPOSE_WALLET_ID,
        merchant_id, crypto.normalize(wallet_id),
    )
    return enc, digest


def _public_merchant(row: dict) -> dict:
    """Merchant projection — never includes wallet_id_enc or key material."""
    try:
        npub = PublicKey.parse(row["pubkey"]).to_bech32()
    except Exception:  # noqa: BLE001 — malformed legacy row fallback
        npub = ""
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "pubkey": row["pubkey"],
        "npub": npub,
        "display_name": row["display_name"],
        "profile_json": row["profile_json"],
        "payment_preference": row["payment_preference"],
        "recommended_app_d": row["recommended_app_d"],
        "notify_emails": json.loads(row["notify_emails"]) if row["notify_emails"] else [],
        "notify_events": json.loads(row["notify_events"]) if row["notify_events"] else {},
        "state": row["state"],
        # m006 column — defaults to 'off' pre-migration for fixture safety.
        "inbox_state": row.get("inbox_state") or "off",
        "theme": json.loads(row["theme"]) if row.get("theme") else None,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        # §12 revision marker — surfaced on the B4 identity card.
        "spec_revision": ext_settings().spec_revision,
    }


async def get_merchant_row(merchant_id: str, user_id: str) -> dict:
    """Owner-scoped fetch — 404 (not 403) on foreign ids: no existence leak."""
    async with db.connect() as conn:
        row = await conn.fetchone(
            f"SELECT * FROM {table('merchants')} WHERE id = :i AND user_id = :u",
            {"i": merchant_id, "u": user_id},
        )
    if not row:
        raise not_found("merchant not found")
    return dict(row)


async def create_merchant(user, *, wallet_id: str, display_name: str | None = None,
                          payment_preference: str = "manual",
                          settings: ExtSettings | None = None) -> dict:
    settings = settings or ext_settings()
    if payment_preference != "manual":
        raise unprocessable(
            "invalid-transition", "Unsupported payment preference",
            "payment_preference is fixed to 'manual' in Release A",
        )
    async with db.connect() as conn:
        existing = await conn.fetchone(
            f"SELECT id FROM {table('merchants')} WHERE user_id = :u",
            {"u": user.id},
        )
    if existing:
        raise conflict(
            "duplicate-merchant", "Merchant exists",
            "a merchant already exists for this user",
        )
    await _wallet_for_user(wallet_id, str(user.id))

    merchant_id = uuid.uuid4().hex
    wallet_enc, wallet_hash = _encrypt_wallet_id(settings, merchant_id, wallet_id)
    now = _now()

    async with DomainTransaction() as tx:
        await tx.execute(
            f"INSERT INTO {tx.table('merchants')} "
            "(id, user_id, pubkey, key_ref, display_name, payment_preference,"
            " wallet_id_enc, wallet_id_hash, state, created_at, updated_at) "
            "VALUES (:id, :u, :pk, :kr, :dn, 'manual', :we, :wh, 'draft', :t, :t)",
            {
                "id": merchant_id,
                "u": str(user.id),
                "pk": merchant_id * 2,
                "kr": f"merchant_keys:{merchant_id}",
                "dn": display_name,
                "we": wallet_enc,
                "wh": wallet_hash,
                "t": now,
            },
        )
        pubkey = await _keystore(settings).generate(merchant_id, transaction=tx)
        await tx.execute(
            f"UPDATE {tx.table('merchants')} SET pubkey = :pk WHERE id = :id",
            {"pk": pubkey, "id": merchant_id},
        )
    row = await get_merchant_row(merchant_id, str(user.id))
    return _public_merchant(row)


async def current_merchant(user, settings: ExtSettings | None = None) -> dict:
    settings = settings or ext_settings()
    async with db.connect() as conn:
        row = await conn.fetchone(
            f"SELECT * FROM {table('merchants')} WHERE user_id = :u",
            {"u": str(user.id)},
        )
    if not row:
        raise not_found("no merchant for this user")
    merchant = _public_merchant(dict(row))
    from . import relay as relay_service

    merchant["relay_health"] = await relay_service.relay_health(row["id"])
    merchant["warnings"] = audit_capture_warnings()
    if merchant["inbox_state"] == "active":
        inbox_relays = [
            r for r in merchant["relay_health"]["relays"]
            if r["enabled"] and r["direction"] in ("inbox", "both")
        ]
        # Zero usable inbox relays = the buyer contact path is dead —
        # the merchant must configure an alternative relay urgently.
        if not inbox_relays or all(
            r["auth_state"] == "auth-failed" for r in inbox_relays
        ):
            merchant["warnings"].append(
                "infinitemarkets: inbox unreachable — every enabled inbox "
                "relay rejected authentication; configure an alternative "
                "relay that accepts NIP-42 auth (urgent)"
            )
    ok, reason = topology_supported()
    if not ok:
        merchant["warnings"].append(f"infinitemarkets: {reason}")
        merchant["blocked"] = True
    else:
        merchant["blocked"] = False
    return merchant


def _validate_profile(profile: dict) -> None:
    if not isinstance(profile, dict):
        raise unprocessable(
            "invalid-profile", "Invalid profile", "profile_json must be an object"
        )
    about = profile.get("about")
    if about is not None and (not isinstance(about, str) or len(about) > 2000):
        raise unprocessable(
            "invalid-profile", "Invalid profile", "about must be 2000 characters or fewer"
        )
    picture = profile.get("picture")
    if picture is not None and (
        not isinstance(picture, str)
        or len(picture) > 500
        or not picture.startswith("https://")
    ):
        raise unprocessable(
            "invalid-profile", "Invalid profile",
            "picture must be an https URL of 500 characters or fewer",
        )

    from lnbits.helpers import is_valid_email_address

    for key in ("nip05", "lud16"):
        value = profile.get(key)
        if value is not None and (
            not isinstance(value, str)
            or len(value) > 200
            or not is_valid_email_address(value)
        ):
            raise unprocessable(
                "invalid-profile", "Invalid profile",
                f"{key} must be a name@domain address of 200 characters or fewer",
            )


async def patch_merchant(merchant_id: str, user, patch: dict,
                         settings: ExtSettings | None = None) -> dict:
    settings = settings or ext_settings()
    row = await get_merchant_row(merchant_id, str(user.id))
    if row["state"] in ("deactivating", "inactive"):
        raise conflict(
            "invalid-transition", "Merchant not editable",
            "merchant is deactivating/inactive",
        )

    allowed = {
        "display_name", "profile_json", "recommended_app_d",
        "notify_emails", "notify_events", "theme", "relay_configs",
        "blossom_servers",
    }
    wallet_id = patch.pop("wallet_id", None)
    unknown = set(patch) - allowed
    if unknown:
        raise unprocessable(
            "unauthorized", "Unknown fields",
            f"unsupported fields: {sorted(unknown)}",
        )
    if "payment_preference" in patch:
        raise unprocessable(
            "invalid-transition", "Unsupported payment preference",
            "payment_preference is fixed to 'manual' in Release A",
        )

    updates: dict = {}
    if wallet_id is not None:
        if await _blocking_orders(merchant_id):
            raise conflict(
                "wallet-mismatch", "Wallet change blocked",
                "open invoice_pending/awaiting_payment orders exist",
            )
        await _wallet_for_user(wallet_id, str(user.id))
        enc, digest = _encrypt_wallet_id(settings, merchant_id, wallet_id)
        updates["wallet_id_enc"] = enc
        updates["wallet_id_hash"] = digest
    if "display_name" in patch:
        updates["display_name"] = patch["display_name"]
    if "profile_json" in patch:
        profile = patch["profile_json"]
        if isinstance(profile, str):
            try:
                parsed = json.loads(profile)
            except json.JSONDecodeError as exc:
                raise unprocessable(
                    "invalid-profile", "Invalid profile",
                    "profile_json must contain a JSON object",
                ) from exc
            profile = parsed
        _validate_profile(profile)
        updates["profile_json"] = json.dumps(profile, sort_keys=True)
    if "recommended_app_d" in patch:
        updates["recommended_app_d"] = patch["recommended_app_d"]
    if "theme" in patch:
        from . import themes as theme_service

        validated = theme_service.validate_theme(patch["theme"])
        updates["theme"] = json.dumps(validated, sort_keys=True)
    if "notify_emails" in patch:
        emails = patch["notify_emails"] or []
        if not isinstance(emails, list) or len(emails) > MAX_NOTIFY_EMAILS:
            raise unprocessable(
                "invalid-transition", "Too many notification addresses",
                f"at most {MAX_NOTIFY_EMAILS} addresses",
            )
        from lnbits.helpers import is_valid_email_address
        for email in emails:
            if not is_valid_email_address(email):
                raise unprocessable(
                    "invalid-transition", "Invalid email address", email
                )
        updates["notify_emails"] = json.dumps(emails)
    if "notify_events" in patch:
        events = patch["notify_events"] or {}
        if not isinstance(events, dict):
            raise unprocessable(
                "invalid-transition", "notify_events must be an object"
            )
        updates["notify_events"] = json.dumps(events)

    relay_configs = patch.pop("relay_configs", None) if "relay_configs" in patch else None
    blossom_servers = (
        patch.pop("blossom_servers", None)
        if "blossom_servers" in patch
        else None
    )

    async with DomainTransaction() as tx:
        for col, val in updates.items():
            await tx.execute(
                f"UPDATE {tx.table('merchants')} SET {col} = :v, "
                "updated_at = :t WHERE id = :i",
                {"v": val, "t": _now(), "i": merchant_id},
            )
        if relay_configs is not None:
            await _replace_relay_configs(tx, merchant_id, relay_configs)
        # Profile-affecting changes enqueue a kind-0 republication intent.
        if updates.keys() & {
            "display_name", "profile_json", "recommended_app_d", "theme"
        }:
            await _enqueue_intent(
                tx, merchant_id, "merchant_profile", merchant_id, 0
            )
    if blossom_servers is not None:
        # media endpoints persist outside relay_configs (spec delta —
        # blossom is https, not a nostr relay)
        from . import relay as relay_service

        await relay_service.set_blossom_servers(merchant_id, blossom_servers)
    row = await get_merchant_row(merchant_id, str(user.id))
    return _public_merchant(row)


async def _replace_relay_configs(tx: DomainTransaction, merchant_id: str,
                                 configs: list) -> None:
    if not isinstance(configs, list):
        raise unprocessable(
            "invalid-relay", "relay_configs must be a list"
        )
    normalized = []
    seen = set()
    for cfg in configs:
        if not isinstance(cfg, dict) or "relay_url" not in cfg:
            raise unprocessable(
                "invalid-relay", "each relay_config needs relay_url"
            )
        from .transport import validate_relay_target

        url = validate_relay_target(cfg["relay_url"])
        direction = cfg.get("direction", "public")
        if direction not in ("public", "inbox", "both"):
            raise unprocessable(
                "invalid-relay", "direction must be public|inbox|both"
            )
        if direction in ("inbox", "both"):
            # Inbox targets carry buyer order traffic — DNS-resolve +
            # public-space egress check (D-30, shared with the peer-relay
            # gate). ws:// loopback under the test hatch still passes.
            from urllib.parse import urlparse

            from ..security import resolve_and_check_egress
            from .transport import insecure_relays_allowed

            if not (
                insecure_relays_allowed() and url.startswith("ws://")
            ):
                parsed = urlparse(url)
                await resolve_and_check_egress(
                    parsed.hostname or "", parsed.port or 443
                )
        enabled = bool(cfg.get("enabled", True))
        if (url, direction) in seen:
            raise unprocessable(
                "invalid-relay", "duplicate relay_config entry"
            )
        seen.add((url, direction))
        normalized.append((url, direction, enabled))

    await tx.execute(
        f"DELETE FROM {tx.table('relay_configs')} WHERE merchant_id = :m",
        {"m": merchant_id},
    )
    for url, direction, enabled in normalized:
        await tx.execute(
            f"INSERT INTO {tx.table('relay_configs')} "
            "(id, merchant_id, relay_url, direction, enabled, created_at,"
            " updated_at) VALUES (:i, :m, :u, :d, :e, :t, :t)",
            {
                "i": uuid.uuid4().hex,
                "m": merchant_id,
                "u": url,
                "d": direction,
                "e": enabled,
                "t": _now(),
            },
        )


async def _enqueue_intent(tx: DomainTransaction, merchant_id: str,
                          aggregate_type: str, aggregate_id: str,
                          event_kind: int,
                          revision: int = 0,
                          event_address: str | None = None) -> str:
    """Insert a pending outbox intent inside the caller's transaction."""
    from .outbox import enqueue_intent

    return await enqueue_intent(
        tx, merchant_id, aggregate_type, aggregate_id, event_kind,
        revision=revision, event_address=event_address,
    )


async def import_nsec(merchant_id: str, user, nsec_bech32: str,
                    settings: ExtSettings | None = None) -> dict:
    """Replace the merchant key with an imported nsec (section 11).

    The body is never logged (Pitfall 8); the merchant pubkey updates to the
    imported identity and a profile republication intent is enqueued.
    """
    settings = settings or ext_settings()
    row = await get_merchant_row(merchant_id, str(user.id))
    if row["state"] in ("deactivating", "inactive"):
        raise conflict(
            "invalid-transition", "Merchant not editable",
            "merchant is deactivating/inactive",
        )
    async with DomainTransaction() as tx:
        pubkey = await _keystore(settings).import_key(
            merchant_id, nsec_bech32, transaction=tx,
        )
        await tx.execute(
            f"UPDATE {tx.table('merchants')} SET pubkey = :p, updated_at = :t "
            "WHERE id = :i",
            {"p": pubkey, "t": _now(), "i": merchant_id},
        )
        await _enqueue_intent(
            tx, merchant_id, "merchant_profile", merchant_id, 0
        )
    row = await get_merchant_row(merchant_id, str(user.id))
    return _public_merchant(row)


async def export_nsec(merchant_id: str, user,
                      settings: ExtSettings | None = None) -> dict:
    """Return the owner's nsec after an explicit merchant action."""
    settings = settings or ext_settings()
    await get_merchant_row(merchant_id, str(user.id))
    return {
        "nsec": await _keystore(settings).export_key(merchant_id),
    }


async def publish(merchant_id: str, user,
                  settings: ExtSettings | None = None) -> dict:
    """Enqueue republication intents for all merchant aggregates and move
    ``draft -> publication_pending`` (02-02 publishes + flips active)."""
    row = await get_merchant_row(merchant_id, str(user.id))
    if row["state"] in ("deactivating", "inactive"):
        raise conflict(
            "invalid-transition", "Merchant not publishable",
            f"merchant state is {row['state']}",
        )
    now = _now()
    # Owner directive: merchants with no configured relays are seeded with
    # the visible starter set (editable rows — no hidden fallback).
    from . import relay as relay_service

    await relay_service.ensure_default_relays(merchant_id)
    async with DomainTransaction() as tx:
        # Merchant profile + NIP-89 handler pair are always republished;
        # commerce aggregates are enqueued by services/catalog.py on their
        # own mutations — a full republish enqueues one per live aggregate.
        for kind in (0, 31989, 31990):
            await _enqueue_intent(
                tx, merchant_id, "merchant_profile", merchant_id, kind
            )
        for agg_table, kind in (
            ("products", 30402), ("collections", 30405), ("shipping_options", 30406),
        ):
            rows = await tx.fetch_all(
                f"SELECT id, revision FROM {tx.table(agg_table)} "
                "WHERE merchant_id = :m AND deleted_at IS NULL"
                + (f" AND {released_product_clause(agg_table, tx.table)}"
                   if agg_table == "products" else ""),
                {"m": merchant_id},
            )
            for r in rows:
                await _enqueue_intent(
                    tx, merchant_id, agg_table, r["id"], kind,
                    revision=r["revision"],
                )
        # NIP-15 projection: stall + products for nip15-enabled categories
        nip15_categories = await tx.fetch_all(
            f"SELECT id FROM {tx.table('categories')} "
            "WHERE merchant_id = :m AND publish_nip15 AND deleted_at IS NULL",
            {"m": merchant_id},
        )
        for cat in nip15_categories:
            await _enqueue_intent(
                tx, merchant_id, "categories", cat["id"], 30017
            )
            prods = await tx.fetch_all(
                f"SELECT id, revision FROM {tx.table('products')} "
                "WHERE category_id = :c AND merchant_id = :m"
                " AND deleted_at IS NULL"
                f" AND {released_product_clause('products', tx.table)}",
                {"c": cat["id"], "m": merchant_id},
            )
            for r in prods:
                await _enqueue_intent(
                    tx, merchant_id, "products", r["id"], 30018,
                    revision=r["revision"],
                )
        if row["state"] == "draft":
            await tx.execute(
                f"UPDATE {tx.table('merchants')} "
                "SET state = 'publication_pending', updated_at = :t "
                "WHERE id = :i AND state = 'draft'",
                {"t": now, "i": merchant_id},
            )
    return {"enqueued": True, "state": "publication_pending"}


INBOX_STATES = ("off", "pending", "active", "error", "deactivating")
INBOX_PUBLISH_AGGREGATE = "merchant"


async def _inbox_revision(tx: DomainTransaction, merchant_id: str) -> int:
    """Next aggregate revision for the merchant's kind-10050 profile —
    §8.6 supersession: a new publish set always outranks stale intents."""
    row = await tx.fetch_one(
        f"SELECT COALESCE(MAX(aggregate_revision), 0) + 1 AS r "
        f"FROM {tx.table('outbox_events')} "
        "WHERE aggregate_type = :at AND aggregate_id = :ai",
        {"at": INBOX_PUBLISH_AGGREGATE, "ai": merchant_id},
    )
    return int(row["r"])


async def enable_inbox(merchant_id: str, user,
                       settings: ExtSettings | None = None) -> dict:
    """Activate Gamma inbox ordering (D-16/GAM-01).

    Requires ≥1 enabled ``direction='inbox'|'both'`` relay_config — a
    merchant with NO relay rows at all opts into the visible starter set
    (``ensure_default_inbox_relays``). Sets ``inbox_state='pending'`` and
    enqueues the kind-10050 publish intent at a bumped revision; the
    outbox worker flips ``pending -> active`` only on ≥1 durable
    ``accepted`` relay_publications row (never on intent alone).
    """
    row = await get_merchant_row(merchant_id, str(user.id))
    if row["state"] in ("deactivating", "inactive"):
        raise conflict(
            "invalid-transition", "Merchant not editable",
            "merchant is deactivating/inactive",
        )
    from . import relay as relay_service

    await relay_service.ensure_default_inbox_relays(merchant_id)
    if not await relay_service.relay_targets(merchant_id, "inbox"):
        raise unprocessable(
            "no-inbox-relays", "No inbox relays configured",
            "enable at least one direction=inbox|both relay_config",
        )
    address = events_inbox_address(row["pubkey"])
    async with DomainTransaction() as tx:
        revision = await _inbox_revision(tx, merchant_id)
        await tx.execute(
            f"UPDATE {tx.table('merchants')} SET inbox_state = 'pending',"
            " updated_at = :t WHERE id = :i",
            {"t": _now(), "i": merchant_id},
        )
        await _enqueue_intent(
            tx, merchant_id, INBOX_PUBLISH_AGGREGATE, merchant_id,
            10050, revision=revision, event_address=address,
        )
    return {"inbox_state": "pending"}


async def disable_inbox(merchant_id: str, user,
                        settings: ExtSettings | None = None) -> dict:
    """Deactivate Gamma inbox ordering (D-17).

    Enqueues the kind-5 tombstone for the non-addressable ``10050:<pk>:``
    profile at a bumped revision (superseding any live publish intent) and
    moves ``inbox_state -> 'deactivating'`` — the intake subscription keys
    off ``inbox_state == 'active'`` and stops. The worker flips to 'off'
    when the tombstone publishes; in-flight orders are untouched.
    """
    row = await get_merchant_row(merchant_id, str(user.id))
    if row.get("inbox_state", "off") == "off":
        return {"inbox_state": "off"}
    address = events_inbox_address(row["pubkey"])
    async with DomainTransaction() as tx:
        revision = await _inbox_revision(tx, merchant_id)
        await tx.execute(
            f"UPDATE {tx.table('merchants')} SET inbox_state = 'deactivating',"
            " updated_at = :t WHERE id = :i",
            {"t": _now(), "i": merchant_id},
        )
        await _enqueue_intent(
            tx, merchant_id, INBOX_PUBLISH_AGGREGATE, merchant_id,
            5, revision=revision, event_address=address,
        )
    return {"inbox_state": "deactivating"}


def events_inbox_address(pubkey: str) -> str:
    from . import events

    return events.inbox_profile_address(pubkey)


async def get_inbox_state(merchant_id: str, user) -> dict:
    """Inbox-state admin read: state machine, declared inbox relays, and
    the latest durable publication evidence for the 10050/tombstone
    intents."""
    row = await get_merchant_row(merchant_id, str(user.id))
    from . import relay as relay_service

    inbox_relays = await relay_service.relay_targets(merchant_id, "inbox")
    async with db.connect() as conn:
        evidence = await conn.fetchall(
            f"SELECT rp.relay_url, rp.delivery_copy, rp.result, rp.message,"
            " rp.attempted_at, oe.event_kind, oe.event_address "
            f"FROM {table('relay_publications')} rp "
            f"JOIN {table('outbox_events')} oe ON oe.id = rp.outbox_event_id "
            "WHERE oe.merchant_id = :m AND oe.aggregate_type = :at "
            "ORDER BY rp.attempted_at DESC LIMIT 20",
            {"m": merchant_id, "at": INBOX_PUBLISH_AGGREGATE},
        )
        latest_intent = await conn.fetchone(
            f"SELECT state, event_kind, attempts, last_error, updated_at "
            f"FROM {table('outbox_events')} "
            "WHERE merchant_id = :m AND aggregate_type = :at "
            "ORDER BY aggregate_revision DESC, created_at DESC LIMIT 1",
            {"m": merchant_id, "at": INBOX_PUBLISH_AGGREGATE},
        )
    return {
        "inbox_state": row.get("inbox_state") or "off",
        "inbox_relays": inbox_relays,
        "latest_intent": dict(latest_intent) if latest_intent else None,
        "last_publication_evidence": [dict(e) for e in evidence],
    }


async def get_notifications(merchant_id: str, user) -> dict:
    row = await get_merchant_row(merchant_id, str(user.id))
    from ..db import db, table

    async with db.connect() as conn:
        queue_rows = await conn.fetchall(
            f"SELECT event_type, channel, state, attempts, last_error,"
            f" created_at, order_id FROM {table('email_queue')}"
            " WHERE merchant_id = :m ORDER BY created_at DESC LIMIT 50",
            {"m": merchant_id},
        )
    return {
        "notify_emails": json.loads(row["notify_emails"])
        if row["notify_emails"] else [],
        "notify_events": json.loads(row["notify_events"])
        if row["notify_events"] else {},
        "queue": [
            {
                "event_type": r["event_type"],
                "channel": r["channel"],
                "state": r["state"],
                "attempts": r["attempts"],
                "last_error": r["last_error"],
                "created_at": r["created_at"],
                "order_bound": r["order_id"] is not None,
            }
            for r in queue_rows
        ],
    }


async def send_test_notification(merchant_id: str, user, recipient: str,
                                 settings: ExtSettings | None = None) -> dict:
    """Bounded test send — ≤5/hour per merchant via rate_limit_buckets,
    enqueued through the durable §8.8 email path."""
    settings = settings or ext_settings()
    row = await get_merchant_row(merchant_id, str(user.id))
    from lnbits.helpers import is_valid_email_address
    if not is_valid_email_address(recipient):
        raise unprocessable(
            "invalid-transition", "Invalid email address", recipient
        )
    allowed = json.loads(row["notify_emails"]) if row["notify_emails"] else []
    if recipient not in allowed:
        raise unprocessable(
            "invalid-transition", "Unknown recipient",
            "test sends only go to configured notify_emails",
        )

    now = _now()
    window = now - (now % 3600)
    async with DomainTransaction() as tx:
        bucket = await tx.fetch_one(
            f"SELECT count FROM {tx.table('rate_limit_buckets')} "
            "WHERE scope_hash = :s AND bucket = 'test-send' AND window_start = :w",
            {
                "s": crypto.hmac_index(
                    settings.privacy_key, crypto.PURPOSE_EMAIL_RECIPIENT,
                    merchant_id, crypto.normalize(recipient),
                ),
                "w": window,
            },
        )
        count = bucket["count"] if bucket else 0
        if count >= TEST_SEND_HOURLY_LIMIT:
            raise ProblemError(
                429, "rate-limited", "Rate limited",
                "test send limit reached",
            )
        if bucket:
            await tx.execute(
                f"UPDATE {tx.table('rate_limit_buckets')} SET count = count + 1 "
                "WHERE scope_hash = :s AND bucket = 'test-send' "
                "AND window_start = :w",
                {
                    "s": crypto.hmac_index(
                        settings.privacy_key, crypto.PURPOSE_EMAIL_RECIPIENT,
                        merchant_id, crypto.normalize(recipient),
                    ),
                    "w": window,
                },
            )
        else:
            await tx.execute(
                f"INSERT INTO {tx.table('rate_limit_buckets')} "
                "(scope_hash, bucket, window_start, count, expires_at) "
                "VALUES (:s, 'test-send', :w, 1, :e)",
                {
                    "s": crypto.hmac_index(
                        settings.privacy_key, crypto.PURPOSE_EMAIL_RECIPIENT,
                        merchant_id, crypto.normalize(recipient),
                    ),
                    "w": window,
                    "e": window + 7200,
                },
            )

    # Enqueue through the durable §8.8 path (orderless rows bind recipient
    # decryption to merchant_id) — the worker handles suppression and
    # host-SMTP gating at send time.
    from . import email as email_service

    row_id = await email_service.enqueue_test_send(
        merchant_id=merchant_id, recipient=recipient, now=now,
    )
    return {"sent": False, "queued": True, "queue_id": row_id}


async def begin_deactivation(merchant_id: str, user) -> dict:
    """Two-step deactivation (section 6.7): report blockers, mark
    deactivating. Key destruction requires durable tombstones (later step)."""
    row = await get_merchant_row(merchant_id, str(user.id))
    if row["state"] == "inactive":
        return {"state": "inactive", "blockers": []}
    blockers: list[dict] = []
    open_orders = await _blocking_orders(merchant_id)
    if open_orders:
        blockers.append(
            {"type": "open-orders", "count": open_orders}
        )
    if row["state"] != "deactivating":
        if blockers:
            raise conflict(
                "invalid-transition", "Deactivation blocked",
                json.dumps(blockers),
            )
        async with DomainTransaction() as tx:
            await tx.execute(
                f"UPDATE {tx.table('merchants')} SET state = 'deactivating',"
                " updated_at = :t WHERE id = :i",
                {"t": _now(), "i": merchant_id},
            )
            # Tombstone intents for every live aggregate (section 6.7).
            for agg_table, kind in (
                ("products", 5), ("collections", 5), ("shipping_options", 5),
            ):
                rows = await tx.fetch_all(
                    f"SELECT id, revision FROM {tx.table(agg_table)} "
                    "WHERE merchant_id = :m AND deleted_at IS NULL",
                    {"m": merchant_id},
                )
                for r in rows:
                    await _enqueue_intent(
                        tx, merchant_id, agg_table, r["id"], kind,
                        revision=r["revision"],
                    )
    return {"state": "deactivating", "blockers": blockers}
