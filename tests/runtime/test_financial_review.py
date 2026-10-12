from __future__ import annotations

import asyncio
import json
import time
import uuid

import pytest
from test_order_admin import _hard01_snapshot
from test_order_saga import (
    API,
    _hard03_unknown_invoice,
    _new_order,
    _row,
    _settle_core_payment,
    _svcs,
)
from test_order_saga import _setup as _setup

pytestmark = pytest.mark.runtime


async def test_review_paid_snapshot_survives_legitimate_wallet_switch(runtime_env, monkeypatch):
    from lnbits.core.crud import create_wallet

    from infinitemarkets.db import DomainTransaction

    svcs = _svcs()
    order, _, _ = await _new_order(runtime_env, scope=uuid.uuid4().hex)
    paid = await _settle_core_payment(order["id"], order["total_sat"])
    await svcs["settlement"].invoice_listener(paid)
    for state in ("processing", "completed"):
        response = await runtime_env["client"].post(
            f"{API}/merchants/{runtime_env['merchant_id']}/orders/{order['id']}/status",
            headers=await runtime_env["cookie"](), json={"to_state": state},
        )
        assert response.status_code == 200, response.text
    replacement = await create_wallet(
        user_id=runtime_env["wallet"].user, wallet_name="review-switch",
    )
    response = await runtime_env["client"].patch(
        f"{API}/merchants/{runtime_env['merchant_id']}",
        headers=await runtime_env["cookie"](), json={"wallet_id": replacement.id},
    )
    assert response.status_code == 200, response.text
    monkeypatch.setattr(svcs["settlement"], "_now", lambda: order["invoice_expiry"] + 1000)
    async with DomainTransaction() as tx:
        fresh = await svcs["orders"]._order_row(tx, order["id"])
        assert await svcs["orders"].fulfillment_authorized(tx, fresh)
    before = await _hard01_snapshot(order["id"])
    await svcs["settlement"].invoice_listener(paid)
    assert await _hard01_snapshot(order["id"]) == before


@pytest.mark.parametrize("damage", [
    "order_hash_null", "order_hash_other", "projection_hash_other", "wallet_refs_null",
    "bolt11_null", "checking_null", "source_hash_null", "expiry_other", "resolution_other",
    "order_hash_malformed", "projection_hash_null", "wallet_refs_corrupt", "bolt11_corrupt",
    "wallet_hash_malformed", "source_hash_malformed", "expiry_null",
])
async def test_review_corrupt_paid_identity_is_readonly_denied(runtime_env, damage):
    from infinitemarkets.db import DomainTransaction

    svcs = _svcs()
    order, product, response = await _new_order(runtime_env, scope=uuid.uuid4().hex)
    updated = await runtime_env["client"].patch(
        f"{API}/products/{product['id']}", headers=await runtime_env["cookie"](),
        json={"delivery_content": "review entitlement"},
    )
    assert updated.status_code == 200
    paid = await _settle_core_payment(order["id"], order["total_sat"])
    await svcs["settlement"].invoice_listener(paid)
    async with DomainTransaction() as tx:
        healthy = await svcs["orders"]._order_row(tx, order["id"])
        assert await svcs["orders"].fulfillment_authorized(tx, healthy), (
            healthy["state"], healthy["payment_exception_reason"],
            healthy["payment_exception_resolution"],
        )
        edits = {
            "order_hash_null": ("orders", "payment_hash = NULL"),
            "order_hash_other": ("orders", "payment_hash = '" + "a" * 64 + "'"),
            "projection_hash_other": ("payments", "payment_hash = '" + "b" * 64 + "'"),
            "wallet_refs_null": ("payments", "wallet_refs_enc = NULL"),
            "bolt11_null": ("payments", "bolt11_enc = NULL"),
            "checking_null": ("payments", "checking_id_enc = NULL"),
            "source_hash_null": ("payments", "source_wallet_id_hash = NULL"),
            "expiry_other": ("orders", "invoice_expiry = invoice_expiry + 1"),
            "resolution_other": ("orders", "payment_exception_resolution = 'legacy-other'"),
            "order_hash_malformed": ("orders", "payment_hash = 'malformed'"),
            "projection_hash_null": ("payments", "payment_hash = NULL"),
            "wallet_refs_corrupt": ("payments", "wallet_refs_enc = :bad"),
            "bolt11_corrupt": ("payments", "bolt11_enc = :bad"),
            "wallet_hash_malformed": ("payments", "wallet_id_hash = 'malformed'"),
            "source_hash_malformed": ("payments", "source_wallet_id_hash = 'malformed'"),
            "expiry_null": ("orders", "invoice_expiry = NULL"),
        }
        table, assignment = edits[damage]
        key = "id" if table == "orders" else "order_id"
        await tx.execute(f"UPDATE {tx.table(table)} SET {assignment} WHERE {key} = :o",
                         {"o": order["id"], "bad": b"invalid-envelope"})
    before = await _hard01_snapshot(order["id"])
    async with DomainTransaction() as tx:
        fresh = await svcs["orders"]._order_row(tx, order["id"])
        assert not await svcs["orders"].fulfillment_authorized(tx, fresh), damage
        assert await svcs["orders"].digital_delivery(tx, fresh) == []
    status = (await runtime_env["client"].get(
        f"{API}/public/order-status", headers={"X-Order-Token": response["public_token"]},
    )).json()
    assert status["digital_delivery"] == []
    result = await runtime_env["client"].post(
        f"{API}/merchants/{runtime_env['merchant_id']}/orders/{order['id']}/status",
        headers=await runtime_env["cookie"](), json={"to_state": "processing"},
    )
    assert result.status_code == 422
    assert await _hard01_snapshot(order["id"]) == before


