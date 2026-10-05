"""Gamma inbox transport (spec section 9.2/8.5) — receive-side only.

The shared no-signer ``Client`` (``services/transport.py``) owns
long-lived kind-1059 subscriptions per (merchant, relay) for merchants
whose ``inbox_state='active'``. ``INFINITEMARKETS_RELAY_IO=off`` keeps
the client from ever dialing.

Admission is split in two stages per §8.5:

- ``admit_event`` — the cheap synchronous gate run per delivered event:
  raw bound -> kind -> exactly-one p tag == merchant -> ``event.verify()``
  -> blocklist -> per-author bucket -> ``INSERT ... ON CONFLICT
  (outer_event_id) DO NOTHING`` as ``received``. A duplicate is a
  successful no-op; rejected pre-insert shapes never reach the table
  (metric counted).
- ``drain_received`` — the leased ``inbox_processor`` worker path:
  ``received`` rows run the expensive chain (``keystore.nip17_unwrap``
  -> rumor bounds -> rumor-author blocklist -> rumor-level dedupe) and
  land at ``validated`` — domain dispatch is plan 03-02's seam (TODO:
  dispatch). ``rejected``/``duplicate`` are terminal.

Per-relay/merchant session semantics (§9.2):

- first session ``since`` = now - 30 days;
- subsequent sessions ``since`` = ``last_completed_session_start`` - 3
  days (the overlap absorbs relay-side lag);
- ``relay_cursors`` commits ONLY after the EOSE frame arrives with every
  delivered event durably admitted — never from event ``created_at``;
- NIP-42 AUTH is manual (``services/nostr_auth.py``) and only ever
  answered on the live connection that delivered the challenge.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid

from loguru import logger

from ..db import DomainTransaction, db, table
from . import metrics

INBOX_PROTOCOL = "gamma-inbox"
FIRST_SESSION_BACKTRACK_S = 30 * 86400
RESYNC_OVERLAP_S = 3 * 86400
KIND_GIFT_WRAP = 1059

#: Session reopen backoff: a relay that keeps CLOSED-ing the REQ (or an
#: _open that throws) used to be retried on the next 5s reconcile tick —
#: an unbounded connect/subscribe/teardown churn that leaked sockets
#: upstream. Exponential per-key backoff, reset only on EOSE (the first
#: evidence a session actually works).
REOPEN_BACKOFF_BASE_S = 30
REOPEN_BACKOFF_MAX_S = 15 * 60

#: A relay that keeps answering our NIP-42 AUTH with CLOSED
#: 'auth-required' is not retrying its way to health — after
#: AUTH_REJECT_MAX closes the (merchant, relay) session is disabled for
#: the process lifetime and the config row is flagged 'auth-failed' for
#: the admin surface (retry via retry_relay_auth re-enables it).
AUTH_REJECT_MAX = 10

# §15 admission bounds
RUMOR_CONTENT_MAX_BYTES = 8 * 1024
RUMOR_TAGS_MAX = 128
RUMOR_TAG_ELEMENT_MAX_BYTES = 2 * 1024
RATE_WRAP_RELAY_PER_MINUTE = 300
DRAIN_BATCH = 64

#: Muted-author audit window: the first dropped wrap per burst leaves a
#: 'rejected' row; later drops in the window are metric-only deletes.
MUTED_BURST_WINDOW_S = 3600


def _now() -> int:
    return int(time.time())


def sub_filter(merchant_pubkey_hex: str, since: int):
    """The §9.2 inbox subscription filter for one merchant."""
    from nostr_sdk import Filter, Kind, PublicKey, Timestamp

    return (
        Filter()
        .kinds([Kind(KIND_GIFT_WRAP)])
        .pubkey(PublicKey.parse(merchant_pubkey_hex))
        .since(Timestamp.from_secs(max(since, 0)))
    )


# --- stage 1: synchronous admission -----------------------------------------


async def _minute_bucket_ok(tx, *, scope: str, bucket: str, cap: int,
                            now: int) -> bool:
    """60-second fixed-window admission bucket (§15) — insert-or-increment
    under the (scope, bucket, window) unique key."""
    window = now - (now % 60)
    row = await tx.fetch_one(
        f"INSERT INTO {tx.table('rate_limit_buckets')} AS rate_bucket "
        "(scope_hash, bucket, window_start, count, expires_at) "
        "VALUES (:s, :b, :w, 1, :e) "
        "ON CONFLICT (scope_hash, bucket, window_start) DO UPDATE "
        "SET count = rate_bucket.count + 1 WHERE rate_bucket.count < :cap "
        "RETURNING count",
        {"s": scope, "b": bucket, "w": window, "e": window + 120,
         "cap": cap},
    )
    return row is not None


def _outer_p_values(raw_tags) -> list[str]:
    return [
        t[1] for t in raw_tags
        if isinstance(t, list) and len(t) >= 2 and t[0] == "p"
    ]


async def admit_event(relay_url: str, event, merchant: dict,
                      settings=None) -> str:
    """Stage-1 admission — §8.5 order:

    raw bound -> kind 1059 -> exactly one ``p`` == merchant pubkey ->
    ``event.verify()`` -> blocklist -> per-author bucket ->
    ``INSERT ... ON CONFLICT (outer_event_id) DO NOTHING``.

    Returns ``'received' | 'duplicate' | 'rejected'``. Pre-insert
    rejections never reach the table (bounded metric only) — invalid-sig
    floods cannot grow rows. The 'inbox-author' cap drops excess
    BEFORE the insert/unwrap work (D-24).
    """
    from .. import crypto
    from ..settings import ext_settings
    from . import metrics

    settings = settings or ext_settings()
    now = _now()
    merchant_id = merchant["id"]

    # bound -> kind -> p-tag -> verify (all cheap, all pre-insert).
    raw = event if isinstance(event, str) else event.as_json()
    if len(raw.encode()) > settings.inbox_max_event_bytes:
        metrics.incr("inbox.admission.oversize")
        return "rejected"
    try:
        raw_data = json.loads(raw)
    except (TypeError, ValueError):
        metrics.incr("inbox.admission.unparseable")
        return "rejected"
    if raw_data.get("kind") != KIND_GIFT_WRAP:
        metrics.incr("inbox.admission.wrong_kind")
        return "rejected"
    p_values = _outer_p_values(raw_data.get("tags") or [])
    if len(p_values) != 1 or p_values[0] != merchant["pubkey"]:
        metrics.incr("inbox.admission.bad_p_tag")
        return "rejected"
    from nostr_sdk import Event

    try:
        parsed = event if not isinstance(event, str) else Event.from_json(raw)
        if not parsed.verify():
            metrics.incr("inbox.admission.bad_signature")
            return "rejected"
    except Exception:  # noqa: BLE001 — any parse/verify failure drops
        metrics.incr("inbox.admission.bad_signature")
        return "rejected"

    outer_author = raw_data.get("pubkey") or ""
    author_hash = crypto.hmac_index(
        settings.privacy_key, crypto.PURPOSE_BUYER_PUBKEY,
        merchant_id, crypto.normalize(outer_author),
    )
    relay_scope = crypto.hmac_index(
        settings.privacy_key, "inbox-wrap", merchant_id,
        crypto.normalize(relay_url),
    )

    async with DomainTransaction() as tx:
        # §15 per-(merchant,relay) intake bound.
        if not await _minute_bucket_ok(
            tx, scope=relay_scope, bucket="wrap-relay",
            cap=RATE_WRAP_RELAY_PER_MINUTE, now=now,
        ):
            metrics.incr("inbox.admission.relay_rate_limited")
            return "rejected"
        blocked = await tx.fetch_one(
            f"SELECT 1 AS x FROM {tx.table('inbox_blocklist')} "
            "WHERE merchant_id = :m AND author_hash = :h",
            {"m": merchant_id, "h": author_hash},
        )
        if blocked is not None:
            metrics.incr("inbox.admission.blocked")
            return "rejected"
        # Per-author cap — drops excess BEFORE insert/unwrap (D-24).
        if not await _minute_bucket_ok(
            tx, scope=author_hash, bucket="inbox-author",
            cap=settings.inbox_author_cap, now=now,
        ):
            metrics.incr("inbox.admission.author_rate_limited")
            return "rejected"
        inserted = await tx.fetch_one(
            f"INSERT INTO {tx.table('inbox_events')} "
            "(id, outer_event_id, merchant_id, source_relay_url,"
            " received_at, processed_state, raw_json) "
            "VALUES (:i, :o, :m, :r, :t, 'received', :raw) "
            "ON CONFLICT (outer_event_id) DO NOTHING RETURNING id",
            {
                "i": uuid.uuid4().hex, "o": raw_data["id"],
                "m": merchant_id, "r": relay_url, "t": now, "raw": raw,
            },
        )
    if inserted is None:
        metrics.incr("inbox.admission.duplicate")
        return "duplicate"
    metrics.incr("inbox.admission.received")
    return "received"


# --- stage 2: leased drain (inbox_processor) ---------------------------------


async def _mark(row_id: str, state: str, reason: str | None,
                now: int) -> None:
    async with DomainTransaction() as tx:
        await tx.execute(
            f"UPDATE {tx.table('inbox_events')} SET"
            " processed_state = :s, reject_reason = :r,"
            " processed_at = :t WHERE id = :i",
            {"s": state, "r": reason, "t": now, "i": row_id},
        )


async def _process_received(row: dict, ks, settings) -> str:
    """One 'received' row through the section-8.5 chain + rumor-level
    dedupe -> 'validated'|'rejected'|'duplicate'."""
    from .. import crypto

    merchant_id = row["merchant_id"]
    row_id = row["id"]
    now = _now()
    metrics.incr("inbox.drain.unwrap")
    try:
        out = await ks.nip17_unwrap(merchant_id, row["raw_json"])
    except Exception as exc:  # WrapRejection carries the bounded reason
        reason = getattr(exc, "reason", type(exc).__name__)
        await _mark(row_id, "rejected", reason, now)
        return "rejected"

    rumor = json.loads(out["rumor_json"])
    if len((rumor.get("content") or "").encode()) > RUMOR_CONTENT_MAX_BYTES:
        await _mark(row_id, "rejected", "rumor-content-bound", now)
        return "rejected"
    tags = rumor.get("tags")
    if not isinstance(tags, list) or len(tags) > RUMOR_TAGS_MAX or any(
        not isinstance(t, list)
        or any(len(str(e).encode()) > RUMOR_TAG_ELEMENT_MAX_BYTES
               for e in t)
        for t in tags
    ):
        await _mark(row_id, "rejected", "rumor-tags-bound", now)
        return "rejected"

    author = out["author_pubkey"]
    author_hash = crypto.hmac_index(
        settings.privacy_key, crypto.PURPOSE_BUYER_PUBKEY,
        merchant_id, crypto.normalize(author),
    )
    author_enc = crypto.encrypt(
        author.encode(), settings.master_keys[settings.active_key_version],
        record_id=row_id, table="inbox_events", column="author_enc",
        key_version=settings.active_key_version,
    )
    async with DomainTransaction() as tx:
        # D-24 per-inner-author cap: excess drops before any domain
        # work — the drop still counts against the same window's bucket.
        cap_ok = await _minute_bucket_ok(
            tx, scope=author_hash, bucket="inbox-author",
            cap=settings.inbox_author_cap, now=now,
        )
        if not cap_ok:
            await tx.execute(
                f"UPDATE {tx.table('inbox_events')} SET"
                " processed_state = 'rejected',"
                " reject_reason = 'author-rate-limited',"
                " author_hash = :ah, author_enc = :ae,"
                " processed_at = :t WHERE id = :i",
                {"t": now, "i": row_id,
                 "ah": author_hash, "ae": author_enc},
            )
            metrics.incr("inbox.drain.author_over_cap")
            return "rejected"
        blocked = await tx.fetch_one(
            f"SELECT 1 AS x FROM {tx.table('inbox_blocklist')} "
            "WHERE merchant_id = :m AND author_hash = :h",
            {"m": merchant_id, "h": author_hash},
        )
        if blocked is not None:
            # Muted authors: ONE 'rejected' drop row per burst window
            # stays auditable (D-21); subsequent wraps delete the row —
            # no inbox_events growth, each drop still a metric +
            # rate-limit-bucket count.
            prior = await tx.fetch_one(
                f"SELECT 1 AS x FROM {tx.table('inbox_events')} "
                "WHERE merchant_id = :m AND author_hash = :h"
                " AND processed_state = 'rejected'"
                " AND reject_reason = 'author-blocked'"
                " AND processed_at >= :w LIMIT 1",
                {"m": merchant_id, "h": author_hash,
                 "w": now - MUTED_BURST_WINDOW_S},
            )
            if prior is not None:
                await tx.execute(
                    f"DELETE FROM {tx.table('inbox_events')} WHERE id = :i",
                    {"i": row_id},
                )
            else:
                await tx.execute(
                    f"UPDATE {tx.table('inbox_events')} SET"
                    " processed_state = 'rejected',"
                    " reject_reason = 'author-blocked',"
                    " author_hash = :ah, author_enc = :ae,"
                    " processed_at = :t WHERE id = :i",
                    {"t": now, "i": row_id,
                     "ah": author_hash, "ae": author_enc},
                )
            metrics.incr("inbox.drain.author_blocked")
            return "rejected"
        # Rumor-level dedupe (§8.5): a retry under a fresh outer id is the
        # SAME message — the guarded update + the (merchant, rumor_id)
        # unique index make the second admission a no-op transition.
        rc = await tx.execute(
            f"UPDATE {tx.table('inbox_events')} SET rumor_id = :r,"
            " kind = :k, author_hash = :ah, author_enc = :ae,"
            " processed_state = 'validated', processed_at = :t"
            " WHERE id = :i AND NOT EXISTS ("
            f"SELECT 1 FROM {tx.table('inbox_events')} x"
            " WHERE x.merchant_id = :m AND x.rumor_id = :r)",
            {
                "r": out["rumor_id"], "k": out["kind"], "ah": author_hash,
                "ae": author_enc, "t": now, "i": row_id,
                "m": merchant_id,
            },
        )
        if rc == 0:
            await tx.execute(
                f"UPDATE {tx.table('inbox_events')} SET"
                " processed_state = 'duplicate',"
                " reject_reason = 'rumor-duplicate', processed_at = :t"
                " WHERE id = :i",
                {"t": now, "i": row_id},
            )
            return "duplicate"
    return "validated"


async def drain_received(*, batch: int = DRAIN_BATCH, keystore=None,
                         settings=None) -> dict:
    """Leased worker pass over ``processed_state='received'`` rows.

    Per-row report-only error handling mirrors ``settlement.reconcile``:
    one bad row never aborts the pass. ``validated`` rows stay parked —
    domain dispatch is the 03-02 seam (TODO: dispatch, not a hidden gap).
    """
    from .. import keystore as keystore_mod
    from ..settings import ext_settings

    settings = settings or ext_settings()
    ks = keystore or keystore_mod.key_store(settings)
    stats = {"validated": 0, "rejected": 0, "duplicate": 0, "errors": 0}
    async with db.connect() as conn:
        rows = await conn.fetchall(
            f"SELECT * FROM {table('inbox_events')} "
            "WHERE processed_state = 'received' "
            "ORDER BY received_at LIMIT :b",
            {"b": batch},
        )
    for row in rows:
        try:
            stats[await _process_received(dict(row), ks, settings)] += 1
        except Exception as exc:  # noqa: BLE001 — report-only per row
            stats["errors"] += 1
            logger.warning(
                "event=infinitemarkets.inbox.process_failed"
                " inbox_event={} err={}",
                row["id"], type(exc).__name__,
            )
    return stats


# --- stage 3: domain dispatch (03-02) -------------------------------------------
#
# ``validated`` rows carry a decrypted, deduped, author-bounded rumor.
# Dispatch re-unwraps the stored ciphertext (deterministic — the row is
# already deduped by rumor id, so re-unwrap cannot double-dispatch) and
# routes by (kind, type) tag. Every state transition is one
# DomainTransaction; ``processed_at`` always sets. Bounded ProblemError
# codes become ``rejected`` rows; parseable rejections also enqueue the
# D-22 ``status=rejected`` type-3 reply.


async def _merchant_for_dispatch(merchant_id: str) -> dict | None:
    async with db.connect() as conn:
        row = await conn.fetchone(
            f"SELECT * FROM {table('merchants')} WHERE id = :m",
            {"m": merchant_id},
        )
    return dict(row) if row else None


async def _enqueue_rejected_reply(
    merchant: dict, recipient_pubkey: str | None,
    order_external_id: str | None, inbox_row_id: str,
) -> None:
    """D-22: ``status=rejected`` type-3 reply inside its own domain tx;
    unintelligible payloads (no recipient/order id) log only."""
    from . import order_messages

    try:
        async with DomainTransaction() as tx:
            await order_messages.enqueue_rejected_reply(
                tx, merchant, recipient_pubkey=recipient_pubkey,
                order_external_id=order_external_id,
                inbox_row_id=inbox_row_id,
            )
    except Exception as exc:  # noqa: BLE001 — reply is best-effort
        logger.warning(
            "event=infinitemarkets.inbox.rejected_reply_failed"
            " inbox_event={} err={}",
            inbox_row_id, type(exc).__name__,
        )


async def _dispatch_validated(row: dict, ks, settings) -> str:
    """One 'validated' row through §8.5 steps 7-10 -> processed |
    rejected | quarantined (+ 'errors' for retryable exceptions)."""
    from ..security import ProblemError
    from . import order_messages

    merchant_id = row["merchant_id"]
    row_id = row["id"]
    now = _now()
    try:
        out = await ks.nip17_unwrap(merchant_id, row["raw_json"])
    except Exception as exc:  # WrapRejection carries the bounded reason
        reason = getattr(exc, "reason", type(exc).__name__)
        await _mark(row_id, "quarantined", reason, now)
        return "quarantined"

    merchant = await _merchant_for_dispatch(merchant_id)
    if merchant is None:
        await _mark(row_id, "quarantined", "merchant-gone", now)
        return "quarantined"
    rumor = json.loads(out["rumor_json"])
    tags = rumor.get("tags") or []
    author = out["author_pubkey"]
    sender_hash = row["author_hash"] or order_messages.buyer_hash(
        settings, merchant_id, author
    )

    # Merchant-authored sender copies: recover evidence only when the
    # rumor id matches an outbound order_messages row — never dispatch
    # as an inbound command.
    if author == merchant["pubkey"]:
        async with db.connect() as conn:
            match = await conn.fetchone(
                f"SELECT id FROM {table('order_messages')} "
                "WHERE rumor_id = :r AND direction = 'out'",
                {"r": out["rumor_id"]},
            )
        if match is None:
            await _mark(row_id, "rejected",
                        "merchant-authored-unknown", now)
            return "rejected"
        async with DomainTransaction() as tx:
            await tx.execute(
                f"UPDATE {tx.table('order_messages')} SET"
                " event_id = :e WHERE id = :i",
                {"e": row["outer_event_id"], "i": match["id"]},
            )
            await tx.execute(
                f"UPDATE {tx.table('inbox_events')} SET"
                " processed_state = 'processed',"
                " reject_reason = 'sender-copy-recovered',"
                " processed_at = :t WHERE id = :i",
                {"t": now, "i": row_id},
            )
        metrics.incr("inbox.dispatch.sender_copy")
        return "processed"

    kind = out["kind"]
    if kind == 16:
        type_tags = [
            t[1] for t in tags
            if isinstance(t, list) and len(t) >= 2 and t[0] == "type"
        ]
        mtype = type_tags[0] if len(type_tags) == 1 else None
        ext_ids = [
            t[1] for t in tags
            if isinstance(t, list) and len(t) >= 2 and t[0] == "order"
        ]
        ext_id = ext_ids[0] if len(ext_ids) == 1 else None
        if mtype == "1":
            try:
                payload = order_messages.build_checkout_payload(
                    out["rumor_json"], merchant
                )
            except ProblemError as exc:
                await _mark(row_id, "rejected", exc.code, now)
                # The reply carries the buyer's own order id verbatim —
                # never a server-assigned id (D-22 no-oracle).
                await _enqueue_rejected_reply(
                    merchant, author, ext_id, row_id,
                )
                return "rejected"
            try:
                from . import checkout as checkout_service

                await checkout_service.gamma_order_intake(
                    merchant=merchant, payload=payload,
                    buyer_pubkey=author,
                    rumor_id=out["rumor_id"], now=now,
                )
            except ProblemError as exc:
                await _mark(row_id, "rejected", exc.code, now)
                await _enqueue_rejected_reply(
                    merchant, author, payload.get("external_id"), row_id
                )
                return "rejected"
            await _mark(row_id, "processed", None, now)
            metrics.incr("inbox.dispatch.order_created")
            return "processed"
        if mtype == "2":
            # Merchant-only type — a buyer-side payment request can
            # never mint invoices (§6.9).
            await _mark(row_id, "rejected",
                        "inbound-type2-unsupported", now)
            return "rejected"
        if mtype == "3":
            result = await order_messages.handle_inbound_status(
                merchant=merchant, sender_hash=sender_hash,
                rumor=rumor, now=now,
            )
            await _mark(row_id, "processed", None, now)
            metrics.incr("inbox.dispatch.status")
            return "processed"
        await _mark(row_id, "rejected", "unknown-order-type", now)
        return "rejected"
    if kind == 17:
        await order_messages.handle_receipt(
            merchant=merchant, sender_hash=sender_hash,
            rumor=rumor, now=now,
        )
        await _mark(row_id, "processed", None, now)
        metrics.incr("inbox.dispatch.receipt")
        return "processed"
    if kind == 14:
        result = await order_messages.handle_dm(
            merchant=merchant, sender_hash=sender_hash,
            author_pubkey=author, rumor=rumor,
            rumor_id=out["rumor_id"], now=now,
        )
        if result["outcome"] == "rate-limited":
            await _mark(row_id, "rejected", "dm-rate-limited", now)
            return "rejected"
        await _mark(row_id, "processed", None, now)
        metrics.incr("inbox.dispatch.dm")
        return "processed"
    await _mark(row_id, "quarantined", "rumor-kind-not-allowed", now)
    return "quarantined"


async def process_pending(*, batch: int = DRAIN_BATCH, keystore=None,
                          settings=None) -> dict:
    """Leased worker pass over ``processed_state='validated'`` rows.

    Report-only per row — a thrown dispatch (retryable exception) leaves
    the row 'validated' for the next pass/reconcile; only ProblemError /
    explicit outcomes mark terminal states.
    """
    from .. import keystore as keystore_mod
    from ..settings import ext_settings

    settings = settings or ext_settings()
    ks = keystore or keystore_mod.key_store(settings)
    stats = {"processed": 0, "rejected": 0, "quarantined": 0,
             "duplicate": 0, "errors": 0}
    async with db.connect() as conn:
        rows = await conn.fetchall(
            f"SELECT * FROM {table('inbox_events')} "
            "WHERE processed_state = 'validated' "
            "ORDER BY received_at LIMIT :b",
            {"b": batch},
        )
    for row in rows:
        try:
            stats[await _dispatch_validated(dict(row), ks, settings)] += 1
        except Exception as exc:  # noqa: BLE001 — retry on the next pass
            stats["errors"] += 1
            logger.warning(
                "event=infinitemarkets.inbox.dispatch_failed"
                " inbox_event={} err={}",
                row["id"], type(exc).__name__,
            )
    return stats


async def drain_and_process(*, batch: int = DRAIN_BATCH, keystore=None,
                            settings=None) -> dict:
    """The worker entry point: received -> validated -> domain dispatch
    in one leased pass."""
    first = await drain_received(batch=batch, keystore=keystore,
                                 settings=settings)
    second = await process_pending(batch=batch, keystore=keystore,
                                   settings=settings)
    merged = dict(first)
    for key, value in second.items():
        merged[key] = merged.get(key, 0) + value
    return merged


# --- session runtime ----------------------------------------------------------


class _Session:
    """One merchant×relay kind-1059 subscription."""

    __slots__ = ("merchant_id", "merchant_pubkey", "relay_url",
                 "subscription_id", "session_start", "delivered",
                 "eose_seen", "filter", "auth_answered", "resubscribed")

    def __init__(self, merchant_id: str, merchant_pubkey: str,
                 relay_url: str, session_start: int):
        self.merchant_id = merchant_id
        self.merchant_pubkey = merchant_pubkey
        self.relay_url = relay_url
        self.subscription_id: str | None = None
        self.session_start = session_start
        self.delivered = 0
        self.eose_seen = False
        # Retained for the post-AUTH REQ re-issue: relays that answer an
        # unauthenticated REQ with an AUTH challenge (nostrrelay's
        # require-auth filter) never register that REQ — the filter must
        # be replayed once the AUTH answer lands (§9.5 gated reads).
        self.filter = None
        self.auth_answered = False
        self.resubscribed = False


class _NotificationHandler:
    """UniFFI callback — exceptions must never cross the FFI boundary."""

    def __init__(self, runtime: "InboxRuntime"):
        self._runtime = runtime

    async def handle(self, relay_url, subscription_id, event):
        try:
            await self._runtime.on_event(
                str(relay_url), str(subscription_id), event
            )
        except Exception as exc:  # noqa: BLE001 — FFI boundary
            logger.warning(
                "event=infinitemarkets.inbox.handler_error"
                " op=event err={}",
                type(exc).__name__,
            )

    async def handle_msg(self, relay_url, msg):
        try:
            await self._runtime.on_msg(str(relay_url), msg)
        except Exception as exc:  # noqa: BLE001 — FFI boundary
            logger.warning(
                "event=infinitemarkets.inbox.handler_error"
                " op=relay_msg err={}",
                type(exc).__name__,
            )


def _handler_class():
    from nostr_sdk import HandleNotification

    class Handler(HandleNotification):
        def __init__(self, runtime):
            self._inner = _NotificationHandler(runtime)

        async def handle(self, relay_url, subscription_id, event):
            await self._inner.handle(relay_url, subscription_id, event)

        async def handle_msg(self, relay_url, msg):
            await self._inner.handle_msg(relay_url, msg)

    return Handler


class InboxRuntime:
    """Inbox session registry over the SHARED no-signer transport — the
    same client that serves the outbox, so one connection carries both
    the publish path and kind-1059 subscriptions."""

    def __init__(self) -> None:
        self._handler_task: asyncio.Task | None = None
        self._sessions: dict[tuple[str, str], _Session] = {}
        self._by_sub: dict[str, _Session] = {}
        # AUTH challenges can arrive between connect_relay() and session
        # registration — stash per relay and answer once a session exists.
        self._pending_auth: dict[str, str] = {}
        # Per-key reopen backoff — see REOPEN_BACKOFF_* above.
        self._failures: dict[tuple[str, str], int] = {}
        self._retry_at: dict[tuple[str, str], int] = {}
        # Per-key AUTH rejection count; a key lands in _disabled at
        # AUTH_REJECT_MAX — see _handle_closed.
        self._auth_rejects: dict[tuple[str, str], int] = {}
        self._disabled: set[tuple[str, str]] = set()

    async def ensure_started(self) -> None:
        from .transport import transport

        tport = transport()
        if tport.client is None:
            await tport.start([])
        if self._handler_task is None:
            self._handler_task = asyncio.ensure_future(
                tport.handle_notifications(_handler_class()(self))
            )

    async def reconcile(self) -> dict:
        """Converge live sessions to active-merchant × enabled-inbox sets.

        Egress validation re-runs here, so a relay that newly resolves to
        private space is dropped on the same cadence reconnect would use.
        """
        from . import relay as relay_service
        from .transport import (
            relay_io_enabled,
            validate_peer_relay_target,
        )

        if not relay_io_enabled():
            return {"sessions": 0}
        desired: dict[tuple[str, str], str] = {}
        async with db.connect() as conn:
            merchants = await conn.fetchall(
                f"SELECT id, pubkey FROM {table('merchants')} "
                "WHERE inbox_state = 'active'"
            )
        for m in merchants:
            for url in await relay_service.relay_targets(m["id"], "inbox"):
                desired[(m["id"], url)] = m["pubkey"]
        if not desired:
            for key in list(self._sessions):
                await self._close(key)
            return {"sessions": 0}
        await self.ensure_started()
        report = {"sessions": len(self._sessions)}
        for key in list(self._sessions):
            if key not in desired:
                await self._close(key)
        now = _now()
        for (mid, url), pubkey in desired.items():
            key = (mid, url)
            if key in self._sessions:
                continue
            if key in self._disabled:
                continue
            if now < self._retry_at.get(key, 0):
                continue
            try:
                await validate_peer_relay_target(url)
            except Exception:
                logger.warning(
                    "event=infinitemarkets.inbox.egress_rejected"
                    " merchant={} relay={}",
                    mid, url,
                )
                continue
            try:
                await self._open(mid, pubkey, url)
            except Exception as exc:  # noqa: BLE001 — backoff, then retry
                self._note_failure(key)
                logger.warning(
                    "event=infinitemarkets.inbox.session_open_failed"
                    " merchant={} relay={} err={}",
                    mid, url, type(exc).__name__,
                )
        report["sessions"] = len(self._sessions)
        return report

    async def _cursor_since(self, merchant_id: str, relay_url: str,
                            now: int) -> int:
        async with db.connect() as conn:
            row = await conn.fetchone(
                f"SELECT last_completed_session_start AS s"
                f" FROM {table('relay_cursors')} WHERE merchant_id = :m"
                " AND relay_url = :r AND protocol = :p",
                {"m": merchant_id, "r": relay_url, "p": INBOX_PROTOCOL},
            )
        if row and row["s"]:
            return int(row["s"]) - RESYNC_OVERLAP_S
        return now - FIRST_SESSION_BACKTRACK_S

    async def _open(self, merchant_id: str, merchant_pubkey: str,
                    relay_url: str) -> None:
        from nostr_sdk import RelayUrl

        from .transport import transport

        tport = transport()
        now = _now()
        since = await self._cursor_since(merchant_id, relay_url, now)
        session = _Session(merchant_id, merchant_pubkey,
                           relay_url, now)
        # Register BEFORE connecting: an AUTH challenge delivered during
        # connect must find a session to key the answer.
        self._sessions[(merchant_id, relay_url)] = session
        target = RelayUrl.parse(relay_url)
        client = tport.client
        try:
            if target not in await client.relays():
                await client.add_relay(target)
            await client.connect_relay(target)
            # Settle briefly: a connect-time AUTH challenge dispatches to
            # _handle_auth on the pump task — give it a slice so the answer
            # lands on the wire BEFORE the REQ (relays demanding NIP-42 close
            # an unauthenticated REQ on sight). Stashed challenges answer now.
            await asyncio.sleep(0.05)
            pending = self._pending_auth.pop(relay_url, None)
            if pending is not None:
                await self._handle_auth(relay_url, pending)
            session.filter = sub_filter(merchant_pubkey, since)
            out = await client.subscribe_to(
                [target], session.filter
            )
            session.subscription_id = str(out.id)
            self._by_sub[str(out.id)] = session
            await self._maybe_resubscribe(session)
        except Exception:
            # A half-open session must not stay registered: reconcile skips
            # keys in _sessions, so it would never retry and never close —
            # the merchant's inbox would be dead until restart.
            key = (merchant_id, relay_url)
            self._sessions.pop(key, None)
            if session.subscription_id:
                self._by_sub.pop(session.subscription_id, None)
            if not any(s.relay_url == relay_url
                       for s in self._sessions.values()):
                try:
                    await tport.remove_relay(relay_url)
                except Exception:  # noqa: BLE001 — best-effort teardown
                    pass
            raise
        logger.info(
            "event=infinitemarkets.inbox.session_open merchant={}"
            " relay={} since={}",
            merchant_id, relay_url, since,
        )

    async def _close(self, key: tuple[str, str]) -> None:
        from .transport import transport

        session = self._sessions.pop(key, None)
        if session is None:
            return
        if session.subscription_id:
            self._by_sub.pop(session.subscription_id, None)
            try:
                await transport().unsubscribe(session.subscription_id)
            except Exception:  # noqa: BLE001 — best-effort teardown
                pass
        in_use = any(s.relay_url == session.relay_url
                     for s in self._sessions.values())
        if not in_use:
            self._pending_auth.pop(session.relay_url, None)
            try:
                # remove_relay, not just disconnect — a disconnected-but-
                # pooled relay silently swallows REQs on reconnect.
                await transport().remove_relay(session.relay_url)
            except Exception:  # noqa: BLE001
                pass
        logger.info(
            "event=infinitemarkets.inbox.session_close merchant={}"
            " relay={}",
            session.merchant_id, session.relay_url,
        )

    # --- notification plumbing ----------------------------------------------

    async def on_event(self, relay_url: str, subscription_id: str,
                       event) -> None:
        session = self._by_sub.get(subscription_id)
        if session is None:
            return
        session.delivered += 1
        result = await admit_event(
            session.relay_url, event,
            {"id": session.merchant_id,
             "pubkey": session.merchant_pubkey},
        )
        logger.debug(
            "event=infinitemarkets.inbox.admitted merchant={}"
            " relay={} result={}",
            session.merchant_id, session.relay_url, result,
        )

    async def on_msg(self, relay_url: str, msg) -> None:
        enum = msg.as_enum()
        if enum.is_end_of_stored_events():
            session = self._by_sub.get(str(enum.subscription_id))
            if session is None:
                return
            await self.eose_and_advance_cursor(session)
        elif enum.is_auth():
            await self._handle_auth(relay_url, enum.challenge)
        elif enum.is_closed():
            await self._handle_closed(
                relay_url, str(enum.subscription_id), enum.message
            )

    async def eose_and_advance_cursor(self, session: _Session) -> None:
        """EOSE reached with every delivered event already durably
        admitted (handler ordering is sequential) — commit
        ``last_completed_session_start`` now and only now (§9.2)."""
        now = _now()
        async with DomainTransaction() as tx:
            await tx.execute(
                f"INSERT INTO {tx.table('relay_cursors')} (id,"
                " merchant_id, relay_url, protocol,"
                " last_completed_session_start, eose_session_id,"
                " eose_at, updated_at) "
                "VALUES (:i, :m, :r, :p, :s, :e, :t, :t) "
                "ON CONFLICT (merchant_id, relay_url, protocol) "
                "DO UPDATE SET last_completed_session_start = :s,"
                " eose_session_id = :e, eose_at = :t, updated_at = :t",
                {
                    "i": uuid.uuid4().hex, "m": session.merchant_id,
                    "r": session.relay_url, "p": INBOX_PROTOCOL,
                    "s": session.session_start, "e": uuid.uuid4().hex,
                    "t": now,
                },
            )
        session.eose_seen = True
        # EOSE is the first evidence a session works — clear its backoff
        # and any accrued AUTH rejections.
        key = (session.merchant_id, session.relay_url)
        self._failures.pop(key, None)
        self._retry_at.pop(key, None)
        self._auth_rejects.pop(key, None)
        self._disabled.discard(key)
        # A REQ served after an AUTH answer is the strongest authentication
        # evidence the relay provides — fold it into the D-26 surface.
        async with DomainTransaction() as tx:
            await tx.execute(
                f"UPDATE {tx.table('relay_configs')} SET"
                " auth_state = 'authenticated', auth_updated_at = :t"
                " WHERE merchant_id = :m AND relay_url = :r"
                " AND auth_state = 'auth-sent'",
                {"t": now, "m": session.merchant_id,
                 "r": session.relay_url},
            )
        logger.info(
            "event=infinitemarkets.inbox.cursor_committed merchant={}"
            " relay={} delivered={}",
            session.merchant_id, session.relay_url, session.delivered,
        )

    async def _handle_auth(self, relay_url: str, challenge: str) -> None:
        from .. import keystore as keystore_mod
        from . import nostr_auth
        from .transport import transport

        session = next(
            (s for s in self._sessions.values()
             if s.relay_url == relay_url),
            None,
        )
        if session is None:
            self._pending_auth[relay_url] = challenge
            return
        answered = await nostr_auth.answer_auth_challenge(
            transport().client, keystore_mod.key_store(),
            session.merchant_id,
            relay_url=relay_url, challenge=challenge,
        )
        # NIP-42: relays that answer an unauthenticated REQ with an AUTH
        # challenge (nostrrelay's require-auth filter) never registered
        # that REQ — once the AUTH answer lands on the wire the filter
        # must be replayed or the session stalls with no EOSE. Relays
        # that instead CLOSE the REQ drop the session first
        # (_handle_closed -> _open replays it), so this only matters when
        # the connection survived the challenge. Marking auth_answered
        # only once a REQ is in flight keeps the pre-REQ pending-answer
        # path from triggering a redundant re-issue.
        if answered and session.filter is not None:
            session.auth_answered = True
            await self._maybe_resubscribe(session)

    async def _maybe_resubscribe(self, session: "_Session") -> None:
        """Replay the session REQ after a surviving AUTH answer."""
        if (
            not session.auth_answered
            or session.resubscribed
            or session.subscription_id is None
            or session.filter is None
        ):
            return
        from nostr_sdk import RelayUrl

        from .transport import transport

        old_id = session.subscription_id
        try:
            out = await transport().client.subscribe_to(
                [RelayUrl.parse(session.relay_url)], session.filter
            )
        except Exception:  # noqa: BLE001 — reconcile re-opens on miss
            return
        session.resubscribed = True
        session.subscription_id = str(out.id)
        self._by_sub.pop(old_id, None)
        self._by_sub[session.subscription_id] = session

    def _note_failure(self, key: tuple[str, str]) -> None:
        """Exponential reopen backoff — unclassified CLOSEDs and open
        failures used to retry every 5s forever."""
        n = self._failures.get(key, 0) + 1
        self._failures[key] = n
        self._retry_at[key] = _now() + min(
            REOPEN_BACKOFF_BASE_S * (2 ** (n - 1)), REOPEN_BACKOFF_MAX_S
        )

    async def _handle_closed(self, relay_url: str, subscription_id: str,
                             message: str) -> None:
        from . import nostr_auth

        session = self._by_sub.get(subscription_id)
        state = nostr_auth.classify_closed(message)
        if session is not None:
            key = (session.merchant_id, session.relay_url)
            if state == "auth-required":
                rejects = self._auth_rejects.get(key, 0) + 1
                self._auth_rejects[key] = rejects
                if rejects >= AUTH_REJECT_MAX:
                    # Relay won't take our AUTH — stop dialing it and flag
                    # the row 'auth-failed' so the admin surface shows a
                    # retryable terminal state instead of an endless flap.
                    self._disabled.add(key)
                    await nostr_auth.update_relay_auth_state(
                        session.merchant_id, session.relay_url,
                        "auth-failed",
                        note=f"auth rejected {rejects} times; disabled",
                    )
                    logger.warning(
                        "event=infinitemarkets.inbox.auth_disabled"
                        " merchant={} relay={} rejects={}",
                        session.merchant_id, relay_url, rejects,
                    )
                else:
                    await nostr_auth.update_relay_auth_state(
                        session.merchant_id, session.relay_url, state
                    )
            elif state:
                await nostr_auth.update_relay_auth_state(
                    session.merchant_id, session.relay_url, state
                )
            # A CLOSED subscription is dead — drop the session so the
            # reconcile cadence re-opens it (e.g. after AUTH lands), under
            # the per-key backoff so a repeat-closer doesn't churn.
            self._note_failure(key)
            await self._close(key)
        logger.info(
            "event=infinitemarkets.inbox.req_closed relay={} state={}"
            " msg={}",
            relay_url, state, (message or "")[:160],
        )

    def clear_backoff(self, merchant_id: str, relay_url: str) -> None:
        """Drop all retry state for one key — the admin 'retry auth'
        action must take effect in-process, not only after a restart."""
        key = (merchant_id, relay_url)
        self._failures.pop(key, None)
        self._retry_at.pop(key, None)
        self._auth_rejects.pop(key, None)
        self._disabled.discard(key)

    async def close(self) -> None:
        task, self._handler_task = self._handler_task, None
        if task is not None:
            task.cancel()
        self._sessions.clear()
        self._by_sub.clear()
        self._pending_auth.clear()
        self._failures.clear()
        self._retry_at.clear()
        self._auth_rejects.clear()
        self._disabled.clear()


_runtime: InboxRuntime | None = None


def inbox_runtime() -> InboxRuntime:
    """Process-wide inbox runtime (per-worker on multi-worker hosts)."""
    global _runtime
    if _runtime is None:
        _runtime = InboxRuntime()
    return _runtime
