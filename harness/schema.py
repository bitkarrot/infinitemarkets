"""Normative schema subset for the executable state/transaction models.

The full subset the plan 01-02 models need, per spec section 4, for these
tables: ``products``, ``orders``, ``order_items``, ``order_events``,
``order_fx_quotes``, ``payments``, ``inbox_events``, ``outbox_events``,
``outbox_dependencies``, ``relay_publications``, ``relay_cursors``,
``inventory_reservations``, ``task_leases``, ``rate_limit_buckets``,
``idempotency_records``, ``email_queue``.

Column names/types are kept literal against the specification so plan 01-03's
P0-14 closure gate can diff this DDL against the spec registry. Only columns
the executable models exercise are included; tables outside the model subset
(``merchants``, ``categories`` ...) are referenced by plain TEXT columns without
FKs, mirroring the tracer's convention.

Dialect notes (verified against the pinned stack):

- SQLite: tables and FK references are unqualified. SQLite rejects
  schema-qualified ``REFERENCES schema.table(id)`` (parse error), and the
  harness SQLite database is a plain (non-``ext_``) host database.
- PostgreSQL: tables and FK references are schema-qualified; PostgreSQL
  resolves FK targets via search_path, not the referencing table's schema.
- Timestamps are stored as BIGINT unix epochs: dialect-appropriate 64-bit
  integers avoid the deprecated sqlite3 datetime adapters and asyncpg
  timezone pitfalls while staying orderable in SQL.
- ``BOOLEAN`` columns are declared BOOLEAN on both dialects (SQLite gives
  them NUMERIC affinity and stores 0/1; readers must normalize with
  ``bool(value)`` for cross-dialect comparisons).
"""

from __future__ import annotations

# Tables in creation order (FK targets first). Plan 01-03's P0-14 closure
# gate diffs this list (and the column DDL below) against the spec registry.
MODEL_TABLES = (
    "products",
    "orders",
    "order_items",
    "order_events",
    "order_fx_quotes",
    "payments",
    "inbox_events",
    "outbox_events",
    "outbox_dependencies",
    "relay_publications",
    "relay_cursors",
    "inventory_reservations",
    "task_leases",
    "rate_limit_buckets",
    "idempotency_records",
    "email_queue",
)


