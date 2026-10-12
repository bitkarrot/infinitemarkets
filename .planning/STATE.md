---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: Core Commerce and Hardening
current_phase: "05"
current_phase_name: Correctness, Recovery, and Security Hardening
status: paused
stopped_at: F1–F6 source corrections verified and reviewed; 05-06 qualification/audit/live gates remain
last_updated: "2026-10-12T23:45:00+00:00"
last_activity: 2026-10-12
last_activity_desc: F4/F5/F6 fixed+reviewed, CI-01 root cause fixed; full make verify green both profiles; 05-06 gates open
progress:
  total_phases: 6
  completed_phases: 3
  total_plans: 24
  completed_plans: 17
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-10-11)

**Core value:** A merchant can sell one authoritative inventory safely through LNbits-backed web and Nostr flows without duplicate invoices, double allocation, or relay delivery being mistaken for payment truth.
**Current focus:** Phase 5 correctness/recovery/security hardening; milestone acceptance remains open.

## Current Position

Phase: 5 of 6 (Correctness, Recovery, and Security Hardening)
Plan: 05-06 qualification remains; 05-01/03 partial gates (host browser, RED chronology); WR-04 token follow-up open
Status: In progress — F1–F6 + CI-01 repaired and reviewed; 05-06 qualification, operator audit and live UAT remain
Last activity: 2026-10-12 — F4/F5/F6 + CI-01 repaired; make verify 982p/8s SQLite, 987p/3s PG, both natural exit0; independent review PASSED

Progress: 3 phase acceptance scopes closed, 2 reopened, 1 in progress. Phase 5 has six reviewed plans; 05-02 scoped tasks complete, financial source implemented, and 05-01/03 still partial. No overall
acceptance percentage is implied by plan/artifact counters. There are 17 executed plan
summaries plus 4 explicitly superseded/re-scoped Phase 4 disposition records;
21 summary files do not mean 21 original plans were executed. GSD may display
100% for that artifact ratio; it is not milestone acceptance or Phase 5 progress.

**Ad-hoc work since 03.1 (not phase-planned, committed + deployed, released as v0.1/v0.2/v0.3/v0.4/v0.5/v0.6/v0.6.1 and packaged for v0.6.2):** storefront filters + collection links; configurable index hero; dark/light shopper toggle; Messages list+thread redesign and counterparty kind-0 profiles; Publications timestamps/row detail, live relay catalog check, filters/sorting, and fresh kind-5 reissue; brand logo URL + footer copy; point-and-click Fine-tune + accent move; single-column merchant settings; primary-colored settings buttons; embeddable shop component (`gm-embed.js` + public products API + CORS), iframe embed with widened CSP, admin Embed snippets; About/More section + screenshots; outbox history prune control; Merchant Nostr Profile (avatar, bio, banner, NIP-05, Lightning address) and owner-only `nsec` reveal; redacted email previews + terminal-history cleanup; sortable Catalog columns and first-column quick actions; searchable country/EU shipping picker; LNbits-style Catalog tables and scrolling mobile section nav; Releases v0.1, v0.2, v0.3, v0.4, v0.5, v0.6, v0.6.1.

## Performance Metrics

**Velocity:**

- Executed plans with original summaries: 15
- Phase 4 historical plans dispositioned: 4 (not 4 original plans executed)
- Average duration: -
- Total execution time: 0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 1 | 3 | - | - |
| 2 | 4 | - | - |
| 3 | 4 | - | - |
| 03.1 | 3 | - | - |
| 4 | 4 historical disposition records | - | - |
| 5 | 6 reviewed; 3 plans complete (05-02/04/05), 2 partial (05-01 host browser, 05-03 chronology), 05-06 pending | - | - |

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
- GSD Phase 1 is the contract's P0 qualification gate; it contains no production runtime implementation.
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

- No loose files in `.planning/todos/pending/`; the shipping picker is already completed.
- This is not zero remaining work: HARD-01–08 are open in REQUIREMENTS.md and Phase 5; Phase 3 UAT item 17 remains pending.

### Release Closeout Gates

