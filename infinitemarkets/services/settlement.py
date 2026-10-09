"""Settlement — spec sections 8.3, 8.4, 8.7 plus §11.3 retention.

Payment truth comes only from LNbits core payment rows. The invoice
listener is an unfiltered fan-out, so the callback self-filters on
``extension`` + exact ``external_id`` and verifies wallet/amount/BOLT11
before acting; reconciliation (startup + 60s leased) provides the durable
path when a callback is lost. A settlement on an expired or cancelled
order marks the payment settled + ``payment_exception`` and changes
nothing else — a late payment never auto-reopens an order (§8.4).
"""

from __future__ import annotations

import json
import time
import uuid

from loguru import logger

from .. import crypto
from ..db import DomainTransaction, db, table
from ..security import unprocessable
from ..settings import ExtSettings, ext_settings
from . import orders as order_service

UNCERTAINTY_WINDOW_S = 300
INBOX_CIPHERTEXT_RETENTION_S = 7 * 86400
INBOX_QUARANTINE_RETENTION_S = 30 * 86400
ORDER_PII_RETENTION_S = 90 * 86400
EXTERNAL_ID_PREFIX = "infinitemarkets:"


def _now() -> int:
    return int(time.time())


# --- invoice listener (section 8.3 trigger) ---------------------------------


async def invoice_listener(payment) -> None:
    """The ``register_invoice_listener`` callback — self-filtered.

    Fires for every core payment event; we only act on
    ``extension="infinitemarkets"`` with an exact ``infinitemarkets:<uuid>``
    external id, then verify before confirming. Every path is idempotent
    — a duplicate delivery is a no-op.
    """
    try:
        if getattr(payment, "extension", None) != "infinitemarkets":
            return
        ext = getattr(payment, "external_id", None) or ""
        if not ext.startswith(EXTERNAL_ID_PREFIX):
            return
        order_id = ext[len(EXTERNAL_ID_PREFIX):]
        await _handle_core_payment(order_id, payment, source="listener")
    except Exception as exc:  # noqa: BLE001 — a listener must never raise
        logger.warning(
            f"infinitemarkets settlement listener error: {type(exc).__name__}"
        )


async def _handle_core_payment(order_id: str, payment, *, source: str) -> None:
    async with db.connect() as conn:
        order = await conn.fetchone(
            f"SELECT * FROM {table('orders')} WHERE id = :i", {"i": order_id}
        )
        if not order:
            return
        projection = await conn.fetchone(
            f"SELECT * FROM {table('payments')} WHERE order_id = :o",
            {"o": order_id},
        )
    order = dict(order)
    if projection is None:
        # No projection: the payment correlates by external id only —
        # buyer-controlled metadata is never settlement evidence.
        await _flag_exception(
            order_id, "settlement-without-projection", source
        )
        return
    projection = dict(projection)

    # Crash window: a core payment exists but the projection was never
    # attached (kill during §8.2 step 3) — attach from the callback first.
    if projection["status"] in ("creating", "creation_unknown") and (
        getattr(payment, "bolt11", None)
    ):
        from .checkout import attach_payment

        await attach_payment(order_id=order_id, payment=payment, now=_now())
        async with db.connect() as conn:
            projection = dict(
                await conn.fetchone(
                    f"SELECT * FROM {table('payments')} WHERE order_id = :o",
                    {"o": order_id},
                )
            )
        async with db.connect() as conn:
            order = dict(
                await conn.fetchone(
                    f"SELECT * FROM {table('orders')} WHERE id = :i",
                    {"i": order_id},
                )
            )

    if not payment.success:
        return

    mismatch = await _verify_settlement(order, projection, payment)
    if mismatch is not None:
        await _flag_exception(order_id, mismatch, source)
        return
    return await confirm_settlement(order_id=order_id, source=source)


