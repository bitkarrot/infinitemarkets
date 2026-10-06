"""Section 8.1 intake + §4.15 idempotency + §3.4 FX through the real
host boot (FakeWallet). Worker tasks are cancelled so every step runs
deterministically from direct service calls — the durable paths they
protect are asserted explicitly here."""

from __future__ import annotations

import asyncio
import importlib
import uuid
from decimal import Decimal

import pytest
import pytest_asyncio

pytestmark = pytest.mark.runtime

ORIGIN = "https://shop.example"
API = "/infinitemarkets/api/v1"


@pytest_asyncio.fixture(scope="module", loop_scope="session", autouse=True)
async def _setup(runtime_env):
    """Cancel live workers for deterministic service-level assertions and
    create the merchant/catalog/products the tests exercise."""
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
              "display_name": "checkout shop"},
        headers=await cookie(),
    )
    assert resp.status_code == 201, resp.text
    mid = resp.json()["id"]
    # Activation: draft -> publication_pending -> active happens when the
    # merchant_profile intent publishes (RELAY_IO=off never sends, so the
    # publish path is covered in test_outbox.py; flip directly here).
    from infinitemarkets.db import DomainTransaction

    async with DomainTransaction() as tx:
        await tx.execute(
            "UPDATE merchants SET state = 'active' WHERE id = :m",
            {"m": mid},
        )
    resp = await client.post(
        f"{API}/categories",
        json={"name": "main", "default_currency": "USD"},
        headers=await cookie(),
    )
    assert resp.status_code == 201, resp.text
    cid = resp.json()["id"]

    async def product(body) -> dict:
        resp = await client.post(
            f"{API}/products",
            json={"category_id": cid, **body},
            headers=await cookie(),
        )
        assert resp.status_code == 201, resp.text
        return resp.json()

    widget = await product({
        "title": "widget", "amount_minor": 500, "currency": "SAT",
        "visibility": "on-sale", "stock_on_hand": 10, "format": "digital",
    })
    gizmo = await product({
        "title": "gizmo", "amount_minor": 100, "currency": "SAT",
        "visibility": "on-sale", "stock_on_hand": 2, "format": "digital",
    })
    draft = await product({
        "title": "wip", "draft": True,
        "amount_minor": 100, "currency": "SAT", "format": "digital",
    })
    usd_item = await product({
        "title": "usd thing",
        "amount_minor": 1000, "currency": "USD", "currency_decimals": 2,
        "visibility": "on-sale", "stock_on_hand": 5, "format": "digital",
    })

    runtime_env.update({
        "merchant_id": mid, "category_id": cid,
        "widget": widget, "gizmo": gizmo, "draft": draft,
        "usd_item": usd_item,
    })
    yield


def _svcs():
    import importlib

    return {
        name: importlib.import_module(f"infinitemarkets.services.{name}")
        for name in ("checkout", "orders", "settlement", "fx", "readiness")
    }


async def _merchant_pubkey(runtime_env):
    from infinitemarkets.db import db  # noqa: PLC0415

    async with db.connect() as conn:
        row = await conn.fetchone(
            "SELECT pubkey FROM infinitemarkets.merchants WHERE id = :m",
            {"m": runtime_env["merchant_id"]},
        )
    return row["pubkey"]


async def _payload(runtime_env, items, **kw):
    return {
        "merchant_pubkey": await _merchant_pubkey(runtime_env),
        "items": items,
        **kw,
    }


async def _order_for_token(token: str) -> dict:
    from infinitemarkets.crypto import token_lookup_hash
    from infinitemarkets.db import db

    async with db.connect() as conn:
        row = await conn.fetchone(
            "SELECT * FROM infinitemarkets.orders WHERE public_token_hash = :h",
            {"h": token_lookup_hash(token)},
        )
    return dict(row)


# --- §8.1 intake validation -------------------------------------------------------


