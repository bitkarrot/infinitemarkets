"""Section 5.4 public checkout/status HTTP contract through the real host
boot: idempotency-key requirement, token-in-header only, restricted field
set with no internals, protective headers, readiness gate, email opt-out."""

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

    client = runtime_env["client"]  # authenticated — admin setup calls

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
              "display_name": "status shop"},
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
    resp = await client.post(
        f"{API}/products",
        json={
            "category_id": cid, "title": "thing",
            "amount_minor": 1000, "currency": "SAT",
            "visibility": "on-sale", "stock_on_hand": 10,
            "format": "digital",
        },
        headers=await cookie(),
    )
    assert resp.status_code == 201, resp.text
    product = resp.json()

    # Readiness: the startup reconcile normally flips this — workers are
    # cancelled in tests, so flip it explicitly (the gate itself is
    # asserted in test_checkout_gated_before_reconciliation on a fresh
    # flag — see below).
    from infinitemarkets.services import readiness

    readiness.mark_reconciled()

    async with DomainTransaction() as tx:
        merchant = await tx.fetch_one(
            "SELECT pubkey FROM merchants WHERE id = :m", {"m": mid},
        )
    # An anonymous (cookie-free) client — the real buyer posture; the
    # shared client's login cookie triggers the host's authenticated-POST
    # checks which are unrelated to the public contract.
    import httpx

    anon = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=runtime_env["app"]),
        base_url=ORIGIN,
    )
    runtime_env.update({
        "merchant_id": mid, "category_id": cid, "product": product,
        "merchant_pubkey": merchant["pubkey"], "anon": anon,
    })
    yield
    await anon.aclose()


def _idem() -> str:
    return uuid.uuid4().hex * 2


