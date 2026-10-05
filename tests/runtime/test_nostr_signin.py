"""NIP-07 buyer sign-in — challenge -> verify -> session -> orders (03-03).

Covers the D-01 vertical: single-use scoped challenges, kind-22242
``Event.verify()`` + freshness, the ``gm_nostr_session`` cookie contract
(HttpOnly/Secure/SameSite=Strict/path), hashed-token session storage,
``/nostr/orders`` buyer-scope isolation with the same paid-gated delivery
rules as ``order-status``, revocable logout, and the D-06 inbox-active
affordance gate. Claim + attributed-checkout coverage lands below the
sign-in tests (03-03 Task 2).
"""

from __future__ import annotations

import asyncio
import hashlib
import time
import uuid

import pytest
import pytest_asyncio

pytestmark = pytest.mark.runtime

ORIGIN = "https://shop.example"
API = "/infinitemarkets/api/v1"
PUB = f"{API}/public"


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
        json={
            "wallet_id": runtime_env["wallet"].id,
            "display_name": "signin shop",
        },
        headers=await cookie(),
    )
    assert resp.status_code == 201, resp.text
    mid = resp.json()["id"]
    from infinitemarkets.db import DomainTransaction

    async with DomainTransaction() as tx:
        await tx.execute(
            "UPDATE merchants SET state = 'active',"
            " inbox_state = 'active' WHERE id = :m",
            {"m": mid},
        )
    resp = await client.post(
        f"{API}/catalogs",
        json={"name": "signin", "default_currency": "SAT"},
        headers=await cookie(),
    )
    assert resp.status_code == 201, resp.text
    cid = resp.json()["id"]

    async def product(title, stock, fmt="digital", price=500, **extra) -> dict:
        resp = await client.post(
            f"{API}/products",
            json={
                "catalog_id": cid,
                "title": title,
                "amount_minor": price,
                "currency": "SAT",
                "visibility": "on-sale",
                "stock_on_hand": stock,
                "format": fmt,
                **extra,
            },
            headers=await cookie(),
        )
        assert resp.status_code == 201, resp.text
        return resp.json()

    runtime_env.update(
        {
            "merchant_id": mid,
            "catalog_id": cid,
            "make_product": product,
            "cookie": cookie,
        }
    )
    yield


async def _merchant(env: dict) -> dict:
    async with env["ext_module"].db.connect() as conn:
        row = await conn.fetchone(
            "SELECT * FROM infinitemarkets.merchants WHERE id = :m",
            {"m": env["merchant_id"]},
        )
    return dict(row)


def _buyer_keys(label: str):
    from harness.sdk import fixed_test_keys

    return fixed_test_keys(label)


def _buyer_hex(label: str) -> str:
    return _buyer_keys(label).public_key().to_hex()


async def _challenge(client) -> str:
    resp = await client.get(f"{PUB}/nostr/challenge")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ttl"] == 300
    return body["challenge"]


async def _sign_event(
    keys, challenge: str, *, kind: int = 22242, created_at: int | None = None
) -> str:
    """A real kind-22242 signed event carrying the challenge."""
    from nostr_sdk import (
        EventBuilder,
        Kind,
        NostrSigner,
        Tag,
        Timestamp,
    )

    builder = EventBuilder(Kind(kind), challenge).tags(
        [Tag.parse(["challenge", challenge])]
    )
    if created_at is not None:
        builder = builder.custom_created_at(Timestamp.from_secs(created_at))
    event = await builder.sign(NostrSigner.keys(keys))
    return event.as_json()


async def _verify(client, event_json: str, *, origin: str | None = ORIGIN):
    headers = {"Origin": origin} if origin else {}
    return await client.post(
        f"{PUB}/nostr/verify", json={"event": event_json}, headers=headers
    )


