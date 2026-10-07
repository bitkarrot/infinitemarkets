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
- **D-03:** Legacy structures are **not** mapped onto our catalog model.
  Stalls do not become categories/collections; zones do not become shipping
  options. Products land uncategorized (flat import); zone data is kept as
  metadata notes only. The merchant organizes after import.
- **D-04:** Import sources are **file uploads only** — nostrmarket JSON /
  Nostr event dumps (kind-30018 stalls, kind-30019 products) and e-commerce
  CSV (Shopify format first). Never URL fetch, never arbitrary path or
  database access, never private-key material (LEG-03 hard requirement).
- **D-05:** CSV column mapping uses **persisted presets**: a built-in Shopify
  preset plus merchant-named custom presets saved per merchant, extensible
  toward WooCommerce.
- **D-06:** Import UI is a **new admin nav section "Migration"** — room for
  the import wizard (upload → preview → validate → dry-run → execute →
  audit) and the cutover dashboard.

### Cutover
- **D-07:** Freeze is a **manual admin action**. For each still-payable
  `legacy_liability_qty` the merchant chooses per item: **wait** (block until
  expiry/settlement), **force-cancel**, or **partition** (reserve qty against
  imported stock until the liability resolves). All three modes exist.
- **D-08:** Freeze is **scoped to imported products only** — the rest of the
  catalog keeps selling normally during reconciliation.
- **D-09:** Cutover is **reversible until completion** — unfreeze releases
  partitions and resumes intake; after liability resolution completes,
  starting over counts as a new cutover.

### Verification
- **D-10:** LEG-05's scarce-stock rehearsal is an **automated test** (runtime
  or e2e suite), not a manual runbook — simulating an unpaid legacy invoice
  and a new-catalog sale racing on the last unit. Repeatable in CI.

### Claude's Discretion
- **Liability manifest signing:** user deferred ("you decide"). Lean toward
  a Nostr-signed manifest — the extension already holds merchant signing
  material and an outbox/event model — with per-liability rows (invoice ref,
  item, qty, resolution) plus a catalog snapshot hash, verifiable as audit
  evidence. Planner may pick hash-only DB rows if signing doesn't fit the
  existing audit model cleanly.

## Canonical References

**Downstream agents MUST read these before planning or implementing.**

- `.planning/ROADMAP.md` — Phase 4 scope, plans 04-01/04-02/04-03, execution order
- `.planning/REQUIREMENTS.md` — LEG-03 (lines ~73), LEG-04, LEG-05 + scope-amendment note
- `.planning/REQUIREMENTS.md` scope amendment — LEG-01/02 dropped (no NIP-15 live interop, no NIP-04)
- `infinitemarkets/models.py` — product DTOs, `legacy_liability_qty` field if present
- `infinitemarkets/services/catalog.py` — normal create/validate/publish path imports must flow through
- `infinitemarkets/services/outbox.py`, `infinitemarkets/services/relay.py` — publication machinery (draft landing = no outbox entries)
- `infinitemarkets/migrations.py` — migration style for new tables (imports, import_rows, liability manifests, csv_presets, partitions)
- `infinitemarkets/views_api.py` — admin API patterns + per-merchant auth
- `tests/e2e/` — e2e harness + seeded demo merchant for rehearsal test
- `/home/exedev/lnbits/lnbits/extensions/nostrmarket/` — legacy data shapes (stalls, products, zones tables; NIP-15 event structure) for importer fixtures. **Not** a runtime dependency — all its tables are empty on this instance; import is from exported files only.
- The `inventory` extension is confirmed **unrelated** to nostrmarket — no imports, no shared tables. Do not integrate it in this phase.

## Notes for researcher/planner

- `legacy_liability_qty` is referenced in REQUIREMENTS but may not exist in
  the schema yet — planner must decide where liabilities live (likely an
  `imported_liabilities` table tied to imported products).
- Partition reserves `legacy_liability_qty` against imported stock the same
  way order reservations work — reuse the reservation model if possible to
  keep single-writer allocation guarantees.
- The "import marker" on products (D-02/D-08) is what freeze scoping and
  liability tracing key off.
- nostrmarket's own tables are empty on this instance — fixtures needed.
