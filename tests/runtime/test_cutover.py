import json
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.runtime

API = "/infinitemarkets/api/v1"


async def test_staging_requires_owned_legacy_import_and_never_authorizes_stock(
    runtime_env, monkeypatch,
):
    from infinitemarkets.db import db, table
    from infinitemarkets.security import ProblemError
    from infinitemarkets.services import cutover

    client = runtime_env["client"]
    await client.get(f"{API}/merchants/current")
    headers = {"Origin": "https://shop.example",
               "X-CSRF-Token": client.cookies.get("gm_csrf")}
    merchant = await client.post(
        f"{API}/merchants", json={"wallet_id": runtime_env["wallet"].id},
        headers=headers,
    )
    assert merchant.status_code == 201, merchant.text
    merchant_id = merchant.json()["id"]
    source = {
        "stalls": [{"id": "old-stall", "currency": "USD"}],
        "products": [{"id": "old-mug", "stall_id": "old-stall",
                      "name": "Old Mug", "price": 2, "quantity": 1}],
        "orders": [{"id": "old-order", "invoice_id": "c" * 64, "paid": True,
                    "items": [{"product_id": "old-mug", "quantity": 1}]}],
    }
    upload = {"file": ("old.json", json.dumps(source).encode(), "application/json")}
    form = {"currency": "USD", "source_instance": "original"}
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
    import_id = imported.json()["import_id"]
    stage_url = f"{API}/migration/imports/{import_id}/cutover"
    assert (await client.post(stage_url)).status_code == 403
    stage = await client.post(stage_url, headers=headers)
    assert stage.status_code == 200, stage.text
    assert stage.json()["state"] == "staged"
    assert stage.json()["cutover_verified"] is False
    assert (await client.post(stage_url, headers=headers)).json()["id"] == stage.json()["id"]
    epoch_id = stage.json()["id"]
    with pytest.raises(ProblemError) as foreign:
        await cutover.cutover_status(
            merchant_id, SimpleNamespace(id="unrelated-owner"), epoch_id
        )
    assert foreign.value.status == 404
    freeze_url = f"{API}/migration/cutovers/{epoch_id}/freeze-request"
    requested = await client.post(freeze_url, headers=headers)
    assert requested.status_code == 200
    assert requested.json()["state"] == "freeze_requested"
    assert requested.json()["snapshot_verified"] is False
    assert (await client.post(freeze_url, headers=headers)).json() == requested.json()
    status = await client.get(f"{API}/migration/cutovers/{epoch_id}")
    assert status.status_code == 200, status.text
    assert status.json()["source"]["disabled"] is False
    assert status.json()["source"]["reason_code"] == "legacy-unavailable"
    assert [event["state"] for event in status.json()["events"]] == [
        "staged", "freeze_requested"
    ]
    check_url = f"{API}/migration/cutovers/{epoch_id}/check-source"
    assert (await client.post(check_url, headers=headers)).status_code == 409

    restart_at = requested.json()["freeze_requested_at"] + 1

    async def disabled():
        return {"disabled": True, "reason_code": "snapshot-unverified",
                "restart_checked_at": restart_at,
                "source_contract": {"code_hash": "a" * 64, "git_commit": "b" * 40}}

    async def evidence(_):
        return {"merchant_id": "old-merchant", "products": {"old-mug"},
                "invoices": [{"invoice_id": "c" * 64, "order_id": "old-order",
                              "items": [{"product_id": "old-mug", "quantity": 1}],
                              "state": "payable"}]}

    monkeypatch.setattr(cutover, "old_source_status", disabled)
    monkeypatch.setattr(cutover, "read_old_source_evidence", evidence)
    checked = await client.post(check_url, headers=headers)
    assert checked.status_code == 200, checked.text
    assert checked.json()["state"] == "snapshot_verified"
    assert checked.json()["snapshot_verified"] is True
    assert checked.json()["payable_quantity"] == 1
    assert "c" * 64 not in checked.text
    restart_at = requested.json()["freeze_requested_at"]
    assert (await client.post(check_url, headers=headers)).status_code == 409
    restart_at = requested.json()["freeze_requested_at"] + 1
    aborted = await client.post(
        f"{API}/migration/cutovers/{epoch_id}/abort", headers=headers
    )
    assert aborted.status_code == 200 and aborted.json()["state"] == "blocked"
    assert (await client.post(check_url, headers=headers)).status_code == 409
    assert (await client.post(
        f"{API}/migration/cutovers/{epoch_id}/abort", headers=headers
    )).json() == aborted.json()
    async with db.connect() as conn:
        row = await conn.fetchone(
            f"SELECT p.draft, p.import_authorized, l.status "
            f"FROM {table('import_rows')} r "
            f"JOIN {table('products')} p ON p.id = r.product_id "
            f"JOIN {table('imported_liabilities')} l ON l.product_id = p.id "
            "WHERE r.import_id = :i", {"i": import_id},
        )
        holds = await conn.fetchone(
            f"SELECT COUNT(*) AS n FROM {table('liability_partitions')} "
            "WHERE epoch_id = :e", {"e": epoch_id},
        )
        epoch = await conn.fetchone(
            f"SELECT state, snapshot_hash, snapshot_json, snapshot_id "
            f"FROM {table('cutover_epochs')} WHERE id = :e", {"e": epoch_id},
        )
    assert row["draft"] and not row["import_authorized"]
    assert row["status"] == "payable" and holds["n"] == 0
    assert epoch["state"] == "blocked" and epoch["snapshot_hash"]
    from nostr_sdk import Event

    signed_snapshot = Event.from_json(epoch["snapshot_json"])
    assert signed_snapshot.verify()
    assert signed_snapshot.id().to_hex() == epoch["snapshot_id"]
    snapshot = json.loads(signed_snapshot.content())
    assert snapshot["phase"] == "verified"
    assert snapshot["payable_quantity"] == 1
    assert "c" * 64 not in epoch["snapshot_json"]
    restarted = await client.post(stage_url, headers=headers)
    assert restarted.status_code == 200
    assert restarted.json()["id"] != epoch_id
    assert restarted.json()["state"] == "staged"


