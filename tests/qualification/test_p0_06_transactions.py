"""P0-06: transaction/fencing/last-unit/FK evidence (QUAL-06).

Executable models for spec sections 8.2 (step 1), 14 (transaction adapter,
idempotency, multi-worker behavior), 4.12/4.16 (FKs, task leases), and 7.1
(the order state machine with order_events audit rows).

Covers:

(a) last-unit concurrency: N parallel buyers each claiming the final unit of
    a finite-stock product through the section 8.2 step-1 conditional UPDATE
    inside one adapter transaction — exactly one winner, stock_reserved
    equals stock_on_hand at most, all losers rolled back with no partial rows
    (SQLite: BEGIN IMMEDIATE serialization; PostgreSQL: concurrent
    connections with row locking);
(b) deadlock avoidance: two concurrent multi-item claims locking products in
    opposite insertion order both complete (sorted-id locking per section 8.2);
(c) rollback completeness: a failed guard mid multi-item claim rolls back
    stock increments, reservation rows, and order transitions atomically;
(d) host auto-commit splitting: the host's auto-committing helper commits the
    open domain transaction mid-flight, so its row — AND the domain rows
    written so far — survive the intended rollback; the adapter alone rolls
    back cleanly, and the adapter never calls the host helpers in-transaction;
(e) fencing: task_leases fencing_token is monotonically increasing; a stale
    fenced write affects zero rows and is rejected, the current-token write
    succeeds;
(f) SQLite FK enforcement: orphan inserts into inventory_reservations,
    order_items, and relay_publications fail;
(g) idempotency: UNIQUE-scope duplicate order inserts conflict rather than
    double-inserting (check-then-insert is never used, section 14);

plus the exhaustive section 7.1 legal/illegal transition table with
order_events audit rows (section 17 state-machine test requirement).

Runs on the selected profile dialect (SQLite locally; the four blocking
profiles run it in CI per D-03).
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid

import pytest

from harness import db as db_module
from harness import state, tx

pytestmark = [pytest.mark.db, pytest.mark.fast]

RESERVATION_EXPIRES_AT = 1_800_000_000
N_BUYERS = 6


async def _seed(qual_db, *, product_id: str, on_hand: int, order_id: str, state_: str):
    """Seed one product and one order (test setup, not a model path)."""
    async with qual_db.connect() as conn:
        async with qual_db.transaction(conn) as t:
            await t.execute(
                f"INSERT INTO {qual_db.table('products')}"
                " (id, merchant_id, stock_on_hand, stock_reserved)"
                " VALUES (:id, :m, :h, 0)",
                {"id": product_id, "m": "merchant-1", "h": on_hand},
            )
            await t.execute(
                f"INSERT INTO {qual_db.table('orders')}"
                " (id, merchant_id, state) VALUES (:id, :m, :s)",
                {"id": order_id, "m": "merchant-1", "s": state_},
            )


async def _reservations(qual_db) -> list[dict]:
    return await qual_db.fetch_all(
        f"SELECT * FROM {qual_db.table('inventory_reservations')}"
    )


async def _product(qual_db, product_id: str) -> dict:
    rows = await qual_db.fetch_all(
        f"SELECT stock_on_hand, stock_reserved FROM {qual_db.table('products')}"
        " WHERE id = :id",
        {"id": product_id},
    )
    assert rows, "seeded product must exist"
    return rows[0]


async def _order_state(qual_db, order_id: str) -> str:
    rows = await qual_db.fetch_all(
        f"SELECT state FROM {qual_db.table('orders')} WHERE id = :id",
        {"id": order_id},
    )
    assert rows, f"order {order_id} must exist"
    return rows[0]["state"]


async def _order_events(qual_db, order_id: str) -> list[dict]:
    return await qual_db.fetch_all(
        f"SELECT * FROM {qual_db.table('order_events')} WHERE order_id = :id"
        " ORDER BY created_at, id",
        {"id": order_id},
    )


async def _claim_final_unit(worker, *, product_id: str, order_id: str):
    """One buyer's section 8.2 step-1 attempt on the worker's own connection."""
    await tx.claim_and_reserve(
        worker,
        product_id=product_id,
        qty=1,
        order_id=order_id,
        reservation_id=f"res-{order_id}",
        expires_at=RESERVATION_EXPIRES_AT,
    )


# --- (tracer scope, kept): the one-transaction step-1 shape -------------------


async def test_winning_cas_leaves_one_held_reservation(qual_db_factory):
    async with qual_db_factory() as qual_db:
        await _seed(
            qual_db, product_id="p1", on_hand=5, order_id="o1", state_="received"
        )
        await tx.claim_and_reserve(
            qual_db,
            product_id="p1",
            qty=2,
            order_id="o1",
            reservation_id="r1",
            expires_at=RESERVATION_EXPIRES_AT,
        )
        product = await _product(qual_db, "p1")
        assert product["stock_reserved"] == 2
        assert product["stock_on_hand"] == 5
        reservations = await _reservations(qual_db)
        assert len(reservations) == 1
        reservation = reservations[0]
        assert reservation["state"] == "held"
        assert reservation["quantity"] == 2
        assert reservation["expires_at"] == RESERVATION_EXPIRES_AT
        assert await _order_state(qual_db, "o1") == "invoice_pending"
        # Section 7.1: the transition wrote its order_events audit row in the
        # same transaction.
        events = await _order_events(qual_db, "o1")
        assert len(events) == 1
        assert events[0]["from_state"] == "received"
        assert events[0]["to_state"] == "invoice_pending"


async def test_lost_cas_rolls_back_the_entire_transaction(qual_db_factory):
    async with qual_db_factory() as qual_db:
        # Order already advanced past 'received' -> the CAS must lose.
        await _seed(
            qual_db,
            product_id="p1",
            on_hand=5,
            order_id="o1",
            state_="invoice_pending",
        )
        with pytest.raises(tx.SagaConflict):
            await tx.claim_and_reserve(
                qual_db,
                product_id="p1",
                qty=2,
                order_id="o1",
                reservation_id="r1",
                expires_at=RESERVATION_EXPIRES_AT,
            )
        # The claim executed inside the transaction, but the CAS loss rolled
        # back EVERYTHING: stock_reserved unchanged, no reservation row.
        product = await _product(qual_db, "p1")
        assert product["stock_reserved"] == 0
        assert await _reservations(qual_db) == []
        assert await _order_events(qual_db, "o1") == []


# --- (a) last-unit concurrency ------------------------------------------------


async def test_last_unit_concurrency_yields_exactly_one_reservation(qual_db_factory):
    """N parallel buyers race for the final unit: exactly one wins.

    Each buyer runs the section 8.2 step-1 claim through its own Database
    handle (own connection): SQLite serializes writers via BEGIN IMMEDIATE
    file locks, PostgreSQL via row locking. Losers must lose COMPLETELY — no
    partial stock increment, reservation, transition, or audit row survives.
    """
    async with qual_db_factory() as qual_db:
        async with qual_db.connect() as conn:
            async with qual_db.transaction(conn) as t:
                await t.execute(
                    f"INSERT INTO {qual_db.table('products')}"
                    " (id, merchant_id, stock_on_hand, stock_reserved)"
                    " VALUES ('p1', 'merchant-1', 1, 0)",
                )
                for i in range(N_BUYERS):
                    await t.execute(
                        f"INSERT INTO {qual_db.table('orders')}"
                        " (id, merchant_id, state) VALUES (:id, 'merchant-1',"
                        " 'received')",
                        {"id": f"buyer-{i}"},
                    )

        # One worker Database per buyer (own engine + asyncio lock), all over
        # the same SQLite file / PostgreSQL schema.
        workers = [qual_db] + [qual_db.worker() for _ in range(N_BUYERS - 1)]
        buyer_ids = [f"buyer-{i}" for i in range(N_BUYERS)]
        results = await asyncio.gather(
            *(
                _claim_final_unit(worker, product_id="p1", order_id=order_id)
                for worker, order_id in zip(workers, buyer_ids, strict=True)
            ),
            return_exceptions=True,
        )

        successes = [r for r in results if not isinstance(r, Exception)]
        failures = [r for r in results if isinstance(r, Exception)]
        # Exactly one buyer wins the last unit; every other buyer lost the
        # conditional stock guard and rolled back completely.
        assert len(successes) == 1
        assert len(failures) == N_BUYERS - 1
        for failure in failures:
            assert isinstance(failure, tx.SagaConflict), (
                f"loser must fail with SagaConflict, got {failure!r}"
            )

        # Exactly one held reservation for the single unit on hand.
        reservations = await _reservations(qual_db)
        assert len(reservations) == 1
        assert reservations[0]["state"] == "held"
        assert reservations[0]["quantity"] == 1
        winner_order = reservations[0]["order_id"]
        assert winner_order in buyer_ids

        product = await _product(qual_db, "p1")
        assert product["stock_reserved"] == 1
        assert product["stock_on_hand"] == 1
        # stock_reserved never exceeds stock_on_hand (section 4.3 invariant).
        assert product["stock_reserved"] <= product["stock_on_hand"]

        # The winner advanced with exactly one audit row; every loser is
        # untouched in 'received' with no reservation and no audit row.
        for order_id in buyer_ids:
            if order_id == winner_order:
                assert await _order_state(qual_db, order_id) == "invoice_pending"
                assert len(await _order_events(qual_db, order_id)) == 1
                continue
            assert await _order_state(qual_db, order_id) == "received"
            assert await _order_events(qual_db, order_id) == []


# --- (b) deadlock avoidance ---------------------------------------------------


async def test_sorted_id_locking_avoids_deadlock(qual_db_factory):
    """Concurrent multi-item claims in opposite insertion order both complete.

    Products are claimed in sorted id order (section 8.2), so two workers
    whose carts list the same products in opposite user order cannot
    deadlock: they serialize on the first (lowest-id) product row. The pause
    hooks force the interleaving that WOULD deadlock if the claim order
    followed cart order; wait_for turns a real deadlock into a loud timeout
    instead of a hang (T-02-03).
    """
    async with qual_db_factory() as qual_db:
        async with qual_db.connect() as conn:
            async with qual_db.transaction(conn) as t:
                for pid in ("pa", "pb"):
                    await t.execute(
                        f"INSERT INTO {qual_db.table('products')}"
                        " (id, merchant_id, stock_on_hand, stock_reserved)"
                        " VALUES (:id, :m, 10, 0)",
                        {"id": pid, "m": "merchant-1"},
                    )
                for oid in ("oa", "ob"):
                    await t.execute(
                        f"INSERT INTO {qual_db.table('orders')}"
                        " (id, merchant_id, state) VALUES (:id, :m, 'received')",
                        {"id": oid, "m": "merchant-1"},
                    )

        first_claimed = {"oa": asyncio.Event(), "ob": asyncio.Event()}

        def make_hook(order_id: str):
            async def hook(product_id: str) -> None:
                # Signal after the first (sorted) claim, then briefly wait
                # for the other worker's first claim to force interleaving.
                if product_id == "pa":
                    first_claimed[order_id].set()
                    with contextlib.suppress(asyncio.TimeoutError):
                        await asyncio.wait_for(
                            first_claimed[
                                "ob" if order_id == "oa" else "oa"
                            ].wait(),
                            timeout=0.3,
                        )

            return hook

        async def run(worker, order_id: str, items: list[dict]):
            await tx.claim_and_reserve_multi(
                worker,
                items=items,
                order_id=order_id,
                expires_at=RESERVATION_EXPIRES_AT,
                pause_hook=make_hook(order_id),
            )

        # Worker A's cart lists pa then pb; worker B's lists pb then pa
        # (opposite insertion order). Sorted-id locking must serialize both
        # to completion instead of deadlocking.
        worker_a = qual_db
        worker_b = qual_db.worker()
        await asyncio.wait_for(
            asyncio.gather(
                run(
                    worker_a,
                    "oa",
                    [
                        {"product_id": "pa", "qty": 2, "reservation_id": "ra-a"},
                        {"product_id": "pb", "qty": 2, "reservation_id": "rb-a"},
                    ],
                ),
                run(
                    worker_b,
                    "ob",
                    [
                        {"product_id": "pb", "qty": 3, "reservation_id": "rb-b"},
                        {"product_id": "pa", "qty": 3, "reservation_id": "ra-b"},
                    ],
                ),
            ),
            timeout=15,
        )

        assert await _order_state(qual_db, "oa") == "invoice_pending"
        assert await _order_state(qual_db, "ob") == "invoice_pending"
        for pid, expected in (("pa", 5), ("pb", 5)):
            product = await _product(qual_db, pid)
            assert product["stock_reserved"] == expected
            assert product["stock_reserved"] <= product["stock_on_hand"]
        reservations = await _reservations(qual_db)
        assert len(reservations) == 4  # two per order, both orders complete


# --- (c) rollback completeness -------------------------------------------------


async def test_guard_failure_mid_claim_rolls_back_everything(qual_db_factory):
    """A lost guard on the SECOND item rolls back the FIRST item's claim too."""
    async with qual_db_factory() as qual_db:
        await _seed(qual_db, product_id="p1", on_hand=5, order_id="o1", state_="received")
        async with qual_db.connect() as conn:
            async with qual_db.transaction(conn) as t:
                await t.execute(
                    f"INSERT INTO {qual_db.table('products')}"
                    " (id, merchant_id, stock_on_hand, stock_reserved)"
                    " VALUES ('p2', :m, 3, 0)",
                    {"m": "merchant-1"},
                )
        with pytest.raises(tx.SagaConflict):
            await tx.claim_and_reserve_multi(
                qual_db,
                items=[
                    {"product_id": "p1", "qty": 2, "reservation_id": "r1"},
                    {"product_id": "p2", "qty": 5, "reservation_id": "r2"},
                ],
                order_id="o1",
                expires_at=RESERVATION_EXPIRES_AT,
            )
        # The first item's stock increment, both reservations, the order
        # transition, and the audit row all rolled back atomically.
        assert (await _product(qual_db, "p1"))["stock_reserved"] == 0
        assert (await _product(qual_db, "p2"))["stock_reserved"] == 0
        assert await _reservations(qual_db) == []
        assert await _order_state(qual_db, "o1") == "received"
        assert await _order_events(qual_db, "o1") == []


