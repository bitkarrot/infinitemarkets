"""04-04: scarce-stock cutover rehearsal.

Two separate proofs, per plan:
- Policy guard: an imported product with an unresolved payable liability is
  unreachable by checkout/publication; after a verified partition the held
  unit stays unavailable while surplus stock remains sellable.
- Real contention: two independent DB connections race the shared
  conditional stock-write primitive on one physical unit; exactly one wins.
"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest

pytestmark = pytest.mark.runtime

API = "/infinitemarkets/api/v1"
ORIGIN = "https://shop.example"


async def _headers(client) -> dict:
    if not client.cookies.get("gm_csrf"):
        await client.get(f"{API}/merchants/current")
    return {"Origin": ORIGIN, "X-CSRF-Token": client.cookies.get("gm_csrf")}


async def _merchant(runtime_env, client, headers):
    resp = await client.get(f"{API}/merchants/current")
    if resp.status_code != 200:
        resp = await client.post(
            f"{API}/merchants",
            json={"wallet_id": runtime_env["wallet"].id},
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
    from infinitemarkets.db import db, table

    merchant_id = resp.json()["id"]
    async with db.connect() as conn:
        await conn.execute(
            f"UPDATE {table('merchants')} SET state = 'active' WHERE id = :m",
            {"m": merchant_id},
        )
    return merchant_id


async def _import_payable(runtime_env, client, headers, qty, instance):
    """Import one nostrmarket product with one payable liability."""
    source = {
        "stalls": [{"id": "old-stall", "currency": "USD"}],
        "products": [{"id": "old-mug", "stall_id": "old-stall",
                      "name": "Old Mug", "price": 2, "quantity": qty}],
        "orders": [{"id": "old-order", "invoice_id": "e" * 64, "paid": False,
                    "items": [{"product_id": "old-mug", "quantity": qty}]}],
    }
    upload = {"file": ("old.json", json.dumps(source).encode(), "application/json")}
    form = {"currency": "USD", "source_instance": instance}
    preview = await client.post(
        f"{API}/migration/legacy/nostrmarket/preview",
        data=form, files=upload, headers=headers,
    )
    assert preview.status_code == 200, preview.text
    form["source_hash"] = preview.json()["source_hash"]
    imported = await client.post(
        f"{API}/migration/legacy/nostrmarket/execute",
        data=form, files=upload, headers=headers,
    )
    assert imported.status_code == 200, imported.text
    return imported.json()["import_id"]


async def _verify_epoch(client, headers, monkeypatch, import_id, qty):
    from infinitemarkets.services import cutover

    stage = await client.post(
        f"{API}/migration/imports/{import_id}/cutover", headers=headers,
    )
    assert stage.status_code == 200, stage.text
    epoch_id = stage.json()["id"]
    requested = await client.post(
        f"{API}/migration/cutovers/{epoch_id}/freeze-request", headers=headers,
    )
    assert requested.status_code == 200
    restart_at = requested.json()["freeze_requested_at"] + 1

    async def disabled():
        return {"disabled": True, "reason_code": "snapshot-unverified",
                "restart_checked_at": restart_at,
                "source_contract": {"code_hash": "a" * 64, "git_commit": "b" * 40}}

    async def evidence(_):
        return {"merchant_id": "old-merchant", "products": {"old-mug"},
                "invoices": [{"invoice_id": "e" * 64, "order_id": "old-order",
                              "items": [{"product_id": "old-mug",
                                         "quantity": qty}],
                              "state": "payable"}]}

    monkeypatch.setattr(cutover, "old_source_status", disabled)
    monkeypatch.setattr(cutover, "read_old_source_evidence", evidence)
    checked = await client.post(
        f"{API}/migration/cutovers/{epoch_id}/check-source", headers=headers,
    )
    assert checked.status_code == 200, checked.text
    liabilities = await client.get(
        f"{API}/migration/cutovers/{epoch_id}/liabilities",
    )
    return epoch_id, liabilities.json()["liabilities"][0]


async def _product_for_import(import_id):
    from infinitemarkets.db import db, table

    async with db.connect() as conn:
        return await conn.fetchone(
            f"SELECT p.* FROM {table('products')} p "
            f"JOIN {table('import_rows')} r ON r.product_id = p.id "
            "WHERE r.import_id = :i LIMIT 1", {"i": import_id},
        )


async def _try_checkout(runtime_env, product, quantity):
    """Service-level checkout attempt; returns the order or the problem."""
    from infinitemarkets.db import db
    from infinitemarkets.services import checkout

    async with db.connect() as conn:
        merchant = await conn.fetchone(
            "SELECT pubkey FROM infinitemarkets.merchants WHERE id = :m",
            {"m": product["merchant_id"]},
        )
    try:
        return await checkout.checkout(
            payload={"merchant_pubkey": merchant["pubkey"],
                     "items": [{"d_tag": product["d_tag"],
                                "quantity": quantity}]},
            idempotency_key=uuid.uuid4().hex * 2,
            client_scope=f"rehearsal-{uuid.uuid4().hex[:8]}",
        )
    except Exception as exc:  # noqa: BLE001 — assert on the problem shape
        return exc


async def _make_sellable(client, headers, product, count):
    """Physical count + publish + mark nip99 active (RELAY_IO is off in the
    test host, so publish intents never confirm — the flag flip emulates
    the confirmed state for stock-path assertions only)."""
    from infinitemarkets.db import db, table

    counted = await client.post(
        f"{API}/products/{product['id']}/stock-count",
        json={"quantity": count}, headers=headers,
    )
    assert counted.status_code == 200, counted.text
    published = await client.patch(
        f"{API}/products/{product['id']}",
        json={"draft": False, "visibility": "on-sale"}, headers=headers,
    )
    assert published.status_code == 200, published.text
    async with db.connect() as conn:
        await conn.execute(
            f"UPDATE {table('products')} SET nip99_status = 'active' "
            "WHERE id = :p", {"p": product["id"]},
        )


async def test_scarce_stock_guard_and_surplus(runtime_env, monkeypatch):
    """stock=1 + payable qty=1: unpartitioned → checkout blocked; after
    partition + completion + count the last unit stays reserved.
    stock=2 + qty=1: exactly one surplus unit is sellable."""
    client = runtime_env["client"]
    headers = await _headers(client)
    await _merchant(runtime_env, client, headers)

    # --- case 1: stock_on_hand = 1, liability qty = 1 -------------------
    import_id = await _import_payable(
        runtime_env, client, headers, qty=1, instance="rehearse-1",
    )
    epoch_id, liability = await _verify_epoch(
        client, headers, monkeypatch, import_id, qty=1,
    )
    product = dict(await _product_for_import(import_id))
    assert product["stock_on_hand"] == 1

    # unpartitioned payable liability → completion and publication blocked
    blocked = await client.post(
        f"{API}/migration/cutovers/{epoch_id}/complete", headers=headers,
    )
    assert blocked.status_code == 409, blocked.text
    attempt = await _try_checkout(runtime_env, product, 1)
    assert getattr(attempt, "status", None) == 422, attempt

    partitioned = await client.post(
        f"{API}/migration/cutovers/{epoch_id}/liabilities/{liability['id']}",
        json={"action": "partition"}, headers=headers,
    )
    assert partitioned.status_code == 200, partitioned.text
    completed = await client.post(
        f"{API}/migration/cutovers/{epoch_id}/complete", headers=headers,
    )
    assert completed.status_code == 200, completed.text

    await _make_sellable(client, headers, product, count=1)
    product = dict(await _product_for_import(import_id))
    assert product["stock_reserved"] == 1  # held for the old invoice
    attempt = await _try_checkout(runtime_env, product, 1)
    assert getattr(attempt, "status", None) == 422, (
        f"held unit must not sell: {attempt}"
    )

    # --- case 2: stock_on_hand = 2, liability qty = 1 → one surplus ----
    import_id = await _import_payable(
        runtime_env, client, headers, qty=1, instance="rehearse-2",
    )
    # stock arrives as declared 1 (source quantity); bump to physical 2
    from infinitemarkets.db import db, table

    async with db.connect() as conn:
        await conn.execute(
            f"UPDATE {table('products')} SET stock_on_hand = 2 "
            f"WHERE id IN (SELECT product_id FROM {table('import_rows')} "
            "WHERE import_id = :i)", {"i": import_id},
        )
        # imported products are physical; digital skips shipping-address
        # resolution — the rehearsal exercises stock, not fulfillment
        await conn.execute(
            f"UPDATE {table('products')} SET format = 'digital' "
            f"WHERE id IN (SELECT product_id FROM {table('import_rows')} "
            "WHERE import_id = :i)", {"i": import_id},
        )
    epoch_id, liability = await _verify_epoch(
        client, headers, monkeypatch, import_id, qty=1,
    )
    product = dict(await _product_for_import(import_id))
    assert product["stock_on_hand"] == 2

    partitioned = await client.post(
        f"{API}/migration/cutovers/{epoch_id}/liabilities/{liability['id']}",
        json={"action": "partition"}, headers=headers,
    )
    assert partitioned.status_code == 200, partitioned.text
    completed = await client.post(
        f"{API}/migration/cutovers/{epoch_id}/complete", headers=headers,
    )
    assert completed.status_code == 200, completed.text
    await _make_sellable(client, headers, product, count=2)

    surplus = await _try_checkout(runtime_env, product, 1)
    assert isinstance(surplus, dict), f"surplus unit should sell: {surplus}"
    double = await _try_checkout(runtime_env, product, 1)
    assert getattr(double, "status", None) == 422, (
        f"second unit is partitioned for the old invoice: {double}"
    )


async def test_shared_stock_primitive_contention(runtime_env, monkeypatch):
    """Two concurrent checkout transactions race one physical unit —
    exactly one reserves it, the loser mints no invoice. Then the schema
    CHECK constraint is shown refusing an unguarded write outright."""
    from infinitemarkets.db import db, table
    from infinitemarkets.services import checkout

    client = runtime_env["client"]
    headers = await _headers(client)
    await _merchant(runtime_env, client, headers)
    cat = await client.post(
        f"{API}/categories",
        json={"name": "contention", "default_currency": "USD"},
        headers=headers,
    )
    assert cat.status_code == 201, cat.text
    product = await client.post(
        f"{API}/products",
        json={"category_id": cat.json()["id"], "title": "one unit",
              "amount_minor": 100, "currency": "SAT", "format": "digital",
              "visibility": "on-sale", "stock_on_hand": 1},
        headers=headers,
    )
    assert product.status_code == 201, product.text
    pid = product.json()["id"]

    async with db.connect() as conn:
        row = await conn.fetchone(
            f"SELECT merchant_id FROM {table('products')} WHERE id = :p",
            {"p": pid},
        )
        merchant = await conn.fetchone(
            f"SELECT pubkey FROM {table('merchants')} WHERE id = :m",
            {"m": row["merchant_id"]},
        )
        await conn.execute(
            f"UPDATE {table('products')} SET nip99_status = 'active' "
            "WHERE id = :p", {"p": pid},
        )

    # both entrants resolve their item set BEFORE either writes — the
    # barrier sits before the transaction, not behind a held lock
    resolved = 0
    gate = asyncio.Event()
    original = checkout._resolve_items

    async def both_entered(*args):
        nonlocal resolved
        out = await original(*args)
        resolved += 1
        if resolved == 2:
            gate.set()
        await asyncio.wait_for(gate.wait(), 5)
        return out

    monkeypatch.setattr(checkout, "_resolve_items", both_entered)
    results = await asyncio.gather(*(
        checkout.checkout(
            payload={"merchant_pubkey": merchant["pubkey"],
                     "items": [{"d_tag": product.json()["d_tag"],
                                "quantity": 1}]},
            idempotency_key=uuid.uuid4().hex * 2,
            client_scope=f"contention-{n}",
        ) for n in range(2)
    ), return_exceptions=True)
    winners = [r for r in results if isinstance(r, dict)]
    losers = [r for r in results if not isinstance(r, dict)]
    assert len(winners) == 1 and len(losers) == 1, results
    assert getattr(losers[0], "status", None) == 422

    async with db.connect() as conn:
        final = await conn.fetchone(
            f"SELECT stock_on_hand, stock_reserved FROM {table('products')} "
            "WHERE id = :p", {"p": pid},
        )
    assert final["stock_reserved"] <= final["stock_on_hand"]
    assert final["stock_reserved"] == 1

    # Backstop: with the capacity predicate stripped the schema CHECK
    # constraint still refuses the oversubscribing write.
    UNSAFE = (
        f"UPDATE {table('products')} SET stock_reserved = stock_reserved + 1 "
        "WHERE id = :p"
    )
    import sqlalchemy.exc

    with pytest.raises(sqlalchemy.exc.IntegrityError):
        async with db.connect() as conn:
            await conn.execute(UNSAFE, {"p": pid})


async def test_unpaid_terminal_releases_hold_exactly_once(
    runtime_env, monkeypatch,
):
    """A payable liability that settles unpaid-terminal releases its held
    partition exactly once; a second reconcile is a no-op."""
    client = runtime_env["client"]
    headers = await _headers(client)
    await _merchant(runtime_env, client, headers)
    import_id = await _import_payable(
        runtime_env, client, headers, qty=1, instance="rehearse-release",
    )
    epoch_id, liability = await _verify_epoch(
        client, headers, monkeypatch, import_id, qty=1,
    )
    partitioned = await client.post(
        f"{API}/migration/cutovers/{epoch_id}/liabilities/{liability['id']}",
        json={"action": "partition"}, headers=headers,
    )
    assert partitioned.status_code == 200, partitioned.text
    product = dict(await _product_for_import(import_id))
    assert product["stock_reserved"] == 1

    from infinitemarkets.services import cutover

    async def unpaid(_u, _h):
        return False

    monkeypatch.setattr(cutover, "_authoritative_payment_state", unpaid)
    first = await client.post(
        f"{API}/migration/cutovers/{epoch_id}/liabilities/{liability['id']}",
        json={"action": "reconcile"}, headers=headers,
    )
    assert first.status_code == 200, first.text
    product = dict(await _product_for_import(import_id))
    assert product["stock_reserved"] == 0 and product["stock_on_hand"] == 1
    second = await client.post(
        f"{API}/migration/cutovers/{epoch_id}/liabilities/{liability['id']}",
        json={"action": "reconcile"}, headers=headers,
    )
    assert second.status_code == 200, second.text
    product = dict(await _product_for_import(import_id))
    assert product["stock_reserved"] == 0 and product["stock_on_hand"] == 1


async def test_paid_terminal_consumes_hold_exactly_once(
    runtime_env, monkeypatch,
):
    """A payable liability that settles paid consumes the held partition
    and decrements stock_on_hand exactly once."""
    client = runtime_env["client"]
    headers = await _headers(client)
    await _merchant(runtime_env, client, headers)
    import_id = await _import_payable(
        runtime_env, client, headers, qty=1, instance="rehearse-paid",
    )
    epoch_id, liability = await _verify_epoch(
        client, headers, monkeypatch, import_id, qty=1,
    )
    partitioned = await client.post(
        f"{API}/migration/cutovers/{epoch_id}/liabilities/{liability['id']}",
        json={"action": "partition"}, headers=headers,
    )
    assert partitioned.status_code == 200, partitioned.text

    from infinitemarkets.services import cutover

    async def paid(_u, _h):
        return True

    monkeypatch.setattr(cutover, "_authoritative_payment_state", paid)
    first = await client.post(
        f"{API}/migration/cutovers/{epoch_id}/liabilities/{liability['id']}",
        json={"action": "reconcile"}, headers=headers,
    )
    assert first.status_code == 200, first.text
    product = dict(await _product_for_import(import_id))
    assert product["stock_reserved"] == 0 and product["stock_on_hand"] == 0
    second = await client.post(
        f"{API}/migration/cutovers/{epoch_id}/liabilities/{liability['id']}",
        json={"action": "reconcile"}, headers=headers,
    )
    assert second.status_code == 200, second.text
    product = dict(await _product_for_import(import_id))
    assert product["stock_reserved"] == 0 and product["stock_on_hand"] == 0