async def _signin(client, label: str):
    """Full challenge -> sign -> verify; returns the httpx client's
    session cookie value."""
    keys = _buyer_keys(label)
    challenge = await _challenge(client)
    event_json = await _sign_event(keys, challenge)
    resp = await _verify(client, event_json)
    assert resp.status_code == 200, resp.text
    return client.cookies.get("gm_nostr_session")


async def _bind_buyer(env: dict, order_id: str, buyer_hex: str) -> None:
    """Simulate a bound buyer (gamma intake or a claim) — same fields the
    real paths write."""
    from infinitemarkets import crypto
    from infinitemarkets.db import DomainTransaction
    from infinitemarkets.settings import ext_settings

    settings = ext_settings()
    ver = settings.active_key_version
    async with DomainTransaction() as tx:
        await tx.execute(
            "UPDATE orders SET buyer_pubkey_enc = :e,"
            " buyer_pubkey_hash = :h WHERE id = :o",
            {
                "e": crypto.encrypt(
                    buyer_hex.encode(),
                    settings.master_keys[ver],
                    record_id=order_id,
                    table="orders",
                    column="buyer_pubkey_enc",
                    key_version=ver,
                ),
                "h": crypto.hmac_index(
                    settings.privacy_key,
                    crypto.PURPOSE_BUYER_PUBKEY,
                    env["merchant_id"],
                    crypto.normalize(buyer_hex),
                ),
                "o": order_id,
            },
        )


async def _web_order(env: dict, product_d: str) -> tuple[dict, str]:
    """A real anonymous web checkout -> (order row, private token).

    A fresh cookie-free client is used so no buyer session (possibly
    left on the shared client) attributes the order.
    """
    import httpx

    merchant = await _merchant(env)
    transport = httpx.ASGITransport(app=env["app"])
    async with httpx.AsyncClient(
        transport=transport, base_url=ORIGIN
    ) as anon:
        resp = await anon.post(
            f"{PUB}/checkout",
            json={
                "merchant_pubkey": merchant["pubkey"],
                "items": [{"d_tag": product_d, "quantity": 1}],
                "email_opt_in": False,
            },
            headers={
                "Idempotency-Key": uuid.uuid4().hex,
                "Origin": ORIGIN,
            },
        )
    assert resp.status_code == 201, resp.text
    token = resp.json()["public_token"]
    digest = env["ext_module"].crypto.token_lookup_hash(token)
    async with env["ext_module"].db.connect() as conn:
        row = await conn.fetchone(
            "SELECT * FROM infinitemarkets.orders"
            " WHERE public_token_hash = :h",
            {"h": digest},
        )
    assert row is not None
    return dict(row), token


async def _set_inbox_state(env: dict, state: str) -> None:
    from infinitemarkets.db import DomainTransaction

    async with DomainTransaction() as tx:
        await tx.execute(
            "UPDATE merchants SET inbox_state = :s WHERE id = :m",
            {"s": state, "m": env["merchant_id"]},
        )


# --- sign-in vertical ----------------------------------------------------------


async def test_challenge_issue_posture(runtime_env):
    """The challenge row stores only a hash, is scope-bound, 300 s TTL,
    single-use flag clear."""
    client = runtime_env["client"]
    challenge = await _challenge(client)
    assert len(challenge) == 43
    async with runtime_env["ext_module"].db.connect() as conn:
        row = await conn.fetchone(
            "SELECT * FROM infinitemarkets.nostr_challenges"
            " WHERE challenge_hash = :h",
            {"h": hashlib.sha256(challenge.encode()).hexdigest()},
        )
    assert row is not None
    row = dict(row)
    assert row["challenge_hash"] != challenge
    assert row["merchant_id"] == runtime_env["merchant_id"]
    assert row["scope_hash"]
    assert row["used_at"] is None
    now = int(time.time())
    assert now + 250 <= row["expires_at"] <= now + 300


