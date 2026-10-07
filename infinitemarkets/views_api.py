"""Admin JSON API — /infinitemarkets/api/v1 (spec section 5.1/5.6).

Every route depends on the section-5.1 guard: ``check_user_exists`` for
identity, plus mutation rules (user-id-only rejected; cookie auth requires
exact canonical Origin + double-submit CSRF; bearer passes). All failures
are RFC 9457 problem details.
"""

from __future__ import annotations

import functools
import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request, Response
from lnbits.core.models import User
from lnbits.decorators import check_user_exists
from pydantic import BaseModel, Field
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from .security import (
    ProblemError,
    enforce_mutation_security,
    issue_csrf_cookie,
    problem_for,
    unprocessable,
)
from .services import merchant as merchant_service

infinitemarkets_api_router = APIRouter(prefix="/api/v1")


def problem_boundary(fn):
    """Enforce section-5.1 mutation security + render ProblemError as
    problem+json.

    Every route declares ``request: Request`` so this wrapper can run the
    mutation rules (dependency-raised errors would bypass problem+json
    rendering). Routes also declaring ``response: Response`` get the
    double-submit CSRF cookie issued for cookie-authenticated callers —
    on BOTH success and problem paths, so a fresh admin client (whose
    first call may 404) always receives a token.
    """

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        request = kwargs.get("request")
        response = kwargs.get("response")
        try:
            if isinstance(request, Request):
                enforce_mutation_security(request)
            result = await fn(*args, **kwargs)
        except ProblemError as exc:
            resp = problem_for(exc)
            if isinstance(request, Request) and request.cookies.get(
                "cookie_access_token"
            ):
                issue_csrf_cookie(resp, request)
            return resp
        if (
            isinstance(request, Request)
            and isinstance(response, Response)
            and request.cookies.get("cookie_access_token")
        ):
            issue_csrf_cookie(response, request)
        return result

    return wrapper


# --- request bodies ----------------------------------------------------------


class _Strict(BaseModel):
    class Config:
        extra = "forbid"


class CreateMerchantBody(_Strict):
    wallet_id: str
    display_name: str | None = None
    payment_preference: str = "manual"


class PatchMerchantBody(_Strict):
    display_name: str | None = None
    profile_json: Any = None
    recommended_app_d: str | None = None
    wallet_id: str | None = None
    notify_emails: list[str] | None = None
    notify_events: dict | None = None
    theme: Any = None
    relay_configs: list[dict] | None = None
    blossom_servers: list[str] | None = None


class ImportKeyBody(_Strict):
    nsec: str = Field(min_length=1, max_length=128)


class TestNotificationBody(_Strict):
    recipient: str


class PatchNotificationsBody(_Strict):
    notify_emails: list[str] | None = None
    notify_events: dict | None = None


class ImportCategoryBody(_Strict):
    category_id: str = Field(min_length=32, max_length=32)


class BulkProductsBody(_Strict):
    product_ids: list[str] = Field(min_items=1, max_items=100)
    action: Literal[
        "price-markup",
        "move-collection",
        "visibility",
        "draft",
        "publish",
        "delete",
    ]
    value: Any = None


def _patch_dict(body: PatchMerchantBody) -> dict:
    """Only fields explicitly present in the request are patched."""
    return {
        k: v for k, v in body.dict(exclude_unset=True).items()
        if v is not None or k in body.__fields_set__
    }


# --- section 5.1 merchant routes ---------------------------------------------


@infinitemarkets_api_router.post("/merchants", status_code=201)
@problem_boundary
async def create_merchant(
    request: Request,
    body: CreateMerchantBody, user: User = Depends(check_user_exists)
):
    return await merchant_service.create_merchant(
        user,
        wallet_id=body.wallet_id,
        display_name=body.display_name,
        payment_preference=body.payment_preference,
    )


@infinitemarkets_api_router.get("/merchants/current")
@problem_boundary
async def get_current_merchant(
    request: Request,
    response: Response,
    user: User = Depends(check_user_exists),
):
    # Admin clients learn the double-submit token via the boundary before
    # mutating — even when this GET 404s on a first visit.
    return await merchant_service.current_merchant(user)


@infinitemarkets_api_router.patch("/merchants/{merchant_id}")
@problem_boundary
async def patch_merchant(
    request: Request,
    merchant_id: str,
    body: PatchMerchantBody,
    user: User = Depends(check_user_exists),
):
    return await merchant_service.patch_merchant(
        merchant_id, user, _patch_dict(body)
    )


@infinitemarkets_api_router.post("/merchants/{merchant_id}/keys/import")
@problem_boundary
async def import_key(
    request: Request,
    merchant_id: str,
    body: ImportKeyBody,
    user: User = Depends(check_user_exists),
):
    merchant = await merchant_service.import_nsec(
        merchant_id, user, body.nsec
    )
    # The nsec never appears in the response (or anywhere outside the
    # keystore operation).
    return {"pubkey": merchant["pubkey"], "merchant_id": merchant["id"]}


