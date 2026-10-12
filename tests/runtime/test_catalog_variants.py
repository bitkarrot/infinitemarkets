from __future__ import annotations

import asyncio
import uuid

import pytest
from test_order_saga import (
    API,
    _mpk,
    _row,
    _settle_core_payment,
    _svcs,
)
from test_order_saga import (
    _setup as _setup,
)

pytestmark = pytest.mark.runtime


async def _variation(runtime_env):
    client = runtime_env["client"]
    headers = await runtime_env["cookie"]()
    parent = await client.post(f"{API}/products", headers=headers, json={
        "category_id": runtime_env["category_id"], "title": uuid.uuid4().hex,
        "product_type": "variable", "visibility": "on-sale",
    })
    assert parent.status_code == 201, parent.text
    child = await client.post(f"{API}/products", headers=headers, json={
        "category_id": runtime_env["category_id"], "title": uuid.uuid4().hex,
        "product_type": "variation", "parent_product_id": parent.json()["id"],
        "amount_minor": 100, "currency": "SAT", "format": "digital",
        "visibility": "on-sale", "stock_on_hand": 1,
    })
    assert child.status_code == 201, child.text
    return parent.json(), child.json()


async def _checkout(runtime_env, product):
    from infinitemarkets.crypto import token_lookup_hash

    response = await _svcs()["checkout"].checkout(
        payload={"merchant_pubkey": await _mpk(runtime_env),
                 "items": [{"d_tag": product["d_tag"], "quantity": 1}]},
        idempotency_key=uuid.uuid4().hex * 2, client_scope=uuid.uuid4().hex,
    )
    return await _row(
        "SELECT * FROM infinitemarkets.orders WHERE public_token_hash = :h",
        {"h": token_lookup_hash(response["public_token"])},
    )


@pytest.mark.parametrize("competitor", ["accept", "checkout"])
async def test_hard03_variation_competing_capacity(runtime_env, monkeypatch, competitor):
    from infinitemarkets.db import DomainTransaction, dialect

    svcs = _svcs()
    parent, product = await _variation(runtime_env)
    orders = []
    for _ in range(2 if competitor == "accept" else 1):
        order = await _checkout(runtime_env, product)
        await svcs["orders"].cancel_order(order_id=order["id"], actor="buyer", reason=None)
        payment = await _settle_core_payment(order["id"], order["total_sat"])
        await svcs["settlement"].invoice_listener(payment)
        orders.append(order)
    before_parent = await _row(
        "SELECT revision FROM infinitemarkets.products WHERE id = :p", {"p": parent["id"]},
    )
    fetch, enter = DomainTransaction.fetch_one, DomainTransaction.__aenter__
    ready = asyncio.Event()
    participants, arrived, connections = set(), set(), set()

    async def barrier(task):
        arrived.add(task)
        if len(arrived) == 2:
            ready.set()
        await asyncio.wait_for(ready.wait(), 5)

    async def controlled_enter(self):
        task = asyncio.current_task()
        if dialect() == "sqlite" and task in participants and task not in arrived:
            await barrier(task)
        return await enter(self)

    async def controlled_fetch(self, sql, params=None):
        task = asyncio.current_task()
        contested = (dialect() == "postgres" and task in participants and task not in arrived
                     and "SELECT" in sql and "products" in sql
                     and params and params.get("p") == product["id"])
        if contested:
            pid = await fetch(self, "SELECT pg_backend_pid() AS pid")
            connections.add(pid["pid"])
            if sql.endswith(" FOR UPDATE"):
                await barrier(task)
            else:
                row = await fetch(self, sql, params)
                await barrier(task)
                return row
        return await fetch(self, sql, params)

    monkeypatch.setattr(DomainTransaction, "__aenter__", controlled_enter)
    monkeypatch.setattr(DomainTransaction, "fetch_one", controlled_fetch)
    first = asyncio.create_task(svcs["settlement"].resolve_exception(
        order_id=orders[0]["id"], action="accept",
    ))
    if competitor == "accept":
        second = asyncio.create_task(svcs["settlement"].resolve_exception(
            order_id=orders[1]["id"], action="accept",
        ))
    else:
        second = asyncio.create_task(_checkout(runtime_env, product))
    participants.update((first, second))
    try:
        results = await asyncio.wait_for(asyncio.gather(first, second, return_exceptions=True), 8)
    finally:
        for task in (first, second):
            if not task.done():
                task.cancel()
        await asyncio.gather(first, second, return_exceptions=True)
    assert len(arrived) == 2, "both independent contenders must reach the barrier"
    if dialect() == "postgres":
        assert len(connections) == 2, "PostgreSQL contention requires independent connections"
    assert not isinstance(results[0], BaseException), results
    stock = await _row(
        "SELECT stock_on_hand, stock_reserved FROM infinitemarkets.products WHERE id = :p",
        {"p": product["id"]},
    )
    assert stock["stock_on_hand"] >= stock["stock_reserved"] >= 0, results
    if competitor == "accept":
        assert all(
            isinstance(result, dict) and result["action"] == "accepted" for result in results
        )
        shorts = [await _row(
            "SELECT backordered_qty FROM infinitemarkets.order_items WHERE order_id = :o",
            {"o": order["id"]},
        ) for order in orders]
        assert sorted(row["backordered_qty"] for row in shorts) == [0, 1]
        assert stock == {"stock_on_hand": 0, "stock_reserved": 0}
    else:
        assert stock["stock_on_hand"] == stock["stock_reserved"]
        assert results[0]["oversold"] == bool(stock["stock_reserved"])
    current_parent = await _row(
        "SELECT revision FROM infinitemarkets.products WHERE id = :p", {"p": parent["id"]},
    )
    assert current_parent["revision"] > before_parent["revision"], (
        "real stock change republishes parent"
    )
    publication = await _row(
        "SELECT COUNT(*) AS n FROM infinitemarkets.outbox_events "
        "WHERE aggregate_id = :p AND aggregate_revision = :r",
        {"p": parent["id"], "r": current_parent["revision"]},
    )
    assert publication["n"] > 0


