"""Buyer account foundation — m008 schema, session compat, union history,
symmetric claim, verified-email attribution (03.1-01, D-01..D-04/D-09).

Covers: partial-unique identity columns on ``buyer_accounts``, the
row-preserving ``buyer_sessions`` rebuild (legacy ``account_id IS NULL``
sessions resolve unchanged), the in-migration ``contact_enc`` +
session→account backfills (re-runnable, malformed-row tolerant), account
get-or-create on sign-in, the pubkey+email union on ``/nostr/orders``,
identity-symmetric ``/nostr/claim``, and verified-email checkout
attribution.
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
    as test_nostr_signin.py."""
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
            "display_name": "accounts shop",
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
        json={"name": "accounts", "default_currency": "SAT"},
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
    """Full challenge -> sign -> verify; the httpx jar keeps the cookie."""
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


async def _reset_buckets(env: dict) -> None:
    """Shared testclient IP — sign-in/claim buckets accumulate across
    tests (plan-02's email buckets join the same hygiene)."""
    from infinitemarkets.db import DomainTransaction

    async with DomainTransaction() as tx:
        await tx.execute(
            "DELETE FROM rate_limit_buckets"
            " WHERE bucket LIKE 'nostr%' OR bucket LIKE 'email%'"
            " OR bucket LIKE 'checkout%'"
        )


async def _web_order(env: dict, product_d: str, *, email=None,
                     client=None) -> tuple[dict, str]:
    """A web checkout -> (order row, private token). Without ``client`` a
    fresh anonymous client is used so no leftover session attributes."""
    import httpx

    merchant = await _merchant(env)
    payload = {
        "merchant_pubkey": merchant["pubkey"],
        "items": [{"d_tag": product_d, "quantity": 1}],
        "email_opt_in": False,
    }
    if email is not None:
        payload["email"] = email
    headers = {
        "Idempotency-Key": uuid.uuid4().hex,
        "Origin": ORIGIN,
    }
    if client is None:
        transport = httpx.ASGITransport(app=env["app"])
        async with httpx.AsyncClient(
            transport=transport, base_url=ORIGIN
        ) as anon:
            resp = await anon.post(f"{PUB}/checkout", json=payload,
                                   headers=headers)
    else:
        resp = await client.post(f"{PUB}/checkout", json=payload,
                                 headers=headers)
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


async def _bind_buyer(env: dict, order_id: str, buyer_hex: str) -> None:
    """Bind an order by pubkey — same fields the real paths write."""
    crypto = _crypto()
    from infinitemarkets.db import DomainTransaction

    settings = _settings()
    ver = settings.active_key_version
    async with DomainTransaction() as tx:
        await tx.execute(
            "UPDATE orders SET buyer_pubkey_enc = :e,"
            " buyer_pubkey_hash = :h WHERE id = :o",
            {
                "e": crypto.encrypt(
                    buyer_hex.encode(), settings.master_keys[ver],
                    record_id=order_id, table="orders",
                    column="buyer_pubkey_enc", key_version=ver,
                ),
                "h": _pubkey_hash(env, buyer_hex),
                "o": order_id,
            },
        )


async def _bind_email(env: dict, order_id: str, email: str) -> None:
    """Bind an order by email hash — hash-only (D-03, no *_enc column)."""
    from infinitemarkets.db import DomainTransaction

    async with DomainTransaction() as tx:
        await tx.execute(
            "UPDATE orders SET buyer_email_hash = :h WHERE id = :o",
            {"h": _email_hash(env, email), "o": order_id},
        )


async def _legacy_session(env: dict, pubkey_hex: str) -> str:
    """Craft a pre-m008 session row: ``account_id NULL`` with the pubkey
    pair written under the session-id AAD — exactly what m007 minted."""
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


