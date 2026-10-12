"""Section 8.2/8.3/8.4/8.7 saga + settlement through the real host boot
(FakeWallet). Workers are cancelled — every step is driven explicitly so
the durable paths (projection-before-call, attach-regardless, settlement
idempotence, late-settlement exception, expiry, reconcile) are asserted
deterministically."""

from __future__ import annotations

import asyncio
import time
import uuid

import pytest
import pytest_asyncio

pytestmark = pytest.mark.runtime

ORIGIN = "https://shop.example"
API = "/infinitemarkets/api/v1"


@pytest_asyncio.fixture(scope="module", loop_scope="session", autouse=True)
async def _setup(runtime_env):
    ext = runtime_env["ext_module"]
    for task in list(ext._owned_tasks):  # noqa: SLF001
        task.cancel()
    await asyncio.sleep(0)

    client = runtime_env["client"]

    async def cookie() -> dict:
        if not client.cookies.get("gm_csrf"):
            await client.get(f"{API}/merchants/current")
        return {
            "Origin": ORIGIN,
            "X-CSRF-Token": client.cookies.get("gm_csrf"),
        }

    resp = await client.post(
        f"{API}/merchants",
        json={"wallet_id": runtime_env["wallet"].id,
              "display_name": "saga shop"},
        headers=await cookie(),
    )
    assert resp.status_code == 201, resp.text
    mid = resp.json()["id"]
    from infinitemarkets.db import DomainTransaction

    async with DomainTransaction() as tx:
        await tx.execute(
            "UPDATE merchants SET state = 'active' WHERE id = :m",
            {"m": mid},
        )
    resp = await client.post(
        f"{API}/categories",
        json={"name": "main", "default_currency": "SAT"},
        headers=await cookie(),
    )
    assert resp.status_code == 201, resp.text
    cid = resp.json()["id"]

    async def product(title, stock) -> dict:
        resp = await client.post(
            f"{API}/products",
            json={
                "category_id": cid, "title": title,
                "amount_minor": 500, "currency": "SAT",
                "visibility": "on-sale", "stock_on_hand": stock,
                "format": "digital",
            },
            headers=await cookie(),
        )
        assert resp.status_code == 201, resp.text
        return resp.json()

    runtime_env.update({
        "merchant_id": mid, "category_id": cid,
        "make_product": product, "cookie": cookie,
    })
    yield


def _svcs():
    import importlib

    return {
        name: importlib.import_module(f"infinitemarkets.services.{name}")
        for name in ("checkout", "orders", "settlement", "email")
    }


async def _mpk(runtime_env):
    from infinitemarkets.db import db

    async with db.connect() as conn:
        row = await conn.fetchone(
            "SELECT pubkey FROM infinitemarkets.merchants WHERE id = :m",
            {"m": runtime_env["merchant_id"]},
        )
    return row["pubkey"]


async def _new_order(runtime_env, *, qty=2, stock=10, title=None, key=None, scope="saga",
                     payload_extra=None):
    """A fresh product, checkout response, and persisted order."""
    svcs = _svcs()
    product = await runtime_env["make_product"](
        title or uuid.uuid4().hex[:8], stock
    )
    resp = await svcs["checkout"].checkout(
        payload={
            "merchant_pubkey": await _mpk(runtime_env),
            "items": [{"d_tag": product["d_tag"], "quantity": qty}],
            **(payload_extra or {}),
        },
        idempotency_key=key or uuid.uuid4().hex * 2,
        client_scope=scope,
    )
    from infinitemarkets.crypto import token_lookup_hash
    from infinitemarkets.db import db

    async with db.connect() as conn:
        order = dict(await conn.fetchone(
            "SELECT * FROM infinitemarkets.orders WHERE public_token_hash = :h",
            {"h": token_lookup_hash(resp["public_token"])},
        ))
    return order, product, resp


async def _row(sql, params):
    from infinitemarkets.db import db

    async with db.connect() as conn:
        return dict(await conn.fetchone(sql, params))


async def _core_row(sql, params):
    """A row from the CORE lnbits database (apipayments, wallets)."""
    from lnbits.core.db import db as core_db

    async with core_db.connect() as conn:
        return dict(await conn.fetchone(sql, params))


# --- §8.3 settlement --------------------------------------------------------------


async def _settle_core_payment(order_id: str, total_sat: int):
    """Pay the core invoice via FakeWallet and return the settled Payment."""
    from lnbits.wallets import get_funding_source

    core = await _core_row(
        "SELECT * FROM apipayments WHERE external_id = :e",
        {"e": f"infinitemarkets:{order_id}"},
    )
    funding = get_funding_source()
    resp = await funding.pay_invoice(
        core["bolt11"], fee_limit_msat=10_000
    )
    assert resp.ok, resp.error_message
    # The same function the host's paid_invoices_stream consumer invokes —
    # deterministic here instead of racing the producer task.
    from lnbits.core.services.payments import (
        update_invoice_from_paid_invoices_stream,
    )

    settled = await update_invoice_from_paid_invoices_stream(
        core["checking_id"]
    )
    assert settled is not None, "FakeWallet settlement did not land"
    assert settled.success
    from infinitemarkets.services.settlement import (
        _core_payments_by_external_id,  # noqa: SLF001
    )

    payments = await _core_payments_by_external_id(
        f"infinitemarkets:{order_id}"
    )
    assert len(payments) == 1
    return payments[0]


async def test_settlement_confirms_once(runtime_env):
    """FakeWallet pays the invoice -> listener -> confirmed; reservations
    consumed; stock decremented exactly once; double-delivery is a no-op."""
    svcs = _svcs()
    order, product, resp = await _new_order(runtime_env, qty=3, stock=10)
    assert order["state"] == "awaiting_payment"

    payment = await _settle_core_payment(order["id"], order["total_sat"])
    await svcs["settlement"].invoice_listener(payment)

    fresh = await _row(
        "SELECT * FROM infinitemarkets.orders WHERE id = :i",
        {"i": order["id"]},
    )
    assert fresh["state"] == "confirmed"
    proj = await _row(
        "SELECT * FROM infinitemarkets.payments WHERE order_id = :o",
        {"o": order["id"]},
    )
    assert proj["status"] == "settled"
    res = await _row(
        "SELECT state, COUNT(*) AS n FROM infinitemarkets.inventory_reservations"
        " WHERE order_id = :o GROUP BY state",
        {"o": order["id"]},
    )
    assert res["state"] == "consumed"
    prod = await _row(
        "SELECT stock_on_hand, stock_reserved FROM infinitemarkets.products"
        " WHERE id = :p",
        {"p": product["id"]},
    )
    assert prod["stock_on_hand"] == 10 - 3
    assert prod["stock_reserved"] == 0

    # Double-delivery: the listener again must be a no-op.
    await svcs["settlement"].invoice_listener(payment)
    prod2 = await _row(
        "SELECT stock_on_hand FROM infinitemarkets.products WHERE id = :p",
        {"p": product["id"]},
    )
    assert prod2["stock_on_hand"] == 10 - 3  # stock never decrements twice


async def test_digital_delivery_revealed_only_after_confirmed_payment(runtime_env):
    """Merchant delivery content is encrypted at rest, never public, and
    reaches the buyer only once LNbits settlement confirms the order."""
    svcs = _svcs()
    client = runtime_env["client"]
    secret = f"https://files.example/dl/{uuid.uuid4().hex}"
    resp = await client.post(
        f"{API}/products",
        json={
            "category_id": runtime_env["category_id"], "title": "zine",
            "amount_minor": 700, "currency": "SAT", "visibility": "on-sale",
            "stock_on_hand": 5, "format": "digital", "delivery_content": secret,
        },
        headers=await runtime_env["cookie"](),
    )
    assert resp.status_code == 201, resp.text
    product = resp.json()
    assert product["delivery_content"] == secret
    assert "delivery_enc" not in product

    raw = await _row(
        "SELECT delivery_enc FROM infinitemarkets.products WHERE id = :p",
        {"p": product["id"]},
    )
    assert raw["delivery_enc"] and secret.encode() not in bytes(raw["delivery_enc"])

    mpk = await _mpk(runtime_env)
    for url in (
        f"/infinitemarkets/p/{mpk}/{product['d_tag']}",
        f"{API}/public/products/{mpk}/{product['d_tag']}",
        f"{API}/products/{product['id']}/events",
    ):
        page = await client.get(url)
        assert page.status_code == 200, (url, page.text)
        assert secret not in page.text, url

    order_resp = await svcs["checkout"].checkout(
        payload={"merchant_pubkey": mpk,
                 "items": [{"d_tag": product["d_tag"], "quantity": 1}]},
        idempotency_key=uuid.uuid4().hex * 2, client_scope="delivery",
    )
    token = {"X-Order-Token": order_resp["public_token"]}
    status = (await client.get(f"{API}/public/order-status", headers=token)).json()
    assert status["state"] == "awaiting_payment"
    assert status["digital_delivery"] == []

    from infinitemarkets.crypto import token_lookup_hash

    order = await _row(
        "SELECT id, total_sat FROM infinitemarkets.orders WHERE public_token_hash = :h",
        {"h": token_lookup_hash(order_resp["public_token"])},
    )
    order_id, total = order["id"], order["total_sat"]
    payment = await _settle_core_payment(order_id, total)
    await svcs["settlement"].invoice_listener(payment)
    status = (await client.get(f"{API}/public/order-status", headers=token)).json()
    assert status["state"] == "confirmed"
    assert status["digital_delivery"] == [{"title": "zine", "content": secret}]

    from infinitemarkets.db import DomainTransaction

    async with DomainTransaction() as tx:
        await tx.execute(
            f"UPDATE {tx.table('orders')} SET payment_exception = TRUE WHERE id = :i",
            {"i": order_id},
        )
    status = (await client.get(f"{API}/public/order-status", headers=token)).json()
    assert status["digital_delivery"] == []

    body = svcs["email"]._render_body(  # noqa: SLF001
        {"event_type": "confirmed"}, {"state": "confirmed", "total_sat": total},
        [], {}, None, [{"title": "zine", "content": secret}],
    )
    assert secret in body


async def test_delivery_content_rejected_for_physical_products(runtime_env):
    client = runtime_env["client"]
    resp = await client.post(
        f"{API}/products",
        json={
            "category_id": runtime_env["category_id"], "title": "mug",
            "amount_minor": 700, "currency": "SAT", "visibility": "on-sale",
            "format": "physical", "delivery_content": "https://x.example/f",
        },
        headers=await runtime_env["cookie"](),
    )
    assert resp.status_code == 422, resp.text


