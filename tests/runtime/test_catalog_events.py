"""Deterministic event builders (§6) + outbox supersession/deps (§8.6).

Pure unit tests — builders are pure functions of domain rows; outbox tests
use the ``keystore_env`` tmp database with m001 applied.
"""

from __future__ import annotations

import importlib
import json

import pytest

pytestmark = pytest.mark.runtime

PUBKEY = "ab" * 32


def _product(**over):
    base = {
        "d_tag": "beans-0001",
        "parent_product_id": None,
        "product_type": "simple",
        "format": "physical",
        "title": "beans",
        "summary": "good beans",
        "description_md": "# beans",
        "amount_minor": 1500,
        "currency": "USD",
        "currency_decimals": 2,
        "recurring_frequency": None,
        "visibility": "on-sale",
        "nip99_status": "active",
        "stock_on_hand": 10,
        "stock_reserved": 2,
        "location": "Berlin",
        "geohash": "u33dc1r",
        "weight_value": 1,
        "weight_unit": "kg",
        "dim_l": 10, "dim_w": 5, "dim_h": 5, "dim_unit": "cm",
        "published_at": 1700000000,
        "nip15_product_id": None,
    }
    base.update(over)
    return base


def _build(events, **kw):
    return events.product_event(
        _product(**kw.pop("product", {})),
        pubkey=PUBKEY,
        spec_revision="5dc79c5",
        images=kw.pop("images", []),
        specs=kw.pop("specs", [{"key": "size", "value": "1kg"}]),
        categories=kw.pop("categories", ["coffee"]),
        member_collection_d_tags=kw.pop("member_collection_d_tags",
                                        ["col-aaaa"]),
        shipping_refs=kw.pop("shipping_refs", []),
    )


def _events():
    return importlib.import_module("infinitemarkets.services.events")


async def test_product_event_deterministic():
    events = _events()
    e1 = _build(events)
    e2 = _build(events)
    assert e1 == e2
    assert json.dumps(e1, sort_keys=True) == json.dumps(e2, sort_keys=True)


async def test_product_event_required_tags():
    events = _events()
    ev = _build(events)
    assert ev["kind"] == 30402
    assert ev["content"] == "# beans"
    tags = ev["tags"]
    by_key = {}
    for t in tags:
        by_key.setdefault(t[0], []).append(t)
    assert by_key["d"][0][1] == "beans-0001"
    assert by_key["title"][0][1] == "beans"
    # fixed-point decimal, no scientific notation
    assert by_key["price"][0] == ["price", "15.00", "USD"]
    assert by_key["type"][0] == ["type", "simple", "physical"]
    assert by_key["visibility"][0] == ["visibility", "on-sale"]
    # finite stock = on_hand - reserved
    assert by_key["stock"][0] == ["stock", "8"]
    assert by_key["status"][0] == ["status", "active"]
    assert by_key["published_at"][0] == ["published_at", "1700000000"]
    # NIP-32 self-describing labels present on commerce kinds
    assert ["L", "org.infinitemarkets.protocol"] in tags
    assert any(t[0] == "l" and t[1] == "5dc79c5" for t in tags)


async def test_product_event_recurring_and_sold():
    events = _events()
    ev = _build(events, product={
        "recurring_frequency": "W", "nip99_status": "sold"})
    price = next(t for t in ev["tags"] if t[0] == "price")
    assert price == ["price", "15.00", "USD", "W"]
    assert ["status", "sold"] in ev["tags"]


async def test_product_event_variation_single_parent_a():
    events = _events()
    ev = _build(
        events,
        product={
            "product_type": "variation",
            "parent_product_id": "p1",
            "_parent_d_tag": "shirt-base",
        },
    )
    a_tags = [t for t in ev["tags"]
              if t[0] == "a" and t[1].startswith("30402:")]
    assert a_tags == [["a", f"30402:{PUBKEY}:shirt-base"]]
    # collection a-tags coexist, sorted
    assert ["a", f"30405:{PUBKEY}:col-aaaa"] in ev["tags"]


async def test_product_event_unlimited_stock_omits_stock_tag():
    events = _events()
    ev = _build(events, product={"stock_on_hand": None})
    assert not any(t[0] == "stock" for t in ev["tags"])


async def test_collection_event():
    events = _events()
    col = {
        "d_tag": "summer", "title": "Summer", "description": "d" * 300,
        "image": "https://x.example/i.png", "location": "Berlin",
        "geohash": "u33d",
    }
    ev = events.collection_event(
        col, pubkey=PUBKEY, spec_revision="5dc79c5",
        member_d_tags=["b-product", "a-product"],
        shipping_d_tags=["std-post"],
    )
    assert ev["kind"] == 30405
    a_tags = [t for t in ev["tags"] if t[0] == "a"]
    assert a_tags == [
        ["a", f"30402:{PUBKEY}:a-product"],
        ["a", f"30402:{PUBKEY}:b-product"],
    ]
    summary = next(t for t in ev["tags"] if t[0] == "summary")
    assert len(summary[1]) == 280  # truncated
    assert ["shipping_option", f"30406:{PUBKEY}:std-post"] in ev["tags"]