@pytest.mark.parametrize("damage", ["order_hash", "projection_hash", "bolt11", "refs", "checking"])
async def test_review_normal_callback_requires_snapshot(runtime_env, damage):
    from infinitemarkets.db import DomainTransaction

    svcs = _svcs()
    order, product, _ = await _new_order(runtime_env, scope=uuid.uuid4().hex)
    paid = await _settle_core_payment(order["id"], order["total_sat"])
    async with DomainTransaction() as tx:
        table, assignment = {
            "order_hash": ("orders", "payment_hash = NULL"),
            "projection_hash": ("payments", "payment_hash = '" + "c" * 64 + "'"),
            "bolt11": ("payments", "bolt11_enc = NULL"),
            "refs": ("payments", "wallet_refs_enc = NULL"),
            "checking": ("payments", "checking_id_enc = NULL"),
        }[damage]
        key = "id" if table == "orders" else "order_id"
        await tx.execute(f"UPDATE {tx.table(table)} SET {assignment} WHERE {key} = :o",
                         {"o": order["id"]})
    await svcs["settlement"].invoice_listener(paid)
    fresh = await svcs["orders"].get_order(order["id"])
    assert fresh["state"] != "confirmed", "normal callback must not bypass mandatory snapshot"
    stock = await _row(
        "SELECT stock_on_hand, stock_reserved FROM infinitemarkets.products WHERE id = :p",
        {"p": product["id"]},
    )
    assert stock == {"stock_on_hand": 10, "stock_reserved": 2}


async def test_review_direct_confirmation_requires_attached_identity(runtime_env, monkeypatch):
    svcs = _svcs()
    order, product, _, _ = await _hard03_unknown_invoice(runtime_env, monkeypatch)
    await _settle_core_payment(order["id"], order["total_sat"])
    result = await svcs["settlement"].confirm_settlement(order_id=order["id"])
    assert result["action"] == "exception", "confirmation cannot skip original attached snapshot"
    projection = await _row("SELECT status FROM infinitemarkets.payments WHERE order_id = :o",
                            {"o": order["id"]})
    assert projection["status"] == "creation_unknown"
    stock = await _row("SELECT stock_on_hand, stock_reserved FROM infinitemarkets.products "
                       "WHERE id = :p", {"p": product["id"]})
    assert stock == {"stock_on_hand": 10, "stock_reserved": 2}


async def test_review_paid_expiry_and_wallet_switch_preserve_original_authority(runtime_env):
    from infinitemarkets.db import DomainTransaction

    svcs = _svcs()
    order, _, _ = await _new_order(runtime_env, scope=uuid.uuid4().hex)
    paid = await _settle_core_payment(order["id"], order["total_sat"])
    await svcs["settlement"].invoice_listener(paid)
    async with DomainTransaction() as tx:
        await tx.execute("UPDATE merchants SET wallet_id_hash = :h WHERE id = :m",
                         {"h": "d" * 64, "m": runtime_env["merchant_id"]})
    before = await _hard01_snapshot(order["id"])
    with pytest.raises(svcs["orders"].IllegalTransition):
        await svcs["settlement"].expire_order(
            order_id=order["id"], now=order["invoice_expiry"] + 1,
        )
    await svcs["settlement"].invoice_listener(paid)
    async with DomainTransaction() as tx:
        current = await svcs["orders"]._order_row(tx, order["id"])
        assert await svcs["orders"].fulfillment_authorized(tx, current)
    assert await _hard01_snapshot(order["id"]) == before


@pytest.mark.parametrize("damage", ["released", "partial", "expired", "corrupt", "missing"])
async def test_review_fresh_creating_without_hold_is_not_payable(runtime_env, monkeypatch, damage):
    from infinitemarkets.db import DomainTransaction

    svcs = _svcs()
    order, product, response, original = await _hard03_unknown_invoice(runtime_env, monkeypatch)
    now = int(time.time())
    async with DomainTransaction() as tx:
        await tx.execute("UPDATE orders SET payment_exception = FALSE, "
                         "payment_exception_reason = NULL, payment_exception_resolution = NULL "
                         "WHERE id = :o", {"o": order["id"]})
        await tx.execute("UPDATE payments SET status = 'creating' WHERE order_id = :o",
                         {"o": order["id"]})
        if damage == "released":
            await svcs["orders"].release_reservations(
                tx, order_id=order["id"], to_state="released", now=now,
            )
        elif damage == "partial":
            await tx.execute("UPDATE inventory_reservations SET quantity = 1 WHERE order_id = :o",
                             {"o": order["id"]})
            await tx.execute("UPDATE products SET stock_reserved = 1 WHERE id = :p",
                             {"p": product["id"]})
        elif damage == "missing":
            await tx.execute("DELETE FROM inventory_reservations WHERE order_id = :o",
                             {"o": order["id"]})
            await tx.execute("UPDATE products SET stock_reserved = 0 WHERE id = :p",
                             {"p": product["id"]})
        elif damage == "corrupt":
            await tx.execute("UPDATE products SET stock_reserved = 1 WHERE id = :p",
                             {"p": product["id"]})
        elif damage == "expired":
            now = int(original.expiry.timestamp())

            async def expired_clock(self):
                return now

            monkeypatch.setattr(DomainTransaction, "now", expired_clock)
        else:
            raise AssertionError("unhandled damage fixture")
    attached = await svcs["checkout"].attach_payment(
        order_id=order["id"], payment=original, now=now,
    )
    assert attached["bolt11"] is None, "failed coverage/deadline must suppress fresh QR"
    fresh = await svcs["orders"].get_order(order["id"])
    assert fresh["state"] == "cancelled" and fresh["payment_exception"]
    status = (await runtime_env["client"].get(
        f"{API}/public/order-status", headers={"X-Order-Token": response["public_token"]},
    )).json()
    assert status["bolt11"] is None
    projection = await _row("SELECT status, payment_hash, core_external_id "
                            "FROM infinitemarkets.payments WHERE order_id = :o",
                            {"o": order["id"]})
    assert projection == {"status": "pending", "payment_hash": original.payment_hash,
                          "core_external_id": f"infinitemarkets:{order['id']}"}
    stock = await _row("SELECT stock_on_hand, stock_reserved FROM infinitemarkets.products "
                       "WHERE id = :p", {"p": product["id"]})
    assert stock == {"stock_on_hand": 10, "stock_reserved": 1 if damage == "corrupt" else 0}
    before = await _hard01_snapshot(order["id"])
    replay = await svcs["checkout"].attach_payment(order_id=order["id"], payment=original, now=now)
    resumed = await svcs["checkout"]._resume_order({"_resume_order_id": order["id"]}, now=now)
    assert replay["bolt11"] is None and resumed["order"]["bolt11"] is None
    assert await _hard01_snapshot(order["id"]) == before


