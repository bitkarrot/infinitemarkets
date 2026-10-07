import asyncio
import csv
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from infinitemarkets.services.migration_import import (
    parse_legacy_catalog,
    parse_shopify_csv,
    preview_shopify_import,
)

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
    with pytest.raises(ValueError, match=r"Shopify row 2: invalid Shopify inventory"):
        parse_shopify_csv(
            b"Handle,Title,Variant Price,Variant Inventory Qty,Image Src\n"
            b"mug,Mug,1.00,not-a-number,\n", currency="USD"
        )
    with pytest.raises(ValueError, match="unsupported"):
        parse_shopify_csv(SAMPLE.read_bytes(), currency="ZZZ")
    yen = parse_shopify_csv(
        b"Handle,Title,Variant Price,Image Src\n"
        b"mug,Mug,12.50,https://cdn.shopify.com/a.jpg\n", currency="JPY"
    )[0]
    assert yen["variants"][0]["amount_minor"] == 13
    assert yen["currency_decimals"] == 0


def test_custom_csv_mapping_is_explicit_and_pinned():
    data = (
        "Key,Name,Price,Stock,Image,SKU,Size\n"
        "mug,Custom Mug,12.50,4,https://cdn.shopify.com/a.jpg,M1,Large\n"
        "mug,,,,https://cdn.shopify.com/b.jpg,,\n"
    ).encode()
    mapping = {"handle": "Key", "title": "Name", "price": "Price", "stock": "Stock",
               "image": "Image", "sku": "SKU", "option1": "Size"}
    with pytest.raises(ValueError, match="headers"):
        parse_shopify_csv(data, currency="USD")
    product = parse_shopify_csv(data, currency="USD", mapping=mapping)[0]
    assert product["stock_on_hand"] == 4 and len(product["images"]) == 2
    assert product["variants"][0]["options"][0] == "Large"
    preview = preview_shopify_import(
        data, currency="USD", source_instance="custom", mapping=mapping
    )
    assert preview["source_hash"] != preview_shopify_import(
        data, currency="USD", source_instance="custom",
        mapping={key: value for key, value in mapping.items() if key != "option1"},
    )["source_hash"]
    with pytest.raises(ValueError, match="mapping"):
        parse_shopify_csv(data, currency="USD", mapping={"handle": "Key"})


def test_nostrmarket_export_normalizes_provisional_orders():
    source = {
        "stalls": [{"id": "stall-a", "currency": "USD", "wallet": "untrusted"}],
        "products": [{"id": "old-a", "stall_id": "stall-a", "name": "Legacy Mug",
                      "price": 12.50, "quantity": 2, "active": True,
                      "image_urls": json.dumps(["https://example.com/mug.jpg"]),
                      "meta": json.dumps({"description": "<p>Mug</p>"})}],
        "orders": [{"id": "old-order", "invoice_id": "a" * 64, "paid": True,
                    "contact_data": "private buyer details",
                    "order_items": json.dumps([{"product_id": "old-a", "quantity": 1}])}],
    }
    result = parse_legacy_catalog(
        json.dumps(source).encode(), source_kind="nostrmarket", currency="USD"
    )
    assert result["products"][0]["variants"][0]["amount_minor"] == 1250
    assert result["products"][0]["description_md"] == "Mug"
    assert result["liabilities"] == [{
        "order_id": "old-order", "invoice_id": "a" * 64,
        "product_legacy_id": "old-a", "quantity": 1,
    }]
    assert result["source_completeness"] == "unknown"
    source["private_key"] = "bad"
    with pytest.raises(ValueError, match="secret fields"):
        parse_legacy_catalog(
            json.dumps(source).encode(), source_kind="nostrmarket", currency="USD"
        )
    del source["private_key"]
    source["products"][0]["image_urls"] = '["https://127.0.0.1/private"]'
    with pytest.raises(ValueError, match="image URL"):
        parse_legacy_catalog(
            json.dumps(source).encode(), source_kind="nostrmarket", currency="USD"
        )
    source["products"][0]["image_urls"] = "[]"
    source["products"][0]["quantity"] = "buyer@example.com"
    with pytest.raises(ValueError, match=r"Legacy product row 1: invalid inventory"):
        parse_legacy_catalog(
            json.dumps(source).encode(), source_kind="nostrmarket", currency="USD"
        )
    source["products"][0]["quantity"] = 2
    source["orders"].append({**source["orders"][0], "id": "second-order"})
    with pytest.raises(ValueError, match="duplicate legacy invoice"):
        parse_legacy_catalog(
            json.dumps(source).encode(), source_kind="nostrmarket", currency="USD"
        )
    with pytest.raises(ValueError, match="nesting limit"):
        parse_legacy_catalog(
            json.dumps({"stalls": [], "products": [{"x": [{"x": [
                {"x": [{"x": "deep"}]}]}]}]}).encode(),
            source_kind="nostrmarket", currency="USD",
        )


