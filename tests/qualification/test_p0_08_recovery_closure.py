"""P0-08: restart-at-checkpoint recovery closure evidence (QUAL-08).

The restart matrix over the executable models: kill at every section 8.2
saga boundary (after reservation before invoice call; after invoice before
attach; after attach before enqueue; between settlement and callback — the
section 17 failure drill where the fake core payment is settled but the
invoice-paid callback is lost), at inbox checkpoints (admitted-not-validated,
validated-not-dispatched), and at outbox checkpoints (claimed not published;
partially published with durable accepted targets; lease expired mid-claim).

After each restart: every row resumes or terminates explicitly (no row left
in claimed/publishing/creating without a live lease or terminal state), only
missing relay targets retry while accepted targets are never resent, the
canonical rumor id and positive-ACK evidence survive restart, stale claims
requeue only via claim-token CAS reconstruction from durable
relay_publications, and relay cursors do not regress (crash before EOSE
leaves the prior cursor intact).

Two settlement-side recovery cases join the matrix (section 8.7 bullet 1,
section 8.3, section 17):

(i) settlement-callback loss — reconciliation queries the core payment
    status and confirms exactly once via the section 8.3 transaction, then
    a duplicate callback and a reconciliation rerun are no-ops;
(ii) pre-reservation crash resume — a committed received order is resumed
    by idempotently beginning section 8.2; a double resume neither
    double-reserves nor double-invoices.

Also covers duplicate gift wraps including the merchant's own sender copy
being recovered as a sender copy without dispatching a domain command
(section 8.5 step 7 semantics at the queue-model level).
"""

from __future__ import annotations

import pytest

from harness import queues, saga, tx

pytestmark = [pytest.mark.db, pytest.mark.fast]

ON_HAND = 5
QTY = 2
TOTAL_SAT = 1000
T0 = 2_000_000_000
UNCERTAINTY_WINDOW = 300


async def _seed_order(
    qual_db,
    *,
    order_id: str = "o1",
    product_id: str = "p1",
    on_hand: int = ON_HAND,
    qty: int = QTY,
    total_sat: int = TOTAL_SAT,
):
    async with qual_db.connect() as conn:
        async with qual_db.transaction(conn) as t:
            await t.execute(
                f"INSERT INTO {qual_db.table('products')}"
                " (id, merchant_id, stock_on_hand, stock_reserved)"
                " VALUES (:p, 'merchant-1', :h, 0)",
                {"p": product_id, "h": on_hand},
            )
            await t.execute(
                f"INSERT INTO {qual_db.table('orders')}"
                " (id, merchant_id, state, total_sat, created_at, updated_at)"
                " VALUES (:o, 'merchant-1', 'received', :total, :now, :now)",
                {"o": order_id, "total": total_sat, "now": T0},
            )
            await t.execute(
                f"INSERT INTO {qual_db.table('order_items')}"
                " (id, order_id, product_id, product_d, title, quantity,"
                "  unit_price_minor, currency, currency_decimals, line_total_sat)"
                " VALUES (:item_id, :o, :p, 'd', 'title', :qty, 500, 'SAT', 0,"
                " :total)",
                {
                    "item_id": f"item-{order_id}",
                    "o": order_id,
                    "p": product_id,
                    "qty": qty,
                    "total": total_sat,
                },
            )


async def _order(qual_db, order_id: str = "o1") -> dict:
    rows = await qual_db.fetch_all(
        f"SELECT * FROM {qual_db.table('orders')} WHERE id = :id",
        {"id": order_id},
    )
    assert rows
    return rows[0]


async def _payment(qual_db, order_id: str = "o1") -> dict:
    rows = await qual_db.fetch_all(
        f"SELECT * FROM {qual_db.table('payments')} WHERE order_id = :id",
        {"id": order_id},
    )
    assert rows
    return rows[0]


async def _product(qual_db, product_id: str = "p1") -> dict:
    rows = await qual_db.fetch_all(
        f"SELECT stock_on_hand, stock_reserved, revision FROM"
        f" {qual_db.table('products')} WHERE id = :id",
        {"id": product_id},
    )
    assert rows
    return rows[0]


async def _reservations(qual_db, order_id: str = "o1") -> list[dict]:
    return await qual_db.fetch_all(
        f"SELECT * FROM {qual_db.table('inventory_reservations')}"
        " WHERE order_id = :id",
        {"id": order_id},
    )


async def _order_events(qual_db, order_id: str = "o1") -> list[dict]:
    return await qual_db.fetch_all(
        f"SELECT * FROM {qual_db.table('order_events')} WHERE order_id = :id"
        " ORDER BY created_at, id",
        {"id": order_id},
    )


async def _outbox_row(qual_db, intent_id: str) -> dict:
    rows = await qual_db.fetch_all(
        f"SELECT * FROM {qual_db.table('outbox_events')} WHERE id = :id",
        {"id": intent_id},
    )
    assert rows, f"outbox intent {intent_id} must exist"
    return rows[0]


