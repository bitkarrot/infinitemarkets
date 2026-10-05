"""Section 5.2 catalog API + section 6/15 validation, through the real
host loader. Covers bounds, drafts, variation rules, soft-delete ordering
with tombstone intents, same-tx outbox enqueue, deterministic event
rendering, markdown round-trip, and owner scoping."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.runtime

ORIGIN = "https://shop.example"
API = "/infinitemarkets/api/v1"


async def _cookie(runtime_env) -> dict:
    client = runtime_env["client"]
    if not client.cookies.get("gm_csrf"):
        await client.get(f"{API}/merchants/current")
    return {
        "Origin": ORIGIN,
        "X-CSRF-Token": client.cookies.get("gm_csrf"),
    }


async def _merchant(runtime_env) -> str:
    """Create the merchant once per module boot."""
    client = runtime_env["client"]
    if "merchant_id" in runtime_env:
        return runtime_env["merchant_id"]
    resp = await client.post(
        f"{API}/merchants",
        json={"wallet_id": runtime_env["wallet"].id,
              "display_name": "catalog shop"},
        headers=await _cookie(runtime_env),
    )
    assert resp.status_code == 201, resp.text
    runtime_env["merchant_id"] = resp.json()["id"]
    return runtime_env["merchant_id"]


async def _catalog(runtime_env) -> str:
    await _merchant(runtime_env)
    if "catalog_id" in runtime_env:
        return runtime_env["catalog_id"]
    resp = await runtime_env["client"].post(
        f"{API}/catalogs",
        json={"name": "main", "default_currency": "USD"},
        headers=await _cookie(runtime_env),
    )
    assert resp.status_code == 201, resp.text
    runtime_env["catalog_id"] = resp.json()["id"]
    return runtime_env["catalog_id"]


async def _outbox(runtime_env, agg_type=None):
    from infinitemarkets.db import db

    async with db.connect() as conn:
        sql = (
            "SELECT * FROM infinitemarkets.outbox_events WHERE merchant_id = :m"
        )
        params = {"m": runtime_env["merchant_id"]}
        if agg_type:
            sql += " AND aggregate_type = :t"
            params["t"] = agg_type
        rows = await conn.fetchall(sql + " ORDER BY created_at, id", params)
    return [dict(r) for r in rows]


async def _deps(runtime_env, intent_id):
    from infinitemarkets.db import db

    async with db.connect() as conn:
        rows = await conn.fetchall(
            "SELECT depends_on_outbox_event_id AS d "
            "FROM infinitemarkets.outbox_dependencies "
            "WHERE outbox_event_id = :e",
            {"e": intent_id},
        )
    return [r["d"] for r in rows]


# --- happy path + bounds --------------------------------------------------------


async def test_catalog_crud(runtime_env):
    cid = await _catalog(runtime_env)
    client = runtime_env["client"]
    resp = await client.get(
        f"{API}/catalogs", headers={"Origin": ORIGIN}
    )
    assert resp.status_code == 200
    assert any(c["id"] == cid for c in resp.json())

    resp = await client.patch(
        f"{API}/catalogs/{cid}",
        json={"name": "renamed", "default_currency": "USD"},
        headers=await _cookie(runtime_env),
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "renamed"


async def test_catalog_delete_guards(runtime_env):
    main = await _catalog(runtime_env)
    client = runtime_env["client"]
    headers = await _cookie(runtime_env)

    resp = await client.post(
        f"{API}/catalogs", json={"name": "second"}, headers=headers
    )
    assert resp.status_code == 201
    second = resp.json()["id"]

    prod = await client.post(
        f"{API}/products",
        json={"catalog_id": second, "title": "pinned", "format": "digital",
              "amount_minor": 5, "currency": "SAT", "draft": True},
        headers=headers,
    )
    assert prod.status_code == 201, prod.text

    # live product -> refused, nothing orphaned
    resp = await client.delete(f"{API}/catalogs/{second}", headers=headers)
    assert resp.status_code == 409
    assert resp.json()["type"].endswith("catalog-not-empty")

    # once emptied the delete lands and the row leaves the list
    resp = await client.delete(
        f"{API}/products/{prod.json()['id']}", headers=headers
    )
    assert resp.status_code == 200
    resp = await client.delete(f"{API}/catalogs/{second}", headers=headers)
    assert resp.status_code == 200
    listed = await client.get(f"{API}/catalogs", headers={"Origin": ORIGIN})
    assert second not in [c["id"] for c in listed.json()]

    # a deleted catalog cannot take new products
    resp = await client.post(
        f"{API}/products",
        json={"catalog_id": second, "title": "x", "format": "digital",
              "amount_minor": 1, "currency": "SAT", "draft": True},
        headers=headers,
    )
    assert resp.status_code == 404

    # the shop's last remaining catalog cannot be deleted
    others = [c["id"] for c in listed.json() if c["id"] != main]
    for cid in others:
        r = await client.delete(f"{API}/catalogs/{cid}", headers=headers)
        assert r.status_code in (200, 409)
    resp = await client.delete(f"{API}/catalogs/{main}", headers=headers)
    assert resp.status_code in (409,)
    assert resp.json()["type"].endswith(("last-catalog", "catalog-not-empty"))


async def test_product_validation_bounds(runtime_env):
    cid = await _catalog(runtime_env)
    client = runtime_env["client"]
    headers = await _cookie(runtime_env)

    cases = [
        {"catalog_id": cid, "title": "x" * 201},
        {"catalog_id": cid, "summary": "x" * 501},
        {"catalog_id": cid, "description_md": "x" * (64 * 1024 + 1)},
        {"catalog_id": cid, "images": [
            f"https://x.example/{i}.png" for i in range(17)
        ]},
        {"catalog_id": cid, "images": ["http://insecure.example/x.png"]},
        {"catalog_id": cid, "currency": "usd"},        # lowercase
        {"catalog_id": cid, "currency": "TOOLONGCURR"},
        {"catalog_id": cid, "currency_decimals": 19},
        {"catalog_id": cid, "product_type": "bogus"},
        {"catalog_id": cid, "stock_on_hand": -1},
        {"catalog_id": cid, "stock_on_hand": 1.5},
        {"catalog_id": cid, "stock_on_hand": True},
        {"catalog_id": cid, "stock_on_hand": 2**63},
        {"catalog_id": cid, "stock_reserved": 1},
        {"catalog_id": cid, "amount_minor": -1},
        {"catalog_id": cid, "amount_minor": 1.5},
        {"catalog_id": cid, "amount_minor": True},
        {"catalog_id": cid, "amount_minor": 2**63},
        {"catalog_id": cid, "unknown_field": 1},
    ]
    for payload in cases:
        resp = await client.post(
            f"{API}/products", json=payload, headers=headers
        )
        assert resp.status_code == 422, payload
        assert resp.json()["type"].startswith("urn:infinitemarkets:")


async def test_product_crud_and_outbox_intent(runtime_env):
    cid = await _catalog(runtime_env)
    client = runtime_env["client"]
    resp = await client.post(
        f"{API}/products",
        json={
            "catalog_id": cid,
            "title": "beans",
            "summary": "good beans",
            "description_md": "# beans\n\nRoasted. <script>x</script>",
            "amount_minor": 1500,
            "currency": "USD",
            "currency_decimals": 2,
            "visibility": "on-sale",
            "stock_on_hand": 10,
            "specs": [{"key": "size", "value": "1kg"}],
            "categories": ["coffee"],
        },
        headers=await _cookie(runtime_env),
    )
    assert resp.status_code == 201, resp.text
    product = resp.json()
    runtime_env["product_id"] = product["id"]
    # markdown round-trip: sanitizer strips the raw HTML tag, keeps markdown
    assert "# beans" in product["description_md"]
    assert "<script>" not in product["description_md"]

    # same-tx outbox intent exists
    intents = await _outbox(runtime_env, "products")
    assert any(
        i["aggregate_id"] == product["id"] and i["event_kind"] == 30402
        for i in intents
    )
    assert product["published_at"] is not None  # assigned on first publish


async def test_published_at_preserved_across_edits(runtime_env):
    pid = runtime_env["product_id"]
    client = runtime_env["client"]
    before = (await client.get(f"{API}/products/{pid}")).json()
    first_ts = before["published_at"]
    assert first_ts is not None
    resp = await client.patch(
        f"{API}/products/{pid}",
        json={"title": "beans v2"},
        headers=await _cookie(runtime_env),
    )
    assert resp.status_code == 200
    # retries/edits must NOT shift the original publication timestamp
    assert resp.json()["published_at"] == first_ts
    assert resp.json()["revision"] == before["revision"] + 1


async def test_draft_produces_no_intent(runtime_env):
    cid = await _catalog(runtime_env)
    client = runtime_env["client"]
    resp = await client.post(
        f"{API}/products",
        json={"catalog_id": cid, "title": "wip", "draft": True},
        headers=await _cookie(runtime_env),
    )
    assert resp.status_code == 201
    pid = resp.json()["id"]
    intents = await _outbox(runtime_env, "products")
    assert not any(i["aggregate_id"] == pid for i in intents)


async def test_variation_rules(runtime_env):
    cid = await _catalog(runtime_env)
    client = runtime_env["client"]
    headers = await _cookie(runtime_env)

    # variable parent
    resp = await client.post(
        f"{API}/products",
        json={"catalog_id": cid, "title": "shirt",
              "product_type": "variable"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    parent = resp.json()["id"]

    # simple product cannot parent a variation
    resp = await client.post(
        f"{API}/products",
        json={"catalog_id": cid, "title": "plain",
              "product_type": "simple"},
        headers=headers,
    )
    simple = resp.json()["id"]

    resp = await client.post(
        f"{API}/products",
        json={"catalog_id": cid, "title": "shirt-M",
              "product_type": "variation",
              "parent_product_id": simple},
        headers=headers,
    )
    assert resp.status_code == 422  # parent not variable

    resp = await client.post(
        f"{API}/products",
        json={"catalog_id": cid, "title": "shirt-M",
              "product_type": "variation",
              "parent_product_id": parent},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    var_id = resp.json()["id"]

    # depth=1: a variation cannot parent another variation
    resp = await client.post(
        f"{API}/products",
        json={"catalog_id": cid, "title": "shirt-M-tall",
              "product_type": "variation",
              "parent_product_id": var_id},
        headers=headers,
    )
    assert resp.status_code == 422


async def test_collection_zero_members_no_intent(runtime_env):
    await _catalog(runtime_env)
    client = runtime_env["client"]
    resp = await client.post(
        f"{API}/collections",
        json={"title": "empty col"},
        headers=await _cookie(runtime_env),
    )
    assert resp.status_code == 201, resp.text
    col_id = resp.json()["id"]
    runtime_env["empty_col"] = col_id
    intents = await _outbox(runtime_env, "collections")
    assert not any(i["aggregate_id"] == col_id for i in intents)


async def test_membership_enqueues_collection_and_product_dep(runtime_env):
    await _catalog(runtime_env)
    client = runtime_env["client"]
    headers = await _cookie(runtime_env)
    col_id = runtime_env["empty_col"]
    pid = runtime_env["product_id"]

    # attach product to collection
    resp = await client.patch(
        f"{API}/products/{pid}",
        json={"collection_ids": [col_id]},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    intents = await _outbox(runtime_env)
    col_intents = [
        i for i in intents
        if i["aggregate_type"] == "collections"
        and i["aggregate_id"] == col_id and i["state"] == "pending"
    ]
    prod_intents = [
        i for i in intents
        if i["aggregate_type"] == "products"
        and i["aggregate_id"] == pid and i["state"] == "pending"
    ]
    assert col_intents and prod_intents
    # 30402 waits on its 30405 (dependency ordering)
    deps = await _deps(runtime_env, prod_intents[-1]["id"])
    assert col_intents[-1]["id"] in deps


async def test_shipping_validation(runtime_env):
    await _catalog(runtime_env)
    client = runtime_env["client"]
    headers = await _cookie(runtime_env)

    # price-distance rejected outright
    resp = await client.post(
        f"{API}/shipping",
        json={"title": "x", "service": "standard",
              "price_distance_minor": 100},
        headers=headers,
    )
    assert resp.status_code == 422

    # pickup requires location/geohash
    resp = await client.post(
        f"{API}/shipping",
        json={"title": "pickup", "service": "pickup"},
        headers=headers,
    )
    assert resp.status_code == 422

    # bad country code
    resp = await client.post(
        f"{API}/shipping",
        json={"title": "x", "countries": ["XX1"]},
        headers=headers,
    )
    assert resp.status_code == 422

    # duration min>max
    resp = await client.post(
        f"{API}/shipping",
        json={"title": "x", "duration_min": 5, "duration_max": 2,
              "duration_unit": "D"},
        headers=headers,
    )
    assert resp.status_code == 422

    resp = await client.post(
        f"{API}/shipping",
        json={
            "title": "standard post", "service": "standard",
            "base_price_minor": 500, "currency": "USD",
            "countries": ["US", "DE"],
            "duration_min": 2, "duration_max": 5, "duration_unit": "D",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    runtime_env["shipping_id"] = resp.json()["id"]

    intents = await _outbox(runtime_env, "shipping_options")
    assert any(
        i["aggregate_id"] == runtime_env["shipping_id"]
        and i["event_kind"] == 30406
        for i in intents
    )


async def test_dry_run_deterministic(runtime_env):
    pid = runtime_env["product_id"]
    client = runtime_env["client"]
    r1 = await client.get(f"{API}/products/{pid}/events")
    r2 = await client.get(f"{API}/products/{pid}/events")
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json() == r2.json()  # byte-identical rendering
    events = r1.json()
    assert events and events[0]["kind"] == 30402
    tags = events[0]["tags"]
    tag_keys = [t[0] for t in tags]
    assert "d" in tag_keys and "price" in tag_keys
    assert ["L", "org.infinitemarkets.protocol"] in tags
    price_tag = next(t for t in tags if t[0] == "price")
    assert price_tag[1] == "1500" or price_tag[1] == "15.00"
    # currency/decimals: amount_minor=1500, decimals=2 -> "15.00" style
    assert price_tag[2] == "USD"


async def test_bulk_product_updates_are_atomic_and_publication_safe(runtime_env):
    cid = await _catalog(runtime_env)
    client = runtime_env["client"]
    headers = await _cookie(runtime_env)
    source = await client.post(
        f"{API}/collections", json={"title": "bulk source"}, headers=headers
    )
    target = await client.post(
        f"{API}/collections", json={"title": "bulk target"}, headers=headers
    )
    assert source.status_code == 201 and target.status_code == 201
    products = []
    for title, amount in (("bulk one", 105), ("bulk two", 200)):
        response = await client.post(
            f"{API}/products",
            json={
                "catalog_id": cid,
                "title": title,
                "amount_minor": amount,
                "currency": "SAT",
                "collection_ids": [source.json()["id"]],
            },
            headers=headers,
        )
        assert response.status_code == 201, response.text
        products.append(response.json())
    product_ids = [product["id"] for product in products]

    response = await client.post(
        f"{API}/products/bulk",
        json={
            "product_ids": [product_ids[0], "0" * 32],
            "action": "price-markup",
            "value": 10,
        },
        headers=headers,
    )
    assert response.status_code == 404
    unchanged = await client.get(f"{API}/products/{product_ids[0]}")
    assert unchanged.json()["amount_minor"] == 105

    response = await client.post(
        f"{API}/products/bulk",
        json={
            "product_ids": product_ids,
            "action": "price-markup",
            "value": 10,
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["updated"] == 2
    updated = [
        (await client.get(f"{API}/products/{product_id}")).json()
        for product_id in product_ids
    ]
    assert [product["amount_minor"] for product in updated] == [116, 220]

    response = await client.post(
        f"{API}/products/bulk",
        json={
            "product_ids": product_ids,
            "action": "move-collection",
            "value": target.json()["id"],
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    moved = [
        (await client.get(f"{API}/products/{product_id}")).json()
        for product_id in product_ids
    ]
    assert all(product["collection_ids"] == [target.json()["id"]] for product in moved)

    response = await client.post(
        f"{API}/products/bulk",
        json={
            "product_ids": product_ids,
            "action": "visibility",
            "value": "hidden",
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    hidden = [
        (await client.get(f"{API}/products/{product_id}")).json()
        for product_id in product_ids
    ]
    assert all(product["visibility"] == "hidden" for product in hidden)

    response = await client.post(
        f"{API}/products/bulk",
        json={"product_ids": product_ids, "action": "draft"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    drafts = [
        (await client.get(f"{API}/products/{product_id}")).json()
        for product_id in product_ids
    ]
    assert all(product["draft"] and product["collection_ids"] == [] for product in drafts)
    intents = await _outbox(runtime_env, "products")
    assert all(
        any(
            intent["aggregate_id"] == product_id and intent["event_kind"] == 5
            for intent in intents
        )
        for product_id in product_ids
    )

    response = await client.post(
        f"{API}/products/bulk",
        json={"product_ids": product_ids, "action": "publish"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    published = [
        (await client.get(f"{API}/products/{product_id}")).json()
        for product_id in product_ids
    ]
    assert all(not product["draft"] for product in published)

    response = await client.post(
        f"{API}/products/bulk",
        json={"product_ids": product_ids, "action": "delete"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"deleted": 2, "product_ids": product_ids}
    for product_id in product_ids:
        assert (await client.get(f"{API}/products/{product_id}")).status_code == 404


async def test_delete_reference_report_and_strip(runtime_env):
    client = runtime_env["client"]
    headers = await _cookie(runtime_env)
    pid = runtime_env["product_id"]
    col_id = runtime_env["empty_col"]

    # collection is referenced by the product -> 409 with reference report
    resp = await client.delete(
        f"{API}/collections/{col_id}", headers=headers
    )
    assert resp.status_code == 409

    # explicit strip-and-republish
    resp = await client.delete(
        f"{API}/collections/{col_id}?strip=true", headers=headers
    )
    assert resp.status_code == 200, resp.text

    intents = await _outbox(runtime_env)
    tomb = [
        i for i in intents
        if i["aggregate_type"] == "collections"
        and i["aggregate_id"] == col_id and i["event_kind"] == 5
    ]
    assert tomb, "kind-5 tombstone intent must be enqueued"
    # tombstone depends on the surviving product republish
    deps = await _deps(runtime_env, tomb[-1]["id"])
    prod_republishes = {
        i["id"] for i in intents
        if i["aggregate_type"] == "products"
        and i["aggregate_id"] == pid and i["event_kind"] == 30402
    }
    assert prod_republishes & set(deps)


async def test_product_delete_enqueues_tombstone(runtime_env):
    client = runtime_env["client"]
    pid = runtime_env["product_id"]
    resp = await client.delete(
        f"{API}/products/{pid}", headers=await _cookie(runtime_env)
    )
    assert resp.status_code == 200
    intents = await _outbox(runtime_env, "products")
    assert any(
        i["aggregate_id"] == pid and i["event_kind"] == 5 for i in intents
    )
    resp = await client.get(f"{API}/products/{pid}")
    assert resp.status_code == 404


async def test_owner_scoping(runtime_env):
    """A second user cannot see or mutate the first user's catalog."""
    import uuid as _uuid

    import httpx
    from lnbits.core.crud import create_wallet
    from lnbits.core.crud.users import create_account
    from lnbits.core.models.users import Account

    username = f"gqother{_uuid.uuid4().hex[:8]}"
    password = "other-pass-123"
    account = Account(id=_uuid.uuid4().hex, username=username, email=None)
    account.hash_password(password)
    await create_account(account)
    await create_wallet(user_id=account.id, wallet_name="other")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=runtime_env["app"]),
        base_url=ORIGIN,
    ) as c2:
        resp = await c2.post(
            "/api/v1/auth", json={"username": username,
                                  "password": password}
        )
        token = resp.json()["access_token"]
        await c2.put(
            "/api/v1/extension/infinitemarkets/enable",
            headers={
                "Cookie": f"cookie_access_token={token}",
                "Origin": ORIGIN,
            },
        )
        # user B has no merchant -> catalog list 404s
        resp = await c2.get(f"{API}/catalogs")
        assert resp.status_code == 404
        # and cannot read user A's product (merchant-scoped fetch)
        resp = await c2.get(
            f"{API}/products/{runtime_env['product_id']}"
        )
        assert resp.status_code == 404
        resp = await c2.post(
            f"{API}/products/bulk",
            json={
                "product_ids": [runtime_env["product_id"]],
                "action": "visibility",
                "value": "hidden",
            },
            headers={
                "Origin": ORIGIN,
                "X-CSRF-Token": c2.cookies.get("gm_csrf"),
            },
        )
        assert resp.status_code == 404
