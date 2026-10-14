"""Infinitemarkets — LNbits extension.

NIP-99 catalog publication and Lightning checkout over one authoritative
inventory. Host integration contract (pinned host v1.6.2-rc1, e336fe1):

- ``infinitemarkets_ext`` — APIRouter carrying its own ``/infinitemarkets`` prefix
  (the host adds none).
- ``infinitemarkets_static_files`` — declarative list; the host mounts it.
- ``infinitemarkets_start`` — synchronous (host calls it unawaited); does
  bounded registrations only.
- ``infinitemarkets_stop`` — cancels exactly the task handles this module owns.
"""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter

from ._vendored import ensure_vendored
from .db import db  # noqa: F401  (host migration runner imports this attr)

# Release archives carry vendored wheels under _vendor/ because the host
# never pip-installs extension dependencies; a no-op when the host env
# already provides them. Must run before the nostr_sdk importers below.
ensure_vendored()

infinitemarkets_ext: APIRouter = APIRouter(
    prefix="/infinitemarkets", tags=["infinitemarkets"]
)

infinitemarkets_static_files = [
    {"path": "/infinitemarkets/static", "name": "infinitemarkets_static"},
]

infinitemarkets_redirect_paths: list = []

#: Task handles this extension owns — cancelled by infinitemarkets_stop.
_owned_tasks: list[asyncio.Task] = []

#: Set when the start hook ran (install test asserts the sync contract).
started_at: int | None = None


def register_owned_task(task: asyncio.Task) -> asyncio.Task:
    """Track an extension-owned task handle for stop-hook cancellation."""
    _owned_tasks.append(task)
    return task


def infinitemarkets_start() -> None:
    """Synchronous start hook (host invokes unawaited on restore).

    Strict ``INFINITEMARKETS_*`` validation runs before anything else: a
    failure raises here, the host marks the extension inactive, and its
    routes 404 — merchant services never activate on bad configuration.
    Worker registrations land in plans 02-02/02-03.
    """
    global started_at
    from loguru import logger

    from .db import topology_supported
    from .security import audit_capture_warnings
    from .settings import ext_settings  # raises on invalid configuration

    ext_settings()
    ok, reason = topology_supported()
    if not ok:
        raise RuntimeError(f"infinitemarkets unsupported topology: {reason}")
    # OQ3: host audit capture has no redaction hook — warn loudly at
    # startup (admin banner repeats it via GET /merchants/current).
    for warning in audit_capture_warnings():
        logger.warning(warning)
    # section 10 workers — the relay-manager tick lazily creates the owned
    # transport (this hook is sync; async init happens inside the loop).
    from .services.tasks import start_workers

    for task in start_workers():
        register_owned_task(task)
    started_at = int(time.time())


async def infinitemarkets_stop() -> None:
    """Cancel exactly the handles this extension owns (spec section 10),
    then close the owned transport (the host awaits coroutine stops)."""
    for task in _owned_tasks:
        task.cancel()
    _owned_tasks.clear()
    from .services.inbox import inbox_runtime
    from .services.transport import transport

    await inbox_runtime().close()
    await transport().close()


from .views import infinitemarkets_generic_router  # noqa: E402
from .views_api import infinitemarkets_api_router  # noqa: E402
from .views_public_api import infinitemarkets_public_api_router  # noqa: E402

infinitemarkets_ext.include_router(infinitemarkets_generic_router)
infinitemarkets_ext.include_router(infinitemarkets_api_router)
infinitemarkets_ext.include_router(infinitemarkets_public_api_router)