async def _verify_settlement(
    order: dict, projection: dict, payment
) -> str | None:
    """§8.3 step 2 verification; returns a bounded reason on mismatch."""
    from bolt11 import decode as bolt11_decode

    settings = ext_settings()
    if not payment.is_in:
        return "settlement-not-incoming"
    if payment.amount % 1000 != 0:
        return "settlement-msat-not-exact"
    if projection["amount_sat"] is not None and (
        payment.sat != projection["amount_sat"]
    ):
        return "settlement-amount-mismatch"
    # Wallet snapshot correlation — the payment must land in the merchant's
    # recorded wallet (a foreign wallet's same-external-id invoice is not
    # settlement evidence).
    if projection["wallet_id_hash"]:
        digest = crypto.hmac_index(
            settings.privacy_key, crypto.PURPOSE_WALLET_ID,
            order["merchant_id"], crypto.normalize(payment.wallet_id),
        )
        if digest != projection["wallet_id_hash"]:
            return "settlement-wallet-mismatch"
    # Recheck the merchant user still owns the wallet (ownership loss is a
    # manual exception, not an automatic confirmation).
    wallet_id = _wallet_id_from_snapshot(projection, order, settings)
    if wallet_id is not None:
        from lnbits.core.crud import get_wallet

        wallet = await get_wallet(wallet_id)
        merchant = await _merchant_row(order["merchant_id"])
        if not wallet or not merchant or wallet.user != merchant["user_id"]:
            return "settlement-wallet-ownership-lost"
    # Decoded BOLT11 correlation — hash + amount + expiry must match the
    # persisted projection.
    if projection["bolt11_enc"] is not None:
        try:
            ver = crypto.envelope_version(projection["bolt11_enc"])
            bolt11 = crypto.decrypt(
                projection["bolt11_enc"], settings.master_keys[ver],
                record_id=order["id"], table="payments",
                column="bolt11_enc", key_version=ver,
            ).decode()
            invoice = bolt11_decode(bolt11)
        except Exception:
            return "settlement-bolt11-undecodable"
        if invoice.payment_hash != payment.payment_hash:
            return "settlement-hash-mismatch"
        if payment.expiry and invoice.expiry_date:
            if int(invoice.expiry_date.timestamp()) != int(
                payment.expiry.timestamp()
            ):
                return "settlement-expiry-mismatch"
    return None


def _wallet_id_from_snapshot(
    projection: dict, order: dict, settings: ExtSettings
) -> str | None:
    if projection["wallet_refs_enc"] is None:
        return None
    try:
        ver = crypto.envelope_version(projection["wallet_refs_enc"])
        raw = crypto.decrypt(
            projection["wallet_refs_enc"], settings.master_keys[ver],
            record_id=order["id"], table="payments",
            column="wallet_refs_enc", key_version=ver,
        ).decode()
        return raw.split("|", 1)[0]
    except Exception:
        return None


async def _merchant_row(merchant_id: str) -> dict | None:
    async with db.connect() as conn:
        row = await conn.fetchone(
            f"SELECT * FROM {table('merchants')} WHERE id = :m",
            {"m": merchant_id},
        )
    return dict(row) if row else None


async def _flag_exception(order_id: str, reason: str, source: str) -> None:
    """payment_exception + on_hold intents + high-severity audit detail."""
    now = _now()
    async with DomainTransaction() as tx:
        await tx.execute(
            f"UPDATE {tx.table('orders')} SET payment_exception = TRUE,"
            " payment_exception_reason = :r, updated_at = :n WHERE id = :i",
            {"r": reason, "n": now, "i": order_id},
        )
        await tx.execute(
            f"INSERT INTO {tx.table('order_events')} "
            "(id, order_id, from_state, to_state, actor, detail_json,"
            " created_at) "
            "SELECT :i, :o, state, state, 'system', :d, :n"
            f" FROM {tx.table('orders')} WHERE id = :o",
            {
                "i": uuid.uuid4().hex,
                "o": order_id,
                "d": json.dumps(
                    {"severity": "high", "exception": reason,
                     "source": source}
                ),
                "n": now,
            },
        )
        order = await tx.fetch_one(
            f"SELECT * FROM {tx.table('orders')} WHERE id = :i" + tx.for_update,
            {"i": order_id},
        )
        if order:
            emails, events, customer = await _notify_context(
                tx, dict(order)
            )
            await order_service.enqueue_email_intents(
                tx, order=dict(order), event_type="on_hold",
                merchant_notify_emails=emails,
                merchant_notify_events=events,
                customer_email=customer, now=now,
            )
    logger.warning(
        f"infinitemarkets payment exception on order {order_id}: {reason}"
    )


