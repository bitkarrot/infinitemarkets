"""Extension migrations — run by the host's ``run_migration`` (mNNN_ prefix).

m001 covers the merchant/catalog/outbox-intent schema subset (spec section 4):
merchants, merchant_keys, settings, catalogs, products + section-4.4 detail
tables, collections + collection_shipping, shipping_options,
protocol_addresses, relay_configs, outbox_events, outbox_dependencies,
relay_publications, task_leases, rate_limit_buckets — plus the section-4.19
indexes that touch these tables.

m002 (plan 02-03) adds the orders/payments/inventory/idempotency/email
cluster plus schema-only inbox_events/order_messages. peer_relays,
relay_cursors, and migration_jobs defer to Phase 3/4 migrations.

Conventions: table names and FK targets use ``db.references_schema``
(``infinitemarkets.`` on PostgreSQL, unqualified on SQLite — the extension
file's ``main`` schema). Timestamps are integer epoch seconds. DDL runs
through ``db.execute`` (auto-commit is legal outside domain transactions).
"""

from __future__ import annotations

import json
import uuid

from lnbits.db import Connection
from loguru import logger

from . import crypto


async def m001_initial(db: Connection):
    s = db.references_schema
    int_t = db.big_int
    blob_t = db.blob

    # --- 4.1 merchants -------------------------------------------------------
    await db.execute(
        f"""
        CREATE TABLE {s}merchants (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL UNIQUE,
            pubkey TEXT NOT NULL UNIQUE,
            key_ref TEXT NOT NULL,
            display_name TEXT,
            profile_json TEXT,
            payment_preference TEXT NOT NULL DEFAULT 'manual',
            recommended_app_d TEXT,
            wallet_id_enc {blob_t} NOT NULL,
            wallet_id_hash TEXT NOT NULL,
            notify_emails TEXT,
            notify_events TEXT,
            theme TEXT,
            state TEXT NOT NULL DEFAULT 'draft',
            created_at {int_t} NOT NULL DEFAULT 0,
            updated_at {int_t} NOT NULL DEFAULT 0
        )
        """
    )

    # --- 4.14 merchant_keys --------------------------------------------------
    await db.execute(
        f"""
        CREATE TABLE {s}merchant_keys (
            merchant_id TEXT PRIMARY KEY
                REFERENCES {s}merchants(id) ON DELETE RESTRICT,
            key_origin TEXT NOT NULL,
            key_version TEXT NOT NULL,
            nonce {blob_t} NOT NULL,
            ciphertext {blob_t} NOT NULL,
            created_at {int_t} NOT NULL DEFAULT 0,
            rotated_at {int_t}
        )
        """
    )

    # --- 4.17 settings -------------------------------------------------------
    await db.execute(
        f"""
        CREATE TABLE {s}settings (
            merchant_id TEXT NOT NULL
                REFERENCES {s}merchants(id) ON DELETE RESTRICT,
            key TEXT NOT NULL,
            value TEXT,
            UNIQUE (merchant_id, key)
        )
        """
    )

    # --- 4.2 catalogs --------------------------------------------------------
    await db.execute(
        f"""
        CREATE TABLE {s}catalogs (
            id TEXT PRIMARY KEY,
            merchant_id TEXT NOT NULL
                REFERENCES {s}merchants(id) ON DELETE RESTRICT,
            name TEXT,
            description TEXT,
            default_currency TEXT,
            default_location TEXT,
            nip15_stall_d TEXT,
            publish_gamma BOOLEAN NOT NULL DEFAULT TRUE,
            publish_nip15 BOOLEAN NOT NULL DEFAULT FALSE,
            deleted_at {int_t},
            created_at {int_t} NOT NULL DEFAULT 0,
            updated_at {int_t} NOT NULL DEFAULT 0
        )
        """
    )

    # --- 4.3 products --------------------------------------------------------
    await db.execute(
        f"""
        CREATE TABLE {s}products (
            id TEXT PRIMARY KEY,
            merchant_id TEXT NOT NULL
                REFERENCES {s}merchants(id) ON DELETE RESTRICT,
            catalog_id TEXT NOT NULL
                REFERENCES {s}catalogs(id) ON DELETE RESTRICT,
            d_tag TEXT NOT NULL,
            parent_product_id TEXT REFERENCES {s}products(id),
            product_type TEXT NOT NULL,
            format TEXT NOT NULL,
            title TEXT,
            summary TEXT,
            description_md TEXT,
            amount_minor {int_t},
            currency TEXT,
            currency_decimals {int_t},
            recurring_frequency TEXT,
            visibility TEXT NOT NULL DEFAULT 'hidden',
            nip99_status TEXT NOT NULL DEFAULT 'active',
            draft BOOLEAN NOT NULL DEFAULT FALSE,
            stock_on_hand {int_t},
            stock_reserved {int_t} NOT NULL DEFAULT 0,
            location TEXT,
            geohash TEXT,
            weight_value REAL,
            weight_unit TEXT,
            dim_l REAL,
            dim_w REAL,
            dim_h REAL,
            dim_unit TEXT,
            nip15_product_id TEXT,
            published_at {int_t},
            revision {int_t} NOT NULL DEFAULT 0,
            deleted_at {int_t},
            created_at {int_t} NOT NULL DEFAULT 0,
            updated_at {int_t} NOT NULL DEFAULT 0,
            UNIQUE (merchant_id, d_tag),
            CHECK (amount_minor IS NULL OR amount_minor >= 0),
            -- ^[A-Z0-9]{3,8}$ charset is asserted in the service layer;
            -- SQLite has no portable REGEXP.
            CHECK (currency IS NULL OR length(currency) BETWEEN 3 AND 8),
            CHECK (
                currency_decimals IS NULL
                OR (currency_decimals >= 0 AND currency_decimals <= 18)
            ),
            CHECK (stock_on_hand IS NULL OR stock_on_hand >= 0),
            CHECK (stock_reserved >= 0),
            CHECK (stock_on_hand IS NULL OR stock_reserved <= stock_on_hand),
            CHECK ((product_type = 'variation') = (parent_product_id IS NOT NULL))
        )
        """
    )

    # --- 4.4 product detail tables -------------------------------------------
    await db.execute(
        f"""
        CREATE TABLE {s}product_images (
            id TEXT PRIMARY KEY,
            product_id TEXT NOT NULL
                REFERENCES {s}products(id) ON DELETE RESTRICT,
            url TEXT NOT NULL,
            dimensions TEXT,
            sort_order {int_t} NOT NULL DEFAULT 0
        )
        """
    )
    await db.execute(
        f"""
        CREATE TABLE {s}product_specs (
            id TEXT PRIMARY KEY,
            product_id TEXT NOT NULL
                REFERENCES {s}products(id) ON DELETE RESTRICT,
            key TEXT NOT NULL,
            value TEXT NOT NULL
        )
        """
    )
    await db.execute(
        f"""
        CREATE TABLE {s}product_categories (
            id TEXT PRIMARY KEY,
            product_id TEXT NOT NULL
                REFERENCES {s}products(id) ON DELETE RESTRICT,
            category TEXT NOT NULL
        )
        """
    )

    # --- 4.5 collections + collection_shipping -------------------------------
    await db.execute(
        f"""
        CREATE TABLE {s}collections (
            id TEXT PRIMARY KEY,
            merchant_id TEXT NOT NULL
                REFERENCES {s}merchants(id) ON DELETE RESTRICT,
            d_tag TEXT NOT NULL,
            title TEXT,
            description TEXT,
            image TEXT,
            location TEXT,
            geohash TEXT,
            revision {int_t} NOT NULL DEFAULT 0,
            deleted_at {int_t},
            created_at {int_t} NOT NULL DEFAULT 0,
            updated_at {int_t} NOT NULL DEFAULT 0,
            UNIQUE (merchant_id, d_tag)
        )
        """
    )
    await db.execute(
        f"""
        CREATE TABLE {s}collection_shipping (
            id TEXT PRIMARY KEY,
            collection_id TEXT NOT NULL
                REFERENCES {s}collections(id) ON DELETE RESTRICT,
            shipping_option_id TEXT NOT NULL,
            UNIQUE (collection_id, shipping_option_id)
        )
        """
    )
    await db.execute(
        f"""
        CREATE TABLE {s}product_collections (
            id TEXT PRIMARY KEY,
            product_id TEXT NOT NULL
                REFERENCES {s}products(id) ON DELETE RESTRICT,
            collection_id TEXT NOT NULL
                REFERENCES {s}collections(id) ON DELETE RESTRICT,
            UNIQUE (product_id, collection_id)
        )
        """
    )

    # --- 4.6 shipping_options -------------------------------------------------
    await db.execute(
        f"""
        CREATE TABLE {s}shipping_options (
            id TEXT PRIMARY KEY,
            merchant_id TEXT NOT NULL
                REFERENCES {s}merchants(id) ON DELETE RESTRICT,
            d_tag TEXT NOT NULL,
            title TEXT,
            description TEXT,
            base_price_minor {int_t},
            currency TEXT,
            service TEXT NOT NULL,
            carrier TEXT,
            countries TEXT,
            regions TEXT,
            duration_min {int_t},
            duration_max {int_t},
            duration_unit TEXT,
            weight_min REAL,
            weight_max REAL,
            weight_unit TEXT,
            dim_min_l REAL,
            dim_min_w REAL,
            dim_min_h REAL,
            dim_max_l REAL,
            dim_max_w REAL,
            dim_max_h REAL,
            dim_unit TEXT,
            price_weight_minor {int_t},
            price_weight_unit TEXT,
            price_volume_minor {int_t},
            price_volume_unit TEXT,
            location TEXT,
            geohash TEXT,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            revision {int_t} NOT NULL DEFAULT 0,
            deleted_at {int_t},
            created_at {int_t} NOT NULL DEFAULT 0,
            updated_at {int_t} NOT NULL DEFAULT 0,
            UNIQUE (merchant_id, d_tag)
        )
        """
    )

    # --- 4.4 continued: shipping reference tables (need shipping_options) -----
    await db.execute(
        f"""
        CREATE TABLE {s}product_shipping_options (
            id TEXT PRIMARY KEY,
            product_id TEXT NOT NULL
                REFERENCES {s}products(id) ON DELETE RESTRICT,
            shipping_option_id TEXT NOT NULL
                REFERENCES {s}shipping_options(id) ON DELETE RESTRICT,
            extra_cost_minor {int_t},
            UNIQUE (product_id, shipping_option_id)
        )
        """
    )
    await db.execute(
        f"""
        CREATE TABLE {s}product_shipping_collections (
            id TEXT PRIMARY KEY,
            product_id TEXT NOT NULL
                REFERENCES {s}products(id) ON DELETE RESTRICT,
            collection_id TEXT NOT NULL
                REFERENCES {s}collections(id) ON DELETE RESTRICT,
            extra_cost_minor {int_t},
            UNIQUE (product_id, collection_id)
        )
        """
    )

    # --- 4.13 protocol_addresses ----------------------------------------------
    await db.execute(
        f"""
        CREATE TABLE {s}protocol_addresses (
            id TEXT PRIMARY KEY,
            domain_type TEXT NOT NULL,
            domain_id TEXT NOT NULL,
            protocol TEXT NOT NULL,
            event_kind {int_t} NOT NULL,
            author_pubkey TEXT NOT NULL,
            d_tag TEXT NOT NULL DEFAULT '',
            latest_event_id TEXT,
            latest_created_at {int_t},
            UNIQUE (protocol, event_kind, author_pubkey, d_tag)
        )
        """
    )

    # --- 4.11 relay_configs ----------------------------------------------------
    await db.execute(
        f"""
        CREATE TABLE {s}relay_configs (
            id TEXT PRIMARY KEY,
            merchant_id TEXT REFERENCES {s}merchants(id) ON DELETE RESTRICT,
            relay_url TEXT NOT NULL,
            direction TEXT NOT NULL,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            created_at {int_t} NOT NULL DEFAULT 0,
            updated_at {int_t} NOT NULL DEFAULT 0
        )
        """
    )

    # --- 4.10 outbox_events + dependencies + relay_publications -----------------
    await db.execute(
        f"""
        CREATE TABLE {s}outbox_events (
            id TEXT PRIMARY KEY,
            merchant_id TEXT NOT NULL,
            aggregate_type TEXT NOT NULL,
            aggregate_id TEXT NOT NULL,
            aggregate_revision {int_t} NOT NULL DEFAULT 0,
            event_kind {int_t} NOT NULL,
            event_address TEXT,
            payload_json TEXT,
            payload_enc {blob_t},
            state TEXT NOT NULL,
            attempts {int_t} NOT NULL DEFAULT 0,
            next_attempt_at {int_t} NOT NULL DEFAULT 0,
            claimed_by TEXT,
            claimed_at {int_t},
            claimed_until {int_t},
            claim_token {int_t} NOT NULL DEFAULT 0,
            last_error TEXT,
            created_at {int_t} NOT NULL DEFAULT 0,
            updated_at {int_t} NOT NULL DEFAULT 0
        )
        """
    )
    await db.execute(
        f"""
        CREATE TABLE {s}outbox_dependencies (
            outbox_event_id TEXT NOT NULL
                REFERENCES {s}outbox_events(id) ON DELETE RESTRICT,
            depends_on_outbox_event_id TEXT NOT NULL
                REFERENCES {s}outbox_events(id) ON DELETE RESTRICT,
            UNIQUE (outbox_event_id, depends_on_outbox_event_id)
        )
        """
    )
    await db.execute(
        f"""
        CREATE TABLE {s}relay_publications (
            id TEXT PRIMARY KEY,
            outbox_event_id TEXT NOT NULL
                REFERENCES {s}outbox_events(id) ON DELETE RESTRICT,
            delivery_copy TEXT NOT NULL,
            relay_url TEXT NOT NULL,
            event_id TEXT NOT NULL,
            attempt_no {int_t} NOT NULL,
            result TEXT NOT NULL,
            message TEXT,
            attempted_at {int_t} NOT NULL,
            UNIQUE (
                outbox_event_id, delivery_copy, relay_url, event_id, attempt_no
            )
        )
        """
    )

    # --- 4.16 task_leases + rate_limit_buckets ---------------------------------
    await db.execute(
        f"""
        CREATE TABLE {s}task_leases (
            name TEXT PRIMARY KEY,
            holder_id TEXT,
            fencing_token {int_t} NOT NULL DEFAULT 0,
            leased_until {int_t} NOT NULL DEFAULT 0,
            updated_at {int_t} NOT NULL DEFAULT 0
        )
        """
    )
    await db.execute(
        f"""
        CREATE TABLE {s}rate_limit_buckets (
            scope_hash TEXT NOT NULL,
            bucket TEXT NOT NULL,
            window_start {int_t} NOT NULL,
            count {int_t} NOT NULL DEFAULT 0,
            expires_at {int_t} NOT NULL,
            UNIQUE (scope_hash, bucket, window_start)
        )
        """
    )

    # --- 4.19 indexes touching m001 tables --------------------------------------
    await db.execute(
        f"CREATE INDEX ix_products_merchant_catalog "
        f"ON {s}products(merchant_id, catalog_id)"
    )
    await db.execute(
        f"CREATE UNIQUE INDEX ix_products_nip15_id "
        f"ON {s}products(merchant_id, nip15_product_id) "
        f"WHERE nip15_product_id IS NOT NULL"
    )
    await db.execute(
        f"CREATE INDEX ix_outbox_events_state_next "
        f"ON {s}outbox_events(state, next_attempt_at)"
    )
    await db.execute(
        f"CREATE INDEX ix_outbox_events_aggregate "
        f"ON {s}outbox_events(aggregate_type, aggregate_id, aggregate_revision)"
    )


