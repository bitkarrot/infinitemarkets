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

import asyncio
import json
import time
import uuid

from ..db import (
    DomainTransaction,
    db,
    released_product_clause,
    table,
)
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


RELAY_CHECK_MAX_RELAYS = 8
RELAY_CHECK_EVENT_LIMIT = 500
RELAY_CHECK_TIMEOUT_S = 8
_RELAY_CHECK_LOCK = asyncio.Lock()


def _first_tag(tags: list[list]) -> str | None:
    return tags[0][1] if tags and len(tags[0]) > 1 else None


def _event_snapshot(event) -> dict:
    """Bounded relay-observed projection — no content body or ciphertext."""
    tags = [tag.as_vec() for tag in event.tags().to_vec()]
    by_name: dict[str, list[list]] = {}
    for tag in tags:
        if tag:
            by_name.setdefault(tag[0], []).append(tag)
    title = _first_tag(by_name.get("title", []))
    quantity = None
    if event.kind().as_u16() in (30017, 30018) and event.content():
        try:
            content = json.loads(event.content())
        except (TypeError, ValueError):
            content = {}
        title = title or content.get("name")
        quantity = content.get("quantity")
    return {
        "id": event.id().to_hex(),
        "kind": event.kind().as_u16(),
        "author": event.author().to_hex(),
        "d_tag": _first_tag(by_name.get("d", [])),
        "created_at": event.created_at().as_secs(),
        "title": title,
        "visibility": _first_tag(by_name.get("visibility", [])),
        "stock": _first_tag(by_name.get("stock", [])),
        "status": _first_tag(by_name.get("status", [])),
        "quantity": quantity,
        "a_tags": [t[1] for t in by_name.get("a", []) if len(t) > 1],
    }


def _local_product_state(product: dict) -> str:
    if product["deleted_at"] is not None:
        return "deleted"
    if product["draft"]:
        return "draft"
    return "active"