# --- (d) host auto-commit splitting proof --------------------------------------


async def test_adapter_only_transaction_rolls_back_cleanly(qual_db_factory):
    """Control for the splitting proof: without host helpers, rollback works."""
    async with qual_db_factory() as qual_db:
        leases = qual_db.table("task_leases")
        async with qual_db.connect() as conn:
            with pytest.raises(RuntimeError):
                async with qual_db.transaction(conn) as t:
                    await t.execute(
                        f"INSERT INTO {leases}"
                        " (name, holder_id, fencing_token, leased_until, updated_at)"
                        " VALUES ('adapter-control', 'w', 1, 99, 1)",
                    )
                    raise RuntimeError("force rollback")
        rows = await qual_db.fetch_all(
            f"SELECT * FROM {leases} WHERE name = 'adapter-control'"
        )
        assert rows == []


async def test_host_auto_commit_helper_splits_domain_transaction(qual_db_factory):
    """The host's auto-committing helper tears the domain transaction open.

    Section 14 forbids calling ``Connection.execute/insert/update`` inside a
    domain transaction because each one auto-commits. Executable proof: open
    a domain transaction, write a domain row through the adapter, then make
    one host-helper write. The helper's implicit commit lands while the
    domain transaction is open, so BOTH rows survive the rollback the domain
    transaction then attempts — the helper's row because it auto-committed,
    and the domain row because that auto-commit tore the open transaction
    (SQLite ``BEGIN IMMEDIATE`` / PostgreSQL ``conn.begin()``) open mid-flight.
    Rollback can no longer restore atomicity: precisely the forbidden split.
    """
    async with qual_db_factory() as qual_db:
        leases = qual_db.table("task_leases")
        async with qual_db.connect() as conn:
            t = qual_db.transaction(conn)
            await t.__aenter__()
            try:
                await t.execute(
                    f"INSERT INTO {leases}"
                    " (name, holder_id, fencing_token, leased_until, updated_at)"
                    " VALUES ('adapter-write', 'w', 1, 99, 1)",
                )
                # The forbidden pattern (section 14): a host auto-committing
                # helper invoked inside the open domain transaction.
                await conn.execute(
                    f"INSERT INTO {leases}"
                    " (name, holder_id, fencing_token, leased_until, updated_at)"
                    " VALUES ('helper-write', 'host', 1, 99, 1)",
                )
            finally:
                # The domain transaction attempts its rollback. SQLAlchemy may
                # or may not raise on the externally-committed transaction
                # object (1.4 closes it silently); either way the database
                # state below is the evidence.
                with contextlib.suppress(Exception):
                    await t.rollback()

        helper_rows = await qual_db.fetch_all(
            f"SELECT * FROM {leases} WHERE name = 'helper-write'"
        )
        adapter_rows = await qual_db.fetch_all(
            f"SELECT * FROM {leases} WHERE name = 'adapter-write'"
        )
        # The helper-written row survived the domain rollback: the helper
        # committed outside the domain transaction's control.
        assert len(helper_rows) == 1
        # The domain write ALSO survived: the helper's implicit commit tore
        # the open transaction open, destroying rollback atomicity.
        assert len(adapter_rows) == 1