async def _notify_context(
    tx: DomainTransaction, order: dict
) -> tuple[list[str], dict, str | None]:
    """Merchant notify config + decrypted customer email for intents."""
    settings = ext_settings()
    merchant = await tx.fetch_one(
        f"SELECT notify_emails, notify_events FROM {tx.table('merchants')}"
        " WHERE id = :m",
        {"m": order["merchant_id"]},
    )
    emails = json.loads(merchant["notify_emails"]) if (
        merchant and merchant["notify_emails"]
    ) else []
    events = json.loads(merchant["notify_events"]) if (
        merchant and merchant["notify_events"]
    ) else {}
    customer = None
    if order.get("contact_enc"):
        try:
            ver = crypto.envelope_version(order["contact_enc"])
            contact = json.loads(
                crypto.decrypt(
                    order["contact_enc"], settings.master_keys[ver],
                    record_id=order["id"], table="orders",
                    column="contact_enc", key_version=ver,
                )
            )
            customer = contact.get("email")
        except Exception:
            customer = None
    return emails, events, customer


# --- section 8.3 confirm transaction ------------------------------------------


async def confirm_settlement(
    *, order_id: str, source: str = "callback", now: int | None = None
) -> dict:
    """The §8.3 settlement-confirm transaction — idempotent by design.

    awaiting_payment: mark settled, consume held reservations (stock
    decremented exactly once), order -> confirmed, email + republication
    intents. Any other state: mark settled + payment_exception, no state
    change, no consumption (§8.4 terminal branch).
    """
    now = _now() if now is None else now
    async with DomainTransaction() as tx:
        order = await tx.fetch_one(
            f"SELECT * FROM {tx.table('orders')} WHERE id = :i" + tx.for_update,
            {"i": order_id},
        )
        if not order:
            raise order_service.TransitionConflict(
                f"order {order_id!r} does not exist"
            )
        rc = await tx.execute(
            f"UPDATE {tx.table('payments')}"
            " SET status = 'settled', settled_at = :n"
            " WHERE order_id = :o"
            " AND status IN ('pending', 'creating', 'creation_unknown',"
            " 'expired')",
            {"n": now, "o": order_id},
        )
        if rc != 1:
            payment = await tx.fetch_one(
                f"SELECT status FROM {tx.table('payments')} WHERE order_id = :o",
                {"o": order_id},
            )
            if payment and payment["status"] == "settled":
                return {
                    "order_id": order_id, "action": "no-op",
                    "reason": "already-settled", "source": source,
                }
            raise order_service.TransitionConflict(
                f"settlement confirm CAS lost for payment of {order_id!r}"
            )

        order = dict(order)
        if order["state"] != "awaiting_payment":
            await tx.execute(
                f"UPDATE {tx.table('orders')} SET payment_exception = TRUE,"
                " payment_exception_reason = 'settled-after-terminal-state',"
                " updated_at = :n WHERE id = :i",
                {"n": now, "i": order_id},
            )
            emails, events, customer = await _notify_context(tx, order)
            await order_service.enqueue_email_intents(
                tx, order=order, event_type="on_hold",
                merchant_notify_emails=emails,
                merchant_notify_events=events,
                customer_email=customer, now=now,
            )
            from . import metrics
            metrics.incr("settlement.exception")
            return {
                "order_id": order_id, "action": "exception",
                "order_state": order["state"], "source": source,
            }

        held = await tx.fetch_all(
            f"SELECT id, product_id, quantity FROM"
            f" {tx.table('inventory_reservations')}"
            " WHERE order_id = :o AND state = 'held'",
            {"o": order_id},
        )
        for row in held:
            rc = await tx.execute(
                f"UPDATE {tx.table('inventory_reservations')}"
                " SET state = 'consumed', updated_at = :n"
                " WHERE id = :i AND state = 'held'",
                {"n": now, "i": row["id"]},
            )
            if rc != 1:
                raise order_service.TransitionConflict(
                    f"reservation consume CAS lost for {row['id']}"
                )
            await tx.execute(
                f"UPDATE {tx.table('products')}"
                " SET stock_on_hand = stock_on_hand - :q,"
                " stock_reserved = stock_reserved - :q,"
                " revision = revision + 1, updated_at = :n"
                " WHERE id = :p",
                {"q": row["quantity"], "n": now, "p": row["product_id"]},
            )
        await order_service.transition_order(
            tx, order_id=order_id, from_state="awaiting_payment",
            to_state="confirmed", actor="system",
            detail={"source": source}, now=now,
        )
        emails, events, customer = await _notify_context(tx, order)
        await order_service.enqueue_email_intents(
            tx, order=order, event_type="confirmed",
            merchant_notify_emails=emails,
            merchant_notify_events=events,
            customer_email=customer, now=now,
        )
        # Stock/state republication for each affected product (§8.3 step 5).
        from .catalog import enqueue_stock_projection

        for row in held:
            await enqueue_stock_projection(tx, row["product_id"])
        from . import metrics
        metrics.incr("settlement.confirmed")
        return {
            "order_id": order_id, "action": "confirmed",
            "consumed": len(held), "source": source,
        }


