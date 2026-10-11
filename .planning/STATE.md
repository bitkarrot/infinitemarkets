---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
current_phase: 04
current_phase_name: Release C — Catalog Import and Export
status: complete
stopped_at: Release C and post-release merchant operations verified; preparing v0.6.1 release
last_updated: "2026-10-10"
last_activity: 2026-10-09
last_activity_desc: Catalog-only import/export, merchant profile controls, email history tooling, message profiles, live relay reconciliation, and fresh kind-5 tombstone reissue verified
progress:
  total_phases: 5
  completed_phases: 5
  total_plans: 18
  completed_plans: 18
  percent: 100
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-10-09)

**Core value:** A merchant can sell one authoritative inventory safely through LNbits-backed web and Nostr flows without duplicate invoices, double allocation, or relay delivery being mistaken for payment truth.
**Current focus:** v1 roadmap complete; operational hardening, marketplace interoperability, and merchant UX maintenance.

## Current Position

Phase: 4 (Release C — Catalog Import and Export) — COMPLETE
Status: Phases 1, 2, 3, 03.1, and 4 complete; legacy freeze/reconciliation plans remain superseded historical records
Last activity: 2026-10-09 — catalog-only workflow verified, live relay reconciliation/tombstone reissue deployed, Publications UX hardened, v0.5 released, Catalog tables restyled, v0.6 released, and v0.6.1 Catalog badge fix packaged

Progress: [██████████] 100% of roadmap phases (5/5)

**Ad-hoc work since 03.1 (not phase-planned, committed + deployed, released as v0.1/v0.2/v0.3/v0.4/v0.5/v0.6 and packaged for v0.6.1):** storefront filters + collection links; configurable index hero; dark/light shopper toggle; Messages list+thread redesign and counterparty kind-0 profiles; Publications timestamps/row detail, live relay catalog check, filters/sorting, and fresh kind-5 reissue; brand logo URL + footer copy; point-and-click Fine-tune + accent move; single-column merchant settings; primary-colored settings buttons; embeddable shop component (`gm-embed.js` + public products API + CORS), iframe embed with widened CSP, admin Embed snippets; About/More section + screenshots; outbox history prune control; Merchant Nostr Profile (avatar, bio, banner, NIP-05, Lightning address) and owner-only `nsec` reveal; redacted email previews + terminal-history cleanup; sortable Catalog columns and first-column quick actions; searchable country/EU shipping picker; LNbits-style Catalog tables and scrolling mobile section nav; Releases v0.1, v0.2, v0.3, v0.4, v0.5, v0.6.

## Performance Metrics

**Velocity:**

- Total plans completed: 18
- Average duration: -
- Total execution time: 0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 1 | 3 | - | - |
| 2 | 4 | - | - |
| 3 | 4 | - | - |
| 03.1 | 3 | - | - |
| 4 | 4 historical records | - | - |

**Recent Trend:**

- Last 5 plans: none
- Trend: Not established

*Updated after each plan completion*
**Per-Plan Metrics:**

| Plan | Duration | Tasks | Files |
|------|----------|-------|-------|
| Phase 1 P01 | 20 min | 3 tasks | 23 files |
| Phase 01 P02 | 21 min | 3 tasks | 15 files |
| Phase 01 P03 | ~50 min | 3 tasks | 25 files |
| Phase 02 P01 | multi-session | 3 tasks | 18 created + 4 modified |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md and the normative specification.