async def catalog_reconcile(merchant_id: str) -> dict:
    """Read-only owner check: compare catalog addresses with relay state.

    Relay ACKs are delivery evidence; this function asks each configured
    public relay which signed addressable events it currently returns for
    the merchant. It preserves separate relays instead of collapsing into
    one answer so divergent/stale copies are visible.
    """
    from nostr_sdk import Filter, Kind, PublicKey

    from ..security import not_found
    from . import events as event_builder
    from .transport import transport

    async with db.connect() as conn:
        merchant = await conn.fetchone(
            f"SELECT id, pubkey FROM {table('merchants')} WHERE id = :m",
            {"m": merchant_id},
        )
        if merchant is None:
            raise not_found("merchant not found")
        products = await conn.fetchall(
            f"SELECT p.id, p.d_tag, p.title, p.visibility, p.draft,"
            " p.deleted_at, p.revision, p.published_at, p.created_at,"
            " p.updated_at, p.nip15_product_id, p.product_type, p.format,"
            " p.stock_on_hand, p.stock_reserved, p.parent_product_id,"
            " p.category_id, p.import_source_kind, c.name AS category_name,"
            " c.publish_gamma, c.publish_nip15, parent.d_tag AS parent_d_tag"
            f" FROM {table('products')} p"
            f" LEFT JOIN {table('categories')} c ON c.id = p.category_id"
            " LEFT JOIN ("
            f"SELECT id, d_tag FROM {table('products')}"
            " ) parent ON parent.id = p.parent_product_id"
            " WHERE p.merchant_id = :m ORDER BY p.created_at, p.id"
            f" LIMIT {RELAY_CHECK_EVENT_LIMIT}",
            {"m": merchant_id},
        )
        categories = await conn.fetchall(
            f"SELECT id, name, nip15_stall_d, publish_nip15, deleted_at,"
            " created_at"
            f" FROM {table('categories')} WHERE merchant_id = :m"
            " ORDER BY created_at, id",
            {"m": merchant_id},
        )
        collections = await conn.fetchall(
            f"SELECT id, d_tag, title, deleted_at, revision, created_at"
            f" FROM {table('collections')} WHERE merchant_id = :m"
            " ORDER BY created_at, id",
            {"m": merchant_id},
        )
        collection_members = await conn.fetchall(
            f"SELECT pc.collection_id, COUNT(*) AS member_count"
            f" FROM {table('product_collections')} pc"
            f" JOIN {table('collections')} c ON c.id = pc.collection_id"
            f" JOIN {table('products')} p ON p.id = pc.product_id"
            " WHERE c.merchant_id = :m AND p.deleted_at IS NULL"
            " AND NOT p.draft"
            f" AND {released_product_clause('p', table)}"
            " GROUP BY pc.collection_id",
            {"m": merchant_id},
        )
        shipping_options = await conn.fetchall(
            f"SELECT id, d_tag, title, deleted_at, active, revision,"
            " created_at"
            f" FROM {table('shipping_options')} WHERE merchant_id = :m"
            " ORDER BY created_at, id",
            {"m": merchant_id},
        )
        protocol_rows = await conn.fetchall(
            f"SELECT domain_type, domain_id, event_kind, d_tag,"
            " latest_event_id, latest_created_at"
            f" FROM {table('protocol_addresses')}"
            " WHERE protocol = 'nostr' AND author_pubkey = :p",
            {"p": merchant["pubkey"]},
        )
        evidence_rows = await conn.fetchall(
            f"SELECT oe.id, oe.event_kind, oe.event_address, oe.state,"
            " oe.aggregate_revision, oe.attempts, oe.updated_at,"
            " rp.relay_url, rp.result, rp.event_id, rp.attempted_at"
            f" FROM {table('outbox_events')} oe"
            f" LEFT JOIN {table('relay_publications')} rp"
            " ON rp.outbox_event_id = oe.id"
            " WHERE oe.merchant_id = :m AND oe.event_address IS NOT NULL",
            {"m": merchant_id},
        )

    product_rows = [dict(r) for r in products]
    title_groups: dict[str, list[dict]] = {}
    for product in product_rows:
        key = (product["title"] or "").strip().lower()
        if key:
            title_groups.setdefault(key, []).append(product)

    addresses: dict[str, dict] = {}
    publishable_ids = {
        p["id"] for p in product_rows
        if not p["draft"] and p["deleted_at"] is None
    }

    def add_address(kind: int, d_tag: str, aggregate_type: str,
                    aggregate_id: str, title: str, local: dict,
                    expected: bool) -> None:
        address = f"{kind}:{merchant['pubkey']}:{d_tag}"
        addresses[address] = {
            "address": address,
            "kind": kind,
            "d_tag": d_tag,
            "aggregate_type": aggregate_type,
            "aggregate_id": aggregate_id,
            "title": title,
            "expected": expected,
            "local": local,
            "outbox": None,
        }

    for product in product_rows:
        local_state = _local_product_state(product)
        publishable = product["id"] in publishable_ids
        duplicates = title_groups.get(
            (product["title"] or "").strip().lower(), []
        )
        local = {
            "state": local_state,
            "visibility": product["visibility"],
            "draft": bool(product["draft"]),
            "deleted_at": product["deleted_at"],
            "revision": product["revision"],
            "product_type": product["product_type"],
            "format": product["format"],
            "category_id": product["category_id"],
            "category_name": product["category_name"],
            "publish_gamma": bool(product["publish_gamma"]),
            "publish_nip15": bool(product["publish_nip15"]),
            "import_source_kind": product["import_source_kind"],
            "same_title_records": [
                {"product_id": p["id"], "d_tag": p["d_tag"],
                 "state": _local_product_state(p)}
                for p in duplicates
            ] if len(duplicates) > 1 else [],
        }
        add_address(
            30402, product["d_tag"], "products", product["id"],
            product["title"] or "", local, publishable,
        )
        nip15_id = event_builder.nip15_product_id(
            product, product.get("parent_d_tag")
        )
        add_address(
            30018, nip15_id, "products", product["id"],
            product["title"] or "", local,
            publishable and bool(product["publish_nip15"]),
        )

    for category in categories:
        stall_d = category["nip15_stall_d"]
        if not stall_d:
            continue
        add_address(
            30017, stall_d, "categories", category["id"],
            category["name"] or "",
            {
                "state": "deleted" if category["deleted_at"] else "active",
                "deleted_at": category["deleted_at"],
                "publish_nip15": bool(category["publish_nip15"]),
            },
            bool(category["publish_nip15"])
            and category["deleted_at"] is None,
        )

    member_counts = {
        r["collection_id"]: int(r["member_count"] or 0)
        for r in collection_members
    }
    for collection in collections:
        members = member_counts.get(collection["id"], 0)
        state = (
            "deleted" if collection["deleted_at"] is not None
            else "active" if members else "inactive"
        )
        add_address(
            30405, collection["d_tag"], "collections", collection["id"],
            collection["title"] or "",
            {
                "state": state,
                "deleted_at": collection["deleted_at"],
                "revision": collection["revision"],
                "member_count": members,
            },
            collection["deleted_at"] is None and members > 0,
        )

    for option in shipping_options:
        state = (
            "deleted" if option["deleted_at"] is not None
            else "active" if option["active"] else "inactive"
        )
        add_address(
            30406, option["d_tag"], "shipping_options", option["id"],
            option["title"] or "",
            {
                "state": state,
                "deleted_at": option["deleted_at"],
                "revision": option["revision"],
                "active": bool(option["active"]),
            },
            option["deleted_at"] is None and bool(option["active"]),
        )

    protocol = {
        f"{r['event_kind']}:{merchant['pubkey']}:{r['d_tag']}": r
        for r in protocol_rows
    }
    evidence: dict[str, dict] = {}
    for row in evidence_rows:
        slot = evidence.setdefault(
            row["event_address"],
            {
                "intents": 0,
                "states": {},
                "accepted_relays": set(),
                "failed_relays": set(),
                "last_attempt_at": None,
                "last_updated_at": 0,
            },
        )
        key = f"{row['id']}:{row['updated_at']}"
        if key not in slot.setdefault("_seen", set()):
            slot["_seen"].add(key)
            slot["intents"] += 1
            state = row["state"]
            slot["states"][state] = slot["states"].get(state, 0) + 1
        slot["last_updated_at"] = max(
            slot["last_updated_at"], row["updated_at"] or 0
        )
        slot["last_attempt_at"] = max(
            slot["last_attempt_at"] or 0, row["attempted_at"] or 0
        )
        if row["result"] == "accepted":
            slot["accepted_relays"].add(row["relay_url"])
        elif row["result"] in ("rejected", "timeout"):
            slot["failed_relays"].add(row["relay_url"])
    for address, slot in evidence.items():
        slot.pop("_seen", None)
        slot["accepted_relays"] = sorted(slot["accepted_relays"])
        slot["failed_relays"] = sorted(slot["failed_relays"])
        if address in addresses:
            addresses[address]["outbox"] = slot

    targets = (await relay_targets(merchant_id, "public"))[
        :RELAY_CHECK_MAX_RELAYS
    ]

    def _fetch_filter():
        return (
            Filter()
            .author(PublicKey.parse(merchant["pubkey"]))
            .kinds([
                Kind(5), Kind(30017), Kind(30018), Kind(30402),
                Kind(30405), Kind(30406),
            ])
            .limit(RELAY_CHECK_EVENT_LIMIT)
        )

    observations: dict[str, dict[str, list[dict]]] = {}
    tombstones: dict[str, dict[str, list[dict]]] = {}

    async def _fetch_relay(url: str) -> dict:
        result = {
            "relay_url": url,
            "state": "ok",
            "error": None,
            "events": 0,
            "invalid_events": 0,
        }
        try:
            fetched = await transport().fetch_from(
                [url], _fetch_filter(), timeout_s=RELAY_CHECK_TIMEOUT_S
            )
        except Exception as exc:  # noqa: BLE001 — per-relay check result
            result.update({
                "state": "error",
                "error": str(exc)[:240],
            })
            return result
        for event in fetched:
            snapshot = _event_snapshot(event)
            try:
                valid = event.verify()
            except Exception:  # noqa: BLE001 — invalid relays must not win
                valid = False
            if (
                not valid
                or snapshot["author"] != merchant["pubkey"]
                or snapshot["kind"] not in {
                    5, 30017, 30018, 30402, 30405, 30406
                }
            ):
                result["invalid_events"] += 1
                continue
            result["events"] += 1
            if snapshot["kind"] == 5:
                for target in snapshot["a_tags"]:
                    tombstones.setdefault(target, {}).setdefault(
                        url, []
                    ).append({
                        "event_id": snapshot["id"],
                        "created_at": snapshot["created_at"],
                    })
                continue
            if snapshot["d_tag"]:
                address = (
                    f"{snapshot['kind']}:{snapshot['author']}:"
                    f"{snapshot['d_tag']}"
                )
                observations.setdefault(address, {}).setdefault(
                    url, []
                ).append({
                    "event_id": snapshot["id"],
                    "created_at": snapshot["created_at"],
                    "title": snapshot["title"],
                    "visibility": snapshot["visibility"],
                    "stock": snapshot["stock"],
                    "status": snapshot["status"],
                    "quantity": snapshot["quantity"],
                })
        return result

    async with _RELAY_CHECK_LOCK:
        relay_results = await asyncio.gather(
            *[_fetch_relay(url) for url in targets]
        ) if targets else []

    checked_relays = {
        r["relay_url"] for r in relay_results if r["state"] == "ok"
    }
    rows = []
    unmatched = []
    all_observed = set(observations) | set(tombstones)
    for address in sorted(set(addresses) | all_observed):
        local_entry = addresses.get(address)
        if local_entry is None:
            obs = [e for by_relay in observations.get(address, {}).values()
                   for e in by_relay]
            unmatched.append({
                "address": address,
                "kind": int(address.split(":", 1)[0]),
                "d_tag": address.rsplit(":", 1)[-1],
                "observed_on": sorted(observations.get(address, {})),
                "tombstoned_on": sorted(tombstones.get(address, {})),
                "latest_event": max(
                    obs, key=lambda e: e["created_at"], default=None
                ),
            })
            continue

        observed = observations.get(address, {})
        deleted = tombstones.get(address, {})
        latest_by_relay = {}
        for url, events in observed.items():
            latest = max(
                events,
                key=lambda e: (e["created_at"] or 0, e["event_id"]),
            )
            latest_by_relay[url] = latest
        observed_on = sorted(latest_by_relay)
        tombstoned_on = sorted(deleted)
        missing_on = sorted(
            url for url in checked_relays if url not in latest_by_relay
        )
        unknown_on = sorted(
            r["relay_url"] for r in relay_results if r["state"] != "ok"
        )
        local = local_entry["local"]
        expected = local_entry["expected"]
        findings = []
        status = "observed" if observed_on else "not-observed"
        if local.get("state") == "deleted":
            if observed_on:
                status = "stale-deleted"
                findings.append("deleted-copy-served")
            if not tombstoned_on:
                findings.append("tombstone-not-observed")
            elif observed_on:
                findings.append("tombstone-did-not-remove-copy")
        elif local.get("state") == "draft":
            if observed_on:
                status = "draft-copy-served"
                findings.append("draft-copy-served")
        elif not expected and observed_on:
            status = "inactive-copy-served"
            findings.append("inactive-copy-served")
        elif expected and checked_relays:
            if not observed_on:
                status = "missing"
                findings.append("missing-on-checked-relays")
            elif missing_on:
                status = "partial"
                findings.append("missing-on-some-relays")
        distinct_latest = {
            event["event_id"] for event in latest_by_relay.values()
        }
        if len(distinct_latest) > 1:
            findings.append("relay-divergence")
            if status in ("observed", "partial"):
                status = "divergent"
        if any(len(events) > 1 for events in observed.values()):
            findings.append("revision-history-observed")
        if local.get("same_title_records"):
            findings.append("same-title-local-records")
        latest = max(
            latest_by_relay.values(),
            key=lambda e: (e["created_at"] or 0, e["event_id"]),
            default=None,
        )
        local_protocol = protocol.get(address)
        if (
            latest and local_protocol
            and local_protocol["latest_created_at"] is not None
            and latest["created_at"] < local_protocol["latest_created_at"]
        ):
            findings.append("older-than-local-latest")
            if status == "observed":
                status = "stale"
        if (
            latest and local_entry["kind"] == 30402
            and latest["stock"] is None
            and (latest["visibility"] or "on-sale") not in
                ("hidden", "pre-order")
        ):
            findings.append("stock-tag-missing")
        rows.append({
            **local_entry,
            "local": {
                **local,
                "protocol_latest_event_id": (
                    local_protocol["latest_event_id"]
                    if local_protocol else None
                ),
                "protocol_latest_created_at": (
                    local_protocol["latest_created_at"]
                    if local_protocol else None
                ),
            },
            "status": status,
            "findings": findings,
            "observed_on": observed_on,
            "missing_on": missing_on,
            "unknown_on": unknown_on,
            "tombstoned_on": tombstoned_on,
            "latest_event": latest,
            "observations": [
                {"relay_url": url, **event}
                for url, events in observed.items()
                for event in events
            ],
            "tombstones": [
                {"relay_url": url, **event}
                for url, events in deleted.items()
                for event in events
            ],
        })

    summary = {
        "relays_checked": len(checked_relays),
        "relay_errors": len(relay_results) - len(checked_relays),
        "addresses_observed": sum(
            1 for r in rows if r["observed_on"] or r["tombstoned_on"]
        ),
        "expected_missing": sum(1 for r in rows if r["status"] == "missing"),
        "stale_deleted": sum(
            1 for r in rows if r["status"] == "stale-deleted"
        ),
        "divergent": sum(1 for r in rows if r["status"] == "divergent"),
        "duplicate_title_groups": sum(
            1 for group in title_groups.values() if len(group) > 1
        ),
        "unmatched_events": len(unmatched),
        "limit": RELAY_CHECK_EVENT_LIMIT,
        "truncated": len(product_rows) >= RELAY_CHECK_EVENT_LIMIT,
    }
    return {
        "checked_at": _now(),
        "pubkey": merchant["pubkey"],
        "relays": relay_results,
        "items": rows,
        "unmatched": unmatched,
        "summary": summary,
        "limits": {
            "relays": RELAY_CHECK_MAX_RELAYS,
            "events_per_relay": RELAY_CHECK_EVENT_LIMIT,
            "timeout_s": RELAY_CHECK_TIMEOUT_S,
        },
    }


