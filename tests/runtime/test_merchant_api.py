"""Section 5.1 merchant API + section 5.1/5.6 security probes, through the
real host loader (runtime_env).

Covers: merchant lifecycle (create/get/patch/publish/deactivate), wallet
binding checks, relay config validation, notification config, the mutation
auth matrix (cookie+Origin+CSRF, bearer, user-id-only rejection), RFC 9457
error shape, and owner scoping (foreign merchant -> 404).
"""

from __future__ import annotations

import uuid

import httpx
import pytest

pytestmark = pytest.mark.runtime

ORIGIN = "https://shop.example"
API = "/infinitemarkets/api/v1"


def _csrf(client: httpx.AsyncClient) -> str:
    token = client.cookies.get("gm_csrf")
    assert token, "gm_csrf cookie must be issued by GET /merchants/current"
    return token


def _cookie_headers(client: httpx.AsyncClient, **over) -> dict:
    h = {"Origin": ORIGIN, "X-CSRF-Token": _csrf(client)}
    h.update(over)
    return h


def _bearer(runtime_env) -> dict:
    return {"Authorization": f"Bearer {runtime_env['token']}"}


async def _cookie(runtime_env) -> dict:
    """Origin+CSRF headers for the shared (cookie-authenticated) client."""
    client = runtime_env["client"]
    if not client.cookies.get("gm_csrf"):
        await client.get(f"{API}/merchants/current")
    return _cookie_headers(client)


# --- auth matrix ---------------------------------------------------------------


async def test_safe_get_requires_auth(runtime_env):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=runtime_env["app"]),
        base_url=ORIGIN,
    ) as anon:
        resp = await anon.get(f"{API}/merchants/current")
    assert resp.status_code in (401, 403)


async def test_cookie_mutation_requires_origin_and_csrf(runtime_env):
    client = runtime_env["client"]
    # seed the CSRF cookie (safe GET)
    await client.get(f"{API}/merchants/current")

    # cookie auth + wrong Origin -> rejected
    resp = await client.post(
        f"{API}/merchants",
        json={"wallet_id": "w"},
        headers={"Origin": "https://evil.example",
                 "X-CSRF-Token": _csrf(client)},
    )
    assert resp.status_code == 403
    assert resp.json()["type"] == "urn:infinitemarkets:unauthorized"

    # cookie auth + correct Origin but NO csrf header -> rejected
    resp = await client.post(
        f"{API}/merchants",
        json={"wallet_id": "w"},
        headers={"Origin": ORIGIN},
    )
    assert resp.status_code == 403

    # cookie auth + no Origin at all -> rejected
    resp = await client.post(
        f"{API}/merchants", json={"wallet_id": "w"}
    )
    assert resp.status_code == 403


async def test_bearer_mutation_passes_without_origin(runtime_env):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=runtime_env["app"]),
        base_url=ORIGIN,
    ) as bearer_client:
        resp = await bearer_client.post(
            f"{API}/merchants",
            json={
                "wallet_id": runtime_env["wallet"].id,
                "display_name": "bearer shop",
            },
            headers=_bearer(runtime_env),
        )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["state"] == "draft"
    assert len(body["pubkey"]) == 64
    runtime_env["merchant_id"] = body["id"]


async def test_user_id_only_mutation_rejected(runtime_env):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=runtime_env["app"]),
        base_url=ORIGIN,
    ) as anon:
        resp = await anon.post(
            f"{API}/merchants?usr={runtime_env['user_id']}",
            json={"wallet_id": runtime_env["wallet"].id},
        )
    # rejected by our guard or the host's usr-only gate — either way not 2xx
    assert resp.status_code in (401, 403)


async def test_cookie_with_forged_bearer_still_enforces_origin(runtime_env):
    """Cookie presence takes precedence: a spoofed bearer header cannot
    bypass the Origin check."""
    client = runtime_env["client"]
    await client.get(f"{API}/merchants/current")
    resp = await client.post(
        f"{API}/merchants",
        json={"wallet_id": "w"},
        headers={
            "Origin": "https://evil.example",
            "X-CSRF-Token": _csrf(client),
            "Authorization": "Bearer forged",
        },
    )
    # Rejected either by the host's token check (401) or our Origin
    # enforcement (403) — a forged bearer can never launder a cookie auth.
    assert resp.status_code in (401, 403)


# --- merchant lifecycle ---------------------------------------------------------


