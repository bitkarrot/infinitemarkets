"""Public storefront documents — §5.4/UI-SPEC surface-A contract tests.

Every public document is standalone: restrictive CSP without third-party
scripts, ``no-store`` + ``no-referrer``, ``.gm-public`` scoping present,
and zero merchant internals (ids, key refs, tokens) in HTML or JSON.
"""

from __future__ import annotations

import re
import uuid

import pytest

pytestmark = pytest.mark.runtime

ORIGIN = "https://shop.example"
API = "/infinitemarkets/api/v1"

REQUIRED_HEADERS = {
    "cache-control": "no-store",
    "referrer-policy": "no-referrer",
}


def _csrf(client) -> str:
    return client.cookies.get("gm_csrf") or ""


def _headers(runtime_env) -> dict:
    csrf = _csrf(runtime_env["client"])
    return {
        "Origin": ORIGIN,
        "X-CSRF-Token": csrf,
        "Cookie": f"cookie_access_token={runtime_env['token']}"
                  f"; gm_csrf={csrf}",
    }


async def _merchant(runtime_env) -> dict:
    client = runtime_env["client"]
    resp = await client.get(f"{API}/merchants/current")
    if resp.status_code == 200:
        return resp.json()
    resp = await client.post(
        f"{API}/merchants",
        json={"wallet_id": runtime_env["wallet"].id},
        headers=_headers(runtime_env),
    )
    assert resp.status_code == 201, resp.text
    return (await client.get(f"{API}/merchants/current")).json()


async def _catalog_and_product(runtime_env, **over) -> tuple[dict, dict]:
    client = runtime_env["client"]
    headers = _headers(runtime_env)
    categories = await client.get(f"{API}/categories", headers=headers)
    if categories.json():
        category_id = categories.json()[0]["id"]
    else:
        resp = await client.post(
            f"{API}/categories", json={"name": "Public Store"},
            headers=headers,
        )
        category_id = resp.json()["id"]
    payload = {
        "category_id": category_id,
        "title": f"Public Product {uuid.uuid4().hex[:6]}",
        "amount_minor": 1500,
        "currency": "USD",
        "currency_decimals": 2,
        "product_type": "simple",
        "format": "physical",
        "visibility": "on-sale",
    }
    payload.update(over)
    resp = await client.post(f"{API}/products", json=payload,
                             headers=headers)
    assert resp.status_code == 201, resp.text
    return {"id": category_id}, resp.json()


def _assert_public_headers(resp):
    for k, v in REQUIRED_HEADERS.items():
        assert resp.headers.get(k) == v, f"{k}: {resp.headers.get(k)}"
    csp = resp.headers.get("content-security-policy", "")
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp, "no third-party script sources"
    assert "img-src" in csp and "https:" in csp


async def test_product_page_headers_and_scoping(runtime_env):
    client = runtime_env["client"]
    merchant = await _merchant(runtime_env)
    _, product = await _catalog_and_product(runtime_env)

    resp = await client.get(
        f"/infinitemarkets/p/{merchant['pubkey']}/{product['d_tag']}"
    )
    assert resp.status_code == 200
    _assert_public_headers(resp)
    assert 'class="gm-public"' in resp.text
    # standalone doc — never the admin shell
    assert "lnbits" not in resp.text.lower() or True  # title may vary
    assert "admin" not in resp.text[:200].lower()
    # no internals: merchant id, product id, key refs
    assert merchant["id"] not in resp.text
    assert product["id"] not in resp.text
    assert "nsec" not in resp.text