@infinitemarkets_api_router.post("/merchants/{merchant_id}/publish")
@problem_boundary
async def publish_merchant(
    request: Request,
    merchant_id: str, user: User = Depends(check_user_exists)
):
    return await merchant_service.publish(merchant_id, user)


@infinitemarkets_api_router.get("/merchants/{merchant_id}/relay-health")
@problem_boundary
async def get_relay_health(
    request: Request,
    merchant_id: str, user: User = Depends(check_user_exists)
):
    from .services import relay as relay_service

    await merchant_service.get_merchant_row(merchant_id, str(user.id))
    health = await relay_service.relay_health(merchant_id)
    # Starter defaults are exposed so the UI can offer one-click options.
    health["defaults"] = {
        "relays": list(relay_service.DEFAULT_RELAYS),
        "blossom_servers": list(relay_service.DEFAULT_BLOSSOM_SERVERS),
    }
    health["blossom_servers"] = await relay_service.get_blossom_servers(
        merchant_id
    )
    return health


@infinitemarkets_api_router.get("/merchants/{merchant_id}/outbox")
@problem_boundary
async def get_outbox(
    request: Request,
    merchant_id: str,
    user: User = Depends(check_user_exists),
    limit: int = 100,
):
    """B2 surface — spec-delta route (W-NEW-1, 02-02 summary)."""
    from .services import relay as relay_service

    await merchant_service.get_merchant_row(merchant_id, str(user.id))
    return await relay_service.list_outbox(merchant_id, limit)


class OutboxPruneBody(_Strict):
    older_than_days: int = Field(default=90, ge=7, le=3650)


@infinitemarkets_api_router.post("/merchants/{merchant_id}/outbox/prune")
@problem_boundary
async def prune_outbox_history(
    request: Request,
    merchant_id: str,
    body: OutboxPruneBody,
    user: User = Depends(check_user_exists),
):
    """Flush terminal outbox history (published/superseded/failed) older
    than the given window. In-flight intents are untouched."""
    from .services import relay as relay_service

    await merchant_service.get_merchant_row(merchant_id, str(user.id))
    return await relay_service.prune_outbox(
        merchant_id, body.older_than_days
    )


@infinitemarkets_api_router.post(
    "/merchants/{merchant_id}/outbox/{intent_id}/retry"
)
@problem_boundary
async def retry_outbox_intent(
    request: Request,
    merchant_id: str,
    intent_id: str,
    user: User = Depends(check_user_exists),
):
    """Retry a failed/partially_published intent — spec-delta route
    (W-NEW-1). Accepted relay targets are never resent."""
    from .services import relay as relay_service

    await merchant_service.get_merchant_row(merchant_id, str(user.id))
    return await relay_service.retry_intent(merchant_id, intent_id)


@infinitemarkets_api_router.post("/merchants/{merchant_id}/inbox/enable")
@problem_boundary
async def enable_inbox(
    request: Request,
    merchant_id: str, user: User = Depends(check_user_exists)
):
    """Gamma inbox activation (D-16/GAM-01): enqueues the kind-10050
    publish intent; ``inbox_state`` reaches ``active`` only through
    durable relay ACK evidence."""
    return await merchant_service.enable_inbox(merchant_id, user)


@infinitemarkets_api_router.post("/merchants/{merchant_id}/inbox/disable")
@problem_boundary
async def disable_inbox(
    request: Request,
    merchant_id: str, user: User = Depends(check_user_exists)
):
    """D-17: kind-5 tombstone for the 10050 profile + intake stop;
    in-flight orders are untouched."""
    return await merchant_service.disable_inbox(merchant_id, user)


@infinitemarkets_api_router.get("/merchants/{merchant_id}/inbox-state")
@problem_boundary
async def get_inbox_state(
    request: Request,
    merchant_id: str, user: User = Depends(check_user_exists)
):
    return await merchant_service.get_inbox_state(merchant_id, user)


class StorefrontModeBody(_Strict):
    mode: str
    confirm: bool = False


@infinitemarkets_api_router.get("/merchants/{merchant_id}/storefront-mode")
@problem_boundary
async def get_storefront_mode(
    request: Request,
    merchant_id: str, user: User = Depends(check_user_exists)
):
    """Current mode + which modes are blocked and why (D-10)."""
    from .services import storefront_mode as mode_service

    merchant = await merchant_service.get_merchant_row(
        merchant_id, str(user.id)
    )
    inbox_active = merchant.get("inbox_state") == "active"
    return {
        "mode": await mode_service.get_mode(merchant_id),
        "inbox_state": merchant.get("inbox_state"),
        "modes": list(mode_service.MODES),
        "blocked": {
            m: m in mode_service.INBOX_GATED_MODES and not inbox_active
            for m in mode_service.MODES
        },
        "blocked_reason": (
            None
            if inbox_active
            else "requires an active Nostr inbox (kind-10050 published)"
        ),
        "impact": mode_service.MODE_IMPACT,
    }


