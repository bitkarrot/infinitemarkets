"""P0-12: host auth/privacy/lifecycle probes (QUAL-12).

Probes against the real pinned host (e336fe1) plus the local relay fixture:

- (a) mutation authorization: a state-changing probe route requires an
  authenticated session (real host JWT cookie minted by the host's own
  login endpoint) AND a route-enforced same-origin check — ID-only
  carriage, cookie-only without Origin, and cross-origin cookie mutations
  all fail; the approved cookie + canonical-origin path passes (host CORS
  is never trusted, section 21.29);
- (b) bearer header: the public-status probe requires X-Order-Token, never
  accepts the token in path/query, and returns Referrer-Policy:
  no-referrer + Cache-Control: no-store (section 5.4);
- (c) audit redaction: recorded rows carry only redaction markers for
  bearer tokens, bolt11 strings, recipient addresses, and PII (section 16);
  request-header capture redacts X-Order-Token;
- (d) startup readiness: the probe start performs only bounded registration
  through task_manager.create_permanent_task — no inline reconciliation —
  and the readiness gate keeps checkout disabled until the startup pass
  completes (section 10);
- (e) cancellation-safe cleanup: a worker owning an SDK client connected
  to a local relay closes the connection when the task is cancelled
  directly (no stop hook), and the stop hook cancels only extension-owned
  handles — never cancel_all_tasks (section 10);
- (f) topology refusal: production-ready mode refuses multi-process SQLite
  and unsupported dialects (section 14, model-level).
"""

from __future__ import annotations

import asyncio
import uuid

import httpx
import pytest
import pytest_asyncio
from nostr_sdk import ClientBuilder, NostrSigner, RelayUrl

from harness import authprobe, sdk
from harness import host as host_module
from harness import relay as relay_module

pytestmark = [
    pytest.mark.fast,
    pytest.mark.host,
    pytest.mark.asyncio(loop_scope="session"),
]

CANONICAL_ORIGIN = "https://shop.example"
ORDER_TOKEN = "gq-order-token-" + "a" * 32
PROBE_PREFIX = "/infinitemarkets-qual-probe"


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def probe_env(tmp_path_factory):
    """One host boot for the module: probe router mounted inside the real
    app, a real account with password, and an httpx ASGI client."""
    from lnbits.core.crud.users import create_account
    from lnbits.core.models.users import Account

    audit = authprobe.AuditLog()
    async with host_module.host_app(tmp_path_factory.mktemp("p012")) as app:
        app.include_router(
            authprobe.build_probe_router(
                canonical_origin=CANONICAL_ORIGIN,
                order_token=ORDER_TOKEN,
                audit=audit,
            )
        )
        # A real account with a password, logged in through the host's own
        # auth endpoint — the cookie path is genuinely host-authenticated.
        # Host username rules: [a-zA-Z0-9._]{2,20}, no leading/trailing _ or .
        username = f"gquser{uuid.uuid4().hex[:8]}"
        password = "probe-pass-123"
        account = Account(
            id=uuid.uuid4().hex, username=username, email=None
        )
        account.hash_password(password)
        await create_account(account)

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url=CANONICAL_ORIGIN
        ) as client:
            yield {
                "app": app,
                "client": client,
                "audit": audit,
                "username": username,
                "password": password,
            }


