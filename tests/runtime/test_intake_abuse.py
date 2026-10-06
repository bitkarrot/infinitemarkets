"""Gamma hostile intake + crash-safety drills — plan 03-02 task 3 (GAM-04).

Admission abuse ordering (bound -> kind -> p-tag -> verify -> blocklist/
caps -> insert), per-author flood caps that drop BEFORE expensive
validation, muted-author bounded growth, crash-between-checkpoint resume
idempotence, and retention erasure — all on the real host boot with
workers cancelled (every stage driven explicitly).
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
            "display_name": "abuse shop",
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
        json={"name": "abuse", "default_currency": "SAT"},
        headers=await cookie(),
    )
    cid = resp.json()["id"]

    async def product(title, stock, fmt="digital", price=500) -> dict:
        resp = await client.post(
            f"{API}/products",
            json={
                "catalog_id": cid, "title": title, "amount_minor": price,
                "currency": "SAT", "visibility": "on-sale",
                "stock_on_hand": stock, "format": fmt,
            },
            headers=await cookie(),
        )
        assert resp.status_code == 201, resp.text
        return resp.json()

    runtime_env.update(
        {
            "merchant_id": mid, "catalog_id": cid,
            "make_product": product, "cookie": cookie,
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
        return dict(await conn.fetchone(
            "SELECT * FROM infinitemarkets.merchants WHERE id = :m",
            {"m": env["merchant_id"]},
        ))


def _ref(merchant: dict) -> dict:
    return {"id": merchant["id"], "pubkey": merchant["pubkey"]}


def _buyer_keys(label: str):
    from harness import sdk

    return sdk.fixed_test_keys(label)


async def _order_wrap(buyer_label, mpk, *, order_id, items,
                      amount=0, extra_tags=None):
    from nostr_sdk import PublicKey

    from harness import sdk

    buyer = _buyer_keys(buyer_label)
    recipient = PublicKey.parse(mpk)
    rumor = sdk.build_order_rumor(
        buyer, recipient, order_external_id=order_id, amount_sat=amount,
        items=[(f"30402:{mpk}:{d}", q) for d, q in items],
        created_at=int(time.time()), extra_tags=extra_tags,
    )
    seal = await sdk.seal_rumor(buyer, recipient, rumor)
    return sdk.wrap_seal(recipient, seal), rumor


async def _wrap_fixed_outer(author_keys, merchant_pubkey: str, rumor,
                            outer_keys):
    """Gift-wrap ``rumor`` with a FIXED outer key — a non-compliant
    flooder reusing its ephemeral key exercises the admission caps."""
    from nostr_sdk import (
        EventBuilder,
        Kind,
        Nip44Version,
        NostrSigner,
        PublicKey,
        Tag,
        Timestamp,
        nip44_encrypt,
    )

    from harness import sdk

    recipient = PublicKey.parse(merchant_pubkey)
    seal = await sdk.seal_rumor(author_keys, recipient, rumor)
    content = nip44_encrypt(
        outer_keys.secret_key(), recipient, seal.as_json(),
        Nip44Version.V2,
    )
    import random

    return await (
        EventBuilder(Kind(1059), content)
        .custom_created_at(
            Timestamp.from_secs(int(time.time()) - random.randint(10, 200))
        )
        .tags([Tag.parse(["p", merchant_pubkey])])
        .sign(NostrSigner.keys(outer_keys))
    )


async def _inbox_rows(env: dict, mid: str) -> list[dict]:
    async with env["ext_module"].db.connect() as conn:
        rows = await conn.fetchall(
            "SELECT * FROM infinitemarkets.inbox_events"
            " WHERE merchant_id = :m ORDER BY received_at",
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


async def _row_for_wrap(env: dict, mid: str, wrap) -> dict | None:
    rows = await _inbox_rows(env, mid)
    return next(
        (r for r in rows if r["outer_event_id"] == wrap.id().to_hex()),
        None,
    )


# --- admission abuse ------------------------------------------------------------


async def test_admission_bound_kind_ptag_sig_order(runtime_env, monkeypatch):
    """Oversize/wrong-kind/multi-p/bad-sig all drop BEFORE any row or
    decrypt work — pre-insert rejections never write inbox rows."""
    from infinitemarkets.services import inbox

    env = runtime_env
    merchant = await _merchant(env)
    mid, mpk = merchant["id"], merchant["pubkey"]
    before = len(await _inbox_rows(env, mid))

    # 1. Oversized raw event.
    giant = json.dumps({
        "id": "aa" * 32, "pubkey": "bb" * 32, "created_at": 1,
        "kind": 1059, "tags": [["p", mpk]], "content": "A" * 40000,
        "sig": "cc" * 32,
    })
    assert await inbox.admit_event("wss://r.example", giant, _ref(merchant)) \
        == "rejected"

    # 2. Wrong-kind.
    from nostr_sdk import EventBuilder, Keys, Kind, NostrSigner, Tag

    evil = Keys.generate()
    wrong = await (
        EventBuilder(Kind(1), "x")
        .tags([Tag.parse(["p", mpk])])
        .sign(NostrSigner.keys(evil))
    )
    assert await inbox.admit_event(
        "wss://r.example", wrong, _ref(merchant)
    ) == "rejected"

    # 3. >1 p tag.
    multi = await (
        EventBuilder(Kind(1059), "x")
        .tags([Tag.parse(["p", mpk]), Tag.parse(["p", mpk])])
        .sign(NostrSigner.keys(evil))
    )
    assert await inbox.admit_event(
        "wss://r.example", multi, _ref(merchant)
    ) == "rejected"

    # 4. Bad signature — valid shape, invalid sig bytes.
    tampered = json.loads(
        (
            await (
                EventBuilder(Kind(1059), "c")
                .tags([Tag.parse(["p", mpk])])
                .sign(NostrSigner.keys(evil))
            )
        ).as_json()
    )
    tampered["sig"] = "ab" * 64  # well-formed but wrong
    assert await inbox.admit_event(
        "wss://r.example", json.dumps(tampered), _ref(merchant)
    ) == "rejected"

    # 5. Malformed JSON.
    assert await inbox.admit_event(
        "wss://r.example", "{not json", _ref(merchant)
    ) == "rejected"

    assert len(await _inbox_rows(env, mid)) == before


async def test_wrap_relay_flood_bucket(
    runtime_env, monkeypatch, frozen_inbox_clock
):
    """§15 wraps-per-(merchant,relay) cap: excess wraps drop at admission
    even when each carries a distinct outer author (the bucket keys on
    relay+merchant, not identity)."""
    from infinitemarkets.services import inbox

    env = runtime_env
    merchant = await _merchant(env)
    mpk = merchant["pubkey"]
    monkeypatch.setattr(inbox, "RATE_WRAP_RELAY_PER_MINUTE", 3)
    relay_url = f"wss://flood-{uuid.uuid4().hex[:8]}.example"
    results = []
    for i in range(6):
        wrap, _rumor = await _order_wrap(
            f"flood-r-{i}-{uuid.uuid4().hex[:6]}", mpk,
            order_id=f"fr-{uuid.uuid4().hex[:8]}", items=[], amount=0,
        )
        results.append(
            await inbox.admit_event(relay_url, wrap, _ref(merchant))
        )
    assert results.count("received") == 3
    assert results.count("rejected") == 3
    # Settle the admitted rows so they cannot pollute the unwrap-count
    # delta measured by the per-author cap test below.
    await inbox.drain_received()
    await inbox.process_pending()


async def test_per_author_flood_drop_before_validation(
    runtime_env, monkeypatch, frozen_inbox_clock
):
    """A fixed outer-key flood hits the per-author admission bucket —
    wraps beyond the cap never reach insert or unwrap."""
    from infinitemarkets.services import inbox

    env = runtime_env
    merchant = await _merchant(env)
    mid, mpk = merchant["id"], merchant["pubkey"]
    cap = 3
    monkeypatch.setenv("INFINITEMARKETS_INBOX_AUTHOR_CAP", str(cap))

    from nostr_sdk import PublicKey

    from harness import sdk

    author = _buyer_keys("flood-author")
    outer = _buyer_keys("flood-outer-fixed")
    recipient = PublicKey.parse(mpk)
    before = len(await _inbox_rows(env, mid))
    unwrap_calls_before = None
    from infinitemarkets.services import metrics

    unwrap_calls_before = metrics.get("inbox.drain.unwrap")
    admitted = []
    for i in range(cap + 4):
        rumor = sdk.build_order_rumor(
            author, recipient,
            order_external_id=f"cap-{i}-{uuid.uuid4().hex[:8]}",
            amount_sat=500,
            items=[],
            created_at=int(time.time()),
        )
        wrap = await _wrap_fixed_outer(
            author, mpk, rumor, outer
        )
        admitted.append(
            await inbox.admit_event("wss://flood.example", wrap, _ref(merchant))
        )
    rows = await _inbox_rows(env, mid)
    # Exactly `cap` wraps landed rows — the rest dropped at admission.
    assert len(rows) - before == cap
    assert admitted.count("received") == cap
    assert admitted.count("rejected") == 4

    # Drain marks them rejected for content-shape reasons — the unwrap
    # call count is bounded by cap, not by flood size.
    await inbox.drain_received()
    unwrap_delta = metrics.get("inbox.drain.unwrap") or 0
    if unwrap_calls_before is None:
        unwrap_calls_before = 0
    assert unwrap_delta - unwrap_calls_before <= cap


async def test_muted_author_bounded_growth(runtime_env, monkeypatch):
    """Muted inner author: the FIRST wrap per burst leaves an auditable
    'author-blocked' rejected row; subsequent wraps delete the row —
    no inbox_events growth after the first drop."""
    from infinitemarkets import crypto
    from infinitemarkets.services import inbox
    from infinitemarkets.settings import ext_settings

    env = runtime_env
    merchant = await _merchant(env)
    mid, mpk = merchant["id"], merchant["pubkey"]

    # Mute the author's hash directly (same row the mute endpoint writes).
    author_pub = _buyer_keys("muted-1").public_key().to_hex()
    author_hash = crypto.hmac_index(
        ext_settings().privacy_key, crypto.PURPOSE_BUYER_PUBKEY,
        mid, crypto.normalize(author_pub),
    )
    async with env["ext_module"].db.connect() as conn:
        await conn.execute(
            "INSERT INTO infinitemarkets.inbox_blocklist"
            " (id, merchant_id, author_hash, created_at)"
            " VALUES (:i, :m, :h, 0)",
            {"i": uuid.uuid4().hex, "m": mid, "h": author_hash},
        )

    before = len(await _inbox_rows(env, mid))
    for i in range(3):
        wrap, _r = await _order_wrap(
            "muted-1", mpk, order_id=f"mute-{i}",
            items=[], extra_tags=None,
        )
        await inbox.admit_event("wss://r.example", wrap, _ref(merchant))
        await inbox.drain_received()
    rows = await _inbox_rows(env, mid)
    # Only the first wrap keeps an auditable rejected row — the rest
    # were deleted pre-dispatch (bounded growth).
    blocked = [
        r for r in rows if r["reject_reason"] == "author-blocked"
    ]
    assert len(blocked) == 1
    assert len(rows) - before == 1


async def test_process_pending_twice_no_duplicate_domain(
    runtime_env, monkeypatch
):
    """Kill-between-dispatch-and-mark: re-running process_pending on a
    'validated' row replays the SAME order intake — one orders row
    thanks to the (merchant, buyer, external_id) unique index."""
    env = runtime_env
    merchant = await _merchant(env)
    mid, mpk = merchant["id"], merchant["pubkey"]
    product = await env["make_product"](uuid.uuid4().hex[:8], 10)
    ext_id = f"replay-{uuid.uuid4().hex[:12]}"

    from harness import relay as relay_module
    from infinitemarkets.services import inbox
    from infinitemarkets.services.transport import transport

    monkeypatch.setenv("INFINITEMARKETS_RELAY_IO", "on")
    monkeypatch.setenv("INFINITEMARKETS_ALLOW_INSECURE_RELAYS", "1")

    async with relay_module.LocalRelay(
        mode=relay_module.RelayMode.ACCEPTING
    ) as buyer_relay:
        from nostr_sdk import EventBuilder, Kind, NostrSigner, Tag

        keys = _buyer_keys("buyer-replay")
        e10050 = await (
            EventBuilder(Kind(10050), "")
            .tags([Tag.parse(["relay", buyer_relay.url])])
            .sign(NostrSigner.keys(keys))
        )
        async with relay_module.LocalRelay(
            mode=relay_module.RelayMode.ACCEPTING,
            canned_events=[json.loads(e10050.as_json())],
        ) as public, relay_module.LocalRelay(
            mode=relay_module.RelayMode.ACCEPTING
        ) as merchant_relay:
            await _set_relays_helper(env, mid, [
                {"relay_url": public.url, "direction": "public"},
                {"relay_url": merchant_relay.url, "direction": "inbox"},
            ])
            await transport().start([])

            wrap, rumor = await _order_wrap(
                "buyer-replay", mpk, order_id=ext_id,
                items=[(product["d_tag"], 1)], amount=500,
            )
            assert await inbox.admit_event(
                "wss://r.example", wrap, _ref(merchant)
            ) == "received"
            await inbox.drain_received()
            row = await _row_for_wrap(env, mid, wrap)
            assert row["processed_state"] == "validated"

            # Simulated crash AFTER the domain writes committed but
            # BEFORE the inbox mark: rewind the row to 'validated' and
            # replay — the intake path must dedupe via the
            # (merchant, buyer, external_id) unique index rather than
            # mint a second order or a second payment-request intent.
            await inbox.process_pending()
            order_count = len([
                o for o in await _orders(env, mid)
                if o["source_event_id"] == rumor.id().to_hex()
            ])
            assert order_count == 1
            intents_before = len([
                r for r in await _outbox_rows(env, mid)
                if r["aggregate_type"] == "order_msg"
            ])

            async with env["ext_module"].db.connect() as conn:
                await conn.execute(
                    "UPDATE infinitemarkets.inbox_events"
                    " SET processed_state = 'validated',"
                    " processed_at = NULL WHERE id = :i",
                    {"i": row["id"]},
                )
            report = await inbox.process_pending()
            assert report["processed"] == 1
            order_count = len([
                o for o in await _orders(env, mid)
                if o["source_event_id"] == rumor.id().to_hex()
            ])
            assert order_count == 1
            assert len([
                r for r in await _outbox_rows(env, mid)
                if r["aggregate_type"] == "order_msg"
            ]) == intents_before

            # Third pass — the row is terminal; nothing left to do.
            report = await inbox.process_pending()
            assert report["processed"] == 0
            order_count = len([
                o for o in await _orders(env, mid)
                if o["source_event_id"] == rumor.id().to_hex()
            ])
            assert order_count == 1


async def test_reconcile_resumes_inbox_rows(runtime_env, monkeypatch):
    """§8.7 crash-resume: rows parked at 'received'/'validated' across a
    kill are re-driven by settlement.reconcile's inbox-resume loop —
    each rumor produces exactly one order, and a second reconcile pass
    is a no-op."""
    from harness import relay as relay_module
    from infinitemarkets.services import inbox, settlement
    from infinitemarkets.services.transport import transport

    env = runtime_env
    merchant = await _merchant(env)
    mid, mpk = merchant["id"], merchant["pubkey"]
    monkeypatch.setenv("INFINITEMARKETS_RELAY_IO", "on")
    monkeypatch.setenv("INFINITEMARKETS_ALLOW_INSECURE_RELAYS", "1")
    product = await env["make_product"](uuid.uuid4().hex[:8], 10)
    buyer_label = "buyer-resume"

    async with relay_module.LocalRelay(
        mode=relay_module.RelayMode.ACCEPTING
    ) as buyer_relay:
        canned = [await _buyer_10050_event(buyer_label, buyer_relay.url)]
        async with relay_module.LocalRelay(
            mode=relay_module.RelayMode.ACCEPTING, canned_events=canned
        ) as public, relay_module.LocalRelay(
            mode=relay_module.RelayMode.ACCEPTING
        ) as merchant_relay:
            await _set_relays_helper(env, mid, [
                {"relay_url": public.url, "direction": "public"},
                {"relay_url": merchant_relay.url, "direction": "inbox"},
            ])
            await transport().start([])

            wrap_a, rumor_a = await _order_wrap(
                buyer_label, mpk, order_id=f"ra-{uuid.uuid4().hex[:12]}",
                items=[(product["d_tag"], 1)], amount=500,
            )
            assert await inbox.admit_event(
                "wss://r.example", wrap_a, _ref(merchant)
            ) == "received"
            # Kill point: wrap_a validates, then the process dies before
            # wrap_b is admitted and before either is dispatched —
            # the restart leaves one 'validated' and one 'received' row.
            await inbox.drain_received()
            wrap_b, rumor_b = await _order_wrap(
                buyer_label, mpk, order_id=f"rb-{uuid.uuid4().hex[:12]}",
                items=[(product["d_tag"], 1)], amount=500,
            )
            assert await inbox.admit_event(
                "wss://r.example", wrap_b, _ref(merchant)
            ) == "received"
            row_a = await _row_for_wrap(env, mid, wrap_a)
            row_b = await _row_for_wrap(env, mid, wrap_b)
            assert row_a["processed_state"] == "validated"
            assert row_b["processed_state"] == "received"

            # Restart: the §8.7 reconcile pass drives both parked states.
            await settlement.reconcile()
            row_a = await _row_for_wrap(env, mid, wrap_a)
            row_b = await _row_for_wrap(env, mid, wrap_b)
            assert row_a["processed_state"] == "processed"
            assert row_b["processed_state"] == "processed"
            for rumor in (rumor_a, rumor_b):
                assert len([
                    o for o in await _orders(env, mid)
                    if o["source_event_id"] == rumor.id().to_hex()
                ]) == 1

            # Second reconcile — idempotent, no duplicate domain writes.
            await settlement.reconcile()
            for rumor in (rumor_a, rumor_b):
                assert len([
                    o for o in await _orders(env, mid)
                    if o["source_event_id"] == rumor.id().to_hex()
                ]) == 1


async def test_same_rumor_two_relays_single_message(runtime_env, monkeypatch):
    """The SAME rumor arriving on two different relays as two wraps is
    one logical message — rumor-level dedupe leaves exactly one
    order_messages row (§8.5/GAM-04)."""
    from nostr_sdk import EventBuilder, Kind, PublicKey, Tag, Timestamp

    from harness import sdk
    from infinitemarkets.services import inbox

    env = runtime_env
    merchant = await _merchant(env)
    mid, mpk = merchant["id"], merchant["pubkey"]

    buyer = _buyer_keys("buyer-tworelay")
    recipient = PublicKey.parse(mpk)
    rumor = (
        EventBuilder(Kind(14), "same message")
        .custom_created_at(Timestamp.from_secs(int(time.time())))
        .tags([Tag.parse(["p", mpk])])
        .build(buyer.public_key())
    )
    wrap_a = sdk.wrap_seal(
        recipient, await sdk.seal_rumor(buyer, recipient, rumor)
    )
    wrap_b = sdk.wrap_seal(
        recipient, await sdk.seal_rumor(buyer, recipient, rumor)
    )
    assert wrap_a.id().to_hex() != wrap_b.id().to_hex()

    assert await inbox.admit_event(
        "wss://relay-a.example", wrap_a, _ref(merchant)
    ) == "received"
    assert await inbox.admit_event(
        "wss://relay-b.example", wrap_b, _ref(merchant)
    ) == "received"
    await inbox.drain_received()
    await inbox.process_pending()

    row_a = await _row_for_wrap(env, mid, wrap_a)
    row_b = await _row_for_wrap(env, mid, wrap_b)
    assert row_a["processed_state"] == "processed"
    assert row_b["processed_state"] == "duplicate"

    async with env["ext_module"].db.connect() as conn:
        msgs = await conn.fetchall(
            "SELECT * FROM infinitemarkets.order_messages"
            " WHERE rumor_id = :r",
            {"r": rumor.id().to_hex()},
        )
    assert len(msgs) == 1


async def test_no_route_refresh_and_48h_deadline(runtime_env, monkeypatch):
    """§9.3 no-route recovery: refresh_stale_peer_relays re-resolves a
    buyer who publishes a kind-10050 mid-window (the parked intent then
    publishes on the next tick) and fails intents 48h after first
    enqueue."""
    from harness import relay as relay_module
    from infinitemarkets.services import inbox, outbox, peer_relays
    from infinitemarkets.services.transport import transport

    env = runtime_env
    merchant = await _merchant(env)
    mid, mpk = merchant["id"], merchant["pubkey"]
    monkeypatch.setenv("INFINITEMARKETS_RELAY_IO", "on")
    monkeypatch.setenv("INFINITEMARKETS_ALLOW_INSECURE_RELAYS", "1")

    buyer_label = f"buyer-late-{uuid.uuid4().hex[:8]}"
    stale_label = f"buyer-gone-{uuid.uuid4().hex[:8]}"
    async with relay_module.LocalRelay(
        mode=relay_module.RelayMode.ACCEPTING
    ) as buyer_relay, relay_module.LocalRelay(
        mode=relay_module.RelayMode.ACCEPTING, canned_events=[]
    ) as public, relay_module.LocalRelay(
        mode=relay_module.RelayMode.ACCEPTING
    ) as merchant_relay:
        await _set_relays_helper(env, mid, [
            {"relay_url": public.url, "direction": "public"},
            {"relay_url": merchant_relay.url, "direction": "inbox"},
        ])
        await transport().start([])

        async def _reply_intent_for(wrap) -> dict:
            """The rejected-reply order_msg intent for one inbox row —
            aggregate_id is ``rejected:<inbox_event_id>``."""
            row = await _row_for_wrap(env, mid, wrap)
            assert row["processed_state"] == "rejected"
            async with env["ext_module"].db.connect() as conn:
                intent = await conn.fetchone(
                    "SELECT * FROM infinitemarkets.outbox_events"
                    " WHERE aggregate_type = 'order_msg'"
                    " AND aggregate_id = :a",
                    {"a": f"rejected:{row['id']}"},
                )
            assert intent is not None
            return dict(intent)

        # First: the buyer has no 10050 anywhere — intake rejects and the
        # reply intent parks no-route.
        wrap1, _r1 = await _order_wrap(
            buyer_label, mpk, order_id="bad id!!", items=[], amount=0,
        )
        assert await inbox.admit_event(
            "wss://src.example", wrap1, _ref(merchant)
        ) == "received"
        await inbox.drain_received()
        await inbox.process_pending()
        target = await _reply_intent_for(wrap1)
        await outbox.worker_tick("abuse-worker")
        intent = dict(
            next(
                r for r in await _outbox_rows(env, mid)
                if r["id"] == target["id"]
            )
        )
        assert intent["state"] == "pending"
        assert intent["last_error"] == "no_inbox_relays"

        # The buyer publishes a kind-10050 mid-window: the refresh sweep
        # force re-resolves (cache-bust) so the next attempt has routes.
        public.canned_events.append(
            await _buyer_10050_event(buyer_label, buyer_relay.url)
        )
        stats = await peer_relays.refresh_stale_peer_relays()
        assert stats["no_route_refreshed"] >= 1
        async with env["ext_module"].db.connect() as conn:
            cached = await conn.fetchall(
                "SELECT relay_url FROM infinitemarkets.peer_relays"
                " WHERE merchant_id = :m AND relay_url = :u",
                {"m": mid, "u": buyer_relay.url},
            )
        assert cached, "refresh did not re-resolve the fresh 10050"

        # Next tick publishes the previously no-route intent — recipient
        # copy lands on the buyer relay, sender copy on the merchant relay.
        async with env["ext_module"].db.connect() as conn:
            await conn.execute(
                "UPDATE infinitemarkets.outbox_events"
                " SET next_attempt_at = 0 WHERE id = :i",
                {"i": target["id"]},
            )
        await outbox.worker_tick("abuse-worker")
        intent = dict(
            next(
                r for r in await _outbox_rows(env, mid)
                if r["id"] == target["id"]
            )
        )
        assert intent["state"] == "published"
        # The recipient copy is the only wrap the buyer relay ever saw;
        # other parked intents also publish sender copies to the shared
        # merchant inbox relay, so assert THAT copy via evidence rows.
        buyer_wraps = [
            e["event"] for e in buyer_relay.received_events
            if isinstance(e.get("event"), dict)
            and e["event"].get("kind") == 1059
        ]
        assert len(buyer_wraps) == 1
        async with env["ext_module"].db.connect() as conn:
            pubs = await conn.fetchall(
                "SELECT delivery_copy, result, relay_url"
                " FROM infinitemarkets.relay_publications"
                " WHERE outbox_event_id = :i",
                {"i": target["id"]},
            )
        assert {
            (p["delivery_copy"], p["result"]) for p in pubs
        } == {("recipient", "accepted"), ("sender", "accepted")}
        assert {p["relay_url"] for p in pubs} == {
            buyer_relay.url, merchant_relay.url
        }

        # The 48h deadline: an aged no-route intent fails terminally on
        # the refresh sweep (never a source/public-relay fallback).
        wrap2, _r2 = await _order_wrap(
            stale_label, mpk, order_id="worse id??", items=[], amount=0,
        )
        assert await inbox.admit_event(
            "wss://src.example", wrap2, _ref(merchant)
        ) == "received"
        await inbox.drain_received()
        await inbox.process_pending()
        stale_intent = await _reply_intent_for(wrap2)
        await outbox.worker_tick("abuse-worker")
        async with env["ext_module"].db.connect() as conn:
            await conn.execute(
                "UPDATE infinitemarkets.outbox_events"
                " SET created_at = :c WHERE id = :i",
                {"c": int(time.time()) - 49 * 3600, "i": stale_intent["id"]},
            )
        stats = await peer_relays.refresh_stale_peer_relays()
        assert stats["no_route_failed"] >= 1
        intent = dict(
            next(
                r for r in await _outbox_rows(env, mid)
                if r["id"] == stale_intent["id"]
            )
        )
        assert intent["state"] == "failed"
        assert intent["last_error"] == "no_inbox_relays"


async def test_rejected_intake_admin_surface_and_mute(
    runtime_env, monkeypatch
):
    """GET rejected-intake lists the bounded reason + author npub; the
    mute endpoint blocklists the author — the next wrap drops."""
    env = runtime_env
    merchant = await _merchant(env)
    mid, mpk = merchant["id"], merchant["pubkey"]
    client = env["client"]

    wrap, rumor = await _order_wrap(
        "buyer-mute-api", mpk, order_id="bad order!!",
        items=[], amount=0,
    )
    from infinitemarkets.services import inbox

    await inbox.admit_event("wss://r.example", wrap, _ref(merchant))
    await inbox.drain_received()
    await inbox.process_pending()
    row = await _row_for_wrap(env, mid, wrap)
    assert row["processed_state"] == "rejected"

    resp = await client.get(
        f"{API}/merchants/{mid}/rejected-intake",
        headers=_headers(env),
    )
    assert resp.status_code == 200, resp.text
    entries = resp.json()["entries"]
    entry = next(e for e in entries if e["id"] == row["id"])
    assert entry["reject_reason"] == "invalid-external-id"
    assert entry["author_npub"].startswith("npub1")

    resp = await client.post(
        f"{API}/merchants/{mid}/rejected-intake/{row['id']}/mute",
        headers=_headers(env, client.cookies.get("gm_csrf") or ""),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["muted"] is True
    assert resp.json()["author_npub"] == entry["author_npub"]

    # Mute is idempotent — a repeat POST never grows a second row.
    resp = await client.post(
        f"{API}/merchants/{mid}/rejected-intake/{row['id']}/mute",
        headers=_headers(env, client.cookies.get("gm_csrf") or ""),
    )
    assert resp.status_code == 200, resp.text
    async with env["ext_module"].db.connect() as conn:
        n = await conn.fetchone(
            "SELECT COUNT(*) AS n FROM infinitemarkets.inbox_blocklist"
            " WHERE merchant_id = :m AND author_hash = :h",
            {"m": mid, "h": row["author_hash"]},
        )
    assert int(n["n"]) == 1

    # A follow-up wrap from the same author drops at drain.
    wrap2, _ = await _order_wrap(
        "buyer-mute-api", mpk, order_id="ok-order-1",
        items=[], amount=0,
    )
    await inbox.admit_event("wss://r.example", wrap2, _ref(merchant))
    await inbox.drain_received()
    rows = await _inbox_rows(env, mid)
    blocked = [
        r for r in rows
        if r["reject_reason"] == "author-blocked"
        and r["outer_event_id"] == wrap2.id().to_hex()
    ]
    # First drop in this burst leaves an auditable row; the wrap
    # never dispatched.
    assert len(blocked) == 1
    assert not [
        o for o in await _orders(env, mid)
        if o["source_event_id"] == wrap2.id().to_hex()
    ]


async def test_retention_erases_rejected_quarantined(
    runtime_env, monkeypatch
):
    """§11.3: rejected/quarantined ciphertext erases at 30d; processed
    at 7d; expired peer_relays purge — the report surfaces counts."""
    from infinitemarkets.db import DomainTransaction
    from infinitemarkets.services import settlement

    env = runtime_env
    merchant = await _merchant(env)
    mid = merchant["id"]
    now = int(time.time())

    # Plant three synthetic inbox rows at staggered ages + an expired
    # peer_relays row.
    async with DomainTransaction() as tx:
        for suffix, state, age in (
            ("old-rej", "rejected", now - 31 * 86400),
            ("new-rej", "rejected", now - 86400),
            ("old-proc", "processed", now - 8 * 86400),
        ):
            await tx.execute(
                f"INSERT INTO {tx.table('inbox_events')} "
                "(id, merchant_id, outer_event_id,"
                " source_relay_url, raw_json, author_enc,"
                " processed_state, reject_reason, received_at,"
                " processed_at) "
                "VALUES (:i, :m, :o, 'wss://x.example',"
                " :raw, :ae, :ps, 'x', :r, :p)",
                {
                    "i": uuid.uuid4().hex + suffix,
                    "m": mid, "o": uuid.uuid4().hex,
                    "raw": "blob",
                    "ae": crypto_enc_placeholder(),
                    "ps": state, "r": age, "p": age,
                },
            )
        await tx.execute(
            f"INSERT INTO {tx.table('peer_relays')} "
            "(id, merchant_id, pubkey_hash, pubkey_enc, relay_url,"
            " fetched_at, expires_at) "
            "VALUES (:i, :m, :h, :e, 'wss://x.example', 0, :x)",
            {
                "i": uuid.uuid4().hex, "m": mid,
                "h": uuid.uuid4().hex, "e": b"x", "x": now - 1,
            },
        )
    report = await settlement.retention_prune(now=now)
    assert report["inbox_erased"] >= 2  # old-rej + old-proc
    assert report["peer_relays_purged"] >= 1
    async with env["ext_module"].db.connect() as conn:
        rows = await conn.fetchall(
            "SELECT raw_json, processed_state"
            " FROM infinitemarkets.inbox_events"
            " WHERE merchant_id = :m AND processed_state != 'received'",
            {"m": mid},
        )
    states = {r["processed_state"]: r["raw_json"] for r in rows
              if r["raw_json"] == "blob"}
    # The young rejected row still holds ciphertext; the aged rows erased.
    assert states.get("rejected") == "blob"


def crypto_enc_placeholder():
    return b"x"


async def _set_relays_helper(env: dict, mid: str, configs: list[dict]):
    client = env["client"]
    resp = await client.patch(
        f"{API}/merchants/{mid}",
        json={"relay_configs": configs},
        headers=_headers(env, client.cookies.get("gm_csrf") or ""),
    )
    assert resp.status_code == 200, resp.text