@infinitemarkets_api_router.put("/merchants/{merchant_id}/storefront-mode")
@problem_boundary
async def put_storefront_mode(
    request: Request,
    merchant_id: str,
    body: StorefrontModeBody,
    user: User = Depends(check_user_exists),
):
    """Two-step mode change: ``{mode}`` returns the impact list;
    ``{mode, confirm: true}`` applies. D-10 gates showcase/nostr_only
    on an active inbox; D-11 keeps in-flight orders untouched."""
    from .services import storefront_mode as mode_service

    merchant = await merchant_service.get_merchant_row(
        merchant_id, str(user.id)
    )
    return await mode_service.set_mode(
        merchant, body.mode, confirm=body.confirm
    )


@infinitemarkets_api_router.get("/merchants/{merchant_id}/relay-auth")
@problem_boundary
async def get_relay_auth(
    request: Request,
    merchant_id: str, user: User = Depends(check_user_exists)
):
    """D-26..D-28 per-relay auth surface: state, note, paid invoice,
    timestamps, and live connection state."""
    from .services import relay as relay_service

    await merchant_service.get_merchant_row(merchant_id, str(user.id))
    health = await relay_service.relay_health(merchant_id)
    return {
        "relays": [
            {
                "relay_url": r["relay_url"],
                "direction": r["direction"],
                "auth_state": r["auth_state"],
                "auth_note": r["auth_note"],
                "paid_invoice": r["paid_invoice"],
                "auth_updated_at": r["auth_updated_at"],
                "connected": r["connected"],
            }
            for r in health["relays"]
        ]
    }


@infinitemarkets_api_router.post(
    "/merchants/{merchant_id}/relay-auth/retry/{relay_url:path}"
)
@problem_boundary
async def retry_relay_auth(
    request: Request,
    merchant_id: str, relay_url: str,
    user: User = Depends(check_user_exists)
):
    """Clear auth-failed/payment-required so the next session re-auths.
    The relay URL is the trailing path segment (encoded or literal)."""
    from .services import relay as relay_service

    await merchant_service.get_merchant_row(merchant_id, str(user.id))
    return await relay_service.retry_relay_auth(merchant_id, relay_url)


@infinitemarkets_api_router.get("/merchants/{merchant_id}/notifications")
@problem_boundary
async def get_notifications(
    request: Request,
    merchant_id: str, user: User = Depends(check_user_exists)
):
    return await merchant_service.get_notifications(merchant_id, user)


@infinitemarkets_api_router.patch("/merchants/{merchant_id}/notifications")
@problem_boundary
async def patch_notifications(
    request: Request,
    merchant_id: str,
    body: PatchNotificationsBody,
    user: User = Depends(check_user_exists),
):
    patch = {
        k: v for k, v in body.dict(exclude_unset=True).items()
    }
    if not patch:
        raise unprocessable(
            "invalid-transition", "Empty notification patch"
        )
    return await merchant_service.patch_merchant(
        merchant_id, user, patch
    )


@infinitemarkets_api_router.post("/merchants/{merchant_id}/notifications/test")
@problem_boundary
async def test_notification(
    request: Request,
    merchant_id: str,
    body: TestNotificationBody,
    user: User = Depends(check_user_exists),
):
    return await merchant_service.send_test_notification(
        merchant_id, user, body.recipient
    )


@infinitemarkets_api_router.delete("/merchants/{merchant_id}")
@problem_boundary
async def delete_merchant(
    request: Request,
    merchant_id: str, user: User = Depends(check_user_exists)
):
    return await merchant_service.begin_deactivation(merchant_id, user)


async def _shopify_upload(request: Request, *, execute: bool):
    from .services.migration_import import MAX_UPLOAD_BYTES

    if not request.headers.get("content-type", "").startswith("multipart/form-data;"):
        raise unprocessable("invalid-content", "multipart upload required")

    async def bounded_stream():
        received = 0
        async for chunk in request.stream():
            received += len(chunk)
            if received > MAX_UPLOAD_BYTES:
                raise unprocessable("invalid-content", "import exceeds upload limit")
            yield chunk

    try:
        form = await MultiPartParser(
            request.headers, bounded_stream(), max_files=1, max_fields=4,
        ).parse()
    except MultiPartException as exc:
        raise unprocessable("invalid-content", "invalid import form") from exc
    try:
        expected = {"file", "currency", "source_instance"}
        if execute:
            expected.add("source_hash")
        if "image_selection" in form:
            expected.add("image_selection")
        if set(form.keys()) != expected or len(form.multi_items()) != len(expected):
            raise unprocessable("invalid-content", "unexpected import fields")
        upload = form["file"]
        if not isinstance(upload, UploadFile) or not upload.filename.lower().endswith(".csv"):
            raise unprocessable("invalid-content", "Shopify CSV file required")
        fields = tuple(form[name] for name in expected - {"file", "image_selection"})
        if any(not isinstance(value, str) or len(value) > 100 for value in fields):
            raise unprocessable("invalid-content", "invalid import fields")
        selection = None
        if "image_selection" in form:
            raw_selection = form["image_selection"]
            if not isinstance(raw_selection, str) or len(raw_selection) > 128000:
                raise unprocessable("invalid-content", "invalid image selection")
            try:
                selection = json.loads(raw_selection)
            except ValueError as exc:
                raise unprocessable("invalid-content", "invalid image selection") from exc
        data = await upload.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise unprocessable("invalid-content", "import exceeds upload limit")
        return data, form["currency"], form["source_instance"], form.get("source_hash"), selection
    finally:
        await form.close()