async def m002_orders(db: Connection):
    """Plan 02-03 — orders/payments/inventory/idempotency/email (spec
    sections 4.7-4.9, 4.12, 4.15, 4.18) plus schema-only order_messages.
    inbox_events is schema-only too (consumed by the Release-B inbox
    worker); peer_relays/relay_cursors/migration_jobs stay deferred."""
    s = db.references_schema
    int_t = db.big_int
    blob_t = db.blob

    # --- 4.7 orders --------------------------------------------------------------
    await db.execute(
        f"""
        CREATE TABLE {s}orders (
            id TEXT PRIMARY KEY,
            merchant_id TEXT NOT NULL
                REFERENCES {s}merchants(id) ON DELETE RESTRICT,
            buyer_pubkey_enc {blob_t},
            buyer_pubkey_hash TEXT,
            protocol TEXT NOT NULL,
            external_id_enc {blob_t},
            external_id_hash TEXT,
            request_hash TEXT,
            source_event_id TEXT,
            currency TEXT NOT NULL DEFAULT 'SAT',
            subtotal_sat {int_t},
            shipping_sat {int_t},
            total_sat {int_t},
            buyer_amount_sat {int_t},
            state TEXT NOT NULL,
            shipping_state TEXT NOT NULL DEFAULT 'not_required',
            contact_enc {blob_t},
            address_enc {blob_t},
            shipping_option_id TEXT,
            payment_hash TEXT UNIQUE,
            invoice_expiry {int_t},
            public_token_hash {blob_t},
            public_token_enc {blob_t},
            public_token_expires_at {int_t},
            checkout_scope_hash TEXT,
            payment_exception BOOLEAN NOT NULL DEFAULT FALSE,
            payment_exception_reason TEXT,
            payment_exception_resolution TEXT,
            oversold BOOLEAN NOT NULL DEFAULT FALSE,
            receipt_verified BOOLEAN NOT NULL DEFAULT FALSE,
            email_opt_in BOOLEAN NOT NULL DEFAULT FALSE,
            created_at {int_t} NOT NULL DEFAULT 0,
            updated_at {int_t} NOT NULL DEFAULT 0
        )
        """
    )
    await db.execute(
        f"""
        CREATE TABLE {s}order_items (
            id TEXT PRIMARY KEY,
            order_id TEXT NOT NULL
                REFERENCES {s}orders(id) ON DELETE CASCADE,
            product_id TEXT NOT NULL,
            product_d TEXT,
            title TEXT,
            quantity INT NOT NULL,
            unit_price_minor {int_t},
            currency TEXT,
            currency_decimals INT,
            line_total_sat {int_t},
            backordered_qty INT NOT NULL DEFAULT 0
        )
        """
    )
    await db.execute(
        f"""
        CREATE TABLE {s}order_events (
            id TEXT PRIMARY KEY,
            order_id TEXT NOT NULL
                REFERENCES {s}orders(id) ON DELETE CASCADE,
            from_state TEXT,
            to_state TEXT NOT NULL,
            actor TEXT NOT NULL,
            detail_json TEXT,
            created_at {int_t} NOT NULL DEFAULT 0
        )
        """
    )
    await db.execute(
        f"""
        CREATE TABLE {s}order_fx_quotes (
            id TEXT PRIMARY KEY,
            order_id TEXT NOT NULL
                REFERENCES {s}orders(id) ON DELETE CASCADE,
            currency TEXT NOT NULL,
            rate_decimal TEXT,
            rate_direction TEXT,
            rate_unit TEXT,
            source TEXT,
            providers TEXT,
            quoted_at {int_t},
            expires_at {int_t},
            UNIQUE (order_id, currency)
        )
        """
    )
    await db.execute(
        f"""
        CREATE TABLE {s}order_fulfillment (
            order_id TEXT PRIMARY KEY
                REFERENCES {s}orders(id) ON DELETE CASCADE,
            tracking_enc {blob_t},
            carrier TEXT,
            eta TEXT,
            updated_at {int_t} NOT NULL DEFAULT 0
        )
        """
    )
    await db.execute(
        f"""
        CREATE TABLE {s}order_messages (
            id TEXT PRIMARY KEY,
            order_id TEXT
                REFERENCES {s}orders(id) ON DELETE CASCADE,
            direction TEXT NOT NULL,
            protocol TEXT,
            semantic_kind TEXT,
            sender_hash TEXT,
            recipient_hash TEXT,
            participant_keys_enc {blob_t},
            rumor_id TEXT,
            event_id TEXT,
            content_enc {blob_t},
            created_at {int_t} NOT NULL DEFAULT 0
        )
        """
    )

    # --- 4.8 payments --------------------------------------------------------------
    await db.execute(
        f"""
        CREATE TABLE {s}payments (
            id TEXT PRIMARY KEY,
            order_id TEXT NOT NULL UNIQUE
                REFERENCES {s}orders(id) ON DELETE CASCADE,
            core_external_id TEXT NOT NULL UNIQUE,
            payment_hash TEXT UNIQUE,
            checking_id_enc {blob_t},
            bolt11_enc {blob_t},
            wallet_refs_enc {blob_t},
            wallet_id_hash TEXT,
            source_wallet_id_hash TEXT,
            amount_sat {int_t},
            status TEXT NOT NULL,
            settled_at {int_t},
            created_at {int_t} NOT NULL DEFAULT 0
        )
        """
    )

    # --- 4.9 inbox_events (schema-only; consumed by the Release-B worker) ----------
    await db.execute(
        f"""
        CREATE TABLE {s}inbox_events (
            id TEXT PRIMARY KEY,
            outer_event_id TEXT NOT NULL UNIQUE,
            rumor_id TEXT,
            merchant_id TEXT
                REFERENCES {s}merchants(id) ON DELETE CASCADE,
            source_relay_url TEXT,
            received_at {int_t} NOT NULL DEFAULT 0,
            kind INT,
            author_hash TEXT,
            author_enc {blob_t},
            processed_state TEXT NOT NULL DEFAULT 'received',
            reject_reason TEXT,
            raw_json TEXT,
            processed_at {int_t}
        )
        """
    )

    # --- 4.12 inventory_reservations -------------------------------------------------
    await db.execute(
        f"""
        CREATE TABLE {s}inventory_reservations (
            id TEXT PRIMARY KEY,
            product_id TEXT NOT NULL
                REFERENCES {s}products(id) ON DELETE RESTRICT,
            order_id TEXT NOT NULL
                REFERENCES {s}orders(id) ON DELETE CASCADE,
            quantity INT NOT NULL CHECK (quantity > 0),
            state TEXT NOT NULL,
            expires_at {int_t},
            created_at {int_t} NOT NULL DEFAULT 0,
            updated_at {int_t} NOT NULL DEFAULT 0,
            UNIQUE (order_id, product_id)
        )
        """
    )

    # --- 4.15 idempotency_records ---------------------------------------------------
    await db.execute(
        f"""
        CREATE TABLE {s}idempotency_records (
            scope_hash TEXT PRIMARY KEY,
            request_hash TEXT NOT NULL,
            state TEXT NOT NULL,
            order_id TEXT,
            owner_id TEXT,
            lease_until {int_t},
            status_code INT,
            response_enc {blob_t},
            created_at {int_t} NOT NULL DEFAULT 0,
            expires_at {int_t} NOT NULL DEFAULT 0
        )
        """
    )

    # --- 4.18 email_queue -------------------------------------------------------------
    await db.execute(
        f"""
        CREATE TABLE {s}email_queue (
            id TEXT PRIMARY KEY,
            merchant_id TEXT NOT NULL
                REFERENCES {s}merchants(id) ON DELETE CASCADE,
            order_id TEXT
                REFERENCES {s}orders(id) ON DELETE CASCADE,
            channel TEXT NOT NULL,
            event_type TEXT NOT NULL,
            recipient_enc {blob_t} NOT NULL,
            recipient_hash TEXT NOT NULL,
            state TEXT NOT NULL,
            attempts INT NOT NULL DEFAULT 0,
            next_attempt_at {int_t} NOT NULL DEFAULT 0,
            claimed_by TEXT,
            claimed_at {int_t},
            claimed_until {int_t},
            claim_token {int_t} NOT NULL DEFAULT 0,
            last_error TEXT,
            created_at {int_t} NOT NULL DEFAULT 0,
            sent_at {int_t},
            UNIQUE (order_id, channel, event_type, recipient_hash)
        )
        """
    )

    # --- 4.19 indexes touching m002 tables ------------------------------------------
    await db.execute(
        f"CREATE INDEX ix_orders_merchant_state "
        f"ON {s}orders(merchant_id, state)"
    )
    await db.execute(
        f"CREATE UNIQUE INDEX ix_orders_web_external_id "
        f"ON {s}orders(merchant_id, external_id_hash) "
        f"WHERE protocol = 'web'"
    )
    await db.execute(
        f"CREATE UNIQUE INDEX ix_orders_nostr_external_id "
        f"ON {s}orders(merchant_id, buyer_pubkey_hash, external_id_hash) "
        f"WHERE buyer_pubkey_hash IS NOT NULL"
    )
    await db.execute(
        f"CREATE UNIQUE INDEX ix_inbox_rumor "
        f"ON {s}inbox_events(rumor_id) WHERE rumor_id IS NOT NULL"
    )
    await db.execute(
        f"CREATE INDEX ix_order_events_order "
        f"ON {s}order_events(order_id, created_at)"
    )
    await db.execute(
        f"CREATE INDEX ix_reservations_expiry "
        f"ON {s}inventory_reservations(state, expires_at)"
    )
    await db.execute(
        f"CREATE INDEX ix_email_queue_state_next "
        f"ON {s}email_queue(state, next_attempt_at)"
    )
    await db.execute(
        f"CREATE INDEX ix_email_queue_order ON {s}email_queue(order_id)"
    )


