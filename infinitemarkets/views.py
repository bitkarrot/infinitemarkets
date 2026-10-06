"""Generic (non-API) routes: the admin shell page + public storefront.

Mounted under ``/infinitemarkets`` by the host via ``infinitemarkets_ext``.

Public pages are STANDALONE documents (never the admin ``base.html``):
``no-store``/``no-referrer``, restrictive CSP with no third-party scripts,
``img-src https:`` for merchant images, and theme tokens scoped under
``.gm-public`` only (spec §5.4, UI-SPEC surface A).
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from lnbits.core.models import User
from lnbits.decorators import check_user_exists
from lnbits.helpers import template_renderer

from .services import nip89
from .views_public_api import PUBLIC_HEADERS

infinitemarkets_generic_router = APIRouter()

_PUBKEY_RE = re.compile(r"[0-9a-f]{64}")
_ASSET_ROOT = Path(__file__).with_name("static") / "infinitemarkets"


def _asset_revision() -> str:
    digest = sha256()
    for path in sorted(_ASSET_ROOT.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(_ASSET_ROOT).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


_ASSET_REVISION = _asset_revision()

_PUBLIC_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' https:; connect-src 'self'; frame-ancestors 'none'; "
    "base-uri 'none'; form-action 'self'"
)
# The embed route is iframe-able by any HTTPS page (it is meant to be
# embedded — e.g. a WebPages static page on this host or an external
# site). Every other public page stays frame-ancestors 'none'.
_EMBED_CSP = _PUBLIC_CSP.replace(
    "frame-ancestors 'none'", "frame-ancestors 'self' https:"
)


def infinitemarkets_renderer():
    return template_renderer(["infinitemarkets"])


async def _card_images(product_ids: list[str]) -> dict[str, list[str]]:
    """First two images per product in one browse-page query."""
    if not product_ids:
        return {}
    from .db import db, table

    placeholders = ", ".join(f":p{i}" for i in range(len(product_ids)))
    params = {f"p{i}": pid for i, pid in enumerate(product_ids)}
    async with db.connect() as conn:
        rows = await conn.fetchall(
            f"SELECT product_id, url FROM {table('product_images')} "
            f"WHERE product_id IN ({placeholders}) ORDER BY sort_order, id",
            params,
        )
    out: dict[str, list[str]] = {}
    for row in rows:
        urls = out.setdefault(row["product_id"], [])
        if len(urls) < 2:
            urls.append(row["url"])
    return out


def _brand_ctx(merchant: dict | None, theme: dict | None) -> dict:
    """Store-header context (sketch chrome): brand tile + display name.
    Brand Basics name/initials override the merchant display name."""
    brand = (theme or {}).get("brand") or {}
    name = brand.get("name") or (merchant or {}).get("display_name") or ""
    initials = brand.get("initials") or (name[:1].upper() if name else "")
    pubkey = (merchant or {}).get("pubkey")
    return {
        "brand_name": name,
        "brand_initials": initials,
        "shop_pubkey": pubkey or "",
        "storefront_url": (
            f"/infinitemarkets/public/merchants/{pubkey}" if pubkey else ""
        ),
    }


NAV_COLLECTIONS_MAX = 6


async def _nav_collections(merchant_id: str) -> list[dict]:
    """Collections with at least one visible member — zero-member
    collections are never rendered (they are unpublishable by contract)."""
    from .db import db, table

    async with db.connect() as conn:
        rows = await conn.fetchall(
            f"SELECT c.* FROM {table('collections')} c "
            "WHERE c.merchant_id = :m AND c.deleted_at IS NULL"
            " AND EXISTS ("
            f"SELECT 1 FROM {table('product_collections')} pc "
            f"JOIN {table('products')} p ON p.id = pc.product_id "
            "WHERE pc.collection_id = c.id AND p.deleted_at IS NULL"
            " AND NOT p.draft AND p.parent_product_id IS NULL"
            " AND p.visibility != 'hidden'"
            ") ORDER BY c.title",
            {"m": merchant_id},
        )
    return [
        {
            "d_tag": c["d_tag"],
            "title": c["title"] or "",
            "description": c["description"] or "",
        }
        for c in rows
    ]


async def _store_ctx(merchant: dict, theme: dict | None) -> dict:
    """Everything the shared store chrome (header nav + footer) needs."""
    from lnbits.settings import settings as host_settings

    from .services import storefront_mode as mode_service
    from .services import themes as theme_service
    from .settings import ext_settings

    collections = await _nav_collections(merchant["id"])
    nostr = await _nostr_ctx(merchant)
    return {
        **_brand_ctx(merchant, theme),
        # Every public document carries the merchant's layout so the
        # opt-in ``gallery`` look reaches chrome pages, not only product.
        "layout": theme_service.theme_layout(theme),
        "nav_collections": collections[:NAV_COLLECTIONS_MAX],
        "all_collections": collections,
        # D-06 + 03.1-D13: the buyer sign-in affordance renders while
        # EITHER method can work — a live inbox profile (NIP-07) OR a
        # configured host email path (magic link). The key name stays
        # ``nostr_signin``; it now means "buyer sign-in affordance" and
        # still gates BOTH the chip markup and the public_nostr.js
        # script tag. Per-method availability inside the modal comes
        # from the /nostr/challenge capability flags.
        "nostr_signin": merchant.get("inbox_state") == "active" or (
            ext_settings().email_enabled
            and host_settings.is_email_notifications_configured()
        ),
        # D-07: the four-state storefront mode drives buy controls and
        # browse depth server-side.
        "storefront_mode": await mode_service.get_mode(merchant["id"]),
        **nostr,
    }


async def _nostr_ctx(merchant: dict) -> dict:
    """npub + enabled inbox relays for Nostr guidance surfaces."""
    try:
        from nostr_sdk import PublicKey

        npub = PublicKey.parse(merchant["pubkey"]).to_bech32()
    except Exception:  # noqa: BLE001 — display-only fallback
        npub = merchant.get("pubkey") or ""
    from .db import db, table

    async with db.connect() as conn:
        rows = await conn.fetchall(
            f"SELECT relay_url FROM {table('relay_configs')} "
            "WHERE merchant_id = :m AND enabled"
            " AND direction IN ('inbox', 'both') ORDER BY relay_url",
            {"m": merchant["id"]},
        )
    return {
        "merchant_npub": npub,
        "inbox_relays": [r["relay_url"] for r in rows],
    }


def _nostr_only_response(request: Request, merchant: dict,
                       ctx: dict) -> HTMLResponse:
    """The Nostr-only notice page for browse surfaces (D-07/D-08):
    browse depth is gated, but the store chrome and Track-order link
    still render so existing buyers keep working."""
    return _public_response(
        request,
        "public_nostr_only.html",
        {
            "merchant_name": merchant.get("display_name") or "",
            "merchant_npub": ctx.get("merchant_npub", ""),
            "inbox_relays": ctx.get("inbox_relays", []),
            "nav_active": "shop",
            **ctx,
        },
    )


def _public_response(request: Request, template: str, ctx: dict,
                   status: int = 200, embed_ok: bool = False) -> HTMLResponse:
    ctx.setdefault("theme_css", "")
    ctx.setdefault("layout", "editorial")
    ctx.setdefault("price_label", nip89.price_label)
    ctx.setdefault("asset_revision", _ASSET_REVISION)
    resp = infinitemarkets_renderer().TemplateResponse(
        request, f"templates/infinitemarkets/{template}", ctx,
        status_code=status,
    )
    for k, v in PUBLIC_HEADERS.items():
        resp.headers[k] = v
    resp.headers["Content-Security-Policy"] = (
        _EMBED_CSP if embed_ok else _PUBLIC_CSP
    )
    return resp


async def _public_guard(request: Request) -> HTMLResponse | None:
    """Rate-limit public pages; a 429 renders honestly, never a 500."""
    from .security import ProblemError

    try:
        await nip89.check_public_rate_limit(request, bucket="public-page")
    except ProblemError as exc:
        return _public_response(
            request, "public_invalid.html",
            {"message": exc.title}, status=exc.status,
        )
    return None


@infinitemarkets_generic_router.get("/", response_class=HTMLResponse)
async def index(request: Request, user: User = Depends(check_user_exists)):
    response = infinitemarkets_renderer().TemplateResponse(
        request,
        "templates/infinitemarkets/admin.html",
        {
            # base.html does JSON.parse({{ user | tojson }}) — it needs the
            # user as a JSON STRING (host convention, see
            # lnbits/core/views/generic.py), not a dict.
            "user": user.json(),
            "asset_revision": _ASSET_REVISION,
        },
    )
    response.headers["Cache-Control"] = "no-store"
    return response


# --- NIP-89 handler + public storefront (spec section 5.4) -----------------------


@infinitemarkets_generic_router.get("/p/{naddr}", response_class=HTMLResponse)
async def nip89_handler(request: Request, naddr: str):
    """NIP-89 naddr -> canonical local product page. Relay hints are
    parsed but NEVER fetched (T-202-06) — resolution is local only."""
    limited = await _public_guard(request)
    if limited is not None:
        return limited
    from .security import ProblemError

    try:
        pubkey, d_tag = nip89.decode_product_naddr(naddr)
    except ProblemError:
        return _public_response(request, "public_invalid.html", {},
                                status=404)
    product = await nip89.product_by_address(pubkey, d_tag)
    if not product:
        return _public_response(request, "public_invalid.html", {},
                                status=404)
    resp = RedirectResponse(
        f"/infinitemarkets/p/{pubkey}/{d_tag}", status_code=301
    )
    for k, v in PUBLIC_HEADERS.items():
        resp.headers[k] = v
    return resp


@infinitemarkets_generic_router.get(
    "/p/{pubkey}/{d_tag}", response_class=HTMLResponse
)
async def product_page(request: Request, pubkey: str, d_tag: str):
    """A1 product page — all documented states per UI-SPEC."""
    limited = await _public_guard(request)
    if limited is not None:
        return limited
    product = await nip89.product_by_address(pubkey, d_tag)
    if not product:
        return _public_response(request, "public_invalid.html", {},
                                status=404)
    detail = await nip89.product_detail(product)
    state = nip89.availability_state(product)
    from .services import themes as theme_service

    theme = await theme_service.get_theme(product["_merchant"]["id"])
    if state in ("unavailable", "hidden", "inactive"):
        return _public_response(
            request, "public_unavailable.html",
            {"state": state}, status=404 if state == "unavailable" else 200,
        )
    store = await _store_ctx(product["_merchant"], theme)
    if store["storefront_mode"] == "nostr_only":
        # D-08: browse depth gated; the notice page keeps the Track-order
        # link so existing private order links keep working.
        return _nostr_only_response(request, product["_merchant"], store)
    return _public_response(
        request,
        "public_product.html",
        {
            "product": nip89.public_product_json(product, detail),
            "state": state,
            "description_html": nip89.render_markdown(
                product.get("description_md")
            ),
            "merchant_name": product["_merchant"].get("display_name") or "",
            "merchant_pubkey": pubkey,
            "theme_css": theme_service.emit_css(theme),
            "layout": theme_service.theme_layout(theme),
            "instant_delivery": (
                product["format"] == "digital"
                and product.get("delivery_enc") is not None
            ),
            **store,
        },
    )


def _browse_price(value: str | None) -> Decimal | None:
    if value and re.fullmatch(r"\d{1,18}(?:\.\d{1,18})?", value):
        return Decimal(value)
    return None


def _product_price(row: dict) -> Decimal:
    return Decimal(row["amount_minor"] or 0).scaleb(-(row["currency_decimals"] or 0))


async def _browse_products(request: Request, merchant: dict,
                           collection_id: str | None = None) -> tuple[list[dict], dict]:
    from .db import db, table

    sql = (
        "SELECT p.id, p.d_tag, p.title, p.amount_minor, p.currency, "
        "p.currency_decimals, p.format, p.visibility, p.stock_on_hand, "
        "p.stock_reserved, p.nip99_status, p.created_at, p.draft, p.deleted_at, "
        "cat.name AS category_name, cat.public_slug AS category_slug "
        f"FROM {table('products')} p "
        f"JOIN {table('categories')} cat ON cat.id = p.category_id "
        "WHERE p.merchant_id = :merchant AND cat.deleted_at IS NULL "
        "AND p.deleted_at IS NULL AND NOT p.draft "
        "AND p.parent_product_id IS NULL AND p.visibility != 'hidden'"
    )
    params = {"merchant": merchant["id"]}
    if collection_id:
        sql += (
            f" AND EXISTS (SELECT 1 FROM {table('product_collections')} pc "
            "WHERE pc.product_id = p.id AND pc.collection_id = :collection_id)"
        )
        params["collection_id"] = collection_id
    elif request.query_params.get("collection"):
        sql += (
            f" AND EXISTS (SELECT 1 FROM {table('product_collections')} pc "
            f"JOIN {table('collections')} c ON c.id = pc.collection_id "
            "WHERE pc.product_id = p.id AND c.merchant_id = :merchant "
            "AND c.deleted_at IS NULL AND c.d_tag = :collection)"
        )
        params["collection"] = request.query_params["collection"][:64]
    async with db.connect() as conn:
        rows = [dict(row) for row in await conn.fetchall(sql, params)]

    categories = {
        row["category_slug"]: row["category_name"]
        for row in rows if row["category_slug"]
    }
    currencies = sorted({row["currency"] for row in rows if row["currency"]})
    selected_category = request.query_params.get("category", "")[:64]
    selected_currency = request.query_params.get("currency", "")[:8]
    if len(currencies) == 1:
        selected_currency = currencies[0]
    elif not selected_currency or selected_currency not in currencies:
        selected_currency = ""
    priced_rows = [
        row for row in rows if selected_currency and row["currency"] == selected_currency
        and row["amount_minor"] is not None
    ]
    prices = [_product_price(row) for row in priced_rows]
    min_price = _browse_price(request.query_params.get("min_price"))
    max_price = _browse_price(request.query_params.get("max_price"))
    if selected_category:
        rows = [row for row in rows if row["category_slug"] == selected_category]
    if selected_currency:
        rows = [row for row in rows if row["currency"] == selected_currency]
        if min_price is not None:
            rows = [
                row for row in rows
                if row["amount_minor"] is not None and _product_price(row) >= min_price
            ]
        if max_price is not None:
            rows = [
                row for row in rows
                if row["amount_minor"] is not None and _product_price(row) <= max_price
            ]
    else:
        min_price = max_price = None
    sort = request.query_params.get("sort", "newest")
    if sort not in ("newest", "name", "price-asc", "price-desc") or (
        sort.startswith("price-") and not selected_currency
    ):
        sort = "newest"
    rows.sort(key=lambda row: row["id"])
    if sort == "name":
        rows.sort(key=lambda row: (row["title"] or "").casefold())
    elif sort.startswith("price-"):
        rows.sort(key=_product_price, reverse=sort == "price-desc")
        rows.sort(key=lambda row: row["amount_minor"] is None)
    else:
        rows.sort(key=lambda row: row["created_at"], reverse=True)
    total = len(rows)
    raw_page = request.query_params.get("page", "1")
    page_size = 24
    max_page = max(1, (total + page_size - 1) // page_size)
    page = min(max(int(raw_page), 1), max_page) if re.fullmatch(r"[0-9]{1,4}", raw_page) else 1
    rows = rows[(page - 1) * page_size:page * page_size]
    query = {
        "category": selected_category,
        "collection": request.query_params.get("collection", "")[:64] if not collection_id else "",
        "currency": selected_currency if len(currencies) > 1 else "",
        "min_price": format(min_price, "f") if min_price is not None else "",
        "max_price": format(max_price, "f") if max_price is not None else "",
        "sort": sort if sort != "newest" else "",
    }
    query = {key: value for key, value in query.items() if value}
    path = request.url.path
    next_page = page + 1 if page * page_size < total else None
    browse = {
        "categories": sorted(categories.items(), key=lambda item: (item[1].casefold(), item[0])),
        "currencies": currencies,
        "category": selected_category,
        "collection": query.get("collection", ""),
        "currency": selected_currency,
        "price_min": format(min(prices), "f") if prices else "",
        "price_max": format(max(prices), "f") if prices else "",
        "price_step": format(
            Decimal(1).scaleb(-max(row["currency_decimals"] or 0 for row in priced_rows)),
            "f",
        ) if priced_rows else "",
        "min_price": query.get("min_price", ""),
        "max_price": query.get("max_price", ""),
        "sort": sort,
        "total": total,
        "page": page,
        "previous": f"{path}?{urlencode(query | {'page': page - 1})}" if page > 1 else None,
        "next": f"{path}?{urlencode(query | {'page': next_page})}" if next_page else None,
        "clear_url": path,
    }
    return rows, browse


@infinitemarkets_generic_router.get(
    "/public/collections/{pubkey}/{d_tag}", response_class=HTMLResponse
)
async def collection_page(request: Request, pubkey: str, d_tag: str):
    limited = await _public_guard(request)
    if limited is not None:
        return limited
    merchant = await nip89.merchant_by_pubkey(pubkey)
    if not merchant or merchant["state"] in ("deactivating", "inactive"):
        return _public_response(request, "public_invalid.html", {},
                                status=404)
    from .db import db, table

    async with db.connect() as conn:
        row = await conn.fetchone(
            f"SELECT * FROM {table('collections')} "
            "WHERE merchant_id = :m AND d_tag = :d AND deleted_at IS NULL",
            {"m": merchant["id"], "d": d_tag},
        )
        if not row:
            return _public_response(request, "public_invalid.html", {},
                                    status=404)
    members, browse = await _browse_products(request, merchant, row["id"])
    member_dicts = [dict(m) | {"_merchant": merchant} for m in members]
    from .services import themes as theme_service

    collection = nip89.collection_json(dict(row), member_dicts)
    images = await _card_images([m["id"] for m in members])
    for prod, member in zip(collection["products"], member_dicts):
        urls = images.get(member["id"], [])
        prod["image"] = urls[0] if urls else None
        prod["hover_image"] = urls[1] if len(urls) > 1 else None
        prod["format"] = member["format"]
    theme = await theme_service.get_theme(merchant["id"])
    store = await _store_ctx(merchant, theme)
    if store["storefront_mode"] == "nostr_only":
        return _nostr_only_response(request, merchant, store)
    return _public_response(
        request,
        "public_collection.html",
        {
            "collection": collection,
            "browse": browse,
            "merchant_pubkey": pubkey,
            "merchant_name": merchant.get("display_name") or "",
            "theme_css": theme_service.emit_css(theme),
            "layout": theme_service.theme_layout(theme),
            "nav_active": d_tag,
            **store,
        },
    )


async def _product_cards(products: list[dict], merchant: dict) -> list[dict]:
    """Image + availability cards for public listing pages (merchant
    index and the embeddable listing share the same shape)."""
    images = await _card_images([p["id"] for p in products])
    return [
        {
            "d_tag": p["d_tag"],
            "title": p["title"] or "",
            "amount_minor": p["amount_minor"],
            "currency": p["currency"],
            "currency_decimals": p["currency_decimals"],
            "image": images[p["id"]][0] if p["id"] in images else None,
            "hover_image": (
                images[p["id"]][1] if len(images.get(p["id"], [])) > 1
                else None
            ),
            "format": p["format"],
            "availability": nip89.availability_state(
                dict(p) | {"_merchant": merchant}
            ),
        }
        for p in products
    ]


@infinitemarkets_generic_router.get(
    "/public/merchants/{pubkey}", response_class=HTMLResponse
)
async def merchant_page(request: Request, pubkey: str):
    limited = await _public_guard(request)
    if limited is not None:
        return limited
    merchant = await nip89.merchant_by_pubkey(pubkey)
    if not merchant or merchant["state"] in ("deactivating", "inactive"):
        return _public_response(request, "public_invalid.html", {},
                                status=404)
    profile = (
        json.loads(merchant["profile_json"]) if merchant["profile_json"] else {}
    )
    products, browse = await _browse_products(request, merchant)
    cards = await _product_cards(products, merchant)
    from .services import themes as theme_service

    theme = await theme_service.get_theme(merchant["id"])
    store = await _store_ctx(merchant, theme)
    if store["storefront_mode"] == "nostr_only":
        return _nostr_only_response(request, merchant, store)
    hero_cfg = theme.get("hero") or {}
    hero = {
        "slogan": (
            hero_cfg.get("slogan") or store["brand_name"]
            or merchant.get("display_name") or "Our store"
        ),
        "subtitle": hero_cfg.get("subtitle") or profile.get("about", ""),
        "image_url": hero_cfg.get("image_url") or "",
        "primary": (
            hero_cfg.get("primary")
            or {"label": "Shop products", "url": "#products"}
        ),
        "secondary": hero_cfg.get("secondary") or {},
    }
    return _public_response(
        request,
        "public_merchant.html",
        {
            "pubkey": merchant["pubkey"],
            "hero": hero,
            # the hero is the index-page intro — any browse state
            # (filter, sort, page) means the shopper is inside the
            # catalog, so the marketing block steps aside.
            "show_hero": not request.query_params,
            "products": cards,
            "browse": browse,
            "theme_css": theme_service.emit_css(theme),
            "nav_active": "shop",
            **store,
            "collections": store["all_collections"],
        },
    )


@infinitemarkets_generic_router.get(
    "/public/embed/merchants/{pubkey}", response_class=HTMLResponse
)
async def embed_merchant_page(request: Request, pubkey: str):
    """Chrome-free product listing for SAME-ORIGIN iframe embedding
    (e.g. the WebPages extension): no header nav, hero or footer — the
    browse section plus a compact sign-in / track-order toolbar.
    Filters, sort and pagination stay inside the iframe; products and
    order tracking open full pages in a new tab."""
    limited = await _public_guard(request)
    if limited is not None:
        return limited
    merchant = await nip89.merchant_by_pubkey(pubkey)
    if not merchant or merchant["state"] in ("deactivating", "inactive"):
        return _public_response(request, "public_invalid.html", {},
                                status=404)
    products, browse = await _browse_products(request, merchant)
    cards = await _product_cards(products, merchant)
    from .services import themes as theme_service

    theme = await theme_service.get_theme(merchant["id"])
    store = await _store_ctx(merchant, theme)
    if store["storefront_mode"] == "nostr_only":
        return _nostr_only_response(request, merchant, store)
    return _public_response(
        request,
        "public_embed.html",
        {
            "pubkey": merchant["pubkey"],
            "products": cards,
            "browse": browse,
            "theme_css": theme_service.emit_css(theme),
            "nav_active": "shop",
            **store,
            "collections": store["all_collections"],
        },
        embed_ok=True,
    )


async def _shop_ctx(request: Request) -> dict:
    """Store chrome for account pages — ``?shop=<pubkey>`` like the order
    page, falling back to the single merchant row so direct navigation to
    /orders and /profile still renders branded chrome + the sign-in chip."""
    shop = request.query_params.get("shop", "")
    merchant = None
    if _PUBKEY_RE.fullmatch(shop):
        merchant = await nip89.merchant_by_pubkey(shop)
    if merchant is None and not shop:
        from .db import db, table

        async with db.connect() as conn:
            row = await conn.fetchone(
                f"SELECT * FROM {table('merchants')} ORDER BY created_at"
                " LIMIT 1"
            )
        merchant = dict(row) if row else None
    if (
        not merchant
        or merchant["state"] in ("deactivating", "inactive")
    ):
        return {}
    from .services import themes as theme_service

    theme = await theme_service.get_theme(merchant["id"])
    return {
        "theme_css": theme_service.emit_css(theme),
        **await _store_ctx(merchant, theme),
    }


@infinitemarkets_generic_router.get("/orders", response_class=HTMLResponse)
async def orders_page(request: Request):
    """Signed-in buyer order history — the account menu's 'My orders'."""
    limited = await _public_guard(request)
    if limited is not None:
        return limited
    ctx = await _shop_ctx(request)
    ctx.setdefault("nav_active", "orders")
    return _public_response(request, "public_orders.html", ctx)