async def _email_session(env: dict, email: str) -> tuple[str, str, str]:
    """Craft an email-only account + session (the plan-02 mint path's
    row shape): returns (cookie token, account_id, email_hash)."""
    crypto = _crypto()
    from infinitemarkets.db import DomainTransaction

    settings = _settings()
    ver = settings.active_key_version
    account_id = uuid.uuid4().hex
    session_id = uuid.uuid4().hex
    token = crypto.generate_public_token()
    now = int(time.time())
    email_hash = _email_hash(env, email)
    async with DomainTransaction() as tx:
        await tx.execute(
            "INSERT INTO buyer_accounts (id, merchant_id, email_enc,"
            " email_hash, created_at, updated_at)"
            " VALUES (:i, :m, :e, :h, :n, :n)",
            {
                "i": account_id,
                "m": env["merchant_id"],
                "e": crypto.encrypt(
                    email.encode(), settings.master_keys[ver],
                    record_id=account_id, table="buyer_accounts",
                    column="email_enc", key_version=ver,
                ),
                "h": email_hash,
                "n": now,
            },
        )
        await tx.execute(
            "INSERT INTO buyer_sessions (id, merchant_id, token_hash,"
            " account_id, expires_at, created_at)"
            " VALUES (:i, :m, :t, :a, :x, :n)",
            {
                "i": session_id,
                "m": env["merchant_id"],
                "t": crypto.token_lookup_hash(token).hex(),
                "a": account_id,
                "x": now + 86400,
                "n": now,
            },
        )
    return token, account_id, email_hash


# --- m008 schema + migration behavior on an isolated scratch database --------


@pytest_asyncio.fixture(loop_scope="session")
async def scratch_db(tmp_path_factory):
    """An isolated ``ext_m008test`` Database — its own SQLite file / own
    PostgreSQL schema — so m001..m008 run against a virgin schema without
    touching the booted extension database."""
    from lnbits.db import Database
    from lnbits.settings import settings

    folder = tmp_path_factory.mktemp("m008-db")
    previous = settings.lnbits_data_folder
    settings.lnbits_data_folder = str(folder)
    try:
        database = Database("ext_m008test")
    finally:
        settings.lnbits_data_folder = previous
    yield database
    from lnbits.db import POSTGRES

    if database.type == POSTGRES:
        async with database.connect() as conn:
            await conn.execute("DROP SCHEMA IF EXISTS m008test CASCADE")
    await database.engine.dispose()


async def _run_migrations(conn, names):
    from infinitemarkets import migrations

    for name in names:
        await getattr(migrations, name)(conn)


_MIGRATIONS_PRE_008 = (
    "m001_initial",
    "m002_orders",
    "m003_checkout_safety",
    "m004_digital_delivery",
    "m005_order_archiving",
    "m006_gamma_inbox",
    "m007_nostr_signin",
)


def _scratch_settings():
    """A self-contained ExtSettings — no INFINITEMARKETS_* env needed."""
    from infinitemarkets.settings import ExtSettings

    return ExtSettings(
        master_keys={"v1": b"k" * 32},
        active_key_version="v1",
        privacy_key=b"p" * 32,
        public_base_url=ORIGIN,
    )


