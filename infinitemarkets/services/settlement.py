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
import re
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

    return await confirm_settlement(order_id=order_id, source=source, core_payment=payment)


def _payment_snapshot(order: dict, projection: dict, *, attached: bool = True) -> dict | None:
    from bolt11 import decode as bolt11_decode

    settings = ext_settings()
    try:
        def decrypt(column):
            value = projection[column]
            if not value or len(value) > 32_768:
                raise ValueError("missing snapshot")
            ver = crypto.envelope_version(value)
            return crypto.decrypt(
                value, settings.master_keys[ver], record_id=order["id"],
                table="payments", column=column, key_version=ver,
            ).decode()

        refs = decrypt("wallet_refs_enc")
        if attached:
            snapshot = json.loads(refs)
            if (not isinstance(snapshot, dict) or type(snapshot.get("version")) is not int
                    or snapshot["version"] != 1
                    or snapshot.get("order_id") != order["id"]
                    or snapshot.get("merchant_id") != order["merchant_id"]
                    or snapshot.get("external_id") != f"infinitemarkets:{order['id']}"
                    or snapshot.get("tag") != "infinitemarkets"
                    or snapshot.get("currency") != "sat"
                    or not isinstance(snapshot.get("user_id"), str)
                    or not snapshot["user_id"]):
                return None
        else:
            wallet, source = refs.split("|")
            snapshot = {"wallet_id": wallet, "source_wallet_id": source}
        for field, purpose in (("wallet_id", crypto.PURPOSE_WALLET_ID),
                               ("source_wallet_id", crypto.PURPOSE_SOURCE_WALLET_ID)):
            wallet = snapshot.get(field)
            digest = projection[field + "_hash"]
            if (not isinstance(wallet, str) or not wallet
                    or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
                    or crypto.hmac_index(settings.privacy_key, purpose, order["merchant_id"],
                                         crypto.normalize(wallet)) != digest):
                return None
        if (snapshot["wallet_id"] != snapshot["source_wallet_id"]
                or projection["order_id"] != order["id"]
                or projection["core_external_id"] != f"infinitemarkets:{order['id']}"
                or type(projection["amount_sat"]) is not int
                or type(order["total_sat"]) is not int
                or projection["amount_sat"] != order["total_sat"]
                or order["total_sat"] <= 0):
            return None
        if attached:
            payment_hash = projection["payment_hash"]
            invoice = bolt11_decode(decrypt("bolt11_enc"))
            checking = decrypt("checking_id_enc")
            if (not isinstance(payment_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", payment_hash)
                    or order["payment_hash"] != payment_hash
                    or invoice.payment_hash != payment_hash
                    or invoice.amount_msat != order["total_sat"] * 1000
                    or type(order["invoice_expiry"]) is not int
                    or int(invoice.expiry_date.timestamp()) != order["invoice_expiry"]
                    or snapshot.get("payment_hash") != payment_hash
                    or type(snapshot.get("amount_sat")) is not int
                    or snapshot["amount_sat"] != order["total_sat"]
                    or type(snapshot.get("expiry")) is not int
                    or snapshot["expiry"] != order["invoice_expiry"]
                    or not checking or snapshot.get("checking_id") != checking):
                return None
            snapshot["invoice"] = invoice
            snapshot["bolt11"] = decrypt("bolt11_enc")
        return snapshot
    except Exception:
        return None


async def _verify_settlement(
    order: dict, projection: dict, payment, *, require_attached: bool = True,
) -> str | None:
    """§8.3 step 2 verification; returns a bounded reason on mismatch."""
    from bolt11 import decode as bolt11_decode

    settings = ext_settings()
    if (getattr(payment, "extension", None) != "infinitemarkets"
            or getattr(payment, "external_id", None) != f"infinitemarkets:{order['id']}"
            or (getattr(payment, "extra", None) or {}).get("tag") != "infinitemarkets"
            or (getattr(payment, "extra", None) or {}).get("order_id") != order["id"]
            or not getattr(payment, "checking_id", None)
            or not getattr(payment, "wallet_id", None)
            or not getattr(payment, "bolt11", None)
            or not getattr(payment, "expiry", None)
            or not isinstance(getattr(payment, "payment_hash", None), str)
            or not re.fullmatch(r"[0-9a-f]{64}", payment.payment_hash)):
        return "settlement-correlation-mismatch"
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
    attached = (require_attached or projection["status"] not in ("creating", "creation_unknown")
                or any(projection.get(key) is not None for key in
                       ("payment_hash", "bolt11_enc", "checking_id_enc")))
    snapshot = _payment_snapshot(order, projection, attached=attached)
    if snapshot is None:
        return "settlement-snapshot-invalid"
    try:
        invoice = bolt11_decode(payment.bolt11)
        if (invoice.payment_hash != payment.payment_hash
                or invoice.amount_msat != order["total_sat"] * 1000):
            return "settlement-hash-mismatch"
        if int(invoice.expiry_date.timestamp()) != int(payment.expiry.timestamp()):
            return "settlement-expiry-mismatch"
        if attached and (snapshot["payment_hash"] != payment.payment_hash
                         or snapshot["bolt11"] != payment.bolt11
                         or snapshot["checking_id"] != payment.checking_id
                         or snapshot["wallet_id"] != payment.wallet_id):
            return "settlement-correlation-mismatch"
    except Exception:
        return "settlement-bolt11-undecodable"
    # Recheck the merchant user still owns the wallet (ownership loss is a
    # manual exception, not an automatic confirmation).
    wallet_id = _wallet_id_from_snapshot(projection, order, settings)
    if wallet_id is not None:
        from lnbits.core.crud import get_wallet

        wallet = await get_wallet(wallet_id)
        merchant = await _merchant_row(order["merchant_id"])
        owner = snapshot.get("user_id") if attached else (merchant or {}).get("user_id")
        if not wallet or not owner or wallet.user != owner:
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
        return json.loads(raw)["wallet_id"] if raw.startswith("{") else raw.split("|", 1)[0]
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
        order = await tx.fetch_one(
            f"SELECT * FROM {tx.table('orders')} WHERE id = :i" + tx.for_update,
            {"i": order_id},
        )
        if order:
            await _inventory_review(tx, dict(order), reason=reason, source=source, now=now)
            order = await order_service._order_row(tx, order_id)
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


async def _inventory_review(
    tx: DomainTransaction, order: dict, *, reason: str, source: str, now: int,
) -> None:
    manual = order["payment_exception_resolution"] not in (None, "unresolved")
    preserve = manual or (bool(order["payment_exception"])
                          and order["payment_exception_reason"] != "invoice-creation-unknown")
    await tx.execute(
        f"UPDATE {tx.table('orders')} SET payment_exception = :h, "
        "payment_exception_reason = :r, payment_exception_resolution = :s, updated_at = :n "
        "WHERE id = :i",
        {"h": bool(order["payment_exception"]) if manual else True,
         "r": order["payment_exception_reason"] if preserve else reason,
         "s": order["payment_exception_resolution"] if preserve else "unresolved",
         "n": now, "i": order["id"]},
    )
    await tx.execute(
        f"INSERT INTO {tx.table('order_events')} "
        "(id, order_id, from_state, to_state, actor, detail_json, created_at) "
        "VALUES (:i, :o, :s, :s, 'system', :d, :n)",
        {"i": uuid.uuid4().hex, "o": order["id"], "s": order["state"], "n": now,
         "d": json.dumps({"severity": "high", "exception": reason, "source": source})},
    )


async def confirm_settlement(
    *, order_id: str, source: str = "callback", now: int | None = None, core_payment=None,
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
        order = dict(order)
        projection = await tx.fetch_one(
            f"SELECT * FROM {tx.table('payments')} WHERE order_id = :o", {"o": order_id},
        )
        if projection and projection["status"] == "settled":
            return {"order_id": order_id, "action": "no-op",
                    "reason": "already-settled", "source": source}
        originals = await _core_payments_by_external_id(f"infinitemarkets:{order_id}")
        mismatch = "settlement-correlation-mismatch"
        if projection and len(originals) == 1 and originals[0].success:
            original = originals[0]
            fields = ("payment_hash", "wallet_id", "checking_id", "bolt11", "amount",
                      "expiry", "extension", "external_id", "extra", "success")
            if core_payment is None or all(
                getattr(core_payment, key, None) == getattr(original, key) for key in fields
            ):
                mismatch = await _verify_settlement(order, dict(projection), original)
            elif getattr(core_payment, "sat", None) != projection["amount_sat"]:
                mismatch = "settlement-amount-mismatch"
            elif getattr(core_payment, "wallet_id", None) != original.wallet_id:
                mismatch = "settlement-wallet-mismatch"
        now = await tx.now()
        if mismatch:
            await _inventory_review(tx, order, reason=mismatch, source=source, now=now)
            current = await order_service._order_row(tx, order_id)
            emails, events, customer = await _notify_context(tx, current)
            await order_service.enqueue_email_intents(
                tx, order=current, event_type="on_hold", merchant_notify_emails=emails,
                merchant_notify_events=events, customer_email=customer, now=now,
            )
            return {"order_id": order_id, "action": "exception", "reason": mismatch}
        coverage = await order_service.reservation_coverage(tx, order, now)
        now = coverage["now"]
        coverage["complete"] = coverage["complete"] and order["invoice_expiry"] > now
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
            reason = ("settled-after-terminal-state" if coverage["releasable"]
                      else "inventory-reservation-counters-incoherent")
            await _inventory_review(tx, order, reason=reason, source=source, now=now)
            if coverage["releasable"]:
                await order_service.release_reservations(
                    tx, order_id=order_id, to_state="released", now=now,
                )
            order = await order_service._order_row(tx, order_id)
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

        if not coverage["complete"]:
            reason = ("inventory-reservation-coverage-lost" if coverage["releasable"]
                      else "inventory-reservation-counters-incoherent")
            await _inventory_review(tx, order, reason=reason, source=source, now=now)
            await order_service.transition_order(
                tx, order_id=order_id, from_state="awaiting_payment",
                to_state="cancelled", actor="system", reason=reason, now=now,
            )
            released = 0
            if coverage["releasable"]:
                released = await order_service.release_reservations(
                    tx, order_id=order_id, to_state="released", now=now,
                )
            order = await order_service._order_row(tx, order_id)
            emails, events, customer = await _notify_context(tx, order)
            for event_type in ("on_hold", "cancelled"):
                await order_service.enqueue_email_intents(
                    tx, order=order, event_type=event_type,
                    merchant_notify_emails=emails, merchant_notify_events=events,
                    customer_email=customer, now=now,
                )
            return {"order_id": order_id, "action": "exception", "order_state": "cancelled",
                    "reason": reason, "released": released, "source": source}
        held = coverage["held"]
        await order_service.consume_reservations(tx, held, now)
        if not await order_service.inventory_accounted(tx, order):
            raise order_service.TransitionConflict("Consumed inventory proof requires review")
        if (order["payment_exception"]
                and order["payment_exception_reason"] == "invoice-creation-unknown"
                and order["payment_exception_resolution"] in (None, "unresolved")):
            await order_service.resolve_creation_uncertainty(tx, order, now)
        await order_service.transition_order(
            tx, order_id=order_id, from_state="awaiting_payment",
            to_state="confirmed", actor="system",
            detail={"source": source}, now=now,
        )
        order = await order_service._order_row(tx, order_id)
        emails, events, customer = await _notify_context(tx, order)
        await order_service.enqueue_email_intents(
            tx, order=order, event_type="confirmed",
            merchant_notify_emails=emails,
            merchant_notify_events=events,
            customer_email=customer, now=now,
        )
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
        return await _expire_order_in_tx(tx, dict(order), now)


async def _expire_order_in_tx(tx: DomainTransaction, order: dict, now: int) -> dict:
    order_id = order["id"]
    payment = await tx.fetch_one(
        f"SELECT status FROM {tx.table('payments')} WHERE order_id = :o",
        {"o": order_id},
    )
    if (order["state"] != "awaiting_payment" or not payment
            or payment["status"] != "pending" or order["invoice_expiry"] is None
            or order["invoice_expiry"] > now):
        return {"order_id": order_id, "action": "no-op", "released": 0}
    held = await tx.fetch_all(
        f"SELECT expires_at FROM {tx.table('inventory_reservations')} "
        "WHERE order_id = :o AND state = 'held'" + tx.for_update,
        {"o": order_id},
    )
    if any(row["expires_at"] is None or row["expires_at"] > now for row in held):
        return {"order_id": order_id, "action": "no-op", "released": 0}
    await order_service.transition_order(
        tx, order_id=order_id, from_state="awaiting_payment",
        to_state="expired", actor="system",
        reason="invoice-expired-unpaid", now=now,
    )
    released = await order_service.release_reservations(
        tx, order_id=order_id, to_state="expired", now=now,
    )
    await tx.execute(
        f"UPDATE {tx.table('payments')} SET status = 'expired'"
        " WHERE order_id = :o AND status = 'pending'",
        {"o": order_id},
    )
    emails, events, customer = await _notify_context(tx, order)
    await order_service.enqueue_email_intents(
        tx, order=order, event_type="expired", merchant_notify_emails=emails,
        merchant_notify_events=events, customer_email=customer, now=now,
    )
    return {"order_id": order_id, "action": "expired", "released": released}


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
        async with DomainTransaction() as tx:
            order = await order_service._order_row(tx, order_id)
            held = await tx.fetch_all(
                f"SELECT expires_at FROM {tx.table('inventory_reservations')} "
                "WHERE order_id = :o AND state = 'held'" + tx.for_update,
                {"o": order_id},
            )
            if not held or not any(
                item["expires_at"] is not None and item["expires_at"] <= now for item in held
            ):
                continue
            if order["state"] == "awaiting_payment":
                result = await _expire_order_in_tx(tx, order, now)
                expired_orders += result["action"] == "expired"
            elif order["state"] == "invoice_pending":
                payment = await tx.fetch_one(
                    f"SELECT status FROM {tx.table('payments')} WHERE order_id = :o",
                    {"o": order_id},
                )
                if not payment or payment["status"] not in ("creating", "creation_unknown"):
                    continue
                await order_service.transition_order(
                    tx, order_id=order_id, from_state="invoice_pending", to_state="cancelled",
                    actor="system", reason="reservation-expired-before-invoice-attachment", now=now,
                )
                released += await order_service.release_reservations(
                    tx, order_id=order_id, to_state="expired", now=now,
                )
                order = await order_service._order_row(tx, order_id)
                emails, events, customer = await _notify_context(tx, order)
                await order_service.enqueue_email_intents(
                    tx, order=order, event_type="cancelled", merchant_notify_emails=emails,
                    merchant_notify_events=events, customer_email=customer, now=now,
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


async def _accept_inventory(tx: DomainTransaction, order: dict, now: int) -> tuple[dict, int]:
    from .catalog import enqueue_stock_projection

    items, expected = await order_service.inventory_items(tx, order)
    reservations = await tx.fetch_all(
        f"SELECT * FROM {tx.table('inventory_reservations')} WHERE order_id = :o LIMIT 65",
        {"o": order["id"]},
    )
    if len(reservations) > 64:
        raise order_service.TransitionConflict("Reservation cardinality requires review")
    held = [dict(row) for row in reservations if row["state"] == "held"]
    consumed = {}
    for row in reservations:
        if row["state"] not in order_service.RESERVATION_STATES:
            raise order_service.TransitionConflict("Unknown reservation history")
        if row["state"] != "consumed":
            continue
        product_id, quantity = row["product_id"], row["quantity"]
        if (product_id not in expected or product_id in consumed
                or type(quantity) is not int or not 0 < quantity <= expected[product_id]):
            raise order_service.TransitionConflict("Malformed consumed history")
        consumed[product_id] = quantity
    products = await order_service.lock_inventory_products(
        tx, order["merchant_id"], set(expected) | {row["product_id"] for row in held},
    )
    if not await order_service.inventory_counters_coherent(tx, products):
        raise order_service.TransitionConflict("Inventory counters require review")
    history = await order_service.confirmation_chain(tx, order)
    if history is None:
        raise order_service.TransitionConflict("Confirmation lineage requires operator review")
    prior = None
    if (order["payment_exception_resolution"] == "accepted" or any(
        row["actor"] == "merchant" and row["from_state"] in ("expired", "cancelled")
        for row in history
    )):
        prior = await order_service.accepted_inventory_accounting(
            tx, order, {item["id"]: item for item in items}, consumed,
        )
        if prior is None:
            raise order_service.TransitionConflict("Prior acceptance requires operator review")
    elif any(item["backordered_qty"] for item in items):
        raise order_service.TransitionConflict("Backorder history requires operator review")
    if held:
        if prior or any(row["product_id"] not in expected or type(row["quantity"]) is not int
                        or not 0 < row["quantity"] <= expected[row["product_id"]]
                        - consumed.get(row["product_id"], 0) for row in held):
            await order_service.release_reservations(
                tx, order_id=order["id"], to_state="released", now=now,
            )
        else:
            await order_service.consume_reservations(tx, held, now)
            for row in held:
                consumed[row["product_id"]] = row["quantity"]
    remaining_consumed = dict(consumed)
    proof = []
    for item in items:
        product_id = item["product_id"]
        used = min(item["quantity"], remaining_consumed.get(product_id, 0))
        remaining_consumed[product_id] = remaining_consumed.get(product_id, 0) - used
        if prior:
            entry = dict(prior["items"][item["id"]])
        else:
            product = await tx.fetch_one(
                f"SELECT stock_on_hand, stock_reserved FROM {tx.table('products')} WHERE id = :p",
                {"p": product_id},
            )
            outstanding = item["quantity"] - used
            available = (outstanding if product["stock_on_hand"] is None
                         else product["stock_on_hand"] - product["stock_reserved"])
            take = min(outstanding, available)
            if take and product["stock_on_hand"] is not None:
                await tx.execute(
                    f"UPDATE {tx.table('products')} SET stock_on_hand = stock_on_hand - :q, "
                    "revision = revision + 1, updated_at = :n WHERE id = :p",
                    {"q": take, "n": now, "p": product_id},
                )
                await enqueue_stock_projection(tx, product_id)
            entry = {"item_id": item["id"], "product_id": product_id,
                     "quantity": item["quantity"], "consumed_qty": used,
                     "accepted_allocated_qty": take, "backordered_qty": outstanding - take}
        await tx.execute(
            f"UPDATE {tx.table('order_items')} SET backordered_qty = :b WHERE id = :i",
            {"b": entry["backordered_qty"], "i": item["id"]},
        )
        proof.append(entry)
    return {"version": 1, "items": proof,
            "parent_confirmation_id": history[-1]["id"] if history else None}, now


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
        if actor != "merchant" or not await order_service.payment_settled(tx, order):
            raise unprocessable(
                "invalid-transition", "No verified settlement",
                "accept requires a verified settled payment",
            )
        now = await tx.now()
        try:
            proof, now = await _accept_inventory(tx, order, now)
        except order_service.TransitionConflict:
            raise unprocessable(
                "invalid-transition", "Inventory accounting requires review",
            ) from None
        oversold = any(entry["backordered_qty"] for entry in proof["items"])
        if len(json.dumps(proof)) > 32_000:
            raise unprocessable("invalid-transition", "Inventory accounting exceeds audit bound")
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
        await order_service.transition_order(
            tx, order_id=order_id, from_state=order["state"],
            to_state="confirmed", actor=actor,
            reason=reason or "exception-accept", detail={"inventory_accounting": proof}, now=now,
        )
        order = await order_service._order_row(tx, order_id)
        if not await order_service.inventory_accounted(tx, order):
            raise order_service.TransitionConflict("Accepted inventory proof requires review")
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
