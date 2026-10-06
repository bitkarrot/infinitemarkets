"""Gamma inbox transport — kind-1059 sessions, §8.5 admission, cursors,
NIP-42 AUTH, egress validation, and peer kind-10050 discovery.

Sessions run on the shared no-signer transport client; tests flip
``INFINITEMARKETS_RELAY_IO``/``INFINITEMARKETS_ALLOW_INSECURE_RELAYS`` at
call time so the real runtime dials ``harness.relay.LocalRelay``.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid

import pytest

pytestmark = pytest.mark.runtime


def _headers(env: dict, csrf: str | None = None) -> dict:
    cookie = f"cookie_access_token={env['token']}"
    if csrf:
        cookie += f"; gm_csrf={csrf}"
    h = {"Cookie": cookie, "Origin": "https://shop.example"}
    if csrf:
        h["X-CSRF-Token"] = csrf
    return h


def _csrf(client) -> str:
    return client.cookies.get("gm_csrf") or ""


async def _merchant(env: dict) -> dict:
    """Create-or-fetch the module merchant; returns its public row."""
    client = env["client"]
    existing = await client.get(
        "/infinitemarkets/api/v1/merchants/current", headers=_headers(env)
    )
    if existing.status_code == 200:
        return existing.json()
    resp = await client.post(
        "/infinitemarkets/api/v1/merchants",
        json={"wallet_id": env["wallet"].id},
        headers=_headers(env, _csrf(client)),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _set_relays(env: dict, mid: str, configs: list[dict]):
    client = env["client"]
    resp = await client.patch(
        f"/infinitemarkets/api/v1/merchants/{mid}",
        json={"relay_configs": configs},
        headers=_headers(env, _csrf(client)),
    )
    assert resp.status_code == 200, resp.text


async def _activate_inbox(env: dict, mid: str):
    """Shortcut: activation itself is covered in test_inbox_activation —
    transport tests drive the state directly."""
    async with env["ext_module"].db.connect() as conn:
        await conn.execute(
            "UPDATE infinitemarkets.merchants SET inbox_state = 'active' "
            "WHERE id = :i",
            {"i": mid},
        )


async def _inbox_rows(env: dict, mid: str) -> list[dict]:
    async with env["ext_module"].db.connect() as conn:
        rows = await conn.fetchall(
            "SELECT * FROM infinitemarkets.inbox_events "
            "WHERE merchant_id = :m ORDER BY received_at",
            {"m": mid},
        )
    return [dict(r) for r in rows]


async def _cursor_row(env: dict, mid: str, url: str) -> dict | None:
    async with env["ext_module"].db.connect() as conn:
        return await conn.fetchone(
            "SELECT * FROM infinitemarkets.relay_cursors "
            "WHERE merchant_id = :m AND relay_url = :r",
            {"m": mid, "r": url},
        )


async def _relay_config_row(env: dict, mid: str, url: str) -> dict | None:
    async with env["ext_module"].db.connect() as conn:
        return await conn.fetchone(
            "SELECT * FROM infinitemarkets.relay_configs "
            "WHERE merchant_id = :m AND relay_url = :r",
            {"m": mid, "r": url},
        )


async def _wait_for(pred, timeout: float = 30.0, interval: float = 0.25):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = await pred()
        if value:
            return value
        await asyncio.sleep(interval)
    raise AssertionError("wait_for timed out")


def _rumor(buyer_public_key: str, merchant_pubkey_hex: str,
           *, content: str = "order payload", order_id: str = "o-1",
           created_at: int | None = None):
    """A buyer-authored kind-16 unsigned rumor addressed to the merchant."""
    from nostr_sdk import EventBuilder, Kind, PublicKey, Tag, Timestamp

    return (
        EventBuilder(Kind(16), content)
        .custom_created_at(
            Timestamp.from_secs(created_at or int(time.time()))
        )
        .tags([
            Tag.parse(["p", merchant_pubkey_hex]),
            Tag.parse(["subject", "order"]),
            Tag.parse(["type", "1"]),
            Tag.parse(["order", order_id]),
        ])
        .build(PublicKey.parse(buyer_public_key))
    )


async def _wrap_rumor(rumor, buyer_secret_hex: str,
                      merchant_pubkey_hex: str):
    """Seal + gift-wrap one rumor for the merchant."""
    from nostr_sdk import (
        EventBuilder,
        Keys,
        NostrSigner,
        PublicKey,
        gift_wrap_from_seal,
    )

    keys = Keys.parse(buyer_secret_hex)
    recipient = PublicKey.parse(merchant_pubkey_hex)
    signer = NostrSigner.keys(keys)
    builder = await EventBuilder.seal(signer, recipient, rumor)
    seal = await builder.sign(signer)
    return gift_wrap_from_seal(recipient, seal)


async def _gift_wrap(buyer_secret_hex: str, merchant_pubkey_hex: str,
                     *, content: str = "order payload",
                     order_id: str = "o-1"):
    """A valid NIP-17 wrap addressed to the merchant."""
    from nostr_sdk import Keys

    rumor = _rumor(
        Keys.parse(buyer_secret_hex).public_key().to_hex(),
        merchant_pubkey_hex, content=content, order_id=order_id,
    )
    return await _wrap_rumor(rumor, buyer_secret_hex, merchant_pubkey_hex)


def _merchant_ref(merchant: dict) -> dict:
    return {"id": merchant["id"], "pubkey": merchant["pubkey"]}


# --- relay-IO kill switch -----------------------------------------------------


async def test_relay_io_off_holds_no_sockets(runtime_env):
    """The fixture boots with RELAY_IO=off: reconcile opens nothing and
    the handler task is never spawned."""
    from infinitemarkets.services.inbox import inbox_runtime

    rt = inbox_runtime()
    result = await rt.reconcile()
    assert result == {"sessions": 0}
    assert rt._handler_task is None


# --- session -> admission -> drain -> cursor vertical -------------------------


async def test_subscription_admission_and_cursor(runtime_env, monkeypatch):
    """One local inbox relay with one canned wrap: REQ -> EVENT -> EOSE ->
    durable admission ('received') -> leased drain -> 'validated' ->
    cursor commit. A forced second session resyncs from
    last_completed_session_start - 3 days."""
    from harness import relay as relay_module
    from infinitemarkets.services import inbox
    from infinitemarkets.services.inbox import inbox_runtime

    env = runtime_env
    merchant = await _merchant(env)
    mid, pubkey = merchant["id"], merchant["pubkey"]

    monkeypatch.setenv("INFINITEMARKETS_RELAY_IO", "on")
    monkeypatch.setenv("INFINITEMARKETS_ALLOW_INSECURE_RELAYS", "1")

    buyer_secret = "aa" * 32
    wrap = await _gift_wrap(buyer_secret, pubkey)
    canned = [json.loads(wrap.as_json())]

    async with relay_module.LocalRelay(
        mode=relay_module.RelayMode.ACCEPTING,
        canned_events=canned,
    ) as relay:
        await _set_relays(env, mid, [
            {"relay_url": relay.url, "direction": "inbox"},
        ])
        await _activate_inbox(env, mid)

        rt = inbox_runtime()
        t0 = int(time.time())
        await rt.reconcile()

        async def _received_row():
            rows = await _inbox_rows(env, mid)
            return [r for r in rows
                    if r["outer_event_id"] == wrap.id().to_hex()]

        rows = await _wait_for(_received_row, timeout=30)
        row = rows[0]
        assert row["processed_state"] == "received"
        assert row["outer_event_id"] == wrap.id().to_hex()

        # The REQ filter: kinds [1059], #p = merchant, since ≈ now-30d.
        assert relay.received_reqs, "relay saw no REQ"
        req_filter = relay.received_reqs[0][2]
        assert req_filter["kinds"] == [1059]
        assert req_filter["#p"] == [pubkey]
        assert abs(req_filter["since"] - (t0 - 30 * 86400)) < 30

        # Cursor committed only after EOSE — and carries the session id.
        cursor = await _wait_for(
            lambda: _cursor_row(env, mid, relay.url), timeout=15
        )
        assert relay.eoses_sent >= 1
        assert int(cursor["last_completed_session_start"]) >= t0 - 5
        assert cursor["eose_session_id"]

        # The leased drain drives 'received' -> 'validated'.
        report = await inbox.drain_received()
        assert report["validated"] >= 1
        rows = await _received_row()
        assert rows[0]["processed_state"] == "validated"
        assert rows[0]["kind"] == 16
        assert rows[0]["rumor_id"]

        # Force a second session: close + reconcile -> the REQ's `since`
        # is last_completed_session_start - 3 days (never created_at).
        key = (mid, relay.url)
        await rt._close(key)
        reqs_before = len(relay.received_reqs)
        await rt.reconcile()

        async def _new_req():
            return relay.received_reqs[reqs_before:]

        await _wait_for(_new_req, timeout=15)
        new_filter = relay.received_reqs[-1][2]
        expected = int(cursor["last_completed_session_start"]) - 3 * 86400
        assert abs(new_filter["since"] - expected) < 30

        await rt.close()


async def test_duplicate_and_retry_wraps_are_noops(runtime_env, monkeypatch):
    """Outer-id dedupe AND rumor-id dedupe: the same wrap and a RETRY of
    the same rumor are both successful no-ops (no second processing)."""
    from infinitemarkets.services import inbox

    env = runtime_env
    merchant = await _merchant(env)
    mid, pubkey = merchant["id"], merchant["pubkey"]

    buyer_secret = "bb" * 32
    from nostr_sdk import Keys

    buyer_pk = Keys.parse(buyer_secret).public_key().to_hex()
    rumor = _rumor(buyer_pk, pubkey, created_at=int(time.time()))
    rumor_wrap_a = await _wrap_rumor(rumor, buyer_secret, pubkey)
    # A RETRY: same canonical rumor id under a fresh seal/wrap.
    rumor_wrap_b = await _wrap_rumor(rumor, buyer_secret, pubkey)
    assert rumor_wrap_a.id().to_hex() != rumor_wrap_b.id().to_hex()

    before = len(await _inbox_rows(env, mid))
    ref = _merchant_ref(merchant)
    first = await inbox.admit_event(
        "wss://relay-a.example", rumor_wrap_a, ref
    )
    assert first == "received"
    again = await inbox.admit_event(
        "wss://relay-b.example", rumor_wrap_a.as_json(), ref
    )
    assert again == "duplicate"
    rows = await _inbox_rows(env, mid)
    assert len(rows) == before + 1

    retry = await inbox.admit_event(
        "wss://relay-b.example", rumor_wrap_b, ref
    )
    assert retry == "received"  # fresh outer id — a new row

    report = await inbox.drain_received()
    rows = await _inbox_rows(env, mid)
    retry_row = next(
        r for r in rows
        if r["outer_event_id"] == rumor_wrap_b.id().to_hex()
    )
    first_row = next(
        r for r in rows
        if r["outer_event_id"] == rumor_wrap_a.id().to_hex()
    )
    assert first_row["processed_state"] == "validated"
    assert retry_row["processed_state"] == "duplicate"
    assert report["duplicate"] >= 1


async def test_admission_rejections(runtime_env, monkeypatch):
    """Oversized raw event, wrong kind, >1 p-tag, bad signature, and
    blocklisted authors all land on bounded rejected paths — pre-insert
    rejections never write rows; unwrap-level rejections mark the row."""
    from infinitemarkets import crypto
    from infinitemarkets.services import inbox
    from infinitemarkets.settings import ext_settings

    env = runtime_env
    merchant = await _merchant(env)
    mid, pubkey = merchant["id"], merchant["pubkey"]
    ref = _merchant_ref(merchant)
    settings = ext_settings()

    before = len(await _inbox_rows(env, mid))

    # 1. Oversized raw event — dropped before any row is written.
    giant = json.dumps({
        "id": "cc" * 32, "pubkey": "dd" * 32, "created_at": 1,
        "kind": 1059, "tags": [["p", pubkey]], "content": "A" * 33000,
        "sig": "ee" * 32,
    })
    assert await inbox.admit_event(
        "wss://r.example", giant, ref
    ) == "rejected"
    assert len(await _inbox_rows(env, mid)) == before  # no row written

    # 2. Wrong-kind outer event — pre-insert drop, no row.
    from nostr_sdk import EventBuilder, Keys, Kind, NostrSigner, Tag

    evil = Keys.generate()
    wrong_kind = await (
        EventBuilder(Kind(1), "x")
        .tags([Tag.parse(["p", pubkey])])
        .sign(NostrSigner.keys(evil))
    )
    assert await inbox.admit_event(
        "wss://r.example", wrong_kind, ref
    ) == "rejected"
    assert len(await _inbox_rows(env, mid)) == before

    # 3. A structurally-valid wrap → row 'received' → drain unwraps and
    # validates it (the rumor's p tag already names the merchant here).
    rumor = _rumor(Keys.parse("ee" * 32).public_key().to_hex(), pubkey)
    wrap = await _wrap_rumor(rumor, "ee" * 32, pubkey)
    assert await inbox.admit_event(
        "wss://r.example", wrap, ref
    ) == "received"
    report = await inbox.drain_received()
    assert report["validated"] >= 1

    # 4. Blocklisted author — insert the blocklist row keyed by rumor-
    # author hash, then a valid wrap from that author rejects in drain.
    buyer_secret = "cc" * 32
    rumor2 = _rumor(
        Keys.parse(buyer_secret).public_key().to_hex(), pubkey,
        order_id="o-blocked",
    )
    wrap2 = await _wrap_rumor(rumor2, buyer_secret, pubkey)
    buyer_pubkey = Keys.parse(buyer_secret).public_key().to_hex()
    author_hash = crypto.hmac_index(
        settings.privacy_key, crypto.PURPOSE_BUYER_PUBKEY,
        mid, crypto.normalize(buyer_pubkey),
    )
    async with env["ext_module"].db.connect() as conn:
        await conn.execute(
            "INSERT INTO infinitemarkets.inbox_blocklist "
            "(id, merchant_id, author_hash, created_at) "
            "VALUES (:i, :m, :h, 0)",
            {"i": uuid.uuid4().hex, "m": mid, "h": author_hash},
        )
    assert await inbox.admit_event(
        "wss://r.example", wrap2, ref
    ) == "received"
    await inbox.drain_received()
    rows = await _inbox_rows(env, mid)
    blocked_row = next(
        r for r in rows if r["outer_event_id"] == wrap2.id().to_hex()
    )
    assert blocked_row["processed_state"] == "rejected"
    assert blocked_row["reject_reason"] == "author-blocked"


# --- NIP-42 AUTH ---------------------------------------------------------------


async def test_nip42_auth_roundtrip(runtime_env, monkeypatch):
    """An AUTH_CHALLENGE relay gets exactly one manual kind-22242 response
    keyed to its own connection, then serves the REQ; the relay's
    auth_state surfaces 'authenticated' after the post-AUTH EOSE."""
    from harness import relay as relay_module
    from infinitemarkets.services.inbox import inbox_runtime

    env = runtime_env
    merchant = await _merchant(env)
    mid, pubkey = merchant["id"], merchant["pubkey"]

    monkeypatch.setenv("INFINITEMARKETS_RELAY_IO", "on")
    monkeypatch.setenv("INFINITEMARKETS_ALLOW_INSECURE_RELAYS", "1")

    buyer_secret = "dd" * 32
    wrap = await _gift_wrap(buyer_secret, pubkey)

    async with relay_module.LocalRelay(
        mode=relay_module.RelayMode.AUTH_CHALLENGE,
        canned_events=[json.loads(wrap.as_json())],
    ) as relay:
        await _set_relays(env, mid, [
            {"relay_url": relay.url, "direction": "inbox"},
        ])
        await _activate_inbox(env, mid)

        rt = inbox_runtime()
        # The first REQ may race the AUTH answer and be CLOSED; the
        # reconcile cadence re-opens until the authed REQ is served.
        for _ in range(6):
            await rt.reconcile()
            if relay.eoses_sent:
                break
            await asyncio.sleep(1.0)

        await _wait_for(
            lambda: _cursor_row(env, mid, relay.url), timeout=20
        )
        accepted = [a for a in relay.auth_events if a["accepted"]]
        assert accepted, "relay never accepted an AUTH response"
        auth_event = accepted[0]["event"]
        assert auth_event["kind"] == 22242
        tag_vals = {t[0]: t[1] for t in auth_event["tags"]}
        assert tag_vals["challenge"] == relay.auth_challenge
        assert tag_vals["relay"] == relay.url
        assert auth_event["pubkey"] == pubkey

        rows = await _inbox_rows(env, mid)
        assert rows

        async def _authed():
            row = await _relay_config_row(env, mid, relay.url)
            return row and row["auth_state"] == "authenticated"

        await _wait_for(_authed, timeout=10)
        await rt.close()


async def test_nip42_oversize_challenge_ignored(runtime_env, monkeypatch):
    """A >1KiB challenge is never signed: no AUTH response reaches the
    relay, the REQ is CLOSED auth-required, and relay_configs records
    'auth-required'."""
    from harness import relay as relay_module
    from infinitemarkets.services.inbox import inbox_runtime

    env = runtime_env
    merchant = await _merchant(env)
    mid = merchant["id"]

    monkeypatch.setenv("INFINITEMARKETS_RELAY_IO", "on")
    monkeypatch.setenv("INFINITEMARKETS_ALLOW_INSECURE_RELAYS", "1")

    async with relay_module.LocalRelay(
        mode=relay_module.RelayMode.AUTH_CHALLENGE,
        auth_challenge="C" * 2048,
    ) as relay:
        await _set_relays(env, mid, [
            {"relay_url": relay.url, "direction": "inbox"},
        ])
        await _activate_inbox(env, mid)

        rt = inbox_runtime()
        for _ in range(4):
            await rt.reconcile()
            await asyncio.sleep(0.5)

        assert relay.auth_events == [], "oversize challenge was signed"

        async def _auth_required():
            row = await _relay_config_row(env, mid, relay.url)
            return row and row["auth_state"] == "auth-required"

        await _wait_for(_auth_required, timeout=15)
        await rt.close()


async def test_answer_auth_challenge_bounds(runtime_env):
    """Direct answer_auth_challenge checks: oversize challenge, foreign
    connection, and unconfigured relay all refuse without signing; a
    live connection + configured inbox relay signs kind-22242."""
    import inspect

    from infinitemarkets import keystore as keystore_mod
    from infinitemarkets.services import nostr_auth
    from infinitemarkets.settings import ext_settings

    env = runtime_env
    merchant = await _merchant(env)
    mid = merchant["id"]
    ks = keystore_mod.key_store(ext_settings())

    class _StubClient:
        def __init__(self, live: set[str]):
            self._live = live
            self.sent = []

        async def relays(self):
            return {u: None for u in self._live}

        async def send_msg_to(self, urls, msg):
            self.sent.append(msg)

    client = _StubClient({"wss://a.example"})

    # Oversize never reaches the signer.
    out = await nostr_auth.answer_auth_challenge(
        client, ks, mid, challenge="x" * 2000,
        relay_url="wss://a.example",
    )
    assert out is False
    # A URL that is not the live connection is never signed toward.
    out = await nostr_auth.answer_auth_challenge(
        client, ks, mid, challenge="c",
        relay_url="wss://evil.example",
    )
    assert out is False
    # A live connection the merchant has not configured refuses too.
    out = await nostr_auth.answer_auth_challenge(
        client, ks, mid, challenge="c",
        relay_url="wss://a.example",
    )
    assert out is False

    # Configure the relay as an inbox target (direct row — a live
    # connection stub needs no PATCH/DNS path).
    async with env["ext_module"].db.connect() as conn:
        await conn.execute(
            "INSERT INTO infinitemarkets.relay_configs "
            "(id, merchant_id, relay_url, direction, enabled,"
            " created_at, updated_at) "
            "VALUES (:i, :m, :u, 'inbox', TRUE, 0, 0)",
            {"i": uuid.uuid4().hex, "m": mid, "u": "wss://a.example"},
        )
    out = await nostr_auth.answer_auth_challenge(
        client, ks, mid, challenge="c1",
        relay_url="wss://a.example",
    )
    assert out is True
    wire = json.loads(client.sent[0].as_json())
    assert wire[0] == "AUTH"
    assert wire[1]["kind"] == 22242

    # Bounded source check — never the SDK-automatic path (call form).
    src = inspect.getsource(nostr_auth)
    assert "automatic_authentication(" not in src


# --- egress / SSRF --------------------------------------------------------------


async def test_validate_peer_relay_target(runtime_env, monkeypatch):
    """IPv4/IPv6 literals + localhost + metadata address are all rejected;
    the test hatch admits ws:// loopback and nothing else."""
    import ipaddress

    from infinitemarkets.services import transport as tport

    monkeypatch.delenv("INFINITEMARKETS_ALLOW_INSECURE_RELAYS", raising=False)

    for bad in (
        "wss://127.0.0.1", "wss://[::1]", "wss://localhost",
        "wss://169.254.169.254", "wss://10.0.0.8", "wss://[fe80::1]",
        "ws://example.com", "https://relay.example",
        "wss://no-such-host.invalid",
    ):
        with pytest.raises(Exception):
            await tport.validate_peer_relay_target(bad)

    # A host resolving ONLY to public space validates — stub the resolver
    # so the test needs no real DNS.
    async def _public_resolve(host, port=443):
        return [ipaddress.ip_address("93.184.216.34")]

    # transport imports the resolver into its own namespace — patch there.
    monkeypatch.setattr(tport, "resolve_and_check_egress", _public_resolve)
    assert (
        await tport.validate_peer_relay_target("wss://relay.example")
        == "wss://relay.example"
    )

    # Under the test hatch ws:// loopback still works (LocalRelay), and
    # non-loopback ws:// does NOT gain a pass.
    monkeypatch.setenv("INFINITEMARKETS_ALLOW_INSECURE_RELAYS", "1")
    assert await tport.validate_peer_relay_target("ws://127.0.0.1:9999")
    with pytest.raises(Exception):
        await tport.validate_peer_relay_target("ws://10.1.2.3")


