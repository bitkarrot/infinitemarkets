"""Public read-only JSON API — spec section 5.4.

Unauthenticated, database rate-limited (120 GET/min per HMAC'd IP scope —
raw IPs never persist), ``no-store``/``no-referrer`` on every response,
and the payload contract carries no merchant internals, internal ids,
buyer echoes, or bearer tokens.
"""

from __future__ import annotations

import functools
import json
import re
import time

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from . import crypto
from .db import (
    db,
    effective_stock_select,
    released_product_clause,
    released_product_select,
    table,
)
from .security import (
    ProblemError,
    not_found,
    problem_for,
    unprocessable,
)
from .services import checkout as checkout_service
from .services import nip89, nostr_auth, readiness
from .settings import ext_settings

infinitemarkets_public_api_router = APIRouter(prefix="/api/v1/public")

PUBLIC_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    # Embeddable widgets (gm-embed.js) fetch these public, unauthenticated,
    # rate-limited reads from arbitrary host pages. Mutations still can't
    # be driven cross-origin: they need a CORS preflight, which this API
    # does not answer.
    "Access-Control-Allow-Origin": "*",
}


def public_boundary(fn):
    """RFC 9457 mapping WITHOUT admin mutation enforcement — public
    routes are anonymous by design (buyers never authenticate), so the
    cookie/bearer CSRF rules of ``problem_boundary`` must not apply.

    Problem responses still carry the section-5.4 protective headers —
    the injected ``Response`` is bypassed when a ProblemError becomes a
    fresh JSONResponse, so they are stamped here too."""

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except ProblemError as exc:
            resp = problem_for(exc)
            for k, v in PUBLIC_HEADERS.items():
                resp.headers[k] = v
            return resp

    return wrapper


async def _guard(request: Request, response: Response) -> None:
    await nip89.check_public_rate_limit(request)
    for k, v in PUBLIC_HEADERS.items():
        response.headers[k] = v


@infinitemarkets_public_api_router.get("/merchants/{pubkey}")
@public_boundary
async def public_merchant(pubkey: str, request: Request, response: Response):
    await _guard(request, response)
    merchant = await nip89.merchant_by_pubkey(pubkey)
    if not merchant or merchant["state"] in ("deactivating", "inactive"):
        raise not_found("merchant not found")
    profile = (
        json.loads(merchant["profile_json"]) if merchant["profile_json"] else {}
    )
    return {
        "pubkey": merchant["pubkey"],
        "display_name": merchant["display_name"] or "",
        "profile": {
            k: v
            for k, v in profile.items()
            if k in ("about", "website", "picture", "banner", "nip05", "lud16")
        },
        "state": "active" if merchant["state"] == "active" else "draft",
    }


@infinitemarkets_public_api_router.get("/merchants/{pubkey}/products")
@public_boundary
async def public_merchant_products(
    pubkey: str, request: Request, response: Response
):
    """Card-shape listing for embeddable widgets and headless consumers —
    the same browse visibility rules as the storefront, no internals.
    ``?collection=<d_tag>`` / ``?category=<slug>`` match the HTML browse
    params; cards link back to the hosted product pages."""
    await _guard(request, response)
    merchant = await nip89.merchant_by_pubkey(pubkey)
    if not merchant or merchant["state"] in ("deactivating", "inactive"):
        raise not_found("merchant not found")
    sql = (
        "SELECT p.id, p.d_tag, p.title, p.amount_minor, p.currency, "
        "p.currency_decimals, p.format, p.visibility, p.stock_on_hand, "
        "p.stock_reserved, p.nip99_status, p.draft, p.deleted_at, "
        "p.import_source_kind, "
        f"{released_product_select('p', table)}, "
        f"{effective_stock_select('p', table)}, "
        "cat.name AS category_name, cat.public_slug AS category_slug "
        f"FROM {table('products')} p "
        f"JOIN {table('categories')} cat ON cat.id = p.category_id "
        "WHERE p.merchant_id = :m AND cat.deleted_at IS NULL "
        "AND p.deleted_at IS NULL AND NOT p.draft "
        "AND p.parent_product_id IS NULL "
        f"AND {released_product_clause('p', table)} "
        "AND p.visibility != 'hidden'"
    )
    params = {"m": merchant["id"]}
    if request.query_params.get("collection"):
        sql += (
            f" AND EXISTS (SELECT 1 FROM {table('product_collections')} pc "
            f"JOIN {table('collections')} c ON c.id = pc.collection_id "
            "WHERE pc.product_id = p.id AND c.merchant_id = :m "
            "AND c.deleted_at IS NULL AND c.d_tag = :collection)"
        )
        params["collection"] = request.query_params["collection"][:64]
    if request.query_params.get("category"):
        sql += " AND cat.public_slug = :category"
        params["category"] = request.query_params["category"][:64]
    async with db.connect() as conn:
        rows = [dict(r) for r in await conn.fetchall(sql, params)]
        images: dict[str, str] = {}
        if rows:
            placeholders = ", ".join(f":p{i}" for i in range(len(rows)))
            image_rows = await conn.fetchall(
                f"SELECT product_id, url FROM {table('product_images')} "
                f"WHERE product_id IN ({placeholders}) ORDER BY sort_order, id",
                {f"p{i}": r["id"] for i, r in enumerate(rows)},
            )
            for img in image_rows:
                images.setdefault(img["product_id"], img["url"])
    products = [
        {
            "d_tag": r["d_tag"],
            "title": r["title"] or "",
            "price": {
                "amount_minor": r["amount_minor"],
                "currency": r["currency"],
                "decimals": r["currency_decimals"],
            },
            "availability": nip89.availability_state(
                dict(r) | {"_merchant": merchant}
            ),
            "format": r["format"],
            "category": r["category_name"] or "",
            "category_slug": r["category_slug"] or "",
            "image": images.get(r["id"]),
            "url": f"/infinitemarkets/p/{merchant['pubkey']}/{r['d_tag']}",
        }
        for r in rows
    ]
    return {"pubkey": merchant["pubkey"], "products": products}