async def test_adapter_performs_in_transaction_writes_without_host_helpers(
    qual_db_factory, monkeypatch
):
    """The adapter never calls the host's auto-committing helpers in-transaction.

    Mechanically proven by replacing ``Connection.execute/insert/update``
    (the host helpers, NOT the SQLAlchemy ``conn.conn`` the adapter uses)
    with raising stubs for the duration of a full adapter transaction.
    """
    async with qual_db_factory() as qual_db:
        await _seed(
            qual_db, product_id="p1", on_hand=5, order_id="o1", state_="received"
        )
        async with qual_db.connect() as conn:

            def forbidden(name: str):
                async def _fail(*args, **kwargs):
                    raise AssertionError(
                        f"host auto-committing helper {name!r} was called "
                        "inside a domain transaction (section 14)"
                    )

                return _fail

            # Patch the INSTANCES (this open Connection, and the Database
            # wrapper that would open a new one) rather than the class: the
            # host's own connect/teardown paths legitimately use its helpers
            # OUTSIDE domain transactions (e.g. CREATE SCHEMA on connect).
            for target in (conn, qual_db.database):
                monkeypatch.setattr(target, "execute", forbidden("execute"))
                monkeypatch.setattr(target, "insert", forbidden("insert"))
                monkeypatch.setattr(target, "update", forbidden("update"))
            async with qual_db.transaction(conn) as t:
                await t.execute(
                    f"INSERT INTO {qual_db.table('task_leases')}"
                    " (name, holder_id, fencing_token, leased_until, updated_at)"
                    " VALUES ('pure', 'w', 1, 99, 1)",
                )
                rows = await t.fetch_all(
                    f"SELECT * FROM {qual_db.table('task_leases')}"
                    " WHERE name = 'pure'"
                )
                assert len(rows) == 1
        # The adapter transaction committed through raw SQLAlchemy / the raw
        # aiosqlite connection only — no forbidden helper fired.


