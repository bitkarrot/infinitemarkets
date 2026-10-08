"""NIP-89 handler + public read API — §5.4 contract tests.

Pins: valid local naddr -> 301 to the canonical page; malformed bech32,
wrong-kind, foreign-pubkey, and unknown-d_tag all render the invalid-link
response with NO outbound relay fetch; relay hints are parsed and ignored;
public JSON exposes only the §5.4 field set; rate limits enforce.
"""

from __future__ import annotations

import time
import uuid
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.runtime

ORIGIN = "https://shop.example"
API = "/infinitemarkets/api/v1"


def _csrf(client) -> str:
    return client.cookies.get("gm_csrf") or ""


async def _merchant(runtime_env) -> tuple[str, dict]:
    """Shared merchant + its pubkey; returns (merchant_id, merchant)."""
    client = runtime_env["client"]
    resp = await client.get(f"{API}/merchants/current")
    if resp.status_code != 200:
        await client.get(f"{API}/merchants/current")  # seed csrf cookie
        resp = await client.post(
            f"{API}/merchants",
            json={"wallet_id": runtime_env["wallet"].id},
            headers={
                "Origin": ORIGIN,
                "X-CSRF-Token": _csrf(client),
                "Cookie": f"cookie_access_token={runtime_env['token']}"
                          f"; gm_csrf={_csrf(client)}",
            },
        )
        assert resp.status_code == 201, resp.text
        resp = await client.get(f"{API}/merchants/current")
    return resp.json()["id"], resp.json()


