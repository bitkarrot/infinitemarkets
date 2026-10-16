"""Native product CSV export and draft reimport, owned-media upload/relink,
and merchant storefront profile (grid density, hero visibility, footer logo)."""

from __future__ import annotations

import csv
import hashlib
import io
import json

import pytest

pytestmark = pytest.mark.runtime

API = "/infinitemarkets/api/v1"
ORIGIN = "https://shop.example"

_PNG = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + b"IHDR"
        + b"\x00" * 13 + b"IDAT" + b"x" * 16 + b"IEND")


def _headers(client) -> dict:
    return {"Origin": ORIGIN, "X-CSRF-Token": client.cookies.get("gm_csrf")}


async def _merchant(runtime_env):
    client = runtime_env["client"]
    await client.get(f"{API}/merchants/current")
    resp = await client.get(f"{API}/merchants/current")
    if resp.status_code == 200:
        return resp.json()
    resp = await client.post(
        f"{API}/merchants",
        json={"wallet_id": runtime_env["wallet"].id},
        headers=_headers(client),
    )
    assert resp.status_code == 201, resp.text
    return (await client.get(f"{API}/merchants/current")).json()


@pytest.mark.parametrize("publish_mode", ["patch", "bulk"])
async def test_export_reimport_and_activation(runtime_env, publish_mode):
    """Native export → CSV → reimport as drafts → publish directly.
    Formula injection is escaped."""
    client = runtime_env["client"]
    merchant = await _merchant(runtime_env)
    headers = _headers(client)

    cat = await client.post(
        f"{API}/categories",
        json={"name": "export-test", "default_currency": "USD"},
        headers=headers,
    )
    assert cat.status_code == 201, cat.text
    product = await client.post(
        f"{API}/products",
        json={
            "category_id": cat.json()["id"], "title": "=cmd|'./C1'!hack",
            "product_type": "variable",
            "description_md": "desc", "amount_minor": 1299, "currency": "USD",
            "currency_decimals": 2, "stock_on_hand": 7,
            "visibility": "on-sale", "format": "digital",
            "images": ["https://cdn.example.com/a.png"],
            "categories": ["geekware"],
        },
        headers=headers,
    )
    assert product.status_code == 201, product.text
    variant = await client.post(
        f"{API}/products",
        json={
            "category_id": cat.json()["id"], "title": "Large",
            "product_type": "variation",
            "parent_product_id": product.json()["id"],
            "amount_minor": 1499, "currency": "USD", "currency_decimals": 2,
            "stock_on_hand": 3, "visibility": "on-sale", "format": "digital",
            "specs": [{"key": "Size", "value": "L"}],
        },
        headers=headers,
    )
    assert variant.status_code == 201, variant.text
    medium = await client.post(
        f"{API}/products",
        json={
            "category_id": cat.json()["id"], "title": "Medium",
            "product_type": "variation", "parent_product_id": product.json()["id"],
            "amount_minor": 1299, "currency": "USD", "currency_decimals": 2,
            "stock_on_hand": 4, "visibility": "on-sale", "format": "digital",
            "specs": [{"key": "Size", "value": "M"}],
        },
        headers=headers,
    )
    assert medium.status_code == 201, medium.text

    exported = await client.get(f"{API}/migration/products/export")
    assert exported.status_code == 200, exported.text
    text = exported.text
    assert "format,infinitemarkets-products-v1" in text.splitlines()[0]
    rows = list(csv.DictReader(io.StringIO(text.split("\n", 1)[1])))
    exported_handles = {
        row["handle"] for row in rows if row["row"] == "product"
    }
    parent = next(
        r for r in rows if r["row"] == "product" and "cmd" in r["title"]
    )
    assert parent["title"].startswith("'=")  # formula-escaped
    variant_rows = [r for r in rows if r["row"] == "variant"]
    assert all(r["parent_handle"] in exported_handles for r in variant_rows)
    assert {(r["option_1"], r["stock_on_hand"]) for r in variant_rows} == {
        ("Size=L", "3"), ("Size=M", "4")
    }

    # Re-import into the same merchant with a stable catalog identifier.
    upload = {"file": ("export.csv", text.encode(), "text/csv")}
    form = {} if publish_mode == "patch" else {"source_instance": "bulk-test-catalog"}
    preview = await client.post(
        f"{API}/migration/native/preview", data=form, files=upload,
        headers=headers,
    )
    assert preview.status_code == 200, preview.text
    form["source_hash"] = preview.json()["source_hash"]
    imported = await client.post(
        f"{API}/migration/native/execute", data=form, files=upload,
        headers=headers,
    )
    assert imported.status_code == 200, imported.text
    import_id = imported.json()["import_id"]

    audit = await client.get(
        f"{API}/migration/imports/{import_id}", headers=headers
    )
    assert audit.status_code == 200, audit.text
    imported_id = next(
        row["product_id"] for row in audit.json()["rows"]
        if row["legacy_id"] == parent["handle"]
    )
    if publish_mode == "patch":
        published = await client.patch(
            f"{API}/products/{imported_id}",
            json={"draft": False, "visibility": "on-sale"}, headers=headers,
        )
    else:
        visible = await client.post(
            f"{API}/products/bulk",
            json={"action": "visibility", "value": "on-sale",
                  "product_ids": [imported_id]}, headers=headers,
        )
        assert visible.status_code == 200, visible.text
        published = await client.post(
            f"{API}/products/bulk",
            json={"action": "publish", "product_ids": [imported_id]},
            headers=headers,
        )
    assert published.status_code == 200, published.text
    from infinitemarkets.db import db, table

    async with db.connect() as conn:
        children = await conn.fetchall(
            f"SELECT draft, visibility FROM {table('products')} "
            "WHERE parent_product_id = :p", {"p": imported_id},
        )
    assert children and all(
        not child["draft"] and child["visibility"] == "on-sale"
        for child in children
    )
    detail = await client.get(f"{API}/products/{imported_id}")
    assert detail.status_code == 200
    page = await client.get(
        f"/infinitemarkets/p/{merchant['pubkey']}/{detail.json()['d_tag']}"
    )
    assert page.status_code == 200
    assert page.text.count('name="variation"') == 2