# --- (e) task-lease fencing -----------------------------------------------------


async def test_task_lease_fencing_rejects_stale_writes(qual_db_factory):
    """task_leases fencing_token: monotonic, stale writes affect zero rows."""
    async with qual_db_factory() as qual_db:
        leases = qual_db.table("task_leases")
        now = 1_000_000

        async def acquire(holder: str, at: int, ttl: int = 60) -> int:
            async with qual_db.connect() as conn:
                async with qual_db.transaction(conn) as t:
                    return await tx.acquire_lease(
                        t, leases, name="outbox-publish", holder=holder,
                        now=at, ttl_seconds=ttl,
                    )

        token_a1 = await acquire("worker-a", now)
        assert token_a1 == 1

        # A live lease held by another worker cannot be taken over.
        with pytest.raises(tx.LeaseHeld):
            await acquire("worker-b", now + 10)

        # A fenced write with the current token succeeds (lease renewal).
        async with qual_db.connect() as conn:
            async with qual_db.transaction(conn) as t:
                await tx.fenced_write(
                    t, leases,
                    "leased_until = :until, updated_at = :now",
                    {"key": "outbox-publish", "fencing_token": token_a1,
                     "until": now + 120, "now": now + 30},
                )

        # Lease expiry: worker B takes over with a strictly higher token.
        token_b = await acquire("worker-b", now + 130)
        assert token_b > token_a1  # monotonically increasing fencing token

        # Worker A's now-stale fenced write affects ZERO rows and is rejected.
        with pytest.raises(tx.StaleFencingToken):
            async with qual_db.connect() as conn:
                async with qual_db.transaction(conn) as t:
                    await tx.fenced_write(
                        t, leases,
                        "leased_until = :until, updated_at = :now",
                        {"key": "outbox-publish", "fencing_token": token_a1,
                         "until": now + 999, "now": now + 140},
                    )
        holder = await qual_db.fetch_all(
            f"SELECT holder_id, fencing_token FROM {leases}"
            " WHERE name = 'outbox-publish'"
        )
        assert holder[0]["holder_id"] == "worker-b"
        assert holder[0]["fencing_token"] == token_b

        # The current-token write still succeeds after the stale rejection.
        async with qual_db.connect() as conn:
            async with qual_db.transaction(conn) as t:
                await tx.fenced_write(
                    t, leases,
                    "leased_until = :until, updated_at = :now",
                    {"key": "outbox-publish", "fencing_token": token_b,
                     "until": now + 200, "now": now + 150},
                )


