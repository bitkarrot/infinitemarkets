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


async def _new_order(runtime_env, *, qty=2, stock=10, title=None, key=None):
    """A fresh product, checkout response, and persisted order."""
    svcs = _svcs()
    product = await runtime_env["make_product"](
        title or uuid.uuid4().hex[:8], stock
    )
    resp = await svcs["checkout"].checkout(
        payload={
            "merchant_pubkey": await _mpk(runtime_env),
            "items": [{"d_tag": product["d_tag"], "quantity": qty}],
        },
        idempotency_key=key or uuid.uuid4().hex * 2,
        client_scope="saga",
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
    await svcs["settlement"].expire_order(order_id=order["id"])
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


async def test_reconcile_resumes_received_order(runtime_env):
    """§8.7: a committed 'received' order (crash between intake and saga)
    resumes through begin_saga — never abandoned."""
    svcs = _svcs()
    checkout = svcs["checkout"]
    product = await runtime_env["make_product"]("resume-me", 5)

    # Insert the intake tx only — monkeypatch begin_saga to a no-op so the
    # order stays 'received'.
    from infinitemarkets.db import DomainTransaction, db

    mpk = await _mpk(runtime_env)
    resp = await checkout.checkout(
        payload={
            "merchant_pubkey": mpk,
            "items": [{"d_tag": product["d_tag"], "quantity": 1}],
        },
        idempotency_key=uuid.uuid4().hex * 2,
        client_scope="saga3",
    )
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
        await tx.execute(
            "UPDATE products SET stock_reserved = stock_reserved - 1"
            " WHERE id = :p",
            {"p": product["id"]},
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
    result = await svcs["settlement"].reservation_expiry_pass()
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

    from lnbits.core.models.payments import Payment

    # Wrong amount (500 vs the order's 1000 sat).
    bad_amount = Payment(
        checking_id="c1", payment_hash="h1",
        wallet_id=runtime_env["wallet"].id,
        amount=500_000, status="success", memo="m",
        extension="infinitemarkets",
        external_id=f"infinitemarkets:{order_amt['id']}",
        fee=0, bolt11="",
    )
    await svcs["settlement"].invoice_listener(bad_amount)

    # Right amount (qty 2 x 500 = 1000 sat), foreign wallet.
    bad_wallet = Payment(
        checking_id="c2", payment_hash="h2", wallet_id="foreign-wallet",
        amount=1_000_000, status="success", memo="m",
        extension="infinitemarkets",
        external_id=f"infinitemarkets:{order_wal['id']}",
        fee=0, bolt11="",
    )
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
    await settlement.expire_order(order_id=order["id"])
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