async def test_settlement_foreign_payment_ignored(runtime_env):
    """A payment with another extension tag or wrong external id is not
    settlement evidence."""
    svcs = _svcs()
    order, _, _ = await _new_order(runtime_env)

    from lnbits.core.models.payments import Payment

    # Different extension -> ignored.
    fake = Payment(
        checking_id="x", payment_hash="y", wallet_id="w",
        amount=1000, status="success", memo="m",
        extension="other-extension",
        external_id=f"infinitemarkets:{order['id']}",
        fee=0, bolt11="",
    )
    await svcs["settlement"].invoice_listener(fake)
    fresh = await _row(
        "SELECT state FROM infinitemarkets.orders WHERE id = :i",
        {"i": order["id"]},
    )
    assert fresh["state"] == "awaiting_payment"


async def test_late_settlement_on_expired_order(runtime_env):
    """§8.4: a settled payment landing on an expired order marks the
    payment settled + payment_exception — no reopen, no consumption."""
    svcs = _svcs()
    order, product, resp = await _new_order(runtime_env, qty=2, stock=10)

    # Expire the order first (invoice unpaid past expiry).
    await svcs["settlement"].expire_order(order_id=order["id"], now=order["invoice_expiry"])
    fresh = await _row(
        "SELECT state FROM infinitemarkets.orders WHERE id = :i",
        {"i": order["id"]},
    )
    assert fresh["state"] == "expired"
    res = await _row(
        "SELECT state FROM infinitemarkets.inventory_reservations"
        " WHERE order_id = :o",
        {"o": order["id"]},
    )
    assert res["state"] == "expired"

    # Now the payment lands — settled-after-terminal-state exception.
    await _settle_core_payment(order["id"], order["total_sat"])
    result = await svcs["settlement"].confirm_settlement(
        order_id=order["id"], source="test"
    )
    assert result["action"] == "exception"
    fresh = await _row(
        "SELECT state, payment_exception FROM infinitemarkets.orders"
        " WHERE id = :i",
        {"i": order["id"]},
    )
    assert fresh["state"] == "expired"  # never auto-reopened
    assert fresh["payment_exception"] in (1, True)
    proj = await _row(
        "SELECT status FROM infinitemarkets.payments WHERE order_id = :o",
        {"o": order["id"]},
    )
    assert proj["status"] == "settled"
    prod = await _row(
        "SELECT stock_on_hand FROM infinitemarkets.products WHERE id = :p",
        {"p": product["id"]},
    )
    assert prod["stock_on_hand"] == 10  # nothing consumed

    # Merchant resolution: accept decrements available stock -> confirmed.
    resolved = await svcs["settlement"].resolve_exception(
        order_id=order["id"], action="accept",
    )
    assert resolved["action"] == "accepted"
    fresh = await _row(
        "SELECT state, payment_exception, payment_exception_resolution"
        " FROM infinitemarkets.orders WHERE id = :i",
        {"i": order["id"]},
    )
    assert fresh["state"] == "confirmed"
    assert fresh["payment_exception"] in (0, False)
    assert fresh["payment_exception_resolution"] == "accepted"
    prod = await _row(
        "SELECT stock_on_hand FROM infinitemarkets.products WHERE id = :p",
        {"p": product["id"]},
    )
    assert prod["stock_on_hand"] == 10 - 2


async def test_buyer_cancel_before_payment(runtime_env):
    """§7.1 buyer-cancel in awaiting_payment: reservations release, the
    projection survives for late-settlement detection, BOLT11 disappears
    from the public surface."""
    svcs = _svcs()
    order, product, resp = await _new_order(runtime_env, qty=2, stock=10)

    await svcs["orders"].cancel_order(
        order_id=order["id"], actor="buyer", reason=None,
    )
    fresh = await _row(
        "SELECT state FROM infinitemarkets.orders WHERE id = :i",
        {"i": order["id"]},
    )
    assert fresh["state"] == "cancelled"
    res = await _row(
        "SELECT state FROM infinitemarkets.inventory_reservations"
        " WHERE order_id = :o",
        {"o": order["id"]},
    )
    assert res["state"] == "released"
    proj = await _row(
        "SELECT status, bolt11_enc FROM infinitemarkets.payments"
        " WHERE order_id = :o",
        {"o": order["id"]},
    )
    # The projection is preserved (late-settlement detection needs it).
    assert proj["status"] == "pending"
    assert proj["bolt11_enc"] is not None
    prod = await _row(
        "SELECT stock_on_hand, stock_reserved FROM infinitemarkets.products"
        " WHERE id = :p",
        {"p": product["id"]},
    )
    assert prod["stock_on_hand"] == 10
    assert prod["stock_reserved"] == 0


async def test_hard01_status_cancellation_releases_atomically(runtime_env):
    svcs = _svcs()
    order, product, _ = await _new_order(runtime_env)
    response = await runtime_env["client"].post(
        f"{API}/merchants/{runtime_env['merchant_id']}/orders/{order['id']}/status",
        json={"to_state": "cancelled"},
        headers=await runtime_env["cookie"](),
    )
    assert response.status_code == 200, response.text
    stock = await _row(
        "SELECT stock_reserved FROM infinitemarkets.products WHERE id = :p",
        {"p": product["id"]},
    )
    assert stock["stock_reserved"] == 0
    from test_order_admin import _hard01_snapshot

    before = await _hard01_snapshot(order["id"])
    result = await svcs["orders"].cancel_order(order_id=order["id"], actor="merchant", reason=None)
    assert result["action"] == "no-op-already-cancelled"
    assert await _hard01_snapshot(order["id"]) == before
    payment = await _settle_core_payment(order["id"], order["total_sat"])
    await svcs["settlement"].invoice_listener(payment)
    fresh = await svcs["orders"].get_order(order["id"])
    assert fresh["state"] == "cancelled"
    assert fresh["payment_exception"]


@pytest.mark.parametrize("damage", ["unpaid", "absent", "partial", "hold"])
@pytest.mark.parametrize("state", ["confirmed", "processing", "completed"])
@pytest.mark.parametrize(
    "current,target",
    [
        ("pending", "processing"),
        ("processing", "shipped"),
        ("shipped", "delivered"),
        ("processing", "exception"),
        ("shipped", "exception"),
        ("exception", "processing"),
        ("exception", "shipped"),
    ],
)
async def test_hard01_settled_without_accounting_shipping(
    runtime_env, damage, state, current, target
):
    from test_order_admin import _hard01_snapshot

    from infinitemarkets.db import DomainTransaction

    svcs = _svcs()
    order, product, _ = await _new_order(runtime_env, scope=uuid.uuid4().hex)
    if damage != "unpaid":
        payment = await _settle_core_payment(order["id"], order["total_sat"])
        await svcs["settlement"].invoice_listener(payment)
    async with DomainTransaction() as tx:
        await tx.execute(
            "UPDATE orders SET state = :s, shipping_state = :c WHERE id = :o",
            {"s": state, "c": current, "o": order["id"]},
        )
        await tx.execute(
            "UPDATE products SET format = 'physical' WHERE id = :p", {"p": product["id"]}
        )
        if damage == "absent":
            await tx.execute(
                "DELETE FROM inventory_reservations WHERE order_id = :o", {"o": order["id"]}
            )
        elif damage == "partial":
            await tx.execute(
                "UPDATE inventory_reservations SET quantity = 1 WHERE order_id = :o",
                {"o": order["id"]},
            )
        elif damage == "hold":
            await tx.execute(
                "UPDATE orders SET payment_exception = TRUE WHERE id = :o", {"o": order["id"]}
            )
    before = await _hard01_snapshot(order["id"])
    response = await runtime_env["client"].post(
        f"{API}/merchants/{runtime_env['merchant_id']}/orders/{order['id']}/shipping",
        json={"shipping_state": target},
        headers=await runtime_env["cookie"](),
    )
    assert response.status_code == 422, response.text
    assert await _hard01_snapshot(order["id"]) == before


@pytest.mark.parametrize(
    "proof_damage",
    [
        "valid",
        "absent",
        "malformed",
        "negative",
        "boolean",
        "duplicate",
        "missing",
        "extra",
        "foreign_item",
        "foreign_product",
        "wrong_actor",
        "wrong_lineage",
        "wrong_total",
        "double_count",
        "wrong_backorder",
        "wrong_version",
        "digital_shortfall",
        "ambiguous_latest",
    ],
)
async def test_hard01_explicit_accepted_accounting_proof(runtime_env, proof_damage):
    from test_order_admin import _hard01_snapshot

    from infinitemarkets.db import DomainTransaction

    svcs = _svcs()
    order, product, _ = await _new_order(runtime_env, scope=uuid.uuid4().hex)
    await svcs["orders"].cancel_order(order_id=order["id"], actor="merchant", reason=None)
    payment = await _settle_core_payment(order["id"], order["total_sat"])
    await svcs["settlement"].invoice_listener(payment)
    async with DomainTransaction() as tx:
        item = dict(
            await tx.fetch_one("SELECT * FROM order_items WHERE order_id = :o", {"o": order["id"]})
        )
        entry = {
            "item_id": item["id"],
            "product_id": product["id"],
            "quantity": 2,
            "consumed_qty": 0,
            "accepted_allocated_qty": 1,
            "backordered_qty": 1,
        }
        proof = {"version": 1, "items": [entry], "parent_confirmation_id": None}
        if proof_damage == "negative":
            entry["accepted_allocated_qty"] = -1
        elif proof_damage == "boolean":
            entry["accepted_allocated_qty"] = True
        elif proof_damage == "duplicate":
            proof["items"].append(dict(entry))
        elif proof_damage == "missing":
            proof["items"] = []
        elif proof_damage == "extra":
            proof["items"].append({**entry, "item_id": uuid.uuid4().hex})
        elif proof_damage == "foreign_item":
            entry["item_id"] = uuid.uuid4().hex
        elif proof_damage == "foreign_product":
            entry["product_id"] = uuid.uuid4().hex
        elif proof_damage == "wrong_total":
            entry["quantity"] = 3
        elif proof_damage == "double_count":
            entry["consumed_qty"] = 1
            entry["accepted_allocated_qty"] = 0
        elif proof_damage == "wrong_backorder":
            entry["accepted_allocated_qty"] = 2
            entry["backordered_qty"] = 0
        elif proof_damage == "wrong_version":
            proof["version"] = 2
        if proof_damage != "digital_shortfall":
            await tx.execute(
                "UPDATE products SET format = 'physical' WHERE id = :p", {"p": product["id"]}
            )
        await tx.execute(
            "UPDATE order_items SET backordered_qty = 1 WHERE order_id = :o", {"o": order["id"]}
        )
        proof_time = int(time.time())
        await svcs["orders"].transition_order(
            tx,
            order_id=order["id"],
            to_state="confirmed",
            actor="merchant",
            reason="synthetic proof fixture",
            detail=None if proof_damage == "absent" else {"inventory_accounting": proof},
            now=proof_time,
        )
        if proof_damage == "ambiguous_latest":
            await svcs["orders"].transition_order(
                tx, order_id=order["id"], to_state="cancelled", actor="merchant",
                reason="synthetic repeated lifecycle", now=proof_time,
            )
            await svcs["orders"].transition_order(
                tx, order_id=order["id"], to_state="confirmed", actor="merchant",
                reason="synthetic repeated proof", detail={"inventory_accounting": proof},
                now=proof_time,
            )
        await tx.execute(
            "UPDATE orders SET payment_exception = FALSE, "
            "payment_exception_resolution = 'accepted', "
            "oversold = TRUE, shipping_state = 'processing' WHERE id = :o",
            {"o": order["id"]},
        )
        if proof_damage == "malformed":
            await tx.execute(
                "UPDATE order_events SET detail_json = '{' "
                "WHERE order_id = :o AND to_state = 'confirmed'",
                {"o": order["id"]},
            )
        elif proof_damage == "wrong_actor":
            await tx.execute(
                "UPDATE order_events SET actor = 'buyer' "
                "WHERE order_id = :o AND to_state = 'confirmed'",
                {"o": order["id"]},
            )
        elif proof_damage == "wrong_lineage":
            await tx.execute(
                "UPDATE order_events SET from_state = 'awaiting_payment' "
                "WHERE order_id = :o AND to_state = 'confirmed'",
                {"o": order["id"]},
            )
    before = await _hard01_snapshot(order["id"])
    fresh = await svcs["orders"].get_order(order["id"])
    async with DomainTransaction() as tx:
        assert await svcs["orders"].inventory_accounted(tx, fresh) is (
            proof_damage in ("valid", "digital_shortfall")
        )
        assert await svcs["orders"].fulfillment_authorized(tx, fresh) is (proof_damage == "valid")
        if proof_damage == "digital_shortfall":
            assert await svcs["orders"].digital_delivery(tx, fresh) == []
    assert await _hard01_snapshot(order["id"]) == before
    response = await runtime_env["client"].post(
        f"{API}/merchants/{runtime_env['merchant_id']}/orders/{order['id']}/shipping",
        json={"shipping_state": "shipped"},
        headers=await runtime_env["cookie"](),
    )
    assert response.status_code == (200 if proof_damage == "valid" else 422), response.text
    if proof_damage != "valid":
        assert await _hard01_snapshot(order["id"]) == before