# --- (f) FK enforcement ---------------------------------------------------------


@pytest.mark.parametrize(
    ("table", "params"),
    [
        ("inventory_reservations", {"product_id": "no-such-product", "order_id": "o1"}),
        ("inventory_reservations", {"product_id": "p1", "order_id": "no-such-order"}),
        ("order_items", {"order_id": "no-such-order", "product_id": "p1"}),
        ("order_items", {"order_id": "o1", "product_id": "no-such-product"}),
        ("relay_publications", {"outbox_event_id": "no-such-outbox-row"}),
    ],
)
async def test_orphan_inserts_violate_foreign_keys(qual_db_factory, table, params):
    async with qual_db_factory() as qual_db:
        await _seed(
            qual_db, product_id="p1", on_hand=5, order_id="o1", state_="received"
        )
        # A valid outbox_events parent for the relay_publications case.
        async with qual_db.connect() as conn:
            async with qual_db.transaction(conn) as t:
                await t.execute(
                    f"INSERT INTO {qual_db.table('outbox_events')}"
                    " (id, merchant_id, aggregate_type, aggregate_id,"
                    "  event_kind, state)"
                    " VALUES ('ox1', 'merchant-1', 'product', 'p1', 30402, 'pending')",
                )
        inserts = {
            "inventory_reservations": (
                f"INSERT INTO {qual_db.table('inventory_reservations')}"
                " (id, product_id, order_id, quantity, state, expires_at)"
                " VALUES (:id, :product_id, :order_id, 1, 'held', 99)"
            ),
            "order_items": (
                f"INSERT INTO {qual_db.table('order_items')}"
                " (id, order_id, product_id, product_d, title, quantity,"
                "  unit_price_minor, currency, currency_decimals, line_total_sat)"
                " VALUES (:id, :order_id, :product_id, 'd', 't', 1, 100,"
                " 'SAT', 0, 100)"
            ),
            "relay_publications": (
                f"INSERT INTO {qual_db.table('relay_publications')}"
                " (id, outbox_event_id, delivery_copy, relay_url, event_id,"
                "  attempt_no, result, attempted_at)"
                " VALUES (:id, :outbox_event_id, 'public', 'wss://r.example',"
                " 'e1', 1, 'accepted', 99)"
            ),
        }
        with pytest.raises(Exception) as exc_info:
            async with qual_db.connect() as conn:
                async with qual_db.transaction(conn) as t:
                    await t.execute(
                        inserts[table],
                        {"id": f"orphan-{uuid.uuid4().hex[:8]}", **params},
                    )
        # sqlite3.IntegrityError and sqlalchemy.exc.IntegrityError both
        # surface the type name IntegrityError.
        assert "IntegrityError" in type(exc_info.value).__name__
        # No orphan row was written (the failed insert rolled back).
        rows = await qual_db.fetch_all(f"SELECT * FROM {qual_db.table(table)}")
        assert rows == []


