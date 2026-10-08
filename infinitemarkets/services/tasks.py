"""Worker registry — spec section 10.

``infinitemarkets_start`` registers exactly the handles this module owns;
``infinitemarkets_stop`` cancels them via ``register_owned_task`` tracking.
Every worker loop is cancellation-safe (try/finally, owned resources
closed).

Lease discipline (§10): ``reservation_expiry``, ``reconciliation``, and
``retention_pruner`` acquire/renew their ``task_leases`` row before each
pass; loss of lease stops work immediately, and every leased write carries
the fencing token. ``email_sender`` and ``outbox_publisher`` need no task
lease — the per-row claim-token CAS is their fencing. ``relay_manager``
runs per-worker unleased (each worker owns its own Client).

The invoice listener registers through
``task_manager.register_invoice_listener`` — an unfiltered fan-out, so the
callback self-filters (§8.3); delivery is memory-only, which is why the
leased reconciliation pass is mandatory for payment truth.
"""

from __future__ import annotations

import asyncio
import uuid

from loguru import logger

OUTBOX_INTERVAL_S = 5
RELAY_TICK_INTERVAL_S = 30
EMAIL_INTERVAL_S = 5
INBOX_INTERVAL_S = 5
RESERVATION_EXPIRY_INTERVAL_S = 30
RECONCILE_INTERVAL_S = 60
RETENTION_INTERVAL_S = 86400
# §9.3: buyer kind-10050 sets for no-route order_msg intents re-resolve
# on a 15-min cadence (the outbox parks them at the same interval).
PEER_RELAY_REFRESH_INTERVAL_S = 15 * 60

LEASE_TTL_S = 120

WORKER_ID = f"worker-{uuid.uuid4().hex[:8]}"


async def _acquire_lease(name: str, ttl: int = LEASE_TTL_S) -> int | None:
    """Acquire or renew a §4.16 task lease; returns the fencing token or
    None when another worker holds a live lease."""
    from ..db import DomainTransaction

    async with DomainTransaction() as tx:
        now = await tx.now()
        rc = await tx.execute(
            f"UPDATE {tx.table('task_leases')} SET holder_id = :h,"
            " fencing_token = fencing_token + 1, leased_until = :u,"
            " updated_at = :n"
            " WHERE name = :name AND (leased_until <= :n OR holder_id = :h)",
            {
                "name": name, "h": WORKER_ID, "n": now, "u": now + ttl,
            },
        )
        if rc == 1:
            row = await tx.fetch_one(
                f"SELECT fencing_token FROM {tx.table('task_leases')}"
                " WHERE name = :name",
                {"name": name},
            )
            return int(row["fencing_token"]) if row else None
        try:
            await tx.execute(
                f"INSERT INTO {tx.table('task_leases')} "
                "(name, holder_id, fencing_token, leased_until, updated_at)"
                " VALUES (:name, :h, 1, :u, :n)",
                {"name": name, "h": WORKER_ID, "n": now, "u": now + ttl},
            )
            return 1
        except Exception:  # noqa: BLE001 — IntegrityError across dialects
            return None


def _now() -> int:
    import time

    return int(time.time())


async def _run_leased(name: str, token: int, operation):
    from ..db import ACTIVE_TASK_LEASE, DomainTransaction

    context = ACTIVE_TASK_LEASE.set((name, WORKER_ID, token))
    try:
        async with DomainTransaction():
            pass
        result = await operation()
        async with DomainTransaction() as tx:
            if name == "reconciliation":
                await tx.execute(
                    f"INSERT INTO {tx.table('task_leases')} "
                    "(name, holder_id, fencing_token, leased_until, updated_at) "
                    "VALUES ('reconciliation_complete', :h, :t, 0, :n) "
                    "ON CONFLICT (name) DO UPDATE SET holder_id = :h,"
                    " fencing_token = :t, updated_at = :n",
                    {"h": WORKER_ID, "t": token, "n": await tx.now()},
                )
        return result
    finally:
        ACTIVE_TASK_LEASE.reset(context)


async def outbox_publisher() -> None:
    """§8.6 publisher loop — claim, build-from-current-state, sign, send,
    persist per-relay evidence."""
    from . import outbox

    while True:
        try:
            result = await outbox.worker_tick(WORKER_ID)
            if result["claimed"]:
                logger.debug(
                    f"infinitemarkets outbox: claimed={result['claimed']} "
                    f"recovered={result['recovered']} "
                    f"outcomes={result['outcomes']}"
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(f"infinitemarkets outbox tick failed: {type(exc).__name__}")
        await asyncio.sleep(OUTBOX_INTERVAL_S)


async def relay_manager() -> None:
    """Health tick — converge the owned transport's connection set to the
    configured public relays. Per-worker, unleased (see module docstring)."""
    from . import relay as relay_service
    from .transport import transport

    while True:
        try:
            targets = await relay_service.all_public_targets()
            tport = transport()
            if tport.client is None:
                await tport.start(targets)
            else:
                await tport.sync_relays(targets)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(f"infinitemarkets relay tick failed: {type(exc).__name__}")
        await asyncio.sleep(RELAY_TICK_INTERVAL_S)


async def email_sender() -> None:
    """§8.8 worker loop — claim-fenced rows; per-worker Database handle."""
    from ..db import worker_db
    from . import email as email_service

    wdb = worker_db()
    try:
        while True:
            try:
                await email_service.recover_stale_claims(database=wdb)
                result = await email_service.worker_tick(
                    WORKER_ID, database=wdb
                )
                if result["claimed"]:
                    logger.debug(
                        f"infinitemarkets email: claimed={result['claimed']}"
                        f" outcomes={result['outcomes']}"
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(f"infinitemarkets email tick failed: {type(exc).__name__}")
            await asyncio.sleep(EMAIL_INTERVAL_S)
    finally:
        await wdb.engine.dispose()


async def inbox_processor() -> None:
    """§8.5/§10 leased drain — 'received' inbox_events run the section-8.5
    chain and land at 'validated' (domain dispatch is 03-02's seam)."""
    from . import inbox as inbox_service

    while True:
        try:
            token = await _acquire_lease("inbox_processor")
            if token is not None:
                report = await _run_leased(
                    "inbox_processor", token,
                    inbox_service.drain_and_process,
                )
                if any(report.values()):
                    logger.debug(
                        f"infinitemarkets inbox drain: {report}"
                    )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                f"infinitemarkets inbox drain failed: {type(exc).__name__}"
            )
        await asyncio.sleep(INBOX_INTERVAL_S)


async def inbox_listener() -> None:
    """§9.2 inbox supervisor — converges kind-1059 sessions to merchants
    with ``inbox_state='active'``. With zero active merchants it stays
    idle (the runtime holds no sockets); cursor commits happen only
    after EOSE + durable admission (see services/inbox.py)."""
    from .inbox import inbox_runtime

    while True:
        try:
            await inbox_runtime().reconcile()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                f"infinitemarkets inbox tick failed: {type(exc).__name__}"
            )
        await asyncio.sleep(INBOX_INTERVAL_S)