async def _assert_no_dangling_queue_rows(qual_db, *, now: int) -> None:
    """Closure invariant: no claimed/publishing row without a live lease."""
    rows = await qual_db.fetch_all(
        f"SELECT id, state, claimed_until FROM {qual_db.table('outbox_events')}"
        " WHERE state IN ('claimed', 'publishing')"
    )
    for row in rows:
        assert row["claimed_until"] is not None and row["claimed_until"] > now, (
            f"outbox row {row['id']} in {row['state']} without a live lease"
        )


def _targets(*specs: tuple[str, str]) -> list[dict]:
    return [
        {"delivery_copy": copy, "relay_url": relay} for copy, relay in specs
    ]


# --- section 8.2 saga boundary restarts ----------------------------------------


async def test_restart_after_reservation_before_invoice_call(qual_db_factory):
    """Crash after the step-1 claim, before the LNbits call.

    The order is invoice_pending with held stock and a ``creating``
    projection; the fake core has nothing. Restart: within the five-minute
    uncertainty window reconciliation changes nothing; after it, the
    projection is failed and ONLY an invoice_pending order is
    released/rejected.
    """
    async with qual_db_factory() as qual_db:
        await _seed_order(qual_db)
        fake = saga.FakeLNbitsCore()

        # Step 1 only: claim + creating projection, no invoice call.
        await tx.claim_and_reserve_multi(
            qual_db,
            items=[{"product_id": "p1", "qty": QTY, "reservation_id": "res-o1-p1"}],
            order_id="o1",
            expires_at=T0 + 900,
            now=T0,
            payment={
                "id": "pay-o1",
                "core_external_id": saga.core_external_id_for("o1"),
                "checking_id_enc": None,
                "wallet_refs_enc": None,
                "wallet_id_hash": "wh-wallet-main",
                "source_wallet_id_hash": "wh-wallet-main",
                "amount_sat": TOTAL_SAT,
            },
        )
        assert fake.create_calls["o1"] == 0
        assert (await _order(qual_db))["state"] == "invoice_pending"
        assert (await _payment(qual_db))["status"] == "creating"

        # Restart within the uncertainty window: still creating, no action.
        model2 = saga.InvoiceSaga(qual_db, fake)
        report = await model2.reconcile(now=T0 + 100)
        assert report["failed_projections"] == []
        assert report["attached"] == []
        assert (await _payment(qual_db))["status"] == "creating"
        assert (await _product(qual_db))["stock_reserved"] == QTY

        # After the window: projection failed, order rejected, stock freed.
        report = await model2.reconcile(now=T0 + UNCERTAINTY_WINDOW + 1)
        assert len(report["failed_projections"]) == 1
        assert (await _payment(qual_db))["status"] == "failed"
        assert (await _order(qual_db))["state"] == "rejected"
        assert (await _product(qual_db))["stock_reserved"] == 0
        assert [r["state"] for r in await _reservations(qual_db)] == ["released"]
        # Explicit closure: nothing left creating without resolution.
        rows = await qual_db.fetch_all(
            f"SELECT * FROM {qual_db.table('payments')}"
            " WHERE status IN ('creating', 'creation_unknown')"
        )
        assert rows == []


async def test_restart_after_invoice_before_attach(qual_db_factory):
    """The section 8.2 crash window: LNbits persisted, the extension did not.

    Restart + reconciliation queries by exact core_external_id, independent
    of order state, and attaches through the step-3 transaction: order enters
    awaiting_payment, reservation expiries align to the decoded invoice
    expiry, and the payment request is enqueued exactly once.
    """
    async with qual_db_factory() as qual_db:
        await _seed_order(qual_db)
        fake = saga.FakeLNbitsCore()

        # Steps 1-2 only: claim, then create the invoice in the fake core,
        # WITHOUT the attach transaction (the crash window).
        await tx.claim_and_reserve_multi(
            qual_db,
            items=[{"product_id": "p1", "qty": QTY, "reservation_id": "res-o1-p1"}],
            order_id="o1",
            expires_at=T0 + 900,
            now=T0,
            payment={
                "id": "pay-o1",
                "core_external_id": saga.core_external_id_for("o1"),
                "checking_id_enc": None,
                "wallet_refs_enc": None,
                "wallet_id_hash": "wh-wallet-main",
                "source_wallet_id_hash": "wh-wallet-main",
                "amount_sat": TOTAL_SAT,
            },
        )
        invoice = await fake.create_invoice(
            order_id="o1",
            core_external_id=saga.core_external_id_for("o1"),
            amount_sat=TOTAL_SAT,
            wallet_id="wallet-main",
            source_wallet_id="wallet-main",
            expiry_at=T0 + 900,
        )
        assert fake.create_calls["o1"] == 1
        assert (await _payment(qual_db))["status"] == "creating"

        # Restart: reconciliation discovers the invoice by external id.
        model2 = saga.InvoiceSaga(qual_db, fake)
        report = await model2.reconcile(now=T0 + 30)
        assert len(report["attached"]) == 1
        assert report["attached"][0]["outcome"] == "attached"

        payment = await _payment(qual_db)
        assert payment["status"] == "pending"
        assert payment["payment_hash"] == invoice.payment_hash
        assert bytes(payment["checking_id_enc"]) == invoice.checking_id.encode()
        assert (await _order(qual_db))["state"] == "awaiting_payment"
        # Reservation expiries aligned to the decoded invoice expiry.
        reservations = await _reservations(qual_db)
        assert [r["state"] for r in reservations] == ["held"]
        assert reservations[0]["expires_at"] == invoice.expiry_at
        # The type-2 payment request exists exactly once (idempotent).
        intent = await _outbox_row(qual_db, "obx-o1-payment-request")
        assert intent["event_kind"] == 2
        report2 = await model2.reconcile(now=T0 + 40)
        assert report2["reenqueued_payment_requests"] == []
        rows = await qual_db.fetch_all(
            f"SELECT id FROM {qual_db.table('outbox_events')}"
            " WHERE aggregate_type = 'order_msg' AND aggregate_id = 'o1'"
        )
        assert len(rows) == 1
        # No second invoice was created by the recovery.
        assert fake.create_calls["o1"] == 1


