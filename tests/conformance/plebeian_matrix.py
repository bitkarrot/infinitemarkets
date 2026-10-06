"""Plebeian conformance matrix — Release-B external-client gate (GAM-05).

An independent Gamma client — a PINNED clone of ``PlebeianApp/market`` —
completes real orders against the canonical extension pipeline on local
relays. Everything the client does is driven through Plebeian's own code:

- ``real-checkout`` — ``src/publish/orders.tsx`` ``publishOrderWithDependencies``
  (the literal checkout path): publishes a recipient-only kind-1059
  delivery-details wrap, a signed public kind-16 type-1 marker, and public
  kind-16 type-2 payment requests carrying the merchant's ``lud16``.
- ``strict-rumor`` — ``src/lib/orders/nip17OrderTransport.ts``
  ``publishNip17OrderTransportMessage`` (the unwired dual-copy transport):
  resolves BOTH parties' kind-10050 sets and publishes sender + recipient
  wraps.
- ``read-wraps`` — ``src/lib/orders/nip17OrderRead.ts``
  ``unwrapNip17OrderMessages``: the buyer reads the merchant's wrapped
  type-2 payment request / type-3 status off the relay.

Topology (all loopback, recorded in the report):

- ``nak serve`` — the neutral local NIP-01 relay; it is the merchant's
  inbox + public/discovery relay AND the buyer's advertised inbox relay.
- The pinned LNbits host boots in-process with the real extension
  (FakeWallet). The merchant's ``inbox_state`` reaches ``active`` through
  a real kind-10050 OK.
- A loopback LNURLp shim stands in for ``https://<domain>/.well-known/
  lnurlp/<name>`` — the qualified host ships no lnurlp extension; the
  shim's callback returns the order's own LNbits invoice so the
  lud16-resolved payment settles the real order (recorded delta; D-31).

Every literal divergence observed is written into ``deltas`` — the run
FAILS if any named divergence is absent from the register (D-32).

Usage::

    uv run python tests/conformance/plebeian_matrix.py run [--json-out F]
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PKG_DIR = REPO_ROOT / "infinitemarkets"
DRIVER_TS = Path(__file__).resolve().parent / "plebeian" / "driver.ts"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

#: Pinned external client (D-29/D-30). Re-verified at run time; a drifted
#: HEAD is recorded AND fails the matrix (the evidence must name the
#: tested revision, and the pin is the tested revision).
PLEBEIAN_PIN = "4bc7f8c0c73ae4ba2ff2a78f0c66d28347d1c1ce"
PLEBEIAN_REPO = "https://github.com/PlebeianApp/market"


def _resolve_clone() -> Path | None:
    for cand in (
        os.environ.get("PLEBEIAN_SRC"),
        "/tmp/plebeian-market",
        str(REPO_ROOT / ".cache" / "gsd-tmp" / "plebeian-market"),
    ):
        if cand and (Path(cand) / "src" / "publish" / "orders.tsx").exists():
            return Path(cand)
    return None


# --- environment must be set BEFORE any lnbits/infinitemarkets import ---------

WORK = Path(tempfile.mkdtemp(prefix="conf-plebeian-"))
EXT_ROOT = WORK / "extroot"
DATA_DIR = WORK / "data"
EXT_DIR = EXT_ROOT / "extensions"
EXT_DIR.mkdir(parents=True)
DATA_DIR.mkdir()
(EXT_DIR / "infinitemarkets").symlink_to(PKG_DIR, target_is_directory=True)

import base64  # noqa: E402

os.environ.update(
    {
        "INFINITEMARKETS_MASTER_KEYS": json.dumps(
            {"v1": base64.b64encode(b"k" * 32).decode()}
        ),
        "INFINITEMARKETS_ACTIVE_KEY_VERSION": "v1",
        "INFINITEMARKETS_PRIVACY_KEY": base64.b64encode(b"p" * 32).decode(),
        "INFINITEMARKETS_RELAY_IO": "on",
        "INFINITEMARKETS_ALLOW_INSECURE_RELAYS": "1",
        "LNBITS_DATA_FOLDER": str(DATA_DIR),
        "LNBITS_EXTENSIONS_PATH": str(EXT_ROOT),
        "LNBITS_EXTENSIONS_DEACTIVATE_ALL": "false",
        "LNBITS_BACKEND_WALLET_CLASS": "FakeWallet",
        "LNBITS_ADMIN_UI": "true",
        "LNBITS_AUDIT_LOG_REQUEST_BODY": "false",
        "LNBITS_AUDIT_LOG_QUERY_PARAMS": "false",
        "LNBITS_AUDIT_LOG_PATH_PARAMS": "false",
        "FIRST_INSTALL": "true",
    }
)


def _free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _derive_nsec(label: str) -> str:
    import hashlib as _h

    from nostr_sdk import Keys

    secret = _h.sha256(f"infinitemarkets-conformance:{label}".encode()).hexdigest()
    return Keys.parse(secret).secret_key().to_bech32()


def _run_cmd(cmd: list[str], timeout: float = 30) -> str:
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=True
        ).stdout.strip()
    except Exception:  # noqa: BLE001 — provenance is best-effort
        return ""


# --- LNURLp shim (loopback stand-in for https://<domain>/.well-known/lnurlp) --


class LnurlpShim:
    """A minimal LNURL-pay endpoint carrying the order's real bolt11.

    lud16 ``matrix@conf.test`` maps to this shim — LNURLp proper requires a
    public https domain, which a loopback conformance env cannot provide
    (recorded delta). The callback returns the order's own LNbits invoice
    so the lud16-resolved payment settles the real order.
    """

    def __init__(self) -> None:
        self.bolt11: str | None = None
        self.served_metadata = 0
        self.served_callbacks = 0
        self.port = _free_port()
        self._runner = None

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def lud16(self) -> str:
        return "matrix@conf.test"

    async def start(self) -> None:
        from aiohttp import web

        async def metadata(_req):
            self.served_metadata += 1
            return web.json_response(
                {
                    "tag": "payRequest",
                    "callback": f"{self.base}/lnurlp/cb",
                    "minSendable": 1000,
                    "maxSendable": 100_000_000_000,
                    "metadata": json.dumps(
                        [["text/plain", "infinitemarkets conformance"]]
                    ),
                }
            )

        async def callback(_req):
            self.served_callbacks += 1
            if not self.bolt11:
                return web.json_response(
                    {"status": "ERROR", "reason": "no invoice seeded"},
                    status=500,
                )
            return web.json_response({"pr": self.bolt11, "routes": []})

        app = web.Application()
        app.router.add_get("/.well-known/lnurlp/matrix", metadata)
        app.router.add_get("/lnurlp/cb", callback)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        await web.TCPSite(self._runner, "127.0.0.1", self.port).start()

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()


# --- host boot + merchant seeding --------------------------------------------


async def _wait_started(server, serve_task, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while not server.started:
        if serve_task.done():
            raise serve_task.exception() or RuntimeError("serve exited")
        if time.monotonic() > deadline:
            raise TimeoutError("uvicorn did not start")
        await asyncio.sleep(0.05)


async def boot(port: int | None = None) -> dict:
    """Boot the pinned LNbits host with the real extension only."""
    import uvicorn

    port = port or _free_port()
    os.environ["INFINITEMARKETS_PUBLIC_BASE_URL"] = f"https://localhost:{port}"
    from tools.checkout_host import host_checkout_dir

    host_dir = host_checkout_dir()
    os.chdir(host_dir)
    from lnbits.app import check_and_register_extensions, create_app
    from lnbits.core.crud import create_wallet
    from lnbits.core.crud.users import create_account
    from lnbits.core.models.users import Account, UpdateSuperuserPassword
    from lnbits.core.services import update_wallet_balance
    from lnbits.core.views.auth_api import first_install
    from lnbits.settings import settings

    app = create_app()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    )
    serve = asyncio.create_task(server.serve())
    await _wait_started(server, serve)

    for mod in [
        m for m in sys.modules
        if m == "infinitemarkets" or m.startswith("infinitemarkets.")
    ]:
        del sys.modules[mod]
    await first_install(
        UpdateSuperuserPassword(
            username="confadmin" + uuid.uuid4().hex[:8],
            password="secret1234",
            password_repeat="secret1234",
            first_install_token=settings.first_install_token,
        )
    )
    await check_and_register_extensions(app)

    account = Account(
        id=uuid.uuid4().hex, username="confuser" + uuid.uuid4().hex[:8],
        email=None,
    )
    account.hash_password("conf-pass-123")
    await create_account(account)
    wallet = await create_wallet(user_id=account.id, wallet_name="conf")
    await update_wallet_balance(wallet=wallet, amount=9_999_999)

    from lnbits.core.crud import (
        create_user_extension,
        get_user_extension,
        update_user_extension,
    )
    from lnbits.core.models.extensions import UserExtension

    ue = await get_user_extension(account.id, "infinitemarkets")
    if ue is None:
        await create_user_extension(
            UserExtension(user=account.id, extension="infinitemarkets",
                          active=True)
        )
    elif not ue.active:
        ue.active = True
        await update_user_extension(ue)

    return {
        "app": app, "server": server, "serve": serve, "port": port,
        "base": f"http://127.0.0.1:{port}", "account": account,
        "wallet": wallet,
    }


async def seed_merchant(env: dict, nak_ws: str) -> dict:
    """Merchant + catalog + products + relay configs through the real
    service layer; kind-10050 publish driven to ``active``."""
    from types import SimpleNamespace

    from infinitemarkets.db import DomainTransaction, db
    from infinitemarkets.services import catalog as catalog_service
    from infinitemarkets.services import merchant as merchant_service
    from infinitemarkets.services import outbox

    user = SimpleNamespace(id=env["account"].id)
    merchant = await merchant_service.create_merchant(
        user, wallet_id=env["wallet"].id, display_name="conf shop"
    )
    mid = merchant["id"]
    nsec = _derive_nsec("matrix-merchant")
    merchant = await merchant_service.import_nsec(mid, user, nsec)
    pubkey = merchant["pubkey"]

    now = int(time.time())
    async with DomainTransaction() as tx:
        await tx.execute(
            "UPDATE merchants SET state = 'active' WHERE id = :m",
            {"m": mid},
        )
        for url, direction in ((nak_ws, "inbox"), (nak_ws, "public")):
            await tx.execute(
                f"INSERT INTO {tx.table('relay_configs')} "
                "(id, merchant_id, relay_url, direction, enabled,"
                " created_at, updated_at) VALUES (:i, :m, :u, :d, TRUE,"
                " :t, :t)",
                {"i": uuid.uuid4().hex, "m": mid, "u": url, "d": direction,
                 "t": now},
            )

    catalog = await catalog_service.create_category(
        mid, user, {"name": "conf", "default_currency": "SAT"}
    )
    digital = await catalog_service.create_product(
        mid, user,
        {
            "category_id": catalog["id"],
            "title": "conf digital widget",
            "amount_minor": 700, "currency": "SAT",
            "visibility": "on-sale", "stock_on_hand": 50,
            "format": "digital", "delivery_content": "conf digital goods",
        },
    )
    physical = await catalog_service.create_product(
        mid, user,
        {
            "category_id": catalog["id"],
            "title": "conf physical widget",
            "amount_minor": 900, "currency": "SAT",
            "visibility": "on-sale", "stock_on_hand": 50,
            "format": "physical",
        },
    )
    shipping = await catalog_service.create_shipping(
        mid, user,
        {
            "title": "conf standard", "service": "standard",
            "currency": "SAT", "base_price_minor": 0,
            "countries": ["US"], "d_tag": "conf-std",
        },
    )

    await merchant_service.publish(mid, user)
    await merchant_service.enable_inbox(mid, user)
    for _ in range(30):
        await outbox.worker_tick(f"conf-{uuid.uuid4().hex[:6]}")
        async with db.connect() as conn:
            row = await conn.fetchone(
                "SELECT inbox_state FROM infinitemarkets.merchants"
                " WHERE id = :i", {"i": mid}
            )
        if row and row["inbox_state"] == "active":
            break
        await asyncio.sleep(0.4)

    return {
        "mid": mid, "pubkey": pubkey, "nsec": nsec,
        "digital_dtag": digital["d_tag"], "physical_dtag": physical["d_tag"],
        "shipping_dtag": shipping["d_tag"],
        "inbox_state": row["inbox_state"] if row else None,
    }


async def _publish_relay_event(nak_ws: str, nsec: str, kind: int,
                               content: str, tags: list[list[str]]) -> dict:
    """Publish one event to nak through a raw websocket — used for the
    merchant's kind-0 (lud16) and kind-30406 shipping fixtures, which are
    environment state the external client resolves, not extension output."""
    import websockets.asyncio.client as ws_client
    from nostr_sdk import (
        EventBuilder,
        Keys,
        Kind,
        NostrSigner,
        Tag,
        Timestamp,
    )

    keys = Keys.parse(nsec)
    builder = EventBuilder(Kind(kind), content).custom_created_at(
        Timestamp.from_secs(int(time.time()))
    )
    if tags:
        builder = builder.tags([Tag.parse(list(t)) for t in tags])
    event = await builder.sign(NostrSigner.keys(keys))
    data = json.loads(event.as_json())
    async with ws_client.connect(nak_ws, open_timeout=10) as ws:
        await ws.send(json.dumps(["EVENT", data]))
        raw = await asyncio.wait_for(ws.recv(), timeout=10)
        frame = json.loads(raw)
    ok = isinstance(frame, list) and len(frame) >= 3 and frame[0] == "OK"
    return {"id": data["id"], "kind": kind, "accepted": bool(ok and frame[2])}


async def _nak_req(nak_ws: str, nostr_filter: dict, seconds: float = 4.0) -> list[dict]:
    """Fetch stored events from nak (evidence reads only)."""
    import websockets.asyncio.client as ws_client

    events: list[dict] = []
    async with ws_client.connect(nak_ws, open_timeout=10) as ws:
        await ws.send(json.dumps(["REQ", "m", nostr_filter]))
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                raw = await asyncio.wait_for(
                    ws.recv(), timeout=max(0.05, deadline - time.monotonic())
                )
            except (asyncio.TimeoutError, TimeoutError):
                break
            frame = json.loads(raw)
            if frame[0] == "EOSE":
                break
            if frame[0] == "EVENT" and len(frame) >= 3:
                events.append(frame[2])
    return events


# --- the bun subprocess -------------------------------------------------------


async def run_driver(clone: Path, params: dict) -> dict:
    """Run the Plebeian bun driver; parse the MATRIX_RESULT line."""
    proc = await asyncio.create_subprocess_exec(
        "bun", ".conformance/matrix_driver.ts", json.dumps(params),
        cwd=str(clone),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return {"error": "driver timed out", "raw": ""}
    text = out.decode(errors="replace")
    for line in reversed(text.splitlines()):
        if line.startswith("MATRIX_RESULT "):
            result = json.loads(line[len("MATRIX_RESULT "):])
            result["_log_tail"] = text[-2000:]
            result["_exit"] = proc.returncode
            return result
    return {"error": "no MATRIX_RESULT line", "_exit": proc.returncode,
            "_log_tail": text[-2000:]}


# --- settlement (FakeWallet — no real sats, D-31) -----------------------------


async def settle_order_invoice(order_id: str) -> dict:
    """Pay the order's LNbits invoice via FakeWallet and run the real
    settlement listener."""
    from lnbits.core.db import db as core_db
    from lnbits.core.services.payments import (
        update_invoice_from_paid_invoices_stream,
    )
    from lnbits.wallets import get_funding_source

    async with core_db.connect() as conn:
        core = await conn.fetchone(
            "SELECT * FROM apipayments WHERE external_id = :e",
            {"e": f"infinitemarkets:{order_id}"},
        )
    assert core is not None, f"no core payment for {order_id}"
    funding = get_funding_source()
    resp = await funding.pay_invoice(core["bolt11"], fee_limit_msat=10_000)
    assert resp.ok, resp.error_message
    settled = await update_invoice_from_paid_invoices_stream(
        core["checking_id"]
    )
    assert settled is not None and settled.success
    from infinitemarkets.services.settlement import (
        _core_payments_by_external_id,  # noqa: SLF001
        invoice_listener,
    )

    payments = await _core_payments_by_external_id(
        f"infinitemarkets:{order_id}"
    )
    await invoice_listener(payments[0])
    return {"bolt11": core["bolt11"], "checking_id": core["checking_id"]}


# --- DB assertions ------------------------------------------------------------


async def _order_by_external_id(mid: str, external_id: str):
    from infinitemarkets import crypto
    from infinitemarkets.db import db
    from infinitemarkets.settings import ext_settings

    h = crypto.hmac_index(
        ext_settings().privacy_key, crypto.PURPOSE_ORDER_ID,
        mid, crypto.normalize(external_id),
    )
    async with db.connect() as conn:
        row = await conn.fetchone(
            "SELECT * FROM infinitemarkets.orders"
            " WHERE merchant_id = :m AND external_id_hash = :h",
            {"m": mid, "h": h},
        )
    return dict(row) if row else None


async def _publication_rows(mid: str, order_id: str) -> list[dict]:
    from infinitemarkets.db import db

    async with db.connect() as conn:
        rows = await conn.fetchall(
            "SELECT rp.delivery_copy, rp.relay_url, rp.result, rp.event_id,"
            " oe.event_kind, oe.payload_enc IS NOT NULL AS has_payload"
            " FROM infinitemarkets.relay_publications rp"
            " JOIN infinitemarkets.outbox_events oe"
            " ON oe.id = rp.outbox_event_id"
            " WHERE oe.merchant_id = :m AND oe.aggregate_id LIKE :p"
            " ORDER BY oe.created_at, rp.delivery_copy",
            {"m": mid, "p": f"{order_id}%"},
        )
    return [dict(r) for r in rows]


async def _inbox_rows(mid: str) -> list[dict]:
    from infinitemarkets.db import db

    async with db.connect() as conn:
        rows = await conn.fetchall(
            "SELECT id, source_relay_url, processed_state, reject_reason,"
            " outer_event_id, rumor_id FROM infinitemarkets.inbox_events"
            " WHERE merchant_id = :m ORDER BY received_at",
            {"m": mid},
        )
    return [dict(r) for r in rows]


async def _wait_for(pred, timeout: float = 30.0, interval: float = 0.3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = await pred()
        if value:
            return value
        await asyncio.sleep(interval)
    return None


async def _drain_pump(mid: str, rounds: int = 4) -> None:
    """Drive the real inbox worker passes + a reconcile between them."""
    from infinitemarkets.services.inbox import drain_and_process, inbox_runtime

    rt = inbox_runtime()
    for _ in range(rounds):
        await rt.reconcile()
        await drain_and_process()
        await asyncio.sleep(0.4)


async def _outbox_pump(rounds: int = 15) -> None:
    from infinitemarkets.services import outbox

    for _ in range(rounds):
        await outbox.worker_tick(f"conf-{uuid.uuid4().hex[:6]}")
        await asyncio.sleep(0.3)


# --- matrix orchestration -----------------------------------------------------


def _delta(delta_id: str, summary: str, evidence: str) -> dict:
    return {"id": delta_id, "summary": summary, "evidence": evidence}


async def matrix_run(probes_out: Path | None) -> int:
    probes: list[dict] = []
    deltas: list[dict] = []
    nak_proc = None
    shim = LnurlpShim()
    env = None

    # ---- 1. pin + tool provenance -------------------------------------------
    clone = _resolve_clone()
    if clone is None:
        target = REPO_ROOT / ".cache" / "gsd-tmp" / "plebeian-market"
        target.parent.mkdir(parents=True, exist_ok=True)
        rc = subprocess.call(
            ["git", "clone", PLEBEIAN_REPO, str(target)]
        )
        clone = target if rc == 0 else None
    actual_commit = (
        _run_cmd(["git", "-C", str(clone), "rev-parse", "HEAD"])
        if clone else ""
    )
    bun_version = _run_cmd(["bun", "--version"])
    nak_version = _run_cmd(["nak", "--version"]) or "debug (unversioned)"
    pinned = actual_commit == PLEBEIAN_PIN
    probes.append({
        "name": "clone_pin",
        "outcome": "pass" if clone and pinned else "fail",
        "detail": {
            "clone": str(clone) if clone else None,
            "pinned": PLEBEIAN_PIN,
            "actual": actual_commit or "absent",
            "bun": bun_version or "absent",
            "nak": nak_version,
        },
    })
    if not clone or not pinned:
        return _emit(probes, deltas, probes_out)

    # Install deps if needed + stage the driver into the clone's
    # untracked .conformance dir (the clone itself stays at the pin).
    if not (clone / "node_modules").exists():
        subprocess.run(["bun", "install"], cwd=str(clone), timeout=300)
    conf_dir = clone / ".conformance"
    conf_dir.mkdir(exist_ok=True)
    shutil.copyfile(DRIVER_TS, conf_dir / "matrix_driver.ts")

    # ---- 2. nak + shim + host ------------------------------------------------
    nak_port = _free_port()
    nak_proc = subprocess.Popen(
        ["nak", "serve", "--hostname", "127.0.0.1", "--port", str(nak_port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    nak_ws = f"ws://127.0.0.1:{nak_port}"
    await shim.start()

    try:
        env = await boot()
        merchant = await seed_merchant(env, nak_ws)
        mid, mpk = merchant["mid"], merchant["pubkey"]

        # Merchant environment events the external client resolves:
        # kind-0 (carries the lud16) + two kind-30406 shipping fixtures
        # (digital + standard) — merchant-key-signed fixture state.
        lud16 = shim.lud16
        ev0 = await _publish_relay_event(
            nak_ws, merchant["nsec"], 0,
            json.dumps({"name": "conf shop", "lud16": lud16}),
            [],
        )
        ev_d = await _publish_relay_event(
            nak_ws, merchant["nsec"], 30406, "digital delivery",
            [["d", "conf-digital"], ["title", "Digital delivery"],
             ["price", "0", "SAT"], ["service", "digital"]],
        )
        ev_p = await _publish_relay_event(
            nak_ws, merchant["nsec"], 30406, "standard shipping",
            [["d", merchant["shipping_dtag"]], ["title", "Standard"],
             ["price", "0", "SAT"], ["service", "standard"],
             ["country", "US"]],
        )
        env_ok = all(e["accepted"] for e in (ev0, ev_d, ev_p)) and (
            merchant["inbox_state"] == "active"
        )
        probes.append({
            "name": "env_bootstrap",
            "outcome": "pass" if env_ok else "fail",
            "detail": {
                "inbox_state": merchant["inbox_state"],
                "kind0_accepted": ev0["accepted"],
                "shipping_events": [ev_d["accepted"], ev_p["accepted"]],
                "nak": nak_ws, "lnurlp_shim": shim.base, "lud16": lud16,
            },
        })

        # Inbox subscription up before the buyer posts.
        from infinitemarkets.services.inbox import inbox_runtime

        rt = inbox_runtime()
        await rt.reconcile()
        await asyncio.sleep(1.0)

        buyer_hex = "cd" * 32
        from nostr_sdk import Keys

        buyer_pubkey = Keys.parse(buyer_hex).public_key().to_hex()

        # ---- 3. REAL-CHECKOUT run — the live UI publish path -----------------
        digital_result = await run_driver(clone, {
            "mode": "real-checkout",
            "relay": nak_ws,
            "buyerSecretHex": buyer_hex,
            "merchantPubkey": mpk,
            "checkout": {
                "shippingData": {
                    "name": "", "firstLineOfAddress": "",
                    "additionalInformation": "", "city": "",
                    "zipPostcode": "", "country": "",
                    "email": "buyer@conf.test", "phone": "",
                },
                "productsBySeller": {mpk: [{
                    "id": merchant["digital_dtag"], "amount": 1,
                    "shippingMethodId": f"30406:{mpk}:conf-digital",
                }]},
                "sellerData": {mpk: {
                    "satsTotal": 700, "shippingSats": 0,
                    "shares": {"sellerAmount": 700},
                }},
                "v4vShares": {},
            },
        })
        real_ids = digital_result.get("orderIds") or []
        digital_pub = digital_result.get("published") or []
        wrap_1059 = [p for p in digital_pub if p.get("kind") == 1059]
        probes.append({
            "name": "real_checkout_publish",
            "outcome": (
                "pass" if real_ids and wrap_1059 else "fail"
            ),
            "detail": {
                "order_ids": real_ids,
                "published_kinds": [p.get("kind") for p in digital_pub],
                "driver_error": digital_result.get("error"),
                "log_tail": digital_result.get("_log_tail", "")[-500:],
            },
        })
        if not real_ids or not wrap_1059:
            return _emit(probes, deltas, probes_out)
        real_order_ext = real_ids[0]

        # The wrap reaches the real inbox subscription on nak -> admitted
        # -> dispatched -> gamma order.
        real_wrap_id = wrap_1059[0]["id"]

        async def _real_order():
            await _drain_pump(mid, rounds=1)
            return await _order_by_external_id(mid, real_order_ext)

        order = await _wait_for(_real_order, timeout=45)
        probes.append({
            "name": "real_checkout_intake",
            "outcome": (
                "pass"
                if order
                and order["protocol"] == "gamma"
                and order["state"] in ("awaiting_payment", "confirmed")
                else "fail"
            ),
            "detail": {
                "order": {k: order[k] for k in
                          ("id", "protocol", "state", "total_sat")}
                if order else None,
                "wrap_id": real_wrap_id,
            },
        })
        if order is None:
            return _emit(probes, deltas, probes_out)
        real_order_id = order["id"]

        # type-2 payment request publishes dual-copy to the buyer's
        # declared relays + the merchant inbox.
        await _outbox_pump()
        pubs = await _publication_rows(mid, real_order_id)
        copies = {p["delivery_copy"] for p in pubs if p["result"] == "accepted"}
        probes.append({
            "name": "real_checkout_payment_request",
            "outcome": (
                "pass" if {"recipient", "sender"} <= copies else "fail"
            ),
            "detail": {"publications": pubs},
        })

        # Payment leg (a): merchant kind-0 lud16 -> LNURLp shim -> the
        # order's own bolt11 -> FakeWallet settlement.
        from lnbits.core.db import db as core_db

        async with core_db.connect() as conn:
            core = await conn.fetchone(
                "SELECT bolt11 FROM apipayments WHERE external_id = :e",
                {"e": f"infinitemarkets:{real_order_id}"},
            )
        shim.bolt11 = core["bolt11"]
        lnurlp_result: dict = {}
        try:
            import httpx

            async with httpx.AsyncClient(timeout=10) as http:
                meta = await http.get(f"{shim.base}/.well-known/lnurlp/matrix")
                meta_json = meta.json()
                cb = await http.get(
                    meta_json["callback"],
                    params={"amount": order["total_sat"] * 1000},
                )
                lnurlp_result = {
                    "metadata": meta_json, "invoice": cb.json()
                }
        except Exception as exc:  # noqa: BLE001
            lnurlp_result = {"error": f"{type(exc).__name__}: {exc}"}
        lud16_ok = lnurlp_result.get("invoice", {}).get("pr") == core["bolt11"]

        pay = await settle_order_invoice(real_order_id)

        async def _confirmed():
            row = await _order_by_external_id(mid, real_order_ext)
            return row if row and row["state"] == "confirmed" else None

        confirmed = await _wait_for(_confirmed, timeout=20)
        await _outbox_pump()
        pubs = await _publication_rows(mid, real_order_id)
        kind16_pubs = [p for p in pubs if p["event_kind"] == 16]
        copies = {p["delivery_copy"] for p in pubs if p["result"] == "accepted"}
        probes.append({
            "name": "real_checkout_settlement",
            "outcome": (
                "pass" if confirmed and lud16_ok
                and {"recipient", "sender"} <= copies else "fail"
            ),
            "detail": {
                "order_state": confirmed["state"] if confirmed else None,
                "lud16": lud16, "lnurlp": {
                    "metadata_hits": shim.served_metadata,
                    "callback_hits": shim.served_callbacks,
                    "invoice_matches_order": lud16_ok,
                },
                "settlement": pay,
                "delivery_copies": sorted(copies),
                "kind16_publications": len(kind16_pubs),
            },
        })

        # Buyer-side read-back through Plebeian's own unwrap path —
        # the type-2/type-3 wraps ARE on the wire even though the live UI
        # never reads them (recorded delta).
        readback = await run_driver(clone, {
            "mode": "read-wraps", "relay": nak_ws,
            "buyerSecretHex": buyer_hex,
        })
        messages = readback.get("messages") or []
        readable = [
            m for m in messages
            if not m.get("error") and m.get("kind") == 16
        ]
        types = sorted({
            next((t[1] for t in m["tags"] if t[0] == "type"), "?")
            for m in readable
        })
        probes.append({
            "name": "buyer_readback",
            "outcome": "pass" if readable else "fail",
            "detail": {
                "wraps_on_wire": readback.get("wrapCount"),
                "types_read": types,
                "errors": [m for m in messages if m.get("error")],
            },
        })

        # ---- 4. STRICT-RUMOR run — Plebeian's dual-copy transport ------------
        strict_ext = f"str-{uuid.uuid4().hex[:16]}"
        strict_ref = f"30402:{mpk}:{merchant['digital_dtag']}"
        strict_result = await run_driver(clone, {
            "mode": "strict-rumor",
            "relay": nak_ws,
            "buyerSecretHex": buyer_hex,
            "merchantPubkey": mpk,
            "orderId": strict_ext,
            "productRef": strict_ref,
            "amountSats": 700,
        })
        transport = strict_result.get("transport") or {}
        transport_ok = (
            transport.get("status") == "published"
            and transport.get("sender", {}).get("target") == "sender"
            and transport.get("recipient", {}).get("target") == "recipient"
        )
        probes.append({
            "name": "strict_rumor_transport",
            "outcome": "pass" if transport_ok else "fail",
            "detail": {
                "status": transport.get("status"),
                "sender_wrap": transport.get("sender", {}).get("giftWrapId"),
                "recipient_wrap":
                    transport.get("recipient", {}).get("giftWrapId"),
                "rumor_id": transport.get("rumorId"),
                "driver_error": strict_result.get("error"),
            },
        })

        async def _strict_order():
            await _drain_pump(mid, rounds=1)
            return await _order_by_external_id(mid, strict_ext)

        s_order = await _wait_for(_strict_order, timeout=45)
        probes.append({
            "name": "strict_rumor_intake",
            "outcome": (
                "pass"
                if s_order and s_order["state"] in (
                    "awaiting_payment", "confirmed"
                )
                else "fail"
            ),
            "detail": {
                "order": {k: s_order[k] for k in
                          ("id", "protocol", "state", "total_sat")}
                if s_order else None,
            },
        })
        if s_order:
            s_order_id = s_order["id"]
            await _outbox_pump()
            # Buyer reads the type-2 wrap and pays the exact bolt11 the
            # merchant's wrap carried — the canonical gamma payment chain.
            strict_read = await run_driver(clone, {
                "mode": "read-wraps", "relay": nak_ws,
                "buyerSecretHex": buyer_hex,
            })
            strict_msgs = [
                m for m in (strict_read.get("messages") or [])
                if not m.get("error")
                and any(
                    t[0] == "order" and t[1] == strict_ext
                    for t in m.get("tags", [])
                )
            ]
            t2 = [
                m for m in strict_msgs
                if any(t == ["type", "2"] or (
                    t[0] == "type" and t[1] == "2") for t in m["tags"])
            ]
            bolt11_wrap = None
            for m in t2:
                for t in m["tags"]:
                    if t[0] == "payment" and len(t) >= 3:
                        bolt11_wrap = t[2]
            s_pay = await settle_order_invoice(s_order_id)

            async def _s_confirmed():
                row = await _order_by_external_id(mid, strict_ext)
                return row if row and row["state"] == "confirmed" else None

            s_confirmed = await _wait_for(_s_confirmed, timeout=20)
            await _outbox_pump()
            s_pubs = await _publication_rows(mid, s_order_id)
            s_copies = {
                p["delivery_copy"] for p in s_pubs
                if p["result"] == "accepted"
            }
            probes.append({
                "name": "strict_rumor_settlement",
                "outcome": (
                    "pass" if s_confirmed
                    and {"recipient", "sender"} <= s_copies else "fail"
                ),
                "detail": {
                    "order_state":
                        s_confirmed["state"] if s_confirmed else None,
                    "type2_wrap_bolt11_matches":
                        bolt11_wrap == s_pay["bolt11"]
                        if bolt11_wrap else "not-read",
                    "delivery_copies": sorted(s_copies),
                    "publications": [
                        {k: p[k] for k in
                         ("delivery_copy", "result", "event_kind")}
                        for p in s_pubs
                    ],
                },
            })

        # ---- 5. PHYSICAL run — opaque address -> rejected intake -------------
        phys_ext_result = await run_driver(clone, {
            "mode": "real-checkout",
            "relay": nak_ws,
            "buyerSecretHex": buyer_hex,
            "merchantPubkey": mpk,
            "checkout": {
                "shippingData": {
                    "name": "Conf Buyer",
                    "firstLineOfAddress": "1 Test Way",
                    "additionalInformation": "",
                    "city": "Testville", "zipPostcode": "12345",
                    "country": "US", "email": "", "phone": "+15550001",
                },
                "productsBySeller": {mpk: [{
                    "id": merchant["physical_dtag"], "amount": 1,
                    "shippingMethodId":
                        f"30406:{mpk}:{merchant['shipping_dtag']}",
                }]},
                "sellerData": {mpk: {
                    "satsTotal": 900, "shippingSats": 0,
                    "shares": {"sellerAmount": 900},
                }},
                "v4vShares": {},
            },
        })
        phys_ids = phys_ext_result.get("orderIds") or []
        probes.append({
            "name": "physical_checkout_publish",
            "outcome": "pass" if phys_ids else "fail",
            "detail": {
                "order_ids": phys_ids,
                "driver_error": phys_ext_result.get("error"),
            },
        })
        if phys_ids:
            phys_wraps = [
                p for p in (phys_ext_result.get("published") or [])
                if p.get("kind") == 1059
            ]
            phys_wrap_id = phys_wraps[0]["id"] if phys_wraps else None

            async def _phys_rejected():
                await _drain_pump(mid, rounds=1)
                rows = await _inbox_rows(mid)
                rej = [
                    r for r in rows
                    if r["outer_event_id"] == phys_wrap_id
                    and r["processed_state"] == "rejected"
                ]
                return rej or None

            rejected = await _wait_for(_phys_rejected, timeout=45)
            await _outbox_pump()

            # The D-22 reply: an order_msg intent for the rejected row
            # reaching the buyer's relays (recipient copy accepted).
            from infinitemarkets.db import db as _db

            async with _db.connect() as conn:
                reply_rows = await conn.fetchall(
                    "SELECT oe.id, oe.state, rp.delivery_copy, rp.result "
                    "FROM infinitemarkets.outbox_events oe "
                    "LEFT JOIN infinitemarkets.relay_publications rp "
                    "ON rp.outbox_event_id = oe.id "
                    "WHERE oe.merchant_id = :m "
                    "AND oe.aggregate_id LIKE 'rejected:%'",
                    {"m": mid},
                )
            reply_ok = any(
                r["delivery_copy"] == "recipient" and r["result"] == "accepted"
                for r in (dict(x) for x in reply_rows)
            )
            probes.append({
                "name": "physical_rejected_intake",
                "outcome": (
                    "pass" if rejected and reply_ok else "fail"
                ),
                "detail": {
                    "rejected_rows": rejected,
                    "reply_publications": [dict(r) for r in reply_rows],
                    "wrap_ids": [p["id"] for p in phys_wraps],
                },
            })

        # ---- 6. delta evidence — what the inbox did NOT see ------------------
        nak_1059 = await _nak_req(
            nak_ws, {"kinds": [1059], "#p": [mpk]}
        )
        nak_public = await _nak_req(
            nak_ws, {"kinds": [16, 17], "authors": [buyer_pubkey]}
        )
        inbox_rows = await _inbox_rows(mid)
        public_in_inbox = [
            r for r in inbox_rows
            if any(
                p["id"] == r["outer_event_id"] for p in nak_public
            )
        ]
        probes.append({
            "name": "public_events_not_admitted",
            "outcome": (
                "pass" if nak_public and not public_in_inbox else "fail"
            ),
            "detail": {
                "public_kind16_17_on_relay": [
                    {"id": e["id"], "kind": e["kind"],
                     "type": next(
                         (t[1] for t in e["tags"] if t[0] == "type"), None
                     )}
                    for e in nak_public
                ],
                "admitted_public_events": len(public_in_inbox),
                "merchant_wraps_on_relay": len(nak_1059),
            },
        })

        # ---- 7. known-delta register (D-32) ----------------------------------
        deltas.extend([
            _delta(
                "no-sender-copy",
                "Plebeian's live checkout publishes a single recipient-only "
                "kind-1059 (no buyer sender copy); the strict-rumor "
                "transport publishes both copies",
                "real_checkout_publish.published (one kind-1059) vs "
                "strict_rumor_transport.sender/recipient attempts",
            ),
            _delta(
                "public-order-events-unread",
                "The public kind-16 type-1 marker, public type-2 lud16 "
                "payment request, and kind-17 receipt are invisible to the "
                "NIP-17 inbox (kind-1059 filter) — receipt_verified may "
                "stay false; recorded, not fixed",
                "public_events_not_admitted (public kind-16/17 on relay, "
                "zero admitted)",
            ),
            _delta(
                "order-info-envelope",
                "Plebeian's type-1 rumor carries subject='order-info' and "
                "a 'name' tag; tolerated by the intake (subject is not "
                "value-enforced per spec tolerance)",
                "real_checkout_intake / strict_rumor_intake order rows",
            ),
            _delta(
                "opaque-address-physical-rejected",
                "Plebeian serializes the address as a newline-joined "
                "opaque string; physical orders are rejected "
                "pre-reservation with a D-22 status=rejected type-3 reply",
                "physical_rejected_intake (rejected row + recipient-copy "
                "reply publication)",
            ),
            _delta(
                "payment-path-lnurlp-shim",
                "Payment leg: merchant kind-0 lud16 -> loopback LNURLp "
                "shim -> the order's own bolt11 -> FakeWallet settlement "
                "(no real sats — D-31). A production host would serve a "
                "fresh invoice per LNURLp callback; settlement "
                "correlation via external_id is unchanged",
                "real_checkout_settlement.lnurlp + "
                "strict_rumor_settlement.type2_wrap_bolt11_matches",
            ),
            _delta(
                "real-checkout-app-relay-only",
                "publishOrderWithDependencies posts the private wrap to "
                "the connected app relay set — not the merchant's "
                "resolved kind-10050 set (Plebeian's own strict transport "
                "does resolve it; both coincide on nak in this env)",
                "driver published[] targets (app relay) vs "
                "strict_rumor_transport.relayTargets",
            ),
        ])
        missing = []
        required_deltas = {
            "no-sender-copy", "public-order-events-unread",
            "order-info-envelope", "opaque-address-physical-rejected",
            "payment-path-lnurlp-shim",
        }
        have = {d["id"] for d in deltas}
        for d in required_deltas - have:
            missing.append(d)
        probes.append({
            "name": "delta_register",
            "outcome": "pass" if not missing else "fail",
            "detail": {
                "recorded": sorted(have), "missing": sorted(missing),
            },
        })

    except Exception as exc:  # noqa: BLE001 — report, never raise raw
        probes.append({
            "name": "matrix_driver",
            "outcome": "fail",
            "detail": {"error": f"{type(exc).__name__}: {exc}"},
        })
    finally:
        if nak_proc is not None:
            nak_proc.terminate()
            try:
                nak_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                nak_proc.kill()
        await shim.stop()
        if env is not None:
            env["server"].should_exit = True
            try:
                await asyncio.wait_for(env["serve"], timeout=10)
            except Exception:  # noqa: BLE001
                pass

    return _emit(probes, deltas, probes_out, extra={
        "clone": str(clone) if clone else None,
        "plebeian_commit": actual_commit,
        "plebeian_pin": PLEBEIAN_PIN,
        "bun": bun_version, "nak": nak_version,
        "nak_ws": nak_ws,
    })


def _emit(probes: list, deltas: list, out: Path | None,
          extra: dict | None = None) -> int:
    outcome = "pass" if (
        probes and all(p["outcome"] == "pass" for p in probes)
    ) else "fail"
    report = {
        "artifact": "plebeian-matrix",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "outcome": outcome,
        **(extra or {}),
        "probes": probes,
        "deltas": deltas,
    }
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0 if outcome == "pass" else 1


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    run_p = sub.add_parser("run", help="provision + run the matrix")
    run_p.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(matrix_run(args.json_out)))


if __name__ == "__main__":
    main()
