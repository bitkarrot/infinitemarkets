"""02-04 admin shell + surfaces contract — the served admin document and
its JS modules carry the UI-SPEC invariants: one nav section, Linear
Split workspace grid, verbatim copy, no-secret boundaries, legal-action
surface, and host-palette-only theming (no merchant tokens)."""

from __future__ import annotations

import asyncio
import re

import pytest
import pytest_asyncio

pytestmark = pytest.mark.runtime

ORIGIN = "https://shop.example"
API = "/infinitemarkets/api/v1"
JS = "/infinitemarkets/static/infinitemarkets/js"


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
        json={"wallet_id": runtime_env["wallet"].id,
              "display_name": "admin shop"},
        headers=await cookie(),
    )
    assert resp.status_code == 201, resp.text
    runtime_env["merchant_id"] = resp.json()["id"]
    yield


async def test_admin_shell_document(runtime_env):
    """The admin page mounts inside the host shell with all modules."""
    resp = await runtime_env["client"].get("/infinitemarkets/")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-store"
    html = resp.text
    assert 'id="gm-admin-root"' in html
    # One nav section — the five surfaces.
    for nav in ("orders", "catalog", "publications", "messages",
                "settings"):
        assert f'data-gm-nav="{nav}"' in html, nav
    assert '<q-item-section>Catalog</q-item-section>' in html
    assert '<h1 class="text-h6 q-my-none col">Catalog</h1>' in html
    assert '<q-tab name="categories" label="Categories"></q-tab>' in html
    assert 'data-gm-surface="messages"' in html
    # Every module script loads.
    revisions = set()
    for mod in ("admin_app", "admin_orders", "admin_catalog",
                "admin_publications", "admin_messages", "admin_settings",
                "admin_notifications"):
        match = re.search(rf"{mod}\.js\?v=([0-9a-f]{{12}})", html)
        assert match, mod
        revisions.add(match.group(1))
    assert len(revisions) == 1
    about = await runtime_env["client"].get(f"{JS}/admin_about.js")
    assert about.status_code == 200
    assert 'admin-categories.jpg' not in about.text


async def test_product_editor_shipping_options(runtime_env):
    html = (await runtime_env["client"].get("/infinitemarkets/")).text
    assert 'v-model="gmCatalog.editor.form.shipping_option_ids"' in html
    assert 'label="Shipping options" :options="gmShippingChoices"' in html
    assert 'label="European Union (27 countries)"' in html
    assert 'Only individual country codes are saved.' in html
    js = (await runtime_env["client"].get(f"{JS}/admin_catalog.js")).text
    assert 'shipping_option_ids: (d.shipping_options || []).map' in js
    assert 'extra_cost_minor: extra' in js
    blocks = dict(re.findall(
        r'var (COUNTRY_CODES|EU_COUNTRIES) = \((.*?)\)\.split\(" "\);', js, re.S,
    ))
    codes = " ".join(re.findall(r'"([A-Z ]+)"', blocks["COUNTRY_CODES"])).split()
    eu = " ".join(re.findall(r'"([A-Z ]+)"', blocks["EU_COUNTRIES"])).split()
    assert len(codes) == len(set(codes)) == 249
    assert len(eu) == len(set(eu)) == 27
    assert set(eu) <= set(codes)
    assert {"US", "CA", "DE", "FR", "GB"} <= set(codes)
    assert "EU" not in codes


async def test_product_actions_precede_title(runtime_env):
    html = (await runtime_env["client"].get("/infinitemarkets/")).text
    assert html.index('data-col="actions"') < html.index('data-col="title"')
    assert html.index('data-col="delete"') > html.index('data-col="state"')
    js = (await runtime_env["client"].get(f"{JS}/admin_catalog.js")).text
    actions = js.index('{ name: "actions", label: "Actions"')
    title = js.index('{ name: "title", label: "Title"')
    delete = js.index('{ name: "delete", label: "Delete"')
    assert actions < title < delete