# --- section 8.4 expiry --------------------------------------------------------


async def expire_order(*, order_id: str, now: int | None = None) -> dict:
    """Invoice expired unpaid: reservations -> expired, order -> expired."""
    now = _now() if now is None else now
    async with DomainTransaction() as tx:
        order = await tx.fetch_one(
            f"SELECT * FROM {tx.table('orders')} WHERE id = :i" + tx.for_update,
            {"i": order_id},
        )
        if not order or order["state"] != "awaiting_payment":
            raise order_service.IllegalTransition(
                "expiry applies to awaiting_payment orders"
            )
        await order_service.transition_order(
            tx, order_id=order_id, from_state="awaiting_payment",
            to_state="expired", actor="system",
            reason="invoice-expired-unpaid", now=now,
        )
        released = await order_service.release_reservations(
            tx, order_id=order_id, to_state="expired", now=now
        )
        await tx.execute(
            f"UPDATE {tx.table('payments')} SET status = 'expired'"
            " WHERE order_id = :o AND status = 'pending'",
            {"o": order_id},
        )
        emails, events, customer = await _notify_context(tx, dict(order))
        await order_service.enqueue_email_intents(
            tx, order=dict(order), event_type="expired",
            merchant_notify_emails=emails,
            merchant_notify_events=events,
            customer_email=customer, now=now,
        )
        return {
            "order_id": order_id, "action": "expired",
            "released": released,
        }


async def reservation_expiry_pass(now: int | None = None) -> dict:
    """§8.4/§8.7: release expired held reservations exactly once.

    awaiting_payment orders whose invoice expiry passed transition ->
    expired through ``expire_order`` (which releases as 'expired');
    invoice_pending orders release reservations but keep their state —
    a still-arriving invoice follows the late-settlement path.
    """
    from .readiness import assert_database_compatible

    await assert_database_compatible()
    now = _now() if now is None else now
    released = 0
    expired_orders = 0
    async with db.connect() as conn:
        rows = await conn.fetchall(
            f"SELECT DISTINCT order_id FROM {table('inventory_reservations')}"
            " WHERE state = 'held' AND expires_at IS NOT NULL"
            " AND expires_at <= :n",
            {"n": now},
        )
    for row in rows:
        order_id = row["order_id"]
        async with db.connect() as conn:
            order = await conn.fetchone(
                f"SELECT state FROM {table('orders')} WHERE id = :i",
                {"i": order_id},
            )
        if not order:
            continue
        if order["state"] == "awaiting_payment":
            try:
                await expire_order(order_id=order_id, now=now)
                expired_orders += 1
            except order_service.IllegalTransition:
                pass
            continue
        async with DomainTransaction() as tx:
            released += await order_service.release_reservations(
                tx, order_id=order_id, to_state="expired", now=now
            )
    return {"released": released, "expired_orders": expired_orders}


# --- section 8.7 reconciliation -------------------------------------------------


async def _core_payments_by_external_id(external_id: str) -> list:
    """Exact-external-id query against LNbits core payments."""
    from lnbits.core.crud import get_payments
    from lnbits.core.models.payments import PaymentFilters
    from lnbits.db import Filter, Filters, Operator

    f = Filter(
        field="external_id", op=Operator.EQ,
        values={"external_id__0_0": external_id}, model=PaymentFilters,
    )
    return await get_payments(
        incoming=True,
        filters=Filters(filters=[f], model=PaymentFilters, limit=10),
    )


