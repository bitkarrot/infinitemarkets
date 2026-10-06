"""Section 5.3 admin order API through the real host boot: owner scoping,
the legal-transition matrix, cancel-with-reason, exception resolution
(accept | refund | confirm-refund) with attestation honesty, token
reissue, decrypted-PII owner gating, event chronology, and admin
Idempotency-Key acceptance."""

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
              "display_name": "admin shop",
              },
        headers=await cookie(),
    )
    assert resp.status_code == 201, resp.text
    mid = resp.json()["id"]
    resp = await client.patch(
        f"{API}/merchants/{mid}",
        json={"notify_emails": ["admin@example.com"]},
        headers=await cookie(),
    )
    assert resp.status_code == 200, resp.text
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

    async def product(title, stock, fmt="digital") -> dict:
        resp = await client.post(
            f"{API}/products",
            json={
                "category_id": cid, "title": title,
                "amount_minor": 500, "currency": "SAT",
                "visibility": "on-sale", "stock_on_hand": stock,
                "format": fmt,
                "shipping_option_ids": [shipping_id] if fmt == "physical" else [],
            },
            headers=await cookie(),
        )
        assert resp.status_code == 201, resp.text
        return resp.json()

    resp = await client.post(
        f"{API}/shipping",
        json={
            "d_tag": "std-ship", "title": "Standard",
            "base_price_minor": 100, "currency": "SAT",
            "countries": ["US"], "active": True,
        },
        headers=await cookie(),
    )
    assert resp.status_code == 201, resp.text
    shipping_id = resp.json()["id"]

    async with DomainTransaction() as tx:
        merchant = await tx.fetch_one(
            "SELECT pubkey FROM merchants WHERE id = :m", {"m": mid},
        )

    from infinitemarkets.services import readiness

    readiness.mark_reconciled()

    import httpx

    anon = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=runtime_env["app"]),
        base_url=ORIGIN,
    )
    runtime_env.update({
        "merchant_id": mid, "category_id": cid,
        "merchant_pubkey": merchant["pubkey"],
        "make_product": product, "cookie": cookie, "anon": anon,
    })
    yield
    await anon.aclose()


def _svcs():
    import importlib

    return {
        name: importlib.import_module(f"infinitemarkets.services.{name}")
        for name in ("checkout", "orders", "settlement")
    }


async def _order(runtime_env, *, fmt="digital", address=False) -> dict:
    """Fresh awaiting_payment order; returns the raw row."""
    svcs = _svcs()
    product = await runtime_env["make_product"](
        uuid.uuid4().hex[:8], 10, fmt
    )
    payload = {
        "merchant_pubkey": runtime_env["merchant_pubkey"],
        "items": [{"d_tag": product["d_tag"], "quantity": 2}],
    }
    if address:
        payload["shipping_option_d"] = "std-ship"
        payload["address"] = {
            "name": "Buyer One", "line1": "1 Main St",
            "city": "Springfield", "region": "US-IL", "country": "US",
            "postal_code": "62701",
        }
        payload["email"] = "buyer@example.com"
        payload["email_opt_in"] = True
    resp = await svcs["checkout"].checkout(
        payload=payload, idempotency_key=uuid.uuid4().hex * 2,
        client_scope="admin-test",
    )
    from infinitemarkets.crypto import token_lookup_hash
    from infinitemarkets.db import db

    async with db.connect() as conn:
        order = dict(await conn.fetchone(
            "SELECT * FROM infinitemarkets.orders WHERE public_token_hash = :h",
            {"h": token_lookup_hash(resp["public_token"])},
        ))
    order["_token"] = resp["public_token"]
    order["_product"] = product
    return order


def _admin(runtime_env, oid: str) -> str:
    return f"{API}/merchants/{runtime_env['merchant_id']}/orders/{oid}"


