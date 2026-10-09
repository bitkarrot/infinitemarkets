"""P0-14 contract-closure registry — declarative, literal, complete.

Every literal below is transcribed from docs/technical-specification.md and
diffed BOTH directions by the P0-14 gate:

- spec <-> registry (route tables, state machines, error codes, task names,
  settings, identifiers, NIP-32 namespace);
- registry <-> harness/schema.py + harness/state.py (fields, states,
  transitions the executable models implement);
- registry <-> tests/fixtures/golden/ (fixture coverage per event kind);
- release gates (section 18) scoping every event kind.

Section 4 modeled-table scope is declared explicitly in
``TABLE_CLASSIFICATION``: every section-4 table is classified as
``"modeled"`` (the Phase-1 executable models exercise it), ``"fk-subset"``
(present only as a minimal FK-supporting subset), or ``"not-modeled"``
(production-runtime table outside the executable models' needs). A section-4
table missing from the classification is a registry bug — the closure gate
fails on it.
"""

from __future__ import annotations

# --- Frozen identifiers (section 21.25) ---------------------------------------

PACKAGE_NAME = "infinitemarkets"
ROUTE_PREFIX = "/infinitemarkets"
API_BASE = "/infinitemarkets/api/v1"
HOOK_START = "infinitemarkets_start"
HOOK_STOP = "infinitemarkets_stop"
ENV_PREFIX = "INFINITEMARKETS_"
PAYMENT_CORRELATION_PREFIX = "infinitemarkets:"
AAD_PREFIX = "infinitemarkets"

FROZEN_IDENTIFIERS = frozenset(
    {
        PACKAGE_NAME,
        ROUTE_PREFIX,
        API_BASE,
        HOOK_START,
        HOOK_STOP,
        ENV_PREFIX,
        PAYMENT_CORRELATION_PREFIX,
        AAD_PREFIX,
    }
)

#: Section 6.8: Phase-0-selected NIP-32 reverse-domain namespace (pinned in
#: PINS.md).
NIP32_NAMESPACE = "org.infinitemarkets.protocol"

# --- Section 7 state machines (literal) ----------------------------------------

ORDER_STATES = (
    "received",
    "invoice_pending",
    "awaiting_payment",
    "confirmed",
    "processing",
    "completed",
    "rejected",
    "expired",
    "cancelled",
)

ORDER_TRANSITIONS: dict[str, frozenset[str]] = {
    "received": frozenset({"rejected", "invoice_pending", "cancelled"}),
    "invoice_pending": frozenset({"awaiting_payment", "rejected", "cancelled"}),
    "awaiting_payment": frozenset({"confirmed", "expired", "cancelled"}),
    "confirmed": frozenset({"processing", "cancelled"}),
    "processing": frozenset({"completed", "cancelled"}),
    "expired": frozenset({"confirmed"}),
    "cancelled": frozenset({"confirmed"}),
    "completed": frozenset(),
    "rejected": frozenset(),
}

ORDER_TERMINAL_STATES = ("completed", "rejected")
BUYER_CANCELLABLE_STATES = ("received", "invoice_pending", "awaiting_payment")
REASON_REQUIRED_TRANSITIONS = frozenset(
    {
        ("confirmed", "cancelled"),
        ("expired", "confirmed"),
        ("cancelled", "confirmed"),
    }
)

SHIPPING_STATES = (
    "not_required",
    "pending",
    "processing",
    "shipped",
    "delivered",
    "exception",
)

SHIPPING_TRANSITIONS: dict[str, frozenset[str]] = {
    "not_required": frozenset({"pending"}),
    "pending": frozenset({"processing"}),
    "processing": frozenset({"shipped", "exception"}),
    "shipped": frozenset({"delivered", "exception"}),
    "exception": frozenset({"processing", "shipped"}),
    "delivered": frozenset(),
}

RESERVATION_STATES = ("held", "consumed", "released", "expired")

RESERVATION_TRANSITIONS: dict[str, frozenset[str]] = {
    "held": frozenset({"consumed", "released", "expired"}),
    "consumed": frozenset(),
    "released": frozenset(),
    "expired": frozenset(),
}

OUTBOX_STATES = (
    "pending",
    "claimed",
    "publishing",
    "partially_published",
    "published",
    "superseded",
    "failed",
)

