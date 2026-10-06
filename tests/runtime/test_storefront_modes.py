"""Storefront modes — the D-07..D-11 gate matrix (plan 03-03 Task 3).

Four modes (``full | showcase | browse_only | nostr_only``, settings key
``storefront_mode``, default ``full``) gate NEW purchases and public
browse depth only. The D-08 hard invariant: private order links,
in-flight invoices, order-status, digital delivery, sign-in and claim
work in EVERY mode; in-flight orders are never touched (D-11);
``showcase``/``nostr_only`` require ``inbox_state == 'active'`` (D-10);
``browse_only`` pauses catalog render/publish intents (D-09) while
``order_msg``/``merchant_profile`` publish in every mode.
"""

from __future__ import annotations

import asyncio
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
            "display_name": "mode shop",
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
        json={"name": "modes", "default_currency": "SAT"},
        headers=await cookie(),
    )
    cid = resp.json()["id"]
    resp = await client.post(
        f"{API}/products",
        json={
            "catalog_id": cid,
            "title": "mode widget",
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
    resp = await client.post(
        f"{API}/collections",
        json={"title": "mode collection"},
        headers=await cookie(),
    )
    assert resp.status_code == 201, resp.text
    collection = resp.json()
    resp = await client.patch(
        f"{API}/products/{product['id']}",
        json={"collection_ids": [collection["id"]]},
        headers=await cookie(),
    )
    assert resp.status_code == 200, resp.text
    runtime_env.update(
        {
            "merchant_id": mid,
            "product": product,
            "collection": collection,
            "cookie": cookie,
        }
    )
    yield
    # Leave the shop in the default mode for any later module.
    async with DomainTransaction() as tx:
        await tx.execute(
            "DELETE FROM settings WHERE merchant_id = :m"
            " AND key = 'storefront_mode'",
            {"m": mid},
        )


async def _merchant(env: dict) -> dict:
    async with env["ext_module"].db.connect() as conn:
        row = await conn.fetchone(
            "SELECT * FROM infinitemarkets.merchants WHERE id = :m",
            {"m": env["merchant_id"]},
        )
    return dict(row)


async def _set_mode(env: dict, mode: str, *, confirm: bool = True):
    resp = await env["client"].put(
        f"{API}/merchants/{env['merchant_id']}/storefront-mode",
        json={"mode": mode, "confirm": confirm},
        headers=await env["cookie"](),
    )
    return resp


async def _checkout(env: dict):
    merchant = await _merchant(env)
    return await env["client"].post(
        f"{PUB}/checkout",
        json={
            "merchant_pubkey": merchant["pubkey"],
            "items": [{"d_tag": env["product"]["d_tag"], "quantity": 1}],
            "email_opt_in": False,
        },
        headers={"Idempotency-Key": uuid.uuid4().hex},
    )


async def _quote(env: dict):
    merchant = await _merchant(env)
    return await env["client"].post(
        f"{PUB}/quote",
        json={
            "merchant_pubkey": merchant["pubkey"],
            "items": [{"d_tag": env["product"]["d_tag"], "quantity": 1}],
        },
    )


async def _web_order(env: dict) -> tuple[dict, str]:
    resp = await _checkout(env)
    assert resp.status_code == 201, resp.text
    token = resp.json()["public_token"]
    digest = env["ext_module"].crypto.token_lookup_hash(token)
    async with env["ext_module"].db.connect() as conn:
        row = await conn.fetchone(
            "SELECT * FROM infinitemarkets.orders"
            " WHERE public_token_hash = :h",
            {"h": digest},
        )
    return dict(row), token


# --- admin surface --------------------------------------------------------------


async def test_collection_links_stay_out_of_shared_header(runtime_env):
    env = runtime_env
    merchant = await _merchant(env)
    pubkey = merchant["pubkey"]
    collection_url = (
        f"/infinitemarkets/public/collections/{pubkey}/"
        f"{env['collection']['d_tag']}"
    )
    for path in (
        f"/infinitemarkets/public/merchants/{pubkey}",
        collection_url,
    ):
        response = await env["client"].get(path)
        assert response.status_code == 200, response.text
        header = response.text.split('<nav class="store-nav"', 1)[1].split(
            "</nav>", 1
        )[0]
        assert collection_url not in header
        assert "Shop" in header and "Track order" in header
        if path != collection_url:
            assert collection_url in response.text


async def test_mode_api_shape_and_d10_gate(runtime_env):
    """GET exposes mode + blocked map; PUT enforces the two-step
    confirm and the D-10 inbox gate for showcase/nostr_only."""
    env = runtime_env
    mid = env["merchant_id"]

    resp = await env["client"].get(
        f"{API}/merchants/{mid}/storefront-mode",
        headers=await env["cookie"](),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mode"] == "full"
    assert body["modes"] == ["full", "showcase", "browse_only",
                             "nostr_only"]
    assert body["blocked"]["showcase"] is False
    assert body["blocked"]["nostr_only"] is False
    assert set(body["impact"].keys()) >= set(body["modes"])

    # Unknown mode -> 422; unconfirmed change returns the impact preview.
    resp = await env["client"].put(
        f"{API}/merchants/{mid}/storefront-mode",
        json={"mode": "bogus", "confirm": True},
        headers=await env["cookie"](),
    )
    assert resp.status_code == 422, resp.text
    assert "storefront-mode" in resp.json()["type"]

    resp = await _set_mode(env, "browse_only", confirm=False)
    assert resp.status_code == 200, resp.text
    assert resp.json()["applied"] is False
    assert resp.json()["requires_confirmation"] is True
    assert resp.json()["impact"]

    # Still full — the preview never writes.
    from infinitemarkets.services import storefront_mode

    assert await storefront_mode.get_mode(mid) == "full"

    # D-10: showcase/nostr_only blocked while inbox_state != 'active'.
    from infinitemarkets.db import DomainTransaction

    async with DomainTransaction() as tx:
        await tx.execute(
            "UPDATE merchants SET inbox_state = 'pending' WHERE id = :m",
            {"m": mid},
        )
    try:
        for mode in ("showcase", "nostr_only"):
            resp = await _set_mode(env, mode, confirm=True)
            assert resp.status_code == 409, (mode, resp.text)
            assert resp.json()["type"].endswith("inbox-required")
            assert (
                await storefront_mode.get_mode(mid)
            ) == "full"
        # browse_only does NOT require the inbox.
        resp = await _set_mode(env, "browse_only", confirm=True)
        assert resp.status_code == 200, resp.text
        await _set_mode(env, "full", confirm=True)
    finally:
        async with DomainTransaction() as tx:
            await tx.execute(
                "UPDATE merchants SET inbox_state = 'active' WHERE id = :m",
                {"m": mid},
            )


async def test_mode_matrix(runtime_env):
    """4 modes x 9 surfaces — the D-07/D-08 contract per cell."""
    import httpx

    env = runtime_env
    merchant = await _merchant(env)
    pk = merchant["pubkey"]
    product_url = f"/infinitemarkets/p/{pk}/{env['product']['d_tag']}"
    collection_url = (
        f"/infinitemarkets/public/collections/{pk}/"
        f"{env['collection']['d_tag']}"
    )
    merchant_url = f"/infinitemarkets/public/merchants/{pk}"
    order_url = f"/infinitemarkets/order?shop={pk}"

    # Seed an in-flight order + a buyer session BEFORE mode flips.
    order, token = await _web_order(env)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=env["app"]), base_url=ORIGIN
    ) as buyer:
        resp = await buyer.get(f"{PUB}/nostr/challenge")
        challenge = resp.json()["challenge"]
        from nostr_sdk import (
            EventBuilder,
            Kind,
            NostrSigner,
            Tag,
            Timestamp,
        )

        from harness.sdk import fixed_test_keys

        keys = fixed_test_keys("mode-buyer")
        event = await (
            EventBuilder(Kind(22242), challenge)
            .tags([Tag.parse(["challenge", challenge])])
            .custom_created_at(Timestamp.from_secs(int(time.time())))
            .sign(NostrSigner.keys(keys))
        )
        resp = await buyer.post(
            f"{PUB}/nostr/verify",
            json={"event": event.as_json()},
            headers={"Origin": ORIGIN},
        )
        assert resp.status_code == 200, resp.text

        for mode in ("full", "showcase", "browse_only", "nostr_only"):
            resp = await _set_mode(env, mode)
            assert resp.status_code == 200, (mode, resp.text)
            assert resp.json()["applied"] is True

            # --- NEW purchases blocked outside 'full' ---
            resp = await _checkout(env)
            if mode == "full":
                assert resp.status_code == 201, (mode, resp.text)
            else:
                assert resp.status_code == 422, (mode, resp.text)
                assert (
                    "storefront-mode-unavailable" in resp.json()["type"]
                )
            resp = await _quote(env)
            if mode == "full":
                assert resp.status_code == 200, (mode, resp.text)
            else:
                assert resp.status_code == 422, (mode, resp.text)

            # --- browse depth ---
            resp = await env["client"].get(product_url)
            assert resp.status_code == 200, (mode, resp.status_code)
            if mode == "nostr_only":
                assert 'data-gm="nostr-only"' in resp.text
                assert 'id="gm-checkout"' not in resp.text
                assert "npub1" in resp.text
            elif mode == "showcase":
                assert 'data-gm="showcase-guidance"' in resp.text
                assert 'id="gm-checkout"' not in resp.text
                assert "npub1" in resp.text
            elif mode == "browse_only":
                assert 'data-gm="browse-only"' in resp.text
                assert 'id="gm-checkout"' not in resp.text
            else:
                assert 'id="gm-checkout"' in resp.text

            for url in (collection_url, merchant_url):
                resp = await env["client"].get(url)
                assert resp.status_code == 200, (mode, url)
                if mode == "nostr_only":
                    assert 'data-gm="nostr-only"' in resp.text
                else:
                    assert 'data-gm="nostr-only"' not in resp.text

            # --- D-08: existing links/invoices/identity never gated ---
            resp = await env["client"].get(order_url)
            assert resp.status_code == 200, (mode, "order page")
            resp = await env["client"].get(
                f"{PUB}/order-status",
                headers={"X-Order-Token": token},
            )
            assert resp.status_code == 200, (mode, "order-status")
            assert resp.json()["state"] == "awaiting_payment"
            assert resp.json()["bolt11"]  # in-flight invoice survives
            resp = await buyer.get(f"{PUB}/nostr/orders")
            assert resp.status_code == 200, (mode, "nostr orders")
            resp = await buyer.get(f"{PUB}/nostr/challenge")
            assert resp.status_code == 200, (mode, "challenge")
            resp = await buyer.post(
                f"{PUB}/nostr/claim",
                json={"token": token},
                headers={"Origin": ORIGIN},
            )
            assert resp.status_code == 200, (mode, "claim")
            # Order state untouched by the mode flip (D-11).
            async with env["ext_module"].db.connect() as conn:
                row = await conn.fetchone(
                    "SELECT state FROM infinitemarkets.orders"
                    " WHERE id = :o",
                    {"o": order["id"]},
                )
            assert row["state"] == "awaiting_payment"

    # Back to full.
    resp = await _set_mode(env, "full")
    assert resp.status_code == 200


async def test_browse_only_pauses_catalog_render(runtime_env):
    """D-09 — render_intent returns None for catalog aggregates under
    browse_only; order_msg/merchant_profile render in every mode."""
    env = runtime_env
    mid = env["merchant_id"]
    from infinitemarkets.services import outbox, storefront_mode

    async with env["ext_module"].db.connect() as conn:
        row = await conn.fetchone(
            "SELECT * FROM infinitemarkets.outbox_events"
            " WHERE merchant_id = :m AND aggregate_type = 'products'"
            " ORDER BY created_at DESC LIMIT 1",
            {"m": mid},
        )
    assert row is not None
    row = dict(row)

    # Full/showcase/nostr_only render the catalog aggregate.
    for mode in ("full", "showcase", "nostr_only"):
        resp = await _set_mode(env, mode)
        assert resp.status_code == 200
        assert await storefront_mode.get_mode(mid) == mode
        rendered = await outbox.render_intent(row)
        assert rendered is not None, mode

    resp = await _set_mode(env, "browse_only")
    assert resp.status_code == 200
    rendered = await outbox.render_intent(row)
    assert rendered is None
    resp = await _set_mode(env, "full")
    assert resp.status_code == 200
    rendered = await outbox.render_intent(row)
    assert rendered is not None


async def test_mode_persists(runtime_env):
    """The settings row round-trips — restart-equivalent reads see it."""
    env = runtime_env
    resp = await _set_mode(env, "showcase")
    assert resp.status_code == 200
    from infinitemarkets.services import storefront_mode

    assert await storefront_mode.get_mode(env["merchant_id"]) == "showcase"
    async with env["ext_module"].db.connect() as conn:
        row = await conn.fetchone(
            "SELECT value FROM infinitemarkets.settings"
            " WHERE merchant_id = :m AND key = 'storefront_mode'",
            {"m": env["merchant_id"]},
        )
    assert row["value"] == "showcase"
    await _set_mode(env, "full")
