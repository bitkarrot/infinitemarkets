"""Section 5.4 public contract through the real host boot: route table
carries no token params, the order-status payload is exactly the §5.4
field set (allowlist), token failures are indistinguishable, protective
headers apply on every public route, both checkout rate windows engage,
and the full Release-A backend journey works end to end — catalog ->
publish intents -> public product -> checkout -> FakeWallet settlement
-> confirmed -> owner-scoped admin visibility — with no secrets, tokens,
payment hashes, or complete BOLT11 strings in any admin-side response."""

from __future__ import annotations

import asyncio
import time
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
              "display_name": "contract shop"},
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
        f"{API}/catalogs",
        json={"name": "main", "default_currency": "SAT"},
        headers=await cookie(),
    )
    assert resp.status_code == 201, resp.text
    cid = resp.json()["id"]
    resp = await client.post(
        f"{API}/products",
        json={
            "catalog_id": cid, "title": "contract thing",
            "amount_minor": 1000, "currency": "SAT",
            "visibility": "on-sale", "stock_on_hand": 25,
            "format": "digital",
        },
        headers=await cookie(),
    )
    assert resp.status_code == 201, resp.text
    product = resp.json()

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
        "merchant_id": mid, "catalog_id": cid, "product": product,
        "merchant_pubkey": merchant["pubkey"], "anon": anon,
        "cookie": cookie,
    })
    yield
    await anon.aclose()


def _idem() -> str:
    return uuid.uuid4().hex * 2


async def test_route_table_has_no_token_param(runtime_env):
    """No public route accepts a token in the path or query — the bearer
    travels only in X-Order-Token."""
    for route in runtime_env["app"].routes:
        path = getattr(route, "path", "")
        if f"{PUBLIC}/" not in path and not path.endswith(PUBLIC):
            continue
        assert "token" not in path.lower(), path
        for param in getattr(route, "dependant", None).query_params if \
                getattr(route, "dependant", None) else []:
            assert "token" not in param.name.lower(), (
                path, param.name
            )