OUTBOX_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"claimed", "superseded"}),
    "partially_published": frozenset({"claimed", "superseded"}),
    # Section 7.4: rows in pending|claimed|publishing|partially_published|
    # failed may all become superseded; a stale claim returns to pending or
    # partially_published via the fencing-token compare-and-swap.
    "claimed": frozenset(
        {"publishing", "pending", "partially_published", "superseded"}
    ),
    "publishing": frozenset(
        {"published", "pending", "partially_published", "failed", "superseded"}
    ),
    "published": frozenset(),
    "superseded": frozenset(),
    "failed": frozenset({"superseded"}),
}

OUTBOX_SUPERSEDABLE_STATES = (
    "pending",
    "claimed",
    "publishing",
    "partially_published",
    "failed",
)
OUTBOX_NON_SUPERSEDABLE_AGGREGATES = ("order_msg",)

INBOX_STATES = (
    "received",
    "validated",
    "processed",
    "rejected",
    "quarantined",
)

INBOX_TRANSITIONS: dict[str, frozenset[str]] = {
    "received": frozenset({"validated", "rejected", "quarantined"}),
    "validated": frozenset({"processed"}),
    "processed": frozenset(),
    "rejected": frozenset(),
    "quarantined": frozenset(),
}

#: All section-7 machines: (states, transitions) per machine name.
STATE_MACHINES: dict[str, tuple[tuple[str, ...], dict[str, frozenset[str]]]] = {
    "order": (ORDER_STATES, ORDER_TRANSITIONS),
    "shipping": (SHIPPING_STATES, SHIPPING_TRANSITIONS),
    "reservation": (RESERVATION_STATES, RESERVATION_TRANSITIONS),
    "outbox": (OUTBOX_STATES, OUTBOX_TRANSITIONS),
    "inbox": (INBOX_STATES, INBOX_TRANSITIONS),
}

# --- Section 5 HTTP routes (literal; relative to API_BASE/public pages) --------

HTTP_ROUTES: tuple[str, ...] = (
    # 5.1 admin — merchant
    "POST /merchants",
    "GET /merchants/current",
    "PATCH /merchants/{id}",
    "POST /merchants/{id}/keys/import",
    "POST /merchants/{id}/publish",
    "GET /merchants/{id}/relay-health",
    "GET /merchants/{id}/notifications",
    "PATCH /merchants/{id}/notifications",
    "POST /merchants/{id}/notifications/test",
    "DELETE /merchants/{id}",
    # 5.2 admin — catalog
    "GET /categories",
    "POST /categories",
    "GET /categories/{id}",
    "PATCH /categories/{id}",
    "DELETE /categories/{id}",
    "GET /products",
    "POST /products",
    "POST /products/bulk",
    "GET /products/{id}",
    "PATCH /products/{id}",
    "DELETE /products/{id}",
    "POST /products/{id}/images",
    "GET /collections",
    "POST /collections",
    "PATCH /collections/{id}",
    "DELETE /collections/{id}",
    "GET /collections/{id}",
    "GET /shipping",
    "POST /shipping",
    "PATCH /shipping/{id}",
    "DELETE /shipping/{id}",
    "GET /shipping/{id}",
    "GET /products/{id}/events",
    # 5.3 admin — orders
    # GET /orders is dual use: the admin list route AND the §5.4 signed-in
    # buyer order-history page declare the same string — one row covers both.
    "GET /orders",
    "POST /orders/bulk",
    "GET /orders/{id}",
    "POST /orders/{id}/status",
    "POST /orders/{id}/shipping",
    "POST /orders/{id}/cancel",
    "POST /orders/{id}/resolve-exception",
    "POST /orders/{id}/public-token/reissue",
    "GET /orders/{id}/events",
    # 5.4 public — catalog and checkout
    "GET /public/merchants/{pubkey}",
    "GET /public/products/{merchant_pubkey}/{d_tag}",
    "GET /public/collections/{merchant_pubkey}/{d_tag}",
    "GET /public/shipping/{merchant_pubkey}/{d_tag}",
    "POST /public/checkout",
    "GET /public/order-status",
    "POST /public/order-email-opt-out",
    "GET /p/{naddr}",
    "GET /p/{merchant_pubkey}/{d_tag}",
    "GET /order",
    # 5.4 public — buyer sign-in + identity linking (03-03/03.1-02)
    # GET /profile + /public/nostr/profile* were spec-declared in 03-03
    # without registry rows — drift reconciled here.
    "GET /profile",
    "GET /public/nostr/profile",
    "POST /public/nostr/profile",
    "GET /signin",
    "GET /auth/email",
    "POST /public/nostr/email/request",
    "POST /public/nostr/email/verify",
    "POST /public/nostr/link/email",
    "GET /public/nostr/link/challenge",
    "POST /public/nostr/link/verify",
    # 5.5 migration
    "POST /import/nostrmarket/preview",
    "POST /import/nostrmarket/execute",
    "GET /import/{job_id}",
    "POST /import/{job_id}/cutover",
)