async def test_settings_key_reveal(runtime_env):
    html = (await runtime_env["client"].get("/infinitemarkets/")).text
    assert 'aria-label="Show private key"' in html
    assert 'label="Store secret key (nsec)"' in html
    assert 'Keep this key secret' in html
    js = (await runtime_env["client"].get(f"{JS}/admin_settings.js")).text
    assert '"/keys/export"' in js
    assert 'nsecReveal' in js
    assert "nsec1" not in html + js


async def test_migration_admin_surface(runtime_env):
    html = (await runtime_env["client"].get("/infinitemarkets/")).text
    assert 'data-gm-nav="migration"' in html
    assert 'data-gm-surface="migration"' in html
    assert 'data-gm="migration-history"' in html
    assert 'data-gm="migration-preview"' in html
    assert "Review and publish them" in html
    assert "gmMigration.sourceKind === 'shopify' && !gmMigration.currency" in html
    js = await runtime_env["client"].get(f"{JS}/admin_migration.js")
    assert js.status_code == 200
    assert "/migration/imports" in js.text
    assert "/migration/csv-presets" in js.text
    assert "cutovers" not in js.text


async def test_admin_verbatim_copy(runtime_env):
    """UI-SPEC copy strings render verbatim in the document."""
    resp = await runtime_env["client"].get("/infinitemarkets/")
    html = resp.text
    # B1 search placeholder.
    assert "Search order or buyer" in html
    # B2 relay outcomes are delivery evidence — never settlement.
    assert "delivery evidence" in html.lower()
    # B1 mobile navigation.
    assert "← Back to orders" in html
    # B6 boundary + layout notes and the B4 key-import note are JS
    # constants bound through Vue — assert them in the module.
    settings_js = (await runtime_env["client"].get(
        f"{JS}/admin_settings.js")).text
    assert (
        "Appearance applies to your public storefront only. It never"
        " changes the admin area, checkout fields, totals, validation,"
        " or payment states." in settings_js
    )
    assert "Mobile always uses the compact layout" in settings_js
    assert "Sent once over TLS and never displayed or logged." in settings_js
    # B2 empty-state copy.
    assert "No publications pending" in html
    assert "No write relays configured" in html


async def test_admin_workspace_layout(runtime_env):
    """B1 Linear Split grid — ~390px list desktop, ~320px medium,
    list→detail on ≤560px."""
    resp = await runtime_env["client"].get("/infinitemarkets/")
    blocks = re.findall(r"<style>(.*?)</style>", resp.text, re.S)
    css = next(b for b in blocks if ".gm-workspace" in b)
    assert "grid-template-columns: 390px minmax(0, 1fr)" in css
    assert "grid-template-columns: 320px minmax(0, 1fr)" in css
    assert "@media (max-width: 560px)" in css


async def test_admin_no_secrets(runtime_env):
    """The admin document never renders nsec, bearer tokens, full payment
    evidence, or merchant theme tokens."""
    resp = await runtime_env["client"].get("/infinitemarkets/")
    html = resp.text
    # The nsec input is masked (password) and its value is never echoed.
    assert 'type="password"' in html
    assert "nsec1" not in html
    # Merchant theme tokens never style the admin shell.
    assert "gm-public {" not in html
    # No full BOLT11/payment-hash rendering surface — technical details
    # use truncated references only (asserted in admin_orders.js too).
    js = (await runtime_env["client"].get(f"{JS}/admin_orders.js")).text
    assert "bolt11" not in js  # never rendered anywhere in admin
    assert "payment_hash" not in js
    # Payment correlation renders only truncated references.
    assert "gmTrunc" in html


async def test_admin_js_legal_actions(runtime_env):
    """The action map only emits legal §7.1/§7.2 transitions."""
    js = (await runtime_env["client"].get(f"{JS}/admin_orders.js")).text
    # Exception branch carries the three resolutions.
    for action in ("accept", "refund", "confirm-refund"):
        assert f'key: "{action}"' in js
    # Shipping transitions are bounded to the §7.2 table targets.
    assert "ship:processing" in js
    assert "ship:shipped" in js
    assert "ship:delivered" in js
    # Token reissue posts to the §5.3 route and shows the link once.
    assert "/public-token/reissue" in js


