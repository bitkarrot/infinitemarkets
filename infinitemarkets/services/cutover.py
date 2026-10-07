from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from pathlib import Path

from lnbits.core.crud.extensions import get_installed_extension
from lnbits.core.crud.payments import get_payments_paginated
from lnbits.core.crud.wallets import get_wallet
from lnbits.core.db import db as core_db
from lnbits.core.models import PaymentFilters
from lnbits.core.services.payments import check_payment_status
from lnbits.db import Database, Filters
from lnbits.settings import settings as host_settings

from ..db import DomainTransaction, db, table
from ..security import ProblemError, conflict, not_found
from . import catalog, migration_import


def _public_epoch(row: dict) -> dict:
    return {
        "id": row["id"], "import_id": row["import_id"], "state": row["state"],
        "freeze_requested_at": row["freeze_requested_at"],
        "freeze_checked_at": row["freeze_checked_at"],
        "snapshot_verified": False, "cutover_verified": False,
    }


async def _next_event_sequence(tx: DomainTransaction, epoch_id: str) -> int:
    row = await tx.fetch_one(
        f"SELECT COALESCE(MAX(sequence), 0) + 1 AS n "
        f"FROM {tx.table('cutover_events')} WHERE epoch_id = :e",
        {"e": epoch_id},
    )
    return row["n"]


MAX_SOURCE_FILES = 128
MAX_SOURCE_FILE_BYTES = 1_048_576


def _source_code_files(root: Path) -> list[Path]:
    if root.is_symlink() or not root.is_dir():
        return []
    candidates = list(root.rglob("*"))
    if len(candidates) > 10_000 or any(path.is_symlink() for path in candidates):
        return []
    files = sorted(
        path.relative_to(root).as_posix()
        for path in candidates
        if path.is_file() and (path.suffix == ".py" or path.name == "config.json")
    )
    if len(files) > MAX_SOURCE_FILES:
        return []
    for relative in files:
        path = root / relative
        try:
            if path.is_symlink() or path.stat().st_size > MAX_SOURCE_FILE_BYTES:
                return []
        except OSError:
            return []
    return [root / relative for relative in files]


def _source_code_hash(root: Path) -> str | None:
    files = _source_code_files(root)
    if not files:
        return None
    digest = hashlib.sha256()
    for path in files:
        try:
            relative = path.relative_to(root).as_posix()
            data = path.read_bytes()
        except OSError:
            return None
        if len(data) > MAX_SOURCE_FILE_BYTES:
            return None
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative.encode())
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


async def _source_contract(source_id: str) -> dict | None:
    async with db.connect() as conn:
        row = await conn.fetchone(
            f"SELECT * FROM {table('cutover_source_contracts')} "
            "WHERE source_id = :s ORDER BY created_at DESC, id DESC LIMIT 1",
            {"s": source_id},
        )
    return dict(row) if row else None


async def old_source_status() -> dict:
    try:
        installed = await get_installed_extension("nostrmarket")
    except Exception:
        return {"disabled": False, "reason_code": "legacy-unavailable"}
    if installed is None:
        return {"disabled": False, "reason_code": "legacy-unavailable"}
    if (installed.active is not False
            or "nostrmarket" not in host_settings.lnbits_deactivated_extensions):
        return {"disabled": False, "reason_code": "legacy-active"}
    contract = await _source_contract("nostrmarket")
    if not contract:
        return {"disabled": True, "reason_code": "source-contract-missing"}
    digest = _source_code_hash(installed.ext_dir)
    if digest is None:
        return {"disabled": True, "reason_code": "source-unreadable"}
    if digest != contract["code_hash"]:
        return {"disabled": True, "reason_code": "source-contract-mismatch"}
    return {
        "disabled": True, "reason_code": "snapshot-unverified",
        "source_contract": {
            "code_hash": digest, "git_commit": contract["git_commit"],
        },
    }


