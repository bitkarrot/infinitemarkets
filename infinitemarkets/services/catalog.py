"""Product and category domain — spec sections 4.2–4.6, 6.7, 15.

Write paths go through ``DomainTransaction`` (raw connection — host
``rewrite_values`` stripping does NOT apply there, preserving markdown/JSON
fidelity; Pitfall 3). Every publishable mutation bumps ``revision`` and
enqueues an outbox intent in the same transaction; drafts and deletes of
never-published aggregates enqueue nothing public.

Deletion is always soft (§6.7): ``deleted_at`` set, detail/reference rows
removed, kind-5 tombstone intent enqueued AFTER republish intents for
survivors (dependency edges express the ordering).
"""

from __future__ import annotations

import json
import re
import time
import uuid
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from ..db import (
    DomainTransaction,
    released_product_clause,
    released_product_select,
)
from ..security import (
    conflict,
    not_found,
    unprocessable,
)
from ..settings import ExtSettings, ext_settings
from .outbox import enqueue_intent

# --- section 15 bounds ----------------------------------------------------------

TITLE_MAX = 200
SUMMARY_MAX = 500
DESC_MAX = 64 * 1024
IMAGES_MAX = 20
CURRENCY_RE = re.compile(r"^[A-Z0-9]{3,8}$")
D_TAG_RE = re.compile(r"^[a-z0-9-]{8,64}$|^[0-9a-f]{8,64}$")
COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
REGION_RE = re.compile(r"^[A-Z]{2}-[A-Z0-9]{1,3}$")

PRODUCT_TYPES = ("simple", "variable", "variation")
FORMATS = ("digital", "physical")
VISIBILITIES = ("hidden", "on-sale", "pre-order")
NIP99_STATUSES = ("active", "sold")
SERVICES = ("standard", "express", "overnight", "pickup")
DURATION_UNITS = ("H", "D", "W")
FREQ_UNITS = ("D", "W", "Y")  # pinned Gamma units (§6.1)

_HTML_TAG_RE = re.compile(r"<[^>]*>")
_BAD_URL_RE = re.compile(r"(?:javascript|data|vbscript)\s*:", re.IGNORECASE)


def _now() -> int:
    return int(time.time())


def _reject_unknown(payload: dict, allowed: set) -> None:
    unknown = set(payload) - allowed
    if unknown:
        raise unprocessable(
            "invalid-content", f"unsupported fields: {sorted(unknown)}"
        )


async def _merchant_id_for(user) -> str:
    """§5.2 routes carry no merchant id — resolve the caller's 1:1 merchant."""
    from . import merchant as merchant_service

    return (await merchant_service.current_merchant(user))["id"]


def sanitize_markdown(text: str | None) -> str | None:
    """Allowlist markdown sanitizer (§15): strip raw HTML tags, reject
    javascript:/data:/vbscript: URLs. Markdown syntax itself is preserved
    byte-for-byte (round-trip fidelity is asserted in tests)."""
    if text is None:
        return None
    if _BAD_URL_RE.search(text):
        raise unprocessable(
            "invalid-content", "Disallowed URL scheme in content"
        )
    return _HTML_TAG_RE.sub("", text)


def _check_title(v: str | None, field: str = "title") -> str | None:
    if v is not None and len(v) > TITLE_MAX:
        raise unprocessable(
            "invalid-content", f"{field} exceeds {TITLE_MAX} chars"
        )
    return v


def _check_summary(v: str | None) -> str | None:
    if v is not None and len(v) > SUMMARY_MAX:
        raise unprocessable(
            "invalid-content", f"summary exceeds {SUMMARY_MAX} chars"
        )
    return v


def _check_description(v: str | None) -> str | None:
    if v is not None:
        if len(v.encode()) > DESC_MAX:
            raise unprocessable(
                "invalid-content", "description exceeds 64KB"
            )
        return sanitize_markdown(v)
    return v


def _check_currency(currency: str | None, decimals: int | None) -> None:
    if currency is not None and (
        not isinstance(currency, str) or not CURRENCY_RE.fullmatch(currency)
    ):
        raise unprocessable(
            "invalid-content", "currency must match ^[A-Z0-9]{3,8}$"
        )
    if decimals is not None and (type(decimals) is not int or not 0 <= decimals <= 18):
        raise unprocessable(
            "invalid-content", "currency_decimals must be 0..18"
        )


def _check_d_tag(d_tag: str) -> str:
    if not D_TAG_RE.match(d_tag):
        raise unprocessable(
            "invalid-content",
            "d_tag must be lowercase hex or [a-z0-9-] slug, 8-64 chars",
        )
    return d_tag


def _gen_d_tag() -> str:
    return uuid.uuid4().hex[:32]


async def _check_d_tag_free(
    tx: DomainTransaction, table_name: str, merchant_id: str, d_tag: str
) -> None:
    row = await tx.fetch_one(
        f"SELECT id FROM {tx.table(table_name)} "
        "WHERE merchant_id = :m AND d_tag = :d",
        {"m": merchant_id, "d": d_tag},
    )
    if row:
        raise conflict(
            "duplicate-resource", "Conflict", "d_tag already in use"
        )


async def _merchant_owned(merchant_id: str, user) -> dict:
    from . import merchant as merchant_service

    return await merchant_service.get_merchant_row(merchant_id, str(user.id))


async def _fetch(table_name: str, id_: str, merchant_id: str) -> dict:
    from ..db import db, table

    async with db.connect() as conn:
        row = await conn.fetchone(
            f"SELECT * FROM {table(table_name)} "
            "WHERE id = :i AND merchant_id = :m",
            {"i": id_, "m": merchant_id},
        )
    if not row:
        raise not_found(f"{table_name[:-1]} not found")
    return dict(row)


async def _fetchall(table_name: str, merchant_id: str,
                    include_deleted: bool = False) -> list[dict]:
    from ..db import db, table

    sql = (
        f"SELECT * FROM {table(table_name)} WHERE merchant_id = :m"
        + ("" if include_deleted else " AND deleted_at IS NULL")
        + " ORDER BY created_at, id"
    )
    async with db.connect() as conn:
        rows = await conn.fetchall(sql, {"m": merchant_id})
    return [dict(r) for r in rows]


# --- outbox helpers --------------------------------------------------------------


async def _product_publishable(tx: DomainTransaction, product_id: str) -> bool:
    row = await tx.fetch_one(
        f"SELECT draft, deleted_at, import_source_kind, "
        f"{released_product_select('products', tx.table)} "
        f"FROM {tx.table('products')} WHERE id = :i",
        {"i": product_id},
    )
    return (
        bool(row)
        and not row["draft"]
        and row["deleted_at"] is None
        and (row["import_source_kind"] is None or row["import_released"])
    )


async def _collection_member_d_tags(
    tx: DomainTransaction, collection_id: str
) -> list[str]:
    rows = await tx.fetch_all(
        f"SELECT p.d_tag FROM {tx.table('product_collections')} pc "
        f"JOIN {tx.table('products')} p ON p.id = pc.product_id "
        "WHERE pc.collection_id = :c AND p.deleted_at IS NULL AND NOT p.draft "
        f"AND {released_product_clause('p', tx.table)}",
        {"c": collection_id},
    )
    return sorted(r["d_tag"] for r in rows)


async def _collections_of_product(
    tx: DomainTransaction, product_id: str
) -> list[str]:
    rows = await tx.fetch_all(
        f"SELECT collection_id AS c FROM {tx.table('product_collections')} "
        "WHERE product_id = :p",
        {"p": product_id},
    )
    return [r["c"] for r in rows]


async def _republish_bulk_collections(
    tx: DomainTransaction,
    merchant_id: str,
    collection_ids: set[str],
    pubkey: str,
    now: int,
) -> list[tuple[str, str]]:
    dependencies = []
    for collection_id in sorted(collection_ids):
        collection = await tx.fetch_one(
            f"SELECT revision, d_tag, deleted_at FROM {tx.table('collections')} "
            "WHERE id = :i AND merchant_id = :m",
            {"i": collection_id, "m": merchant_id},
        )
        if not collection or collection["deleted_at"] is not None:
            continue
        revision = (collection["revision"] or 0) + 1
        await tx.execute(
            f"UPDATE {tx.table('collections')} SET revision = :r,"
            " updated_at = :t WHERE id = :i",
            {"r": revision, "t": now, "i": collection_id},
        )
        intent = await _enqueue_collection(
            tx, merchant_id, collection_id, revision, pubkey
        )
        if intent is None:
            await enqueue_intent(
                tx,
                merchant_id,
                "collections",
                collection_id,
                5,
                revision=revision,
                event_address=f"30405:{pubkey}:{collection['d_tag']}",
            )
        else:
            dependencies.append(("collections", collection_id))
    return dependencies


async def _product_shipping_refs(
    tx: DomainTransaction, product_id: str
) -> list[tuple[str, str]]:
    """(aggregate_type, aggregate_id) deps: shipping options + shipping
    collections referenced by the product."""
    rows = await tx.fetch_all(
        f"SELECT shipping_option_id AS i FROM {tx.table('product_shipping_options')} "
        "WHERE product_id = :p",
        {"p": product_id},
    )
    deps = [("shipping_options", r["i"]) for r in rows]
    rows = await tx.fetch_all(
        f"SELECT collection_id AS i FROM {tx.table('product_shipping_collections')} "
        "WHERE product_id = :p",
        {"p": product_id},
    )
    return deps + [("collections", r["i"]) for r in rows]