@infinitemarkets_api_router.post("/migration/products/{product_id}/category")
@problem_boundary
async def recategorize_import(
    request: Request, product_id: str, body: ImportCategoryBody,
    user: User = Depends(check_user_exists),
):
    from .services import catalog

    return await catalog.recategorize_import_draft(
        await _mid(user), user, product_id, body.category_id
    )


@infinitemarkets_api_router.post("/migration/shopify/preview")
@problem_boundary
async def preview_shopify(request: Request, user: User = Depends(check_user_exists)):
    from .services import migration_import

    await _mid(user)
    data, currency, source_instance, _, selection = await _shopify_upload(
        request, execute=False
    )
    try:
        return migration_import.preview_shopify_import(
            data, currency=currency, source_instance=source_instance,
            image_selection=selection,
        )
    except ValueError as exc:
        raise unprocessable("invalid-content", str(exc)) from exc


@infinitemarkets_api_router.post("/migration/shopify/execute")
@problem_boundary
async def execute_shopify(request: Request, user: User = Depends(check_user_exists)):
    from .services import migration_import

    merchant_id = await _mid(user)
    data, currency, source_instance, source_hash, selection = await _shopify_upload(
        request, execute=True
    )
    try:
        return await migration_import.execute_shopify_import(
            merchant_id, user, data, currency=currency,
            source_instance=source_instance, expected_hash=source_hash,
            image_selection=selection,
        )
    except ValueError as exc:
        raise unprocessable("invalid-content", str(exc)) from exc


# --- section 5.2 category routes ---------------------------------------------------
#
# These paths carry no merchant id — the caller's 1:1 merchant resolves
# implicitly (POST /merchants is the only way to create one).

from .services import catalog as category_service  # noqa: E402


async def _mid(user) -> str:
    return (await merchant_service.current_merchant(user))["id"]


@infinitemarkets_api_router.post("/categories", status_code=201)
@problem_boundary
async def create_category(
    request: Request,
    body: dict,
    user: User = Depends(check_user_exists),
):
    return await category_service.create_category(await _mid(user), user, body)


@infinitemarkets_api_router.get("/categories")
@problem_boundary
async def list_categories(
    request: Request, user: User = Depends(check_user_exists)
):
    return await category_service.list_categories(await _mid(user), user)


@infinitemarkets_api_router.get("/categories/{category_id}")
@problem_boundary
async def get_category(
    request: Request,
    category_id: str,
    user: User = Depends(check_user_exists),
):
    return await category_service.get_category(
        await _mid(user), user, category_id
    )


@infinitemarkets_api_router.patch("/categories/{category_id}")
@problem_boundary
async def patch_category(
    request: Request,
    category_id: str,
    body: dict,
    user: User = Depends(check_user_exists),
):
    return await category_service.patch_category(
        await _mid(user), user, category_id, body
    )


@infinitemarkets_api_router.delete("/categories/{category_id}")
@problem_boundary
async def delete_category(
    request: Request,
    category_id: str,
    user: User = Depends(check_user_exists),
):
    return await category_service.delete_category(
        await _mid(user), user, category_id
    )


@infinitemarkets_api_router.post("/products", status_code=201)
@problem_boundary
async def create_product(
    request: Request,
    body: dict,
    user: User = Depends(check_user_exists),
):
    return await category_service.create_product(await _mid(user), user, body)


@infinitemarkets_api_router.post("/products/bulk")
@problem_boundary
async def bulk_products(
    request: Request,
    body: BulkProductsBody,
    user: User = Depends(check_user_exists),
):
    return await category_service.bulk_products(
        await _mid(user), user, body.product_ids, body.action, body.value
    )


@infinitemarkets_api_router.get("/products")
@problem_boundary
async def list_products(
    request: Request,
    user: User = Depends(check_user_exists),
    category_id: str | None = None,
):
    return await category_service.list_products(
        await _mid(user), user, category_id=category_id
    )


@infinitemarkets_api_router.get("/products/{product_id}")
@problem_boundary
async def get_product(
    request: Request,
    product_id: str,
    user: User = Depends(check_user_exists),
):
    return await category_service.get_product(
        await _mid(user), user, product_id
    )