async def test_list_and_detail(runtime_env):
    client = runtime_env["client"]
    mid = runtime_env["merchant_id"]
    order = await _order(runtime_env)

    resp = await client.get(f"{API}/merchants/{mid}/orders")
    assert resp.status_code == 200
    ids = [o["id"] for o in resp.json()]
    assert order["id"] in ids

    resp = await client.get(
        f"{API}/merchants/{mid}/orders", params={"state": "awaiting_payment"}
    )
    assert resp.status_code == 200
    assert all(o["state"] == "awaiting_payment" for o in resp.json())

    resp = await client.get(
        f"{API}/merchants/{mid}/orders", params={"state": "bogus"}
    )
    assert resp.status_code == 422
    assert resp.json()["type"] == "urn:infinitemarkets:invalid-transition"

    # UI-SPEC filter set: needs_attention + order-id prefix search.
    resp = await client.get(
        f"{API}/merchants/{mid}/orders",
        params={"state": "needs_attention"},
    )
    assert resp.status_code == 200
    assert all(
        o["payment_exception"] or o["oversold"] for o in resp.json()
    )
    resp = await client.get(
        f"{API}/merchants/{mid}/orders",
        params={"q": order["id"][:12]},
    )
    assert resp.status_code == 200
    assert [o["id"] for o in resp.json()] == [order["id"]]
    resp = await client.get(
        f"{API}/merchants/{mid}/orders",
        params={"protocol": "web"},
    )
    assert all(o["protocol"] == "web" for o in resp.json())

    detail = (await client.get(_admin(runtime_env, order["id"]))).json()
    assert detail["state"] == "awaiting_payment"
    assert detail["total_sat"] == 1000
    assert len(detail["items"]) == 1
    assert detail["payment"]["status"] == "pending"


async def test_bulk_archive_and_restore_closed_orders(runtime_env):
    client = runtime_env["client"]
    cookie = runtime_env["cookie"]
    mid = runtime_env["merchant_id"]
    closed = await _order(runtime_env)
    active = await _order(runtime_env)
    services = _svcs()
    result = await services["settlement"].confirm_settlement(
        order_id=closed["id"], source="test"
    )
    assert result["action"] == "confirmed"
    for to_state in ("processing", "completed"):
        response = await client.post(
            f"{_admin(runtime_env, closed['id'])}/status",
            json={"to_state": to_state},
            headers=await cookie(),
        )
        assert response.status_code == 200, response.text

    listed = {
        item["id"]: item
        for item in (await client.get(f"{API}/merchants/{mid}/orders")).json()
    }
    assert listed[closed["id"]]["archive_eligible"] is True
    assert listed[active["id"]]["archive_eligible"] is False

    from infinitemarkets.db import db

    async with db.connect() as conn:
        before = dict(
            await conn.fetchone(
                "SELECT updated_at FROM infinitemarkets.orders WHERE id = :o",
                {"o": closed["id"]},
            )
        )
        related_before = {
            table: (
                await conn.fetchone(
                    f"SELECT COUNT(*) AS n FROM infinitemarkets.{table} "
                    "WHERE order_id = :o",
                    {"o": closed["id"]},
                )
            )["n"]
            for table in ("payments", "order_events", "inventory_reservations")
        }

    bulk_url = f"{API}/merchants/{mid}/orders/bulk"
    response = await client.post(
        bulk_url,
        json={"order_ids": [closed["id"], active["id"]], "action": "archive"},
        headers=await cookie(),
    )
    assert response.status_code == 422
    async with db.connect() as conn:
        row = await conn.fetchone(
            "SELECT archived_at FROM infinitemarkets.orders WHERE id = :o",
            {"o": closed["id"]},
        )
    assert row["archived_at"] is None

    response = await client.post(
        bulk_url,
        json={"order_ids": [closed["id"], "0" * 32], "action": "archive"},
        headers=await cookie(),
    )
    assert response.status_code == 404

    response = await client.post(
        bulk_url,
        json={"order_ids": [closed["id"]], "action": "archive"},
        headers=await cookie(),
    )
    assert response.status_code == 200, response.text
    assert response.json()["archived"] == 1

    active_orders = (
        await client.get(f"{API}/merchants/{mid}/orders")
    ).json()
    archived_orders = (
        await client.get(
            f"{API}/merchants/{mid}/orders", params={"archived": True}
        )
    ).json()
    assert closed["id"] not in {order["id"] for order in active_orders}
    assert closed["id"] in {order["id"] for order in archived_orders}
    detail = (await client.get(_admin(runtime_env, closed["id"]))).json()
    assert detail["archived_at"] is not None

    async with db.connect() as conn:
        after = dict(
            await conn.fetchone(
                "SELECT updated_at FROM infinitemarkets.orders WHERE id = :o",
                {"o": closed["id"]},
            )
        )
        related_after = {
            table: (
                await conn.fetchone(
                    f"SELECT COUNT(*) AS n FROM infinitemarkets.{table} "
                    "WHERE order_id = :o",
                    {"o": closed["id"]},
                )
            )["n"]
            for table in ("payments", "order_events", "inventory_reservations")
        }
    assert after["updated_at"] == before["updated_at"]
    assert related_after == related_before

    response = await client.post(
        bulk_url,
        json={"order_ids": [closed["id"]], "action": "restore"},
        headers=await cookie(),
    )
    assert response.status_code == 200, response.text
    assert response.json()["restored"] == 1
    active_orders = (
        await client.get(f"{API}/merchants/{mid}/orders")
    ).json()
    assert closed["id"] in {order["id"] for order in active_orders}