# --- (g) idempotency: UNIQUE scope, never check-then-insert ----------------------


async def _insert_scoped_order(
    qual_db,
    *,
    order_id: str,
    buyer_hash: str,
    external_hash: str,
    request_hash: str,
):
    """Section 8.1 step 8's order insert (single transaction; UNIQUE scope)."""
    async with qual_db.connect() as conn:
        async with qual_db.transaction(conn) as t:
            await t.execute(
                f"INSERT INTO {qual_db.table('orders')}"
                " (id, merchant_id, state, buyer_pubkey_hash, external_id_hash,"
                "  request_hash)"
                " VALUES (:id, 'merchant-1', 'received', :b, :e, :r)",
                {"id": order_id, "b": buyer_hash, "e": external_hash, "r": request_hash},
            )


async def test_duplicate_scoped_order_insert_conflicts(qual_db_factory):
    """Same (merchant, buyer, external id) scope: the UNIQUE index conflicts.

    A duplicate is rejected by the UNIQUE constraint — never double-inserted
    — which is why check-then-insert is unnecessary (section 14).
    """
    async with qual_db_factory() as qual_db:
        await _insert_scoped_order(
            qual_db,
            order_id="o1",
            buyer_hash="buyer-h1",
            external_hash="ext-h1",
            request_hash="req-h1",
        )
        with pytest.raises(Exception) as exc_info:
            await _insert_scoped_order(
                qual_db,
                order_id="o2",
                buyer_hash="buyer-h1",
                external_hash="ext-h1",
                request_hash="req-h1",
            )
        assert "IntegrityError" in type(exc_info.value).__name__
        rows = await qual_db.fetch_all(
            f"SELECT id FROM {qual_db.table('orders')}"
            " WHERE external_id_hash = 'ext-h1'"
        )
        assert [r["id"] for r in rows] == ["o1"]


