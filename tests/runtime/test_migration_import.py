import csv
import json
import os
from pathlib import Path

import pytest

from infinitemarkets.services.migration_import import parse_shopify_csv, preview_shopify_import

SAMPLE = Path(__file__).resolve().parents[1] / "fixtures" / "shopify_products_sample.csv"


def test_modern_shopify_groups_variants_and_unknown_stock():
    products = parse_shopify_csv(SAMPLE.read_bytes(), currency="USD")
    assert len(products) == 2
    mug, shirt = products
    assert mug["handle"] == "ceramic-mug"
    assert mug["stock_on_hand"] == 7
    assert shirt["stock_on_hand"] == 8
    assert [v["sku"] for v in shirt["variants"]] == ["TSHIRT-S", "TSHIRT-M"]
    assert [v["amount_minor"] for v in shirt["variants"]] == [2450, 2450]
    assert all(p["draft"] and p["visibility"] == "hidden" for p in products)


def test_classic_shopify_image_only_rows_and_missing_inventory():
    headers = [
        "Handle",
        "Title",
        "Body (HTML)",
        "Variant SKU",
        "Variant Price",
        "Image Src",
        "Image Position",
        "Variant Image",
        "Status",
    ]
    rows = [
        [
            "mug",
            "Mug",
            "<p>Hello</p><script>danger()</script>",
            "MUG-1",
            "12.50",
            "https://cdn.shopify.com/a.jpg",
            "1",
            "https://cdn.shopify.com/a.jpg",
            "active",
        ],
        ["mug", "", "", "", "", "https://cdn.shopify.com/b.jpg", "2", "", ""],
    ]
    from io import StringIO

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    writer.writerows(rows)
    (product,) = parse_shopify_csv(output.getvalue().encode(), currency="USD")
    assert product["description_md"] == "Hello"
    assert product["images"] == ["https://cdn.shopify.com/a.jpg", "https://cdn.shopify.com/b.jpg"]
    assert product["stock_on_hand"] == 0
    assert product["inventory_unknown"] is True
    assert product["source_status"] == "active"


def test_shopify_rejects_overflow_and_bad_urls():
    data = (
        "Handle,Title,Variant SKU,Variant Price,Image Src\n"
        + "mug,Mug,MUG,10,https://cdn.shopify.com/0.jpg\n"
        + "".join(f"mug,,,,https://cdn.shopify.com/{i}.jpg\n" for i in range(1, 21))
    )
    with pytest.raises(ValueError, match="image selection"):
        parse_shopify_csv(data.encode(), currency="USD")
    with pytest.raises(ValueError, match="image URL"):
        parse_shopify_csv(data.replace("cdn.shopify.com", "127.0.0.1").encode(), currency="USD")
    initial = preview_shopify_import(
        data.encode(), currency="USD", source_instance="sample-store"
    )
    assert initial["products"][0]["image_selection_required"]
    assert len(initial["products"][0]["images"]) == 21
    chosen = {"mug": initial["products"][0]["images"][:20]}
    selected = preview_shopify_import(
        data.encode(), currency="USD", source_instance="sample-store",
        image_selection=chosen,
    )
    assert len(selected["products"][0]["images"]) == 20
    assert selected["source_hash"] != initial["source_hash"]
    assert len(parse_shopify_csv(
        data.encode(), currency="USD", image_selection=chosen
    )[0]["images"]) == 20


def test_three_product_stock_fixture_with_variant_total():
    data = (
        "Handle,Title,Variant SKU,Variant Price,Variant Inventory Qty,Image Src\n"
        "blanket,Blanket,B-S,20.00,34,https://cdn.shopify.com/1.jpg\n"
        "blanket,,B-M,20.00,33,https://cdn.shopify.com/2.jpg\n"
        "blanket,,B-L,20.00,33,https://cdn.shopify.com/3.jpg\n"
        "blanket,,,,,https://cdn.shopify.com/4.jpg\n"
        "mug,Mug,MUG,8.00,100,https://cdn.shopify.com/5.jpg\n"
        "bag,Bag,BAG,14.00,100,https://cdn.shopify.com/6.jpg\n"
    )
    products = parse_shopify_csv(data.encode(), currency="USD")
    assert len(products) == 3
    assert [p["stock_on_hand"] for p in products] == [100, 100, 100]
    assert [v["stock_on_hand"] for v in products[0]["variants"]] == [34, 33, 33]
    assert len(products[0]["images"]) == 4


