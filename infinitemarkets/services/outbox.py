"""Transactional outbox enqueue — spec section 8.6.

Every publishable domain mutation inserts an ``outbox_events`` row in
``pending`` INSIDE the same domain transaction. Two rules are enforced
here:

- **Supersession** (§8.6 step 2): older pending intents for the same
  aggregate are marked ``superseded`` — the publisher always rebuilds from
  current state, so a stale intent must never publish outdated content.
- **Dependency edges** (§8.6 ordering): ``outbox_dependencies`` rows wire
  ``30406 → 30405 → 30402`` and "republish survivors before the kind-5
  tombstone" ordering. A dependency edge points at the dep aggregate's
  latest live intent; the worker only claims rows whose deps are
  ``published``.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import time
import uuid
from contextlib import asynccontextmanager

from ..db import DomainTransaction, LeaseLostError


def _now() -> int:
    return int(time.time())


async def enqueue_intent(
    tx: DomainTransaction,
    merchant_id: str,
    aggregate_type: str,
    aggregate_id: str,
    event_kind: int,
    *,
    revision: int = 0,
    event_address: str | None = None,
    depends_on: list[tuple[str, str]] | None = None,
) -> str:
    """Insert a pending intent; returns the new outbox_event id.

    ``depends_on`` is a list of ``(aggregate_type, aggregate_id)`` — each is
    bound to that aggregate's newest live intent (pending/claimed/
    partially_published), so the dependency always tracks the current
    content rather than a superseded row.
    """
    # Supersede older pending intents for this aggregate.
    await tx.execute(
        f"UPDATE {tx.table('outbox_events')} SET state = 'superseded',"
        " updated_at = :t WHERE aggregate_type = :at"
        " AND aggregate_id = :ai AND aggregate_revision < :r"
        " AND state IN ('pending', 'claimed', 'partially_published')",
        {
            "t": _now(),
            "at": aggregate_type,
            "ai": aggregate_id,
            "r": revision,
        },
    )
    # Idempotency: an identical live intent (same aggregate+revision+kind)
    # already covers this enqueue — return it instead of duplicating.
    existing = await tx.fetch_one(
        f"SELECT id FROM {tx.table('outbox_events')} "
        "WHERE aggregate_type = :at AND aggregate_id = :ai"
        " AND aggregate_revision = :r AND event_kind = :k"
        " AND state IN ('pending', 'claimed', 'partially_published')",
        {"at": aggregate_type, "ai": aggregate_id, "r": revision, "k": event_kind},
    )
    if existing:
        return existing["id"]

    intent_id = uuid.uuid4().hex
    await tx.execute(
        f"INSERT INTO {tx.table('outbox_events')} "
        "(id, merchant_id, aggregate_type, aggregate_id, aggregate_revision,"
        " event_kind, event_address, state, attempts, next_attempt_at,"
        " claim_token, created_at, updated_at) "
        "VALUES (:i, :m, :at, :ai, :r, :k, :ea, 'pending', 0, :t, 0, :t, :t)",
        {
            "i": intent_id,
            "m": merchant_id,
            "at": aggregate_type,
            "ai": aggregate_id,
            "r": revision,
            "k": event_kind,
            "ea": event_address,
            "t": _now(),
        },
    )

    for dep_type, dep_id in depends_on or []:
        dep = await tx.fetch_one(
            f"SELECT id FROM {tx.table('outbox_events')} "
            "WHERE aggregate_type = :t AND aggregate_id = :i"
            " AND state IN ('pending', 'claimed', 'partially_published')"
            " ORDER BY aggregate_revision DESC, created_at DESC LIMIT 1",
            {"t": dep_type, "i": dep_id},
        )
        if dep and dep["id"] != intent_id:
            edge = await tx.fetch_one(
                f"SELECT outbox_event_id FROM {tx.table('outbox_dependencies')} "
                "WHERE outbox_event_id = :e"
                " AND depends_on_outbox_event_id = :d",
                {"e": intent_id, "d": dep["id"]},
            )
            if not edge:
                await tx.execute(
                    f"INSERT INTO {tx.table('outbox_dependencies')} "
                    "(outbox_event_id, depends_on_outbox_event_id) "
                    "VALUES (:e, :d)",
                    {"e": intent_id, "d": dep["id"]},
                )
    return intent_id


# --- section 8.6 publisher worker ------------------------------------------------

OUTBOX_MAX_ATTEMPTS = int(os.environ.get("OUTBOX_MAX_ATTEMPTS", "20"))
OUTBOX_BATCH = int(os.environ.get("OUTBOX_BATCH", "32"))
CLAIM_LEASE_S = 120
BACKOFF_BASE_S = 5
BACKOFF_CAP_S = 30 * 60
CLOCK_SKEW_TOLERANCE_S = 300

# §9.3 no-route policy for order_msg: refresh the buyer kind-10050
# discovery every 15 min and give up 48h after first enqueue.
ORDER_MSG_NO_ROUTE_REFRESH_S = 15 * 60
ORDER_MSG_NO_ROUTE_DEADLINE_S = 48 * 3600

# OQ6-pinned transient failure vocabulary — these are transport states,
# not relay verdicts, so they classify as retryable 'timeout'.
_CATALOG_AGGREGATES = frozenset(
    {"products", "collections", "shipping_options", "catalogs"}
)
TRANSIENT_REASONS = frozenset(
    {
        "timeout",
        "relay not connected",
        "relay is initialized but not ready",
    }
)


def _backoff(attempts: int) -> int:
    return min(2 ** attempts * BACKOFF_BASE_S, BACKOFF_CAP_S) + random.randint(0, 5)


async def claim_batch(now: int, worker_id: str,
                      limit: int = OUTBOX_BATCH,
                      database=None) -> list[dict]:
    """Atomically claim pending/partially_published rows (§8.6 step 1).

    SQLite: BEGIN IMMEDIATE + bounded select/update on a raw connection.
    PostgreSQL: SELECT ... FOR UPDATE SKIP LOCKED inside one transaction.
    """
    from lnbits.db import COCKROACH, POSTGRES

    from ..db import DomainTransaction
    from ..db import db as default_db

    handle = database or default_db
    is_sqlite = handle.type not in (POSTGRES, COCKROACH)
    async with DomainTransaction(database) as tx:
        if is_sqlite:
            rows = await tx.fetch_all(
                f"SELECT id FROM {tx.table('outbox_events')} "
                "WHERE state IN ('pending','partially_published') "
                "AND next_attempt_at <= :now AND attempts < :max "
                "ORDER BY created_at LIMIT :l",
                {"now": now, "max": OUTBOX_MAX_ATTEMPTS, "l": limit},
            )
        else:
            rows = await tx.fetch_all(
                f"SELECT id FROM {tx.table('outbox_events')} "
                "WHERE state IN ('pending','partially_published') "
                "AND next_attempt_at <= :now AND attempts < :max "
                "ORDER BY created_at LIMIT :l FOR UPDATE SKIP LOCKED",
                {"now": now, "max": OUTBOX_MAX_ATTEMPTS, "l": limit},
            )
        claimed = []
        for r in rows:
            n = await tx.execute(
                f"UPDATE {tx.table('outbox_events')} "
                "SET state = 'claimed', claimed_by = :w, claimed_at = :now,"
                " claimed_until = :until, claim_token = claim_token + 1,"
                " updated_at = :now "
                "WHERE id = :i AND state IN ('pending','partially_published')",
                {
                    "w": worker_id,
                    "now": now,
                    "until": now + CLAIM_LEASE_S,
                    "i": r["id"],
                },
            )
            if n:
                row = await tx.fetch_one(
                    f"SELECT * FROM {tx.table('outbox_events')} WHERE id = :i",
                    {"i": r["id"]},
                )
                claimed.append(row)
        return claimed


async def _deps_published(tx, intent_id: str) -> bool:
    """The edge is met once ANY revision of the depended-on aggregate is
    published — a superseded dep intent does not wedge dependents
    forever (the aggregate's newer revision is what actually landed).
    No published revision at all (pending, superseded-only, failed)
    still blocks — ordering cannot be guaranteed without one."""
    row = await tx.fetch_one(
        f"SELECT COUNT(*) AS n FROM {tx.table('outbox_dependencies')} d "
        f"JOIN {tx.table('outbox_events')} e "
        "ON e.id = d.depends_on_outbox_event_id "
        "WHERE d.outbox_event_id = :i "
        "AND NOT EXISTS ("
        f"  SELECT 1 FROM {tx.table('outbox_events')} p "
        "  WHERE p.aggregate_type = e.aggregate_type"
        "    AND p.aggregate_id = e.aggregate_id"
        "    AND p.state = 'published'"
        ")",
        {"i": intent_id},
    )
    return row["n"] == 0


async def _newer_live_exists(tx, row: dict) -> bool:
    """A newer live intent for the same aggregate+kind supersedes this one."""
    newer = await tx.fetch_one(
        f"SELECT id FROM {tx.table('outbox_events')} "
        "WHERE aggregate_type = :t AND aggregate_id = :a"
        " AND event_kind = :k AND aggregate_revision > :r"
        " AND state IN ('pending','claimed','partially_published')",
        {"t": row["aggregate_type"], "a": row["aggregate_id"],
         "k": row["event_kind"], "r": row["aggregate_revision"]},
    )
    return bool(newer)


async def _accepted_targets(tx, intent_id: str,
                            delivery_copy: str | None = None) -> set[str]:
    """Durable ``accepted`` evidence — ``delivery_copy`` scopes the query
    for dual-copy ``order_msg`` intents (recipient|sender)."""
    if delivery_copy is None:
        rows = await tx.fetch_all(
            f"SELECT DISTINCT relay_url AS u"
            f" FROM {tx.table('relay_publications')} "
            "WHERE outbox_event_id = :i AND result = 'accepted'",
            {"i": intent_id},
        )
    else:
        rows = await tx.fetch_all(
            f"SELECT DISTINCT relay_url AS u"
            f" FROM {tx.table('relay_publications')} "
            "WHERE outbox_event_id = :i AND result = 'accepted'"
            " AND delivery_copy = :c",
            {"i": intent_id, "c": delivery_copy},
        )
    return {r["u"] for r in rows}


async def _cas_state(tx, row: dict, state: str, now: int,
                     next_attempt_at: int | None = None,
                     last_error: str | None = None,
                     bump_attempts: bool = True) -> bool:
    """Every leased write compares the active claim_token (§4.10).

    ``bump_attempts=False`` for waits that are not failures — a
    dependency-blocked requeue must not burn the attempt budget (rows
    that hit OUTBOX_MAX_ATTEMPTS while ``pending`` become permanently
    unclaimable and invisible)."""
    n = await tx.execute(
        f"UPDATE {tx.table('outbox_events')} "
        "SET state = :s, attempts = :a, next_attempt_at = :na,"
        " last_error = :e, updated_at = :now "
        "WHERE id = :i AND claim_token = :t AND state = 'claimed'"
        " AND claimed_by = :w AND claimed_until > :db_now",
        {
            "s": state,
            "a": row["attempts"] + (1 if bump_attempts else 0),
            "na": next_attempt_at if next_attempt_at is not None else 0,
            "e": last_error,
            "now": now,
            "i": row["id"],
            "t": row["claim_token"],
            "w": row["claimed_by"],
            "db_now": await tx.now(),
        },
    )
    return bool(n)


async def _record_publications(tx, intent_id: str, copy: str, event_id: str,
                               attempt_no: int, results: list[tuple[str, str, str]],
                               now: int) -> None:
    """One durable row per copy+relay with the verbatim outcome (§4.10)."""
    for relay_url, result, message in results:
        await tx.execute(
            f"INSERT INTO {tx.table('relay_publications')} "
            "(id, outbox_event_id, delivery_copy, relay_url, event_id,"
            " attempt_no, result, message, attempted_at) "
            "VALUES (:i, :e, :c, :u, :ev, :a, :r, :m, :t)",
            {
                "i": uuid.uuid4().hex,
                "e": intent_id,
                "c": copy,
                "u": relay_url,
                "ev": event_id,
                "a": attempt_no,
                "r": result,
                "m": (message or "")[:512],
                "t": now,
            },
        )


async def render_intent(row: dict, database=None) -> dict | None:
    """Build the unsigned event from CURRENT domain state (§8.6 step 3).

    Returns None when the aggregate no longer exists/is unpublished — the
    caller marks the intent superseded (stale content is never published).
    """
    from . import events

    agg, kind = row["aggregate_type"], row["event_kind"]

    # tombstones build from the descriptor alone — the aggregate may be gone
    if kind == 5:
        addr = (row.get("event_address") or "").split(":")
        if len(addr) != 3:
            return None
        _, pubkey, d_tag = addr
        return events.tombstone_intent(pubkey=pubkey, kind=int(addr[0]),
                                       d_tag=d_tag)

    from ..db import db as default_db
    from ..db import table

    async with (database or default_db).connect() as conn:
        if agg in _CATALOG_AGGREGATES:
            # D-09: browse_only pauses catalog publication — intents are
            # superseded by the same "no longer publishable" posture the
            # publish_nip15 gate uses; order_msg/merchant_profile are
            # unaffected.
            from . import storefront_mode

            if not storefront_mode.publish_allowed(
                await storefront_mode.get_mode(
                    row["merchant_id"], conn=conn
                )
            ):
                return None
        if agg == "products":
            p = await conn.fetchone(
                f"SELECT * FROM {table('products')} WHERE id = :i",
                {"i": row["aggregate_id"]},
            )
            if not p or p["draft"] or p["deleted_at"] is not None:
                return None
            p = dict(p)
            merchant = await conn.fetchone(
                f"SELECT * FROM {table('merchants')} WHERE id = :m",
                {"m": row["merchant_id"]},
            )
            pubkey = merchant["pubkey"]
            images = await conn.fetchall(
                f"SELECT url, dimensions, sort_order FROM "
                f"{table('product_images')} WHERE product_id = :p "
                "ORDER BY sort_order, url", {"p": p["id"]})
            specs = await conn.fetchall(
                f"SELECT key, value FROM {table('product_specs')} "
                "WHERE product_id = :p", {"p": p["id"]})
            cats = await conn.fetchall(
                f"SELECT category FROM {table('product_categories')} "
                "WHERE product_id = :p", {"p": p["id"]})
            cols = await conn.fetchall(
                f"SELECT c.d_tag FROM {table('product_collections')} pc "
                f"JOIN {table('collections')} c ON c.id = pc.collection_id "
                "WHERE pc.product_id = :p AND c.deleted_at IS NULL",
                {"p": p["id"]})
            ship = await conn.fetchall(
                f"SELECT so.d_tag, pso.extra_cost_minor FROM "
                f"{table('product_shipping_options')} pso "
                f"JOIN {table('shipping_options')} so "
                "ON so.id = pso.shipping_option_id "
                "WHERE pso.product_id = :p AND so.deleted_at IS NULL",
                {"p": p["id"]})
            ship_cols = await conn.fetchall(
                f"SELECT c.d_tag, psc.extra_cost_minor FROM "
                f"{table('product_shipping_collections')} psc "
                f"JOIN {table('collections')} c ON c.id = psc.collection_id "
                "WHERE psc.product_id = :p AND c.deleted_at IS NULL",
                {"p": p["id"]})
            if kind == 30018:
                catalog = await conn.fetchone(
                    f"SELECT * FROM {table('catalogs')} WHERE id = :c",
                    {"c": p["catalog_id"]})
                if not catalog or not catalog["publish_nip15"]:
                    return None
                parent_d = None
                if p["product_type"] == "variation":
                    parent = await conn.fetchone(
                        f"SELECT d_tag FROM {table('products')} "
                        "WHERE id = :i", {"i": p["parent_product_id"]})
                    parent_d = parent["d_tag"] if parent else None
                return events.nip15_product_event(
                    p, stall_d=catalog["nip15_stall_d"],
                    stall_currency=catalog["default_currency"] or "",
                    parent_d_tag=parent_d,
                    images=[dict(i) for i in images],
                    specs=[dict(s) for s in specs],
                    shipping_surcharges=[
                        {"d_tag": s["d_tag"],
                         "extra_cost_minor": s["extra_cost_minor"]}
                        for s in ship
                    ])
            if p["product_type"] == "variation":
                parent = await conn.fetchone(
                    f"SELECT d_tag FROM {table('products')} WHERE id = :i",
                    {"i": p["parent_product_id"]})
                p["_parent_d_tag"] = parent["d_tag"] if parent else ""
            return events.product_event(
                p, pubkey=pubkey,
                spec_revision=_spec_revision(),
                images=[dict(i) for i in images],
                specs=[dict(s) for s in specs],
                categories=[c["category"] for c in cats],
                member_collection_d_tags=[c["d_tag"] for c in cols],
                shipping_refs=[
                    {"kind": 30406, "d_tag": s["d_tag"],
                     "extra_cost_minor": s["extra_cost_minor"]}
                    for s in ship
                ] + [
                    {"kind": 30405, "d_tag": s["d_tag"],
                     "extra_cost_minor": s["extra_cost_minor"]}
                    for s in ship_cols
                ])

        if agg == "collections":
            c = await conn.fetchone(
                f"SELECT * FROM {table('collections')} WHERE id = :i",
                {"i": row["aggregate_id"]})
            if not c or c["deleted_at"] is not None:
                return None
            c = dict(c)
            merchant = await conn.fetchone(
                f"SELECT * FROM {table('merchants')} WHERE id = :m",
                {"m": row["merchant_id"]})
            members = await conn.fetchall(
                f"SELECT p.d_tag FROM {table('product_collections')} pc "
                f"JOIN {table('products')} p ON p.id = pc.product_id "
                "WHERE pc.collection_id = :c AND p.deleted_at IS NULL"
                " AND NOT p.draft", {"c": c["id"]})
            if not members:
                return None  # zero-member collections never publish
            ship = await conn.fetchall(
                f"SELECT so.d_tag FROM {table('collection_shipping')} cs "
                f"JOIN {table('shipping_options')} so "
                "ON so.id = cs.shipping_option_id "
                "WHERE cs.collection_id = :c AND so.deleted_at IS NULL",
                {"c": c["id"]})
            return events.collection_event(
                c, pubkey=merchant["pubkey"], spec_revision=_spec_revision(),
                member_d_tags=[m["d_tag"] for m in members],
                shipping_d_tags=[s["d_tag"] for s in ship])

        if agg == "shipping_options":
            o = await conn.fetchone(
                f"SELECT * FROM {table('shipping_options')} WHERE id = :i",
                {"i": row["aggregate_id"]})
            if not o or o["deleted_at"] is not None or not o["active"]:
                return None
            merchant = await conn.fetchone(
                f"SELECT * FROM {table('merchants')} WHERE id = :m",
                {"m": row["merchant_id"]})
            return events.shipping_event(
                dict(o), pubkey=merchant["pubkey"],
                spec_revision=_spec_revision())

        if agg == "catalogs":
            cat = await conn.fetchone(
                f"SELECT * FROM {table('catalogs')} WHERE id = :i",
                {"i": row["aggregate_id"]})
            if not cat or cat["deleted_at"] is not None \
                    or not cat["publish_nip15"]:
                return None
            # zones: the catalog's referenced shipping options + the
            # deterministic digital zone when digital products exist
            zones = []
            opts = await conn.fetchall(
                f"SELECT DISTINCT so.* FROM {table('shipping_options')} so "
                f"JOIN {table('collection_shipping')} cs "
                "ON cs.shipping_option_id = so.id "
                f"JOIN {table('product_collections')} pc "
                "ON pc.collection_id = cs.collection_id "
                f"JOIN {table('products')} p ON p.id = pc.product_id "
                "WHERE p.catalog_id = :c AND p.deleted_at IS NULL"
                " AND so.deleted_at IS NULL",
                {"c": cat["id"]})
            for o in opts:
                regions = json.loads(o["regions"]) if o["regions"] else []
                countries = (
                    json.loads(o["countries"]) if o["countries"] else []
                )
                zones.append({
                    "id": o["d_tag"], "name": o["title"] or o["d_tag"],
                    "cost_minor": o["base_price_minor"] or 0,
                    "currency_decimals": 2,
                    "regions": countries + regions,
                })
            digital = await conn.fetchone(
                f"SELECT id FROM {table('products')} "
                "WHERE catalog_id = :c AND format = 'digital'"
                " AND deleted_at IS NULL AND NOT draft LIMIT 1",
                {"c": cat["id"]})
            if digital:
                zones.append(events.digital_zone())
            return events.stall_event(dict(cat), zones=zones)

        if agg == "merchant":
            # kind-10050 inbox profile (GAM-01/D-16) — rebuilt from the
            # CURRENT enabled inbox relay set, like every other aggregate.
            merchant = await conn.fetchone(
                f"SELECT * FROM {table('merchants')} WHERE id = :m",
                {"m": row["merchant_id"]})
            if not merchant or kind != 10050:
                return None
            inbox_rows = await conn.fetchall(
                f"SELECT relay_url FROM {table('relay_configs')} "
                "WHERE (merchant_id = :m OR merchant_id IS NULL) AND enabled"
                " AND direction IN ('inbox', 'both') ORDER BY relay_url",
                {"m": row["merchant_id"]})
            urls = [r["relay_url"] for r in inbox_rows]
            if not urls:
                return None
            # §9.3/§6.9: the public advertisement carries at most 3 relay
            # tags — the sorted head is the deterministic choice.
            return events.build_kind10050(
                merchant["pubkey"], urls[:3])

        if agg == "merchant_profile":
            merchant = await conn.fetchone(
                f"SELECT * FROM {table('merchants')} WHERE id = :m",
                {"m": row["merchant_id"]})
            if not merchant:
                return None
            merchant = dict(merchant)
            if kind == 0:
                return events.merchant_profile_event(
                    merchant, pubkey=merchant["pubkey"])
            if kind == 31989:
                return events.handler_recommendation_event(
                    merchant, pubkey=merchant["pubkey"])
            if kind == 31990:
                return events.handler_info_event(
                    merchant, pubkey=merchant["pubkey"],
                    public_base_url=_public_base_url())
    return None


def _spec_revision() -> str:
    from ..settings import ext_settings

    return ext_settings().spec_revision


def _public_base_url() -> str:
    from ..settings import ext_settings

    return ext_settings().public_base_url


@asynccontextmanager
async def _publication_transaction(row, worker_id, database=None):
    async with DomainTransaction(database) as tx:
        await tx.fetch_one(
            f"SELECT id FROM {tx.table('merchants')} WHERE id = :m" + tx.for_update,
            {"m": row["merchant_id"]},
        )
        live = await tx.fetch_one(
            f"SELECT * FROM {tx.table('outbox_events')} WHERE id = :i"
            " AND state = 'claimed' AND claim_token = :t AND claimed_by = :w"
            " AND claimed_until > :n" + tx.for_update,
            {"i": row["id"], "t": row["claim_token"], "w": worker_id, "n": await tx.now()},
        )
        yield (tx, dict(live)) if live else None
        if live and await tx.now() >= live["claimed_until"]:
            raise LeaseLostError("publication lease expired")


async def publish_intent(row: dict, *, transport, keystore, relay_targets,
                         worker_id: str, now: int, database=None) -> str:
    """One claimed intent through the §8.6 pipeline. Returns the outcome."""
    from ..settings import ext_settings

    settings = ext_settings()
    intent_id = row["id"]

    if row["aggregate_type"] == "order_msg":
        return await _publish_order_msg(
            row, transport=transport, keystore=keystore,
            worker_id=worker_id, database=database,
        )

    async with _publication_transaction(row, worker_id, database) as claimed:
        if not claimed:
            return "lost_claim"
        tx, row = claimed
        now = await tx.now()
        # step 2 — dependencies must be published first
        if not await _deps_published(tx, intent_id):
            await _cas_state(
                tx, row, "pending", now, next_attempt_at=now,
                bump_attempts=False,
            )
            return "blocked"

        if await _newer_live_exists(tx, row):
            await _cas_state(tx, row, "superseded", now)
            return "superseded"

        unsigned = await render_intent(row, database)
        if unsigned is None:
            await _cas_state(tx, row, "superseded", now)
            return "superseded"

        # §8.6 step 4 — addressable events use created_at =
        # max(db_now, latest_created_at+1); a newer-than-now timestamp is a
        # clock-skew pause, never a backdate.
        latest = 0
        if row.get("event_address"):
            pa = await tx.fetch_one(
                f"SELECT latest_created_at FROM {tx.table('protocol_addresses')} "
                "WHERE protocol = 'nostr' AND event_kind = :k"
                " AND d_tag = :d AND author_pubkey = :p",
                _address_parts(row["event_address"]),
            )
            latest = (pa["latest_created_at"] or 0) if pa else 0
        clock_scope = (
            "event_address = :a" if row.get("event_address") else
            "aggregate_type = :at AND aggregate_id = :ai AND event_kind = :k"
        )
        clock = await tx.fetch_one(
            f"SELECT MAX(last_signed_at) AS latest FROM {tx.table('outbox_events')}"
            f" WHERE merchant_id = :m AND {clock_scope}",
            {"m": row["merchant_id"], "a": row.get("event_address"),
             "at": row["aggregate_type"], "ai": row["aggregate_id"], "k": row["event_kind"]},
        )
        latest = max(latest, clock["latest"] or 0)
        if latest > now + CLOCK_SKEW_TOLERANCE_S:
            # clock skew — pause, do not publish a stale/future event
            await _cas_state(tx, row, "pending", now, next_attempt_at=latest + 1)
            return "clock_skew"
        created_at = max(now, latest + 1)

        accepted = await _accepted_targets(tx, intent_id)
        targets = [u for u in relay_targets if u not in accepted]
        if row["event_kind"] == 5 and not row.get("event_address"):
            targets = []

        if not targets:
            # everything already accepted (or nothing to send)
            if accepted:
                await _cas_state(tx, row, "published", now)
                await _maybe_activate_merchant(tx, row)
                await _maybe_update_inbox_state(tx, row, "published")
                return "published"
            if row["event_kind"] == 5 and not row.get("event_address"):
                await _cas_state(tx, row, "superseded", now)
                return "superseded"
            state = "failed" if row["attempts"] + 1 >= OUTBOX_MAX_ATTEMPTS else "pending"
            await _cas_state(
                tx, row, state, now, next_attempt_at=now + _backoff(row["attempts"] + 1),
                last_error="no-relay-targets",
            )
            await _maybe_update_inbox_state(tx, row, state)
            return state

        # sign inside the tx window — key released immediately after
        event = await _sign(settings, keystore, row, unsigned, created_at)
        event_id = event.id().to_hex()
        await tx.execute(
            f"UPDATE {tx.table('outbox_events')} SET last_signed_at = :n WHERE id = :i",
            {"n": created_at, "i": intent_id},
        )
        send_timeout = min(30, max(0.1, row["claimed_until"] - await tx.now()))

    try:
        output = await asyncio.wait_for(transport.send_to(targets, event), send_timeout)
    except Exception as exc:  # one relay must never crash the batch
        output = None
        send_error = type(exc).__name__
    else:
        send_error = None

    results = []
    if output is not None:
        ok_urls = {str(u) for u in output.success}
        failed = {str(u): str(m) for u, m in output.failed.items()}
        for u in targets:
            if u in ok_urls:
                results.append((u, "accepted", ""))
            elif u in failed:
                reason = failed[u]
                # OQ6: transient transport failures share the failed
                # map with real negative-OK rejections — classify the
                # known transient vocabulary as retryable timeout and
                # preserve any other message verbatim as 'rejected'.
                results.append(
                    (u,
                     "timeout" if reason in TRANSIENT_REASONS
                     else "rejected",
                     reason))
            else:
                results.append((u, "timeout", "absent from send output"))
    else:
        for u in targets:
            results.append((u, "timeout", send_error or "send failed"))

    async with _publication_transaction(row, worker_id, database) as claimed:
        if not claimed:
            return "lost_claim"
        tx, row = claimed
        now = await tx.now()
        attempt_no = row["attempts"] + 1
        await _record_publications(
            tx, intent_id, "public", event_id, attempt_no, results, now)

        ok_count = sum(1 for _, r, _ in results if r == "accepted")
        if ok_count >= 1 or accepted:
            # quorum reached (public events: >=1 positive OK)
            if ok_count and row.get("event_address") and row["event_kind"] != 5:
                await _record_address(tx, row, event_id, created_at, now)
            await _cas_state(tx, row, "published", now)
            await _maybe_activate_merchant(tx, row)
            await _maybe_update_inbox_state(tx, row, "published")
            return "published"
        if any(r == "accepted" for _, r, _ in results):
            state = "partially_published"
        else:
            state = "pending"
        next_at = now + _backoff(attempt_no)
        if attempt_no >= OUTBOX_MAX_ATTEMPTS:
            state = "failed"
            next_at = 0
        await _cas_state(tx, row, state, now, next_attempt_at=next_at)
        await _maybe_update_inbox_state(tx, row, state)
        return state


async def _publish_order_msg(row: dict, *, transport, keystore,
                             worker_id: str, database=None) -> str:
    """§8.6 order_msg branch — TWO independent wraps per attempt (GAM-03).

    - ``recipient`` copy: buyer-declared kind-10050 peer relays ONLY —
      never public relays, never the source relay;
    - ``sender`` copy: the merchant's own inbox relays only;
    - durable evidence rows carry ``delivery_copy`` ``recipient``/
      ``sender``; retries subtract accepted targets per class so one
      class never re-sends to accepted relays;
    - ``published`` requires ≥1 positive relay OK in EACH copy class —
      one accepted class lands ``partially_published`` and retries the
      missing class; zero lands ``pending`` backoff -> ``failed``;
    - no valid buyer routes -> ``pending`` + ``no_inbox_relays``; the
      buyer's kind-10050 set re-resolves every 15 min for 48h, then the
      intent goes ``failed`` (§9.3 no-route policy).
    """
    import json as _json

    from .. import crypto as crypto_mod
    from ..db import db as default_db
    from ..db import table as default_table
    from ..settings import ext_settings
    from . import metrics, order_messages, peer_relays
    from . import relay as relay_service

    settings = ext_settings()
    intent_id = row["id"]

    # Phase 0 — OUTSIDE the claim transaction: decrypt the descriptor,
    # resolve declared copy routes, subtract durable accepted evidence,
    # rebuild the frozen rumor and wrap BOTH copies. Peer-relay
    # discovery writes its cache in its own domain tx — nesting it under
    # the claim would deadlock the SQLite writer serialisation.
    descriptor = None
    if row["payload_enc"] is not None:
        ver = crypto_mod.envelope_version(row["payload_enc"])
        descriptor = _json.loads(
            crypto_mod.decrypt(
                row["payload_enc"], settings.master_keys[ver],
                record_id=intent_id, table="outbox_events",
                column="payload_enc", key_version=ver,
            ).decode()
        )
    recipient_pubkey = descriptor["recipient_pubkey"] if descriptor else None
    merchant_pubkey = descriptor["author_pubkey"] if descriptor else None

    async def _accepted(copy: str) -> set[str]:
        async with (database or default_db).connect() as conn:
            rows = await conn.fetchall(
                f"SELECT DISTINCT relay_url AS u"
                f" FROM {default_table('relay_publications')} "
                "WHERE outbox_event_id = :i AND result = 'accepted'"
                " AND delivery_copy = :c",
                {"i": intent_id, "c": copy},
            )
        return {r["u"] for r in rows}

    buyer_routes: list[str] | str = peer_relays.NO_INBOX_RELAYS
    sender_all: list[str] = []
    if descriptor is not None:
        buyer_routes = await peer_relays.resolve_buyer_inbox_relays(
            row["merchant_id"], recipient_pubkey, settings=settings,
        )
        sender_all = await relay_service.relay_targets(
            row["merchant_id"], "inbox",
        )
    recipient_accepted = await _accepted("recipient")
    sender_accepted = await _accepted("sender")
    no_route = buyer_routes == peer_relays.NO_INBOX_RELAYS
    recipient_targets = (
        []
        if no_route
        else [u for u in buyer_routes if u not in recipient_accepted]
    )
    sender_targets = [u for u in sender_all if u not in sender_accepted]

    # Exactly TWO nip17_wrap calls — recipient copy + sender copy. The
    # frozen descriptor created_at reproduces the canonical rumor id;
    # each wrap carries a fresh seal/ephemeral outer per attempt.
    rumor = (
        order_messages.rebuild_rumor(descriptor)
        if descriptor is not None
        else None
    )
    recipient_wrap = None
    if recipient_targets:
        recipient_wrap = await keystore.nip17_wrap(
            row["merchant_id"], rumor, recipient_pubkey
        )
    sender_wrap = None
    if sender_targets:
        sender_wrap = await keystore.nip17_wrap(
            row["merchant_id"], rumor, merchant_pubkey
        )

    async with _publication_transaction(row, worker_id, database) as claimed:
        if not claimed:
            return "lost_claim"
        tx, row = claimed
        now = await tx.now()
        if not await _deps_published(tx, intent_id):
            await _cas_state(
                tx, row, "pending", now, next_attempt_at=now,
                bump_attempts=False,
            )
            return "blocked"
        if descriptor is None:
            await _cas_state(tx, row, "failed", now,
                             last_error="missing-payload")
            return "failed"

        if not recipient_accepted and no_route:
            # §9.3: re-resolve on the 15-min cadence; the 48h deadline
            # runs from first enqueue (created_at), not last attempt.
            if now - row["created_at"] >= ORDER_MSG_NO_ROUTE_DEADLINE_S:
                await _cas_state(
                    tx, row, "failed", now, last_error="no_inbox_relays"
                )
                return "failed"
            await _cas_state(
                tx, row, "pending", now,
                next_attempt_at=now + ORDER_MSG_NO_ROUTE_REFRESH_S,
                last_error="no_inbox_relays",
            )
            return "pending"

        if not recipient_targets and not sender_targets:
            # Nothing left to send — publish iff BOTH classes carry
            # durable accepted evidence.
            if recipient_accepted and sender_accepted:
                await _cas_state(tx, row, "published", now)
                return "published"
            state = (
                "partially_published"
                if recipient_accepted or sender_accepted
                else "pending"
            )
            if row["attempts"] + 1 >= OUTBOX_MAX_ATTEMPTS:
                state = "failed"
            await _cas_state(
                tx, row, state, now,
                next_attempt_at=now + _backoff(row["attempts"] + 1),
                last_error="no_inbox_relays"
                if not recipient_accepted else "no-relay-targets",
            )
            return state
        send_timeout = min(
            30, max(0.1, row["claimed_until"] - await tx.now())
        )

    sends: list[tuple[str, object | None, list[str]]] = []
    if recipient_wrap is not None:
        sends.append(("recipient", recipient_wrap, recipient_targets))
    if sender_wrap is not None:
        sends.append(("sender", sender_wrap, sender_targets))
    per_class_results: dict[str, list[tuple[str, str, str]]] = {}
    for copy, wrap, targets in sends:
        try:
            output = await asyncio.wait_for(
                transport.send_to(targets, wrap), send_timeout
            )
        except Exception as exc:  # one relay must never crash the batch
            output = None
            send_error = type(exc).__name__
        else:
            send_error = None
        results: list[tuple[str, str, str]] = []
        if output is not None:
            ok_urls = {str(u) for u in output.success}
            failed = {str(u): str(m) for u, m in output.failed.items()}
            for u in targets:
                if u in ok_urls:
                    results.append((u, "accepted", ""))
                elif u in failed:
                    reason = failed[u]
                    results.append(
                        (
                            u,
                            "timeout" if reason in TRANSIENT_REASONS
                            else "rejected",
                            reason,
                        )
                    )
                else:
                    results.append((u, "timeout", "absent from send output"))
        else:
            for u in targets:
                results.append((u, "timeout", send_error or "send failed"))
        per_class_results[copy] = results

    async with _publication_transaction(row, worker_id, database) as claimed:
        if not claimed:
            return "lost_claim"
        tx, row = claimed
        now = await tx.now()
        attempt_no = row["attempts"] + 1
        for copy, results in per_class_results.items():
            await _record_publications(
                tx, intent_id, copy,
                (
                    recipient_wrap if copy == "recipient" else sender_wrap
                ).id().to_hex(),
                attempt_no, results, now,
            )
        rec_ok = bool(recipient_accepted) or any(
            r == "accepted" for _, r, _
            in per_class_results.get("recipient", [])
        )
        sen_ok = bool(sender_accepted) or any(
            r == "accepted" for _, r, _
            in per_class_results.get("sender", [])
        )
        if rec_ok and sen_ok:
            await _cas_state(tx, row, "published", now)
            metrics.incr("publication.published")
            return "published"
        if rec_ok or sen_ok:
            # One class proven — the missing class retries alone; the
            # accepted class is never resent (accepted-targets subtract).
            state = "partially_published"
        else:
            state = "pending"
        next_at = now + _backoff(attempt_no)
        if attempt_no >= OUTBOX_MAX_ATTEMPTS:
            state = "failed"
            next_at = 0
        await _cas_state(tx, row, state, now, next_attempt_at=next_at)
        return state


async def _maybe_activate_merchant(tx, row) -> None:
    """§3.5 activation: a published merchant_profile intent flips
    ``publication_pending -> active`` — checkout/public surfaces gate on
    ``active`` and this is the only write path for that transition."""
    if row["aggregate_type"] != "merchant_profile":
        return
    await tx.execute(
        f"UPDATE {tx.table('merchants')} SET state = 'active',"
        " updated_at = :n WHERE id = :m AND state = 'publication_pending'",
        {"n": _now(), "m": row["aggregate_id"]},
    )


async def _maybe_update_inbox_state(tx, row, outcome: str) -> None:
    """GAM-01/D-16/D-17: ``merchants.inbox_state`` tracks durable relay
    evidence for the kind-10050 profile — never the intent itself.

    - ``pending -> active`` only when the 10050 intent reaches
      ``published`` (≥1 ``accepted`` relay_publications row exists);
    - ``pending -> error`` when the intent exhausts attempts (``failed``);
    - ``deactivating -> off`` when the ``10050:<pk>:`` kind-5 tombstone
      publishes; a failed tombstone surfaces as ``error`` so a stuck
      deactivation is visible rather than silently retaining reachability.
    """
    if row["aggregate_type"] != "merchant":
        return
    address = row.get("event_address") or ""
    new_state = None
    if row["event_kind"] == 10050:
        if outcome == "published":
            new_state = "active"
        elif outcome == "failed":
            new_state = "error"
    elif row["event_kind"] == 5 and address.startswith("10050:"):
        if outcome == "published":
            new_state = "off"
        elif outcome == "failed":
            new_state = "error"
    if new_state is None:
        return
    await tx.execute(
        f"UPDATE {tx.table('merchants')} SET inbox_state = :s,"
        " updated_at = :n WHERE id = :m",
        {"s": new_state, "n": _now(), "m": row["aggregate_id"]},
    )


def _address_parts(address: str) -> dict:
    kind, pubkey, d_tag = address.split(":", 2)
    return {"p": pubkey, "d": d_tag, "k": int(kind)}


async def _record_address(tx, row, event_id, created_at, now):
    """Preserve protocol-address history (§6.7): upsert the latest event id
    so tombstones and retries reference it."""
    parts = _address_parts(row["event_address"])
    await tx.execute(
        f"INSERT INTO {tx.table('protocol_addresses')} "
        "(id, domain_type, domain_id, protocol, event_kind, author_pubkey,"
        " d_tag, latest_event_id, latest_created_at) "
        "VALUES (:i, :dt, :di, 'nostr', :k, :p, :d, :e, :c) "
        "ON CONFLICT (protocol, event_kind, author_pubkey, d_tag) DO UPDATE SET"
        " latest_event_id = :e, latest_created_at = :c",
        {
            "i": uuid.uuid4().hex,
            "dt": row["aggregate_type"],
            "di": row["aggregate_id"],
            "k": row["event_kind"],
            "p": parts["p"],
            "d": parts["d"],
            "e": event_id,
            "c": created_at,
        },
    )


async def _sign(settings, keystore, row, unsigned, created_at):
    """Deterministic dict -> UnsignedEvent -> merchant-signed Event."""
    from nostr_sdk import EventBuilder, Kind, PublicKey, Tag, Timestamp

    builder = EventBuilder(Kind(unsigned["kind"]), unsigned["content"])
    builder = builder.tags([Tag.parse(list(t)) for t in unsigned["tags"]])
    builder = builder.custom_created_at(Timestamp.from_secs(created_at))
    pubkey_hex = row["event_address"].split(":", 2)[1] \
        if row.get("event_address") and ":" in row["event_address"] \
        else await keystore.public_key(row["merchant_id"])
    unsigned_event = builder.build(PublicKey.parse(pubkey_hex))
    return await keystore.sign_event(row["merchant_id"], unsigned_event)


def _targets_inbox_set(row: dict) -> bool:
    """The kind-10050 profile and its kind-5 tombstone publish to the
    discovery set buyers query — enabled public ∪ inbox targets (OQ1)."""
    if row["event_kind"] == 10050:
        return True
    return row["event_kind"] == 5 and (
        row.get("event_address") or ""
    ).startswith("10050:")


async def publish_targets(row: dict, database=None) -> list[str]:
    """Relay targets for one intent: the public set for catalog/profile
    events; public ∪ inbox for the kind-10050 publish set. ``order_msg``
    intents return [] — _publish_order_msg resolves recipient/sender
    copy sets from peer_relays + merchant inbox relays internally."""
    from . import relay as relay_service

    if row["aggregate_type"] == "order_msg":
        return []
    if _targets_inbox_set(row):
        public = await relay_service.relay_targets(
            row["merchant_id"], "public", database=database
        )
        inbox = await relay_service.relay_targets(
            row["merchant_id"], "inbox", database=database
        )
        return sorted(set(public) | set(inbox))
    return await relay_service.relay_targets(
        row["merchant_id"], "public", database=database
    )


async def recover_stale_claims(now: int, database=None) -> int:
    """Lease-expired claims return to pending/partially_published with the
    claim-token CAS; durable accepted evidence is reconstructed (§8.6)."""
    from ..db import DomainTransaction

    async with DomainTransaction(database) as tx:
        stale = await tx.fetch_all(
            f"SELECT * FROM {tx.table('outbox_events')} "
            "WHERE state = 'claimed' AND claimed_until <= :now" + tx.for_update,
            {"now": now},
        )
        recovered = 0
        for row in stale:
            accepted = await _accepted_targets(tx, row["id"])
            state = "partially_published" if accepted else "pending"
            recovered += await tx.execute(
                f"UPDATE {tx.table('outbox_events')} SET state = :s,"
                " claimed_by = NULL, claimed_until = NULL, claim_token = claim_token + 1,"
                " next_attempt_at = :retry, updated_at = :now"
                " WHERE id = :i AND state = 'claimed' AND claim_token = :t"
                " AND claimed_until <= :now",
                {"s": state, "retry": now + _backoff(row["attempts"]), "now": now,
                 "i": row["id"], "t": row["claim_token"]},
            )
        return recovered


async def worker_tick(worker_id: str, *, now: int | None = None) -> dict:
    """One publisher pass: recover stale claims, claim a batch, publish."""
    from .. import keystore as keystore_mod
    from ..db import worker_db
    from . import metrics
    from .transport import transport

    now = now or _now()
    wdb = worker_db()  # per-worker handle — separate connection pool (§10)
    try:
        recovered = await recover_stale_claims(now, wdb)
        tport = transport()
        if tport.client is None:
            # transport not started yet (relay-manager owns lazy init)
            return {"claimed": 0, "recovered": recovered, "outcomes": []}
        claimed = await claim_batch(now, worker_id, database=wdb)
        outcomes = []
        ks = keystore_mod.key_store()
        for row in claimed:
            targets = await publish_targets(row, database=wdb)
            try:
                outcome = await publish_intent(
                    row, transport=tport, keystore=ks,
                    relay_targets=targets, worker_id=worker_id, now=now,
                    database=wdb,
                )
            except LeaseLostError:
                outcome = "lost_claim"
            except Exception as exc:
                outcome = "lost_claim"
                async with _publication_transaction(row, worker_id, wdb) as live:
                    if live:
                        tx, current = live
                        await _cas_state(
                            tx, current, "pending", now,
                            next_attempt_at=now + _backoff(current["attempts"] + 1),
                            last_error=type(exc).__name__,
                        )
                        outcome = "pending"
            outcomes.append(outcome)
            metrics.incr(f"publication.{outcome}")
        return {"claimed": len(claimed), "recovered": recovered,
                "outcomes": outcomes}
    finally:
        await wdb.engine.dispose()