async def test_hard01_fresh_accept_retains_authoritative_fulfillment(runtime_env):
    from infinitemarkets.db import DomainTransaction

    svcs = _svcs()
    order, _, _ = await _new_order(runtime_env, scope=uuid.uuid4().hex)
    await svcs["orders"].cancel_order(order_id=order["id"], actor="merchant", reason=None)
    payment = await _settle_core_payment(order["id"], order["total_sat"])
    await svcs["settlement"].invoice_listener(payment)
    response = await runtime_env["client"].post(
        f"{API}/merchants/{runtime_env['merchant_id']}/orders/{order['id']}/resolve-exception",
        json={"action": "accept"},
        headers=await runtime_env["cookie"](),
    )
    assert response.status_code == 200, response.text
    fresh = await svcs["orders"].get_order(order["id"])
    assert fresh["state"] == "confirmed"
    assert fresh["payment_exception_resolution"] == "accepted"
    async with DomainTransaction() as tx:
        assert await svcs["orders"].fulfillment_authorized(tx, fresh) is True


async def test_hard01_cancel_rolls_back_inventory_and_intents(runtime_env, monkeypatch):
    from test_order_admin import _hard01_snapshot

    svcs = _svcs()
    order, _, _ = await _new_order(runtime_env)
    before = await _hard01_snapshot(order["id"])

    async def fail_after_release(*args, **kwargs):
        raise RuntimeError("synthetic intent failure")

    monkeypatch.setattr(svcs["orders"], "enqueue_email_intents", fail_after_release)
    with pytest.raises(RuntimeError, match="synthetic intent failure"):
        await svcs["orders"].cancel_order(
            order_id=order["id"],
            actor="merchant",
            reason=None,
            merchant_context={"notify_emails": [], "notify_events": {}},
        )
    assert await _hard01_snapshot(order["id"]) == before


async def test_hard01_concurrent_cancel_releases_once(runtime_env):
    svcs = _svcs()
    order, product, _ = await _new_order(runtime_env)
    results = await asyncio.wait_for(
        asyncio.gather(
            *(
                svcs["orders"].cancel_order(order_id=order["id"], actor="merchant", reason=None)
                for _ in range(2)
            )
        ),
        timeout=5,
    )
    assert sorted(result["action"] for result in results) == [
        "cancelled",
        "no-op-already-cancelled",
    ]
    stock = await _row(
        "SELECT stock_reserved FROM infinitemarkets.products WHERE id = :p", {"p": product["id"]}
    )
    assert stock["stock_reserved"] == 0
    events = await _row(
        "SELECT COUNT(*) AS n FROM infinitemarkets.order_events "
        "WHERE order_id = :o AND to_state = 'cancelled'",
        {"o": order["id"]},
    )
    assert events["n"] == 1


async def test_hard01_paid_cancellation_requires_reason(runtime_env):
    from test_order_admin import _hard01_snapshot

    svcs = _svcs()
    order, _, _ = await _new_order(runtime_env)
    payment = await _settle_core_payment(order["id"], order["total_sat"])
    await svcs["settlement"].invoice_listener(payment)
    await runtime_env["client"].post(
        f"{API}/merchants/{runtime_env['merchant_id']}/orders/{order['id']}/status",
        json={"to_state": "processing"},
        headers=await runtime_env["cookie"](),
    )
    url = f"{API}/merchants/{runtime_env['merchant_id']}/orders/{order['id']}"
    before = await _hard01_snapshot(order["id"])
    for path, body in (
        ("status", {"to_state": "cancelled"}),
        ("cancel", {}),
        ("cancel", {"reason": "   "}),
    ):
        response = await runtime_env["client"].post(
            f"{url}/{path}",
            json=body,
            headers=await runtime_env["cookie"](),
        )
        assert response.status_code == 422, response.text
        assert await _hard01_snapshot(order["id"]) == before
    response = await runtime_env["client"].post(
        f"{url}/cancel",
        json={"reason": "manual refund required"},
        headers=await runtime_env["cookie"](),
    )
    assert response.status_code == 200, response.text


async def test_invoice_creation_unknown_never_duplicates(runtime_env):
    """§8.2 step 4: an InvoiceError(pending)/timeout marks the projection
    creation_unknown + payment_exception — begin_saga never retries the
    external call, reconciliation recovers by exact external id."""
    svcs = _svcs()
    checkout = svcs["checkout"]
    product = await runtime_env["make_product"]("crashy", 5)
    resp = await checkout.checkout(
        payload={
            "merchant_pubkey": await _mpk(runtime_env),
            "items": [{"d_tag": product["d_tag"], "quantity": 1}],
        },
        idempotency_key=uuid.uuid4().hex * 2,
        client_scope="saga2",
    )
    from infinitemarkets.crypto import token_lookup_hash
    from infinitemarkets.db import db

    async with db.connect() as conn:
        order = dict(await conn.fetchone(
            "SELECT * FROM infinitemarkets.orders WHERE public_token_hash = :h",
            {"h": token_lookup_hash(resp["public_token"])},
        ))
    assert order["state"] == "awaiting_payment"

    # Simulate the unknown outcome directly on the projection.
    from infinitemarkets.db import DomainTransaction

    async with DomainTransaction() as tx:
        await tx.execute(
            "UPDATE payments SET status = 'creation_unknown'"
            " WHERE order_id = :o",
            {"o": order["id"]},
        )
    # Reconciliation finds the matching core payment by exact external id
    # and attaches it (the crash-window path).
    report = await svcs["settlement"].reconcile()
    assert any(
        a["order_id"] == order["id"] for a in report["attached"]
    ), report
    proj = await _row(
        "SELECT status FROM infinitemarkets.payments WHERE order_id = :o",
        {"o": order["id"]},
    )
    assert proj["status"] == "pending"
    # Exactly one core invoice exists — reconciliation never creates one.
    core = await _core_row(
        "SELECT COUNT(*) AS n FROM apipayments WHERE external_id = :e",
        {"e": f"infinitemarkets:{order['id']}"},
    )
    assert core["n"] == 1


async def test_reconcile_resumes_received_order(runtime_env, monkeypatch):
    """§8.7: a committed 'received' order (crash between intake and saga)
    resumes through begin_saga — never abandoned."""
    svcs = _svcs()
    checkout = svcs["checkout"]
    product = await runtime_env["make_product"]("resume-me", 5)

    # Insert the intake tx only — monkeypatch begin_saga to a no-op so the
    # order stays 'received'.
    from infinitemarkets.db import DomainTransaction, db

    mpk = await _mpk(runtime_env)
    begin = checkout.begin_saga

    async def pause_saga(**kwargs):
        return {"state": "received"}

    monkeypatch.setattr(checkout, "begin_saga", pause_saga)
    resp = await checkout.checkout(
        payload={
            "merchant_pubkey": mpk,
            "items": [{"d_tag": product["d_tag"], "quantity": 1}],
        },
        idempotency_key=uuid.uuid4().hex * 2,
        client_scope="saga3",
    )
    monkeypatch.setattr(checkout, "begin_saga", begin)
    from infinitemarkets.crypto import token_lookup_hash

    async with db.connect() as conn:
        order = dict(await conn.fetchone(
            "SELECT * FROM infinitemarkets.orders WHERE public_token_hash = :h",
            {"h": token_lookup_hash(resp["public_token"])},
        ))
    # Force the order back to received + drop its saga artifacts (the
    # crash happened before begin_saga ran).
    async with DomainTransaction() as tx:
        await tx.execute(
            "UPDATE orders SET state = 'received' WHERE id = :i",
            {"i": order["id"]},
        )
        await tx.execute(
            "DELETE FROM payments WHERE order_id = :o",
            {"o": order["id"]},
        )
        await tx.execute(
            "DELETE FROM inventory_reservations WHERE order_id = :o",
            {"o": order["id"]},
        )
    report = await svcs["settlement"].reconcile()
    assert any(
        r.get("state") == "awaiting_payment" for r in report["resumed"]
    ), report
    fresh = await _row(
        "SELECT state FROM infinitemarkets.orders WHERE id = :i",
        {"i": order["id"]},
    )
    assert fresh["state"] == "awaiting_payment"
    proj = await _row(
        "SELECT status FROM infinitemarkets.payments WHERE order_id = :o",
        {"o": order["id"]},
    )
    assert proj["status"] == "pending"


