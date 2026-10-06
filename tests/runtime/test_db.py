"""DomainTransaction adapter tests (plan 02-01 Task 1).

Covers the section-14 transaction contract without a host boot: a fresh
``Database("ext_infinitemarkets")`` bound to a tmp data folder, m001 applied,
then BEGIN IMMEDIATE commit/rollback/serialization semantics through the
adapter.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest
import pytest_asyncio

pytestmark = [
    pytest.mark.runtime,
    pytest.mark.asyncio(loop_scope="session"),
]


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def ext_db(tmp_path_factory):
    """A fresh extension Database over a tmp file, m001 applied.

    ``Database.__init__`` reads ``settings.lnbits_data_folder`` at
    construction — point it at tmp first so no shared state is touched.
    """
    from lnbits.db import Database
    from lnbits.settings import settings

    folder = tmp_path_factory.mktemp("ext-db")
    previous = settings.lnbits_data_folder
    settings.lnbits_data_folder = str(folder)
    try:
        database = Database("ext_infinitemarkets")
        from infinitemarkets.migrations import m001_initial

        async with database.connect() as conn:
            await m001_initial(conn)
        yield database
    finally:
        settings.lnbits_data_folder = previous


async def test_commit_persists(ext_db):
    from infinitemarkets.db import DomainTransaction

    async with DomainTransaction(ext_db) as tx:
        await tx.execute(
            f"INSERT INTO {tx.table('task_leases')} "
            "(name, holder_id, fencing_token, leased_until, updated_at) "
            "VALUES (:name, :h, 1, 0, 0)",
            {"name": "t-commit", "h": "w1"},
        )
    async with ext_db.connect() as conn:
        row = await conn.fetchone(
            "SELECT * FROM infinitemarkets.task_leases WHERE name = :n",
            {"n": "t-commit"},
        )
    assert row is not None
    assert row["fencing_token"] == 1


async def test_rollback_discards(ext_db):
    from infinitemarkets.db import DomainTransaction

    class Boom(Exception):
        pass

    with pytest.raises(Boom):
        async with DomainTransaction(ext_db) as tx:
            await tx.execute(
                f"INSERT INTO {tx.table('task_leases')} "
                "(name, holder_id, fencing_token, leased_until, updated_at) "
                "VALUES (:name, :h, 1, 0, 0)",
                {"name": "t-rollback", "h": "w1"},
            )
            raise Boom()

    async with ext_db.connect() as conn:
        row = await conn.fetchone(
            "SELECT * FROM infinitemarkets.task_leases WHERE name = :n",
            {"n": "t-rollback"},
        )
    assert row is None


async def test_fencing_update_inside_tx(ext_db):
    """Read-modify-write inside one transaction — the claim pattern."""
    from infinitemarkets.db import DomainTransaction

    async with ext_db.connect() as conn:
        await conn.execute(
            "INSERT INTO infinitemarkets.task_leases "
            "(name, holder_id, fencing_token, leased_until, updated_at) "
            "VALUES (:name, :h, 0, 0, 0)",
            {"name": "t-fence", "h": "w0"},
        )

    async with DomainTransaction(ext_db) as tx:
        row = await tx.fetch_one(
            f"SELECT * FROM {tx.table('task_leases')} WHERE name = :n",
            {"n": "t-fence"},
        )
        updated = await tx.execute(
            f"UPDATE {tx.table('task_leases')} "
            "SET fencing_token = :t, holder_id = :h "
            "WHERE name = :n AND fencing_token = :prev",
            {"t": row["fencing_token"] + 1, "h": "w1", "n": "t-fence",
             "prev": row["fencing_token"]},
        )
        assert updated == 1

    async with ext_db.connect() as conn:
        row = await conn.fetchone(
            "SELECT * FROM infinitemarkets.task_leases WHERE name = :n",
            {"n": "t-fence"},
        )
    assert row["fencing_token"] == 1
    assert row["holder_id"] == "w1"


async def test_concurrent_writers_serialize(ext_db):
    """Two transactions on separate Database handles serialize via SQLite's
    file lock — neither loses its write (busy_timeout) and commits land."""
    from lnbits.db import Database
    from lnbits.settings import settings

    from infinitemarkets.db import DomainTransaction

    # Second handle over the same file (per-worker pattern).
    folder = Path(ext_db.path).parent if hasattr(ext_db, "path") else settings.lnbits_data_folder
    previous = settings.lnbits_data_folder
    settings.lnbits_data_folder = str(folder)
    try:
        other = Database("ext_infinitemarkets")
    finally:
        settings.lnbits_data_folder = previous

    async def write(database, name):
        async with DomainTransaction(database) as tx:
            await tx.execute(
                f"INSERT INTO {tx.table('task_leases')} "
                "(name, holder_id, fencing_token, leased_until, updated_at) "
                "VALUES (:name, '', 0, 0, 0)",
                {"name": name},
            )
            await asyncio.sleep(0.05)

    await asyncio.gather(
        write(ext_db, "t-a"), write(other, "t-b")
    )
    async with ext_db.connect() as conn:
        rows = await conn.fetchall(
            "SELECT name FROM infinitemarkets.task_leases "
            "WHERE name IN ('t-a', 't-b')"
        )
    assert {r["name"] for r in rows} == {"t-a", "t-b"}


async def test_fk_enforced_inside_tx(ext_db):
    """PRAGMA foreign_keys=ON applies on the raw transaction connection."""
    from infinitemarkets.db import DomainTransaction

    async def bad_insert():
        async with DomainTransaction(ext_db) as tx:
            await tx.execute(
                f"INSERT INTO {tx.table('catalogs')} "
                "(id, merchant_id) VALUES (:i, :m)",
                {"i": "c1", "m": "nonexistent-merchant"},
            )

    with pytest.raises(Exception):
        await bad_insert()


async def test_domain_transaction_allows_separate_read_connection(ext_db):
    from infinitemarkets.db import DomainTransaction

    async def transaction_with_read():
        async with DomainTransaction(ext_db) as tx:
            await tx.fetch_one(f"SELECT COUNT(*) AS n FROM {tx.table('task_leases')}")
            async with ext_db.connect() as conn:
                row = await conn.fetchone("SELECT COUNT(*) AS n FROM infinitemarkets.task_leases")
            assert row["n"] >= 0

    await asyncio.wait_for(transaction_with_read(), timeout=3)


async def test_cancelled_transaction_entry_releases_sqlite_lock(ext_db, monkeypatch):
    from lnbits.db import SQLITE

    if ext_db.type != SQLITE:
        pytest.skip("SQLite-specific BEGIN IMMEDIATE cancellation drill")
    import aiosqlite

    from infinitemarkets.db import DomainTransaction

    execute = aiosqlite.Connection.execute

    async def cancel_after_begin(conn, sql, parameters=None):
        cursor = await execute(conn, sql, parameters)
        if sql == "BEGIN IMMEDIATE":
            raise asyncio.CancelledError()
        return cursor

    with monkeypatch.context() as patch:
        patch.setattr(aiosqlite.Connection, "execute", cancel_after_begin)
        with pytest.raises(asyncio.CancelledError):
            async with DomainTransaction(ext_db):
                pytest.fail("cancelled entry must not yield a transaction")
    async with DomainTransaction(ext_db) as tx:
        assert await tx.fetch_one("SELECT 1 AS available") == {"available": 1}


async def test_checkout_safety_upgrade_preserves_financial_values(ext_db):
    from infinitemarkets.db import DomainTransaction
    from infinitemarkets.migrations import m002_orders, m003_checkout_safety

    async with ext_db.connect() as conn:
        await m002_orders(conn)
    async with DomainTransaction(ext_db) as tx:
        await tx.execute(
            f"INSERT INTO {tx.table('merchants')}"
            " (id, user_id, pubkey, key_ref, wallet_id_enc, wallet_id_hash)"
            " VALUES ('upgrade', 'upgrade', 'upgrade', 'upgrade', :wallet, 'upgrade')",
            {"wallet": b"opaque-wallet"},
        )
        await tx.execute(
            f"INSERT INTO {tx.table('catalogs')} (id, merchant_id) VALUES ('upgrade', 'upgrade')"
        )
        for currency in ("SAT", "USD", "JPY", "KWD", "ZZZ"):
            await tx.execute(
                f"INSERT INTO {tx.table('shipping_options')}"
                " (id, merchant_id, d_tag, currency, base_price_minor, service)"
                " VALUES (:c, 'upgrade', :c, :c, 550, 'shipping')", {"c": currency},
            )
            await tx.execute(
                f"INSERT INTO {tx.table('products')}"
                " (id, merchant_id, catalog_id, d_tag, product_type, format,"
                " amount_minor, currency, stock_on_hand)"
                " VALUES (:c, 'upgrade', 'upgrade', :c, 'simple', 'physical', 123, :c, 7)",
                {"c": currency},
            )
        await tx.execute(
            f"INSERT INTO {tx.table('orders')} (id, merchant_id, protocol, state, total_sat)"
            " VALUES ('upgrade', 'upgrade', 'web', 'completed', 12345)"
        )
    async with ext_db.connect() as conn:
        await m003_checkout_safety(conn)
    async with DomainTransaction(ext_db) as tx:
        for currency, decimals in {"SAT": 0, "USD": 2, "JPY": 0, "KWD": 3, "ZZZ": 2}.items():
            product = await tx.fetch_one(
                f"SELECT * FROM {tx.table('products')} WHERE id = :c", {"c": currency},
            )
            option = await tx.fetch_one(
                f"SELECT * FROM {tx.table('shipping_options')} WHERE id = :c", {"c": currency},
            )
            assert product["currency_decimals"] == option["currency_decimals"] == decimals
            assert product["amount_minor"] == 123
            assert product["stock_on_hand"] == 7
            assert option["base_price_minor"] == 550
        order = await tx.fetch_one(
            f"SELECT total_sat FROM {tx.table('orders')} WHERE id = 'upgrade'"
        )
        assert order["total_sat"] == 12345


async def test_categories_upgrade_keeps_products_and_publication_history(tmp_path):
    from lnbits.db import Database
    from lnbits.settings import settings

    from infinitemarkets.migrations import m001_initial, m009_categories

    previous = settings.lnbits_data_folder
    settings.lnbits_data_folder = str(tmp_path)
    try:
        database = Database(f"ext_upgrade_{uuid.uuid4().hex[:12]}")
        async with database.connect() as conn:
            s = conn.references_schema
            await m001_initial(conn)
            await conn.execute(
                f"INSERT INTO {s}merchants "
                "(id, user_id, pubkey, key_ref, wallet_id_enc, wallet_id_hash) "
                "VALUES ('merchant', 'user', 'pubkey', 'key', :wallet, 'hash')",
                {"wallet": b"opaque-wallet"},
            )
            await conn.execute(
                f"INSERT INTO {s}catalogs "
                "(id, merchant_id, name) VALUES ('original', 'merchant', 'Main Catalog')"
            )
            await conn.execute(
                f"INSERT INTO {s}products "
                "(id, merchant_id, catalog_id, d_tag, product_type, format) "
                "VALUES ('product', 'merchant', 'original', 'product', 'simple', 'digital')"
            )
            await conn.execute(
                f"INSERT INTO {s}outbox_events "
                "(id, merchant_id, aggregate_type, aggregate_id, aggregate_revision, "
                "event_kind, state, attempts, next_attempt_at, claim_token, "
                "created_at, updated_at) VALUES "
                "('intent', 'merchant', 'catalogs', 'original', 0, 30017, "
                "'pending', 0, 0, 0, 0, 0)"
            )
            await conn.execute(
                f"INSERT INTO {s}protocol_addresses "
                "(id, domain_type, domain_id, protocol, event_kind, author_pubkey, d_tag) "
                "VALUES ('address', 'catalogs', 'original', 'nip15', 30017, "
                "'pubkey', 'stall')"
            )
            await conn.execute(
                f"INSERT INTO {s}relay_publications "
                "(id, outbox_event_id, delivery_copy, relay_url, event_id, "
                "attempt_no, result, attempted_at) VALUES "
                "('receipt', 'intent', 'public', 'wss://relay.example', "
                "'event', 1, 'ok', 1)"
            )
            await m009_categories(conn)
            category = await conn.fetchone(
                f"SELECT name, public_slug FROM {s}categories WHERE id = 'original'"
            )
            product = await conn.fetchone(
                f"SELECT category_id FROM {s}products WHERE id = 'product'"
            )
            intent = await conn.fetchone(
                f"SELECT aggregate_type, aggregate_id FROM {s}outbox_events "
                "WHERE id = 'intent'"
            )
            address = await conn.fetchone(
                f"SELECT domain_type, domain_id FROM {s}protocol_addresses "
                "WHERE id = 'address'"
            )
            publication = await conn.fetchone(
                f"SELECT outbox_event_id, event_id, result FROM {s}relay_publications "
                "WHERE id = 'receipt'"
            )
            assert category["name"] == "Main Catalog"
            assert category["public_slug"] and category["public_slug"] != "original"
            assert product["category_id"] == "original"
            assert intent["aggregate_type"] == "categories"
            assert intent["aggregate_id"] == "original"
            assert address["domain_type"] == "categories"
            assert address["domain_id"] == "original"
            assert publication == {"outbox_event_id": "intent", "event_id": "event", "result": "ok"}
    finally:
        settings.lnbits_data_folder = previous