async def test_archived_late_payment_returns_to_active_attention(runtime_env):
    client = runtime_env["client"]
    cookie = runtime_env["cookie"]
    mid = runtime_env["merchant_id"]
    order = await _order(runtime_env)
    services = _svcs()
    result = await services["settlement"].expire_order(order_id=order["id"])
    assert result["action"] == "expired"

    bulk_url = f"{API}/merchants/{mid}/orders/bulk"
    response = await client.post(
        bulk_url,
        json={"order_ids": [order["id"]], "action": "archive"},
        headers=await cookie(),
    )
    assert response.status_code == 200, response.text

    result = await services["settlement"].confirm_settlement(
        order_id=order["id"], source="test"
    )
    assert result["action"] == "exception"
    active_orders = (
        await client.get(f"{API}/merchants/{mid}/orders")
    ).json()
    active = next(item for item in active_orders if item["id"] == order["id"])
    assert active["payment_exception"] is True
    assert active["archived_at"] is not None

    response = await client.post(
        f"{_admin(runtime_env, order['id'])}/resolve-exception",
        json={"action": "accept"},
        headers=await cookie(),
    )
    assert response.status_code == 200, response.text
    detail = (await client.get(_admin(runtime_env, order["id"]))).json()
    assert detail["state"] == "confirmed"
    assert detail["payment_exception"] is False
    assert detail["archived_at"] is None


async def test_transition_matrix(runtime_env):
    """Legal transitions accepted; illegal -> 422 invalid-transition."""
    client = runtime_env["client"]
    cookie = runtime_env["cookie"]
    order = await _order(runtime_env)
    url = _admin(runtime_env, order["id"])

    # awaiting_payment -> completed is NOT legal.
    resp = await client.post(
        f"{url}/status", json={"to_state": "completed"},
        headers=await cookie(),
    )
    assert resp.status_code == 422
    assert resp.json()["type"] == "urn:infinitemarkets:invalid-transition"

    # awaiting_payment -> confirmed -> processing -> completed is.
    for to_state in ("confirmed", "processing", "completed"):
        resp = await client.post(
            f"{url}/status", json={"to_state": to_state},
            headers=await cookie(),
        )
        assert resp.status_code == 200, (to_state, resp.text)
        assert resp.json()["state"] == to_state

    # Terminal: completed -> anything rejects.
    resp = await client.post(
        f"{url}/status", json={"to_state": "cancelled"},
        headers=await cookie(),
    )
    assert resp.status_code == 422
    assert resp.json()["type"] == "urn:infinitemarkets:invalid-transition"

    # Email intents were enqueued per transition.
    from infinitemarkets.db import db

    async with db.connect() as conn:
        rows = await conn.fetchall(
            "SELECT event_type FROM infinitemarkets.email_queue"
            " WHERE order_id = :o AND channel = 'merchant'",
            {"o": order["id"]},
        )
    types = {r["event_type"] for r in rows}
    assert {"confirmed", "processing"} <= types