# --- Section 5.6 error codes ----------------------------------------------------

ERROR_CODES = frozenset(
    {
        "insufficient-stock",
        "invalid-transition",
        "duplicate-order",
        "wallet-mismatch",
        "product-inactive",
        "rate-limited",
        "invalid-shipping-destination",
        "order-expired",
        "unauthorized",
    }
)

# --- Section 10 task names -------------------------------------------------------

#: Permanent tasks registered as ``infinitemarkets.<task>`` (section 10 table).
TASK_NAMES = frozenset(
    {
        "infinitemarkets.relay_manager",
        "infinitemarkets.inbox_processor",
        "infinitemarkets.outbox_publisher",
        "infinitemarkets.email_sender",
        "infinitemarkets.reservation_expiry",
        "infinitemarkets.reconciliation",
        "infinitemarkets.retention_pruner",
        # Invoice callback: registered on every worker (no lease); the host
        # names it "<name>_invoice_listener" (verified P0-03).
        "infinitemarkets_invoice_listener",
    }
)

# --- Section 12 settings/env vars --------------------------------------------------

SETTINGS = frozenset(
    {
        "INFINITEMARKETS_MASTER_KEYS",
        "INFINITEMARKETS_ACTIVE_KEY_VERSION",
        "INFINITEMARKETS_PUBLIC_BASE_URL",
        "INFINITEMARKETS_PRIVACY_KEY",
        "RESERVATION_TTL",
        "OUTBOX_MAX_ATTEMPTS",
        "OUTBOX_BATCH",
        "PEER_RELAY_TTL",
        "INBOX_MAX_EVENT_BYTES",
        "CHECKOUT_RATE_LIMIT",
        "INFINITEMARKETS_EMAIL_ENABLED",
        "EMAIL_MAX_ATTEMPTS",
        "SPEC_REVISION",
    }
)

# --- Section 6 event kinds + Phase-1 fixture coverage -----------------------------

#: kind -> {"fixture": path fragment under tests/fixtures/golden/ or None,
#:          "phase1_required": bool}
EVENT_KINDS: dict[int, dict] = {
    0: {"fixture": None, "phase1_required": False},  # merchant profile
    5: {"fixture": None, "phase1_required": False},  # deletion tombstone
    13: {"fixture": "nip17/recipient/seal.json", "phase1_required": True},
    14: {"fixture": "nip17/rumor_kind14.json", "phase1_required": True},
    16: {"fixture": "nip17/rumor.json", "phase1_required": True},
    17: {"fixture": "nip17/rumor_kind17.json", "phase1_required": True},
    1059: {"fixture": "nip17/recipient/wrap.json", "phase1_required": True},
    31989: {
        "fixture": "nip89/recommendation_31989.json",
        "phase1_required": True,
    },
    31990: {"fixture": "nip89/handler_31990.json", "phase1_required": True},
    30402: {"fixture": "nip89/naddr.txt", "phase1_required": True},
    30017: {"fixture": "nip15/stall_30017.json", "phase1_required": True},
    30018: {"fixture": "nip15/product_30018.json", "phase1_required": True},
    30405: {"fixture": None, "phase1_required": False},  # collection
    30406: {"fixture": None, "phase1_required": False},  # shipping option
    4: {"fixture": None, "phase1_required": False},  # NIP-04 legacy DM
    10050: {"fixture": None, "phase1_required": False},  # inbox relay list
    # Deferred/spec-mentioned but out of the Phase-1 executable scope:
    10013: {"fixture": None, "phase1_required": False},  # drafts (deferred, §6.7)
    30403: {"fixture": None, "phase1_required": False},  # draft product (§6.7)
}

