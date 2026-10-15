"""P0-10: SMTP boolean boundary evidence (QUAL-10).

Executable section 8.8 send-path model runs proving:

(a) only ``True`` enters ``sent``: True -> sent with sent_at; False, a
    raised exception, and recipient rejection all return the row to pending
    with bounded unclassified retry ``min(2^attempts * 30s, 4h)`` and after
    ``EMAIL_MAX_ATTEMPTS`` (5) enter ``failed`` — never sent, never a
    category label beyond the bounded last_error code;
(b) suppressed rows are marked suppressed without any SMTP call when
    unconfigured/disabled/revoked;
(c) rate limiting before delivery via rate_limit_buckets keyed on
    recipient_hash (customer, 8/hour) and merchant id (merchant alerts,
    60/hour) — never the raw address — and excess waits rather than
    delivering;
(d) log exposure: the model's structured logs never contain recipient
    addresses or bearer links (the magic-link token) — correlation is by
    order id and event type only;
(e) queue uniqueness dedupes INTENT, not SMTP delivery: a crash after SMTP
    acceptance before commit may re-deliver on resume — exactly-once intent
    with at-least-once delivery semantics under that crash point.
"""

from __future__ import annotations

import pytest

from harness import email as email_module

pytestmark = [pytest.mark.db, pytest.mark.fast]

T0 = 2_000_000_000
BUYER = "buyer-boundary@example.org"
MERCHANT = "alerts-boundary@shop.example"


async def _seed_order(
    qual_db,
    *,
    order_id: str = "o1",
    email_opt_in: bool = True,
):
    async with qual_db.connect() as conn:
        async with qual_db.transaction(conn) as t:
            await t.execute(
                f"INSERT INTO {qual_db.table('orders')}"
                " (id, merchant_id, state, email_opt_in, total_sat,"
                "  created_at, updated_at)"
                " VALUES (:o, 'merchant-1', 'received', :opt_in, 1000,"
                "  :now, :now)",
                {"o": order_id, "opt_in": email_opt_in, "now": T0},
            )


async def _enqueue_customer(qual_db, model, *, event_type="confirmed", address=BUYER):
    await model.enqueue(
        merchant_id="merchant-1",
        order_id="o1",
        channel="customer",
        event_type=event_type,
        recipient_address=address,
        now=T0,
    )


async def _queue_row(qual_db) -> dict:
    rows = await qual_db.fetch_all(
        f"SELECT * FROM {qual_db.table('email_queue')}"
    )
    assert len(rows) == 1
    return rows[0]


async def _claim_one(model, *, now: int) -> dict:
    claimed = await model.claim(now=now, lease_seconds=600)
    assert len(claimed) == 1
    return claimed[0]


# --- (a) only True enters sent --------------------------------------------------


async def test_only_true_enters_sent_false_retries_with_bound(qual_db_factory):
    async with qual_db_factory() as qual_db:
        await _seed_order(qual_db)
        model = email_module.EmailModel(qual_db)
        model.smtp.outcome = "false"  # unclassified failure
        await _enqueue_customer(qual_db, model)

        row = await _claim_one(model, now=T0 + 10)
        result = await model.send(row, now=T0 + 10)
        assert result == {"action": "pending", "attempts": 1}
        stored = await _queue_row(qual_db)
        assert stored["state"] == "pending"
        assert not stored["sent_at"]
        # Bounded unclassified retry: min(2^1 * 30s, 4h).
        assert stored["next_attempt_at"] == T0 + 10 + 60
        assert stored["last_error"] == "smtp-failed"
        # Never a transient-vs-5xx category label.
        assert "transient" not in stored["last_error"]
        assert "5xx" not in stored["last_error"]

        # Attempt 2 after the retry delay.
        row = await _claim_one(model, now=T0 + 10 + 60)
        result = await model.send(row, now=T0 + 10 + 60)
        assert result == {"action": "pending", "attempts": 2}
        stored = await _queue_row(qual_db)
        assert stored["next_attempt_at"] == T0 + 10 + 60 + 120  # 2^2 * 30s