async def test_verify_sets_cookie_and_hashed_session(runtime_env):
    client = runtime_env["client"]
    keys = _buyer_keys("sess-1")
    challenge = await _challenge(client)
    event_json = await _sign_event(keys, challenge)
    resp = await _verify(client, event_json)
    assert resp.status_code == 200, resp.text
    assert resp.json()["signed_in"] is True
    assert resp.json()["pubkey"].startswith("npub1")

    set_cookie = resp.headers.get("set-cookie", "")
    assert "gm_nostr_session=" in set_cookie
    for attr in ("httponly", "secure", "samesite=strict",
                 "path=/infinitemarkets", "max-age"):
        assert attr in set_cookie.lower(), set_cookie

    token = client.cookies.get("gm_nostr_session")
    assert token and token in set_cookie
    async with runtime_env["ext_module"].db.connect() as conn:
        row = await conn.fetchone(
            "SELECT * FROM infinitemarkets.buyer_sessions"
            " WHERE merchant_id = :m ORDER BY created_at DESC LIMIT 1",
            {"m": runtime_env["merchant_id"]},
        )
    assert row is not None
    row = dict(row)
    # The raw token is never persisted — only its SHA-256 hex digest.
    from infinitemarkets import crypto

    assert row["token_hash"] == crypto.token_lookup_hash(token).hex()
    assert row["token_hash"] != token
    assert row["revoked_at"] is None
    assert row["expires_at"] > int(time.time()) + 6 * 86400

    # The challenge was consumed atomically.
    async with runtime_env["ext_module"].db.connect() as conn:
        ch = await conn.fetchone(
            "SELECT used_at FROM infinitemarkets.nostr_challenges"
            " WHERE challenge_hash = :h",
            {"h": hashlib.sha256(challenge.encode()).hexdigest()},
        )
    assert ch["used_at"] is not None


async def test_verify_rejections_share_identical_outcome(runtime_env):
    """Bad signature, wrong kind, stale created_at, unknown challenge and
    challenge reuse all produce the same 401 problem body."""
    client = runtime_env["client"]
    keys = _buyer_keys("sess-2")
    challenge = await _challenge(client)

    variants = []
    # wrong kind
    variants.append(
        await _sign_event(keys, challenge, kind=1)
    )
    # stale event
    variants.append(
        await _sign_event(
            keys, challenge, created_at=int(time.time()) - 600
        )
    )
    # tampered signature (challenge of a different value — sign fails
    # the challenge lookup even though the signature is real)
    variants.append(
        await _sign_event(keys, "X" * 43)
    )
    # malformed JSON
    variants.append('{"not": "an event"}')

    outcomes = []
    for event_json in variants:
        resp = await _verify(client, event_json)
        assert resp.status_code == 401, (resp.status_code, resp.text)
        outcomes.append((resp.status_code, resp.json()))

    # Replay of a challenge that was ALREADY spent matches too.
    good = await _sign_event(keys, challenge)
    resp = await _verify(client, good)
    assert resp.status_code == 200, resp.text
    resp = await _verify(client, good)
    assert resp.status_code == 401
    outcomes.append((resp.status_code, resp.json()))

    first = outcomes[0][1]
    for _, body in outcomes:
        assert body["type"] == first["type"]
        assert body["title"] == first["title"]
        assert body["status"] == 401


async def test_verify_requires_exact_origin(runtime_env):
    client = runtime_env["client"]
    keys = _buyer_keys("sess-3")
    challenge = await _challenge(client)
    event_json = await _sign_event(keys, challenge)

    resp = await _verify(client, event_json, origin=None)
    assert resp.status_code == 403, resp.text
    resp = await _verify(client, event_json, origin="https://evil.example")
    assert resp.status_code == 403, resp.text


