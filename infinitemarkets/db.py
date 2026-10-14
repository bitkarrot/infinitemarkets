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

import asyncio
import time
import weakref
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


_IN_DOMAIN_TX: ContextVar[bool] = ContextVar("im_in_domain_tx", default=False)


class _ExtDatabase(Database):
    """Shared-handle guard: db.connect() inside an active
    DomainTransaction can lock-invert (tx holds the file's write lock,
    the nested connect waits on this handle's asyncio.Lock which may be
    held by a task waiting on that write lock) — deadlock. On sqlite the
    in-tx path must ride the transaction's own connection instead.
    """

    @asynccontextmanager
    async def connect(self):
        if self.type == SQLITE and _IN_DOMAIN_TX.get():
            from loguru import logger

            logger.warning(
                "infinitemarkets: db.connect() inside an active "
                "DomainTransaction — pass conn=tx instead"
            )
        async with super().connect() as conn:
            yield conn


db = _ExtDatabase("ext_infinitemarkets")

#: Tasks currently inside a DomainTransaction — diagnostic for lock
#: contention ("database is locked"): who holds the writer.
_ACTIVE_TX: dict[int, tuple[str, float]] = {}


def active_transactions() -> dict[int, tuple[str, float]]:
    """{task id: (coroutine name, entered_at epoch)} — for debugging."""
    return dict(_ACTIVE_TX)


def worker_db() -> Database:
    """A separate ``Database`` handle over the same extension database.

    ``Database.connect()`` serializes on a per-object lock, so every
    concurrent worker (outbox publisher, email sender, ...) owns its own
    handle — same file on SQLite, same schema on PostgreSQL.
    """
    wdb = Database("ext_infinitemarkets")
    _register_sqlite_pragmas(wdb)
    return wdb


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


#: Engines already carrying pragma listeners — a WeakSet so a disposed
#: worker engine's id() can never be mistaken for a live registration
#: (ids recycle; workers create+dispose an engine every tick).
_PRAGMAS_ENGINES: "weakref.WeakSet" = weakref.WeakSet()


def _register_sqlite_pragmas(database: Database | None = None) -> None:
    """Attach per-connection pragmas to a host engine (SQLite only).

    DomainTransaction holds ``BEGIN IMMEDIATE`` writes on its own raw
    connection — without a busy timeout, every ``db.connect()`` write
    elsewhere (e.g. the public rate-limiter upsert) fails instantly with
    "database is locked" instead of waiting the transaction out. The
    engine ``connect`` listener covers all future physical connections
    — including the pooled host connections that bypass this module's
    helper. Each ``Database`` handle owns its own engine, so worker_db()
    registers too.
    """
    database = database or db
    if database.type != SQLITE:
        return
    engine = database.engine.sync_engine
    if engine in _PRAGMAS_ENGINES:
        return
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _set_conn_pragmas(dbapi_conn, _rec):
        cur = dbapi_conn.cursor()
        try:
            # WAL: readers never block the writer and a writer never
            # blocks readers — only writer↔writer still serializes (with
            # busy_timeout covering the wait). Persists on the db file.
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA busy_timeout=15000")
        finally:
            cur.close()

    _PRAGMAS_ENGINES.add(engine)


@asynccontextmanager
async def connect() -> AsyncIterator[Connection]:
    """Host connection for single-statement reads/writes (auto-commit).

    Foreign-key enforcement is per-connection on SQLite — enabled here so
    every consumer of this helper gets it.
    """
    _register_sqlite_pragmas()
    async with db.connect() as conn:
        if db.type == SQLITE:
            await _raw_sqlite(conn).execute("PRAGMA foreign_keys=ON")
        yield conn


# db.engine exists from Database.__init__ — registering at import covers
# every connection this engine ever makes (pooled host path included).
_register_sqlite_pragmas()


def _raw_sqlite(conn: Connection):
    """The raw aiosqlite connection behind a host Connection."""
    return (
        conn.conn.sync_connection.connection.dbapi_connection._connection  # noqa: SLF001
    )