async def test_raised_exception_and_recipient_rejection_surface_identically(
    qual_db_factory,
):
    async with qual_db_factory() as qual_db:
        for outcome in ("raise", "recipient-rejected"):
            await _seed_order(qual_db, order_id=f"o-{outcome}")
            model = email_module.EmailModel(qual_db)
            model.smtp.outcome = outcome
            await model.enqueue(
                merchant_id="merchant-1",
                order_id=f"o-{outcome}",
                channel="customer",
                event_type="confirmed",
                recipient_address=BUYER,
                now=T0,
            )
            rows = await model.claim(now=T0 + 10)
            assert len(rows) == 1
            result = await model.send(rows[0], now=T0 + 10)
            # Both surface as the SAME unclassified bounded retry — the host
            # erases SMTP failure categories; v1 does not invent
            # transient-vs-5xx classification.
            assert result["action"] == "pending"
            stored = [
                row
                for row in await qual_db.fetch_all(
                    f"SELECT * FROM {qual_db.table('email_queue')}"
                )
                if row["order_id"] == f"o-{outcome}"
            ][0]
            assert stored["state"] == "pending"
            assert stored["last_error"] == "smtp-failed"
            assert not stored["sent_at"]


async def test_exhausted_attempts_enter_failed_never_sent(qual_db_factory):
    async with qual_db_factory() as qual_db:
        await _seed_order(qual_db)
        model = email_module.EmailModel(qual_db)
        model.smtp.outcome = "false"
        await _enqueue_customer(qual_db, model)

        # Failed cycles bring attempts up; the fifth failure enters failed
        # (EMAIL_MAX_ATTEMPTS = 5).
        now = T0 + 10
        for attempt in range(1, model.EMAIL_MAX_ATTEMPTS):
            row = await _claim_one(model, now=now)
            result = await model.send(row, now=now)
            assert result["action"] == "pending"
            assert result["attempts"] == attempt
            now += min(2 ** attempt * 30, model.RETRY_MAX_S)
        row = await _claim_one(model, now=now)
        result = await model.send(row, now=now)
        assert result == {"action": "failed", "attempts": model.EMAIL_MAX_ATTEMPTS}

        stored = await _queue_row(qual_db)
        assert stored["state"] == "failed"
        assert not stored["sent_at"]
        # The exhausted row is no longer claimable, and it was NEVER sent.
        assert await model.claim(now=now + 10_000) == []
        assert all(c["to"] == BUYER for c in model.smtp.calls)


async def test_true_enters_sent_with_sent_at(qual_db_factory):
    async with qual_db_factory() as qual_db:
        await _seed_order(qual_db)
        model = email_module.EmailModel(qual_db)
        model.smtp.outcome = "true"
        await _enqueue_customer(qual_db, model)

        row = await _claim_one(model, now=T0 + 10)
        result = await model.send(row, now=T0 + 10)
        assert result["action"] == "sent"
        stored = await _queue_row(qual_db)
        assert stored["state"] == "sent"
        assert stored["sent_at"] == T0 + 10
        assert stored["last_error"] is None
        assert len(model.smtp.calls) == 1


# --- (b) suppression without any SMTP call -----------------------------------------