async def test_intake_rejects_bad_items(runtime_env):
    checkout = _svcs()["checkout"]
    from infinitemarkets.security import ProblemError

    async def bad(items):
        with pytest.raises(ProblemError):
            await checkout.checkout(
                payload={
                    "merchant_pubkey": await _merchant_pubkey(runtime_env),
                    "items": items,
                },
                idempotency_key=uuid.uuid4().hex * 2,
                client_scope="t1",
            )

    await bad([])                                    # empty
    await bad([{}])                                  # missing fields
    await bad([{"d_tag": "d", "quantity": 0}])       # qty bounds
    await bad([{"d_tag": "d", "quantity": -1}])
    await bad([{"d_tag": "d", "quantity": 10001}])
    await bad([{"d_tag": "d", "quantity": 1.5}])
    await bad([{"d_tag": "d", "quantity": "x"}])
    await bad([{"d_tag": "x" * 65, "quantity": 1}])  # d_tag bound
    await bad(                                       # §15 item cap
        [{"d_tag": "d", "quantity": 1}] * 65
    )


async def test_intake_rejects_unpurchasable(runtime_env):
    checkout = _svcs()["checkout"]
    from infinitemarkets.security import ProblemError

    # Unknown d_tag.
    with pytest.raises(ProblemError):
        await checkout.checkout(
            payload=await _payload(
                runtime_env, [{"d_tag": "nope", "quantity": 1}]
            ),
            idempotency_key=uuid.uuid4().hex * 2,
            client_scope="t2",
        )
    # Draft products never sell (§8.1 step 4).
    with pytest.raises(ProblemError):
        await checkout.checkout(
            payload=await _payload(
                runtime_env,
                [{"d_tag": runtime_env["draft"]["d_tag"], "quantity": 1}],
            ),
            idempotency_key=uuid.uuid4().hex * 2,
            client_scope="t2",
        )
    # Unknown merchant.
    with pytest.raises(ProblemError):
        await checkout.checkout(
            payload={
                "merchant_pubkey": "ab" * 32,
                "items": [{"d_tag": "d", "quantity": 1}],
            },
            idempotency_key=uuid.uuid4().hex * 2,
            client_scope="t2",
        )


async def test_fresh_checkout_creates_order(runtime_env):
    """Happy path: intake + saga driven to awaiting_payment by the
    FakeWallet create_invoice; reservations held; projection pending."""
    checkout = _svcs()["checkout"]
    body = await _payload(runtime_env, [
        {"d_tag": runtime_env["widget"]["d_tag"], "quantity": 2},
        {"d_tag": runtime_env["gizmo"]["d_tag"], "quantity": 1},
    ])
    resp = await checkout.checkout(
        payload=body, idempotency_key=uuid.uuid4().hex * 2,
        client_scope="t3",
    )
    token = resp["public_token"]
    assert len(token) >= 32
    order = resp["order"]
    assert order["state"] == "awaiting_payment"
    assert order["total_sat"] == 2 * 500 + 100
    assert order["bolt11"] and order["bolt11"].startswith("ln")
    assert order["expires_at"]

    runtime_env["token"] = token
    runtime_env["order_id"] = (await _order_for_token(token))["id"]

    from infinitemarkets.db import db

    async with db.connect() as conn:
        res = await conn.fetchall(
            "SELECT * FROM infinitemarkets.inventory_reservations"
            " WHERE order_id = :o",
            {"o": runtime_env["order_id"]},
        )
        assert {r["product_id"]: r["quantity"] for r in res} == {
            runtime_env["widget"]["id"]: 2,
            runtime_env["gizmo"]["id"]: 1,
        }
        assert all(r["state"] == "held" for r in res)
        proj = await conn.fetchone(
            "SELECT * FROM infinitemarkets.payments WHERE order_id = :o",
            {"o": runtime_env["order_id"]},
        )
        assert proj["status"] == "pending"
        assert proj["core_external_id"] == (
            f"infinitemarkets:{runtime_env['order_id']}"
        )
        items = await conn.fetchall(
            "SELECT * FROM infinitemarkets.order_items WHERE order_id = :o",
            {"o": runtime_env["order_id"]},
        )
        assert len(items) == 2
        assert {i["title"] for i in items} == {"widget", "gizmo"}


