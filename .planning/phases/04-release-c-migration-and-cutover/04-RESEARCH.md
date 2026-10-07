# Phase 4: Release C — Migration and Cutover — Research

**Gathered:** 2026-10-07 · verified against the codebase, not recalled

## Verified schema facts

- **No `legacy_liability_qty` anywhere** — the column referenced by LEG-04
  does not exist. It must be introduced this phase (either as a product
  column or, more likely, a dedicated liabilities table; see below).
- **`inventory_reservations` exists** (`migrations.py` ~line 630): per-order
  reservation rows with `state` + `expires_at`; products carry
  `stock_on_hand`/`stock_reserved` with `CHECK (stock_reserved <= stock_on_hand)`.
  Partition (D-07) should reuse this accounting — a liability partition is a
  reservation-like hold that is not an order.
- **Products table**: `stock_on_hand`, `stock_reserved`, visibility flags,
  `category_id` nullable — flat/uncategorized imports (D-03) already fit.
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
- **Liabilities** derive from legacy *unpaid-but-payable* orders — the import
  file shape must let merchants supply pending orders (order_id, product_id,
  qty, invoice_ref/expiry); nostrmarket `orders` rows carry
  `invoice`/`paid`/`shipped` fields — define a simple JSON liabilities
  upload rather than parsing the live DB.

## Hazards

- **Upload size**: bound the multipart body (suggest ≤10 MB, count-limited
  rows); stream-parse CSV with the stdlib `csv` module — no new dependency.
- **Images**: NIP-15 image URLs are external URLs — import them as
  pending/external product images through the existing media path; never
  server-side fetch at import time (SSRF — matches D-04 spirit; fetch only
  through the already-validated media pipeline if it exists, else store URL
  for later merchant action).
- **Dedup**: `legacy_id` (legacy product id / d-tag / CSV handle) must be
  unique per merchant — re-upload = update-or-skip, never duplicate rows.
- **Single writer**: partition + reservations must serialize through the
  same stock path (DomainTransaction + `for_update`) — this is the whole
  point of LEG-05.
- **Cutover state machine**: states like `none → frozen → reconciling →
  complete` (+ abort path `frozen → none`); store on merchant settings or a
  dedicated `cutover` table row.
- **Manifest signing** (deferred decision): merchant key material already
  exists for NIP-99 signing — reuse it; manifest = canonical JSON of
  liability rows + catalog hash, signed as a kind-? event or detached
  Schnorr sig stored with the import record.