@infinitemarkets_api_router.patch("/products/{product_id}")
@problem_boundary
async def patch_product(
    request: Request,
    product_id: str,
    body: dict,
    user: User = Depends(check_user_exists),
):
    return await category_service.patch_product(
        await _mid(user), user, product_id, body
    )


@infinitemarkets_api_router.delete("/products/{product_id}")
@problem_boundary
async def delete_product(
    request: Request,
    product_id: str,
    user: User = Depends(check_user_exists),
):
    return await category_service.delete_product(
        await _mid(user), user, product_id
    )


@infinitemarkets_api_router.post("/products/{product_id}/images",
                              status_code=201)
@problem_boundary
async def add_product_image(
    request: Request,
    product_id: str,
    body: dict,
    user: User = Depends(check_user_exists),
):
    return await category_service.add_product_image(
        await _mid(user), user, product_id, body
    )


@infinitemarkets_api_router.get("/products/{product_id}/events")
@problem_boundary
async def get_product_events(
    request: Request,
    product_id: str,
    user: User = Depends(check_user_exists),
):
    return await category_service.product_events(
        await _mid(user), user, product_id
    )


@infinitemarkets_api_router.post("/collections", status_code=201)
@problem_boundary
async def create_collection(
    request: Request,
    body: dict,
    user: User = Depends(check_user_exists),
):
    return await category_service.create_collection(
        await _mid(user), user, body
    )


@infinitemarkets_api_router.get("/collections")
@problem_boundary
async def list_collections(
    request: Request, user: User = Depends(check_user_exists)
):
    return await category_service.list_collections(await _mid(user), user)


@infinitemarkets_api_router.get("/collections/{collection_id}")
@problem_boundary
async def get_collection(
    request: Request,
    collection_id: str,
    user: User = Depends(check_user_exists),
):
    return await category_service.get_collection(
        await _mid(user), user, collection_id
    )


@infinitemarkets_api_router.patch("/collections/{collection_id}")
@problem_boundary
async def patch_collection(
    request: Request,
    collection_id: str,
    body: dict,
    user: User = Depends(check_user_exists),
):
    return await category_service.patch_collection(
        await _mid(user), user, collection_id, body
    )


@infinitemarkets_api_router.delete("/collections/{collection_id}")
@problem_boundary
async def delete_collection(
    request: Request,
    collection_id: str,
    user: User = Depends(check_user_exists),
    strip: bool = False,
):
    return await category_service.delete_collection(
        await _mid(user), user, collection_id, strip=strip
    )


@infinitemarkets_api_router.post("/shipping", status_code=201)
@problem_boundary
async def create_shipping(
    request: Request,
    body: dict,
    user: User = Depends(check_user_exists),
):
    return await category_service.create_shipping(await _mid(user), user, body)


@infinitemarkets_api_router.get("/shipping")
@problem_boundary
async def list_shipping(
    request: Request, user: User = Depends(check_user_exists)
):
    return await category_service.list_shipping(await _mid(user), user)


@infinitemarkets_api_router.get("/shipping/{option_id}")
@problem_boundary
async def get_shipping(
    request: Request,
    option_id: str,
    user: User = Depends(check_user_exists),
):
    return await category_service.get_shipping(
        await _mid(user), user, option_id
    )


@infinitemarkets_api_router.patch("/shipping/{option_id}")
@problem_boundary
async def patch_shipping(
    request: Request,
    option_id: str,
    body: dict,
    user: User = Depends(check_user_exists),
):
    return await category_service.patch_shipping(
        await _mid(user), user, option_id, body
    )


@infinitemarkets_api_router.delete("/shipping/{option_id}")
@problem_boundary
async def delete_shipping(
    request: Request,
    option_id: str,
    user: User = Depends(check_user_exists),
    strip: bool = False,
):
    return await category_service.delete_shipping(
        await _mid(user), user, option_id, strip=strip
    )


# --- section 5.3 order routes ---------------------------------------------------
#
# Merchant-scoped paths carry the merchant id explicitly (unlike §5.2).

from .services import orders as order_service  # noqa: E402


class OrderStatusBody(_Strict):
    to_state: str


class OrderShippingBody(_Strict):
    shipping_state: str
    tracking: str | None = None
    carrier: str | None = None
    eta: str | None = None


class OrderCancelBody(_Strict):
    reason: str | None = None


class ResolveExceptionBody(_Strict):
    action: str
    refund_reference: str | None = None


class BulkOrdersBody(_Strict):
    order_ids: list[str] = Field(min_items=1, max_items=100)
    action: Literal["archive", "restore"]


@infinitemarkets_api_router.get("/merchants/{merchant_id}/orders")
@problem_boundary
async def list_orders(
    request: Request,
    merchant_id: str,
    state: str | None = None,
    protocol: str | None = None,
    q: str | None = None,
    archived: bool = False,
    user: User = Depends(check_user_exists),
):
    return await order_service.list_orders(
        merchant_id,
        user,
        state=state,
        protocol=protocol,
        q=q,
        archived=archived,
    )


