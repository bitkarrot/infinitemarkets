"""Theme token backend — UI-SPEC B6 tiered-controls contract.

Pins: preset/layout vocabulary, bounded Brand Basics, explicit opt-in for
Advanced Tokens, allowlist rejection, WCAG ≥4.5:1 save gates with named
pair + ratio, `.gm-public` scoping on public docs only, compact ≤560px
fallback intact.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.runtime

ORIGIN = "https://shop.example"
API = "/infinitemarkets/api/v1"


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


async def _patch_theme(runtime_env, theme: dict):
    merchant = await _merchant(runtime_env)
    return await runtime_env["client"].patch(
        f"{API}/merchants/{merchant['id']}",
        json={"theme": theme},
        headers=_headers(runtime_env),
    ), merchant


async def test_preset_and_layout_persist(runtime_env):
    resp, merchant = await _patch_theme(
        runtime_env, {"preset": "high-contrast", "layout": "guided"}
    )
    assert resp.status_code == 200, resp.text
    theme = resp.json()["theme"]
    assert theme["preset"] == "high-contrast"
    assert theme["layout"] == "guided"


async def test_invalid_preset_and_layout_rejected(runtime_env):
    for theme in ({"preset": "neon-punk"}, {"layout": "masonry"}):
        resp, _ = await _patch_theme(runtime_env, theme)
        assert resp.status_code == 422, (theme, resp.status_code)


async def test_gallery_layout_is_opt_in_and_reaches_every_page(runtime_env):
    client = runtime_env["client"]
    resp, merchant = await _patch_theme(
        runtime_env, {"preset": "warm-market", "layout": "gallery"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["theme"]["layout"] == "gallery"
    shop = merchant["pubkey"]

    # chrome pages carry the merchant's layout, not just the product page
    for path in (
        f"/infinitemarkets/signin?shop={shop}",
        f"/infinitemarkets/order?shop={shop}",
    ):
        page = await client.get(path)
        assert page.status_code == 200, path
        assert 'data-layout="gallery"' in page.text, path

    css = await client.get(
        "/infinitemarkets/static/infinitemarkets/css/gm-public.css"
    )
    # every gallery selector is scoped under .gm-public (never leaks)
    gallery = [
        line for line in css.text.splitlines()
        if 'data-layout="gallery"' in line and not line.lstrip().startswith("/*")
    ]
    assert gallery and all(
        '.gm-public[data-layout="gallery"]' in line for line in gallery
    )

    # restore the default so later tests see the editorial baseline
    resp, _ = await _patch_theme(runtime_env, {"layout": "editorial"})
    assert resp.status_code == 200


async def test_brand_basics_bounds(runtime_env):
    # initials >3 chars rejected
    resp, _ = await _patch_theme(
        runtime_env, {"brand": {"initials": "TOOL"}}
    )
    assert resp.status_code == 422

    # non-hex accent rejected
    resp, _ = await _patch_theme(
        runtime_env, {"brand": {"accent": "blue"}}
    )
    assert resp.status_code == 422

    # arbitrary font rejected — preset stacks only
    resp, _ = await _patch_theme(
        runtime_env, {"brand": {"font": "https://evil.example/font.woff2"}}
    )
    assert resp.status_code == 422

    # valid brand basics accepted
    resp, _ = await _patch_theme(
        runtime_env,
        {"brand": {"name": "Corner Store", "initials": "CS",
                   "accent": "#0f766e", "font": "serif",
                   "corners": "soft"}},
    )
    assert resp.status_code == 200, resp.text


async def test_advanced_tokens_require_opt_in(runtime_env):
    resp, _ = await _patch_theme(
        runtime_env, {"advanced": {"--color-bg": "#ffffff"}}
    )
    assert resp.status_code == 422, resp.text
    assert "opt-in" in resp.json()["detail"]


async def test_advanced_token_allowlist(runtime_env):
    # non-allowlisted token rejected
    resp, _ = await _patch_theme(
        runtime_env,
        {"advanced": {"--focus-ring": "#ff0000"}, "advanced_opt_in": True},
    )
    assert resp.status_code == 422
    assert "allowlist" in resp.json()["detail"]

    # free-form CSS value rejected
    resp, _ = await _patch_theme(
        runtime_env,
        {"advanced": {"--color-bg": "url(https://evil.example)"},
         "advanced_opt_in": True},
    )
    assert resp.status_code == 422

    # valid color + radius + space accepted
    resp, _ = await _patch_theme(
        runtime_env,
        {"advanced": {"--color-bg": "#fefefe", "--radius-md": "12px",
                      "--space-lg": "40px"},
         "advanced_opt_in": True},
    )
    assert resp.status_code == 200, resp.text


async def test_contrast_gate_blocks_failing_pairs(runtime_env):
    """text/bg below 4.5:1 must fail with the pair + computed ratio."""
    resp, _ = await _patch_theme(
        runtime_env,
        {"advanced": {"--color-text": "#999999", "--color-bg": "#888888"},
         "advanced_opt_in": True},
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert "--color-text" in detail and "--color-bg" in detail
    assert ":1" in detail  # the computed ratio is named


async def test_theme_reaches_public_page_only(runtime_env):
    """Emitted theme CSS is .gm-public-scoped on public docs; admin
    responses carry the theme OBJECT but never emit CSS."""
    client = runtime_env["client"]
    merchant = await _merchant(runtime_env)
    await _patch_theme(runtime_env, {"preset": "clean-minimal"})

    # admin payload has the object
    current = await client.get(f"{API}/merchants/current")
    assert current.json()["theme"]["preset"] == "clean-minimal"

    # a published-state product page carries the scoped emission
    categories = await client.get(f"{API}/categories", headers=_headers(runtime_env))
    if categories.json():
        category_id = categories.json()[0]["id"]
    else:
        category_id = (
            await client.post(
                f"{API}/categories", json={"name": "T"},
                headers=_headers(runtime_env),
            )
        ).json()["id"]
    product = (
        await client.post(
            f"{API}/products",
            json={
                "category_id": category_id,
                "title": "Themed",
                "amount_minor": 100,
                "currency": "USD",
                "currency_decimals": 2,
                "product_type": "simple",
                "format": "physical",
                "visibility": "on-sale",
            },
            headers=_headers(runtime_env),
        )
    ).json()
    resp = await client.get(
        f"/infinitemarkets/p/{merchant['pubkey']}/{product['d_tag']}"
    )
    assert ".gm-public {" in resp.text
    assert "--color-bg: #f4f7f7" in resp.text  # clean-minimal emitted

    # the admin shell document never carries theme CSS
    resp = await client.get("/infinitemarkets/", headers=_headers(runtime_env))
    assert ".gm-public" not in resp.text


async def test_layout_compact_fallback_in_css(runtime_env):
    """Layout preference is honored, but ≤560px always renders compact —
    the media query is unconditional in gm-public.css."""
    client = runtime_env["client"]
    css = await client.get(
        "/infinitemarkets/static/infinitemarkets/css/gm-public.css"
    )
    assert "max-width: 560px" in css.text
    assert "grid-template-columns: 1fr" in css.text


async def test_reset_to_preset_clears_overrides(runtime_env):
    from infinitemarkets.services import themes

    resp, _ = await _patch_theme(
        runtime_env,
        {"brand": {"accent": "#0f766e"},
         "advanced": {"--color-bg": "#fefefe"}, "advanced_opt_in": True},
    )
    assert resp.status_code == 200
    # reset: preset only — advanced + brand cleared
    resp, _ = await _patch_theme(runtime_env, {"preset": "warm-market"})
    theme = resp.json()["theme"]
    tokens = themes.resolve_tokens(theme)
    assert tokens["--color-bg"] == "#f7f1e8"  # sketch preset value restored


@pytest.mark.parametrize("tokens", [
    {"--color-text-muted": "#f7f1e8"},
    {"--color-surface-alt": "#2b241f"},
    {"--color-primary-hover": "#ffffff"},
    {"--color-bg": "#225bdb", "--color-surface": "#111111",
     "--color-surface-alt": "#111111", "--color-text": "#ffffff",
     "--color-text-muted": "#ffffff"},
])
async def test_advanced_tokens_preserve_secondary_text_and_focus(runtime_env, tokens):
    response, _ = await _patch_theme(
        runtime_env, {"advanced": tokens, "advanced_opt_in": True},
    )
    assert response.status_code == 422
    assert response.json()["type"] == "urn:infinitemarkets:contrast-gate"


def test_dark_scheme_tokens_meet_the_same_contrast_gate():
    """Every preset (and a merchant-darkened primary) derives a dark set
    that still clears the WCAG pairs on the dark surfaces."""
    from infinitemarkets.services import themes

    for preset in themes.PRESETS:
        dark = themes.dark_scheme_tokens({"preset": preset})
        bg = dark["--color-bg"]
        assert dark["color-scheme"] == "dark"
        for key in ("--color-text", "--color-text-muted",
                    "--color-primary", "--color-primary-hover",
                    "--color-focus"):
            assert themes.contrast_ratio(dark[key], bg) >= 4.5, (preset, key)
        assert themes.contrast_ratio(
            dark["--color-on-primary"], dark["--color-primary"]
        ) >= 4.5, preset
        css = themes.emit_css({"preset": preset})
        assert 'data-scheme="dark"' in css
        assert "prefers-color-scheme: dark" in css
        assert '[data-scheme="light"]' in css
        # base light tokens still emitted alongside the dark variant
        assert themes.resolve_tokens({"preset": preset})["--color-bg"] in css

    # A merchant primary that is already dark gets lightened for dark mode.
    dark = themes.dark_scheme_tokens(
        {"preset": "warm-market",
         "advanced": {"--color-primary": "#1a0f00"}}
    )
    assert dark["--color-primary"] != "#1a0f00"
    assert themes.contrast_ratio(
        dark["--color-primary"], dark["--color-bg"]
    ) >= 4.5


async def test_public_pages_carry_scheme_toggle_and_dark_tokens(runtime_env):
    """The nav scheme toggle renders on public chrome and the emitted
    theme carries the shopper-scheme blocks for every layout preset."""
    client = runtime_env["client"]
    merchant = await _merchant(runtime_env)
    resp = await client.get(
        f"/infinitemarkets/signin?shop={merchant['pubkey']}"
    )
    assert resp.status_code == 200
    assert 'id="gm-scheme-toggle"' in resp.text
    assert 'data-scheme="dark"' in resp.text
    assert "prefers-color-scheme: dark" in resp.text


async def test_hero_renders_on_index_only_and_validates(runtime_env):
    """Configurable hero: slogan/subtitle/CTAs/image on the bare index
    page, hidden behind any browse state; URLs are strictly bounded."""
    client = runtime_env["client"]
    merchant = await _merchant(runtime_env)
    base = f"/infinitemarkets/public/merchants/{merchant['pubkey']}"

    # unconfigured — brand name + a default 'Shop products' anchor CTA
    index = await client.get(base)
    assert index.status_code == 200
    assert 'class="merchant-hero"' in index.text
    assert "Shop products" in index.text and 'id="products"' in index.text
    assert "Independent store" not in index.text
    filtered = await client.get(f"{base}?sort=name")
    assert "merchant-hero" not in filtered.text

    resp, _ = await _patch_theme(runtime_env, {"hero": {
        "slogan": "Curated goods",
        "subtitle": "Made slowly",
        "image_url": "https://images.example/hero.jpg",
        "primary": {"label": "Shop all", "url": "#products"},
        "secondary": {"label": "Our story", "url": "https://example.com/a"},
    }})
    assert resp.status_code == 200, resp.text
    index = await client.get(base)
    assert "Curated goods" in index.text
    assert "Made slowly" in index.text
    assert "merchant-hero--image" in index.text
    assert "hero.jpg" in index.text
    assert "Shop all" in index.text and 'href="#products"' in index.text
    assert "Our story" in index.text
    filtered = await client.get(f"{base}?sort=name")
    assert "Curated goods" not in filtered.text

    # URL and shape validation
    for bad in (
        {"image_url": "javascript:alert(1)"},
        {"image_url": "http://images.example/x.jpg"},
        {"image_url": "//cdn.example/x.jpg"},
        {"image_url": "https://user:pw@example.com/x.jpg"},
        {"image_url": "https://192.168.1.1/x.jpg"},
        {"primary": {"label": "x", "url": "javascript:alert(1)"}},
        {"primary": "string"},
        {"bogus": 1},
    ):
        resp, _ = await _patch_theme(runtime_env, {"hero": bad})
        assert resp.status_code == 422, (bad, resp.status_code)

    # label without url defaults to #products; url without label is dropped
    resp, _ = await _patch_theme(runtime_env, {"hero": {
        "primary": {"label": "Go", "url": ""},
        "secondary": {"label": "", "url": "https://example.com"},
    }})
    assert resp.status_code == 200, resp.text
    hero = resp.json()["theme"]["hero"]
    assert hero["primary"]["url"] == "#products"
    assert "secondary" not in hero
    await _patch_theme(runtime_env, {"preset": "warm-market"})


async def test_brand_name_overrides_display_name_in_hero(runtime_env):
    """Brand Basics `name` is the shopper-facing name — hero and page
    title must not fall back to the raw merchant display_name."""
    client = runtime_env["client"]
    merchant = await _merchant(runtime_env)
    resp, _ = await _patch_theme(
        runtime_env, {"brand": {"name": "Corner Store"}}
    )
    assert resp.status_code == 200, resp.text
    try:
        resp = await client.get(
            f"/infinitemarkets/public/merchants/{merchant['pubkey']}"
        )
        assert resp.status_code == 200
        assert '<h1 class="merchant-title">Corner Store</h1>' in resp.text
        assert 'merchant-title">admin shop<' not in resp.text
        assert "<title>Shop · Corner Store" in resp.text
    finally:
        # preset reset clears the brand block for later tests
        await _patch_theme(runtime_env, {"preset": "warm-market"})