def test_any_unknown_variant_blocks_product_stock():
    data = (
        "Handle,Title,Variant SKU,Variant Price,Variant Inventory Qty,Image Src\n"
        "shirt,Shirt,S,10.00,50,https://cdn.shopify.com/1.jpg\n"
        "shirt,,M,10.00,,https://cdn.shopify.com/2.jpg\n"
    )
    (product,) = parse_shopify_csv(data.encode(), currency="USD")
    assert product["stock_on_hand"] == 0
    assert product["inventory_unknown"] is True


def test_shopify_requires_explicit_currency():
    with pytest.raises(ValueError, match="currency"):
        parse_shopify_csv(SAMPLE.read_bytes(), currency="")
    with pytest.raises(ValueError, match="unsupported"):
        parse_shopify_csv(SAMPLE.read_bytes(), currency="ZZZ")


async def test_imported_drafts_cannot_be_published(runtime_env):
    from infinitemarkets.db import db, table
    from infinitemarkets.services import migration_import

    client = runtime_env["client"]
    origin = "https://shop.example"
    await client.get("/infinitemarkets/api/v1/merchants/current")
    headers = {"Origin": origin, "X-CSRF-Token": client.cookies.get("gm_csrf")}
    merchant = await client.post(
        "/infinitemarkets/api/v1/merchants",
        json={"wallet_id": runtime_env["wallet"].id},
        headers=headers,
    )
    assert merchant.status_code == 201, merchant.text
    merchant_id = merchant.json()["id"]
    data = SAMPLE.read_bytes()
    preview = migration_import.preview_shopify_import(
        data, currency="USD", source_instance="sample-store"
    )
    import_api = "/infinitemarkets/api/v1/migration/shopify"
    form = {"currency": "USD", "source_instance": "sample-store"}
    upload = {"file": ("shopify.csv", data, "text/csv")}
    preview_response = await client.post(
        f"{import_api}/preview", data=form, files=upload, headers=headers
    )
    assert preview_response.status_code == 200, preview_response.text
    assert preview_response.json()["source_hash"] == preview["source_hash"]
    assert (await client.post(
        f"{import_api}/preview", data=form, files=upload,
    )).status_code == 403
    assert (await client.post(
        f"{import_api}/execute",
        data={**form, "source_hash": "wrong"}, files=upload, headers=headers,
    )).status_code == 409
    form["source_hash"] = preview["source_hash"]
    response = await client.post(
        f"{import_api}/execute", data=form, files=upload, headers=headers
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["product_count"] == 2
    from nostr_sdk import Event

    async with db.connect() as conn:
        commitment = await conn.fetchone(
            f"SELECT commitment_json FROM {table('catalog_imports')} "
            "WHERE id = :i", {"i": result["import_id"]},
        )
    signed = Event.from_json(commitment["commitment_json"])
    assert signed.verify() and signed.id().to_hex() == result["commitment_id"]
    repeated = await client.post(
        f"{import_api}/execute", data=form, files=upload, headers=headers
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["already_imported"]
    async with db.connect() as conn:
        rows = await conn.fetchall(
            f"SELECT id, draft, visibility, stock_on_hand FROM {table('products')} "
            "WHERE merchant_id = :m ORDER BY title", {"m": merchant_id},
        )
        outbox = await conn.fetchone(
            f"SELECT COUNT(*) AS n FROM {table('outbox_events')} "
            "WHERE merchant_id = :m AND aggregate_type = 'products'", {"m": merchant_id},
        )
    assert len(rows) == 4
    assert all(row["draft"] and row["visibility"] == "hidden" for row in rows)
    assert outbox["n"] == 0
    product_id = rows[0]["id"]
    api = "/infinitemarkets/api/v1/products"
    assert (await client.patch(
        f"{api}/{product_id}", json={"draft": False}, headers=headers
    )).status_code == 409
    assert (await client.post(
        f"{api}/bulk", json={"product_ids": [product_id], "action": "publish"},
        headers=headers,
    )).status_code == 409
    category = await client.post(
        "/infinitemarkets/api/v1/categories", json={"name": "Reviewed"}, headers=headers
    )
    assert category.status_code == 201, category.text
    async with db.connect() as conn:
        parent = await conn.fetchone(
            f"SELECT product_id FROM {table('import_rows')} "
            "WHERE import_id = :i AND legacy_id = 'cotton-tshirt'",
            {"i": result["import_id"]},
        )
    moved = await client.post(
        f"/infinitemarkets/api/v1/migration/products/{parent['product_id']}/category",
        json={"category_id": category.json()["id"]}, headers=headers,
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["draft"] and moved.json()["category_id"] == category.json()["id"]
    async with db.connect() as conn:
        children = await conn.fetchall(
            f"SELECT category_id, draft FROM {table('products')} "
            "WHERE parent_product_id = :p", {"p": parent["product_id"]},
        )
    assert len(children) == 2
    assert all(c["draft"] and c["category_id"] == category.json()["id"] for c in children)
    overflow = (
        "Handle,Title,Variant SKU,Variant Price,Image Src\n"
        "poster,Poster,POSTER,10.00,https://cdn.shopify.com/0.jpg\n"
        + "".join(
            f"poster,,,,https://cdn.shopify.com/{n}.jpg\n" for n in range(1, 21)
        )
    ).encode()
    image_form = {"currency": "USD", "source_instance": "overflow-store"}
    image_upload = {"file": ("images.csv", overflow, "text/csv")}
    first = await client.post(
        f"{import_api}/preview", data=image_form, files=image_upload, headers=headers
    )
    assert first.status_code == 200, first.text
    assert first.json()["products"][0]["image_selection_required"]
    selected = {"poster": first.json()["products"][0]["images"][:20]}
    image_form["image_selection"] = json.dumps(selected)
    second = await client.post(
        f"{import_api}/preview", data=image_form, files=image_upload, headers=headers
    )
    assert second.status_code == 200, second.text
    assert len(second.json()["products"][0]["images"]) == 20
    image_form["source_hash"] = first.json()["source_hash"]
    assert (await client.post(
        f"{import_api}/execute", data=image_form, files=image_upload, headers=headers
    )).status_code == 409
    image_form["source_hash"] = second.json()["source_hash"]
    imported = await client.post(
        f"{import_api}/execute", data=image_form, files=image_upload, headers=headers
    )
    assert imported.status_code == 200, imported.text
    assert imported.json()["product_count"] == 1


async def test_private_three_product_sample_import(runtime_env):
    from infinitemarkets.db import db, table
    from infinitemarkets.services import migration_import

    sample_path = os.environ.get("INFINITEMARKETS_SHOPIFY_TEST_CSV")
    if not sample_path:
        pytest.skip("Private Shopify sample is not configured")
    data = Path(sample_path).read_bytes()
    client = runtime_env["client"]
    response = await client.get("/infinitemarkets/api/v1/merchants/current")
    assert response.status_code == 200, response.text
    preview = migration_import.preview_shopify_import(
        data, currency="USD", source_instance="private-sample"
    )
    assert len(preview["products"]) == 3
    assert [p["stock_on_hand"] for p in preview["products"]] == [100, 100, 100]
    upload = {"file": ("shopify.csv", data, "text/csv")}
    await client.get("/infinitemarkets/api/v1/merchants/current")
    headers = {
        "Origin": "https://shop.example",
        "X-CSRF-Token": client.cookies.get("gm_csrf"),
    }
    response = await client.post(
        "/infinitemarkets/api/v1/migration/shopify/execute",
        data={"currency": "USD", "source_instance": "private-sample",
              "source_hash": preview["source_hash"]},
        files=upload, headers=headers,
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["product_count"] == 3
    async with db.connect() as conn:
        rows = await conn.fetchall(
            f"SELECT p.id, p.draft, p.visibility, p.stock_on_hand "
            f"FROM {table('products')} p JOIN {table('import_rows')} r "
            "ON r.product_id = p.id WHERE r.import_id = :i",
            {"i": result["import_id"]},
        )
    assert len(rows) == 3
    assert all(row["draft"] and row["visibility"] == "hidden" for row in rows)
    assert sorted(row["stock_on_hand"] for row in rows) == [0, 100, 100]
    async with db.connect() as conn:
        variants = await conn.fetchall(
            f"SELECT p.stock_on_hand, p.draft FROM {table('products')} p "
            f"JOIN {table('import_rows')} r ON r.product_id = p.parent_product_id "
            "WHERE r.import_id = :i", {"i": result["import_id"]},
        )
    assert sorted(row["stock_on_hand"] for row in variants) == [33, 33, 34]
    assert all(row["draft"] for row in variants)