async def test_orders_requires_session(runtime_env):
    import httpx

    transport = httpx.ASGITransport(app=runtime_env["app"])
    async with httpx.AsyncClient(
        transport=transport, base_url=ORIGIN
    ) as fresh:
        resp = await fresh.get(f"{PUB}/nostr/orders")
        assert resp.status_code == 401, resp.text
        # A malformed cookie is equally anonymous.
        fresh.cookies.set("gm_nostr_session", "not-a-real-token")
        resp = await fresh.get(f"{PUB}/nostr/orders")
        assert resp.status_code == 401, resp.text


async def test_orders_scoped_to_buyer_and_delivery_gated(runtime_env):
    """Buyer A sees only buyer A's orders; digital delivery appears ONLY
    on paid states (same gating as the private order page, D-03)."""
    import httpx

    env = runtime_env
    product = await env["make_product"](
        f"dl-{uuid.uuid4().hex[:6]}", 10,
        delivery_content="https://example.com/dl-key",
    )
    order_a, _ = await _web_order(env, product["d_tag"])
    order_b, _ = await _web_order(env, product["d_tag"])
    order_other, _ = await _web_order(env, product["d_tag"])
    await _bind_buyer(env, order_a["id"], _buyer_hex("buyer-a"))
    await _bind_buyer(env, order_b["id"], _buyer_hex("buyer-a"))
    await _bind_buyer(env, order_other["id"], _buyer_hex("buyer-b"))

    # order_b simulates a paid digital order (delivery unlocked).
    from infinitemarkets.db import DomainTransaction

    async with DomainTransaction() as tx:
        await tx.execute(
            "UPDATE orders SET state = 'confirmed' WHERE id = :o",
            {"o": order_b["id"]},
        )

    transport = httpx.ASGITransport(app=env["app"])
    async with httpx.AsyncClient(
        transport=transport, base_url=ORIGIN
    ) as fresh:
        await _signin(fresh, "buyer-a")
        resp = await fresh.get(f"{PUB}/nostr/orders")
        assert resp.status_code == 200, resp.text
        orders = resp.json()["orders"]
        ids = {o["order_id"] for o in orders}
        assert order_a["id"] in ids
        assert order_b["id"] in ids
        assert order_other["id"] not in ids

        by_id = {o["order_id"]: o for o in orders}
        # §5.4 field set present on every entry.
        for key in (
            "state", "shipping_state", "total_sat", "bolt11",
            "payment_status", "items", "expires_at", "email_opt_in",
            "payment_exception", "digital_delivery",
        ):
            assert key in by_id[order_a["id"]], key
        # awaiting_payment -> delivery locked; confirmed -> unlocked.
        assert by_id[order_a["id"]]["digital_delivery"] == []
        assert by_id[order_b["id"]]["digital_delivery"]

        # A second buyer sees only their own order.
    async with httpx.AsyncClient(
        transport=transport, base_url=ORIGIN
    ) as fresh2:
        await _signin(fresh2, "buyer-b")
        resp = await fresh2.get(f"{PUB}/nostr/orders")
        ids = {o["order_id"] for o in resp.json()["orders"]}
        assert ids == {order_other["id"]}


async def test_logout_revokes_session(runtime_env):
    import httpx

    transport = httpx.ASGITransport(app=runtime_env["app"])
    async with httpx.AsyncClient(
        transport=transport, base_url=ORIGIN
    ) as fresh:
        await _signin(fresh, "buyer-c")
        resp = await fresh.post(
            f"{PUB}/nostr/logout", headers={"Origin": ORIGIN}
        )
        assert resp.status_code == 200, resp.text
        resp = await fresh.get(f"{PUB}/nostr/orders")
        assert resp.status_code == 401, resp.text


async def test_signin_affordance_follows_inbox_state(runtime_env):
    """D-06 — the button renders only while inbox_state == 'active'."""
    client = runtime_env["client"]
    merchant = await _merchant(runtime_env)
    url = f"/infinitemarkets/order?shop={merchant['pubkey']}"
    await _set_inbox_state(runtime_env, "active")
    resp = await client.get(url)
    assert 'id="gm-nostr-signin"' in resp.text
    assert "public_nostr.js" in resp.text

    await _set_inbox_state(runtime_env, "disabled")
    try:
        resp = await client.get(url)
        assert 'id="gm-nostr-signin"' not in resp.text
        assert "public_nostr.js" not in resp.text
    finally:
        await _set_inbox_state(runtime_env, "active")


