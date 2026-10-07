# Phase 4: Release C — Migration and Cutover — Research

**Gathered:** 2026-10-07 · verified against the codebase, not recalled

## Verified schema facts

- **No `legacy_liability_qty` anywhere** — the quantity referenced by LEG-04 is not a column. Derive outstanding quantity from a dedicated per-invoice/item liabilities table; do not add a mutable counter detached from invoice evidence.
- **`inventory_reservations` exists** (`migrations.py:630-645`): `order_id NOT NULL` FK to this extension's orders; it cannot directly hold old liabilities. Products carry `stock_on_hand`/`stock_reserved` with `CHECK (stock_reserved <= stock_on_hand)`. Make a separate liability-partition table, with conditional `stock_reserved += qty` in the same transaction/lock discipline as order reservations (`checkout.py:1060-1103`).
- **Products require a category**: `catalog_id NOT NULL` in m001, renamed to `category_id` in m009; `models.Product.category_id: str`, `create_product` rejects empty category, and public listings inner-join categories. D-03 now uses an idempotent merchant-scoped holding category plus a recategorize-before-publish flow (`migrations.py:113-119,1234-1239`; `catalog.py:823-833`; `views.py:359-368`).
- Every multi-statement write goes through `DomainTransaction` with
  `{s}`/`{int_t}`/`{blob_t}` dialect helpers (SQLite + Postgres both live).
- New tables = new `m0NN_*` function appended to the explicit migration list;
  `keystore_env` tests boot by explicit import — forgetting the list entry
  silently skips the migration (Phase 03.1 pitfall).

## Legacy source shapes (from nostrmarket @ /home/exedev/lnbits)

- **NIP-15 stall** = kind `30017`, `["d", stall_id]` tag; content:
  `{id, name, description, currency, shipping}`.
- **NIP-15 product** = kind `30018`, `["d", id]` + `["t", cat]` tags; content:
  `{id, stall_id, name, description, images[], currency, price, quantity,
  active, shipping[]}`.
- **Deletion** = kind `5` — imports must ignore kind-5 (deleted products).
- nostrmarket local tables (stalls/products/zones/orders) are **empty on this
  instance**; `inventory` extension is confirmed unrelated — no imports,
  no shared tables. Import is file-upload only (D-04): accept (a) a JSON
  event dump (array or NDJSON of signed NIP-15 events), (b) a nostrmarket
  JSON export of stalls/products/orders, (c) Shopify CSV.
- **Liabilities** derive from legacy unpaid-but-payable orders. nostrmarket `orders` stores `order_items` JSON, `invoice_id` (payment hash), `paid`, `shipped`, and `time` (`nostrmarket/migrations.py:75-94`). Old order intake is controlled by `merchant.config.active` (`nostrmarket/services.py:483-493`), independent of this extension; the toggle endpoint is `nostrmarket/views_api.py:246-259`. The old paid callback decrements nostrmarket product stock without a lock (`nostrmarket/services.py:174-184,222-240`). Neither an uploaded subset nor a signed file proves all payable invoices were captured.
- **Host payment evidence (same-instance only)**: `lnbits/core/crud/payments.py:71-85` has wallet-scoped `get_wallet_payment(wallet_id, payment_hash)` and `lnbits/core/services/payments.py:641-656` checks funding-source invoice status. Verify wallet ownership and enumerate all in-scope legacy tagged payments/old orders through an authorized, bounded interface before asserting snapshot completeness. This is not permission to query arbitrary extension tables or other wallets. A missing record, unverifiable remote wallet, ambiguous status, or unconfirmed old freeze must block activation; operator attestation alone is not authoritative proof.

## Hazards

- **Upload size**: bound the multipart body (suggest ≤10 MB, count-limited
  rows); stream-parse CSV with the stdlib `csv` module — no new dependency.
- **Images**: NIP-15 image URLs are external URLs — import them as
  pending/external product images through the existing media path; never
  server-side fetch at import time (SSRF — matches D-04 spirit; fetch only
  through the already-validated media pipeline if it exists, else store URL
  for later merchant action).
- **Dedup**: key on `(merchant_id, source_kind, source_instance, legacy_id)` rather than legacy_id alone. Re-upload is idempotent: never mutate published, held, or previously imported stock silently; pin normalized row hashes across preview and execute. Uploaded raw bytes and unexpected JSON fields must never be retained.
- **Single writer**: partition + order reservations must use a shared conditional product stock update with common merchant/product lock order in DomainTransaction, including a row lock on PostgreSQL; `_resolve_items` runs before the saga and is NOT the authoritative place to check cutover (`checkout.py:233-269,1060-1103`). Both web and Gamma enter the saga (`checkout.py:723-772,1491-1492`).
- **Publication escapes**: `catalog.bulk_products(..., action='publish')` flips draft and enqueues (`catalog.py:1172-1229`); `merchant.publish` enumerates all products (`merchant.py:482-494`); patch and stock projections may also enqueue. Gate all publish/visibility paths and checkout against cutover status, with an explicit product hold until verified snapshot and either terminal liability or partition.
- **Cutover state**: `staged → freeze_requested → snapshot_verified → reconciling → ready/complete`; abort returns to a **blocked** state and retains payable partitions, never to unguarded intake. Partitioned invoices remain outstanding but covered; settlement consumes stock+hold atomically, verified unpaid terminality releases only the hold. A merchant-supplied expiry timestamp alone is not evidence.
- **Rehearsal**: frozen imported products cannot reach a checkout stock write; test freeze rejection separately and test the shared conditional allocation primitive under actual concurrent transactions. Do not mislabel an early checkout rejection as a race.
- **Manifest signing**: keystore only exposes `sign_event(merchant_id, UnsignedEvent)` (`keystore.py:201-208`). Sign an unpublished versioned Nostr event committing to sorted salted/merchant-scoped invoice-reference digests, quantities and source/catalog hashes; verify the event signature. This proves integrity, not invoice completeness or status. Never publish or persist sensitive raw data in the manifest.