async def test_review_pg_checkout_email_fk_cycle_completes(runtime_env, monkeypatch):
    from infinitemarkets.db import DomainTransaction, dialect

    if dialect() != "postgres":
        pytest.skip("PostgreSQL FK row-lock compatibility")
    svcs = _svcs()
    order, product, _ = await _new_order(runtime_env, scope=uuid.uuid4().hex)
    await svcs["orders"].cancel_order(order_id=order["id"], actor="buyer", reason=None)
    paid = await _settle_core_payment(order["id"], order["total_sat"])
    await svcs["settlement"].invoice_listener(paid)
    async def pause_saga(**kwargs):
        return {"state": "received"}

    with monkeypatch.context() as patch:
        patch.setattr(svcs["checkout"], "begin_saga", pause_saga)
        received = await svcs["checkout"].checkout(
            payload={"merchant_pubkey": await _merchant_pubkey(runtime_env),
                     "items": [{"d_tag": product["d_tag"], "quantity": 1}]},
            idempotency_key=uuid.uuid4().hex * 2, client_scope=uuid.uuid4().hex,
        )
    from infinitemarkets.crypto import token_lookup_hash

    competitor = await _row("SELECT id FROM infinitemarkets.orders WHERE public_token_hash = :h",
                            {"h": token_lookup_hash(received["public_token"])})
    async with DomainTransaction() as tx:
        await tx.execute("UPDATE merchants SET notify_emails = :e WHERE id = :m",
                         {"e": json.dumps(["review@example.invalid"]),
                          "m": runtime_env["merchant_id"]})
    product_locked, merchant_locked = asyncio.Event(), asyncio.Event()
    fetch = DomainTransaction.fetch_one
    from infinitemarkets.services import catalog

    publish = catalog.enqueue_stock_projection
    connections = {}

    async def controlled_publish(tx, product_id):
        if asyncio.current_task().get_name() == "review-accept":
            connections["accept"] = (await tx.fetch_one("SELECT pg_backend_pid() AS pid"))["pid"]
            product_locked.set()
            await asyncio.wait_for(merchant_locked.wait(), 5)
        return await publish(tx, product_id)

    async def controlled_fetch(tx, sql, params=None):
        result = await fetch(tx, sql, params)
        if (asyncio.current_task().get_name() == "review-checkout"
                and "SELECT id FROM" in sql and "merchants" in sql
                and (sql.endswith(tx.for_update) or sql.endswith(tx.for_no_key_update))):
            connections["checkout"] = (await fetch(tx, "SELECT pg_backend_pid() AS pid"))["pid"]
            merchant_locked.set()
        return result

    async def checkout_same_product():
        return await svcs["checkout"].begin_saga(order_id=competitor["id"])

    monkeypatch.setattr(catalog, "enqueue_stock_projection", controlled_publish)
    monkeypatch.setattr(DomainTransaction, "fetch_one", controlled_fetch)
    workers = [asyncio.create_task(svcs["settlement"].resolve_exception(
        order_id=order["id"], action="accept",
    ), name="review-accept")]
    try:
        await asyncio.wait_for(product_locked.wait(), 5)
        workers.append(asyncio.create_task(checkout_same_product(), name="review-checkout"))
        results = await asyncio.wait_for(asyncio.gather(*workers, return_exceptions=True), 12)
    finally:
        for worker in workers:
            if not worker.done():
                worker.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
    assert len(set(connections.values())) == 2
    assert all(not isinstance(result, BaseException) for result in results), (
        "real email FK and checkout must both complete without deadlock",
        [type(result).__name__ for result in results],
    )
    stock = await _row("SELECT stock_on_hand, stock_reserved FROM infinitemarkets.products "
                       "WHERE id = :p", {"p": product["id"]})
    assert stock == {"stock_on_hand": 8, "stock_reserved": 1}
    email = await _row("SELECT COUNT(*) AS n FROM infinitemarkets.email_queue "
                       "WHERE order_id = :o AND event_type = 'confirmed'", {"o": order["id"]})
    assert email["n"] == 1
    audit = await _row("SELECT COUNT(*) AS n FROM infinitemarkets.order_events "
                       "WHERE order_id = :o AND from_state = 'cancelled' "
                       "AND to_state = 'confirmed' AND actor = 'merchant'", {"o": order["id"]})
    assert audit["n"] == 1
    assert (await svcs["orders"].get_order(competitor["id"]))["state"] == "awaiting_payment"
    async with DomainTransaction() as tx:
        current = await svcs["orders"]._order_row(tx, order["id"])
        assert await svcs["orders"].fulfillment_authorized(tx, current)


async def _merchant_pubkey(runtime_env):
    from test_order_saga import _mpk

    return await _mpk(runtime_env)