async def _enqueue_product(
    tx: DomainTransaction, merchant_id: str, product_id: str,
    revision: int, pubkey: str,
) -> str | None:
    """Enqueue a 30402 intent when publishable; also assigns
    ``published_at`` once (§6 — retries never change it)."""
    row = await tx.fetch_one(
        f"SELECT draft, deleted_at, d_tag, published_at, "
        f"import_source_kind, {released_product_select('products', tx.table)} "
        f"FROM {tx.table('products')} WHERE id = :i",
        {"i": product_id},
    )
    if (
        not row or row["draft"] or row["deleted_at"] is not None
        or (row["import_source_kind"] is not None and not row["import_released"])
    ):
        return None
    if row["published_at"] is None:
        await tx.execute(
            f"UPDATE {tx.table('products')} SET published_at = :t "
            "WHERE id = :i",
            {"t": _now(), "i": product_id},
        )
    deps = []
    for cid in await _collections_of_product(tx, product_id):
        deps.append(("collections", cid))
    deps.extend(await _product_shipping_refs(tx, product_id))
    return await enqueue_intent(
        tx, merchant_id, "products", product_id, 30402,
        revision=revision,
        event_address=f"30402:{pubkey}:{row['d_tag']}",
        depends_on=deps,
    )


async def enqueue_stock_projection(tx: DomainTransaction, product_id: str) -> None:
    row = await tx.fetch_one(
        f"SELECT p.merchant_id, p.revision, m.pubkey FROM {tx.table('products')} p "
        f"JOIN {tx.table('merchants')} m ON m.id = p.merchant_id WHERE p.id = :p",
        {"p": product_id},
    )
    if row:
        await _enqueue_product(
            tx, row["merchant_id"], product_id, row["revision"], row["pubkey"],
        )


async def _enqueue_collection(
    tx: DomainTransaction, merchant_id: str, collection_id: str,
    revision: int, pubkey: str,
) -> str | None:
    """Enqueue a 30405 intent — but a collection with zero active members
    MUST NOT publish (§6.2), so the intent is skipped until membership is
    non-empty."""
    row = await tx.fetch_one(
        f"SELECT d_tag, deleted_at FROM {tx.table('collections')} "
        "WHERE id = :i",
        {"i": collection_id},
    )
    if not row or row["deleted_at"] is not None:
        return None
    members = await _collection_member_d_tags(tx, collection_id)
    if not members:
        return None
    deps = [
        ("shipping_options", r["shipping_option_id"])
        for r in await tx.fetch_all(
            f"SELECT shipping_option_id FROM {tx.table('collection_shipping')} "
            "WHERE collection_id = :c",
            {"c": collection_id},
        )
    ]
    return await enqueue_intent(
        tx, merchant_id, "collections", collection_id, 30405,
        revision=revision,
        event_address=f"30405:{pubkey}:{row['d_tag']}",
        depends_on=deps,
    )


async def _enqueue_shipping(
    tx: DomainTransaction, merchant_id: str, option_id: str,
    revision: int, pubkey: str,
) -> str | None:
    row = await tx.fetch_one(
        f"SELECT d_tag, deleted_at, active FROM {tx.table('shipping_options')} "
        "WHERE id = :i",
        {"i": option_id},
    )
    if not row or row["deleted_at"] is not None or not row["active"]:
        return None
    return await enqueue_intent(
        tx, merchant_id, "shipping_options", option_id, 30406,
        revision=revision,
        event_address=f"30406:{pubkey}:{row['d_tag']}",
    )


async def _enqueue_stall_if_enabled(
    tx: DomainTransaction, merchant_id: str, category_id: str,
    pubkey: str,
) -> None:
    row = await tx.fetch_one(
        f"SELECT publish_nip15, nip15_stall_d FROM {tx.table('categories')} "
        "WHERE id = :i",
        {"i": category_id},
    )
    if row and row["publish_nip15"]:
        await enqueue_intent(
            tx, merchant_id, "categories", category_id, 30017,
            event_address=f"30017:{pubkey}:{row['nip15_stall_d'] or ''}",
        )


# --- categories -------------------------------------------------------------------


_CATEGORY_FIELDS = {
    "name", "description", "default_currency", "default_location",
    "nip15_stall_d", "publish_gamma", "publish_nip15",
}


async def create_category(merchant_id: str, user, payload: dict) -> dict:
    await _merchant_owned(merchant_id, user)
    _reject_unknown(payload, _CATEGORY_FIELDS)
    name = _check_title(payload.get("name"), "name")
    description = _check_description(payload.get("description"))
    currency = payload.get("default_currency")
    if currency is not None and not CURRENCY_RE.match(currency):
        raise unprocessable("invalid-content", "invalid default_currency")
    category_id = uuid.uuid4().hex
    stall_d = payload.get("nip15_stall_d") or _gen_d_tag()
    now = _now()
    async with DomainTransaction() as tx:
        await tx.execute(
            f"INSERT INTO {tx.table('categories')} "
            "(id, merchant_id, name, description, default_currency,"
            " default_location, nip15_stall_d, publish_gamma, publish_nip15,"
            " public_slug, created_at, updated_at) "
            "VALUES (:i, :m, :n, :d, :c, :l, :sd, :pg, :pn, :slug, :t, :t)",
            {
                "slug": uuid.uuid4().hex,
                "i": category_id,
                "m": merchant_id,
                "n": name,
                "d": description,
                "c": currency,
                "l": payload.get("default_location"),
                "sd": stall_d,
                "pg": bool(payload.get("publish_gamma", True)),
                "pn": bool(payload.get("publish_nip15", False)),
                "t": now,
            },
        )
    return await get_category(merchant_id, user, category_id)


async def list_categories(merchant_id: str, user) -> list[dict]:
    await _merchant_owned(merchant_id, user)
    return await _fetchall("categories", merchant_id)


async def get_category(merchant_id: str, user, category_id: str) -> dict:
    await _merchant_owned(merchant_id, user)
    row = await _fetch("categories", category_id, merchant_id)
    if row["deleted_at"] is not None:
        raise not_found("category not found")
    return row


async def patch_category(merchant_id: str, user, category_id: str,
                        patch: dict) -> dict:
    merchant = await _merchant_owned(merchant_id, user)
    row = await _fetch("categories", category_id, merchant_id)
    if row["deleted_at"] is not None:
        raise not_found("category not found")
    allowed = {
        "name", "description", "default_currency", "default_location",
        "publish_gamma", "publish_nip15",
    }
    unknown = set(patch) - allowed
    if unknown:
        raise unprocessable(
            "invalid-content", f"unsupported fields: {sorted(unknown)}"
        )
    updates: dict = {}
    if "name" in patch:
        updates["name"] = _check_title(patch["name"], "name")
    if "description" in patch:
        updates["description"] = _check_description(patch["description"])
    if "default_currency" in patch:
        c = patch["default_currency"]
        if c is not None and not CURRENCY_RE.match(c):
            raise unprocessable(
                "invalid-content", "invalid default_currency"
            )
        updates["default_currency"] = c
    if "default_location" in patch:
        updates["default_location"] = patch["default_location"]
    for flag in ("publish_gamma", "publish_nip15"):
        if flag in patch:
            updates[flag] = bool(patch[flag])
    async with DomainTransaction() as tx:
        for col, val in updates.items():
            await tx.execute(
                f"UPDATE {tx.table('categories')} SET {col} = :v,"
                " updated_at = :t WHERE id = :i",
                {"v": val, "t": _now(), "i": category_id},
            )
        if updates:
            await _enqueue_stall_if_enabled(
                tx, merchant_id, category_id, merchant["pubkey"]
            )
    return await get_category(merchant_id, user, category_id)


async def delete_category(merchant_id: str, user, category_id: str) -> dict:
    """Soft delete — the category row is retained. Refused while live
    products still sit in it (they would be orphaned) and for the shop's
    last remaining category (new products need somewhere to live)."""
    await _merchant_owned(merchant_id, user)
    row = await _fetch("categories", category_id, merchant_id)
    if row["deleted_at"] is not None:
        raise not_found("category not found")
    async with DomainTransaction() as tx:
        live = await tx.fetch_one(
            f"SELECT COUNT(*) AS n FROM {tx.table('products')} "
            "WHERE category_id = :i AND deleted_at IS NULL",
            {"i": category_id},
        )
        if live["n"]:
            raise conflict(
                "category-not-empty",
                "Category still has products",
                f"{live['n']} product(s) — move or delete them first",
            )
        others = await tx.fetch_one(
            f"SELECT COUNT(*) AS n FROM {tx.table('categories')} "
            "WHERE merchant_id = :m AND id != :i AND deleted_at IS NULL",
            {"m": merchant_id, "i": category_id},
        )
        if not others["n"]:
            raise conflict(
                "last-category",
                "Cannot delete the last category",
                "create another category first",
            )
        await tx.execute(
            f"UPDATE {tx.table('categories')} SET deleted_at = :t,"
            " updated_at = :t WHERE id = :i",
            {"t": _now(), "i": category_id},
        )
    return {"deleted": True, "id": category_id}


# --- products --------------------------------------------------------------------


def _validate_product_payload(p: dict, partial: bool = False) -> None:
    if not partial or "title" in p:
        _check_title(p.get("title"))
    if not partial or "summary" in p:
        _check_summary(p.get("summary"))
    if not partial or "description_md" in p:
        _check_description(p.get("description_md"))
    if not partial or "currency" in p or "currency_decimals" in p:
        _check_currency(p.get("currency"), p.get("currency_decimals"))
    if "product_type" in p and p["product_type"] not in PRODUCT_TYPES:
        raise unprocessable(
            "invalid-content", f"product_type must be one of {PRODUCT_TYPES}"
        )
    if "format" in p and p["format"] not in FORMATS:
        raise unprocessable(
            "invalid-content", f"format must be one of {FORMATS}"
        )
    if "visibility" in p and p["visibility"] not in VISIBILITIES:
        raise unprocessable(
            "invalid-content", f"visibility must be one of {VISIBILITIES}"
        )
    if "nip99_status" in p and p["nip99_status"] not in NIP99_STATUSES:
        raise unprocessable(
            "invalid-content", "nip99_status must be active|sold"
        )
    if "recurring_frequency" in p and p["recurring_frequency"] is not None:
        if p["recurring_frequency"] not in FREQ_UNITS:
            raise unprocessable(
                "invalid-content", "recurring_frequency must be D|W|Y"
            )
    for field in ("amount_minor", "stock_on_hand", "stock_reserved"):
        value = p.get(field)
        if value is not None and (type(value) is not int or not 0 <= value < 2**63):
            raise unprocessable("invalid-content", f"{field} must be a nonnegative int64")
    if "stock_reserved" in p and (
        partial or type(p["stock_reserved"]) is not int or p["stock_reserved"] != 0
    ):
        raise unprocessable("invalid-content", "stock_reserved is maintained by reservations")
    if (
        p.get("stock_on_hand") is not None
        and p.get("stock_reserved") is not None
        and p["stock_reserved"] > p["stock_on_hand"]
    ):
        raise unprocessable(
            "invalid-content",
            "stock_reserved cannot exceed stock_on_hand",
        )
    if "amount_minor" in p and p["amount_minor"] is not None:
        if p["amount_minor"] < 0:
            raise unprocessable(
                "invalid-content", "amount_minor must be >= 0"
            )
    images = p.get("images")
    if images is not None:
        if not isinstance(images, list) or len(images) > IMAGES_MAX:
            raise unprocessable(
                "invalid-content", f"at most {IMAGES_MAX} images"
            )
        for img in images:
            url = img.get("url") if isinstance(img, dict) else img
            if not isinstance(url, str) or not url.startswith("https://"):
                raise unprocessable(
                    "invalid-content", "image URLs must be https://"
                )


