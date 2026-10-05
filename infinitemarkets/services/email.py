"""Email notification worker — spec section 8.8.

Best-effort, never blocking order transitions. Rows are claimed with the
claim-token CAS discipline of §8.6; every leased write compares the token.
Suppression (marked ``suppressed``, no SMTP call) applies when the host
SMTP path is unconfigured, the extension email switch is off, the merchant
disabled the event type, consent was revoked, or the merchant is inactive.

Templates render at send time from current order state — subjects carry
only the merchant display name and event name (never buyer PII or internal
ids); bodies may include item summaries, totals, state, and the public
status link rendered from the protected token copy while it is live.

Only a host ``send_email`` ``True`` enters ``sent``; ``False``/exception
returns to ``pending`` with bounded unclassified backoff — v1 does not
claim to distinguish transient transport errors from SMTP 5xx.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
import uuid

from loguru import logger

from .. import crypto
from ..db import Database, DomainTransaction, db
from ..settings import ext_settings

EMAIL_BATCH = 16
CLAIM_LEASE_S = 120
BACKOFF_BASE_S = 30
BACKOFF_CAP_S = 4 * 3600
CUSTOMER_HOURLY_CAP = 8
MERCHANT_HOURLY_CAP = 60
ACCOUNT_HOURLY_CAP = 8

_EVENT_LABELS = {
    "order_received": "new order received",
    "confirmed": "order confirmed",
    "processing": "order processing",
    "shipped": "order shipped",
    "delivered": "order delivered",
    "cancelled": "order cancelled",
    "expired": "order expired",
    "on_hold": "order on hold",
    "refund_requested": "refund requested",
    "signin_link": "your sign-in link",
}


def _now() -> int:
    return int(time.time())


def _backoff(attempts: int) -> int:
    return min(
        2 ** attempts * BACKOFF_BASE_S, BACKOFF_CAP_S
    ) + random.randint(0, 30)


# --- claim (section 8.8 step 1 — §8.6 discipline) -----------------------------


async def claim_batch(
    now: int, worker_id: str, database: Database | None = None,
) -> list[dict]:
    """Atomically claim due rows; claim_token fencing on every write."""
    settings = ext_settings()
    database = database or db
    async with DomainTransaction(database) as tx:
        select = (
            f"SELECT id FROM {tx.table('email_queue')} "
            "WHERE state IN ('pending') AND next_attempt_at <= :n"
            " AND attempts < :maxa ORDER BY next_attempt_at, id"
            " LIMIT :lim"
        )
        if tx.for_update:
            select += tx.for_update + " SKIP LOCKED"
        ids = [
            r["id"] for r in await tx.fetch_all(
                select, {"n": now, "maxa": settings.email_max_attempts,
                         "lim": EMAIL_BATCH},
            )
        ]
        if not ids:
            return []
        placeholders = ", ".join(f":i{k}" for k in range(len(ids)))
        params = {f"i{k}": v for k, v in enumerate(ids)}
        await tx.execute(
            f"UPDATE {tx.table('email_queue')} SET state = 'claimed',"
            " claimed_by = :w, claimed_at = :n, claimed_until = :u,"
            " claim_token = claim_token + 1"
            f" WHERE id IN ({placeholders}) AND state = 'pending'",
            {"w": worker_id, "n": now, "u": now + CLAIM_LEASE_S, **params},
        )
        return await tx.fetch_all(
            f"SELECT * FROM {tx.table('email_queue')} "
            f"WHERE id IN ({placeholders}) AND state = 'claimed' AND claimed_by = :w",
            {**params, "w": worker_id},
        )


async def _leased_write(
    tx: DomainTransaction, row: dict, set_clause: str, params: dict
) -> None:
    """One claim-token-CAS write; a lost CAS raises."""
    rc = await tx.execute(
        f"UPDATE {tx.table('email_queue')} SET {set_clause}"
        " WHERE id = :i AND claim_token = :ct AND claimed_until > :n"
        " AND state = 'claimed' AND claimed_by = :w",
        {**params, "i": row["id"], "ct": row["claim_token"],
         "n": await tx.now(), "w": row["claimed_by"]},
    )
    if rc != 1:
        raise RuntimeError(
            f"email row {row['id']!r} lost its claim-token CAS"
        )


async def _rate_bucket_ok(
    tx: DomainTransaction, *, scope: str, bucket: str, cap: int, now: int
) -> bool:
    """Hourly fixed-window cap — the bucket key is already an HMAC/hash
    (recipient_hash or merchant id), never a raw address (§15/§8.8)."""
    window = now - (now % 3600)
    row = await tx.fetch_one(
        f"INSERT INTO {tx.table('rate_limit_buckets')} AS rate_bucket "
        "(scope_hash, bucket, window_start, count, expires_at) "
        "VALUES (:s, :b, :w, 1, :e) "
        "ON CONFLICT (scope_hash, bucket, window_start) DO UPDATE "
        "SET count = rate_bucket.count + 1 WHERE rate_bucket.count < :cap RETURNING count",
        {"s": scope, "b": bucket, "w": window, "e": window + 7200, "cap": cap},
    )
    return row is not None


# --- suppression + rendering -----------------------------------------------------


async def _suppression_reason(
    tx: DomainTransaction, row: dict, merchant: dict | None,
    order: dict | None, host_email_ready: bool,
) -> str | None:
    """Bounded suppression code, or None when the send may proceed."""
    settings = ext_settings()
    if not settings.email_enabled:
        return "email-disabled"
    if not host_email_ready:
        return "host-email-unconfigured"
    if merchant is None or merchant["state"] == "inactive":
        return "merchant-inactive"
    events = json.loads(merchant["notify_events"]) if (
        merchant["notify_events"]
    ) else {}
    if row["event_type"] in events and not events[row["event_type"]]:
        return "event-disabled"
    # ``channel == 'account'`` rows (magic links) skip the consent check by
    # construction — the mailbox itself is the credential being proven.
    if row["channel"] == "customer":
        if order is None or not order["email_opt_in"]:
            return "consent-revoked"
    return None


def _subject(merchant: dict, event_type: str) -> str:
    """Subjects carry only display name + event name — never PII/ids."""
    name = (merchant.get("display_name") or "Infinitemarkets").strip()
    label = _EVENT_LABELS.get(event_type, "order update")
    return f"{name}: {label}"[:150]


def _render_body(
    row: dict, order: dict | None, items: list[dict],
    merchant: dict, status_link: str | None,
    delivery: list[dict] | None = None,
) -> str:
    """Plain-text body — item summaries, totals, state, status link, and
    (on the paid confirmation only) the merchant's digital delivery.

    Never carries decrypted addresses, keys, payment secrets, or full
    BOLT11/preimage material (§8.8).
    """
    label = _EVENT_LABELS.get(row["event_type"], "order update")
    lines = [f"Order {label}."]
    if order is not None:
        lines.append(f"State: {order['state']}")
        if order.get("total_sat") is not None:
            lines.append(f"Total: {order['total_sat']} sats")
    for item in items:
        lines.append(
            f"- {item.get('title') or 'item'} x{item['quantity']}"
        )
    for entry in delivery or []:
        lines.append(f"\nYour digital item — {entry['title']}:\n{entry['content']}")
    if status_link:
        lines.append(f"Order status: {status_link}")
    lines.append(
        "This is a transactional order notification."
    )
    return "\n".join(lines)


def _render_signin_body(merchant: dict, link: str) -> str:
    """Magic-link body — the fragment-bearing URL is the only secret;
    the bare token and the recipient address never appear anywhere."""
    name = (merchant.get("display_name") or "Infinitemarkets").strip()
    return "\n".join(
        [
            f"Use this link to sign in to {name}: {link}",
            "The link expires in 15 minutes and works once.",
            "If you didn't request it, you can ignore this email.",
        ]
    )


async def _status_link(
    order: dict | None, settings
) -> str | None:
    """Render the magic link only while the order's token is live and the
    AEAD copy still exists (erased on expiry/revocation)."""
    if not order or not order.get("public_token_enc"):
        return None
    now = _now()
    if (
        order.get("public_token_expires_at") is not None
        and order["public_token_expires_at"] <= now
    ):
        return None
    try:
        ver = crypto.envelope_version(order["public_token_enc"])
        token = crypto.decrypt(
            order["public_token_enc"], settings.master_keys[ver],
            record_id=order["id"], table="orders",
            column="public_token_enc", key_version=ver,
        ).decode()
    except Exception:
        return None
    return f"{settings.public_base_url}/infinitemarkets/order#{token}"


# --- the worker --------------------------------------------------------------------


async def worker_tick(
    worker_id: str, *, now: int | None = None,
    database: Database | None = None,
) -> dict:
    """One §8.8 pass: claim -> suppress-or-send -> classify."""
    now = _now() if now is None else now
    settings = ext_settings()
    rows = await claim_batch(now, worker_id, database)
    outcomes: dict[str, int] = {}
    if not rows:
        return {"claimed": 0, "outcomes": outcomes}

    from lnbits.settings import settings as host_settings

    host_ready = host_settings.is_email_notifications_configured()
    from lnbits.core.services.notifications import send_email

    async def _send(row: dict) -> str:
        async with DomainTransaction(database) as tx:
            deadline = time.monotonic()
            db_now = await tx.now()
            live = await tx.fetch_one(
                f"SELECT * FROM {tx.table('email_queue')} WHERE id = :i"
                " AND state = 'claimed' AND claimed_by = :w AND claim_token = :t"
                " AND claimed_until > :n" + tx.for_update,
                {"i": row["id"], "w": worker_id, "t": row["claim_token"], "n": db_now},
            )
            if not live:
                return "lost_claim"
            row = live
            deadline += row["claimed_until"] - db_now
            merchant = await tx.fetch_one(
                f"SELECT * FROM {tx.table('merchants')} WHERE id = :m",
                {"m": row["merchant_id"]},
            )
            order = None
            items: list[dict] = []
            if row["order_id"]:
                order = await tx.fetch_one(
                    f"SELECT * FROM {tx.table('orders')} WHERE id = :o",
                    {"o": row["order_id"]},
                )
                items = await tx.fetch_all(
                    f"SELECT title, quantity FROM {tx.table('order_items')}"
                    " WHERE order_id = :o",
                    {"o": row["order_id"]},
                )
            delivery: list[dict] = []
            if order and row["channel"] == "customer" and row["event_type"] == "confirmed":
                from .orders import digital_delivery

                delivery = await digital_delivery(tx, order)
            reason = await _suppression_reason(
                tx, row, merchant, order, host_ready
            )
            if reason:
                await _leased_write(
                    tx, row,
                    "state = 'suppressed', last_error = :e",
                    {"e": reason},
                )
                return "suppressed"

            # §8.8 step 6: per-recipient rate limit before the SMTP call.
            # ``channel == 'account'`` needs its own explicit branch —
            # scoped on the recipient hash; the else-branch would silently
            # bucket account rows under ``email-merchant``.
            if row["channel"] == "account":
                ok = await _rate_bucket_ok(
                    tx, scope=row["recipient_hash"],
                    bucket="email-account", cap=ACCOUNT_HOURLY_CAP,
                    now=now,
                )
            elif row["channel"] == "customer":
                ok = await _rate_bucket_ok(
                    tx, scope=row["recipient_hash"],
                    bucket="email-customer", cap=CUSTOMER_HOURLY_CAP,
                    now=now,
                )
            else:
                ok = await _rate_bucket_ok(
                    tx, scope=row["merchant_id"],
                    bucket="email-merchant", cap=MERCHANT_HOURLY_CAP,
                    now=now,
                )
            if not ok:
                # Defer to the next window — the row stays claimed only
                # until we return it to pending with a bounded retry time.
                await _leased_write(
                    tx, row,
                    "state = 'pending', next_attempt_at = :na,"
                    " claimed_by = NULL, claimed_at = NULL,"
                    " claimed_until = NULL",
                    {"na": now - (now % 3600) + 3600},
                )
                return "rate-deferred"
        # The SMTP boundary is outside the transaction (never hold the
        # claim across network I/O).
        ver = crypto.envelope_version(row["recipient_enc"])
        recipient = crypto.decrypt(
            row["recipient_enc"], settings.master_keys[ver],
            # encrypt-time record ids: order rows bind to the order,
            # orderless rows (test sends) bind to the merchant.
            record_id=row["order_id"] or row["merchant_id"],
            table="email_queue",
            column="recipient_enc", key_version=ver,
        ).decode()
        if (
            row["channel"] == "account"
            and row["event_type"] == "signin_link"
        ):
            # Magic-link render: the token lives only in ``payload_enc``
            # until this point; the link carries it in the URL fragment
            # (§5.4 contract — never path/query/subject/logs).
            pver = crypto.envelope_version(row["payload_enc"])
            token = json.loads(
                crypto.decrypt(
                    row["payload_enc"], settings.master_keys[pver],
                    record_id=row["id"], table="email_queue",
                    column="payload_enc", key_version=pver,
                )
            )["token"]
            shop_q = (
                f"?shop={merchant['pubkey']}"
                if merchant and merchant.get("pubkey")
                else ""
            )
            link = (
                f"{settings.public_base_url}/infinitemarkets/auth/email"
                f"{shop_q}#{token}"
            )
            subject = _subject(merchant or {}, row["event_type"])
            body = _render_signin_body(merchant or {}, link)
        else:
            link = await _status_link(order, settings)
            subject = _subject(merchant or {}, row["event_type"])
            body = _render_body(
                row, order, items, merchant or {}, link, delivery
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return "lost_claim"
        try:
            sent = await asyncio.wait_for(
                send_email(
                    host_settings.lnbits_email_notifications_server,
                    host_settings.lnbits_email_notifications_port,
                    host_settings.lnbits_email_notifications_username,
                    host_settings.lnbits_email_notifications_password,
                    host_settings.lnbits_email_notifications_email,
                    [recipient],
                    subject,
                    body,
                ),
                timeout=min(30, remaining),
            )
        except Exception:
            sent = False
        async with DomainTransaction(database) as tx:
            if sent:
                # Sent rows retain no bearer material: recipient_enc AND
                # any payload_enc (magic-link token) are wiped together.
                await _leased_write(
                    tx, row,
                    "state = 'sent', sent_at = :t, recipient_enc = :empty,"
                    " payload_enc = :empty",
                    {"t": now, "empty": b""},
                )
                return "sent"
            attempts = row["attempts"] + 1
            if attempts >= settings.email_max_attempts:
                await _leased_write(
                    tx, row,
                    "state = 'failed', attempts = :a, last_error = 'send-failed'",
                    {"a": attempts},
                )
                return "failed"
            await _leased_write(
                tx, row,
                "state = 'pending', attempts = :a,"
                " next_attempt_at = :na, last_error = 'send-failed',"
                " claimed_by = NULL, claimed_at = NULL,"
                " claimed_until = NULL",
                {"a": attempts, "na": now + _backoff(attempts)},
            )
            return "retry"

    for row in rows:
        try:
            outcome = await _send(row)
        except Exception as exc:  # noqa: BLE001 — per-row isolation
            logger.warning(
                f"infinitemarkets email row {row['id']} failed: {type(exc).__name__}"
            )
            outcome = "error"
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
        from . import metrics
        metrics.incr(f"email.{outcome}")
    return {"claimed": len(rows), "outcomes": outcomes}


async def recover_stale_claims(
    now: int | None = None, database: Database | None = None
) -> int:
    """Return rows whose claim lease expired to pending (§8.6 recovery)."""
    now = _now() if now is None else now
    database = database or db
    async with DomainTransaction(database) as tx:
        rc = await tx.execute(
            f"UPDATE {tx.table('email_queue')} SET state = 'pending',"
            " claimed_by = NULL, claimed_at = NULL, claimed_until = NULL"
            " WHERE state = 'claimed' AND claimed_until <= :n",
            {"n": now},
        )
    return rc


async def enqueue_test_send(
    *, merchant_id: str, recipient: str, now: int | None = None
) -> str:
    """Enqueue the §5.1 test notification through the same durable path."""
    settings = ext_settings()
    now = _now() if now is None else now
    enc = crypto.encrypt(
        recipient.encode(),
        settings.master_keys[settings.active_key_version],
        record_id=merchant_id, table="email_queue",
        column="recipient_enc", key_version=settings.active_key_version,
    )
    digest = crypto.hmac_index(
        settings.privacy_key, crypto.PURPOSE_EMAIL_RECIPIENT,
        merchant_id, crypto.normalize(recipient),
    )
    row_id = uuid.uuid4().hex
    async with DomainTransaction() as tx:
        await tx.execute(
            f"INSERT INTO {tx.table('email_queue')} "
            "(id, merchant_id, order_id, channel, event_type,"
            " recipient_enc, recipient_hash, state, attempts,"
            " next_attempt_at, claim_token, created_at) "
            "VALUES (:i, :m, NULL, 'merchant', 'order_received',"
            " :re, :rh, 'pending', 0, :n, 0, :n)",
            {"i": row_id, "m": merchant_id, "re": enc, "rh": digest,
             "n": now},
        )
    return row_id


async def enqueue_magic_link(
    tx: DomainTransaction, *, merchant_id: str, recipient: str,
    token: str, now: int,
) -> str:
    """Enqueue one orderless sign-in link — ``channel='account'`` /
    ``event_type='signin_link'`` (D-07).

    Called INSIDE the caller's ``DomainTransaction`` so the
    ``email_signin_tokens`` row and this queue row commit atomically.
    The raw token persists ONLY inside ``payload_enc`` (AEAD'd like the
    ``orders.public_token_enc`` custody posture) and is decrypted at send
    time to render the fragment link; ``email_queue`` rows with NULL
    ``order_id`` never dedupe — the request-side per-email/IP caps are
    the only volume bound.
    """
    settings = ext_settings()
    ver = settings.active_key_version
    key = settings.master_keys[ver]
    row_id = uuid.uuid4().hex
    enc = crypto.encrypt(
        recipient.encode(), key,
        record_id=merchant_id, table="email_queue",
        column="recipient_enc", key_version=ver,
    )
    digest = crypto.hmac_index(
        settings.privacy_key, crypto.PURPOSE_EMAIL_RECIPIENT,
        merchant_id, crypto.normalize(recipient),
    )
    payload = crypto.encrypt(
        json.dumps({"token": token}).encode(), key,
        record_id=row_id, table="email_queue",
        column="payload_enc", key_version=ver,
    )
    await tx.execute(
        f"INSERT INTO {tx.table('email_queue')} "
        "(id, merchant_id, order_id, channel, event_type,"
        " recipient_enc, recipient_hash, payload_enc, state, attempts,"
        " next_attempt_at, claim_token, created_at) "
        "VALUES (:i, :m, NULL, 'account', 'signin_link', :re, :rh, :pe,"
        " 'pending', 0, :n, 0, :n)",
        {"i": row_id, "m": merchant_id, "re": enc, "rh": digest,
         "pe": payload, "n": now},
    )
    return row_id