# --- peer relay discovery ------------------------------------------------------


async def test_peer_relay_discovery_and_cache(runtime_env, monkeypatch):
    """kind-10050 on the discovery relay -> validated routes -> cached
    rows; the second resolve is a cache hit (no second REQ)."""
    import importlib

    from harness import relay as relay_module

    env = runtime_env
    merchant = await _merchant(env)
    mid = merchant["id"]

    monkeypatch.setenv("INFINITEMARKETS_RELAY_IO", "on")
    monkeypatch.setenv("INFINITEMARKETS_ALLOW_INSECURE_RELAYS", "1")

    from nostr_sdk import EventBuilder, Keys, Kind, NostrSigner, Tag

    buyer = Keys.generate()
    buyer_pk = buyer.public_key().to_hex()

    async with relay_module.LocalRelay(
        mode=relay_module.RelayMode.ACCEPTING
    ) as discovery:
        # Advertise ONE loopback route (the LocalRelay url) — under the
        # insecure hatch it survives egress validation.
        async with relay_module.LocalRelay(
            mode=relay_module.RelayMode.ACCEPTING
        ) as inbox_peer:
            k10050 = await (
                EventBuilder(Kind(10050), "")
                .tags([Tag.parse(["relay", inbox_peer.url])])
                .sign(NostrSigner.keys(buyer))
            )
            discovery.canned_events.append(json.loads(k10050.as_json()))

            await _set_relays(env, mid, [
                {"relay_url": discovery.url, "direction": "public"},
            ])

            peer_mod = importlib.import_module(
                "infinitemarkets.services.peer_relays"
            )
            routes = await peer_mod.resolve_buyer_inbox_relays(
                mid, buyer_pk
            )
            assert routes == [inbox_peer.url]

            async with env["ext_module"].db.connect() as conn:
                rows = await conn.fetchall(
                    "SELECT relay_url FROM infinitemarkets.peer_relays "
                    "WHERE merchant_id = :m",
                    {"m": mid},
                )
            assert [r["relay_url"] for r in rows] == [inbox_peer.url]

            # Cache hit — no second REQ for THIS buyer. Count only REQs
            # whose filter names the buyer: the merchant's own background
            # discovery shares the relay and would otherwise race the
            # count (seen on the slower ARM runner).
            def buyer_reqs() -> int:
                return sum(
                    1 for req in list(discovery.received_reqs)
                    if any(
                        buyer_pk in (flt.get("authors") or [])
                        for flt in req[2:] if isinstance(flt, dict)
                    )
                )

            reqs = buyer_reqs()
            assert reqs >= 1
            routes2 = await peer_mod.resolve_buyer_inbox_relays(
                mid, buyer_pk
            )
            assert routes2 == routes
            assert buyer_reqs() == reqs