# --- Section 18 release gates -------------------------------------------------------

#: Release name -> event-kind scope the release may claim (section 18).
RELEASE_GATES: dict[str, frozenset[int]] = {
    # Release A: Gamma/NIP-99 catalog + web checkout. EXCLUDES NIP-17/NIP-04
    # and MUST NOT claim Gamma order-protocol support.
    "A": frozenset({0, 5, 30402, 30405, 30406, 31989, 31990}),
    # Release B: full Gamma merchant — kind-10050, NIP-17 sender+receiver
    # copies, type 1-4 messages, kind-17 receipts.
    "B": frozenset({13, 14, 16, 17, 1059, 10050}),
    # Release C: interop — NIP-15 30017/30018 + NIP-04 order channel.
    "C": frozenset({4, 30017, 30018}),
}

#: Kinds Release A must NOT carry (NIP-17/NIP-04-only protocol surface).
RELEASE_A_EXCLUDED_KINDS = frozenset({4, 13, 14, 16, 17, 1059, 10050})

# --- Section 4 modeled-table classification -----------------------------------------

TABLE_MODELED = "modeled"
TABLE_FK_SUBSET = "fk-subset"
TABLE_NOT_MODELED = "not-modeled"

#: Every section-4 table classified. A missing entry is a registry bug.
TABLE_CLASSIFICATION: dict[str, str] = {
    # 4.1-4.3
    "merchants": TABLE_NOT_MODELED,
    "categories": TABLE_NOT_MODELED,
    "products": TABLE_MODELED,
    # 4.4 product detail tables
    "product_images": TABLE_NOT_MODELED,
    "product_specs": TABLE_NOT_MODELED,
    "product_categories": TABLE_NOT_MODELED,
    "product_collections": TABLE_NOT_MODELED,
    "product_shipping_options": TABLE_NOT_MODELED,
    "product_shipping_collections": TABLE_NOT_MODELED,
    # 4.5-4.6
    "collections": TABLE_NOT_MODELED,
    "collection_shipping": TABLE_NOT_MODELED,
    "shipping_options": TABLE_NOT_MODELED,
    # 4.7 orders cluster
    "orders": TABLE_MODELED,
    "order_items": TABLE_MODELED,
    "order_events": TABLE_MODELED,
    "order_fx_quotes": TABLE_MODELED,
    "order_fulfillment": TABLE_NOT_MODELED,
    "order_messages": TABLE_NOT_MODELED,
    # 4.8-4.10
    "payments": TABLE_MODELED,
    "inbox_events": TABLE_MODELED,
    "outbox_events": TABLE_MODELED,
    "outbox_dependencies": TABLE_MODELED,
    "relay_publications": TABLE_MODELED,
    # 4.11
    "relay_configs": TABLE_NOT_MODELED,
    "peer_relays": TABLE_NOT_MODELED,
    "counterparty_profiles": TABLE_NOT_MODELED,
    "relay_cursors": TABLE_MODELED,
    # 4.12-4.18
    "inventory_reservations": TABLE_MODELED,
    "protocol_addresses": TABLE_NOT_MODELED,
    "merchant_keys": TABLE_NOT_MODELED,
    "idempotency_records": TABLE_MODELED,
    "task_leases": TABLE_MODELED,
    "rate_limit_buckets": TABLE_MODELED,
    "settings": TABLE_NOT_MODELED,
    "migration_jobs": TABLE_NOT_MODELED,
    "email_queue": TABLE_MODELED,
    # Buyer-session tables (plan 03-03, D-01 — not spec §4 literals)
    "nostr_challenges": TABLE_NOT_MODELED,
    "buyer_sessions": TABLE_NOT_MODELED,
    # Buyer-account tables (plan 03.1, §4.23)
    "buyer_accounts": TABLE_NOT_MODELED,
    "email_signin_tokens": TABLE_NOT_MODELED,
    "inbox_blocklist": TABLE_NOT_MODELED,
}

# --- Section 4 modeled-table field sets -------------------------------------------
#
# The fields the Phase-1 executable models implement per modeled table.
# ``order_fx_quotes`` additionally carries ``providers``/``expires_at``
# required by section 3.4's persistence rule (provider names, observed/
# expiry timestamps) beyond the section-4.7 summary parenthetical.