async def test_restart_after_attach_before_enqueue(qual_db_factory):
    """Crash after attach (awaiting_payment + pending payment) but before the
    type-2 outbox row: reconciliation enqueues it idempotently."""
    async with qual_db_factory() as qual_db:
        await _seed_order(qual_db)
        fake = saga.FakeLNbitsCore()
        model = saga.InvoiceSaga(qual_db, fake)
        await model.begin(order_id="o1", now=T0)
        # Simulate the crash: the enqueue never happened.
        async with qual_db.connect() as conn:
            async with qual_db.transaction(conn) as t:
                await t.execute(
                    f"DELETE FROM {qual_db.table('outbox_events')}"
                    " WHERE id = 'obx-o1-payment-request'"
                )

        model2 = saga.InvoiceSaga(qual_db, fake)
        report = await model2.reconcile(now=T0 + 30)
        assert report["reenqueued_payment_requests"] == ["o1"]
        await _outbox_row(qual_db, "obx-o1-payment-request")
        # Idempotent: a rerun enqueues nothing more.
        report2 = await model2.reconcile(now=T0 + 40)
        assert report2["reenqueued_payment_requests"] == []
        rows = await qual_db.fetch_all(
            f"SELECT id FROM {qual_db.table('outbox_events')}"
            " WHERE aggregate_type = 'order_msg' AND aggregate_id = 'o1'"
        )
        assert len(rows) == 1


async def test_restart_between_settlement_and_callback(qual_db_factory):
    """Section 17 drill: core payment settled, invoice-paid callback LOST.

    Restart, then reconciliation queries the core payment status and confirms
    EXACTLY ONCE via the section 8.3 transaction: the order transitions to
    confirmed, every held reservation is consumed exactly once,
    stock_on_hand and stock_reserved are each decremented exactly once, the
    order_events row is written, and the type-3 confirmed + stock/state
    republication intents are enqueued. Delivering the lost callback a
    second time (and rerunning reconciliation) is a no-op.
    """
    async with qual_db_factory() as qual_db:
        await _seed_order(qual_db)
        fake = saga.FakeLNbitsCore()
        model = saga.InvoiceSaga(qual_db, fake)
        await model.begin(order_id="o1", now=T0)
        assert (await _order(qual_db))["state"] == "awaiting_payment"
        assert (await _product(qual_db))["stock_reserved"] == QTY

        # Settle in the fake core with callback delivery suppressed.
        delivered = await fake.settle(
            saga.core_external_id_for("o1"), deliver_callback=False
        )
        assert delivered is False
        assert fake.callbacks == []

        # Restart: reconciliation confirms exactly once (section 8.3).
        model2 = saga.InvoiceSaga(qual_db, fake)
        report = await model2.reconcile(now=T0 + 60)
        assert len(report["confirmed"]) == 1
        confirmed = report["confirmed"][0]
        assert confirmed["action"] == "confirmed"
        assert confirmed["consumed"] == 1  # one reservation row, QTY units
        assert confirmed["source"] == "reconciliation"

        order = await _order(qual_db)
        assert order["state"] == "confirmed"
        product = await _product(qual_db)
        assert product["stock_on_hand"] == ON_HAND - QTY  # decremented ONCE
        assert product["stock_reserved"] == 0  # decremented ONCE
        assert product["revision"] == 1  # republication revision bump
        reservations = await _reservations(qual_db)
        assert [r["state"] for r in reservations] == ["consumed"]
        payment = await _payment(qual_db)
        assert payment["status"] == "settled"
        assert payment["settled_at"] == T0 + 60

        # The order_events audit row was written by the confirm transaction
        # (all three transitions share the seeded clock, so compare as a set).
        events = await _order_events(qual_db, "o1")
        assert sorted((e["from_state"], e["to_state"]) for e in events) == sorted(
            [
                ("received", "invoice_pending"),
                ("invoice_pending", "awaiting_payment"),
                ("awaiting_payment", "confirmed"),
            ]
        )
        assert len(events) == 3

        # Type-3 confirmed + stock/state republication intents enqueued.
        await _outbox_row(qual_db, "obx-o1-status-confirmed")
        await _outbox_row(qual_db, "obx-o1-stock-p1")
        stock_intent = await _outbox_row(qual_db, "obx-o1-stock-p1")
        assert stock_intent["aggregate_type"] == "product"
        assert stock_intent["aggregate_id"] == "p1"
        assert stock_intent["aggregate_revision"] == 1

        # Delivering the lost callback a second time is a no-op.
        late = await model2.confirm_settlement(
            order_id="o1", source="callback", now=T0 + 70
        )
        assert late["action"] == "no-op"
        assert late["reason"] == "already-settled"
        # Rerunning reconciliation is a no-op: the payment is settled, so
        # the pending-payment pass has nothing to confirm.
        report2 = await model2.reconcile(now=T0 + 80)
        assert report2["confirmed"] == []
        # Exactly-once: nothing double-decremented.
        assert (await _product(qual_db))["stock_on_hand"] == ON_HAND - QTY
        assert (await _order(qual_db))["state"] == "confirmed"
        assert (await _payment(qual_db))["settled_at"] == T0 + 60