async def test_peer_relay_no_route_sentinel(runtime_env, monkeypatch):
    """Malformed/invalid advertisements -> NO_INBOX_RELAYS — never a
    source-relay fallback."""
    import importlib
    import json as json_mod

    from nostr_sdk import EventBuilder, Keys, Kind, NostrSigner, Tag

    from harness import relay as relay_module

    env = runtime_env
    merchant = await _merchant(env)
    mid = merchant["id"]

    monkeypatch.setenv("INFINITEMARKETS_RELAY_IO", "on")
    monkeypatch.setenv("INFINITEMARKETS_ALLOW_INSECURE_RELAYS", "1")

    peer_mod = importlib.import_module(
        "infinitemarkets.services.peer_relays"
    )

    stranger = Keys.generate()

    async with relay_module.LocalRelay(
        mode=relay_module.RelayMode.ACCEPTING
    ) as discovery:
        await _set_relays(env, mid, [
            {"relay_url": discovery.url, "direction": "public"},
        ])

        # (a) >3 relay tags — the whole advertisement is malformed.
        buyer_a = Keys.generate()
        bad_tags = await (
            EventBuilder(Kind(10050), "")
            .tags([Tag.parse(["relay", "wss://a.example"]),
                   Tag.parse(["relay", "wss://b.example"]),
                   Tag.parse(["relay", "wss://c.example"]),
                   Tag.parse(["relay", "wss://d.example"])])
            .sign(NostrSigner.keys(buyer_a))
        )
        discovery.canned_events.append(json_mod.loads(bad_tags.as_json()))
        out = await peer_mod.resolve_buyer_inbox_relays(
            mid, buyer_a.public_key().to_hex()
        )
        assert out == peer_mod.NO_INBOX_RELAYS

        # (b) ws:// non-loopback under insecure hatch — still rejected
        # (egress requires public wss + DNS-public).
        buyer_b = Keys.generate()
        bad_scheme = await (
            EventBuilder(Kind(10050), "")
            .tags([Tag.parse(["relay", "ws://10.9.9.9"])])
            .sign(NostrSigner.keys(buyer_b))
        )
        discovery.canned_events = [json_mod.loads(bad_scheme.as_json())]
        out = await peer_mod.resolve_buyer_inbox_relays(
            mid, buyer_b.public_key().to_hex()
        )
        assert out == peer_mod.NO_INBOX_RELAYS

        # (c) empty discovery result — no event at all.
        discovery.canned_events = []
        out = await peer_mod.resolve_buyer_inbox_relays(
            mid, stranger.public_key().to_hex()
        )
        assert out == peer_mod.NO_INBOX_RELAYS