@pytest.mark.parametrize("scope", ["same_order", "shared_parent"])
async def test_hard03_accept_lockset_finishes_once(runtime_env, monkeypatch, scope):
    from infinitemarkets.db import DomainTransaction, dialect
    from infinitemarkets.security import ProblemError

    svcs = _svcs()
    parent, first_product = await _variation(runtime_env)
    products = [first_product]
    if scope == "shared_parent":
        response = await runtime_env["client"].post(
            f"{API}/products", headers=await runtime_env["cookie"](), json={
                "category_id": runtime_env["category_id"], "title": uuid.uuid4().hex,
                "product_type": "variation", "parent_product_id": parent["id"],
                "amount_minor": 100, "currency": "SAT", "format": "digital",
                "visibility": "on-sale", "stock_on_hand": 1,
            },
        )
        assert response.status_code == 201, response.text
        products.append(response.json())
    orders = []
    for product in products:
        order = await _checkout(runtime_env, product)
        await svcs["orders"].cancel_order(order_id=order["id"], actor="buyer", reason=None)
        payment = await _settle_core_payment(order["id"], order["total_sat"])
        await svcs["settlement"].invoice_listener(payment)
        orders.append(order)
    enter = DomainTransaction.__aenter__
    participants, arrived, connections = set(), set(), set()
    ready = asyncio.Event()

    async def controlled_enter(self):
        task = asyncio.current_task()
        if task not in participants:
            return await enter(self)
        if dialect() == "postgres":
            tx = await enter(self)
            pid = await tx.fetch_one("SELECT pg_backend_pid() AS pid")
            connections.add(pid["pid"])
        arrived.add(task)
        if len(arrived) == 2:
            ready.set()
        try:
            await asyncio.wait_for(ready.wait(), 5)
        except BaseException as error:
            if dialect() == "postgres":
                await tx.__aexit__(type(error), error, error.__traceback__)
            raise
        return tx if dialect() == "postgres" else await enter(self)

    monkeypatch.setattr(DomainTransaction, "__aenter__", controlled_enter)
    calls = [asyncio.create_task(svcs["settlement"].resolve_exception(
        order_id=orders[index if scope == "shared_parent" else 0]["id"], action="accept",
    )) for index in range(2)]
    participants.update(calls)
    try:
        results = await asyncio.wait_for(asyncio.gather(*calls, return_exceptions=True), 8)
    finally:
        for call in calls:
            if not call.done():
                call.cancel()
        await asyncio.gather(*calls, return_exceptions=True)
    assert len(arrived) == 2
    if dialect() == "postgres":
        assert len(connections) == 2
    if scope == "same_order":
        assert sum(isinstance(result, dict) and result["action"] == "accepted"
                   for result in results) == 1
        assert sum(isinstance(result, ProblemError) and result.code == "invalid-transition"
                   for result in results) == 1
    else:
        assert all(
            isinstance(result, dict) and result["action"] == "accepted" for result in results
        )
    for product in products:
        stock = await _row(
            "SELECT stock_on_hand, stock_reserved FROM infinitemarkets.products WHERE id = :p",
            {"p": product["id"]},
        )
        assert stock == {"stock_on_hand": 0, "stock_reserved": 0}
    for order in orders:
        event = await _row(
            "SELECT COUNT(*) AS n FROM infinitemarkets.order_events WHERE order_id = :o "
            "AND to_state = 'confirmed'", {"o": order["id"]},
        )
        assert event["n"] == 1
