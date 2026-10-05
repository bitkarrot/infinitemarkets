"""Launch a real LNbits + infinitemarkets server for Playwright E2E.

Boots the pinned host through uvicorn with the same posture as the
runtime suite (FakeWallet, extension symlinked into a tmp
LNBITS_EXTENSIONS_PATH, INFINITEMARKETS_* env), plus a real local Nostr
relay (harness.relay.LocalRelay) so outbox publication produces genuine
positive-ACK evidence instead of external-relay failures. Seeds an
account/wallet/merchant/catalog/products + one live order via the real
HTTP APIs and the real publish path, then serves until killed.

Two harness-only routes are registered on the app AFTER startup —
``/_e2e/settle`` (pays the order's invoice through FakeWallet and runs
the same settlement calls the listener makes) and ``/_e2e/seed`` (the
seed JSON the Playwright specs read). Neither touches shipped code.

    uv run python tools/e2e_server.py          # http://127.0.0.1:5099
    GM_E2E_PORT=5200 uv run python tools/e2e_server.py
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path

from fastapi import Header, Request  # noqa: F401 — route annotations

REPO_ROOT = Path(__file__).resolve().parents[1]
PKG_DIR = REPO_ROOT / "infinitemarkets"
sys.path.insert(0, str(REPO_ROOT))

PORT = int(os.environ.get("GM_E2E_PORT", "5099"))
# Served over HTTPS so the real browser satisfies the §5.1 invariant
# (cookie mutations require Origin == INFINITEMARKETS_PUBLIC_BASE_URL, and
# that setting must be an https:// origin). A throwaway self-signed cert
# is generated per run; the seed client + Playwright ignore verification.
BASE_URL = f"https://localhost:{PORT}"
SEED_PATH = Path(os.environ.get(
    "GM_E2E_SEED_PATH", str(REPO_ROOT / "tests" / "e2e" / ".seed.json"),
))

# Fixed merchant identity so public URLs are stable across server
# restarts (test-only key — the E2E database is disposable).
E2E_NSEC = (
    "nsec1qyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqstywftw"
)
E2E_PUBKEY = (
    "1b84c5567b126440995d3ed5aaba0565d71e1834604819ff9c17f5e9d5dd078f"
)

# All environment must be set BEFORE any lnbits import — `settings` and
# `lnbits.core.db.db` bind these values at construction. Setting them as
# attributes later leaves the core DB bound to ./data (repo root), which
# carries stale install/deactivation state across runs.
TMP = Path(tempfile.mkdtemp(prefix="gm-e2e-"))
EXT_DIR = TMP / "extroot" / "extensions"
DATA_DIR = TMP / "data"
EXT_DIR.mkdir(parents=True)
(EXT_DIR / "infinitemarkets").symlink_to(PKG_DIR, target_is_directory=True)
DATA_DIR.mkdir()

os.environ.update(
    {
        "INFINITEMARKETS_MASTER_KEYS": json.dumps(
            {"v1": base64.b64encode(b"k" * 32).decode()}
        ),
        "INFINITEMARKETS_ACTIVE_KEY_VERSION": "v1",
        "INFINITEMARKETS_PRIVACY_KEY": base64.b64encode(b"p" * 32).decode(),
        "INFINITEMARKETS_PUBLIC_BASE_URL": BASE_URL,
        # Real relay I/O against the local LocalRelay — deterministic
        # positive ACKs, no external relay dependency.
        "INFINITEMARKETS_RELAY_IO": "on",
        # TEST-ONLY escape hatch: permits ws:// loopback relay targets.
        "INFINITEMARKETS_ALLOW_INSECURE_RELAYS": "1",
        # Host settings via env so they are in place at settings/db
        # construction — not just attribute assignment after the fact.
        "LNBITS_DATA_FOLDER": str(DATA_DIR),
        "LNBITS_EXTENSIONS_PATH": str(TMP / "extroot"),
        "LNBITS_EXTENSIONS_DEACTIVATE_ALL": "false",
        "LNBITS_BACKEND_WALLET_CLASS": "FakeWallet",
        # Dummy SMTP so is_email_notifications_configured() is True and
        # the email sign-in method is enabled. Send attempts fail fast
        # on connection-refused (bounded worker retry) — /_e2e/mailbox
        # reads the durable queue rows regardless of send state.
        "LNBITS_EMAIL_NOTIFICATIONS_ENABLED": "true",
        "LNBITS_EMAIL_NOTIFICATIONS_EMAIL": "e2e@example.com",
        "LNBITS_EMAIL_NOTIFICATIONS_SERVER": "127.0.0.1",
        "LNBITS_EMAIL_NOTIFICATIONS_PORT": "10025",
        "LNBITS_EMAIL_NOTIFICATIONS_USERNAME": "e2e",
        "LNBITS_EMAIL_NOTIFICATIONS_PASSWORD": "e2e",
        "LNBITS_ADMIN_UI": "true",
        "LNBITS_AUDIT_LOG_REQUEST_BODY": "false",
        "LNBITS_AUDIT_LOG_QUERY_PARAMS": "false",
        "LNBITS_AUDIT_LOG_PATH_PARAMS": "false",
        "FIRST_INSTALL": "true",
    }
)


async def _seed(app, seed: dict, relay_url: str) -> None:
    """Create account/wallet/merchant/catalog/products/order through the
    same paths the runtime suite uses, then run the real publish path so
    outbox intents get genuine ACKs from the local relay."""
    import httpx
    from lnbits.core.crud import create_wallet
    from lnbits.core.crud.users import create_account
    from lnbits.core.models.users import (
        Account,
        UpdateSuperuserPassword,
    )
    from lnbits.core.services import update_wallet_balance
    from lnbits.core.views.auth_api import first_install
    from lnbits.settings import settings

    # First install gates the auth API — create the superuser through the
    # host's own path (same as the runtime conftest).
    superuser = f"gqadmin-{uuid.uuid4().hex[:8]}"
    await first_install(
        UpdateSuperuserPassword(
            username=superuser,
            password="secret1234",
            password_repeat="secret1234",
            first_install_token=settings.first_install_token,
        )
    )

    # Fixed credentials so a human can log into the browser session —
    # local E2E only, never reused (fresh tmp DB per run).
    username = "admin"
    password = "adminpass123"
    account = Account(id=uuid.uuid4().hex, username=username, email=None)
    account.hash_password(password)
    await create_account(account)
    wallet = await create_wallet(user_id=account.id, wallet_name="e2e")
    await update_wallet_balance(wallet=wallet, amount=9_999_999)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=BASE_URL,
        verify=False,
    ) as client:
        resp = await client.post(
            "/api/v1/auth",
            json={"username": username, "password": password},
        )
        assert resp.status_code == 200, resp.text
        token = resp.json()["access_token"]
        # Cookie in the jar (not a raw header) so httpx merges it with the
        # gm_csrf cookie the admin API issues — a hand-set Cookie header
        # would suppress jar cookies and fail the double-submit check.
        client.cookies.set(
            "cookie_access_token", token, domain="localhost", path="/"
        )
        resp = await client.put(
            "/api/v1/extension/infinitemarkets/enable",
            headers={"Origin": BASE_URL},
        )
        assert resp.status_code == 200, resp.text

        api = "/infinitemarkets/api/v1"

        async def cookie() -> dict:
            if not client.cookies.get("gm_csrf"):
                await client.get(
                    f"{api}/merchants/current", headers={"Origin": BASE_URL}
                )
            return {
                "Origin": BASE_URL,
                "X-CSRF-Token": client.cookies.get("gm_csrf"),
            }

        resp = await client.post(
            f"{api}/merchants",
            json={"wallet_id": wallet.id, "display_name": "e2e shop"},
            headers=await cookie(),
        )
        assert resp.status_code == 201, resp.text
        mid = resp.json()["id"]

        from infinitemarkets.db import DomainTransaction
        from infinitemarkets.services import merchant as merchant_service

        # Fixed test identity so storefront/product URLs are STABLE across
        # restarts (key material is test-only; the seed DB is disposable).
        await merchant_service.import_nsec(mid, account, E2E_NSEC)

        # The merchant publishes to the LOCAL relay only — enabled, 'both'
        # direction so it serves public publish targets (and future inbox).
        # Seeded before publish() so ensure_default_relays leaves it alone.
        async with DomainTransaction() as tx:
            await tx.execute(
                f"INSERT INTO {tx.table('relay_configs')} "
                "(id, merchant_id, relay_url, direction, enabled,"
                " created_at, updated_at) VALUES (:i, :m, :u, 'both', TRUE,"
                " :t, :t)",
                {
                    "i": uuid.uuid4().hex,
                    "m": mid,
                    "u": relay_url,
                    "t": int(time.time()),
                },
            )
        pubkey = E2E_PUBKEY

        resp = await client.post(
            f"{api}/catalogs",
            json={"name": "main", "default_currency": "SAT"},
            headers=await cookie(),
        )
        cid = resp.json()["id"]

        img_base = f"{BASE_URL}/infinitemarkets/static/infinitemarkets/img"
        resp = await client.post(
            f"{api}/products",
            json={
                "catalog_id": cid,
                "d_tag": "e2e-digital-tour",
                "title": "e2e digital tour",
                "summary": "A guided digital tour experience",
                "amount_minor": 2500,
                "currency": "SAT",
                "visibility": "on-sale",
                # Generous stock — suite reruns reuse the same seed and
                # held reservations must never flip the product 'sold'.
                "stock_on_hand": 200,
                "format": "digital",
                "images": [{"url": f"{img_base}/demo-digital.svg"}],
                "delivery_content": (
                    "Download your tour: https://files.example/e2e-digital-tour.zip\n"
                    "Access code: E2E-TOUR-2026"
                ),
            },
            headers=await cookie(),
        )
        digital = resp.json()

        resp = await client.post(
            f"{api}/shipping",
            json={
                "title": "Standard mail",
                "service": "standard",
                "countries": ["US", "DE"],
                "base_price_minor": 500,
                "currency": "SAT",
            },
            headers=await cookie(),
        )
        assert resp.status_code == 201, resp.text
        shipping = resp.json()

        resp = await client.post(
            f"{api}/products",
            json={
                "catalog_id": cid,
                "d_tag": "e2e-poster",
                "title": "e2e poster",
                "summary": "Printed poster — ships tracked",
                "amount_minor": 7500,
                "currency": "SAT",
                "visibility": "on-sale",
                "stock_on_hand": 100,
                "format": "physical",
                "shipping_option_ids": [shipping["id"]],
                "images": [{"url": f"{img_base}/demo-poster.svg"}],
            },
            headers=await cookie(),
        )
        assert resp.status_code == 201, resp.text
        physical = resp.json()

        # One collection so the storefront navigation has a category link.
        resp = await client.post(
            f"{api}/collections",
            json={"title": "Featured", "description": "Staff picks"},
            headers=await cookie(),
        )
        assert resp.status_code == 201, resp.text
        collection = resp.json()
        for prod in (digital, physical):
            resp = await client.patch(
                f"{api}/products/{prod['id']}",
                json={"collection_ids": [collection["id"]]},
                headers=await cookie(),
            )
            assert resp.status_code == 200, resp.text

        # Real publish path: enqueues every aggregate intent; the outbox
        # worker signs + delivers to the local relay and flips the merchant
        # draft -> publication_pending -> active on profile ACK.
        resp = await client.post(
            f"{api}/merchants/{mid}/publish",
            headers=await cookie(),
        )
        assert resp.status_code in (200, 202), resp.text
        for _ in range(80):
            async with DomainTransaction() as tx:
                state = await tx.fetch_one(
                    f"SELECT state FROM {tx.table('merchants')} WHERE id = :m", {"m": mid}
                )
            if state and state["state"] == "active":
                break
            await asyncio.sleep(0.5)
        else:
            raise RuntimeError("merchant did not reach active via publish")

        # GAM-01 inbox activation: kind-10050 publishes to the local
        # relay through the real outbox worker; inbox_state reaches
        # 'active' only on the durable ACK. Sign-in affordance +
        # showcase/nostr_only mode gating depend on it.
        resp = await client.post(
            f"{api}/merchants/{mid}/inbox/enable",
            json={},
            headers=await cookie(),
        )
        assert resp.status_code == 200, resp.text
        for _ in range(80):
            async with DomainTransaction() as tx:
                row = await tx.fetch_one(
                    f"SELECT inbox_state FROM {tx.table('merchants')}"
                    " WHERE id = :m", {"m": mid}
                )
            if row and row["inbox_state"] == "active":
                break
            await asyncio.sleep(0.5)
        else:
            raise RuntimeError("inbox did not reach active via publish")

        # One live order so the admin Orders tab has a row on load.
        resp = await client.post(
            f"{api}/public/checkout",
            json={
                "merchant_pubkey": pubkey,
                "items": [{"d_tag": digital["d_tag"], "quantity": 1}],
            },
            headers={
                "Idempotency-Key": uuid.uuid4().hex * 2,
                "Origin": BASE_URL,
            },
        )
        assert resp.status_code == 201, resp.text
        order = resp.json()

        # One rejected intake row so the Messages -> Rejected intake
        # dialog has a mute-able entry (author_hash only — npub is
        # optional display metadata).
        rejected_id = uuid.uuid4().hex
        async with DomainTransaction() as tx:
            await tx.execute(
                f"INSERT INTO {tx.table('inbox_events')} "
                "(id, outer_event_id, merchant_id, source_relay_url,"
                " received_at, kind, processed_state, reject_reason,"
                " author_hash, processed_at)"
                " VALUES (:i, :e, :m, :r, :n, 1059, 'rejected',"
                " 'type-3 missing order tag', :h, :n)",
                {
                    "i": rejected_id,
                    "e": uuid.uuid4().hex,
                    "m": mid,
                    "r": relay_url,
                    "h": "e2e" + uuid.uuid4().hex[:29],
                    "n": int(time.time()),
                },
            )

    from infinitemarkets.services import readiness

    readiness.mark_reconciled()

    seed.update(
        {
            "base_url": BASE_URL,
            "username": username,
            "password": password,
            "access_token": token,
            "merchant_id": mid,
            "pubkey": pubkey,
            "digital": digital,
            "physical": physical,
            "shipping": shipping,
            "seeded_order_token": order["public_token"],
            "relay_url": relay_url,
            "digital_url": f"{BASE_URL}/infinitemarkets/p/{pubkey}/{digital['d_tag']}",
            "physical_url": f"{BASE_URL}/infinitemarkets/p/{pubkey}/{physical['d_tag']}",
            # The fixed NIP-07 buyer identity behind /_e2e/sign.
            "buyer_pubkey": (
                __import__(
                    "harness.sdk", fromlist=["fixed_test_keys"]
                ).fixed_test_keys("e2e-buyer").public_key().to_hex()
            ),
        }
    )


async def _settle(token: str) -> dict:
    """Pay the order's core invoice via FakeWallet and run the listener
    path — the same calls the paid-invoices stream consumer makes."""
    from lnbits.core.db import db as core_db
    from lnbits.core.services.payments import (
        update_invoice_from_paid_invoices_stream,
    )
    from lnbits.wallets import get_funding_source

    from infinitemarkets.crypto import token_lookup_hash
    from infinitemarkets.db import db

    async with db.connect() as conn:
        row = await conn.fetchone(
            "SELECT * FROM infinitemarkets.orders WHERE public_token_hash = :h",
            {"h": token_lookup_hash(token)},
        )
    if row is None:
        return {"ok": False, "error": "unknown token"}
    order = dict(row)

    async with core_db.connect() as conn:
        core = dict(
            await conn.fetchone(
                "SELECT * FROM apipayments WHERE external_id = :e",
                {"e": f"infinitemarkets:{order['id']}"},
            )
        )
    funding = get_funding_source()
    resp = await funding.pay_invoice(core["bolt11"], fee_limit_msat=10_000)
    if not resp.ok:
        return {"ok": False, "error": resp.error_message}
    settled = await update_invoice_from_paid_invoices_stream(
        core["checking_id"]
    )
    assert settled is not None

    from infinitemarkets.services.settlement import (
        _core_payments_by_external_id,  # noqa: SLF001
        invoice_listener,
    )

    payments = await _core_payments_by_external_id(
        f"infinitemarkets:{order['id']}"
    )
    await invoice_listener(payments[0])
    return {"ok": True, "order_id": order["id"]}


async def main() -> None:
    from lnbits.settings import settings

    from tools.checkout_host import host_checkout_dir

    settings.first_install = True

    # Local Nostr relay — deterministic positive ACKs for outbox
    # publication; no external relay dependency in E2E.
    from harness.relay import LocalRelay, RelayMode

    local_relay = await LocalRelay(mode=RelayMode.ACCEPTING).start()

    cert = TMP / "e2e.pem"
    key = TMP / "e2e-key.pem"
    import subprocess

    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048",
            "-keyout", str(key), "-out", str(cert),
            "-days", "1", "-nodes", "-subj", "/CN=localhost",
        ],
        check=True,
        capture_output=True,
    )

    os.chdir(host_checkout_dir())
    from lnbits.app import create_app

    app = create_app()

    seed: dict = {}

    async def e2e_seed():
        return seed

    async def e2e_settle(x_order_token: str = Header(...)):
        return await _settle(x_order_token)

    # Harness-only: sign a NIP-07-shaped event with the fixed E2E buyer
    # key so Playwright's window.nostr stub produces a REAL signed event
    # (the verify path exercises Event.verify() against it). Test-only
    # key material; the E2E database is disposable.
    def _buyer_keys(label: str = "e2e-buyer"):
        from harness.sdk import fixed_test_keys

        return fixed_test_keys(label)

    async def e2e_sign(request: Request):
        from nostr_sdk import (
            EventBuilder,
            Kind,
            NostrSigner,
            Tag,
            Timestamp,
        )

        body = await request.json()
        # Optional ``label`` picks a different fixed test key so specs
        # can exercise identities that aren't the shared e2e-buyer
        # account (e.g. linking a FRESH key — a merge needs one).
        label = str(body.get("label") or "e2e-buyer")
        builder = EventBuilder(
            Kind(int(body.get("kind", 22242))),
            str(body.get("content", "")),
        )
        tags = body.get("tags") or []
        if tags:
            builder = builder.tags([Tag.parse(t) for t in tags])
        created = body.get("created_at") or int(time.time())
        event = await builder.custom_created_at(
            Timestamp.from_secs(int(created))
        ).sign(NostrSigner.keys(_buyer_keys(label)))
        return {
            "event": json.loads(event.as_json()),
            "pubkey": _buyer_keys(label).public_key().to_hex(),
        }

    async def e2e_mode(request: Request):
        """Flip the storefront mode through the service layer — the
        admin two-step confirm stays the product path; this just keeps
        buyer specs from driving the settings UI."""
        from infinitemarkets.services import storefront_mode

        body = await request.json()
        mid = body.get("merchant_id") or seed.get("merchant_id")
        mode = body.get("mode") or "full"
        from infinitemarkets.db import db

        async with db.connect() as conn:
            merchant = await conn.fetchone(
                "SELECT * FROM infinitemarkets.merchants WHERE id = :m",
                {"m": mid},
            )
        return await storefront_mode.set_mode(
            dict(merchant), mode, confirm=True
        )

    async def e2e_mailbox(to: str = ""):
        """Inspect the durable email_queue for the newest 'account' row
        addressed to ``to`` and return its fragment sign-in link — the
        magic-link flow proven end to end with zero SMTP dependency.
        Harness-only (registered post-startup like /_e2e/sign): it
        decrypts queue custody on a disposable DB, never shipped code.
        Specs poll this — worker timing is not deterministic."""
        from infinitemarkets import crypto
        from infinitemarkets.db import db
        from infinitemarkets.settings import ext_settings

        if not to:
            return {"link": None}
        settings = ext_settings()
        async with db.connect() as conn:
            rows = await conn.fetchall(
                "SELECT * FROM infinitemarkets.email_queue"
                " WHERE channel = 'account'"
                " AND state IN ('pending','claimed','failed','suppressed')"
                " ORDER BY created_at DESC LIMIT 20"
            )
        for row in rows:
            row = dict(row)
            if not row["recipient_enc"] or not row["payload_enc"]:
                continue
            ver = crypto.envelope_version(row["recipient_enc"])
            try:
                recipient = crypto.decrypt(
                    row["recipient_enc"], settings.master_keys[ver],
                    # Orderless rows bind recipient_enc to the merchant.
                    record_id=row["merchant_id"], table="email_queue",
                    column="recipient_enc", key_version=ver,
                ).decode()
            except Exception:  # noqa: BLE001 — skip undecryptable rows
                continue
            if crypto.normalize(recipient) != crypto.normalize(to):
                continue
            pver = crypto.envelope_version(row["payload_enc"])
            token = json.loads(
                crypto.decrypt(
                    row["payload_enc"], settings.master_keys[pver],
                    record_id=row["id"], table="email_queue",
                    column="payload_enc", key_version=pver,
                )
            )["token"]
            return {
                "to": to,
                "link": (
                    f"{BASE_URL}/infinitemarkets/auth/email"
                    f"?shop={seed['pubkey']}#{token}"
                ),
                "state": row["state"],
                "created_at": row["created_at"],
            }
        return {"link": None}

    app.add_api_route("/_e2e/seed", e2e_seed, methods=["GET"])
    app.add_api_route("/_e2e/settle", e2e_settle, methods=["POST"])
    app.add_api_route("/_e2e/sign", e2e_sign, methods=["POST"])
    app.add_api_route("/_e2e/mode", e2e_mode, methods=["POST"])
    app.add_api_route("/_e2e/mailbox", e2e_mailbox, methods=["GET"])

    import uvicorn

    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=PORT,
            log_level="warning",
            ssl_certfile=str(cert),
            ssl_keyfile=str(key),
        )
    )
    serve = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)
        if serve.done():
            raise serve.exception()  # type: ignore[misc]

    import importlib

    from lnbits.app import check_and_register_extensions

    ext_module = importlib.import_module("infinitemarkets")
    if ext_module.started_at is None:
        await check_and_register_extensions(app)

    await _seed(app, seed, local_relay.url)
    SEED_PATH.parent.mkdir(parents=True, exist_ok=True)
    SEED_PATH.write_text(json.dumps(seed, indent=2))
    print(
        f"e2e server ready at {BASE_URL} — relay {local_relay.url}"
        f" — seed -> {SEED_PATH}"
    )

    try:
        await serve
    finally:
        await local_relay.stop()


if __name__ == "__main__":
    asyncio.run(main())