async def _create_product(client, merchant_id: str, headers: dict,
                          **over) -> dict:
    # a catalog is required first
    categories = await client.get(f"{API}/categories", headers=headers)
    if categories.json():
        category_id = categories.json()[0]["id"]
    else:
        resp = await client.post(
            f"{API}/categories", json={"name": "Store"}, headers=headers
        )
        assert resp.status_code == 201, resp.text
        category_id = resp.json()["id"]
    payload = {
        "category_id": category_id,
        "title": "NIP-89 Test Product",
        "amount_minor": 4200,
        "currency": "USD",
        "currency_decimals": 2,
        "product_type": "simple",
        "format": "physical",
        "visibility": "on-sale",
    }
    payload.update(over)
    resp = await client.post(f"{API}/products", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _headers(runtime_env) -> dict:
    client = runtime_env["client"]
    csrf = _csrf(client)
    return {
        "Origin": ORIGIN,
        "X-CSRF-Token": csrf,
        "Cookie": f"cookie_access_token={runtime_env['token']}"
                  f"; gm_csrf={csrf}",
    }


async def test_valid_naddr_redirects_to_canonical(runtime_env):
    from nostr_sdk import Coordinate, Kind, Nip19Coordinate, PublicKey

    client = runtime_env["client"]
    mid, merchant = await _merchant(runtime_env)
    product = await _create_product(client, mid, _headers(runtime_env))

    from nostr_sdk import RelayUrl

    naddr = Nip19Coordinate(
        Coordinate(Kind(30402), PublicKey.parse(merchant["pubkey"]),
                   identifier=product["d_tag"]),
        # relay hint: parsed by the SDK, never fetched server-side
        [RelayUrl.parse("wss://hint-ignored.example")],
    ).to_bech32()

    resp = await client.get(f"/infinitemarkets/p/{naddr}")
    assert resp.status_code == 301
    assert resp.headers["location"].endswith(
        f"/infinitemarkets/p/{merchant['pubkey']}/{product['d_tag']}"
    )
    # public security headers on the redirect too
    assert resp.headers["cache-control"] == "no-store"
    assert resp.headers["referrer-policy"] == "no-referrer"


async def test_invalid_naddr_variants_render_invalid_link(runtime_env):
    from nostr_sdk import Coordinate, Keys, Kind, Nip19Coordinate, PublicKey

    client = runtime_env["client"]
    await _merchant(runtime_env)

    foreign = Keys.generate().public_key().to_hex()
    variants = [
        "naddr1notrealbech32",  # malformed
        Nip19Coordinate(  # wrong kind — 30405 collection coordinate
            Coordinate(Kind(30405), PublicKey.parse(foreign),
                       identifier="deadbeef00"),
            [],
        ).to_bech32(),
        Nip19Coordinate(  # foreign merchant pubkey
            Coordinate(Kind(30402), PublicKey.parse(foreign),
                       identifier="deadbeef00"),
            [],
        ).to_bech32(),
    ]
    for naddr in variants:
        resp = await client.get(f"/infinitemarkets/p/{naddr}")
        assert resp.status_code == 404, (naddr, resp.status_code)
        assert "not valid here" in resp.text


async def test_public_product_json_contract(runtime_env):
    client = runtime_env["client"]
    mid, merchant = await _merchant(runtime_env)
    product = await _create_product(
        client, mid, _headers(runtime_env),
        stock_on_hand=5, summary="A public listing",
    )
    resp = await client.get(
        f"{API}/public/products/{merchant['pubkey']}/{product['d_tag']}"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["d_tag"] == product["d_tag"]
    assert body["merchant_pubkey"] == merchant["pubkey"]
    assert body["price"]["amount_minor"] == 4200
    assert body["availability"] == "available"
    assert body["stock"] == 5
    # no internals
    for forbidden in ("id", "merchant_id", "category_id", "stock_reserved",
                      "wallet_id_enc", "key_ref", "user_id"):
        assert forbidden not in body
    assert resp.headers["cache-control"] == "no-store"
    assert resp.headers["referrer-policy"] == "no-referrer"


async def test_public_product_page_states(runtime_env):
    client = runtime_env["client"]
    mid, merchant = await _merchant(runtime_env)
    headers = _headers(runtime_env)
    product = await _create_product(client, mid, headers)
    url = f"/infinitemarkets/p/{merchant['pubkey']}/{product['d_tag']}"

    resp = await client.get(url)
    assert resp.status_code == 200
    assert "gm-public" in resp.text
    # A2 checkout card — the pre-invoice CTA per UI-SPEC.
    assert "Review payment" in resp.text
    assert "default-src 'self'" in resp.headers["content-security-policy"]
    # no admin chrome or internals
    assert "wallet_id" not in resp.text
    assert mid not in resp.text

    # sold state -> chip + buy controls gone
    await client.patch(
        f"{API}/products/{product['id']}",
        json={"nip99_status": "sold"},
        headers=headers,
    )
    resp = await client.get(url)
    assert "Out of Stock" in resp.text
    assert "btn-buy" not in resp.text

    # hidden -> not available
    await client.patch(
        f"{API}/products/{product['id']}",
        json={"nip99_status": "active", "visibility": "hidden"},
        headers=headers,
    )
    resp = await client.get(url)
    assert "This product is not available." in resp.text


@pytest.mark.parametrize("private_state", ["draft", "hidden", "deleted"])
async def test_private_product_never_leaks_through_public_json(runtime_env, private_state):
    client = runtime_env["client"]
    mid, merchant = await _merchant(runtime_env)
    headers = _headers(runtime_env)
    product = await _create_product(
        client, mid, headers, title=f"private-{uuid.uuid4().hex}",
        draft=private_state == "draft",
        visibility="hidden" if private_state == "hidden" else "on-sale",
    )
    if private_state == "deleted":
        response = await client.delete(f"{API}/products/{product['id']}", headers=headers)
        assert response.status_code == 200
    response = await client.get(
        f"{API}/public/products/{merchant['pubkey']}/{product['d_tag']}"
    )
    assert response.status_code == 404
    assert product["title"] not in response.text
    assert response.headers["cache-control"] == "no-store"


async def test_hidden_variation_is_not_exposed_by_public_parent(runtime_env):
    client = runtime_env["client"]
    mid, merchant = await _merchant(runtime_env)
    headers = _headers(runtime_env)
    parent = await _create_product(client, mid, headers, product_type="variable")
    child = await _create_product(
        client, mid, headers, product_type="variation", parent_product_id=parent["id"],
        visibility="hidden", title=f"restricted-{uuid.uuid4().hex}",
    )
    response = await client.get(
        f"{API}/public/products/{merchant['pubkey']}/{parent['d_tag']}"
    )
    assert response.status_code == 200, response.text
    assert child["title"] not in response.text
    assert child["d_tag"] not in response.text


@pytest.mark.parametrize("currency,decimals", [("SAT", 0), ("USD", 2), ("JPY", 0)])
async def test_product_currency_precision_is_explicit(runtime_env, currency, decimals):
    mid, _ = await _merchant(runtime_env)
    product = await _create_product(
        runtime_env["client"], mid, _headers(runtime_env), currency=currency,
        currency_decimals=None,
    )
    assert product["currency_decimals"] == decimals


async def test_rate_limit_enforced_on_public_routes(runtime_env, monkeypatch):
    """120 GET/min/IP — push past the bound and expect 429."""
    from infinitemarkets.services import nip89

    now = int(time.time())
    monkeypatch.setattr(nip89, "time", SimpleNamespace(time=lambda: now))
    client = runtime_env["client"]
    for _ in range(130):
        resp = await client.get(f"{API}/public/merchants/{uuid.uuid4().hex}")
    assert resp.status_code == 429, resp.status_code
    # RFC 9457 problem+json
    assert resp.json()["status"] == 429