@pytest.mark.parametrize("surface", ["public", "history", "email"])
async def test_review_public_delivery_snapshot_serializes_cancellation(
    runtime_env, monkeypatch, surface,
):
    from infinitemarkets.db import DomainTransaction, dialect

    if dialect() != "postgres":
        pytest.skip("PostgreSQL snapshot/order-lock interleaving")
    svcs = _svcs()
    address = f"{uuid.uuid4().hex}@example.invalid"
    order, product, response = await _new_order(
        runtime_env, scope=uuid.uuid4().hex,
        payload_extra={"email": address, "email_opt_in": True},
    )
    update = await runtime_env["client"].patch(
        f"{API}/products/{product['id']}", headers=await runtime_env["cookie"](),
        json={"delivery_content": "atomic entitlement"},
    )
    assert update.status_code == 200
    paid = await _settle_core_payment(order["id"], order["total_sat"])
    await svcs["settlement"].invoice_listener(paid)
    fresh = await svcs["orders"].get_order(order["id"])
    assert fresh["state"] == "confirmed", fresh.get("payment_exception_reason")
    authority, resume, cancelling = asyncio.Event(), asyncio.Event(), asyncio.Event()
    gate = svcs["orders"].fulfillment_authorized
    fetch = DomainTransaction.fetch_one

    async def pause_authority(conn, current):
        authorized = await gate(conn, current)
        if current["id"] == order["id"] and not authority.is_set():
            assert authorized
            authority.set()
            await asyncio.wait_for(resume.wait(), 5)
        return authorized

    async def observe_cancel(tx, sql, params=None):
        if (asyncio.current_task().get_name() == "review-cancel"
                and "orders" in sql and sql.endswith(tx.for_update)):
            cancelling.set()
        return await fetch(tx, sql, params)

    monkeypatch.setattr(svcs["orders"], "fulfillment_authorized", pause_authority)
    monkeypatch.setattr(DomainTransaction, "fetch_one", observe_cancel)
    sent = []

    async def read_surface():
        if surface == "email":
            import lnbits.core.services.notifications as notifications
            from lnbits.settings import settings

            monkeypatch.setattr(
                type(settings), "is_email_notifications_configured", lambda self: True,
            )

            async def send(*args):
                if address in args[5]:
                    sent.append(args[7])
                return True

            monkeypatch.setattr(notifications, "send_email", send)
            await svcs["email"].worker_tick("review-email")
            return any("atomic entitlement" in body for body in sent)
        if surface == "history":
            import httpx
            from test_nostr_signin import _bind_buyer, _buyer_hex, _signin

            label = "review-snapshot-history"
            await _bind_buyer(runtime_env, order["id"], _buyer_hex(label))
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(
                    app=runtime_env["app"], client=("198.51.100.200", 1234),
                ), base_url="https://shop.example",
            ) as buyer:
                await _signin(buyer, label)
                result = await buyer.get(f"{API}/public/nostr/orders")
                entry = next(
                    row for row in result.json()["orders"] if row["order_id"] == order["id"]
                )
                return bool(entry["digital_delivery"])
        result = await runtime_env["client"].get(
            f"{API}/public/order-status", headers={"X-Order-Token": response["public_token"]},
        )
        return bool(result.json()["digital_delivery"])

    reader = asyncio.create_task(read_surface(), name="review-public")
    workers = [reader]
    try:
        await asyncio.wait_for(authority.wait(), 5)
        cancel = asyncio.create_task(svcs["orders"].cancel_order(
            order_id=order["id"], actor="merchant", reason="concurrent cancellation",
        ), name="review-cancel")
        workers.append(cancel)
        await asyncio.wait_for(cancelling.wait(), 5)
        await asyncio.sleep(0.1)
        assert not cancel.done(), (
            "authority and content select must hold the same current order lock"
        )
        resume.set()
        await asyncio.wait_for(asyncio.gather(*workers), 8)
    finally:
        resume.set()
        for worker in workers:
            if not worker.done():
                worker.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
    assert reader.result()
    status = (await runtime_env["client"].get(
        f"{API}/public/order-status", headers={"X-Order-Token": response["public_token"]},
    )).json()
    assert status["digital_delivery"] == []


@pytest.mark.parametrize("damage", [
    "future", "missing_parent", "cycle", "branch", "changed_quantity",
    "parent_list", "items_string",
])
async def test_review_accept_lineage_damage_is_readonly_hold(runtime_env, damage):
    from infinitemarkets.db import DomainTransaction
    from infinitemarkets.security import ProblemError

    svcs = _svcs()
    order, _, _ = await _new_order(runtime_env, scope=uuid.uuid4().hex)
    await svcs["orders"].cancel_order(order_id=order["id"], actor="buyer", reason=None)
    paid = await _settle_core_payment(order["id"], order["total_sat"])
    await svcs["settlement"].invoice_listener(paid)
    await svcs["settlement"].resolve_exception(order_id=order["id"], action="accept")
    async with DomainTransaction() as tx:
        event = await tx.fetch_one("SELECT * FROM order_events WHERE order_id = :o "
                                   "AND from_state = 'cancelled' AND to_state = 'confirmed'",
                                   {"o": order["id"]})
        detail = json.loads(event["detail_json"])
        if damage == "future":
            await tx.execute("UPDATE order_events SET created_at = :n WHERE id = :i",
                             {"n": await tx.now() + 1000, "i": event["id"]})
        elif damage == "branch":
            await tx.execute("INSERT INTO order_events "
                             "(id, order_id, from_state, to_state, actor, detail_json, created_at) "
                             "VALUES (:i, :o, 'cancelled', 'confirmed', 'merchant', :d, :n)",
                             {"i": uuid.uuid4().hex, "o": order["id"],
                              "d": event["detail_json"], "n": event["created_at"]})
        else:
            if damage == "missing_parent":
                detail["inventory_accounting"]["parent_confirmation_id"] = uuid.uuid4().hex
            elif damage == "cycle":
                detail["inventory_accounting"]["parent_confirmation_id"] = event["id"]
            elif damage == "parent_list":
                detail["inventory_accounting"]["parent_confirmation_id"] = []
            elif damage == "items_string":
                detail["inventory_accounting"]["items"] = "malformed"
            else:
                detail["inventory_accounting"]["items"][0]["quantity"] += 1
            await tx.execute("UPDATE order_events SET detail_json = :d WHERE id = :i",
                             {"d": json.dumps(detail), "i": event["id"]})
        fresh = await svcs["orders"]._order_row(tx, order["id"])
        assert not await svcs["orders"].inventory_accounted(tx, fresh)
    await svcs["orders"].cancel_order(
        order_id=order["id"], actor="merchant", reason="damaged lineage review",
    )
    before = await _hard01_snapshot(order["id"])
    with pytest.raises(ProblemError):
        await svcs["settlement"].resolve_exception(order_id=order["id"], action="accept")
    assert await _hard01_snapshot(order["id"]) == before