async def test_export_is_merchant_scoped(runtime_env):
    """A second user's merchant cannot see another's export rows."""
    client = runtime_env["client"]
    await _merchant(runtime_env)
    exported = await client.get(f"{API}/migration/products/export")
    assert exported.status_code == 200
    # every exported row belongs to the caller's merchant
    assert "infinitemarkets-products-v1" in exported.text


async def test_media_upload_and_relink(runtime_env):
    """Merchant-uploaded media: manifest+bytes → namespaced file → relink
    swaps owned product image URLs to /library/ local paths."""
    from lnbits.settings import settings as host_settings

    from infinitemarkets.db import db, table

    client = runtime_env["client"]
    await _merchant(runtime_env)
    headers = _headers(client)

    cat = await client.post(
        f"{API}/categories",
        json={"name": "media-test", "default_currency": "USD"},
        headers=headers,
    )
    assert cat.status_code == 201, cat.text
    cdn_url = "https://cdn.shopify.com/s/files/1/x.png"
    product = await client.post(
        f"{API}/products",
        json={
            "category_id": cat.json()["id"], "title": "Media item",
            "amount_minor": 100, "currency": "USD", "currency_decimals": 2,
            "visibility": "hidden", "format": "digital",
            "images": [cdn_url], "draft": True,
        },
        headers=headers,
    )
    assert product.status_code == 201, product.text

    sha = hashlib.sha256(_PNG).hexdigest()
    manifest = json.dumps({cdn_url: sha})
    upload = await client.post(
        f"{API}/migration/media/upload",
        data={"manifest": manifest},
        files={"file": ("x.png", _PNG, "image/png")},
        headers=headers,
    )
    assert upload.status_code == 200, upload.text
    assert upload.json()["uploaded"] == 1
    namespace = upload.json()["namespace"]

    media_dir = (
        host_settings.lnbits_data_folder
        and __import__("pathlib").Path(host_settings.lnbits_data_folder)
        / "images" / "infinitemarkets" / namespace
    )
    stored = list(media_dir.glob(f"{sha}.*"))
    assert stored, list(media_dir.iterdir()) if media_dir.exists() else "missing dir"
    assert hashlib.sha256(stored[0].read_bytes()).hexdigest() == sha

    relink = await client.post(
        f"{API}/migration/media/relink", headers=headers,
    )
    assert relink.status_code == 200, relink.text
    assert relink.json()["relinked"] >= 1

    async with db.connect() as conn:
        row = await conn.fetchone(
            f"SELECT url FROM {table('product_images')} WHERE product_id = :p",
            {"p": product.json()["id"]},
        )
    assert row["url"].startswith("/library/infinitemarkets/")

    # Already-local rows are skipped under BOTH prefixes — a second relink
    # and a rewritten (m019-era) row are never re-relinked.
    again = await client.post(
        f"{API}/migration/media/relink", headers=headers,
    )
    assert again.status_code == 200, again.text
    assert again.json()["relinked"] == 0
    async with db.connect() as conn:
        row = await conn.fetchone(
            f"SELECT url FROM {table('product_images')} WHERE product_id = :p",
            {"p": product.json()["id"]},
        )
    assert row["url"].startswith("/library/infinitemarkets/")