async def test_shipping_event():
    events = _events()
    opt = {
        "d_tag": "std-post", "title": "Standard",
        "description": "tracked", "base_price_minor": 550,
        "currency": "USD", "service": "standard",
        "countries": json.dumps(["US", "DE"]),
        "regions": json.dumps(["US-CA"]),
        "carrier": "post", "duration_min": 2, "duration_max": 5,
        "duration_unit": "D",
        "weight_min": 0, "weight_max": 10, "weight_unit": "kg",
        "price_weight_minor": 100, "price_weight_unit": "kg",
    }
    ev = events.shipping_event(opt, pubkey=PUBKEY, spec_revision="5dc79c5")
    assert ev["kind"] == 30406
    tags = ev["tags"]
    assert ["price", "5.50", "USD"] in tags
    countries = [t for t in tags if t[0] == "country"]
    assert countries == [["country", "DE"], ["country", "US"]]
    assert ["region", "US-CA"] in tags
    assert ["service", "standard"] in tags
    assert ["duration", "2", "5", "D"] in tags
    assert ["price-weight", "1.00", "USD", "kg"] in tags


async def test_identity_and_handler_events_have_no_labels():
    events = _events()
    merchant = {
        "display_name": "shop",
        "profile_json": json.dumps({
            "about": "Handmade goods",
            "picture": "https://cdn.example/avatar.png",
        }),
        "recommended_app_d": "infinitemarkets",
    }
    profile = events.merchant_profile_event(merchant, pubkey=PUBKEY)
    assert profile["kind"] == 0
    content = json.loads(profile["content"])
    assert content["name"] == "shop"
    assert content["about"] == "Handmade goods"
    assert content["picture"] == "https://cdn.example/avatar.png"
    assert not any(t[0] in ("L", "l") for t in profile["tags"])

    rec = events.handler_recommendation_event(merchant, pubkey=PUBKEY)
    assert rec["kind"] == 31989
    # d is the SUPPORTED KIND, not the app id
    assert ["d", "30402"] in rec["tags"]
    assert ["a", f"31990:{PUBKEY}:infinitemarkets", "", "web"] in rec["tags"]

    info = events.handler_info_event(
        merchant, pubkey=PUBKEY, public_base_url="https://shop.example"
    )
    assert info["kind"] == 31990
    assert ["d", "infinitemarkets"] in info["tags"]
    assert ["k", "30402"] in info["tags"]


async def test_tombstone_descriptor():
    events = _events()
    tomb = events.tombstone_intent(
        pubkey=PUBKEY, kind=30402, d_tag="beans-0001"
    )
    assert tomb["kind"] == 5
    assert ["a", f"30402:{PUBKEY}:beans-0001"] in tomb["tags"]
    assert ["k", "30402"] in tomb["tags"]


async def test_nip15_projection():
    events = _events()
    stall = events.stall_event(
        {
            "nip15_stall_d": "stall-1", "name": "shop",
            "description": "d", "default_currency": "USD",
        },
        zones=[
            {"id": "std-post", "name": "Standard", "cost_minor": 550,
             "currency_decimals": 2, "regions": ["US", "DE", "US-CA"]},
            events.digital_zone(),
        ],
    )
    assert stall["kind"] == 30017
    assert stall["tags"] == [["d", "stall-1"]]
    content = json.loads(stall["content"])
    assert content["currency"] == "USD"
    assert content["shipping"][0]["id"] == "digital"  # sorted first
    std = next(z for z in content["shipping"] if z["id"] == "std-post")
    assert std["cost"] == 5.5
    assert std["regions"] == ["DE", "US", "US-CA"]  # countries+regions flat

    prod = events.nip15_product_event(
        _product(), stall_d="stall-1", stall_currency="USD",
        images=[{"url": "https://x.example/a.png"}],
        specs=[{"key": "size", "value": "1kg"}],
        shipping_surcharges=[{"d_tag": "std-post", "extra_cost_minor": 150}],
    )
    assert prod["kind"] == 30018
    assert prod["tags"] == [["d", "beans-0001"]]
    content = json.loads(prod["content"])
    assert content["id"] == "beans-0001"  # d == content.id
    assert content["stall_id"] == "stall-1"
    assert content["price"] == 15.0
    assert content["quantity"] == 8
    assert content["specs"] == [["size", "1kg"]]
    # extra-cost surcharge is per-unit product cost, NOT added to zone base
    assert content["shipping"] == [{"id": "std-post", "cost": 1.5}]


async def test_nip15_hidden_and_digital():
    events = _events()
    hidden = events.nip15_product_event(
        _product(visibility="hidden"),
        stall_d="s", stall_currency="USD",
    )
    assert json.loads(hidden["content"])["quantity"] == 0

    digital = events.nip15_product_event(
        _product(format="digital", stock_on_hand=None),
        stall_d="s", stall_currency="USD",
    )
    content = json.loads(digital["content"])
    assert content["quantity"] is None  # unlimited
    assert content["shipping"] == [{"id": "digital", "cost": 0}]