async def test_concurrent_duplicate_scoped_order_inserts_yield_one_row(
    qual_db_factory,
):
    """Two parallel intake transactions with the same scope: exactly one row.

    The UNIQUE partial index (section 4.19) makes the loser fail with a
    constraint violation — the section 14 no-check-then-insert guarantee
    under concurrency.
    """
    async with qual_db_factory() as qual_db:
        worker_b = qual_db.worker()

        async def insert(worker, order_id: str):
            async with worker.connect() as conn:
                async with worker.transaction(conn) as t:
                    await t.execute(
                        f"INSERT INTO {worker.table('orders')}"
                        " (id, merchant_id, state, buyer_pubkey_hash,"
                        "  external_id_hash, request_hash)"
                        " VALUES (:id, 'merchant-1', 'received', 'buyer-h1',"
                        "  'ext-h1', 'req-h1')",
                        {"id": order_id},
                    )

        results = await asyncio.gather(
            insert(qual_db, "o-first"),
            insert(worker_b, "o-second"),
            return_exceptions=True,
        )
        conflicts = [r for r in results if isinstance(r, Exception)]
        assert len(conflicts) == 1
        assert "IntegrityError" in type(conflicts[0]).__name__
        rows = await qual_db.fetch_all(
            f"SELECT id FROM {worker_b.table('orders')}"
            " WHERE external_id_hash = 'ext-h1'"
        )
        assert len(rows) == 1


async def test_idempotency_record_scope_conflict(qual_db_factory):
    """idempotency_records: same scope, different request hash -> conflict.

    Section 14/4.15: key reuse with another hash is a conflict (409), not a
    replay; first request claims the row by unique insert before creating an
    order.
    """
    async with qual_db_factory() as qual_db:
        records = qual_db.table("idempotency_records")

        async def insert_record(request_hash: str, order_id: str | None):
            async with qual_db.connect() as conn:
                async with qual_db.transaction(conn) as t:
                    await t.execute(
                        f"INSERT INTO {records}"
                        " (scope_hash, request_hash, state, order_id, owner_id,"
                        "  created_at, expires_at)"
                        " VALUES ('scope-1', :r, 'in_progress', :o, 'user-1',"
                        "  1000, 9000)",
                        {"r": request_hash, "o": order_id},
                    )

        await insert_record("req-hash-1", "o1")
        with pytest.raises(Exception) as exc_info:
            await insert_record("req-hash-2", "o2")
        assert "IntegrityError" in type(exc_info.value).__name__
        rows = await qual_db.fetch_all(
            f"SELECT request_hash, order_id FROM {records} WHERE scope_hash = 'scope-1'"
        )
        assert len(rows) == 1
        assert rows[0]["request_hash"] == "req-hash-1"
        assert rows[0]["order_id"] == "o1"