REISSUE_TOMBSTONE_MAX = 100


async def reissue_deletion_requests(merchant_id: str,
                                    addresses: list[str]) -> dict:
    """Queue fresh kind-5 requests for deleted local catalog addresses.

    A tombstone is a request, not a relay command. Each reissue gets a
    monotonically newer outbox revision so relays that accepted — but
    ignored — an earlier kind-5 receive a fresh signed event through the
    normal delivery path instead of being skipped by per-intent ACK
    evidence.
    """
    from ..security import not_found
    from . import events as event_builder
    from .outbox import enqueue_intent

    if not isinstance(addresses, list) or not addresses:
        raise unprocessable(
            "invalid-content", "addresses must be a non-empty list"
        )
    requested = []
    seen = set()
    for address in addresses:
        if not isinstance(address, str) or len(address) > 512:
            raise unprocessable(
                "invalid-content", "addresses must contain valid strings"
            )
        if address not in seen:
            seen.add(address)
            requested.append(address)
    if len(requested) > REISSUE_TOMBSTONE_MAX:
        raise unprocessable(
            "invalid-content",
            f"at most {REISSUE_TOMBSTONE_MAX} addresses may be reissued",
        )

    queued = []
    async with DomainTransaction() as tx:
        merchant = await tx.fetch_one(
            f"SELECT id, pubkey FROM {tx.table('merchants')} WHERE id = :m",
            {"m": merchant_id},
        )
        if merchant is None:
            raise not_found("merchant not found")

        products = await tx.fetch_all(
            f"SELECT p.id, p.d_tag, p.revision, p.nip15_product_id,"
            " p.product_type, p.parent_product_id,"
            " parent.d_tag AS parent_d_tag"
            f" FROM {tx.table('products')} p"
            " LEFT JOIN ("
            f"SELECT id, d_tag FROM {tx.table('products')}"
            " ) parent ON parent.id = p.parent_product_id"
            " WHERE p.merchant_id = :m AND p.deleted_at IS NOT NULL",
            {"m": merchant_id},
        )
        categories = await tx.fetch_all(
            f"SELECT id, nip15_stall_d"
            f" FROM {tx.table('categories')}"
            " WHERE merchant_id = :m AND deleted_at IS NOT NULL",
            {"m": merchant_id},
        )
        collections = await tx.fetch_all(
            f"SELECT id, d_tag, revision FROM {tx.table('collections')}"
            " WHERE merchant_id = :m AND deleted_at IS NOT NULL",
            {"m": merchant_id},
        )
        shipping_options = await tx.fetch_all(
            f"SELECT id, d_tag, revision FROM {tx.table('shipping_options')}"
            " WHERE merchant_id = :m AND deleted_at IS NOT NULL",
            {"m": merchant_id},
        )

        targets: dict[str, dict] = {}
        for product in products:
            product = dict(product)
            targets[f"30402:{merchant['pubkey']}:{product['d_tag']}"] = {
                "aggregate_type": "products",
                "aggregate_id": product["id"],
                "revision": product["revision"] or 0,
            }
            nip15_id = event_builder.nip15_product_id(
                product, product["parent_d_tag"]
            )
            targets[f"30018:{merchant['pubkey']}:{nip15_id}"] = {
                "aggregate_type": "products",
                "aggregate_id": product["id"],
                "revision": product["revision"] or 0,
            }
        for category in categories:
            if not category["nip15_stall_d"]:
                continue
            address = (
                f"30017:{merchant['pubkey']}:"
                f"{category['nip15_stall_d']}"
            )
            targets[address] = {
                "aggregate_type": "categories",
                "aggregate_id": category["id"],
                "revision": 0,
            }
        for collection in collections:
            targets[
                f"30405:{merchant['pubkey']}:{collection['d_tag']}"
            ] = {
                "aggregate_type": "collections",
                "aggregate_id": collection["id"],
                "revision": collection["revision"] or 0,
            }
        for option in shipping_options:
            targets[
                f"30406:{merchant['pubkey']}:{option['d_tag']}"
            ] = {
                "aggregate_type": "shipping_options",
                "aggregate_id": option["id"],
                "revision": option["revision"] or 0,
            }

        for address in requested:
            parts = address.split(":")
            if len(parts) != 3:
                raise unprocessable(
                    "invalid-content",
                    f"invalid catalog address: {address}",
                )
            target = targets.get(address)
            if target is None:
                raise unprocessable(
                    "invalid-content",
                    "address is not a deleted local catalog address",
                    address,
                )
            latest = await tx.fetch_one(
                f"SELECT MAX(aggregate_revision) AS n"
                f" FROM {tx.table('outbox_events')}"
                " WHERE aggregate_type = :t AND aggregate_id = :i"
                " AND event_kind = 5",
                {
                    "t": target["aggregate_type"],
                    "i": target["aggregate_id"],
                },
            )
            revision = max(
                target["revision"] or 0, latest["n"] or 0
            ) + 1
            intent_id = await enqueue_intent(
                tx,
                merchant_id,
                target["aggregate_type"],
                target["aggregate_id"],
                5,
                revision=revision,
                event_address=address,
            )
            queued.append({
                "address": address,
                "outbox_event_id": intent_id,
                "revision": revision,
            })
    return {"queued": len(queued), "items": queued}