async def _verified_epoch(
    runtime_env, monkeypatch, qty=1, invoice_state="payable", instance="original",
):
    """Import a nostrmarket catalog with one liability and drive a cutover
    epoch to ``snapshot_verified`` with mocked disabled-source evidence."""
    from infinitemarkets.services import cutover

    client = runtime_env["client"]
    headers = {"Origin": "https://shop.example",
               "X-CSRF-Token": client.cookies.get("gm_csrf")}
    merchant = await client.get(f"{API}/merchants/current")
    if merchant.status_code == 404:
        merchant = await client.post(
            f"{API}/merchants", json={"wallet_id": runtime_env["wallet"].id},
            headers=headers,
        )
        assert merchant.status_code == 201, merchant.text
    else:
        assert merchant.status_code == 200, merchant.text
    source = {
        "stalls": [{"id": "old-stall", "currency": "USD"}],
        "products": [{"id": "old-mug", "stall_id": "old-stall",
                      "name": "Old Mug", "price": 2, "quantity": qty}],
        "orders": [{"id": "old-order", "invoice_id": "c" * 64, "paid": True,
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
    import_id = imported.json()["import_id"]
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
                "invoices": [{"invoice_id": "c" * 64, "order_id": "old-order",
                              "items": [{"product_id": "old-mug", "quantity": qty}],
                              "state": invoice_state}]}

    monkeypatch.setattr(cutover, "old_source_status", disabled)
    monkeypatch.setattr(cutover, "read_old_source_evidence", evidence)
    checked = await client.post(
        f"{API}/migration/cutovers/{epoch_id}/check-source", headers=headers,
    )
    assert checked.status_code == 200, checked.text
    liabilities = await client.get(
        f"{API}/migration/cutovers/{epoch_id}/liabilities",
    )
    assert liabilities.status_code == 200, liabilities.text
    liability = liabilities.json()["liabilities"][0]
    return client, headers, merchant.json()["id"], epoch_id, liability


async def test_disposition_wait_partition_and_complete(runtime_env, monkeypatch):
    from infinitemarkets.db import db, table

    client, headers, merchant_id, epoch_id, liability = await _verified_epoch(
        runtime_env, monkeypatch, qty=1, instance="t-disp",
    )
    liability_id = liability["id"]
    assert liability["status"] == "payable"
    action_url = f"{API}/migration/cutovers/{epoch_id}/liabilities/{liability_id}"
    waited = await client.post(action_url, headers=headers, json={"action": "wait"})
    assert waited.status_code == 200 and waited.json()["status"] == "waiting"
    epoch = await client.get(f"{API}/migration/cutovers/{epoch_id}")
    assert epoch.json()["state"] == "reconciling"

    # partition beyond the physical stock baseline fails closed
    async with db.connect() as conn:
        await conn.execute(
            f"UPDATE {table('products')} SET stock_on_hand = 0 "
            "WHERE id = :p", {"p": liability["product_id"]},
        )
    partitioned = await client.post(
        action_url, headers=headers, json={"action": "partition"},
    )
    assert partitioned.status_code == 409

    async with db.connect() as conn:
        await conn.execute(
            f"UPDATE {table('products')} SET stock_on_hand = 5 "
            "WHERE id = :p", {"p": liability["product_id"]},
        )
    partitioned = await client.post(
        action_url, headers=headers, json={"action": "partition"},
    )
    assert partitioned.status_code == 200, partitioned.text
    assert partitioned.json()["status"] == "partitioned"
    assert partitioned.json()["partition_state"] == "held"
    async with db.connect() as conn:
        product = await conn.fetchone(
            f"SELECT stock_on_hand, stock_reserved FROM {table('products')} "
            "WHERE id = :p", {"p": liability["product_id"]},
        )
    assert (product["stock_on_hand"], product["stock_reserved"]) == (5, 1)

    # double-partition is idempotent — no second hold
    again = await client.post(action_url, headers=headers, json={"action": "partition"})
    assert again.status_code == 200 and again.json()["partition_state"] == "held"
    async with db.connect() as conn:
        product = await conn.fetchone(
            f"SELECT stock_reserved FROM {table('products')} WHERE id = :p",
            {"p": liability["product_id"]},
        )
    assert product["stock_reserved"] == 1

    completed = await client.post(
        f"{API}/migration/cutovers/{epoch_id}/complete", headers=headers,
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["state"] == "complete"
    assert completed.json()["cutover_verified"] is True
    # the payable hold survives completion
    async with db.connect() as conn:
        part = await conn.fetchone(
            f"SELECT state FROM {table('liability_partitions')} WHERE epoch_id = :e",
            {"e": epoch_id},
        )
        product = await conn.fetchone(
            f"SELECT stock_reserved, import_authorized FROM {table('products')} "
            "WHERE id = :p", {"p": liability["product_id"]},
        )
    assert part["state"] == "held" and product["stock_reserved"] == 1
    assert product["import_authorized"]


async def test_reconcile_paid_consumes_partition_once(runtime_env, monkeypatch):
    from infinitemarkets.db import db, table
    from infinitemarkets.services import cutover

    client, headers, merchant_id, epoch_id, liability = await _verified_epoch(
        runtime_env, monkeypatch, qty=1, instance="t-paid",
    )
    liability_id = liability["id"]
    action_url = f"{API}/migration/cutovers/{epoch_id}/liabilities/{liability_id}"
    async with db.connect() as conn:
        await conn.execute(
            f"UPDATE {table('products')} SET stock_on_hand = 5 "
            "WHERE id = :p", {"p": liability["product_id"]},
        )
    assert (await client.post(
        action_url, headers=headers, json={"action": "partition"},
    )).status_code == 200

    # unknown/pending status is not terminal — nothing moves
    async def pending(_u, _h):
        return None

    monkeypatch.setattr(cutover, "_authoritative_payment_state", pending)
    unchanged = await client.post(action_url, headers=headers, json={"action": "reconcile"})
    assert unchanged.status_code == 200
    assert unchanged.json()["status"] == "partitioned"
    async with db.connect() as conn:
        product = await conn.fetchone(
            f"SELECT stock_on_hand, stock_reserved FROM {table('products')} "
            "WHERE id = :p", {"p": liability["product_id"]},
        )
    assert (product["stock_on_hand"], product["stock_reserved"]) == (5, 1)

    async def settled(_u, _h):
        return True

    monkeypatch.setattr(cutover, "_authoritative_payment_state", settled)
    paid = await client.post(action_url, headers=headers, json={"action": "reconcile"})
    assert paid.status_code == 200 and paid.json()["status"] == "paid"
    async with db.connect() as conn:
        product = await conn.fetchone(
            f"SELECT stock_on_hand, stock_reserved FROM {table('products')} "
            "WHERE id = :p", {"p": liability["product_id"]},
        )
        part = await conn.fetchone(
            f"SELECT state FROM {table('liability_partitions')} WHERE epoch_id = :e",
            {"e": epoch_id},
        )
    assert (product["stock_on_hand"], product["stock_reserved"]) == (4, 0)
    assert part["state"] == "consumed"
    # idempotent replay — no second decrement
    replay = await client.post(action_url, headers=headers, json={"action": "reconcile"})
    assert replay.status_code == 200 and replay.json()["status"] == "paid"
    async with db.connect() as conn:
        product = await conn.fetchone(
            f"SELECT stock_on_hand FROM {table('products')} WHERE id = :p",
            {"p": liability["product_id"]},
        )
    assert product["stock_on_hand"] == 4


async def test_reconcile_unpaid_terminal_releases_hold(runtime_env, monkeypatch):
    from infinitemarkets.db import db, table
    from infinitemarkets.services import cutover

    client, headers, merchant_id, epoch_id, liability = await _verified_epoch(
        runtime_env, monkeypatch, qty=2, instance="t-unpaid",
    )
    liability_id = liability["id"]
    action_url = f"{API}/migration/cutovers/{epoch_id}/liabilities/{liability_id}"
    async with db.connect() as conn:
        await conn.execute(
            f"UPDATE {table('products')} SET stock_on_hand = 10 "
            "WHERE id = :p", {"p": liability["product_id"]},
        )
    assert (await client.post(
        action_url, headers=headers, json={"action": "partition"},
    )).status_code == 200

    async def expired(_u, _h):
        return False

    monkeypatch.setattr(cutover, "_authoritative_payment_state", expired)
    released = await client.post(action_url, headers=headers, json={"action": "reconcile"})
    assert released.status_code == 200
    assert released.json()["status"] == "unpaid_terminal"
    async with db.connect() as conn:
        product = await conn.fetchone(
            f"SELECT stock_on_hand, stock_reserved FROM {table('products')} "
            "WHERE id = :p", {"p": liability["product_id"]},
        )
        part = await conn.fetchone(
            f"SELECT state FROM {table('liability_partitions')} WHERE epoch_id = :e",
            {"e": epoch_id},
        )
    assert (product["stock_on_hand"], product["stock_reserved"]) == (10, 0)
    assert part["state"] == "released"
    completed = await client.post(
        f"{API}/migration/cutovers/{epoch_id}/complete", headers=headers,
    )
    assert completed.status_code == 200 and completed.json()["state"] == "complete"


async def test_complete_rejects_uncovered_payable(runtime_env, monkeypatch):
    client, headers, merchant_id, epoch_id, liability = await _verified_epoch(
        runtime_env, monkeypatch, qty=1, instance="t-uncovered",
    )
    complete = await client.post(
        f"{API}/migration/cutovers/{epoch_id}/complete", headers=headers,
    )
    assert complete.status_code == 409
    waited = await client.post(
        f"{API}/migration/cutovers/{epoch_id}/liabilities/{liability['id']}",
        headers=headers, json={"action": "wait"},
    )
    assert waited.status_code == 200
    complete = await client.post(
        f"{API}/migration/cutovers/{epoch_id}/complete", headers=headers,
    )
    assert complete.status_code == 409


async def test_complete_releases_products_and_reblocks_on_reactivation(
    runtime_env, monkeypatch,
):
    from infinitemarkets.db import db, table
    from infinitemarkets.services import cutover

    client, headers, merchant_id, epoch_id, liability = await _verified_epoch(
        runtime_env, monkeypatch, qty=1, instance="t-release",
        invoice_state="paid",
    )
    assert liability["status"] == "paid"
    completed = await client.post(
        f"{API}/migration/cutovers/{epoch_id}/complete", headers=headers,
    )
    assert completed.status_code == 200 and completed.json()["state"] == "complete"

    # released epoch alone is not enough — no physical stock count yet
    patch = await client.patch(
        f"{API}/products/{liability['product_id']}",
        headers=headers, json={"draft": False, "visibility": "on-sale"},
    )
    assert patch.status_code == 409

    count = await client.post(
        f"{API}/products/{liability['product_id']}/stock-count",
        headers=headers, json={"quantity": 7},
    )
    assert count.status_code == 200, count.text
    patch = await client.patch(
        f"{API}/products/{liability['product_id']}",
        headers=headers, json={"draft": False, "visibility": "on-sale"},
    )
    assert patch.status_code == 200, patch.text
    async with db.connect() as conn:
        product = await conn.fetchone(
            f"SELECT d_tag, draft FROM {table('products')} WHERE id = :p",
            {"p": liability["product_id"]},
        )
    assert not product["draft"]
    current = await client.get(f"{API}/merchants/current")
    pubkey = current.json()["pubkey"]
    detail = await client.get(
        f"/infinitemarkets/p/{pubkey}/{product['d_tag']}"
    )
    assert detail.status_code == 200, detail.status_code

    # detected reactivation re-blocks the epoch and re-blocks the product
    async def reactivated():
        return {"disabled": False, "reason_code": "legacy-active"}

    monkeypatch.setattr(cutover, "old_source_status", reactivated)
    status = await client.get(f"{API}/migration/cutovers/{epoch_id}")
    assert status.status_code == 200
    assert status.json()["state"] == "blocked"
    repatch = await client.patch(
        f"{API}/products/{liability['product_id']}",
        headers=headers, json={"visibility": "pre-order"},
    )
    assert repatch.status_code == 409


async def test_reconcile_pass_reblocks_and_settles(runtime_env, monkeypatch):
    from infinitemarkets.db import db, table
    from infinitemarkets.services import cutover

    client, headers, merchant_id, epoch_id, liability = await _verified_epoch(
        runtime_env, monkeypatch, qty=1, instance="t-pass",
    )
    async with db.connect() as conn:
        await conn.execute(
            f"UPDATE {table('products')} SET stock_on_hand = 3 "
            "WHERE id = :p", {"p": liability["product_id"]},
        )
    action_url = f"{API}/migration/cutovers/{epoch_id}/liabilities/{liability['id']}"
    assert (await client.post(
        action_url, headers=headers, json={"action": "partition"},
    )).status_code == 200

    # payment lookup failure fails closed — nothing settles or releases
    async def unavailable(_u, _h):
        raise cutover.conflict("legacy-evidence", "unavailable")

    monkeypatch.setattr(
        cutover, "_authoritative_payment_state", unavailable
    )
    report = await cutover.cutover_reconcile_pass()
    assert report["errors"] >= 1 and report["settled"] == 0
    assert report["released"] == 0
    async with db.connect() as conn:
        product = await conn.fetchone(
            f"SELECT stock_on_hand, stock_reserved FROM {table('products')} "
            "WHERE id = :p", {"p": liability["product_id"]},
        )
    assert (product["stock_on_hand"], product["stock_reserved"]) == (3, 1)

    async def settled(_u, _h):
        return True

    monkeypatch.setattr(cutover, "_authoritative_payment_state", settled)
    report = await cutover.cutover_reconcile_pass()
    assert report["settled"] >= 1 and report["errors"] == 0
    async with db.connect() as conn:
        product = await conn.fetchone(
            f"SELECT stock_on_hand, stock_reserved FROM {table('products')} "
            "WHERE id = :p", {"p": liability["product_id"]},
        )
        epoch = await conn.fetchone(
            f"SELECT state FROM {table('cutover_epochs')} WHERE id = :e",
            {"e": epoch_id},
        )
    assert (product["stock_on_hand"], product["stock_reserved"]) == (2, 0)
    assert epoch["state"] == "reconciling"

    # source reactivation re-blocks the epoch via the pass
    async def reactivated():
        return {"disabled": False, "reason_code": "legacy-active"}

    monkeypatch.setattr(cutover, "old_source_status", reactivated)
    report = await cutover.cutover_reconcile_pass()
    assert report["reblocked"] >= 1
    async with db.connect() as conn:
        epoch = await conn.fetchone(
            f"SELECT state FROM {table('cutover_epochs')} WHERE id = :e",
            {"e": epoch_id},
        )
    assert epoch["state"] == "blocked"


async def test_abort_during_reconcile_retains_holds(runtime_env, monkeypatch):
    from infinitemarkets.db import db, table

    client, headers, merchant_id, epoch_id, liability = await _verified_epoch(
        runtime_env, monkeypatch, qty=1, instance="t-abort-holds",
    )
    action_url = f"{API}/migration/cutovers/{epoch_id}/liabilities/{liability['id']}"
    assert (await client.post(
        action_url, headers=headers, json={"action": "partition"},
    )).status_code == 200
    aborted = await client.post(
        f"{API}/migration/cutovers/{epoch_id}/abort", headers=headers,
    )
    assert aborted.status_code == 200 and aborted.json()["state"] == "blocked"
    async with db.connect() as conn:
        part = await conn.fetchone(
            f"SELECT state FROM {table('liability_partitions')} WHERE epoch_id = :e",
            {"e": epoch_id},
        )
        product = await conn.fetchone(
            f"SELECT stock_reserved, draft, visibility FROM {table('products')} "
            "WHERE id = :p", {"p": liability["product_id"]},
        )
    # the payable hold survives abort; the invoice may still settle
    assert part["state"] == "held" and product["stock_reserved"] == 1
    assert product["draft"] and product["visibility"] == "hidden"


async def test_old_source_requires_installed_and_runtime_disable(
    runtime_env, monkeypatch,
):
    from infinitemarkets.services import cutover

    async def installed(_):
        return SimpleNamespace(active=False, ext_dir="/source")

    async def contract(_):
        return {"code_hash": "a" * 64, "git_commit": "b" * 40}

    async def missing(_):
        return None

    repository_contract = cutover._source_contract

    monkeypatch.setattr(cutover, "get_installed_extension", installed)
    monkeypatch.setattr(cutover, "_source_contract", contract)
    monkeypatch.setattr(
        cutover, "_source_code_hash", lambda _: "a" * 64,
    )
    monkeypatch.setattr(
        cutover, "host_settings",
        SimpleNamespace(lnbits_deactivated_extensions={"nostrmarket"}),
    )
    status = await cutover.old_source_status()
    assert status["disabled"] is True
    assert status["source_contract"]["code_hash"] == "a" * 64
    monkeypatch.setattr(
        cutover, "host_settings", SimpleNamespace(lnbits_deactivated_extensions=set()),
    )
    assert (await cutover.old_source_status())["disabled"] is False
    monkeypatch.setattr(
        cutover, "host_settings",
        SimpleNamespace(lnbits_deactivated_extensions={"nostrmarket"}),
    )
    monkeypatch.setattr(cutover, "_source_contract", missing)
    assert (await cutover.old_source_status())["reason_code"] == "source-contract-missing"
    monkeypatch.setattr(cutover, "_source_contract", contract)
    monkeypatch.setattr(cutover, "_source_code_hash", lambda _: "b" * 64)
    assert (await cutover.old_source_status())["reason_code"] == "source-contract-mismatch"
    monkeypatch.setattr(cutover, "_source_code_hash", lambda _: None)
    assert (await cutover.old_source_status())["reason_code"] == "source-unreadable"
    row = await repository_contract("nostrmarket")
    assert row["git_commit"] == "d941f0a3f94bea94ff6dc1f34a993f8a6aa5934f"
    assert row["code_hash"] == (
        "24759dc45d5d5b9c733031c2eb9142cd618eed3198bd779669bd2ac3ce659d51"
    )


async def test_old_evidence_is_bounded_and_owner_scoped(runtime_env, monkeypatch):
    from lnbits.core.crud.wallets import create_wallet
    from lnbits.db import Database

    from infinitemarkets.security import ProblemError
    from infinitemarkets.services import cutover

    source = Database("ext_nostrmarket")
    user_id = runtime_env["user_id"]
    old_pubkey = "d" * 64
    invoice = "e" * 64
    async with source.connect() as conn:
        await conn.execute(
            "CREATE TABLE nostrmarket.merchants (id TEXT, user_id TEXT, "
            "public_key TEXT, meta TEXT)"
        )
        await conn.execute(
            "CREATE TABLE nostrmarket.stalls (id TEXT, merchant_id TEXT, wallet TEXT)"
        )
        await conn.execute(
            "CREATE TABLE nostrmarket.products (id TEXT, merchant_id TEXT, stall_id TEXT)"
        )
        await conn.execute(
            "CREATE TABLE nostrmarket.orders (id TEXT, merchant_id TEXT, "
            "merchant_public_key TEXT, stall_id TEXT, invoice_id TEXT, order_items TEXT)"
        )
        await conn.execute(
            "INSERT INTO nostrmarket.merchants (id, user_id, public_key, meta) "
            "VALUES ('old-merchant', :u, :p, :meta)",
            {"u": user_id, "p": old_pubkey, "meta": '{"active":false}'},
        )
        await conn.execute(
            "INSERT INTO nostrmarket.stalls (id, merchant_id, wallet) "
            "VALUES ('old-stall', 'old-merchant', :wallet)",
            {"wallet": runtime_env["wallet"].id},
        )
        await conn.execute(
            "INSERT INTO nostrmarket.products (id, merchant_id, stall_id) "
            "VALUES ('old-poster', 'old-merchant', 'old-stall')"
        )
        await conn.execute(
            "INSERT INTO nostrmarket.orders "
            "(id, merchant_id, merchant_public_key, stall_id, invoice_id, order_items) "
            "VALUES ('old-order', 'old-merchant', :p, 'old-stall', :invoice, :items)",
            {"p": old_pubkey, "invoice": invoice,
             "items": json.dumps([{"product_id": "old-poster", "quantity": 1}])},
        )

    async def installed(_):
        return SimpleNamespace(active=False, ext_dir="/source")

    async def contract(_):
        return {"code_hash": "a" * 64, "git_commit": "b" * 40}

    payment = SimpleNamespace(
        payment_hash=invoice, wallet_id=runtime_env["wallet"].id, amount=5000,
        extra={"tag": "nostrmarket", "merchant_pubkey": old_pubkey,
               "order_id": "old-order"},
    )

    async def pages(**_):
        return SimpleNamespace(data=[payment], total=1)

    async def status(_):
        return SimpleNamespace(paid=None)

    monkeypatch.setattr(cutover, "get_installed_extension", installed)
    monkeypatch.setattr(cutover, "_source_contract", contract)
    monkeypatch.setattr(cutover, "_source_code_hash", lambda _: "a" * 64)
    monkeypatch.setattr(
        cutover, "host_settings",
        SimpleNamespace(lnbits_deactivated_extensions={"nostrmarket"}),
    )
    monkeypatch.setattr(cutover, "get_payments_paginated", pages)
    monkeypatch.setattr(cutover, "check_payment_status", status)
    evidence = await cutover.read_old_source_evidence(user_id)
    assert evidence["merchant_id"] == "old-merchant"
    assert evidence["products"] == {"old-poster"}
    assert evidence["invoices"] == [{
        "invoice_id": invoice, "order_id": "old-order",
        "items": [{"product_id": "old-poster", "quantity": 1}], "state": "payable",
    }]
    payment.extra["order_id"] = "missing-order"
    with pytest.raises(ProblemError) as missing:
        await cutover.read_old_source_evidence(user_id)
    assert missing.value.status == 409
    assert invoice not in str(missing.value)
    payment.extra["order_id"] = "old-order"
    second = await create_wallet(user_id=user_id, wallet_name="Second old wallet")
    extra_payment = SimpleNamespace(
        payment_hash="a" * 64, wallet_id=second.id, amount=5000,
        extra={"tag": "nostrmarket", "merchant_pubkey": old_pubkey,
               "order_id": "missing-order"},
    )

    async def multiple_wallet_pages(**kwargs):
        return SimpleNamespace(
            data=[extra_payment if kwargs["wallet_id"] == second.id else payment], total=1
        )

    monkeypatch.setattr(cutover, "get_payments_paginated", multiple_wallet_pages)
    with pytest.raises(ProblemError) as extra_wallet:
        await cutover.read_old_source_evidence(user_id)
    assert extra_wallet.value.status == 409
    extra_payment.payment_hash = invoice
    extra_payment.extra["order_id"] = "old-order"
    with pytest.raises(ProblemError) as wrong_wallet:
        await cutover.read_old_source_evidence(user_id)
    assert wrong_wallet.value.status == 409

    async def unowned(_):
        return SimpleNamespace(user="other", can_view_payments=True)

    monkeypatch.setattr(cutover, "get_wallet", unowned)
    with pytest.raises(ProblemError) as denied:
        await cutover.read_old_source_evidence(user_id)
    assert denied.value.status == 409

    async def owned(wallet_id):
        return SimpleNamespace(id=wallet_id, user=user_id, can_view_payments=True)

    async def excessive(**_):
        return SimpleNamespace(data=[], total=5001)

    monkeypatch.setattr(cutover, "get_wallet", owned)
    monkeypatch.setattr(cutover, "get_payments_paginated", excessive)
    with pytest.raises(ProblemError) as overflow:
        await cutover.read_old_source_evidence(user_id)
    assert overflow.value.status == 409
    async with source.connect() as conn:
        await conn.execute(
            "UPDATE nostrmarket.merchants SET meta = :meta WHERE id = 'old-merchant'",
            {"meta": '{"active":true}'},
        )
    async def legitimate(**kwargs):
        if kwargs["wallet_id"] == runtime_env["wallet"].id:
            return SimpleNamespace(data=[payment], total=1)
        return SimpleNamespace(data=[], total=0)

    monkeypatch.setattr(cutover, "get_payments_paginated", legitimate)
    with pytest.raises(ProblemError) as reactivated:
        await cutover.read_old_source_evidence(user_id)
    assert reactivated.value.status == 409


async def test_old_source_comparison_rejects_missing_and_extra_invoices(runtime_env):
    from infinitemarkets import crypto
    from infinitemarkets.security import ProblemError
    from infinitemarkets.services import cutover
    from infinitemarkets.settings import ext_settings

    merchant_id = "new-merchant"
    invoice = "f" * 64
    source = {
        "merchant_id": "old-merchant", "products": {"old-poster"},
        "invoices": [{"invoice_id": invoice, "order_id": "old-order",
                      "items": [{"product_id": "old-poster", "quantity": 1}],
                      "state": "payable"}],
    }
    key = ext_settings().privacy_key
    audit = {
        "id": "import-1", "source_kind": "nostrmarket",
        "rows": [{"legacy_id": "old-poster", "product_id": "new-product"}],
        "liabilities": [{"product_id": "new-product", "quantity": 1,
                         "invoice_hash": crypto.hmac_index(
                             key, "legacy-invoice", merchant_id, invoice),
                         "order_hash": crypto.hmac_index(
                             key, "legacy-order", merchant_id, "old-order")}],
    }
    checked = cutover.compare_old_source(merchant_id, audit, source)
    assert checked["payable_quantity"] == 1
    assert checked["paid_quantity"] == 0
    assert checked["source_product_count"] == 1
    assert invoice not in json.dumps(checked)
    missing = {**source, "invoices": []}
    with pytest.raises(ProblemError) as incomplete:
        cutover.compare_old_source(merchant_id, audit, missing)
    assert incomplete.value.status == 409
    extra = {**source, "invoices": source["invoices"] + [
        {**source["invoices"][0], "invoice_id": "b" * 64},
    ]}
    with pytest.raises(ProblemError) as unclaimed:
        cutover.compare_old_source(merchant_id, audit, extra)
    assert unclaimed.value.status == 409
    wrong_product = {**source, "products": {"old-poster", "unimported"}}
    with pytest.raises(ProblemError) as incomplete_catalog:
        cutover.compare_old_source(merchant_id, audit, wrong_product)
    assert incomplete_catalog.value.status == 409


async def test_shopify_source_cannot_start_unverifiable_cutover(runtime_env):
    from pathlib import Path

    client = runtime_env["client"]
    await client.get(f"{API}/merchants/current")
    headers = {"Origin": "https://shop.example",
               "X-CSRF-Token": client.cookies.get("gm_csrf")}
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "shopify_products_sample.csv"
    upload = {"file": ("sample.csv", fixture.read_bytes(), "text/csv")}
    form = {"currency": "USD", "source_instance": "shopify-not-verifiable"}
    preview = await client.post(
        f"{API}/migration/shopify/preview", data=form, files=upload, headers=headers
    )
    assert preview.status_code == 200
    form["source_hash"] = preview.json()["source_hash"]
    imported = await client.post(
        f"{API}/migration/shopify/execute", data=form, files=upload, headers=headers
    )
    assert imported.status_code == 200, imported.text
    blocked = await client.post(
        f"{API}/migration/imports/{imported.json()['import_id']}/cutover",
        headers=headers,
    )
    assert blocked.status_code == 409