@infinitemarkets_generic_router.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request):
    """Signed-in buyer kind-0 profile editor — the account menu's
    'Profile'."""
    limited = await _public_guard(request)
    if limited is not None:
        return limited
    ctx = await _shop_ctx(request)
    ctx.setdefault("nav_active", "profile")
    return _public_response(request, "public_profile.html", ctx)


@infinitemarkets_generic_router.get("/signin", response_class=HTMLResponse)
async def signin_page(request: Request):
    """Dedicated buyer sign-in page — the header chip navigates here
    when signed out. In-page methods (no modal): Nostr NIP-07 and the
    email magic link each carry their own busy state."""
    limited = await _public_guard(request)
    if limited is not None:
        return limited
    ctx = await _shop_ctx(request)
    ctx.setdefault("nav_active", "signin")
    return _public_response(request, "public_signin.html", ctx)


@infinitemarkets_generic_router.get("/auth/email", response_class=HTMLResponse)
async def auth_email_page(request: Request):
    """§5.4 email sign-in landing shell — the magic-link token arrives
    ONLY as a URL fragment (never sent to the server); page JS reads the
    storefront-captured fragment and POSTs it to ``/nostr/email/verify``
    which mints the identical session cookie (D-08)."""
    limited = await _public_guard(request)
    if limited is not None:
        return limited
    ctx = await _shop_ctx(request)
    ctx.setdefault("nav_active", "track")
    return _public_response(request, "public_auth_email.html", ctx)


@infinitemarkets_generic_router.get("/order", response_class=HTMLResponse)
async def order_page(request: Request):
    """A3 order-status document shell — the bearer token arrives only as a
    URL fragment (never sent to the server); JS strips it immediately and
    sends it as ``X-Order-Token``. Status polling lands in 02-03/02-04."""
    limited = await _public_guard(request)
    if limited is not None:
        return limited
    # Optional ?shop=<merchant pubkey> (public identity, never a token)
    # restores the shop's header, navigation and theme around the page.
    shop = request.query_params.get("shop", "")
    ctx: dict = {}
    if _PUBKEY_RE.fullmatch(shop):
        merchant = await nip89.merchant_by_pubkey(shop)
        if merchant and merchant["state"] not in ("deactivating", "inactive"):
            from .services import themes as theme_service

            theme = await theme_service.get_theme(merchant["id"])
            ctx = {
                "theme_css": theme_service.emit_css(theme),
                "nav_active": "track",
                **await _store_ctx(merchant, theme),
            }
    ctx.setdefault("nav_active", "track")
    return _public_response(request, "public_order.html", ctx)