async def _validate_variation(
    tx: DomainTransaction, merchant_id: str, product_type: str,
    parent_id: str | None,
) -> str | None:
    """Variation rules (§4.3/§6.1): exactly one parent, parent must be
    ``variable``, parent must not itself be a variation (depth = 1)."""
    if product_type != "variation":
        return None
    if not parent_id:
        raise unprocessable(
            "invalid-content", "variation requires parent_product_id"
        )
    parent = await tx.fetch_one(
        f"SELECT product_type, deleted_at FROM {tx.table('products')} "
        "WHERE id = :i AND merchant_id = :m",
        {"i": parent_id, "m": merchant_id},
    )
    if not parent or parent["deleted_at"] is not None:
        raise unprocessable("invalid-content", "parent product not found")
    if parent["product_type"] != "variable":
        raise unprocessable(
            "invalid-content",
            "variation parent must be a variable product",
        )
    return parent_id


_PRODUCT_FIELDS = (
    "title", "summary", "description_md", "amount_minor", "currency",
    "currency_decimals", "recurring_frequency", "visibility",
    "nip99_status", "draft", "stock_on_hand", "stock_reserved",
    "location", "geohash",
    "weight_value", "weight_unit", "dim_l", "dim_w", "dim_h", "dim_unit",
    "nip15_product_id",
)


def _sanitize_product_fields(patch: dict) -> dict:
    out = {}
    for f in _PRODUCT_FIELDS:
        if f in patch:
            v = patch[f]
            if f == "description_md":
                v = _check_description(v)
            elif f == "title":
                v = _check_title(v)
            elif f == "summary":
                v = _check_summary(v)
            elif f == "draft":
                v = bool(v)
            out[f] = v
    return out


async def _replace_product_details(
    tx: DomainTransaction, product_id: str, patch: dict,
    merchant_id: str,
) -> None:
    """Replace detail-table sets when the corresponding key is present."""
    if "images" in patch:
        await tx.execute(
            f"DELETE FROM {tx.table('product_images')} WHERE product_id = :p",
            {"p": product_id},
        )
        for i, img in enumerate(patch["images"] or []):
            url = img.get("url") if isinstance(img, dict) else img
            await tx.execute(
                f"INSERT INTO {tx.table('product_images')} "
                "(id, product_id, url, dimensions, sort_order) "
                "VALUES (:i, :p, :u, :d, :s)",
                {
                    "i": uuid.uuid4().hex,
                    "p": product_id,
                    "u": url,
                    "d": img.get("dimensions") if isinstance(img, dict) else None,
                    "s": img.get("sort_order", i) if isinstance(img, dict) else i,
                },
            )
    if "specs" in patch:
        await tx.execute(
            f"DELETE FROM {tx.table('product_specs')} WHERE product_id = :p",
            {"p": product_id},
        )
        for spec in patch["specs"] or []:
            await tx.execute(
                f"INSERT INTO {tx.table('product_specs')} "
                "(id, product_id, key, value) VALUES (:i, :p, :k, :v)",
                {
                    "i": uuid.uuid4().hex,
                    "p": product_id,
                    "k": spec["key"],
                    "v": spec["value"],
                },
            )
    if "categories" in patch:
        await tx.execute(
            f"DELETE FROM {tx.table('product_categories')} "
            "WHERE product_id = :p",
            {"p": product_id},
        )
        for cat in patch["categories"] or []:
            await tx.execute(
                f"INSERT INTO {tx.table('product_categories')} "
                "(id, product_id, category) VALUES (:i, :p, :c)",
                {"i": uuid.uuid4().hex, "p": product_id, "c": cat},
            )
    if "collection_ids" in patch:
        # membership — draft products may not join collections (§6.7)
        prod = await tx.fetch_one(
            f"SELECT draft FROM {tx.table('products')} WHERE id = :i",
            {"i": product_id},
        )
        wanted = list(dict.fromkeys(patch["collection_ids"] or []))
        if wanted and prod and prod["draft"]:
            raise unprocessable(
                "invalid-content", "draft products cannot join collections"
            )
        for cid in wanted:
            col = await tx.fetch_one(
                f"SELECT id, deleted_at FROM {tx.table('collections')} "
                "WHERE id = :i AND merchant_id = :m",
                {"i": cid, "m": merchant_id},
            )
            if not col or col["deleted_at"] is not None:
                raise unprocessable(
                    "invalid-content", f"collection {cid} not found"
                )
        await tx.execute(
            f"DELETE FROM {tx.table('product_collections')} "
            "WHERE product_id = :p",
            {"p": product_id},
        )
        for cid in wanted:
            await tx.execute(
                f"INSERT INTO {tx.table('product_collections')} "
                "(id, product_id, collection_id) VALUES (:i, :p, :c)",
                {"i": uuid.uuid4().hex, "p": product_id, "c": cid},
            )
    for key, tbl, fk in (
        ("shipping_option_ids", "product_shipping_options",
         "shipping_option_id"),
        ("shipping_collection_ids", "product_shipping_collections",
         "collection_id"),
    ):
        if key not in patch:
            continue
        pairs = patch[key] or []  # list of ids or {id, extra_cost_minor}
        await tx.execute(
            f"DELETE FROM {tx.table(tbl)} WHERE product_id = :p",
            {"p": product_id},
        )
        for entry in pairs:
            if isinstance(entry, dict):
                ref_id, extra = entry["id"], entry.get("extra_cost_minor")
            else:
                ref_id, extra = entry, None
            await tx.execute(
                f"INSERT INTO {tx.table(tbl)} "
                f"(id, product_id, {fk}, extra_cost_minor) "
                "VALUES (:i, :p, :r, :e)",
                {
                    "i": uuid.uuid4().hex,
                    "p": product_id,
                    "r": ref_id,
                    "e": extra,
                },
            )


_PRODUCT_PAYLOAD_FIELDS = set(_PRODUCT_FIELDS) | {
    "category_id", "d_tag", "product_type", "format", "parent_product_id",
    "stock_reserved", "images", "specs", "categories", "collection_ids",
    "shipping_option_ids", "shipping_collection_ids", "delivery_content",
}

DELIVERY_MAX = 4000