def test_nip15_signed_events_and_ndjson_only_allowed_kinds():
    from nostr_sdk import EventBuilder, Keys, Kind, Tag

    keys = Keys.generate()
    stalls = {"id": "stall-a", "name": "Stall", "currency": "sat"}
    products = {"id": "old-a", "stall_id": "stall-a", "name": "Poster",
                "price": 120, "quantity": 1, "images": ["https://example.com/p.jpg"]}
    events = [
        EventBuilder(Kind(kind), json.dumps(content))
        .tags([Tag.parse(["d", content["id"]])]).sign_with_keys(keys)
        for kind, content in ((30017, stalls), (30018, products))
    ]
    deleted = EventBuilder(Kind(5), "old tombstone").sign_with_keys(keys)
    dumped = "\n".join(event.as_json() for event in [*events, deleted]).encode()
    result = parse_legacy_catalog(dumped, source_kind="nip15_events", currency="SAT")
    assert len(result["products"]) == 1 and result["liabilities"] == []
    assert result["products"][0]["stock_on_hand"] == 1
    with pytest.raises(ValueError, match="currency"):
        parse_legacy_catalog(dumped, source_kind="nip15_events", currency="USD")
    with pytest.raises(ValueError, match="signature"):
        parse_legacy_catalog(
            dumped.replace(b"Poster", b"Tamper"),
            source_kind="nip15_events", currency="SAT",
        )


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
        data, currency="USD", source_instance="sample-store", merchant_id=merchant_id
    )
    import_api = "/infinitemarkets/api/v1/migration/shopify"
    form = {"currency": "USD", "source_instance": "sample-store"}
    upload = {"file": ("shopify.csv", data, "text/csv")}
    preview_response = await client.post(
        f"{import_api}/preview", data=form, files=upload, headers=headers
    )
    assert preview_response.status_code == 200, preview_response.text
    assert preview_response.json()["source_hash"] == preview["source_hash"]
    dry_run = await client.post(
        f"{import_api}/dry-run", data=form, files=upload, headers=headers
    )
    assert dry_run.status_code == 200
    assert dry_run.json()["source_hash"] == preview["source_hash"]
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
    listed = await client.get("/infinitemarkets/api/v1/migration/imports")
    assert listed.status_code == 200 and listed.json()[0]["id"] == result["import_id"]
    audit = await client.get(
        f"/infinitemarkets/api/v1/migration/imports/{result['import_id']}"
    )
    assert audit.status_code == 200 and audit.json()["cutover_verified"] is False
    assert audit.json()["commitment"]["id"] == result["commitment_id"]
    assert len(audit.json()["rows"]) == 2
    assert "invoice_ref_enc" not in audit.text
    async with db.connect() as conn:
        original_row = await conn.fetchone(
            f"SELECT id, normalized_json FROM {table('import_rows')} "
            "WHERE import_id = :i ORDER BY legacy_id LIMIT 1",
            {"i": result["import_id"]},
        )
        await conn.execute(
            f"UPDATE {table('import_rows')} SET normalized_json = :j WHERE id = :i",
            {"i": original_row["id"], "j": '{"handle":"tampered"}'},
        )
    try:
        tampered = await client.get(
            f"/infinitemarkets/api/v1/migration/imports/{result['import_id']}"
        )
        assert tampered.status_code == 409
    finally:
        async with db.connect() as conn:
            await conn.execute(
                f"UPDATE {table('import_rows')} SET normalized_json = :j WHERE id = :i",
                {"i": original_row["id"], "j": original_row["normalized_json"]},
            )
    from infinitemarkets.security import ProblemError

    with pytest.raises(ProblemError) as foreign:
        await migration_import.audit_import(
            merchant_id, SimpleNamespace(id="unrelated-owner"), result["import_id"]
        )
    assert foreign.value.status == 404
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
    republish = await client.post(
        f"/infinitemarkets/api/v1/merchants/{merchant_id}/publish", headers=headers
    )
    assert republish.status_code == 200, republish.text
    async with db.connect() as conn:
        product_intents = await conn.fetchone(
            f"SELECT COUNT(*) AS n FROM {table('outbox_events')} "
            "WHERE merchant_id = :m AND aggregate_type = 'products'", {"m": merchant_id},
        )
    assert product_intents["n"] == 0
    product_id = rows[0]["id"]
    api = "/infinitemarkets/api/v1/products"
    assert (await client.patch(
        f"{api}/{product_id}", json={"draft": False}, headers=headers
    )).status_code == 409
    assert (await client.post(
        f"{api}/bulk", json={"product_ids": [product_id], "action": "publish"},
        headers=headers,
    )).status_code == 409
    from infinitemarkets.services import checkout

    async with db.connect() as conn:
        blocked = await conn.fetchone(
            f"SELECT d_tag FROM {table('products')} WHERE id = :i", {"i": product_id},
        )
    with pytest.raises(ProblemError) as rejected:
        await checkout._resolve_items(
            merchant_id, [{"d_tag": blocked["d_tag"], "quantity": 1}]
        )
    assert rejected.value.status == 422
    async with db.connect() as conn:
        await conn.execute(
            f"UPDATE {table('products')} SET draft = FALSE, visibility = 'on-sale' "
            "WHERE id = :i", {"i": product_id},
        )
    try:
        with pytest.raises(ProblemError) as held:
            await checkout._resolve_items(
                merchant_id, [{"d_tag": blocked["d_tag"], "quantity": 1}]
            )
        assert held.value.status == 422
    finally:
        async with db.connect() as conn:
            await conn.execute(
                f"UPDATE {table('products')} SET draft = TRUE, visibility = 'hidden' "
                "WHERE id = :i", {"i": product_id},
            )
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
    preset = {"name": "Small CSV", "mapping": {
        "handle": "Key", "title": "Name", "price": "Price", "stock": "Stock",
    }}
    saved = await client.post(
        "/infinitemarkets/api/v1/migration/csv-presets", json=preset, headers=headers
    )
    assert saved.status_code == 200, saved.text
    assert (await client.get(
        "/infinitemarkets/api/v1/migration/csv-presets"
    )).json()[0]["id"] == saved.json()["id"]
    mapped_csv = b"Key,Name,Price,Stock\ncustom,Custom Item,8.75,3\n"
    mapped_form = {"currency": "USD", "source_instance": "mapped",
                   "mapping": json.dumps(preset["mapping"])}
    mapped_file = {"file": ("custom.csv", mapped_csv, "text/csv")}
    mapped_preview = await client.post(
        f"{import_api}/preview", data=mapped_form, files=mapped_file, headers=headers
    )
    assert mapped_preview.status_code == 200, mapped_preview.text
    mapped_form["source_hash"] = mapped_preview.json()["source_hash"]
    mapped_result = await client.post(
        f"{import_api}/execute", data=mapped_form, files=mapped_file, headers=headers
    )
    assert mapped_result.status_code == 200, mapped_result.text
    concurrent_form = {key: value for key, value in mapped_form.items()
                       if key != "source_hash"}
    concurrent_form["source_instance"] = "mapped-concurrent"
    concurrent_preview = await client.post(
        f"{import_api}/preview", data=concurrent_form,
        files=mapped_file, headers=headers,
    )
    assert concurrent_preview.status_code == 200
    concurrent_form["source_hash"] = concurrent_preview.json()["source_hash"]
    concurrent = await asyncio.gather(*(
        client.post(f"{import_api}/execute", data=concurrent_form,
                    files=mapped_file, headers=headers)
        for _ in range(2)
    ))
    assert all(r.status_code == 200 for r in concurrent), [r.text for r in concurrent]
    assert concurrent[0].json()["import_id"] == concurrent[1].json()["import_id"]
    assert sorted(r.json()["already_imported"] for r in concurrent) == [False, True]
    legacy = {
        "stalls": [{"id": "s-1", "currency": "USD"}],
        "products": [{"id": "p-1", "stall_id": "s-1", "name": "Old Print",
                      "price": 4.25, "quantity": 1,
                      "images": ["https://example.com/print.jpg"]}],
        "orders": [{"id": "order-1", "invoice_id": "b" * 64,
                    "paid": True, "contact_data": "buyer@example.com",
                    "items": [{"product_id": "p-1", "quantity": 1}]}],
    }
    legacy_data = json.dumps(legacy).encode()
    legacy_api = "/infinitemarkets/api/v1/migration/legacy/nostrmarket"
    legacy_form = {"currency": "USD", "source_instance": "old-store"}
    legacy_upload = {"file": ("legacy.json", legacy_data, "application/json")}
    first = await client.post(
        f"{legacy_api}/preview", data=legacy_form, files=legacy_upload, headers=headers
    )
    assert first.status_code == 200, first.text
    assert first.json()["liabilities"][0]["status"] == "unverified"
    assert "buyer@example.com" not in first.text and "b" * 64 not in first.text
    legacy_form["source_hash"] = first.json()["source_hash"]
    imported = await client.post(
        f"{legacy_api}/execute", data=legacy_form, files=legacy_upload, headers=headers
    )
    assert imported.status_code == 200, imported.text
    audited = await client.get(
        f"/infinitemarkets/api/v1/migration/imports/{imported.json()['import_id']}"
    )
    assert audited.status_code == 200 and audited.json()["liability_count"] == 1
    assert audited.json()["liabilities"][0]["status"] == "unverified"
    assert "buyer@example.com" not in audited.text and "b" * 64 not in audited.text
    async with db.connect() as conn:
        stored = await conn.fetchone(
            f"SELECT l.invoice_ref_enc, l.status, p.draft, p.import_authorized "
            f"FROM {table('imported_liabilities')} l "
            f"JOIN {table('products')} p ON p.id = l.product_id "
            "WHERE l.import_id = :i", {"i": imported.json()["import_id"]},
        )
    assert stored["status"] == "unverified" and stored["draft"]
    assert not stored["import_authorized"]
    assert b"b" * 64 not in bytes(stored["invoice_ref_enc"])
    from nostr_sdk import EventBuilder, Keys, Kind, Tag

    signing_keys = Keys.generate()
    events = [
        EventBuilder(Kind(kind), json.dumps(content))
        .tags([Tag.parse(["d", content["id"]])]).sign_with_keys(signing_keys)
        for kind, content in (
            (30017, {"id": "stall-event", "currency": "sat"}),
            (30018, {"id": "p-1", "stall_id": "stall-event",
                     "name": "Signed Poster", "price": 42, "quantity": 1}),
        )
    ]
    events_data = json.dumps([json.loads(e.as_json()) for e in events]).encode()
    events_form = {"currency": "SAT", "source_instance": "event-source"}
    events_file = {"file": ("events.json", events_data, "application/json")}
    event_api = "/infinitemarkets/api/v1/migration/legacy/nip15_events"
    event_preview = await client.post(
        f"{event_api}/dry-run", data=events_form, files=events_file, headers=headers
    )
    assert event_preview.status_code == 200, event_preview.text
    assert event_preview.json()["source_completeness"] == "unknown"
    events_form["source_hash"] = event_preview.json()["source_hash"]
    event_imported = await client.post(
        f"{event_api}/execute", data=events_form, files=events_file, headers=headers
    )
    assert event_imported.status_code == 200, event_imported.text
    assert event_imported.json()["product_count"] == 1
    event_audit = await client.get(
        f"/infinitemarkets/api/v1/migration/imports/{event_imported.json()['import_id']}"
    )
    assert event_audit.json()["source_kind"] == "nip15_events"
    assert event_audit.json()["cutover_verified"] is False


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
        data, currency="USD", source_instance="private-sample",
        merchant_id=response.json()["id"],
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
