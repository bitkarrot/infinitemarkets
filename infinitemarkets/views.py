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
from hashlib import sha256
from pathlib import Path

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


def infinitemarkets_renderer():
    return template_renderer(["infinitemarkets"])


async def _first_images(product_ids: list[str]) -> dict[str, str]:
    """Lowest-sort_order image URL per product — one query for card
    thumbnails on browse pages."""
    if not product_ids:
        return {}
    from .db import db, table

    placeholders = ", ".join(f":p{i}" for i in range(len(product_ids)))
    params = {f"p{i}": pid for i, pid in enumerate(product_ids)}
    async with db.connect() as conn:
        rows = await conn.fetchall(
            f"SELECT product_id, url FROM {table('product_images')} "
            f"WHERE product_id IN ({placeholders}) ORDER BY sort_order",
            params,
        )
    out: dict[str, str] = {}
    for r in rows:
        out.setdefault(r["product_id"], r["url"])
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
            " AND NOT p.draft AND p.visibility != 'hidden'"
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
    from .settings import ext_settings

    collections = await _nav_collections(merchant["id"])
    nostr = await _nostr_ctx(merchant)
    return {
        **_brand_ctx(merchant, theme),
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
                   status: int = 200) -> HTMLResponse:
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
    resp.headers["Content-Security-Policy"] = _PUBLIC_CSP
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
        members = await conn.fetchall(
            f"SELECT p.* FROM {table('products')} p "
            f"JOIN {table('product_collections')} pc ON pc.product_id = p.id "
            "WHERE pc.collection_id = :c AND p.deleted_at IS NULL"
            " AND NOT p.draft AND p.visibility != 'hidden'",
            {"c": row["id"]},
        )
    member_dicts = [dict(m) | {"_merchant": merchant} for m in members]
    from .services import themes as theme_service

    collection = nip89.collection_json(dict(row), member_dicts)
    images = await _first_images([m["id"] for m in members])
    for prod, member in zip(collection["products"], member_dicts):
        prod["image"] = images.get(member["id"])
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
            "merchant_pubkey": pubkey,
            "merchant_name": merchant.get("display_name") or "",
            "theme_css": theme_service.emit_css(theme),
            "layout": theme_service.theme_layout(theme),
            "nav_active": d_tag,
            **store,
        },
    )


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
    from .db import db, table

    async with db.connect() as conn:
        products = await conn.fetchall(
            f"SELECT * FROM {table('products')} "
            "WHERE merchant_id = :m AND deleted_at IS NULL AND NOT draft"
            " AND parent_product_id IS NULL AND visibility != 'hidden'"
            " ORDER BY created_at",
            {"m": merchant["id"]},
        )
    images = await _first_images([p["id"] for p in products])
    cards = [
        {
            "d_tag": p["d_tag"],
            "title": p["title"] or "",
            "amount_minor": p["amount_minor"],
            "currency": p["currency"],
            "currency_decimals": p["currency_decimals"],
            "image": images.get(p["id"]),
            "format": p["format"],
            "availability": nip89.availability_state(
                dict(p) | {"_merchant": merchant}
            ),
        }
        for p in products
    ]
    from .services import themes as theme_service

    theme = await theme_service.get_theme(merchant["id"])
    store = await _store_ctx(merchant, theme)
    if store["storefront_mode"] == "nostr_only":
        return _nostr_only_response(request, merchant, store)
    return _public_response(
        request,
        "public_merchant.html",
        {
            "pubkey": merchant["pubkey"],
            "display_name": merchant.get("display_name") or "",
            "about": profile.get("about", ""),
            "picture": profile.get("picture"),
            "products": cards,
            "theme_css": theme_service.emit_css(theme),
            "nav_active": "shop",
            **store,
            "collections": store["all_collections"],
        },
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