async def _checkout(runtime_env) -> dict:
    product = runtime_env["product"]
    resp = await runtime_env["anon"].post(
        f"{PUBLIC}/checkout",
        json={
            "merchant_pubkey": runtime_env["merchant_pubkey"],
            "items": [{"d_tag": product["d_tag"], "quantity": 1}],
            "email": "buyer@example.com",
            "email_opt_in": True,
        },
        headers={"Idempotency-Key": _idem(), "Origin": ORIGIN},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_checkout_requires_idempotency_key(runtime_env):
    resp = await runtime_env["anon"].post(
        f"{PUBLIC}/checkout",
        json={
            "merchant_pubkey": runtime_env["merchant_pubkey"],
            "items": [{"d_tag": "x", "quantity": 1}],
        },
    )
    assert resp.status_code == 400
    # Malformed keys (too short, bad chars) also reject before any work.
    for bad in ("short", "has space in it!!", "x" * 129):
        resp = await runtime_env["client"].post(
            f"{PUBLIC}/checkout",
            json={
                "merchant_pubkey": runtime_env["merchant_pubkey"],
                "items": [{"d_tag": "x", "quantity": 1}],
            },
            headers={"Idempotency-Key": bad},
        )
        assert resp.status_code == 400, bad


async def test_checkout_happy_path(runtime_env):
    body = await _checkout(runtime_env)
    assert body["public_token"]
    assert body["order"]["state"] == "awaiting_payment"
    assert body["order"]["total_sat"] == 1000
    assert body["order"]["bolt11"].startswith("ln")
    assert body["order"]["expires_at"]
    runtime_env["token"] = body["public_token"]
    # Protective headers on the checkout response.
    resp = await runtime_env["anon"].post(
        f"{PUBLIC}/checkout",
        json={
            "merchant_pubkey": runtime_env["merchant_pubkey"],
            "items": [{"d_tag": runtime_env["product"]["d_tag"],
                       "quantity": 1}],
        },
        headers={"Idempotency-Key": _idem(), "Origin": ORIGIN},
    )
    assert resp.headers["cache-control"] == "no-store"
    assert resp.headers["referrer-policy"] == "no-referrer"


async def test_order_status_token_contract(runtime_env):
    """The token travels ONLY in X-Order-Token; invalid shapes and
    unknown tokens fail identically (no existence oracle)."""
    client = runtime_env["anon"]
    token = runtime_env["token"]

    # No header.
    resp = await client.get(f"{PUBLIC}/order-status")
    assert resp.status_code == 401
    body_no = resp.json()
    # Malformed shape and well-formed-but-unknown fail identically.
    resp_bad = await client.get(
        f"{PUBLIC}/order-status", headers={"X-Order-Token": "!!!bad!!!"}
    )
    resp_unknown = await client.get(
        f"{PUBLIC}/order-status",
        headers={"X-Order-Token": "A" * 43 + "-"},
    )
    assert resp_bad.status_code == resp_unknown.status_code == 401
    assert resp_bad.json() == resp_unknown.json() == body_no

    # Valid token -> restricted field set only.
    resp = await client.get(
        f"{PUBLIC}/order-status", headers={"X-Order-Token": token}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "awaiting_payment"
    assert body["total_sat"] == 1000
    assert body["bolt11"].startswith("ln")
    assert body["items"][0]["title"] == "thing"
    # §5.4 forbidden fields: no internals, no payment_hash, no PII echoes.
    for forbidden in (
        "id", "order_id", "merchant_id", "payment_hash", "checking_id",
        "wallet_id", "external_id", "buyer_pubkey", "contact", "address",
        "email", "tracking",
    ):
        assert forbidden not in body, forbidden
    assert "email@example.com" not in resp.text
    assert resp.headers["cache-control"] == "no-store"
    assert resp.headers["referrer-policy"] == "no-referrer"


async def test_order_status_after_confirmation(runtime_env):
    """A confirmed order's status hides the bolt11 (settled)."""
    from infinitemarkets.crypto import token_lookup_hash
    from infinitemarkets.db import db

    token = runtime_env["token"]
    async with db.connect() as conn:
        order = dict(await conn.fetchone(
            "SELECT * FROM infinitemarkets.orders WHERE public_token_hash = :h",
            {"h": token_lookup_hash(token)},
        ))
    import importlib

    settlement = importlib.import_module("infinitemarkets.services.settlement")
    await settlement.confirm_settlement(
        order_id=order["id"], source="test"
    )
    resp = await runtime_env["client"].get(
        f"{PUBLIC}/order-status", headers={"X-Order-Token": token}
    )
    body = resp.json()
    assert body["state"] == "confirmed"
    assert body["bolt11"] is None
    assert body["payment_status"] == "settled"


async def test_email_opt_out(runtime_env):
    """Opt-out flips email_opt_in, suppresses queued customer rows, and
    clears the token AEAD copy — the link itself keeps working."""
    client = runtime_env["anon"]
    token = runtime_env["token"]

    resp = await client.post(
        f"{PUBLIC}/order-email-opt-out",
        headers={"X-Order-Token": token},
    )
    assert resp.status_code == 200
    assert resp.json()["email_opt_in"] is False

    from infinitemarkets.crypto import token_lookup_hash
    from infinitemarkets.db import db

    async with db.connect() as conn:
        order = dict(await conn.fetchone(
            "SELECT * FROM infinitemarkets.orders WHERE public_token_hash = :h",
            {"h": token_lookup_hash(token)},
        ))
        assert order["email_opt_in"] in (0, False)
        assert order["public_token_enc"] is None
        queued = await conn.fetchall(
            "SELECT state FROM infinitemarkets.email_queue"
            " WHERE order_id = :o AND channel = 'customer'",
            {"o": order["id"]},
        )
        assert all(r["state"] == "suppressed" for r in queued)

    # The link still resolves (opt-out is not revocation).
    resp = await client.get(
        f"{PUBLIC}/order-status", headers={"X-Order-Token": token}
    )
    assert resp.status_code == 200


async def test_checkout_gated_by_readiness(runtime_env):
    """The readiness gate fails closed — checkout 503s until the first
    reconcile pass completes."""
    import importlib

    readiness = importlib.import_module("infinitemarkets.services.readiness")
    readiness._reconciled = False  # noqa: SLF001 — test the closed path
    try:
        resp = await runtime_env["client"].post(
            f"{PUBLIC}/checkout",
            json={
                "merchant_pubkey": runtime_env["merchant_pubkey"],
                "items": [{"d_tag": runtime_env["product"]["d_tag"],
                           "quantity": 1}],
            },
            headers={"Idempotency-Key": _idem()},
        )
        assert resp.status_code == 503
    finally:
        readiness.mark_reconciled()