async def test_idempotency_replay_and_conflict(runtime_env):
    checkout = _svcs()["checkout"]
    body = await _payload(runtime_env, [
        {"d_tag": runtime_env["widget"]["d_tag"], "quantity": 1},
    ])
    key = uuid.uuid4().hex * 2
    first = await checkout.checkout(
        payload=body, idempotency_key=key, client_scope="t4"
    )
    second = await checkout.checkout(
        payload=body, idempotency_key=key, client_scope="t4"
    )
    # Same key + same body -> byte-identical stored response.
    assert second["public_token"] == first["public_token"]

    from infinitemarkets.db import db

    async with db.connect() as conn:
        await conn.fetchone(
            "SELECT COUNT(*) AS n FROM infinitemarkets.orders"
            " WHERE merchant_id = :m",
            {"m": runtime_env["merchant_id"]},
        )
    # One replay must never mint a second order for the same request.
    first_order = (await _order_for_token(first["public_token"]))["id"]

    from infinitemarkets.security import ProblemError

    other = await _payload(runtime_env, [
        {"d_tag": runtime_env["gizmo"]["d_tag"], "quantity": 1},
    ])
    with pytest.raises(ProblemError) as exc:
        await checkout.checkout(
            payload=other, idempotency_key=key, client_scope="t4"
        )
    assert exc.value.code == "idempotency-conflict"
    runtime_env["first_order_id"] = first_order


async def test_idempotency_crash_resume(runtime_env):
    """A lease that dies after the order exists resumes the saga rather
    than duplicating the order/invoice (§4.15)."""
    checkout = _svcs()["checkout"]
    body = await _payload(runtime_env, [
        {"d_tag": runtime_env["widget"]["d_tag"], "quantity": 1},
    ])
    key = uuid.uuid4().hex * 2
    first = await checkout.checkout(
        payload=body, idempotency_key=key, client_scope="t5"
    )
    scope = checkout._scope_hash(  # noqa: SLF001
        runtime_env["merchant_id"], "/api/v1/public/checkout", key,
    )
    # Force the record back to an expired in_progress lease — a kill
    # between intake and response.
    from infinitemarkets.db import DomainTransaction, db

    async with DomainTransaction() as tx:
        await tx.execute(
            "UPDATE idempotency_records SET state = 'in_progress',"
            " lease_until = 1, response_enc = NULL WHERE scope_hash = :s",
            {"s": scope},
        )
    replay = await checkout.checkout(
        payload=body, idempotency_key=key, client_scope="t5"
    )
    # Resume returns the SAME order/token — never a second order.
    assert replay["public_token"] == first["public_token"]
    async with db.connect() as conn:
        n = await conn.fetchone(
            "SELECT COUNT(*) AS n FROM infinitemarkets.orders"
            " WHERE merchant_id = :m",
            {"m": runtime_env["merchant_id"]},
        )
        assert n["n"] == 3  # fresh + replay + crash-resume only


async def test_oversell_rejected(runtime_env):
    """§8.2 claim CAS: requesting more than available fails; no partial
    reservations remain."""
    checkout = _svcs()["checkout"]
    body = await _payload(runtime_env, [
        {"d_tag": runtime_env["gizmo"]["d_tag"], "quantity": 5},
    ])
    from infinitemarkets.security import ProblemError

    with pytest.raises(ProblemError) as exc:
        await checkout.checkout(
            payload=body, idempotency_key=uuid.uuid4().hex * 2,
            client_scope="t6",
        )
    assert exc.value.code == "insufficient-stock"
    from infinitemarkets.db import db

    async with db.connect() as conn:
        res = await conn.fetchone(
            "SELECT COUNT(*) AS n FROM infinitemarkets.inventory_reservations"
            " WHERE product_id = :p AND state = 'held'",
            {"p": runtime_env["gizmo"]["id"]},
        )
        # gizmo stock 2: the fresh checkout held 1; the oversell held 0.
        assert res["n"] == 1