async def test_paid_relay_evidence_is_never_delivery(runtime_env, monkeypatch):
    """A paid-write negative OK is recorded evidence, not an acceptance —
    the message maps to 'payment-required' with the bolt11 surfaced, and
    the state persists on relay_configs (D-27)."""
    from harness import relay as relay_module
    from infinitemarkets.services import nostr_auth

    env = runtime_env
    merchant = await _merchant(env)
    mid, pubkey = merchant["id"], merchant["pubkey"]

    monkeypatch.setenv("INFINITEMARKETS_RELAY_IO", "on")
    monkeypatch.setenv("INFINITEMARKETS_ALLOW_INSECURE_RELAYS", "1")

    async with relay_module.LocalRelay(
        mode=relay_module.RelayMode.PAID
    ) as paid:
        await _set_relays(env, mid, [
            {"relay_url": paid.url, "direction": "public"},
        ])

        # Sign a small event through the merchant keystore, send via the
        # shared transport, and observe the negative-OK evidence.
        from nostr_sdk import EventBuilder, PublicKey

        from infinitemarkets import keystore as keystore_mod
        from infinitemarkets.services.transport import transport
        from infinitemarkets.settings import ext_settings

        ks = keystore_mod.key_store(ext_settings())
        unsigned = EventBuilder.text_note("paid-probe").build(
            PublicKey.parse(pubkey)
        )
        signed = await ks.sign_event(mid, unsigned)

        tport = transport()
        await tport.start([])
        out = await tport.send_to([paid.url], signed)
        assert str(paid.url) in str(out.failed), out
        assert not out.success

        state, invoice = nostr_auth.classify_relay_ok(
            "This is a paid relay: 'publish lnbc10n1xyz'"
        )
        assert state == "payment-required"
        assert invoice == "lnbc10n1xyz"
        assert nostr_auth.classify_closed(
            "payment-required: paid relay"
        ) == "payment-required"

        # Persist through the bounded surface — the D-26 vocabulary only.
        await nostr_auth.update_relay_auth_state(
            mid, paid.url, state, invoice=invoice
        )
        row = await _relay_config_row(env, mid, paid.url)
        assert row["auth_state"] == "payment-required"
        assert row["paid_invoice"] == "lnbc10n1xyz"
        await tport.close()


