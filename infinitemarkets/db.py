"""Extension database handle + section-14 transaction adapter.

Conventions (verified against the pinned host, e336fe1):

- ``Database("ext_infinitemarkets")`` maps to the ``infinitemarkets`` schema on
  PostgreSQL and to ``<data>/ext_infinitemarkets.sqlite3`` on SQLite — where the
  host ``connect()`` also ATTACHes that same file under the ``infinitemarkets``
  alias, so ``infinitemarkets.<table>`` resolves on the host connection too.
- ``Connection.execute``/``insert``/``update`` auto-commit. Domain writes that
  span statements MUST go through :func:`domain_tx` — never the helpers.
- On SQLite the host connection cannot run ``BEGIN IMMEDIATE`` (the same file
  is attached twice — verified harness finding), so domain transactions open
  a dedicated raw aiosqlite connection to the same file. SQLite file locking
  still serializes writers.
- ``db.connect()`` serializes through one asyncio.Lock per Database object:
  concurrent workers call :func:`worker_db` for their own handle.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import AsyncIterator

from lnbits.db import COCKROACH, POSTGRES, SQLITE, Connection, Database

SCHEMA = "infinitemarkets"
ACTIVE_TASK_LEASE: ContextVar[tuple[str, str, int] | None] = ContextVar(
    "infinitemarkets_task_lease", default=None,
)


class LeaseLostError(RuntimeError):
    pass


db = Database("ext_infinitemarkets")


def worker_db() -> Database:
    """A separate ``Database`` handle over the same extension database.

    ``Database.connect()`` serializes on a per-object lock, so every
    concurrent worker (outbox publisher, email sender, ...) owns its own
    handle — same file on SQLite, same schema on PostgreSQL.
    """
    return Database("ext_infinitemarkets")


def table(name: str) -> str:
    """Schema-qualified table reference for host-connection SQL.

    ``infinitemarkets.<name>`` resolves on both dialects: a real schema on
    PostgreSQL, the ATTACH alias on SQLite.
    """
    return f"{SCHEMA}.{name}"


def dialect() -> str:
    if db.type == POSTGRES:
        return "postgres"
    if db.type == COCKROACH:
        return "cockroachdb"
    return "sqlite"


def topology() -> str:
    """Deployment topology per spec section 14 / decision 15."""
    return dialect()


def topology_supported() -> tuple[bool, str | None]:
    """Refuse unsupported topologies (section 14).

    SQLite is single-process only; CockroachDB is not a v1 target. SQLite
    multi-process is not detectable from inside the process — the extension
    refuses only what it can prove (documented residual).
    """
    if dialect() == "cockroachdb":
        return False, "cockroachdb is not a supported v1 topology"
    return True, None


@asynccontextmanager
async def connect() -> AsyncIterator[Connection]:
    """Host connection for single-statement reads/writes (auto-commit).

    Foreign-key enforcement is per-connection on SQLite — enabled here so
    every consumer of this helper gets it.
    """
    async with db.connect() as conn:
        if db.type == SQLITE:
            await _raw_sqlite(conn).execute("PRAGMA foreign_keys=ON")
        yield conn


def _raw_sqlite(conn: Connection):
    """The raw aiosqlite connection behind a host Connection."""
    return (
        conn.conn.sync_connection.connection.dbapi_connection._connection  # noqa: SLF001
    )


def released_product_clause(ref: str, table_fn) -> str:
    """SQL predicate — True when a product is not a cutover-blocked import.

    ``ref`` is the product table alias/name usable inside the predicate.
    Imported rows stay blocked until a ``complete`` epoch covers their
    import; ``import_authorized`` alone is never sufficient. ``table_fn``
    qualifies names per dialect (``db.table`` outside, ``tx.table`` inside).
    """
    return (
        f"({ref}.import_source_kind IS NULL OR EXISTS ("
        f"SELECT 1 FROM {table_fn('import_rows')} r "
        f"JOIN {table_fn('catalog_imports')} ci ON ci.id = r.import_id "
        f"AND ci.merchant_id = {ref}.merchant_id "
        f"JOIN {table_fn('cutover_epochs')} e ON e.import_id = r.import_id "
        f"AND e.merchant_id = ci.merchant_id AND e.state = 'complete' "
        f"WHERE r.product_id = {ref}.id))"
    )


def released_product_select(ref: str, table_fn) -> str:
    """SELECT fragment — ``import_released`` bool for dict-based checks."""
    return (
        f"EXISTS (SELECT 1 FROM {table_fn('import_rows')} r "
        f"JOIN {table_fn('catalog_imports')} ci ON ci.id = r.import_id "
        f"AND ci.merchant_id = {ref}.merchant_id "
        f"JOIN {table_fn('cutover_epochs')} e ON e.import_id = r.import_id "
        f"AND e.merchant_id = ci.merchant_id AND e.state = 'complete' "
        f"WHERE r.product_id = {ref}.id) AS import_released"
    )


class DomainTransaction:
    """One section-14 domain transaction: explicit begin/commit/rollback.

    - PostgreSQL: ``conn.conn.begin()`` on a host ``Database.connect()``
      context; tables referenced schema-qualified (``infinitemarkets.x``).
    - SQLite: a dedicated raw aiosqlite connection to the extension file with
      ``BEGIN IMMEDIATE``; tables referenced unqualified (the file's ``main``
      schema is the extension database). The host connection's double-attach
      makes ``BEGIN IMMEDIATE`` fail there — this raw connection is the
      verified path.
    """

    def __init__(self, database: Database | None = None) -> None:
        self._db = database or db
        self._dialect = dialect() if database is None else (
            "postgres"
            if database.type == POSTGRES
            else "cockroachdb"
            if database.type == COCKROACH
            else "sqlite"
        )
        self._host_conn_cm = None
        self._pg_tx = None
        self._raw = None
        self._fence = ACTIVE_TASK_LEASE.get()

    async def __aenter__(self) -> "DomainTransaction":
        try:
            if self._dialect == "sqlite":
                import aiosqlite

                self._raw = await aiosqlite.connect(self._db.path)
                await self._raw.execute("PRAGMA foreign_keys=ON")
                await self._raw.execute("PRAGMA busy_timeout=5000")
                await self._raw.execute("BEGIN IMMEDIATE")
            else:
                cm = self._db.engine.connect()
                raw = await cm.__aenter__()
                self._host_conn_cm = cm
                self._conn = Connection(raw, self._db.type, self._db.name, self._db.schema)
                self._pg_tx = await raw.begin()
                await self.execute(f"SET LOCAL search_path TO {SCHEMA}, public")
            await self._check_fence()
            return self
        except BaseException as exc:
            if self._raw is not None:
                await self._raw.close()
            if self._host_conn_cm is not None:
                await self._host_conn_cm.__aexit__(type(exc), exc, exc.__traceback__)
            raise

    @property
    def for_update(self) -> str:
        return " FOR UPDATE" if self._dialect == "postgres" else ""

    async def now(self) -> int:
        expression = (
            "CAST(strftime('%s', 'now') AS INTEGER)" if self._dialect == "sqlite"
            else "FLOOR(EXTRACT(EPOCH FROM clock_timestamp()))"
        )
        row = await self.fetch_one(f"SELECT {expression} AS epoch")
        return int(row["epoch"])

    async def _check_fence(self) -> None:
        if self._fence is None:
            return
        name, holder, token = self._fence
        rc = await self.execute(
            f"UPDATE {self.table('task_leases')} SET fencing_token = fencing_token"
            " WHERE name = :n AND holder_id = :h AND fencing_token = :t AND leased_until > :now",
            {"n": name, "h": holder, "t": token, "now": await self.now()},
        )
        if rc != 1:
            raise LeaseLostError(f"task lease lost: {name}")

    async def __aexit__(self, exc_type, exc, tb) -> None:
        try:
            if exc_type is None:
                await self.commit()
            else:
                await self.rollback()
        finally:
            if self._raw is not None:
                await self._raw.close()
            if self._host_conn_cm is not None:
                await self._host_conn_cm.__aexit__(None, None, None)
        return None

    def table(self, name: str) -> str:
        """Table reference inside this transaction (schema on PG, bare on
        the raw SQLite connection)."""
        return f"{SCHEMA}.{name}" if self._dialect != "sqlite" else name

    async def commit(self) -> None:
        await self._check_fence()
        if self._raw is not None:
            await self._raw.commit()
        elif self._pg_tx is not None:
            await self._pg_tx.commit()

    async def rollback(self) -> None:
        if self._raw is not None:
            await self._raw.rollback()
        elif self._pg_tx is not None:
            await self._pg_tx.rollback()

    async def execute(self, sql: str, params: dict | None = None) -> int:
        """Execute one raw parameterized statement; return the rowcount."""
        if self._raw is not None:
            cursor = await self._raw.execute(sql, params or {})
            return cursor.rowcount
        from sqlalchemy.sql import text

        result = await self._conn.conn.execute(text(sql), params or {})
        return result.rowcount

    async def fetch_all(
        self, sql: str, params: dict | None = None
    ) -> list[dict]:
        if self._raw is not None:
            cursor = await self._raw.execute(sql, params or {})
            columns = [d[0] for d in cursor.description]
            rows = await cursor.fetchall()
            return [dict(zip(columns, row)) for row in rows]
        from sqlalchemy.sql import text

        result = await self._conn.conn.execute(text(sql), params or {})
        return [dict(row) for row in result.mappings().all()]

    async def fetch_one(
        self, sql: str, params: dict | None = None
    ) -> dict | None:
        rows = await self.fetch_all(sql, params)
        return rows[0] if rows else None