async def _old_source_rows(user_id: str) -> tuple[dict, list, list, list]:
    source = Database("ext_nostrmarket")
    if source.type == "SQLITE" and not Path(source.path).is_file():
        await source.engine.dispose()
        raise conflict("legacy-unavailable", "Old catalog cannot be read")
    try:
        async with source.connect() as conn:
            s = source.references_schema
            merchants = await conn.fetchall(
                f"SELECT id, public_key, meta FROM {s}merchants "
                "WHERE user_id = :u LIMIT 2", {"u": user_id},
            )
            if len(merchants) != 1:
                raise conflict("legacy-source", "Old merchant must be uniquely owned")
            merchant = dict(merchants[0])
            merchant_id = merchant["id"]
            stalls = await conn.fetchall(
                f"SELECT id, wallet FROM {s}stalls WHERE merchant_id = :m LIMIT 65",
                {"m": merchant_id},
            )
            products = await conn.fetchall(
                f"SELECT id, stall_id FROM {s}products "
                "WHERE merchant_id = :m LIMIT 5001", {"m": merchant_id},
            )
            orders = await conn.fetchall(
                f"SELECT id, merchant_public_key, stall_id, invoice_id, order_items "
                f"FROM {s}orders WHERE merchant_id = :m LIMIT 5001",
                {"m": merchant_id},
            )
    except ProblemError:
        raise
    except Exception as exc:
        raise conflict("legacy-unavailable", "Old catalog cannot be read") from exc
    finally:
        await source.engine.dispose()
    return merchant, stalls, products, orders


def _old_order_items(raw: str, product_ids: set[str]) -> list[dict]:
    try:
        items = migration_import._bounded_json(raw.encode())
    except (AttributeError, ValueError) as exc:
        raise conflict("legacy-evidence", "Old order items are incomplete") from exc
    if not isinstance(items, list) or not 0 < len(items) <= 5000:
        raise conflict("legacy-evidence", "Old order items are incomplete")
    normalized, seen = [], set()
    for item in items:
        if (not isinstance(item, dict) or item.get("product_id") not in product_ids
                or item["product_id"] in seen or type(item.get("quantity")) is not int
                or not 0 < item["quantity"] <= migration_import.MAX_STOCK):
            raise conflict("legacy-evidence", "Old order items are incomplete")
        seen.add(item["product_id"])
        normalized.append({"product_id": item["product_id"], "quantity": item["quantity"]})
    return normalized


