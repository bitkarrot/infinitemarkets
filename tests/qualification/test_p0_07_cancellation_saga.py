"""P0-07: cancellation/invoice saga race evidence (QUAL-07).

Executable section 8.2/8.3/8.4/8.7 model runs against the controllable fake
LNbits payment boundary. For each cancellation state in received,
invoice_pending, awaiting_payment and each invoice-creation outcome in
success, definitive rejection, timeout/unknown: pause the saga at the
documented boundary, cancel, then deliver the outcome and restart the model.

Asserts (never trusting the happy path):

- stock releases exactly once (double cancellation does not double-release);
- core_external_id correlation survives cancellation;
- a cancelled order never reopens and never receives a delivered BOLT11 or
  payment request;
- no second invoice is ever created (the fake counts create_invoice calls
  per order);
- a settlement after cancellation sets payment_exception and keeps the order
  cancelled;
- reconciliation of creation_unknown attaches exactly one discovered invoice
  by external id;
- the multi-match critical exception path: two core payments with one
  external id quarantines the order, nothing auto-delivered.
"""

from __future__ import annotations

import asyncio

import pytest

from harness import saga, tx

pytestmark = [pytest.mark.db, pytest.mark.fast]

ON_HAND = 5
QTY = 2
TOTAL_SAT = 1000
T0 = 2_000_000_000


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


async def _product(qual_db, product_id: str = "p1") -> dict:
    rows = await qual_db.fetch_all(
        f"SELECT stock_on_hand, stock_reserved FROM {qual_db.table('products')}"
        " WHERE id = :id",
        {"id": product_id},
    )
    assert rows
    return rows[0]


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


async def _reservations(qual_db, order_id: str = "o1") -> list[dict]:
    return await qual_db.fetch_all(
        f"SELECT * FROM {qual_db.table('inventory_reservations')}"
        " WHERE order_id = :id",
        {"id": order_id},
    )


async def _intent_ids(qual_db, order_id: str = "o1") -> list[str]:
    rows = await qual_db.fetch_all(
        f"SELECT id FROM {qual_db.table('outbox_events')}"
        " WHERE aggregate_type = 'order_msg' AND aggregate_id = :id",
        {"id": order_id},
    )
    return sorted(row["id"] for row in rows)


def _wire_callback(fake: saga.FakeLNbitsCore, model: saga.InvoiceSaga) -> None:
    """Route the fake's invoice-paid callback into the section 8.3 path."""

    async def on_invoice_paid(record: dict) -> None:
        order_id = record["external_id"].split(":", 1)[1]
        await model.confirm_settlement(order_id=order_id, source="callback")

    fake.on_invoice_paid(on_invoice_paid)


# --- cancellation from received: the claim CAS must lose ----------------------


@pytest.mark.parametrize("outcome", ["success", "rejected", "unknown"])
async def test_cancel_from_received_never_creates_an_invoice(
    qual_db_factory, outcome
):
    """Cancellation wins before the saga begins: no stock, no invoice, ever."""
    async with qual_db_factory() as qual_db:
        await _seed_order(qual_db)
        fake = saga.FakeLNbitsCore()
        fake.outcomes["o1"] = outcome
        model = saga.InvoiceSaga(qual_db, fake)

        result = await model.cancel(order_id="o1")
        assert result["action"] == "cancelled"
        assert result["released"] == 0  # nothing was held yet

        # The section 8.2 step-1 CAS loses; the entire claim rolls back.
        with pytest.raises(tx.SagaConflict):
            await model.begin(order_id="o1", now=T0)

        assert fake.create_calls["o1"] == 0  # never reached the boundary
        assert await _reservations(qual_db) == []
        order = await _order(qual_db)
        assert order["state"] == "cancelled"
        product = await _product(qual_db)
        assert product["stock_reserved"] == 0
        assert product["stock_on_hand"] == ON_HAND
        # No payment projection survived the rolled-back claim.
        rows = await qual_db.fetch_all(
            f"SELECT * FROM {qual_db.table('payments')}"
        )
        assert rows == []

        # Double cancellation: no-op, releases nothing.
        second = await model.cancel(order_id="o1")
        assert second["action"] == "no-op-already-cancelled"
        assert (await _product(qual_db))["stock_reserved"] == 0