# --- settlement-side case (ii): pre-reservation crash resume -------------------


async def test_pre_reservation_crash_resume_is_idempotent(qual_db_factory):
    """Section 8.7 bullet 3: a committed received order (crash between
    intake and reservation) resumes section 8.2 idempotently; a double
    resume neither double-reserves nor double-invoices."""
    async with qual_db_factory() as qual_db:
        await _seed_order(qual_db)  # intake committed; crash before claim
        fake = saga.FakeLNbitsCore()
        model = saga.InvoiceSaga(qual_db, fake)

        # Restart: reconciliation resumes the committed received order.
        report = await model.reconcile(now=T0)
        assert len(report["resumed"]) == 1
        assert report["resumed"][0]["outcome"] == "attached"
        assert fake.create_calls["o1"] == 1
        assert (await _order(qual_db))["state"] == "awaiting_payment"
        assert (await _product(qual_db))["stock_reserved"] == QTY
        assert len(await _reservations(qual_db)) == 1

        # Double resume: the order is no longer received -> no action.
        report2 = await model.reconcile(now=T0 + 10)
        assert report2["resumed"] == []
        assert fake.create_calls["o1"] == 1  # no second invoice
        assert (await _product(qual_db))["stock_reserved"] == QTY  # no double

        # A forced re-begin loses the claim CAS (already begun).
        with pytest.raises(tx.SagaConflict):
            await model.begin(order_id="o1", now=T0 + 20)
        assert fake.create_calls["o1"] == 1
        assert (await _product(qual_db))["stock_reserved"] == QTY


# --- inbox checkpoint restarts ---------------------------------------------------


async def test_restart_admitted_not_validated(qual_db_factory):
    """Crash after admission, before the validated checkpoint: restart
    reprocesses received -> validated -> processed."""
    async with qual_db_factory() as qual_db:
        inbox = queues.InboxModel(qual_db)
        row = await inbox.admit(
            outer_event_id="wrap-1",
            rumor_id="rumor-1",
            merchant_id="merchant-1",
            author_hash="buyer-hash",
            now=T0,
        )
        assert row["processed_state"] == "received"
        assert row["duplicate"] is False

        # Restart: a fresh model resumes the admitted row.
        inbox2 = queues.InboxModel(qual_db)
        report = await inbox2.resume(now=T0 + 10)
        assert report["validated"] == [row["id"]]
        assert report["dispatched"] == [row["id"]]
        assert (await inbox2.row(row["id"]))["processed_state"] == "processed"

        # Quarantine retention is bounded: no plaintext reason survives
        # (quarantine is reachable from 'received', section 7.5).
        fresh = await inbox2.admit(
            outer_event_id="wrap-2",
            rumor_id="rumor-2",
            merchant_id="merchant-1",
            author_hash="buyer-hash",
            now=T0 + 15,
        )
        await inbox2.quarantine(fresh["id"], reason="x" * 500, now=T0 + 20)
        quarantined = await inbox2.row(fresh["id"])
        assert quarantined["processed_state"] == "quarantined"
        assert len(quarantined["reject_reason"]) <= 128


async def test_restart_validated_not_dispatched(qual_db_factory):
    """Crash after the committed validated checkpoint, before domain
    dispatch: restart resumes from validated without repeating admission."""
    async with qual_db_factory() as qual_db:
        inbox = queues.InboxModel(qual_db)
        row = await inbox.admit(
            outer_event_id="wrap-1",
            rumor_id="rumor-1",
            merchant_id="merchant-1",
            author_hash="buyer-hash",
            now=T0,
        )
        await inbox.validate(row["id"], now=T0 + 5)  # committed checkpoint
        assert (await inbox.row(row["id"]))["processed_state"] == "validated"

        # Restart: dispatch resumes from the durable checkpoint.
        inbox2 = queues.InboxModel(qual_db)
        report = await inbox2.resume(now=T0 + 10)
        assert report["validated"] == []
        assert report["dispatched"] == [row["id"]]
        assert (await inbox2.row(row["id"]))["processed_state"] == "processed"

        # Duplicate admission of the same outer event id: successful no-op.
        dup = await inbox2.admit(
            outer_event_id="wrap-1",
            rumor_id="rumor-1",
            merchant_id="merchant-1",
            author_hash="buyer-hash",
            now=T0 + 15,
        )
        assert dup["duplicate"] is True
        assert dup["id"] == row["id"]
        rows = await qual_db.fetch_all(
            f"SELECT * FROM {qual_db.table('inbox_events')}"
        )
        assert len(rows) == 1


