"""Runtime install tests — real host discovery + lifecycle (plan 02-01 Task 1).

These exercise the extension through the host's own loader, not fixture
routers: config.json discovery, m001 migration, route registration, the
synchronous start hook, the declarative static mount, and deactivation.
"""

from __future__ import annotations

import importlib
import sys

import pytest

from harness.registry import SCHEMA_FIELDS, TABLE_CLASSIFICATION

pytestmark = [
    pytest.mark.runtime,
    pytest.mark.asyncio(loop_scope="session"),
]

M001_TABLES = {
    "merchants",
    "merchant_keys",
    "settings",
    "categories",
    "products",
    "product_images",
    "product_specs",
    "product_categories",
    "product_collections",
    "product_shipping_options",
    "product_shipping_collections",
    "collections",
    "collection_shipping",
    "shipping_options",
    "protocol_addresses",
    "relay_configs",
    "outbox_events",
    "outbox_dependencies",
    "relay_publications",
    "task_leases",
    "rate_limit_buckets",
}

# Tables m002 creates (orders/payments/inventory/idempotency/email).
M002_TABLES = {
    "orders",
    "order_items",
    "order_events",
    "order_fx_quotes",
    "order_fulfillment",
    "order_messages",
    "payments",
    "inventory_reservations",
    "idempotency_records",
    "email_queue",
    "inbox_events",
}

# Tables m006 creates (Gamma inbox — peer relays, cursors, blocklist).
M006_TABLES = {
    "peer_relays",
    "relay_cursors",
    "inbox_blocklist",
}

# Tables m007 creates (NIP-07 buyer sign-in — D-01).
M007_TABLES = {
    "nostr_challenges",
    "buyer_sessions",
}

# Tables no migration creates yet (Phase 4).
ABSENT_TABLES = {
    "migration_jobs",
}


def _cookie_headers(token: str, origin: str | None = None) -> dict:
    headers = {"Cookie": f"cookie_access_token={token}"}
    if origin:
        headers["Origin"] = origin
    return headers


async def _table_names(ext_module) -> set[str]:
    from lnbits.db import POSTGRES

    db = ext_module.db
    async with db.connect() as conn:
        if db.type == POSTGRES:
            rows = await conn.fetchall(
                "SELECT table_name AS name FROM information_schema.tables "
                "WHERE table_schema = 'infinitemarkets'"
            )
            return {r["name"] for r in rows}
        rows = await conn.fetchall(
            "SELECT name FROM infinitemarkets.sqlite_master "
            "WHERE type = 'table'"
        )
        return {r["name"] for r in rows}


async def _columns(ext_module, name: str) -> set[str]:
    from lnbits.db import POSTGRES

    db = ext_module.db
    async with db.connect() as conn:
        if db.type == POSTGRES:
            rows = await conn.fetchall(
                "SELECT column_name AS name FROM information_schema.columns "
                "WHERE table_schema = 'infinitemarkets' AND table_name = :t",
                {"t": name},
            )
            return {r["name"] for r in rows}
        rows = await conn.fetchall(
            f"SELECT name FROM pragma_table_info('{name}')"
        )
        return {r["name"] for r in rows}


async def test_discovered_and_registered(runtime_env):
    """The host discovered the extension via config.json and ran the sync
    start hook (``started_at`` set) — proving the sync-def contract."""
    ext_module = runtime_env["ext_module"]
    assert ext_module.started_at is not None
    assert ext_module.infinitemarkets_ext.prefix == "/infinitemarkets"


async def test_m001_tables_created(runtime_env):
    tables = await _table_names(runtime_env["ext_module"])
    missing = (M001_TABLES | M002_TABLES | M006_TABLES | M007_TABLES) - tables
    assert not missing, f"missing m001/m002/m006 tables: {missing}"
    stray = ABSENT_TABLES & tables
    assert not stray, f"migrations created tables owned by later phases: {stray}"


async def test_m006_columns_created(runtime_env):
    """m006 column adds: merchants.inbox_state, relay_configs auth fields,
    order_messages surface markers."""
    merchants = await _columns(runtime_env["ext_module"], "merchants")
    assert "inbox_state" in merchants
    relay_configs = await _columns(
        runtime_env["ext_module"], "relay_configs"
    )
    assert {"auth_state", "auth_note", "paid_invoice",
            "auth_updated_at"} <= relay_configs
    order_messages = await _columns(
        runtime_env["ext_module"], "order_messages"
    )
    assert {"conversation_id", "read_at"} <= order_messages


async def test_modeled_columns_match_registry(runtime_env):
    """Every modeled field set (spec section 4 literals) is a subset of the
    migrated table's columns — the registry<->migration diff."""
    ext_module = runtime_env["ext_module"]
    for name in M001_TABLES | M002_TABLES | M006_TABLES | M007_TABLES:
        if TABLE_CLASSIFICATION.get(name) != "modeled":
            continue
        modeled = SCHEMA_FIELDS[name]
        actual = await _columns(ext_module, name)
        assert modeled <= actual, (
            f"{name}: registry fields missing from migration: "
            f"{modeled - actual}"
        )


async def test_admin_page_requires_auth(runtime_env):
    """No credentials at all -> no page. (The module client carries the
    login cookie in its jar, so use a fresh transport client.)"""
    import httpx

    transport = httpx.ASGITransport(app=runtime_env["app"])
    async with httpx.AsyncClient(
        transport=transport, base_url="https://shop.example"
    ) as client:
        resp = await client.get("/infinitemarkets/", follow_redirects=False)
    assert resp.status_code in (307, 401, 403), resp.status_code


async def test_admin_page_renders_template(runtime_env):
    """Real-loader template spike (research OQ2): the resolved template name
    is ``templates/infinitemarkets/index.html`` — the renderer searches the
    extension ROOT, so the name carries the templates/ prefix."""
    client = runtime_env["client"]
    resp = await client.get(
        "/infinitemarkets/",
        headers=_cookie_headers(runtime_env["token"]),
    )
    assert resp.status_code == 200, resp.text
    assert "Infinitemarkets" in resp.text


async def test_static_probe_mounted(runtime_env):
    client = runtime_env["client"]
    resp = await client.get(
        "/infinitemarkets/static/infinitemarkets/probe.txt"
    )
    assert resp.status_code == 200
    assert "infinitemarkets" in resp.text


async def test_deactivation_404s_routes(runtime_env):
    """Host deactivation drops the extension's routes (middleware 404)."""
    from lnbits.core.models.extensions import Extension
    from lnbits.core.services.extensions import (
        activate_extension,
        deactivate_extension,
    )

    client = runtime_env["client"]
    await deactivate_extension("infinitemarkets")
    try:
        resp = await client.get(
            "/infinitemarkets/",
            headers=_cookie_headers(runtime_env["token"]),
        )
        assert resp.status_code == 404, resp.status_code
    finally:
        # Restore for other tests sharing the module-scoped boot.
        await activate_extension(
            Extension(code="infinitemarkets", is_valid=True)
        )


async def test_reactivation_reruns_start_hook(runtime_env):
    """Deactivation + activation reimports the module and reruns the sync
    start hook — the live module in sys.modules has ``started_at`` set."""
    ext_module = importlib.import_module("infinitemarkets")
    assert sys.modules["infinitemarkets"] is ext_module
    assert ext_module.started_at is not None