async def test_cancel_releases_stock_once(runtime_env):
    client = runtime_env["client"]
    cookie = runtime_env["cookie"]
    order = await _order(runtime_env)
    product = order["_product"]
    url = _admin(runtime_env, order["id"])

    resp = await client.post(
        f"{url}/cancel", json={"reason": "merchant test"},
        headers=await cookie(),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["action"] == "cancelled"
    assert resp.json()["released"] == 2

    from infinitemarkets.db import db

    async with db.connect() as conn:
        prod = dict(await conn.fetchone(
            "SELECT stock_on_hand, stock_reserved FROM"
            " infinitemarkets.products WHERE id = :p",
            {"p": product["id"]},
        ))
        assert prod["stock_on_hand"] == 10
        assert prod["stock_reserved"] == 0
        res = dict(await conn.fetchone(
            "SELECT state FROM infinitemarkets.inventory_reservations"
            " WHERE order_id = :o",
            {"o": order["id"]},
        ))
        assert res["state"] == "released"
        ev = dict(await conn.fetchone(
            "SELECT actor, detail_json FROM infinitemarkets.order_events"
            " WHERE order_id = :o AND to_state = 'cancelled'",
            {"o": order["id"]},
        ))
        assert ev["actor"] == "merchant"
        assert "merchant test" in ev["detail_json"]

    # Second cancel is an explicit no-op — nothing double-releases.
    resp = await client.post(
        f"{url}/cancel", json={}, headers=await cookie(),
    )
    assert resp.status_code == 200
    assert resp.json()["action"] == "no-op-already-cancelled"
    async with db.connect() as conn:
        prod = dict(await conn.fetchone(
            "SELECT stock_reserved FROM infinitemarkets.products"
            " WHERE id = :p",
            {"p": product["id"]},
        ))
        assert prod["stock_reserved"] == 0


async def test_exception_refund_attestation(runtime_env):
    """refund = attestation only (honest note + refund_requested intent);
    confirm-refund closes the exception."""
    client = runtime_env["client"]
    cookie = runtime_env["cookie"]
    order = await _order(runtime_env)
    url = _admin(runtime_env, order["id"])
    from infinitemarkets.db import DomainTransaction

    async with DomainTransaction() as tx:
        await tx.execute(
            "UPDATE orders SET payment_exception = TRUE"
            " WHERE id = :i",
            {"i": order["id"]},
        )

    resp = await client.post(
        f"{url}/resolve-exception",
        json={"action": "refund", "refund_reference": "ln-tx-xyz"},
        headers=await cookie(),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["action"] == "refund_requested"
    assert "attestation" in body["note"]
    assert "cannot verify" in body["note"]

    resp = await client.post(
        f"{url}/resolve-exception",
        json={"action": "confirm-refund",
              "refund_reference": "ln-tx-xyz"},
        headers=await cookie(),
    )
    assert resp.status_code == 200
    assert resp.json()["action"] == "refund_confirmed"

    detail = (await client.get(url)).json()
    assert detail["payment_exception"] is False
    assert detail["payment_exception_resolution"] == "refund_confirmed"

    from infinitemarkets.db import db

    async with db.connect() as conn:
        rows = await conn.fetchall(
            "SELECT event_type FROM infinitemarkets.email_queue"
            " WHERE order_id = :o AND event_type = 'refund_requested'",
            {"o": order["id"]},
        )
    assert rows  # the intent exists (merchant channel)

    # Bad action -> 422.
    resp = await client.post(
        f"{url}/resolve-exception", json={"action": "voodoo"},
        headers=await cookie(),
    )
    assert resp.status_code == 422


async def test_token_reissue(runtime_env):
    """Reissue revokes the old token immediately (401) and returns a new
    link exactly once."""
    client = runtime_env["client"]
    anon = runtime_env["anon"]
    cookie = runtime_env["cookie"]
    order = await _order(runtime_env)
    old_token = order["_token"]

    resp = await client.post(
        f"{_admin(runtime_env, order['id'])}/public-token/reissue",
        headers=await cookie(),
    )
    assert resp.status_code == 200, resp.text
    new_token = resp.json()["public_token"]
    assert new_token and new_token != old_token

    resp = await anon.get(
        f"{PUBLIC}/order-status", headers={"X-Order-Token": old_token}
    )
    assert resp.status_code == 401
    resp = await anon.get(
        f"{PUBLIC}/order-status", headers={"X-Order-Token": new_token}
    )
    assert resp.status_code == 200


async def test_decrypted_pii_owner_only(runtime_env):
    """The owner sees decrypted contact+address; a second user gets 404
    on the same detail path."""
    client = runtime_env["client"]
    order = await _order(runtime_env, fmt="physical", address=True)
    url = _admin(runtime_env, order["id"])

    detail = (await client.get(url)).json()
    assert detail["contact"]["email"] == "buyer@example.com"
    assert detail["address"]["city"] == "Springfield"
    assert detail["shipping_state"] == "pending"

    import uuid as _uuid

    import httpx
    from lnbits.core.crud import create_wallet
    from lnbits.core.crud.users import create_account
    from lnbits.core.models.users import Account

    username = f"gqadminb{_uuid.uuid4().hex[:8]}"
    password = "other-pass-123"
    account = Account(id=_uuid.uuid4().hex, username=username, email=None)
    account.hash_password(password)
    await create_account(account)
    await create_wallet(user_id=account.id, wallet_name="b")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=runtime_env["app"]),
        base_url=ORIGIN,
    ) as c2:
        resp = await c2.post(
            "/api/v1/auth",
            json={"username": username, "password": password},
        )
        token = resp.json()["access_token"]
        await c2.put(
            "/api/v1/extension/infinitemarkets/enable",
            headers={
                "Cookie": f"cookie_access_token={token}",
                "Origin": ORIGIN,
            },
        )
        for method in ("get", "post"):
            resp = await getattr(c2, method)(
                url if method == "get" else f"{url}/cancel",
                **({} if method == "get" else {"json": {}}),
                headers={
                    "Cookie": f"cookie_access_token={token}",
                    "Origin": ORIGIN,
                },
            )
            # user B has no merchant row -> 404 before the order resolves.
            assert resp.status_code in (401, 403, 404), (
                method, resp.status_code, resp.text
            )