async def test_fx_usd_conversion(runtime_env, monkeypatch):
    """USD-priced product -> Decimal conversion + order_fx_quotes row."""
    svcs = _svcs()
    checkout = svcs["checkout"]
    fx = svcs["fx"]

    async def fake_rates(currency):
        return [("kraken", 100_000.0), ("bitfinex", 100_000.0)]

    monkeypatch.setattr(fx, "btc_rates", fake_rates)
    body = await _payload(runtime_env, [
        {"d_tag": runtime_env["usd_item"]["d_tag"], "quantity": 1},
    ])
    resp = await checkout.checkout(
        payload=body, idempotency_key=uuid.uuid4().hex * 2,
        client_scope="t7",
    )
    # $10.00 at $100k/BTC = 10_000 sats.
    assert resp["order"]["total_sat"] == 10_000
    order_id = (await _order_for_token(resp["public_token"]))["id"]
    from infinitemarkets.db import db

    async with db.connect() as conn:
        quote = await conn.fetchone(
            "SELECT * FROM infinitemarkets.order_fx_quotes WHERE order_id = :o",
            {"o": order_id},
        )
        assert quote is not None
        assert quote["currency"] == "USD"
        # rate_decimal is sats per major unit: $100k/BTC -> 1000 sat/USD.
        assert Decimal(quote["rate_decimal"]) == Decimal("1000")
        assert quote["providers"] == "kraken,bitfinex"


async def test_missing_fx_rejected(runtime_env, monkeypatch):
    """No provider data -> the order is rejected before any invoice."""
    svcs = _svcs()
    checkout = svcs["checkout"]
    fx = svcs["fx"]

    async def empty_rates(currency):
        return []

    monkeypatch.setattr(fx, "btc_rates", empty_rates)
    body = await _payload(runtime_env, [
        {"d_tag": runtime_env["usd_item"]["d_tag"], "quantity": 1},
    ])
    from infinitemarkets.security import ProblemError

    with pytest.raises(ProblemError) as exc:
        await checkout.checkout(
            payload=body, idempotency_key=uuid.uuid4().hex * 2,
            client_scope="t8",
        )
    assert exc.value.code == "fx-unavailable"


@pytest.mark.parametrize("crash_at", ["before_invoice", "after_invoice"])
async def test_checkout_crash_keeps_idempotency_link(runtime_env, monkeypatch, crash_at):
    checkout = _svcs()["checkout"]
    body = await _payload(runtime_env, [
        {"d_tag": runtime_env["widget"]["d_tag"], "quantity": 1},
    ])
    key = uuid.uuid4().hex * 2
    scope = checkout._scope_hash(
        runtime_env["merchant_id"], "/api/v1/public/checkout", key,
    )

    async def crash(*args, **kwargs):
        raise asyncio.CancelledError()

    with monkeypatch.context() as patch:
        patch.setattr(
            checkout,
            "begin_saga" if crash_at == "before_invoice" else "_complete_idempotency",
            crash,
        )
        with pytest.raises(asyncio.CancelledError):
            await checkout.checkout(
                payload=body, idempotency_key=key, client_scope=crash_at,
            )

    from infinitemarkets.db import DomainTransaction

    async with DomainTransaction() as tx:
        record = await tx.fetch_one(
            f"SELECT order_id FROM {tx.table('idempotency_records')} WHERE scope_hash = :s",
            {"s": scope},
        )
        assert record["order_id"] is not None
        await tx.execute(
            f"UPDATE {tx.table('idempotency_records')} SET lease_until = 1"
            " WHERE scope_hash = :s",
            {"s": scope},
        )
    resumed = await checkout.checkout(
        payload=body, idempotency_key=key, client_scope=crash_at,
    )
    order = await _order_for_token(resumed["public_token"])
    assert order["id"] == record["order_id"]
    from lnbits.core.db import db as core_db

    async with core_db.connect() as conn:
        count = await conn.fetchone(
            "SELECT COUNT(*) AS n FROM apipayments WHERE external_id = :e",
            {"e": f"infinitemarkets:{order['id']}"},
        )
    assert count["n"] == 1