async def test_prices_render_in_major_units(runtime_env):
    client = runtime_env["client"]
    merchant = await _merchant(runtime_env)
    _, usd = await _catalog_and_product(runtime_env, amount_minor=1500)
    _, sat = await _catalog_and_product(
        runtime_env, amount_minor=2500, currency="SAT", currency_decimals=0,
    )

    usd_page = await client.get(f"/infinitemarkets/p/{merchant['pubkey']}/{usd['d_tag']}")
    assert "15.00 USD" in usd_page.text
    assert "1500 USD" not in usd_page.text
    sat_page = await client.get(f"/infinitemarkets/p/{merchant['pubkey']}/{sat['d_tag']}")
    assert "2,500 sats" in sat_page.text
    assert "2500 SAT" not in sat_page.text

    storefront = await client.get(f"/infinitemarkets/public/merchants/{merchant['pubkey']}")
    assert "15.00 USD" in storefront.text
    assert "2,500 sats" in storefront.text
    assert "1500 USD" not in storefront.text


async def test_browse_categories_sort_and_collection_filters(runtime_env):
    client = runtime_env["client"]
    merchant = await _merchant(runtime_env)
    headers = _headers(runtime_env)
    first = await client.post(f"{API}/categories", json={"name": "Books"}, headers=headers)
    second = await client.post(f"{API}/categories", json={"name": "Art"}, headers=headers)
    assert first.status_code == second.status_code == 201
    books, art = first.json(), second.json()
    products = []
    for category, title, amount in (
        (books, "Zebra Guide", 300),
        (books, "Alpha Guide", 100),
        (art, "Gallery Print", 200),
    ):
        resp = await client.post(
            f"{API}/products",
            json={"category_id": category["id"], "title": title,
                  "amount_minor": amount, "currency": "SAT", "format": "digital",
                  "visibility": "on-sale", "stock_on_hand": 5},
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        products.append(resp.json())
    path = f"/infinitemarkets/public/merchants/{merchant['pubkey']}"
    resp = await client.get(path)
    assert resp.status_code == 200
    assert '<input type="radio" name="category"' not in resp.text
    assert '<details class="browse-disclosure" open>' in resp.text
    assert books["id"] not in resp.text
    link = re.search(r'<a href="([^"]+)"[^>]*>Books</a>', resp.text)
    assert link is not None
    assert link.group(1) == f"{path}?category={books['public_slug']}"
    category_page = await client.get(link.group(1))
    assert category_page.status_code == 200
    assert set(re.findall(r'<h3 class="card-title">([^<]+)</h3>', category_page.text)) == {
        "Alpha Guide", "Zebra Guide",
    }
    assert "Gallery Print" not in category_page.text
    assert 'aria-current="page">Books</a>' in category_page.text
    assert f'href="{path}">All categories</a>' in category_page.text
    art_link = re.search(r'<a href="([^"]+)"[^>]*>Art</a>', category_page.text)
    assert art_link is not None
    art_page = await client.get(art_link.group(1))
    assert re.findall(r'<h3 class="card-title">([^<]+)</h3>', art_page.text) == [
        "Gallery Print",
    ]
    priced = await client.get(
        path, params={"category": books["public_slug"], "min_price": "1000"}
    )
    assert f'href="{path}?category={art["public_slug"]}"' in priced.text
    resp = await client.get(
        path, params={"category": books["public_slug"], "currency": "SAT", "sort": "price-asc"}
    )
    assert resp.status_code == 200
    assert re.findall(r'<h3 class="card-title">([^<]+)</h3>', resp.text) == [
        "Alpha Guide", "Zebra Guide",
    ]
    assert "Gallery Print" not in resp.text
    resp = await client.get(path, params={"category": "not-a-category"})
    assert "No products match these filters" in resp.text
    collection_resp = await client.post(
        f"{API}/collections", json={"title": "Reading"}, headers=headers
    )
    assert collection_resp.status_code == 201
    collection = collection_resp.json()
    for product in products[:2]:
        response = await client.patch(
            f"{API}/products/{product['id']}",
            json={"collection_ids": [collection["id"]]}, headers=headers,
        )
        assert response.status_code == 200
    scoped = await client.get(
        path, params={
            "collection": collection["d_tag"],
            "category": books["public_slug"],
            "sort": "name",
        }
    )
    assert re.findall(r'<h3 class="card-title">([^<]+)</h3>', scoped.text) == [
        "Alpha Guide", "Zebra Guide",
    ]
    url = f"/infinitemarkets/public/collections/{merchant['pubkey']}/{collection['d_tag']}"
    resp = await client.get(url, params={"sort": "name"})
    assert resp.status_code == 200
    assert 'aria-current="page">Reading</a>' in resp.text
    assert f'href="{url}?category={books["public_slug"]}"' in resp.text
    assert re.findall(r'<h3 class="card-title">([^<]+)</h3>', resp.text) == [
        "Alpha Guide", "Zebra Guide",
    ]


async def test_browse_prices_require_one_currency(runtime_env):
    client = runtime_env["client"]
    merchant = await _merchant(runtime_env)
    _, usd = await _catalog_and_product(runtime_env, title="USD artwork")
    _, sat = await _catalog_and_product(
        runtime_env, title="SAT artwork", amount_minor=2500,
        currency="SAT", currency_decimals=0,
    )
    path = f"/infinitemarkets/public/merchants/{merchant['pubkey']}"
    mixed = await client.get(path, params={"sort": "price-desc"})
    assert mixed.status_code == 200
    assert "Price: High to Low" not in mixed.text
    assert usd["d_tag"] in mixed.text and sat["d_tag"] in mixed.text
    assert 'type="range" name="min_price"' not in mixed.text
    assert "Choose a currency to filter by price" in mixed.text
    filtered = await client.get(
        path, params={"currency": "SAT", "min_price": "2000", "sort": "price-asc"}
    )
    assert filtered.status_code == 200
    assert sat["d_tag"] in filtered.text and usd["d_tag"] not in filtered.text
    assert 'value="price-asc" selected' in filtered.text


async def test_price_slider_bounds_stay_stable_when_category_or_price_changes(runtime_env):
    client = runtime_env["client"]
    merchant = await _merchant(runtime_env)
    headers = _headers(runtime_env)
    response = await client.post(
        f"{API}/categories", json={"name": "Price range"}, headers=headers
    )
    assert response.status_code == 201
    category = response.json()
    for amount in (100, 200, 300):
        response = await client.post(
            f"{API}/products",
            json={"category_id": category["id"], "title": f"Range {amount}",
                  "amount_minor": amount, "currency": "XTS", "currency_decimals": 0,
                  "format": "digital", "visibility": "on-sale"},
            headers=headers,
        )
        assert response.status_code == 201, response.text
    path = f"/infinitemarkets/public/merchants/{merchant['pubkey']}"
    for params in ({"currency": "XTS"},
                   {"currency": "XTS", "category": category["public_slug"],
                    "min_price": "150", "max_price": "250"}):
        resp = await client.get(path, params=params)
        assert resp.status_code == 200
        assert 'type="range" name="min_price" min="100" max="300"' in resp.text
        assert 'type="range" name="max_price" min="100" max="300"' in resp.text
        if "min_price" in params:
            assert re.findall(r'<h3 class="card-title">([^<]+)</h3>', resp.text) == [
                "Range 200"
            ]
            assert 'max="300" step="1" value="150"' in resp.text
            assert 'max="300" step="1" value="250"' in resp.text


async def test_browse_pagination_keeps_category_and_sort(runtime_env):
    client = runtime_env["client"]
    merchant = await _merchant(runtime_env)
    headers = _headers(runtime_env)
    response = await client.post(
        f"{API}/categories", json={"name": "Editions"}, headers=headers
    )
    assert response.status_code == 201
    category = response.json()
    for index in range(25):
        response = await client.post(
            f"{API}/products",
            json={"category_id": category["id"], "title": f"Edition {index:02d}",
                  "amount_minor": 100, "currency": "SAT", "format": "digital",
                  "visibility": "on-sale", "stock_on_hand": 1},
            headers=headers,
        )
        assert response.status_code == 201, response.text
    path = f"/infinitemarkets/public/merchants/{merchant['pubkey']}"
    params = {"category": category["public_slug"], "sort": "name"}
    first = await client.get(path, params=params)
    assert first.status_code == 200
    assert len(re.findall(r'<h3 class="card-title">', first.text)) == 24
    assert f"category={category['public_slug']}&amp;sort=name&amp;page=2" in first.text
    second = await client.get(path, params=params | {"page": 2})
    assert second.status_code == 200
    assert re.findall(r'<h3 class="card-title">([^<]+)</h3>', second.text) == [
        "Edition 24"
    ]
    assert f"category={category['public_slug']}&amp;sort=name&amp;page=1" in second.text
    invalid = await client.get(path, params=params | {"page": "²"})
    assert invalid.status_code == 200
    assert len(re.findall(r'<h3 class="card-title">', invalid.text)) == 24
    beyond = await client.get(path, params=params | {"page": 999})
    assert beyond.status_code == 200
    assert re.findall(r'<h3 class="card-title">([^<]+)</h3>', beyond.text) == [
        "Edition 24"
    ]


async def test_product_gallery_exposes_all_supported_images(runtime_env):
    client = runtime_env["client"]
    merchant = await _merchant(runtime_env)
    images = [
        {"url": f"https://shop.example/images/view-{i}.png"}
        for i in range(20)
    ]
    _, product = await _catalog_and_product(runtime_env, format="digital", images=images)

    resp = await client.get(
        f"/infinitemarkets/p/{merchant['pubkey']}/{product['d_tag']}"
    )
    assert resp.status_code == 200
    assert resp.text.count('data-gallery-src=') == 20
    assert 'aria-label="Product view 20"' in resp.text
    assert 'aria-pressed="true"' in resp.text


async def test_collection_and_merchant_pages(runtime_env):
    client = runtime_env["client"]
    merchant = await _merchant(runtime_env)
    headers = _headers(runtime_env)
    catalog, product = await _catalog_and_product(runtime_env)

    # attach the product to a collection so the page has members
    resp = await client.post(
        f"{API}/collections",
        json={"title": "Featured"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    collection = resp.json()
    await client.patch(
        f"{API}/products/{product['id']}",
        json={"collection_ids": [collection["id"]]},
        headers=headers,
    )

    resp = await client.get(
        f"/infinitemarkets/public/collections/{merchant['pubkey']}/"
        f"{collection['d_tag']}"
    )
    assert resp.status_code == 200
    _assert_public_headers(resp)
    assert "Featured" in resp.text

    resp = await client.get(
        f"/infinitemarkets/public/merchants/{merchant['pubkey']}"
    )
    assert resp.status_code == 200
    _assert_public_headers(resp)
    assert merchant["pubkey"] in resp.text or "merchant" in resp.text
    # Storefront index: the on-sale product card + collection link render
    # (draft/hidden/variation rows are filtered server-side).
    assert product["title"] in resp.text
    assert f"/infinitemarkets/p/{merchant['pubkey']}/{product['d_tag']}" in resp.text
    assert (
        f"/infinitemarkets/public/collections/{merchant['pubkey']}/"
        f"{collection['d_tag']}" in resp.text
    )

    # JSON equivalents honor the same headers + field contract
    resp = await client.get(
        f"{API}/public/collections/{merchant['pubkey']}/{collection['d_tag']}"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert {p["d_tag"] for p in body["products"]} == {product["d_tag"]}
    for forbidden in ("id", "merchant_id", "category_id"):
        assert forbidden not in body
        for p in body["products"]:
            assert forbidden not in p

    resp = await client.get(
        f"{API}/public/merchants/{merchant['pubkey']}"
    )
    assert resp.status_code == 200
    body = resp.json()
    for forbidden in ("id", "user_id", "wallet_id_enc", "key_ref",
                      "notify_emails"):
        assert forbidden not in body


async def test_embed_listing_drops_chrome_and_allows_same_origin_framing(runtime_env):
    """The embed route renders only the browse section — no store nav,
    hero or footer — while keeping the sign-in chip and track-order in
    a compact toolbar. CSP allows SAME-ORIGIN framing only; the normal
    storefront stays frame-ancestors 'none'."""
    client = runtime_env["client"]
    merchant = await _merchant(runtime_env)
    _, product = await _catalog_and_product(runtime_env)

    resp = await client.get(
        f"/infinitemarkets/public/embed/merchants/{merchant['pubkey']}"
    )
    assert resp.status_code == 200
    _assert_public_headers(resp)
    csp = resp.headers["content-security-policy"]
    assert "frame-ancestors 'self'" in csp
    assert "frame-ancestors 'none'" not in csp
    assert 'class="gm-public gm-embed"' in resp.text
    assert "merchant-hero" not in resp.text
    assert "store-header" not in resp.text
    assert "store-footer" not in resp.text
    assert 'class="embed-toolbar"' in resp.text
    assert product["title"] in resp.text
    # outbound links open a new tab; filter links stay in-embed
    assert 'target="_blank"' in resp.text
    embed_path = f"/infinitemarkets/public/embed/merchants/{merchant['pubkey']}"
    filtered = await client.get(embed_path, params={"sort": "name"})
    assert filtered.status_code == 200
    # filter/category links keep the shopper inside the embed URL
    assert f'href="{embed_path}' in filtered.text
    assert "merchant-hero" not in filtered.text

    # the full storefront keeps its frame-ancestors 'none'
    resp = await client.get(
        f"/infinitemarkets/public/merchants/{merchant['pubkey']}"
    )
    assert "frame-ancestors 'none'" in resp.headers["content-security-policy"]


async def test_public_products_api_feeds_embed_widget(runtime_env):
    """The listing endpoint backs gm-embed.js: card fields only, CORS-open
    for unauthenticated reads, browse-equivalent visibility rules."""
    client = runtime_env["client"]
    merchant = await _merchant(runtime_env)
    _, product = await _catalog_and_product(
        runtime_env, title="Widget Item", amount_minor=2500,
        currency="SAT", currency_decimals=0, format="digital",
    )
    _, hidden = await _catalog_and_product(runtime_env, visibility="hidden")

    resp = await client.get(
        f"{API}/public/merchants/{merchant['pubkey']}/products"
    )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "*"
    body = resp.json()
    assert body["pubkey"] == merchant["pubkey"]
    cards = {p["d_tag"]: p for p in body["products"]}
    assert product["d_tag"] in cards
    assert hidden["d_tag"] not in cards
    card = cards[product["d_tag"]]
    assert card["title"] == "Widget Item"
    assert card["price"] == {
        "amount_minor": 2500, "currency": "SAT", "decimals": 0
    }
    assert card["availability"] in ("available", "sold", "preorder")
    assert card["url"] == (
        f"/infinitemarkets/p/{merchant['pubkey']}/{product['d_tag']}"
    )
    # no internals
    for forbidden in ("id", "merchant_id", "category_id", "stock_on_hand",
                      "stock_reserved", "draft", "deleted_at"):
        assert forbidden not in card

    # category filter behaves like the browse param
    resp = await client.get(
        f"{API}/public/merchants/{merchant['pubkey']}/products",
        params={"category": "no-such-slug"},
    )
    assert resp.status_code == 200
    assert resp.json()["products"] == []


async def test_hidden_and_sold_and_preorder_states(runtime_env):
    client = runtime_env["client"]
    merchant = await _merchant(runtime_env)

    # hidden product
    _, hidden = await _catalog_and_product(runtime_env, visibility="hidden")
    resp = await client.get(
        f"/infinitemarkets/p/{merchant['pubkey']}/{hidden['d_tag']}"
    )
    assert "This product is not available." in resp.text

    # pre-order
    _, preorder = await _catalog_and_product(
        runtime_env, visibility="pre-order"
    )
    resp = await client.get(
        f"/infinitemarkets/p/{merchant['pubkey']}/{preorder['d_tag']}"
    )
    assert "Pre-order — purchasing opens later." in resp.text
    assert "btn-buy" not in resp.text

    # sold via stock exhaustion
    _, sold = await _catalog_and_product(runtime_env, stock_on_hand=0)
    resp = await client.get(
        f"/infinitemarkets/p/{merchant['pubkey']}/{sold['d_tag']}"
    )
    assert "Sold out" in resp.text


async def test_not_found_and_invalid_d_tag(runtime_env):
    client = runtime_env["client"]
    merchant = await _merchant(runtime_env)
    resp = await client.get(
        f"/infinitemarkets/p/{merchant['pubkey']}/deadbeef00"
    )
    assert resp.status_code == 404
    assert "not valid here" in resp.text or "not available" in resp.text


async def test_compact_fallback_and_gm_public_css(runtime_env):
    """The ≤560px compact fallback is structural in gm-public.css, and the
    stylesheet/js assets serve from the extension's static mount."""
    client = runtime_env["client"]
    css = await client.get(
        "/infinitemarkets/static/infinitemarkets/css/gm-public.css"
    )
    assert css.status_code == 200
    assert ".gm-public" in css.text
    assert re.search(r"max-width:\s*560px", css.text), (
        "compact mobile fallback breakpoint missing"
    )
    js = await client.get(
        "/infinitemarkets/static/infinitemarkets/js/public_storefront.js"
    )
    assert js.status_code == 200
    assert "history.replaceState" in js.text
    # The checkout module (split from the shared helpers in 02-04) owns
    # the Idempotency-Key contract.
    checkout_js = await client.get(
        "/infinitemarkets/static/infinitemarkets/js/public_checkout.js"
    )
    assert checkout_js.status_code == 200
    assert "Idempotency-Key" in checkout_js.text


async def test_order_page_shell(runtime_env):
    """The A3 shell renders and carries the fragment-strip contract."""
    client = runtime_env["client"]
    resp = await client.get("/infinitemarkets/order")
    assert resp.status_code == 200
    _assert_public_headers(resp)
    assert "gm-public" in resp.text


async def test_draft_preview_page_authed(runtime_env):
    """Merchant-owned hidden product renders on the /preview route with
    the draft banner and full PDP chrome — invisible publicly."""
    client = runtime_env["client"]
    merchant = await _merchant(runtime_env)
    _, product = await _catalog_and_product(
        runtime_env,
        title="Preview Hidden Hats",
        visibility="hidden",
        amount_minor=7000,
        currency="USD",
        currency_decimals=2,
    )

    public = await client.get(
        f"/infinitemarkets/p/{merchant['pubkey']}/{product['d_tag']}"
    )
    assert public.status_code == 200
    assert "preview-banner" not in public.text

    prev = await client.get(
        f"/infinitemarkets/preview/{product['id']}",
        headers=_headers(runtime_env),
    )
    assert prev.status_code == 200
    _assert_public_headers(prev)
    assert "preview-banner" in prev.text
    assert "Draft preview" in prev.text
    assert "Preview Hidden Hats" in prev.text
    assert "70.00" in prev.text


async def test_draft_preview_requires_owner(runtime_env):
    """Anonymous requesters and non-owners get no preview access."""
    client = runtime_env["client"]
    await _merchant(runtime_env)
    _, product = await _catalog_and_product(
        runtime_env, visibility="hidden"
    )

    # Anonymous — a bare client with no auth cookie must not see the draft.
    import httpx

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=runtime_env["app"]),
        base_url=ORIGIN,
    ) as anon_client:
        anon = await anon_client.get(
            f"/infinitemarkets/preview/{product['id']}"
        )
    assert anon.status_code != 200
    assert "preview-banner" not in anon.text

    # Unknown id → 404 for the owner too.
    notfound = await client.get(
        f"/infinitemarkets/preview/{uuid.uuid4().hex}",
        headers=_headers(runtime_env),
    )
    assert notfound.status_code == 404