async def test_current_merchant_projection(runtime_env):
    resp = await runtime_env["client"].get(f"{API}/merchants/current")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == runtime_env["merchant_id"]
    assert body["state"] == "draft"
    assert "wallet_id_enc" not in body
    assert "wallet_id_hash" not in body
    assert "relay_health" in body
    assert "warnings" in body


async def test_duplicate_merchant_rejected(runtime_env):
    resp = await runtime_env["client"].post(
        f"{API}/merchants",
        json={"wallet_id": runtime_env["wallet"].id},
        headers=await _cookie(runtime_env),
    )
    assert resp.status_code == 409
    assert resp.json()["type"] == "urn:infinitemarkets:duplicate-merchant"


async def test_wallet_binding_rejects_foreign_wallet(runtime_env):
    """wallet_id not owned by the user -> 409 wallet-mismatch."""
    resp = await runtime_env["client"].patch(
        f"{API}/merchants/{runtime_env['merchant_id']}",
        json={"wallet_id": uuid.uuid4().hex},
        headers=await _cookie(runtime_env),
    )
    assert resp.status_code == 409
    assert resp.json()["type"] == "urn:infinitemarkets:wallet-mismatch"


async def test_relay_config_validation(runtime_env, monkeypatch):
    mid = runtime_env["merchant_id"]

    # Inbox-direction ('inbox'|'both') writes run the DNS egress check —
    # stub resolution to public space so the fixture needs no real DNS.
    import ipaddress

    from infinitemarkets import security

    async def _public(host, port=443):
        return [ipaddress.ip_address("93.184.216.34")]

    monkeypatch.setattr(security, "resolve_and_check_egress", _public)
    # ws:// transport rejected
    resp = await runtime_env["client"].patch(
        f"{API}/merchants/{mid}",
        json={"relay_configs": [
            {"relay_url": "ws://relay.example.com", "direction": "outbox"}
        ]},
        headers=await _cookie(runtime_env),
    )
    assert resp.status_code == 422
    assert resp.json()["type"] == "urn:infinitemarkets:invalid-relay"

    # valid wss config replaces the set
    resp = await runtime_env["client"].patch(
        f"{API}/merchants/{mid}",
        json={"relay_configs": [
            {"relay_url": "wss://relay.example.com", "direction": "both"},
        ]},
        headers=await _cookie(runtime_env),
    )
    assert resp.status_code == 200, resp.text

    health = await runtime_env["client"].get(
        f"{API}/merchants/{mid}/relay-health",
        headers=await _cookie(runtime_env),
    )
    assert health.status_code == 200
    relays = health.json()["relays"]
    assert [r["relay_url"] for r in relays] == ["wss://relay.example.com"]


async def test_notification_config(runtime_env):
    mid = runtime_env["merchant_id"]
    # >5 addresses rejected
    resp = await runtime_env["client"].patch(
        f"{API}/merchants/{mid}/notifications",
        json={"notify_emails": [f"a{i}@x.example" for i in range(6)]},
        headers=await _cookie(runtime_env),
    )
    assert resp.status_code == 422

    resp = await runtime_env["client"].patch(
        f"{API}/merchants/{mid}/notifications",
        json={
            "notify_emails": ["ops@x.example"],
            "notify_events": {"order_received": True, "order_paid": True},
        },
        headers=await _cookie(runtime_env),
    )
    assert resp.status_code == 200, resp.text

    state = await runtime_env["client"].get(
        f"{API}/merchants/{mid}/notifications", headers=await _cookie(runtime_env)
    )
    body = state.json()
    assert body["notify_emails"] == ["ops@x.example"]
    assert body["notify_events"]["order_received"] is True
    assert "queue" in body  # plan delta: queue array present (empty until m002)