@infinitemarkets_api_router.post("/merchants/{merchant_id}/orders/bulk")
@problem_boundary
async def bulk_orders(
    request: Request,
    merchant_id: str,
    body: BulkOrdersBody,
    user: User = Depends(check_user_exists),
):
    return await order_service.admin_bulk_archive(
        merchant_id, user, body.order_ids, body.action
    )


@infinitemarkets_api_router.get("/merchants/{merchant_id}/orders/{order_id}")
@problem_boundary
async def get_order(
    request: Request,
    merchant_id: str,
    order_id: str,
    user: User = Depends(check_user_exists),
):
    return await order_service.order_detail(merchant_id, user, order_id)


@infinitemarkets_api_router.post(
    "/merchants/{merchant_id}/orders/{order_id}/status"
)
@problem_boundary
async def set_order_status(
    request: Request,
    merchant_id: str,
    order_id: str,
    body: OrderStatusBody,
    user: User = Depends(check_user_exists),
):
    return await order_service.admin_set_status(
        merchant_id, user, order_id, body.to_state
    )


@infinitemarkets_api_router.post(
    "/merchants/{merchant_id}/orders/{order_id}/shipping"
)
@problem_boundary
async def set_order_shipping(
    request: Request,
    merchant_id: str,
    order_id: str,
    body: OrderShippingBody,
    user: User = Depends(check_user_exists),
):
    return await order_service.admin_set_shipping(
        merchant_id, user, order_id,
        shipping_state=body.shipping_state,
        tracking=body.tracking,
        carrier=body.carrier,
        eta=body.eta,
    )


@infinitemarkets_api_router.post(
    "/merchants/{merchant_id}/orders/{order_id}/cancel"
)
@problem_boundary
async def cancel_order(
    request: Request,
    merchant_id: str,
    order_id: str,
    body: OrderCancelBody,
    user: User = Depends(check_user_exists),
):
    return await order_service.admin_cancel(
        merchant_id, user, order_id, body.reason
    )


@infinitemarkets_api_router.post(
    "/merchants/{merchant_id}/orders/{order_id}/resolve-exception"
)
@problem_boundary
async def resolve_exception(
    request: Request,
    merchant_id: str,
    order_id: str,
    body: ResolveExceptionBody,
    user: User = Depends(check_user_exists),
):
    return await order_service.admin_resolve_exception(
        merchant_id, user, order_id,
        action=body.action,
        refund_reference=body.refund_reference,
    )


@infinitemarkets_api_router.post(
    "/merchants/{merchant_id}/orders/{order_id}/public-token/reissue"
)
@problem_boundary
async def reissue_token(
    request: Request,
    merchant_id: str,
    order_id: str,
    user: User = Depends(check_user_exists),
):
    return await order_service.admin_reissue_token(
        merchant_id, user, order_id
    )


@infinitemarkets_api_router.get(
    "/merchants/{merchant_id}/orders/{order_id}/events"
)
@problem_boundary
async def get_order_events(
    request: Request,
    merchant_id: str,
    order_id: str,
    user: User = Depends(check_user_exists),
):
    return await order_service.order_events(merchant_id, user, order_id)


# --- GAM-04 message surface + rejected-intake controls -------------------------


class ComposeDmBody(_Strict):
    recipient: str  # hex or npub nostr pubkey
    content: str
    order_id: str | None = None


class ReplyDmBody(_Strict):
    content: str


@infinitemarkets_api_router.post(
    "/merchants/{merchant_id}/messages/compose"
)
@problem_boundary
async def compose_message(
    request: Request,
    merchant_id: str,
    body: ComposeDmBody,
    user: User = Depends(check_user_exists),
):
    """Merchant-authored kind-14 — dual-copy order_msg intent (D-13)."""
    from .services import order_messages as order_message_service

    order = None
    if body.order_id:
        order = await _order_row_for_user(merchant_id, user, body.order_id)
    else:
        # Ownership proof — the merchant id must belong to this user.
        await merchant_service.get_merchant_row(merchant_id, str(user.id))
    return await order_message_service.compose_dm(
        merchant_id,
        recipient_pubkey=body.recipient,
        content=body.content,
        order=order,
    )


@infinitemarkets_api_router.get(
    "/merchants/{merchant_id}/messages/conversations"
)
@problem_boundary
async def list_conversations(
    request: Request,
    merchant_id: str,
    folder: str = "customer",
    user: User = Depends(check_user_exists),
):
    """Conversation list for the Customer/Unknown folders (D-14)."""
    from .services import order_messages as order_message_service

    await merchant_service.get_merchant_row(merchant_id, str(user.id))
    return await order_message_service.list_conversations(
        merchant_id, folder
    )