async def reconcile(now: int | None = None) -> dict:
    """One §8.7 pass — web + order intake scope (03-01). Order-message
    rumor dispatch remains plan 03-02 scope: inbox_events rows accepted
    here are durable evidence, not order intake yet."""
    from .readiness import assert_database_compatible

    await assert_database_compatible()
    now = _now() if now is None else now
    report: dict[str, list] = {
        "resumed": [], "attached": [], "failed_projections": [],
        "confirmed": [], "expired": [], "critical": [],
    }

    # Resume committed 'received' orders idempotently (never abandon an
    # order merely because a crash occurred between intake and reservation).
    async with db.connect() as conn:
        received = await conn.fetchall(
            f"SELECT id FROM {table('orders')} WHERE state = 'received'"
        )
    from . import checkout as checkout_service

    for row in received:
        try:
            result = await checkout_service.begin_saga(
                order_id=row["id"], now=now
            )
            report["resumed"].append(
                {"order_id": row["id"], **result}
            )
        except Exception as exc:
            report["resumed"].append(
                {"order_id": row["id"], "action": "resume-failed",
                 "reason": type(exc).__name__}
            )

    # creating|creation_unknown projections — exact external id, regardless
    # of the commerce order state (§8.2 step 5).
    async with db.connect() as conn:
        projections = await conn.fetchall(
            f"SELECT * FROM {table('payments')} "
            "WHERE status IN ('creating', 'creation_unknown')"
        )
    for projection in projections:
        projection = dict(projection)
        matches = await _core_payments_by_external_id(
            projection["core_external_id"]
        )
        if len(matches) > 1:
            await _flag_exception(
                projection["order_id"], "multiple-core-payments",
                "reconciliation",
            )
            report["critical"].append(
                {"order_id": projection["order_id"],
                 "matches": len(matches)}
            )
            continue
        if len(matches) == 1:
            result = await checkout_service.attach_payment(
                order_id=projection["order_id"], payment=matches[0], now=now
            )
            report["attached"].append(result)
            continue
        if now - projection["created_at"] >= UNCERTAINTY_WINDOW_S:
            await checkout_service._mark_rejection(  # noqa: SLF001
                projection["order_id"], now=now
            )
            report["failed_projections"].append(
                {"order_id": projection["order_id"],
                 "reason": "zero-matches-after-window"}
            )

    # Pending payments — query core status; settled -> §8.3, expired ->
    # expiry path.
    async with db.connect() as conn:
        pending = await conn.fetchall(
            f"SELECT * FROM {table('payments')} WHERE status IN ('pending', 'expired')"
        )
    for projection in pending:
        projection = dict(projection)
        matches = await _core_payments_by_external_id(
            projection["core_external_id"]
        )
        if not matches:
            continue
        if len(matches) != 1:
            await _flag_exception(
                projection["order_id"], "multiple-core-payments", "reconciliation",
            )
            report["critical"].append({"order_id": projection["order_id"], "matches": len(matches)})
            continue
        core = matches[0]
        try:
            from lnbits.core.services.payments import (
                check_payment_status,
            )

            status = None if core.success else await check_payment_status(core)
            if core.success or status.paid:
                verified = core if core.success else core.copy(update={"status": "success"})
                result = await _handle_core_payment(
                    projection["order_id"], verified, source="reconciliation",
                )
                if result is not None:
                    report["confirmed"].append(result)
            elif projection["status"] == "pending" and (
                not core.pending or getattr(core, "is_expired", False)
            ):
                order = await order_service.get_order(projection["order_id"])
                if order["state"] == "awaiting_payment":
                    result = await expire_order(order_id=order["id"], now=now)
                    report["expired"].append(result)
                elif order["state"] in ("cancelled", "expired", "rejected"):
                    async with DomainTransaction() as tx:
                        await tx.execute(
                            f"UPDATE {tx.table('payments')} SET status = 'expired'"
                            " WHERE order_id = :o AND status = 'pending'",
                            {"o": order["id"]},
                        )
        except Exception as exc:  # noqa: BLE001 — funding-source probe
            logger.debug(
                f"infinitemarkets reconcile: status probe failed for"
                f" {projection['core_external_id']}: {type(exc).__name__}"
            )

    # §8.7 inbox resume: 'received' rows re-run the drain and 'validated'
    # rows resume domain dispatch — every route is idempotent
    # (outer/rumor dedupe, the orders unique partial index, aggregate-id
    # intent dedupe), so replaying a killed dispatch never re-creates a
    # domain command.
    from . import inbox as inbox_service
    from . import order_messages as order_msg_service

    try:
        drain = await inbox_service.drain_and_process()
        if any(drain.values()):
            report["resumed"].append({"inbox_drain": drain})
    except Exception as exc:  # noqa: BLE001 — report-only
        logger.debug(
            f"infinitemarkets reconcile: inbox drain failed:"
            f" {type(exc).__name__}"
        )
    try:
        # Type-2 re-enqueue: awaiting_payment gamma orders whose invoice
        # attached before the payment-request enqueue was killed.
        requeued = await order_msg_service.reenqueue_payment_requests()
        if requeued:
            report["resumed"].append(
                {"payment_requests_requeued": requeued}
            )
    except Exception as exc:  # noqa: BLE001 — report-only
        logger.debug(
            f"infinitemarkets reconcile: payment-request reenqueue"
            f" failed: {type(exc).__name__}"
        )
    return report


