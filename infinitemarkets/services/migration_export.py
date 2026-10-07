"""Merchant-scoped product CSV export (plan 04-03 Task 1).

Exports the merchant's own catalog as a versioned RFC4180 UTF-8 CSV that
the native importer (`source_kind="infinitemarkets"`) can preview and
re-import as blocked drafts. The export is a catalog snapshot ONLY — it
contains no keys, invoices, buyers, orders, reservations, delivery
secrets, or encrypted material, and it is not a verified inventory or
liability snapshot.
"""

from __future__ import annotations

import csv
import io
import re

from ..db import db, table
from ..security import unprocessable

FORMAT_MARKER = "infinitemarkets-products-v1"

MAX_EXPORT_PRODUCTS = 5000
MAX_EXPORT_ROWS = 40000

_HEADER = [
    "row", "handle", "title", "description_md", "currency",
    "amount_minor", "currency_decimals", "product_type", "parent_handle",
    "variant_index", "sku", "option_1", "option_2", "option_3",
    "stock_on_hand", "visibility", "draft", "images", "categories",
    "import_source_kind", "import_source_instance", "import_legacy_id",
]

# Spreadsheet formula/dangerous leading characters (CSV injection guard).
_DANGEROUS = ("=", "+", "-", "@", "\t", "\r", "\x0b", "\x0c")


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    text = str(value)
    if text.startswith(_DANGEROUS):
        return "'" + text
    return text


def _list_cell(values: list[str]) -> str:
    safe = [str(v).replace("|", " ").strip() for v in values if str(v).strip()]
    return "|".join(safe)


async def export_products_csv(merchant_id: str, user) -> str:
    """Build the versioned CSV for the merchant's full catalog."""
    from . import catalog

    await catalog._merchant_owned(merchant_id, user)
    async with db.connect() as conn:
        products = await conn.fetchall(
            f"SELECT p.id, p.d_tag, p.title, p.description_md, p.currency, "
            f"p.amount_minor, p.currency_decimals, p.product_type, "
            f"p.parent_product_id, p.stock_on_hand, p.stock_reserved, "
            f"p.visibility, p.draft, "
            f"p.import_source_kind, p.import_source_instance, "
            f"p.import_legacy_id "
            f"FROM {table('products')} p WHERE p.merchant_id = :m "
            f"AND p.deleted_at IS NULL ORDER BY p.created_at, p.id "
            f"LIMIT :limit",
            {"m": merchant_id, "limit": MAX_EXPORT_PRODUCTS + 1},
        )
        if len(products) > MAX_EXPORT_PRODUCTS:
            raise unprocessable(
                "export-limit", "Catalog exceeds export row limit",
            )
        product_ids = [p["id"] for p in products]
        images, specs, categories = {}, {}, {}
        if product_ids:
            ph = ", ".join(f":p{i}" for i in range(len(product_ids)))
            for row in await conn.fetchall(
                f"SELECT product_id, url FROM {table('product_images')} "
                f"WHERE product_id IN ({ph}) ORDER BY sort_order, id",
                {f"p{i}": p for i, p in enumerate(product_ids)},
            ):
                images.setdefault(row["product_id"], []).append(row["url"])
            for row in await conn.fetchall(
                f"SELECT product_id, key, value FROM {table('product_specs')} "
                f"WHERE product_id IN ({ph}) ORDER BY key, id",
                {f"p{i}": p for i, p in enumerate(product_ids)},
            ):
                specs.setdefault(row["product_id"], []).append(dict(row))
            for row in await conn.fetchall(
                f"SELECT product_id, category FROM {table('product_categories')} "
                f"WHERE product_id IN ({ph}) ORDER BY category",
                {f"p{i}": p for i, p in enumerate(product_ids)},
            ):
                categories.setdefault(row["product_id"], []).append(row["category"])

    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(["format", FORMAT_MARKER])
    writer.writerow(_HEADER)
    by_id = {p["id"]: p for p in products}
    count = 0
    for product in products:
        spec_map = {s["key"]: s["value"] for s in specs.get(product["id"], [])}
        # variant option dimensions: every non-SKU spec becomes one option,
        # emitted as "Name=Value" so the named dimension survives a
        # round-trip; positional "Option N" specs emit the bare value.
        options = []
        for spec in specs.get(product["id"], []):
            if spec["key"] == "SKU":
                continue
            if re.fullmatch(r"Option \d", spec["key"]):
                options.append(spec["value"])
            else:
                options.append(f"{spec['key']}={spec['value']}")
        parent_handle = ""
        variant_index = ""
        if product["product_type"] == "variation":
            parent = by_id.get(product["parent_product_id"])
            if parent is None:
                continue  # dangling variation — never silently export orphan
            parent_handle = parent["d_tag"]
            siblings = [
                s for s in products
                if s["parent_product_id"] == parent["id"]
            ]
            variant_index = str(siblings.index(product) + 1)
        writer.writerow([
            "variant" if product["product_type"] == "variation" else "product",
            _cell(product["d_tag"]), _cell(product["title"]),
            _cell(product["description_md"]), _cell(product["currency"]),
            product["amount_minor"] if product["amount_minor"] is not None
            else "",
            product["currency_decimals"]
            if product["currency_decimals"] is not None else "",
            product["product_type"], _cell(parent_handle), variant_index,
            _cell(spec_map.get("SKU", "")),
            _cell(options[0] if len(options) > 0 else ""),
            _cell(options[1] if len(options) > 1 else ""),
            _cell(options[2] if len(options) > 2 else ""),
            product["stock_on_hand"]
            if product["stock_on_hand"] is not None else "",
            product["visibility"], "1" if product["draft"] else "0",
            _cell(_list_cell(images.get(product["id"], []))),
            _cell(_list_cell(categories.get(product["id"], []))),
            _cell(product["import_source_kind"]),
            _cell(product["import_source_instance"]),
            _cell(product["import_legacy_id"]),
        ])
        count += 1
        if count > MAX_EXPORT_ROWS:
            raise unprocessable(
                "export-limit", "Catalog exceeds export row limit",
            )
    return out.getvalue()