@pytest.mark.parametrize("field,value", [
    ("checking_id", ""), ("expiry", None), ("bolt11", ""), ("extra", {}),
    ("extra", {"tag": "infinitemarkets", "order_id": "another-order"}),
    ("payment_hash", "d" * 64), ("wallet_id", "foreign-wallet"),
])
async def test_review_callback_identity_matches_canonical_core(runtime_env, field, value):
    svcs = _svcs()
    order, _, _ = await _new_order(runtime_env, scope=uuid.uuid4().hex)
    paid = await _settle_core_payment(order["id"], order["total_sat"])
    await svcs["settlement"].invoice_listener(paid.copy(update={field: value}))
    fresh = await svcs["orders"].get_order(order["id"])
    assert fresh["state"] == "awaiting_payment" and fresh["payment_exception"]
    projection = await _row("SELECT status FROM infinitemarkets.payments WHERE order_id = :o",
                            {"o": order["id"]})
    assert projection["status"] == "pending"


@pytest.mark.parametrize("operation", ["coverage", "release", "accept"])
async def test_review_reservation_cardinality_fails_closed(runtime_env, operation):
    from infinitemarkets.db import DomainTransaction
    from infinitemarkets.security import ProblemError

    svcs = _svcs()
    order, product, _ = await _new_order(runtime_env, scope=uuid.uuid4().hex)
    if operation == "accept":
        await svcs["orders"].cancel_order(order_id=order["id"], actor="buyer", reason=None)
        paid = await _settle_core_payment(order["id"], order["total_sat"])
        await svcs["settlement"].invoice_listener(paid)
    async with DomainTransaction() as tx:
        template = dict(await tx.fetch_one("SELECT * FROM products WHERE id = :p",
                                           {"p": product["id"]}))
        reservation = dict(await tx.fetch_one(
            "SELECT * FROM inventory_reservations WHERE order_id = :o", {"o": order["id"]},
        ))
        for _ in range(64):
            replica = {**template, "id": uuid.uuid4().hex, "d_tag": uuid.uuid4().hex}
            columns = ", ".join(replica)
            placeholders = ", ".join(":" + key for key in replica)
            await tx.execute(f"INSERT INTO products ({columns}) VALUES ({placeholders})", replica)
            replica_reservation = {**reservation, "id": uuid.uuid4().hex,
                                   "product_id": replica["id"]}
            columns = ", ".join(replica_reservation)
            placeholders = ", ".join(":" + key for key in replica_reservation)
            await tx.execute(
                f"INSERT INTO inventory_reservations ({columns}) VALUES ({placeholders})",
                replica_reservation,
            )
    before = await _hard01_snapshot(order["id"])
    if operation == "accept":
        with pytest.raises(ProblemError):
            await svcs["settlement"].resolve_exception(order_id=order["id"], action="accept")
    else:
        async with DomainTransaction() as tx:
            current = await svcs["orders"]._order_row(tx, order["id"])
            if operation == "coverage":
                coverage = await svcs["orders"].reservation_coverage(tx, current, await tx.now())
                assert not coverage["complete"] and not coverage["releasable"]
            else:
                with pytest.raises(svcs["orders"].TransitionConflict):
                    await svcs["orders"].release_reservations(
                        tx, order_id=order["id"], to_state="released", now=await tx.now(),
                    )
    assert await _hard01_snapshot(order["id"]) == before


@pytest.mark.parametrize("field", ["version", "amount_sat", "expiry", "user_id"])
async def test_review_snapshot_boolean_version_is_not_authority(runtime_env, field):
    from infinitemarkets import crypto
    from infinitemarkets.db import DomainTransaction
    from infinitemarkets.settings import ext_settings

    svcs = _svcs()
    order, _, _ = await _new_order(runtime_env, scope=uuid.uuid4().hex)
    paid = await _settle_core_payment(order["id"], order["total_sat"])
    await svcs["settlement"].invoice_listener(paid)
    settings = ext_settings()
    async with DomainTransaction() as tx:
        projection = dict(await tx.fetch_one("SELECT * FROM payments WHERE order_id = :o",
                                             {"o": order["id"]}))
        ver = crypto.envelope_version(projection["wallet_refs_enc"])
        snapshot = json.loads(crypto.decrypt(
            projection["wallet_refs_enc"], settings.master_keys[ver], record_id=order["id"],
            table="payments", column="wallet_refs_enc", key_version=ver,
        ))
        snapshot[field] = (True if field == "version" else ["invalid"] if field == "user_id"
                           else float(snapshot[field]))
        encoded = crypto.encrypt(
            json.dumps(snapshot).encode(), settings.master_keys[ver], record_id=order["id"],
            table="payments", column="wallet_refs_enc", key_version=ver,
        )
        await tx.execute("UPDATE payments SET wallet_refs_enc = :e WHERE order_id = :o",
                         {"e": encoded, "o": order["id"]})
        current = await svcs["orders"]._order_row(tx, order["id"])
        assert not await svcs["orders"].fulfillment_authorized(tx, current)


async def test_review_accept_stock_intent_uses_database_clock(runtime_env, monkeypatch):
    from infinitemarkets.db import DomainTransaction
    from infinitemarkets.services import outbox

    svcs = _svcs()
    order, product, _ = await _new_order(runtime_env, scope=uuid.uuid4().hex)
    await svcs["orders"].cancel_order(order_id=order["id"], actor="buyer", reason=None)
    paid = await _settle_core_payment(order["id"], order["total_sat"])
    await svcs["settlement"].invoice_listener(paid)
    monkeypatch.setattr(outbox, "_now", lambda: int(time.time()) + 1000)
    await svcs["settlement"].resolve_exception(order_id=order["id"], action="accept")
    async with DomainTransaction() as tx:
        intents = await tx.fetch_all("SELECT created_at, updated_at, next_attempt_at "
                                     "FROM outbox_events WHERE aggregate_id = :p",
                                     {"p": product["id"]})
        assert intents
        now = await tx.now()
        assert all(value <= now for row in intents for value in row.values())


