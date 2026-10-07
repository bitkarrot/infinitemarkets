from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import time
import uuid
from collections import OrderedDict
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from html.parser import HTMLParser
from urllib.parse import urlsplit

from lnbits.utils.exchange_rates import currencies

from ..db import DomainTransaction
from ..keystore import MerchantKeyStore
from ..security import conflict
from ..settings import ext_settings
from . import catalog
from .fx import default_currency_decimals

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_ROWS = 5000
MAX_COLUMNS = 100
MAX_CELL_LENGTH = 65536
MAX_IMAGES = 20
MAX_STOCK = 2**63 - 1


class _TextOnly(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.suppressed = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.suppressed += 1
        elif tag in ("br", "p", "div", "li") and not self.suppressed:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.suppressed = max(0, self.suppressed - 1)
        elif tag in ("p", "div", "li") and not self.suppressed:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.suppressed:
            self.parts.append(data)


def _description(value: str) -> str:
    parser = _TextOnly()
    parser.feed(value)
    return re.sub(r"\n\s*\n+", "\n", "".join(parser.parts)).strip()


def _image_url(value: str) -> str:
    if len(value) > 2048 or any(ord(c) < 32 for c in value):
        raise ValueError("invalid Shopify image URL")
    try:
        url = urlsplit(value)
        host = url.hostname
        port = url.port
    except ValueError as exc:
        raise ValueError("invalid Shopify image URL") from exc
    if (
        url.scheme != "https"
        or host not in ("cdn.shopify.com", "burst.shopifycdn.com")
        or url.username
        or url.password
        or port not in (None, 443)
    ):
        raise ValueError("invalid Shopify image URL")
    return value


def _amount(value: str, decimals: int) -> int:
    if not re.fullmatch(r"[0-9]{1,14}(?:\.[0-9]{1,8})?", value):
        raise ValueError("invalid Shopify price")
    try:
        major = Decimal(value)
        if not major.is_finite() or major < 0:
            raise ValueError("invalid Shopify price")
        minor = int((major * (10**decimals)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, OverflowError) as exc:
        raise ValueError("invalid Shopify price") from exc
    if minor > MAX_STOCK:
        raise ValueError("invalid Shopify price")
    return minor


def _stock(value: str) -> int | None:
    if not value:
        return None
    if len(value) > 19 or not value.isascii() or not value.isdecimal():
        raise ValueError("invalid Shopify inventory quantity")
    qty = int(value)
    if qty > MAX_STOCK:
        raise ValueError("invalid Shopify inventory quantity")
    return qty


def _rows(reader: csv.DictReader):
    try:
        yield from reader
    except csv.Error as exc:
        raise ValueError("invalid Shopify CSV row") from exc


def parse_shopify_csv(
    data: bytes, *, currency: str, image_selection: dict[str, list[str]] | None = None,
    preview: bool = False,
) -> list[dict]:
    if not currency or not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValueError("select a three-letter source currency")
    if currency not in currencies:
        raise ValueError("unsupported source currency")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("Shopify CSV exceeds upload limit")
    if image_selection is not None and (
        not isinstance(image_selection, dict) or len(image_selection) > MAX_ROWS
        or any(
            not isinstance(handle, str) or not isinstance(urls, list)
            or len(urls) > MAX_IMAGES or any(not isinstance(url, str) for url in urls)
            for handle, urls in image_selection.items()
        )
    ):
        raise ValueError("invalid Shopify image selection")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("Shopify CSV must be UTF-8") from exc
    try:
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
        headers = reader.fieldnames or []
    except csv.Error as exc:
        raise ValueError("invalid Shopify CSV headers") from exc
    if (
        len(headers) > MAX_COLUMNS
        or len(set(headers)) != len(headers)
        or not all(h and len(h) <= 100 for h in headers)
    ):
        raise ValueError("invalid Shopify CSV headers")
    if {"Handle", "Variant Price", "Image Src"} <= set(headers):
        keys = {
            "handle": "Handle",
            "description": "Body (HTML)",
            "sku": "Variant SKU",
            "price": "Variant Price",
            "image": "Image Src",
            "variant_image": "Variant Image",
            "stock": "Variant Inventory Qty",
            "option": "Option",
            "status": "Status",
        }
    elif {"URL handle", "Price", "Product image URL"} <= set(headers) or {
        "URL handle",
        "Price",
        "Inventory quantity",
    } <= set(headers):
        keys = {
            "handle": "URL handle",
            "description": "Description",
            "sku": "SKU",
            "price": "Price",
            "image": "Product image URL",
            "variant_image": "Variant image URL",
            "stock": "Inventory quantity",
            "option": "Option",
            "status": "Status",
        }
    else:
        raise ValueError("unsupported Shopify CSV headers")
    products: OrderedDict[str, dict] = OrderedDict()
    seen_variants: dict[str, set[tuple]] = {}
    images: dict[str, dict[str, int]] = {}
    decimals = default_currency_decimals(currency)
    for index, row in enumerate(_rows(reader)):
        if index >= MAX_ROWS:
            raise ValueError("Shopify CSV exceeds row limit")
        if None in row or any(v is None or len(v) > MAX_CELL_LENGTH for v in row.values()):
            raise ValueError("invalid Shopify CSV row")
        handle = row[keys["handle"]].strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,199}", handle):
            raise ValueError("invalid Shopify handle")
        product = products.get(handle)
        if product is None:
            product = {
                "handle": handle,
                "title": "",
                "description_md": "",
                "currency": currency,
                "currency_decimals": decimals,
                "variants": [],
                "images": [],
                "stock_on_hand": 0,
                "inventory_unknown": False,
                "source_status": "",
                "draft": True,
                "visibility": "hidden",
            }
            products[handle] = product
            seen_variants[handle] = set()
            images[handle] = {}
        title = row.get("Title", "").strip()
        if title:
            if len(title) > 200:
                raise ValueError("Shopify title exceeds limit")
            product["title"] = title
        desc = row.get(keys["description"], "")
        if desc:
            if len(desc.encode()) > MAX_CELL_LENGTH:
                raise ValueError("Shopify description exceeds limit")
            product["description_md"] = _description(desc)
        status = row.get(keys["status"], "").strip()
        if status:
            product["source_status"] = status[:32]
        image = row.get(keys["image"], "").strip()
        if image:
            image = _image_url(image)
            pos = row.get("Image Position", "").strip()
            if pos and (not pos.isascii() or not pos.isdecimal() or int(pos) > MAX_ROWS):
                raise ValueError("invalid Shopify image position")
            images[handle].setdefault(image, int(pos) if pos else MAX_ROWS + index)
        variant_image = row.get(keys["variant_image"], "").strip()
        if variant_image:
            variant_image = _image_url(variant_image)
            images[handle].setdefault(variant_image, MAX_ROWS * 2 + index)
        price = row.get(keys["price"], "").strip()
        if price:
            options = [
                row.get(
                    f"{keys['option']}{n} Value", row.get(f"{keys['option']}{n} value", "")
                ).strip()
                for n in (1, 2, 3)
            ]
            sku = row.get(keys["sku"], "").strip()
            if len(sku) > 200 or any(len(option) > 200 for option in options):
                raise ValueError("Shopify variant field exceeds limit")
            identity = (sku, *options)
            if identity in seen_variants[handle]:
                raise ValueError("duplicate Shopify variant")
            seen_variants[handle].add(identity)
            qty = _stock(row.get(keys["stock"], "").strip())
            product["inventory_unknown"] |= qty is None
            product["stock_on_hand"] += qty or 0
            if product["stock_on_hand"] > MAX_STOCK:
                raise ValueError("invalid Shopify inventory quantity")
            product["variants"].append(
                {
                    "sku": sku,
                    "options": options,
                    "amount_minor": _amount(price, decimals),
                    "stock_on_hand": qty or 0,
                    "inventory_unknown": qty is None,
                    "image": variant_image or None,
                }
            )
        elif row.get(keys["sku"], "").strip() or row.get(keys["stock"], "").strip():
            raise ValueError("Shopify variant has no price")
    if not products:
        raise ValueError("Shopify CSV has no products")
    if set(image_selection or {}) - set(products):
        raise ValueError("invalid Shopify image selection")
    for handle, product in products.items():
        if not product["title"] or not product["variants"]:
            raise ValueError("Shopify product missing title or variants")
        if product["inventory_unknown"]:
            product["stock_on_hand"] = 0
        ordered = [url for url, _ in sorted(images[handle].items(), key=lambda pair: pair[1])]
        selection = (image_selection or {}).get(handle)
        if selection is not None:
            if (len(set(selection)) != len(selection) or len(selection) > MAX_IMAGES
                    or not set(selection) <= set(ordered)):
                raise ValueError("invalid Shopify image selection")
            required = {v["image"] for v in product["variants"] if v["image"]}
            if not required <= set(selection):
                raise ValueError("Shopify selection must include variant images")
            ordered = [url for url in ordered if url in selection]
        elif len(ordered) > MAX_IMAGES:
            if not preview:
                raise ValueError("Shopify product needs explicit image selection")
            product["image_selection_required"] = True
        product["images"] = ordered
    return list(products.values())


def preview_shopify_import(
    data: bytes, *, currency: str, source_instance: str,
    image_selection: dict[str, list[str]] | None = None,
) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", source_instance):
        raise ValueError("invalid source instance")
    products = parse_shopify_csv(
        data, currency=currency, image_selection=image_selection, preview=True
    )
    selected = json.dumps(
        {handle: sorted(urls) for handle, urls in (image_selection or {}).items()},
        sort_keys=True, separators=(",", ":"),
    ).encode()
    source_hash = hashlib.sha256(
        source_instance.encode() + b"\0" + currency.encode() + b"\0" + data
        + b"\0" + selected
    ).hexdigest()
    return {"source_hash": source_hash, "source_instance": source_instance,
            "products": products, "source_completeness": "unknown",
            "cutover_verified": False}


async def execute_shopify_import(
    merchant_id: str, user, data: bytes, *, currency: str,
    source_instance: str, expected_hash: str,
    image_selection: dict[str, list[str]] | None = None,
) -> dict:
    await catalog._merchant_owned(merchant_id, user)
    preview = preview_shopify_import(
        data, currency=currency, source_instance=source_instance,
        image_selection=image_selection,
    )
    if any(p.get("image_selection_required") for p in preview["products"]):
        raise ValueError("Shopify product needs explicit image selection")
    if not expected_hash or expected_hash != preview["source_hash"]:
        raise conflict("import-changed", "Import differs from preview")
    products = preview["products"]
    import_id = uuid.uuid4().hex
    now = int(time.time())
    from nostr_sdk import EventBuilder, Kind, PublicKey, Tag

    keystore = MerchantKeyStore(ext_settings())
    pubkey = await keystore.public_key(merchant_id)
    commitment = {
        "version": 1, "phase": "provisional", "source": "shopify",
        "source_hash": expected_hash, "product_count": len(products),
        "source_instance_hash": hashlib.sha256(source_instance.encode()).hexdigest(),
        "liability_completeness": "unknown",
    }
    builder = EventBuilder(
        Kind(30078), json.dumps(commitment, sort_keys=True, separators=(",", ":"))
    ).tags([Tag.parse(["d", "im-import-" + expected_hash[:32]])])
    signed = await keystore.sign_event(merchant_id, builder.build(PublicKey.parse(pubkey)))
    if not signed.verify():
        raise conflict("import-signature", "Import commitment could not be verified")
    async with DomainTransaction() as tx:
        await tx.fetch_one(
            f"SELECT id FROM {tx.table('merchants')} WHERE id = :m{tx.for_update}",
            {"m": merchant_id},
        )
        previous = await tx.fetch_one(
            f"SELECT id, product_count, commitment_id FROM {tx.table('catalog_imports')} "
            "WHERE merchant_id = :m AND source_kind = 'shopify' "
            "AND source_instance = :s AND source_hash = :h",
            {"m": merchant_id, "s": source_instance, "h": expected_hash},
        )
        if previous:
            return {"import_id": previous["id"], "product_count": previous["product_count"],
                    "state": "blocked_drafts", "already_imported": True,
                    "commitment_id": previous["commitment_id"]}
        for product in products:
            existing = await tx.fetch_one(
                f"SELECT id FROM {tx.table('products')} "
                "WHERE merchant_id = :m AND import_source_kind = 'shopify' "
                "AND import_source_instance = :s AND import_legacy_id = :l",
                {"m": merchant_id, "s": source_instance, "l": product["handle"]},
            )
            if existing:
                raise conflict("import-conflict", "Source product was imported before")
        holding = await tx.fetch_one(
            f"SELECT id FROM {tx.table('categories')} "
            "WHERE merchant_id = :m AND import_review = TRUE AND deleted_at IS NULL",
            {"m": merchant_id},
        )
        category_id = holding["id"] if holding else uuid.uuid4().hex
        if not holding:
            await tx.execute(
                f"INSERT INTO {tx.table('categories')} "
                "(id, merchant_id, name, default_currency, nip15_stall_d, "
                "publish_gamma, publish_nip15, import_review, public_slug, "
                "created_at, updated_at) "
                "VALUES (:i, :m, :n, :c, :d, FALSE, FALSE, TRUE, :slug, :t, :t)",
                {"i": category_id, "m": merchant_id, "n": "Imported — review",
                 "c": currency, "d": uuid.uuid4().hex, "slug": uuid.uuid4().hex,
                 "t": now},
            )
        await tx.execute(
            f"INSERT INTO {tx.table('catalog_imports')} "
            "(id, merchant_id, source_kind, source_instance, source_hash, "
            "source_currency, commitment_json, commitment_id, "
            "state, product_count, created_at) "
            "VALUES (:i, :m, 'shopify', :s, :h, :c, :j, :e, "
            "'blocked_drafts', :n, :t)",
            {"i": import_id, "m": merchant_id, "s": source_instance,
             "h": expected_hash, "c": currency, "j": signed.as_json(),
             "e": signed.id().to_hex(), "n": len(products), "t": now},
        )
        for product in products:
            variants = product["variants"]
            parent_payload = {
                "title": product["title"], "description_md": product["description_md"],
                "currency": currency, "currency_decimals": product["currency_decimals"],
                "product_type": "variable" if len(variants) > 1 else "simple",
                "amount_minor": min(v["amount_minor"] for v in variants),
                "stock_on_hand": 0 if len(variants) > 1 else product["stock_on_hand"],
                "draft": True, "visibility": "hidden", "images": product["images"],
            }
            if len(variants) == 1:
                variant = variants[0]
                parent_payload["specs"] = _variant_specs(variant)
            parent_id = await catalog.create_import_draft(
                tx, merchant_id, category_id, parent_payload,
                source_instance, product["handle"],
            )
            if len(variants) > 1:
                for index, variant in enumerate(variants):
                    label = (
                        " / ".join(filter(None, variant["options"]))
                        or variant["sku"] or str(index + 1)
                    )
                    payload = {
                        "title": product["title"][:150] + " — " + label[:45],
                        "currency": currency, "currency_decimals": product["currency_decimals"],
                        "product_type": "variation", "parent_product_id": parent_id,
                        "amount_minor": variant["amount_minor"],
                        "stock_on_hand": variant["stock_on_hand"],
                        "draft": True, "visibility": "hidden", "specs": _variant_specs(variant),
                        "images": [variant["image"]] if variant["image"] else [],
                    }
                    await catalog.create_import_draft(
                        tx, merchant_id, category_id, payload,
                        source_instance, f"{product['handle']}::{index + 1}",
                    )
            normalized_hash = hashlib.sha256(
                json.dumps(product, sort_keys=True, ensure_ascii=True).encode()
            ).hexdigest()
            await tx.execute(
                f"INSERT INTO {tx.table('import_rows')} "
                "(id, import_id, product_id, legacy_id, content_hash) "
                "VALUES (:i, :b, :p, :l, :h)",
                {"i": uuid.uuid4().hex, "b": import_id, "p": parent_id,
                 "l": product["handle"], "h": normalized_hash},
            )
    return {"import_id": import_id, "product_count": len(products),
            "state": "blocked_drafts", "already_imported": False,
            "commitment_id": signed.id().to_hex()}


def _variant_specs(variant: dict) -> list[dict]:
    specs = []
    if variant["sku"]:
        specs.append({"key": "SKU", "value": variant["sku"]})
    for index, option in enumerate(variant["options"], start=1):
        if option:
            specs.append({"key": f"Option {index}", "value": option})
    return specs