async def test_nip15_currency_mismatch_is_error():
    events = _events()
    with pytest.raises(events.CompatibilityError):
        events.nip15_product_event(
            _product(currency="EUR"),
            stall_d="s", stall_currency="USD",
        )


async def test_nip15_variation_id_composition_and_fallback():
    events = _events()
    var = _product(product_type="variation", d_tag="red-m")
    assert events.nip15_product_id(var, "shirt") == "shirt-red-m"

    # oversized composite -> deterministic hash fallback
    long_parent = "p" * 60
    var2 = _product(product_type="variation", d_tag="x" * 40)
    pid = events.nip15_product_id(var2, long_parent)
    assert pid.startswith("v-") and len(pid) == 34
    assert pid == events.nip15_product_id(var2, long_parent)

    # persisted id always wins
    var3 = _product(product_type="variation", d_tag="red-m",
                    nip15_product_id="legacy-42")
    assert events.nip15_product_id(var3, "shirt") == "legacy-42"


# --- outbox (§8.6) ---------------------------------------------------------------

_MID = "m-outbox"


async def _enqueue(env, agg_type, agg_id, kind, revision=0,
                   address=None, deps=None):
    outbox = importlib.import_module("infinitemarkets.services.outbox")
    db_mod = importlib.import_module("infinitemarkets.db")
    async with db_mod.DomainTransaction() as tx:
        return await outbox.enqueue_intent(
            tx, _MID, agg_type, agg_id, kind,
            revision=revision, event_address=address,
            depends_on=deps or [],
        )


async def _intents(env, aggregate_id=None):
    db_mod = importlib.import_module("infinitemarkets.db")
    sql = (
        "SELECT * FROM infinitemarkets.outbox_events WHERE merchant_id = :m"
    )
    params = {"m": _MID}
    if aggregate_id:
        sql += " AND aggregate_id = :a"
        params["a"] = aggregate_id
    async with db_mod.db.connect() as conn:
        rows = await conn.fetchall(sql + " ORDER BY created_at, id", params)
    return [dict(r) for r in rows]


async def test_outbox_enqueue_and_supersession(keystore_env):
    first = await _enqueue(keystore_env, "products", "p1", 30402,
                           revision=1)
    intents = await _intents(keystore_env, "p1")
    assert len(intents) == 1
    assert intents[0]["state"] == "pending"
    assert intents[0]["aggregate_revision"] == 1

    # same aggregate+revision+kind -> idempotent, returns existing row
    again = await _enqueue(keystore_env, "products", "p1", 30402,
                           revision=1)
    assert again == first
    assert len(await _intents(keystore_env, "p1")) == 1

    # newer revision supersedes the stale intent
    second = await _enqueue(keystore_env, "products", "p1", 30402,
                            revision=2)
    assert second != first
    intents = await _intents(keystore_env, "p1")
    by_id = {i["id"]: i for i in intents}
    assert by_id[first]["state"] == "superseded"
    assert by_id[second]["state"] == "pending"


async def test_outbox_dependency_edges(keystore_env):
    col = await _enqueue(keystore_env, "collections", "c1", 30405,
                         revision=1)
    prod = await _enqueue(
        keystore_env, "products", "p2", 30402, revision=1,
        deps=[("collections", "c1")],
    )
    db_mod = importlib.import_module("infinitemarkets.db")
    async with db_mod.db.connect() as conn:
        edges = await conn.fetchall(
            "SELECT depends_on_outbox_event_id AS d "
            "FROM infinitemarkets.outbox_dependencies "
            "WHERE outbox_event_id = :e",
            {"e": prod},
        )
    assert [e["d"] for e in edges] == [col]

    # deps bind to the LATEST live intent: superseding the collection
    # intent then adding another dependent points at the new row
    col2 = await _enqueue(keystore_env, "collections", "c1", 30405,
                          revision=2)
    prod2 = await _enqueue(
        keystore_env, "products", "p3", 30402, revision=1,
        deps=[("collections", "c1")],
    )
    async with db_mod.db.connect() as conn:
        edges = await conn.fetchall(
            "SELECT depends_on_outbox_event_id AS d "
            "FROM infinitemarkets.outbox_dependencies "
            "WHERE outbox_event_id = :e",
            {"e": prod2},
        )
    assert [e["d"] for e in edges] == [col2]

    # dependency on an aggregate with no live intent -> no edge (not an
    # error: e.g. tombstoned/unpublished refs are dropped)
    orphan = await _enqueue(
        keystore_env, "products", "p4", 30402, revision=1,
        deps=[("collections", "nonexistent")],
    )
    async with db_mod.db.connect() as conn:
        edges = await conn.fetchall(
            "SELECT * FROM infinitemarkets.outbox_dependencies "
            "WHERE outbox_event_id = :e",
            {"e": orphan},
        )
    assert edges == []