async def test_reservation_expiry_releases_once(runtime_env):
    """§8.4: an expired held reservation releases exactly once; the
    awaiting_payment order whose invoice expired transitions -> expired."""
    svcs = _svcs()
    order, product, resp = await _new_order(runtime_env, qty=2, stock=10)

    # Push the reservation expiry into the past.
    from infinitemarkets.db import DomainTransaction

    async with DomainTransaction() as tx:
        await tx.execute(
            "UPDATE inventory_reservations SET expires_at = 1"
            " WHERE order_id = :o",
            {"o": order["id"]},
        )
    result = await svcs["settlement"].reservation_expiry_pass(now=order["invoice_expiry"])
    assert result["expired_orders"] >= 1
    fresh = await _row(
        "SELECT state FROM infinitemarkets.orders WHERE id = :i",
        {"i": order["id"]},
    )
    assert fresh["state"] == "expired"
    res = await _row(
        "SELECT state FROM infinitemarkets.inventory_reservations"
        " WHERE order_id = :o",
        {"o": order["id"]},
    )
    assert res["state"] == "expired"
    prod = await _row(
        "SELECT stock_on_hand, stock_reserved FROM infinitemarkets.products"
        " WHERE id = :p",
        {"p": product["id"]},
    )
    assert prod["stock_on_hand"] == 10
    assert prod["stock_reserved"] == 0
    # Second pass: nothing left to release (exactly-once).
    result2 = await svcs["settlement"].reservation_expiry_pass()
    assert result2["released"] == 0


async def test_kill_before_callback_reconcile_confirms(runtime_env):
    """§8.7: the listener is memory-only — a settled core payment with no
    callback delivery is recovered by reconciliation, exactly once."""
    svcs = _svcs()
    order, product, resp = await _new_order(runtime_env, qty=2, stock=10)

    # Pay the invoice but NEVER invoke the listener — the kill between
    # settlement and callback means only the core row carries truth.
    await _settle_core_payment(order["id"], order["total_sat"])
    fresh = await _row(
        "SELECT state FROM infinitemarkets.orders WHERE id = :i",
        {"i": order["id"]},
    )
    assert fresh["state"] == "awaiting_payment"  # nothing confirmed yet

    report = await svcs["settlement"].reconcile()
    assert any(
        c["order_id"] == order["id"] for c in report["confirmed"]
    ), report
    fresh = await _row(
        "SELECT state FROM infinitemarkets.orders WHERE id = :i",
        {"i": order["id"]},
    )
    assert fresh["state"] == "confirmed"
    prod = await _row(
        "SELECT stock_on_hand FROM infinitemarkets.products WHERE id = :p",
        {"p": product["id"]},
    )
    assert prod["stock_on_hand"] == 10 - 2

    # A second pass cannot confirm twice.
    report2 = await svcs["settlement"].reconcile()
    assert not any(
        c["order_id"] == order["id"] for c in report2["confirmed"]
    )
    prod = await _row(
        "SELECT stock_on_hand FROM infinitemarkets.products WHERE id = :p",
        {"p": product["id"]},
    )
    assert prod["stock_on_hand"] == 10 - 2


async def test_amount_and_wallet_mismatch_quarantine(runtime_env):
    """§8.3 verification: a matching-external-id payment with the wrong
    amount or a foreign wallet is NEVER settlement evidence — the order
    quarantines with a bounded reason and nothing confirms or consumes."""
    svcs = _svcs()
    order_amt, product_amt, _ = await _new_order(
        runtime_env, qty=2, stock=10
    )
    order_wal, product_wal, _ = await _new_order(
        runtime_env, qty=2, stock=10
    )

    paid_amount = await _settle_core_payment(order_amt["id"], order_amt["total_sat"])
    paid_wallet = await _settle_core_payment(order_wal["id"], order_wal["total_sat"])

    # Wrong amount (500 vs the order's 1000 sat).
    bad_amount = paid_amount.copy(update={"amount": 500_000})
    await svcs["settlement"].invoice_listener(bad_amount)

    # Right amount (qty 2 x 500 = 1000 sat), foreign wallet.
    bad_wallet = paid_wallet.copy(update={"wallet_id": "foreign-wallet"})
    await svcs["settlement"].invoice_listener(bad_wallet)

    for order, reason in (
        (order_amt, "settlement-amount-mismatch"),
        (order_wal, "settlement-wallet-mismatch"),
    ):
        fresh = await _row(
            "SELECT state, payment_exception, payment_exception_reason"
            " FROM infinitemarkets.orders WHERE id = :i",
            {"i": order["id"]},
        )
        assert fresh["state"] == "awaiting_payment", reason
        assert fresh["payment_exception"] in (1, True)
        assert fresh["payment_exception_reason"] == reason
        proj = await _row(
            "SELECT status FROM infinitemarkets.payments WHERE order_id = :o",
            {"o": order["id"]},
        )
        assert proj["status"] == "pending"  # never marked settled
        res = await _row(
            "SELECT state FROM infinitemarkets.inventory_reservations"
            " WHERE order_id = :o",
            {"o": order["id"]},
        )
        assert res["state"] == "held"  # never consumed

    for product in (product_amt, product_wal):
        prod = await _row(
            "SELECT stock_on_hand FROM infinitemarkets.products WHERE id = :p",
            {"p": product["id"]},
        )
        assert prod["stock_on_hand"] == 10


async def test_lease_fencing(runtime_env, monkeypatch):
    """§10/§14: one live holder per task lease — a second worker gets
    None while the lease is held; expiry allows takeover and the fencing
    token strictly increases."""
    import importlib

    tasks = importlib.import_module("infinitemarkets.services.tasks")
    name = f"drill-{uuid.uuid4().hex[:8]}"

    monkeypatch.setattr(tasks, "WORKER_ID", "holder-A")
    token_a = await tasks._acquire_lease(name)  # noqa: SLF001
    assert token_a == 1

    # A competing worker cannot take a live lease.
    monkeypatch.setattr(tasks, "WORKER_ID", "holder-B")
    assert await tasks._acquire_lease(name) is None  # noqa: SLF001

    # The holder renews — fencing token increments per renewal.
    monkeypatch.setattr(tasks, "WORKER_ID", "holder-A")
    token_a2 = await tasks._acquire_lease(name)  # noqa: SLF001
    assert token_a2 > token_a

    # Expire the lease -> takeover with a strictly larger token.
    from infinitemarkets.db import DomainTransaction

    async with DomainTransaction() as tx:
        await tx.execute(
            "UPDATE task_leases SET leased_until = 1 WHERE name = :n",
            {"n": name},
        )
    monkeypatch.setattr(tasks, "WORKER_ID", "holder-B")
    token_b = await tasks._acquire_lease(name)  # noqa: SLF001
    assert token_b is not None and token_b > token_a2


async def test_duplicate_attachment_preserves_settled_projection(runtime_env):
    svcs = _svcs()
    order, product, _ = await _new_order(runtime_env, qty=1)
    payment = await _settle_core_payment(order["id"], order["total_sat"])
    await svcs["settlement"].invoice_listener(payment)
    await svcs["checkout"].attach_payment(order_id=order["id"], payment=payment, now=1)
    projection = await _row(
        "SELECT status FROM infinitemarkets.payments WHERE order_id = :o",
        {"o": order["id"]},
    )
    assert projection["status"] == "settled"
    await svcs["settlement"].invoice_listener(payment)
    fresh = await _row(
        "SELECT state, payment_exception FROM infinitemarkets.orders WHERE id = :i",
        {"i": order["id"]},
    )
    assert fresh["state"] == "confirmed"
    assert not fresh["payment_exception"]
    stock = await _row(
        "SELECT stock_on_hand FROM infinitemarkets.products WHERE id = :p",
        {"p": product["id"]},
    )
    assert stock["stock_on_hand"] == 9


async def test_reconciliation_verifies_payment_amount(runtime_env, monkeypatch):
    settlement = _svcs()["settlement"]
    order, product, _ = await _new_order(runtime_env, qty=1)
    lookup = settlement._core_payments_by_external_id
    payment = (await lookup(f"infinitemarkets:{order['id']}"))[0]
    wrong = payment.copy(update={"amount": payment.amount + 1000, "status": "success"})

    async def mismatched(external_id):
        if external_id == f"infinitemarkets:{order['id']}":
            return [wrong]
        return await lookup(external_id)

    monkeypatch.setattr(settlement, "_core_payments_by_external_id", mismatched)
    await settlement.reconcile()
    fresh = await _row(
        "SELECT state, payment_exception, payment_exception_reason"
        " FROM infinitemarkets.orders WHERE id = :i",
        {"i": order["id"]},
    )
    assert fresh["state"] == "awaiting_payment"
    assert fresh["payment_exception"]
    assert fresh["payment_exception_reason"] == "settlement-amount-mismatch"
    stock = await _row(
        "SELECT stock_on_hand FROM infinitemarkets.products WHERE id = :p",
        {"p": product["id"]},
    )
    assert stock["stock_on_hand"] == 10


async def test_reconciliation_recovers_late_payment_without_callback(runtime_env):
    settlement = _svcs()["settlement"]
    order, product, _ = await _new_order(runtime_env, qty=1)
    await settlement.expire_order(order_id=order["id"], now=order["invoice_expiry"])
    await _settle_core_payment(order["id"], order["total_sat"])
    await settlement.reconcile()
    projection = await _row(
        "SELECT status FROM infinitemarkets.payments WHERE order_id = :o",
        {"o": order["id"]},
    )
    assert projection["status"] == "settled"
    fresh = await _row(
        "SELECT state, payment_exception FROM infinitemarkets.orders WHERE id = :i",
        {"i": order["id"]},
    )
    assert fresh["state"] == "expired"
    assert fresh["payment_exception"]
    stock = await _row(
        "SELECT stock_on_hand, stock_reserved FROM infinitemarkets.products WHERE id = :p",
        {"p": product["id"]},
    )
    assert stock == {"stock_on_hand": 10, "stock_reserved": 0}