async def _review_gamma_timeout(runtime_env, monkeypatch):
    from lnbits.core.services import payments as host_payments
    from nostr_sdk import Keys

    from infinitemarkets.services import peer_relays

    svcs = _svcs()
    product = await runtime_env["make_product"](uuid.uuid4().hex, 10)
    merchant = await _row("SELECT * FROM infinitemarkets.merchants WHERE id = :m",
                          {"m": runtime_env["merchant_id"]})
    original = host_payments.create_invoice

    async def routes(*args, **kwargs):
        return ["wss://review.example.invalid"]

    async def lose_response(**kwargs):
        await original(**kwargs)
        raise TimeoutError("synthetic original response loss")

    with monkeypatch.context() as patch:
        patch.setattr(peer_relays, "resolve_buyer_inbox_relays", routes)
        patch.setattr(host_payments, "create_invoice", lose_response)
        result = await svcs["checkout"].gamma_order_intake(
            merchant=merchant,
            payload={"items": [{"d_tag": product["d_tag"], "quantity": 2}],
                     "external_id": uuid.uuid4().hex},
            buyer_pubkey=Keys.generate().public_key().to_hex(), rumor_id=uuid.uuid4().hex * 2,
        )
    order = await svcs["orders"].get_order(result["order_id"])
    assert order["protocol"] == "gamma" and order["state"] == "invoice_pending"
    invoice = (await svcs["settlement"]._core_payments_by_external_id(
        f"infinitemarkets:{order['id']}",
    ))[0]
    return order, product, invoice


@pytest.mark.parametrize("damage", ["healthy", "strong", "reasonless", "manual", "unknown",
                                    "expired", "lost", "corrupt", "status", "identity"])
async def test_review_gamma_request_admission(runtime_env, monkeypatch, damage):
    from infinitemarkets import crypto
    from infinitemarkets.db import DomainTransaction
    from infinitemarkets.services import order_messages
    from infinitemarkets.settings import ext_settings

    svcs = _svcs()
    order, product, original = await _review_gamma_timeout(runtime_env, monkeypatch)
    async with DomainTransaction() as tx:
        if damage in ("strong", "reasonless", "manual", "unknown"):
            await tx.execute("UPDATE orders SET payment_exception = :h, "
                             "payment_exception_reason = :r, payment_exception_resolution = :s "
                             "WHERE id = :o", {"o": order["id"],
                              "h": damage in ("strong", "reasonless"),
                              "r": "settlement-wallet-mismatch" if damage == "strong" else None,
                              "s": "refund_requested" if damage == "manual" else
                              "legacy-other" if damage == "unknown" else None})
    await svcs["settlement"].reconcile()
    requests = await _row("SELECT COUNT(*) AS n FROM infinitemarkets.order_messages "
                          "WHERE order_id = :o AND semantic_kind = 'payment-request'",
                          {"o": order["id"]})
    if damage in ("strong", "reasonless", "manual", "unknown"):
        assert requests["n"] == 0, "reconciliation must not admit a protected type-2 request"
    elif damage == "healthy":
        assert requests["n"] == 1
        row = await _row("SELECT id, payload_enc FROM infinitemarkets.outbox_events "
                         "WHERE aggregate_type = 'order_msg' AND aggregate_id = :a",
                         {"a": f"{order['id']}:1"})
        ver = crypto.envelope_version(row["payload_enc"])
        descriptor = json.loads(crypto.decrypt(
            row["payload_enc"], ext_settings().master_keys[ver], record_id=row["id"],
            table="outbox_events", column="payload_enc", key_version=ver,
        ))
        assert ["payment", "lightning", original.bolt11] in descriptor["tags"]
        assert descriptor["type"] == "2"
        assert descriptor["author_pubkey"] == await _merchant_pubkey(runtime_env)
        assert descriptor["recipient_pubkey"] != descriptor["author_pubkey"]
    else:
        async with DomainTransaction() as tx:
            await tx.execute("DELETE FROM order_messages WHERE order_id = :o "
                             "AND semantic_kind = 'payment-request'", {"o": order["id"]})
            await tx.execute("DELETE FROM outbox_events WHERE aggregate_type = 'order_msg' "
                             "AND aggregate_id = :a", {"a": f"{order['id']}:1"})
            if damage == "expired":
                async def expired_clock(self):
                    return int(original.expiry.timestamp()) + 1
                monkeypatch.setattr(DomainTransaction, "now", expired_clock)
            elif damage == "lost":
                await svcs["orders"].release_reservations(
                    tx, order_id=order["id"], to_state="released", now=await tx.now(),
                )
            elif damage == "corrupt":
                await tx.execute("UPDATE products SET stock_reserved = 1 WHERE id = :p",
                                 {"p": product["id"]})
            elif damage == "status":
                await tx.execute("UPDATE payments SET status = 'expired' WHERE order_id = :o",
                                 {"o": order["id"]})
            elif damage == "identity":
                await tx.execute("UPDATE payments SET checking_id_enc = NULL WHERE order_id = :o",
                                 {"o": order["id"]})
        before = await _hard01_snapshot(order["id"])
        async with DomainTransaction() as tx:
            stale = await svcs["orders"]._order_row(tx, order["id"])
            assert await order_messages.enqueue_payment_request(
                tx, stale, bolt11=original.bolt11, expiration=int(original.expiry.timestamp()),
            ) is None
        assert await _hard01_snapshot(order["id"]) == before
    before = await _hard01_snapshot(order["id"])
    await order_messages.reenqueue_payment_requests()
    assert await _hard01_snapshot(order["id"]) == before
    assert len(await svcs["settlement"]._core_payments_by_external_id(
        f"infinitemarkets:{order['id']}",
    )) == 1


