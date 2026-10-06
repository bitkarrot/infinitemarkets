"""Gamma NIP-17 outbox — dual-copy order_msg publication (GAM-03).

Every outbound merchant rumor produces TWO independently wrapped copies
per attempt: the recipient copy rides ONLY the buyer's declared
kind-10050 relays, the sender copy rides ONLY the merchant's own inbox
relays — never a public relay, never the source relay. ``published``
requires ≥1 durable positive OK in EACH copy class; one accepted class
lands ``partially_published`` and retries only the missing class; the
§9.3 no-route policy parks unroutable buyers at 15-min cadence for 48h.
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


# --- fixtures / helpers (shared shape with test_nip17_inbox) --------------------


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
            "display_name": "outbox shop",
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
    from nostr_sdk import EventBuilder, Kind, NostrSigner, Tag

    keys = _buyer_keys(buyer_label)
    event = await (
        EventBuilder(Kind(10050), "")
        .tags([Tag.parse(["relay", relay_url])])
        .sign(NostrSigner.keys(keys))
    )
    return json.loads(event.as_json())


async def _order_wrap(buyer_label, merchant_pubkey, *, order_id, items,
                      amount=0, extra_tags=None):
    from nostr_sdk import PublicKey

    from harness import sdk

    buyer = _buyer_keys(buyer_label)
    recipient = PublicKey.parse(merchant_pubkey)
    rumor = sdk.build_order_rumor(
        buyer, recipient, order_external_id=order_id, amount_sat=amount,
        items=[(f"30402:{merchant_pubkey}:{d}", q) for d, q in items],
        created_at=int(time.time()), extra_tags=extra_tags,
    )
    seal = await sdk.seal_rumor(buyer, recipient, rumor)
    return sdk.wrap_seal(recipient, seal), rumor


async def _pipeline(env: dict, merchant: dict, wrap):
    """admit -> drain -> dispatch -> publish tick for one order wrap."""
    from infinitemarkets.services import inbox

    ref = {"id": merchant["id"], "pubkey": merchant["pubkey"]}
    admitted = await inbox.admit_event("wss://source.example", wrap, ref)
    assert admitted == "received"
    await inbox.drain_received()
    await inbox.process_pending()
    return admitted


async def _inbox_row_for_wrap(env: dict, mid: str, wrap) -> dict | None:
    outer_id = wrap.id().to_hex()
    async with env["ext_module"].db.connect() as conn:
        row = await conn.fetchone(
            "SELECT * FROM infinitemarkets.inbox_events"
            " WHERE merchant_id = :m AND outer_event_id = :o",
            {"m": mid, "o": outer_id},
        )
    return dict(row) if row else None


async def _outbox_rows(env: dict, mid: str, aggregate_type="order_msg",
                       aggregate_prefix: str | None = None):
    async with env["ext_module"].db.connect() as conn:
        if aggregate_prefix is not None:
            rows = await conn.fetchall(
                "SELECT * FROM infinitemarkets.outbox_events"
                " WHERE merchant_id = :m AND aggregate_type = :a"
                " AND aggregate_id LIKE :p",
                {"m": mid, "a": aggregate_type,
                 "p": f"{aggregate_prefix}%"},
            )
        else:
            rows = await conn.fetchall(
                "SELECT * FROM infinitemarkets.outbox_events"
                " WHERE merchant_id = :m AND aggregate_type = :a",
                {"m": mid, "a": aggregate_type},
            )
    return [dict(r) for r in rows]


async def _publications(env: dict, intent_id: str):
    async with env["ext_module"].db.connect() as conn:
        rows = await conn.fetchall(
            "SELECT * FROM infinitemarkets.relay_publications"
            " WHERE outbox_event_id = :i",
            {"i": intent_id},
        )
    return [dict(r) for r in rows]


async def _order_for_rumor(env: dict, mid: str, rumor_id: str) -> dict:
    async with env["ext_module"].db.connect() as conn:
        order = await conn.fetchone(
            "SELECT * FROM infinitemarkets.orders"
            " WHERE merchant_id = :m AND source_event_id = :r",
            {"m": mid, "r": rumor_id},
        )
    assert order is not None
    return dict(order)


def _wrap_events(relay) -> list[dict]:
    return [
        e["event"] for e in relay.received_events
        if isinstance(e.get("event"), dict)
        and e["event"].get("kind") == 1059
    ]


async def _unwrap_relay_wrap(env: dict, merchant_id: str, wrap_json: dict,
                             *, expected_rumor_recipient=None):
    from infinitemarkets import keystore as keystore_mod
    from infinitemarkets.settings import ext_settings

    ks = keystore_mod.key_store(ext_settings())
    return await ks.nip17_unwrap(
        merchant_id, json.dumps(wrap_json),
        expected_rumor_recipient=expected_rumor_recipient,
    )


# --- tests --------------------------------------------------------------------


async def test_dual_copy_publication_runtime(runtime_env, monkeypatch):
    """One order_msg attempt wraps the SAME rumor into two independent
    copies: recipient -> buyer relay only, sender -> merchant relay
    only; relay_publications carries both classes and 'published' lands
    only on dual acceptance."""
    from harness import relay as relay_module
    from infinitemarkets.services import outbox

    env = runtime_env
    merchant = await _merchant(env)
    mid, mpk = merchant["id"], merchant["pubkey"]
    buyer_label = "buyer-pub-1"
    buyer_hex = _buyer_keys(buyer_label).public_key().to_hex()

    buyer_relay = relay_module.LocalRelay(
        mode=relay_module.RelayMode.ACCEPTING
    )
    await buyer_relay.start()
    try:
        canned = [await _buyer_10050_event(buyer_label, buyer_relay.url)]
        public = relay_module.LocalRelay(
            mode=relay_module.RelayMode.ACCEPTING, canned_events=canned
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

            product = await env["make_product"](uuid.uuid4().hex[:8], 10)
            ext_id = f"pub-{uuid.uuid4().hex[:12]}"
            wrap, rumor = await _order_wrap(
                buyer_label, mpk, order_id=ext_id,
                items=[(product["d_tag"], 1)], amount=500,
            )
            await _pipeline(env, merchant, wrap)

            order = await _order_for_rumor(env, mid, rumor.id().to_hex())
            intents = await _outbox_rows(
                env, mid, aggregate_prefix=order["id"]
            )
            assert len(intents) == 1
            intent = intents[0]

            outcome = await outbox.worker_tick("test-worker")
            assert outcome["claimed"] >= 1

            intent_after = await _outbox_rows(
                env, mid, aggregate_prefix=order["id"]
            )
            assert intent_after[0]["state"] == "published"

            pubs = await _publications(env, intent["id"])
            copies = {p["delivery_copy"] for p in pubs}
            assert copies == {"recipient", "sender"}
            rec_pubs = [p for p in pubs if p["delivery_copy"] == "recipient"]
            sen_pubs = [p for p in pubs if p["delivery_copy"] == "sender"]
            assert all(p["result"] == "accepted" for p in pubs)
            assert {p["relay_url"] for p in rec_pubs} == {buyer_relay.url}
            assert {p["relay_url"] for p in sen_pubs} == {
                merchant_relay.url
            }
            # No cross-routing: each wrap reached only its own relay.
            assert len(_wrap_events(buyer_relay)) == 1
            assert len(_wrap_events(merchant_relay)) == 1
            buyer_wrap = _wrap_events(buyer_relay)[0]
            sender_wrap = _wrap_events(merchant_relay)[0]
            assert buyer_wrap["id"] != sender_wrap["id"]
            # Outer p tags: buyer wrap -> buyer, sender wrap -> merchant.
            buyer_p = [
                t[1] for t in buyer_wrap["tags"] if t[0] == "p"
            ]
            sender_p = [
                t[1] for t in sender_wrap["tags"] if t[0] == "p"
            ]
            assert buyer_p == [buyer_hex]
            assert sender_p == [mpk]

            # Inner rumor is byte-identical (same canonical rumor id):
            # unwrap the buyer copy with the BUYER keys and the sender
            # copy through the merchant keystore (p names the buyer).
            from nostr_sdk import Event, PublicKey

            from harness import sdk

            buyer_event = Event.from_json(json.dumps(buyer_wrap))
            _seal, inner_rumor = await sdk.unwrap_gift_wrap(
                _buyer_keys(buyer_label), buyer_event,
                expected_rumor_recipient=PublicKey.parse(buyer_hex),
            )
            out_sender = await _unwrap_relay_wrap(
                env, mid, sender_wrap,
                expected_rumor_recipient=PublicKey.parse(buyer_hex),
            )
            assert (
                inner_rumor.id().to_hex() == out_sender["rumor_id"]
            )
            assert inner_rumor.author().to_hex() == mpk
        finally:
            await public.stop()
            await merchant_relay.stop()
    finally:
        await buyer_relay.stop()


async def test_partial_acceptance_retries_missing_class_only(
    runtime_env, monkeypatch
):
    """A REJECTING buyer relay leaves 'partially_published': the sender
    class is proven once and never resent; the next attempt sends ONLY
    a fresh wrap to the buyer relay — same rumor id, fresh outer ids."""
    from harness import relay as relay_module
    from infinitemarkets.services import outbox

    env = runtime_env
    merchant = await _merchant(env)
    mid, mpk = merchant["id"], merchant["pubkey"]
    buyer_label = "buyer-pub-2"
    buyer_hex = _buyer_keys(buyer_label).public_key().to_hex()

    buyer_relay = relay_module.LocalRelay(
        mode=relay_module.RelayMode.REJECTING
    )
    await buyer_relay.start()
    try:
        canned = [await _buyer_10050_event(buyer_label, buyer_relay.url)]
        public = relay_module.LocalRelay(
            mode=relay_module.RelayMode.ACCEPTING, canned_events=canned
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

            product = await env["make_product"](uuid.uuid4().hex[:8], 10)
            wrap, rumor = await _order_wrap(
                buyer_label, mpk, order_id=f"pp-{uuid.uuid4().hex[:12]}",
                items=[(product["d_tag"], 1)], amount=500,
            )
            await _pipeline(env, merchant, wrap)
            order = await _order_for_rumor(env, mid, rumor.id().to_hex())
            intents = await _outbox_rows(
                env, mid, aggregate_prefix=order["id"]
            )
            intent = intents[0]

            await outbox.worker_tick("test-worker")
            intent_after = await _outbox_rows(
                env, mid, aggregate_prefix=order["id"]
            )
            assert intent_after[0]["state"] == "partially_published"
            pubs = await _publications(env, intent["id"])
            assert {
                (p["delivery_copy"], p["result"]) for p in pubs
            } == {("recipient", "rejected"), ("sender", "accepted")}
            assert len(_wrap_events(buyer_relay)) == 1
            assert len(_wrap_events(merchant_relay)) == 1
            first_outer = _wrap_events(buyer_relay)[0]["id"]

            # Flip the buyer relay to accepting — the retry carries a
            # fresh outer id (new seal/wrapper) but the SAME rumor.
            buyer_relay.mode = relay_module.RelayMode.ACCEPTING
            async with env["ext_module"].db.connect() as conn:
                await conn.execute(
                    "UPDATE infinitemarkets.outbox_events"
                    " SET next_attempt_at = 0 WHERE id = :i",
                    {"i": intent["id"]},
                )
            await outbox.worker_tick("test-worker")
            intent_after = await _outbox_rows(
                env, mid, aggregate_prefix=order["id"]
            )
            assert intent_after[0]["state"] == "published"
            assert len(_wrap_events(buyer_relay)) == 2
            # The sender class was never resent.
            assert len(_wrap_events(merchant_relay)) == 1
            second = _wrap_events(buyer_relay)[1]
            assert second["id"] != first_outer
            from nostr_sdk import Event, PublicKey

            from harness import sdk

            _seal, inner = await sdk.unwrap_gift_wrap(
                _buyer_keys(buyer_label),
                Event.from_json(json.dumps(second)),
                expected_rumor_recipient=PublicKey.parse(buyer_hex),
            )
            assert inner.id().to_hex()
            # Same rumor id across attempts — fresh seal/wrap outer ids.
            _s, first_inner = await sdk.unwrap_gift_wrap(
                _buyer_keys(buyer_label),
                Event.from_json(
                    json.dumps(_wrap_events(buyer_relay)[0])
                ),
                expected_rumor_recipient=PublicKey.parse(buyer_hex),
            )
            assert inner.id().to_hex() == first_inner.id().to_hex()
        finally:
            await public.stop()
            await merchant_relay.stop()
    finally:
        await buyer_relay.stop()


async def test_no_buyer_10050_no_route_policy(runtime_env, monkeypatch):
    """Zero valid buyer routes -> pending/'no_inbox_relays'; the intent
    re-attempts on the 15-min cadence and fails 48h after enqueue."""
    from harness import relay as relay_module
    from infinitemarkets.services import outbox

    env = runtime_env
    merchant = await _merchant(env)
    mid, mpk = merchant["id"], merchant["pubkey"]

    public = relay_module.LocalRelay(
        mode=relay_module.RelayMode.ACCEPTING, canned_events=[]
    )
    merchant_relay = relay_module.LocalRelay(
        mode=relay_module.RelayMode.ACCEPTING
    )
    await public.start()
    await merchant_relay.start()
    try:
        monkeypatch.setenv("INFINITEMARKETS_RELAY_IO", "on")
        monkeypatch.setenv("INFINITEMARKETS_ALLOW_INSECURE_RELAYS", "1")
        await _set_relays(env, mid, [
            {"relay_url": public.url, "direction": "public"},
            {"relay_url": merchant_relay.url, "direction": "inbox"},
        ])
        from infinitemarkets.services.transport import transport

        await transport().start([])

        product = await env["make_product"](uuid.uuid4().hex[:8], 10)
        wrap, rumor = await _order_wrap(
            "buyer-noroute-2", mpk, order_id=f"nr2-{uuid.uuid4().hex[:12]}",
            items=[(product["d_tag"], 1)], amount=500,
        )
        await _pipeline(env, merchant, wrap)
        # Intake rejects (no-inbox-relays); the rejected-reply intent
        # parks on the same §9.3 policy.
        intents = await _outbox_rows(
            env, mid, aggregate_prefix="rejected:"
        )
        assert len(intents) == 1
        intent = intents[0]

        await outbox.worker_tick("test-worker")
        intent_after = await _outbox_rows(
            env, mid, aggregate_prefix="rejected:"
        )
        assert intent_after[0]["state"] == "pending"
        assert intent_after[0]["last_error"] == "no_inbox_relays"
        # Next attempt lands ~15min out — not the generic backoff.
        assert (
            intent_after[0]["next_attempt_at"]
            >= intent_after[0]["updated_at"] + 14 * 60
        )
        # No wraps were sent anywhere for the recipient class.
        assert _wrap_events(public) == []

        # 48h after first enqueue -> failed.
        async with env["ext_module"].db.connect() as conn:
            await conn.execute(
                "UPDATE infinitemarkets.outbox_events"
                " SET created_at = :c, next_attempt_at = 0"
                " WHERE id = :i",
                {
                    "c": int(time.time()) - 49 * 3600,
                    "i": intent["id"],
                },
            )
        await outbox.worker_tick("test-worker")
        intent_after = await _outbox_rows(
            env, mid, aggregate_prefix="rejected:"
        )
        assert intent_after[0]["state"] == "failed"
        assert intent_after[0]["last_error"] == "no_inbox_relays"
    finally:
        await public.stop()
        await merchant_relay.stop()