# --- section 7.1 exhaustive transition table ------------------------------------


async def test_order_state_machine_table_exhaustive(qual_db_factory):
    """Every (from, to) pair against the section 7.1 table, with audit rows.

    Section 17 state-machine test requirement: legal pairs transition and
    write exactly one order_events row in the same transaction; illegal
    pairs raise IllegalTransition and leave the order and its audit log
    untouched; a lost CAS raises TransitionConflict.
    """
    async with qual_db_factory() as qual_db:
        legal_pairs = {
            (frm, to)
            for frm, targets in state.ORDER_TRANSITIONS.items()
            for to in targets
        }
        checked = 0
        for from_state in state.ORDER_STATES:
            for to_state in state.ORDER_STATES:
                order_id = f"o-{from_state}-{to_state}"
                async with qual_db.connect() as conn:
                    async with qual_db.transaction(conn) as t:
                        await t.execute(
                            f"INSERT INTO {qual_db.table('orders')}"
                            " (id, merchant_id, state) VALUES (:id, 'm', :s)",
                            {"id": order_id, "s": from_state},
                        )
                checked += 1
                if (from_state, to_state) in legal_pairs:
                    requires_reason = state.order_transition_requires_reason(
                        from_state, to_state
                    )
                    if requires_reason:
                        # A required reason must be enforced.
                        with pytest.raises(state.IllegalTransition):
                            await state.transition_order_isolated(
                                qual_db,
                                order_id=order_id,
                                from_state=from_state,
                                to_state=to_state,
                            )
                    await state.transition_order_isolated(
                        qual_db,
                        order_id=order_id,
                        from_state=from_state,
                        to_state=to_state,
                        reason="merchant-verified late-settlement accept"
                        if requires_reason
                        else None,
                        actor="merchant" if requires_reason else "system",
                    )
                    assert await _order_state(qual_db, order_id) == to_state
                    events = await _order_events(qual_db, order_id)
                    assert len(events) == 1
                    assert events[0]["from_state"] == from_state
                    assert events[0]["to_state"] == to_state
                else:
                    with pytest.raises(state.IllegalTransition):
                        await state.transition_order_isolated(
                            qual_db,
                            order_id=order_id,
                            from_state=from_state,
                            to_state=to_state,
                            reason="reason does not legalize an illegal pair",
                        )
                    assert await _order_state(qual_db, order_id) == from_state
                    assert await _order_events(qual_db, order_id) == []
        assert checked == len(state.ORDER_STATES) ** 2

        # Terminal states never leave (completed/rejected have no outgoing).
        for terminal in state.ORDER_TERMINAL_STATES:
            assert state.ORDER_TRANSITIONS[terminal] == frozenset()

        # A lost CAS raises TransitionConflict (a SagaConflict) with no event.
        await _seed(
            qual_db, product_id="pc", on_hand=1, order_id="oc", state_="awaiting_payment"
        )
        with pytest.raises(tx.SagaConflict):
            await state.transition_order_isolated(
                qual_db,
                order_id="oc",
                from_state="received",  # wrong expected state -> CAS loses
                to_state="invoice_pending",
            )
        assert await _order_state(qual_db, "oc") == "awaiting_payment"
        assert await _order_events(qual_db, "oc") == []


# --- dialect surface ------------------------------------------------------------


def test_dialect_selection_matches_environment():
    """The dialect switch is LNBITS_DATABASE_URL-driven (D-03 evidence)."""
    assert db_module.dialect_name() in ("sqlite", "postgres")
    assert db_module.is_postgres() == (db_module.dialect_name() == "postgres")