@pytest.mark.parametrize("invalid_quantity", [True, False])
async def test_boolean_quantity_is_rejected(runtime_env, invalid_quantity):
    from infinitemarkets.security import ProblemError

    with pytest.raises(ProblemError) as error:
        await _svcs()["checkout"].checkout(
            payload=await _payload(runtime_env, [
                {"d_tag": runtime_env["widget"]["d_tag"], "quantity": invalid_quantity},
            ]),
            idempotency_key=uuid.uuid4().hex * 2, client_scope="boolean-quantity",
        )
    assert error.value.status == 422


@pytest.mark.parametrize("unit,value", [("g", 500), ("lb", 2)])
async def test_shipping_weight_constraints_normalize_units(runtime_env, unit, value):
    option = {
        "weight_max": 1, "weight_min": None, "weight_unit": "kg",
        "dim_max_l": None, "dim_max_w": None, "dim_max_h": None,
        "dim_min_l": None, "dim_min_w": None, "dim_min_h": None,
        "dim_unit": None,
    }
    product = {
        "format": "physical", "weight_value": value, "weight_unit": unit,
        "dim_l": None, "dim_w": None, "dim_h": None, "dim_unit": None,
    }
    _svcs()["checkout"]._check_shipping_constraints(option, [{"product": product, "qty": 1}])


@pytest.mark.parametrize("problem", ["unassigned", "missing-region", "region-country-mismatch"])
async def test_shipping_rejects_invalid_coverage(runtime_env, problem):
    client = runtime_env["client"]
    headers = {"Origin": ORIGIN, "X-CSRF-Token": client.cookies.get("gm_csrf")}
    response = await client.post(
        f"{API}/shipping", headers=headers,
        json={
            "title": "restricted shipping", "service": "standard", "base_price_minor": 10,
            "currency": "SAT", "countries": ["US", "CA"], "regions": ["US-CA"],
        },
    )
    assert response.status_code == 201, response.text
    option = response.json()
    response = await client.post(
        f"{API}/products", headers=headers,
        json={
            "category_id": runtime_env["category_id"], "title": "shipping restrictions",
            "format": "physical", "visibility": "on-sale", "currency": "SAT",
            "amount_minor": 100, "stock_on_hand": 1,
            "shipping_option_ids": [] if problem == "unassigned" else [option["id"]],
        },
    )
    assert response.status_code == 201, response.text
    product = response.json()
    address = {"country": "CA" if problem == "region-country-mismatch" else "US", "line1": "Test"}
    if problem != "missing-region":
        address["region"] = "US-CA"
    from infinitemarkets.security import ProblemError

    with pytest.raises(ProblemError) as error:
        await _svcs()["checkout"].checkout(
            payload=await _payload(
                runtime_env, [{"d_tag": product["d_tag"], "quantity": 1}],
                shipping_option_d=option["d_tag"], address=address,
            ),
            idempotency_key=uuid.uuid4().hex * 2, client_scope=problem,
        )
    assert error.value.status == 422