- [x] Current pre-fix CI observed: run 38194415581 on `a7082c7`, all four Linux SQLite/PostgreSQL profiles plus lint passed. This does not test all F1–F6 regressions.
- [x] Existing account/catalog delivery checked: 70 passed, 1 optional private-Shopify-sample skip, process exit 0; lint passed.
- [x] Historical Phase 4 cutover plans explicitly dispositioned; no removed feature is reinstated.
- [x] F1–F6 fixed and permanently regression-tested on both DB profiles; reopened security threats mitigated per local review — threat closure still gated on 05-06 qualification.
- [x] CI-01 paired-test lifecycle fixed: root cause (cancelled engine checkout orphaning aiosqlite worker thread) demonstrated; bounded subprocess regression + both orders + full suites exit0.
- [x] Fresh repaired-revision database/platform evidence recorded (SQLite 982/8s, PG 987/3s exit0; evidence bundle regenerated). Browser/conformance items tracked separately under open gates.
- [ ] Operator read-only historical paid-order audit authorized and performed before production exposure, record disposition or release; NONE performed during synthetic implementation.
- [ ] Phase 3 live Plebeian checkout/payment UAT completed with operator authorization; only listing smoke is recorded so far.

### Blockers/Concerns

- F1–F6 source corrections pass local runtime + independent review (05-REVIEW.md); CI-01 root cause fixed with process-exit regression; full make verify green both profiles; pushed to origin/main (eaf7d64) for the four-profile CI matrix. 05-06 gates remain: pinned-host browser errors, WR-01 chronology, live Plebeian, release clearance.
- WR-04 token revocation boundary RESOLVED (locked presented-token recheck on status/opt-out/claim; regressions both DBs).
- Historical paid-order audit: authorized read-only scan complete — zero actual order records in any reachable local datastore; remote/deployed instance audit remains an operator gate if one exists.
- WR-04: pre-existing in-flight token rotation/expiry race remains MEDIUM / OPEN / NOT FIXED / NOT WAIVED; no fresh revoked-token admission after committed rotation demonstrated. Separate authorization follow-up before broader security clearance.
- F1 pinned-host admin pageerrors and F2 original browser RED chronology remain open; do not turn scoped source GREEN into plan/phase/release acceptance.
- Security configuration remains unchanged: ASVS level 1, enforcement enabled, block on high. Old zero-open-threat claims are superseded, not treated as waivers.
- CI-01 is test infrastructure debt, not evidence of a production teardown defect; do not call a timed-out test process successful.
- Phase 2 visual-token/screenshot recommendations remain non-blocking UX follow-ups. No further demo reset, old-data migration or live-funds test is authorized by this closeout.
- Release B still needs its live external checkout evidence and operator egress controls for broader deployment claims.
- Release C is catalog-only; old-store stock coordination remains operator-managed. Kind-5 deletion cannot compel a relay/client to remove public data.

### Roadmap Evolution

- 2026-10-11: user chose hardening first. Phase 5 added for F1–F6, CI-01 and release/security evidence; optional integrations and shipping-import expansion deferred.

- Phase 03.1 inserted after Phase 3: Buyer accounts — email magic-link sign-in and Nostr identity linking
- Phase 4 revised: LEG-01/02 and old-system cutover LEG-04/05 dropped; active LEG-03/06 cover catalog-only file import/export, hidden draft review and normal publication.

## Deferred Items

| Category | Item | Status | Deferred At | Milestone |
|----------|------|--------|-------------|-----------|
| Integrations | External inventory/shipping authority and shipping import/binding | Deferred until hardening | 2026-10-11 | Future |
| Contracts | S1 entitlement policy; S2 identifiers/history; S3/S4 observability and cleanup | Retained follow-ups in root FUTURE-ROADMAP.md | 2026-10-11 | After blocking repairs |
| Accounts | Identity unlink and notification-preference expansion | Out of delivered scope | Buyer-account delivery | Future |
| Protocol | NIP-37 draft synchronization | Deferred | Initialization | v2 |
| Commerce | Subscriptions, preorder purchasing, automated refunds | Deferred | Initialization | v2 |
| Transport | `nostrclient`/`nostrrelay` runtime adapters | Qualification required | Initialization | Future |

## Session Continuity

Last session: 2026-10-12
Stopped at: F4–F6/CI-01 tranche committed locally; pause before 05-06 qualification work
Resume file: .planning/phases/05-correctness-recovery-and-security-hardening/05-REVIEW.md