async def test_stale_expiry_worker_cannot_release_inventory(runtime_env, monkeypatch):
    from infinitemarkets.services import tasks

    order, _, _ = await _new_order(runtime_env, qty=1)
    from infinitemarkets.db import DomainTransaction

    async with DomainTransaction() as tx:
        await tx.execute(
            f"UPDATE {tx.table('inventory_reservations')} SET expires_at = 1 WHERE order_id = :o",
            {"o": order["id"]},
        )
    current = await tasks._acquire_lease("reservation_expiry")
    assert current is not None

    async def stale(name, **kwargs):
        return current - 1

    async def stop(*args):
        raise asyncio.CancelledError()

    with monkeypatch.context() as patch:
        patch.setattr(tasks, "_acquire_lease", stale)
        from types import SimpleNamespace

        patch.setattr(tasks, "asyncio", SimpleNamespace(
            sleep=stop, CancelledError=asyncio.CancelledError,
        ))
        with pytest.raises(asyncio.CancelledError):
            await tasks.reservation_expiry()
    reservation = await _row(
        "SELECT state FROM infinitemarkets.inventory_reservations WHERE order_id = :o",
        {"o": order["id"]},
    )
    assert reservation["state"] == "held"
    fresh = await _row("SELECT state FROM infinitemarkets.orders WHERE id = :o", {"o": order["id"]})
    assert fresh["state"] == "awaiting_payment"


async def test_settlement_enqueues_addressed_stock_publication(runtime_env):
    order, product, _ = await _new_order(runtime_env, qty=1)
    payment = await _settle_core_payment(order["id"], order["total_sat"])
    await _svcs()["settlement"].invoice_listener(payment)
    row = await _row(
        "SELECT * FROM infinitemarkets.outbox_events WHERE aggregate_id = :p"
        " AND event_kind = 30402 ORDER BY aggregate_revision DESC LIMIT 1",
        {"p": product["id"]},
    )
    assert row["aggregate_type"] == "products"
    assert row["event_address"].endswith(":" + product["d_tag"])
    assert row["aggregate_revision"] > 0
    from infinitemarkets.services.outbox import render_intent

    event = await render_intent(row)
    assert event["kind"] == 30402
    assert ["stock", "9"] in event["tags"]


@pytest.mark.parametrize("recent_update", [False, True])
async def test_retention_erases_all_terminal_order_private_copies(runtime_env, recent_update):
    from infinitemarkets.db import DomainTransaction

    order, _, _ = await _new_order(runtime_env, qty=1)
    now = int(time.time())
    async with DomainTransaction() as tx:
        await tx.execute(
            f"UPDATE {tx.table('orders')} SET state = 'cancelled', updated_at = :n WHERE id = :o",
            {"o": order["id"], "n": now if recent_update else 1},
        )
        await tx.execute(
            f"INSERT INTO {tx.table('order_events')}"
            " (id, order_id, from_state, to_state, actor, detail_json, created_at)"
            " VALUES (:i, :o, 'awaiting_payment', 'cancelled', 'merchant', '{}', 1)",
            {"i": uuid.uuid4().hex, "o": order["id"]},
        )
        await tx.execute(
            f"INSERT INTO {tx.table('order_fulfillment')} (order_id, tracking_enc) VALUES (:o, :v)",
            {"o": order["id"], "v": b"opaque-tracking"},
        )
        await tx.execute(
            f"INSERT INTO {tx.table('email_queue')}"
            " (id, merchant_id, order_id, channel, event_type,"
            " recipient_enc, recipient_hash, state)"
            " VALUES (:i, :m, :o, 'customer', 'confirmed', :v, 'retention-recipient', 'failed')",
            {"i": uuid.uuid4().hex, "m": order["merchant_id"], "o": order["id"],
             "v": b"opaque-recipient"},
        )
    await _svcs()["settlement"].retention_prune(now=now)
    fresh = await _row(
        "SELECT contact_enc, public_token_enc, total_sat FROM infinitemarkets.orders WHERE id = :o",
        {"o": order["id"]},
    )
    assert fresh["contact_enc"] is None
    assert fresh["public_token_enc"] is None
    assert fresh["total_sat"] == order["total_sat"]
    for table, column in (
        ("order_fulfillment", "tracking_enc"), ("email_queue", "recipient_enc"),
        ("email_queue", "payload_enc"), ("email_queue", "preview_enc"),
        ("idempotency_records", "response_enc"),
    ):
        row = await _row(
            f"SELECT {column} FROM infinitemarkets.{table} WHERE order_id = :o",
            {"o": order["id"]},
        )
        assert row and not row[column], table


async def test_invoice_listener_redacts_error_context(runtime_env, monkeypatch):
    from types import SimpleNamespace

    from loguru import logger

    settlement = _svcs()["settlement"]
    canary = "private-listener-canary"

    async def fail(*args, **kwargs):
        raise RuntimeError(canary)

    monkeypatch.setattr(settlement, "_handle_core_payment", fail)
    messages = []
    sink = logger.add(messages.append, format="{message}")
    try:
        await settlement.invoice_listener(SimpleNamespace(
            extension="infinitemarkets", external_id=f"infinitemarkets:{canary}",
        ))
    finally:
        logger.remove(sink)
    assert messages and all(canary not in message for message in messages)


@pytest.mark.parametrize("mismatch", ["amount", "wallet"])
async def test_unverified_lnbits_invoice_is_not_offered_to_buyer(
    runtime_env, monkeypatch, mismatch,
):
    from lnbits.core.services import payments as host_payments

    create_invoice = host_payments.create_invoice

    async def unexpected_invoice(**kwargs):
        if mismatch == "amount":
            kwargs["amount"] += 1
        payment = await create_invoice(**kwargs)
        if mismatch == "wallet":
            payment = payment.copy(update={"wallet_id": uuid.uuid4().hex})
        return payment

    monkeypatch.setattr(host_payments, "create_invoice", unexpected_invoice)
    key = uuid.uuid4().hex * 2
    order, product, result = await _new_order(runtime_env, qty=1, stock=2, key=key)
    assert result["order"]["state"] == "invoice_pending"
    assert result["order"]["bolt11"] is None
    assert order["payment_exception"]
    assert order["payment_exception_reason"] == "invoice-correlation-failed"
    projection = await _row(
        "SELECT status, bolt11_enc, core_external_id FROM infinitemarkets.payments"
        " WHERE order_id = :o",
        {"o": order["id"]},
    )
    assert projection["status"] == "creation_unknown"
    assert projection["bolt11_enc"] is None
    replay = await _svcs()["checkout"].checkout(
        payload={
            "merchant_pubkey": await _mpk(runtime_env),
            "items": [{"d_tag": product["d_tag"], "quantity": 1}],
        },
        idempotency_key=key, client_scope="saga",
    )
    assert replay == result
    invoices = await _core_row(
        "SELECT COUNT(*) AS n FROM apipayments WHERE external_id = :e",
        {"e": projection["core_external_id"]},
    )
    assert invoices["n"] == 1


@pytest.mark.parametrize("damage", ["missing", "partial", "extra", "expired", "counter"])
async def test_hard03_missing_coverage_settles_into_inventory_review(runtime_env, damage):
    from infinitemarkets.crypto import token_lookup_hash
    from infinitemarkets.db import DomainTransaction, db

    svcs = _svcs()
    products = [await runtime_env["make_product"](uuid.uuid4().hex, 10) for _ in range(3)]
    response = await svcs["checkout"].checkout(
        payload={"merchant_pubkey": await _mpk(runtime_env), "items": [
            {"d_tag": product["d_tag"], "quantity": 2} for product in products[:2]
        ]},
        idempotency_key=uuid.uuid4().hex * 2, client_scope=uuid.uuid4().hex,
    )
    order = await _row(
        "SELECT * FROM infinitemarkets.orders WHERE public_token_hash = :h",
        {"h": token_lookup_hash(response["public_token"])},
    )
    assert order["invoice_expiry"] > int(time.time())
    async with DomainTransaction() as tx:
        if damage == "missing":
            await tx.execute(
                "DELETE FROM inventory_reservations WHERE order_id = :o AND product_id = :p",
                {"o": order["id"], "p": products[0]["id"]},
            )
            await tx.execute("UPDATE products SET stock_reserved = 0 WHERE id = :p",
                             {"p": products[0]["id"]})
        elif damage == "partial":
            await tx.execute(
                "UPDATE inventory_reservations SET quantity = 1 "
                "WHERE order_id = :o AND product_id = :p",
                {"o": order["id"], "p": products[0]["id"]},
            )
            await tx.execute("UPDATE products SET stock_reserved = 1 WHERE id = :p",
                             {"p": products[0]["id"]})
        elif damage == "extra":
            await tx.execute(
                "INSERT INTO inventory_reservations "
                "(id, product_id, order_id, quantity, state, expires_at, created_at, updated_at) "
                "VALUES (:i, :p, :o, 1, 'held', :e, :n, :n)",
                {"i": uuid.uuid4().hex, "p": products[2]["id"], "o": order["id"],
                 "e": order["invoice_expiry"], "n": int(time.time())},
            )
            await tx.execute("UPDATE products SET stock_reserved = 1 WHERE id = :p",
                             {"p": products[2]["id"]})
        elif damage == "expired":
            await tx.execute("UPDATE inventory_reservations SET expires_at = 1 WHERE order_id = :o",
                             {"o": order["id"]})
        else:
            await tx.execute("UPDATE products SET stock_reserved = 1 WHERE id = :p",
                             {"p": products[1]["id"]})
    payment = await _settle_core_payment(order["id"], order["total_sat"])
    await svcs["settlement"].invoice_listener(payment)
    fresh = await svcs["orders"].get_order(order["id"])
    assert fresh["state"] == "cancelled", "incomplete/corrupt allocation must not confirm"
    assert fresh["payment_exception"]
    assert fresh["payment_exception_reason"] == (
        "inventory-reservation-counters-incoherent" if damage == "counter"
        else "inventory-reservation-coverage-lost"
    )
    projection = await _row("SELECT status FROM infinitemarkets.payments WHERE order_id = :o",
                            {"o": order["id"]})
    assert projection["status"] == "settled"
    async with db.connect() as conn:
        assert not await svcs["orders"].fulfillment_authorized(conn, fresh)
        holds = await conn.fetchall(
            "SELECT * FROM infinitemarkets.inventory_reservations "
            "WHERE order_id = :o AND state = 'held'",
            {"o": order["id"]},
        )
    assert len(holds) == (2 if damage == "counter" else 0)
    normal = await _row(
        "SELECT COUNT(*) AS n FROM infinitemarkets.email_queue "
        "WHERE order_id = :o AND event_type = 'confirmed'",
        {"o": order["id"]},
    )
    assert normal["n"] == 0
    for product in products:
        stock = await _row("SELECT stock_on_hand FROM infinitemarkets.products WHERE id = :p",
                           {"p": product["id"]})
        assert stock["stock_on_hand"] == 10
    from test_order_admin import _hard01_snapshot

    before = await _hard01_snapshot(order["id"])
    await svcs["settlement"].invoice_listener(payment)
    assert await _hard01_snapshot(order["id"]) == before