async def m003_checkout_safety(db: Connection):
    from .services.fx import CURRENCY_DECIMALS

    s = db.references_schema
    await db.execute(
        f"ALTER TABLE {s}shipping_options ADD COLUMN currency_decimals INTEGER"
        " NOT NULL DEFAULT 2 CHECK (currency_decimals >= 0 AND currency_decimals <= 18)"
    )
    await db.execute(
        f"ALTER TABLE {s}idempotency_records ADD COLUMN claim_token {db.big_int}"
        " NOT NULL DEFAULT 0"
    )
    await db.execute(
        f"ALTER TABLE {s}outbox_events ADD COLUMN last_signed_at {db.big_int}"
        " NOT NULL DEFAULT 0"
    )
    await db.execute(
        f"CREATE INDEX ix_outbox_address_clock ON {s}outbox_events"
        " (merchant_id, event_address, last_signed_at)"
    )
    await db.execute(
        f"CREATE INDEX ix_orders_checkout_scope ON {s}orders"
        " (merchant_id, checkout_scope_hash, state)"
    )
    await db.execute(
        f"CREATE INDEX ix_reservations_product_state ON {s}inventory_reservations"
        " (product_id, state)"
    )
    await db.execute(
        f"CREATE INDEX ix_idempotency_order ON {s}idempotency_records (order_id)"
    )
    for currency, decimals in CURRENCY_DECIMALS.items():
        await db.execute(
            f"UPDATE {s}shipping_options SET currency_decimals = :d WHERE currency = :c",
            {"d": decimals, "c": currency},
        )
        await db.execute(
            f"UPDATE {s}products SET currency_decimals = :d WHERE currency = :c"
            " AND currency_decimals IS NULL",
            {"d": decimals, "c": currency},
        )
    await db.execute(
        f"UPDATE {s}products SET currency_decimals = 2"
        " WHERE currency_decimals IS NULL AND currency IS NOT NULL"
    )


