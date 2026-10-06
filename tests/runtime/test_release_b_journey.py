"""Release-B buyer journey — one end-to-end arc through every seam the
plan 03-03 wires together:

real relay capture (LocalRelay) -> gamma NIP-17 order intake ->
type-2 payment request published dual-copy -> kind-17 receipt ->
kind-14 DM reply -> NIP-07 sign-in + order history + claim ->
storefront modes -> deactivation tombstone (D-17).
"""

from __future__ import annotations

import asyncio
import json
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
            "display_name": "journey shop",
        },
        headers=await cookie(),
    )
    assert resp.status_code == 201, resp.text
    mid = resp.json()["id"]

    from harness.relay import LocalRelay, RelayMode
    from infinitemarkets.db import DomainTransaction

    merchant_relay = LocalRelay(mode=RelayMode.ACCEPTING)
    await merchant_relay.start()
    async with DomainTransaction() as tx:
        await tx.execute(
            "UPDATE merchants SET state = 'active' WHERE id = :m",
            {"m": mid},
        )
        await tx.execute(
            f"INSERT INTO {tx.table('relay_configs')} "
            "(id, merchant_id, relay_url, direction, enabled,"
            " created_at, updated_at) VALUES (:i, :m, :u, 'inbox', TRUE,"
            " :t, :t)",
            {"i": uuid.uuid4().hex, "m": mid, "u": merchant_relay.url,
             "t": int(time.time())},
        )
    resp = await client.post(
        f"{API}/categories",
        json={"name": "journey", "default_currency": "SAT"},
        headers=await cookie(),
    )
    cid = resp.json()["id"]
    resp = await client.post(
        f"{API}/products",
        json={
            "category_id": cid,
            "title": "journey widget",
            "amount_minor": 700,
            "currency": "SAT",
            "visibility": "on-sale",
            "stock_on_hand": 50,
            "format": "digital",
            "delivery_content": "the digital goods",
        },
        headers=await cookie(),
    )
    assert resp.status_code == 201, resp.text
    product = resp.json()

    # Inbox activation — kind-10050 publishes through the real relay.
    resp = await client.post(
        f"{API}/merchants/{mid}/inbox/enable",
        json={},
        headers=await cookie(),
    )
    assert resp.status_code == 200, resp.text

    runtime_env.update(
        {
            "merchant_id": mid,
            "category_id": cid,
            "product": product,
            "cookie": cookie,
            "merchant_relay": merchant_relay,
        }
    )
    yield
    await merchant_relay.stop()


async def _merchant(env: dict) -> dict:
    async with env["ext_module"].db.connect() as conn:
        row = await conn.fetchone(
            "SELECT * FROM infinitemarkets.merchants WHERE id = :m",
            {"m": env["merchant_id"]},
        )
    return dict(row)


def _buyer_keys(label: str):
    from harness import sdk

    return sdk.fixed_test_keys(label)


async def _buyer_10050_event(buyer_label: str, relay_url: str) -> dict:
    from nostr_sdk import EventBuilder, Kind, NostrSigner, Tag

    keys = _buyer_keys(buyer_label)
    event = await (
        EventBuilder(Kind(10050), "")
        .tags([Tag.parse(["relay", relay_url])])
        .sign(NostrSigner.keys(keys))
    )
    return json.loads(event.as_json())


async def _nip07_sign_in(env: dict, label: str):
    """A real NIP-07 sign-in — SDK-signed kind-22242 against the
    issued challenge."""
    import httpx
    from nostr_sdk import (
        EventBuilder,
        Kind,
        NostrSigner,
        Tag,
        Timestamp,
    )

    keys = _buyer_keys(label)
    buyer = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=env["app"]), base_url=ORIGIN
    )
    resp = await buyer.get(f"{PUB}/nostr/challenge")
    assert resp.status_code == 200, resp.text
    challenge = resp.json()["challenge"]
    event = await (
        EventBuilder(Kind(22242), challenge)
        .tags([Tag.parse(["challenge", challenge])])
        .custom_created_at(Timestamp.from_secs(int(time.time())))
        .sign(NostrSigner.keys(keys))
    )
    resp = await buyer.post(
        f"{PUB}/nostr/verify",
        json={"event": event.as_json()},
        headers={"Origin": ORIGIN},
    )
    assert resp.status_code == 200, resp.text
    return buyer, keys


async def _worker_tick_until(env: dict, pred, attempts: int = 12) -> dict:
    """Drive the real outbox worker until `pred` sees the wanted state."""
    from infinitemarkets.services import outbox

    outcome = None
    for _ in range(attempts):
        outcome = await outbox.worker_tick("journey-worker")
        if await pred():
            return outcome
        await asyncio.sleep(0.05)
    return outcome or {}


