import json
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.runtime

API = "/infinitemarkets/api/v1"


async def test_staging_requires_owned_legacy_import_and_never_authorizes_stock(runtime_env):
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
    aborted = await client.post(
        f"{API}/migration/cutovers/{epoch_id}/abort", headers=headers
    )
    assert aborted.status_code == 200 and aborted.json()["state"] == "blocked"
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
    assert row["draft"] and not row["import_authorized"]
    assert row["status"] == "unverified" and holds["n"] == 0
    restarted = await client.post(stage_url, headers=headers)
    assert restarted.status_code == 200
    assert restarted.json()["id"] != epoch_id
    assert restarted.json()["state"] == "staged"


async def test_old_source_requires_installed_and_runtime_disable(monkeypatch):
    from infinitemarkets.services import cutover

    async def installed(_):
        return SimpleNamespace(active=False)

    monkeypatch.setattr(cutover, "get_installed_extension", installed)
    monkeypatch.setattr(
        cutover, "host_settings",
        SimpleNamespace(lnbits_deactivated_extensions={"nostrmarket"}),
    )
    assert (await cutover.old_source_status())["disabled"] is True
    monkeypatch.setattr(
        cutover, "host_settings", SimpleNamespace(lnbits_deactivated_extensions=set()),
    )
    assert (await cutover.old_source_status())["disabled"] is False


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