async def _scratch_seed(conn) -> None:
    """Two merchants, an order with a real contact_enc, one with a
    garbage contact_enc, and three pre-m008 sessions (two sharing a
    pubkey, one with an undecryptable ciphertext)."""
    crypto = _crypto()
    st = _scratch_settings()
    ver = st.active_key_version
    key = st.master_keys[ver]
    for mid in ("sm1", "sm2"):
        await conn.execute(
            "INSERT INTO merchants (id, user_id, pubkey, key_ref,"
            " wallet_id_enc, wallet_id_hash)"
            " VALUES (:m, :u, :p, :k, :w, :wh)",
            {"m": mid, "u": f"u-{mid}", "p": f"pk-{mid}", "k": f"kr-{mid}",
             "w": b"w" * 40, "wh": f"wh-{mid}"},
        )
    contact = crypto.encrypt(
        json.dumps({"email": "Backfill@Example.com ", "phone": None}).encode(),
        key, record_id="s-order-1", table="orders", column="contact_enc",
        key_version=ver,
    )
    await conn.execute(
        "INSERT INTO orders (id, merchant_id, protocol, state, contact_enc)"
        " VALUES ('s-order-1', 'sm1', 'web', 'received', :c)",
        {"c": contact},
    )
    await conn.execute(
        "INSERT INTO orders (id, merchant_id, protocol, state, contact_enc)"
        " VALUES ('s-order-2', 'sm1', 'web', 'received', :c)",
        {"c": b"not-an-envelope"},
    )
    pubkey_hex = "ab" * 32
    ph = crypto.hmac_index(
        st.privacy_key, crypto.PURPOSE_BUYER_PUBKEY, "sm1",
        crypto.normalize(pubkey_hex),
    )
    enc = crypto.encrypt(
        pubkey_hex.encode(), key, record_id="s-sess-1",
        table="buyer_sessions", column="buyer_pubkey_enc", key_version=ver,
    )
    await conn.execute(
        "INSERT INTO buyer_sessions (id, merchant_id, token_hash,"
        " buyer_pubkey_enc, buyer_pubkey_hash, expires_at, created_at)"
        " VALUES ('s-sess-1', 'sm1', 'st1', :e, :h, 99999999, 111)",
        {"e": enc, "h": ph},
    )
    await conn.execute(
        "INSERT INTO buyer_sessions (id, merchant_id, token_hash,"
        " buyer_pubkey_enc, buyer_pubkey_hash, expires_at, created_at)"
        " VALUES ('s-sess-2', 'sm1', 'st2', NULL, :h, 99999999, 112)",
        {"h": ph},
    )
    # A pubkey whose only session ciphertext is undecryptable — no account
    # may be minted for it (the sessions stay on the legacy read path).
    ph2 = crypto.hmac_index(
        st.privacy_key, crypto.PURPOSE_BUYER_PUBKEY, "sm1", "deadbeef"
    )
    await conn.execute(
        "INSERT INTO buyer_sessions (id, merchant_id, token_hash,"
        " buyer_pubkey_enc, buyer_pubkey_hash, expires_at, created_at)"
        " VALUES ('s-sess-3', 'sm1', 'st3', :e, :h, 99999999, 113)",
        {"e": b"junk", "h": ph2},
    )