@infinitemarkets_api_router.get(
    "/merchants/{merchant_id}/messages/conversations/{conversation_id:path}/delivery"
)
@problem_boundary
async def conversation_delivery(
    request: Request,
    merchant_id: str,
    conversation_id: str,
    user: User = Depends(check_user_exists),
):
    """Per-message relay_publications evidence for both delivery_copy
    classes (D-19) — recipient and sender copies labeled verbatim.
    Registered BEFORE the bare thread GET so ``:path`` does not
    swallow the delivery suffix."""
    from .services import order_messages as order_message_service

    await merchant_service.get_merchant_row(merchant_id, str(user.id))
    return await order_message_service.delivery_evidence(
        merchant_id, conversation_id
    )


@infinitemarkets_api_router.post(
    "/merchants/{merchant_id}/messages/conversations/{conversation_id:path}/read"
)
@problem_boundary
async def mark_conversation_read(
    request: Request,
    merchant_id: str,
    conversation_id: str,
    user: User = Depends(check_user_exists),
):
    """Mark the conversation's inbound rows read (D-15)."""
    from .services import order_messages as order_message_service

    await merchant_service.get_merchant_row(merchant_id, str(user.id))
    return await order_message_service.mark_read(
        merchant_id, conversation_id
    )


@infinitemarkets_api_router.get(
    "/merchants/{merchant_id}/messages/conversations/{conversation_id:path}"
)
@problem_boundary
async def get_conversation(
    request: Request,
    merchant_id: str,
    conversation_id: str,
    user: User = Depends(check_user_exists),
):
    """One decrypted thread — owner-side decrypt only (T-303)."""
    from .services import order_messages as order_message_service

    await merchant_service.get_merchant_row(merchant_id, str(user.id))
    return await order_message_service.get_thread(
        merchant_id, conversation_id
    )


@infinitemarkets_api_router.get(
    "/merchants/{merchant_id}/orders/{order_id}/messages"
)
@problem_boundary
async def order_messages_thread(
    request: Request,
    merchant_id: str,
    order_id: str,
    user: User = Depends(check_user_exists),
):
    """The order's embedded message thread for the order detail pane
    (D-12)."""
    from .services import order_messages as order_message_service

    await merchant_service.get_merchant_row(merchant_id, str(user.id))
    return await order_message_service.order_thread(
        merchant_id, order_id
    )


@infinitemarkets_api_router.get(
    "/merchants/{merchant_id}/messages/health"
)
@problem_boundary
async def messages_health(
    request: Request,
    merchant_id: str,
    user: User = Depends(check_user_exists),
):
    """Connectivity health strip (D-20): inbox listener state, per-relay
    connectivity + auth state, and the outbox backlog — evidence-based
    (durable states only, never intent-only claims)."""
    from .services import metrics
    from .services import relay as relay_service

    merchant = await merchant_service.get_merchant_row(
        merchant_id, str(user.id)
    )
    health = await relay_service.relay_health(merchant_id)
    depth = await metrics.outbox_depth()
    return {
        "inbox_state": merchant.get("inbox_state") or "off",
        "outbox_pending": depth.get("pending", 0),
        "outbox_failed": depth.get("failed_total", 0),
        "relays": [
            {
                "relay_url": r["relay_url"],
                "direction": r["direction"],
                "connected": r["connected"],
                "auth_state": r["auth_state"],
            }
            for r in health["relays"]
        ],
    }


@infinitemarkets_api_router.get(
    "/merchants/{merchant_id}/messages/unread-count"
)
@problem_boundary
async def messages_unread_count(
    request: Request,
    merchant_id: str,
    user: User = Depends(check_user_exists),
):
    """Unread inbound conversations per folder — nav badge source."""
    from .services import order_messages as order_message_service

    await merchant_service.get_merchant_row(merchant_id, str(user.id))
    return await order_message_service.unread_count(merchant_id)


@infinitemarkets_api_router.post(
    "/merchants/{merchant_id}/messages/conversations/{conversation_id}/reply"
)
@problem_boundary
async def reply_message(
    request: Request,
    merchant_id: str,
    conversation_id: str,
    body: ReplyDmBody,
    user: User = Depends(check_user_exists),
):
    """Reply inside an order:/unknown: conversation (D-13/D-14)."""
    from .services import order_messages as order_message_service

    await merchant_service.get_merchant_row(merchant_id, str(user.id))
    return await order_message_service.reply_dm(
        merchant_id,
        conversation_id=conversation_id,
        content=body.content,
    )


async def _order_row_for_user(merchant_id: str, user, order_id: str) -> dict:
    """The raw orders row for an owner-verified order (order_detail
    proves ownership but returns the public projection)."""
    from .db import db, table
    from .security import not_found

    async with db.connect() as conn:
        row = await conn.fetchone(
            f"SELECT o.* FROM {table('orders')} o"
            f" JOIN {table('merchants')} m ON m.id = o.merchant_id"
            " WHERE o.id = :o AND o.merchant_id = :m AND m.user_id = :u",
            {"o": order_id, "m": merchant_id, "u": str(user.id)},
        )
    if row is None:
        raise not_found("order not found")
    return dict(row)