async def test_merchant_sender_copy_recovered_without_dispatch(qual_db_factory):
    """Section 8.5 step 7: the merchant's own sender copy (a duplicate gift
    wrap of OUR outbound rumor) is recovered as a sender copy WITHOUT
    dispatching a domain command."""
    async with qual_db_factory() as qual_db:
        outbox = queues.OutboxModel(qual_db)
        # Our outbound order_msg intent carries the canonical rumor id.
        await outbox.enqueue(
            intent_id="obx-out-1",
            merchant_id="merchant-1",
            aggregate_type="order_msg",
            aggregate_id="o1",
            event_kind=3,
            payload={"rumor_id": "rumor-ours"},
            targets=_targets(("recipient", "wss://buyer-relay")),
            now=T0,
        )
        inbox = queues.InboxModel(qual_db)
        # The merchant's sender copy wraps the same rumor id.
        row = await inbox.admit(
            outer_event_id="wrap-sender",
            rumor_id="rumor-ours",
            merchant_id="merchant-1",
            author_hash="merchant-hash",
            now=T0,
        )
        await inbox.validate(row["id"], now=T0 + 5)
        result = await inbox.dispatch(row["id"], now=T0 + 6)
        assert result["action"] == "sender-copy-recovered"
        assert inbox.dispatched == []  # no domain command dispatched
        assert (await inbox.row(row["id"]))["processed_state"] == "processed"

        # A buyer rumor with a different id dispatches normally.
        buyer_row = await inbox.admit(
            outer_event_id="wrap-buyer",
            rumor_id="rumor-buyer",
            merchant_id="merchant-1",
            author_hash="buyer-hash",
            now=T0 + 10,
        )
        await inbox.validate(buyer_row["id"], now=T0 + 11)
        result = await inbox.dispatch(buyer_row["id"], now=T0 + 12)
        assert result["action"] == "dispatched"
        assert inbox.dispatched == [buyer_row["id"]]


# --- outbox checkpoint restarts ---------------------------------------------------


async def test_restart_claimed_not_published(qual_db_factory):
    """Crash after claim, before publish: the stale claim requeues ONLY via
    claim-token CAS; the stale worker's later leased write fails."""
    async with qual_db_factory() as qual_db:
        outbox = queues.OutboxModel(qual_db)
        await outbox.enqueue(
            intent_id="obx-1",
            merchant_id="merchant-1",
            aggregate_type="order_msg",
            aggregate_id="o1",
            event_kind=3,
            payload={"rumor_id": "rumor-1"},
            targets=_targets(
                ("recipient", "wss://r1"),
                ("sender", "wss://r2"),
            ),
            now=T0,
        )
        claimed = await outbox.claim(worker="w1", now=T0, lease_seconds=60)
        assert len(claimed) == 1
        assert claimed[0]["state"] == "claimed"
        assert claimed[0]["claim_token"] == 1
        assert claimed[0]["claimed_by"] == "w1"

        # Crash. Restart with the lease EXPIRED: requeue via CAS only.
        requeued = await outbox.requeue_stale(now=T0 + 61)
        assert requeued == [{"id": "obx-1", "state": "pending"}]
        row = await _outbox_row(qual_db, "obx-1")
        assert row["state"] == "pending"
        assert row["claim_token"] == 2  # incremented: the old claim is fenced
        assert row["claimed_by"] is None
        await _assert_no_dangling_queue_rows(qual_db, now=T0 + 61)

        # The STALE worker (still holding claim_token 1) cannot commit its
        # outcome-policy write: the claim-token CAS fails.
        with pytest.raises(tx.StaleClaim):
            await outbox.record_outcomes(
                claimed[0],
                [
                    {
                        "delivery_copy": "recipient",
                        "relay_url": "wss://r1",
                        "event_id": "stale-outer-1",
                        "result": "accepted",
                    }
                ],
                now=T0 + 70,
            )
        # The state write was fenced — the row is still pending, token 2.
        row = await _outbox_row(qual_db, "obx-1")
        assert row["state"] == "pending"
        assert row["claim_token"] == 2
        # The stale worker's durable positive evidence IS retained (it is a
        # true relay OK — append-only, honored by reconstruction): the
        # accepted target will never be resent.
        pubs = await qual_db.fetch_all(
            f"SELECT * FROM {qual_db.table('relay_publications')}"
            " WHERE outbox_event_id = 'obx-1'"
        )
        assert [p["relay_url"] for p in pubs] == ["wss://r1"]
        assert pubs[0]["result"] == "accepted"

        # Retry after requeue: only the MISSING target is attempted.
        claimed2 = await outbox.claim(worker="w2", now=T0 + 100, lease_seconds=60)
        assert len(claimed2) == 1
        attempt = await outbox.publish_attempt(claimed2[0], now=T0 + 100)
        assert [(t["delivery_copy"], t["relay_url"]) for t in attempt] == [
            ("sender", "wss://r2")
        ]
        await outbox.record_outcomes(
            claimed2[0],
            [
                {**target, "result": "accepted"} for target in attempt
            ],
            now=T0 + 100,
        )
        row = await _outbox_row(qual_db, "obx-1")
        assert row["state"] == "published"
        await _assert_no_dangling_queue_rows(qual_db, now=T0 + 110)


