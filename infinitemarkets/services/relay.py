"""Relay target resolution + health surface — spec section 4.11/8.6/9.5.

Owner directive (02-CONTEXT, 2026-09-22): endpoint sets are
merchant-configurable with starter defaults:

- ``relay_configs`` rows carry ``direction=public|inbox|both``;
  ``merchant_id NULL`` rows are server-wide defaults (spec §4.11 literal).
- A merchant that publishes with zero configured relays is seeded with
  ``DEFAULT_RELAYS`` — editable starter rows, not a hidden fallback.
- Blossom media endpoints live in the ``settings`` table under
  ``blossom_servers`` (spec delta — blossom is an HTTPS media protocol,
  not a nostr relay); starter defaults are exposed for the UI.
"""

from __future__ import annotations

import json
import time
import uuid

from ..db import DomainTransaction, db, table
from ..security import unprocessable

# Starter publication relays — merchant-editable, seeded on first publish.
DEFAULT_RELAYS = (
    "wss://relay.damus.io",
    "wss://nos.lol",
    "wss://relay.nostr.net",
)

# Starter blossom media endpoints (https media servers, not nostr relays).
DEFAULT_BLOSSOM_SERVERS = (
    "https://blossom.primal.net",
    "https://blossom.band",
)

# Starter inbox (kind-10050) relays — merchant-editable, seeded only when
# the merchant has NO relay_configs rows at all (the same visible-starter
# posture as DEFAULT_RELAYS; §9.3 requires a recipient-gated inbox relay
# for Release-B production-ready mode, which is an operator/qualification
# concern beyond this starter set).
DEFAULT_INBOX_RELAYS = (
    "wss://nos.lol",
    "wss://relay.damus.io",
)


def _now() -> int:
    return int(time.time())


# --- targets ---------------------------------------------------------------------


async def relay_targets(merchant_id: str, direction: str = "public",
                        database=None) -> list[str]:
    """Enabled relay targets for a direction ('public'|'inbox');
    'both'-direction rows serve both. Server-wide default rows
    (merchant_id NULL) apply when the merchant has none of its own."""
    async with (database or db).connect() as conn:
        rows = await conn.fetchall(
            f"SELECT relay_url, direction, enabled FROM {table('relay_configs')} "
            "WHERE (merchant_id = :m OR merchant_id IS NULL) AND enabled",
            {"m": merchant_id},
        )
    own = [r for r in rows if r["relay_url"]]
    targets = []
    for r in own:
        if r["direction"] in (direction, "both"):
            targets.append(r["relay_url"])
    return sorted(set(targets))


async def all_public_targets() -> list[str]:
    """Union of every enabled public-direction target — used by the shared
    transport's connect set at start."""
    async with db.connect() as conn:
        rows = await conn.fetchall(
            f"SELECT relay_url FROM {table('relay_configs')} "
            "WHERE enabled AND direction IN ('public', 'both')"
        )
    return sorted({r["relay_url"] for r in rows})


async def ensure_default_relays(merchant_id: str) -> None:
    """Seed the starter set when a merchant publishes with no configured
    relays (owner directive — visible, editable rows, not a hidden default).
    """
    async with db.connect() as conn:
        existing = await conn.fetchone(
            f"SELECT id FROM {table('relay_configs')} "
            "WHERE merchant_id = :m LIMIT 1",
            {"m": merchant_id},
        )
    if existing:
        return
    async with DomainTransaction() as tx:
        for url in DEFAULT_RELAYS:
            await tx.execute(
                f"INSERT INTO {tx.table('relay_configs')} "
                "(id, merchant_id, relay_url, direction, enabled,"
                " created_at, updated_at) VALUES (:i, :m, :u, 'public', TRUE,"
                " :t, :t)",
                {
                    "i": uuid.uuid4().hex,
                    "m": merchant_id,
                    "u": url,
                    "t": _now(),
                },
            )


async def ensure_default_inbox_relays(merchant_id: str) -> None:
    """Seed the starter inbox set when a merchant enabling Gamma inbox has
    NO relay_configs rows of its own — the merchant opts into defaults by
    never having configured any. A merchant that already manages relay
    rows must add an ``inbox``/``both`` row explicitly (D-16)."""
    async with db.connect() as conn:
        existing = await conn.fetchone(
            f"SELECT id FROM {table('relay_configs')} "
            "WHERE merchant_id = :m LIMIT 1",
            {"m": merchant_id},
        )
    if existing:
        return
    async with DomainTransaction() as tx:
        for url in DEFAULT_INBOX_RELAYS:
            await tx.execute(
                f"INSERT INTO {tx.table('relay_configs')} "
                "(id, merchant_id, relay_url, direction, enabled,"
                " created_at, updated_at) VALUES (:i, :m, :u, 'inbox', TRUE,"
                " :t, :t)",
                {
                    "i": uuid.uuid4().hex,
                    "m": merchant_id,
                    "u": url,
                    "t": _now(),
                },
            )