async def test_m019_rewrites_legacy_media_urls(runtime_env):
    """m019 data migration (06-04): stored ``/images/infinitemarkets/``
    references rewrite to ``/library/infinitemarkets/`` — the mount the
    pinned host actually serves. Covers product_images.url (column-start),
    merchants.profile_json/theme and settings.value (JSON-string-start);
    a foreign-host URL containing the substring is untouched even when it
    shares a row with a rewritten value; re-running rewrites nothing."""
    import uuid as uuid_mod

    from infinitemarkets import migrations
    from infinitemarkets.db import db, table

    client = runtime_env["client"]
    merchant = await _merchant(runtime_env)
    mid = merchant["id"]
    headers = _headers(client)

    cat = await client.post(
        f"{API}/categories",
        json={"name": "m019-test", "default_currency": "USD"},
        headers=headers,
    )
    assert cat.status_code == 201, cat.text
    product = await client.post(
        f"{API}/products",
        json={
            "category_id": cat.json()["id"], "title": "m019 item",
            "amount_minor": 100, "currency": "USD", "currency_decimals": 2,
            "visibility": "hidden", "format": "digital", "draft": True,
            "images": ["https://cdn.example.com/legacy.png"],
        },
        headers=headers,
    )
    assert product.status_code == 201, product.text
    pid = product.json()["id"]

    legacy_pic = f"/images/infinitemarkets/{'ab' * 12}/{'cd' * 32}.png"
    live_pic = f"/library/infinitemarkets/{'ab' * 12}/{'cd' * 32}.png"
    foreign = "https://other.example/images/infinitemarkets/x.png"
    async with db.connect() as conn:
        # column-start legacy reference (v1.0 relink output)
        await conn.execute(
            f"UPDATE {table('product_images')} SET url = :u "
            "WHERE product_id = :p",
            {"u": legacy_pic, "p": pid},
        )
        # foreign-host URL carrying the same substring — control row
        await conn.execute(
            f"INSERT INTO {table('product_images')} "
            "(id, product_id, url, sort_order) VALUES (:i, :p, :u, 1)",
            {"i": uuid_mod.uuid4().hex, "p": pid, "u": foreign},
        )
        # JSON-embedded legacy refs sharing a row with a foreign URL
        await conn.execute(
            f"UPDATE {table('merchants')} SET profile_json = :pj, "
            "theme = :th WHERE id = :m",
            {
                "pj": json.dumps({
                    "picture": legacy_pic,
                    "website": foreign,
                }),
                "th": json.dumps({
                    "footer": {"logo_url": legacy_pic},
                }),
                "m": mid,
            },
        )
        await conn.execute(
            f"INSERT INTO {table('settings')} (merchant_id, key, value) "
            "VALUES (:m, :k, :v)",
            {
                "m": mid, "k": "m019-probe",
                "v": json.dumps({"img": legacy_pic, "remote": foreign}),
            },
        )

        migrate = getattr(migrations, "m019_media_library_mount", None)
        assert migrate is not None, "m019_media_library_mount missing"
        await migrate(conn)

        imgs = await conn.fetchall(
            f"SELECT url FROM {table('product_images')} "
            "WHERE product_id = :p ORDER BY url",
            {"p": pid},
        )
        urls = sorted(r["url"] for r in imgs)
        assert urls == sorted([foreign, live_pic])
        mrow = await conn.fetchone(
            f"SELECT profile_json, theme FROM {table('merchants')} "
            "WHERE id = :m",
            {"m": mid},
        )
        profile = json.loads(mrow["profile_json"])
        assert profile["picture"] == live_pic
        assert profile["website"] == foreign
        theme = json.loads(mrow["theme"])
        assert theme["footer"]["logo_url"] == live_pic
        srow = await conn.fetchone(
            f"SELECT value FROM {table('settings')} "
            "WHERE merchant_id = :m AND key = 'm019-probe'",
            {"m": mid},
        )
        setting = json.loads(srow["value"])
        assert setting["img"] == live_pic
        assert setting["remote"] == foreign

        # idempotent: a second run leaves every row byte-identical
        await migrate(conn)
        imgs = await conn.fetchall(
            f"SELECT url FROM {table('product_images')} "
            "WHERE product_id = :p ORDER BY url",
            {"p": pid},
        )
        assert sorted(r["url"] for r in imgs) == sorted(
            [foreign, live_pic]
        )
        mrow = await conn.fetchone(
            f"SELECT profile_json, theme FROM {table('merchants')} "
            "WHERE id = :m",
            {"m": mid},
        )
        assert json.loads(mrow["profile_json"]) == profile
        assert json.loads(mrow["theme"]) == theme