async def read_old_source_evidence(user_id: str) -> dict:
    if not (await old_source_status())["disabled"]:
        raise conflict("legacy-active", "Old extension must be disabled before inspection")
    merchant, stalls, products, orders = await _old_source_rows(user_id)
    try:
        if not isinstance(merchant["meta"], str) or len(merchant["meta"]) > 65536:
            raise ValueError("old settings exceed size limit")
        config = json.loads(merchant["meta"])
    except (TypeError, ValueError) as exc:
        raise conflict("legacy-evidence", "Old merchant settings are incomplete") from exc
    if (not isinstance(config, dict)
            or not isinstance(merchant["public_key"], str)
            or not re.fullmatch(r"[0-9a-fA-F]{64}", merchant["public_key"])
            or not 0 < len(stalls) <= 64 or not 0 < len(products) <= 5000
            or len(orders) > 5000):
        raise conflict("legacy-evidence", "Old merchant or catalog is incomplete")
    stall_wallets = {row["id"]: row["wallet"] for row in stalls}
    stall_ids = set(stall_wallets)
    product_ids = {row["id"] for row in products}
    if (len(stall_ids) != len(stalls) or len(product_ids) != len(products)
            or any(row["stall_id"] not in stall_ids for row in products)):
        raise conflict("legacy-evidence", "Old product scope is incomplete")
    try:
        owned_rows = await core_db.fetchall(
            'SELECT id FROM wallets WHERE "user" = :u LIMIT 65', {"u": user_id},
        )
    except Exception as exc:
        raise conflict("legacy-wallet", "Old source wallets are unavailable") from exc
    owned_ids = {row["id"] for row in owned_rows}
    if (len(owned_rows) > 64 or len(owned_ids) != len(owned_rows)
            or not {row["wallet"] for row in stalls} <= owned_ids):
        raise conflict("legacy-wallet", "Old source wallets are unavailable")
    order_by_id, current_invoices = {}, set()
    for row in orders:
        invoice = row["invoice_id"]
        if (not isinstance(row["id"], str) or not 0 < len(row["id"]) <= 128
                or row["id"] in order_by_id or row["stall_id"] not in stall_ids
                or row["merchant_public_key"] != merchant["public_key"]
                or not isinstance(invoice, str)
                or not re.fullmatch(r"[0-9a-fA-F]{64}", invoice)
                or invoice.lower() in current_invoices):
            raise conflict("legacy-evidence", "Old order scope is incomplete")
        current_invoices.add(invoice.lower())
        order_by_id[row["id"]] = {
            "invoice_id": invoice.lower(),
            "wallet_id": stall_wallets[row["stall_id"]],
            "items": _old_order_items(row["order_items"], product_ids),
        }
    matched, evidence, scanned = set(), [], 0
    for wallet_id in sorted(owned_ids):
        try:
            wallet = await get_wallet(wallet_id)
        except Exception as exc:
            raise conflict("legacy-wallet", "Old source wallets are unavailable") from exc
        if (not wallet or wallet.user != user_id or wallet.id != wallet_id
                or not wallet.can_view_payments):
            raise conflict("legacy-wallet", "Old source wallets are unavailable")
        offset, total = 0, None
        while total is None or offset < total:
            try:
                page = await get_payments_paginated(
                    wallet_id=wallet_id, incoming=True,
                    filters=Filters[PaymentFilters](
                        model=PaymentFilters, limit=250, offset=offset,
                        sortby="time", direction="asc",
                    ),
                )
            except Exception as exc:
                raise conflict("legacy-wallet", "Old payments cannot be enumerated") from exc
            if (type(page.total) is not int or not 0 <= page.total <= 5000
                    or (total is not None and total != page.total)
                    or len(page.data) > 250 or len(page.data) > page.total - offset
                    or (offset < page.total and not page.data)
                    or scanned + page.total > 5000):
                raise conflict("legacy-evidence", "Old payment enumeration is incomplete")
            total = page.total
            for payment in page.data:
                if not isinstance(payment.extra, dict):
                    raise conflict("legacy-evidence", "Old payment metadata is incomplete")
                if payment.extra.get("tag") != "nostrmarket":
                    continue
                if (payment.extra.get("merchant_pubkey") != merchant["public_key"]
                        or type(payment.amount) is not int or payment.amount <= 0
                        or payment.wallet_id != wallet_id
                        or not isinstance(payment.payment_hash, str)
                        or not re.fullmatch(r"[0-9a-fA-F]{64}", payment.payment_hash)):
                    raise conflict("legacy-evidence", "Old payment identity is incomplete")
                order_id = payment.extra.get("order_id")
                invoice = payment.payment_hash.lower()
                if (order_id not in order_by_id or invoice != order_by_id[order_id]["invoice_id"]
                        or wallet_id != order_by_id[order_id]["wallet_id"]
                        or invoice in matched):
                    raise conflict("legacy-evidence", "Old payment and order sets differ")
                try:
                    status = await check_payment_status(payment)
                except Exception as exc:
                    raise conflict("legacy-evidence", "Old payment status is unavailable") from exc
                if status.paid not in (None, True, False):
                    raise conflict("legacy-evidence", "Old payment status is unavailable")
                matched.add(invoice)
                evidence.append({"invoice_id": invoice, "order_id": order_id,
                                 "items": order_by_id[order_id]["items"],
                                 "state": "paid" if status.paid is True else "payable"})
            offset += len(page.data)
        scanned += total
    if matched != current_invoices or not (await old_source_status())["disabled"]:
        raise conflict("legacy-evidence", "Old payment and order sets differ")
    return {"merchant_id": merchant["id"], "products": product_ids,
            "invoices": sorted(evidence, key=lambda item: item["invoice_id"])}


def compare_old_source(merchant_id: str, audit: dict, source: dict) -> dict:
    from .. import crypto
    from ..settings import ext_settings

    if audit["source_kind"] != "nostrmarket":
        raise conflict("source-unverifiable", "Old source cannot be verified")
    product_by_id = {row["product_id"]: row["legacy_id"] for row in audit["rows"]}
    legacy_ids = set(product_by_id.values())
    if (len(product_by_id) != len(audit["rows"])
            or len(legacy_ids) != len(product_by_id)
            or legacy_ids != source["products"]):
        raise conflict("legacy-evidence", "Old product sets differ")
    key = ext_settings().privacy_key
    actual, seen_invoices, paid_qty, payable_qty = [], set(), 0, 0
    for invoice in source["invoices"]:
        raw_invoice = invoice["invoice_id"]
        if raw_invoice in seen_invoices or invoice["state"] not in ("paid", "payable"):
            raise conflict("legacy-evidence", "Old invoice set is incomplete")
        seen_invoices.add(raw_invoice)
        invoice_hash = crypto.hmac_index(key, "legacy-invoice", merchant_id, raw_invoice)
        order_hash = crypto.hmac_index(key, "legacy-order", merchant_id, invoice["order_id"])
        for item in invoice["items"]:
            product_id, qty = item["product_id"], item["quantity"]
            if product_id not in legacy_ids or type(qty) is not int or not 0 < qty <= 2**63 - 1:
                raise conflict("legacy-evidence", "Old invoice items are incomplete")
            actual.append((invoice_hash, order_hash, product_id, qty))
            if invoice["state"] == "paid":
                paid_qty += qty
            else:
                payable_qty += qty
    expected = [
        (row["invoice_hash"], row["order_hash"],
         product_by_id.get(row["product_id"]), row["quantity"])
        for row in audit["liabilities"]
    ]
    if (len(actual) != len(expected) or any(row[2] is None for row in expected)
            or sorted(actual) != sorted(expected)):
        raise conflict("legacy-evidence", "Old payment and import sets differ")
    evidence_items = sorted(
        (crypto.hmac_index(key, "legacy-invoice", merchant_id, row["invoice_id"]),
         row["state"]) for row in source["invoices"]
    )
    return {
        "source_merchant_index": crypto.hmac_index(
            key, "cutover-source", merchant_id, source["merchant_id"]),
        "evidence_hash": crypto.hmac_index(
            key, "cutover-evidence", merchant_id,
            json.dumps((audit["id"], sorted(actual), evidence_items),
                       separators=(",", ":"))),
        "source_product_count": len(legacy_ids),
        "liability_count": len(actual), "paid_quantity": paid_qty,
        "payable_quantity": payable_qty, "snapshot_verified": False,
        "cutover_verified": False,
    }


