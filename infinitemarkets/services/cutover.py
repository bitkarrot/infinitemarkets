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
    verified_states = ("snapshot_verified", "reconciling", "ready", "complete")
    return {
        "id": row["id"], "import_id": row["import_id"], "state": row["state"],
        "freeze_requested_at": row["freeze_requested_at"],
        "freeze_checked_at": row["freeze_checked_at"],
        "snapshot_verified": row["state"] in verified_states,
        "snapshot_hash": row.get("snapshot_hash"),
        "cutover_verified": row["state"] == "complete",
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
    restart_checked_at = getattr(host_settings, "server_startup_time", None)
    return {
        "disabled": True, "reason_code": "snapshot-unverified",
        "restart_checked_at": restart_checked_at,
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
            or config.get("active") is not False
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


def _snapshot_payload(
    merchant_id: str, audit: dict, source_status: dict,
    comparison: dict, now: int,
) -> dict:
    from .. import crypto
    from ..settings import ext_settings

    key = ext_settings().privacy_key
    cutoff_hash = crypto.hmac_index(
        key, "legacy-cutoff", merchant_id,
        str(source_status["restart_checked_at"]),
    )
    source_hash = crypto.hmac_index(
        key, "legacy-source-code", merchant_id,
        source_status["source_contract"]["code_hash"],
    )
    return {
        "version": 1, "phase": "verified", "source": "nostrmarket",
        "source_merchant_index": comparison["source_merchant_index"],
        "source_code_hash": source_hash, "cutoff_hash": cutoff_hash,
        "restart_checked_at": source_status["restart_checked_at"],
        "import_id": audit["id"], "import_source_hash": audit["source_hash"],
        "liability_count": comparison["liability_count"],
        "paid_quantity": comparison["paid_quantity"],
        "payable_quantity": comparison["payable_quantity"],
        "source_product_count": comparison["source_product_count"],
        "evidence_hash": comparison["evidence_hash"], "created_at": now,
    }


async def check_source(merchant_id: str, user, epoch_id: str) -> dict:
    await catalog._merchant_owned(merchant_id, user)
    async with db.connect() as conn:
        epoch = await conn.fetchone(
            f"SELECT import_id, state, freeze_requested_at "
            f"FROM {table('cutover_epochs')} "
            "WHERE id = :i AND merchant_id = :m",
            {"i": epoch_id, "m": merchant_id},
        )
    if not epoch:
        raise not_found("cutover not found")
    if epoch["state"] != "freeze_requested":
        raise conflict("invalid-transition", "Old source cannot be checked in this state")
    source_status = await old_source_status()
    if not source_status["disabled"]:
        raise conflict("legacy-active", "Old extension must be disabled before inspection")
    if (source_status["reason_code"] != "snapshot-unverified"
            or source_status.get("restart_checked_at") is None
            or source_status.get("source_contract") is None):
        raise conflict("legacy-source", "Old source contract is not verified")
    if (epoch["freeze_requested_at"] is not None
            and source_status["restart_checked_at"] is not None
            and not (epoch["freeze_requested_at"]
                     < source_status["restart_checked_at"])):
        raise conflict(
            "legacy-source",
            "LNbits must be restarted after the freeze request before inspection",
        )
    audited = await migration_import.audit_import(merchant_id, user, epoch["import_id"])
    evidence = await read_old_source_evidence(user.id)
    comparison = compare_old_source(merchant_id, audited, evidence)
    from .. import crypto
    from ..settings import ext_settings

    key = ext_settings().privacy_key
    state_by_hash = {
        crypto.hmac_index(key, "legacy-invoice", merchant_id, row["invoice_id"]):
        row["state"]
        for row in evidence["invoices"]
    }
    final_status = await old_source_status()
    if (not final_status["disabled"]
            or final_status["reason_code"] != "snapshot-unverified"
            or final_status.get("restart_checked_at")
            != source_status["restart_checked_at"]):
        raise conflict("legacy-evidence", "Old source changed during inspection")
    now = int(time.time())
    payload = _snapshot_payload(merchant_id, audited, source_status, comparison, now)
    from nostr_sdk import EventBuilder, Kind, PublicKey, Tag

    from ..keystore import MerchantKeyStore
    from ..settings import ext_settings

    keystore = MerchantKeyStore(ext_settings())
    pubkey = await keystore.public_key(merchant_id)
    builder = EventBuilder(
        Kind(30078), json.dumps(payload, sort_keys=True, separators=(",", ":"))
    ).tags([Tag.parse(["d", "im-cutover-" + comparison["evidence_hash"][:32]])])
    signed = await keystore.sign_event(
        merchant_id, builder.build(PublicKey.parse(pubkey))
    )
    if not signed.verify():
        raise conflict("import-signature", "Snapshot commitment could not be verified")
    async with DomainTransaction() as tx:
        await tx.fetch_one(
            f"SELECT id FROM {tx.table('merchants')} WHERE id = :m{tx.for_update}",
            {"m": merchant_id},
        )
        current = await _owned_epoch(tx, merchant_id, epoch_id)
        if current["state"] != "freeze_requested":
            raise conflict("invalid-transition", "Old source changed during inspection")
        row = await tx.fetch_one(
            f"SELECT source_hash FROM {tx.table('catalog_imports')} "
            "WHERE id = :i AND merchant_id = :m",
            {"i": epoch["import_id"], "m": merchant_id},
        )
        if not row or row["source_hash"] != audited["source_hash"]:
            raise conflict("import-changed", "Import changed since its audit")
        liabilities = await tx.fetch_all(
            f"SELECT id, invoice_hash, status "
            f"FROM {tx.table('imported_liabilities')} "
            "WHERE import_id = :b AND merchant_id = :m",
            {"b": epoch["import_id"], "m": merchant_id},
        )
        for liability in liabilities:
            evidence_state = state_by_hash.get(liability["invoice_hash"])
            if evidence_state not in ("paid", "payable"):
                raise conflict("legacy-evidence", "Old invoice set is incomplete")
            if liability["status"] == "unverified":
                await tx.execute(
                    f"UPDATE {tx.table('imported_liabilities')} SET status = :s "
                    "WHERE id = :i AND status = 'unverified'",
                    {"i": liability["id"], "s": evidence_state},
                )
        rc = await tx.execute(
            f"UPDATE {tx.table('cutover_epochs')} "
            "SET state = 'snapshot_verified', snapshot_hash = :h, "
            "snapshot_json = :j, snapshot_id = :s, freeze_checked_at = :t, "
            "updated_at = :t WHERE id = :i AND state = 'freeze_requested'",
            {
                "i": epoch_id, "h": comparison["evidence_hash"],
                "j": signed.as_json(), "s": signed.id().to_hex(), "t": now,
            },
        )
        if rc != 1:
            raise conflict("invalid-transition", "Old source changed during inspection")
        await tx.execute(
            f"INSERT INTO {tx.table('cutover_events')} "
            "(id, epoch_id, state, reason_code, sequence, created_at) "
            "VALUES (:i, :e, 'snapshot_verified', 'source-check', :n, :t)",
            {"i": uuid.uuid4().hex, "e": epoch_id,
             "n": await _next_event_sequence(tx, epoch_id), "t": now},
        )
    return {**comparison, "snapshot_verified": True,
            "snapshot_hash": comparison["evidence_hash"],
            "epoch_id": epoch_id, "state": "snapshot_verified",
            "checked_at": now}


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
        if row["state"] == "complete":
            raise conflict("invalid-transition", "Completed cutover cannot be aborted")
        # staged/freeze_requested/snapshot_verified/reconciling — abort keeps
        # products blocked and any held partitions in place (invoices may
        # still settle out-of-band; only terminal evidence releases holds).
        await tx.execute(
            f"UPDATE {tx.table('products')} SET draft = TRUE, "
            "visibility = 'hidden' "
            f"WHERE merchant_id = :m AND (draft = FALSE OR visibility != 'hidden') "
            f"AND id IN ("
            f"SELECT product_id FROM {tx.table('import_rows')} "
            "WHERE import_id = :i)",
            {"m": merchant_id, "i": row["import_id"]},
        )
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
    source = await old_source_status()
    now = int(time.time())
    async with DomainTransaction() as tx:
        await tx.fetch_one(
            f"SELECT id FROM {tx.table('merchants')} WHERE id = :m{tx.for_update}",
            {"m": merchant_id},
        )
        row = await _owned_epoch(tx, merchant_id, epoch_id)
        if (row["state"] in ("snapshot_verified", "reconciling", "ready",
                             "complete")
                and not (source["disabled"]
                         and source["reason_code"] == "snapshot-unverified")):
            # detected reactivation or a changed/missing source contract —
            # fail closed; released products and queued intents re-block
            # automatically via the epoch predicate
            reason = (
                "source-reactivated" if not source["disabled"]
                else "source-contract-" + str(source["reason_code"])
            )[:64]
            await tx.execute(
                f"UPDATE {tx.table('cutover_epochs')} "
                "SET state = 'blocked', updated_at = :t "
                "WHERE id = :i AND state IN ('snapshot_verified', "
                "'reconciling', 'ready', 'complete')",
                {"i": epoch_id, "t": now},
            )
            await tx.execute(
                f"INSERT INTO {tx.table('cutover_events')} "
                "(id, epoch_id, state, reason_code, sequence, created_at) "
                "VALUES (:i, :e, 'blocked', :r, :n, :t)",
                {"i": uuid.uuid4().hex, "e": epoch_id, "r": reason,
                 "n": await _next_event_sequence(tx, epoch_id), "t": now},
            )
            row["state"] = "blocked"
        events = await tx.fetch_all(
            f"SELECT state, reason_code, created_at "
            f"FROM {tx.table('cutover_events')} "
            "WHERE epoch_id = :e ORDER BY sequence LIMIT 100",
            {"e": epoch_id},
        )
    return {**_public_epoch(row), "source": source,
            "events": [dict(event) for event in events]}


LIABILITY_TERMINAL = ("paid", "unpaid_terminal")
LIABILITY_OPEN = ("payable", "waiting", "partitioned")


async def list_liabilities(merchant_id: str, user, epoch_id: str) -> dict:
    """Hashed per-liability view — raw invoice/order refs never leave."""
    await catalog._merchant_owned(merchant_id, user)
    async with db.connect() as conn:
        epoch = await conn.fetchone(
            f"SELECT import_id, state FROM {table('cutover_epochs')} "
            "WHERE id = :i AND merchant_id = :m",
            {"i": epoch_id, "m": merchant_id},
        )
        if not epoch:
            raise not_found("cutover not found")
        rows = await conn.fetchall(
            f"SELECT l.id, l.invoice_hash, l.order_hash, l.product_id, "
            f"l.quantity, l.status, l.created_at, p.title, p.import_legacy_id, "
            f"COALESCE(part.state, 'none') AS partition_state "
            f"FROM {table('imported_liabilities')} l "
            f"JOIN {table('products')} p ON p.id = l.product_id "
            f"LEFT JOIN {table('liability_partitions')} part "
            "ON part.liability_id = l.id AND part.epoch_id = :e "
            "WHERE l.import_id = :b AND l.merchant_id = :m "
            "ORDER BY l.created_at, l.id LIMIT 5000",
            {"e": epoch_id, "b": epoch["import_id"], "m": merchant_id},
        )
    return {"epoch_id": epoch_id, "state": epoch["state"],
            "liabilities": [dict(row) for row in rows]}


async def _owned_open_epoch(
    tx: DomainTransaction, merchant_id: str, epoch_id: str
) -> dict:
    epoch = await _owned_epoch(tx, merchant_id, epoch_id)
    if epoch["state"] not in ("snapshot_verified", "reconciling"):
        raise conflict("invalid-transition", "Cutover is not reconciling liabilities")
    return epoch


async def _mark_reconciling(
    tx: DomainTransaction, epoch: dict, now: int
) -> None:
    if epoch["state"] != "snapshot_verified":
        return
    await tx.execute(
        f"UPDATE {tx.table('cutover_epochs')} SET state = 'reconciling', "
        "updated_at = :t WHERE id = :i AND state = 'snapshot_verified'",
        {"i": epoch["id"], "t": now},
    )
    await tx.execute(
        f"INSERT INTO {tx.table('cutover_events')} "
        "(id, epoch_id, state, reason_code, sequence, created_at) "
        "VALUES (:i, :e, 'reconciling', 'disposition-started', :n, :t)",
        {"i": uuid.uuid4().hex, "e": epoch["id"],
         "n": await _next_event_sequence(tx, epoch["id"]), "t": now},
    )
    epoch["state"] = "reconciling"


async def _owned_liability(
    tx: DomainTransaction, merchant_id: str, epoch: dict, liability_id: str
) -> dict:
    row = await tx.fetch_one(
        f"SELECT * FROM {tx.table('imported_liabilities')} "
        f"WHERE id = :i AND merchant_id = :m AND import_id = :b{tx.for_update}",
        {"i": liability_id, "m": merchant_id, "b": epoch["import_id"]},
    )
    if not row:
        raise not_found("liability not found")
    return dict(row)


def _liability_public(liability: dict, partition: dict | None = None) -> dict:
    out = {
        "id": liability["id"], "invoice_hash": liability["invoice_hash"],
        "order_hash": liability["order_hash"], "product_id": liability["product_id"],
        "quantity": liability["quantity"], "status": liability["status"],
    }
    if partition is not None:
        out["partition_state"] = partition["state"]
    return out


async def choose_wait(merchant_id: str, user, epoch_id: str, liability_id: str) -> dict:
    await catalog._merchant_owned(merchant_id, user)
    now = int(time.time())
    async with DomainTransaction() as tx:
        await tx.fetch_one(
            f"SELECT id FROM {tx.table('merchants')} WHERE id = :m{tx.for_update}",
            {"m": merchant_id},
        )
        epoch = await _owned_open_epoch(tx, merchant_id, epoch_id)
        liability = await _owned_liability(tx, merchant_id, epoch, liability_id)
        if liability["status"] in ("waiting", "partitioned"):
            return _liability_public(liability)
        if liability["status"] != "payable":
            raise conflict("invalid-transition", "Liability cannot be held for waiting")
        await tx.execute(
            f"UPDATE {tx.table('imported_liabilities')} SET status = 'waiting' "
            "WHERE id = :i AND status = 'payable'",
            {"i": liability_id},
        )
        await _mark_reconciling(tx, epoch, now)
        await tx.execute(
            f"INSERT INTO {tx.table('cutover_events')} "
            "(id, epoch_id, state, reason_code, sequence, created_at) "
            "VALUES (:i, :e, 'reconciling', 'liability-wait', :n, :t)",
            {"i": uuid.uuid4().hex, "e": epoch_id,
             "n": await _next_event_sequence(tx, epoch_id), "t": now},
        )
        liability["status"] = "waiting"
    return _liability_public(liability)


async def choose_partition(
    merchant_id: str, user, epoch_id: str, liability_id: str
) -> dict:
    """Hold stock for a still-payable old invoice — same conditional capacity
    primitive and merchant→product lock order as ``begin_saga``."""
    await catalog._merchant_owned(merchant_id, user)
    now = int(time.time())
    async with DomainTransaction() as tx:
        await tx.fetch_one(
            f"SELECT id FROM {tx.table('merchants')} WHERE id = :m{tx.for_update}",
            {"m": merchant_id},
        )
        epoch = await _owned_open_epoch(tx, merchant_id, epoch_id)
        liability = await _owned_liability(tx, merchant_id, epoch, liability_id)
        partition = await tx.fetch_one(
            f"SELECT * FROM {tx.table('liability_partitions')} "
            "WHERE liability_id = :l AND epoch_id = :e",
            {"l": liability_id, "e": epoch_id},
        )
        if liability["status"] == "partitioned" and partition:
            return _liability_public(liability, dict(partition))
        if liability["status"] not in ("payable", "waiting"):
            raise conflict("invalid-transition", "Liability cannot be partitioned")
        product = await tx.fetch_one(
            f"SELECT id, stock_on_hand, stock_reserved "
            f"FROM {tx.table('products')} "
            f"WHERE id = :p AND merchant_id = :m{tx.for_update}",
            {"p": liability["product_id"], "m": merchant_id},
        )
        if not product:
            raise conflict("legacy-evidence", "Liability product is missing")
        rc = await tx.execute(
            f"UPDATE {tx.table('products')} "
            "SET stock_reserved = stock_reserved + :q, updated_at = :t "
            "WHERE id = :p AND stock_on_hand IS NOT NULL "
            "AND stock_reserved + :q <= stock_on_hand",
            {"p": liability["product_id"], "q": liability["quantity"], "t": now},
        )
        if rc != 1:
            raise conflict(
                "insufficient-stock",
                "Physical stock baseline cannot cover this old liability",
            )
        await tx.execute(
            f"INSERT INTO {tx.table('liability_partitions')} "
            "(id, epoch_id, liability_id, product_id, quantity, state, "
            "created_at, updated_at) "
            "VALUES (:i, :e, :l, :p, :q, 'held', :t, :t)",
            {"i": uuid.uuid4().hex, "e": epoch_id, "l": liability_id,
             "p": liability["product_id"], "q": liability["quantity"], "t": now},
        )
        await tx.execute(
            f"UPDATE {tx.table('imported_liabilities')} "
            "SET status = 'partitioned' WHERE id = :i",
            {"i": liability_id},
        )
        await _mark_reconciling(tx, epoch, now)
        await tx.execute(
            f"INSERT INTO {tx.table('cutover_events')} "
            "(id, epoch_id, state, reason_code, sequence, created_at) "
            "VALUES (:i, :e, 'reconciling', 'liability-partitioned', :n, :t)",
            {"i": uuid.uuid4().hex, "e": epoch_id,
             "n": await _next_event_sequence(tx, epoch_id), "t": now},
        )
        liability["status"] = "partitioned"
        partition = {"state": "held"}
    return _liability_public(liability, partition)


def _decrypt_invoice_ref(liability: dict) -> str:
    from .. import crypto
    from ..settings import ext_settings

    settings = ext_settings()
    return crypto.decrypt(
        bytes(liability["invoice_ref_enc"]),
        settings.master_keys[settings.active_key_version],
        record_id=liability["id"], table="imported_liabilities",
        column="invoice_ref_enc", key_version=settings.active_key_version,
    ).decode()


async def _authoritative_payment_state(user_id: str, payment_hash: str) -> bool | None:
    """Wallet-scoped authoritative check — True paid, False terminal unpaid,
    None still payable. Any ambiguity or lookup error fails closed."""
    try:
        rows = await core_db.fetchall(
            "SELECT wallet_id FROM apipayments WHERE payment_hash = :h LIMIT 2",
            {"h": payment_hash},
        )
    except Exception as exc:
        raise conflict("legacy-evidence", "Old payment status is unavailable") from exc
    if len(rows) != 1:
        raise conflict("legacy-evidence", "Old payment identity is incomplete")
    wallet_id = rows[0]["wallet_id"]
    try:
        wallet = await get_wallet(wallet_id)
    except Exception as exc:
        raise conflict("legacy-wallet", "Old source wallets are unavailable") from exc
    if (not wallet or wallet.user != user_id or wallet.id != wallet_id
            or not wallet.can_view_payments):
        raise conflict("legacy-wallet", "Old source wallets are unavailable")
    try:
        payment_row = await core_db.fetchone(
            "SELECT * FROM apipayments WHERE wallet_id = :w "
            "AND payment_hash = :h",
            {"w": wallet.source_wallet_id, "h": payment_hash},
        )
        if (not payment_row or not isinstance(payment_row["extra"], str)
                or '"nostrmarket"' not in payment_row["extra"]):
            raise conflict("legacy-evidence", "Old payment identity is incomplete")
        from lnbits.core.models import Payment

        payment = Payment(**dict(payment_row))
        status = await check_payment_status(payment)
    except ProblemError:
        raise
    except Exception as exc:
        raise conflict("legacy-evidence", "Old payment status is unavailable") from exc
    if status.paid not in (None, True, False):
        raise conflict("legacy-evidence", "Old payment status is unavailable")
    return status.paid


async def _apply_terminal_status(
    tx: DomainTransaction,
    merchant_id: str,
    epoch: dict,
    liability: dict,
    paid: bool,
    now: int,
) -> str:
    """Exactly-once settle/release for one liability inside its tx.
    Returns the new status."""
    product = await tx.fetch_one(
        f"SELECT id, stock_on_hand, stock_reserved "
        f"FROM {tx.table('products')} "
        f"WHERE id = :p AND merchant_id = :m{tx.for_update}",
        {"p": liability["product_id"], "m": merchant_id},
    )
    if not product:
        raise conflict("legacy-evidence", "Liability product is missing")
    partition = await tx.fetch_one(
        f"SELECT * FROM {tx.table('liability_partitions')} "
        "WHERE liability_id = :l AND epoch_id = :e",
        {"l": liability["id"], "e": epoch["id"]},
    )
    qty = liability["quantity"]
    if paid:
        if partition and partition["state"] == "held":
            rc = await tx.execute(
                f"UPDATE {tx.table('products')} SET "
                "stock_on_hand = stock_on_hand - :q, "
                "stock_reserved = stock_reserved - :q, updated_at = :t "
                "WHERE id = :p AND stock_on_hand >= :q "
                "AND stock_reserved >= :q",
                {"p": product["id"], "q": qty, "t": now},
            )
            if rc != 1:
                raise conflict(
                    "insufficient-stock",
                    "Physical stock cannot settle this old payment",
                )
            await tx.execute(
                f"UPDATE {tx.table('liability_partitions')} "
                "SET state = 'consumed', updated_at = :t "
                "WHERE id = :i AND state = 'held'",
                {"i": partition["id"], "t": now},
            )
        else:
            rc = await tx.execute(
                f"UPDATE {tx.table('products')} "
                "SET stock_on_hand = stock_on_hand - :q, updated_at = :t "
                "WHERE id = :p AND (stock_on_hand IS NULL OR stock_on_hand >= :q)",
                {"p": product["id"], "q": qty, "t": now},
            )
            if rc != 1:
                raise conflict(
                    "insufficient-stock",
                    "Physical stock cannot settle this old payment",
                )
        new_status, reason = "paid", "liability-paid"
    else:
        if partition and partition["state"] == "held":
            rc = await tx.execute(
                f"UPDATE {tx.table('products')} "
                "SET stock_reserved = stock_reserved - :q, updated_at = :t "
                "WHERE id = :p AND stock_reserved >= :q",
                {"p": product["id"], "q": qty, "t": now},
            )
            if rc != 1:
                raise conflict(
                    "insufficient-stock",
                    "Stock hold cannot be released cleanly",
                )
            await tx.execute(
                f"UPDATE {tx.table('liability_partitions')} "
                "SET state = 'released', updated_at = :t "
                "WHERE id = :i AND state = 'held'",
                {"i": partition["id"], "t": now},
            )
        new_status, reason = "unpaid_terminal", "liability-unpaid-terminal"
    await tx.execute(
        f"UPDATE {tx.table('imported_liabilities')} SET status = :s "
        "WHERE id = :i",
        {"i": liability["id"], "s": new_status},
    )
    await _mark_reconciling(tx, epoch, now)
    await tx.execute(
        f"INSERT INTO {tx.table('cutover_events')} "
        "(id, epoch_id, state, reason_code, sequence, created_at) "
        "VALUES (:i, :e, :s, :r, :n, :t)",
        {"i": uuid.uuid4().hex, "e": epoch["id"], "s": epoch["state"],
         "r": reason, "n": await _next_event_sequence(tx, epoch["id"]), "t": now},
    )
    return new_status


async def reconcile_liability(
    merchant_id: str, user, epoch_id: str, liability_id: str
) -> dict:
    """Re-check one open liability against the host wallet ledger and apply
    the exactly-once settle/release transition. Runs after freeze —
    ``snapshot_verified``, ``reconciling`` and ``complete`` epochs all allow
    this since holds survive completion."""
    await catalog._merchant_owned(merchant_id, user)
    async with db.connect() as conn:
        epoch = await conn.fetchone(
            f"SELECT import_id, state FROM {table('cutover_epochs')} "
            "WHERE id = :i AND merchant_id = :m",
            {"i": epoch_id, "m": merchant_id},
        )
        if not epoch:
            raise not_found("cutover not found")
        if epoch["state"] not in ("snapshot_verified", "reconciling", "complete"):
            raise conflict("invalid-transition", "Cutover is not reconciling liabilities")
        liability = await conn.fetchone(
            f"SELECT * FROM {table('imported_liabilities')} "
            "WHERE id = :i AND merchant_id = :m AND import_id = :b",
            {"i": liability_id, "m": merchant_id, "b": epoch["import_id"]},
        )
        if not liability:
            raise not_found("liability not found")
        liability = dict(liability)
        if liability["status"] in LIABILITY_TERMINAL:
            return _liability_public(liability)
        payment_hash = _decrypt_invoice_ref(liability)
    paid = await _authoritative_payment_state(str(user.id), payment_hash)
    if paid is None:
        return _liability_public(liability)
    if not (await old_source_status())["disabled"]:
        raise conflict("legacy-active", "Old source is active again")
    now = int(time.time())
    async with DomainTransaction() as tx:
        await tx.fetch_one(
            f"SELECT id FROM {tx.table('merchants')} WHERE id = :m{tx.for_update}",
            {"m": merchant_id},
        )
        epoch_row = await _owned_epoch(tx, merchant_id, epoch_id)
        liability = await _owned_liability(tx, merchant_id, epoch_row, liability_id)
        if liability["status"] in LIABILITY_TERMINAL:
            return _liability_public(liability)
        liability["status"] = await _apply_terminal_status(
            tx, merchant_id, epoch_row, liability, paid, now
        )
    return _liability_public(liability)


async def cutover_reconcile_pass(page_size: int = 50) -> dict:
    """Leased background pass (rides the ``reconciliation`` task lease):
    re-checks open liabilities on snapshot-verified epochs and re-blocks
    any verified epoch whose old source is no longer attested-disabled.
    Bounded pages; every payment lookup error fails closed for that row."""
    checked = reblocked = settled = released = errors = 0
    async with db.connect() as conn:
        epochs = await conn.fetchall(
            f"SELECT e.id, e.merchant_id, e.state, e.import_id, m.user_id "
            f"FROM {table('cutover_epochs')} e "
            f"JOIN {table('merchants')} m ON m.id = e.merchant_id "
            "WHERE e.state IN ('snapshot_verified', 'reconciling', 'complete') "
            "ORDER BY e.created_at LIMIT 20",
        )
    for epoch_row in epochs:
        epoch = dict(epoch_row)
        source = await old_source_status()
        if not (source["disabled"]
                and source["reason_code"] == "snapshot-unverified"):
            reason = (
                "source-reactivated" if not source["disabled"]
                else "source-contract-" + str(source["reason_code"])
            )[:64]
            now = int(time.time())
            async with DomainTransaction() as tx:
                await tx.fetch_one(
                    f"SELECT id FROM {tx.table('merchants')} "
                    f"WHERE id = :m{tx.for_update}",
                    {"m": epoch["merchant_id"]},
                )
                rc = await tx.execute(
                    f"UPDATE {tx.table('cutover_epochs')} "
                    "SET state = 'blocked', updated_at = :t "
                    "WHERE id = :i AND state IN ('snapshot_verified', "
                    "'reconciling', 'ready', 'complete')",
                    {"i": epoch["id"], "t": now},
                )
                if rc == 1:
                    await tx.execute(
                        f"INSERT INTO {tx.table('cutover_events')} "
                        "(id, epoch_id, state, reason_code, sequence, created_at) "
                        "VALUES (:i, :e, 'blocked', :r, :n, :t)",
                        {"i": uuid.uuid4().hex, "e": epoch["id"], "r": reason,
                         "n": await _next_event_sequence(tx, epoch["id"]),
                         "t": now},
                    )
                    reblocked += 1
            continue
        if epoch["state"] == "complete":
            continue
        async with db.connect() as conn:
            liabilities = await conn.fetchall(
                f"SELECT * FROM {table('imported_liabilities')} "
                "WHERE import_id = :i AND merchant_id = :m "
                "AND status IN ('payable', 'waiting', 'partitioned') "
                "ORDER BY created_at, id LIMIT :n",
                {"i": epoch["import_id"], "m": epoch["merchant_id"],
                 "n": page_size},
            )
        for row in liabilities:
            liability = dict(row)
            try:
                paid = await _authoritative_payment_state(
                    epoch["user_id"], _decrypt_invoice_ref(liability)
                )
            except ProblemError:
                errors += 1
                continue
            if paid is None:
                continue
            now = int(time.time())
            async with DomainTransaction() as tx:
                await tx.fetch_one(
                    f"SELECT id FROM {tx.table('merchants')} "
                    f"WHERE id = :m{tx.for_update}",
                    {"m": epoch["merchant_id"]},
                )
                locked_epoch = await tx.fetch_one(
                    f"SELECT * FROM {tx.table('cutover_epochs')} "
                    f"WHERE id = :i AND merchant_id = :m{tx.for_update}",
                    {"i": epoch["id"], "m": epoch["merchant_id"]},
                )
                if (not locked_epoch or locked_epoch["state"] not in (
                        "snapshot_verified", "reconciling", "complete")):
                    continue
                live = await _owned_liability(
                    tx, epoch["merchant_id"], dict(locked_epoch),
                    liability["id"],
                )
                if live["status"] in LIABILITY_TERMINAL:
                    continue
                status = await _apply_terminal_status(
                    tx, epoch["merchant_id"], dict(locked_epoch),
                    live, paid, now,
                )
                if status == "paid":
                    settled += 1
                else:
                    released += 1
                checked += 1
    return {
        "epochs_checked": len(epochs), "reblocked": reblocked,
        "settled": settled, "released": released, "errors": errors,
    }


async def complete_cutover(merchant_id: str, user, epoch_id: str) -> dict:
    """Complete only when every liability is terminal or fully partitioned —
    payable uncovered liabilities block completion; held partitions stay."""
    await catalog._merchant_owned(merchant_id, user)
    source_status = await old_source_status()
    if not source_status["disabled"] or (
            source_status["reason_code"] != "snapshot-unverified"):
        raise conflict("legacy-source", "Old source must remain disabled")
    now = int(time.time())
    async with DomainTransaction() as tx:
        await tx.fetch_one(
            f"SELECT id FROM {tx.table('merchants')} WHERE id = :m{tx.for_update}",
            {"m": merchant_id},
        )
        epoch = await _owned_epoch(tx, merchant_id, epoch_id)
        if epoch["state"] == "complete":
            return _public_epoch(epoch)
        if epoch["state"] not in ("snapshot_verified", "reconciling"):
            raise conflict("invalid-transition", "Cutover cannot complete")
        snapshot_restart = None
        if epoch["snapshot_json"]:
            try:
                from nostr_sdk import Event

                signed_snapshot = Event.from_json(epoch["snapshot_json"])
                if signed_snapshot.verify():
                    snapshot_restart = json.loads(
                        signed_snapshot.content()
                    ).get("restart_checked_at")
            except (RuntimeError, TypeError, ValueError):
                snapshot_restart = None
        if (snapshot_restart is None
                or snapshot_restart != source_status.get("restart_checked_at")):
            # host restarted again or the snapshot was tampered — the epoch's
            # evidence no longer describes this running instance
            raise conflict(
                "legacy-source", "Host restarted since the snapshot was taken"
            )
        open_rows = await tx.fetch_all(
            f"SELECT l.status FROM {tx.table('imported_liabilities')} l "
            f"WHERE l.import_id = :i AND l.merchant_id = :m "
            "AND l.status NOT IN ('paid', 'unpaid_terminal', 'partitioned')",
            {"i": epoch["import_id"], "m": merchant_id},
        )
        if open_rows:
            raise conflict(
                "legacy-liabilities", "Uncovered payable liabilities remain"
            )
        held = await tx.fetch_all(
            f"SELECT part.product_id, SUM(part.quantity) AS qty "
            f"FROM {tx.table('liability_partitions')} part "
            "WHERE part.epoch_id = :e AND part.state = 'held' "
            "GROUP BY part.product_id",
            {"e": epoch_id},
        )
        for row in held:
            product = await tx.fetch_one(
                f"SELECT id, stock_on_hand, stock_reserved "
                f"FROM {tx.table('products')} "
                f"WHERE id = :p AND merchant_id = :m{tx.for_update}",
                {"p": row["product_id"], "m": merchant_id},
            )
            if (not product or product["stock_on_hand"] is None
                    or product["stock_reserved"] < row["qty"]):
                raise conflict(
                    "legacy-liabilities", "Partitioned liabilities lost their hold"
                )
        rc = await tx.execute(
            f"UPDATE {tx.table('cutover_epochs')} SET state = 'complete', "
            "updated_at = :t WHERE id = :i AND state IN "
            "('snapshot_verified', 'reconciling')",
            {"i": epoch_id, "t": now},
        )
        if rc != 1:
            raise conflict("invalid-transition", "Cutover cannot complete")
        await tx.execute(
            f"UPDATE {tx.table('products')} SET import_authorized = TRUE "
            f"WHERE merchant_id = :m AND id IN ("
            f"SELECT product_id FROM {tx.table('import_rows')} "
            "WHERE import_id = :i)",
            {"m": merchant_id, "i": epoch["import_id"]},
        )
        await tx.execute(
            f"INSERT INTO {tx.table('cutover_events')} "
            "(id, epoch_id, state, reason_code, sequence, created_at) "
            "VALUES (:i, :e, 'complete', 'liabilities-covered', :n, :t)",
            {"i": uuid.uuid4().hex, "e": epoch_id,
             "n": await _next_event_sequence(tx, epoch_id), "t": now},
        )
        epoch["state"] = "complete"
    return _public_epoch(epoch)