# --- section 8.3 exception resolution (merchant) --------------------------------


async def resolve_exception(
    *,
    order_id: str,
    action: str,
    reason: str | None = None,
    refund_reference: str | None = None,
    actor: str = "merchant",
) -> dict:
    """§8.3 merchant resolution: accept | refund | confirm-refund."""
    now = _now()
    if action == "accept":
        return await _resolve_accept(
            order_id=order_id, reason=reason, actor=actor, now=now
        )
    if action == "refund":
        return await _resolve_refund(
            order_id=order_id, actor=actor,
            refund_reference=refund_reference, now=now,
        )
    if action == "confirm-refund":
        return await _resolve_confirm_refund(
            order_id=order_id, actor=actor,
            refund_reference=refund_reference, now=now,
        )
    raise unprocessable(
        "invalid-transition", "Invalid resolution",
        "action must be accept|refund|confirm-refund",
    )


async def _resolve_accept(
    *, order_id: str, reason: str | None, actor: str, now: int
) -> dict:
    """Accept verified late settlement: decrement available finite stock,
    record backorders, transition -> confirmed (reason required)."""
    async with DomainTransaction() as tx:
        order = await tx.fetch_one(
            f"SELECT * FROM {tx.table('orders')} WHERE id = :i" + tx.for_update,
            {"i": order_id},
        )
        if not order:
            from ..security import not_found

            raise not_found("order not found")
        order = dict(order)
        if order["state"] not in ("expired", "cancelled"):
            raise unprocessable(
                "invalid-transition",
                f"accept applies to expired/cancelled orders,"
                f" not {order['state']!r}",
            )
        payment = await tx.fetch_one(
            f"SELECT status FROM {tx.table('payments')} WHERE order_id = :o",
            {"o": order_id},
        )
        if not payment or payment["status"] != "settled":
            raise unprocessable(
                "invalid-transition", "No verified settlement",
                "accept requires a verified settled payment",
            )
        items = await tx.fetch_all(
            f"SELECT id, product_id, quantity FROM {tx.table('order_items')}"
            " WHERE order_id = :o",
            {"o": order_id},
        )
        oversold = False
        for item in sorted(items, key=lambda i: i["product_id"]):
            product = await tx.fetch_one(
                f"SELECT stock_on_hand, stock_reserved FROM"
                f" {tx.table('products')} WHERE id = :p",
                {"p": item["product_id"]},
            )
            backordered = 0
            if product and product["stock_on_hand"] is not None:
                available = max(
                    0, product["stock_on_hand"] - product["stock_reserved"]
                )
                take = min(item["quantity"], available)
                backordered = item["quantity"] - take
                if take:
                    await tx.execute(
                        f"UPDATE {tx.table('products')} SET"
                        " stock_on_hand = stock_on_hand - :t,"
                        " revision = revision + 1, updated_at = :n"
                        " WHERE id = :p",
                        {"t": take, "n": now, "p": item["product_id"]},
                    )
            if backordered:
                oversold = True
            await tx.execute(
                f"UPDATE {tx.table('order_items')} SET backordered_qty = :b"
                " WHERE id = :i",
                {"b": backordered, "i": item["id"]},
            )
        await order_service.transition_order(
            tx, order_id=order_id, from_state=order["state"],
            to_state="confirmed", actor=actor,
            reason=reason or "exception-accept", now=now,
        )
        await tx.execute(
            f"UPDATE {tx.table('orders')} SET"
            " payment_exception = FALSE,"
            " payment_exception_resolution = 'accepted',"
            " oversold = :os,"
            " shipping_state = CASE WHEN shipping_state != 'not_required'"
            "   THEN 'processing' ELSE shipping_state END,"
            " updated_at = :n WHERE id = :i",
            {"os": oversold, "n": now, "i": order_id},
        )
        emails, events, customer = await _notify_context(tx, order)
        await order_service.enqueue_email_intents(
            tx, order=order, event_type="confirmed",
            merchant_notify_emails=emails,
            merchant_notify_events=events,
            customer_email=customer, now=now,
        )
        if oversold:
            # §8.3: the type-3 status MUST disclose the backorder — the
            # on_hold customer/merchant email carries the disclosure.
            await order_service.enqueue_email_intents(
                tx, order=order, event_type="on_hold",
                merchant_notify_emails=emails,
                merchant_notify_events=events,
                customer_email=customer, now=now,
            )
        return {
            "order_id": order_id, "action": "accepted",
            "oversold": oversold,
        }