async def test_m008_schema_shape(scratch_db):
    """Fresh m008 schema: buyer_accounts partial-unique identities,
    email_signin_tokens, rebuilt buyer_sessions (account_id + nullable
    pubkey hash), orders.buyer_email_hash, email_queue.payload_enc,
    nostr_challenges.purpose/account_id."""
    async with scratch_db.connect() as conn:
        await _run_migrations(conn, _MIGRATIONS_PRE_008 + ("m008_buyer_accounts",))
        await conn.execute(
            "INSERT INTO merchants (id, user_id, pubkey, key_ref,"
            " wallet_id_enc, wallet_id_hash)"
            " VALUES ('m1', 'u1', 'pk1', 'kr1', :w, 'wh')",
            {"w": b"w" * 40},
        )
        # Partial unique: duplicate email_hash fails, NULLs coexist.
        await conn.execute(
            "INSERT INTO buyer_accounts (id, merchant_id, email_hash)"
            " VALUES ('a1', 'm1', 'eh1')"
        )
        with pytest.raises(Exception):
            await conn.execute(
                "INSERT INTO buyer_accounts (id, merchant_id, email_hash)"
                " VALUES ('a2', 'm1', 'eh1')"
            )
        await conn.execute(
            "INSERT INTO buyer_accounts (id, merchant_id)"
            " VALUES ('a3', 'm1')"
        )
        await conn.execute(
            "INSERT INTO buyer_accounts (id, merchant_id)"
            " VALUES ('a4', 'm1')"
        )
        # Merchant scope: same email_hash under a different merchant is
        # fine; the pubkey partial-unique index behaves identically.
        await conn.execute(
            "INSERT INTO merchants (id, user_id, pubkey, key_ref,"
            " wallet_id_enc, wallet_id_hash)"
            " VALUES ('m2', 'u2', 'pk2', 'kr2', :w, 'wh2')",
            {"w": b"w" * 40},
        )
        await conn.execute(
            "INSERT INTO buyer_accounts (id, merchant_id, email_hash)"
            " VALUES ('a5', 'm2', 'eh1')"
        )
        await conn.execute(
            "INSERT INTO buyer_accounts (id, merchant_id, pubkey_hash)"
            " VALUES ('a6', 'm2', 'ph-dup')"
        )
        with pytest.raises(Exception):
            await conn.execute(
                "INSERT INTO buyer_accounts (id, merchant_id, pubkey_hash)"
                " VALUES ('a7', 'm2', 'ph-dup')"
            )
        await conn.execute(
            "INSERT INTO buyer_accounts (id, merchant_id, pubkey_hash)"
            " VALUES ('a8', 'm1', 'ph-dup')"
        )  # same hash on another merchant is fine

        # Rebuilt buyer_sessions: account_id + NULL buyer_pubkey_hash.
        await conn.execute(
            "INSERT INTO buyer_sessions (id, merchant_id, token_hash,"
            " account_id, expires_at, created_at)"
            " VALUES ('es1', 'm1', 'et1', 'a1', 999, 1)"
        )
        # email_signin_tokens / orders.buyer_email_hash /
        # email_queue.payload_enc / nostr_challenges.purpose+account_id.
        await conn.execute(
            "INSERT INTO email_signin_tokens (id, merchant_id, token_hash,"
            " email_hash, purpose, expires_at)"
            " VALUES ('t1', 'm1', 'th1', 'eh1', 'signin', 999)"
        )
        await conn.execute(
            "INSERT INTO orders (id, merchant_id, protocol, state,"
            " buyer_email_hash) VALUES ('o1', 'm1', 'web', 'received', 'eh1')"
        )
        await conn.execute(
            "INSERT INTO email_queue (id, merchant_id, channel, event_type,"
            " recipient_enc, recipient_hash, state, payload_enc)"
            " VALUES ('q1', 'm1', 'account', 'signin_link', :r, 'rh1',"
            " 'pending', :p)",
            {"r": b"r" * 40, "p": b"p" * 40},
        )
        await conn.execute(
            "INSERT INTO nostr_challenges (id, merchant_id, challenge_hash,"
            " scope_hash, expires_at, purpose, account_id)"
            " VALUES ('c1', 'm1', 'ch1', 'sh1', 999, 'link', 'a1')"
        )