async def test_events_chronology(runtime_env):
    client = runtime_env["client"]
    cookie = runtime_env["cookie"]
    order = await _order(runtime_env)
    url = _admin(runtime_env, order["id"])
    await client.post(
        f"{url}/status", json={"to_state": "confirmed"},
        headers=await cookie(),
    )
    resp = await client.get(f"{url}/events")
    assert resp.status_code == 200
    events = resp.json()
    assert len(events) >= 3  # received, invoice_pending, awaiting_payment, confirmed
    states = [(e["from_state"], e["to_state"]) for e in events]
    assert ("received", "invoice_pending") in states
    assert ("awaiting_payment", "confirmed") in states
    times = [e["created_at"] for e in events]
    assert times == sorted(times)


async def test_admin_idempotency_key_accepted(runtime_env):
    """§14: admin mutations accept a well-formed Idempotency-Key header;
    malformed keys still reject."""
    client = runtime_env["client"]
    cookie = runtime_env["cookie"]
    order = await _order(runtime_env)
    url = _admin(runtime_env, order["id"])

    hdrs = await cookie()
    hdrs["Idempotency-Key"] = uuid.uuid4().hex * 2
    resp = await client.post(
        f"{url}/status", json={"to_state": "confirmed"}, headers=hdrs,
    )
    assert resp.status_code == 200

    hdrs = await cookie()
    hdrs["Idempotency-Key"] = "bad key!!"
    resp = await client.post(
        f"{url}/status", json={"to_state": "processing"}, headers=hdrs,
    )
    assert resp.status_code == 422
    assert resp.json()["type"] == "urn:infinitemarkets:invalid-idempotency-key"