async def test_admin_publications_copy(runtime_env):
    """B2 — relay ACKs labeled delivery evidence, missing relays named,
    retry only on failed/partial rows."""
    js = (await runtime_env["client"].get(
        f"{JS}/admin_publications.js")).text
    assert "partially_published" in js
    assert "/outbox/" in js and "/retry" in js
    # The outbox state pills cover the full durable vocabulary.
    for state in ("pending", "claimed", "publishing",
                  "partially_published", "failed", "superseded"):
        assert state in js
    # Timestamps + row-detail surface (queued/updated shown in the table,
    # full intent fields + per-relay evidence in the detail dialog).
    assert "gmPubKindLabel" in js and "gmPubDetailFields" in js
    html = (await runtime_env["client"].get("/infinitemarkets/")).text
    assert 'data-gm="outbox-row"' in html
    assert 'data-gm="outbox-detail"' in html
    assert "Queued" in html


async def test_admin_notifications_copy(runtime_env):
    """B5 — per-event toggles incl. on_hold, test-send, queue states."""
    js = (await runtime_env["client"].get(
        f"{JS}/admin_notifications.js")).text
    for ev in ("order_received", "confirmed", "on_hold"):
        assert ev in js
    assert "/notifications/test" in js
    assert "Suppressed" in js
    assert "Failed after" in js


async def test_admin_theme_editor(runtime_env):
    """B6 — Tiered Controls: presets, bounded brand basics, opt-in
    advanced tokens, live contrast gate, public-only preview."""
    js = (await runtime_env["client"].get(
        f"{JS}/admin_settings.js")).text
    for preset in ("warm-market", "clean-minimal", "high-contrast"):
        assert preset in js
    assert "advanced_opt_in" in js
    # Client-side WCAG math mirrors the server gate.
    assert "4.5" in js
    assert "contrast" in js
    # Preview tokens resolve client-side (preset → brand → advanced).
    assert "gmPreviewTokens" in js


# --- GAM-04 Messages workspace (plan 03-03 Task 4) ------------------------------


async def _seed_dm(
    runtime_env, merchant: dict, *, buyer_pubkey: str,
    subject: str | None, content: str,
) -> str:
    """Feed one inbound kind-14 through the real handler — the same
    threading + sender-hash math the inbox uses."""
    import time
    import uuid

    from infinitemarkets.services import order_messages
    from infinitemarkets.settings import ext_settings

    settings = ext_settings()
    sender_hash = order_messages.buyer_hash(
        settings, merchant["id"], buyer_pubkey
    )
    rumor = {
        "content": content,
        "tags": [["subject", subject]] if subject else [],
        "created_at": int(time.time()),
    }
    result = await order_messages.handle_dm(
        merchant=merchant, sender_hash=sender_hash,
        author_pubkey=buyer_pubkey, rumor=rumor,
        rumor_id=uuid.uuid4().hex, now=int(time.time()),
    )
    return result["conversation_id"]


async def _sign_in(runtime_env, label: str) -> "tuple":
    import time

    import httpx
    from nostr_sdk import (
        EventBuilder,
        Kind,
        NostrSigner,
        Tag,
        Timestamp,
    )

    from harness.sdk import fixed_test_keys

    env = runtime_env
    keys = fixed_test_keys(label)
    buyer = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=env["app"]), base_url=ORIGIN
    )
    resp = await buyer.get(f"{API}/public/nostr/challenge")
    challenge = resp.json()["challenge"]
    event = await (
        EventBuilder(Kind(22242), challenge)
        .tags([Tag.parse(["challenge", challenge])])
        .custom_created_at(Timestamp.from_secs(int(time.time())))
        .sign(NostrSigner.keys(keys))
    )
    resp = await buyer.post(
        f"{API}/public/nostr/verify",
        json={"event": event.as_json()},
        headers={"Origin": ORIGIN},
    )
    assert resp.status_code == 200, resp.text
    return buyer, keys