async def test_hard02_recovered_original_invoice_is_payable_and_fulfillable(
    runtime_env, monkeypatch,
):
    from test_order_admin import _hard01_snapshot

    from infinitemarkets.db import db

    svcs = _svcs()
    order, product, response, original = await _hard03_unknown_invoice(runtime_env, monkeypatch)
    secret = "synthetic-original-invoice-delivery"
    updated = await runtime_env["client"].patch(
        f"{API}/products/{product['id']}", json={"delivery_content": secret},
        headers=await runtime_env["cookie"](),
    )
    assert updated.status_code == 200, updated.text
    token = {"X-Order-Token": response["public_token"]}
    before = await runtime_env["client"].get(f"{API}/public/order-status", headers=token)
    assert before.status_code == 200
    assert before.json()["payment_exception"]
    assert before.json()["bolt11"] is None
    assert before.json()["digital_delivery"] == []
    report = await svcs["settlement"].reconcile()
    assert any(row["order_id"] == order["id"] for row in report["attached"])
    recovered = await svcs["orders"].get_order(order["id"])
    assert not recovered["payment_exception"], (
        "verified original invoice must be payable before settlement"
    )
    assert recovered["payment_exception_reason"] is None
    assert recovered["payment_exception_resolution"] is None
    status = (await runtime_env["client"].get(f"{API}/public/order-status", headers=token)).json()
    assert status["state"] == "awaiting_payment"
    assert status["payment_status"] == "pending"
    assert status["bolt11"] == original.bolt11
    assert status["total_sat"] == original.sat == 1000
    item = await _row(
        "SELECT product_id, currency, quantity, line_total_sat FROM infinitemarkets.order_items "
        "WHERE order_id = :o", {"o": order["id"]},
    )
    assert item == {"product_id": product["id"], "currency": "SAT", "quantity": 2,
                    "line_total_sat": 1000}
    assert not status["payment_exception"]
    assert status["digital_delivery"] == []
    assert recovered["payment_hash"] == original.payment_hash
    core = await _core_row("SELECT COUNT(*) AS n FROM apipayments WHERE external_id = :e",
                           {"e": f"infinitemarkets:{order['id']}"})
    assert core["n"] == 1
    payment = await _settle_core_payment(order["id"], order["total_sat"])
    await svcs["settlement"].invoice_listener(payment)
    fresh = await svcs["orders"].get_order(order["id"])
    assert fresh["state"] == "confirmed" and not fresh["payment_exception"]
    async with db.connect() as conn:
        assert await svcs["orders"].inventory_accounted(conn, fresh)
    status = (await runtime_env["client"].get(f"{API}/public/order-status", headers=token)).json()
    assert status["digital_delivery"] == [{"title": product["title"], "content": secret}]
    assert status["total_sat"] == 1000 and status["bolt11"] is None
    snapshot = await _hard01_snapshot(order["id"])
    await svcs["settlement"].invoice_listener(payment)
    await svcs["settlement"].reconcile()
    await svcs["checkout"].attach_payment(
        order_id=order["id"], payment=payment, now=int(time.time()),
    )
    assert await _hard01_snapshot(order["id"]) == snapshot
    assert (await _core_row("SELECT COUNT(*) AS n FROM apipayments WHERE external_id = :e",
                            {"e": f"infinitemarkets:{order['id']}"}))["n"] == 1


@pytest.mark.parametrize("held,reason,resolution", [
    (True, "settlement-amount-mismatch", None),
    (True, "settlement-wallet-mismatch", "unresolved"),
    (True, "multiple-core-payments", "unresolved"),
    (True, "invoice-correlation-failed", None),
    (True, None, None),
    (True, "inventory-reservation-counters-incoherent", "unresolved"),
    (True, "invoice-creation-unknown", "accepted"),
    (True, "invoice-creation-unknown", "refund_requested"),
    (True, "invoice-creation-unknown", "refund_confirmed"),
    (False, None, "refund_requested"),
    (False, None, "refund_confirmed"),
])
async def test_hard02_timeout_preserves_protected_hold(
    runtime_env, monkeypatch, held, reason, resolution,
):
    from infinitemarkets.db import DomainTransaction

    svcs = _svcs()
    order, _, response, original = await _hard03_unknown_invoice(runtime_env, monkeypatch)
    async with DomainTransaction() as tx:
        await tx.execute(
            "UPDATE orders SET payment_exception = :h, payment_exception_reason = :r, "
            "payment_exception_resolution = :s WHERE id = :o",
            {"h": held, "r": reason, "s": resolution, "o": order["id"]},
        )
    expected = (held, reason, resolution)
    await svcs["checkout"]._mark_unknown(order["id"], now=int(time.time()))
    fresh = await svcs["orders"].get_order(order["id"])
    assert (bool(fresh["payment_exception"]), fresh["payment_exception_reason"],
            fresh["payment_exception_resolution"]) == expected, (
        "timeout must not weaken protected authority"
    )
    await svcs["checkout"].attach_payment(
        order_id=order["id"], payment=original, now=int(time.time()),
    )
    payment = await _settle_core_payment(order["id"], order["total_sat"])
    await svcs["settlement"].invoice_listener(payment)
    fresh = await svcs["orders"].get_order(order["id"])
    assert (bool(fresh["payment_exception"]), fresh["payment_exception_reason"],
            fresh["payment_exception_resolution"]) == expected
    if held:
        status = (await runtime_env["client"].get(
            f"{API}/public/order-status", headers={"X-Order-Token": response["public_token"]},
        )).json()
        assert status["payment_exception"] and status["digital_delivery"] == []


async def test_hard02_callback_before_timeout_is_mutation_free(runtime_env, monkeypatch):
    from test_order_admin import _hard01_snapshot

    svcs = _svcs()
    order, _, _, _ = await _hard03_unknown_invoice(runtime_env, monkeypatch)
    paid = await _settle_core_payment(order["id"], order["total_sat"])
    await svcs["settlement"].invoice_listener(paid)
    before = await _hard01_snapshot(order["id"])
    await svcs["checkout"]._mark_unknown(order["id"], now=int(time.time()) + 1)
    assert await _hard01_snapshot(order["id"]) == before


@pytest.mark.parametrize("reason,resolution", [
    ("invoice-creation-unknown", None), (None, "refund_requested"),
    ("settlement-wallet-mismatch", "unresolved"),
])
async def test_hard02_already_settled_legacy_is_pure_noop(runtime_env, reason, resolution):
    from test_order_admin import _hard01_snapshot

    from infinitemarkets.db import DomainTransaction

    svcs = _svcs()
    order, _, _ = await _new_order(runtime_env, scope=uuid.uuid4().hex)
    paid = await _settle_core_payment(order["id"], order["total_sat"])
    await svcs["settlement"].invoice_listener(paid)
    async with DomainTransaction() as tx:
        await tx.execute(
            "UPDATE orders SET payment_exception = TRUE, payment_exception_reason = :r, "
            "payment_exception_resolution = :s WHERE id = :o",
            {"r": reason, "s": resolution, "o": order["id"]},
        )
    before = await _hard01_snapshot(order["id"])
    await svcs["settlement"].invoice_listener(paid)
    result = await svcs["settlement"].confirm_settlement(order_id=order["id"])
    assert result["action"] == "no-op"
    await svcs["settlement"].reconcile()
    await svcs["checkout"].attach_payment(order_id=order["id"], payment=paid, now=int(time.time()))
    await svcs["checkout"]._mark_unknown(order["id"], now=int(time.time()))
    assert await _hard01_snapshot(order["id"]) == before


@pytest.mark.parametrize("path", ["late", "incomplete", "mismatch"])
@pytest.mark.parametrize("held,reason,resolution", [
    (True, "inventory-reservation-counters-incoherent", "unresolved"),
    (True, None, None), (False, None, "refund_confirmed"),
])
async def test_hard02_review_does_not_replace_protected_authority(
    runtime_env, monkeypatch, path, held, reason, resolution,
):
    from infinitemarkets.db import DomainTransaction

    svcs = _svcs()
    order, _, _, original = await _hard03_unknown_invoice(runtime_env, monkeypatch)
    async with DomainTransaction() as tx:
        await tx.execute(
            "UPDATE orders SET payment_exception = :h, payment_exception_reason = :r, "
            "payment_exception_resolution = :s WHERE id = :o",
            {"h": held, "r": reason, "s": resolution, "o": order["id"]},
        )
    await svcs["checkout"].attach_payment(
        order_id=order["id"], payment=original, now=int(time.time()),
    )
    if path == "late":
        await svcs["orders"].cancel_order(
            order_id=order["id"], actor="system", reason="synthetic review",
        )
    elif path == "incomplete":
        async with DomainTransaction() as tx:
            await tx.execute("UPDATE inventory_reservations SET expires_at = 1 WHERE order_id = :o",
                             {"o": order["id"]})
    if path == "mismatch":
        await svcs["settlement"]._flag_exception(
            order["id"], "settlement-amount-mismatch", "synthetic",
        )
    else:
        payment = await _settle_core_payment(order["id"], order["total_sat"])
        await svcs["settlement"].invoice_listener(payment)
    fresh = await svcs["orders"].get_order(order["id"])
    assert (bool(fresh["payment_exception"]), fresh["payment_exception_reason"],
            fresh["payment_exception_resolution"]) == (held, reason, resolution)


