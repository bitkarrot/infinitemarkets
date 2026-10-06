"""02-04 Release-A journey — one continuous merchant+buyer pass through
every surface the plan ships: catalog → public storefront → checkout →
invoice → settlement → order workspace action → publications →
notifications → appearance, all through the real host boot."""

from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio

pytestmark = pytest.mark.runtime

ORIGIN = "https://shop.example"
API = "/infinitemarkets/api/v1"
PUBLIC = f"{API}/public"


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
              "display_name": "journey shop"},
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
    cid = resp.json()["id"]
    resp = await client.post(
        f"{API}/products",
        json={"category_id": cid, "title": "tour", "amount_minor": 2500,
              "currency": "SAT", "visibility": "on-sale",
              "stock_on_hand": 3, "format": "digital"},
        headers=await cookie(),
    )
    product = resp.json()

    async with DomainTransaction() as tx:
        merchant = await tx.fetch_one(
            "SELECT pubkey FROM merchants WHERE id = :m", {"m": mid},
        )

    import httpx

    anon = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=runtime_env["app"]),
        base_url=ORIGIN,
    )
    runtime_env.update({
        "merchant_id": mid, "product": product,
        "pubkey": merchant["pubkey"], "anon": anon, "cookie": cookie,
    })
    from infinitemarkets.services import readiness

    readiness.mark_reconciled()
    yield
    await anon.aclose()


async def test_release_a_journey(runtime_env):
    client = runtime_env["client"]
    anon = runtime_env["anon"]
    mid = runtime_env["merchant_id"]
    product = runtime_env["product"]
    pubkey = runtime_env["pubkey"]

    # 1. Public product page renders the checkout card.
    page = await anon.get(f"/infinitemarkets/p/{pubkey}/{product['d_tag']}")
    assert page.status_code == 200
    assert 'id="gm-checkout-card"' in page.text
    assert 'data-sum="total"' in page.text

    # 2. Buyer checkout — Idempotency-Key header, 201 + order projection.
    idem = uuid.uuid4().hex * 2
    checkout = await anon.post(
        f"{PUBLIC}/checkout",
        json={"merchant_pubkey": pubkey,
              "items": [{"d_tag": product["d_tag"], "quantity": 1}]},
        headers={"Idempotency-Key": idem, "Origin": ORIGIN},
    )
    assert checkout.status_code == 201, checkout.text
    body = checkout.json()
    token = body["public_token"]
    assert body["order"]["state"] == "awaiting_payment"
    assert body["order"]["total_sat"] == 2500
    assert body["order"]["bolt11"].startswith("ln")

    # 2b. Replay with the SAME key renders the existing order — never a
    # second invoice (409 or stored-response 200/201).
    replay = await anon.post(
        f"{PUBLIC}/checkout",
        json={"merchant_pubkey": pubkey,
              "items": [{"d_tag": product["d_tag"], "quantity": 1}]},
        headers={"Idempotency-Key": idem, "Origin": ORIGIN},
    )
    assert replay.status_code in (200, 201, 409)
    assert replay.json()["public_token"] == token

    # 3. Buyer status page + header-token polling.
    order_page = await anon.get("/infinitemarkets/order")
    assert order_page.status_code == 200
    status = await anon.get(
        f"{PUBLIC}/order-status", headers={"X-Order-Token": token}
    )
    assert status.status_code == 200
    assert status.json()["state"] == "awaiting_payment"

    # 4. Settlement → confirmed (durable truth — relay delivery plays no
    # part).
    from infinitemarkets.crypto import token_lookup_hash
    from infinitemarkets.db import db

    async with db.connect() as conn:
        order = dict(await conn.fetchone(
            "SELECT * FROM infinitemarkets.orders WHERE public_token_hash = :h",
            {"h": token_lookup_hash(token)},
        ))
    import importlib

    settlement = importlib.import_module("infinitemarkets.services.settlement")
    await settlement.confirm_settlement(order_id=order["id"], source="test")
    status = await anon.get(
        f"{PUBLIC}/order-status", headers={"X-Order-Token": token}
    )
    assert status.json()["state"] == "confirmed"
    assert status.json()["bolt11"] is None

    # 5. Admin order workspace — list row, detail, events, legal action.
    cookie = runtime_env["cookie"]
    headers = await cookie()
    orders = await client.get(
        f"{API}/merchants/{mid}/orders", headers=headers
    )
    assert orders.status_code == 200
    row = next(r for r in orders.json() if r["id"] == order["id"])
    assert row["state"] == "confirmed"
    assert row["first_item"] == "tour"

    detail = await client.get(
        f"{API}/merchants/{mid}/orders/{order['id']}", headers=headers
    )
    assert detail.status_code == 200
    assert detail.json()["items"][0]["title"] == "tour"

    events = await client.get(
        f"{API}/merchants/{mid}/orders/{order['id']}/events",
        headers=headers,
    )
    assert any(
        e["to_state"] == "confirmed" for e in events.json()
    )

    # confirmed → processing is the legal merchant action.
    moved = await client.post(
        f"{API}/merchants/{mid}/orders/{order['id']}/status",
        json={"to_state": "processing"}, headers=headers,
    )
    assert moved.status_code == 200, moved.text

    # 6. Publications — health + outbox surfaces answer (empty is fine —
    # RELAY_IO=off in tests; the contract is the shape).
    health = await client.get(
        f"{API}/merchants/{mid}/relay-health", headers=headers
    )
    assert health.status_code == 200
    assert "relays" in health.json()
    outbox = await client.get(
        f"{API}/merchants/{mid}/outbox", headers=headers
    )
    assert outbox.status_code == 200
    assert "intents" in outbox.json()

    # 7. Notifications — save an address, queue a test send, see the row.
    patched = await client.patch(
        f"{API}/merchants/{mid}/notifications",
        json={"notify_emails": ["ops@example.com"]},
        headers=headers,
    )
    assert patched.status_code == 200, patched.text
    test_send = await client.post(
        f"{API}/merchants/{mid}/notifications/test",
        json={"recipient": "ops@example.com"},
        headers=headers,
    )
    assert test_send.status_code == 200, test_send.text
    notif = await client.get(
        f"{API}/merchants/{mid}/notifications", headers=headers
    )
    assert notif.json()["notify_emails"] == ["ops@example.com"]
    # The test send lands as an orderless merchant-channel queue row.
    assert any(
        q["channel"] == "merchant" and not q["order_bound"]
        for q in notif.json()["queue"]
    )

    # 8. Appearance — save a theme; the public page emits scoped tokens.
    themed = await client.patch(
        f"{API}/merchants/{mid}",
        json={"theme": {"preset": "clean-minimal",
                        "layout": "guided"}},
        headers=headers,
    )
    assert themed.status_code == 200, themed.text
    page = await anon.get(f"/infinitemarkets/p/{pubkey}/{product['d_tag']}")
    assert 'data-layout="guided"' in page.text
    assert "--color-bg: #f4f7f7" in page.text

    # 9. Admin shell still serves for the owner.
    admin = await client.get("/infinitemarkets/")
    assert admin.status_code == 200
    assert 'id="gm-admin-root"' in admin.text