async def test_m008_rebuild_preserves_and_backfills(scratch_db):
    """The rebuild preserves every session row verbatim plus the joined
    account_id; the orders backfill decrypts contact_enc, skips malformed
    rows, and re-running either helper is a no-op."""
    crypto = _crypto()
    st = _scratch_settings()
    async with scratch_db.connect() as conn:
        await _run_migrations(conn, _MIGRATIONS_PRE_008)
        await _scratch_seed(conn)
        before = await conn.fetchone(
            "SELECT COUNT(*) AS n FROM buyer_sessions"
        )
        await _run_migrations(conn, ("m008_buyer_accounts",))
        after = await conn.fetchall(
            "SELECT * FROM buyer_sessions ORDER BY created_at"
        )
        assert len(after) == before["n"] == 3
        # Both pubkey sessions joined the single minted account.
        accounts = await conn.fetchall("SELECT * FROM buyer_accounts")
        assert len(accounts) == 1
        account = dict(accounts[0])
        assert account["email_hash"] is None
        expected_ph = crypto.hmac_index(
            st.privacy_key, crypto.PURPOSE_BUYER_PUBKEY, "sm1",
            crypto.normalize("ab" * 32),
        )
        assert account["pubkey_hash"] == expected_ph
        # The pubkey ciphertext was re-encrypted under the account id AAD.
        ver = crypto.envelope_version(account["pubkey_enc"])
        plaintext = crypto.decrypt(
            account["pubkey_enc"], st.master_keys[ver],
            record_id=account["id"], table="buyer_accounts",
            column="pubkey_enc", key_version=ver,
        ).decode()
        assert plaintext == "ab" * 32
        assert after[0]["account_id"] == account["id"]
        assert after[1]["account_id"] == account["id"]
        # The undecryptable session keeps the legacy NULL path.
        assert after[2]["account_id"] is None
        # Order backfill: real contact hash-written, garbage skipped.
        o1 = await conn.fetchone(
            "SELECT buyer_email_hash FROM orders WHERE id = 's-order-1'"
        )
        assert o1["buyer_email_hash"] == crypto.hmac_index(
            st.privacy_key, crypto.PURPOSE_BUYER_EMAIL, "sm1",
            crypto.normalize("Backfill@Example.com "),
        )
        o2 = await conn.fetchone(
            "SELECT buyer_email_hash FROM orders WHERE id = 's-order-2'"
        )
        assert o2["buyer_email_hash"] is None
        # Re-running the helpers is a no-op (re-runnable migration).
        from infinitemarkets.migrations import (
            _backfill_buyer_email_hashes,
            _backfill_session_accounts,
        )

        assert await _backfill_buyer_email_hashes(conn, settings=st) == 0
        assert await _backfill_session_accounts(conn, settings=st) == 0


async def test_m008_backfill_restores_nulled_hash(runtime_env):
    """A real web checkout writes buyer_email_hash at intake; nulling it
    and re-running the helper on the live conn restores it; a garbage
    contact_enc row is skipped without raising."""
    env = runtime_env
    product = await env["make_product"](f"bf-{uuid.uuid4().hex[:6]}", 5)
    order, _ = await _web_order(env, product["d_tag"], email="backfill@example.com")
    expected = _email_hash(env, "backfill@example.com")
    assert order["buyer_email_hash"] == expected

    from infinitemarkets.db import DomainTransaction

    async with DomainTransaction() as tx:
        await tx.execute(
            "UPDATE orders SET buyer_email_hash = NULL WHERE id = :o",
            {"o": order["id"]},
        )
        # A contact_enc row that cannot decrypt — skipped, not fatal.
        await tx.execute(
            "INSERT INTO orders (id, merchant_id, protocol, state,"
            " contact_enc) VALUES (:i, :m, 'web', 'received', :c)",
            {"i": uuid.uuid4().hex, "m": env["merchant_id"], "c": b"junk"},
        )
    from infinitemarkets.migrations import _backfill_buyer_email_hashes

    async with env["ext_module"].db.connect() as conn:
        updated = await _backfill_buyer_email_hashes(conn)
        row = await conn.fetchone(
            "SELECT buyer_email_hash FROM infinitemarkets.orders"
            " WHERE id = :o",
            {"o": order["id"]},
        )
    assert updated >= 1
    assert row["buyer_email_hash"] == expected


# --- account-scoped sessions (D-02) ------------------------------------------