async def prune_outbox(merchant_id: str, older_than_days: int) -> dict:
    """Manual history flush — outbox intents have no automatic retention.
    Deletes terminal rows (published / superseded / failed) whose last
    touch is older than `older_than_days`, plus their dependency edges
    and per-relay delivery evidence (the FKs are ON DELETE RESTRICT, so
    dependents go first). In-flight rows — pending, claimed,
    partially_published — are never touched, and order/financial/audit
    tables are entirely out of scope."""
    days = int(older_than_days)
    if not 7 <= days <= 3650:
        raise unprocessable(
            "invalid-content",
            "older_than_days must be between 7 and 3650",
        )
    cutoff = int(time.time()) - days * 86400
    deleted = 0
    async with DomainTransaction() as tx:
        rows = await tx.fetch_all(
            f"SELECT id FROM {tx.table('outbox_events')} "
            "WHERE merchant_id = :m "
            "AND state IN ('published', 'superseded', 'failed') "
            "AND updated_at <= :c",
            {"m": merchant_id, "c": cutoff},
        )
        ids = [r["id"] for r in rows]
        for i in range(0, len(ids), 500):
            marks = ids[i : i + 500]
            params = {f"x{j}": v for j, v in enumerate(marks)}
            in_list = ",".join(f":x{j}" for j in range(len(marks)))
            # Edges referencing the pruned set on EITHER side —
            # a surviving row may depend on a pruned one.
            await tx.execute(
                f"DELETE FROM {tx.table('outbox_dependencies')} "
                f"WHERE outbox_event_id IN ({in_list}) "
                f"OR depends_on_outbox_event_id IN ({in_list})",
                params,
            )
            await tx.execute(
                f"DELETE FROM {tx.table('relay_publications')} "
                f"WHERE outbox_event_id IN ({in_list})",
                params,
            )
            deleted += await tx.execute(
                f"DELETE FROM {tx.table('outbox_events')} "
                f"WHERE id IN ({in_list})",
                params,
            )
    return {"pruned": deleted, "older_than_days": days}


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