async def test_restart_partially_published_retries_only_missing(qual_db_factory):
    """Crash mid-publication with durable accepted targets: restart requeues
    to partially_published and retries ONLY the missing targets; the accepted
    target is never resent; the NIP-17 quorum closes only after both a
    recipient-copy and a sender-copy positive OK."""
    async with qual_db_factory() as qual_db:
        outbox = queues.OutboxModel(qual_db)
        await outbox.enqueue(
            intent_id="obx-1",
            merchant_id="merchant-1",
            aggregate_type="order_msg",
            aggregate_id="o1",
            event_kind=3,
            payload={"rumor_id": "rumor-1"},
            targets=_targets(
                ("recipient", "wss://r1"),
                ("recipient", "wss://r2"),
                ("sender", "wss://r3"),
            ),
            now=T0,
        )
        claimed = await outbox.claim(worker="w1", now=T0, lease_seconds=60)
        attempt = await outbox.publish_attempt(claimed[0], now=T0)
        assert len(attempt) == 3
        by_relay = {a["relay_url"]: a for a in attempt}
        # Relay OKs land as DURABLE evidence (section 8.6 step 6), then the
        # worker CRASHES before the outcome-policy write: r1 accepted, r2
        # and r3 timed out, the row still claimed/publishing.
        await outbox.record_publications(
            claimed[0],
            [
                {**by_relay["wss://r1"], "result": "accepted"},
                {**by_relay["wss://r2"], "result": "timeout"},
                {**by_relay["wss://r3"], "result": "timeout"},
            ],
            now=T0,
        )
        row = await _outbox_row(qual_db, "obx-1")
        assert row["state"] == "publishing"  # crash: no outcome write

        # Restart with the lease expired: the stale claim requeues via
        # claim-token CAS RECONSTRUCTED from the durable positive evidence —
        # partially_published, not pending.
        requeued = await outbox.requeue_stale(now=T0 + 61)
        assert requeued == [{"id": "obx-1", "state": "partially_published"}]
        row = await _outbox_row(qual_db, "obx-1")
        assert row["attempts"] == 0  # the crashed attempt never completed
        accepted = await outbox.accepted_targets("obx-1")
        assert accepted == {("recipient", "wss://r1")}

        # The retry attempts ONLY the missing targets.
        claimed2 = await outbox.claim(worker="w2", now=T0 + 100, lease_seconds=60)
        attempt2 = await outbox.publish_attempt(claimed2[0], now=T0 + 100)
        assert [(t["delivery_copy"], t["relay_url"]) for t in attempt2] == [
            ("recipient", "wss://r2"),
            ("sender", "wss://r3"),
        ]

        # r2 rejects, r3 accepts: recipient r1 + sender r3 -> quorum met.
        by_relay2 = {a["relay_url"]: a for a in attempt2}
        outcome2 = await outbox.record_outcomes(
            claimed2[0],
            [
                {**by_relay2["wss://r2"], "result": "rejected"},
                {**by_relay2["wss://r3"], "result": "accepted"},
            ],
            now=T0 + 100,
        )
        assert outcome2["state"] == "published"

        # Positive-ACK evidence survived the restart: r1 attempted ONCE.
        pubs = await qual_db.fetch_all(
            f"SELECT * FROM {qual_db.table('relay_publications')}"
            " WHERE outbox_event_id = 'obx-1'"
        )
        assert len(pubs) == 5  # 3 (crashed attempt) + 2 (missing only)
        r1_pubs = [p for p in pubs if p["relay_url"] == "wss://r1"]
        assert len(r1_pubs) == 1
        assert r1_pubs[0]["result"] == "accepted"
        await _assert_no_dangling_queue_rows(qual_db, now=T0 + 110)


async def test_lease_expired_mid_claim_requeues_and_reclaims(qual_db_factory):
    """Lease expiry mid-claim: the row requeues via CAS and is claimable
    again by a live worker."""
    async with qual_db_factory() as qual_db:
        outbox = queues.OutboxModel(qual_db)
        await outbox.enqueue(
            intent_id="obx-1",
            merchant_id="merchant-1",
            aggregate_type="product",
            aggregate_id="p1",
            event_kind=30402,
            targets=_targets(("public", "wss://pub")),
            now=T0,
        )
        claimed = await outbox.claim(worker="w1", now=T0, lease_seconds=30)
        assert len(claimed) == 1
        # Lease expires; requeue; claim again.
        requeued = await outbox.requeue_stale(now=T0 + 31)
        assert requeued == [{"id": "obx-1", "state": "pending"}]
        claimed2 = await outbox.claim(worker="w2", now=T0 + 40, lease_seconds=30)
        assert len(claimed2) == 1
        assert claimed2[0]["claimed_by"] == "w2"
        # claim 0 -> claim 1, requeue 2, re-claim 3: the token only climbs.
        assert claimed2[0]["claim_token"] == 3
        await _assert_no_dangling_queue_rows(qual_db, now=T0 + 45)