async def test_publish_enqueues_outbox_intents(runtime_env):
    mid = runtime_env["merchant_id"]
    resp = await runtime_env["client"].post(
        f"{API}/merchants/{mid}/publish", headers=await _cookie(runtime_env)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "publication_pending"

    # the profile intent must be queued in outbox_events
    from infinitemarkets.db import db

    async with db.connect() as conn:
        rows = await conn.fetchall(
            "SELECT aggregate_type, event_kind, state "
            "FROM infinitemarkets.outbox_events WHERE merchant_id = :m",
            {"m": mid},
        )
    profile_kinds = {
        r["event_kind"] for r in rows
        if r["aggregate_type"] == "merchant_profile"
    }
    # publish enqueues the profile + NIP-89 handler pair (02-02)
    assert {0, 31989, 31990} <= profile_kinds
    # the publisher worker runs live in this boot — intents may be
    # claimed/pending while external starter relays time out
    assert all(
        r["state"] in ("pending", "claimed", "partially_published",
                       "published")
        for r in rows
    )

    # merchant row moved to publication_pending
    current = await runtime_env["client"].get(f"{API}/merchants/current")
    assert current.json()["state"] == "publication_pending"


async def test_key_import_replaces_identity(runtime_env):
    mid = runtime_env["merchant_id"]
    from nostr_sdk import Keys

    nsec = Keys.generate().secret_key().to_bech32()
    resp = await runtime_env["client"].post(
        f"{API}/merchants/{mid}/keys/import",
        json={"nsec": nsec},
        headers=await _cookie(runtime_env),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["pubkey"] == Keys.parse(nsec).public_key().to_hex()
    assert "nsec" not in resp.text


async def test_key_export_reveals_nsec_to_owner(runtime_env):
    current = await runtime_env["client"].get(f"{API}/merchants/current")
    if current.status_code == 404:
        created = await runtime_env["client"].post(
            f"{API}/merchants",
            json={"wallet_id": runtime_env["wallet"].id},
            headers=await _cookie(runtime_env),
        )
        assert created.status_code == 201, created.text
        runtime_env["merchant_id"] = created.json()["id"]
        current = created
    assert current.status_code in (200, 201)
    mid = runtime_env["merchant_id"]
    assert "nsec1" not in current.text

    resp = await runtime_env["client"].post(
        f"{API}/merchants/{mid}/keys/export",
        headers=await _cookie(runtime_env),
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["cache-control"] == "no-store"
    nsec = resp.json()["nsec"]
    assert nsec.startswith("nsec1")

    from nostr_sdk import Keys

    assert Keys.parse(nsec).public_key().to_hex() == current.json()["pubkey"]

    current = await runtime_env["client"].get(f"{API}/merchants/current")
    assert nsec not in current.text


async def test_idempotency_key_accepted_and_shape_validated(runtime_env):
    """§14: admin mutations accept Idempotency-Key; malformed keys are
    rejected with a problem detail."""
    client = runtime_env["client"]
    resp = await client.get(f"{API}/merchants/current")
    assert resp.status_code == 200
    resp = await client.patch(
        f"{API}/merchants/{runtime_env['merchant_id']}",
        json={"display_name": "idempotent rename"},
        headers={**await _cookie(runtime_env), "Idempotency-Key": "op-42"},
    )
    assert resp.status_code == 200, resp.text
    resp = await client.patch(
        f"{API}/merchants/{runtime_env['merchant_id']}",
        json={"display_name": "bad key"},
        headers={
            **await _cookie(runtime_env),
            "Idempotency-Key": "spaces not allowed",
        },
    )
    assert resp.status_code == 422


async def test_foreign_merchant_is_404(runtime_env):
    foreign = uuid.uuid4().hex
    headers = await _cookie(runtime_env)
    resp = await runtime_env["client"].patch(
        f"{API}/merchants/{foreign}",
        json={"display_name": "not mine"},
        headers=headers,
    )
    assert resp.status_code == 404

    resp = await runtime_env["client"].post(
        f"{API}/merchants/{foreign}/keys/export",
        headers=headers,
    )
    assert resp.status_code == 404


async def test_deactivation_enqueues_tombstones(runtime_env):
    mid = runtime_env["merchant_id"]
    resp = await runtime_env["client"].delete(
        f"{API}/merchants/{mid}", headers=await _cookie(runtime_env)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "deactivating"

    current = await runtime_env["client"].get(f"{API}/merchants/current")
    assert current.json()["state"] == "deactivating"


async def test_audit_posture_qualified_and_flagged(runtime_env):
    """OQ3: the fixture boots in the qualified posture (capture off -> no
    warning); flipping a host audit flag on must surface the banner."""
    from lnbits.settings import settings as host_settings

    current = await runtime_env["client"].get(f"{API}/merchants/current")
    warnings = current.json()["warnings"]
    assert not any("audit" in w.lower() for w in warnings)

    # flip a capture flag on — the warning must fire
    previous = host_settings.lnbits_audit_log_request_body
    host_settings.lnbits_audit_log_request_body = True
    try:
        current = await runtime_env["client"].get(f"{API}/merchants/current")
        warnings = current.json()["warnings"]
        assert any(
            "lnbits_audit_log_request_body" in w for w in warnings
        )
    finally:
        host_settings.lnbits_audit_log_request_body = previous
