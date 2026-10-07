# Phase 4: Release C — Migration and Cutover - Context

**Gathered:** 2026-10-07
**Status:** Ready for planning

## Phase Boundary

Import-and-cutover only. Merchants bring an existing catalog onto Infinite
Markets (nostrmarket JSON/Nostr events + e-commerce CSV exports), reconcile
every still-payable legacy liability before imported stock becomes sellable,
and prove via an automated scarce-stock rehearsal that a legacy unpaid
invoice and the new catalog can never allocate the same physical unit twice.

Live NIP-15/NIP-04 protocol interop is **out of scope** — LEG-01 and LEG-02
were dropped in the Phase-4 scope amendment. The legacy surface is treated as
data to migrate, not a protocol to speak.

Requirements: LEG-03, LEG-04, LEG-05 (all Pending).

## Implementation Decisions

### Import pipeline
- **D-01:** Imported products land as **drafts**; the merchant reviews and
  publishes them through the normal create/validate/publish path. No
  auto-publish, no surprise relay traffic.
- **D-02:** Legacy identifiers are preserved as **metadata** on the imported
  product rows (legacy_id / source marker columns) so cutover and audit can
  trace back. New NIP-99 publications get fresh `d` tags — we do not rewrite
  or collide with legacy publications.
- **D-03 (revised for current schema):** Do not map legacy stalls to categories/collections or zones to shipping. The existing product schema requires a category; place imported drafts in one idempotently created, merchant-scoped **Imported — review** holding category (both Gamma and NIP-15 publication disabled). This is an organizational placeholder, not a legacy-structure mapping. The merchant chooses a final category before publishing; provide a guarded recategorization action because product PATCH does not currently allow category changes. Preserve only allowlisted, non-sensitive legacy metadata.
- **D-04:** Import sources are **file uploads only** — nostrmarket JSON / Nostr event dumps (kind-30017 stalls, kind-30018 products) and e-commerce CSV (Shopify format first). Never URL fetch, never arbitrary path or legacy database access, never persist private-key material (LEG-03 hard requirement).
- **D-05:** CSV column mapping uses **persisted presets**: a built-in Shopify
  preset plus merchant-named custom presets saved per merchant, extensible
  toward WooCommerce.
- **D-06:** Import UI is a **new admin nav section "Migration"** — room for
  the import wizard (upload → preview → validate → dry-run → execute →
  audit) and the cutover dashboard.

### Cutover
- **D-07 (safety clarification):** Merchant starts cutover manually, but the new app **cannot freeze the old extension**. The operator must stop old intake at its source and attest with auditable evidence; no imported product is publishable/sellable before a complete post-freeze liability snapshot is verified. Per payable invoice: **wait** (unsellable until verified terminal evidence), **partition** (reserve its quantity against the shared physical count so only surplus may sell), or **cancel/reconcile** (only after evidence that it cannot be paid, or consume stock if already paid). A local button must never imply that a Lightning invoice was cancelled. Unknown/unverifiable invoices fail closed.
- **D-08 (safety clarification):** Cutover restrictions apply only to imported products, not the existing native catalog. Imported products remain draft and unavailable until the old intake freeze and liability snapshot are verified; while reconciling, each imported product is blocked until its still-payable liabilities are fully partitioned or verified terminal. Partitioned liabilities may remain after cutover completion but their holds persist and continue to count against stock until verified settlement/expiry.
- **D-09 (safety clarification):** Operator may abort before completion, but abort is **fail-closed**: imported products remain draft/unavailable, and partitions are retained while any legacy invoice could still settle. Release holds only when their corresponding liability is verified terminal; do not re-enable legacy intake through this app. Re-running after a completed cutover creates a new audited cutover epoch.
- **D-11:** A liability snapshot must be complete and attributable to a stopped old intake. For same-instance nostrmarket, verify wallet ownership and invoice status through a narrow, authorized LNbits host payment lookup, never via arbitrary extension DB/path/URL input. External sources lacking authoritative, checkable freeze and invoice evidence may preview/import drafts but cannot pass the sellability gate. An operator assertion alone is not cryptographic proof of completeness; document the trust boundary and fail closed where completeness is unknown. Ongoing safety assumes the legacy operator keeps intake disabled; reactivation detected by periodic checks must re-block imported sales, but the extension cannot enforce a remote operator's future behavior.