async def test_order_status_exact_field_set(runtime_env):
    """The status payload is EXACTLY the section-5.4 field set — an
    allowlist, not merely the absence of a few forbidden keys."""
    anon = runtime_env["anon"]
    resp = await anon.post(
        f"{PUBLIC}/checkout",
        json={
            "merchant_pubkey": runtime_env["merchant_pubkey"],
            "items": [{"d_tag": runtime_env["product"]["d_tag"],
                       "quantity": 1}],
            "email": "contract@example.com",
            "email_opt_in": True,
        },
        headers={"Idempotency-Key": _idem(), "Origin": ORIGIN},
    )
    assert resp.status_code == 201, resp.text
    token = resp.json()["public_token"]
    runtime_env["journey_token"] = token

    resp = await anon.get(
        f"{PUBLIC}/order-status", headers={"X-Order-Token": token}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {
        "state", "shipping_state", "total_sat", "bolt11",
        "payment_status", "items", "expires_at", "email_opt_in",
        # 02-04: buyer-safe hold flag for the "On hold" label (never
        # the exception reason).
        "payment_exception",
        # Digital delivery — empty until LNbits-confirmed payment.
        "digital_delivery",
    }
    assert body["digital_delivery"] == []
    assert set(body["items"][0]) == {
        "title", "quantity", "line_total_sat",
    }
    # No decrypted PII, internal ids, hashes, or secrets anywhere.
    for needle in ("contract@example.com", "payment_hash",
                   "checking_id", "wallet_id", "external_id"):
        assert needle not in resp.text


async def test_token_failures_indistinguishable(runtime_env):
    """Dead, malformed, and well-formed-but-unknown tokens all produce
    byte-identical responses (compare-digest, no existence oracle)."""
    anon = runtime_env["anon"]
    bodies = []
    for token in (
        None, "", "!!!", "A" * 43 + "-",
        "gm" + "0" * 64,  # plausible shape, never issued
    ):
        resp = await anon.get(
            f"{PUBLIC}/order-status",
            headers={"X-Order-Token": token} if token else {},
        )
        assert resp.status_code == 401
        bodies.append(resp.content)
    assert all(b == bodies[0] for b in bodies)


async def test_protective_headers_everywhere(runtime_env):
    """no-store + no-referrer on every public response — reads and
    mutations alike."""
    anon = runtime_env["anon"]
    mpk = runtime_env["merchant_pubkey"]
    product = runtime_env["product"]
    responses = [
        await anon.get(f"{PUBLIC}/merchants/{mpk}"),
        await anon.get(f"{PUBLIC}/products/{mpk}/{product['d_tag']}"),
        await anon.get(f"{PUBLIC}/order-status"),
        await anon.post(
            f"{PUBLIC}/order-email-opt-out",
            headers={"X-Order-Token": "nope"},
        ),
    ]
    for resp in responses:
        assert resp.headers["cache-control"] == "no-store", resp
        assert resp.headers["referrer-policy"] == "no-referrer", resp


async def test_checkout_rate_limits(runtime_env, monkeypatch):
    """Both §15 windows engage: the per-minute cap trips first."""
    monkeypatch.setenv("INFINITEMARKETS_CHECKOUT_RATE_LIMIT", "2")
    from infinitemarkets.db import db

    async with db.connect() as conn:
        await conn.execute(
            "DELETE FROM infinitemarkets.rate_limit_buckets"
            " WHERE bucket LIKE 'checkout%'",
        )
    anon = runtime_env["anon"]
    payload = {
        "merchant_pubkey": runtime_env["merchant_pubkey"],
        "items": [{"d_tag": runtime_env["product"]["d_tag"],
                   "quantity": 1}],
    }
    # The limiter is a fixed 60s window: four requests straddling a
    # minute boundary would land in two buckets and never trip the cap.
    if time.time() % 60 > 50:
        await asyncio.sleep(61 - time.time() % 60)
    results = []
    for _ in range(4):
        resp = await anon.post(
            f"{PUBLIC}/checkout", json=payload,
            headers={"Idempotency-Key": _idem(), "Origin": ORIGIN},
        )
        results.append(resp.status_code)
    assert results[:2] == [201, 201]
    assert results[2:] == [429, 429]
    assert resp.json()["type"] == "urn:infinitemarkets:rate-limited"


async def test_end_to_end_journey(runtime_env):
    """The Release-A loop at API level: publish intents exist, the product
    is publicly readable, checkout issues one invoice, FakeWallet settles,
    the listener confirms, and the owner's admin surface shows the order,
    audit trail, and email rows — without leaking secrets."""
    anon = runtime_env["anon"]
    client = runtime_env["client"]
    mpk = runtime_env["merchant_pubkey"]
    product = runtime_env["product"]
    mid = runtime_env["merchant_id"]

    from infinitemarkets.db import db

    # Publish intents were enqueued for the catalog aggregates.
    async with db.connect() as conn:
        intents = await conn.fetchall(
            "SELECT aggregate_type, event_kind FROM"
            " infinitemarkets.outbox_events WHERE merchant_id = :m",
            {"m": mid},
        )
    kinds = {(r["aggregate_type"], r["event_kind"]) for r in intents}
    assert ("products", 30402) in kinds

    # The product is readable on the public API.
    resp = await anon.get(f"{PUBLIC}/products/{mpk}/{product['d_tag']}")
    assert resp.status_code == 200
    assert resp.json()["title"] == "contract thing"

    # Public checkout -> one order, one invoice.
    resp = await anon.post(
        f"{PUBLIC}/checkout",
        json={
            "merchant_pubkey": mpk,
            "items": [{"d_tag": product["d_tag"], "quantity": 2}],
            "email": "journey@example.com",
            "email_opt_in": True,
        },
        headers={"Idempotency-Key": _idem(), "Origin": ORIGIN},
    )
    assert resp.status_code == 201, resp.text
    token = resp.json()["public_token"]

    from infinitemarkets.crypto import token_lookup_hash

    async with db.connect() as conn:
        order = dict(await conn.fetchone(
            "SELECT * FROM infinitemarkets.orders WHERE public_token_hash = :h",
            {"h": token_lookup_hash(token)},
        ))
        core = dict(await conn.fetchone(
            "SELECT COUNT(*) AS n FROM infinitemarkets.payments"
            " WHERE order_id = :o",
            {"o": order["id"]},
        ))
    assert core["n"] == 1

    # FakeWallet settles the host invoice; the listener confirms once.
    from lnbits.core.db import db as core_db
    from lnbits.wallets import get_funding_source

    async with core_db.connect() as conn:
        core_payment = dict(await conn.fetchone(
            "SELECT * FROM apipayments WHERE external_id = :e",
            {"e": f"infinitemarkets:{order['id']}"},
        ))
    funding = get_funding_source()
    pay = await funding.pay_invoice(
        core_payment["bolt11"], fee_limit_msat=10_000
    )
    assert pay.ok, pay.error_message
    from lnbits.core.services.payments import (
        update_invoice_from_paid_invoices_stream,
    )

    settled = await update_invoice_from_paid_invoices_stream(
        core_payment["checking_id"]
    )
    assert settled is not None and settled.success

    import importlib

    settlement = importlib.import_module("infinitemarkets.services.settlement")
    await settlement.invoice_listener(settled)

    # Order confirmed; status hides the invoice now.
    resp = await anon.get(
        f"{PUBLIC}/order-status", headers={"X-Order-Token": token}
    )
    body = resp.json()
    assert body["state"] == "confirmed"
    assert body["bolt11"] is None
    assert body["payment_status"] == "settled"

    # The owner's admin surface shows everything.
    detail = (
        await client.get(
            f"{API}/merchants/{mid}/orders/{order['id']}"
        )
    ).json()
    assert detail["state"] == "confirmed"
    assert detail["payment"]["status"] == "settled"
    events = (
        await client.get(
            f"{API}/merchants/{mid}/orders/{order['id']}/events"
        )
    ).json()
    assert ("awaiting_payment", "confirmed") in [
        (e["from_state"], e["to_state"]) for e in events
    ]

    async with db.connect() as conn:
        emails = await conn.fetchall(
            "SELECT channel, event_type FROM infinitemarkets.email_queue"
            " WHERE order_id = :o",
            {"o": order["id"]},
        )
    assert any(r["event_type"] == "confirmed" for r in emails)

    # No secrets in any admin response: no payment hash, no checking id,
    # no full bolt11, no public token, no decrypted stockpile internals.
    admin_text = (await client.get(
        f"{API}/merchants/{mid}/orders/{order['id']}"
    )).text
    for needle in (
        core_payment["payment_hash"], core_payment["checking_id"],
        "bolt11", token, "public_token", "nsec",
    ):
        assert needle not in admin_text, needle