def ddl(dialect: str, schema: str | None) -> list[str]:
    """DDL statements for the normative model subset.

    ``dialect`` is ``"sqlite"`` or ``"postgres"``; ``schema`` is the
    PostgreSQL schema name (None on SQLite).
    """

    def t(table: str) -> str:
        return f"{schema}.{table}" if schema else table

    # FK targets must match the table qualification rules described above.
    def fk(table: str) -> str:
        return f"{schema}.{table}" if schema else table

    pg = dialect == "postgres"
    int_type = "BIGINT" if pg else "INTEGER"
    ts_type = "BIGINT" if pg else "INTEGER"
    blob_type = "BYTEA" if pg else "BLOB"

    return [
        # --- section 4.3 (columns the inventory/reservation models need) ---
        f"""
        CREATE TABLE {t("products")} (
            id TEXT PRIMARY KEY,
            merchant_id TEXT NOT NULL,
            title TEXT,
            stock_on_hand {int_type},
            stock_reserved {int_type} NOT NULL DEFAULT 0,
            revision {int_type} NOT NULL DEFAULT 0,
            deleted_at {ts_type},
            created_at {ts_type} NOT NULL DEFAULT 0,
            updated_at {ts_type} NOT NULL DEFAULT 0
        )
        """,
        # --- section 4.7 (order snapshot columns the models need) ---
        f"""
        CREATE TABLE {t("orders")} (
            id TEXT PRIMARY KEY,
            merchant_id TEXT NOT NULL,
            protocol TEXT NOT NULL DEFAULT 'gamma',
            state TEXT NOT NULL,
            buyer_pubkey_hash TEXT,
            external_id_hash TEXT,
            request_hash TEXT,
            subtotal_sat {int_type} NOT NULL DEFAULT 0,
            shipping_sat {int_type} NOT NULL DEFAULT 0,
            total_sat {int_type} NOT NULL DEFAULT 0,
            buyer_amount_sat {int_type},
            payment_exception BOOLEAN NOT NULL DEFAULT FALSE,
            payment_exception_reason TEXT,
            payment_exception_resolution TEXT,
            public_token_hash TEXT,
            public_token_enc {blob_type},
            public_token_expires_at {ts_type},
            email_opt_in BOOLEAN NOT NULL DEFAULT FALSE,
            created_at {ts_type} NOT NULL DEFAULT 0,
            updated_at {ts_type} NOT NULL DEFAULT 0
        )
        """,
        f"""
        CREATE TABLE {t("order_items")} (
            id TEXT PRIMARY KEY,
            order_id TEXT NOT NULL REFERENCES {fk("orders")}(id),
            product_id TEXT NOT NULL REFERENCES {fk("products")}(id),
            product_d TEXT NOT NULL,
            title TEXT NOT NULL,
            quantity {int_type} NOT NULL CHECK (quantity > 0),
            unit_price_minor {int_type} NOT NULL,
            currency TEXT NOT NULL,
            currency_decimals {int_type} NOT NULL,
            line_total_sat {int_type} NOT NULL
        )
        """,
        f"""
        CREATE TABLE {t("order_events")} (
            id TEXT PRIMARY KEY,
            order_id TEXT NOT NULL REFERENCES {fk("orders")}(id),
            from_state TEXT,
            to_state TEXT NOT NULL,
            actor TEXT NOT NULL,
            detail_json TEXT,
            created_at {ts_type} NOT NULL
        )
        """,
        f"""
        CREATE TABLE {t("order_fx_quotes")} (
            order_id TEXT NOT NULL REFERENCES {fk("orders")}(id),
            currency TEXT NOT NULL,
            rate_decimal TEXT NOT NULL,
            rate_direction TEXT NOT NULL,
            rate_unit TEXT NOT NULL,
            source TEXT NOT NULL,
            providers TEXT NOT NULL,
            quoted_at {ts_type} NOT NULL,
            expires_at {ts_type} NOT NULL,
            UNIQUE (order_id, currency)
        )
        """,
        # --- section 4.8 ---
        f"""
        CREATE TABLE {t("payments")} (
            id TEXT PRIMARY KEY,
            order_id TEXT NOT NULL UNIQUE REFERENCES {fk("orders")}(id),
            core_external_id TEXT NOT NULL UNIQUE,
            payment_hash TEXT UNIQUE,
            checking_id_enc {blob_type},
            bolt11_enc {blob_type},
            wallet_refs_enc {blob_type},
            wallet_id_hash TEXT NOT NULL,
            source_wallet_id_hash TEXT NOT NULL,
            amount_sat {int_type} NOT NULL,
            status TEXT NOT NULL,
            settled_at {ts_type},
            created_at {ts_type} NOT NULL DEFAULT 0
        )
        """,
        # --- section 4.9 ---
        f"""
        CREATE TABLE {t("inbox_events")} (
            id TEXT PRIMARY KEY,
            outer_event_id TEXT NOT NULL UNIQUE,
            rumor_id TEXT,
            merchant_id TEXT NOT NULL,
            source_relay_url TEXT,
            received_at {ts_type} NOT NULL,
            kind {int_type} NOT NULL,
            author_hash TEXT,
            author_enc {blob_type},
            processed_state TEXT NOT NULL,
            reject_reason TEXT,
            raw_json TEXT,
            processed_at {ts_type}
        )
        """,
        # --- section 4.10 ---
        f"""
        CREATE TABLE {t("outbox_events")} (
            id TEXT PRIMARY KEY,
            merchant_id TEXT NOT NULL,
            aggregate_type TEXT NOT NULL,
            aggregate_id TEXT NOT NULL,
            aggregate_revision {int_type} NOT NULL DEFAULT 0,
            event_kind {int_type} NOT NULL,
            event_address TEXT,
            payload_json TEXT,
            payload_enc {blob_type},
            state TEXT NOT NULL,
            attempts {int_type} NOT NULL DEFAULT 0,
            next_attempt_at {ts_type} NOT NULL DEFAULT 0,
            claimed_by TEXT,
            claimed_at {ts_type},
            claimed_until {ts_type},
            claim_token {int_type} NOT NULL DEFAULT 0,
            last_error TEXT,
            created_at {ts_type} NOT NULL DEFAULT 0,
            updated_at {ts_type} NOT NULL DEFAULT 0
        )
        """,
        f"""
        CREATE TABLE {t("outbox_dependencies")} (
            outbox_event_id TEXT NOT NULL REFERENCES {fk("outbox_events")}(id),
            depends_on_outbox_event_id TEXT NOT NULL REFERENCES {fk("outbox_events")}(id),
            UNIQUE (outbox_event_id, depends_on_outbox_event_id)
        )
        """,
        f"""
        CREATE TABLE {t("relay_publications")} (
            id TEXT PRIMARY KEY,
            outbox_event_id TEXT NOT NULL REFERENCES {fk("outbox_events")}(id),
            delivery_copy TEXT NOT NULL,
            relay_url TEXT NOT NULL,
            event_id TEXT NOT NULL,
            attempt_no {int_type} NOT NULL,
            result TEXT NOT NULL,
            message TEXT,
            attempted_at {ts_type} NOT NULL,
            UNIQUE (outbox_event_id, delivery_copy, relay_url, event_id, attempt_no)
        )
        """,
        # --- section 4.11 ---
        f"""
        CREATE TABLE {t("relay_cursors")} (
            id TEXT PRIMARY KEY,
            merchant_id TEXT NOT NULL,
            relay_url TEXT NOT NULL,
            protocol TEXT NOT NULL,
            last_completed_session_start {ts_type},
            eose_session_id TEXT,
            eose_at {ts_type},
            updated_at {ts_type} NOT NULL DEFAULT 0,
            UNIQUE (merchant_id, relay_url, protocol)
        )
        """,
        # --- section 4.12 ---
        f"""
        CREATE TABLE {t("inventory_reservations")} (
            id TEXT PRIMARY KEY,
            product_id TEXT NOT NULL REFERENCES {fk("products")}(id),
            order_id TEXT NOT NULL REFERENCES {fk("orders")}(id),
            quantity {int_type} NOT NULL CHECK (quantity > 0),
            state TEXT NOT NULL,
            expires_at {ts_type} NOT NULL,
            created_at {ts_type} NOT NULL DEFAULT 0,
            updated_at {ts_type} NOT NULL DEFAULT 0,
            UNIQUE (order_id, product_id)
        )
        """,
        # --- section 4.16 ---
        f"""
        CREATE TABLE {t("task_leases")} (
            name TEXT PRIMARY KEY,
            holder_id TEXT,
            fencing_token {int_type} NOT NULL DEFAULT 0,
            leased_until {ts_type} NOT NULL,
            updated_at {ts_type} NOT NULL DEFAULT 0
        )
        """,
        f"""
        CREATE TABLE {t("rate_limit_buckets")} (
            scope_hash TEXT NOT NULL,
            bucket TEXT NOT NULL,
            window_start {ts_type} NOT NULL,
            count {int_type} NOT NULL DEFAULT 0,
            expires_at {ts_type} NOT NULL,
            UNIQUE (scope_hash, bucket, window_start)
        )
        """,
        # --- section 4.15 ---
        f"""
        CREATE TABLE {t("idempotency_records")} (
            scope_hash TEXT PRIMARY KEY,
            request_hash TEXT NOT NULL,
            state TEXT NOT NULL,
            order_id TEXT,
            owner_id TEXT NOT NULL,
            lease_until {ts_type},
            status_code {int_type},
            response_enc {blob_type},
            created_at {ts_type} NOT NULL DEFAULT 0,
            expires_at {ts_type} NOT NULL
        )
        """,
        # --- section 4.18 ---
        f"""
        CREATE TABLE {t("email_queue")} (
            id TEXT PRIMARY KEY,
            merchant_id TEXT NOT NULL,
            order_id TEXT REFERENCES {fk("orders")}(id),
            channel TEXT NOT NULL,
            event_type TEXT NOT NULL,
            recipient_enc {blob_type} NOT NULL,
            recipient_hash TEXT NOT NULL,
            state TEXT NOT NULL,
            attempts {int_type} NOT NULL DEFAULT 0,
            next_attempt_at {ts_type} NOT NULL DEFAULT 0,
            claimed_by TEXT,
            claimed_at {ts_type},
            claimed_until {ts_type},
            claim_token {int_type} NOT NULL DEFAULT 0,
            last_error TEXT,
            created_at {ts_type} NOT NULL DEFAULT 0,
            sent_at {ts_type},
            UNIQUE (order_id, channel, event_type, recipient_hash)
        )
        """,
        # --- section 4.19 partial/secondary indexes the models rely on ---
        # rumor_id is UNIQUE where present (spec: UNIQUE-where-present).
        f"""
        CREATE UNIQUE INDEX ix_inbox_events_rumor_id
        ON {t("inbox_events")}(rumor_id) WHERE rumor_id IS NOT NULL
        """,
        f"""
        CREATE UNIQUE INDEX ix_orders_buyer_external
        ON {t("orders")}(merchant_id, buyer_pubkey_hash, external_id_hash)
        WHERE buyer_pubkey_hash IS NOT NULL
        """,
        f"""
        CREATE INDEX ix_outbox_events_state_next
        ON {t("outbox_events")}(state, next_attempt_at)
        """,
        f"""
        CREATE INDEX ix_email_queue_state_next
        ON {t("email_queue")}(state, next_attempt_at)
        """,
        f"""
        CREATE INDEX ix_email_queue_order
        ON {t("email_queue")}(order_id)
        """,
    ]