# --- cancellation from invoice_pending: the race, per outcome ------------------


@pytest.mark.parametrize("outcome", ["success", "rejected", "unknown"])
async def test_cancel_during_inflight_invoice_creation(qual_db_factory, outcome):
    """Cancel while invoice creation is genuinely in flight, then deliver.

    The saga is paused inside the fake's create_invoice (after the step-1
    claim, before LNbits persists anything): the order is invoice_pending
    with a held reservation and a creating projection.
    """
    async with qual_db_factory() as qual_db:
        await _seed_order(qual_db)
        fake = saga.FakeLNbitsCore()
        fake.outcomes["o1"] = outcome
        fake.pause_enabled = True
        model = saga.InvoiceSaga(qual_db, fake)
        _wire_callback(fake, model)

        task = asyncio.create_task(model.begin(order_id="o1", now=T0))
        await fake.in_flight.wait()  # paused mid create_invoice

        # Cancellation wins the race while creation is in flight.
        cancel_result = await model.cancel(order_id="o1")
        assert cancel_result["action"] == "cancelled"
        assert cancel_result["released"] == QTY
        assert (await _product(qual_db))["stock_reserved"] == 0

        fake.pause_gate.set()  # deliver the outcome
        result = await task
        assert fake.create_calls["o1"] == 1  # exactly one invoice attempt

        order = await _order(qual_db)
        assert order["state"] == "cancelled"  # never reopens

        # No BOLT11 delivery and no payment request for the cancelled order.
        assert all(entry["order_id"] != "o1" for entry in model.deliveries)
        assert await _intent_ids(qual_db) == ["obx-o1-status-cancelled"]

        payment = await _payment(qual_db)
        # core_external_id correlation survives cancellation (section 24).
        assert payment["core_external_id"] == "infinitemarkets:o1"

        if outcome == "success":
            assert result["outcome"] == "attached-cancelled"
            assert result["delivered"] is False
            # The projection is retained for late-settlement detection.
            assert payment["status"] == "pending"
            assert payment["payment_hash"]
            assert payment["bolt11_enc"]
            # The fake core still holds the invoice; a settlement after
            # cancellation sets payment_exception and keeps the order
            # cancelled — no state change, no consumption.
            settlement = await model.confirm_settlement(
                order_id="o1", source="callback", now=T0 + 60
            )
            assert settlement["action"] == "exception"
            assert settlement["order_state"] == "cancelled"
            order = await _order(qual_db)
            assert order["state"] == "cancelled"
            assert bool(order["payment_exception"])
            assert order["payment_exception_reason"]
            payment = await _payment(qual_db)
            assert payment["status"] == "settled"
            # Reservations were released (not consumed); stock untouched.
            reservations = await _reservations(qual_db)
            assert [r["state"] for r in reservations] == ["released"]
            product = await _product(qual_db)
            assert product["stock_on_hand"] == ON_HAND
            assert product["stock_reserved"] == 0
        elif outcome == "rejected":
            assert result["outcome"] == "rejected"
            # Definitive rejection: projection failed; the cancelled order
            # stays cancelled (only invoice_pending orders are rejected).
            assert payment["status"] == "failed"
            assert order["state"] == "cancelled"
        else:  # unknown
            assert result["outcome"] == "creation_unknown"
            assert payment["status"] == "creation_unknown"
            assert bool(order["payment_exception"])
            # Timeout/unknown never creates a second invoice; recovery is
            # reconciliation by external id only.
            assert fake.create_calls["o1"] == 1

        # A second cancellation is a no-op that releases nothing again.
        second = await model.cancel(order_id="o1")
        assert second["action"] == "no-op-already-cancelled"
        assert (await _product(qual_db))["stock_reserved"] == 0
        assert (await _order(qual_db))["state"] == "cancelled"


# --- cancellation from awaiting_payment: late settlement (section 8.4) ----------


