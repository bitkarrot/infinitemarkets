"""Host app fixture for the LNbits host contract probes (P0-03).

Follows the pinned checkout's own tests/conftest.py pattern (verified at
4fa70f3): an isolated tmp data folder for NEW databases, FakeWallet funding
(LNBITS_BACKEND_WALLET_CLASS semantics applied to the mutable settings
singleton), create_app + asgi_lifespan.LifespanManager + first_install
bootstrap, and wallet/account creation via the host's own crud/services
(create_user_account / create_wallet).

The fixture owns no production routes — it exists so probes can exercise
the real pinned host. The core database is the module-level
``lnbits.core.db.db`` created at import (with the harness LNBITS_DATA_FOLDER
under .cache/), so a second boot reuses the same core tables — exactly the
restart semantics the callback-nondurability probe requires.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

DEFAULT_SUPERUSER_PREFIX = "gqadmin"  # + '_' + 8 hex; host caps username at 20 chars
DEFAULT_PASSWORD = "secret1234"

_HOST_SETTINGS_KEYS = (
    "lnbits_data_folder",
    "lnbits_backend_wallet_class",
    "lnbits_extensions_deactivate_all",
    "lnbits_admin_ui",
    "first_install",
    "lnbits_autoupdate_extensions_on_startup",
    "lnbits_autoupdate_extensions_interval_hours",
    "lnbits_allow_new_accounts",
)


@asynccontextmanager
async def host_app(data_folder: Path | str):
    """Boot the pinned LNbits host app with FakeWallet + isolated data folder.

    Yields the FastAPI app inside an active LifespanManager. Restores the
    mutated settings and the process cwd on exit.

    The host resolves several runtime paths relative to the process cwd
    (verified at 4fa70f3: ``app.mount("/static",
    StaticFiles(directory=Path("lnbits", "static")))`` and the extensions
    directory), and the host's own tests therefore run from the checkout
    root. This fixture reproduces that environment by chdir-ing into the
    pinned checkout for the app's lifetime; the harness LNBITS_DATA_FOLDER
    is absolute, so the core database is unaffected by the cwd change.
    """
    import os
    import uuid

    from asgi_lifespan import LifespanManager
    from lnbits.app import create_app
    from lnbits.core.models.users import UpdateSuperuserPassword
    from lnbits.core.views.auth_api import first_install
    from lnbits.settings import settings

    from tools.checkout_host import host_checkout_dir

    snapshot = {key: getattr(settings, key) for key in _HOST_SETTINGS_KEYS}
    previous_cwd = Path.cwd()

    settings.lnbits_data_folder = str(data_folder)
    settings.lnbits_backend_wallet_class = "FakeWallet"
    settings.lnbits_extensions_deactivate_all = True
    settings.lnbits_admin_ui = True
    settings.first_install = True
    # Hermetic boot: no extension autoupdate at startup (app.py:553 gates
    # on lnbits_autoupdate_extensions_on_startup) and interval==0 skips the
    # scheduled pass (core/tasks.py:49-51).
    settings.lnbits_autoupdate_extensions_on_startup = False
    settings.lnbits_autoupdate_extensions_interval_hours = 0
    # v1.7.1 defaults account creation off (settings.py:57); the host's own
    # tests/conftest.py:397 enables it for fixtures the same way.
    settings.lnbits_allow_new_accounts = True

    os.chdir(host_checkout_dir())
    try:
        app = create_app()
        async with LifespanManager(app, startup_timeout=30):
            # Unique superuser per boot: the module-level core database is
            # shared across boots (and pytest runs), so a fixed username
            # would collide on the second boot.
            # The shared core DB carries an admin-settings row across boots,
            # and check_admin_settings (core/services/users.py:172-188)
            # overwrites in-memory settings from it at startup — re-assert
            # the boot posture into both the row and the live object.
            from lnbits.core.crud import update_admin_settings
            from lnbits.core.services.settings import update_cached_settings
            from lnbits.settings import EditableSettings

            boot_overrides = {
                "lnbits_allow_new_accounts": True,
                "lnbits_autoupdate_extensions_on_startup": False,
                "lnbits_autoupdate_extensions_interval_hours": 0,
            }
            await update_admin_settings(EditableSettings(**boot_overrides))
            update_cached_settings(boot_overrides)

            superuser = f"{DEFAULT_SUPERUSER_PREFIX}_{uuid.uuid4().hex[:8]}"
            await first_install(
                UpdateSuperuserPassword(
                    username=superuser,
                    password=DEFAULT_PASSWORD,
                    password_repeat=DEFAULT_PASSWORD,
                    first_install_token=settings.first_install_token,
                )
            )
            # Yield the raw FastAPI app (the lifespan manager's app is the
            # state-middleware wrapper) so probes can mount fixture-only
            # routers on it.
            yield app
    finally:
        os.chdir(previous_cwd)
        for key, value in snapshot.items():
            setattr(settings, key, value)


async def create_test_wallet(wallet_name: str = "gamma-qual"):
    """Create a fresh funded user + wallet via the host's own services.

    Mirrors the host's tests/conftest.py from_user/from_wallet fixtures:
    create_user_account + create_wallet + update_wallet_balance funding, so
    probes can settle FakeWallet invoices through pay_invoice.
    """
    import uuid

    from lnbits.core.crud import create_wallet
    from lnbits.core.models.users import Account
    from lnbits.core.services import create_user_account, update_wallet_balance

    # v1.7.1: account=None requires the user-id-only auth method
    # (services/users.py:44-60), which the default posture disables —
    # pass an explicit Account, matching the host's own conftest.
    user = await create_user_account(Account(id=uuid.uuid4().hex))
    wallet = await create_wallet(user_id=user.id, wallet_name=wallet_name)
    await update_wallet_balance(wallet=wallet, amount=9999999)
    return user, wallet