SCHEMA_FIELDS: dict[str, frozenset[str]] = {
    "products": frozenset(
        {
            "id",
            "merchant_id",
            "title",
            "stock_on_hand",
            "stock_reserved",
            "revision",
            "deleted_at",
            "created_at",
            "updated_at",
        }
    ),
    "orders": frozenset(
        {
            "id",
            "merchant_id",
            "protocol",
            "state",
            "buyer_pubkey_hash",
            "external_id_hash",
            "request_hash",
            "subtotal_sat",
            "shipping_sat",
            "total_sat",
            "buyer_amount_sat",
            "payment_exception",
            "payment_exception_reason",
            "payment_exception_resolution",
            "public_token_hash",
            "public_token_enc",
            "public_token_expires_at",
            "email_opt_in",
            "created_at",
            "updated_at",
        }
    ),
    "order_items": frozenset(
        {
            "id",
            "order_id",
            "product_id",
            "product_d",
            "title",
            "quantity",
            "unit_price_minor",
            "currency",
            "currency_decimals",
            "line_total_sat",
        }
    ),
    "order_events": frozenset(
        {
            "id",
            "order_id",
            "from_state",
            "to_state",
            "actor",
            "detail_json",
            "created_at",
        }
    ),
    "order_fx_quotes": frozenset(
        {
            "order_id",
            "currency",
            "rate_decimal",
            "rate_direction",
            "rate_unit",
            "source",
            "providers",
            "quoted_at",
            "expires_at",
        }
    ),
    "payments": frozenset(
        {
            "id",
            "order_id",
            "core_external_id",
            "payment_hash",
            "checking_id_enc",
            "bolt11_enc",
            "wallet_refs_enc",
            "wallet_id_hash",
            "source_wallet_id_hash",
            "amount_sat",
            "status",
            "settled_at",
            "created_at",
        }
    ),
    "inbox_events": frozenset(
        {
            "id",
            "outer_event_id",
            "rumor_id",
            "merchant_id",
            "source_relay_url",
            "received_at",
            "kind",
            "author_hash",
            "author_enc",
            "processed_state",
            "reject_reason",
            "raw_json",
            "processed_at",
        }
    ),
    "outbox_events": frozenset(
        {
            "id",
            "merchant_id",
            "aggregate_type",
            "aggregate_id",
            "aggregate_revision",
            "event_kind",
            "event_address",
            "payload_json",
            "payload_enc",
            "state",
            "attempts",
            "next_attempt_at",
            "claimed_by",
            "claimed_at",
            "claimed_until",
            "claim_token",
            "last_error",
            "created_at",
            "updated_at",
        }
    ),
    "outbox_dependencies": frozenset(
        {"outbox_event_id", "depends_on_outbox_event_id"}
    ),
    "relay_publications": frozenset(
        {
            "id",
            "outbox_event_id",
            "delivery_copy",
            "relay_url",
            "event_id",
            "attempt_no",
            "result",
            "message",
            "attempted_at",
        }
    ),
    "relay_cursors": frozenset(
        {
            "id",
            "merchant_id",
            "relay_url",
            "protocol",
            "last_completed_session_start",
            "eose_session_id",
            "eose_at",
            "updated_at",
        }
    ),
    "inventory_reservations": frozenset(
        {
            "id",
            "product_id",
            "order_id",
            "quantity",
            "state",
            "expires_at",
            "created_at",
            "updated_at",
        }
    ),
    "task_leases": frozenset(
        {"name", "holder_id", "fencing_token", "leased_until", "updated_at"}
    ),
    "rate_limit_buckets": frozenset(
        {"scope_hash", "bucket", "window_start", "count", "expires_at"}
    ),
    "idempotency_records": frozenset(
        {
            "scope_hash",
            "request_hash",
            "state",
            "order_id",
            "owner_id",
            "lease_until",
            "status_code",
            "response_enc",
            "created_at",
            "expires_at",
        }
    ),
    "email_queue": frozenset(
        {
            "id",
            "merchant_id",
            "order_id",
            "channel",
            "event_type",
            "recipient_enc",
            "recipient_hash",
            "state",
            "attempts",
            "next_attempt_at",
            "claimed_by",
            "claimed_at",
            "claimed_until",
            "claim_token",
            "last_error",
            "created_at",
            "sent_at",
        }
    ),
}