@pytest.mark.parametrize("currency,base,fees,extra,expected", [
    ("SAT", 500, {}, None, 500),
    ("USD", 550, {}, None, 550),
    ("USD", 550, {}, 7, 564),
    ("JPY", 7, {}, None, 700),
    ("SAT", 10, {"price_weight_minor": 100, "price_weight_unit": "kg"}, None, 110),
    ("SAT", 10, {"price_weight_minor": 100, "price_weight_unit": "lb"}, None, 231),
    ("SAT", 10, {"price_volume_minor": 2, "price_volume_unit": "cm3"}, None, 4010),
    ("SAT", 10, {}, 7, 24),
])
async def test_shipping_quotes_include_precision_and_components(
    runtime_env, monkeypatch, currency, base, fees, extra, expected,
):
    async def rates(currency):
        return [("test-provider", 1_000_000.0)]

    monkeypatch.setattr(_svcs()["fx"], "btc_rates", rates)
    client = runtime_env["client"]
    headers = {"Origin": ORIGIN, "X-CSRF-Token": client.cookies.get("gm_csrf")}
    response = await client.post(
        f"{API}/shipping", headers=headers,
        json={
            "title": "priced shipping", "service": "standard", "base_price_minor": base,
            "currency": currency, "countries": ["US"], **fees,
        },
    )
    assert response.status_code == 201, response.text
    shipping = response.json()
    response = await client.post(
        f"{API}/products", headers=headers,
        json={
            "category_id": runtime_env["category_id"], "title": "shipping components",
            "format": "physical", "visibility": "on-sale", "currency": "SAT",
            "amount_minor": 100, "stock_on_hand": 5,
            "weight_value": 500, "weight_unit": "g",
            "dim_l": 10, "dim_w": 10, "dim_h": 10, "dim_unit": "cm",
            "shipping_option_ids": [{"id": shipping["id"], "extra_cost_minor": extra}],
        },
    )
    assert response.status_code == 201, response.text
    product = response.json()
    payload = await _payload(
        runtime_env, [{"d_tag": product["d_tag"], "quantity": 2}],
        shipping_option_d=shipping["d_tag"], address={"country": "US", "line1": "Test"},
    )
    preview = await client.post(f"{API}/public/quote", json=payload)
    assert preview.status_code == 200, preview.text
    assert preview.json() == {
        "subtotal_sat": 200, "shipping_sat": expected, "total_sat": 200 + expected,
    }
    assert preview.headers["cache-control"] == "no-store"
    fresh = await client.get(f"{API}/products/{product['id']}")
    assert fresh.json()["stock_reserved"] == 0
    result = await _svcs()["checkout"].checkout(
        payload={**payload, "expected_total_sat": preview.json()["total_sat"]},
        idempotency_key=uuid.uuid4().hex * 2, client_scope=uuid.uuid4().hex,
    )
    order = await _order_for_token(result["public_token"])
    assert order["shipping_sat"] == expected
    assert order["total_sat"] == 200 + expected


async def test_reclaimed_checkout_fences_stale_admission(runtime_env, monkeypatch):
    checkout = _svcs()["checkout"]
    db_module = importlib.import_module("infinitemarkets.db")
    original = checkout._insert_order_intake
    paused, resume = asyncio.Event(), asyncio.Event()
    captured = {}

    async def blocked_intake(**kwargs):
        if not captured:
            captured["scope"] = kwargs["scope"]
            paused.set()
            await resume.wait()
        return await original(**kwargs)

    monkeypatch.setattr(checkout, "_insert_order_intake", blocked_intake)
    client = runtime_env["client"]
    headers = {"Origin": ORIGIN, "X-CSRF-Token": client.cookies.get("gm_csrf")}
    response = await client.post(f"{API}/products", headers=headers, json={
        "category_id": runtime_env["category_id"], "title": "stale admission",
        "amount_minor": 100, "currency": "SAT", "format": "digital",
        "visibility": "on-sale", "stock_on_hand": 2,
    })
    assert response.status_code == 201, response.text
    payload = await _payload(runtime_env, [{"d_tag": response.json()["d_tag"], "quantity": 1}])
    key = uuid.uuid4().hex * 2
    first = asyncio.create_task(checkout.checkout(
        payload=payload, idempotency_key=key, client_scope="stale-admission",
    ))
    try:
        await asyncio.wait_for(paused.wait(), 3)
        async with db_module.DomainTransaction() as tx:
            await tx.execute(
                f"UPDATE {tx.table('idempotency_records')} SET lease_until = 0"
                " WHERE scope_hash = :s", {"s": captured["scope"]},
            )
        second = await checkout.checkout(
            payload=payload, idempotency_key=key, client_scope="stale-admission",
        )
        resume.set()
        with pytest.raises(checkout.ProblemError) as error:
            await first
        assert error.value.status == 409
        async with db_module.db.connect() as conn:
            row = await conn.fetchone(
                f"SELECT state FROM {db_module.table('idempotency_records')} WHERE scope_hash = :s",
                {"s": captured["scope"]},
            )
        assert row["state"] == "completed"
        replay = await checkout.checkout(
            payload=payload, idempotency_key=key, client_scope="stale-admission",
        )
        assert replay == second
    finally:
        resume.set()
        await asyncio.gather(first, return_exceptions=True)