@infinitemarkets_public_api_router.get("/products/{pubkey}/{d_tag}")
@public_boundary
async def public_product(
    pubkey: str, d_tag: str, request: Request, response: Response
):
    await _guard(request, response)
    product = await nip89.product_by_address(pubkey, d_tag)
    if not product or nip89.availability_state(product) in (
        "unavailable", "hidden", "inactive",
    ):
        raise not_found("product not found")
    detail = await nip89.product_detail(product)
    return nip89.public_product_json(product, detail)


@infinitemarkets_public_api_router.get("/collections/{pubkey}/{d_tag}")
@public_boundary
async def public_collection(
    pubkey: str, d_tag: str, request: Request, response: Response
):
    await _guard(request, response)
    merchant = await nip89.merchant_by_pubkey(pubkey)
    if not merchant or merchant["state"] in ("deactivating", "inactive"):
        raise not_found("collection not found")
    async with db.connect() as conn:
        row = await conn.fetchone(
            f"SELECT * FROM {table('collections')} "
            "WHERE merchant_id = :m AND d_tag = :d AND deleted_at IS NULL",
            {"m": merchant["id"], "d": d_tag},
        )
        if not row:
            raise not_found("collection not found")
        members = await conn.fetchall(
            f"SELECT p.*, {effective_stock_select('p', table)} "
            f"FROM {table('products')} p "
            f"JOIN {table('product_collections')} pc ON pc.product_id = p.id "
            "WHERE pc.collection_id = :c AND p.deleted_at IS NULL"
            " AND NOT p.draft AND p.visibility != 'hidden'"
            f" AND {released_product_clause('p', table)}",
            {"c": row["id"]},
        )
    member_dicts = []
    for m in members:
        md = dict(m)
        md["_merchant"] = merchant
        member_dicts.append(md)
    return nip89.collection_json(dict(row), member_dicts)


@infinitemarkets_public_api_router.get("/shipping/{pubkey}/{d_tag}")
@public_boundary
async def public_shipping(
    pubkey: str, d_tag: str, request: Request, response: Response
):
    await _guard(request, response)
    merchant = await nip89.merchant_by_pubkey(pubkey)
    if not merchant or merchant["state"] in ("deactivating", "inactive"):
        raise not_found("shipping option not found")
    async with db.connect() as conn:
        row = await conn.fetchone(
            f"SELECT * FROM {table('shipping_options')} "
            "WHERE merchant_id = :m AND d_tag = :d AND deleted_at IS NULL"
            " AND active",
            {"m": merchant["id"], "d": d_tag},
        )
    if not row:
        raise not_found("shipping option not found")
    row = dict(row)
    return {
        "d_tag": row["d_tag"],
        "title": row["title"] or "",
        "base_price_minor": row["base_price_minor"],
        "currency": row["currency"],
        "service": row["service"],
        "countries": json.loads(row["countries"]) if row["countries"] else [],
        "regions": json.loads(row["regions"]) if row["regions"] else [],
        "duration_min": row["duration_min"],
        "duration_max": row["duration_max"],
        "duration_unit": row["duration_unit"],
    }


