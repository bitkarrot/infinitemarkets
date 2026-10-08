# Phase 04 — Migration & Cutover Verification

**Historical verification, superseded 2026-10-08:** The original cutover experiment and its results below describe code that was later removed. They are not evidence that current imports perform an old-invoice audit. Current CSV/JSON product imports create hidden drafts for merchant review and ordinary Catalog publication; no cutover/stock-count gate remains. See `docs/technical-specification.md` §13.

Date: 2026-10-07. Scope: LEG-03..06. Local qualification only — **no live
cutover, deployment, or push of the freeze gate has occurred.**

## Observed evidence

### Import → attested activation → guarded sale (Shopify/native)

- `test_shopify_attested_activation_and_stock_gate`: real 3-product
  Shopify CSV → preview → execute (blocked drafts) → stage →
  `POST /cutovers/{id}/attest` → epoch `complete`. Product PATCH to
  `draft=false` is still 409 until `POST /products/{id}/stock-count` —
  attestation alone never sells stock. Second attest is idempotent.
- `test_attest_rejects_nostrmarket_and_liability_imports`: attestation is
  409 for nostrmarket imports (with or without orders — the same-instance
  settlement surface exists regardless) and for any import carrying a
  liability row.
- `test_export_reimport_and_attested_activation`: export → parse →
  verify preamble marker, variant `parent_handle`/`option_N=Size=L`
  round-trip, `'` formula-escape → native preview → execute → stage →
  attest → complete.

### Verified cutover (nostrmarket, same instance)

- Full lifecycle verified in `test_cutover.py` (16 tests) and
  `test_cutover_rehearsal.py` (4 tests), on **both** SQLite and Docker
  PostgreSQL 18: disable+restart attestation, pinned source-contract hash
  (real installed nostrmarket @ `d941f0a`, code hash `24759dc4…`),
  Nostr-signed post-freeze snapshot, per-liability wait/partition/
  reconcile, exactly-once terminal transitions, completion gate,
  abort-retains-holds, leased background reconcile pass, and re-block on
  source reactivation or contract drift.
- Re-block applies **only** to nostrmarket-sourced epochs — a reactivated
  old extension cannot disturb a completed Shopify/native attestation.

### Scarce stock (LEG-05)

- `test_scarce_stock_guard_and_surplus`: stock=1 + payable qty=1 —
  completion and checkout are both refused while unpartitioned; after
  partition + completion + count, `stock_reserved=1` and the held unit
  cannot sell (422). stock=2 + qty=1 — the single surplus unit sells,
  the second unit stays partitioned.
- `test_shared_stock_primitive_contention`: two concurrent
  `checkout.checkout` transactions both resolve items before either
  writes; exactly one wins, loser gets `insufficient-stock` (422), no
  invoice minted, `stock_reserved ≤ stock_on_hand`. A raw write without
  the capacity predicate is refused by the schema CHECK constraint —
  the guard is belt-and-suspenders.
- `test_unpaid_terminal_releases_hold_exactly_once` /
  `test_paid_terminal_consumes_hold_exactly_once`: release/consume are
  exactly-once; repeated reconcile is a no-op.

### Media + storefront

- `test_media_upload_and_relink` / `_rejects_foreign_and_mismatched`:
  manifest-scoped sha256-verified upload, JPEG/PNG/WebP sniffing,
  content-addressed storage in host `data/images/infinitemarkets/<ns>/`,
  relink rewrites owned URLs only; foreign URLs and hash mismatches are
  rejected.
- `test_lightnin_dark_storefront_profile`: `lightnin-dark` preset +
  `storefront.grid=quad` + `hero_hidden` + `footer.logo_url` persist,
  render `data-grid="quad"`, suppress the hero, and emit `#242833` /
  `#fce477` tokens; invalid grid values are 422.
- `tests/e2e/cutover-rehearsal.mjs` (run against seeded e2e host):
  export preamble verified over HTTP; desktop 1440 renders 4 columns,
  mobile 390 renders 2, hero toggle round-trips.

## Commands run

- `make lint` — clean (ruff).
- `uv run pytest tests/runtime` — 445 passed, 4 skipped (SQLite).
- `uv run pytest tests/runtime/test_cutover.py
  tests/runtime/test_migration_import.py
  tests/runtime/test_cutover_rehearsal.py
  tests/runtime/test_migration_export_media.py` under
  `LNBITS_DATABASE_URL=postgres://lnbits:lnbits@localhost:5432/lnbits`
  (docker `postgres:18`) — all pass.
- `node tests/e2e/cutover-rehearsal.mjs` — all checks pass.

## Honest limitations / residual risk

- **No live cutover has been rehearsed.** The real nostrmarket disable +
  LNbits restart is an operator action and has not been performed; all
  freeze evidence in tests is mocked or fixture-driven.
- Shopify CSVs contain no inventory quantities and no payable-invoice
  surface — imported stock is *declared, not verified*, and activation is
  merchant-attested rather than cryptographically proven. The physical
  stock count gate is the only stock authority for these sources.
- The merchant media upload is API-level; a browser batch UI for
  hundreds of images is not built (operator scripting expected).
- `import_authorized` is now only settable via epoch completion — it is
  still not sufficient alone to sell (release predicate also requires
  `stock_counted_at`).