async def reservation_expiry() -> None:
    """§8.4 expiry loop (30s, leased): expired held reservations release
    exactly once; expired invoices take the §8.4 path."""
    from . import settlement

    while True:
        try:
            token = await _acquire_lease("reservation_expiry")
            if token is not None:
                result = await _run_leased(
                    "reservation_expiry", token, settlement.reservation_expiry_pass,
                )
                if result["released"] or result["expired_orders"]:
                    logger.debug(
                        f"infinitemarkets reservation expiry:"
                        f" released={result['released']}"
                        f" expired_orders={result['expired_orders']}"
                    )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                f"infinitemarkets reservation expiry tick failed: {type(exc).__name__}"
            )
        await asyncio.sleep(RESERVATION_EXPIRY_INTERVAL_S)


async def reconciliation() -> None:
    """§8.7 pass — runs once immediately (startup reconciliation gates
    checkout readiness), then every 60s under the task lease. The §9.3
    peer-relay refresh/no-route sweep rides the same lease every 15 min."""
    from ..db import DomainTransaction, db, table
    from . import peer_relays, readiness, settlement

    first = True
    started_at = None
    last_peer_refresh = 0.0
    while True:
        try:
            if started_at is None:
                async with DomainTransaction() as tx:
                    started_at = await tx.now()
            token = await _acquire_lease("reconciliation")
            if token is not None:
                report = await _run_leased("reconciliation", token, settlement.reconcile)
                if any(report.values()):
                    logger.debug(f"infinitemarkets reconcile: {report}")
                now_mono = _now()
                if now_mono - last_peer_refresh >= PEER_RELAY_REFRESH_INTERVAL_S:
                    last_peer_refresh = now_mono
                    stats = await peer_relays.refresh_stale_peer_relays()
                    if any(stats.values()):
                        logger.debug(
                            f"infinitemarkets peer-relay refresh: {stats}"
                        )
                if first:
                    readiness.mark_reconciled()
                    first = False
            elif first:
                # Another worker holds the lease — readiness still flips
                # once that worker completes its first pass; poll again
                # quickly rather than waiting the full interval.
                async with db.connect() as conn:
                    completed = await conn.fetchone(
                        f"SELECT updated_at FROM {table('task_leases')}"
                        " WHERE name = 'reconciliation_complete'",
                    )
                if completed and completed["updated_at"] >= started_at:
                    readiness.mark_reconciled()
                    first = False
                else:
                    await asyncio.sleep(5)
                    continue
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(f"infinitemarkets reconcile tick failed: {type(exc).__name__}")
            await asyncio.sleep(5)
            continue
        await asyncio.sleep(RECONCILE_INTERVAL_S)


async def retention_pruner() -> None:
    """§11.3 daily retention pass (leased)."""
    from . import settlement

    while True:
        try:
            token = await _acquire_lease("retention_pruner",
                                       ttl=LEASE_TTL_S * 4)
            if token is not None:
                report = await _run_leased("retention_pruner", token, settlement.retention_prune)
                if any(report.values()):
                    logger.debug(f"infinitemarkets retention: {report}")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                f"infinitemarkets retention tick failed: {type(exc).__name__}"
            )
        await asyncio.sleep(RETENTION_INTERVAL_S)


def start_workers() -> list[asyncio.Task]:
    """Register owned tasks through the host task manager; returns the
    handles so infinitemarkets_start can track them for stop."""
    from lnbits.tasks import task_manager

    from . import settlement

    handles = []
    listener = task_manager.register_invoice_listener(
        settlement.invoice_listener, name="infinitemarkets"
    )
    handles.append(listener.task)
    for func, name in (
        (outbox_publisher, "infinitemarkets_outbox"),
        (relay_manager, "infinitemarkets_relay_manager"),
        (inbox_listener, "infinitemarkets_inbox_listener"),
        (inbox_processor, "infinitemarkets_inbox_processor"),
        (email_sender, "infinitemarkets_email_sender"),
        (reservation_expiry, "infinitemarkets_reservation_expiry"),
        (reconciliation, "infinitemarkets_reconciliation"),
        (retention_pruner, "infinitemarkets_retention_pruner"),
    ):
        handle = task_manager.create_task(func(), name=name)
        handles.append(handle.task)
    return handles