async def test_release_b_journey(runtime_env, monkeypatch):
    """The full arc: gamma order -> payment request -> receipt -> DM ->
    NIP-07 history + claim -> modes -> tombstone."""
    import httpx
    from nostr_sdk import PublicKey

    from harness import sdk
    from harness.relay import LocalRelay, RelayMode
    from infinitemarkets.services import inbox

    env = runtime_env
    merchant = await _merchant(env)
    mid, mpk = merchant["id"], merchant["pubkey"]
    merchant_relay = env["merchant_relay"]
    buyer_label = "journey-buyer"
    buyer_hex = _buyer_keys(buyer_label).public_key().to_hex()

    monkeypatch.setenv("INFINITEMARKETS_RELAY_IO", "on")
    monkeypatch.setenv("INFINITEMARKETS_ALLOW_INSECURE_RELAYS", "1")
    from infinitemarkets.services.transport import transport

    await transport().start([])

    # --- 1. inbox activation reaches 'active' via durable ACK ---
    async def _inbox_active() -> bool:
        row = await _merchant(env)
        return row.get("inbox_state") == "active"

    await _worker_tick_until(env, _inbox_active)
    assert await _inbox_active(), "kind-10050 did not publish"
    k10050 = [
        e["event"] for e in merchant_relay.received_events
        if isinstance(e.get("event"), dict)
        and e["event"].get("kind") == 10050
    ]
    assert k10050, "kind-10050 profile not captured on relay"

    # --- 2. buyer declares inbox relays; gamma order lands ---
    buyer_relay = LocalRelay(mode=RelayMode.ACCEPTING)
    await buyer_relay.start()
    try:
        canned = [await _buyer_10050_event(buyer_label, buyer_relay.url)]
        public = LocalRelay(
            mode=RelayMode.ACCEPTING, canned_events=canned
        )
        await public.start()
        try:
            # The merchant's discovery relay carries the buyer's 10050.
            client = env["client"]
            resp = await client.patch(
                f"{API}/merchants/{mid}",
                json={
                    "relay_configs": [
                        {"relay_url": public.url, "direction": "public"},
                        {
                            "relay_url": merchant_relay.url,
                            "direction": "inbox",
                        },
                    ]
                },
                headers={
                    "Origin": ORIGIN,
                    "X-CSRF-Token": client.cookies.get("gm_csrf"),
                },
            )
            assert resp.status_code == 200, resp.text

            ext_id = f"jny-{uuid.uuid4().hex[:12]}"
            recipient = PublicKey.parse(mpk)
            rumor = sdk.build_order_rumor(
                _buyer_keys(buyer_label), recipient,
                order_external_id=ext_id, amount_sat=700,
                items=[
                    (f"30402:{mpk}:{env['product']['d_tag']}", 1)
                ],
                created_at=int(time.time()),
            )
            seal = await sdk.seal_rumor(
                _buyer_keys(buyer_label), recipient, rumor
            )
            wrap = sdk.wrap_seal(recipient, seal)
            ref = {"id": mid, "pubkey": mpk}
            admitted = await inbox.admit_event(
                "wss://source.example", wrap, ref
            )
            assert admitted == "received"
            await inbox.drain_received()
            await inbox.process_pending()

            async with env["ext_module"].db.connect() as conn:
                order = await conn.fetchone(
                    "SELECT * FROM infinitemarkets.orders"
                    " WHERE merchant_id = :m AND source_event_id = :r",
                    {"m": mid, "r": rumor.id().to_hex()},
                )
            assert order is not None, "gamma order not created"
            order = dict(order)
            assert order["state"] == "awaiting_payment"
            assert order["buyer_pubkey_hash"]

            # --- 3. type-2 payment request publishes dual-copy ---
            intents = None

            async def _msg_published() -> bool:
                nonlocal intents
                async with env["ext_module"].db.connect() as conn:
                    intents = await conn.fetchall(
                        "SELECT * FROM infinitemarkets.outbox_events"
                        " WHERE merchant_id = :m AND aggregate_type"
                        " = 'order_msg' AND aggregate_id LIKE :p",
                        {"m": mid, "p": f"{order['id']}%"},
                    )
                return bool(
                    intents and intents[0]["state"] == "published"
                )

            await _worker_tick_until(env, _msg_published)
            assert await _msg_published(), "payment request unpublished"
            # Buyer relay got a 1059 (recipient copy); merchant relay got
            # the sender copy.
            wraps_buyer = [
                e["event"] for e in buyer_relay.received_events
                if e.get("event", {}).get("kind") == 1059
            ]
            wraps_merchant = [
                e["event"] for e in merchant_relay.received_events
                if e.get("event", {}).get("kind") == 1059
            ]
            assert wraps_buyer, "recipient copy missing on buyer relay"
            assert wraps_merchant, "sender copy missing on merchant relay"

            # --- 4. kind-17 receipt — audit evidence, never settlement ---
            from infinitemarkets.services import order_messages

            sender_hash = order_messages.buyer_hash(
                __import__("infinitemarkets.settings",
                           fromlist=["ext_settings"]).ext_settings(),
                mid, buyer_hex,
            )
            receipt_rumor = {
                "content": "",
                "tags": [
                    ["order", ext_id],
                    ["payment", "lightning"],
                    ["amount", "700"],
                ],
                "created_at": int(time.time()),
            }
            outcome = await order_messages.handle_receipt(
                merchant=merchant, sender_hash=sender_hash,
                rumor=receipt_rumor, now=int(time.time()),
            )
            # No matching bolt11/preimage -> audit-only.
            assert outcome["outcome"] == "audit-only"

            # --- 5. buyer DM -> merchant thread; merchant reply ---
            dm = await order_messages.handle_dm(
                merchant=merchant, sender_hash=sender_hash,
                author_pubkey=buyer_hex,
                rumor={
                    "content": "when will my journey widget arrive?",
                    "tags": [["subject", ext_id]],
                    "created_at": int(time.time()),
                },
                rumor_id=uuid.uuid4().hex,
                now=int(time.time()),
            )
            assert dm["conversation_id"] == f"order:{order['id']}"
            reply = await order_messages.reply_dm(
                mid, conversation_id=dm["conversation_id"],
                content="on its way",
            )
            assert reply["queued"] is True

            thread = await order_messages.get_thread(
                mid, dm["conversation_id"]
            )
            bodies = [m["content"] for m in thread["messages"]]
            assert any("journey widget" in c for c in bodies)
            assert any("on its way" in c for c in bodies)
        finally:
            await public.stop()
    finally:
        await buyer_relay.stop()

    # --- 6. NIP-07 sign-in: the gamma buyer sees their order ---
    buyer, _keys = await _nip07_sign_in(env, buyer_label)
    resp = await buyer.get(f"{PUB}/nostr/orders")
    assert resp.status_code == 200, resp.text
    orders = resp.json()["orders"]
    assert any(o["order_id"] == order["id"] for o in orders)
    assert any("journey widget" in o["first_item"] for o in orders)

    # --- 7. claim flow: anonymous web order -> bound to this buyer ---
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=env["app"]), base_url=ORIGIN
    ) as anon:
        resp = await anon.post(
            f"{PUB}/checkout",
            json={
                "merchant_pubkey": mpk,
                "items": [
                    {"d_tag": env["product"]["d_tag"], "quantity": 1}
                ],
            },
            headers={"Idempotency-Key": uuid.uuid4().hex},
        )
    assert resp.status_code == 201, resp.text
    token = resp.json()["public_token"]
    resp = await buyer.post(
        f"{PUB}/nostr/claim",
        json={"token": token},
        headers={"Origin": ORIGIN},
    )
    assert resp.status_code == 200, resp.text
    resp = await buyer.get(f"{PUB}/nostr/orders")
    assert len(resp.json()["orders"]) == 2

    # --- 8. storefront modes gate new purchases only ---
    cookie = await env["cookie"]()
    resp = await env["client"].put(
        f"{API}/merchants/{mid}/storefront-mode",
        json={"mode": "nostr_only", "confirm": True},
        headers=cookie,
    )
    assert resp.status_code == 200, resp.text

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=env["app"]), base_url=ORIGIN
    ) as anon:
        resp = await anon.post(
            f"{PUB}/checkout",
            json={
                "merchant_pubkey": mpk,
                "items": [
                    {"d_tag": env["product"]["d_tag"], "quantity": 1}
                ],
            },
            headers={"Idempotency-Key": uuid.uuid4().hex},
        )
        assert resp.status_code == 422  # no new purchases
        # The private order link still resolves.
        resp = await anon.get(f"{PUB}/order-status",
                              headers={"X-Order-Token": token})
        assert resp.status_code == 200
        assert resp.json()["state"] == "awaiting_payment"
        resp = await anon.get(
            f"/infinitemarkets/order?shop={mpk}"
        )
        assert resp.status_code == 200
        # Storefront browse surfaces show the nostr-only notice.
        resp = await anon.get(
            f"/infinitemarkets/p/{mpk}/{env['product']['d_tag']}"
        )
        assert 'data-gm="nostr-only"' in resp.text

    await env["client"].put(
        f"{API}/merchants/{mid}/storefront-mode",
        json={"mode": "full", "confirm": True},
        headers=cookie,
    )

    # --- 9. deactivation publishes the 10050 tombstone (D-17) ---
    resp = await env["client"].post(
        f"{API}/merchants/{mid}/inbox/disable",
        json={},
        headers=cookie,
    )
    assert resp.status_code == 200, resp.text

    async def _tombstoned() -> bool:
        async with env["ext_module"].db.connect() as conn:
            intents = await conn.fetchall(
                "SELECT state FROM infinitemarkets.outbox_events"
                " WHERE merchant_id = :m AND aggregate_type = 'merchant'"
                " AND event_kind = 5",
                {"m": mid},
            )
        return bool(intents) and intents[0]["state"] == "published"

    await _worker_tick_until(env, _tombstoned)
    assert await _tombstoned(), "inbox tombstone never published"
    k5 = [
        e["event"] for e in merchant_relay.received_events
        if isinstance(e.get("event"), dict) and e["event"].get("kind") == 5
    ]
    assert k5, "kind-5 tombstone not captured on relay"
    row = await _merchant(env)
    assert row.get("inbox_state") in ("deactivating", "off")
    # Existing orders untouched by deactivation (D-11/D-17).
    resp = await buyer.get(f"{PUB}/nostr/orders")
    assert resp.status_code == 200
    assert len(resp.json()["orders"]) == 2
    await buyer.aclose()
