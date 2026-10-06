"""Gamma NIP-17 inbox -> domain dispatch — plan 03-02 (GAM-02/GAM-04).

A validated kind-16 type-1 wrap drives the SAME checkout pipeline as the
web path: server-priced order, reservation, FakeWallet invoice, and a
type-2 payment-request ``order_msg`` intent — never a public token or a
bolt11 HTTP response. Every malformed/hostile shape lands on a bounded
rejected path with a merchant-visible reason and (when parseable) a
``status=rejected`` type-3 reply intent.

Real host boot + FakeWallet + LocalRelay fixtures; extension workers are
cancelled — admission, drain, dispatch and publication are driven
explicitly.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio

pytestmark = pytest.mark.runtime

ORIGIN = "https://shop.example"
API = "/infinitemarkets/api/v1"


# --- fixtures / helpers -------------------------------------------------------


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
            "display_name": "nip17 shop",
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
        f"{API}/categories",
        json={"name": "gamma", "default_currency": "SAT"},
        headers=await cookie(),
    )
    assert resp.status_code == 201, resp.text
    cid = resp.json()["id"]

    async def product(title, stock, fmt="digital", price=500) -> dict:
        resp = await client.post(
            f"{API}/products",
            json={
                "category_id": cid,
                "title": title,
                "amount_minor": price,
                "currency": "SAT",
                "visibility": "on-sale",
                "stock_on_hand": stock,
                "format": fmt,
            },
            headers=await cookie(),
        )
        assert resp.status_code == 201, resp.text
        return resp.json()

    runtime_env.update(
        {
            "merchant_id": mid,
            "category_id": cid,
            "make_product": product,
            "cookie": cookie,
        }
    )
    yield


def _headers(env: dict, csrf: str | None = None) -> dict:
    cookie = f"cookie_access_token={env['token']}"
    if csrf:
        cookie += f"; gm_csrf={csrf}"
    h = {"Cookie": cookie, "Origin": ORIGIN}
    if csrf:
        h["X-CSRF-Token"] = csrf
    return h


async def _merchant(env: dict) -> dict:
    async with env["ext_module"].db.connect() as conn:
        row = await conn.fetchone(
            "SELECT * FROM infinitemarkets.merchants WHERE id = :m",
            {"m": env["merchant_id"]},
        )
    return dict(row)


async def _set_relays(env: dict, mid: str, configs: list[dict]):
    client = env["client"]
    resp = await client.patch(
        f"{API}/merchants/{mid}",
        json={"relay_configs": configs},
        headers=_headers(env, client.cookies.get("gm_csrf") or ""),
    )
    assert resp.status_code == 200, resp.text


def _buyer_keys(label: str):
    from harness import sdk

    return sdk.fixed_test_keys(label)


async def _buyer_10050_event(buyer_label: str, relay_url: str) -> dict:
    """A buyer-signed kind-10050 advertising ``relay_url``."""
    from nostr_sdk import EventBuilder, Kind, NostrSigner, Tag

    keys = _buyer_keys(buyer_label)
    event = await (
        EventBuilder(Kind(10050), "")
        .tags([Tag.parse(["relay", relay_url])])
        .sign(NostrSigner.keys(keys))
    )
    return json.loads(event.as_json())


@asynccontextmanager
async def _relay_env(env: dict, monkeypatch, mid: str, *,
                   buyer_label: str | None = None,
                   buyer_mode=None):
    """Buyer inbox relay + public discovery relay + merchant inbox relay.

    The buyer's signed kind-10050 (advertising the buyer relay) is canned
    content on the public relay; the buyer/merchant inbox relays record
    received EVENTs for dual-copy assertions.
    """
    from harness import relay as relay_module
    from infinitemarkets.services.transport import transport

    monkeypatch.setenv("INFINITEMARKETS_RELAY_IO", "on")
    monkeypatch.setenv("INFINITEMARKETS_ALLOW_INSECURE_RELAYS", "1")

    mode = buyer_mode or relay_module.RelayMode.ACCEPTING
    async with relay_module.LocalRelay(mode=mode) as buyer_relay:
        canned = []
        if buyer_label is not None:
            canned = [
                await _buyer_10050_event(buyer_label, buyer_relay.url)
            ]
        async with relay_module.LocalRelay(
            mode=relay_module.RelayMode.ACCEPTING, canned_events=canned
        ) as public, relay_module.LocalRelay(
            mode=relay_module.RelayMode.ACCEPTING
        ) as merchant_relay:
            await _set_relays(env, mid, [
                {"relay_url": public.url, "direction": "public"},
                {"relay_url": merchant_relay.url, "direction": "inbox"},
            ])
            tport = transport()
            await tport.start([])
            yield public, buyer_relay, merchant_relay


async def _order_wrap(
    buyer_label: str,
    merchant_pubkey: str,
    *,
    order_id: str,
    items: list[tuple[str, int]],
    amount: int = 0,
    extra_tags: list[list[str]] | None = None,
):
    """A buyer-sealed kind-16 type-1 wrap addressed to the merchant."""
    from nostr_sdk import PublicKey

    from harness import sdk

    buyer = _buyer_keys(buyer_label)
    recipient = PublicKey.parse(merchant_pubkey)
    rumor = sdk.build_order_rumor(
        buyer,
        recipient,
        order_external_id=order_id,
        amount_sat=amount,
        items=[(f"30402:{merchant_pubkey}:{d}", q) for d, q in items],
        created_at=int(time.time()),
        extra_tags=extra_tags,
    )
    seal = await sdk.seal_rumor(buyer, recipient, rumor)
    wrap = sdk.wrap_seal(recipient, seal)
    return wrap, rumor


async def _generic_wrap(
    buyer_label: str,
    merchant_pubkey: str,
    *,
    kind: int,
    content: str,
    tags: list[list[str]],
    seal_keys=None,
):
    """Any rumor kind sealed by ``seal_keys`` (default: the buyer)."""
    from nostr_sdk import EventBuilder, Kind, PublicKey, Tag, Timestamp

    from harness import sdk

    author = seal_keys or _buyer_keys(buyer_label)
    recipient = PublicKey.parse(merchant_pubkey)
    rumor = (
        EventBuilder(Kind(kind), content)
        .custom_created_at(Timestamp.from_secs(int(time.time())))
        .tags([Tag.parse(t) for t in tags])
        .build(author.public_key())
    )
    seal = await sdk.seal_rumor(author, recipient, rumor)
    wrap = sdk.wrap_seal(recipient, seal)
    return wrap, rumor


async def _inbox_rows(env: dict, mid: str) -> list[dict]:
    async with env["ext_module"].db.connect() as conn:
        rows = await conn.fetchall(
            "SELECT * FROM infinitemarkets.inbox_events "
            "WHERE merchant_id = :m ORDER BY received_at",
            {"m": mid},
        )
    return [dict(r) for r in rows]


async def _orders(env: dict, mid: str) -> list[dict]:
    async with env["ext_module"].db.connect() as conn:
        rows = await conn.fetchall(
            "SELECT * FROM infinitemarkets.orders WHERE merchant_id = :m",
            {"m": mid},
        )
    return [dict(r) for r in rows]


async def _outbox_rows(env: dict, mid: str) -> list[dict]:
    async with env["ext_module"].db.connect() as conn:
        rows = await conn.fetchall(
            "SELECT * FROM infinitemarkets.outbox_events"
            " WHERE merchant_id = :m",
            {"m": mid},
        )
    return [dict(r) for r in rows]


async def _reservation_count(env: dict, product_id: str) -> int:
    async with env["ext_module"].db.connect() as conn:
        row = await conn.fetchone(
            "SELECT COUNT(*) AS n"
            " FROM infinitemarkets.inventory_reservations"
            " WHERE product_id = :p",
            {"p": product_id},
        )
    return int(row["n"])


async def _row_for_wrap(env: dict, mid: str, wrap) -> dict | None:
    outer_id = wrap.id().to_hex()
    rows = await _inbox_rows(env, mid)
    return next((r for r in rows if r["outer_event_id"] == outer_id), None)


async def _pipeline(env: dict, merchant: dict, wrap):
    """admit -> drain -> dispatch for one wrap."""
    from infinitemarkets.services import inbox

    ref = {"id": merchant["id"], "pubkey": merchant["pubkey"]}
    admitted = await inbox.admit_event("wss://source.example", wrap, ref)
    await inbox.drain_received()
    report = await inbox.process_pending()
    return admitted, report


# --- tests --------------------------------------------------------------------


async def test_type1_creates_gamma_order_and_type2_intent(
    runtime_env, monkeypatch
):
    """received -> validated -> processed: a type-1 wrap mints a gamma
    order (protocol='gamma', buyer-key HMAC, source rumor id, no public
    token), and ``awaiting_payment`` enqueues ONE type-2 ``order_msg``
    intent instead of returning bolt11 to a caller."""
    env = runtime_env
    merchant = await _merchant(env)
    mid, mpk = merchant["id"], merchant["pubkey"]
    product = await env["make_product"](uuid.uuid4().hex[:8], 10)
    ext_id = f"order-{uuid.uuid4().hex[:12]}"

    async with _relay_env(env, monkeypatch, mid, buyer_label="buyer-1"):
        wrap, rumor = await _order_wrap(
            "buyer-1", mpk, order_id=ext_id,
            items=[(product["d_tag"], 2)], amount=999999,
        )
        admitted, report = await _pipeline(env, merchant, wrap)
        assert admitted == "received"
        row = await _row_for_wrap(env, mid, wrap)
        assert row["processed_state"] == "processed"
        assert row["kind"] == 16
        assert row["rumor_id"] == rumor.id().to_hex()
        assert row["processed_at"]

    orders = [o for o in await _orders(env, mid)
              if o["source_event_id"] == rumor.id().to_hex()]
    assert len(orders) == 1
    order = orders[0]
    assert order["protocol"] == "gamma"
    assert order["buyer_pubkey_hash"]
    assert order["buyer_pubkey_enc"]
    assert order["public_token_hash"] is None
    # Buyer-declared amount is stored, never trusted for pricing.
    assert order["buyer_amount_sat"] == 999999
    assert order["total_sat"] == 1000  # 2 x 500 — server-priced
    assert order["state"] == "awaiting_payment"
    assert order["shipping_state"] == "not_required"

    intents = [
        r for r in await _outbox_rows(env, mid)
        if r["aggregate_type"] == "order_msg"
    ]
    assert len(intents) == 1
    intent = intents[0]
    assert intent["event_kind"] == 16
    assert intent["aggregate_revision"] == 0
    assert intent["payload_enc"] is not None
    assert intent["aggregate_id"].startswith(order["id"] + ":")


async def test_duplicate_wrap_and_rumor_retry_single_order(
    runtime_env, monkeypatch
):
    """Outer-id dedupe AND rumor-id dedupe: the same wrap is a no-op and
    a retry under a fresh outer marks 'duplicate' — one order total."""
    env = runtime_env
    merchant = await _merchant(env)
    mid, mpk = merchant["id"], merchant["pubkey"]
    product = await env["make_product"](uuid.uuid4().hex[:8], 10)
    ext_id = f"dup-{uuid.uuid4().hex[:12]}"

    async with _relay_env(env, monkeypatch, mid, buyer_label="buyer-dup"):
        from nostr_sdk import PublicKey

        from harness import sdk
        from infinitemarkets.services import inbox

        buyer = _buyer_keys("buyer-dup")
        recipient = PublicKey.parse(mpk)
        rumor = sdk.build_order_rumor(
            buyer, recipient, order_external_id=ext_id,
            amount_sat=500, items=[(f"30402:{mpk}:{product['d_tag']}", 1)],
            created_at=int(time.time()),
        )
        wrap_a = sdk.wrap_seal(
            recipient, await sdk.seal_rumor(buyer, recipient, rumor)
        )
        wrap_b = sdk.wrap_seal(
            recipient, await sdk.seal_rumor(buyer, recipient, rumor)
        )
        ref = {"id": mid, "pubkey": mpk}
        assert await inbox.admit_event(
            "wss://a.example", wrap_a, ref
        ) == "received"
        assert await inbox.admit_event(
            "wss://b.example", wrap_a, ref
        ) == "duplicate"
        assert await inbox.admit_event(
            "wss://c.example", wrap_b, ref
        ) == "received"
        await inbox.drain_received()
        await inbox.process_pending()
        retry_row = await _row_for_wrap(env, mid, wrap_b)
        assert retry_row["processed_state"] == "duplicate"

    orders = await _orders(env, mid)
    assert len([
        o for o in orders
        if o["source_event_id"] == rumor.id().to_hex()
    ]) == 1


async def test_missing_buyer_10050_rejected(runtime_env, monkeypatch):
    """§9.3 no-route: a buyer without a declared kind-10050 set rejects
    intake BEFORE any order/reservation — a ``status=rejected`` type-3
    reply is enqueued and itself sits pending 'no_inbox_relays'."""
    env = runtime_env
    merchant = await _merchant(env)
    mid, mpk = merchant["id"], merchant["pubkey"]
    product = await env["make_product"](uuid.uuid4().hex[:8], 10)
    ext_id = f"nr-{uuid.uuid4().hex[:12]}"

    async with _relay_env(env, monkeypatch, mid, buyer_label=None):
        wrap, rumor = await _order_wrap(
            "buyer-noroute", mpk, order_id=ext_id,
            items=[(product["d_tag"], 1)], amount=500,
        )
        admitted, report = await _pipeline(env, merchant, wrap)
        assert admitted == "received"
        row = await _row_for_wrap(env, mid, wrap)
        assert row["processed_state"] == "rejected"
        assert row["reject_reason"] == "no-inbox-relays"

    assert not [
        o for o in await _orders(env, mid)
        if o["source_event_id"] == rumor.id().to_hex()
    ]
    assert await _reservation_count(env, product["id"]) == 0
    replies = [
        r for r in await _outbox_rows(env, mid)
        if r["aggregate_type"] == "order_msg"
        and r["aggregate_id"].startswith("rejected:")
    ]
    assert len(replies) == 1


async def test_external_id_charset_violation_rejected(runtime_env, monkeypatch):
    """An ``order`` tag outside ^[A-Za-z0-9_-]{1,64}$ is rejected at the
    payload builder — before any order insert."""
    env = runtime_env
    merchant = await _merchant(env)
    mid, mpk = merchant["id"], merchant["pubkey"]
    product = await env["make_product"](uuid.uuid4().hex[:8], 10)

    async with _relay_env(env, monkeypatch, mid, buyer_label="buyer-e1"):
        wrap, rumor = await _order_wrap(
            "buyer-e1", mpk, order_id="not an order id!!",
            items=[(product["d_tag"], 1)], amount=500,
        )
        await _pipeline(env, merchant, wrap)
        row = await _row_for_wrap(env, mid, wrap)
        assert row["processed_state"] == "rejected"
        assert row["reject_reason"] == "invalid-external-id"
        assert await _reservation_count(env, product["id"]) == 0


async def test_cross_merchant_item_rejected(runtime_env, monkeypatch):
    """A ``30402:<foreign-pk>:<d>`` item reference rejects — cross-merchant
    carts never reach pricing or reservation."""
    env = runtime_env
    merchant = await _merchant(env)
    mid, mpk = merchant["id"], merchant["pubkey"]
    product = await env["make_product"](uuid.uuid4().hex[:8], 10)
    foreign = _buyer_keys("foreign-merchant").public_key().to_hex()

    async with _relay_env(env, monkeypatch, mid, buyer_label="buyer-x"):
        # items arrive pre-shaped as '30402:<pk>:<d>' — build manually to
        # keep the foreign pubkey.
        from nostr_sdk import PublicKey

        from harness import sdk

        buyer = _buyer_keys("buyer-x")
        recipient = PublicKey.parse(mpk)
        rumor = sdk.build_order_rumor(
            buyer, recipient,
            order_external_id=f"x-{uuid.uuid4().hex[:12]}",
            amount_sat=500,
            items=[(f"30402:{foreign}:{product['d_tag']}", 1)],
            created_at=int(time.time()),
        )
        seal = await sdk.seal_rumor(buyer, recipient, rumor)
        wrap = sdk.wrap_seal(recipient, seal)
        await _pipeline(env, merchant, wrap)
        row = await _row_for_wrap(env, mid, wrap)
        assert row["processed_state"] == "rejected"
        assert row["reject_reason"] == "invalid-content"
        assert await _reservation_count(env, product["id"]) == 0


async def test_opaque_address_physical_rejected(runtime_env, monkeypatch):
    """An opaque (non-JSON) ``address`` string + a physical cart takes the
    §8.1 step-7 reject-before-reservation path; a type-3 rejected reply
    is enqueued."""
    env = runtime_env
    merchant = await _merchant(env)
    mid, mpk = merchant["id"], merchant["pubkey"]
    product = await env["make_product"](
        uuid.uuid4().hex[:8], 10, fmt="physical"
    )

    async with _relay_env(env, monkeypatch, mid, buyer_label="buyer-ph"):
        wrap, rumor = await _order_wrap(
            "buyer-ph", mpk, order_id=f"ph-{uuid.uuid4().hex[:12]}",
            items=[(product["d_tag"], 1)], amount=500,
            extra_tags=[["address", "123 main st"]],
        )
        await _pipeline(env, merchant, wrap)
        row = await _row_for_wrap(env, mid, wrap)
        assert row["processed_state"] == "rejected"
        assert row["reject_reason"] == "invalid-shipping-destination"
        assert await _reservation_count(env, product["id"]) == 0

    replies = [
        r for r in await _outbox_rows(env, mid)
        if r["aggregate_type"] == "order_msg"
        and r["aggregate_id"].startswith("rejected:")
    ]
    assert len(replies) >= 1


async def test_buyer_type2_rejected(runtime_env, monkeypatch):
    """An inbound type-2 payment request is merchant-only (§6.9) —
    rejected, no order mutation."""
    env = runtime_env
    merchant = await _merchant(env)
    mid, mpk = merchant["id"], merchant["pubkey"]

    async with _relay_env(env, monkeypatch, mid, buyer_label="buyer-t2"):
        wrap, rumor = await _generic_wrap(
            "buyer-t2", mpk, kind=16, content="pay me",
            tags=[
                ["p", mpk], ["subject", "order-payment"], ["type", "2"],
                ["order", "whatever-1"], ["amount", "21"],
            ],
        )
        await _pipeline(env, merchant, wrap)
        row = await _row_for_wrap(env, mid, wrap)
        assert row["processed_state"] == "rejected"
        assert row["reject_reason"] == "inbound-type2-unsupported"


async def test_inbound_type3_unknown_order_audit_only(runtime_env, monkeypatch):
    """Buyer type-3 naming an order id that doesn't exist is processed
    audit-only — no state writes, no oracle."""
    env = runtime_env
    merchant = await _merchant(env)
    mid, mpk = merchant["id"], merchant["pubkey"]

    async with _relay_env(env, monkeypatch, mid, buyer_label="buyer-t3"):
        wrap, rumor = await _generic_wrap(
            "buyer-t3", mpk, kind=16, content="cancel",
            tags=[
                ["p", mpk], ["subject", "order-info"], ["type", "3"],
                ["order", "ghost-order-1"], ["status", "cancelled"],
            ],
        )
        await _pipeline(env, merchant, wrap)
        row = await _row_for_wrap(env, mid, wrap)
        assert row["processed_state"] == "processed"
        assert row["reject_reason"] is None


async def test_kind14_dm_threads_unknown(runtime_env, monkeypatch):
    """A kind-14 DM without a matching order lands in the merchant-visible
    ``unknown:<sender_hash>`` conversation — no order-existence oracle."""
    env = runtime_env
    merchant = await _merchant(env)
    mid, mpk = merchant["id"], merchant["pubkey"]

    async with _relay_env(env, monkeypatch, mid, buyer_label="buyer-dm"):
        wrap, rumor = await _generic_wrap(
            "buyer-dm", mpk, kind=14, content="hi merchant",
            tags=[["p", mpk]],
        )
        await _pipeline(env, merchant, wrap)
        row = await _row_for_wrap(env, mid, wrap)
        assert row["processed_state"] == "processed"

    async with env["ext_module"].db.connect() as conn:
        msg = await conn.fetchone(
            "SELECT * FROM infinitemarkets.order_messages"
            " WHERE rumor_id = :r",
            {"r": rumor.id().to_hex()},
        )
    assert msg is not None
    assert msg["direction"] == "in"
    assert msg["order_id"] is None
    assert msg["conversation_id"].startswith("unknown:")


async def test_sender_copy_recovery_no_dispatch(runtime_env, monkeypatch):
    """A merchant-authored wrap whose rumor id matches an outbound
    order_messages row marks 'sender-copy-recovered' — never dispatched
    as an inbound command, no orders/order_events mutation."""
    env = runtime_env
    merchant = await _merchant(env)
    mid, mpk = merchant["id"], merchant["pubkey"]

    # Fabricate an outbound descriptor row (as enqueue_order_msg would)
    # plus a wrap of the SAME rumor sealed by the merchant key.
    from infinitemarkets import keystore as keystore_mod
    from infinitemarkets.db import DomainTransaction
    from infinitemarkets.services import order_messages
    from infinitemarkets.services import outbox as outbox_service
    from infinitemarkets.settings import ext_settings

    buyer = _buyer_keys("buyer-recv").public_key().to_hex()
    async with DomainTransaction() as tx:
        payload = {
            "rumor_kind": 16, "type": "3", "subject": "order-info",
            "order_external_id": "ext-1", "status": "cancelled",
            "recipient_pubkey": buyer,
            "author_pubkey": mpk, "content": "", "semantic": "status",
        }
        payload["rumor_created_at"] = int(time.time())
        descriptor = order_messages.rumor_descriptor(None, 0, payload)
        intent_id = await outbox_service.enqueue_intent(
            tx, mid, "order_msg", "manual:1", 16, revision=0,
        )
        ver = ext_settings().active_key_version
        from infinitemarkets import crypto

        encrypted = crypto.encrypt(
            json.dumps(
                descriptor, sort_keys=True, separators=(",", ":")
            ).encode(),
            ext_settings().master_keys[ver],
            record_id=intent_id, table="outbox_events",
            column="payload_enc", key_version=ver,
        )
        await tx.execute(
            "UPDATE outbox_events SET payload_enc = :p WHERE id = :i",
            {"p": encrypted, "i": intent_id},
        )
        msg_id = uuid.uuid4().hex
        await tx.execute(
            "INSERT INTO order_messages "
            "(id, order_id, direction, protocol, semantic_kind,"
            " recipient_hash, rumor_id, created_at) "
            "VALUES (:i, NULL, 'out', 'nip17', 'status', :rh, :r, :n)",
            {
                "i": msg_id, "r": descriptor["rumor_id"],
                "rh": order_messages.buyer_hash(ext_settings(), mid, buyer),
                "n": int(time.time()),
            },
        )
    rumor = order_messages.rebuild_rumor(descriptor)
    ks = keystore_mod.key_store(ext_settings())
    wrap = await ks.nip17_wrap(mid, rumor, mpk)

    orders_before = len(await _orders(env, mid))
    async with _relay_env(env, monkeypatch, mid):
        await _pipeline(env, merchant, wrap)
    row = await _row_for_wrap(env, mid, wrap)
    assert row["processed_state"] == "processed"
    assert row["reject_reason"] == "sender-copy-recovered"
    assert len(await _orders(env, mid)) == orders_before


async def test_disallowed_rumor_kind_rejected(runtime_env, monkeypatch):
    """A rumor kind outside the {14,16,17} allowlist rejects at the
    unwrap stage — never reaches domain dispatch."""
    env = runtime_env
    merchant = await _merchant(env)
    mid, mpk = merchant["id"], merchant["pubkey"]

    async with _relay_env(env, monkeypatch, mid):
        wrap, rumor = await _generic_wrap(
            "buyer-quar", mpk, kind=1, content="not an order",
            tags=[["p", mpk]],
        )
        from infinitemarkets.services import inbox

        ref = {"id": mid, "pubkey": mpk}
        await inbox.admit_event("wss://source.example", wrap, ref)
        await inbox.drain_received()
        row = await _row_for_wrap(env, mid, wrap)
        assert row["processed_state"] == "rejected"
        assert row["reject_reason"] == "rumor-kind-not-allowed"


# --- Task 2: inbound semantics + outbound message chaining ---------------------


async def _gamma_order(env: dict, monkeypatch, merchant: dict,
                       buyer_label: str, *, qty=1):
    """Drive a type-1 wrap through intake; return (order, rumor)."""
    mid, mpk = merchant["id"], merchant["pubkey"]
    product = await env["make_product"](uuid.uuid4().hex[:8], 10)
    wrap, rumor = await _order_wrap(
        buyer_label, mpk, order_id=f"t2-{uuid.uuid4().hex[:12]}",
        items=[(product["d_tag"], qty)], amount=500,
    )
    async with _relay_env(env, monkeypatch, mid, buyer_label=buyer_label):
        await _pipeline(env, merchant, wrap)
    async with env["ext_module"].db.connect() as conn:
        order = await conn.fetchone(
            "SELECT * FROM infinitemarkets.orders"
            " WHERE merchant_id = :m AND source_event_id = :r",
            {"m": mid, "r": rumor.id().to_hex()},
        )
    assert order is not None
    return dict(order), rumor


def _external_id(env: dict, order: dict) -> str:
    """Owner-side decrypt of orders.external_id_enc."""
    from infinitemarkets import crypto
    from infinitemarkets.settings import ext_settings

    settings = ext_settings()
    ver = crypto.envelope_version(order["external_id_enc"])
    return crypto.decrypt(
        order["external_id_enc"], settings.master_keys[ver],
        record_id=order["id"], table="orders",
        column="external_id_enc", key_version=ver,
    ).decode()


async def _payment_row(env: dict, order_id: str) -> dict:
    async with env["ext_module"].db.connect() as conn:
        return dict(await conn.fetchone(
            "SELECT * FROM infinitemarkets.payments WHERE order_id = :o",
            {"o": order_id},
        ))


def _dec_bolt11(order: dict, payment: dict) -> str:
    from infinitemarkets import crypto
    from infinitemarkets.settings import ext_settings

    settings = ext_settings()
    ver = crypto.envelope_version(payment["bolt11_enc"])
    return crypto.decrypt(
        payment["bolt11_enc"], settings.master_keys[ver],
        record_id=order["id"], table="payments",
        column="bolt11_enc", key_version=ver,
    ).decode()


async def _fresh_order_row(env: dict, order_id: str) -> dict:
    async with env["ext_module"].db.connect() as conn:
        return dict(await conn.fetchone(
            "SELECT * FROM infinitemarkets.orders WHERE id = :i",
            {"i": order_id},
        ))


async def _held_units(env: dict, order_id: str) -> int:
    async with env["ext_module"].db.connect() as conn:
        row = await conn.fetchone(
            "SELECT COALESCE(SUM(quantity), 0) AS n"
            " FROM infinitemarkets.inventory_reservations"
            " WHERE order_id = :o AND state = 'held'",
            {"o": order_id},
        )
    return int(row["n"])


async def _msg_rows(env: dict, order_id: str | None = None) -> list[dict]:
    async with env["ext_module"].db.connect() as conn:
        if order_id:
            rows = await conn.fetchall(
                "SELECT * FROM infinitemarkets.order_messages"
                " WHERE order_id = :o",
                {"o": order_id},
            )
        else:
            rows = await conn.fetchall(
                "SELECT * FROM infinitemarkets.order_messages"
            )
    return [dict(r) for r in rows]


async def test_buyer_cancel_on_awaiting_payment(runtime_env, monkeypatch):
    """Buyer type-3 ``cancelled`` on an awaiting_payment order is
    actionable: §7.1 legality releases stock once + transitions cancelled,
    and the transition emits a type-3 'cancelled' order_msg intent."""
    env = runtime_env
    merchant = await _merchant(env)
    mid, mpk = merchant["id"], merchant["pubkey"]
    buyer = "buyer-cancel-1"
    order, _rumor = await _gamma_order(env, monkeypatch, merchant, buyer)
    assert order["state"] == "awaiting_payment"
    assert await _held_units(env, order["id"]) == 1
    ext_id = _external_id(env, order)

    async with _relay_env(env, monkeypatch, mid, buyer_label=buyer):
        wrap, rumor = await _generic_wrap(
            buyer, mpk, kind=16, content="cancel please",
            tags=[
                ["p", mpk], ["subject", "order-info"], ["type", "3"],
                ["order", ext_id], ["status", "cancelled"],
            ],
        )
        await _pipeline(env, merchant, wrap)
        row = await _row_for_wrap(env, mid, wrap)
        assert row["processed_state"] == "processed"

    order = await _fresh_order_row(env, order["id"])
    assert order["state"] == "cancelled"
    assert await _held_units(env, order["id"]) == 0
    # The cancel transition enqueued the outbound type-3 reply.
    msgs = await _msg_rows(env, order["id"])
    outbound = [m for m in msgs if m["direction"] == "out"]
    semantics = {m["semantic_kind"] for m in outbound}
    assert "payment-request" in semantics
    assert "status" in semantics
    intents = [
        r for r in await _outbox_rows(env, mid)
        if r["aggregate_type"] == "order_msg"
        and r["aggregate_id"].startswith(order["id"] + ":")
    ]
    assert len(intents) == len(outbound)


async def test_buyer_cancel_on_confirmed_illegal(runtime_env, monkeypatch):
    """Confirmed orders are NOT buyer-cancellable (§7.1) — the wrap is
    audit-only 'processed', no mutation."""
    from infinitemarkets.services import settlement

    env = runtime_env
    merchant = await _merchant(env)
    mid, mpk = merchant["id"], merchant["pubkey"]
    order, _rumor = await _gamma_order(
        env, monkeypatch, merchant, "buyer-cancel-2"
    )
    await settlement.confirm_settlement(order_id=order["id"])
    order = await _fresh_order_row(env, order["id"])
    assert order["state"] == "confirmed"
    ext_id = _external_id(env, order)

    async with _relay_env(env, monkeypatch, mid, buyer_label="buyer-cancel-2"):
        wrap, _r = await _generic_wrap(
            "buyer-cancel-2", mpk, kind=16, content="",
            tags=[
                ["p", mpk], ["subject", "order-info"], ["type", "3"],
                ["order", ext_id], ["status", "cancelled"],
            ],
        )
        await _pipeline(env, merchant, wrap)
        row = await _row_for_wrap(env, mid, wrap)
        assert row["processed_state"] == "processed"
    order = await _fresh_order_row(env, order["id"])
    assert order["state"] == "confirmed"


async def test_buyer_status_confirmed_audit_only(runtime_env, monkeypatch):
    """Only 'cancelled' is actionable inbound — a buyer type-3
    'confirmed' is audit-only, never mutates merchant state."""
    env = runtime_env
    merchant = await _merchant(env)
    mid, mpk = merchant["id"], merchant["pubkey"]
    order, _r = await _gamma_order(
        env, monkeypatch, merchant, "buyer-status-1"
    )
    ext_id = _external_id(env, order)
    async with _relay_env(env, monkeypatch, mid, buyer_label="buyer-status-1"):
        wrap, _ = await _generic_wrap(
            "buyer-status-1", mpk, kind=16, content="",
            tags=[
                ["p", mpk], ["subject", "order-info"], ["type", "3"],
                ["order", ext_id], ["status", "confirmed"],
            ],
        )
        await _pipeline(env, merchant, wrap)
    order = await _fresh_order_row(env, order["id"])
    assert order["state"] == "awaiting_payment"


async def test_foreign_buyer_cancel_no_oracle(runtime_env, monkeypatch):
    """A different buyer's cancel naming a real order id is audit-only —
    sender-hash mismatch means no reveal, no mutation."""
    env = runtime_env
    merchant = await _merchant(env)
    mid, mpk = merchant["id"], merchant["pubkey"]
    order, _r = await _gamma_order(
        env, monkeypatch, merchant, "buyer-own-1"
    )
    ext_id = _external_id(env, order)
    async with _relay_env(env, monkeypatch, mid, buyer_label="stranger-1"):
        wrap, _ = await _generic_wrap(
            "stranger-1", mpk, kind=16, content="",
            tags=[
                ["p", mpk], ["subject", "order-info"], ["type", "3"],
                ["order", ext_id], ["status", "cancelled"],
            ],
        )
        await _pipeline(env, merchant, wrap)
        row = await _row_for_wrap(env, mid, wrap)
        assert row["processed_state"] == "processed"
    order = await _fresh_order_row(env, order["id"])
    assert order["state"] == "awaiting_payment"


async def test_kind17_receipt_verified(runtime_env, monkeypatch):
    """A kind-17 receipt with the stored bolt11 + a preimage hashing to
    payments.payment_hash sets cosmetic receipt_verified — never touches
    payment state."""
    from lnbits.wallets import get_funding_source

    from infinitemarkets.services import settlement

    env = runtime_env
    merchant = await _merchant(env)
    mid, mpk = merchant["id"], merchant["pubkey"]
    order, _r = await _gamma_order(
        env, monkeypatch, merchant, "buyer-rcpt-1"
    )
    payment = await _payment_row(env, order["id"])
    bolt11 = _dec_bolt11(order, payment)
    # FakeWallet's honest preimage — settle the invoice first so the
    # payment_secrets entry exists.
    funding = get_funding_source()
    preimage = funding.payment_secrets.get(payment["payment_hash"])
    assert preimage is not None, "FakeWallet did not record a preimage"
    await settlement.confirm_settlement(order_id=order["id"])
    order = await _fresh_order_row(env, order["id"])
    assert order["state"] == "confirmed"
    ext_id = _external_id(env, order)

    async with _relay_env(env, monkeypatch, mid, buyer_label="buyer-rcpt-1"):
        wrap, _ = await _generic_wrap(
            "buyer-rcpt-1", mpk, kind=17, content="paid!",
            tags=[
                ["p", mpk], ["subject", "order-payment"],
                ["order", ext_id], ["amount", str(order["total_sat"])],
                ["payment", "lightning", bolt11, preimage],
            ],
        )
        await _pipeline(env, merchant, wrap)
        row = await _row_for_wrap(env, mid, wrap)
        assert row["processed_state"] == "processed"
    order = await _fresh_order_row(env, order["id"])
    assert order["receipt_verified"]  # cosmetic flag only
    assert order["state"] == "confirmed"  # settlement untouched
    async with env["ext_module"].db.connect() as conn:
        ev = await conn.fetchone(
            "SELECT * FROM infinitemarkets.order_events"
            " WHERE order_id = :o AND detail_json LIKE '%nip17-receipt%'",
            {"o": order["id"]},
        )
    assert ev is not None


async def test_kind17_bad_preimage_no_verify(runtime_env, monkeypatch):
    """Wrong preimage / mismatched bolt11 never verifies — audit row
    still lands (buyer-claimed amount recorded for dispute display)."""
    env = runtime_env
    merchant = await _merchant(env)
    mid, mpk = merchant["id"], merchant["pubkey"]
    order, _r = await _gamma_order(
        env, monkeypatch, merchant, "buyer-rcpt-2"
    )
    payment = await _payment_row(env, order["id"])
    bolt11 = _dec_bolt11(order, payment)
    ext_id = _external_id(env, order)

    async with _relay_env(env, monkeypatch, mid, buyer_label="buyer-rcpt-2"):
        wrap, _ = await _generic_wrap(
            "buyer-rcpt-2", mpk, kind=17, content="",
            tags=[
                ["p", mpk], ["subject", "order-payment"],
                ["order", ext_id], ["amount", "99999"],
                ["payment", "lightning", bolt11, "ff" * 32],
            ],
        )
        await _pipeline(env, merchant, wrap)
        row = await _row_for_wrap(env, mid, wrap)
        assert row["processed_state"] == "processed"
    order = await _fresh_order_row(env, order["id"])
    assert not order["receipt_verified"]
    async with env["ext_module"].db.connect() as conn:
        ev = await conn.fetchone(
            "SELECT detail_json FROM infinitemarkets.order_events"
            " WHERE order_id = :o AND detail_json LIKE '%nip17-receipt%'",
            {"o": order["id"]},
        )
    assert "buyer_claimed_amount_sat" in (ev["detail_json"] or "")


async def test_kind14_threads_order_when_sender_matches(
    runtime_env, monkeypatch
):
    """kind-14 subject=<external_id> threads ONLY when the sender hash
    matches orders.buyer_pubkey_hash; a stranger's same-subject DM lands
    in Unknown without revealing the order exists."""
    env = runtime_env
    merchant = await _merchant(env)
    mid, mpk = merchant["id"], merchant["pubkey"]
    order, _r = await _gamma_order(
        env, monkeypatch, merchant, "buyer-dm-2"
    )
    ext_id = _external_id(env, order)

    async with _relay_env(env, monkeypatch, mid, buyer_label="buyer-dm-2"):
        wrap, rumor = await _generic_wrap(
            "buyer-dm-2", mpk, kind=14, content="about my order",
            tags=[["p", mpk], ["subject", ext_id]],
        )
        await _pipeline(env, merchant, wrap)
        wrap2, rumor2 = await _generic_wrap(
            "stranger-2", mpk, kind=14, content="guessing orders",
            tags=[["p", mpk], ["subject", ext_id]],
        )
        from infinitemarkets.services import inbox

        ref = {"id": mid, "pubkey": mpk}
        await inbox.admit_event("wss://src.example", wrap2, ref)
        await inbox.drain_received()
        await inbox.process_pending()

    async with env["ext_module"].db.connect() as conn:
        msgs = [
            dict(r) for r in await conn.fetchall(
                "SELECT * FROM infinitemarkets.order_messages"
                " WHERE rumor_id IN (:a, :b)",
                {"a": rumor.id().to_hex(), "b": rumor2.id().to_hex()},
            )
        ]
    by_rumor = {m["rumor_id"]: m for m in msgs}
    threaded = by_rumor[rumor.id().to_hex()]
    stranger = by_rumor[rumor2.id().to_hex()]
    assert threaded["order_id"] == order["id"]
    assert threaded["conversation_id"] == f"order:{order['id']}"
    assert stranger["order_id"] is None
    assert stranger["conversation_id"].startswith("unknown:")


async def test_dm_rate_cap(runtime_env, monkeypatch):
    """§15: the 21st DM from one inner buyer in an hour rejects."""
    env = runtime_env
    merchant = await _merchant(env)
    mid, mpk = merchant["id"], merchant["pubkey"]

    async with _relay_env(env, monkeypatch, mid):
        from infinitemarkets.services import inbox

        ref = {"id": mid, "pubkey": mpk}
        for i in range(21):
            wrap, _r = await _generic_wrap(
                "buyer-flood", mpk, kind=14, content=f"msg{i}",
                tags=[["p", mpk]],
            )
            await inbox.admit_event("wss://src.example", wrap, ref)
        await inbox.drain_received()
        await inbox.process_pending()
        rows = await _inbox_rows(env, mid)
        dms = [r for r in rows if r["kind"] == 14 and
               r["processed_state"] in ("processed", "rejected")]
        rejected = [r for r in dms if r["processed_state"] == "rejected"]
        assert len(rejected) == 1
        assert rejected[0]["reject_reason"] == "dm-rate-limited"


async def test_admin_compose_dm_dual_copy(runtime_env, monkeypatch):
    """compose_dm enqueues a kind-14 order_msg + an 'out'
    order_messages row on the unknown:<counterparty> conversation."""
    env = runtime_env
    merchant = await _merchant(env)
    mid = merchant["id"]
    from infinitemarkets.services import order_messages

    recipient = _buyer_keys("buyer-comp").public_key().to_hex()
    result = await order_messages.compose_dm(
        mid, recipient_pubkey=recipient, content="hello buyer",
    )
    assert result["queued"] is True
    assert result["conversation_id"].startswith("unknown:")
    msgs = await _msg_rows(env)
    out = [m for m in msgs if m["direction"] == "out" and
           m["conversation_id"] == result["conversation_id"]]
    assert len(out) == 1
    assert out[0]["semantic_kind"] == "dm"
    intents = [
        r for r in await _outbox_rows(env, mid)
        if r["aggregate_type"] == "order_msg"
        and r["event_kind"] == 14
    ]
    assert len(intents) == 1
    assert intents[0]["aggregate_revision"] == 0


async def test_reply_dm_resolves_unknown_counterparty(
    runtime_env, monkeypatch
):
    """reply_dm on an unknown: conversation reuses the stored
    participant pubkey — the merchant only needs the conversation id."""
    env = runtime_env
    merchant = await _merchant(env)
    mid, mpk = merchant["id"], merchant["pubkey"]
    from infinitemarkets.services import order_messages

    async with _relay_env(env, monkeypatch, mid):
        wrap, _r = await _generic_wrap(
            "buyer-reply", mpk, kind=14, content="question?",
            tags=[["p", mpk]],
        )
        await _pipeline(env, merchant, wrap)
    msgs = await _msg_rows(env)
    inbound = [m for m in msgs if m["direction"] == "in" and
               m["conversation_id"].startswith("unknown:")]
    assert inbound
    conv = inbound[0]["conversation_id"]
    result = await order_messages.reply_dm(
        mid, conversation_id=conv, content="answer!",
    )
    assert result["queued"] is True
    assert result["conversation_id"] == conv


async def test_order_msg_revision0_never_supersedes(runtime_env, monkeypatch):
    """Multiple order_msg intents per order stay live at revision 0 —
    the supersession UPDATE only touches aggregate_revision < 0."""
    env = runtime_env
    merchant = await _merchant(env)
    mid = merchant["id"]
    order, _r = await _gamma_order(
        env, monkeypatch, merchant, "buyer-rev0"
    )
    from infinitemarkets.db import DomainTransaction
    from infinitemarkets.services import order_messages

    async with DomainTransaction() as tx:
        row = await tx.fetch_one(
            "SELECT * FROM orders WHERE id = :i", {"i": order["id"]}
        )
        await order_messages.enqueue_status(tx, dict(row), "confirmed")
        await order_messages.enqueue_status(tx, dict(row), "processing")
    intents = [
        r for r in await _outbox_rows(env, mid)
        if r["aggregate_type"] == "order_msg"
        and r["aggregate_id"].startswith(order["id"] + ":")
    ]
    assert all(r["state"] == "pending" for r in intents)
    assert len(intents) >= 3  # payment-request + two status intents