async def _resolve_refund(
    *, order_id: str, actor: str, refund_reference: str | None, now: int
) -> dict:
    """Refund path — attestation only: v1 performs no outgoing payment;
    the exception remains open until confirm-refund."""
    async with DomainTransaction() as tx:
        order = await tx.fetch_one(
            f"SELECT * FROM {tx.table('orders')} WHERE id = :i" + tx.for_update,
            {"i": order_id},
        )
        if not order:
            from ..security import not_found

            raise not_found("order not found")
        order = dict(order)
        if not order["payment_exception"]:
            raise unprocessable(
                "invalid-transition", "No payment exception",
                "refund requires an open payment exception",
            )
        detail = {"event": "refund_requested"}
        if refund_reference:
            detail["refund_reference"] = refund_reference
        await tx.execute(
            f"INSERT INTO {tx.table('order_events')} "
            "(id, order_id, from_state, to_state, actor, detail_json,"
            " created_at) VALUES (:i, :o, :s, :s, :a, :d, :n)",
            {
                "i": uuid.uuid4().hex,
                "o": order_id,
                "s": order["state"],
                "a": actor,
                "d": json.dumps(detail),
                "n": now,
            },
        )
        await tx.execute(
            f"UPDATE {tx.table('orders')} SET"
            " payment_exception_resolution = 'refund_requested',"
            " updated_at = :n WHERE id = :i",
            {"n": now, "i": order_id},
        )
        emails, events, customer = await _notify_context(tx, order)
        await order_service.enqueue_email_intents(
            tx, order=order, event_type="refund_requested",
            merchant_notify_emails=emails,
            merchant_notify_events=events,
            customer_email=customer, now=now,
        )
        return {
            "order_id": order_id, "action": "refund_requested",
            "note": (
                "attestation only — infinitemarkets cannot verify an"
                " outgoing refund payment"
            ),
        }


async def _resolve_confirm_refund(
    *, order_id: str, actor: str, refund_reference: str | None, now: int
) -> dict:
    """Merchant attests the refund happened off-band — records the
    reference and closes the exception without claiming LNbits verified
    an outgoing payment."""
    async with DomainTransaction() as tx:
        order = await tx.fetch_one(
            f"SELECT * FROM {tx.table('orders')} WHERE id = :i" + tx.for_update,
            {"i": order_id},
        )
        if not order:
            from ..security import not_found

            raise not_found("order not found")
        order = dict(order)
        if order["payment_exception_resolution"] != "refund_requested":
            raise unprocessable(
                "invalid-transition",
                "confirm-refund requires a refund_requested exception",
            )
        detail = {"event": "refund_confirmed"}
        if refund_reference:
            detail["refund_reference"] = refund_reference
        await tx.execute(
            f"INSERT INTO {tx.table('order_events')} "
            "(id, order_id, from_state, to_state, actor, detail_json,"
            " created_at) VALUES (:i, :o, :s, :s, :a, :d, :n)",
            {
                "i": uuid.uuid4().hex,
                "o": order_id,
                "s": order["state"],
                "a": actor,
                "d": json.dumps(detail),
                "n": now,
            },
        )
        await tx.execute(
            f"UPDATE {tx.table('orders')} SET"
            " payment_exception = FALSE,"
            " payment_exception_resolution = 'refund_confirmed',"
            " updated_at = :n WHERE id = :i",
            {"n": now, "i": order_id},
        )
        return {"order_id": order_id, "action": "refund_confirmed"}


# --- section 11.3 retention pruner (daily, leased) -------------------------------