@pytest.mark.parametrize("interleave", ["cancel", "projection", "deadline"])
async def test_review_gamma_selection_before_cancellation(runtime_env, monkeypatch, interleave):
    from infinitemarkets.db import DomainTransaction, dialect
    from infinitemarkets.services import order_messages

    svcs = _svcs()
    order, _, original = await _review_gamma_timeout(runtime_env, monkeypatch)
    await svcs["checkout"].attach_payment(
        order_id=order["id"], payment=original, now=int(time.time()),
    )
    selected, resume = asyncio.Event(), asyncio.Event()
    enqueue = order_messages.enqueue_payment_request
    pids = {}

    async def pause(tx, current, **kwargs):
        if current["id"] == order["id"] and dialect() == "postgres":
            pids["request"] = (await tx.fetch_one("SELECT pg_backend_pid() AS pid"))["pid"]
            selected.set()
            await asyncio.wait_for(resume.wait(), 5)
        return await enqueue(tx, current, **kwargs)

    enter = DomainTransaction.__aenter__

    async def pause_entry(self):
        if (dialect() == "sqlite" and not selected.is_set()
                and asyncio.current_task().get_name() == "review-request-repair"):
            selected.set()
            await asyncio.wait_for(resume.wait(), 5)
        return await enter(self)

    monkeypatch.setattr(DomainTransaction, "__aenter__", pause_entry)
    monkeypatch.setattr(order_messages, "enqueue_payment_request", pause)
    worker = asyncio.create_task(order_messages.reenqueue_payment_requests(),
                                 name="review-request-repair")
    try:
        await asyncio.wait_for(selected.wait(), 5)
        async with DomainTransaction() as tx:
            if dialect() == "postgres":
                pids["cancel"] = (await tx.fetch_one("SELECT pg_backend_pid() AS pid"))["pid"]
            current = await svcs["orders"]._order_row(tx, order["id"])
            if interleave == "cancel":
                await svcs["orders"]._cancel_order_in_tx(
                    tx, current, actor="buyer", reason=None,
                    merchant_context=None, now=await tx.now(),
                )
            elif interleave == "projection":
                await tx.execute("UPDATE payments SET status = 'expired' WHERE order_id = :o",
                                 {"o": order["id"]})
            else:
                async def expired_clock(self):
                    return int(original.expiry.timestamp()) + 1

                monkeypatch.setattr(DomainTransaction, "now", expired_clock)
        before = await _hard01_snapshot(order["id"])
        resume.set()
        await asyncio.wait_for(worker, 8)
        if dialect() == "postgres":
            assert len(set(pids.values())) == 2
        assert await _hard01_snapshot(order["id"]) == before
    finally:
        resume.set()
        if not worker.done():
            worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


@pytest.mark.parametrize("operation", ["attachment", "settlement"])
@pytest.mark.parametrize("lock", ["orders", "products"])
async def test_review_deadline_after_financial_lock_wait(runtime_env, monkeypatch, operation, lock):
    from infinitemarkets.db import DomainTransaction, dialect

    svcs = _svcs()
    if operation == "attachment":
        order, product, _, payment = await _hard03_unknown_invoice(runtime_env, monkeypatch)
    else:
        order, product, _ = await _new_order(runtime_env, scope=uuid.uuid4().hex)
        payment = await _settle_core_payment(order["id"], order["total_sat"])
    deadline = int(payment.expiry.timestamp())
    clock = [deadline - 1]
    occupied, waiting, resume = asyncio.Event(), asyncio.Event(), asyncio.Event()
    fetch = DomainTransaction.fetch_one
    enter = DomainTransaction.__aenter__
    pids = {}

    async def current_time(self):
        return clock[0]

    async def observe_fetch(tx, sql, params=None):
        if (asyncio.current_task().get_name() == "review-deadline-worker"
                and dialect() == "postgres" and lock in sql and sql.endswith(tx.for_update)):
            pids["worker"] = (await fetch(tx, "SELECT pg_backend_pid() AS pid"))["pid"]
            waiting.set()
        return await fetch(tx, sql, params)

    async def observe_enter(self):
        if asyncio.current_task().get_name() == "review-deadline-worker" and dialect() == "sqlite":
            waiting.set()
        return await enter(self)

    async def holder():
        async with DomainTransaction() as tx:
            await tx.fetch_one(f"SELECT id FROM {tx.table(lock)} WHERE id = :i" + tx.for_update,
                               {"i": order["id"] if lock == "orders" else product["id"]})
            if dialect() == "postgres":
                pids["holder"] = (await tx.fetch_one("SELECT pg_backend_pid() AS pid"))["pid"]
            occupied.set()
            await asyncio.wait_for(resume.wait(), 5)

    monkeypatch.setattr(DomainTransaction, "now", current_time)
    monkeypatch.setattr(DomainTransaction, "fetch_one", observe_fetch)
    monkeypatch.setattr(DomainTransaction, "__aenter__", observe_enter)
    monkeypatch.setattr(svcs["settlement"], "_now", lambda: deadline - 1)
    workers = [asyncio.create_task(holder())]
    try:
        await asyncio.wait_for(occupied.wait(), 5)
        action = (svcs["checkout"].attach_payment(order_id=order["id"], payment=payment,
                                                now=deadline - 1)
                  if operation == "attachment" else
                  svcs["settlement"].confirm_settlement(order_id=order["id"], core_payment=payment))
        worker = asyncio.create_task(action, name="review-deadline-worker")
        workers.append(worker)
        await asyncio.wait_for(waiting.wait(), 5)
        clock[0] = deadline + 1
        resume.set()
        await asyncio.wait_for(asyncio.gather(*workers), 8)
        if dialect() == "postgres":
            assert len(set(pids.values())) == 2
        async with DomainTransaction() as tx:
            assert await tx.now() > deadline
        current = await svcs["orders"].get_order(order["id"])
        assert current["state"] == "cancelled" and current["payment_exception"]
        if operation == "attachment":
            assert worker.result()["bolt11"] is None
        stock = await _row("SELECT stock_on_hand, stock_reserved FROM infinitemarkets.products "
                           "WHERE id = :p", {"p": product["id"]})
        assert stock == {"stock_on_hand": 10, "stock_reserved": 0}
    finally:
        resume.set()
        for task in workers:
            if not task.done():
                task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)


@pytest.mark.parametrize("field", ["quantity", "consumed_qty", "accepted_allocated_qty",
                                   "backordered_qty"])