async def test_messages_workspace(runtime_env):
    """GAM-04 conversations/thread/read/unread/delivery + compose +
    rejected-intake + cross-tenant isolation."""
    import time
    import uuid

    env = runtime_env
    client = env["client"]
    mid = env["merchant_id"]

    async def cookie() -> dict:
        return {
            "Origin": ORIGIN,
            "X-CSRF-Token": client.cookies.get("gm_csrf"),
        }

    from infinitemarkets import crypto
    from infinitemarkets.db import DomainTransaction
    from infinitemarkets.services import order_messages
    from infinitemarkets.settings import ext_settings

    # Merchant row + active inbox (messages surface needs merchant state).
    async with DomainTransaction() as tx:
        await tx.execute(
            "UPDATE merchants SET state = 'active',"
            " inbox_state = 'active' WHERE id = :m",
            {"m": mid},
        )
    async with env["ext_module"].db.connect() as conn:
        merchant = dict(
            await conn.fetchone(
                "SELECT * FROM infinitemarkets.merchants WHERE id = :m",
                {"m": mid},
            )
        )

    # A product to order.
    resp = await client.post(
        f"{API}/categories",
        json={"name": "msgs", "default_currency": "SAT"},
        headers=await cookie(),
    )
    assert resp.status_code == 201, resp.text
    resp = await client.post(
        f"{API}/products",
        json={
            "category_id": resp.json()["id"],
            "title": "msg widget",
            "amount_minor": 500,
            "currency": "SAT",
            "visibility": "on-sale",
            "stock_on_hand": 50,
            "format": "digital",
        },
        headers=await cookie(),
    )
    assert resp.status_code == 201, resp.text
    product = resp.json()

    # A web order, claimed by a signed-in buyer -> buyer bound.
    resp = await client.post(
        f"{API}/public/checkout",
        json={
            "merchant_pubkey": merchant["pubkey"],
            "items": [{"d_tag": product["d_tag"], "quantity": 1}],
            "email_opt_in": False,
        },
        headers={"Idempotency-Key": uuid.uuid4().hex},
    )
    assert resp.status_code == 201, resp.text
    token = resp.json()["public_token"]
    digest = crypto.token_lookup_hash(token)
    async with env["ext_module"].db.connect() as conn:
        orow0 = await conn.fetchone(
            "SELECT id FROM infinitemarkets.orders"
            " WHERE public_token_hash = :h",
            {"h": digest},
        )
    order_id = orow0["id"]
    buyer, keys = await _sign_in(env, "msg-buyer")
    resp = await buyer.post(
        f"{API}/public/nostr/claim",
        json={"token": token},
        headers={"Origin": ORIGIN},
    )
    assert resp.status_code == 200, resp.text
    buyer_hex = keys.public_key().to_hex()

    # Order-bound DM threads onto order:<id>; a stranger's DM lands in
    # Unknown (D-14).
    async with env["ext_module"].db.connect() as conn:
        orow = await conn.fetchone(
            "SELECT external_id_enc FROM infinitemarkets.orders"
            " WHERE id = :o",
            {"o": order_id},
        )
    settings = ext_settings()
    ver = crypto.envelope_version(orow["external_id_enc"])
    ext_id = crypto.decrypt(
        orow["external_id_enc"], settings.master_keys[ver],
        record_id=order_id, table="orders",
        column="external_id_enc", key_version=ver,
    ).decode()
    conv_order = await _seed_dm(
        env, merchant, buyer_pubkey=buyer_hex,
        subject=ext_id, content="Is my order shipped yet?",
    )
    assert conv_order == f"order:{order_id}"
    from harness.sdk import fixed_test_keys

    stranger_hex = fixed_test_keys("stranger").public_key().to_hex()
    conv_unknown = await _seed_dm(
        env, merchant, buyer_pubkey=stranger_hex,
        subject=None, content="hello, do you ship to Mars?",
    )
    assert conv_unknown.startswith("unknown:")

    # --- conversations list, folder-scoped ---
    resp = await client.get(
        f"{API}/merchants/{mid}/messages/conversations?folder=customer",
        headers=await cookie(),
    )
    assert resp.status_code == 200, resp.text
    customer = resp.json()["conversations"]
    found = [c for c in customer if c["conversation_id"] == conv_order]
    assert found and found[0]["order_id"] == order_id
    assert found[0]["unread"] >= 1
    assert "shipped" in found[0]["preview"]
    assert found[0]["counterparty_npub"].startswith("npub1")

    resp = await client.get(
        f"{API}/merchants/{mid}/messages/conversations?folder=unknown",
        headers=await cookie(),
    )
    unknown = resp.json()["conversations"]
    found_u = [
        c for c in unknown if c["conversation_id"] == conv_unknown
    ]
    assert found_u and "Mars" in found_u[0]["preview"]

    # --- thread + read flag + unread-count ---
    resp = await client.get(
        f"{API}/merchants/{mid}/messages/unread-count",
        headers=await cookie(),
    )
    assert resp.status_code == 200
    assert resp.json()["customer"] >= 1
    assert resp.json()["unknown"] >= 1

    resp = await client.get(
        f"{API}/merchants/{mid}/messages/conversations/{conv_order}",
        headers=await cookie(),
    )
    assert resp.status_code == 200, resp.text
    thread = resp.json()
    inbound = [m for m in thread["messages"] if m["direction"] == "in"]
    assert inbound and inbound[0]["read"] is False
    assert any("shipped" in m["content"] for m in inbound)

    resp = await client.post(
        f"{API}/merchants/{mid}/messages/conversations/{conv_order}/read",
        json={},
        headers=await cookie(),
    )
    assert resp.status_code == 200
    resp = await client.get(
        f"{API}/merchants/{mid}/messages/unread-count",
        headers=await cookie(),
    )
    assert resp.json()["customer"] == 0

    # --- reply queues a dual-copy intent + 'out' thread row ---
    resp = await client.post(
        f"{API}/merchants/{mid}/messages/conversations/{conv_order}/reply",
        json={"content": "Ships tomorrow."},
        headers=await cookie(),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["queued"] is True
    assert resp.json()["intent_id"]

    resp = await client.get(
        f"{API}/merchants/{mid}/messages/conversations/{conv_order}",
        headers=await cookie(),
    )
    assert any(
        m["direction"] == "out" and "tomorrow" in m["content"]
        for m in resp.json()["messages"]
    )

    # --- delivery evidence: both copy classes visible ---
    resp = await client.get(
        f"{API}/merchants/{mid}/messages/conversations/{conv_order}/delivery",
        headers=await cookie(),
    )
    assert resp.status_code == 200, resp.text
    msgs = resp.json()["messages"]
    assert msgs and msgs[-1]["intent_id"]
    assert set(msgs[-1]["copies"].keys()) >= {"recipient", "sender"}

    # Regression: order_msg intents carry sealed payload_enc bytes — the
    # B2 outbox listing must not serialize ciphertext into the response
    # (bytes break JSON encoding → the whole publications surface 400s).
    resp = await client.get(
        f"{API}/merchants/{mid}/outbox",
        headers=await cookie(),
    )
    assert resp.status_code == 200, resp.text
    intents = resp.json()["intents"]
    assert all("payload_enc" not in i for i in intents)
    assert intents and all(
        i["created_at"] is not None and i["updated_at"] is not None
        for i in intents
    )

    # --- compose to a fresh npub -> Unknown conversation ---
    other_hex = fixed_test_keys("msg-other").public_key().to_hex()
    resp = await client.post(
        f"{API}/merchants/{mid}/messages/compose",
        json={"recipient": other_hex, "content": "welcome"},
        headers=await cookie(),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["conversation_id"].startswith("unknown:")

    # --- rejected intake listing + mute (inbox_events rows) ---
    rejected_id = uuid.uuid4().hex
    async with DomainTransaction() as tx:
        await tx.execute(
            "INSERT INTO inbox_events"
            " (id, outer_event_id, merchant_id, source_relay_url,"
            "  received_at, kind, processed_state, reject_reason,"
            "  author_hash, processed_at)"
            " VALUES (:i, :e, :m, 'wss://relay.test', :n, 1059,"
            " 'rejected', 'type-3 missing order tag', 'deadbeef', :n)",
            {"i": rejected_id, "e": uuid.uuid4().hex, "m": mid,
             "n": int(time.time())},
        )
    resp = await client.get(
        f"{API}/merchants/{mid}/rejected-intake",
        headers=await cookie(),
    )
    assert resp.status_code == 200, resp.text
    entries = resp.json()["entries"]
    rid = next(
        e["id"] for e in entries
        if e["reject_reason"] == "type-3 missing order tag"
    )
    assert rid == rejected_id
    resp = await client.post(
        f"{API}/merchants/{mid}/rejected-intake/{rid}/mute",
        json={},
        headers=await cookie(),
    )
    assert resp.status_code == 200, resp.text

    # The muted badge is durable — a follow-up listing marks the row so
    # the admin panel can render 'muted' without guessing.
    resp = await client.get(
        f"{API}/merchants/{mid}/rejected-intake",
        headers=await cookie(),
    )
    assert resp.status_code == 200, resp.text
    entry = next(e for e in resp.json()["entries"] if e["id"] == rid)
    assert entry["muted"] is True
    assert entry["reject_reason"] == "type-3 missing order tag"

    # --- order-detail sibling thread ---
    resp = await client.get(
        f"{API}/merchants/{mid}/orders/{order_id}/messages",
        headers=await cookie(),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["conversation_id"] == conv_order

    # --- cross-tenant: a second merchant can never open A's
    # conversations — route-level owner scoping AND the service-level
    # HMAC ownership proof both hold. (One merchant per user — mint a
    # sibling merchant row directly for the service-level probe.)
    other_mid = uuid.uuid4().hex
    resp = await client.get(
        f"{API}/merchants/{other_mid}/messages/conversations",
        headers=await cookie(),
    )
    assert resp.status_code == 404, resp.text

    from nostr_sdk import Keys

    other_pk = Keys.generate().public_key().to_hex()
    async with DomainTransaction() as tx:
        await tx.execute(
            "INSERT INTO merchants"
            " (id, user_id, pubkey, key_ref, wallet_id_enc,"
            "  wallet_id_hash, display_name, state, created_at,"
            "  updated_at)"
            " VALUES (:i, :u, :pk, 'kref', :we, 'wh', 'foreign shop',"
            " 'active', :n, :n)",
            {
                "i": other_mid, "u": "other-user-" + uuid.uuid4().hex[:8],
                "pk": other_pk, "we": b"\x00", "n": int(time.time()),
            },
        )
    async with env["ext_module"].db.connect() as conn:
        assert not await order_messages._conversation_owned(
            conn, other_mid, conv_order, settings
        )
        # Even the unknown folder proves ownership via the merchant-
        # scoped sender HMAC — foreign merchants cannot join.
        assert not await order_messages._conversation_owned(
            conn, other_mid, conv_unknown, settings
        )


async def test_messages_health_and_relay_auth(runtime_env):
    """D-20 health strip + D-26..D-28 relay-auth surface and retry."""
    env = runtime_env
    client = env["client"]
    mid = env["merchant_id"]

    async def cookie() -> dict:
        return {
            "Origin": ORIGIN,
            "X-CSRF-Token": client.cookies.get("gm_csrf"),
        }

    resp = await client.get(
        f"{API}/merchants/{mid}/messages/health",
        headers=await cookie(),
    )
    assert resp.status_code == 200, resp.text
    health = resp.json()
    assert health["inbox_state"] == "active"
    assert "outbox_pending" in health
    assert isinstance(health["relays"], list)

    resp = await client.get(
        f"{API}/merchants/{mid}/relay-auth",
        headers=await cookie(),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "relays" in body

    resp = await client.post(
        f"{API}/merchants/{mid}/relay-auth/retry/wss://relay.invalid",
        json={},
        headers=await cookie(),
    )
    assert resp.status_code == 404, resp.text