def _delivery_enc(product_id: str, fmt: str, value) -> bytes | None:
    """Encrypt merchant digital-delivery content (never published, never
    in public JSON; revealed to the buyer only after confirmed payment)."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if not isinstance(value, str) or len(value) > DELIVERY_MAX:
        raise unprocessable(
            "invalid-content",
            f"delivery_content must be text of at most {DELIVERY_MAX} characters",
        )
    if fmt != "digital":
        raise unprocessable(
            "invalid-content", "delivery_content is only for digital products",
        )
    settings = ext_settings()
    from .. import crypto

    return crypto.encrypt(
        value.strip().encode(), settings.master_keys[settings.active_key_version],
        record_id=product_id, table="products", column="delivery_enc",
        key_version=settings.active_key_version,
    )


def decrypt_delivery(product_id: str, blob) -> str | None:
    if blob is None:
        return None
    from .. import crypto

    settings = ext_settings()
    ver = crypto.envelope_version(blob)
    return crypto.decrypt(
        blob, settings.master_keys[ver], record_id=product_id,
        table="products", column="delivery_enc", key_version=ver,
    ).decode()


def _product_out(row: dict) -> dict:
    """Owner-scoped admin projection: the ciphertext never leaves the
    service; the merchant sees their own delivery content in plain text."""
    blob = row.pop("delivery_enc", None)
    row["delivery_content"] = decrypt_delivery(row["id"], blob)
    return row


async def create_import_draft(
    tx: DomainTransaction, merchant_id: str, category_id: str,
    payload: dict, source_instance: str, legacy_id: str,
    source_kind: str = "shopify",
) -> str:
    if source_kind not in ("shopify", "nostrmarket", "nip15_events",
                           "infinitemarkets"):
        raise unprocessable("invalid-content", "unsupported import source")
    _reject_unknown(payload, _PRODUCT_PAYLOAD_FIELDS)
    _validate_product_payload(payload)
    if payload.get("draft") is not True or payload.get("visibility") != "hidden":
        raise unprocessable("import-blocked", "import products must be hidden drafts")
    product_type = payload.get("product_type", "simple")
    parent_id = await _validate_variation(
        tx, merchant_id, product_type, payload.get("parent_product_id")
    )
    fields = _sanitize_product_fields(payload)
    if fields.get("currency_decimals") is None:
        from .fx import default_currency_decimals

        fields["currency_decimals"] = default_currency_decimals(fields.get("currency"))
    product_id = uuid.uuid4().hex
    now = _now()
    columns = [
        "id", "merchant_id", "category_id", "d_tag", "product_type", "format",
        "parent_product_id", "import_source_kind", "import_source_instance",
        "import_legacy_id", "revision", "created_at", "updated_at",
    ]
    values = [
        product_id, merchant_id, category_id, _gen_d_tag(), product_type, "physical",
        parent_id, source_kind, source_instance, legacy_id, 0, now, now,
    ]
    for field, value in fields.items():
        columns.append(field)
        values.append(value)
    placeholders = ", ".join(f":p{i}" for i in range(len(values)))
    await tx.execute(
        f"INSERT INTO {tx.table('products')} ({', '.join(columns)}) "
        f"VALUES ({placeholders})",
        {f"p{i}": value for i, value in enumerate(values)},
    )
    await _replace_product_details(tx, product_id, payload, merchant_id)
    return product_id


async def create_product(merchant_id: str, user, payload: dict) -> dict:
    merchant = await _merchant_owned(merchant_id, user)
    _reject_unknown(payload, _PRODUCT_PAYLOAD_FIELDS)
    _validate_product_payload(payload)
    product_type = payload.get("product_type", "simple")
    fmt = payload.get("format", "physical")
    if not payload.get("category_id"):
        raise unprocessable("invalid-content", "category_id is required")
    category = await _fetch("categories", payload["category_id"], merchant_id)
    if category["deleted_at"] is not None:
        raise not_found("category not found")
    d_tag = payload.get("d_tag") or _gen_d_tag()
    _check_d_tag(d_tag)

    product_id = uuid.uuid4().hex
    now = _now()
    async with DomainTransaction() as tx:
        await _check_d_tag_free(tx, "products", merchant_id, d_tag)
        parent_id = await _validate_variation(
            tx, merchant_id, product_type, payload.get("parent_product_id")
        )
        fields = _sanitize_product_fields(payload)
        if fields.get("currency_decimals") is None:
            from .fx import default_currency_decimals

            fields["currency_decimals"] = default_currency_decimals(fields.get("currency"))
        cols = ["id", "merchant_id", "category_id", "d_tag", "product_type",
                "format", "revision", "created_at", "updated_at"]
        vals = [product_id, merchant_id, payload["category_id"], d_tag,
                product_type, fmt, 0, now, now]
        if parent_id:
            cols.append("parent_product_id")
            vals.append(parent_id)
        for f, v in fields.items():
            cols.append(f)
            vals.append(v)
        placeholders = ", ".join(f":p{i}" for i in range(len(cols)))
        await tx.execute(
            f"INSERT INTO {tx.table('products')} "
            f"({', '.join(cols)}) VALUES ({placeholders})",
            {f"p{i}": v for i, v in enumerate(vals)},
        )
        delivery = _delivery_enc(product_id, fmt, payload.get("delivery_content"))
        if delivery is not None:
            await tx.execute(
                f"UPDATE {tx.table('products')} SET delivery_enc = :d WHERE id = :i",
                {"d": delivery, "i": product_id},
            )
        await _replace_product_details(tx, product_id, payload, merchant_id)
        # membership changes republish affected collections FIRST (§8.6
        # ordering) so the product intent's dependency edges bind to them
        for cid in await _collections_of_product(tx, product_id):
            col = await tx.fetch_one(
                f"SELECT revision FROM {tx.table('collections')} WHERE id = :i",
                {"i": cid},
            )
            await tx.execute(
                f"UPDATE {tx.table('collections')} SET revision = :r,"
                " updated_at = :t WHERE id = :i",
                {"r": (col["revision"] or 0) + 1, "t": now, "i": cid},
            )
            await _enqueue_collection(
                tx, merchant_id, cid, (col["revision"] or 0) + 1,
                merchant["pubkey"],
            )
        await _enqueue_product(
            tx, merchant_id, product_id, 0, merchant["pubkey"]
        )
        await _enqueue_stall_if_enabled(
            tx, merchant_id, payload["category_id"], merchant["pubkey"]
        )
    return await get_product(merchant_id, user, product_id)


async def recategorize_import_draft(
    merchant_id: str, user, product_id: str, category_id: str,
) -> dict:
    await _merchant_owned(merchant_id, user)
    async with DomainTransaction() as tx:
        product = await tx.fetch_one(
            f"SELECT id, draft, stock_reserved, import_source_kind, product_type "
            f"FROM {tx.table('products')} WHERE id = :i AND merchant_id = :m "
            f"AND deleted_at IS NULL{tx.for_update}",
            {"i": product_id, "m": merchant_id},
        )
        if not product:
            raise not_found("product not found")
        if (
            not product["import_source_kind"] or not product["draft"]
            or product["stock_reserved"] or product["product_type"] == "variation"
        ):
            raise conflict("import-blocked", "Only unreserved imported drafts can move")
        children = await tx.fetch_all(
            f"SELECT id, draft, stock_reserved FROM {tx.table('products')} "
            "WHERE parent_product_id = :i AND merchant_id = :m "
            f"AND deleted_at IS NULL{tx.for_update}",
            {"i": product_id, "m": merchant_id},
        )
        if any(not child["draft"] or child["stock_reserved"] for child in children):
            raise conflict("import-blocked", "Imported variants must remain unreserved drafts")
        category = await tx.fetch_one(
            f"SELECT id, import_review FROM {tx.table('categories')} "
            "WHERE id = :c AND merchant_id = :m AND deleted_at IS NULL",
            {"c": category_id, "m": merchant_id},
        )
        if not category or category["import_review"]:
            raise unprocessable("invalid-content", "Choose a live merchant category")
        for target_id in [product_id, *(child["id"] for child in children)]:
            await tx.execute(
                f"UPDATE {tx.table('products')} SET category_id = :c, "
                "revision = revision + 1, updated_at = :t WHERE id = :i",
                {"c": category_id, "t": _now(), "i": target_id},
            )
    return await get_product(merchant_id, user, product_id)


async def list_products(merchant_id: str, user,
                        category_id: str | None = None) -> list[dict]:
    await _merchant_owned(merchant_id, user)
    from ..db import db, table

    sql = (
        f"SELECT * FROM {table('products')} WHERE merchant_id = :m"
        " AND deleted_at IS NULL"
    )
    params: dict = {"m": merchant_id}
    if category_id:
        sql += " AND category_id = :c"
        params["c"] = category_id
    sql += " ORDER BY created_at, id"
    async with db.connect() as conn:
        rows = await conn.fetchall(sql, params)
    return [_product_out(dict(r)) for r in rows]


async def get_product(merchant_id: str, user, product_id: str) -> dict:
    await _merchant_owned(merchant_id, user)
    row = _product_out(await _fetch("products", product_id, merchant_id))
    if row["deleted_at"] is not None:
        raise not_found("product not found")
    row["images"] = await _detail_list(
        "product_images", product_id, "sort_order"
    )
    row["specs"] = await _detail_list("product_specs", product_id)
    row["categories"] = [
        r["category"]
        for r in await _detail_list("product_categories", product_id)
    ]
    row["collection_ids"] = [
        r["collection_id"]
        for r in await _detail_list("product_collections", product_id)
    ]
    row["shipping_options"] = await _detail_list(
        "product_shipping_options", product_id
    )
    row["shipping_collections"] = await _detail_list(
        "product_shipping_collections", product_id
    )
    return row


async def _detail_list(table_name: str, product_id: str,
                       order: str = "id") -> list[dict]:
    from ..db import db, table

    async with db.connect() as conn:
        rows = await conn.fetchall(
            f"SELECT * FROM {table(table_name)} WHERE product_id = :p "
            f"ORDER BY {order}",
            {"p": product_id},
        )
    return [dict(r) for r in rows]


async def _publish_import_variants(
    tx: DomainTransaction, merchant_id: str, parent_id: str,
    pubkey: str, visibility: str, now: int,
) -> None:
    children = await tx.fetch_all(
        f"SELECT id, revision FROM {tx.table('products')} "
        "WHERE parent_product_id = :p AND merchant_id = :m "
        f"AND import_source_kind IS NOT NULL AND draft AND deleted_at IS NULL{tx.for_update}",
        {"p": parent_id, "m": merchant_id},
    )
    for child in children:
        await tx.execute(
            f"UPDATE {tx.table('products')} SET draft = FALSE, "
            "visibility = :v, revision = revision + 1, updated_at = :t "
            "WHERE id = :i",
            {"i": child["id"], "v": visibility, "t": now},
        )
        await _enqueue_product(
            tx, merchant_id, child["id"], child["revision"] + 1, pubkey
        )


async def patch_product(merchant_id: str, user, product_id: str,
                        patch: dict) -> dict:
    merchant = await _merchant_owned(merchant_id, user)
    row = await _fetch("products", product_id, merchant_id)
    if row["deleted_at"] is not None:
        raise not_found("product not found")
    _reject_unknown(patch, _PRODUCT_PAYLOAD_FIELDS)
    _validate_product_payload(patch, partial=True)
    fields = _sanitize_product_fields(patch)
    if (
        "currency" in fields and fields["currency"] != row["currency"]
        and "currency_decimals" not in fields
    ) or ("currency_decimals" in fields and fields["currency_decimals"] is None):
        from .fx import default_currency_decimals

        fields["currency_decimals"] = default_currency_decimals(
            fields.get("currency", row["currency"]),
        )
    new_type = patch.get("product_type", row["product_type"])
    parent_id = patch.get("parent_product_id", row["parent_product_id"])
    if parent_id == product_id:
        raise unprocessable(
            "invalid-content", "a product cannot be its own parent"
        )

    now = _now()
    async with DomainTransaction() as tx:
        await tx.fetch_one(
            f"SELECT id FROM {tx.table('products')} "
            f"WHERE id = :i AND merchant_id = :m{tx.for_update}",
            {"i": product_id, "m": merchant_id},
        )
        if "product_type" in patch or "parent_product_id" in patch:
            # re-validate the resulting combination
            parent_id = await _validate_variation(
                tx, merchant_id, new_type, parent_id
            )
            fields["product_type"] = new_type
            fields["parent_product_id"] = parent_id
            if new_type != "variation":
                # a variable/simple product must not be referenced as a
                # variation's parent check happens on children — but a
                # product_type change away from 'variable' with existing
                # children is a dangling-parent defect
                children = await tx.fetch_all(
                    f"SELECT id FROM {tx.table('products')} "
                    "WHERE parent_product_id = :i AND deleted_at IS NULL",
                    {"i": product_id},
                )
                if children:
                    raise conflict(
                        "invalid-transition",
                        "Product has variations",
                        "cannot change type while variations reference it",
                    )
        # stock auto-status: available reaching 0 -> sold (§6.1)
        if "stock_on_hand" in fields or "stock_reserved" in fields:
            on_hand = fields.get("stock_on_hand", row["stock_on_hand"])
            reserved = fields.get(
                "stock_reserved", row["stock_reserved"]
            )
            if (
                on_hand is not None
                and reserved is not None
                and reserved > on_hand
            ):
                raise unprocessable(
                    "invalid-content",
                    "stock_reserved cannot exceed stock_on_hand",
                )
            if on_hand is not None:
                available = on_hand - (reserved or 0)
                if "nip99_status" not in fields:
                    fields["nip99_status"] = (
                        "sold" if available <= 0 else "active"
                    )
        for col, val in fields.items():
            await tx.execute(
                f"UPDATE {tx.table('products')} SET {col} = :v WHERE id = :i",
                {"v": val, "i": product_id},
            )
        if "delivery_content" in patch:
            await tx.execute(
                f"UPDATE {tx.table('products')} SET delivery_enc = :d WHERE id = :i",
                {
                    "d": _delivery_enc(product_id, row["format"], patch["delivery_content"]),
                    "i": product_id,
                },
            )
        await tx.execute(
            f"UPDATE {tx.table('products')} SET revision = revision + 1,"
            " updated_at = :t WHERE id = :i",
            {"t": now, "i": product_id},
        )
        await _replace_product_details(tx, product_id, patch, merchant_id)
        new_revision = (row["revision"] or 0) + 1
        # collections republish first so product deps bind to live intents
        for cid in await _collections_of_product(tx, product_id):
            col = await tx.fetch_one(
                f"SELECT revision FROM {tx.table('collections')} WHERE id = :i",
                {"i": cid},
            )
            nr = (col["revision"] or 0) + 1
            await tx.execute(
                f"UPDATE {tx.table('collections')} SET revision = :r,"
                " updated_at = :t WHERE id = :i",
                {"r": nr, "t": now, "i": cid},
            )
            await _enqueue_collection(
                tx, merchant_id, cid, nr, merchant["pubkey"]
            )
        await _enqueue_product(
            tx, merchant_id, product_id, new_revision, merchant["pubkey"]
        )
        if (row["product_type"] == "variable" and row["import_source_kind"]
                and not fields.get("draft", row["draft"])
                and fields.get("visibility", row["visibility"]) != "hidden"):
            await _publish_import_variants(
                tx, merchant_id, product_id, merchant["pubkey"],
                fields.get("visibility", row["visibility"]), now,
            )
    return await get_product(merchant_id, user, product_id)


async def bulk_products(
    merchant_id: str,
    user,
    product_ids: list[str],
    action: str,
    value=None,
) -> dict:
    merchant = await _merchant_owned(merchant_id, user)
    ids = list(dict.fromkeys(product_ids))
    if not 1 <= len(ids) <= 100 or any(
        not isinstance(product_id, str)
        or not re.fullmatch(r"[0-9a-f]{32}", product_id)
        for product_id in ids
    ):
        raise unprocessable(
            "invalid-content", "product_ids must contain 1 to 100 product IDs"
        )
    if action not in {
        "price-markup", "move-collection", "visibility", "draft", "publish", "delete"
    }:
        raise unprocessable("invalid-content", "unsupported bulk action")

    percentage = None
    if action == "price-markup":
        try:
            percentage = Decimal(str(value))
        except (InvalidOperation, ValueError):
            raise unprocessable(
                "invalid-content", "price markup must be a number"
            ) from None
        if not percentage.is_finite() or not 0 < percentage <= 10000:
            raise unprocessable(
                "invalid-content", "price markup must be greater than 0 and at most 10000"
            )
    elif action == "visibility" and value not in VISIBILITIES:
        raise unprocessable(
            "invalid-content", f"visibility must be one of {VISIBILITIES}"
        )
    elif action == "move-collection" and (
        not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{32}", value)
    ):
        raise unprocessable("invalid-content", "collection is required")

    now = _now()
    async with DomainTransaction() as tx:
        placeholders = ", ".join(f":p{i}" for i in range(len(ids)))
        params = {f"p{i}": product_id for i, product_id in enumerate(ids)}
        params["m"] = merchant_id
        rows = await tx.fetch_all(
            f"SELECT *, {released_product_select('products', tx.table)} "
            f"FROM {tx.table('products')} WHERE merchant_id = :m "
            f"AND deleted_at IS NULL AND id IN ({placeholders})"
            f"{tx.for_update}",
            params,
        )
        by_id = {row["id"]: row for row in rows}
        if len(by_id) != len(ids):
            raise not_found("one or more products not found")
        if action == "delete":
            for product_id in ids:
                await _delete_product_locked(
                    tx, merchant_id, product_id, merchant["pubkey"]
                )
            return {"deleted": len(ids), "product_ids": ids}

        collection_ids: set[str] = set()
        for product_id in ids:
            collection_ids.update(
                await _collections_of_product(tx, product_id)
            )

        if action == "move-collection":
            target = await tx.fetch_one(
                f"SELECT id, deleted_at FROM {tx.table('collections')} "
                "WHERE id = :i AND merchant_id = :m",
                {"i": value, "m": merchant_id},
            )
            if not target or target["deleted_at"] is not None:
                raise not_found("collection not found")
            if any(bool(by_id[product_id]["draft"]) for product_id in ids):
                raise unprocessable(
                    "invalid-content",
                    "draft products cannot be moved to a collection",
                )
            collection_ids.add(value)

        for product_id in ids:
            row = by_id[product_id]
            assignments = ["revision = revision + 1", "updated_at = :t"]
            update_params = {"i": product_id, "t": now}
            if action == "price-markup":
                amount = (
                    Decimal(row["amount_minor"] or 0)
                    * (Decimal(100) + percentage)
                    / Decimal(100)
                ).quantize(Decimal(1), rounding=ROUND_HALF_UP)
                if amount >= 2**63:
                    raise unprocessable(
                        "invalid-content", "price markup exceeds the int64 limit"
                    )
                assignments.append("amount_minor = :v")
                update_params["v"] = int(amount)
            elif action == "visibility":
                assignments.append("visibility = :v")
                update_params["v"] = value
            elif action in {"draft", "publish"}:
                assignments.append("draft = :v")
                update_params["v"] = action == "draft"
            elif action == "move-collection":
                await tx.execute(
                    f"DELETE FROM {tx.table('product_collections')} "
                    "WHERE product_id = :p",
                    {"p": product_id},
                )
                await tx.execute(
                    f"INSERT INTO {tx.table('product_collections')} "
                    "(id, product_id, collection_id) VALUES (:i, :p, :c)",
                    {"i": uuid.uuid4().hex, "p": product_id, "c": value},
                )
            if action == "draft":
                await tx.execute(
                    f"DELETE FROM {tx.table('product_collections')} "
                    "WHERE product_id = :p",
                    {"p": product_id},
                )
            await tx.execute(
                f"UPDATE {tx.table('products')} SET {', '.join(assignments)} "
                "WHERE id = :i",
                update_params,
            )

        dependencies = await _republish_bulk_collections(
            tx, merchant_id, collection_ids, merchant["pubkey"], now
        )
        for product_id in ids:
            product = await tx.fetch_one(
                f"SELECT revision, d_tag, published_at FROM {tx.table('products')} "
                "WHERE id = :i",
                {"i": product_id},
            )
            if (
                action == "draft"
                and not by_id[product_id]["draft"]
                and product["published_at"] is not None
            ):
                await enqueue_intent(
                    tx,
                    merchant_id,
                    "products",
                    product_id,
                    5,
                    revision=product["revision"],
                    event_address=f"30402:{merchant['pubkey']}:{product['d_tag']}",
                    depends_on=dependencies,
                )
            else:
                await _enqueue_product(
                    tx,
                    merchant_id,
                    product_id,
                    product["revision"],
                    merchant["pubkey"],
                )
            row = by_id[product_id]
            visible = value if action == "visibility" else row["visibility"]
            draft = action != "publish" and bool(row["draft"])
            if (action in ("publish", "visibility") and row["product_type"] == "variable"
                    and row["import_source_kind"] and not draft and visible != "hidden"):
                await _publish_import_variants(
                    tx, merchant_id, product_id, merchant["pubkey"], visible, now
                )
    return {"updated": len(ids), "product_ids": ids}


async def add_product_image(merchant_id: str, user, product_id: str,
                            payload: dict) -> dict:
    merchant = await _merchant_owned(merchant_id, user)
    row = await _fetch("products", product_id, merchant_id)
    if row["deleted_at"] is not None:
        raise not_found("product not found")
    url = payload.get("url")
    if not isinstance(url, str) or not url.startswith("https://"):
        raise unprocessable(
            "invalid-content", "image URL must be https://"
        )
    async with DomainTransaction() as tx:
        count = await tx.fetch_one(
            f"SELECT COUNT(*) AS n FROM {tx.table('product_images')} "
            "WHERE product_id = :p",
            {"p": product_id},
        )
        if (count["n"] if count else 0) >= IMAGES_MAX:
            raise unprocessable(
                "invalid-content", f"at most {IMAGES_MAX} images"
            )
        await tx.execute(
            f"INSERT INTO {tx.table('product_images')} "
            "(id, product_id, url, dimensions, sort_order) "
            "VALUES (:i, :p, :u, :d, :s)",
            {
                "i": uuid.uuid4().hex,
                "p": product_id,
                "u": url,
                "d": payload.get("dimensions"),
                "s": payload.get("sort_order", count["n"] if count else 0),
            },
        )
        await tx.execute(
            f"UPDATE {tx.table('products')} SET revision = revision + 1,"
            " updated_at = :t WHERE id = :i",
            {"t": _now(), "i": product_id},
        )
        await _enqueue_product(
            tx, merchant_id, product_id, (row["revision"] or 0) + 1,
            merchant["pubkey"],
        )
    return await get_product(merchant_id, user, product_id)


async def _delete_product_locked(
    tx: DomainTransaction, merchant_id: str, product_id: str,
    pubkey: str,
) -> None:
    """Soft-delete core inside an open transaction — shared by DELETE and
    the last-member cascade."""
    row = await tx.fetch_one(
        f"SELECT d_tag, deleted_at FROM {tx.table('products')} WHERE id = :i",
        {"i": product_id},
    )
    if not row or row["deleted_at"] is not None:
        return
    now = _now()
    # Affected collections BEFORE membership removal (they republish first).
    member_collections = await _collections_of_product(tx, product_id)
    for tbl in (
        "product_images", "product_specs", "product_categories",
        "product_collections", "product_shipping_options",
        "product_shipping_collections",
    ):
        await tx.execute(
            f"DELETE FROM {tx.table(tbl)} WHERE product_id = :p",
            {"p": product_id},
        )
    await tx.execute(
        f"UPDATE {tx.table('products')} SET deleted_at = :t,"
        " updated_at = :t, revision = revision + 1 WHERE id = :i",
        {"t": now, "i": product_id},
    )
    # republish surviving collections (a-tags rebuilt without the product)
    deps: list[tuple[str, str]] = []
    for cid in member_collections:
        col = await tx.fetch_one(
            f"SELECT revision FROM {tx.table('collections')} WHERE id = :i",
            {"i": cid},
        )
        nr = (col["revision"] or 0) + 1
        await tx.execute(
            f"UPDATE {tx.table('collections')} SET revision = :r,"
            " updated_at = :t WHERE id = :i",
            {"r": nr, "t": now, "i": cid},
        )
        intent = await _enqueue_collection(
            tx, merchant_id, cid, nr, pubkey
        )
        if intent is None:
            # last active member removed -> the collection cannot publish
            # (§6.2). Tombstone the relay copy but keep the local row — the
            # merchant may add members later and re-publish.
            col_row = await tx.fetch_one(
                f"SELECT d_tag FROM {tx.table('collections')} WHERE id = :i",
                {"i": cid},
            )
            await enqueue_intent(
                tx, merchant_id, "collections", cid, 5,
                revision=nr,
                event_address=f"30405:{pubkey}:{col_row['d_tag']}",
            )
        else:
            deps.append(("collections", cid))
    # tombstone intent — depends on survivor republishes
    await enqueue_intent(
        tx, merchant_id, "products", product_id, 5,
        revision=(await tx.fetch_one(
            f"SELECT revision FROM {tx.table('products')} WHERE id = :i",
            {"i": product_id},
        ))["revision"],
        event_address=f"30402:{pubkey}:{row['d_tag']}",
        depends_on=deps,
    )


async def delete_product(merchant_id: str, user, product_id: str) -> dict:
    merchant = await _merchant_owned(merchant_id, user)
    row = await _fetch("products", product_id, merchant_id)
    if row["deleted_at"] is not None:
        raise not_found("product not found")
    async with DomainTransaction() as tx:
        await _delete_product_locked(
            tx, merchant_id, product_id, merchant["pubkey"]
        )
    return {"deleted": True, "id": product_id}


# --- collections -----------------------------------------------------------------


_COLLECTION_FIELDS = {
    "d_tag", "title", "description", "image", "location", "geohash",
    "shipping_option_ids",
}


async def create_collection(merchant_id: str, user, payload: dict) -> dict:
    await _merchant_owned(merchant_id, user)
    _reject_unknown(payload, _COLLECTION_FIELDS)
    title = _check_title(payload.get("title"))
    description = _check_description(payload.get("description"))
    image = payload.get("image")
    if image is not None and not image.startswith("https://"):
        raise unprocessable(
            "invalid-content", "collection image must be https://"
        )
    collection_id = uuid.uuid4().hex
    d_tag = payload.get("d_tag") or _gen_d_tag()
    _check_d_tag(d_tag)
    now = _now()
    async with DomainTransaction() as tx:
        await _check_d_tag_free(tx, "collections", merchant_id, d_tag)
        await tx.execute(
            f"INSERT INTO {tx.table('collections')} "
            "(id, merchant_id, d_tag, title, description, image, location,"
            " geohash, created_at, updated_at) "
            "VALUES (:i, :m, :d, :t2, :desc, :img, :loc, :g, :t, :t)",
            {
                "i": collection_id,
                "m": merchant_id,
                "d": d_tag,
                "t2": title,
                "desc": description,
                "img": image,
                "loc": payload.get("location"),
                "g": payload.get("geohash"),
                "t": now,
            },
        )
        for sid in payload.get("shipping_option_ids") or []:
            opt = await tx.fetch_one(
                f"SELECT id, deleted_at FROM {tx.table('shipping_options')} "
                "WHERE id = :i AND merchant_id = :m",
                {"i": sid, "m": merchant_id},
            )
            if not opt or opt["deleted_at"] is not None:
                raise unprocessable(
                    "invalid-content", f"shipping option {sid} not found"
                )
            await tx.execute(
                f"INSERT INTO {tx.table('collection_shipping')} "
                "(id, collection_id, shipping_option_id) "
                "VALUES (:i, :c, :s)",
                {"i": uuid.uuid4().hex, "c": collection_id, "s": sid},
            )
        # zero members -> no intent (§6.2); non-empty happens via product
        # membership paths which enqueue the collection then.
    return await get_collection(merchant_id, user, collection_id)


async def list_collections(merchant_id: str, user) -> list[dict]:
    await _merchant_owned(merchant_id, user)
    return await _fetchall("collections", merchant_id)


async def get_collection(merchant_id: str, user, collection_id: str) -> dict:
    await _merchant_owned(merchant_id, user)
    row = await _fetch("collections", collection_id, merchant_id)
    if row["deleted_at"] is not None:
        raise not_found("collection not found")
    from ..db import db, table

    async with db.connect() as conn:
        members = await conn.fetchall(
            f"SELECT p.id, p.d_tag, p.title, p.draft FROM {table('product_collections')} pc "
            f"JOIN {table('products')} p ON p.id = pc.product_id "
            "WHERE pc.collection_id = :c AND p.deleted_at IS NULL",
            {"c": collection_id},
        )
        ship = await conn.fetchall(
            f"SELECT shipping_option_id FROM {table('collection_shipping')} "
            "WHERE collection_id = :c",
            {"c": collection_id},
        )
    row["members"] = [dict(m) for m in members]
    row["shipping_option_ids"] = [s["shipping_option_id"] for s in ship]
    return row


async def patch_collection(merchant_id: str, user, collection_id: str,
                           patch: dict) -> dict:
    merchant = await _merchant_owned(merchant_id, user)
    row = await _fetch("collections", collection_id, merchant_id)
    if row["deleted_at"] is not None:
        raise not_found("collection not found")
    allowed = {"title", "description", "image", "location", "geohash",
               "shipping_option_ids"}
    unknown = set(patch) - allowed
    if unknown:
        raise unprocessable(
            "invalid-content", f"unsupported fields: {sorted(unknown)}"
        )
    now = _now()
    async with DomainTransaction() as tx:
        for col in ("title", "description", "image", "location", "geohash"):
            if col in patch:
                v = patch[col]
                if col == "title":
                    v = _check_title(v)
                elif col == "description":
                    v = _check_description(v)
                elif col == "image" and v is not None and not v.startswith(
                    "https://"
                ):
                    raise unprocessable(
                        "invalid-content", "image must be https://"
                    )
                await tx.execute(
                    f"UPDATE {tx.table('collections')} SET {col} = :v"
                    " WHERE id = :i",
                    {"v": v, "i": collection_id},
                )
        if "shipping_option_ids" in patch:
            await tx.execute(
                f"DELETE FROM {tx.table('collection_shipping')} "
                "WHERE collection_id = :c",
                {"c": collection_id},
            )
            for sid in patch["shipping_option_ids"] or []:
                opt = await tx.fetch_one(
                    f"SELECT id, deleted_at FROM {tx.table('shipping_options')} "
                    "WHERE id = :i AND merchant_id = :m",
                    {"i": sid, "m": merchant_id},
                )
                if not opt or opt["deleted_at"] is not None:
                    raise unprocessable(
                        "invalid-content",
                        f"shipping option {sid} not found",
                    )
                await tx.execute(
                    f"INSERT INTO {tx.table('collection_shipping')} "
                    "(id, collection_id, shipping_option_id) "
                    "VALUES (:i, :c, :s)",
                    {"i": uuid.uuid4().hex, "c": collection_id, "s": sid},
                )
        nr = (row["revision"] or 0) + 1
        await tx.execute(
            f"UPDATE {tx.table('collections')} SET revision = :r,"
            " updated_at = :t WHERE id = :i",
            {"r": nr, "t": now, "i": collection_id},
        )
        await _enqueue_collection(
            tx, merchant_id, collection_id, nr, merchant["pubkey"]
        )
    return await get_collection(merchant_id, user, collection_id)


async def _collection_references(
    tx: DomainTransaction, collection_id: str
) -> dict:
    members = await tx.fetch_all(
        f"SELECT product_id AS i FROM {tx.table('product_collections')} "
        "WHERE collection_id = :c",
        {"c": collection_id},
    )
    ship_refs = await tx.fetch_all(
        f"SELECT product_id AS i FROM {tx.table('product_shipping_collections')} "
        "WHERE collection_id = :c",
        {"c": collection_id},
    )
    return {
        "member_products": [r["i"] for r in members],
        "shipping_referencing_products": [r["i"] for r in ship_refs],
    }


async def _delete_collection_locked(
    tx: DomainTransaction, merchant_id: str, collection_id: str,
    pubkey: str, strip: bool = False,
) -> dict:
    row = await tx.fetch_one(
        f"SELECT d_tag, deleted_at FROM {tx.table('collections')} WHERE id = :i",
        {"i": collection_id},
    )
    if not row or row["deleted_at"] is not None:
        return {"deleted": True}
    refs = await _collection_references(tx, collection_id)
    if (refs["member_products"] or refs["shipping_referencing_products"]) \
            and not strip:
        raise conflict(
            "invalid-transition", "Collection is referenced",
            json.dumps(refs),
        )
    now = _now()
    affected_products = list(
        dict.fromkeys(
            refs["member_products"] + refs["shipping_referencing_products"]
        )
    )
    await tx.execute(
        f"DELETE FROM {tx.table('product_collections')} "
        "WHERE collection_id = :c",
        {"c": collection_id},
    )
    await tx.execute(
        f"DELETE FROM {tx.table('product_shipping_collections')} "
        "WHERE collection_id = :c",
        {"c": collection_id},
    )
    await tx.execute(
        f"DELETE FROM {tx.table('collection_shipping')} "
        "WHERE collection_id = :c",
        {"c": collection_id},
    )
    await tx.execute(
        f"UPDATE {tx.table('collections')} SET deleted_at = :t,"
        " revision = revision + 1, updated_at = :t WHERE id = :i",
        {"t": now, "i": collection_id},
    )
    tomb_rev = (await tx.fetch_one(
        f"SELECT revision FROM {tx.table('collections')} WHERE id = :i",
        {"i": collection_id},
    ))["revision"]
    # survivors republish first; tombstone depends on them
    deps: list[tuple[str, str]] = []
    for pid in affected_products:
        prod = await tx.fetch_one(
            f"SELECT revision, draft, deleted_at FROM {tx.table('products')} "
            "WHERE id = :i",
            {"i": pid},
        )
        if not prod or prod["deleted_at"] is not None:
            continue
        nr = (prod["revision"] or 0) + 1
        await tx.execute(
            f"UPDATE {tx.table('products')} SET revision = :r,"
            " updated_at = :t WHERE id = :i",
            {"r": nr, "t": now, "i": pid},
        )
        intent = await _enqueue_product(
            tx, merchant_id, pid, nr, pubkey
        )
        if intent:
            deps.append(("products", pid))
    await enqueue_intent(
        tx, merchant_id, "collections", collection_id, 5,
        revision=tomb_rev,
        event_address=f"30405:{pubkey}:{row['d_tag']}",
        depends_on=deps,
    )
    return {"deleted": True}


async def delete_collection(merchant_id: str, user, collection_id: str,
                            strip: bool = False) -> dict:
    merchant = await _merchant_owned(merchant_id, user)
    row = await _fetch("collections", collection_id, merchant_id)
    if row["deleted_at"] is not None:
        raise not_found("collection not found")
    async with DomainTransaction() as tx:
        result = await _delete_collection_locked(
            tx, merchant_id, collection_id, merchant["pubkey"], strip=strip
        )
    return {"deleted": True, "id": collection_id, **result}


# --- shipping options -------------------------------------------------------------


def _validate_shipping_payload(p: dict, partial: bool = False) -> None:
    # §4.6: price-distance is rejected outright in v1
    for key in p:
        if key.startswith("price_distance") or key == "price-distance":
            raise unprocessable(
                "invalid-content",
                "price-distance shipping is not supported in v1",
            )
    if "title" in p or not partial:
        _check_title(p.get("title"))
    if "description" in p:
        _check_description(p["description"])
    if "service" in p and p["service"] not in SERVICES:
        raise unprocessable(
            "invalid-content", f"service must be one of {SERVICES}"
        )
    _check_currency(p.get("currency"), p.get("currency_decimals"))
    for field in ("base_price_minor", "price_weight_minor", "price_volume_minor"):
        value = p.get(field)
        if value is not None and (type(value) is not int or not 0 <= value <= 2**63 - 1):
            raise unprocessable(
                "invalid-content", f"{field} must be nonnegative integer minor units",
            )
    import math

    for stem in ("weight", "dim_l", "dim_w", "dim_h"):
        lower, upper = (
            ("weight_min", "weight_max") if stem == "weight"
            else (f"dim_min_{stem[-1]}", f"dim_max_{stem[-1]}")
        )
        for field in (lower, upper):
            value = p.get(field)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value < 0
            ):
                raise unprocessable("invalid-content", f"{field} must be finite and nonnegative")
        if p.get(lower) is not None and p.get(upper) is not None and p[lower] > p[upper]:
            raise unprocessable("invalid-content", f"{lower} must not exceed {upper}")
    if "countries" in p and p["countries"] is not None:
        countries = p["countries"]
        if not isinstance(countries, list) or not countries:
            raise unprocessable(
                "invalid-content", "countries must be a non-empty list"
            )
        for c in countries:
            if not isinstance(c, str) or not COUNTRY_RE.match(c):
                raise unprocessable(
                    "invalid-content",
                    "countries must be ISO 3166-1 alpha-2",
                )
    if "regions" in p and p["regions"] is not None:
        for r in p["regions"]:
            if not isinstance(r, str) or not REGION_RE.match(r):
                raise unprocessable(
                    "invalid-content",
                    "regions must be ISO 3166-2",
                )
    if "duration_unit" in p and p["duration_unit"] is not None:
        if p["duration_unit"] not in DURATION_UNITS:
            raise unprocessable(
                "invalid-content", "duration_unit must be H|D|W"
            )
    lo, hi = p.get("duration_min"), p.get("duration_max")
    if lo is not None and hi is not None and lo > hi:
        raise unprocessable(
            "invalid-content", "duration_min must be <= duration_max"
        )
    if p.get("service") == "pickup" or (partial and p.get("service") is None):
        pass  # pickup location check needs merged state — done in caller


_SHIPPING_FIELDS = (
    "title", "description", "base_price_minor", "currency", "currency_decimals", "service",
    "countries", "regions",
    "carrier", "duration_min", "duration_max", "duration_unit",
    "weight_min", "weight_max", "weight_unit",
    "dim_min_l", "dim_min_w", "dim_min_h",
    "dim_max_l", "dim_max_w", "dim_max_h", "dim_unit",
    "price_weight_minor", "price_weight_unit",
    "price_volume_minor", "price_volume_unit",
    "location", "geohash", "active",
)


_SHIPPING_PAYLOAD_FIELDS = set(_SHIPPING_FIELDS) | {"d_tag"}


async def create_shipping(merchant_id: str, user, payload: dict) -> dict:
    merchant = await _merchant_owned(merchant_id, user)
    from .fx import default_currency_decimals

    payload = dict(payload)
    _reject_unknown(payload, _SHIPPING_PAYLOAD_FIELDS)
    _validate_shipping_payload(payload)
    if payload.get("currency_decimals") is None:
        payload["currency_decimals"] = default_currency_decimals(payload.get("currency"))
    if payload.get("service") == "pickup" and not (
        payload.get("location") or payload.get("geohash")
    ):
        raise unprocessable(
            "invalid-content", "pickup requires location or geohash"
        )
    option_id = uuid.uuid4().hex
    d_tag = payload.get("d_tag") or _gen_d_tag()
    _check_d_tag(d_tag)
    now = _now()
    cols = ["id", "merchant_id", "d_tag", "service", "revision",
            "created_at", "updated_at"]
    vals = [option_id, merchant_id, d_tag,
            payload.get("service", "standard"), 0, now, now]
    for f in _SHIPPING_FIELDS:
        if f in payload and f not in ("service",):
            v = payload[f]
            if f in ("countries", "regions"):
                v = json.dumps(v) if v is not None else None
            elif f == "description":
                v = _check_description(v)
            cols.append(f)
            vals.append(v)
    async with DomainTransaction() as tx:
        await _check_d_tag_free(
            tx, "shipping_options", merchant_id, d_tag
        )
        placeholders = ", ".join(f":p{i}" for i in range(len(cols)))
        await tx.execute(
            f"INSERT INTO {tx.table('shipping_options')} "
            f"({', '.join(cols)}) VALUES ({placeholders})",
            {f"p{i}": v for i, v in enumerate(vals)},
        )
        await _enqueue_shipping(
            tx, merchant_id, option_id, 0, merchant["pubkey"]
        )
    return await get_shipping(merchant_id, user, option_id)


async def list_shipping(merchant_id: str, user) -> list[dict]:
    await _merchant_owned(merchant_id, user)
    rows = await _fetchall("shipping_options", merchant_id)
    for row in rows:
        for f in ("countries", "regions"):
            if row.get(f):
                row[f] = json.loads(row[f])
    return rows


async def get_shipping(merchant_id: str, user, option_id: str) -> dict:
    await _merchant_owned(merchant_id, user)
    row = await _fetch("shipping_options", option_id, merchant_id)
    if row["deleted_at"] is not None:
        raise not_found("shipping option not found")
    for f in ("countries", "regions"):
        if row.get(f):
            row[f] = json.loads(row[f])
    return row


async def patch_shipping(merchant_id: str, user, option_id: str,
                         patch: dict) -> dict:
    merchant = await _merchant_owned(merchant_id, user)
    row = await _fetch("shipping_options", option_id, merchant_id)
    if row["deleted_at"] is not None:
        raise not_found("shipping option not found")
    _reject_unknown(patch, _SHIPPING_PAYLOAD_FIELDS)
    _validate_shipping_payload(patch, partial=True)
    from .fx import default_currency_decimals

    patch = dict(patch)
    if (
        "currency" in patch and patch["currency"] != row["currency"]
        and "currency_decimals" not in patch
    ) or ("currency_decimals" in patch and patch["currency_decimals"] is None):
        patch["currency_decimals"] = default_currency_decimals(
            patch.get("currency", row["currency"]),
        )
    merged = dict(row)
    merged.update(patch)
    for field in ("countries", "regions"):
        if isinstance(merged.get(field), str):
            merged[field] = json.loads(merged[field])
    _validate_shipping_payload(merged)
    if merged.get("service") == "pickup" and not (
        merged.get("location") or merged.get("geohash")
    ):
        raise unprocessable(
            "invalid-content", "pickup requires location or geohash"
        )
    now = _now()
    async with DomainTransaction() as tx:
        for f in _SHIPPING_FIELDS:
            if f in patch:
                v = patch[f]
                if f in ("countries", "regions"):
                    v = json.dumps(v) if v is not None else None
                elif f == "description":
                    v = _check_description(v)
                elif f == "active":
                    v = bool(v)
                await tx.execute(
                    f"UPDATE {tx.table('shipping_options')} SET {f} = :v"
                    " WHERE id = :i",
                    {"v": v, "i": option_id},
                )
        nr = (row["revision"] or 0) + 1
        await tx.execute(
            f"UPDATE {tx.table('shipping_options')} SET revision = :r,"
            " updated_at = :t WHERE id = :i",
            {"r": nr, "t": now, "i": option_id},
        )
        await _enqueue_shipping(
            tx, merchant_id, option_id, nr, merchant["pubkey"]
        )
        # referencing collections + products republish (their tags embed
        # this option's d_tag/address)
        for r in await tx.fetch_all(
            f"SELECT collection_id AS i FROM {tx.table('collection_shipping')} "
            "WHERE shipping_option_id = :s",
            {"s": option_id},
        ):
            col = await tx.fetch_one(
                f"SELECT revision FROM {tx.table('collections')} WHERE id = :i",
                {"i": r["i"]},
            )
            cnr = (col["revision"] or 0) + 1
            await tx.execute(
                f"UPDATE {tx.table('collections')} SET revision = :r,"
                " updated_at = :t WHERE id = :i",
                {"r": cnr, "t": now, "i": r["i"]},
            )
            await _enqueue_collection(
                tx, merchant_id, r["i"], cnr, merchant["pubkey"]
            )
        for r in await tx.fetch_all(
            f"SELECT product_id AS i FROM {tx.table('product_shipping_options')} "
            "WHERE shipping_option_id = :s",
            {"s": option_id},
        ):
            prod = await tx.fetch_one(
                f"SELECT revision FROM {tx.table('products')} WHERE id = :i",
                {"i": r["i"]},
            )
            pnr = (prod["revision"] or 0) + 1
            await tx.execute(
                f"UPDATE {tx.table('products')} SET revision = :r,"
                " updated_at = :t WHERE id = :i",
                {"r": pnr, "t": now, "i": r["i"]},
            )
            await _enqueue_product(
                tx, merchant_id, r["i"], pnr, merchant["pubkey"]
            )
    return await get_shipping(merchant_id, user, option_id)


async def delete_shipping(merchant_id: str, user, option_id: str,
                          strip: bool = False) -> dict:
    merchant = await _merchant_owned(merchant_id, user)
    row = await _fetch("shipping_options", option_id, merchant_id)
    if row["deleted_at"] is not None:
        raise not_found("shipping option not found")
    now = _now()
    async with DomainTransaction() as tx:
        prod_refs = await tx.fetch_all(
            f"SELECT product_id AS i FROM {tx.table('product_shipping_options')} "
            "WHERE shipping_option_id = :s",
            {"s": option_id},
        )
        col_refs = await tx.fetch_all(
            f"SELECT collection_id AS i FROM {tx.table('collection_shipping')} "
            "WHERE shipping_option_id = :s",
            {"s": option_id},
        )
        if (prod_refs or col_refs) and not strip:
            raise conflict(
                "invalid-transition", "Shipping option is referenced",
                json.dumps({
                    "products": [r["i"] for r in prod_refs],
                    "collections": [r["i"] for r in col_refs],
                }),
            )
        await tx.execute(
            f"DELETE FROM {tx.table('product_shipping_options')} "
            "WHERE shipping_option_id = :s",
            {"s": option_id},
        )
        await tx.execute(
            f"DELETE FROM {tx.table('collection_shipping')} "
            "WHERE shipping_option_id = :s",
            {"s": option_id},
        )
        await tx.execute(
            f"UPDATE {tx.table('shipping_options')} SET deleted_at = :t,"
            " revision = revision + 1, updated_at = :t WHERE id = :i",
            {"t": now, "i": option_id},
        )
        tomb_rev = (await tx.fetch_one(
            f"SELECT revision FROM {tx.table('shipping_options')} WHERE id = :i",
            {"i": option_id},
        ))["revision"]
        deps: list[tuple[str, str]] = []
        for r in prod_refs:
            prod = await tx.fetch_one(
                f"SELECT revision, draft, deleted_at "
                f"FROM {tx.table('products')} WHERE id = :i",
                {"i": r["i"]},
            )
            if not prod or prod["deleted_at"] is not None:
                continue
            nr = (prod["revision"] or 0) + 1
            await tx.execute(
                f"UPDATE {tx.table('products')} SET revision = :r,"
                " updated_at = :t WHERE id = :i",
                {"r": nr, "t": now, "i": r["i"]},
            )
            if await _enqueue_product(
                tx, merchant_id, r["i"], nr, merchant["pubkey"]
            ):
                deps.append(("products", r["i"]))
        for r in col_refs:
            col = await tx.fetch_one(
                f"SELECT revision FROM {tx.table('collections')} WHERE id = :i",
                {"i": r["i"]},
            )
            cnr = (col["revision"] or 0) + 1
            await tx.execute(
                f"UPDATE {tx.table('collections')} SET revision = :r,"
                " updated_at = :t WHERE id = :i",
                {"r": cnr, "t": now, "i": r["i"]},
            )
            if await _enqueue_collection(
                tx, merchant_id, r["i"], cnr, merchant["pubkey"]
            ):
                deps.append(("collections", r["i"]))
        await enqueue_intent(
            tx, merchant_id, "shipping_options", option_id, 5,
            revision=tomb_rev,
            event_address=f"30406:{merchant['pubkey']}:{row['d_tag']}",
            depends_on=deps,
        )
    return {"deleted": True, "id": option_id}


# --- dry-run event rendering ------------------------------------------------------


async def product_events(merchant_id: str, user, product_id: str,
                         settings: ExtSettings | None = None) -> list[dict]:
    """GET /products/{id}/events — rendered unsigned events per protocol."""
    settings = settings or ext_settings()
    merchant = await _merchant_owned(merchant_id, user)
    row = await _fetch("products", product_id, merchant_id)
    if row["deleted_at"] is not None:
        raise not_found("product not found")
    if row["import_source_kind"] is not None:
        from ..db import db
        from ..db import table as table_fn

        async with db.connect() as conn:
            released = await conn.fetchone(
                f"SELECT {released_product_select('products', table_fn)} "
                f"FROM {table_fn('products')} WHERE id = :i",
                {"i": product_id},
            )
        if not released or not released["import_released"]:
            return []
    if row["draft"]:
        # drafts produce NO public events (§6.7)
        return []
    from ..db import db, table

    async with db.connect() as conn:
        images = await conn.fetchall(
            f"SELECT url, dimensions, sort_order "
            f"FROM {table('product_images')} WHERE product_id = :p "
            "ORDER BY sort_order, url",
            {"p": product_id},
        )
        specs = await conn.fetchall(
            f"SELECT key, value FROM {table('product_specs')} "
            "WHERE product_id = :p ORDER BY key",
            {"p": product_id},
        )
        cats = await conn.fetchall(
            f"SELECT category FROM {table('product_categories')} "
            "WHERE product_id = :p",
            {"p": product_id},
        )
        cols = await conn.fetchall(
            f"SELECT c.d_tag FROM {table('product_collections')} pc "
            f"JOIN {table('collections')} c ON c.id = pc.collection_id "
            "WHERE pc.product_id = :p AND c.deleted_at IS NULL",
            {"p": product_id},
        )
        ship_opts = await conn.fetchall(
            f"SELECT so.d_tag, pso.extra_cost_minor "
            f"FROM {table('product_shipping_options')} pso "
            f"JOIN {table('shipping_options')} so "
            "ON so.id = pso.shipping_option_id "
            "WHERE pso.product_id = :p AND so.deleted_at IS NULL",
            {"p": product_id},
        )
        ship_cols = await conn.fetchall(
            f"SELECT c.d_tag, psc.extra_cost_minor "
            f"FROM {table('product_shipping_collections')} psc "
            f"JOIN {table('collections')} c ON c.id = psc.collection_id "
            "WHERE psc.product_id = :p AND c.deleted_at IS NULL",
            {"p": product_id},
        )
    parent_d_tag = None
    if row["product_type"] == "variation":
        parent = await _fetch(
            "products", row["parent_product_id"], merchant_id
        )
        parent_d_tag = parent["d_tag"]
        row["_parent_d_tag"] = parent_d_tag
    shipping_refs = [
        {"kind": 30406, "d_tag": r["d_tag"],
         "extra_cost_minor": r["extra_cost_minor"]}
        for r in ship_opts
    ] + [
        {"kind": 30405, "d_tag": r["d_tag"],
         "extra_cost_minor": r["extra_cost_minor"]}
        for r in ship_cols
    ]
    from . import events

    rendered = [
        events.product_event(
            row,
            pubkey=merchant["pubkey"],
            spec_revision=settings.spec_revision,
            images=[dict(i) for i in images],
            specs=[dict(s) for s in specs],
            categories=[c["category"] for c in cats],
            member_collection_d_tags=[c["d_tag"] for c in cols],
            shipping_refs=shipping_refs,
        )
    ]
    category = await _fetch("categories", row["category_id"], merchant_id)
    if category["publish_nip15"]:
        try:
            rendered.append(
                events.nip15_product_event(
                    row,
                    stall_d=category["nip15_stall_d"],
                    stall_currency=category["default_currency"] or "",
                    parent_d_tag=parent_d_tag,
                    images=[dict(i) for i in images],
                    specs=[dict(s) for s in specs],
                    shipping_surcharges=[
                        {"d_tag": r["d_tag"],
                         "extra_cost_minor": r["extra_cost_minor"]}
                        for r in ship_opts
                    ],
                )
            )
        except events.CompatibilityError as exc:
            raise unprocessable("currency-mismatch", str(exc)) from exc
    return rendered