async def test_cancel_from_awaiting_payment_then_late_settlement(qual_db_factory):
    """Settled-after-cancel: exception path, exactly-once, callback loss proof."""
    async with qual_db_factory() as qual_db:
        await _seed_order(qual_db)
        fake = saga.FakeLNbitsCore()
        model = saga.InvoiceSaga(qual_db, fake)
        _wire_callback(fake, model)

        result = await model.begin(order_id="o1", now=T0)
        assert result["outcome"] == "attached"
        assert result["delivered"] is True
        assert (await _order(qual_db))["state"] == "awaiting_payment"
        assert (await _product(qual_db))["stock_reserved"] == QTY
        assert await _intent_ids(qual_db) == ["obx-o1-payment-request"]
        assert [d["order_id"] for d in model.deliveries] == ["o1"]

        # Cancel from awaiting_payment: release exactly once.
        cancel_result = await model.cancel(order_id="o1")
        assert cancel_result["released"] == QTY
        assert (await _product(qual_db))["stock_reserved"] == 0
        assert [r["state"] for r in await _reservations(qual_db)] == ["released"]

        # Section 17 drill: settlement fired in the fake core with the
        # invoice-paid callback SUPPRESSED (kill between settlement and
        # callback).
        delivered = await fake.settle("infinitemarkets:o1", deliver_callback=False)
        assert delivered is False
        assert fake.callbacks == []

        # Restart + reconciliation queries the core payment status and
        # routes settled to the section 8.3 transaction.
        model2 = saga.InvoiceSaga(qual_db, fake)
        report = await model2.reconcile(now=T0 + 120)
        assert len(report["confirmed"]) == 1
        confirmed = report["confirmed"][0]
        # The order was cancelled pre-payment: the exception branch.
        assert confirmed["action"] == "exception"
        assert confirmed["order_state"] == "cancelled"
        order = await _order(qual_db)
        assert order["state"] == "cancelled"  # a late payment never reopens
        assert bool(order["payment_exception"])
        payment = await _payment(qual_db)
        assert payment["status"] == "settled"
        # Nothing consumed: released reservations, full stock_on_hand.
        assert [r["state"] for r in await _reservations(qual_db)] == ["released"]
        assert (await _product(qual_db))["stock_on_hand"] == ON_HAND

        # Delivering the lost callback afterwards is a no-op (already
        # settled never confirms twice), and rerunning reconciliation too.
        late = await model2.confirm_settlement(
            order_id="o1", source="callback", now=T0 + 130
        )
        assert late["action"] == "no-op"
        assert late["reason"] == "already-settled"
        report2 = await model2.reconcile(now=T0 + 140)
        assert report2["confirmed"] == []
        assert (await _order(qual_db))["state"] == "cancelled"
        assert (await _product(qual_db))["stock_on_hand"] == ON_HAND


# --- creation_unknown reconciliation: discovery by external id ------------------


async def test_creation_unknown_reconciliation_attaches_exactly_one(
    qual_db_factory,
):
    """Unknown outcome that DID persist in core: reconciliation discovers and
    attaches exactly one invoice by exact external id (section 8.2 step 5)."""
    async with qual_db_factory() as qual_db:
        await _seed_order(qual_db)
        fake = saga.FakeLNbitsCore()
        fake.outcomes["o1"] = "unknown"
        fake.unknown_persisted.add("o1")  # core persisted before the timeout
        model = saga.InvoiceSaga(qual_db, fake)

        result = await model.begin(order_id="o1", now=T0)
        assert result["outcome"] == "creation_unknown"
        assert (await _payment(qual_db))["status"] == "creation_unknown"
        assert bool((await _order(qual_db))["payment_exception"])
        assert fake.create_calls["o1"] == 1

        # Restart: a fresh model reconciles by exact core_external_id.
        model2 = saga.InvoiceSaga(qual_db, fake)
        report = await model2.reconcile(now=T0 + 30)
        assert len(report["attached"]) == 1
        attached = report["attached"][0]
        assert attached["order_id"] == "o1"
        assert attached["outcome"] == "attached"  # order was invoice_pending
        assert attached["delivered"] is True

        payment = await _payment(qual_db)
        assert payment["status"] == "pending"
        assert payment["payment_hash"]
        assert (await _order(qual_db))["state"] == "awaiting_payment"
        # No second invoice was created.
        assert fake.create_calls["o1"] == 1
        # Reservations aligned to the decoded invoice expiry and still held.
        reservations = await _reservations(qual_db)
        assert [r["state"] for r in reservations] == ["held"]
        core = fake.query_by_external_id("infinitemarkets:o1")
        assert reservations[0]["expires_at"] == core[0].expiry_at

        # Re-running reconciliation changes nothing (idempotent attach
        # path: the projection is no longer creating/creation_unknown).
        report2 = await model2.reconcile(now=T0 + 40)
        assert report2["attached"] == []