async def m004_digital_delivery(db: Connection):
    """Merchant-entered digital delivery content (download link, license
    key or instructions), AEAD-encrypted and revealed to the buyer only
    after LNbits-confirmed payment."""
    s = db.references_schema
    await db.execute(f"ALTER TABLE {s}products ADD COLUMN delivery_enc {db.blob}")


async def m005_order_archiving(db: Connection):
    s = db.references_schema
    await db.execute(
        f"ALTER TABLE {s}orders ADD COLUMN archived_at {db.big_int}"
    )
    await db.execute(
        f"CREATE INDEX ix_orders_merchant_archive "
        f"ON {s}orders(merchant_id, archived_at, created_at)"
    )


async def m006_gamma_inbox(db: Connection):
    """Plan 03-01 — Release B Gamma inbox schema (spec section 4.11).

    Creates the deferred ``peer_relays`` / ``relay_cursors`` tables plus the
    ``inbox_blocklist`` (D-23 mute surface), the ``merchants.inbox_state``
    activation state machine column (``off|pending|active|error|
    deactivating`` — enforced in the domain layer, GAM-01/D-16), the
    ``relay_configs`` NIP-42/paid-relay auth columns (D-26..D-28), and the
    ``order_messages`` Messages-surface markers (conversation threading +
    read markers, written from plan 03-02 onward).
    """
    s = db.references_schema
    int_t = db.big_int
    blob_t = db.blob

    # --- 4.11 peer_relays: buyer kind-10050 discovery cache --------------------
    await db.execute(
        f"""
        CREATE TABLE {s}peer_relays (
            id TEXT PRIMARY KEY,
            merchant_id TEXT NOT NULL
                REFERENCES {s}merchants(id) ON DELETE RESTRICT,
            pubkey_hash TEXT NOT NULL,
            pubkey_enc {blob_t},
            relay_url TEXT NOT NULL,
            fetched_at {int_t},
            expires_at {int_t}
        )
        """
    )
    await db.execute(
        f"CREATE UNIQUE INDEX ux_peer_relays "
        f"ON {s}peer_relays(merchant_id, pubkey_hash, relay_url)"
    )
    await db.execute(
        f"CREATE INDEX ix_peer_relays_pubkey "
        f"ON {s}peer_relays(pubkey_hash)"
    )

    # --- 4.11 relay_cursors: EOSE-bound session cursors (section 9.2) ----------
    await db.execute(
        f"""
        CREATE TABLE {s}relay_cursors (
            id TEXT PRIMARY KEY,
            merchant_id TEXT NOT NULL
                REFERENCES {s}merchants(id) ON DELETE CASCADE,
            relay_url TEXT NOT NULL,
            protocol TEXT NOT NULL,
            last_completed_session_start {int_t},
            eose_session_id TEXT,
            eose_at {int_t},
            updated_at {int_t},
            UNIQUE (merchant_id, relay_url, protocol)
        )
        """
    )

    # --- inbox_blocklist: muted authors dropped at intake (D-23) ---------------
    await db.execute(
        f"""
        CREATE TABLE {s}inbox_blocklist (
            id TEXT PRIMARY KEY,
            merchant_id TEXT NOT NULL
                REFERENCES {s}merchants(id) ON DELETE CASCADE,
            author_hash TEXT NOT NULL,
            reason TEXT,
            created_at {int_t},
            UNIQUE (merchant_id, author_hash)
        )
        """
    )

    # --- merchants.inbox_state: kind-10050 activation state machine ------------
    await db.execute(
        f"ALTER TABLE {s}merchants ADD COLUMN inbox_state TEXT"
        " NOT NULL DEFAULT 'off'"
    )

    # --- relay_configs: per-relay NIP-42/paid-relay auth surface (D-26..D-28) --
    await db.execute(
        f"ALTER TABLE {s}relay_configs ADD COLUMN auth_state TEXT"
    )
    await db.execute(
        f"ALTER TABLE {s}relay_configs ADD COLUMN auth_note TEXT"
    )
    await db.execute(
        f"ALTER TABLE {s}relay_configs ADD COLUMN paid_invoice TEXT"
    )
    await db.execute(
        f"ALTER TABLE {s}relay_configs ADD COLUMN auth_updated_at {int_t}"
    )

    # --- order_messages: Messages-surface markers (03-02 writes them) ----------
    await db.execute(
        f"ALTER TABLE {s}order_messages ADD COLUMN conversation_id TEXT"
    )
    await db.execute(
        f"ALTER TABLE {s}order_messages ADD COLUMN read_at {int_t}"
    )

    # --- section 8.5 rumor-level dedupe ----------------------------------------
    # Retried rumors arrive under fresh outer event ids — the outer id is
    # already unique (m002); rumor_id is unique per merchant so a second
    # wrap of the same rumor is a no-op transition. NULLs (pre-processing
    # rows) never collide.
    await db.execute(
        f"CREATE UNIQUE INDEX ux_inbox_events_merchant_rumor "
        f"ON {s}inbox_events(merchant_id, rumor_id)"
    )