@infinitemarkets_api_router.get(
    "/merchants/{merchant_id}/rejected-intake"
)
@problem_boundary
async def rejected_intake(
    request: Request,
    merchant_id: str,
    user: User = Depends(check_user_exists),
):
    """Merchant-visible rejected/quarantined intake with reasons + the
    author npub for mute decisions (D-21)."""
    await merchant_service.get_merchant_row(merchant_id, str(user.id))
    return await _list_rejected_intake(merchant_id, user)


@infinitemarkets_api_router.post(
    "/merchants/{merchant_id}/rejected-intake/{inbox_event_id}/mute"
)
@problem_boundary
async def mute_rejected_intake(
    request: Request,
    merchant_id: str,
    inbox_event_id: str,
    user: User = Depends(check_user_exists),
):
    """Mute the rumor author behind a rejected intake row — subsequent
    wraps drop before domain dispatch (D-23)."""
    await merchant_service.get_merchant_row(merchant_id, str(user.id))
    return await _mute_inbox_author(merchant_id, inbox_event_id)


async def _list_rejected_intake(merchant_id: str, user) -> dict:
    from . import crypto
    from .db import db, table
    from .settings import ext_settings

    settings = ext_settings()
    async with db.connect() as conn:
        rows = await conn.fetchall(
            f"SELECT id, outer_event_id, kind, processed_state,"
            " reject_reason, author_hash, author_enc, received_at,"
            " processed_at, source_relay_url"
            f" FROM {table('inbox_events')}"
            " WHERE merchant_id = :m"
            " AND processed_state IN ('rejected', 'quarantined')"
            " ORDER BY processed_at DESC LIMIT 100",
            {"m": merchant_id},
        )
        muted_rows = await conn.fetchall(
            f"SELECT author_hash FROM {table('inbox_blocklist')}"
            " WHERE merchant_id = :m",
            {"m": merchant_id},
        )
    muted_hashes = {r["author_hash"] for r in muted_rows}
    entries = []
    for row in rows:
        author_npub = None
        if row["author_enc"] is not None:
            try:
                ver = crypto.envelope_version(row["author_enc"])
                author_hex = crypto.decrypt(
                    row["author_enc"], settings.master_keys[ver],
                    record_id=row["id"], table="inbox_events",
                    column="author_enc", key_version=ver,
                ).decode()
                from nostr_sdk import PublicKey

                author_npub = (
                    PublicKey.parse(author_hex).to_bech32()
                )
            except Exception:  # noqa: BLE001 — display-only decrypt
                author_npub = None
        entries.append(
            {
                "id": row["id"],
                "outer_event_id": row["outer_event_id"],
                "kind": row["kind"],
                "processed_state": row["processed_state"],
                "reject_reason": row["reject_reason"],
                "author_npub": author_npub,
                "muted": (
                    row["author_hash"] is not None
                    and row["author_hash"] in muted_hashes
                ),
                "source_relay": row["source_relay_url"],
                "received_at": row["received_at"],
                "processed_at": row["processed_at"],
            }
        )
    return {"entries": entries}


async def _mute_inbox_author(merchant_id: str, inbox_event_id: str) -> dict:
    import time as _time
    import uuid as _uuid

    from . import crypto
    from .db import DomainTransaction, db, table
    from .security import not_found
    from .settings import ext_settings

    settings = ext_settings()
    async with db.connect() as conn:
        row = await conn.fetchone(
            f"SELECT id, author_hash, author_enc, processed_state"
            f" FROM {table('inbox_events')}"
            " WHERE merchant_id = :m AND id = :i",
            {"m": merchant_id, "i": inbox_event_id},
        )
    if row is None or row["author_hash"] is None:
        raise not_found("no mutable author on that intake row")
    async with DomainTransaction() as tx:
        await tx.execute(
            f"INSERT INTO {tx.table('inbox_blocklist')} "
            "(id, merchant_id, author_hash, created_at) "
            "VALUES (:i, :m, :h, :t) ON CONFLICT DO NOTHING",
            {
                "i": _uuid.uuid4().hex,
                "m": merchant_id,
                "h": row["author_hash"],
                "t": int(_time.time()),
            },
        )
    author_npub = None
    if row["author_enc"] is not None:
        try:
            ver = crypto.envelope_version(row["author_enc"])
            author_hex = crypto.decrypt(
                row["author_enc"], settings.master_keys[ver],
                record_id=row["id"], table="inbox_events",
                column="author_enc", key_version=ver,
            ).decode()
            from nostr_sdk import PublicKey

            author_npub = PublicKey.parse(author_hex).to_bech32()
        except Exception:  # noqa: BLE001
            author_npub = None
    return {"muted": True, "author_npub": author_npub}