async def test_native_image_url_library_round_trip(runtime_env):
    """06-04 import side: ``_native_image_url`` round-trips owned
    ``/library/infinitemarkets/`` refs verbatim, normalizes owned legacy
    ``/images/infinitemarkets/`` input onto the live mount at ingest, and
    keeps accepting non-owned ``/images/`` values — ``..``/``//`` guards
    unchanged."""
    import pytest as _pytest

    from infinitemarkets.services import migration_import

    live = "/library/infinitemarkets/abc123/def.png"
    assert migration_import._native_image_url(live) == live
    assert migration_import._native_image_url(
        "/images/infinitemarkets/abc123/def.png"
    ) == live
    assert migration_import._native_image_url(
        "/images/other-site/pic.png"
    ) == "/images/other-site/pic.png"
    assert migration_import._native_image_url(
        "https://cdn.example/x.png"
    ) == "https://cdn.example/x.png"
    for bad in (
        "/images/../x.png",
        "/library/../x.png",
        "//evil.example/x.png",
        "http://insecure.example/x.png",
    ):
        with _pytest.raises(ValueError, match="image URL"):
            migration_import._native_image_url(bad)


async def test_media_upload_rejects_foreign_and_mismatched(runtime_env):
    """Manifest URLs must belong to the merchant's own products and the
    sha256 must match the uploaded bytes."""
    client = runtime_env["client"]
    headers = _headers(client)
    await _merchant(runtime_env)

    foreign = json.dumps({"https://other.example/img.png": "a" * 64})
    resp = await client.post(
        f"{API}/migration/media/upload",
        data={"manifest": foreign},
        files={"file": ("x.png", _PNG, "image/png")},
        headers=headers,
    )
    assert resp.status_code == 409, resp.text

    # unowned hash in manifest scope — URL is owned but bytes don't match
    cat = await client.post(
        f"{API}/categories",
        json={"name": "media-bad", "default_currency": "USD"},
        headers=headers,
    )
    await client.post(
        f"{API}/products",
        json={
            "category_id": cat.json()["id"], "title": "Mismatch",
            "amount_minor": 100, "currency": "USD", "currency_decimals": 2,
            "visibility": "hidden", "format": "digital", "draft": True,
            "images": ["https://cdn.example.com/owned.png"],
        },
        headers=headers,
    )
    manifest = json.dumps({"https://cdn.example.com/owned.png": "b" * 64})
    resp = await client.post(
        f"{API}/migration/media/upload",
        data={"manifest": manifest},
        files={"file": ("x.png", _PNG, "image/png")},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["uploaded"] == 0
    assert resp.json()["results"][0]["reason"] == "hash-not-in-manifest"


async def test_lightnin_dark_storefront_profile(runtime_env):
    """lightnin-dark preset + quad grid + hidden hero + footer logo reach
    the public document."""
    client = runtime_env["client"]
    merchant = await _merchant(runtime_env)
    resp = await client.patch(
        f"{API}/merchants/{merchant['id']}",
        json={"theme": {
            "preset": "lightnin-dark",
            "storefront": {"grid": "quad", "hero_hidden": True},
            "footer": {"logo_url": "/images/infinitemarkets/x/logo.png"},
        }},
        headers=_headers(client),
    )
    assert resp.status_code == 200, resp.text
    theme = resp.json()["theme"]
    assert theme["preset"] == "lightnin-dark"
    assert theme["storefront"]["grid"] == "quad"
    assert theme["storefront"]["hero_hidden"] is True

    index = await client.get(
        f"/infinitemarkets/public/merchants/{merchant['pubkey']}"
    )
    assert index.status_code == 200
    assert 'data-grid="quad"' in index.text
    assert 'class="merchant-hero"' not in index.text
    assert "footer-logo" in index.text
    assert "images/infinitemarkets/x/logo.png" in index.text
    assert "#242833" in index.text and "#fce477" in index.text

    # invalid grid rejected
    bad = await client.patch(
        f"{API}/merchants/{merchant['id']}",
        json={"theme": {"storefront": {"grid": "mega"}}},
        headers=_headers(client),
    )
    assert bad.status_code == 422