# --- blossom media endpoints (spec delta — §4.11 covers nostr relays only) -------


def validate_blossom_url(raw: str) -> str:
    """Blossom endpoints are https:// media servers — same SSRF posture as
    relay URLs: no userinfo/fragments, no raw IPs, no internal hostnames."""
    import ipaddress
    import re
    from urllib.parse import urlparse

    if not raw or len(raw) > 512 or raw != raw.strip():
        raise unprocessable("invalid-endpoint", "Invalid endpoint URL")
    parsed = urlparse(raw)
    if parsed.scheme != "https":
        raise unprocessable(
            "invalid-endpoint", "Blossom endpoints must use https://"
        )
    if parsed.username or parsed.password or parsed.fragment:
        raise unprocessable(
            "invalid-endpoint",
            "Endpoint URLs must not carry userinfo or fragments",
        )
    host = parsed.hostname or ""
    try:
        ipaddress.ip_address(host.strip("[]"))
        raise unprocessable(
            "invalid-endpoint", "Raw IP endpoint hosts are not accepted"
        ) from None
    except ValueError:
        pass
    labels = host.rstrip(".").split(".")
    if len(labels) < 2 or not re.match(r"^[a-z0-9.-]+$", host):
        raise unprocessable(
            "invalid-endpoint",
            "Internal or single-label endpoint hostnames are not accepted",
        )
    return f"https://{host}" + (f":{parsed.port}" if parsed.port else "") + (
        parsed.path if parsed.path not in ("", "/") else ""
    )


async def get_blossom_servers(merchant_id: str) -> list[str]:
    async with db.connect() as conn:
        row = await conn.fetchone(
            f"SELECT value FROM {table('settings')} "
            "WHERE merchant_id = :m AND key = 'blossom_servers'",
            {"m": merchant_id},
        )
    return json.loads(row["value"]) if row and row["value"] else []


async def set_blossom_servers(merchant_id: str, urls: list[str]) -> list[str]:
    validated = sorted({validate_blossom_url(u) for u in urls})
    async with DomainTransaction() as tx:
        await tx.execute(
            f"DELETE FROM {tx.table('settings')} "
            "WHERE merchant_id = :m AND key = 'blossom_servers'",
            {"m": merchant_id},
        )
        await tx.execute(
            f"INSERT INTO {tx.table('settings')} (merchant_id, key, value) "
            "VALUES (:m, 'blossom_servers', :v)",
            {"m": merchant_id, "v": json.dumps(validated)},
        )
    return validated


# --- health + outbox admin surface ------------------------------------------------


async def relay_health(merchant_id: str) -> dict:
    """Per-relay health: config + connection state + durable publication
    evidence aggregates (§8.6 relay_publications) + the D-26..D-28
    per-relay auth surface (m006 columns)."""
    async with db.connect() as conn:
        configs = await conn.fetchall(
            f"SELECT relay_url, direction, enabled, auth_state,"
            " auth_note, paid_invoice, auth_updated_at"
            f" FROM {table('relay_configs')} "
            "WHERE merchant_id = :m ORDER BY relay_url",
            {"m": merchant_id},
        )
        evidence = await conn.fetchall(
            f"SELECT rp.relay_url, rp.result, COUNT(*) AS n,"
            " MAX(rp.attempted_at) AS last_at "
            f"FROM {table('relay_publications')} rp "
            f"JOIN {table('outbox_events')} oe ON oe.id = rp.outbox_event_id "
            "WHERE oe.merchant_id = :m GROUP BY rp.relay_url, rp.result",
            {"m": merchant_id},
        )
    by_relay: dict[str, dict] = {}
    for r in evidence:
        slot = by_relay.setdefault(
            r["relay_url"], {"accepted": 0, "rejected": 0, "timeout": 0,
                             "last_attempt_at": 0}
        )
        slot[r["result"]] = slot.get(r["result"], 0) + r["n"]
        slot["last_attempt_at"] = max(
            slot["last_attempt_at"], r["last_at"] or 0
        )
    from .transport import transport

    connected = set(await transport().connected_urls())
    return {
        "relays": [
            {
                "relay_url": c["relay_url"],
                "direction": c["direction"],
                "enabled": bool(c["enabled"]),
                "auth_state": c["auth_state"],
                "auth_note": c["auth_note"],
                "paid_invoice": c["paid_invoice"],
                "auth_updated_at": c["auth_updated_at"],
                "connected": c["relay_url"] in connected,
                **by_relay.get(c["relay_url"], {
                    "accepted": 0, "rejected": 0, "timeout": 0,
                    "last_attempt_at": None,
                }),
            }
            for c in configs
        ],
        "blossom_servers": await get_blossom_servers(merchant_id),
    }