# --- section 5.4 checkout / order-status / opt-out -----------------------------


def _client_scope(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@infinitemarkets_public_api_router.post("/quote")
@public_boundary
async def public_quote(request: Request, response: Response, body: dict):
    await _guard(request, response)
    readiness.assert_checkout_ready()
    await nip89.check_public_rate_limit(request, bucket="quote", limit=30, window_s=60)
    return await checkout_service.quote_preview(body)


@infinitemarkets_public_api_router.post("/checkout", status_code=201)
@public_boundary
async def public_checkout(request: Request, response: Response, body: dict):
    """§5.4 checkout — idempotency-claimed intake + §8.2 saga.

    Both checkout rate windows (10/min + 100/hour per HMAC'd IP) apply
    BEFORE the idempotency claim so replays also count toward the cap.
    """
    await _guard(request, response)
    readiness.assert_checkout_ready()
    settings = ext_settings()
    scope = _client_scope(request)
    # §15: both checkout windows — 10/min AND 100/hour per IP.
    await nip89.check_public_rate_limit(
        request, bucket="checkout-min",
        limit=settings.checkout_rate_limit, window_s=60,
    )
    await nip89.check_public_rate_limit(
        request, bucket="checkout-hour",
        limit=settings.checkout_rate_limit_hourly, window_s=3600,
    )
    key = checkout_service.validate_idempotency_key(
        request.headers.get("idempotency-key")
    )
    # D-04: a valid session attributes the order to the buyer pubkey —
    # a stale/missing cookie keeps anonymous web-checkout semantics.
    # When a session cookie is PRESENT the mutation is attributed, so
    # exact-Origin applies (cookie-mutation rule); stale cookies resolve
    # to no session rather than bypassing checkout.
    if request.cookies.get(nostr_auth.SESSION_COOKIE) is not None:
        nostr_auth.require_origin(request)
    buyer_session = await nostr_auth.session_from_cookie(
        request.cookies.get(nostr_auth.SESSION_COOKIE)
    )
    return await checkout_service.checkout(
        payload=body, idempotency_key=key, client_scope=scope,
        buyer_session=buyer_session,
    )


_TOKEN_INVALID = ProblemError(
    401, "unauthorized", "Token invalid",
    "this order link is no longer valid",
)


async def _order_for_token(token: str | None) -> dict:
    """Resolve the order by bearer token — identical failure for every
    invalid shape (no existence oracle, §11.4/§5.4)."""
    if not token:
        raise _TOKEN_INVALID
    try:
        digest = crypto.token_lookup_hash(token)
    except crypto.CryptoError:
        raise _TOKEN_INVALID from None
    async with db.connect() as conn:
        row = await conn.fetchone(
            f"SELECT * FROM {table('orders')} "
            "WHERE public_token_hash = :h",
            {"h": digest},
        )
    if not row:
        raise _TOKEN_INVALID
    order = dict(row)
    now = int(time.time())
    if (
        order["public_token_expires_at"] is not None
        and order["public_token_expires_at"] <= now
    ):
        raise _TOKEN_INVALID
    return order


@infinitemarkets_public_api_router.get("/order-status")
@public_boundary
async def public_order_status(request: Request, response: Response):
    """§5.4 status — token arrives ONLY via the X-Order-Token header.

    The response is restricted to exactly the §5.4 field set: state,
    shipping_state, total_sat, bolt11 (while awaiting_payment), payment
    status, item summaries, expiry, and digital delivery content (only
    after confirmed payment). No internals, no payment_hash, no buyer
    echoes.
    """
    await _guard(request, response)
    order = await _order_for_token(request.headers.get("x-order-token"))
    async with db.connect() as conn:
        items = await conn.fetchall(
            f"SELECT title, quantity, line_total_sat FROM"
            f" {table('order_items')} WHERE order_id = :o",
            {"o": order["id"]},
        )
        payment = await conn.fetchone(
            f"SELECT status, bolt11_enc FROM {table('payments')} "
            "WHERE order_id = :o",
            {"o": order["id"]},
        )
        from .services.orders import digital_delivery

        delivery = await digital_delivery(conn, order)
    body = _order_status_projection(order, items, payment, delivery)
    body["bolt11"] = await _order_payment_bolt11(order, payment)
    return body


@infinitemarkets_public_api_router.post("/order-email-opt-out")
@public_boundary
async def public_order_email_opt_out(request: Request, response: Response):
    """§8.8 opt-out — sets email_opt_in=false and cancels queued customer
    rows for the order (never a signal beyond the bearer token)."""
    await _guard(request, response)
    order = await _order_for_token(request.headers.get("x-order-token"))
    from .db import DomainTransaction

    async with DomainTransaction() as tx:
        await tx.execute(
            f"UPDATE {tx.table('orders')} SET email_opt_in = FALSE,"
            " public_token_enc = NULL, updated_at = :n WHERE id = :i",
            {"n": int(time.time()), "i": order["id"]},
        )
        await tx.execute(
            f"UPDATE {tx.table('email_queue')} SET state = 'suppressed'"
            " WHERE order_id = :o AND channel = 'customer'"
            " AND state IN ('pending', 'claimed')",
            {"o": order["id"]},
        )
    return {"email_opt_in": False}


# --- NIP-07 buyer sign-in + order history (03-03, D-01..D-05) ----------------
#
# The session cookie is HttpOnly + Secure + SameSite=Strict, scoped to the
# extension prefix; every session mutation enforces the exact-Origin rule
# (same posture as admin cookie mutations — PATTERNS §6a). Lookups are
# no-oracle: malformed/unknown/expired/revoked tokens and every sign-in
# failure class share one 401 response.


class _Strict(BaseModel):
    class Config:
        extra = "forbid"


class NostrVerifyBody(_Strict):
    event: str | None = Field(
        default=None, min_length=1,
        max_length=nostr_auth.SIGNIN_EVENT_MAX_BYTES,
    )
    nsec: str | None = Field(default=None, min_length=1, max_length=128)


class NostrClaimBody(_Strict):
    token: str = Field(min_length=1, max_length=4096)


class NostrProfileBody(_Strict):
    event: str = Field(min_length=1, max_length=nostr_auth.SIGNIN_EVENT_MAX_BYTES)


class EmailRequestBody(_Strict):
    email: str = Field(min_length=3, max_length=254)


class EmailVerifyBody(_Strict):
    token: str = Field(min_length=1, max_length=128)


class LinkEmailBody(_Strict):
    email: str = Field(min_length=3, max_length=254)


class LinkVerifyBody(_Strict):
    event: str = Field(min_length=1, max_length=nostr_auth.SIGNIN_EVENT_MAX_BYTES)


async def _merchant_for_signin(request: Request) -> dict:
    """The merchant this sign-in scopes to — ``?shop=<pubkey>`` or the
    single merchant row (single-merchant deployments)."""
    shop = request.query_params.get("shop", "")
    if re.fullmatch(r"[0-9a-f]{64}", shop or ""):
        merchant = await nip89.merchant_by_pubkey(shop)
        if merchant and merchant["state"] not in (
            "deactivating", "inactive",
        ):
            return merchant
        raise not_found("merchant not found")
    async with db.connect() as conn:
        row = await conn.fetchone(
            f"SELECT * FROM {table('merchants')} ORDER BY created_at LIMIT 1"
        )
    if not row:
        raise not_found("merchant not found")
    return dict(row)


async def _buyer_session(request: Request) -> dict:
    """Resolve the session cookie — identical 401 for every failure."""
    session = await nostr_auth.session_from_cookie(
        request.cookies.get(nostr_auth.SESSION_COOKIE)
    )
    if session is None:
        raise nostr_auth.SESSION_INVALID
    return session


@infinitemarkets_public_api_router.get("/nostr/challenge")
@public_boundary
async def nostr_challenge(request: Request, response: Response):
    """Issue a one-time 256-bit sign-in challenge (300 s TTL)."""
    await _guard(request, response)
    await nip89.check_public_rate_limit(
        request, bucket="nostr-challenge", limit=30, window_s=60
    )
    merchant = await _merchant_for_signin(request)
    result = await nostr_auth.issue_challenge(
        merchant["id"], _client_scope(request)
    )
    from lnbits.settings import settings as host_settings

    result["nsec_signin"] = ext_settings().nsec_signin
    # Host-capability disclosure (not a per-account oracle): which sign-in
    # methods the deployment can actually serve right now.
    result["email_signin"] = bool(
        ext_settings().email_enabled
        and host_settings.is_email_notifications_configured()
    )
    result["nostr_signin"] = merchant["inbox_state"] == "active"
    return result


@infinitemarkets_public_api_router.post("/nostr/verify")
@public_boundary
async def nostr_verify(
    request: Request, response: Response, body: NostrVerifyBody
):
    """Verify the signed kind-22242 challenge event → session cookie.

    Exact-Origin applies unconditionally here: verifying a foreign-origin
    request would otherwise let a cross-site page fixate a session
    cookie on the victim's browser (login CSRF).

    ``nsec`` is a dev/e2e path gated by ``INFINITEMARKETS_NSEC_SIGNIN`` —
    when off it fails with the identical 401 as a bad signature."""
    await _guard(request, response)
    await nip89.check_public_rate_limit(
        request, bucket="nostr-verify", limit=30, window_s=60
    )
    nostr_auth.require_origin(request)
    merchant = await _merchant_for_signin(request)
    if body.nsec:
        if not ext_settings().nsec_signin:
            raise nostr_auth.SIGNIN_INVALID
        result = await nostr_auth.signin_nsec(
            merchant["id"], body.nsec
        )
    elif body.event:
        result = await nostr_auth.verify_signin(
            merchant["id"], body.event, _client_scope(request)
        )
    else:
        raise nostr_auth.SIGNIN_INVALID
    response.set_cookie(
        nostr_auth.SESSION_COOKIE,
        result["token"],
        max_age=nostr_auth.NOSTR_SESSION_TTL_S,
        httponly=True,
        secure=True,
        samesite="strict",
        path=nostr_auth.SESSION_COOKIE_PATH,
    )
    return {
        "signed_in": True,
        "pubkey": result["npub"],
        "expires_at": result["expires_at"],
    }


@infinitemarkets_public_api_router.post("/nostr/email/request")
@public_boundary
async def nostr_email_request(
    request: Request, response: Response, body: EmailRequestBody
):
    """D-05/D-06 no-oracle magic-link request.

    The SAME body answers every outcome — unknown email, known email,
    per-email cap reached (the send is silently skipped; the per-IP
    bucket stays an honest 429). Exact-Origin applies: the minted token
    is a credential, and mailbox-triggered sends must not be cross-site
    fireable."""
    await _guard(request, response)
    await nip89.check_public_rate_limit(
        request, bucket="nostr-email-req", limit=10, window_s=60
    )
    nostr_auth.require_origin(request)
    merchant = await _merchant_for_signin(request)
    await nostr_auth.request_email_signin(merchant["id"], body.email)
    return {"sent": True, "detail": "check your email for a sign-in link"}


@infinitemarkets_public_api_router.post("/nostr/email/verify")
@public_boundary
async def nostr_email_verify(
    request: Request, response: Response, body: EmailVerifyBody
):
    """D-08 fragment-token verify → identical session cookie (signin) or
    identity link (link). Every failure class is the identical 401 —
    malformed, unknown, used, expired, and wrong-shop tokens are
    indistinguishable. Exact-Origin is the login-CSRF gate — never
    relaxed for the fragment flow."""
    await _guard(request, response)
    await nip89.check_public_rate_limit(
        request, bucket="nostr-email-verify", limit=30, window_s=60
    )
    nostr_auth.require_origin(request)
    merchant = await _merchant_for_signin(request)
    result = await nostr_auth.verify_email_token(
        merchant["id"], body.token
    )
    if result["purpose"] == "link":
        # Prove, don't sign-in — no cookie is minted for link tokens.
        return {
            "linked": result["linked"],
            "merged": result["merged"],
            "bound_orders": result["bound_orders"],
            "redirect": "/infinitemarkets/profile",
        }
    response.set_cookie(
        nostr_auth.SESSION_COOKIE,
        result["session"]["token"],
        max_age=nostr_auth.NOSTR_SESSION_TTL_S,
        httponly=True,
        secure=True,
        samesite="strict",
        path=nostr_auth.SESSION_COOKIE_PATH,
    )
    return {
        "signed_in": True,
        "pubkey": result["session"]["npub"],
        "email": result["email"],
        "bound_orders": result["bound_orders"],
        "redirect": "/infinitemarkets/orders",
    }


# --- identity linking (D-10/D-11) ---------------------------------------------
#
# Prove-and-attach flows for a signed-in account. Email direction: mail a
# ``purpose='link'`` token bound to the session account — the click proves
# inbox ownership without needing a session. Nostr direction: a
# ``purpose='link'`` challenge + signed kind-22242 round-trip. A verified
# identity already owned elsewhere merges by union; unrepresentable
# unions reject with an honest 409 (the prover owns the identity — never
# an oracle).


@infinitemarkets_public_api_router.post("/nostr/link/email")
@public_boundary
async def nostr_link_email(
    request: Request, response: Response, body: LinkEmailBody
):
    """Send a link-verification token to ``email`` for the session
    account. Same uniform body as the sign-in request; an account that
    already holds a verified email gets an early honest 409."""
    await _guard(request, response)
    await nip89.check_public_rate_limit(
        request, bucket="nostr-link", limit=10, window_s=60
    )
    nostr_auth.require_origin(request)
    session = await _buyer_session(request)
    await nostr_auth.request_email_link(session, body.email)
    return {"sent": True, "detail": "check your email for a sign-in link"}


@infinitemarkets_public_api_router.get("/nostr/link/challenge")
@public_boundary
async def nostr_link_challenge(request: Request, response: Response):
    """Issue a ``purpose='link'`` challenge bound to the session account
    (D-10) — it can prove a pubkey but never mint a session."""
    await _guard(request, response)
    await nip89.check_public_rate_limit(
        request, bucket="nostr-link", limit=10, window_s=60
    )
    session = await _buyer_session(request)
    return await nostr_auth.issue_link_challenge(
        session["merchant_id"], session, _client_scope(request)
    )


@infinitemarkets_public_api_router.post("/nostr/link/verify")
@public_boundary
async def nostr_link_verify(
    request: Request, response: Response, body: LinkVerifyBody
):
    """Verify the signed link event → attach/merge the proven pubkey
    onto the session account (D-10/D-11)."""
    await _guard(request, response)
    await nip89.check_public_rate_limit(
        request, bucket="nostr-link", limit=10, window_s=60
    )
    nostr_auth.require_origin(request)
    session = await _buyer_session(request)
    result = await nostr_auth.verify_link_event(
        session["merchant_id"], body.event, _client_scope(request),
        session=session,
    )
    return {
        "linked": result["linked"],
        "merged": result["merged"],
        "bound_orders": result["bound_orders"],
        "redirect": "/infinitemarkets/profile",
    }


@infinitemarkets_public_api_router.post("/nostr/logout")
@public_boundary
async def nostr_logout(request: Request, response: Response):
    """Revoke the session row + clear the cookie."""
    await _guard(request, response)
    nostr_auth.require_origin(request)
    await nostr_auth.revoke_session(
        request.cookies.get(nostr_auth.SESSION_COOKIE)
    )
    response.delete_cookie(
        nostr_auth.SESSION_COOKIE,
        path=nostr_auth.SESSION_COOKIE_PATH,
        samesite="strict",
        secure=True,
        httponly=True,
    )
    return {"signed_in": False}


def _order_status_projection(
    order: dict, items: list, payment: dict | None, delivery: list
) -> dict:
    """The §5.4 field set shared by ``order-status`` and
    ``/nostr/orders`` — identical keys, identical gating."""
    return {
        "state": order["state"],
        "shipping_state": order["shipping_state"],
        "total_sat": order["total_sat"],
        "bolt11": None,  # caller fills while awaiting_payment
        "payment_status": payment["status"] if payment else None,
        "items": [
            {
                "title": i["title"],
                "quantity": i["quantity"],
                "line_total_sat": i["line_total_sat"],
            }
            for i in items
        ],
        "expires_at": order["invoice_expiry"],
        "email_opt_in": bool(order["email_opt_in"]),
        "payment_exception": bool(order["payment_exception"]),
        "digital_delivery": delivery,
    }


async def _order_payment_bolt11(order: dict, payment: dict | None):
    """Decrypt the invoice only while the order awaits payment."""
    if (
        order["state"] != "awaiting_payment"
        or not payment
        or payment["bolt11_enc"] is None
    ):
        return None
    settings = ext_settings()
    ver = crypto.envelope_version(payment["bolt11_enc"])
    return crypto.decrypt(
        payment["bolt11_enc"], settings.master_keys[ver],
        record_id=order["id"], table="payments", column="bolt11_enc",
        key_version=ver,
    ).decode()


@infinitemarkets_public_api_router.get("/nostr/orders")
@public_boundary
async def nostr_orders(request: Request, response: Response):
    """The signed-in buyer's own order history — the union of the session
    account's ``pubkey_hash`` and ``email_hash`` bindings (D-03/D-09; a
    NULL parameter collapses its side), same field set + delivery gating
    as ``order-status``."""
    await _guard(request, response)
    session = await _buyer_session(request)
    settings = ext_settings()
    out = []
    async with db.connect() as conn:
        merchant = await conn.fetchone(
            f"SELECT pubkey FROM {table('merchants')} WHERE id = :m",
            {"m": session["merchant_id"]},
        )
        rows = await conn.fetchall(
            f"SELECT * FROM {table('orders')} WHERE merchant_id = :m"
            " AND (buyer_pubkey_hash = :ph OR buyer_email_hash = :eh)"
            " ORDER BY created_at DESC LIMIT 100",
            {
                "m": session["merchant_id"],
                "ph": session["pubkey_hash"],
                "eh": session["email_hash"],
            },
        )
        from .services.orders import digital_delivery

        for row in rows:
            order = dict(row)
            items = await conn.fetchall(
                f"SELECT title, quantity, line_total_sat FROM"
                f" {table('order_items')} WHERE order_id = :o",
                {"o": order["id"]},
            )
            payment = await conn.fetchone(
                f"SELECT status, bolt11_enc FROM {table('payments')}"
                " WHERE order_id = :o",
                {"o": order["id"]},
            )
            delivery = await digital_delivery(conn, order)
            entry = _order_status_projection(order, items, payment, delivery)
            entry["bolt11"] = await _order_payment_bolt11(order, payment)
            entry["order_id"] = order["id"]
            entry["created_at"] = order["created_at"]
            entry["receipt_verified"] = bool(order["receipt_verified"])
            entry["first_item"] = items[0]["title"] if items else ""
            # Token-equivalent visibility: the private status link is
            # recoverable while the stored token copy is live.
            status_url = None
            now = int(time.time())
            if (
                order["public_token_enc"] is not None
                and order["public_token_expires_at"] is not None
                and order["public_token_expires_at"] > now
            ):
                ver = crypto.envelope_version(order["public_token_enc"])
                token = crypto.decrypt(
                    order["public_token_enc"], settings.master_keys[ver],
                    record_id=order["id"], table="orders",
                    column="public_token_enc", key_version=ver,
                ).decode()
                shop = (
                    f"?shop={merchant['pubkey']}" if merchant else ""
                )
                status_url = (
                    f"{settings.public_base_url}/infinitemarkets/order"
                    f"{shop}#{token}"
                )
            entry["status_url"] = status_url
            out.append(entry)
    return {"orders": out}


# --- buyer kind-0 profile (read + publish via merchant public relays) ----
#
# The header account chip needs a display name/avatar and the profile page
# edits standard kind-0 fields. Reads fetch the session pubkey's latest
# kind-0 from the session merchant's public relays (short process-local
# cache — the chip probes every page). Writes accept a signed kind-0
# authored by the session key and publish it on the same public set.

#: Kind-0 fields the profile editor manages/display the chip uses.
PROFILE_FIELDS = (
    "name", "display_name", "picture", "banner", "about",
    "nip05", "lud16", "website",
)
PROFILE_EVENT_MAX_AGE_S = nostr_auth.SIGNIN_EVENT_MAX_AGE_S
_PROFILE_CACHE_TTL_S = 300
_PROFILE_CACHE_MAX = 256
_profile_cache: dict[str, tuple[float, dict | None]] = {}


async def _fetch_kind0(merchant_id: str, pubkey_hex: str):
    """Latest kind-0 for ``pubkey_hex`` on the merchant's public relays —
    returns the field projection dict or None."""
    from nostr_sdk import Filter, Kind, PublicKey

    from .services import relay as relay_service
    from .services.transport import transport

    now = time.monotonic()
    cached = _profile_cache.get(pubkey_hex)
    if cached and cached[0] > now:
        return cached[1]
    urls = await relay_service.relay_targets(merchant_id, "public")
    profile = None
    if urls:
        try:
            events = await transport().fetch_from(
                urls,
                Filter().kinds([Kind(0)]).author(
                    PublicKey.parse(pubkey_hex)
                ),
                timeout_s=8,
            )
        except Exception:  # noqa: BLE001 — relay outage is a null profile
            events = []
        events = [
            e for e in events
            if e.kind().as_u16() == 0
            and e.author().to_hex() == pubkey_hex
        ]
        if events:
            latest = max(
                events, key=lambda e: e.created_at().as_secs()
            )
            try:
                content = json.loads(latest.content() or "{}")
            except (json.JSONDecodeError, TypeError):
                content = {}
            if isinstance(content, dict):
                profile = {
                    k: content[k]
                    for k in PROFILE_FIELDS
                    if isinstance(content.get(k), str) and content[k]
                }
    if len(_profile_cache) >= _PROFILE_CACHE_MAX:
        _profile_cache.clear()
    _profile_cache[pubkey_hex] = (now + _PROFILE_CACHE_TTL_S, profile)
    return profile


@infinitemarkets_public_api_router.get("/nostr/profile")
@public_boundary
async def nostr_profile(request: Request, response: Response):
    """Session account identity + the buyer's relay kind-0 metadata —
    drives the account chip (name/avatar) and prefills the profile
    editor. Email-only accounts return null ``pubkey``/``npub``/
    ``profile`` plus their verified ``email`` (session-owner-only
    disclosure — not an oracle to anyone else)."""
    await _guard(request, response)
    await nip89.check_public_rate_limit(
        request, bucket="nostr-profile", limit=60, window_s=60
    )
    session = await _buyer_session(request)
    buyer_pubkey = session["buyer_pubkey"]
    npub = None
    profile = None
    if buyer_pubkey:
        from nostr_sdk import PublicKey

        npub = PublicKey.parse(buyer_pubkey).to_bech32()
        profile = await _fetch_kind0(session["merchant_id"], buyer_pubkey)
    return {
        "pubkey": buyer_pubkey,
        "npub": npub,
        "email": session["email"],
        "profile": profile,
    }


@infinitemarkets_public_api_router.post("/nostr/profile")
@public_boundary
async def nostr_profile_publish(
    request: Request, response: Response, body: NostrProfileBody
):
    """Publish a buyer-signed kind-0 to the session merchant's public
    relays. The event must verify, be authored by the session key, be
    fresh, and carry a JSON-object profile document."""
    await _guard(request, response)
    await nip89.check_public_rate_limit(
        request, bucket="nostr-profile-post", limit=10, window_s=60
    )
    nostr_auth.require_origin(request)
    session = await _buyer_session(request)
    if not session["buyer_pubkey"]:
        # Kind-0 needs a key to verify/author — an email-only session can
        # never satisfy the author check, so refuse honestly up front
        # instead of failing the comparison (or crashing) later.
        raise unprocessable(
            "nostr-identity-required",
            "Link a Nostr key to manage a public profile",
        )
    from nostr_sdk import Event

    try:
        event = Event.from_json(body.event)
    except Exception:
        raise unprocessable("invalid-event", "Event is not valid JSON")
    if event.kind().as_u16() != 0:
        raise unprocessable(
            "invalid-event", "Profile publish requires a kind-0 event"
        )
    if event.author().to_hex() != session["buyer_pubkey"]:
        raise unprocessable(
            "invalid-event",
            "Event must be authored by the signed-in key",
        )
    try:
        if not event.verify():
            raise unprocessable("invalid-event", "Invalid signature")
    except ProblemError:
        raise
    except Exception:
        raise unprocessable("invalid-event", "Invalid signature")
    if (
        abs(int(time.time()) - event.created_at().as_secs())
        > PROFILE_EVENT_MAX_AGE_S
    ):
        raise unprocessable("stale-event", "Event is not fresh")
    try:
        content = json.loads(event.content() or "{}")
    except (json.JSONDecodeError, TypeError):
        raise unprocessable(
            "invalid-event", "Profile content must be a JSON object"
        ) from None
    if not isinstance(content, dict):
        raise unprocessable(
            "invalid-event", "Profile content must be a JSON object"
        )
    from .services import relay as relay_service
    from .services.transport import transport

    urls = await relay_service.relay_targets(
        session["merchant_id"], "public"
    )
    if not urls:
        raise unprocessable(
            "no-relay-targets", "No public relays are configured"
        )
    output = await transport().send_to(urls, event)
    accepted = sorted(str(u) for u in output.success)
    failed = {str(u): str(m) for u, m in output.failed.items()}
    _profile_cache.pop(session["buyer_pubkey"], None)
    return {
        "published": bool(accepted),
        "accepted": accepted,
        "failed": failed,
    }


@infinitemarkets_public_api_router.post("/nostr/claim")
@public_boundary
async def nostr_claim(
    request: Request, response: Response, body: NostrClaimBody
):
    """Bind the session's buyer pubkey to a token-resolved order (D-05).

    Every token failure is the identical ``_TOKEN_INVALID`` outcome —
    claim never distinguishes dead/malformed/expired/foreign-bound.
    """
    await _guard(request, response)
    await nip89.check_public_rate_limit(
        request, bucket="nostr-claim", limit=30, window_s=60
    )
    nostr_auth.require_origin(request)
    session = await _buyer_session(request)
    order = await _order_for_token(body.token)
    if order["merchant_id"] != session["merchant_id"]:
        # Cross-merchant token resolution is an identical invalid outcome.
        raise _TOKEN_INVALID
    return await nostr_auth.claim_order(session, order)