async def m007_nostr_signin(db: Connection):
    """Plan 03-03 — NIP-07 buyer sign-in schema (D-01, locked option).

    ``nostr_challenges``: single-use sign-in challenges — only the SHA-256
    lookup hash is stored (``token_lookup_hash`` posture), scope-bound to
    merchant+client-IP HMAC, 300 s TTL.

    ``buyer_sessions``: revocable buyer sessions — only the token hash is
    stored (same strict-lookup posture as ``public_token_hash``), the
    buyer pubkey under AEAD plus its ``buyer-pubkey`` HMAC index for the
    order-history scope, TTL'd + server-side revocable via ``revoked_at``.
    """
    s = db.references_schema
    int_t = db.big_int
    blob_t = db.blob

    await db.execute(
        f"""
        CREATE TABLE {s}nostr_challenges (
            id TEXT PRIMARY KEY,
            merchant_id TEXT NOT NULL
                REFERENCES {s}merchants(id) ON DELETE RESTRICT,
            challenge_hash TEXT NOT NULL UNIQUE,
            scope_hash TEXT NOT NULL,
            expires_at {int_t} NOT NULL,
            used_at {int_t},
            created_at {int_t} NOT NULL DEFAULT 0
        )
        """
    )
    await db.execute(
        f"""
        CREATE TABLE {s}buyer_sessions (
            id TEXT PRIMARY KEY,
            merchant_id TEXT NOT NULL
                REFERENCES {s}merchants(id) ON DELETE RESTRICT,
            token_hash TEXT NOT NULL UNIQUE,
            buyer_pubkey_enc {blob_t},
            buyer_pubkey_hash TEXT NOT NULL,
            expires_at {int_t} NOT NULL,
            revoked_at {int_t},
            created_at {int_t} NOT NULL DEFAULT 0
        )
        """
    )
    await db.execute(
        f"CREATE INDEX ix_buyer_sessions_pubkey "
        f"ON {s}buyer_sessions(merchant_id, buyer_pubkey_hash)"
    )