async def test_signin_creates_and_reuses_account(runtime_env):
    """NIP-07 sign-in mints the buyer_accounts row and points the session
    at it; re-signing with the same key reuses the account."""
    import httpx

    env = runtime_env
    await _reset_buckets(env)
    transport = httpx.ASGITransport(app=env["app"])
    async with httpx.AsyncClient(
        transport=transport, base_url=ORIGIN
    ) as fresh:
        await _signin(fresh, "acct-buyer-1")
        ph = _pubkey_hash(env, _buyer_hex("acct-buyer-1"))
        async with env["ext_module"].db.connect() as conn:
            account = await conn.fetchone(
                "SELECT * FROM infinitemarkets.buyer_accounts"
                " WHERE merchant_id = :m AND pubkey_hash = :h",
                {"m": env["merchant_id"], "h": ph},
            )
            session = await conn.fetchone(
                "SELECT * FROM infinitemarkets.buyer_sessions"
                " WHERE merchant_id = :m AND buyer_pubkey_hash = :h"
                " ORDER BY created_at DESC LIMIT 1",
                {"m": env["merchant_id"], "h": ph},
            )
        assert account is not None, "sign-in must create the account row"
        assert account["pubkey_enc"] is not None
        assert session["account_id"] == account["id"]
        # The compat columns stay populated on pubkey sessions.
        assert session["buyer_pubkey_enc"] is not None

        # Re-sign-in reuses the same account (get-or-create, not insert).
        await _reset_buckets(env)
        await _signin(fresh, "acct-buyer-1")
        async with env["ext_module"].db.connect() as conn:
            count = await conn.fetchone(
                "SELECT COUNT(*) AS n FROM infinitemarkets.buyer_accounts"
                " WHERE merchant_id = :m AND pubkey_hash = :h",
                {"m": env["merchant_id"], "h": ph},
            )
            sessions = await conn.fetchone(
                "SELECT COUNT(*) AS n FROM infinitemarkets.buyer_sessions"
                " WHERE merchant_id = :m AND account_id = :a",
                {"m": env["merchant_id"], "a": account["id"]},
            )
        assert count["n"] == 1
        assert sessions["n"] == 2


async def test_legacy_session_still_resolves(runtime_env):
    """A pre-m008 session (account_id NULL) resolves on the unchanged
    pubkey path: /nostr/profile and /nostr/orders work."""
    import httpx

    env = runtime_env
    token = await _legacy_session(env, _buyer_hex("legacy-buyer"))
    transport = httpx.ASGITransport(app=env["app"])
    async with httpx.AsyncClient(
        transport=transport, base_url=ORIGIN
    ) as fresh:
        fresh.cookies.set("gm_nostr_session", token)
        resp = await fresh.get(f"{PUB}/nostr/profile")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["pubkey"] == _buyer_hex("legacy-buyer")
        assert body["npub"].startswith("npub1")
        assert body["email"] is None
        resp = await fresh.get(f"{PUB}/nostr/orders")
        assert resp.status_code == 200, resp.text


async def test_email_only_session_profile_and_orders(runtime_env):
    """An email-only session resolves: /nostr/profile returns null pubkey
    fields + the verified email; /nostr/orders returns email-bound orders;
    POST /nostr/profile refuses honestly before any nostr_sdk work."""
    import httpx

    env = runtime_env
    token, _account_id, _email_hash = await _email_session(
        env, "verified@example.com"
    )
    order, _ = await _web_order(
        env, (await env["make_product"](f"e-{uuid.uuid4().hex[:6]}", 5))["d_tag"]
    )
    await _bind_email(env, order["id"], "verified@example.com")

    transport = httpx.ASGITransport(app=env["app"])
    async with httpx.AsyncClient(
        transport=transport, base_url=ORIGIN
    ) as fresh:
        fresh.cookies.set("gm_nostr_session", token)
        resp = await fresh.get(f"{PUB}/nostr/profile")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["pubkey"] is None
        assert body["npub"] is None
        assert body["profile"] is None
        assert body["email"] == "verified@example.com"

        resp = await fresh.get(f"{PUB}/nostr/orders")
        assert resp.status_code == 200, resp.text
        ids = {o["order_id"] for o in resp.json()["orders"]}
        assert order["id"] in ids

        # Kind-0 publish is honestly refused — no key to author with.
        resp = await fresh.post(
            f"{PUB}/nostr/profile",
            json={"event": "{}"},
            headers={"Origin": ORIGIN},
        )
        assert resp.status_code == 422, resp.text
        assert resp.json()["type"].endswith("nostr-identity-required")