async def check_source(merchant_id: str, user, epoch_id: str) -> dict:
    await catalog._merchant_owned(merchant_id, user)
    async with db.connect() as conn:
        epoch = await conn.fetchone(
            f"SELECT import_id, state FROM {table('cutover_epochs')} "
            "WHERE id = :i AND merchant_id = :m",
            {"i": epoch_id, "m": merchant_id},
        )
    if not epoch:
        raise not_found("cutover not found")
    if epoch["state"] != "freeze_requested":
        raise conflict("invalid-transition", "Old source cannot be checked in this state")
    if not (await old_source_status())["disabled"]:
        raise conflict("legacy-active", "Old extension must be disabled before inspection")
    audited = await migration_import.audit_import(merchant_id, user, epoch["import_id"])
    evidence = await read_old_source_evidence(user.id)
    comparison = compare_old_source(merchant_id, audited, evidence)
    async with db.connect() as conn:
        current = await conn.fetchone(
            f"SELECT state FROM {table('cutover_epochs')} "
            "WHERE id = :i AND merchant_id = :m",
            {"i": epoch_id, "m": merchant_id},
        )
    if (not current or current["state"] != "freeze_requested"
            or not (await old_source_status())["disabled"]):
        raise conflict("legacy-evidence", "Old source changed during inspection")
    return {**comparison, "epoch_id": epoch_id, "checked_at": int(time.time())}


async def stage_import(merchant_id: str, user, import_id: str) -> dict:
    audited = await migration_import.audit_import(merchant_id, user, import_id)
    if audited["source_kind"] != "nostrmarket":
        raise conflict("source-unverifiable", "Only same-instance nostrmarket can stage cutover")
    now = int(time.time())
    async with DomainTransaction() as tx:
        await tx.fetch_one(
            f"SELECT id FROM {tx.table('merchants')} WHERE id = :m{tx.for_update}",
            {"m": merchant_id},
        )
        source = await tx.fetch_one(
            f"SELECT source_hash FROM {tx.table('catalog_imports')} "
            "WHERE id = :i AND merchant_id = :m",
            {"i": import_id, "m": merchant_id},
        )
        if not source or source["source_hash"] != audited["source_hash"]:
            raise conflict("import-changed", "Import changed since its audit")
        previous = await tx.fetch_one(
            f"SELECT * FROM {tx.table('cutover_epochs')} "
            "WHERE merchant_id = :m AND import_id = :i "
            "ORDER BY epoch_number DESC LIMIT 1",
            {"m": merchant_id, "i": import_id},
        )
        if previous and previous["state"] in ("staged", "freeze_requested"):
            return _public_epoch(previous)
        if previous and previous["state"] != "blocked":
            raise conflict("cutover-active", "Cutover epoch already exists")
        epoch_id = uuid.uuid4().hex
        await tx.execute(
            f"INSERT INTO {tx.table('cutover_epochs')} "
            "(id, merchant_id, import_id, epoch_number, state, created_at, updated_at) "
            "VALUES (:i, :m, :b, :n, 'staged', :t, :t)",
            {"i": epoch_id, "m": merchant_id, "b": import_id, "t": now,
             "n": previous["epoch_number"] + 1 if previous else 1},
        )
        await tx.execute(
            f"INSERT INTO {tx.table('cutover_events')} "
            "(id, epoch_id, state, reason_code, sequence, created_at) "
            "VALUES (:i, :e, 'staged', 'stage', 1, :t)",
            {"i": uuid.uuid4().hex, "e": epoch_id, "t": now},
        )
    return {"id": epoch_id, "import_id": import_id, "state": "staged",
            "freeze_requested_at": None, "freeze_checked_at": None,
            "snapshot_verified": False, "cutover_verified": False}