### Verification
- **D-10 (testable guarantee):** LEG-05 is an automated two-part rehearsal: (1) a real web/Gamma integration test shows freeze blocks both checkout paths while the old invoice can still be paid and surplus can sell only after the verified partition, and (2) a real-transaction contention test invokes the shared stock-allocation primitive from independent connections so both contenders reach the conditional stock write. Do not call an early-rejected checkout a concurrency race. Repeat on SQLite and PostgreSQL.

### Claude's Discretion
- **Liability manifest signing (resolved):** Sign a hash-only, canonical commitment to the allowlisted import rows, source snapshot and each liability's hashed invoice reference/qty using the existing `keystore.sign_event` API and a versioned, unpublished Nostr event. Record event id, pubkey, signature and signed content for verification. No plaintext invoice references, keys, raw uploads or buyer PII in the manifest or log. The signature proves integrity and author approval, **not** completeness or payment status; the cutover gate requires separate authoritative evidence.

## Canonical References

**Downstream agents MUST read these before planning or implementing.**

- `.planning/ROADMAP.md` — Phase 4 scope, plans 04-01/04-02/04-03, execution order
- `.planning/REQUIREMENTS.md` — LEG-03 (lines ~73), LEG-04, LEG-05 + scope-amendment note
- `.planning/REQUIREMENTS.md` scope amendment — LEG-01/02 dropped (no NIP-15 live interop, no NIP-04)
- `infinitemarkets/models.py`, `infinitemarkets/migrations.py` — product category is required; `legacy_liability_qty` is not a column yet
- `infinitemarkets/services/catalog.py` — validation, draft creation and category/pub gates; importer needs a transaction-aware draft primitive rather than nested `create_product` transactions
- `infinitemarkets/services/outbox.py`, `infinitemarkets/services/relay.py` — publication machinery (draft landing = no outbox entries)
- `infinitemarkets/migrations.py` — migration style for new tables (imports, import_rows, liability manifests, csv_presets, partitions)
- `infinitemarkets/views_api.py` — admin API patterns + per-merchant auth
- `tests/e2e/` — e2e harness + seeded demo merchant for rehearsal test
- `/home/exedev/lnbits/lnbits/extensions/nostrmarket/` — legacy data shapes (stalls, products, zones tables; NIP-15 event structure) for importer fixtures. **Not** a runtime dependency — all its tables are empty on this instance; import is from exported files only.
- The `inventory` extension is confirmed **unrelated** to nostrmarket — no imports, no shared tables. Do not integrate it in this phase.

## Notes for researcher/planner

- `legacy_liability_qty` does not exist; use a per-invoice/item liabilities table with derived outstanding quantity. A source snapshot must include **all** still-payable old invoices, not just a merchant-selected subset; verify freeze/enumeration before sellability, otherwise fail closed.
- `inventory_reservations.order_id` is non-null and references this extension's orders. Use a distinct liability-partition row but the **same conditional stock update and transaction lock order** as checkout. Legacy settlement consumes physical stock and releases the hold in one transaction; verified unpaid terminality releases the hold without consuming.
- Imported draft status and cutover status both gate publish and web/Gamma checkout. No `publish`/bulk-edit/stock-change escape route. The import marker is persistent across re-import and audit.
- nostrmarket tables are empty here — fixtures needed. Its paid callback updates its own product quantity (not Infinite Markets), so the new ledger must reconcile that stock transition once; do not silently rely on the legacy callback for shared-stock correctness.