async def test_public_nostr_js_safety(runtime_env):
    """window.nostr absence degrades gracefully; no innerHTML on API data."""
    from pathlib import Path

    src = (
        Path(__file__).resolve().parents[2]
        / "infinitemarkets/static/infinitemarkets/js/public_nostr.js"
    ).read_text()
    assert "window.nostr" in src
    assert "NIP-07" in src
    assert ".innerHTML" not in src
    assert "kind: KIND_SIGNIN" in src or "kind: 22242" in src


# --- claim flow + attributed web checkout (03-03 Task 2, D-04/D-05) ----------


async def test_claim_binds_buyer_and_audits(runtime_env):
    """Token + session -> buyer_pubkey bound, order_events audit row,
    order appears in the buyer's history."""
    import httpx

    env = runtime_env
    product = await env["make_product"](f"claim-{uuid.uuid4().hex[:6]}", 5)
    order, token = await _web_order(env, product["d_tag"])
    assert order["buyer_pubkey_hash"] is None

    transport = httpx.ASGITransport(app=env["app"])
    async with httpx.AsyncClient(
        transport=transport, base_url=ORIGIN
    ) as fresh:
        await _signin(fresh, "claimer-1")
        resp = await fresh.post(
            f"{PUB}/nostr/claim",
            json={"token": token},
            headers={"Origin": ORIGIN},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["claimed"] is True
        assert resp.json()["order_id"] == order["id"]

        resp = await fresh.get(f"{PUB}/nostr/orders")
        ids = {o["order_id"] for o in resp.json()["orders"]}
        assert order["id"] in ids

    async with env["ext_module"].db.connect() as conn:
        row = await conn.fetchone(
            "SELECT buyer_pubkey_hash, buyer_pubkey_enc"
            " FROM infinitemarkets.orders WHERE id = :o",
            {"o": order["id"]},
        )
        assert row["buyer_pubkey_hash"] is not None
        assert row["buyer_pubkey_enc"] is not None
        event = await conn.fetchone(
            "SELECT detail_json, actor FROM infinitemarkets.order_events"
            " WHERE order_id = :o AND detail_json LIKE '%buyer-claimed%'",
            {"o": order["id"]},
        )
    assert event is not None
    assert event["actor"] == "buyer"


async def test_claim_failures_share_identical_outcome(runtime_env):
    """Bad-format, unknown and foreign-bound tokens produce the SAME
    401 problem body — no order-existence or ownership oracle."""
    import httpx

    env = runtime_env
    product = await env["make_product"](f"claim2-{uuid.uuid4().hex[:6]}", 5)
    order_own, token_own = await _web_order(env, product["d_tag"])
    order_other, token_other = await _web_order(env, product["d_tag"])
    await _bind_buyer(env, order_other["id"], _buyer_hex("someone-else"))

    transport = httpx.ASGITransport(app=env["app"])
    async with httpx.AsyncClient(
        transport=transport, base_url=ORIGIN
    ) as fresh:
        await _signin(fresh, "claimer-2")
        outcomes = []
        for token in (
            "garbage",
            "A" * 43,  # well-formed, unknown
            token_other,  # bound to a different buyer
        ):
            resp = await fresh.post(
                f"{PUB}/nostr/claim",
                json={"token": token},
                headers={"Origin": ORIGIN},
            )
            assert resp.status_code == 401, (token[:10], resp.text)
            outcomes.append(resp.json())
        assert all(o == outcomes[0] for o in outcomes)

        # Idempotent repeat claim.
        resp = await fresh.post(
            f"{PUB}/nostr/claim",
            json={"token": token_own},
            headers={"Origin": ORIGIN},
        )
        assert resp.status_code == 200, resp.text
        resp = await fresh.post(
            f"{PUB}/nostr/claim",
            json={"token": token_own},
            headers={"Origin": ORIGIN},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["already_linked"] is True

    # The foreign-bound order was NOT mutated.
    async with env["ext_module"].db.connect() as conn:
        row = await conn.fetchone(
            "SELECT buyer_pubkey_hash FROM infinitemarkets.orders"
            " WHERE id = :o",
            {"o": order_other["id"]},
        )
    from infinitemarkets import crypto
    from infinitemarkets.settings import ext_settings

    assert row["buyer_pubkey_hash"] == crypto.hmac_index(
        ext_settings().privacy_key, crypto.PURPOSE_BUYER_PUBKEY,
        env["merchant_id"], crypto.normalize(_buyer_hex("someone-else")),
    )


async def test_claim_requires_session(runtime_env):
    import httpx

    env = runtime_env
    product = await env["make_product"](f"claim3-{uuid.uuid4().hex[:6]}", 5)
    _, token = await _web_order(env, product["d_tag"])
    transport = httpx.ASGITransport(app=env["app"])
    async with httpx.AsyncClient(
        transport=transport, base_url=ORIGIN
    ) as fresh:
        resp = await fresh.post(
            f"{PUB}/nostr/claim",
            json={"token": token},
            headers={"Origin": ORIGIN},
        )
    assert resp.status_code == 401, resp.text


async def test_attributed_web_checkout(runtime_env):
    """Signed-in checkout writes buyer_pubkey_* on the web order AND
    enqueues the type-2 payment request intent; anonymous checkout
    remains unbound."""
    import httpx

    env = runtime_env
    product = await env["make_product"](f"attr-{uuid.uuid4().hex[:6]}", 5)
    merchant = await _merchant(env)

    transport = httpx.ASGITransport(app=env["app"])
    async with httpx.AsyncClient(
        transport=transport, base_url=ORIGIN
    ) as fresh:
        await _signin(fresh, "shopper-1")
        resp = await fresh.post(
            f"{PUB}/checkout",
            json={
                "merchant_pubkey": merchant["pubkey"],
                "items": [{"d_tag": product["d_tag"], "quantity": 1}],
                "email_opt_in": False,
            },
            headers={
                "Idempotency-Key": uuid.uuid4().hex,
                "Origin": ORIGIN,
            },
        )
    assert resp.status_code == 201, resp.text
    token = resp.json()["public_token"]
    assert token  # private-link contract unchanged

    # Session-cookie mutations require exact-Origin — a signed-in
    # checkout WITHOUT Origin is refused before any attribution.
    async with httpx.AsyncClient(
        transport=transport, base_url=ORIGIN
    ) as no_origin:
        await _signin(no_origin, "shopper-no-origin")
        resp2 = await no_origin.post(
            f"{PUB}/checkout",
            json={
                "merchant_pubkey": merchant["pubkey"],
                "items": [{"d_tag": product["d_tag"], "quantity": 1}],
                "email_opt_in": False,
            },
            headers={"Idempotency-Key": uuid.uuid4().hex},
        )
        assert resp2.status_code == 403, resp2.text

    from infinitemarkets import crypto
    from infinitemarkets.settings import ext_settings

    digest = env["ext_module"].crypto.token_lookup_hash(token)
    async with env["ext_module"].db.connect() as conn:
        order = await conn.fetchone(
            "SELECT * FROM infinitemarkets.orders"
            " WHERE public_token_hash = :h",
            {"h": digest},
        )
    order = dict(order)
    expected_hash = crypto.hmac_index(
        ext_settings().privacy_key, crypto.PURPOSE_BUYER_PUBKEY,
        env["merchant_id"], crypto.normalize(_buyer_hex("shopper-1")),
    )
    assert order["buyer_pubkey_hash"] == expected_hash
    assert order["buyer_pubkey_enc"] is not None

    # The type-2 payment request is queued on the order_msg path.
    async with env["ext_module"].db.connect() as conn:
        intents = await conn.fetchall(
            "SELECT * FROM infinitemarkets.outbox_events"
            " WHERE merchant_id = :m AND aggregate_type = 'order_msg'"
            " AND aggregate_id LIKE :p",
            {"m": env["merchant_id"], "p": f"{order['id']}:%"},
        )
        msgs = await conn.fetchall(
            "SELECT * FROM infinitemarkets.order_messages"
            " WHERE order_id = :o AND direction = 'out'",
            {"o": order["id"]},
        )
    assert intents, "expected an order_msg intent for the payment request"
    assert msgs, "expected an 'out' order_messages row"

    # Anonymous checkout stays unbound.
    product2 = await env["make_product"](f"anon-{uuid.uuid4().hex[:6]}", 5)
    _, token2 = await _web_order(env, product2["d_tag"])
    async with env["ext_module"].db.connect() as conn:
        anon = await conn.fetchone(
            "SELECT buyer_pubkey_hash FROM infinitemarkets.orders"
            " WHERE public_token_hash = :h",
            {"h": env["ext_module"].crypto.token_lookup_hash(token2)},
        )
    assert anon["buyer_pubkey_hash"] is None


async def test_attributed_web_order_wraps_to_buyer_relays(
    runtime_env, monkeypatch
):
    """The attributed web order's payment request reaches the BUYER's
    declared inbox relay (recipient copy) and the merchant's inbox
    relay (sender copy) — identical routing to gamma orders."""
    import json as _json

    import httpx

    from harness import relay as relay_module
    from infinitemarkets.services import outbox

    env = runtime_env
    merchant = await _merchant(env)
    mid, mpk = merchant["id"], merchant["pubkey"]
    label = "web-attr-buyer"
    buyer_hex = _buyer_hex(label)

    buyer_relay = relay_module.LocalRelay(mode=relay_module.RelayMode.ACCEPTING)
    await buyer_relay.start()
    try:
        from nostr_sdk import EventBuilder, Kind, NostrSigner, Tag

        profile = await (
            EventBuilder(Kind(10050), "")
            .tags([Tag.parse(["relay", buyer_relay.url])])
            .sign(NostrSigner.keys(_buyer_keys(label)))
        )
        public = relay_module.LocalRelay(
            mode=relay_module.RelayMode.ACCEPTING,
            canned_events=[_json.loads(profile.as_json())],
        )
        merchant_relay = relay_module.LocalRelay(
            mode=relay_module.RelayMode.ACCEPTING
        )
        await public.start()
        await merchant_relay.start()
        try:
            monkeypatch.setenv("INFINITEMARKETS_RELAY_IO", "on")
            monkeypatch.setenv(
                "INFINITEMARKETS_ALLOW_INSECURE_RELAYS", "1"
            )
            await _set_relays(env, mid, [
                {"relay_url": public.url, "direction": "public"},
                {"relay_url": merchant_relay.url, "direction": "inbox"},
            ])
            from infinitemarkets.services.transport import transport

            await transport().start([])

            product = await env["make_product"](
                f"wrap-{uuid.uuid4().hex[:6]}", 5
            )
            # Earlier tests consumed the per-minute checkout window for
            # the shared testclient scope — reset so this checkout is
            # judged on behavior, not quota.
            from infinitemarkets.db import DomainTransaction

            async with DomainTransaction() as tx:
                await tx.execute(
                    "DELETE FROM rate_limit_buckets"
                    " WHERE bucket LIKE 'checkout%'"
                )
            t = httpx.ASGITransport(app=env["app"])
            async with httpx.AsyncClient(
                transport=t, base_url=ORIGIN
            ) as fresh:
                await _signin(fresh, label)
                resp = await fresh.post(
                    f"{PUB}/checkout",
                    json={
                        "merchant_pubkey": mpk,
                        "items": [
                            {"d_tag": product["d_tag"], "quantity": 1}
                        ],
                        "email_opt_in": False,
                    },
                    headers={
                        "Idempotency-Key": uuid.uuid4().hex,
                        "Origin": ORIGIN,
                    },
                )
            assert resp.status_code == 201, resp.text
            digest = env["ext_module"].crypto.token_lookup_hash(
                resp.json()["public_token"]
            )
            async with env["ext_module"].db.connect() as conn:
                order = await conn.fetchone(
                    "SELECT id FROM infinitemarkets.orders"
                    " WHERE public_token_hash = :h",
                    {"h": digest},
                )
            async with env["ext_module"].db.connect() as conn:
                intents = await conn.fetchall(
                    "SELECT * FROM infinitemarkets.outbox_events"
                    " WHERE merchant_id = :m AND aggregate_type = 'order_msg'"
                    " AND aggregate_id LIKE :p",
                    {"m": mid, "p": f"{order['id']}:%"},
                )
            assert intents

            outcome = await outbox.worker_tick("test-worker")
            assert outcome["claimed"] >= 1

            rec_wraps = [
                e["event"]
                for e in buyer_relay.received_events
                if isinstance(e.get("event"), dict)
                and e["event"].get("kind") == 1059
            ]
            sen_wraps = [
                e["event"]
                for e in merchant_relay.received_events
                if isinstance(e.get("event"), dict)
                and e["event"].get("kind") == 1059
            ]
            assert rec_wraps, "no recipient wrap on the buyer relay"
            assert sen_wraps, "no sender wrap on the merchant relay"
            p_tags = [
                t[1]
                for t in rec_wraps[0]["tags"]
                if t[0] == "p"
            ]
            assert p_tags == [buyer_hex]
        finally:
            await public.stop()
            await merchant_relay.stop()
    finally:
        await buyer_relay.stop()


async def _set_relays(env: dict, mid: str, configs: list[dict]):
    client = env["client"]
    resp = await client.patch(
        f"{API}/merchants/{mid}",
        json={"relay_configs": configs},
        headers={
            "Origin": ORIGIN,
            "X-CSRF-Token": client.cookies.get("gm_csrf") or "",
        },
    )
    assert resp.status_code == 200, resp.text


async def test_nsec_signin_gated_and_mints_session(runtime_env, monkeypatch):
    """The nsec dev path is OFF by default — identical 401 to a bad
    signature — and mints a normal session when the flag is on."""
    import httpx

    keys = _buyer_keys("e2e-nsec")
    nsec = keys.secret_key().to_bech32()
    transport = httpx.ASGITransport(app=runtime_env["app"])
    async with httpx.AsyncClient(
        transport=transport, base_url=ORIGIN
    ) as fresh:
        monkeypatch.delenv("INFINITEMARKETS_NSEC_SIGNIN", raising=False)
        resp = await fresh.post(
            f"{PUB}/nostr/verify",
            json={"nsec": nsec},
            headers={"Origin": ORIGIN},
        )
        assert resp.status_code == 401, resp.text
        monkeypatch.setenv("INFINITEMARKETS_NSEC_SIGNIN", "1")
        resp = await fresh.post(
            f"{PUB}/nostr/verify",
            json={"nsec": nsec},
            headers={"Origin": ORIGIN},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["pubkey"].startswith("npub1")
        # The minted cookie serves the session endpoints.
        resp = await fresh.get(f"{PUB}/nostr/orders")
        assert resp.status_code == 200, resp.text
        # Garbage nsec is the identical invalid outcome.
        resp = await fresh.post(
            f"{PUB}/nostr/verify",
            json={"nsec": "nsec1bogus"},
            headers={"Origin": ORIGIN},
        )
        assert resp.status_code == 401, resp.text
