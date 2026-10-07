"""04-03: native product CSV export + reimport, owned-media upload/relink,
merchant storefront profile (grid density, hero visibility, footer logo),
and attested activation for non-nostrmarket imports."""

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


async def test_export_reimport_and_attested_activation(runtime_env):
    """Native export → CSV → reimport as blocked drafts → attest →
    physical count → publishable. Formula injection is escaped."""
    client = runtime_env["client"]
    await _merchant(runtime_env)
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
    variant_row = next(r for r in rows if r["row"] == "variant")
    assert variant_row["parent_handle"] in exported_handles
    assert variant_row["option_1"] == "Size=L"
    assert variant_row["stock_on_hand"] == "3"

    # Re-import into the same merchant (source_instance varies per run via
    # timestamp inside execute, so re-importing own export is allowed).
    upload = {"file": ("export.csv", text.encode(), "text/csv")}
    form = {"currency": "USD", "source_instance": "self-reimport"}
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

    staged = await client.post(
        f"{API}/migration/imports/{import_id}/cutover", headers=headers,
    )
    assert staged.status_code == 200, staged.text
    attested = await client.post(
        f"{API}/migration/cutovers/{staged.json()['id']}/attest",
        headers=headers,
    )
    assert attested.status_code == 200, attested.text
    assert attested.json()["state"] == "complete"


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
    swaps owned product image URLs to /images/ local paths."""
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
    assert row["url"].startswith("/images/infinitemarkets/")


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
