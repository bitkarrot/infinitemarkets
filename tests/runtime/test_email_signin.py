"""Email magic-link sign-in + identity linking (03.1-02, D-05..D-11).

Covers the ``channel='account'`` queue transport (honest suppression,
per-recipient ``email-account`` bucketing, AEAD'd ``payload_enc`` wiped
on send), the no-oracle ``/nostr/email/request`` + fragment-token
``/nostr/email/verify`` vertical (uniform body, hash-only tokens,
single-use CAS, identical cookie contract, ``bound_orders``), and the
prove-both link flows ending in representability-checked union merges.
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
    """Seed one active merchant + a product factory — same harness shape
    as test_nostr_signin.py / test_buyer_accounts.py."""
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
            "display_name": "magic shop",
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
        json={"name": "magic", "default_currency": "SAT"},
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


# --- helpers -----------------------------------------------------------------


def _crypto():
    from infinitemarkets import crypto

    return crypto


def _settings():
    from infinitemarkets.settings import ext_settings

    return ext_settings()


def _svc():
    import importlib

    return {
        n: importlib.import_module(f"infinitemarkets.services.{n}")
        for n in ("email", "nostr_auth")
    }


def _buyer_keys(label: str):
    from harness.sdk import fixed_test_keys

    return fixed_test_keys(label)


def _buyer_hex(label: str) -> str:
    return _buyer_keys(label).public_key().to_hex()


def _email_hash(env: dict, email: str) -> str:
    crypto = _crypto()
    return crypto.hmac_index(
        _settings().privacy_key, crypto.PURPOSE_BUYER_EMAIL,
        env["merchant_id"], crypto.normalize(email),
    )


def _pubkey_hash(env: dict, pubkey_hex: str) -> str:
    crypto = _crypto()
    return crypto.hmac_index(
        _settings().privacy_key, crypto.PURPOSE_BUYER_PUBKEY,
        env["merchant_id"], crypto.normalize(pubkey_hex),
    )


async def _merchant(env: dict) -> dict:
    async with env["ext_module"].db.connect() as conn:
        row = await conn.fetchone(
            "SELECT * FROM infinitemarkets.merchants WHERE id = :m",
            {"m": env["merchant_id"]},
        )
    return dict(row)


async def _reset_buckets(env: dict) -> None:
    """Shared testclient IP — every request-side bucket accumulates
    across tests. ``email%`` is required: the worker's ``email-account``
    bucket does not match ``nostr%``."""
    from infinitemarkets.db import DomainTransaction

    async with DomainTransaction() as tx:
        await tx.execute(
            "DELETE FROM rate_limit_buckets"
            " WHERE bucket LIKE 'nostr%' OR bucket LIKE 'email%'"
            " OR bucket LIKE 'checkout%'"
        )


async def _challenge(client) -> str:
    resp = await client.get(f"{PUB}/nostr/challenge")
    assert resp.status_code == 200, resp.text
    return resp.json()["challenge"]


async def _sign_event(keys, challenge: str) -> str:
    from nostr_sdk import (
        EventBuilder,
        Kind,
        NostrSigner,
        Tag,
    )

    builder = EventBuilder(Kind(22242), challenge).tags(
        [Tag.parse(["challenge", challenge])]
    )
    return (await builder.sign(NostrSigner.keys(keys))).as_json()


async def _signin(client, label: str):
    """Full NIP-07 challenge -> sign -> verify (httpx jar keeps cookie)."""
    keys = _buyer_keys(label)
    challenge = await _challenge(client)
    event_json = await _sign_event(keys, challenge)
    resp = await client.post(
        f"{PUB}/nostr/verify",
        json={"event": event_json},
        headers={"Origin": ORIGIN},
    )
    assert resp.status_code == 200, resp.text
    return client.cookies.get("gm_nostr_session")


async def _web_order(env: dict, product_d: str, *, email=None) -> dict:
    """A fresh anonymous web checkout (order row)."""
    import httpx

    merchant = await _merchant(env)
    payload = {
        "merchant_pubkey": merchant["pubkey"],
        "items": [{"d_tag": product_d, "quantity": 1}],
        "email_opt_in": False,
    }
    if email is not None:
        payload["email"] = email
    transport = httpx.ASGITransport(app=env["app"])
    async with httpx.AsyncClient(
        transport=transport, base_url=ORIGIN
    ) as anon:
        resp = await anon.post(
            f"{PUB}/checkout",
            json=payload,
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
        row = await conn.fetchone(
            "SELECT * FROM infinitemarkets.orders"
            " WHERE public_token_hash = :h",
            {"h": digest},
        )
    assert row is not None
    return dict(row)


async def _account_rows(env: dict, *, email: str | None = None) -> list[dict]:
    """``channel='account'`` queue rows for the module merchant — when
    ``email`` is given, only rows for that recipient hash."""
    sql = (
        "SELECT * FROM infinitemarkets.email_queue"
        " WHERE merchant_id = :m AND channel = 'account'"
    )
    params = {"m": env["merchant_id"]}
    if email is not None:
        sql += " AND recipient_hash = :rh"
        params["rh"] = _crypto().hmac_index(
            _settings().privacy_key, _crypto().PURPOSE_EMAIL_RECIPIENT,
            env["merchant_id"], _crypto().normalize(email),
        )
    async with env["ext_module"].db.connect() as conn:
        rows = await conn.fetchall(
            sql + " ORDER BY created_at, id", params
        )
    return [dict(r) for r in rows]


def _payload_token(env: dict, row: dict) -> str:
    """Decrypt the queue row's ``payload_enc`` -> the raw magic-link
    token (the only read-back path — tokens are hash-only at rest)."""
    crypto = _crypto()
    settings = _settings()
    ver = crypto.envelope_version(row["payload_enc"])
    return json.loads(
        crypto.decrypt(
            row["payload_enc"], settings.master_keys[ver],
            record_id=row["id"], table="email_queue",
            column="payload_enc", key_version=ver,
        )
    )["token"]


async def _token_rows(env: dict) -> list[dict]:
    async with env["ext_module"].db.connect() as conn:
        rows = await conn.fetchall(
            "SELECT * FROM infinitemarkets.email_signin_tokens"
            " WHERE merchant_id = :m ORDER BY created_at, id",
            {"m": env["merchant_id"]},
        )
    return [dict(r) for r in rows]


async def _request_email(client, email: str, *, origin: str | None = ORIGIN):
    headers = {"Origin": origin} if origin else {}
    return await client.post(
        f"{PUB}/nostr/email/request", json={"email": email}, headers=headers
    )


async def _verify_email(client, token: str, *, origin: str | None = ORIGIN):
    headers = {"Origin": origin} if origin else {}
    return await client.post(
        f"{PUB}/nostr/email/verify", json={"token": token}, headers=headers
    )


async def _account_by_id(env: dict, account_id: str) -> dict | None:
    async with env["ext_module"].db.connect() as conn:
        row = await conn.fetchone(
            "SELECT * FROM infinitemarkets.buyer_accounts WHERE id = :a",
            {"a": account_id},
        )
    return dict(row) if row else None


async def _legacy_session(env: dict, pubkey_hex: str) -> str:
    """Craft a pre-m008 session row: ``account_id NULL`` + the pubkey
    pair under the session-id AAD — exactly what m007 minted."""
    crypto = _crypto()
    from infinitemarkets.db import DomainTransaction

    settings = _settings()
    ver = settings.active_key_version
    session_id = uuid.uuid4().hex
    token = crypto.generate_public_token()
    now = int(time.time())
    async with DomainTransaction() as tx:
        await tx.execute(
            "INSERT INTO buyer_sessions (id, merchant_id, token_hash,"
            " buyer_pubkey_enc, buyer_pubkey_hash, account_id, expires_at,"
            " created_at) VALUES (:i, :m, :t, :e, :h, NULL, :x, :n)",
            {
                "i": session_id,
                "m": env["merchant_id"],
                "t": crypto.token_lookup_hash(token).hex(),
                "e": crypto.encrypt(
                    pubkey_hex.encode(), settings.master_keys[ver],
                    record_id=session_id, table="buyer_sessions",
                    column="buyer_pubkey_enc", key_version=ver,
                ),
                "h": _pubkey_hash(env, pubkey_hex),
                "x": now + 86400,
                "n": now,
            },
        )
    return token


# --- Task 1: channel='account' transport --------------------------------------


async def test_magic_link_suppressed_when_host_unconfigured(runtime_env):
    """D-07 honest degradation: unconfigured host SMTP suppresses the
    account row with the same vocabulary as order mail — never silent."""
    svcs = _svc()
    env = runtime_env
    from infinitemarkets.db import DomainTransaction

    token = _crypto().generate_public_token()
    async with DomainTransaction() as tx:
        row_id = await svcs["email"].enqueue_magic_link(
            tx, merchant_id=env["merchant_id"],
            recipient="nobody@example.com", token=token,
            now=int(time.time()),
        )
    result = await svcs["email"].worker_tick("w-account")
    assert result["claimed"] >= 1
    rows = await _account_rows(env)
    mine = [r for r in rows if r["id"] == row_id]
    assert mine and mine[0]["state"] == "suppressed"
    assert mine[0]["last_error"] == "host-email-unconfigured"


async def test_magic_link_send_renders_fragment_and_wipes(runtime_env, monkeypatch):
    """Configured SMTP -> sent; body carries the fragment link, never the
    bare token; subject has no token/address; sent row wipes both enc
    columns."""
    svcs = _svc()
    env = runtime_env
    from lnbits.settings import settings as host_settings

    monkeypatch.setattr(
        type(host_settings), "is_email_notifications_configured",
        lambda self: True,
    )
    sent_calls = []

    async def fake_send(*args, **kwargs):
        sent_calls.append(args)
        return True

    import lnbits.core.services.notifications as notif

    monkeypatch.setattr(notif, "send_email", fake_send)

    from infinitemarkets.db import DomainTransaction

    token = _crypto().generate_public_token()
    async with DomainTransaction() as tx:
        row_id = await svcs["email"].enqueue_magic_link(
            tx, merchant_id=env["merchant_id"],
            recipient="buyer@example.com", token=token,
            now=int(time.time()),
        )
    await svcs["email"].worker_tick("w-account")
    rows = await _account_rows(env)
    mine = [r for r in rows if r["id"] == row_id]
    assert mine and mine[0]["state"] == "sent"
    # Sent row retains no bearer material.
    assert not mine[0]["recipient_enc"]
    assert not mine[0]["payload_enc"]

    assert sent_calls, "host send_email was not invoked"
    args = sent_calls[0]
    recipients, subject, body = args[5], args[6], args[7]
    assert recipients == ["buyer@example.com"]
    merchant = await _merchant(env)
    assert "your sign-in link" in subject
    assert merchant["display_name"] in subject
    assert token not in subject
    assert "buyer@example.com" not in subject
    # The token appears EXACTLY once — inside the URL fragment.
    assert f"/infinitemarkets/auth/email?shop={merchant['pubkey']}#{token}" in body
    assert body.count(token) == 1
    assert "expires in 15 minutes" in body


async def test_magic_link_suppressed_when_email_disabled(runtime_env, monkeypatch):
    """``INFINITEMARKETS_EMAIL_ENABLED=0`` -> ``email-disabled`` (same
    vocabulary as order mail)."""
    svcs = _svc()
    env = runtime_env
    monkeypatch.setenv("INFINITEMARKETS_EMAIL_ENABLED", "0")
    from lnbits.settings import settings as host_settings

    monkeypatch.setattr(
        type(host_settings), "is_email_notifications_configured",
        lambda self: True,
    )
    from infinitemarkets.db import DomainTransaction

    async with DomainTransaction() as tx:
        row_id = await svcs["email"].enqueue_magic_link(
            tx, merchant_id=env["merchant_id"],
            recipient="off@example.com", token=_crypto().generate_public_token(),
            now=int(time.time()),
        )
    await svcs["email"].worker_tick("w-account")
    rows = await _account_rows(env)
    mine = [r for r in rows if r["id"] == row_id]
    assert mine and mine[0]["state"] == "suppressed"
    assert mine[0]["last_error"] == "email-disabled"


async def test_account_channel_uses_email_account_bucket(runtime_env, monkeypatch):
    """``channel='account'`` consumes the ``email-account`` bucket keyed
    on ``recipient_hash`` — never ``consent-revoked``, never the
    ``email-merchant`` bucket. The (cap+1)th send in the window defers."""
    svcs = _svc()
    env = runtime_env
    await _reset_buckets(env)
    from lnbits.settings import settings as host_settings

    monkeypatch.setattr(
        type(host_settings), "is_email_notifications_configured",
        lambda self: True,
    )

    async def fake_send(*args, **kwargs):
        return True

    import lnbits.core.services.notifications as notif

    monkeypatch.setattr(notif, "send_email", fake_send)
    from infinitemarkets.db import DomainTransaction

    cap = svcs["email"].ACCOUNT_HOURLY_CAP
    row_ids = []
    async with DomainTransaction() as tx:
        for i in range(cap + 1):
            row_ids.append(
                await svcs["email"].enqueue_magic_link(
                    tx, merchant_id=env["merchant_id"],
                    recipient="cap@example.com",
                    token=_crypto().generate_public_token(),
                    now=int(time.time()),
                )
            )
    result = await svcs["email"].worker_tick("w-account")
    assert result["outcomes"].get("rate-deferred", 0) == 1
    rows = await _account_rows(env)
    mine = {r["id"]: r for r in rows if r["id"] in row_ids}
    sent = [r for r in mine.values() if r["state"] == "sent"]
    deferred = [r for r in mine.values() if r["state"] == "pending"]
    assert len(sent) == cap
    assert len(deferred) == 1
    assert all(r["last_error"] != "consent-revoked" for r in mine.values())

    # The bucket row is scoped on the recipient hash under email-account.
    recipient_hash = _crypto().hmac_index(
        _settings().privacy_key, _crypto().PURPOSE_EMAIL_RECIPIENT,
        env["merchant_id"], _crypto().normalize("cap@example.com"),
    )
    async with env["ext_module"].db.connect() as conn:
        buckets = await conn.fetchall(
            "SELECT scope_hash, bucket, count"
            " FROM infinitemarkets.rate_limit_buckets"
            " WHERE scope_hash = :s",
            {"s": recipient_hash},
        )
    account_buckets = [dict(b) for b in buckets if b["bucket"] == "email-account"]
    assert account_buckets and account_buckets[0]["count"] >= cap
    assert not [b for b in buckets if b["bucket"] == "email-merchant"]


# --- Task 2: request/verify vertical (D-05, D-06, D-08, D-09) -------------------


async def test_request_uniform_body_no_oracle(runtime_env):
    """D-05 — identical body+status for unknown vs known emails; the
    only server-side trace is one ``signin_link`` queue row per request
    plus a hash-only token row (raw token never persisted)."""
    env = runtime_env
    await _reset_buckets(env)
    client = env["client"]

    known = "known-buyer@example.com"
    # Seed history: a prior web checkout under that address.
    product = await env["make_product"](f"pre-{uuid.uuid4().hex[:6]}", 5)
    await _web_order(env, product["d_tag"], email=known)

    bodies = []
    for email in (known, "never-seen@example.com", known):
        resp = await _request_email(client, email)
        assert resp.status_code == 200, resp.text
        bodies.append((resp.status_code, resp.json()))
    assert all(b == bodies[0] for b in bodies), bodies
    assert bodies[0][1]["sent"] is True

    rows = (
        await _account_rows(env, email=known)
        + await _account_rows(env, email="never-seen@example.com")
    )
    assert len(rows) == 3
    assert all(r["event_type"] == "signin_link" for r in rows)
    assert all(r["order_id"] is None for r in rows)
    assert all(r["payload_enc"] for r in rows)

    tokens = await _token_rows(env)
    assert len(tokens) == 3
    raw = _payload_token(env, rows[0])
    assert all(raw != t["token_hash"] for t in tokens)
    assert all(t["purpose"] == "signin" for t in tokens)
    assert all(t["used_at"] is None for t in tokens)
    assert all(t["expires_at"] - int(time.time()) <= 900 for t in tokens)
    # The sign-in request already resolved the identity's account.
    async with env["ext_module"].db.connect() as conn:
        acct = await conn.fetchone(
            "SELECT * FROM infinitemarkets.buyer_accounts"
            " WHERE merchant_id = :m AND email_hash = :h",
            {"m": env["merchant_id"], "h": _email_hash(env, known)},
        )
    assert acct is not None
    assert acct["email_enc"]


async def test_request_per_ip_bucket_is_honest_429(runtime_env):
    """D-06 — the per-IP bucket (10/min) is an honest 429."""
    env = runtime_env
    await _reset_buckets(env)
    client = env["client"]
    last = None
    for i in range(11):
        last = await _request_email(client, f"ip-{i}@example.com")
        if last.status_code == 429:
            break
    assert last is not None and last.status_code == 429, last.text
    assert last.json()["type"].endswith("rate-limited")


async def test_request_per_email_cap_silently_skips(runtime_env):
    """D-05/D-06 — the 4th request for the same address still answers the
    uniform 200 but mints+enqueues nothing (the per-email bucket is
    never a 429 oracle)."""
    env = runtime_env
    await _reset_buckets(env)
    client = env["client"]
    email = "capped@example.com"
    bodies = []
    for _ in range(4):
        resp = await _request_email(client, email)
        assert resp.status_code == 200, resp.text
        bodies.append((resp.status_code, resp.json()))
    assert all(b == bodies[0] for b in bodies)
    rows = await _account_rows(env, email=email)
    assert len(rows) == 3  # capped at 3/hr — request 4 minted nothing
    tokens = [
        t for t in await _token_rows(env)
        if t["email_hash"] == _email_hash(env, email)
    ]
    assert len(tokens) == 3


async def _signin_via_email(env: dict, client, email: str) -> dict:
    """Full request -> payload-token read-back -> verify; returns the
    verify response body."""
    resp = await _request_email(client, email)
    assert resp.status_code == 200, resp.text
    rows = await _account_rows(env, email=email)
    token = _payload_token(env, rows[-1])
    resp = await _verify_email(client, token)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_verify_signin_cookie_contract_and_bound_orders(runtime_env):
    """D-08/D-09 — verify mints the IDENTICAL gm_nostr_session cookie
    (HttpOnly/Secure/SameSite=Strict/path/7d) and bound_orders counts
    orders placed with that email BEFORE sign-in (union history)."""
    env = runtime_env
    await _reset_buckets(env)
    email = "early-buyer@example.com"
    product = await env["make_product"](f"early-{uuid.uuid4().hex[:6]}", 5)
    order = await _web_order(env, product["d_tag"], email=email)
    assert order["buyer_email_hash"] == _email_hash(env, email)

    import httpx

    transport = httpx.ASGITransport(app=env["app"])
    async with httpx.AsyncClient(
        transport=transport, base_url=ORIGIN
    ) as fresh:
        resp = await _request_email(fresh, email)
        assert resp.status_code == 200, resp.text
        rows = await _account_rows(env, email=email)
        token = _payload_token(env, rows[-1])
        resp = await _verify_email(fresh, token)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["signed_in"] is True
        assert body["bound_orders"] >= 1
        assert body["email"] == email
        assert body["pubkey"] is None  # email-only account
        assert body["redirect"] == "/infinitemarkets/orders"

        set_cookie = resp.headers.get("set-cookie", "")
        assert "gm_nostr_session=" in set_cookie
        for attr in ("httponly", "secure", "samesite=strict",
                     "path=/infinitemarkets", "max-age"):
            assert attr in set_cookie.lower(), set_cookie

        # The session serves the union history — the pre-signin order
        # placed with this email is there (D-09).
        resp = await fresh.get(f"{PUB}/nostr/orders")
        assert resp.status_code == 200, resp.text
        ids = {o["order_id"] for o in resp.json()["orders"]}
        assert order["id"] in ids

        # Single-use CAS — the same token fails identically.
        resp = await _verify_email(fresh, token)
        assert resp.status_code == 401, resp.text


async def test_verify_failures_share_identical_401(runtime_env):
    """Malformed, unknown, wrong-shop, expired and used tokens all
    produce the same 401 problem body (no oracle, T-312-01)."""
    env = runtime_env
    await _reset_buckets(env)
    import httpx

    # A second merchant gives ?shop= a real "wrong shop" target — one
    # merchant per user is enforced, so the row is seeded directly.
    from infinitemarkets.db import DomainTransaction

    other_pubkey = "cd" * 32
    async with DomainTransaction() as tx:
        await tx.execute(
            "INSERT INTO merchants (id, user_id, pubkey, key_ref,"
            " wallet_id_enc, wallet_id_hash, state, created_at)"
            " VALUES ('other-m', 'u-other', :p, 'kr-other', :w, 'wh',"
            " 'active', :n)",
            # Later created_at — the no-shop fallback resolves the
            # earliest merchant row (the module's seeded shop).
            {"p": other_pubkey, "w": b"w" * 40, "n": 9999999999},
        )

    transport = httpx.ASGITransport(app=env["app"])
    async with httpx.AsyncClient(
        transport=transport, base_url=ORIGIN
    ) as fresh:
        resp = await _request_email(fresh, "victim@example.com")
        assert resp.status_code == 200
        rows = await _account_rows(env, email="victim@example.com")
        token = _payload_token(env, rows[-1])

        outcomes = []
        variants = [
            ("not-a-token", None),
            (_crypto().generate_public_token(), None),  # well-formed, unknown
            (token, other_pubkey),                      # wrong shop
        ]
        for candidate, shop in variants:
            q = f"?shop={shop}" if shop else ""
            resp = await fresh.post(
                f"{PUB}/nostr/email/verify{q}",
                json={"token": candidate},
                headers={"Origin": ORIGIN},
            )
            assert resp.status_code == 401, (candidate[:10], resp.text)
            outcomes.append(resp.json())

        # Expired row — identical outcome.
        from infinitemarkets.db import DomainTransaction

        async with DomainTransaction() as tx:
            await tx.execute(
                "UPDATE email_signin_tokens SET expires_at = 1"
                " WHERE merchant_id = :m",
                {"m": env["merchant_id"]},
            )
        resp = await _verify_email(fresh, token)
        assert resp.status_code == 401
        outcomes.append(resp.json())

        first = outcomes[0]
        for body in outcomes:
            assert body["type"] == first["type"]
            assert body["title"] == first["title"]
            assert body["status"] == 401


async def test_verify_requires_exact_origin(runtime_env):
    """Login-CSRF posture — the verify POST enforces exact-Origin and is
    never relaxed for the fragment flow (T-312-04)."""
    env = runtime_env
    await _reset_buckets(env)
    import httpx

    transport = httpx.ASGITransport(app=env["app"])
    async with httpx.AsyncClient(
        transport=transport, base_url=ORIGIN
    ) as fresh:
        await _request_email(fresh, "origin@example.com")
        rows = await _account_rows(env, email="origin@example.com")
        token = _payload_token(env, rows[-1])
        resp = await _verify_email(fresh, token, origin=None)
        assert resp.status_code == 403, resp.text
        resp = await _verify_email(fresh, token, origin="https://evil.example")
        assert resp.status_code == 403, resp.text


async def test_auth_email_page_serves_shell(runtime_env):
    """GET /auth/email renders the fragment landing shell — the token
    never reaches the server (D-08)."""
    env = runtime_env
    merchant = await _merchant(env)
    resp = await env["client"].get(
        f"/infinitemarkets/auth/email?shop={merchant['pubkey']}"
    )
    assert resp.status_code == 200, resp.text
    assert "public_auth_email.js" in resp.text
    assert "gm-email-auth" in resp.text
    assert resp.headers["referrer-policy"] == "no-referrer"


async def test_challenge_capability_flags(runtime_env):
    """/nostr/challenge discloses host capabilities (email_signin,
    nostr_signin) alongside nsec_signin — never a per-account oracle."""
    env = runtime_env
    resp = await env["client"].get(f"{PUB}/nostr/challenge")
    assert resp.status_code == 200
    body = resp.json()
    assert "email_signin" in body
    assert "nostr_signin" in body
    assert "nsec_signin" in body
    assert body["nostr_signin"] is True  # seeded inbox_state='active'


async def test_public_auth_email_js_safety(runtime_env):
    """The landing JS sources the token ONLY from GM.orderToken() (the
    storefront module owns the §5.4 fragment strip), defines its own
    api/shopQuery path, and never touches innerHTML."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    src = (
        root / "infinitemarkets/static/infinitemarkets/js"
        / "public_auth_email.js"
    ).read_text()
    assert "GM.orderToken()" in src
    assert "GM.h" in src
    assert ".innerHTML" not in src
    assert "location.hash.slice" not in src
    # Self-contained call path — GM.api alone would hit the wrong URL.
    assert '"/infinitemarkets/api/v1/public"' in src
    template = (
        root / "infinitemarkets/templates/infinitemarkets"
        / "public_auth_email.html"
    ).read_text()
    assert "defer" in template
