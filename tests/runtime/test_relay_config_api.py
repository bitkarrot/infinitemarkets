"""Relay/blossom endpoint configurability + outbox admin routes — API level.

Owner directive (2026-09-22): merchants configure their own publication,
inbox, and blossom media endpoints with starter defaults surfaced by the
health route. Relay ``direction`` is the normative ``public|inbox|both``
vocabulary; blossom endpoints are https:// media servers validated under
the same SSRF posture (spec delta, recorded in 02-02-SUMMARY.md).
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.runtime


def _headers(env: dict, csrf: str | None = None) -> dict:
    # Real cookie jar semantics: auth + double-submit cookie travel together.
    cookie = f"cookie_access_token={env['token']}"
    if csrf:
        cookie += f"; gm_csrf={csrf}"
    h = {"Cookie": cookie, "Origin": "https://shop.example"}
    if csrf:
        h["X-CSRF-Token"] = csrf
    return h


async def _merchant_id(env: dict) -> tuple[str, str]:
    """Create a merchant; return (merchant_id, csrf)."""
    client = env["client"]
    # the boundary issues gm_csrf on any authenticated request — seed it;
    # the shared user gets exactly one merchant (user_id UNIQUE).
    existing = await client.get(
        "/infinitemarkets/api/v1/merchants/current", headers=_headers(env)
    )
    if existing.status_code == 200:
        return existing.json()["id"], _csrf(client)
    resp = await client.post(
        "/infinitemarkets/api/v1/merchants",
        json={"wallet_id": env["wallet"].id},
        headers=_headers(env, _csrf(client)),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"], _csrf(client)


def _csrf(client) -> str:
    return client.cookies.get("gm_csrf") or ""


async def test_relay_config_accepts_public_inbox_both(runtime_env,
                                                    monkeypatch):
    client, env = runtime_env["client"], runtime_env
    mid, csrf = await _merchant_id(env)

    # Inbox-direction writes also run the DNS egress check (D-30) — stub
    # resolution to public space so the fixture needs no real DNS.
    import ipaddress

    from infinitemarkets import security

    async def _public(host, port=443):
        return [ipaddress.ip_address("93.184.216.34")]

    monkeypatch.setattr(security, "resolve_and_check_egress", _public)

    resp = await client.patch(
        f"/infinitemarkets/api/v1/merchants/{mid}",
        json={
            "relay_configs": [
                {"relay_url": "wss://relay-a.example", "direction": "public"},
                {"relay_url": "wss://relay-b.example", "direction": "inbox"},
                {"relay_url": "wss://relay-c.example", "direction": "both"},
                {
                    "relay_url": "wss://relay-d.example",
                    "direction": "public",
                    "enabled": False,
                },
            ]
        },
        headers=_headers(env, csrf),
    )
    assert resp.status_code == 200, resp.text

    health = await client.get(
        f"/infinitemarkets/api/v1/merchants/{mid}/relay-health",
        headers=_headers(env),
    )
    assert health.status_code == 200, health.text
    body = health.json()
    relays = {r["relay_url"]: r for r in body["relays"]}
    assert relays["wss://relay-a.example"]["direction"] == "public"
    assert relays["wss://relay-b.example"]["direction"] == "inbox"
    assert relays["wss://relay-c.example"]["direction"] == "both"
    assert relays["wss://relay-d.example"]["enabled"] is False
    # starter defaults surface for the admin UI
    assert "wss://relay.damus.io" in body["defaults"]["relays"]
    assert body["defaults"]["blossom_servers"]


async def test_inbox_direction_requires_public_dns(runtime_env,
                                                   monkeypatch):
    """D-30: a relay_configs write with direction 'inbox'|'both' fails
    when the host resolves private/unresolvable; 'public' targets keep
    syntactic-only validation."""
    client, env = runtime_env["client"], runtime_env
    mid, csrf = await _merchant_id(env)


    from infinitemarkets import security
    from infinitemarkets.security import unprocessable

    async def _private(host, port=443):
        raise unprocessable(
            "invalid-relay",
            "Relay host does not resolve to public routable space",
        )

    monkeypatch.setattr(security, "resolve_and_check_egress", _private)
    for direction in ("inbox", "both"):
        resp = await client.patch(
            f"/infinitemarkets/api/v1/merchants/{mid}",
            json={"relay_configs": [
                {"relay_url": "wss://relay-b.example",
                 "direction": direction},
            ]},
            headers=_headers(env, csrf),
        )
        assert resp.status_code == 422, (direction, resp.status_code)

    # 'public' direction never touches DNS — passes even when resolution
    # would fail.
    resp = await client.patch(
        f"/infinitemarkets/api/v1/merchants/{mid}",
        json={"relay_configs": [
            {"relay_url": "wss://relay-a.example", "direction": "public"},
        ]},
        headers=_headers(env, csrf),
    )
    assert resp.status_code == 200, resp.text


async def test_relay_config_rejects_invalid_and_duplicates(runtime_env):
    client, env = runtime_env["client"], runtime_env
    mid, csrf = await _merchant_id(env)
    for configs in (
        [{"relay_url": "http://relay.example"}],
        [{"relay_url": "wss://127.0.0.1:7777"}],
        [{"relay_url": "wss://localhost"}],
        [{"relay_url": "wss://user:pw@relay.example"}],
        [{"relay_url": "wss://a.example", "direction": "outbox"}],
        [
            {"relay_url": "wss://dup.example", "direction": "public"},
            {"relay_url": "wss://dup.example", "direction": "public"},
        ],
    ):
        resp = await client.patch(
            f"/infinitemarkets/api/v1/merchants/{mid}",
            json={"relay_configs": configs},
            headers=_headers(env, csrf),
        )
        assert resp.status_code == 422, (configs, resp.status_code, resp.text)


async def test_blossom_servers_configurable_with_https_only(runtime_env):
    client, env = runtime_env["client"], runtime_env
    mid, csrf = await _merchant_id(env)
    resp = await client.patch(
        f"/infinitemarkets/api/v1/merchants/{mid}",
        json={
            "blossom_servers": [
                "https://blossom.primal.net",
                "https://media.example.com",
            ]
        },
        headers=_headers(env, csrf),
    )
    assert resp.status_code == 200, resp.text

    health = await client.get(
        f"/infinitemarkets/api/v1/merchants/{mid}/relay-health",
        headers=_headers(env),
    )
    assert health.json()["blossom_servers"] == [
        "https://blossom.primal.net",
        "https://media.example.com",
    ]

    for bad in ("http://media.example.com", "https://127.0.0.1:3000",
                "https://user:pw@media.example.com"):
        resp = await client.patch(
            f"/infinitemarkets/api/v1/merchants/{mid}",
            json={"blossom_servers": [bad]},
            headers=_headers(env, csrf),
        )
        assert resp.status_code in (400, 422), (bad, resp.status_code)


async def test_outbox_listing_and_retry_routes(runtime_env):
    """W-NEW-1 spec-delta routes: owner-scoped listing + retry."""
    client, env = runtime_env["client"], runtime_env
    mid, csrf = await _merchant_id(env)

    resp = await client.get(
        f"/infinitemarkets/api/v1/merchants/{mid}/outbox",
        headers=_headers(env),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["intents"] == []

    # publishing enqueues intents (profile + handler pair) that surface here
    resp = await client.post(
        f"/infinitemarkets/api/v1/merchants/{mid}/publish",
        headers=_headers(env, csrf),
    )
    assert resp.status_code == 200, resp.text
    listing = await client.get(
        f"/infinitemarkets/api/v1/merchants/{mid}/outbox",
        headers=_headers(env),
    )
    intents = listing.json()["intents"]
    assert intents, "publish must enqueue intents"
    kinds = {i["event_kind"] for i in intents}
    assert {0, 31989, 31990} <= kinds
    for intent in intents:
        assert "relay_publications" in intent
        assert "depends_on" in intent

    # starter defaults are surfaced for the UI (this merchant already has
    # configured relays, so publish does not seed — seeding is pinned by
    # test_relay_targets_direction_and_defaults in test_outbox.py)
    health = await client.get(
        f"/infinitemarkets/api/v1/merchants/{mid}/relay-health",
        headers=_headers(env),
    )
    assert "wss://relay.damus.io" in health.json()["defaults"]["relays"]

    # a published intent rejects retry
    intent_id = intents[0]["id"]
    resp = await client.post(
        f"/infinitemarkets/api/v1/merchants/{mid}/outbox/{intent_id}/retry",
        headers=_headers(env, csrf),
    )
    assert resp.status_code == 409, resp.text

    # other-merchant access is forbidden
    resp = await client.get(
        f"/infinitemarkets/api/v1/merchants/{uuid.uuid4().hex}/outbox",
        headers=_headers(env),
    )
    assert resp.status_code in (403, 404)


async def test_outbox_prune_history(runtime_env):
    """Prune deletes only terminal outbox rows past the window, with
    their relay evidence and dependency edges; in-flight rows survive."""
    import time

    from infinitemarkets.db import db, table

    client, env = runtime_env["client"], runtime_env
    mid, csrf = await _merchant_id(env)
    now = int(time.time())
    old = now - 100 * 86400

    async def ins_outbox(i, state, ts):
        await conn.execute(
            f"INSERT INTO {table('outbox_events')} "
            "(id, merchant_id, aggregate_type, aggregate_id, event_kind,"
            " state, created_at, updated_at)"
            " VALUES (:i, :m, 'product', :i, 30402, :s, :t, :t)",
            {"i": i, "m": mid, "s": state, "t": ts},
        )

    async with db.connect() as conn:
        for i, (state, ts) in enumerate((
            ("published", old), ("superseded", old), ("failed", old),
            ("published", now), ("pending", old), ("claimed", old),
        )):
            await ins_outbox(f"pr-{i}", state, ts)
        await conn.execute(
            f"INSERT INTO {table('relay_publications')} "
            "(id, outbox_event_id, delivery_copy, relay_url, event_id,"
            " attempt_no, result, attempted_at)"
            " VALUES ('rp-0', 'pr-0', 'a', 'wss://x', 'e', 1, 'accepted', :t)",
            {"t": old},
        )
        # an edge where the pruned side is the DEPENDENCY
        await conn.execute(
            f"INSERT INTO {table('outbox_dependencies')} "
            "(outbox_event_id, depends_on_outbox_event_id)"
            " VALUES ('pr-4', 'pr-0')",
        )

    async def listed():
        r = await client.get(
            f"/infinitemarkets/api/v1/merchants/{mid}/outbox",
            headers=_headers(env),
        )
        return {i["id"] for i in r.json()["intents"]}

    mine = {f"pr-{i}" for i in range(6)}
    assert mine <= await listed()

    resp = await client.post(
        f"/infinitemarkets/api/v1/merchants/{mid}/outbox/prune",
        json={"older_than_days": 30},
        headers=_headers(env, csrf),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["pruned"] == 3
    assert (await listed()) & mine == {"pr-3", "pr-4", "pr-5"}

    # evidence + edge rows went with the deleted events — including the
    # edge where the pruned row was the dependency (either-side match)
    async with db.connect() as conn:
        assert (await conn.fetchone(
            f"SELECT COUNT(*) n FROM {table('relay_publications')} "
            "WHERE outbox_event_id IN ('pr-0', 'pr-1', 'pr-2')"
        ))["n"] == 0
        assert (await conn.fetchone(
            f"SELECT COUNT(*) n FROM {table('outbox_dependencies')} "
            "WHERE outbox_event_id IN ('pr-0', 'pr-1', 'pr-2') "
            "OR depends_on_outbox_event_id IN ('pr-0', 'pr-1', 'pr-2')"
        ))["n"] == 0

    # bounds are enforced
    for bad in (0, 6, 4000):
        resp = await client.post(
            f"/infinitemarkets/api/v1/merchants/{mid}/outbox/prune",
            json={"older_than_days": bad},
            headers=_headers(env, csrf),
        )
        assert resp.status_code in (400, 422), (bad, resp.status_code)

    resp = await client.post(
        f"/infinitemarkets/api/v1/merchants/{uuid.uuid4().hex}/outbox/prune",
        json={"older_than_days": 30},
        headers=_headers(env, csrf),
    )
    assert resp.status_code in (403, 404)


async def test_catalog_relay_check(runtime_env, monkeypatch):
    """Owner-triggered relay reconciliation distinguishes stale, missing,
    divergent, tombstoned, and duplicate local product records."""
    import json
    import time

    from nostr_sdk import EventBuilder, Kind, PublicKey, Tag, Timestamp

    from harness.relay import LocalRelay, RelayMode
    from infinitemarkets.db import DomainTransaction, db, table
    from infinitemarkets.keystore import MerchantKeyStore
    from infinitemarkets.settings import ext_settings

    monkeypatch.setenv("INFINITEMARKETS_RELAY_IO", "on")
    monkeypatch.setenv("INFINITEMARKETS_ALLOW_INSECURE_RELAYS", "1")
    client, env = runtime_env["client"], runtime_env
    mid, csrf = await _merchant_id(env)
    merchant = await client.get(
        "/infinitemarkets/api/v1/merchants/current",
        headers=_headers(env),
    )
    pubkey = merchant.json()["pubkey"]

    title = f"relay-check-{uuid.uuid4().hex[:8]}"
    category = await client.post(
        "/infinitemarkets/api/v1/categories",
        json={"name": "Relay check", "default_currency": "SAT"},
        headers=_headers(env, csrf),
    )
    assert category.status_code == 201, category.text
    cid = category.json()["id"]

    async def product(name, stock=5, fmt="physical"):
        payload = {
            "category_id": cid,
            "title": name,
            "amount_minor": 100,
            "currency": "SAT",
            "visibility": "on-sale",
            "format": fmt,
        }
        if stock is not None:
            payload["stock_on_hand"] = stock
        resp = await client.post(
            "/infinitemarkets/api/v1/products",
            json=payload,
            headers=_headers(env, csrf),
        )
        assert resp.status_code == 201, resp.text
        return resp.json()

    active = await product(title)
    duplicate = await product(title)
    digital = await product(f"digital-{title}", stock=None, fmt="digital")
    deleted = await product(f"deleted-{title}")
    now = int(time.time())
    async with DomainTransaction() as tx:
        await tx.execute(
            f"UPDATE {tx.table('products')} SET deleted_at = :t"
            " WHERE id = :i",
            {"t": now, "i": deleted["id"]},
        )

    async def signed(kind, content, tags, created_at):
        unsigned = (
            EventBuilder(Kind(kind), content)
            .tags([Tag.parse(tag) for tag in tags])
            .custom_created_at(Timestamp.from_secs(created_at))
            .build(PublicKey.parse(pubkey))
        )
        event = await MerchantKeyStore(ext_settings()).sign_event(
            mid, unsigned
        )
        return json.loads(event.as_json())

    active_old = await signed(
        30402, "old copy",
        [["d", active["d_tag"]], ["title", title],
         ["visibility", "on-sale"], ["stock", "5"]],
        now - 20,
    )
    active_new = await signed(
        30402, "new copy",
        [["d", active["d_tag"]], ["title", title],
         ["visibility", "on-sale"], ["stock", "5"]],
        now - 10,
    )
    deleted_event = await signed(
        30402, "deleted copy",
        [["d", deleted["d_tag"]], ["title", f"deleted-{title}"],
         ["visibility", "on-sale"], ["stock", "3"]],
        now - 30,
    )
    digital_event = await signed(
        30402, "digital copy",
        [["d", digital["d_tag"]], ["title", f"digital-{title}"],
         ["visibility", "on-sale"], ["type", "simple", "digital"]],
        now - 15,
    )
    tombstone = await signed(
        5, "deleted",
        [["a", f"30402:{pubkey}:{deleted['d_tag']}"], ["k", "30402"]],
        now - 5,
    )

    relay_a = await LocalRelay(
        mode=RelayMode.ACCEPTING,
        canned_events=[active_new, digital_event, deleted_event, tombstone],
    ).start()
    relay_b = await LocalRelay(
        mode=RelayMode.ACCEPTING,
        canned_events=[active_old, deleted_event],
    ).start()
    relay_a_url, relay_b_url = relay_a.url, relay_b.url
    try:
        patch = await client.patch(
            f"/infinitemarkets/api/v1/merchants/{mid}",
            json={"relay_configs": [
                {"relay_url": relay_a.url, "direction": "public"},
                {"relay_url": relay_b.url, "direction": "public"},
            ]},
            headers=_headers(env, csrf),
        )
        assert patch.status_code == 200, patch.text
        resp = await client.post(
            f"/infinitemarkets/api/v1/merchants/{mid}/catalog/relay-check",
            json={},
            headers=_headers(env, csrf),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        rows = {
            i["address"]: i for i in body["items"] if i["kind"] == 30402
        }
        deleted_row = rows[f"30402:{pubkey}:{deleted['d_tag']}"]
        reissue = await client.post(
            f"/infinitemarkets/api/v1/merchants/{mid}/catalog/tombstones/reissue",
            json={"addresses": [
                deleted_row["address"], deleted_row["address"]
            ]},
            headers=_headers(env, csrf),
        )
        assert reissue.status_code == 200, reissue.text
        again = await client.post(
            f"/infinitemarkets/api/v1/merchants/{mid}/catalog/tombstones/reissue",
            json={"addresses": [deleted_row["address"]]},
            headers=_headers(env, csrf),
        )
        assert again.status_code == 200, again.text
        from infinitemarkets.services import outbox

        outcome = await outbox.worker_tick("tombstone-test")
        deleted_address = deleted_row["address"]

        def tombstone_received(relay):
            return any(
                item.get("event", {}).get("kind") == 5
                and [
                    tag for tag in item.get("event", {}).get("tags", [])
                    if len(tag) > 1 and tag[0] == "a"
                    and tag[1] == deleted_address
                ]
                for item in relay.received_events
            )

        tombstone_sent = (
            tombstone_received(relay_a) and tombstone_received(relay_b)
        )
    finally:
        await relay_a.stop()
        await relay_b.stop()

    assert body["pubkey"] == pubkey
    assert all(r["state"] == "ok" for r in body["relays"])
    assert all(r["invalid_events"] == 0 for r in body["relays"])
    active_row = rows[f"30402:{pubkey}:{active['d_tag']}"]
    assert active_row["status"] == "divergent"
    assert set(active_row["observed_on"]) == {relay_a_url, relay_b_url}
    assert "relay-divergence" in active_row["findings"]
    assert "same-title-local-records" in active_row["findings"]

    duplicate_row = rows[f"30402:{pubkey}:{duplicate['d_tag']}"]
    assert duplicate_row["status"] == "missing"
    assert "same-title-local-records" in duplicate_row["findings"]

    digital_row = rows[f"30402:{pubkey}:{digital['d_tag']}"]
    assert digital_row["status"] == "partial"
    assert digital_row["observed_on"] == [relay_a_url]
    assert digital_row["missing_on"] == [relay_b_url]
    assert "stock-tag-missing" in digital_row["findings"]

    assert deleted_row["status"] == "stale-deleted"
    assert deleted_row["tombstoned_on"] == [relay_a_url]
    assert "tombstone-did-not-remove-copy" in deleted_row["findings"]

    summary = body["summary"]
    assert summary["relays_checked"] == 2
    assert summary["divergent"] >= 1
    assert summary["stale_deleted"] >= 1
    assert summary["duplicate_title_groups"] >= 1
    assert "old copy" not in json.dumps(body)

    assert reissue.json()["queued"] == 1
    first_revision = reissue.json()["items"][0]["revision"]
    assert again.json()["items"][0]["revision"] > first_revision
    latest_intent_id = again.json()["items"][0]["outbox_event_id"]
    assert outcome["claimed"] >= 1
    assert tombstone_sent, (outcome, relay_a.received_events, relay_b.received_events)

    async with db.connect() as conn:
        intent = await conn.fetchone(
            f"SELECT id, event_address, event_kind, state,"
            f" aggregate_revision FROM {table('outbox_events')}"
            " WHERE id = :i",
            {"i": latest_intent_id},
        )
        publications = await conn.fetchall(
            f"SELECT relay_url, result FROM {table('relay_publications')}"
            " WHERE outbox_event_id = :i",
            {"i": latest_intent_id},
        )
    assert intent["event_address"] == deleted_row["address"]
    assert intent["state"] == "published"
    assert intent["aggregate_revision"] > first_revision
    assert {
        p["relay_url"] for p in publications if p["result"] == "accepted"
    } == {relay_a_url, relay_b_url}

    invalid = await client.post(
        f"/infinitemarkets/api/v1/merchants/{mid}/catalog/tombstones/reissue",
        json={"addresses": [active_row["address"]]},
        headers=_headers(env, csrf),
    )
    assert invalid.status_code == 422, invalid.text
