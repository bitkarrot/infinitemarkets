"""Runtime install fixtures — the REAL host discovery path.

Unlike the qualification probes (which mount fixture routers inside a host
app), these tests exercise the actual extension lifecycle:

    LNBITS_EXTENSIONS_PATH/extensions/infinitemarkets/config.json
        -> build_all_installed_extensions_list (from_ext_dir)
        -> migrate_extension_database (m001)
        -> register_ext_routes (imports ``infinitemarkets``)
        -> register_ext_tasks (calls ``infinitemarkets_start`` synchronously)

The extension directory is a symlink to the repo package — same files, real
loader. ``INFINITEMARKETS_*`` env is set before the lifespan startup so the
sync start hook's strict validation passes.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

REPO_ROOT = Path(__file__).resolve().parents[2]
PKG_DIR = REPO_ROOT / "infinitemarkets"

CANONICAL_ORIGIN = "https://shop.example"


def pytest_collection_modifyitems(items):
    for item in items:
        if item.path.is_relative_to(Path(__file__).parent) and pytest_asyncio.is_async_test(item):
            item.add_marker(pytest.mark.asyncio(loop_scope="session"), append=False)


@pytest_asyncio.fixture(scope="module", loop_scope="session", autouse=True)
async def _isolated_postgres_schema():
    from lnbits.core.db import db as core_db
    from lnbits.db import POSTGRES

    if core_db.type != POSTGRES:
        yield
        return
    async with core_db.connect() as conn:
        existing = await conn.fetchone(
            "SELECT nspname FROM pg_namespace WHERE nspname = 'infinitemarkets'"
        )
    if existing:
        raise RuntimeError(
            "Runtime tests require a disposable database without a infinitemarkets schema"
        )
    try:
        yield
    finally:
        module = sys.modules.get("infinitemarkets.db")
        if module is not None:
            await module.db.engine.dispose()
        async with core_db.connect() as conn:
            await conn.execute("DROP SCHEMA IF EXISTS infinitemarkets CASCADE")

_EXT_ENV = {
    "INFINITEMARKETS_MASTER_KEYS": json.dumps(
        {"v1": base64.b64encode(b"k" * 32).decode()}
    ),
    "INFINITEMARKETS_ACTIVE_KEY_VERSION": "v1",
    "INFINITEMARKETS_PRIVACY_KEY": base64.b64encode(b"p" * 32).decode(),
    "INFINITEMARKETS_PUBLIC_BASE_URL": CANONICAL_ORIGIN,
    # Never dial real relays from a host-boot test — workers stay live
    # (claim/evidence paths exercised) but the transport never connects.
    "INFINITEMARKETS_RELAY_IO": "off",
}

_RUNTIME_SETTINGS_KEYS = (
    "lnbits_data_folder",
    "lnbits_backend_wallet_class",
    "lnbits_extensions_path",
    "lnbits_extensions_deactivate_all",
    "lnbits_admin_ui",
    "first_install",
    # OQ3 qualified posture: audit capture off for infinitemarkets tests
    "lnbits_audit_log_request_body",
    "lnbits_audit_log_query_params",
    "lnbits_audit_log_path_params",
)


@asynccontextmanager
async def _runtime_app(data_folder: Path, ext_root: Path):
    """Boot the pinned host with the real extension-discovery path.

    Mirrors harness.host.host_app (chdir into the checkout, FakeWallet,
    isolated data folder) but with ``lnbits_extensions_path`` pointed at a
    tmp dir whose ``extensions/infinitemarkets`` is a symlink to the repo
    package, and ``lnbits_extensions_deactivate_all = False`` so the real
    restore/registration path activates the extension.
    """
    from asgi_lifespan import LifespanManager
    from lnbits.app import create_app
    from lnbits.core.models.users import UpdateSuperuserPassword
    from lnbits.core.views.auth_api import first_install
    from lnbits.settings import settings

    from tools.checkout_host import host_checkout_dir

    snapshot = {key: getattr(settings, key) for key in _RUNTIME_SETTINGS_KEYS}
    previous_cwd = Path.cwd()
    env_snapshot = {k: os.environ.get(k) for k in _EXT_ENV}

    extensions_dir = ext_root / "extensions"
    extensions_dir.mkdir(parents=True)
    link = extensions_dir / "infinitemarkets"
    if not link.exists():
        link.symlink_to(PKG_DIR, target_is_directory=True)

    os.environ.update(_EXT_ENV)
    settings.lnbits_data_folder = str(data_folder)
    settings.lnbits_backend_wallet_class = "FakeWallet"
    settings.lnbits_extensions_path = str(ext_root)
    settings.lnbits_extensions_deactivate_all = False
    settings.lnbits_admin_ui = True
    settings.first_install = True
    # Qualified audit posture (OQ3): no path/query/body capture.
    settings.lnbits_audit_log_request_body = False
    settings.lnbits_audit_log_query_params = False
    settings.lnbits_audit_log_path_params = False

    # The extension module must not be pre-imported: ``Database.__init__``
    # binds the SQLite path at construction, and the host's migration loader
    # uses whatever module object is in sys.modules. Purge any earlier
    # import so the boot binds this run's data folder.
    for mod in [
        m for m in sys.modules
        if m == "infinitemarkets" or m.startswith("infinitemarkets.")
    ]:
        del sys.modules[mod]

    # The core DB (.cache/qual-data) is shared across boots: prior runs leave
    # installed_extensions/dbversions/extensions rows for infinitemarkets while
    # this boot's ext DB file is fresh. Reset BEFORE startup so the boot is
    # a real fresh install through the host's own restore path.
    from lnbits.core.db import db as core_db

    async with core_db.connect() as conn:
        from lnbits.db import SQLITE

        exists = await conn.fetchone(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'installed_extensions'"
            if core_db.type == SQLITE else
            "SELECT tablename FROM pg_catalog.pg_tables"
            " WHERE schemaname = current_schema() AND tablename = 'installed_extensions'"
        )
        if exists:
            await conn.execute(
                "DELETE FROM installed_extensions WHERE id = :id",
                {"id": "infinitemarkets"},
            )
            await conn.execute(
                "DELETE FROM dbversions WHERE db = :id", {"id": "infinitemarkets"}
            )
            await conn.execute(
                'DELETE FROM extensions WHERE extension = :id',
                {"id": "infinitemarkets"},
            )
    settings.lnbits_installed_extensions_ids.discard("infinitemarkets")
    settings.lnbits_deactivated_extensions.discard("infinitemarkets")

    os.chdir(host_checkout_dir())
    try:
        app = create_app()
        async with LifespanManager(app, startup_timeout=30):
            superuser = f"gqadmin-{uuid.uuid4().hex[:8]}"
            await first_install(
                UpdateSuperuserPassword(
                    username=superuser,
                    password="secret1234",
                    password_repeat="secret1234",
                    first_install_token=settings.first_install_token,
                )
            )
            # If the persisted deactivate_all flag skipped the startup
            # registration pass, run it now — the same path admin
            # activation uses: scan -> migrate -> register routes -> start
            # hook. (deactivate_all is an editable admin setting reloaded
            # from the shared core DB at startup.)
            import importlib

            from lnbits.app import check_and_register_extensions
            from lnbits.core.crud import update_admin_settings
            from lnbits.core.services.settings import update_cached_settings
            from lnbits.settings import EditableSettings

            await update_admin_settings(
                EditableSettings(
                    lnbits_extensions_deactivate_all=False,
                    lnbits_audit_log_request_body=False,
                    lnbits_audit_log_query_params=False,
                    lnbits_audit_log_path_params=False,
                )
            )
            update_cached_settings(
                {
                    "lnbits_extensions_deactivate_all": False,
                    "lnbits_audit_log_request_body": False,
                    "lnbits_audit_log_query_params": False,
                    "lnbits_audit_log_path_params": False,
                }
            )
            ext_module = importlib.import_module("infinitemarkets")
            if ext_module.started_at is None:
                await check_and_register_extensions(app)
            yield app
    finally:
        os.chdir(previous_cwd)
        for key, value in snapshot.items():
            setattr(settings, key, value)
        for key, value in env_snapshot.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def keystore_env(tmp_path_factory):
    """Fresh infinitemarkets module set with all runtime migrations applied.

    ``Database.__init__`` binds ``settings.lnbits_data_folder`` at import
    time, so any ``infinitemarkets`` module imported earlier (e.g. at test
    collection) holds a stale path. The fixture purges ``infinitemarkets*``
    modules, sets the folder, then imports db/keystore fresh — tests MUST
    take ``MerchantKeyStore`` from the yielded namespace, not a module-level
    import.

    Yields ``{"db", "keystore", "crypto", "settings"}`` module objects.
    """
    import importlib

    from lnbits.settings import settings

    folder = tmp_path_factory.mktemp("keystore-db")
    previous = settings.lnbits_data_folder
    settings.lnbits_data_folder = str(folder)
    for mod in [
        m for m in sys.modules
        if m == "infinitemarkets" or m.startswith("infinitemarkets.")
    ]:
        del sys.modules[mod]
    try:
        gdb = importlib.import_module("infinitemarkets.db")
        keystore = importlib.import_module("infinitemarkets.keystore")
        crypto = importlib.import_module("infinitemarkets.crypto")
        gsettings = importlib.import_module("infinitemarkets.settings")
        from infinitemarkets.migrations import (
            m001_initial,
            m002_orders,
            m003_checkout_safety,
            m004_digital_delivery,
            m005_order_archiving,
            m006_gamma_inbox,
            m007_nostr_signin,
            m008_buyer_accounts,
            m009_categories,
            m010_import_drafts,
        )

        async with gdb.db.connect() as conn:
            await m001_initial(conn)
            await m002_orders(conn)
            await m003_checkout_safety(conn)
            await m004_digital_delivery(conn)
            await m005_order_archiving(conn)
            await m006_gamma_inbox(conn)
            await m007_nostr_signin(conn)
            await m008_buyer_accounts(conn)
            await m009_categories(conn)
            await m010_import_drafts(conn)
        yield {
            "db": gdb.db,
            "keystore": keystore,
            "crypto": crypto,
            "settings": gsettings,
        }
    finally:
        settings.lnbits_data_folder = previous


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def runtime_env(tmp_path_factory):
    """One real-loader host boot per module + an authenticated client.

    Yields ``{app, client, token, user_id, wallet, ext_module}`` where
    ``ext_module`` is the module object the host registered (imported AFTER
    registration so ``sys.modules`` reimport semantics are observed).
    """
    import importlib

    from lnbits.core.crud import create_wallet
    from lnbits.core.services import update_wallet_balance

    tmp = tmp_path_factory.mktemp("runtime")
    async with _runtime_app(tmp / "data", tmp / "extroot") as app:
        # Real account with password (same pattern as the P0-12 auth probes),
        # logged in through the host's own auth endpoint.
        from lnbits.core.crud.users import create_account
        from lnbits.core.models.users import Account

        username = f"gquser{uuid.uuid4().hex[:8]}"
        password = "runtime-pass-123"
        account = Account(
            id=uuid.uuid4().hex, username=username, email=None
        )
        account.hash_password(password)
        await create_account(account)

        wallet = await create_wallet(
            user_id=account.id, wallet_name="runtime-wallet"
        )
        await update_wallet_balance(wallet=wallet, amount=9999999)

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url=CANONICAL_ORIGIN
        ) as client:
            resp = await client.post(
                "/api/v1/auth",
                json={"username": username, "password": password},
            )
            assert resp.status_code == 200, resp.text
            token = resp.json()["access_token"]

            # Per-user enablement: the host gates extension routes on the
            # user's active extension list (extension not enabled -> 403).
            resp = await client.put(
                "/api/v1/extension/infinitemarkets/enable",
                headers={
                    "Cookie": f"cookie_access_token={token}",
                    "Origin": CANONICAL_ORIGIN,
                },
            )
            assert resp.status_code == 200, resp.text

            # The host reimports the extension during registration — import
            # now so tests observe the module object the host registered.
            sys.path.insert(
                0, str(tmp / "extroot" / "extensions")
            )
            try:
                ext_module = importlib.import_module("infinitemarkets")
            finally:
                sys.path.remove(str(tmp / "extroot" / "extensions"))

            # The startup reconciliation worker gates checkout until its
            # first pass marks readiness — poll the live flag so the first
            # checkout call in a module cannot race it on slow runners.
            readiness_mod = importlib.import_module(
                "infinitemarkets.services.readiness"
            )
            deadline = time.monotonic() + 60.0
            while not readiness_mod.readiness()["checkout"]:
                if time.monotonic() > deadline:
                    raise AssertionError(
                        "checkout readiness never arrived — "
                        "reconciliation worker did not complete its "
                        "first pass within 60s"
                    )
                await asyncio.sleep(0.25)

            yield {
                "app": app,
                "client": client,
                "token": token,
                "user_id": account.id,
                "username": username,
                "wallet": wallet,
                "ext_module": ext_module,
                "tmp": tmp,
            }


@pytest.fixture
def window_headroom():
    """Await until the current fixed rate-limit window has headroom.

    The extension's limiters count in fixed windows (``now - now % N``).
    A test that asserts a cap trips must land every request in ONE
    window; when a window is about to roll over, wait it out instead of
    flaking (a roll-over splits the burst across two buckets)."""

    async def wait(window_s: int = 60, margin_s: int = 10) -> None:
        remaining = window_s - time.time() % window_s
        if remaining < margin_s:
            await asyncio.sleep(remaining + 0.2)

    return wait


@pytest.fixture
def frozen_inbox_clock(monkeypatch):
    """Pin the inbox admission clock so a multi-second burst of wraps is
    counted in a single fixed window (see ``window_headroom``)."""
    from infinitemarkets.services import inbox

    now = int(time.time())
    monkeypatch.setattr(inbox, "_now", lambda: now)
    return now