async def _backfill_buyer_email_hashes(db: Connection, *, settings=None) -> int:
    """Populate ``orders.buyer_email_hash`` from ``contact_enc`` (D-03).

    Hash equality drives the ``/nostr/orders`` union lookup, so the same
    ``PURPOSE_BUYER_EMAIL`` + ``crypto.normalize`` domain as
    ``buyer_accounts.email_hash`` applies — never ``PURPOSE_EMAIL_RECIPIENT``.
    Rows whose ``contact_enc`` fails decrypt/``json.loads`` or carries a
    falsy/non-string ``email`` are skipped without aborting the migration.
    ``ext_settings`` resolves lazily — only when a row actually needs
    decrypting — so env-less migration runs (``keystore_env``) stay clean.
    Returns the number of rows updated; re-runnable.
    """
    from .settings import ext_settings

    s = db.references_schema
    rows = await db.fetchall(
        f"SELECT id, merchant_id, contact_enc FROM {s}orders"
        " WHERE contact_enc IS NOT NULL AND buyer_email_hash IS NULL"
    )
    updated = 0
    for row in rows:
        if settings is None:
            settings = ext_settings()
        try:
            ver = crypto.envelope_version(row["contact_enc"])
            contact = json.loads(
                crypto.decrypt(
                    row["contact_enc"], settings.master_keys[ver],
                    record_id=row["id"], table="orders",
                    column="contact_enc", key_version=ver,
                )
            )
        except Exception:  # noqa: BLE001 — malformed rows skip, never abort
            continue
        email = contact.get("email") if isinstance(contact, dict) else None
        if not isinstance(email, str) or not crypto.normalize(email):
            continue
        await db.execute(
            f"UPDATE {s}orders SET buyer_email_hash = :h WHERE id = :i",
            {
                "h": crypto.hmac_index(
                    settings.privacy_key, crypto.PURPOSE_BUYER_EMAIL,
                    row["merchant_id"], crypto.normalize(email),
                ),
                "i": row["id"],
            },
        )
        updated += 1
    logger.info("m008.orders_backfilled={}", updated)
    return updated