async def test_suppressed_rows_never_touch_smtp(qual_db_factory):
    async with qual_db_factory() as qual_db:
        await _seed_order(qual_db)  # opted-in customer row
        # (1) host SMTP not configured.
        model = email_module.EmailModel(qual_db, email_configured=False)
        await _enqueue_customer(qual_db, model)
        row = await _claim_one(model, now=T0 + 10)
        result = await model.send(row, now=T0 + 10)
        assert result == {"action": "suppressed", "reason": "smtp-not-configured"}
        stored = await _queue_row(qual_db)
        assert stored["state"] == "suppressed"
        assert stored["last_error"] == "smtp-not-configured"

    async with qual_db_factory() as qual_db:
        await _seed_order(qual_db)
        # (2) the merchant disabled the event type.
        model = email_module.EmailModel(
            qual_db, enabled_event_types={"order_received"}
        )
        await _enqueue_customer(qual_db, model, event_type="shipped")
        row = await _claim_one(model, now=T0 + 10)
        result = await model.send(row, now=T0 + 10)
        assert result == {"action": "suppressed", "reason": "event-type-disabled"}
        stored = await _queue_row(qual_db)
        assert stored["state"] == "suppressed"

    async with qual_db_factory() as qual_db:
        await _seed_order(qual_db)
        # (3) customer consent revoked between enqueue and send: the opt-out
        # cancels the queued customer row, so nothing is claimable to send.
        model = email_module.EmailModel(qual_db)
        await _enqueue_customer(qual_db, model)
        await model.opt_out(order_id="o1", now=T0 + 5)
        assert await model.claim(now=T0 + 10) == []
        assert model.smtp.calls == []  # no SMTP call in ANY suppression path


# --- (c) rate limiting before delivery ----------------------------------------------


async def test_customer_rate_limit_waits_rather_than_delivering(qual_db_factory):
    async with qual_db_factory() as qual_db:
        model = email_module.EmailModel(qual_db)
        # Nine opted-in orders for the SAME recipient: over the 8/hour
        # per-recipient_hash bound (section 15).
        for i in range(9):
            await _seed_order(qual_db, order_id=f"o{i}")
            await model.enqueue(
                merchant_id="merchant-1",
                order_id=f"o{i}",
                channel="customer",
                event_type="confirmed",
                recipient_address=BUYER,
                now=T0,
            )

        now = T0 + 10
        delivered = 0
        waited = 0
        while True:
            claimed = await model.claim(now=now, lease_seconds=600)
            if not claimed:
                break
            for row in claimed:
                result = await model.send(row, now=now)
                if result["action"] == "sent":
                    delivered += 1
                elif result["action"] == "rate-limited":
                    waited += 1
                    assert result["wait_until"] > now  # excess WAITS
        assert delivered == model.CUSTOMER_PER_HOUR
        assert waited == 1
        assert len(model.smtp.calls) == delivered  # the excess was NOT sent

        # The rate-limited row delivers in the next window.
        next_window = (T0 + 10) // 3600 * 3600 + 3600
        claimed = await model.claim(now=next_window, lease_seconds=600)
        assert len(claimed) == 1
        result = await model.send(claimed[0], now=next_window)
        assert result["action"] == "sent"

        # The buckets are keyed on the recipient HASH, never the raw
        # address (byte-level absence is proven in P0-09 (e)).
        buckets = await qual_db.fetch_all(
            f"SELECT * FROM {qual_db.table('rate_limit_buckets')}"
        )
        assert buckets
        for bucket in buckets:
            assert BUYER not in bucket["scope_hash"]


async def test_merchant_alert_rate_limit_at_60_per_hour(qual_db_factory):
    async with qual_db_factory() as qual_db:
        model = email_module.EmailModel(qual_db)
        await _seed_order(qual_db)
        # 61 merchant alert rows for the same merchant (merchant alerts are
        # not order-unique; the bound is 60/hour per merchant).
        for i in range(model.MERCHANT_PER_HOUR + 1):
            await model.enqueue(
                merchant_id="merchant-1",
                order_id="o1",
                channel="merchant",
                event_type="order_received",
                recipient_address=f"owner{i:03d}@shop.example",
                now=T0,
            )

        now = T0 + 10
        delivered = 0
        waited = 0
        while True:
            claimed = await model.claim(now=now, lease_seconds=600)
            if not claimed:
                break
            for row in claimed:
                result = await model.send(row, now=now)
                if result["action"] == "sent":
                    delivered += 1
                elif result["action"] == "rate-limited":
                    waited += 1
        assert delivered == model.MERCHANT_PER_HOUR
        assert waited == 1
        assert len(model.smtp.calls) == delivered


# --- (d) log exposure -----------------------------------------------------------------