async def _owned_epoch(tx: DomainTransaction, merchant_id: str, epoch_id: str) -> dict:
    row = await tx.fetch_one(
        f"SELECT * FROM {tx.table('cutover_epochs')} "
        f"WHERE id = :i AND merchant_id = :m{tx.for_update}",
        {"i": epoch_id, "m": merchant_id},
    )
    if not row:
        raise not_found("cutover not found")
    return dict(row)


async def request_freeze(merchant_id: str, user, epoch_id: str) -> dict:
    await catalog._merchant_owned(merchant_id, user)
    now = int(time.time())
    async with DomainTransaction() as tx:
        await tx.fetch_one(
            f"SELECT id FROM {tx.table('merchants')} WHERE id = :m{tx.for_update}",
            {"m": merchant_id},
        )
        row = await _owned_epoch(tx, merchant_id, epoch_id)
        if row["state"] == "freeze_requested":
            return _public_epoch(row)
        if row["state"] != "staged":
            raise conflict("invalid-transition", "Cutover cannot request freeze")
        await tx.execute(
            f"UPDATE {tx.table('cutover_epochs')} "
            "SET state = 'freeze_requested', freeze_requested_at = :t, updated_at = :t "
            "WHERE id = :i AND state = 'staged'",
            {"i": epoch_id, "t": now},
        )
        await tx.execute(
            f"INSERT INTO {tx.table('cutover_events')} "
            "(id, epoch_id, state, reason_code, sequence, created_at) "
            "VALUES (:i, :e, 'freeze_requested', 'operator-request', :n, :t)",
            {"i": uuid.uuid4().hex, "e": epoch_id, "t": now,
             "n": await _next_event_sequence(tx, epoch_id)},
        )
        row.update(state="freeze_requested", freeze_requested_at=now)
    return _public_epoch(row)


async def abort_staging(merchant_id: str, user, epoch_id: str) -> dict:
    await catalog._merchant_owned(merchant_id, user)
    now = int(time.time())
    async with DomainTransaction() as tx:
        await tx.fetch_one(
            f"SELECT id FROM {tx.table('merchants')} WHERE id = :m{tx.for_update}",
            {"m": merchant_id},
        )
        row = await _owned_epoch(tx, merchant_id, epoch_id)
        if row["state"] == "blocked":
            return _public_epoch(row)
        if row["state"] not in ("staged", "freeze_requested"):
            raise conflict("invalid-transition", "Cannot abort verified cutover here")
        await tx.execute(
            f"UPDATE {tx.table('cutover_epochs')} "
            "SET state = 'blocked', updated_at = :t WHERE id = :i",
            {"i": epoch_id, "t": now},
        )
        await tx.execute(
            f"INSERT INTO {tx.table('cutover_events')} "
            "(id, epoch_id, state, reason_code, sequence, created_at) "
            "VALUES (:i, :e, 'blocked', 'operator-abort', :n, :t)",
            {"i": uuid.uuid4().hex, "e": epoch_id, "t": now,
             "n": await _next_event_sequence(tx, epoch_id)},
        )
        row["state"] = "blocked"
    return _public_epoch(row)


async def cutover_status(merchant_id: str, user, epoch_id: str) -> dict:
    await catalog._merchant_owned(merchant_id, user)
    async with db.connect() as conn:
        row = await conn.fetchone(
            f"SELECT * FROM {table('cutover_epochs')} "
            "WHERE id = :i AND merchant_id = :m",
            {"i": epoch_id, "m": merchant_id},
        )
        if not row:
            raise not_found("cutover not found")
        events = await conn.fetchall(
            f"SELECT state, reason_code, created_at FROM {table('cutover_events')} "
            "WHERE epoch_id = :e ORDER BY sequence LIMIT 100",
            {"e": epoch_id},
        )
    return {**_public_epoch(row), "source": await old_source_status(),
            "events": [dict(event) for event in events]}