async def test_zero_matches_after_window_fails_projection_only_for_invoice_pending(
    qual_db_factory,
):
    """Zero core matches: only after the five-minute uncertainty window may
    the projection be marked failed — and only an invoice_pending order is
    released/rejected; a cancelled order stays cancelled."""
    async with qual_db_factory() as qual_db:
        await _seed_order(qual_db)
        fake = saga.FakeLNbitsCore()
        fake.outcomes["o1"] = "unknown"  # nothing persisted in core
        model = saga.InvoiceSaga(qual_db, fake)
        await model.begin(order_id="o1", now=T0)

        # Within the uncertainty window: no premature failure.
        report = await model.reconcile(now=T0 + 100)
        assert report["failed_projections"] == []
        assert (await _payment(qual_db))["status"] == "creation_unknown"

        # After the window: projection failed, invoice_pending order
        # rejected, stock released.
        report = await model.reconcile(now=T0 + 400)
        assert len(report["failed_projections"]) == 1
        assert (await _payment(qual_db))["status"] == "failed"
        assert (await _order(qual_db))["state"] == "rejected"
        assert (await _product(qual_db))["stock_reserved"] == 0

        # The cancelled variant stays cancelled (section 8.2 step 5).
        await _seed_order(qual_db, order_id="o2", product_id="p2")
        fake.outcomes["o2"] = "unknown"
        model2 = saga.InvoiceSaga(qual_db, fake)
        await model2.begin(order_id="o2", now=T0)
        await model2.cancel(order_id="o2")
        report = await model2.reconcile(now=T0 + 400)
        assert len(report["failed_projections"]) == 1
        assert (await _order(qual_db, "o2"))["state"] == "cancelled"
        assert (await _payment(qual_db, "o2"))["status"] == "failed"


# --- multi-match critical exception ----------------------------------------------


async def test_multiple_core_payments_with_one_external_id_quarantines(
    qual_db_factory,
):
    """Two core payments with one external id: critical manual exception;
    the order is quarantined (payment_exception) and NOTHING is delivered
    automatically (section 8.2 step 5 / section 8.7)."""
    async with qual_db_factory() as qual_db:
        await _seed_order(qual_db)
        fake = saga.FakeLNbitsCore()
        fake.outcomes["o1"] = "unknown"
        fake.unknown_persisted.add("o1")
        model = saga.InvoiceSaga(qual_db, fake)
        await model.begin(order_id="o1", now=T0)  # creation_unknown
        assert (await _payment(qual_db))["status"] == "creation_unknown"

        # A second core payment appears with the SAME external id.
        fake.add_extra_core_payment("infinitemarkets:o1", order_id="o1")

        report = await model.reconcile(now=T0 + 30)
        assert len(report["critical"]) == 1
        critical = report["critical"][0]
        assert critical["order_id"] == "o1"
        assert critical["matches"] == 2

        # Nothing attached, nothing delivered, no state change.
        assert report["attached"] == []
        payment = await _payment(qual_db)
        assert payment["status"] == "creation_unknown"
        assert not payment["payment_hash"]
        order = await _order(qual_db)
        assert order["state"] == "invoice_pending"  # unchanged
        assert bool(order["payment_exception"])
        assert order["payment_exception_reason"] == "multiple-core-payments"
        assert model.deliveries == []
        assert fake.create_calls["o1"] == 1  # no second invoice
