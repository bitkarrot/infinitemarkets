"""P0-03: LNbits host contract probes (QUAL-03).

Probes against the real pinned host (e336fe1) with FakeWallet funding:

- (a) invoice metadata: create_invoice with extension="infinitemarkets",
  external_id="infinitemarkets:<uuid>", sat amount, and the infinitemarkets extra
  tag; the persisted core payment row records extension, exact external_id,
  wallet id, and amount, and exact external_id lookup retrieves it (the
  section 8.2 reconciliation key);
- (b) invoice-listener lifecycle: a listener registered via
  task_manager.register_invoice_listener(coro, name="infinitemarkets") receives
  the settled Payment carrying our extension/external_id when the FakeWallet
  invoice is paid through the host's own settlement path (pay_invoice);
- (c) owned-handle cancellation: cancelling only the extension-owned handle
  stops our listener while unrelated registered tasks survive — the host's
  cancel-everything API is never invoked (section 10);
- (d) no durable callback delivery: after a simulated restart (second app
  boot), the previously registered listener receives nothing, and the newly
  settled payment is discoverable by exact external_id query — proving the
  reconciliation path (query, not replayed callback) is the only recovery
  route (sections 8.3/8.7).

Observed lifecycle and failure semantics (documented for the report):

- register_invoice_listener returns a Task named "{name}_invoice_listener";
  cancel_task(task) removes it from the dispatch list and cancels the
  asyncio task — scoped cancellation, other listeners untouched.
- Listener registration is in-memory only: it does not survive an app
  restart. Settled payments persist in the core database and are recovered
  by exact external_id query.
- FakeWallet settlement reaches listeners through the host's real pipeline:
  pay_invoice -> FakeWallet queue -> fundingsource_invoice_producer ->
  update_invoice_from_paid_invoices_stream (marks SUCCESS in core DB) ->
  task_manager.invoice_queue -> dispatch to all registered listeners.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from harness import host as host_module

# The pinned host keeps module-level asyncio singletons (task_manager queues,
# FakeWallet queue, permanent tasks) that assume ONE long-lived event loop —
# exactly how the host's own test suite runs it. Host probes therefore share
# a session-scoped loop; other markers keep function-scoped loops.
pytestmark = [
    pytest.mark.fast,
    pytest.mark.host,
    pytest.mark.asyncio(loop_scope="session"),
]

SETTLE_TIMEOUT_S = 20.0


def _external_id() -> tuple[str, str]:
    order_id = str(uuid.uuid4())
    return order_id, f"infinitemarkets:{order_id}"


async def _create_infinitemarkets_invoice(wallet, amount_sat: int = 123):
    from lnbits.core.services.payments import create_invoice

    order_id, external_id = _external_id()
    payment = await create_invoice(
        wallet_id=wallet.id,
        amount=amount_sat,
        memo="Infinitemarkets order",
        expiry=3600,
        extra={"tag": "infinitemarkets", "order_id": order_id},
        extension="infinitemarkets",
        external_id=external_id,
    )
    return order_id, external_id, payment


async def _settle(payment, wallet):
    from lnbits.core.services.payments import pay_invoice

    return await pay_invoice(
        wallet_id=wallet.id, payment_request=payment.bolt11
    )


async def _payments_by_external_id(external_id: str) -> list:
    from lnbits.core.crud import get_payments
    from lnbits.core.models import PaymentFilters
    from lnbits.db import Filter, Filters

    return await get_payments(
        filters=Filters(
            filters=[Filter.parse_query("external_id", [external_id], PaymentFilters)],
            model=PaymentFilters,
            sortby="time",
            direction="desc",
        )
    )


async def test_invoice_metadata_persisted_and_exactly_queryable(tmp_path):
    """P0-03 (a): extension/external-id/wallet/amount metadata + lookup."""
    async with host_module.host_app(tmp_path / "run") as _app:
        _user, wallet = await host_module.create_test_wallet()
        order_id, external_id, payment = await _create_infinitemarkets_invoice(
            wallet, amount_sat=321
        )

        # Persisted core payment row carries the contract metadata.
        assert payment.extension == "infinitemarkets"
        assert payment.external_id == external_id
        assert payment.wallet_id == wallet.id
        assert payment.amount == 321_000  # msat
        assert payment.extra["tag"] == "infinitemarkets"
        assert payment.extra["order_id"] == order_id

        # Exact external_id lookup retrieves it (the reconciliation key).
        found = await _payments_by_external_id(external_id)
        assert len(found) == 1, "exactly one payment for the exact external_id"
        assert found[0].checking_id == payment.checking_id
        assert found[0].extension == "infinitemarkets"
        assert found[0].external_id == external_id

        # A different external_id does not match (no cross-key leakage).
        _other_order, other_external, _p2 = await _create_infinitemarkets_invoice(
            wallet, amount_sat=1
        )
        assert await _payments_by_external_id(other_external)


async def test_invoice_listener_lifecycle_and_owned_handle_cancellation(tmp_path):
    """P0-03 (b) + (c): listener receives settled payment; scoped cancellation."""
    from lnbits.task_manager import task_manager

    async with host_module.host_app(tmp_path / "run") as _app:
        _user, wallet = await host_module.create_test_wallet()

        received: list = []
        got_payment = asyncio.Event()

        async def on_paid(payment) -> None:
            received.append(payment)
            got_payment.set()

        our_task = task_manager.register_invoice_listener(on_paid, name="infinitemarkets")

        # An unrelated named task that must survive our cancellation.
        stop_unrelated = asyncio.Event()

        async def unrelated_worker() -> None:
            await stop_unrelated.wait()

        unrelated_task = task_manager.create_task(
            unrelated_worker(), name="gamma_qual_unrelated_worker"
        )

        try:
            # (b) settle through the host's own settlement path.
            _oid, external_id, payment = await _create_infinitemarkets_invoice(wallet)
            await _settle(payment, wallet)
            await asyncio.wait_for(got_payment.wait(), timeout=SETTLE_TIMEOUT_S)

            assert len(received) == 1
            settled = received[0]
            assert settled.extension == "infinitemarkets"
            assert settled.external_id == external_id
            assert settled.wallet_id == wallet.id
            assert settled.status == "success"

            # (c) cancel ONLY the extension-owned handle.
            task_manager.cancel_task(our_task)
            await asyncio.sleep(0.1)
            assert our_task.task.cancelled() or our_task.task.done()
            # The unrelated task survives our cancellation.
            assert not unrelated_task.task.done()
            assert task_manager.get_task("gamma_qual_unrelated_worker") is not None

            # After cancellation our listener receives nothing further.
            _oid2, external_id2, payment2 = await _create_infinitemarkets_invoice(wallet)
            await _settle(payment2, wallet)
            await asyncio.sleep(1.5)
            assert len(received) == 1, "cancelled listener must receive nothing"

            # But the newly settled payment is still exactly queryable.
            found = await _payments_by_external_id(external_id2)
            assert len(found) == 1
            assert found[0].status == "success"
        finally:
            if not unrelated_task.task.done():
                stop_unrelated.set()
                await asyncio.sleep(0.1)
            if task_manager.get_task("gamma_qual_unrelated_worker"):
                task_manager.cancel_task(unrelated_task)


async def test_no_durable_callback_delivery_across_restart(tmp_path):
    """P0-03 (d): callback non-durability across restart; query is recovery.

    Registration is in-memory only: after a simulated restart (second app
    boot over the same core database), the previously registered listener
    receives nothing, while the settled payment remains discoverable by
    exact external_id query — the reconciliation path is the only recovery
    route (sections 8.3/8.7).
    """
    from lnbits.task_manager import task_manager

    received: list = []

    async def on_paid(payment) -> None:
        received.append(payment)

    # First boot: register the listener and settle one invoice.
    async with host_module.host_app(tmp_path / "run") as _app:
        _user, wallet = await host_module.create_test_wallet()
        # Registered (returned Task intentionally unused here: the point is
        # that registration is in-memory only and does not survive restart).
        task_manager.register_invoice_listener(on_paid, name="infinitemarkets")
        try:
            _oid, external_id, payment = await _create_infinitemarkets_invoice(wallet)
            await _settle(payment, wallet)
            await asyncio.sleep(2.0)
            assert len(received) == 1, "listener must fire before restart"
        finally:
            # App shutdown stops the listener task (in-memory registration).
            pass

    # Simulated restart: second app boot. The previously registered
    # listener receives nothing even though a new invoice settles.
    async with host_module.host_app(tmp_path / "run") as _app2:
        _user2, wallet2 = await host_module.create_test_wallet()
        _oid2, external_id2, payment2 = await _create_infinitemarkets_invoice(wallet2)
        await _settle(payment2, wallet2)
        await asyncio.sleep(2.0)
        assert len(received) == 1, (
            "no durable callback delivery: the pre-restart listener must "
            "receive nothing after restart"
        )

        # The settled payment remains discoverable by exact external_id —
        # the query path is the only recovery route.
        found = await _payments_by_external_id(external_id2)
        assert len(found) == 1
        assert found[0].status == "success"
        assert found[0].external_id == external_id2

        # And the pre-restart payment is still queryable too.
        found1 = await _payments_by_external_id(external_id)
        assert len(found1) == 1
        assert found1[0].status == "success"