async def retry_relay_auth(merchant_id: str, relay_url: str) -> dict:
    """Clear a failed/paid auth state so the next session re-auths — the
    row moves back to 'auth-required' with the note/invoice cleared."""
    async with db.connect() as conn:
        row = await conn.fetchone(
            f"SELECT id, auth_state FROM {table('relay_configs')} "
            "WHERE merchant_id = :m AND relay_url = :r",
            {"m": merchant_id, "r": relay_url},
        )
    if row is None:
        from ..security import not_found

        raise not_found("relay not configured")
    if row["auth_state"] not in ("auth-failed", "payment-required",
                               "auth-required"):
        from ..security import conflict

        raise conflict(
            "invalid-transition", "Relay auth not retryable",
            "only auth-failed|payment-required|auth-required retry",
        )
    async with DomainTransaction() as tx:
        await tx.execute(
            f"UPDATE {tx.table('relay_configs')} SET"
            " auth_state = 'auth-required', auth_note = NULL,"
            " paid_invoice = NULL, auth_updated_at = :t"
            " WHERE merchant_id = :m AND relay_url = :r",
            {"t": _now(), "m": merchant_id, "r": relay_url},
        )
    try:
        from .inbox import inbox_runtime

        inbox_runtime().clear_backoff(merchant_id, relay_url)
    except Exception:  # noqa: BLE001 — runtime may not be started
        pass
    return {"relay_url": relay_url, "auth_state": "auth-required"}


async def list_outbox(merchant_id: str, limit: int = 100) -> dict:
    """B2 surface: outbox intents with per-relay outcomes + dependency
    markers (spec-delta admin route, owner-scoped, ≤100 rows)."""
    limit = min(max(1, limit), 100)
    async with db.connect() as conn:
        # payload_enc carries sealed order_msg descriptors — ciphertext is
        # never an admin-renderable value and bytes break JSON encoding.
        rows = await conn.fetchall(
            f"SELECT id, merchant_id, aggregate_type, aggregate_id,"
            " aggregate_revision, event_kind, event_address, payload_json,"
            " state, attempts, next_attempt_at, claimed_by, claimed_at,"
            " claimed_until, claim_token, last_error, created_at, updated_at"
            f" FROM {table('outbox_events')} "
            "WHERE merchant_id = :m ORDER BY created_at DESC LIMIT :l",
            {"m": merchant_id, "l": limit},
        )
        ids = [r["id"] for r in rows]
        pubs: dict[str, list] = {}
        deps: dict[str, list] = {}
        if ids:
            marks = ",".join(f"'{i}'" for i in ids)
            for p in await conn.fetchall(
                f"SELECT * FROM {table('relay_publications')} "
                f"WHERE outbox_event_id IN ({marks})"
            ):
                pubs.setdefault(p["outbox_event_id"], []).append(dict(p))
            for d in await conn.fetchall(
                f"SELECT * FROM {table('outbox_dependencies')} "
                f"WHERE outbox_event_id IN ({marks})"
            ):
                deps.setdefault(d["outbox_event_id"], []).append(
                    d["depends_on_outbox_event_id"]
                )
    return {
        "intents": [
            {
                **{k: v for k, v in dict(r).items()},
                "relay_publications": pubs.get(r["id"], []),
                "depends_on": deps.get(r["id"], []),
            }
            for r in rows
        ]
    }


async def retry_intent(merchant_id: str, intent_id: str) -> dict:
    """Requeue a failed/partially_published intent — resets attempts and
    next_attempt_at. Accepted relay targets are never resent (the worker
    subtracts durable ``accepted`` evidence before each send)."""
    async with DomainTransaction() as tx:
        row = await tx.fetch_one(
            f"SELECT state FROM {tx.table('outbox_events')} "
            "WHERE id = :i AND merchant_id = :m",
            {"i": intent_id, "m": merchant_id},
        )
        if not row:
            from ..security import not_found

            raise not_found("outbox intent not found")
        if row["state"] not in ("failed", "partially_published"):
            from ..security import conflict

            raise conflict(
                "invalid-transition",
                "Only failed or partially published intents can be retried",
            )
        await tx.execute(
            f"UPDATE {tx.table('outbox_events')} "
            "SET state = 'pending', attempts = 0, next_attempt_at = :t,"
            " last_error = NULL, updated_at = :t WHERE id = :i",
            {"t": _now(), "i": intent_id},
        )
    return {"id": intent_id, "state": "pending"}
