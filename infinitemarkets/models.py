"""Pydantic models for the m001 tables (host ``insert``/``update`` helpers).

The host's ``insert``/``update`` build statements from ``model_to_dict`` —
models here carry exactly the columns written through those helpers. Raw
``execute`` is reserved for DDL and for queries whose parameters contain no
markdown/JSON payloads (``rewrite_values`` HTML-strips strings — Pitfall 3).
"""

from __future__ import annotations

from pydantic import BaseModel


class Merchant(BaseModel):
    id: str
    user_id: str
    pubkey: str
    key_ref: str
    display_name: str | None = None
    profile_json: str | None = None
    payment_preference: str = "manual"
    recommended_app_d: str | None = None
    wallet_id_enc: bytes
    wallet_id_hash: str
    notify_emails: str | None = None
    notify_events: str | None = None
    theme: str | None = None
    state: str = "draft"
    inbox_state: str = "off"
    created_at: int = 0
    updated_at: int = 0


class MerchantKey(BaseModel):
    merchant_id: str
    key_origin: str
    key_version: str
    nonce: bytes
    ciphertext: bytes
    created_at: int = 0
    rotated_at: int | None = None


class MerchantSetting(BaseModel):
    merchant_id: str
    key: str
    value: str | None = None


class Category(BaseModel):
    id: str
    merchant_id: str
    name: str | None = None
    description: str | None = None
    default_currency: str | None = None
    default_location: str | None = None
    nip15_stall_d: str | None = None
    publish_gamma: bool = True
    publish_nip15: bool = False
    deleted_at: int | None = None
    created_at: int = 0
    updated_at: int = 0


class Product(BaseModel):
    id: str
    merchant_id: str
    category_id: str
    d_tag: str
    parent_product_id: str | None = None
    product_type: str
    format: str
    title: str | None = None
    summary: str | None = None
    description_md: str | None = None
    amount_minor: int | None = None
    currency: str | None = None
    currency_decimals: int | None = None
    recurring_frequency: str | None = None
    visibility: str = "hidden"
    nip99_status: str = "active"
    draft: bool = False
    stock_on_hand: int | None = None
    stock_reserved: int = 0
    location: str | None = None
    geohash: str | None = None
    weight_value: float | None = None
    weight_unit: str | None = None
    dim_l: float | None = None
    dim_w: float | None = None
    dim_h: float | None = None
    dim_unit: str | None = None
    nip15_product_id: str | None = None
    published_at: int | None = None
    revision: int = 0
    deleted_at: int | None = None
    created_at: int = 0
    updated_at: int = 0


class ProductImage(BaseModel):
    id: str
    product_id: str
    url: str
    dimensions: str | None = None
    sort_order: int = 0


class ProductSpec(BaseModel):
    id: str
    product_id: str
    key: str
    value: str


class ProductCategory(BaseModel):
    id: str
    product_id: str
    category: str


class ProductCollection(BaseModel):
    id: str
    product_id: str
    collection_id: str


class ProductShippingOption(BaseModel):
    id: str
    product_id: str
    shipping_option_id: str
    extra_cost_minor: int | None = None


class ProductShippingCollection(BaseModel):
    id: str
    product_id: str
    collection_id: str
    extra_cost_minor: int | None = None


class Collection(BaseModel):
    id: str
    merchant_id: str
    d_tag: str
    title: str | None = None
    description: str | None = None
    image: str | None = None
    location: str | None = None
    geohash: str | None = None
    revision: int = 0
    deleted_at: int | None = None
    created_at: int = 0
    updated_at: int = 0


class CollectionShipping(BaseModel):
    id: str
    collection_id: str
    shipping_option_id: str


class ShippingOption(BaseModel):
    id: str
    merchant_id: str
    d_tag: str
    title: str | None = None
    description: str | None = None
    base_price_minor: int | None = None
    currency: str | None = None
    currency_decimals: int = 2
    service: str
    carrier: str | None = None
    countries: str | None = None
    regions: str | None = None
    duration_min: int | None = None
    duration_max: int | None = None
    duration_unit: str | None = None
    weight_min: float | None = None
    weight_max: float | None = None
    weight_unit: str | None = None
    dim_min_l: float | None = None
    dim_min_w: float | None = None
    dim_min_h: float | None = None
    dim_max_l: float | None = None
    dim_max_w: float | None = None
    dim_max_h: float | None = None
    dim_unit: str | None = None
    price_weight_minor: int | None = None
    price_weight_unit: str | None = None
    price_volume_minor: int | None = None
    price_volume_unit: str | None = None
    location: str | None = None
    geohash: str | None = None
    active: bool = True
    revision: int = 0
    deleted_at: int | None = None
    created_at: int = 0
    updated_at: int = 0


class ProtocolAddress(BaseModel):
    id: str
    domain_type: str
    domain_id: str
    protocol: str
    event_kind: int
    author_pubkey: str
    d_tag: str = ""
    latest_event_id: str | None = None
    latest_created_at: int | None = None


class RelayConfig(BaseModel):
    id: str
    merchant_id: str | None = None
    relay_url: str
    direction: str
    enabled: bool = True
    auth_state: str | None = None
    auth_note: str | None = None
    paid_invoice: str | None = None
    auth_updated_at: int | None = None
    created_at: int = 0
    updated_at: int = 0


class PeerRelay(BaseModel):
    id: str
    merchant_id: str
    pubkey_hash: str
    pubkey_enc: bytes | None = None
    relay_url: str
    fetched_at: int | None = None
    expires_at: int | None = None


class RelayCursor(BaseModel):
    id: str
    merchant_id: str
    relay_url: str
    protocol: str
    last_completed_session_start: int | None = None
    eose_session_id: str | None = None
    eose_at: int | None = None
    updated_at: int | None = None


class InboxBlocklist(BaseModel):
    id: str
    merchant_id: str
    author_hash: str
    reason: str | None = None
    created_at: int | None = None


class OutboxEvent(BaseModel):
    id: str
    merchant_id: str
    aggregate_type: str
    aggregate_id: str
    aggregate_revision: int = 0
    event_kind: int
    event_address: str | None = None
    payload_json: str | None = None
    payload_enc: bytes | None = None
    state: str = "pending"
    attempts: int = 0
    next_attempt_at: int = 0
    claimed_by: str | None = None
    claimed_at: int | None = None
    claimed_until: int | None = None
    claim_token: int = 0
    last_error: str | None = None
    created_at: int = 0
    updated_at: int = 0


class OutboxDependency(BaseModel):
    outbox_event_id: str
    depends_on_outbox_event_id: str


class RelayPublication(BaseModel):
    id: str
    outbox_event_id: str
    delivery_copy: str
    relay_url: str
    event_id: str
    attempt_no: int
    result: str
    message: str | None = None
    attempted_at: int = 0


class TaskLease(BaseModel):
    name: str
    holder_id: str | None = None
    fencing_token: int = 0
    leased_until: int = 0
    updated_at: int = 0


class RateLimitBucket(BaseModel):
    scope_hash: str
    bucket: str
    window_start: int
    count: int = 0
    expires_at: int