async def test_zero_positive_oks_backoff_then_failed(qual_db_factory):
    """Zero positive OKs: back to pending with backoff min(2^attempts*5s,
    30min); the row is not claimable before next_attempt_at; exhausted
    attempts enter failed (never sent)."""
    async with qual_db_factory() as qual_db:
        outbox = queues.OutboxModel(qual_db)
        await outbox.enqueue(
            intent_id="obx-1",
            merchant_id="merchant-1",
            aggregate_type="product",
            aggregate_id="p1",
            event_kind=30402,
            targets=_targets(("public", "wss://pub")),
            now=T0,
        )
        claimed = await outbox.claim(worker="w1", now=T0, lease_seconds=60)
        attempt = await outbox.publish_attempt(claimed[0], now=T0)
        outcome = await outbox.record_outcomes(
            claimed[0], [{**attempt[0], "result": "timeout"}], now=T0
        )
        assert outcome["state"] == "pending"
        assert outcome["attempts"] == 1
        row = await _outbox_row(qual_db, "obx-1")
        assert row["next_attempt_at"] == T0 + 10  # min(2^1 * 5s, 30min)

        # Not claimable before the backoff elapses.
        early = await outbox.claim(worker="w1", now=T0 + 5, lease_seconds=60)
        assert early == []
        # Claimable after.
        claimed2 = await outbox.claim(worker="w1", now=T0 + 10, lease_seconds=60)
        assert len(claimed2) == 1
        attempt2 = await outbox.publish_attempt(claimed2[0], now=T0 + 10)
        outcome2 = await outbox.record_outcomes(
            claimed2[0], [{**attempt2[0], "result": "rejected"}], now=T0 + 10
        )
        assert outcome2["state"] == "pending"
        assert outcome2["attempts"] == 2
        row = await _outbox_row(qual_db, "obx-1")
        assert row["next_attempt_at"] == T0 + 10 + 20  # min(2^2 * 5s, 30min)

        # Exhausted attempts: seed attempts to the bound, one more failure
        # enters failed (section 8.6: after MAX_ATTEMPTS, mark failed).
        async with qual_db.connect() as conn:
            async with qual_db.transaction(conn) as t:
                await t.execute(
                    f"UPDATE {qual_db.table('outbox_events')}"
                    " SET attempts = :n, state = 'pending',"
                    " next_attempt_at = 0 WHERE id = 'obx-1'",
                    {"n": outbox.MAX_ATTEMPTS - 1},
                )
        claimed3 = await outbox.claim(worker="w1", now=T0 + 100, lease_seconds=60)
        assert len(claimed3) == 1
        attempt3 = await outbox.publish_attempt(claimed3[0], now=T0 + 100)
        outcome3 = await outbox.record_outcomes(
            claimed3[0], [{**attempt3[0], "result": "timeout"}], now=T0 + 100
        )
        assert outcome3["state"] == "failed"
        # Never sent, never published.
        assert (await _outbox_row(qual_db, "obx-1"))["state"] == "failed"
        # The claim gate also refuses an exhausted row.
        assert await outbox.claim(worker="w1", now=T0 + 200, lease_seconds=60) == []


async def test_order_msg_keeps_stable_rumor_id_across_retries(qual_db_factory):
    """Retries reuse the SAME canonical rumor id while outer event ids
    change (fresh seals/wrappers per attempt, section 8.6 step 3)."""
    async with qual_db_factory() as qual_db:
        outbox = queues.OutboxModel(qual_db)
        await outbox.enqueue(
            intent_id="obx-1",
            merchant_id="merchant-1",
            aggregate_type="order_msg",
            aggregate_id="o1",
            event_kind=3,
            payload={"rumor_id": "rumor-stable"},
            targets=_targets(("recipient", "wss://r1"), ("sender", "wss://r2")),
            now=T0,
        )
        claimed = await outbox.claim(worker="w1", now=T0, lease_seconds=60)
        attempt1 = await outbox.publish_attempt(claimed[0], now=T0)
        outer_ids_1 = [a["event_id"] for a in attempt1]
        await outbox.record_outcomes(
            claimed[0],
            [{**a, "result": "timeout"} for a in attempt1],
            now=T0,
        )
        assert (await _outbox_row(qual_db, "obx-1"))["state"] == "pending"

        # Retry: fresh outer event ids, same canonical rumor id.
        claimed2 = await outbox.claim(worker="w1", now=T0 + 10, lease_seconds=60)
        attempt2 = await outbox.publish_attempt(claimed2[0], now=T0 + 10)
        outer_ids_2 = [a["event_id"] for a in attempt2]
        assert set(outer_ids_1).isdisjoint(set(outer_ids_2))

        import json as _json

        payload = _json.loads((await _outbox_row(qual_db, "obx-1"))["payload_json"])
        assert payload["rumor_id"] == "rumor-stable"
        assert payload["current_outer_event_ids"] == outer_ids_2

        # The durable publication rows carry the per-attempt event ids.
        await outbox.record_outcomes(
            claimed2[0],
            [{**a, "result": "accepted"} for a in attempt2],
            now=T0 + 10,
        )
        pubs = await qual_db.fetch_all(
            f"SELECT * FROM {qual_db.table('relay_publications')}"
            " WHERE outbox_event_id = 'obx-1'"
        )
        assert sorted(p["event_id"] for p in pubs) == sorted(
            outer_ids_1 + outer_ids_2
        )
        assert (await _outbox_row(qual_db, "obx-1"))["state"] == "published"