- Runtime identity is `infinitemarkets`.
- Direct qualified `nostr-sdk` is the baseline; other relay extensions are unqualified adapter candidates.
- GSD Phase 1 is the contract's Phase 0 evidence gate; it contains no production runtime implementation.
- Release order is A web commerce, B Gamma NIP-17, C catalog import/export with drafts; no old-system migration gate.
- Checkout preserves Editorial/Guided/Compact merchant presets with responsive mobile fallback and invariant payment semantics.
- Merchant order operations use a split list/detail workspace with embedded chronology.
- Public themes use preset, Brand Basics, and guarded Advanced Tokens tiers; admin styling stays host-controlled.
- Phase 2 UI planning must load `.devin/skills/sketch-findings-infinitemarkets/` and produce a binding UI contract.
- [Phase 1]: Plan 01-01 shipped the permanent qualification harness: pins/provenance (P0-01), SDK security boundary (P0-02), host contract boundary (P0-03), one canonical make verify + evidence bundle, CI blocking matrix. — Everything later phases build depends on the pinned host/SDK/database contract being proven reproducible; the harness is permanent regression infrastructure (D-05), not disposable qualification code.
- [Phase 1]: PG queue claims run as lock-select/update/fetch in one transaction with FOR UPDATE SKIP LOCKED: SQLAlchemy 1.4 + asyncpg returns no rows from raw text() UPDATE...RETURNING (01-02)
- [Phase 1]: Idempotent intent inserts use ON CONFLICT DO NOTHING with deterministic ids: PostgreSQL aborts transactions on constraint violations, so IntegrityError catch-and-continue is not dialect-portable (01-02)
- [Phase 1]: Outbox publication evidence is durable and append-only, recorded separately from the fenced claim-token outcome write: models the section 8.6 crash point and makes stale-claim reconstruction honest (01-02)
- [Phase 1]: Cancelled orders retain their payment projection for late-settlement detection; BOLT11 delivery and payment-request enqueue happen only for invoice_pending orders (spec 8.2 step 3, decision 24)
- [Phase 2]: Host `deactivate_all` is a persisted editable admin setting — runtime fixtures must reset it in the shared core DB, and `sys.modules` must be purged before re-import so `Database()` binds the right data folder (02-01)
- [Phase 2]: Host `rewrite_values` HTML-strips raw execute/fetch params — markdown/JSON payloads only persist via `insert`/`update` or DomainTransaction raw statements (02-01)
- [Phase 2]: Cookie auth wins when a request carries both cookie and bearer headers — prevents bearer bypass of Origin/CSRF (02-01)
- [Phase 2]: Kind-5 tombstone intents carry the bumped aggregate revision so supersession retires stale pending publishes; product intents enqueue AFTER collection republishes so dependency edges bind to live rows (02-01)

### Pending Todos

- None. Country-name and EU-zone shipping picker completed (`.planning/todos/completed/2026-10-08-select-shipping-countries-and-zones-by-name.md`).

### Release Closeout Gates

- [x] Current implementation CI passed lint and Linux x86_64/ARM64 SQLite/PostgreSQL qualification: run 36352552899 on `021c402`.
- [x] Human buyer/merchant UAT passed 3/3; security/accessibility review is verified with 26/26 threats closed.
- [x] Nyquist validation covers all 16 Phase 2 requirements; UI review found no blocker.
- [x] At the user's request, the 5099 demo was replaced with a fresh seed; quote and buyer/admin browser checks passed. Old disposable database files were not deleted, but are not mounted in the new demo.

### Blockers/Concerns

- Phase 2 has no remaining blocker. Typography/spacing token consolidation and durable visual snapshot baselines are non-blocking UI recommendations in `02-UI-REVIEW.md`.
- The new demo uses a fresh disposable database rather than migrating old demo orders and the previously hand-added images. If those records must remain visible, the old database requires a separate recovery plan.
- Release B cannot claim full production interoperability without deployed egress controls and external-client evidence.
- Release C provides catalog-only import/export; it does not reconcile old invoices or freeze another store. Operators must avoid selling the same physical units elsewhere independently.
- Kind-5 deletion is a relay request. The live relay check detects stale deleted copies, and reissue sends fresh tombstones, but relays/clients can still ignore NIP-09.

### Roadmap Evolution

- Phase 03.1 inserted after Phase 3: Buyer accounts — email magic-link sign-in and Nostr identity linking
- Phase 4 revised: LEG-01/02 and old-system cutover LEG-04/05 dropped; active LEG-03/06 cover catalog-only file import/export, hidden draft review and normal publication.

## Deferred Items

| Category | Item | Status | Deferred At | Milestone |
|----------|------|--------|-------------|-----------|
| Protocol | NIP-37 draft synchronization | Deferred | Initialization | v2 |
| Commerce | Subscriptions, preorder purchasing, automated refunds | Deferred | Initialization | v2 |
| Transport | `nostrclient`/`nostrrelay` runtime adapters | Qualification required | Initialization | Future |

## Session Continuity

Last session: 2026-10-09
Stopped at: v1 roadmap and Phase 4 verified; preparing the v0.6.1 release artifacts and manifest
Resume file: .planning/phases/04-release-c-migration-and-cutover/04-VERIFICATION.md