async def retention_prune(now: int | None = None) -> dict:
    """§11.3 retention — cryptographic erasure preserving financial/audit
    fields. Inbox ciphertext is Release-B-inert; order PII + message
    plaintext erase 90d after terminal state; expired token AEAD copies
    erase immediately. Merchant-shortened retention would tighten — never
    extend — these defaults (settings table, ``retention_days``)."""
    now = _now() if now is None else now
    report = {"inbox_erased": 0, "orders_erased": 0, "tokens_erased": 0}
    async with DomainTransaction() as tx:
        # Expired/revoked token copies (magic-link rendering window ended).
        rc = await tx.execute(
            f"UPDATE {tx.table('orders')} SET public_token_enc = NULL"
            " WHERE public_token_enc IS NOT NULL AND"
            " public_token_expires_at IS NOT NULL"
            " AND public_token_expires_at <= :n",
            {"n": now},
        )
        report["tokens_erased"] = rc
        # Processed inbox ciphertext beyond 7d (schema-only until Release B).
        rc = await tx.execute(
            f"UPDATE {tx.table('inbox_events')} SET raw_json = NULL,"
            " author_enc = NULL WHERE processed_state = 'processed'"
            " AND processed_at IS NOT NULL AND processed_at <= :t",
            {"t": now - INBOX_CIPHERTEXT_RETENTION_S},
        )
        report["inbox_erased"] = rc
        # Rejected/quarantined intake ciphertext beyond 30d — the bounded
        # reason + hash columns stay for dispute display.
        rc = await tx.execute(
            f"UPDATE {tx.table('inbox_events')} SET raw_json = NULL,"
            " author_enc = NULL WHERE processed_state IN"
            " ('rejected', 'quarantined')"
            " AND processed_at IS NOT NULL AND processed_at <= :t",
            {"t": now - INBOX_QUARANTINE_RETENTION_S},
        )
        report["inbox_erased"] += rc
        # Expired peer-relay/profile cache rows purge outright.
        rc = await tx.execute(
            f"DELETE FROM {tx.table('peer_relays')} WHERE expires_at <= :n",
            {"n": now},
        )
        report["peer_relays_purged"] = rc
        rc = await tx.execute(
            f"DELETE FROM {tx.table('counterparty_profiles')}"
            " WHERE expires_at <= :n",
            {"n": now},
        )
        report["counterparty_profiles_purged"] = rc
        # Terminal orders older than 90d: erase PII ciphertexts, keep the
        # financial/audit columns (hashes, totals, states, events).
        terminal = (
            "o.state IN ('completed', 'rejected', 'cancelled', 'expired')"
            f" AND COALESCE((SELECT MAX(e.created_at) FROM {tx.table('order_events')} e"
            " WHERE e.order_id = o.id AND e.to_state = o.state"
            " AND e.from_state != e.to_state), o.updated_at) <= :t"
        )
        cutoff = {"t": now - ORDER_PII_RETENTION_S}
        rc = await tx.execute(
            f"UPDATE {tx.table('orders')} AS o SET"
            " contact_enc = NULL, address_enc = NULL,"
            " buyer_pubkey_enc = NULL, external_id_enc = NULL,"
            f" public_token_enc = NULL WHERE {terminal}",
            cutoff,
        )
        report["orders_erased"] = rc
        terminal_ids = f"SELECT o.id FROM {tx.table('orders')} o WHERE {terminal}"
        await tx.execute(
            f"UPDATE {tx.table('order_fulfillment')} SET tracking_enc = NULL"
            f" WHERE order_id IN ({terminal_ids})", cutoff,
        )
        await tx.execute(
            f"UPDATE {tx.table('email_queue')} SET recipient_enc = :empty,"
            " payload_enc = :empty, preview_enc = :empty,"
            " state = CASE WHEN state = 'sent' THEN 'sent' ELSE 'suppressed' END,"
            " claim_token = claim_token + 1, claimed_until = NULL, claimed_by = NULL"
            f" WHERE order_id IN ({terminal_ids})", {**cutoff, "empty": b""},
        )
        await tx.execute(
            f"UPDATE {tx.table('idempotency_records')} SET response_enc = NULL"
            f" WHERE expires_at <= :now OR order_id IN ({terminal_ids})",
            {**cutoff, "now": now},
        )
        await tx.execute(
            f"UPDATE {tx.table('order_messages')} SET"
            " content_enc = NULL, participant_keys_enc = NULL"
            " WHERE created_at <= :t",
            {"t": now - ORDER_PII_RETENTION_S},
        )
    return report