async def test_hard02_concurrent_timeout_manual_decision_attachment(runtime_env, monkeypatch):
    from infinitemarkets.db import DomainTransaction, dialect

    svcs = _svcs()
    order, _, _, original = await _hard03_unknown_invoice(runtime_env, monkeypatch)
    locked, release = asyncio.Event(), asyncio.Event()
    entered = {name: asyncio.Event() for name in ("timeout", "attachment")}
    connections = {}
    enter = DomainTransaction.__aenter__
    queries = []
    execute = DomainTransaction.execute
    fetch_one = DomainTransaction.fetch_one

    async def tracked_enter(self):
        name = asyncio.current_task().get_name()
        if name in entered and dialect() == "sqlite":
            entered[name].set()
        tx = await enter(self)
        if name in (*entered, "manual-decision"):
            connections[name] = ((await tx.fetch_one("SELECT pg_backend_pid() AS pid"))["pid"]
                                 if dialect() == "postgres" else self._raw)
        if name in entered and dialect() == "postgres":
            entered[name].set()
        return tx

    async def tracked_execute(self, sql, params=None):
        if asyncio.current_task().get_name() == "timeout":
            queries.append(sql)
        return await execute(self, sql, params)

    async def tracked_fetch(self, sql, params=None):
        if asyncio.current_task().get_name() == "timeout":
            queries.append(sql)
        return await fetch_one(self, sql, params)

    async def manual_decision():
        async with DomainTransaction() as tx:
            await svcs["orders"]._order_row(tx, order["id"])
            locked.set()
            await asyncio.wait_for(release.wait(), 5)
            await tx.execute(
                f"UPDATE {tx.table('orders')} SET payment_exception = TRUE, "
                "payment_exception_reason = NULL, "
                "payment_exception_resolution = 'refund_requested' WHERE id = :o",
                {"o": order["id"]},
            )

    monkeypatch.setattr(DomainTransaction, "__aenter__", tracked_enter)
    monkeypatch.setattr(DomainTransaction, "execute", tracked_execute)
    monkeypatch.setattr(DomainTransaction, "fetch_one", tracked_fetch)
    workers = [asyncio.create_task(manual_decision(), name="manual-decision")]
    try:
        await asyncio.wait_for(locked.wait(), 5)
        workers.extend([
            asyncio.create_task(svcs["checkout"]._mark_unknown(
                order["id"], now=int(time.time()),
            ), name="timeout"),
            asyncio.create_task(svcs["checkout"].attach_payment(
                order_id=order["id"], payment=original, now=int(time.time()),
            ), name="attachment"),
        ])
        for event in entered.values():
            await asyncio.wait_for(event.wait(), 5)
        release.set()
        await asyncio.wait_for(asyncio.gather(*workers), 10)
    finally:
        release.set()
        for worker in workers:
            if not worker.done():
                worker.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
    assert len(connections) == 3 and len(set(connections.values())) == 3
    financial = [sql for sql in queries if "orders" in sql or "payments" in sql]
    assert financial[0].startswith("SELECT * FROM ") and "orders" in financial[0]
    fresh = await svcs["orders"].get_order(order["id"])
    assert fresh["state"] == "awaiting_payment"
    assert fresh["payment_exception"] and fresh["payment_exception_reason"] is None
    assert fresh["payment_exception_resolution"] == "refund_requested"
    assert (await _core_row("SELECT COUNT(*) AS n FROM apipayments WHERE external_id = :e",
                            {"e": f"infinitemarkets:{order['id']}"}))["n"] == 1


@pytest.mark.parametrize("boundary", ["cancelled", "expired", "unallocated", "duplicate"])
async def test_hard02_attachment_does_not_clear_outside_new_active_coverage(
    runtime_env, monkeypatch, boundary,
):
    from infinitemarkets.db import DomainTransaction

    svcs = _svcs()
    order, _, response, original = await _hard03_unknown_invoice(runtime_env, monkeypatch)
    now = int(time.time())
    if boundary == "duplicate":
        await svcs["checkout"].attach_payment(order_id=order["id"], payment=original, now=now)
        async with DomainTransaction() as tx:
            await tx.execute("UPDATE orders SET payment_exception = TRUE, "
                             "payment_exception_reason = 'invoice-creation-unknown' WHERE id = :o",
                             {"o": order["id"]})
    elif boundary == "cancelled":
        await svcs["orders"].cancel_order(order_id=order["id"], actor="system", reason="synthetic")
    elif boundary == "expired":
        async with DomainTransaction() as tx:
            await tx.execute(
                "UPDATE orders SET state = 'expired' WHERE id = :o", {"o": order["id"]},
            )
    else:
        async with DomainTransaction() as tx:
            await svcs["orders"].release_reservations(
                tx, order_id=order["id"], to_state="released", now=now,
            )
    attached = await svcs["checkout"].attach_payment(
        order_id=order["id"], payment=original, now=now,
    )
    fresh = await svcs["orders"].get_order(order["id"])
    assert fresh["payment_exception"]
    assert fresh["payment_exception_reason"] == (
        "inventory-reservation-coverage-lost" if boundary == "unallocated"
        else "invoice-creation-unknown"
    )
    if boundary in ("cancelled", "expired"):
        assert fresh["state"] == boundary and attached["bolt11"] is None
    status = (await runtime_env["client"].get(
        f"{API}/public/order-status", headers={"X-Order-Token": response["public_token"]},
    )).json()
    assert status["payment_exception"] and status["digital_delivery"] == []
    assert status["bolt11"] is None, "unresolved recovery must not expose a payable invoice"


@pytest.mark.parametrize("resolution", [None, "unresolved"])
async def test_hard02_new_settlement_resolves_before_notification_snapshots(
    runtime_env, monkeypatch, resolution,
):
    from infinitemarkets.db import DomainTransaction

    svcs = _svcs()
    order, _, response = await _new_order(runtime_env, scope=uuid.uuid4().hex)
    async with DomainTransaction() as tx:
        await tx.execute(
            "UPDATE orders SET payment_exception = TRUE, "
            "payment_exception_reason = 'invoice-creation-unknown', "
            "payment_exception_resolution = :r WHERE id = :o",
            {"r": resolution, "o": order["id"]},
        )
    original = svcs["orders"].enqueue_email_intents
    snapshots = []

    async def capture(tx, **kwargs):
        if kwargs["order"]["id"] == order["id"] and kwargs["event_type"] == "confirmed":
            snapshots.append(kwargs["order"].copy())
        return await original(tx, **kwargs)

    monkeypatch.setattr(svcs["orders"], "enqueue_email_intents", capture)
    paid = await _settle_core_payment(order["id"], order["total_sat"])
    await svcs["settlement"].invoice_listener(paid)
    fresh = await svcs["orders"].get_order(order["id"])
    assert fresh["state"] == "confirmed" and not fresh["payment_exception"]
    assert fresh["payment_exception_reason"] is None
    assert fresh["payment_exception_resolution"] is None
    assert len(snapshots) == 1 and not snapshots[0]["payment_exception"]
    assert snapshots[0]["state"] == "confirmed"
    assert snapshots[0]["payment_exception_reason"] is None
    status = (await runtime_env["client"].get(
        f"{API}/public/order-status", headers={"X-Order-Token": response["public_token"]},
    )).json()
    assert not status["payment_exception"] and status["payment_status"] == "settled"


async def _hard03_unknown_invoice(runtime_env, monkeypatch):
    from lnbits.core.services import payments as host_payments

    original = host_payments.create_invoice

    async def persist_then_timeout(**kwargs):
        await original(**kwargs)
        raise TimeoutError("synthetic response loss")

    with monkeypatch.context() as patch:
        patch.setattr(host_payments, "create_invoice", persist_then_timeout)
        order, product, response = await _new_order(runtime_env, scope=uuid.uuid4().hex)
    assert order["state"] == "invoice_pending"
    assert order["payment_exception_reason"] == "invoice-creation-unknown"
    payment = (await _svcs()["settlement"]._core_payments_by_external_id(
        f"infinitemarkets:{order['id']}"
    ))[0]
    return order, product, response, payment


@pytest.mark.parametrize("winner", ["attachment", "settlement"])
async def test_hard03_stale_expiry_selection_rechecks_current_truth(
    runtime_env, monkeypatch, winner,
):
    from infinitemarkets.db import DomainTransaction, dialect

    svcs = _svcs()
    order, product, _, payment = await _hard03_unknown_invoice(runtime_env, monkeypatch)
    now = int(time.time())
    async with DomainTransaction() as tx:
        await tx.execute("UPDATE inventory_reservations SET expires_at = :e WHERE order_id = :o",
                         {"e": now - 1, "o": order["id"]})
    selected, resume = asyncio.Event(), asyncio.Event()
    enter = DomainTransaction.__aenter__
    expiry_task = None
    expiry_connections, winner_connections = set(), set()

    async def controlled_enter(self):
        if dialect() == "postgres":
            tx = await enter(self)
            pid = await tx.fetch_one("SELECT pg_backend_pid() AS pid")
            if asyncio.current_task() is expiry_task:
                if not selected.is_set():
                    expiry_connections.add(pid["pid"])
            else:
                winner_connections.add(pid["pid"])
        if asyncio.current_task() is expiry_task:
            selected.set()
            try:
                await asyncio.wait_for(resume.wait(), 5)
            except BaseException as error:
                if dialect() == "postgres":
                    await tx.__aexit__(type(error), error, error.__traceback__)
                raise
        return tx if dialect() == "postgres" else await enter(self)

    monkeypatch.setattr(DomainTransaction, "__aenter__", controlled_enter)
    expiry_task = asyncio.create_task(svcs["settlement"].reservation_expiry_pass(now=now))
    try:
        await asyncio.wait_for(selected.wait(), 5)
        result = await svcs["checkout"].attach_payment(
            order_id=order["id"], payment=payment, now=now,
        )
        assert result["state"] == "awaiting_payment"
        if winner == "settlement":
            paid = await _settle_core_payment(order["id"], order["total_sat"])
            await svcs["settlement"].invoice_listener(paid)
        resume.set()
        await asyncio.wait_for(expiry_task, 5)
    finally:
        resume.set()
        if not expiry_task.done():
            expiry_task.cancel()
        await asyncio.gather(expiry_task, return_exceptions=True)
    if dialect() == "postgres":
        assert len(expiry_connections) == 1 and winner_connections
        assert expiry_connections.isdisjoint(winner_connections)
    fresh = await svcs["orders"].get_order(order["id"])
    assert fresh["state"] == ("confirmed" if winner == "settlement" else "awaiting_payment"), (
        "stale selection cannot expire newly aligned or consumed holds"
    )
    reservation = await _row(
        "SELECT state, expires_at FROM infinitemarkets.inventory_reservations WHERE order_id = :o",
        {"o": order["id"]},
    )
    assert reservation["state"] == ("consumed" if winner == "settlement" else "held")
    assert reservation["expires_at"] == result["expires_at"]
    stock = await _row(
        "SELECT stock_on_hand, stock_reserved FROM infinitemarkets.products WHERE id = :p",
        {"p": product["id"]},
    )
    assert stock == {"stock_on_hand": 8 if winner == "settlement" else 10,
                     "stock_reserved": 0 if winner == "settlement" else 2}


