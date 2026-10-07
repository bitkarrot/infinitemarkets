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

## Merchant Shopify reference (private upload + transient live shop, 2026-10-07)

- `/tmp/products_export.csv` parses as **619 CSV rows, 50 handles, 299 SKU/variant rows, 320 image-only rows, 814 image references / 595 distinct URLs**. All referenced URLs use `https://cdn.shopify.com` with version query `v`; do not log raw product/export data or commit the upload. Eight export handles returned 404 at the live store, so do not assume export status equals current visibility.
- The export uses classic Shopify `Handle`, `Body (HTML)`, `Variant Price`, `Image Src`, `Variant Image`, `Status` fields; `/tmp/product_template.csv` uses newer `URL handle`, `Description`, `Price`, `Product image URL`, `Variant image URL`, `Inventory quantity`. Neither source embeds image bytes. Real export has **no `Variant Inventory Qty`, currency, or stock-count proof**. `stock_on_hand=NULL` is unlimited in Infinite Markets; unknown physical stock must be 0 (blocked), then separately entered/verified before sellability. Source-currency selection is required; never guess USD from displayed store locale alone. Handle-grouping and distinct variant SKUs prevent image-only rows from creating bogus products.
- Current catalog cap was 16; user requested **20** and catalog/gallery/test code was updated separately. 20 handles have >12 images, 12 have >16, **5 have >20**, maximum 32. Preview must show overflow and require merchant choice (<=20) without silently discarding images. A stable order follows Image Position and source row order; variant-only images must remain associated with variants where possible. Descriptions contain untrusted HTML: sanitize before rendering as text/markdown.
- A bounded one-off operator backup fetched **595/595 distinct export images** into private `~/shopify-archive/images/` (~142 MB), with URL→file/handle/sha256 mapping in `~/shopify-archive/manifest.json`; this is **not** the import pipeline and does not authorize arbitrary URL fetching. For the second stage, ingest merchant-uploaded files+manifest with auth/quota/hash/type/path-traversal checks into `settings.lnbits_data_folder/images/infinitemarkets/` (host mounts the managed images directory at `/images` in `lnbits/app.py:189-192`) rather than storing uploads under extension code or requiring Blossom. Support explicit alternate Blossom destination only if its upload/auth lifecycle is implemented and verified.
- Playwright reference in `~/shopify-archive/screenshots/`: **42 live product pages × desktop/mobile** plus homepage/catalog desktop/mobile = 88 JPEGs, with eight 404 export handles noted in `screenshots-index.json`. `storefront-observation.json` records Shopify's dark charcoal RGB(36,40,51) / `#242833`, yellow button RGB(252,228,119), Inter-like text, 4-column 263px square product cards, rounded-16px images and logo-forward header/footer. Infinite Markets already supports merchant logo URLs, dark mode and gallery layout, but gallery grid is 3 columns at desktop (`gm-public.css:1883-1892`), and the current product checkout/variation controls are not Shopify's. A merchant-configurable 4-column compact mode/branding can approach this appearance without changing payment semantics or applying the style to other merchants.

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