async def _backfill_session_accounts(db: Connection, *, settings=None) -> int:
    """Create one ``buyer_accounts`` row per distinct
    ``(merchant_id, buyer_pubkey_hash)`` present in the pre-rebuild
    ``buyer_sessions`` table (D-02 compat).

    ``pubkey_enc`` is AAD record-bound — the group's first decryptable
    session ciphertext is re-encrypted under the new account id, never
    transplanted. A group whose ciphertexts all fail decrypt produces NO
    account: those sessions keep resolving on the legacy
    ``account_id IS NULL`` path rather than breaking. ``ext_settings``
    resolves lazily (same ``keystore_env`` posture as the orders
    backfill). Returns the number of accounts created; re-runnable.
    """
    from .settings import ext_settings

    s = db.references_schema
    rows = await db.fetchall(
        f"SELECT id, merchant_id, buyer_pubkey_enc, buyer_pubkey_hash,"
        f" created_at FROM {s}buyer_sessions"
        " WHERE buyer_pubkey_hash IS NOT NULL ORDER BY created_at"
    )
    groups: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        groups.setdefault(
            (row["merchant_id"], row["buyer_pubkey_hash"]), []
        ).append(row)
    created = 0
    for (merchant_id, pubkey_hash), group in groups.items():
        exists = await db.fetchone(
            f"SELECT id FROM {s}buyer_accounts"
            " WHERE merchant_id = :m AND pubkey_hash = :h",
            {"m": merchant_id, "h": pubkey_hash},
        )
        if exists:
            continue
        if settings is None:
            settings = ext_settings()
        account_id = uuid.uuid4().hex
        pubkey_enc = None
        for member in group:
            if member["buyer_pubkey_enc"] is None:
                continue
            try:
                enc_ver = crypto.envelope_version(member["buyer_pubkey_enc"])
                plaintext = crypto.decrypt(
                    member["buyer_pubkey_enc"], settings.master_keys[enc_ver],
                    record_id=member["id"], table="buyer_sessions",
                    column="buyer_pubkey_enc", key_version=enc_ver,
                )
            except Exception:  # noqa: BLE001 — try the next session row
                continue
            ver = settings.active_key_version
            pubkey_enc = crypto.encrypt(
                plaintext, settings.master_keys[ver],
                record_id=account_id, table="buyer_accounts",
                column="pubkey_enc", key_version=ver,
            )
            break
        if pubkey_enc is None:
            # No decryptable pubkey ciphertext — leave these sessions on
            # the legacy read path instead of minting an account whose
            # pubkey_hash the secret can no longer back.
            continue
        created_at = group[0]["created_at"]
        await db.execute(
            f"INSERT INTO {s}buyer_accounts (id, merchant_id, pubkey_enc,"
            " pubkey_hash, created_at, updated_at)"
            " VALUES (:i, :m, :pe, :ph, :n, :n)",
            {
                "i": account_id, "m": merchant_id,
                "pe": pubkey_enc, "ph": pubkey_hash, "n": created_at,
            },
        )
        created += 1
    logger.info("m008.session_accounts_created={}", created)
    return created


async def m008_buyer_accounts(db: Connection):
    """Plan 03.1-01 — buyer account foundation (D-01..D-04).

    ``buyer_accounts``: one row per (merchant, account) — nullable
    ``email_hash``/``pubkey_hash`` HMAC identity columns, each
    unique-when-present and merchant-scoped, plus AEAD ``*_enc`` copies
    bound to the account id; retired accounts carry ``retired_at``
    (never a hard delete).

    ``email_signin_tokens``: hash-only single-use magic-link tokens
    (``token_lookup_hash`` posture) for the plan-02 sign-in/link flows.

    ``buyer_sessions`` is REBUILT — SQLite cannot relax the ``NOT NULL``
    on ``buyer_pubkey_hash`` — gaining ``account_id``; rows whose pubkey
    hash found no account keep ``account_id IS NULL`` and resolve on the
    unchanged legacy path.

    ``orders.buyer_email_hash`` is the ``PURPOSE_BUYER_EMAIL`` HMAC index
    shared with ``buyer_accounts.email_hash`` (hash only — the plaintext
    already lives in ``contact_enc``); existing orders are backfilled by
    decrypting ``contact_enc`` in place. ``email_queue.payload_enc`` and
    the ``nostr_challenges`` ``purpose``/``account_id`` link columns are
    the plan-02 surface (D-05/D-07/D-10 schema).

    Order matters: accounts + the orders column before backfills, the
    account backfill before the sessions rebuild (its JOIN consumes the
    populated accounts), challenge/queue columns last.
    """
    s = db.references_schema
    int_t = db.big_int
    blob_t = db.blob

    # --- D-01: buyer_accounts ------------------------------------------------
    await db.execute(
        f"""
        CREATE TABLE {s}buyer_accounts (
            id TEXT PRIMARY KEY,
            merchant_id TEXT NOT NULL
                REFERENCES {s}merchants(id) ON DELETE RESTRICT,
            email_enc {blob_t},
            email_hash TEXT,
            pubkey_enc {blob_t},
            pubkey_hash TEXT,
            retired_at {int_t},
            created_at {int_t} NOT NULL DEFAULT 0,
            updated_at {int_t} NOT NULL DEFAULT 0
        )
        """
    )
    await db.execute(
        f"CREATE UNIQUE INDEX ux_buyer_accounts_email "
        f"ON {s}buyer_accounts(merchant_id, email_hash) "
        f"WHERE email_hash IS NOT NULL"
    )
    await db.execute(
        f"CREATE UNIQUE INDEX ux_buyer_accounts_pubkey "
        f"ON {s}buyer_accounts(merchant_id, pubkey_hash) "
        f"WHERE pubkey_hash IS NOT NULL"
    )

    # --- D-05/D-10: email_signin_tokens (consumed by plan 02) ----------------
    await db.execute(
        f"""
        CREATE TABLE {s}email_signin_tokens (
            id TEXT PRIMARY KEY,
            merchant_id TEXT NOT NULL
                REFERENCES {s}merchants(id) ON DELETE RESTRICT,
            token_hash TEXT NOT NULL UNIQUE,
            email_hash TEXT NOT NULL,
            purpose TEXT NOT NULL,
            account_id TEXT REFERENCES {s}buyer_accounts(id),
            expires_at {int_t} NOT NULL,
            used_at {int_t},
            created_at {int_t} NOT NULL DEFAULT 0
        )
        """
    )

    # --- D-03: orders.buyer_email_hash ----------------------------------------
    await db.execute(
        f"ALTER TABLE {s}orders ADD COLUMN buyer_email_hash TEXT"
    )
    await db.execute(
        f"CREATE INDEX ix_orders_buyer_email "
        f"ON {s}orders(merchant_id, buyer_email_hash)"
    )

    # --- backfills (need the new column + buyer_accounts, old sessions) ------
    await _backfill_buyer_email_hashes(db)
    await _backfill_session_accounts(db)

    # --- D-02: rebuild buyer_sessions (SQLite cannot relax NOT NULL) ----------
    await db.execute(
        f"""
        CREATE TABLE {s}buyer_sessions_new (
            id TEXT PRIMARY KEY,
            merchant_id TEXT NOT NULL
                REFERENCES {s}merchants(id) ON DELETE RESTRICT,
            token_hash TEXT NOT NULL UNIQUE,
            buyer_pubkey_enc {blob_t},
            buyer_pubkey_hash TEXT,
            account_id TEXT REFERENCES {s}buyer_accounts(id),
            expires_at {int_t} NOT NULL,
            revoked_at {int_t},
            created_at {int_t} NOT NULL DEFAULT 0
        )
        """
    )
    await db.execute(
        f"INSERT INTO {s}buyer_sessions_new (id, merchant_id, token_hash,"
        f" buyer_pubkey_enc, buyer_pubkey_hash, account_id, expires_at,"
        f" revoked_at, created_at)"
        f" SELECT s2.id, s2.merchant_id, s2.token_hash, s2.buyer_pubkey_enc,"
        f" s2.buyer_pubkey_hash, a.id, s2.expires_at, s2.revoked_at,"
        f" s2.created_at"
        f" FROM {s}buyer_sessions s2"
        f" LEFT JOIN {s}buyer_accounts a"
        f" ON a.merchant_id = s2.merchant_id"
        f" AND a.pubkey_hash = s2.buyer_pubkey_hash"
    )
    await db.execute(f"DROP TABLE {s}buyer_sessions")
    await db.execute(
        f"ALTER TABLE {s}buyer_sessions_new RENAME TO buyer_sessions"
    )
    await db.execute(
        f"CREATE INDEX ix_buyer_sessions_pubkey "
        f"ON {s}buyer_sessions(merchant_id, buyer_pubkey_hash)"
    )

    # --- D-07: email_queue.payload_enc (rendered at send time) -----------------
    await db.execute(
        f"ALTER TABLE {s}email_queue ADD COLUMN payload_enc {blob_t}"
    )

    # --- D-10: nostr_challenges link-challenge columns -------------------------
    await db.execute(
        f"ALTER TABLE {s}nostr_challenges ADD COLUMN purpose TEXT"
        " NOT NULL DEFAULT 'signin'"
    )
    await db.execute(
        f"ALTER TABLE {s}nostr_challenges ADD COLUMN account_id TEXT"
        f" REFERENCES {s}buyer_accounts(id)"
    )