@pytest.mark.parametrize("kind", ["float", "boolean"])
async def test_review_ancestor_quantity_types_fail_closed(runtime_env, field, kind):
    from infinitemarkets.db import DomainTransaction
    from infinitemarkets.security import ProblemError

    svcs = _svcs()
    order, _, _ = await _new_order(runtime_env, qty=1, scope=uuid.uuid4().hex)
    await svcs["orders"].cancel_order(order_id=order["id"], actor="buyer", reason=None)
    paid = await _settle_core_payment(order["id"], order["total_sat"])
    await svcs["settlement"].invoice_listener(paid)
    await svcs["settlement"].resolve_exception(order_id=order["id"], action="accept")
    await svcs["orders"].cancel_order(order_id=order["id"], actor="merchant", reason="repeat")
    await svcs["settlement"].resolve_exception(order_id=order["id"], action="accept")
    async with DomainTransaction() as tx:
        chain = await svcs["orders"].confirmation_chain(tx, order)
        predecessor = chain[0]
        detail = predecessor["detail"]
        value = detail["inventory_accounting"]["items"][0][field]
        assert value in (0, 1)
        detail["inventory_accounting"]["items"][0][field] = (
            float(value) if kind == "float" else bool(value)
        )
        await tx.execute("UPDATE order_events SET detail_json = :d WHERE id = :i",
                         {"d": json.dumps(detail), "i": predecessor["id"]})
    before = await _hard01_snapshot(order["id"])
    async with DomainTransaction() as tx:
        current = await svcs["orders"]._order_row(tx, order["id"])
        assert not await svcs["orders"].fulfillment_authorized(tx, current)
    assert await _hard01_snapshot(order["id"]) == before
    await svcs["orders"].cancel_order(order_id=order["id"], actor="merchant", reason="review")
    before = await _hard01_snapshot(order["id"])
    with pytest.raises(ProblemError):
        await svcs["settlement"].resolve_exception(order_id=order["id"], action="accept")
    assert await _hard01_snapshot(order["id"]) == before


@pytest.mark.parametrize("damage", ["status", "checking", "corrupt", "expired", "lost"])
async def test_review_public_invoice_requires_live_identity(runtime_env, monkeypatch, damage):
    from infinitemarkets.db import DomainTransaction

    svcs = _svcs()
    key = uuid.uuid4().hex * 2
    order, product, response = await _new_order(runtime_env, key=key, scope=uuid.uuid4().hex)
    async with DomainTransaction() as tx:
        if damage == "status":
            await tx.execute("UPDATE payments SET status = 'expired' WHERE order_id = :o",
                             {"o": order["id"]})
        elif damage == "checking":
            await tx.execute("UPDATE payments SET checking_id_enc = NULL WHERE order_id = :o",
                             {"o": order["id"]})
        elif damage == "corrupt":
            await tx.execute("UPDATE payments SET bolt11_enc = :b WHERE order_id = :o",
                             {"b": b"invalid-envelope", "o": order["id"]})
        elif damage == "lost":
            await svcs["orders"].release_reservations(
                tx, order_id=order["id"], to_state="released", now=await tx.now(),
            )
        elif damage == "expired":
            async def expired_clock(self):
                return order["invoice_expiry"] + 1
            monkeypatch.setattr(DomainTransaction, "now", expired_clock)
    before = await _hard01_snapshot(order["id"])
    status = await runtime_env["client"].get(
        f"{API}/public/order-status", headers={"X-Order-Token": response["public_token"]},
    )
    assert status.status_code == 200, status.text
    assert status.json()["bolt11"] is None
    replay = await svcs["checkout"]._resume_order({"_resume_order_id": order["id"]}, now=0)
    assert replay["order"]["bolt11"] is None
    cached = await svcs["checkout"].checkout(
        payload={"merchant_pubkey": await _merchant_pubkey(runtime_env),
                 "items": [{"d_tag": product["d_tag"], "quantity": 2}]},
        idempotency_key=key, client_scope=uuid.uuid4().hex,
    )
    assert cached["order"]["bolt11"] is None, (
        "cached completed response must recheck invoice authority"
    )
    assert await _hard01_snapshot(order["id"]) == before


async def test_review_later_reconciliation_candidate_uses_current_clock(runtime_env, monkeypatch):
    from infinitemarkets.db import DomainTransaction

    svcs = _svcs()
    first, _, _, first_invoice = await _hard03_unknown_invoice(runtime_env, monkeypatch)
    later, _, _, later_invoice = await _hard03_unknown_invoice(runtime_env, monkeypatch)
    cutoff = min(int(first_invoice.expiry.timestamp()), int(later_invoice.expiry.timestamp())) - 1
    clock = [cutoff]
    attach = svcs["checkout"].attach_payment

    async def current_time(self):
        return clock[0]

    async def advance_later(**kwargs):
        if kwargs["order_id"] == later["id"]:
            clock[0] = int(later_invoice.expiry.timestamp()) + 1
        return await attach(**kwargs)

    monkeypatch.setattr(DomainTransaction, "now", current_time)
    monkeypatch.setattr(svcs["checkout"], "attach_payment", advance_later)
    report = await svcs["settlement"].reconcile(now=cutoff)
    attached = {row["order_id"]: row for row in report["attached"]}
    assert first["id"] in attached and later["id"] in attached
    assert attached[later["id"]]["state"] == "cancelled"
    assert attached[later["id"]]["bolt11"] is None
    current = await svcs["orders"].get_order(later["id"])
    assert current["payment_exception"] and current["payment_hash"] == later_invoice.payment_hash


async def test_review_gamma_discards_stale_caller_invoice(runtime_env, monkeypatch):
    from infinitemarkets import crypto
    from infinitemarkets.db import DomainTransaction
    from infinitemarkets.services import order_messages
    from infinitemarkets.settings import ext_settings

    svcs = _svcs()
    order, _, invoice = await _review_gamma_timeout(runtime_env, monkeypatch)
    await svcs["checkout"].attach_payment(
        order_id=order["id"], payment=invoice, now=int(time.time()),
    )
    async with DomainTransaction() as tx:
        intent = await order_messages.enqueue_payment_request(
            tx, order, bolt11="stale-untrusted-invoice", expiration=0,
        )
        assert intent
        row = await tx.fetch_one("SELECT payload_enc FROM outbox_events WHERE id = :i",
                                 {"i": intent})
        ver = crypto.envelope_version(row["payload_enc"])
        descriptor = json.loads(crypto.decrypt(
            row["payload_enc"], ext_settings().master_keys[ver], record_id=intent,
            table="outbox_events", column="payload_enc", key_version=ver,
        ))
        assert ["payment", "lightning", invoice.bolt11] in descriptor["tags"]
        assert ["expiration", str(int(invoice.expiry.timestamp()))] in descriptor["tags"]
        assert await order_messages.enqueue_payment_request(tx, order) is None