async def test_hard03_pending_expiry_retains_correlation_without_payable_invoice(
    runtime_env, monkeypatch,
):
    from infinitemarkets.db import DomainTransaction

    svcs = _svcs()
    order, product, _, payment = await _hard03_unknown_invoice(runtime_env, monkeypatch)
    async with DomainTransaction() as tx:
        await tx.execute("UPDATE inventory_reservations SET expires_at = 1 WHERE order_id = :o",
                         {"o": order["id"]})
    await svcs["settlement"].reservation_expiry_pass()
    fresh = await svcs["orders"].get_order(order["id"])
    assert fresh["state"] == "cancelled", "expired pending capacity must not remain payable"
    projection = await _row(
        "SELECT status, core_external_id FROM infinitemarkets.payments WHERE order_id = :o",
        {"o": order["id"]},
    )
    assert projection == {"status": "creation_unknown",
                          "core_external_id": f"infinitemarkets:{order['id']}"}
    result = await svcs["checkout"].attach_payment(
        order_id=order["id"], payment=payment, now=int(time.time()),
    )
    assert result["state"] == "cancelled" and result["bolt11"] is None
    paid = await _settle_core_payment(order["id"], order["total_sat"])
    await svcs["settlement"].invoice_listener(paid)
    fresh = await svcs["orders"].get_order(order["id"])
    assert fresh["state"] == "cancelled" and fresh["payment_exception"]
    stock = await _row(
        "SELECT stock_on_hand, stock_reserved FROM infinitemarkets.products WHERE id = :p",
        {"p": product["id"]},
    )
    assert stock == {"stock_on_hand": 10, "stock_reserved": 0}


@pytest.mark.parametrize("path", ["consumed", "partial", "residual", "unlimited"])
async def test_hard03_accept_cumulative_accounting_once(runtime_env, path, monkeypatch):
    import json

    from infinitemarkets.db import DomainTransaction, db

    svcs = _svcs()
    order, product, _ = await _new_order(
        runtime_env, qty=3, stock=None if path == "unlimited" else 10,
        scope=uuid.uuid4().hex,
    )
    if path != "consumed":
        await svcs["orders"].cancel_order(order_id=order["id"], actor="buyer", reason=None)
    payment = await _settle_core_payment(order["id"], order["total_sat"])
    await svcs["settlement"].invoice_listener(payment)
    if path == "consumed":
        await svcs["orders"].cancel_order(
            order_id=order["id"], actor="merchant", reason="paid cancellation",
        )
    async with DomainTransaction() as tx:
        await tx.execute("UPDATE products SET format = 'physical' WHERE id = :p",
                         {"p": product["id"]})
        await tx.execute("UPDATE orders SET shipping_state = 'pending' WHERE id = :o",
                         {"o": order["id"]})
        if path == "partial":
            await tx.execute("UPDATE products SET stock_on_hand = 1 WHERE id = :p",
                             {"p": product["id"]})
        elif path == "residual":
            await tx.execute("UPDATE inventory_reservations SET state = 'held' WHERE order_id = :o",
                             {"o": order["id"]})
            await tx.execute("UPDATE products SET stock_reserved = 3 WHERE id = :p",
                             {"p": product["id"]})
    async with DomainTransaction() as tx:
        epoch = await tx.now()

    async def fixed_now(self):
        return epoch

    monkeypatch.setattr(DomainTransaction, "now", fixed_now)
    monkeypatch.setattr(svcs["orders"], "_now", lambda: epoch)
    monkeypatch.setattr(svcs["settlement"], "_now", lambda: epoch)
    for attempt in range(3):
        result = await svcs["settlement"].resolve_exception(order_id=order["id"], action="accept")
        assert result["action"] == "accepted"
        fresh = await svcs["orders"].get_order(order["id"])
        assert fresh["updated_at"] == epoch, "accept must use authoritative DB epoch"
        from test_order_admin import _hard01_snapshot

        snapshot = await _hard01_snapshot(order["id"])
        for name in ("order_events", "inventory_reservations", "products", "email_queue"):
            for row in snapshot[name]:
                for field in ("created_at", "updated_at", "next_attempt_at"):
                    if row.get(field) is not None:
                        assert row[field] <= epoch, "accept must not fabricate future timestamps"
        stock = await _row(
            "SELECT stock_on_hand, stock_reserved FROM infinitemarkets.products WHERE id = :p",
            {"p": product["id"]},
        )
        assert stock == {
            "stock_on_hand": None if path == "unlimited" else 0 if path == "partial" else 7,
            "stock_reserved": 0,
        }, "accept must not charge accounted units twice"
        item = await _row("SELECT * FROM infinitemarkets.order_items WHERE order_id = :o",
                          {"o": order["id"]})
        assert item["backordered_qty"] == (2 if path == "partial" else 0)
        async with db.connect() as conn:
            assert await svcs["orders"].inventory_accounted(conn, fresh)
            assert await svcs["orders"].fulfillment_authorized(conn, fresh)
            events = await conn.fetchall(
                "SELECT detail_json FROM infinitemarkets.order_events WHERE order_id = :o "
                "AND actor = 'merchant' AND to_state = 'confirmed' ORDER BY created_at DESC",
                {"o": order["id"]},
            )
        proof = json.loads(events[0]["detail_json"])["inventory_accounting"]
        assert proof["version"] == 1 and len(proof["items"]) == 1
        entry = proof["items"][0]
        assert (entry["consumed_qty"] + entry["accepted_allocated_qty"]
                + entry["backordered_qty"]) == 3
        if attempt < 2:
            await svcs["orders"].cancel_order(
                order_id=order["id"], actor="merchant", reason="repeat paid cancellation",
            )
    response = await runtime_env["client"].post(
        f"{API}/merchants/{runtime_env['merchant_id']}/orders/{order['id']}/status",
        json={"to_state": "processing"}, headers=await runtime_env["cookie"](),
    )
    assert response.status_code == 200, response.text
    response = await runtime_env["client"].post(
        f"{API}/merchants/{runtime_env['merchant_id']}/orders/{order['id']}/shipping",
        json={"shipping_state": "shipped"}, headers=await runtime_env["cookie"](),
    )
    assert response.status_code == 200, response.text
    response = await runtime_env["client"].post(
        f"{API}/merchants/{runtime_env['merchant_id']}/orders/{order['id']}/status",
        json={"to_state": "completed"}, headers=await runtime_env["cookie"](),
    )
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("damage", ["reason_only", "malformed", "wrong_consumed", "backorder"])
async def test_hard03_accept_rejects_unproven_history_without_mutation(runtime_env, damage):
    import json

    from test_order_admin import _hard01_snapshot

    from infinitemarkets.db import DomainTransaction
    from infinitemarkets.security import ProblemError

    svcs = _svcs()
    order, _, _ = await _new_order(runtime_env, scope=uuid.uuid4().hex)
    await svcs["orders"].cancel_order(order_id=order["id"], actor="buyer", reason=None)
    payment = await _settle_core_payment(order["id"], order["total_sat"])
    await svcs["settlement"].invoice_listener(payment)
    await svcs["settlement"].resolve_exception(order_id=order["id"], action="accept")
    await svcs["orders"].cancel_order(
        order_id=order["id"], actor="merchant", reason="paid cancellation for review",
    )
    async with DomainTransaction() as tx:
        row = await tx.fetch_one(
            "SELECT id, detail_json FROM order_events WHERE order_id = :o "
            "AND to_state = 'confirmed' ORDER BY created_at DESC, id DESC",
            {"o": order["id"]},
        )
        detail = json.loads(row["detail_json"])
        if damage == "reason_only":
            detail.pop("inventory_accounting")
        elif damage == "malformed":
            detail["inventory_accounting"] = {"version": True, "items": []}
        elif damage == "wrong_consumed":
            detail["inventory_accounting"]["items"][0]["consumed_qty"] = 2
            detail["inventory_accounting"]["items"][0]["accepted_allocated_qty"] = 0
        else:
            await tx.execute("UPDATE order_items SET backordered_qty = 1 WHERE order_id = :o",
                             {"o": order["id"]})
        await tx.execute("UPDATE order_events SET detail_json = :d WHERE id = :i",
                         {"d": json.dumps(detail), "i": row["id"]})
    before = await _hard01_snapshot(order["id"])
    with pytest.raises(ProblemError) as error:
        await svcs["settlement"].resolve_exception(order_id=order["id"], action="accept")
    assert error.value.code == "invalid-transition"
    assert await _hard01_snapshot(order["id"]) == before


@pytest.mark.parametrize("reason,resolution", [
    (None, None), ("settlement-wallet-mismatch", "unresolved"),
    ("manual review", "refund_requested"), ("manual attestation", "refund_confirmed"),
])
async def test_hard03_inventory_review_preserves_independent_hold(runtime_env, reason, resolution):
    from infinitemarkets.db import DomainTransaction

    svcs = _svcs()
    order, product, _ = await _new_order(runtime_env, scope=uuid.uuid4().hex)
    async with DomainTransaction() as tx:
        await tx.execute(
            "UPDATE orders SET payment_exception = TRUE, payment_exception_reason = :r, "
            "payment_exception_resolution = :s WHERE id = :o",
            {"r": reason, "s": resolution, "o": order["id"]},
        )
        await tx.execute("DELETE FROM inventory_reservations WHERE order_id = :o",
                         {"o": order["id"]})
        await tx.execute("UPDATE products SET stock_reserved = 0 WHERE id = :p",
                         {"p": product["id"]})
    payment = await _settle_core_payment(order["id"], order["total_sat"])
    await svcs["settlement"].invoice_listener(payment)
    fresh = await svcs["orders"].get_order(order["id"])
    assert fresh["state"] == "cancelled" and fresh["payment_exception"]
    assert (fresh["payment_exception_reason"], fresh["payment_exception_resolution"]) == (
        reason, resolution,
    )


async def test_hard03_complete_multi_item_consumption(runtime_env):
    from infinitemarkets.crypto import token_lookup_hash
    from infinitemarkets.db import db

    svcs = _svcs()
    products = [await runtime_env["make_product"](uuid.uuid4().hex, stock) for stock in (10, None)]
    response = await svcs["checkout"].checkout(
        payload={"merchant_pubkey": await _mpk(runtime_env), "items": [
            {"d_tag": product["d_tag"], "quantity": 2} for product in products
        ]}, idempotency_key=uuid.uuid4().hex * 2, client_scope=uuid.uuid4().hex,
    )
    order = await _row("SELECT * FROM infinitemarkets.orders WHERE public_token_hash = :h",
                       {"h": token_lookup_hash(response["public_token"])})
    payment = await _settle_core_payment(order["id"], order["total_sat"])
    await svcs["settlement"].invoice_listener(payment)
    fresh = await svcs["orders"].get_order(order["id"])
    assert fresh["state"] == "confirmed"
    async with db.connect() as conn:
        assert await svcs["orders"].inventory_accounted(conn, fresh)
    for product, expected in zip(products, (8, None)):
        stock = await _row(
            "SELECT stock_on_hand, stock_reserved FROM infinitemarkets.products WHERE id = :p",
            {"p": product["id"]},
        )
        assert stock == {"stock_on_hand": expected, "stock_reserved": 0}
    from test_order_admin import _hard01_snapshot

    before = await _hard01_snapshot(order["id"])
    await svcs["settlement"].invoice_listener(payment)
    assert await _hard01_snapshot(order["id"]) == before