async def m009_categories(db: Connection):
    s = db.references_schema
    await db.execute(f"ALTER TABLE {s}catalogs RENAME TO categories")
    await db.execute(
        f"ALTER TABLE {s}products RENAME COLUMN catalog_id TO category_id"
    )
    await db.execute(f"ALTER TABLE {s}categories ADD COLUMN public_slug TEXT")
    for row in await db.fetchall(f"SELECT id FROM {s}categories"):
        await db.execute(
            f"UPDATE {s}categories SET public_slug = :slug WHERE id = :id",
            {"slug": uuid.uuid4().hex, "id": row["id"]},
        )
    await db.execute(
        f"CREATE UNIQUE INDEX ux_categories_public_slug "
        f"ON {s}categories(merchant_id, public_slug)"
    )
    await db.execute(
        f"CREATE INDEX ix_products_merchant_category "
        f"ON {s}products(merchant_id, category_id)"
    )
    await db.execute(f"DROP INDEX {s}ix_products_merchant_catalog")
    await db.execute(
        f"UPDATE {s}outbox_events SET aggregate_type = 'categories' "
        "WHERE aggregate_type = 'catalogs'"
    )
    await db.execute(
        f"UPDATE {s}protocol_addresses SET domain_type = 'categories' "
        "WHERE domain_type = 'catalogs'"
    )


async def m010_import_drafts(db: Connection):
    s = db.references_schema
    int_t = db.big_int
    for column in ("import_source_kind", "import_source_instance", "import_legacy_id"):
        await db.execute(f"ALTER TABLE {s}products ADD COLUMN {column} TEXT")
    await db.execute(
        f"ALTER TABLE {s}products ADD COLUMN import_authorized BOOLEAN NOT NULL DEFAULT FALSE"
    )
    await db.execute(
        f"CREATE UNIQUE INDEX ux_products_import_identity ON {s}products"
        "(merchant_id, import_source_kind, import_source_instance, import_legacy_id)"
    )
    await db.execute(
        f"ALTER TABLE {s}categories ADD COLUMN import_review BOOLEAN NOT NULL DEFAULT FALSE"
    )
    await db.execute(
        f"CREATE UNIQUE INDEX ux_categories_import_review ON {s}categories"
        "(merchant_id) WHERE import_review = TRUE"
    )
    await db.execute(
        f"CREATE TABLE {s}catalog_imports ("
        "id TEXT PRIMARY KEY, merchant_id TEXT NOT NULL "
        f"REFERENCES {s}merchants(id) ON DELETE RESTRICT, "
        "source_kind TEXT NOT NULL, source_instance TEXT NOT NULL, "
        "source_hash TEXT NOT NULL, source_currency TEXT NOT NULL, "
        "commitment_json TEXT NOT NULL, commitment_id TEXT NOT NULL, "
        "state TEXT NOT NULL, product_count INTEGER NOT NULL, "
        f"created_at {int_t} NOT NULL, "
        "UNIQUE (merchant_id, source_kind, source_instance, source_hash))"
    )
    await db.execute(
        f"CREATE TABLE {s}import_rows ("
        "id TEXT PRIMARY KEY, import_id TEXT NOT NULL "
        f"REFERENCES {s}catalog_imports(id) ON DELETE RESTRICT, "
        "product_id TEXT NOT NULL "
        f"REFERENCES {s}products(id) ON DELETE RESTRICT, "
        "legacy_id TEXT NOT NULL, content_hash TEXT NOT NULL, "
        "UNIQUE (import_id, legacy_id))"
    )