async def test_stock_rejection_does_not_leave_recoverable_received_order(runtime_env, monkeypatch):
    checkout = _svcs()["checkout"]
    db_module = importlib.import_module("infinitemarkets.db")
    client = runtime_env["client"]
    headers = {"Origin": ORIGIN, "X-CSRF-Token": client.cookies.get("gm_csrf")}
    response = await client.post(f"{API}/products", headers=headers, json={
        "category_id": runtime_env["category_id"], "title": "stock rejection",
        "amount_minor": 100, "currency": "SAT", "format": "digital",
        "visibility": "on-sale", "stock_on_hand": 1,
    })
    assert response.status_code == 201, response.text
    product = response.json()
    original = checkout.begin_saga

    async def lose_stock(**kwargs):
        async with db_module.DomainTransaction() as tx:
            await tx.execute(
                f"UPDATE {tx.table('products')} SET stock_on_hand = 0 WHERE id = :i",
                {"i": product["id"]},
            )
        return await original(**kwargs)

    monkeypatch.setattr(checkout, "begin_saga", lose_stock)
    with pytest.raises(checkout.ProblemError) as error:
        await checkout.checkout(
            payload=await _payload(runtime_env, [{"d_tag": product["d_tag"], "quantity": 1}]),
            idempotency_key=uuid.uuid4().hex * 2, client_scope="stock-rejection",
        )
    assert error.value.status == 422
    async with db_module.db.connect() as conn:
        row = await conn.fetchone(
            f"SELECT o.state FROM {db_module.table('orders')} o"
            f" JOIN {db_module.table('order_items')} i ON i.order_id = o.id"
            " WHERE i.product_id = :p", {"p": product["id"]},
        )
    assert row["state"] == "rejected"


@pytest.mark.parametrize("cap", ["open", "held"])
async def test_checkout_caps_are_transactional(runtime_env, monkeypatch, cap):
    checkout = _svcs()["checkout"]
    db_module = importlib.import_module("infinitemarkets.db")
    client = runtime_env["client"]
    headers = {"Origin": ORIGIN, "X-CSRF-Token": client.cookies.get("gm_csrf")}
    response = await client.post(f"{API}/products", headers=headers, json={
        "category_id": runtime_env["category_id"], "title": f"{cap} cap race",
        "amount_minor": 100, "currency": "SAT", "format": "digital", "visibility": "on-sale",
    })
    assert response.status_code == 201, response.text
    product = response.json()
    counter = "_open_order_count" if cap == "open" else "_held_reservation_count"
    limit = "MAX_OPEN_ORDERS_PER_SCOPE" if cap == "open" else "MAX_HELD_PER_PRODUCT"
    monkeypatch.setattr(checkout, limit, 2)
    original = getattr(checkout, counter)
    arrived = 0
    ready = asyncio.Event()

    async def all_read_before_writing(*args):
        nonlocal arrived
        count = await original(*args)
        arrived += 1
        if arrived == 3:
            ready.set()
        await asyncio.wait_for(ready.wait(), 3)
        return count

    monkeypatch.setattr(checkout, counter, all_read_before_writing)
    payload = await _payload(runtime_env, [{"d_tag": product["d_tag"], "quantity": 1}])
    results = await asyncio.gather(*(
        checkout.checkout(
            payload=payload, idempotency_key=uuid.uuid4().hex * 2,
            client_scope=f"cap-{cap}" if cap == "open" else uuid.uuid4().hex,
        ) for _ in range(3)
    ), return_exceptions=True)
    assert sum(isinstance(result, dict) for result in results) == 2
    errors = [result for result in results if isinstance(result, Exception)]
    assert len(errors) == 1 and isinstance(errors[0], checkout.ProblemError)
    assert errors[0].status == (429 if cap == "open" else 422)
    async with db_module.db.connect() as conn:
        held = await conn.fetchone(
            f"SELECT COUNT(*) AS n FROM {db_module.table('inventory_reservations')}"
            " WHERE product_id = :p AND state = 'held'", {"p": product["id"]},
        )
    assert held["n"] == 2


