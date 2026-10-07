from __future__ import annotations

import csv
import hashlib
import io
import ipaddress
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
CSV_FIELDS = frozenset({
    "handle", "title", "description", "sku", "price", "stock", "image",
    "variant_image", "image_position", "status", "option1", "option2", "option3",
})


def validate_csv_mapping(mapping: dict) -> dict[str, str]:
    if (not isinstance(mapping, dict) or not {"handle", "title", "price"} <= set(mapping)
            or not set(mapping) <= CSV_FIELDS or len(mapping) > len(CSV_FIELDS)
            or any(not isinstance(v, str) or not 0 < len(v) <= 100
                   or re.search(
                       r"buyer|customer|email|phone|address|password|secret|token|private.?key|api.?key",
                       v, re.I,
                   ) for v in mapping.values())
            or len(set(mapping.values())) != len(mapping)):
        raise ValueError("invalid CSV column mapping")
    return dict(mapping)


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
    mapping: dict[str, str] | None = None, preview: bool = False,
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
        or any(re.search(r"private.?key|nsec|seed|password|secret|token", h, re.I)
               for h in headers)
    ):
        raise ValueError("invalid Shopify CSV headers")
    if mapping is not None:
        keys = validate_csv_mapping(mapping)
        if not set(keys.values()) <= set(headers):
            raise ValueError("CSV mapping references missing columns")
    elif {"Handle", "Variant Price", "Image Src"} <= set(headers):
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
            raise ValueError(f"Shopify row {index + 2}: invalid CSV row")
        handle = row[keys["handle"]].strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,199}", handle):
            raise ValueError(f"Shopify row {index + 2}: invalid handle")
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
        title = row.get(keys.get("title", "Title"), "").strip()
        if title:
            if len(title) > 200:
                raise ValueError(f"Shopify row {index + 2}: title exceeds limit")
            product["title"] = title
        desc = row.get(keys.get("description", ""), "")
        if desc:
            if len(desc.encode()) > MAX_CELL_LENGTH:
                raise ValueError(f"Shopify row {index + 2}: description exceeds limit")
            product["description_md"] = _description(desc)
        status = row.get(keys.get("status", ""), "").strip()
        if status:
            if status not in ("active", "draft", "archived"):
                raise ValueError(f"Shopify row {index + 2}: invalid source status")
            product["source_status"] = status
        image = row.get(keys.get("image", ""), "").strip()
        if image:
            try:
                image = _image_url(image)
            except ValueError as exc:
                raise ValueError(f"Shopify row {index + 2}: invalid image URL") from exc
            pos = row.get(keys.get("image_position", "Image Position"), "").strip()
            if pos and (not pos.isascii() or not pos.isdecimal() or int(pos) > MAX_ROWS):
                raise ValueError(f"Shopify row {index + 2}: invalid image position")
            images[handle].setdefault(image, int(pos) if pos else MAX_ROWS + index)
        variant_image = row.get(keys.get("variant_image", ""), "").strip()
        if variant_image:
            try:
                variant_image = _image_url(variant_image)
            except ValueError as exc:
                raise ValueError(f"Shopify row {index + 2}: invalid variant image URL") from exc
            images[handle].setdefault(variant_image, MAX_ROWS * 2 + index)
        price = row.get(keys["price"], "").strip()
        if price:
            options = [
                row.get(keys.get(f"option{n}", ""), "").strip()
                if mapping is not None else row.get(
                    f"{keys['option']}{n} Value", row.get(f"{keys['option']}{n} value", "")
                ).strip()
                for n in (1, 2, 3)
            ]
            sku = row.get(keys.get("sku", ""), "").strip()
            if len(sku) > 200 or any(len(option) > 200 for option in options):
                raise ValueError(f"Shopify row {index + 2}: variant field exceeds limit")
            identity = (sku, *options)
            if identity in seen_variants[handle]:
                raise ValueError(f"Shopify row {index + 2}: duplicate variant")
            seen_variants[handle].add(identity)
            try:
                qty = _stock(row.get(keys.get("stock", ""), "").strip())
                amount_minor = _amount(price, decimals)
            except ValueError as exc:
                raise ValueError(f"Shopify row {index + 2}: {exc}") from exc
            product["inventory_unknown"] |= qty is None
            product["stock_on_hand"] += qty or 0
            if product["stock_on_hand"] > MAX_STOCK:
                raise ValueError(f"Shopify row {index + 2}: inventory total exceeds limit")
            product["variants"].append(
                {
                    "sku": sku,
                    "options": options,
                    "amount_minor": amount_minor,
                    "stock_on_hand": qty or 0,
                    "inventory_unknown": qty is None,
                    "image": variant_image or None,
                }
            )
        elif row.get(keys.get("sku", ""), "").strip() or row.get(
            keys.get("stock", ""), ""
        ).strip():
            raise ValueError(f"Shopify row {index + 2}: variant has no price")
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
    mapping: dict[str, str] | None = None,
    merchant_id: str | None = None,
) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", source_instance):
        raise ValueError("invalid source instance")
    products = parse_shopify_csv(
        data, currency=currency, image_selection=image_selection,
        mapping=mapping, preview=True,
    )
    selected = json.dumps(
        {handle: sorted(urls) for handle, urls in (image_selection or {}).items()},
        sort_keys=True, separators=(",", ":"),
    ).encode()
    source_hash = hashlib.sha256(
        source_instance.encode() + b"\0" + currency.encode() + b"\0" + data
        + b"\0" + selected + b"\0"
        + json.dumps(mapping or {}, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if merchant_id is not None:
        from .. import crypto

        source_hash = crypto.hmac_index(
            ext_settings().privacy_key, "shopify-source", merchant_id, source_hash
        )
    return {"source_hash": source_hash, "source_instance": source_instance,
            "products": products, "source_completeness": "unknown",
            "cutover_verified": False}


def preview_legacy_import(
    merchant_id: str, data: bytes, *, source_kind: str,
    currency: str, source_instance: str,
) -> dict:
    from .. import crypto

    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", source_instance):
        raise ValueError("invalid source instance")
    normalized = parse_legacy_catalog(data, source_kind=source_kind, currency=currency)
    key = ext_settings().privacy_key
    liabilities = [
        {"invoice_hash": crypto.hmac_index(key, "legacy-invoice", merchant_id,
                                            row["invoice_id"]),
         "order_hash": crypto.hmac_index(key, "legacy-order", merchant_id,
                                          row["order_id"]),
         "product_legacy_id": row["product_legacy_id"], "quantity": row["quantity"],
         "status": "unverified"}
        for row in normalized["liabilities"]
    ]
    source_hash = crypto.hmac_index(
        key, "legacy-source", merchant_id,
        hashlib.sha256(
            source_kind.encode() + b"\0" + source_instance.encode() + b"\0"
            + currency.encode() + b"\0" + data
        ).hexdigest(),
    )
    return {"source_hash": source_hash, "source_instance": source_instance,
            "source_kind": source_kind, "products": normalized["products"],
            "liabilities": liabilities, "source_completeness": "unknown",
            "cutover_verified": False}


async def execute_shopify_import(
    merchant_id: str, user, data: bytes, *, currency: str,
    source_instance: str, expected_hash: str,
    image_selection: dict[str, list[str]] | None = None,
    mapping: dict[str, str] | None = None,
) -> dict:
    return await execute_catalog_import(
        merchant_id, user, data, currency=currency,
        source_instance=source_instance, expected_hash=expected_hash,
        source_kind="shopify", image_selection=image_selection, mapping=mapping,
    )


async def execute_catalog_import(
    merchant_id: str, user, data: bytes, *, currency: str,
    source_instance: str, expected_hash: str, source_kind: str,
    image_selection: dict[str, list[str]] | None = None,
    mapping: dict[str, str] | None = None,
) -> dict:
    await catalog._merchant_owned(merchant_id, user)
    if source_kind == "shopify":
        preview = preview_shopify_import(
            data, currency=currency, source_instance=source_instance,
            image_selection=image_selection, mapping=mapping, merchant_id=merchant_id,
        )
        if any(p.get("image_selection_required") for p in preview["products"]):
            raise ValueError("Shopify product needs explicit image selection")
        liabilities_raw = []
    else:
        if image_selection is not None or mapping is not None:
            raise ValueError("CSV mapping and image selection are only for Shopify")
        preview = preview_legacy_import(
            merchant_id, data, source_kind=source_kind, currency=currency,
            source_instance=source_instance,
        )
        liabilities_raw = parse_legacy_catalog(
            data, source_kind=source_kind, currency=currency
        )["liabilities"]
    if not expected_hash or expected_hash != preview["source_hash"]:
        raise conflict("import-changed", "Import differs from preview")
    products = preview["products"]
    import_id = uuid.uuid4().hex
    now = int(time.time())
    from nostr_sdk import EventBuilder, Kind, PublicKey, Tag

    from .. import crypto

    keystore = MerchantKeyStore(ext_settings())
    pubkey = await keystore.public_key(merchant_id)
    liability_summary = [
        (row["invoice_hash"], row["order_hash"], row["product_legacy_id"],
         row["quantity"])
        for row in preview.get("liabilities", [])
    ]
    catalog_hash = hashlib.sha256(json.dumps(
        sorted(products, key=lambda item: item["handle"]),
        sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    liability_hash = hashlib.sha256(json.dumps(
        sorted(liability_summary), separators=(",", ",")
    ).encode()).hexdigest()
    commitment = {
        "version": 1, "phase": "provisional", "source": source_kind,
        "source_currency": currency,
        "source_hash": expected_hash, "catalog_hash": catalog_hash,
        "liability_hash": liability_hash, "product_count": len(products),
        "liability_count": len(liability_summary),
        "liability_quantity": sum(row[3] for row in liability_summary),
        "source_instance_hash": crypto.hmac_index(
            ext_settings().privacy_key, "source-instance", merchant_id, source_instance
        ),
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
            "WHERE merchant_id = :m AND source_kind = :k "
            "AND source_instance = :s AND source_hash = :h",
            {"m": merchant_id, "k": source_kind,
             "s": source_instance, "h": expected_hash},
        )
        if previous:
            return {"import_id": previous["id"], "product_count": previous["product_count"],
                    "state": "blocked_drafts", "already_imported": True,
                    "commitment_id": previous["commitment_id"]}
        for product in products:
            existing = await tx.fetch_one(
                f"SELECT id FROM {tx.table('products')} "
                "WHERE merchant_id = :m AND import_source_kind = :k "
                "AND import_source_instance = :s AND import_legacy_id = :l",
                {"m": merchant_id, "k": source_kind,
                 "s": source_instance, "l": product["handle"]},
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
            "state, product_count, liability_count, created_at) "
            "VALUES (:i, :m, :k, :s, :h, :c, :j, :e, "
            "'blocked_drafts', :n, :ln, :t)",
            {"i": import_id, "m": merchant_id, "k": source_kind,
             "s": source_instance, "h": expected_hash, "c": currency,
             "j": signed.as_json(), "e": signed.id().to_hex(),
             "n": len(products), "ln": len(liabilities_raw), "t": now},
        )
        product_ids = {}
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
                source_instance, product["handle"], source_kind,
            )
            product_ids[product["handle"]] = parent_id
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
                        source_instance, f"{product['handle']}::{index + 1}", source_kind,
                    )
            normalized = json.dumps(product, sort_keys=True, ensure_ascii=True)
            normalized_hash = hashlib.sha256(normalized.encode()).hexdigest()
            await tx.execute(
                f"INSERT INTO {tx.table('import_rows')} "
                "(id, import_id, product_id, legacy_id, content_hash, normalized_json) "
                "VALUES (:i, :b, :p, :l, :h, :j)",
                {"i": uuid.uuid4().hex, "b": import_id, "p": parent_id,
                 "l": product["handle"], "h": normalized_hash, "j": normalized},
            )
        if liabilities_raw:
            from .. import crypto

            settings = ext_settings()
            for raw, summary in zip(liabilities_raw, preview["liabilities"], strict=True):
                liability_id = uuid.uuid4().hex
                invoice_enc = crypto.encrypt(
                    raw["invoice_id"].encode(),
                    settings.master_keys[settings.active_key_version],
                    record_id=liability_id, table="imported_liabilities",
                    column="invoice_ref_enc", key_version=settings.active_key_version,
                )
                await tx.execute(
                    f"INSERT INTO {tx.table('imported_liabilities')} "
                    "(id, merchant_id, import_id, product_id, invoice_hash, "
                    "order_hash, invoice_ref_enc, quantity, status, created_at) "
                    "VALUES (:i, :m, :b, :p, :h, :o, :e, :q, 'unverified', :t)",
                    {"i": liability_id, "m": merchant_id, "b": import_id,
                     "p": product_ids[raw["product_legacy_id"]],
                     "h": summary["invoice_hash"], "o": summary["order_hash"],
                     "e": invoice_enc, "q": raw["quantity"], "t": now},
                )
    return {"import_id": import_id, "product_count": len(products),
            "state": "blocked_drafts", "already_imported": False,
            "commitment_id": signed.id().to_hex()}


def _bounded_json(data: bytes) -> object:
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("legacy catalog exceeds upload limit")
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate legacy JSON field")
            result[key] = value
        return result

    try:
        value = json.loads(
            data.decode("utf-8-sig"), object_pairs_hook=unique_keys,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("invalid JSON number")),
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid legacy JSON") from exc

    def check(item, depth=0):
        if depth > 6:
            raise ValueError("legacy JSON exceeds nesting limit")
        if isinstance(item, dict):
            if len(item) > MAX_COLUMNS:
                raise ValueError("legacy JSON exceeds field limit")
            for key, child in item.items():
                if not isinstance(key, str) or len(key) > 100:
                    raise ValueError("invalid legacy JSON field")
                if re.search(
                    r"private.?key|api.?key|access.?key|nsec|seed|mnemonic|password|secret|token",
                    key, re.I,
                ):
                    raise ValueError("legacy JSON contains secret fields")
                check(child, depth + 1)
        elif isinstance(item, list):
            if len(item) > MAX_ROWS:
                raise ValueError("legacy JSON exceeds row limit")
            for child in item:
                check(child, depth + 1)
        elif isinstance(item, str) and len(item) > MAX_CELL_LENGTH:
            raise ValueError("legacy JSON string exceeds limit")
        elif isinstance(item, float) and (item != item or abs(item) == float("inf")):
            raise ValueError("invalid JSON number")
    check(value)
    return value


def _legacy_image(value: str) -> str:
    if not isinstance(value, str) or len(value) > 2048 or any(ord(c) < 32 for c in value):
        raise ValueError("invalid legacy image URL")
    try:
        url = urlsplit(value)
        host, port = url.hostname, url.port
    except ValueError as exc:
        raise ValueError("invalid legacy image URL") from exc
    if host:
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError("invalid legacy image URL")
    if (
        url.scheme != "https" or not host or "." not in host
        or host.endswith((".local", ".internal", ".test"))
        or host == "localhost" or url.username or url.password
        or port not in (None, 443)
    ):
        raise ValueError("invalid legacy image URL")
    return value


def _legacy_currency(value: str, selected: str) -> str:
    value = value.upper() if isinstance(value, str) else ""
    if value and value != selected:
        raise ValueError("legacy source currency does not match selection")
    return selected


def parse_legacy_catalog(data: bytes, *, source_kind: str, currency: str) -> dict:
    if source_kind not in ("nostrmarket", "nip15_events"):
        raise ValueError("unsupported legacy format")
    if not re.fullmatch(r"[A-Z]{3}", currency) or currency not in (*currencies, "SAT"):
        raise ValueError("unsupported source currency")
    if source_kind == "nip15_events":
        from nostr_sdk import Event

        if data.lstrip().startswith(b"["):
            entries = _bounded_json(data)
        else:
            lines = data.splitlines()
            if len(lines) > MAX_ROWS:
                raise ValueError("legacy event dump exceeds row limit")
            entries = [_bounded_json(line) for line in lines if line.strip()]
        if not isinstance(entries, list):
            raise ValueError("legacy event dump must be an array or NDJSON")
        stalls, products, author = [], [], None
        for event_index, entry in enumerate(entries, start=1):
            if not isinstance(entry, dict) or entry.get("kind") not in (5, 30017, 30018):
                raise ValueError(f"Legacy event row {event_index}: unsupported kind")
            try:
                signed = Event.from_json(json.dumps(entry))
                if not signed.verify():
                    raise ValueError("invalid legacy event signature")
            except (ValueError, RuntimeError, TypeError, KeyError) as exc:
                raise ValueError(f"Legacy event row {event_index}: invalid signature") from exc
            if entry["kind"] == 5:
                continue
            if author is None:
                author = entry["pubkey"]
            if entry["pubkey"] != author:
                raise ValueError(f"Legacy event row {event_index}: mixed authors")
            d_tags = [t[1] for t in entry.get("tags", []) if isinstance(t, list)
                      and len(t) == 2 and t[0] == "d"]
            if len(d_tags) != 1:
                raise ValueError(f"Legacy event row {event_index}: needs one d tag")
            if not isinstance(entry.get("content"), str):
                raise ValueError(f"Legacy event row {event_index}: invalid content")
            content = _bounded_json(entry["content"].encode())
            if not isinstance(content, dict) or content.get("id") != d_tags[0]:
                raise ValueError(f"Legacy event row {event_index}: identity mismatch")
            (stalls if entry["kind"] == 30017 else products).append(content)
        orders = []
    else:
        source = _bounded_json(data)
        if not isinstance(source, dict) or set(source) - {"stalls", "products", "orders"}:
            raise ValueError("invalid nostrmarket export")
        stalls, products, orders = (source.get(name, []) for name in (
            "stalls", "products", "orders"
        ))
    if not all(isinstance(rows, list) and len(rows) <= MAX_ROWS
               for rows in (stalls, products, orders)) or not products:
        raise ValueError("legacy catalog requires products")
    stall_ids = set()
    for stall_index, stall in enumerate(stalls, start=1):
        if not isinstance(stall, dict) or not isinstance(stall.get("id"), str):
            raise ValueError(f"Legacy stall row {stall_index}: invalid stall")
        stall_id = stall["id"]
        if not stall_id or len(stall_id) > 128 or stall_id in stall_ids:
            raise ValueError(f"Legacy stall row {stall_index}: duplicate or invalid stall")
        stall_ids.add(stall_id)
        try:
            _legacy_currency(stall.get("currency") or "", currency)
        except ValueError as exc:
            raise ValueError(f"Legacy stall row {stall_index}: currency mismatch") from exc
    normalized, ids = [], set()
    for product_index, row in enumerate(products, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"Legacy product row {product_index}: invalid product")
        legacy_id = row.get("id")
        if not isinstance(legacy_id, str) or not legacy_id or len(legacy_id) > 128:
            raise ValueError(f"Legacy product row {product_index}: invalid identity")
        if legacy_id in ids:
            raise ValueError(f"Legacy product row {product_index}: duplicate identity")
        ids.add(legacy_id)
        if row.get("stall_id") not in stall_ids:
            raise ValueError(f"Legacy product row {product_index}: missing stall")
        config = row.get("config") or row.get("meta") or {}
        if isinstance(config, str):
            config = _bounded_json(config.encode())
        if not isinstance(config, dict):
            raise ValueError(f"Legacy product row {product_index}: invalid configuration")
        try:
            _legacy_currency(row.get("currency") or config.get("currency") or "", currency)
        except ValueError as exc:
            raise ValueError(f"Legacy product row {product_index}: currency mismatch") from exc
        title = row.get("name")
        if not isinstance(title, str) or not title or len(title) > 200:
            raise ValueError(f"Legacy product row {product_index}: invalid title")
        image_urls = row.get("images", row.get("image_urls", []))
        if isinstance(image_urls, str):
            image_urls = _bounded_json(image_urls.encode())
        if not isinstance(image_urls, list) or len(image_urls) > MAX_IMAGES:
            raise ValueError(f"Legacy product row {product_index}: image limit exceeded")
        try:
            images = list(dict.fromkeys(_legacy_image(url) for url in image_urls))
        except ValueError as exc:
            raise ValueError(f"Legacy product row {product_index}: invalid image URL") from exc
        active = row.get("active")
        if active is not None and type(active) is not bool:
            raise ValueError(f"Legacy product row {product_index}: invalid source status")
        quantity = row.get("quantity")
        if quantity is not None and (type(quantity) is not int or not 0 <= quantity <= MAX_STOCK):
            raise ValueError(f"Legacy product row {product_index}: invalid inventory quantity")
        price = row.get("price")
        if type(price) not in (int, float, str):
            raise ValueError(f"Legacy product row {product_index}: invalid price")
        try:
            amount_minor = _amount(str(price), default_currency_decimals(currency))
        except ValueError as exc:
            raise ValueError(f"Legacy product row {product_index}: invalid price") from exc
        description = row.get("description") or config.get("description") or ""
        if not isinstance(description, str) or len(description) > MAX_CELL_LENGTH:
            raise ValueError(f"Legacy product row {product_index}: invalid description")
        normalized.append({
            "handle": legacy_id, "title": title, "description_md": _description(description),
            "currency": currency, "currency_decimals": default_currency_decimals(currency),
            "variants": [{"sku": "", "options": [], "amount_minor": amount_minor,
                          "stock_on_hand": quantity or 0, "inventory_unknown": quantity is None,
                          "image": None}],
            "images": images, "stock_on_hand": quantity or 0,
            "inventory_unknown": quantity is None, "source_status": active,
            "draft": True, "visibility": "hidden",
        })
    liabilities, seen_orders, seen_invoices = [], set(), set()
    for order_index, row in enumerate(orders, start=1):
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            raise ValueError(f"Legacy order row {order_index}: invalid order")
        order_id, invoice = row["id"], row.get("invoice_id")
        if (not order_id or len(order_id) > 128 or order_id in seen_orders
                or not isinstance(invoice, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", invoice)):
            raise ValueError(f"Legacy order row {order_index}: invalid order or invoice")
        if invoice.lower() in seen_invoices:
            raise ValueError(f"Legacy order row {order_index}: duplicate legacy invoice")
        seen_invoices.add(invoice.lower())
        seen_orders.add(order_id)
        items = row.get("items", row.get("order_items"))
        if isinstance(items, str):
            items = _bounded_json(items.encode())
        if not isinstance(items, list) or not items or len(items) > MAX_ROWS:
            raise ValueError(f"Legacy order row {order_index}: invalid items")
        item_ids = set()
        for item_index, item in enumerate(items, start=1):
            if not isinstance(item, dict) or item.get("product_id") not in ids:
                raise ValueError(
                    f"Legacy order row {order_index} item {item_index}: unknown product"
                )
            qty = item.get("quantity")
            if type(qty) is not int or not 0 < qty <= MAX_STOCK:
                raise ValueError(
                    f"Legacy order row {order_index} item {item_index}: invalid quantity"
                )
            if item["product_id"] in item_ids or len(liabilities) >= MAX_ROWS:
                raise ValueError(
                    f"Legacy order row {order_index} item {item_index}: duplicate or excessive"
                )
            item_ids.add(item["product_id"])
            liabilities.append({"order_id": order_id, "invoice_id": invoice.lower(),
                                "product_legacy_id": item["product_id"], "quantity": qty})
    return {"products": normalized, "liabilities": liabilities,
            "source_completeness": "unknown"}


async def save_csv_preset(merchant_id: str, user, name: str, mapping: dict) -> dict:
    await catalog._merchant_owned(merchant_id, user)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _-]{0,63}", name):
        raise ValueError("invalid CSV preset name")
    normalized = json.dumps(validate_csv_mapping(mapping), sort_keys=True)
    async with DomainTransaction() as tx:
        await tx.fetch_one(
            f"SELECT id FROM {tx.table('merchants')} WHERE id = :m{tx.for_update}",
            {"m": merchant_id},
        )
        existing = await tx.fetch_one(
            f"SELECT id, mapping_json FROM {tx.table('csv_presets')} "
            "WHERE merchant_id = :m AND name = :n",
            {"m": merchant_id, "n": name},
        )
        if existing:
            if existing["mapping_json"] != normalized:
                raise conflict("preset-conflict", "CSV preset name already exists")
            preset_id = existing["id"]
        else:
            count = await tx.fetch_one(
                f"SELECT COUNT(*) AS n FROM {tx.table('csv_presets')} WHERE merchant_id = :m",
                {"m": merchant_id},
            )
            if count["n"] >= 100:
                raise ValueError("CSV preset limit reached")
            preset_id = uuid.uuid4().hex
            await tx.execute(
                f"INSERT INTO {tx.table('csv_presets')} "
                "(id, merchant_id, name, mapping_json, created_at) "
                "VALUES (:i, :m, :n, :j, :t)",
                {"i": preset_id, "m": merchant_id, "n": name,
                 "j": normalized, "t": int(time.time())},
            )
    return {"id": preset_id, "name": name, "mapping": json.loads(normalized)}


async def list_csv_presets(merchant_id: str, user) -> list[dict]:
    from ..db import db, table

    await catalog._merchant_owned(merchant_id, user)
    async with db.connect() as conn:
        rows = await conn.fetchall(
            f"SELECT id, name, mapping_json FROM {table('csv_presets')} "
            "WHERE merchant_id = :m ORDER BY name LIMIT 100", {"m": merchant_id},
        )
    return [{"id": row["id"], "name": row["name"],
             "mapping": json.loads(row["mapping_json"])} for row in rows]


async def list_imports(merchant_id: str, user) -> list[dict]:
    from ..db import db, table

    await catalog._merchant_owned(merchant_id, user)
    async with db.connect() as conn:
        rows = await conn.fetchall(
            f"SELECT id, source_kind, source_instance, source_hash, "
            "source_currency, state, product_count, liability_count, "
            "commitment_id, created_at "
            f"FROM {table('catalog_imports')} WHERE merchant_id = :m "
            "ORDER BY created_at DESC, id DESC LIMIT 100",
            {"m": merchant_id},
        )
    return [dict(row) for row in rows]


async def audit_import(merchant_id: str, user, import_id: str) -> dict:
    from nostr_sdk import Event

    from ..db import db, table
    from ..security import not_found

    await catalog._merchant_owned(merchant_id, user)
    async with db.connect() as conn:
        record = await conn.fetchone(
            f"SELECT id, source_kind, source_instance, source_hash, "
            "source_currency, state, product_count, liability_count, "
            "commitment_json, commitment_id, created_at "
            f"FROM {table('catalog_imports')} "
            "WHERE id = :i AND merchant_id = :m",
            {"i": import_id, "m": merchant_id},
        )
        if not record:
            raise not_found("import not found")
        rows = await conn.fetchall(
            "SELECT r.legacy_id, r.content_hash, r.product_id, r.normalized_json, "
            "p.merchant_id, p.import_source_kind, p.import_source_instance, "
            "p.import_legacy_id "
            f"FROM {table('import_rows')} r "
            f"JOIN {table('products')} p ON p.id = r.product_id "
            "WHERE r.import_id = :i ORDER BY r.legacy_id LIMIT 5000",
            {"i": import_id},
        )
        liabilities = await conn.fetchall(
            f"SELECT invoice_hash, order_hash, product_id, quantity, status "
            f"FROM {table('imported_liabilities')} WHERE import_id = :i "
            "ORDER BY invoice_hash, product_id LIMIT 5000",
            {"i": import_id},
        )
    try:
        signed = Event.from_json(record["commitment_json"])
        commitment = json.loads(signed.content())
        normalized = [json.loads(row["normalized_json"]) for row in rows]
    except (ValueError, RuntimeError, TypeError) as exc:
        raise conflict("import-signature", "Import commitment could not be verified") from exc
    if not isinstance(commitment, dict) or any(
        not isinstance(item, dict) for item in normalized
    ):
        raise conflict("import-signature", "Import commitment could not be verified")
    current_pubkey = await MerchantKeyStore(ext_settings()).public_key(merchant_id)
    from .. import crypto

    row_identities = {row["product_id"]: row["legacy_id"] for row in rows}
    liability_summary = [
        (row["invoice_hash"], row["order_hash"],
         row_identities.get(row["product_id"]), row["quantity"])
        for row in liabilities
    ]
    if (not signed.verify() or signed.id().to_hex() != record["commitment_id"]
            or signed.author().to_hex() != current_pubkey
            or len(rows) != record["product_count"]
            or len(liabilities) != record["liability_count"]
            or len(row_identities) != len(rows)
            or any(row["merchant_id"] != merchant_id
                   or row["import_source_kind"] != record["source_kind"]
                   or row["import_source_instance"] != record["source_instance"]
                   or row["import_legacy_id"] != row["legacy_id"]
                   or normalized[index].get("handle") != row["legacy_id"]
                   or hashlib.sha256(row["normalized_json"].encode()).hexdigest()
                   != row["content_hash"] for index, row in enumerate(rows))
            or any(item[2] is None for item in liability_summary)
            or commitment.get("version") != 1
            or commitment.get("phase") != "provisional"
            or commitment.get("liability_completeness") != "unknown"
            or commitment.get("source") != record["source_kind"]
            or commitment.get("source_currency") != record["source_currency"]
            or commitment.get("source_hash") != record["source_hash"]
            or commitment.get("source_instance_hash") != crypto.hmac_index(
                ext_settings().privacy_key, "source-instance", merchant_id,
                record["source_instance"])
            or commitment.get("product_count") != len(rows)
            or commitment.get("liability_count") != len(liabilities)
            or commitment.get("liability_quantity") != sum(item[3] for item in liability_summary)
            or commitment.get("catalog_hash") != hashlib.sha256(json.dumps(
                sorted(normalized, key=lambda item: item["handle"]),
                sort_keys=True, separators=(",", ":")
            ).encode()).hexdigest()
            or commitment.get("liability_hash") != hashlib.sha256(json.dumps(
                sorted(liability_summary), separators=(",", ":")
            ).encode()).hexdigest()):
        raise conflict("import-signature", "Import commitment could not be verified")
    return {
        **{key: value for key, value in dict(record).items() if key != "commitment_json"},
        "commitment": json.loads(record["commitment_json"]),
        "rows": [{key: row[key] for key in ("legacy_id", "content_hash", "product_id")}
                 for row in rows],
        "liabilities": [dict(row) for row in liabilities],
        "cutover_verified": False,
    }


def _variant_specs(variant: dict) -> list[dict]:
    specs = []
    if variant["sku"]:
        specs.append({"key": "SKU", "value": variant["sku"]})
    for index, option in enumerate(variant["options"], start=1):
        if option:
            specs.append({"key": f"Option {index}", "value": option})
    return specs