async def test_session_fails_closed_on_retired_account(runtime_env):
    """A session pointing at a retired account resolves to None — the
    identical 401 as an expired/unknown cookie (T-311-01)."""
    import httpx

    env = runtime_env
    token, account_id, _hash = await _email_session(env, "retired@example.com")
    from infinitemarkets.db import DomainTransaction

    async with DomainTransaction() as tx:
        await tx.execute(
            "UPDATE buyer_accounts SET retired_at = :n WHERE id = :a",
            {"n": int(time.time()), "a": account_id},
        )
    transport = httpx.ASGITransport(app=env["app"])
    async with httpx.AsyncClient(
        transport=transport, base_url=ORIGIN
    ) as fresh:
        fresh.cookies.set("gm_nostr_session", token)
        resp = await fresh.get(f"{PUB}/nostr/orders")
        assert resp.status_code == 401, resp.text
        assert resp.json()["status"] == 401


# --- union history + symmetric claim (D-03/D-04/D-09) -------------------------


async def test_union_history_dual_identity(runtime_env):
    """An account holding BOTH identities sees pubkey-bound and
    email-bound orders in one union; a different account's orders never
    appear."""
    import httpx

    env = runtime_env
    crypto = _crypto()
    await _reset_buckets(env)
    product = await env["make_product"](f"u-{uuid.uuid4().hex[:6]}", 10)
    by_pubkey, _ = await _web_order(env, product["d_tag"])
    by_email, _ = await _web_order(env, product["d_tag"])
    foreign, _ = await _web_order(env, product["d_tag"])

    buyer_hex = _buyer_hex("union-buyer")
    await _bind_buyer(env, by_pubkey["id"], buyer_hex)
    await _bind_email(env, by_email["id"], "union@example.com")
    await _bind_email(env, foreign["id"], "someone-else@example.com")

    transport = httpx.ASGITransport(app=env["app"])
    async with httpx.AsyncClient(
        transport=transport, base_url=ORIGIN
    ) as fresh:
        await _signin(fresh, "union-buyer")
        # Give the signed-in account its second identity — the same row
        # the link flow (plan 02) would produce.
        settings = _settings()
        ver = settings.active_key_version
        async with env["ext_module"].db.connect() as conn:
            account = await conn.fetchone(
                "SELECT id FROM infinitemarkets.buyer_accounts"
                " WHERE merchant_id = :m AND pubkey_hash = :h",
                {"m": env["merchant_id"], "h": _pubkey_hash(env, buyer_hex)},
            )
        from infinitemarkets.db import DomainTransaction

        async with DomainTransaction() as tx:
            await tx.execute(
                "UPDATE buyer_accounts SET email_enc = :e, email_hash = :h"
                " WHERE id = :a",
                {
                    "e": crypto.encrypt(
                        b"union@example.com", settings.master_keys[ver],
                        record_id=account["id"], table="buyer_accounts",
                        column="email_enc", key_version=ver,
                    ),
                    "h": _email_hash(env, "union@example.com"),
                    "a": account["id"],
                },
            )
        resp = await fresh.get(f"{PUB}/nostr/orders")
        assert resp.status_code == 200, resp.text
        ids = {o["order_id"] for o in resp.json()["orders"]}
        assert by_pubkey["id"] in ids  # bound by pubkey hash
        assert by_email["id"] in ids   # bound by email hash
        assert foreign["id"] not in ids  # different account's binding