async def test_logs_expose_neither_recipients_nor_bearer_links(qual_db_factory):
    async with qual_db_factory() as qual_db:
        await _seed_order(qual_db)
        model = email_module.EmailModel(qual_db)
        token = await model.issue_public_token(order_id="o1", now=T0)
        await _enqueue_customer(qual_db, model)
        link = await model.render_magic_link(order_id="o1", now=T0 + 1)
        assert link is not None

        # Exercise send (sent), retry (failure), and suppressed log paths.
        row = await _claim_one(model, now=T0 + 10)
        await model.send(row, now=T0 + 10)  # sent

        model2 = email_module.EmailModel(qual_db)  # a second row for retry
        await model2.enqueue(
            merchant_id="merchant-1",
            order_id="o1",
            channel="merchant",
            event_type="refund_requested",
            recipient_address=MERCHANT,
            now=T0,
        )
        model2.smtp.outcome = "false"
        rows = await model2.claim(now=T0 + 20, lease_seconds=600)
        await model2.send(rows[0], now=T0 + 20)  # retry

        # A third row for the suppressed path (unconfigured host SMTP).
        await model2.enqueue(
            merchant_id="merchant-1",
            order_id="o1",
            channel="merchant",
            event_type="on_hold",
            recipient_address=MERCHANT,
            now=T0,
        )
        model3 = email_module.EmailModel(qual_db, email_configured=False)
        rows = await model3.claim(now=T0 + 30, lease_seconds=600)
        assert len(rows) == 1
        await model3.send(rows[0], now=T0 + 30)  # suppressed

        all_logs = model.logs + model2.logs + model3.logs
        assert all_logs  # logs were captured on every path
        for entry in all_logs:
            serialized = repr(entry)
            # Correlation is by order id and event type only.
            assert BUYER not in serialized
            assert MERCHANT not in serialized
            assert token not in serialized  # the bearer link token
            assert "example.org" not in serialized
            assert "example.com" not in serialized
        assert any(entry["code"] == "sent" for entry in all_logs)
        assert any(entry["code"] == "retry" for entry in all_logs)
        assert any("suppressed" in entry["code"] for entry in all_logs)


# --- (e) intent vs delivery under the crash point -------------------------------------


async def test_crash_after_smtp_acceptance_redelivers_on_resume(qual_db_factory):
    """Queue uniqueness dedupes intent, not SMTP delivery.

    A crash after SMTP acceptance but before the commit leaves the row
    claimable again: the delivery may repeat (at-least-once delivery),
    while the queue still holds exactly ONE intent row (exactly-once
    intent). This is the documented semantics of section 4.18's closing
    note, exhibited rather than hidden.
    """
    async with qual_db_factory() as qual_db:
        await _seed_order(qual_db)
        model = email_module.EmailModel(qual_db)
        await _enqueue_customer(qual_db, model)

        row = await _claim_one(model, now=T0 + 10)
        with pytest.raises(email_module.CrashAfterSmtpAcceptance):
            await model.send(row, now=T0 + 10, crash_after_smtp=True)

        # The crash left the row claimed (the outcome never committed);
        # after the lease expires it is claimable again.
        stored = await _queue_row(qual_db)
        assert stored["state"] == "claimed"
        assert stored["sent_at"] is None
        # SMTP already accepted the first delivery.
        assert len(model.smtp.calls) == 1

        # Resume: the expired lease requeues via claim-token CAS, and the
        # row is re-delivered (at-least-once delivery)...
        requeued = await model.requeue_stale(now=T0 + 10 + 700)
        assert requeued == 1
        row = await _claim_one(model, now=T0 + 10 + 800)
        result = await model.send(row, now=T0 + 10 + 800)
        assert result["action"] == "sent"
        assert len(model.smtp.calls) == 2  # delivered twice under the crash

        # ...while the queue intent stays EXACTLY ONE row.
        rows = await qual_db.fetch_all(
            f"SELECT * FROM {qual_db.table('email_queue')}"
        )
        assert len(rows) == 1
        assert rows[0]["state"] == "sent"
