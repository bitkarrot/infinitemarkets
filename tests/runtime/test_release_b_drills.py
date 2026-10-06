"""Release-B release drills — plan 03-04 (final conformance gate).

Batteries:

(a) reference gated-relay environment — the LNbits ``nostrrelay``
    extension provisioned in an isolated host by
    ``tests/conformance/nostrrelay_env.py`` (subprocess; the relay must
    run inside its own booted host). Proves anonymous/stranger reads
    yield nothing, the authed+allowlisted merchant REQ serves wraps,
    open kind-1059 writes are accepted, and paid-write negative OKs are
    classified ``payment-required`` — including through the extension's
    own inbox session.
(b) NIP-42 AUTH drills — real challenge round-trip to AUTH'd service,
    oversize challenges never signed, foreign-connection challenges
    never signed.
(c) paid-write negative OK -> ``payment-required`` classification ->
    relay-auth API surface -> retry clears it (D-27: invoices are
    surfaced for external payment only — the extension never pays).
(d) overload — >300 wraps/min/relay dropped pre-decrypt, a >1000-row
    admitted backlog drains in bounded batches, every bound visible in
    the metrics surface.
(e) egress — private/loopback/link-local/multicast/reserved/metadata
    IPv4+IPv6 rejected at validation AND at the dial boundary
    (connect/reconnect revalidation never reaches the SDK).
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

pytestmark = pytest.mark.runtime

REPO_ROOT = Path(__file__).resolve().parents[2]
NOSTRRELAY_SRC = REPO_ROOT / ".cache" / "gsd-tmp" / "nostrrelay"
ENV_SCRIPT = REPO_ROOT / "tests" / "conformance" / "nostrrelay_env.py"

CANONICAL_ORIGIN = "https://shop.example"


# --- shared helpers (self-contained copies of the inbox_transport pattern) -----


def _headers(env: dict, csrf: str | None = None) -> dict:
    cookie = f"cookie_access_token={env['token']}"
    if csrf:
        cookie += f"; gm_csrf={csrf}"
    h = {"Cookie": cookie, "Origin": CANONICAL_ORIGIN}
    if csrf:
        h["X-CSRF-Token"] = csrf
    return h


def _csrf(client) -> str:
    return client.cookies.get("gm_csrf") or ""


async def _merchant(env: dict) -> dict:
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
    async with env["ext_module"].db.connect() as conn:
        await conn.execute(
            "UPDATE infinitemarkets.merchants SET inbox_state = 'active' "
            "WHERE id = :i",
            {"i": mid},
        )


async def _wait_for(pred, timeout: float = 30.0, interval: float = 0.25):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = await pred()
        if value:
            return value
        await asyncio.sleep(interval)
    raise AssertionError("wait_for timed out")


def _buyer_secret(i: int) -> str:
    """A distinct buyer secret per wrap — the per-author drain cap
    (60/min) must not mask the per-relay admission cap under test."""
    import hashlib

    return hashlib.sha256(f"drill-buyer-{i}".encode()).hexdigest()


async def _wrap(merchant_pubkey_hex: str, *, order_id: str,
                buyer_secret_hex: str = "aa" * 32):
    """A valid NIP-17 wrap addressed to the merchant."""

    from nostr_sdk import (
        EventBuilder,
        Keys,
        Kind,
        NostrSigner,
        PublicKey,
        Tag,
        Timestamp,
        gift_wrap_from_seal,
    )

    buyer = Keys.parse(buyer_secret_hex)
    rumor = (
        EventBuilder(Kind(16), "order payload")
        .custom_created_at(Timestamp.from_secs(int(time.time())))
        .tags([
            Tag.parse(["p", merchant_pubkey_hex]),
            Tag.parse(["subject", "order"]),
            Tag.parse(["type", "1"]),
            Tag.parse(["order", order_id]),
        ])
        .build(buyer.public_key())
    )
    signer = NostrSigner.keys(buyer)
    recipient = PublicKey.parse(merchant_pubkey_hex)
    seal_builder = await EventBuilder.seal(signer, recipient, rumor)
    seal = await seal_builder.sign(signer)
    return gift_wrap_from_seal(recipient, seal)


# ---------------------------------------------------------------------------
# (a) reference gated-relay environment (nostrrelay, real host boot)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not NOSTRRELAY_SRC.exists(),
    reason="nostrrelay source checkout missing — provision with "
           "`git clone https://github.com/lnbits/nostrrelay "
           ".cache/gsd-tmp/nostrrelay`",
)
async def test_reference_gated_relay_environment(tmp_path):
    """The nostrrelay env subprocess boots the pinned host with the real
    extension + the copied nostrrelay source and runs the probe battery.
    Every probe must pass; the JSON report lands in evidence."""
    if not ENV_SCRIPT.exists():
        pytest.fail(f"missing env script: {ENV_SCRIPT}")

    out = tmp_path / "nostrrelay-env.json"
    env = dict(os.environ)
    env.pop("LNBITS_DATA_FOLDER", None)  # the script picks its own tmp dir
    proc = await asyncio.create_subprocess_exec(
        sys.executable, str(ENV_SCRIPT), "run",
        "--json-out", str(out),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        env=env,
        cwd=str(REPO_ROOT),
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=300)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        pytest.fail("nostrrelay env run timed out after 300s")

    text = stdout.decode(errors="replace")
    report = json.loads(out.read_text()) if out.exists() else None
    assert report is not None, (
        f"no report emitted (exit {proc.returncode}):\n{text[-3000:]}"
    )
    assert proc.returncode == 0, (
        f"env run failed (exit {proc.returncode}): "
        f"{[p for p in report['probes'] if p['outcome'] != 'pass']}"
    )
    by_name = {p["name"]: p for p in report["probes"]}
    for name in (
        "gated_anon_req",
        "gated_stranger_req",
        "gated_merchant_req",
        "open_write_accepted",
        "gated_paid_write",
        "extension_gated_inbox",
        "extension_open_inbox",
        "paid_publish_surface",
    ):
        assert by_name.get(name, {}).get("outcome") == "pass", (
            f"{name}: {by_name.get(name)}"
        )


# ---------------------------------------------------------------------------
# (b) NIP-42 AUTH drills
# ---------------------------------------------------------------------------


async def test_nip42_auth_challenge_roundtrip(runtime_env, monkeypatch):
    """A connect-time AUTH challenge is answered with a kind-22242 signed
    by the merchant key; the post-auth REQ is served (wraps + EOSE)."""
    from harness import relay as relay_module
    from infinitemarkets.services.inbox import inbox_runtime

    env = runtime_env
    merchant = await _merchant(env)
    mid, pubkey = merchant["id"], merchant["pubkey"]

    monkeypatch.setenv("INFINITEMARKETS_RELAY_IO", "on")
    monkeypatch.setenv("INFINITEMARKETS_ALLOW_INSECURE_RELAYS", "1")

    wrap = await _wrap(pubkey, order_id="auth-drill-1")
    canned = [json.loads(wrap.as_json())]

    async with relay_module.LocalRelay(
        mode=relay_module.RelayMode.AUTH_CHALLENGE,
        canned_events=canned,
    ) as relay:
        await _set_relays(env, mid, [
            {"relay_url": relay.url, "direction": "inbox"},
        ])
        await _activate_inbox(env, mid)

        rt = inbox_runtime()
        await rt.reconcile()
        await asyncio.sleep(0.5)

        async def _authed_served():
            return [
                a for a in relay.auth_events if a["accepted"]
            ] and relay.eoses_sent >= 1

        await _wait_for(_authed_served, timeout=20)
        await asyncio.sleep(0.5)

        async with env["ext_module"].db.connect() as conn:
            row = await conn.fetchone(
                "SELECT * FROM infinitemarkets.inbox_events"
                " WHERE merchant_id = :m AND outer_event_id = :o",
                {"m": mid, "o": wrap.id().to_hex()},
            )
        assert row is not None, "wrap not admitted post-auth"


async def test_auth_challenge_oversize_never_signed(runtime_env,
                                                    monkeypatch):
    """An AUTH challenge beyond the 1 KiB bound is never signed — no
    AUTH response leaves the merchant (D-26 flood bound)."""
    from harness import relay as relay_module
    from infinitemarkets.services.inbox import inbox_runtime

    env = runtime_env
    merchant = await _merchant(env)
    mid = merchant["id"]

    monkeypatch.setenv("INFINITEMARKETS_RELAY_IO", "on")
    monkeypatch.setenv("INFINITEMARKETS_ALLOW_INSECURE_RELAYS", "1")

    async with relay_module.LocalRelay(
        mode=relay_module.RelayMode.AUTH_CHALLENGE,
        auth_challenge="x" * 2048,
    ) as relay:
        await _set_relays(env, mid, [
            {"relay_url": relay.url, "direction": "inbox"},
        ])
        await _activate_inbox(env, mid)
        rt = inbox_runtime()
        await rt.reconcile()
        await asyncio.sleep(1.0)
        assert relay.auth_events == [], (
            f"signed an oversize challenge: {relay.auth_events}"
        )


async def test_auth_challenge_foreign_connection_never_signed(
    runtime_env, monkeypatch,
):
    """A challenge for a URL that is not a live connection is never
    signed (the per-connection guard in answer_auth_challenge)."""
    from infinitemarkets import keystore as keystore_mod
    from infinitemarkets.services import nostr_auth
    from infinitemarkets.services.transport import transport
    from infinitemarkets.settings import ext_settings

    env = runtime_env
    merchant = await _merchant(env)
    mid = merchant["id"]

    monkeypatch.setenv("INFINITEMARKETS_RELAY_IO", "on")
    monkeypatch.setenv("INFINITEMARKETS_ALLOW_INSECURE_RELAYS", "1")

    tport = transport()
    await tport.start([])
    try:
        ok = await nostr_auth.answer_auth_challenge(
            tport.client,
            keystore_mod.key_store(ext_settings()),
            mid,
            relay_url="wss://unrelated.example",
            challenge="fake-challenge",
        )
        assert ok is False
    finally:
        await tport.close()


# ---------------------------------------------------------------------------
# (c) paid-write -> payment-required surface (D-27)
# ---------------------------------------------------------------------------


async def test_paid_write_negative_ok_surfaces_and_retries(
    runtime_env, monkeypatch,
):
    """A paid-relay negative OK ('This is a paid relay: <id>') classifies
    to ``payment-required``; the invoice/state lands on relay_configs and
    the relay-auth API; POST retry clears back to ``auth-required``.
    The extension NEVER pays — no wallet call is anywhere in the path."""
    from nostr_sdk import EventBuilder, PublicKey

    from harness import relay as relay_module
    from infinitemarkets.services import nostr_auth
    from infinitemarkets.services.transport import transport
    from infinitemarkets.settings import ext_settings

    env = runtime_env
    merchant = await _merchant(env)
    mid, pubkey = merchant["id"], merchant["pubkey"]

    monkeypatch.setenv("INFINITEMARKETS_RELAY_IO", "on")
    monkeypatch.setenv("INFINITEMARKETS_ALLOW_INSECURE_RELAYS", "1")

    invoice_probe = "lnbc10n1conformance"

    async with relay_module.LocalRelay(
        mode=relay_module.RelayMode.PAID,
        payment_message=(
            f"This is a paid relay: 'publish {invoice_probe}'"
        ),
    ) as paid:
        await _set_relays(env, mid, [
            {"relay_url": paid.url, "direction": "public"},
        ])

        from infinitemarkets import keystore as keystore_mod

        ks = keystore_mod.key_store(ext_settings())
        unsigned = EventBuilder.text_note("paid-drill").build(
            PublicKey.parse(pubkey)
        )
        signed = await ks.sign_event(mid, unsigned)

        tport = transport()
        await tport.start([])
        try:
            out = await tport.send_to([paid.url], signed)
            assert str(paid.url) in str(out.failed), out
            assert not out.success
        finally:
            pass

        # The negative-OK text classifies to payment-required with the
        # invoice surfaced for EXTERNAL payment (D-27).
        state, invoice = nostr_auth.classify_relay_ok(
            next(iter(out.failed.values()))
        )
        assert state == "payment-required"
        assert invoice == invoice_probe

        await nostr_auth.update_relay_auth_state(
            mid, paid.url, state, invoice=invoice
        )

        # The relay-auth API surfaces it.
        resp = await env["client"].get(
            f"/infinitemarkets/api/v1/merchants/{mid}/relay-auth",
            headers=_headers(env),
        )
        assert resp.status_code == 200, resp.text
        surfaced = [
            r for r in resp.json()["relays"] if r["relay_url"] == paid.url
        ]
        assert surfaced and surfaced[0]["auth_state"] == "payment-required"

        # Retry clears the surface for the next auth attempt — the URL
        # rides the trailing path segment.
        resp = await env["client"].post(
            f"/infinitemarkets/api/v1/merchants/{mid}"
            f"/relay-auth/retry/{paid.url}",
            headers=_headers(env, _csrf(env["client"])),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["auth_state"] == "auth-required"
        await tport.close()


# ---------------------------------------------------------------------------
# (d) overload: admission cap + bounded drain + visible metrics
# ---------------------------------------------------------------------------


async def test_relay_wrap_rate_cap_drops_pre_decrypt(
    runtime_env, monkeypatch, frozen_inbox_clock,
):
    """>300 wraps/min on one relay scope: excess dropped BEFORE decrypt.

    Every drop is a bounded rejection (no inbox_events row) counted in
    ``inbox.admission.relay_rate_limited``; the admitted 300 insert but
    the drain's unwrap counter only moves when a drain actually runs.
    """
    from infinitemarkets.services import inbox, metrics

    env = runtime_env
    merchant = await _merchant(env)
    mid, pubkey = merchant["id"], merchant["pubkey"]

    relay_url = "wss://flood-a.example"
    results = {"received": 0, "rejected": 0, "duplicate": 0}
    for i in range(310):
        wrap = await _wrap(
            pubkey, order_id=f"flood-{i}", buyer_secret_hex=_buyer_secret(i)
        )
        results[
            await inbox.admit_event(
                relay_url, wrap, {"id": mid, "pubkey": pubkey}
            )
        ] += 1

    assert results["received"] == inbox.RATE_WRAP_RELAY_PER_MINUTE == 300
    assert results["rejected"] == 10
    assert metrics.get("inbox.admission.relay_rate_limited") == 10

    async with env["ext_module"].db.connect() as conn:
        row = await conn.fetchone(
            "SELECT COUNT(*) AS n FROM infinitemarkets.inbox_events"
            " WHERE merchant_id = :m AND source_relay_url = :u",
            {"m": mid, "u": relay_url},
        )
    assert int(row["n"]) == 300, "dropped wraps must never reach the table"


async def test_backlog_drains_in_bounded_batches(runtime_env, monkeypatch):
    """>1000 admitted wraps across relay scopes drain in batches bounded
    by DRAIN_BATCH (64) — the queue is processed, not grown unboundedly,
    and every pass is visible in the metrics surface."""
    from infinitemarkets.services import inbox, metrics

    env = runtime_env
    merchant = await _merchant(env)
    mid, pubkey = merchant["id"], merchant["pubkey"]

    scopes = [f"wss://flood-{c}.example" for c in "bcdef"]
    total = 0
    n = 0
    for url in scopes:
        for i in range(260):
            n += 1
            wrap = await _wrap(
                pubkey, order_id=f"q-{url[-8:]}-{i}",
                buyer_secret_hex=_buyer_secret(1000 + n),
            )
            assert await inbox.admit_event(
                url, wrap, {"id": mid, "pubkey": pubkey}
            ) == "received"
            total += 1
    assert total == 1300 > 1000

    received_before = metrics.get("inbox.admission.received")
    assert received_before >= 1300

    # Bounded passes: each drain handles at most DRAIN_BATCH rows.
    passes = 0
    processed = 0
    while True:
        report = await inbox.drain_received()
        handled = sum(report.values())
        assert handled <= inbox.DRAIN_BATCH, (
            f"drain handled {handled} > {inbox.DRAIN_BATCH}"
        )
        processed += handled
        passes += 1
        if handled == 0:
            break
        assert passes < 60, "drain made no progress"

    # The whole backlog was processed — no 'received' rows remain in the
    # tested scopes (the shared module host may carry earlier tests' rows,
    # so assert per-scope table state, not the pass total).
    async with env["ext_module"].db.connect() as conn:
        left = await conn.fetchone(
            "SELECT COUNT(*) AS n FROM infinitemarkets.inbox_events"
            " WHERE merchant_id = :m AND processed_state = 'received'"
            " AND source_relay_url IN ("
            + ",".join(f"'{u}'" for u in scopes) + ")",
            {"m": mid},
        )
    assert int(left["n"]) == 0
    assert metrics.get("inbox.drain.unwrap") >= 1300


# ---------------------------------------------------------------------------
# (e) egress matrix — validation + connect/reconnect boundary
# ---------------------------------------------------------------------------

_EGRESS_IPV4 = [
    "127.0.0.1",        # loopback
    "10.0.0.9",         # private
    "172.16.5.5",       # private
    "192.168.1.9",      # private
    "169.254.169.254",  # link-local cloud metadata (explicit)
    "169.254.1.1",      # link-local
    "100.64.0.1",       # CGNAT shared space
    "192.0.0.1",        # IETF protocol assignments
    "198.18.0.1",       # benchmark
    "224.0.0.1",        # multicast
    "240.0.0.1",        # reserved
    "0.0.0.0",          # unspecified
]
_EGRESS_IPV6 = [
    "::1",              # loopback
    "fe80::1",          # link-local
    "fd00::1",          # ULA private
    "fc00::1",          # ULA private
    "ff02::1",          # multicast
    "::",               # unspecified
    "2001:db8::1",      # documentation range (non-global)
    "::ffff:10.0.0.1",  # IPv4-mapped private
]


@pytest.mark.parametrize("ip", _EGRESS_IPV4 + _EGRESS_IPV6)
async def test_egress_dns_matrix_rejects_non_public(runtime_env,
                                                    monkeypatch, ip):
    """Every non-public answer is rejected at validate/connect —
    especially 169.254.169.254 — via the real DNS-check path, both at
    the ``validate_peer_relay_target`` boundary and (for inbox
    directions) at relay-config write and at reconcile/dial."""
    import ipaddress

    from infinitemarkets import security
    from infinitemarkets.services.transport import validate_peer_relay_target

    host = f"probe-{ipaddress.ip_address(ip).packed.hex()}.invalid"
    target_ip = ipaddress.ip_address(ip)
    family = (
        socket.AF_INET6 if target_ip.version == 6 else socket.AF_INET
    )
    sockaddr = (ip, 443, 0, 0) if family == socket.AF_INET6 else (ip, 443)

    real_getaddrinfo = socket.getaddrinfo

    def fake_getaddrinfo(h, port, family_=0, type_=0, proto=0, flags=0):
        if h == host:
            return [(family, socket.SOCK_STREAM, 6, "", sockaddr)]
        return real_getaddrinfo(h, port, family_, type_, proto, flags)

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    security._dns_cache.pop(host, None)

    url = f"wss://{host}"

    env = runtime_env
    merchant = await _merchant(env)
    mid = merchant["id"]

    # Gate 1 — validate_peer_relay_target (the D-30 discovery/dial gate).
    with pytest.raises(Exception):
        await validate_peer_relay_target(url)

    # Gate 2 — relay-config write for an inbox-direction row also
    # DNS-checks (PATCH must reject).
    resp = await env["client"].patch(
        f"/infinitemarkets/api/v1/merchants/{mid}",
        json={"relay_configs": [
            {"relay_url": url, "direction": "inbox"},
        ]},
        headers=_headers(env, _csrf(env["client"])),
    )
    assert resp.status_code == 422, resp.text

    # Gate 3 — connect: a pre-existing inbox row (inserted directly,
    # bypassing the PATCH gate as a persisted row could exist from an
    # earlier good-resolution window) must never reach the SDK dial.
    now = int(time.time())
    async with env["ext_module"].db.connect() as conn:
        await conn.execute(
            "DELETE FROM infinitemarkets.relay_configs"
            " WHERE merchant_id = :m",
            {"m": mid},
        )
        await conn.execute(
            "INSERT INTO infinitemarkets.relay_configs "
            "(id, merchant_id, relay_url, direction, enabled,"
            " created_at, updated_at)"
            " VALUES (:i, :m, :u, 'inbox', TRUE, :t, :t)",
            {"i": uuid.uuid4().hex, "m": mid, "u": url, "t": now},
        )
    await _activate_inbox(env, mid)
    monkeypatch.setenv("INFINITEMARKETS_RELAY_IO", "on")

    from infinitemarkets.services.inbox import inbox_runtime

    rt = inbox_runtime()
    opened = []
    real_open = rt._open

    async def spy_open(*args, **kwargs):
        opened.append(args)
        return await real_open(*args, **kwargs)

    monkeypatch.setattr(rt, "_open", spy_open)
    await rt.reconcile()
    assert opened == [], "egress check must precede the dial"
    assert (mid, url) not in rt._sessions


async def test_egress_revalidation_on_reconnect(runtime_env, monkeypatch):
    """DNS-rebind flip: a peer relay that resolves public at discovery
    time is dropped on the NEXT resolve_and_check_egress pass once the
    answer changes to private — reconnect-time revalidation."""
    import ipaddress

    from infinitemarkets import security

    host = "flap.rebind.invalid"
    url = f"wss://{host}"
    good = ipaddress.ip_address("93.184.216.34")
    bad = ipaddress.ip_address("10.99.99.99")
    answer = {"ip": good}

    real_getaddrinfo = socket.getaddrinfo

    def fake_getaddrinfo(h, port, family_=0, type_=0, proto=0, flags=0):
        if h == host:
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "",
                 (str(answer["ip"]), port or 443))
            ]
        return real_getaddrinfo(h, port, family_, type_, proto, flags)

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    security._dns_cache.pop(host, None)

    from infinitemarkets.services.transport import validate_peer_relay_target

    assert await validate_peer_relay_target(url)  # public answer passes

    # The cached answer is still public; expire it, then flip to private.
    security._dns_cache.pop(host, None)
    answer["ip"] = bad
    with pytest.raises(Exception):
        await validate_peer_relay_target(url)
