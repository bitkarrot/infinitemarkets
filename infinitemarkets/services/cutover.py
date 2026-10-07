from __future__ import annotations

import time
import uuid

from lnbits.core.crud.extensions import get_installed_extension
from lnbits.settings import settings as host_settings

from ..db import DomainTransaction, db, table
from ..security import conflict, not_found
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
    return {"disabled": True, "reason_code": "snapshot-unverified"}


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