async def test_claim_binds_email_and_keeps_no_oracle(runtime_env):
    """An email-only session's claim binds buyer_email_hash under the
    same per-column CAS; a foreign-bound order and a dead token produce
    the identical 401 and leave the order unmutated."""
    import httpx

    env = runtime_env
    product = await env["make_product"](f"ce-{uuid.uuid4().hex[:6]}", 10)
    unbound, token_unbound = await _web_order(env, product["d_tag"])
    foreign, token_foreign = await _web_order(env, product["d_tag"])
    await _bind_email(env, foreign["id"], "other@example.com")

    token, _, email_hash = await _email_session(env, "claimer@example.com")
    await _reset_buckets(env)
    transport = httpx.ASGITransport(app=env["app"])
    async with httpx.AsyncClient(
        transport=transport, base_url=ORIGIN
    ) as fresh:
        fresh.cookies.set("gm_nostr_session", token)
        resp = await fresh.post(
            f"{PUB}/nostr/claim",
            json={"token": token_unbound},
            headers={"Origin": ORIGIN},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["claimed"] is True

        async with env["ext_module"].db.connect() as conn:
            row = await conn.fetchone(
                "SELECT buyer_email_hash, buyer_pubkey_hash"
                " FROM infinitemarkets.orders WHERE id = :o",
                {"o": unbound["id"]},
            )
            event = await conn.fetchone(
                "SELECT actor FROM infinitemarkets.order_events"
                " WHERE order_id = :o"
                " AND detail_json LIKE '%buyer-claimed%'",
                {"o": unbound["id"]},
            )
        assert row["buyer_email_hash"] == email_hash
        assert row["buyer_pubkey_hash"] is None
        assert event is not None and event["actor"] == "buyer"

        # Repeat claim is the idempotent no-op.
        resp = await fresh.post(
            f"{PUB}/nostr/claim",
            json={"token": token_unbound},
            headers={"Origin": ORIGIN},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["already_linked"] is True

        # A foreign-bound order and a dead token share the identical 401.
        resp_foreign = await fresh.post(
            f"{PUB}/nostr/claim",
            json={"token": token_foreign},
            headers={"Origin": ORIGIN},
        )
        resp_dead = await fresh.post(
            f"{PUB}/nostr/claim",
            json={"token": "A" * 43},
            headers={"Origin": ORIGIN},
        )
        assert resp_foreign.status_code == 401
        assert resp_dead.status_code == 401
        assert resp_foreign.json() == resp_dead.json()

    async with env["ext_module"].db.connect() as conn:
        row = await conn.fetchone(
            "SELECT buyer_email_hash FROM infinitemarkets.orders"
            " WHERE id = :o",
            {"o": foreign["id"]},
        )
    assert row["buyer_email_hash"] == _email_hash(env, "other@example.com")


# --- verified-email checkout attribution (D-03) -------------------------------


async def test_checkout_attribution_verified_email(runtime_env):
    """An email-only session's checkout binds the account's VERIFIED
    email hash — never the unverified form email, which still lands in
    contact_enc unchanged. Anonymous checkouts hash the form email; no
    email leaves NULL."""
    import httpx

    env = runtime_env
    crypto = _crypto()
    settings = _settings()
    product = await env["make_product"](f"attr-{uuid.uuid4().hex[:6]}", 10)
    token, _, email_hash = await _email_session(env, "attr-verified@example.com")

    await _reset_buckets(env)
    transport = httpx.ASGITransport(app=env["app"])
    async with httpx.AsyncClient(
        transport=transport, base_url=ORIGIN
    ) as fresh:
        fresh.cookies.set("gm_nostr_session", token)
        # Form email differs from the verified identity on purpose.
        order, _ = await _web_order(
            env, product["d_tag"], email="form@example.com", client=fresh
        )
    assert order["buyer_email_hash"] == email_hash
    # The form email is untouched in contact_enc.
    ver = crypto.envelope_version(order["contact_enc"])
    contact = json.loads(
        crypto.decrypt(
            order["contact_enc"], settings.master_keys[ver],
            record_id=order["id"], table="orders", column="contact_enc",
            key_version=ver,
        )
    )
    assert contact["email"] == "form@example.com"

    # Anonymous checkout with a form email binds the form email's hash
    # (the D-09 auto-bind seed); no email writes NULL.
    await _reset_buckets(env)
    order2, _ = await _web_order(env, product["d_tag"], email="anon@example.com")
    assert order2["buyer_email_hash"] == _email_hash(env, "anon@example.com")

    await _reset_buckets(env)
    order3, _ = await _web_order(env, product["d_tag"])
    assert order3["buyer_email_hash"] is None