def released_product_clause(ref: str, table_fn) -> str:
    """SQL predicate — always true. Imported products are ordinary drafts:
    the cutover/attestation gate was removed, so nothing blocks a row on
    ``import_source_kind``. Kept at call sites so the predicate signature
    is stable and queries stay readable."""
    return "1 = 1"


def released_product_select(ref: str, table_fn) -> str:
    """SELECT fragment — ``import_released`` is always true now."""
    return "1 AS import_released"


def effective_stock_select(ref: str, table_fn) -> str:
    """SELECT fragment — ``eff_on_hand``/``eff_reserved`` columns where a
    ``variable`` parent's stock is the live sum over its non-deleted
    variation children (parents never carry sellable units of their own).
    Other rows pass through their own columns. Emitted under distinct
    aliases so ``SELECT *`` callers keep raw values too — readers prefer
    the ``eff_`` columns when present."""
    return (
        f"(CASE WHEN {ref}.product_type = 'variable' THEN ("
        f"SELECT SUM(v.stock_on_hand) FROM {table_fn('products')} v "
        f"WHERE v.parent_product_id = {ref}.id AND v.deleted_at IS NULL"
        f") ELSE {ref}.stock_on_hand END) AS eff_on_hand, "
        f"(CASE WHEN {ref}.product_type = 'variable' THEN ("
        f"SELECT SUM(v.stock_reserved) FROM {table_fn('products')} v "
        f"WHERE v.parent_product_id = {ref}.id AND v.deleted_at IS NULL"
        f") ELSE {ref}.stock_reserved END) AS eff_reserved"
    )


def effective_stock(row: dict) -> tuple:
    """Read the ``eff_*`` columns when a query emitted them, else the row's
    own stock columns."""
    on_hand = (
        row["eff_on_hand"]
        if "eff_on_hand" in row
        else row.get("stock_on_hand")
    )
    reserved = (
        row["eff_reserved"]
        if "eff_reserved" in row
        else row.get("stock_reserved")
    )
    return on_hand, (reserved or 0)


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
        self._tx_ctx = None
        self._fence = ACTIVE_TASK_LEASE.get()

    async def __aenter__(self) -> "DomainTransaction":
        try:
            if self._dialect == "sqlite":
                import aiosqlite

                self._raw = await aiosqlite.connect(self._db.path)
                await self._raw.execute("PRAGMA journal_mode=WAL")
                await self._raw.execute("PRAGMA foreign_keys=ON")
                await self._raw.execute("PRAGMA busy_timeout=15000")
                await self._raw.execute("BEGIN IMMEDIATE")
            else:
                cm = self._db.engine.connect()
                raw = await cm.__aenter__()
                self._host_conn_cm = cm
                self._conn = Connection(raw, self._db.type, self._db.name, self._db.schema)
                self._pg_tx = await raw.begin()
                await self.execute(f"SET LOCAL search_path TO {SCHEMA}, public")
            await self._check_fence()
            if self._dialect == "sqlite":
                self._tx_ctx = _IN_DOMAIN_TX.set(True)
            try:
                task = asyncio.current_task()
                coro = task.get_coro() if task else None
                _ACTIVE_TX[id(task)] = (
                    getattr(coro, "__qualname__", "unknown"), time.time()
                )
            except Exception:
                pass
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

    @property
    def for_no_key_update(self) -> str:
        return " FOR NO KEY UPDATE" if self._dialect == "postgres" else ""

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
            if self._tx_ctx is not None:
                _IN_DOMAIN_TX.reset(self._tx_ctx)
            try:
                _ACTIVE_TX.pop(id(asyncio.current_task()), None)
            except Exception:
                pass
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

    # Host-Connection spellings — a DomainTransaction passed as ``conn``
    # into helpers written against db.connect() semantics must answer
    # identically; otherwise those helpers open a second connection to
    # the same file and self-deadlock on sqlite (busy_timeout cannot
    # resolve a task waiting on its own lock).
    fetchone = fetch_one
    fetchall = fetch_all