async def _login(probe_env) -> str:
    """Real host login -> the cookie_access_token value."""
    resp = await probe_env["client"].post(
        "/api/v1/auth",
        json={
            "username": probe_env["username"],
            "password": probe_env["password"],
        },
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    assert resp.cookies.get("cookie_access_token") == token
    return token


# --- (a) mutation authorization ------------------------------------------------


async def test_id_only_login_method_refused(probe_env):
    """The host's ID-only auth method is refused by default posture.

    ``user_id_only`` is not in ``auth_allowed_methods`` (default:
    username_and_password only) — POST /api/v1/auth/usr is rejected even
    for a real account, and the superuser is additionally blocked from
    ID-only login by the admin rule.
    """
    resp = await probe_env["client"].post(
        "/api/v1/auth/usr", json={"usr": uuid.uuid4().hex}
    )
    assert resp.status_code == 403, resp.text


async def test_mutation_requires_authenticated_session(probe_env):
    """A state-changing request carrying only an id — no credentials —
    is rejected by the host's real access-token dependency."""
    resp = await probe_env["client"].post(
        f"{PROBE_PREFIX}/mutate",
        json={"id": uuid.uuid4().hex},
        headers={"Origin": CANONICAL_ORIGIN},
    )
    assert resp.status_code == 401


async def test_cookie_only_without_origin_rejected(probe_env):
    """Authenticated cookie but NO Origin: the route's own same-origin
    check rejects (host CORS is never trusted, section 21.29)."""
    token = await _login(probe_env)
    resp = await probe_env["client"].post(
        f"{PROBE_PREFIX}/mutate",
        json={"id": uuid.uuid4().hex},
        headers={"Cookie": f"cookie_access_token={token}"},
    )
    assert resp.status_code == 403


async def test_cross_origin_cookie_mutation_rejected(probe_env):
    token = await _login(probe_env)
    resp = await probe_env["client"].post(
        f"{PROBE_PREFIX}/mutate",
        json={"id": uuid.uuid4().hex},
        headers={"Cookie": f"cookie_access_token={token}", "Origin": "https://evil.example"},
    )
    assert resp.status_code == 403


async def test_approved_cookie_same_origin_path_passes(probe_env):
    token = await _login(probe_env)
    resp = await probe_env["client"].post(
        f"{PROBE_PREFIX}/mutate",
        json={"id": uuid.uuid4().hex},
        headers={"Cookie": f"cookie_access_token={token}", "Origin": CANONICAL_ORIGIN},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True


async def test_wrong_origin_subdomain_rejected(probe_env):
    """A subdomain of the canonical origin is NOT same-origin."""
    token = await _login(probe_env)
    resp = await probe_env["client"].post(
        f"{PROBE_PREFIX}/mutate",
        json={"id": uuid.uuid4().hex},
        headers={"Cookie": f"cookie_access_token={token}", "Origin": "https://sub.shop.example"},
    )
    assert resp.status_code == 403


# --- (b) bearer header + privacy response headers -------------------------------


async def test_order_status_requires_x_order_token_header(probe_env):
    resp = await probe_env["client"].get(
        f"{PROBE_PREFIX}/order-status",
        headers={"X-Order-Token": ORDER_TOKEN},
    )
    assert resp.status_code == 200
    assert resp.headers["referrer-policy"] == "no-referrer"
    assert resp.headers["cache-control"] == "no-store"


async def test_order_status_token_in_query_rejected(probe_env):
    """Bearer tokens MUST NOT appear in path or query (section 5.4)."""
    resp = await probe_env["client"].get(
        f"{PROBE_PREFIX}/order-status?token={ORDER_TOKEN}"
    )
    assert resp.status_code == 401


async def test_order_status_token_in_path_not_routed(probe_env):
    resp = await probe_env["client"].get(
        f"{PROBE_PREFIX}/order-status/{ORDER_TOKEN}"
    )
    # No such route — token-in-path carriage is never accepted.
    assert resp.status_code in (401, 404, 405)


async def test_order_status_wrong_token_rejected(probe_env):
    resp = await probe_env["client"].get(
        f"{PROBE_PREFIX}/order-status",
        headers={"X-Order-Token": "wrong-token"},
    )
    assert resp.status_code == 401


# --- (c) audit + request/header redaction ----------------------------------------


async def test_audit_rows_redact_secrets_and_pii():
    audit = authprobe.AuditLog()
    token = "secret-order-token-value"
    bolt11 = "lnbc210n1pjqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq"
    address = "123 Hidden St, Springfield"
    email = "buyer@example.com"
    row = audit.record(
        "infinitemarkets.probe.test",
        order_id="gq-order-01",
        token=token,
        bolt11=bolt11,
        address=address,
        email=email,
        # secret value under an innocuous name — caught by shape:
        memo=bolt11,
        note="c" * 64,
    )
    assert row["order_id"] == "gq-order-01"  # identifiers pass through
    rendered = str(audit.rows)
    for secret in (token, bolt11, address, email, "c" * 64):
        assert secret not in rendered
    assert row["token"] == authprobe.REDACTED
    assert row["bolt11"] == authprobe.REDACTED
    assert row["memo"] == "<redacted:bolt11>"
    assert row["note"] == "<redacted:hex64>"


async def test_request_header_logging_redacts_order_token():
    headers = {
        "x-order-token": ORDER_TOKEN,
        "authorization": "Bearer abc.def.ghi",
        "cookie": "cookie_access_token=xyz",
        "user-agent": "qual-probe",
    }
    redacted = authprobe.redacted_headers(headers)
    assert redacted["x-order-token"] == authprobe.REDACTED
    assert redacted["authorization"] == authprobe.REDACTED
    assert redacted["cookie"] == authprobe.REDACTED
    assert redacted["user-agent"] == "qual-probe"


async def test_order_status_audit_capture_redacts_token(probe_env):
    """The bearer-path audit row must not contain the raw token (5.4/16)."""
    await probe_env["client"].get(
        f"{PROBE_PREFIX}/order-status", headers={"X-Order-Token": ORDER_TOKEN}
    )
    status_rows = [
        r for r in probe_env["audit"].rows
        if r["event"] == "infinitemarkets.probe.order-status"
    ]
    assert status_rows, "the order-status request was audit-captured"
    rendered = str(status_rows)
    assert ORDER_TOKEN not in rendered
    assert status_rows[0]["headers"]["x-order-token"] == authprobe.REDACTED


# --- (d) startup readiness ---------------------------------------------------------


async def test_startup_registers_only_bounded_tasks(probe_env):
    """Section 10: start performs bounded create_permanent_task registration
    only — no inline network/reconciliation — and checkout stays gated
    until the startup pass completes."""
    from lnbits.task_manager import task_manager

    lifecycle = authprobe.ProbeLifecycle(task_manager)
    ran_inline: list[str] = []

    async def reconcile():
        ran_inline.append("reconcile")
        lifecycle.mark_startup_reconciled()
        # One startup pass completes; the task then idles (permanent tasks
        # restart their func on clean return — block instead of spinning).
        await asyncio.Event().wait()

    assert lifecycle.checkout_allowed() is False

    handles = lifecycle.start({"infinitemarkets.reconciliation": reconcile})
    try:
        # Registration is synchronous/bounded: the coroutine has NOT run
        # inline during start().
        assert ran_inline == []
        assert task_manager.get_task("infinitemarkets.reconciliation") is not None
        assert all(h.name == "infinitemarkets.reconciliation" for h in handles)
        assert lifecycle.ready is False
        assert lifecycle.checkout_allowed() is False

        # Let the registered task run its startup pass.
        for _ in range(100):
            if lifecycle.ready:
                break
            await asyncio.sleep(0.05)
        assert lifecycle.ready is True
        assert lifecycle.checkout_allowed() is True
        assert ran_inline == ["reconcile"]
    finally:
        lifecycle.stop()


# --- (e) cancellation-safe cleanup ---------------------------------------------------


async def test_sdk_client_cleanup_on_direct_task_cancel(probe_env):
    """Section 10: process shutdown may cancel tasks WITHOUT the stop hook —
    the finally cleanup must still close the SDK relay connection."""
    async with relay_module.LocalRelay(
        mode=relay_module.RelayMode.ACCEPTING
    ) as local:
        keys = sdk.generate_keys()
        client = ClientBuilder().signer(NostrSigner.keys(keys)).build()
        assert await client.add_relay(RelayUrl.parse(local.url))
        await client.connect()
        # connect() returns after scheduling; wait for the handshake to land.
        for _ in range(100):
            if any(c.event == "connect" for c in local.connections):
                break
            await asyncio.sleep(0.05)
        assert any(c.event == "connect" for c in local.connections)

        stop = asyncio.Event()
        task = asyncio.create_task(authprobe.sdk_client_worker(client, stop))
        await asyncio.sleep(0.05)

        # Direct cancellation — simulating process shutdown without the
        # extension stop hook.
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        # Give the relay a beat to record the disconnect.
        for _ in range(50):
            if any(c.event == "disconnect" for c in local.connections):
                break
            await asyncio.sleep(0.05)
        assert any(
            c.event == "disconnect" for c in local.connections
        ), "cancelled worker must close the relay connection in finally"


async def test_stop_hook_cancels_only_owned_handles(probe_env):
    """The stop hook cancels extension-owned handles only — never the
    host's cancel-everything API (section 10)."""
    from lnbits.task_manager import task_manager

    lifecycle = authprobe.ProbeLifecycle(task_manager)
    never = asyncio.Event()

    async def owned_worker():
        await never.wait()

    async def unrelated_worker():
        await never.wait()

    unrelated = task_manager.create_task(
        unrelated_worker(), name="gamma_qual_p012_unrelated"
    )
    handles = lifecycle.start({"infinitemarkets.probe_worker": owned_worker})
    try:
        await asyncio.sleep(0.05)
        assert task_manager.get_task("infinitemarkets.probe_worker") is not None

        lifecycle.stop()

        await asyncio.sleep(0.05)
        assert all(h.task.done() or h.task.cancelled() for h in handles)
        assert task_manager.get_task("infinitemarkets.probe_worker") is None
        # The unrelated task survived: stop used cancel_task on owned
        # handles only — cancel_all_tasks would have killed it.
        assert not unrelated.task.done()
        assert task_manager.get_task("gamma_qual_p012_unrelated") is not None
    finally:
        if not unrelated.task.done():
            task_manager.cancel_task(unrelated)


# --- (f) topology refusal -----------------------------------------------------------


@pytest.mark.parametrize(
    "dialect,workers,allowed,reason",
    [
        ("sqlite", 1, True, "supported"),
        ("sqlite", 2, False, "sqlite-multi-process-refused"),
        ("sqlite", 8, False, "sqlite-multi-process-refused"),
        ("postgresql", 1, True, "supported"),
        ("postgresql", 4, True, "supported"),
        ("cockroachdb", 1, False, "unsupported-dialect:cockroachdb"),
        ("", 1, False, "unsupported-dialect:unknown"),
    ],
)
async def test_production_topology_refusal(dialect, workers, allowed, reason):
    decision = authprobe.evaluate_production_topology(dialect, workers)
    assert decision.allowed is allowed
    assert decision.reason == reason