async def test_claim_respects_dependencies_and_supersede(qual_db_factory):
    """Section 8.6 step 2: claim only rows whose dependencies are
    published; a newer revision supersedes a public row, never an
    order_msg row."""
    async with qual_db_factory() as qual_db:
        outbox = queues.OutboxModel(qual_db)
        await outbox.enqueue(
            intent_id="obx-a",
            merchant_id="merchant-1",
            aggregate_type="product",
            aggregate_id="p1",
            aggregate_revision=1,
            event_kind=30402,
            targets=_targets(("public", "wss://pub")),
            now=T0,
        )
        await outbox.enqueue(
            intent_id="obx-b",
            merchant_id="merchant-1",
            aggregate_type="product",
            aggregate_id="p1",
            aggregate_revision=2,
            event_kind=30402,
            targets=_targets(("public", "wss://pub")),
            depends_on=["obx-a"],
            now=T0,
        )

        # B is not claimable while A is unpublished.
        claimed = await outbox.claim(worker="w1", now=T0, lease_seconds=60)
        assert [row["id"] for row in claimed] == ["obx-a"]
        attempt = await outbox.publish_attempt(claimed[0], now=T0)
        await outbox.record_outcomes(
            claimed[0], [{**a, "result": "accepted"} for a in attempt], now=T0
        )
        assert (await _outbox_row(qual_db, "obx-a"))["state"] == "published"

        # Now B is claimable — but its worker CRASHES mid-claim (stays
        # claimed), which is exactly the state a newer revision supersedes.
        claimed_b = await outbox.claim(worker="w1", now=T0 + 10, lease_seconds=60)
        assert [row["id"] for row in claimed_b] == ["obx-b"]
        assert (await _outbox_row(qual_db, "obx-b"))["state"] == "claimed"

        # A newer revision (3) supersedes the older non-published rows;
        # order_msg rows are never superseded; the already-PUBLISHED row
        # (obx-a) is terminal and never superseded (section 7.4).
        await outbox.enqueue(
            intent_id="obx-c",
            merchant_id="merchant-1",
            aggregate_type="product",
            aggregate_id="p1",
            aggregate_revision=3,
            event_kind=30402,
            targets=_targets(("public", "wss://pub")),
            now=T0 + 20,
        )
        await outbox.enqueue(
            intent_id="obx-msg",
            merchant_id="merchant-1",
            aggregate_type="order_msg",
            aggregate_id="o1",
            aggregate_revision=1,
            event_kind=3,
            payload={"rumor_id": "rumor-x"},
            targets=_targets(("recipient", "wss://r1")),
            now=T0 + 20,
        )
        superseded = await outbox.supersede_obsolete(now=T0 + 20)
        # obx-b (rev 2, claimed) is superseded by rev 3. obx-a (rev 1) is
        # published — terminal, never superseded. obx-msg is an order_msg.
        assert superseded == ["obx-b"]
        assert (await _outbox_row(qual_db, "obx-a"))["state"] == "published"
        assert (await _outbox_row(qual_db, "obx-msg"))["state"] == "pending"


# --- relay cursor restarts --------------------------------------------------------


async def test_relay_cursors_advance_only_after_eose(qual_db_factory):
    """Session-time cursors: a crash before EOSE leaves the prior cursor
    intact; completion after EOSE (with pre-EOSE events durably admitted)
    advances it; it never regresses."""
    async with qual_db_factory() as qual_db:
        inbox = queues.InboxModel(qual_db)
        cursors = queues.CursorModel(qual_db)
        await cursors.start_session(relay_url="wss://r1", now=1000)
        # Events delivered before EOSE are durably admitted.
        admitted = [
            await inbox.admit(
                outer_event_id=f"wrap-{i}",
                rumor_id=f"rumor-{i}",
                merchant_id="merchant-1",
                author_hash="buyer-hash",
                now=1000 + i,
            )
            for i in range(2)
        ]
        assert all(row["processed_state"] == "received" for row in admitted)

        # CRASH before EOSE: the session is lost, the cursor is NOT written.
        cursors2 = queues.CursorModel(qual_db)
        assert await cursors2.cursor(relay_url="wss://r1") is None

        # New session completes after EOSE: the cursor advances (to the
        # SESSION start time, never an event time).
        s2 = await cursors2.start_session(relay_url="wss://r1", now=2000)
        await cursors2.complete_session(s2, now=2500)
        cursor = await cursors2.cursor(relay_url="wss://r1")
        assert cursor["last_completed_session_start"] == 2000
        assert cursor["eose_session_id"] == s2

        # A later crash before EOSE leaves the prior cursor intact.
        cursors3 = queues.CursorModel(qual_db)
        await cursors3.start_session(relay_url="wss://r1", now=3000)
        cursor = await cursors3.cursor(relay_url="wss://r1")
        assert cursor["last_completed_session_start"] == 2000

        # Completion advances monotonically; an older session never
        # regresses the cursor.
        s4 = await cursors3.start_session(relay_url="wss://r1", now=4000)
        await cursors3.complete_session(s4, now=4500)
        cursor = await cursors3.cursor(relay_url="wss://r1")
        assert cursor["last_completed_session_start"] == 4000