async def test_duplicate_cart_items_are_rejected_before_intake(runtime_env):
    checkout = _svcs()["checkout"]
    item = {"d_tag": runtime_env["widget"]["d_tag"], "quantity": 1}
    with pytest.raises(checkout.ProblemError) as error:
        await checkout._resolve_items(runtime_env["merchant_id"], [item, item])
    assert error.value.status == 422


async def test_non_utc_database_blocks_financial_operations(runtime_env, monkeypatch):
    from infinitemarkets.services import readiness, settlement

    async def local_timezone():
        return "America/Los_Angeles"

    monkeypatch.setattr(readiness, "_database_timezone", local_timezone)
    checkout = _svcs()["checkout"]
    with pytest.raises(checkout.ProblemError) as error:
        await checkout.checkout(
            payload={}, idempotency_key=uuid.uuid4().hex,
            client_scope="timezone",
        )
    assert error.value.status == 503
    assert readiness.readiness()["checkout"] is False
    with pytest.raises(checkout.ProblemError):
        readiness.assert_checkout_ready()
    for operation in (settlement.reconcile, settlement.reservation_expiry_pass):
        with pytest.raises(checkout.ProblemError):
            await operation()

    async def utc_timezone():
        return "UTC"

    monkeypatch.setattr(readiness, "_database_timezone", utc_timezone)
    monkeypatch.setattr(readiness, "_process_uses_utc", lambda: False)
    with pytest.raises(checkout.ProblemError):
        await readiness.assert_database_compatible()
    monkeypatch.setattr(readiness, "_process_uses_utc", lambda: True)
    await readiness.assert_database_compatible()
    assert readiness.readiness()["checkout"] is True


async def test_changed_quote_creates_no_order_or_invoice(runtime_env):
    from infinitemarkets.db import db, table

    payload = await _payload(runtime_env, [
        {"d_tag": runtime_env["widget"]["d_tag"], "quantity": 1},
    ])
    client = runtime_env["client"]
    quoted = await client.post(f"{API}/public/quote", json=payload)
    assert quoted.status_code == 200, quoted.text
    async with db.connect() as conn:
        before = await conn.fetchone(
            f"SELECT COUNT(*) AS n FROM {table('orders')}"
        )
    result = await client.post(
        f"{API}/public/checkout",
        json={**payload, "expected_total_sat": quoted.json()["total_sat"] + 1},
        headers={"Idempotency-Key": uuid.uuid4().hex * 2, "Origin": ORIGIN},
    )
    assert result.status_code == 422, result.text
    assert result.json()["type"] == "urn:infinitemarkets:quote-changed"
    async with db.connect() as conn:
        after = await conn.fetchone(
            f"SELECT COUNT(*) AS n FROM {table('orders')}"
        )
    assert after["n"] == before["n"]