async def test_relay_auth_endpoints(runtime_env, monkeypatch):
    """GET /relay-auth surfaces the D-26 surface + connection state;
    POST retry clears a failed/paid state back to 'auth-required'."""
    env = runtime_env
    client = env["client"]
    merchant = await _merchant(env)
    mid = merchant["id"]

    from infinitemarkets.services import nostr_auth

    async with env["ext_module"].db.connect() as conn:
        await conn.execute(
            "INSERT INTO infinitemarkets.relay_configs "
            "(id, merchant_id, relay_url, direction, enabled,"
            " created_at, updated_at) "
            "VALUES (:i, :m, :u, 'public', TRUE, 0, 0)",
            {"i": uuid.uuid4().hex, "m": mid,
             "u": "wss://relay-auth.example"},
        )
    await nostr_auth.update_relay_auth_state(
        mid, "wss://relay-auth.example", "payment-required",
        invoice="lnbc10n1inv",
    )

    resp = await client.get(
        f"/infinitemarkets/api/v1/merchants/{mid}/relay-auth",
        headers=_headers(env),
    )
    assert resp.status_code == 200, resp.text
    rows = {r["relay_url"]: r for r in resp.json()["relays"]}
    row = rows["wss://relay-auth.example"]
    assert row["auth_state"] == "payment-required"
    assert row["paid_invoice"] == "lnbc10n1inv"
    assert row["connected"] is False

    from urllib.parse import quote

    url = quote("wss://relay-auth.example", safe="")
    resp = await client.post(
        f"/infinitemarkets/api/v1/merchants/{mid}"
        f"/relay-auth/retry/{url}",
        headers=_headers(env, _csrf(client)),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["auth_state"] == "auth-required"
    row = await _relay_config_row(env, mid, "wss://relay-auth.example")
    assert row["auth_state"] == "auth-required"
    assert row["paid_invoice"] is None


async def test_peer_relay_refresh(runtime_env, monkeypatch):
    """Expired peer_relays rows are deleted + re-resolved by
    refresh_stale_peer_relays (the 15-min TTL cycle)."""
    import importlib

    from nostr_sdk import EventBuilder, Keys, Kind, NostrSigner, Tag

    from harness import relay as relay_module

    env = runtime_env
    merchant = await _merchant(env)
    mid = merchant["id"]

    monkeypatch.setenv("INFINITEMARKETS_RELAY_IO", "on")
    monkeypatch.setenv("INFINITEMARKETS_ALLOW_INSECURE_RELAYS", "1")

    peer_mod = importlib.import_module(
        "infinitemarkets.services.peer_relays"
    )
    buyer = Keys.generate()
    buyer_pk = buyer.public_key().to_hex()

    async with relay_module.LocalRelay(
        mode=relay_module.RelayMode.ACCEPTING
    ) as discovery:
        async with relay_module.LocalRelay(
            mode=relay_module.RelayMode.ACCEPTING
        ) as inbox_peer:
            k10050 = await (
                EventBuilder(Kind(10050), "")
                .tags([Tag.parse(["relay", inbox_peer.url])])
                .sign(NostrSigner.keys(buyer))
            )
            discovery.canned_events.append(json.loads(k10050.as_json()))
            await _set_relays(env, mid, [
                {"relay_url": discovery.url, "direction": "public"},
            ])
            routes = await peer_mod.resolve_buyer_inbox_relays(
                mid, buyer_pk
            )
            assert routes == [inbox_peer.url]

            # Expire the cached rows — refresh re-resolves through the
            # encrypted pubkey.
            async with env["ext_module"].db.connect() as conn:
                await conn.execute(
                    "UPDATE infinitemarkets.peer_relays "
                    "SET expires_at = 0 WHERE merchant_id = :m",
                    {"m": mid},
                )
            stats = await peer_mod.refresh_stale_peer_relays()
            assert stats["refreshed"] >= 1
            routes2 = await peer_mod.resolve_buyer_inbox_relays(
                mid, buyer_pk
            )
            assert routes2 == routes


async def test_no_signer_on_owned_transports():
    """Source assertion — the shared transport keeps no-signer posture
    and disables automatic AUTH."""
    import inspect

    from infinitemarkets.services import transport

    t_src = inspect.getsource(transport.RelayTransport.start)
    assert "signer" not in t_src.lower()
    assert "automatic_authentication(False)" in t_src
