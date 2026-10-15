---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: Core Commerce and Hardening
current_phase: "05"
current_phase_name: Correctness, Recovery, and Security Hardening
status: milestone-closed
stopped_at: product release v1.0.0 tagged and published 2026-10-13; v1.0 milestone archived
last_updated: "2026-10-15T03:00:00+00:00"
last_activity: 2026-10-15
last_activity_desc: product releases through v1.0.10 published (dismissable keyfile warning, category moves, collection counts, publish + inbox indicators)
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
Plan: milestone v1.0 archived and tagged 2026-10-13 (commit 3c0ad9a); next milestone unplanned — deferred scope candidates noted in ROADMAP
Status: milestone v1.0 shipped; product releases through v1.0.10 cut 2026-10-15 — all Phase 5 gates closed or operator-disposed
Last activity: 2026-10-15 — v1.0.10 published: dismissable keyfile warning (ack sidecar), product/bulk category moves, collection product counts, not-live catalog banner, Nostr inbox enable card; Devin Review fixes landed on both PRs

Progress: 3 phase acceptance scopes closed, 2 reopened, 1 in progress. Phase 5 has six reviewed plans; all plan gates closed or operator-disposed as of 2026-10-13. No overall
acceptance percentage is implied by plan/artifact counters. There are 17 executed plan
summaries plus 4 explicitly superseded/re-scoped Phase 4 disposition records;
21 summary files do not mean 21 original plans were executed. GSD may display
100% for that artifact ratio; it is not milestone acceptance or Phase 5 progress.

**Ad-hoc work since 03.1 (not phase-planned, committed + deployed, released as v0.1/v0.2/v0.3/v0.4/v0.5/v0.6/v0.6.1 and packaged for v0.6.2):** storefront filters + collection links; configurable index hero; dark/light shopper toggle; Messages list+thread redesign and counterparty kind-0 profiles; Publications timestamps/row detail, live relay catalog check, filters/sorting, and fresh kind-5 reissue; brand logo URL + footer copy; point-and-click Fine-tune + accent move; single-column merchant settings; primary-colored settings buttons; embeddable shop component (`gm-embed.js` + public products API + CORS), iframe embed with widened CSP, admin Embed snippets; About/More section + screenshots; outbox history prune control; Merchant Nostr Profile (avatar, bio, banner, NIP-05, Lightning address) and owner-only `nsec` reveal; redacted email previews + terminal-history cleanup; sortable Catalog columns and first-column quick actions; searchable country/EU shipping picker; LNbits-style Catalog tables and scrolling mobile section nav; Releases v0.1, v0.2, v0.3, v0.4, v0.5, v0.6, v0.6.1.

**Ad-hoc work since v1.0.0 (released as v1.0.1–v1.0.9):** vendored
nostr-sdk wheels + stdlib for frozen hosts; persistent auto-generated
encryption keys + `LNBITS_BASEURL` fallback; same-origin cookie-mutation
acceptance; starter relay seeding at merchant creation; plebeian +
conduit market relays; code-scanning/Devin Review fixes (lock-inversion
deadlock, origin trust, keyfile race, SDK pin, admin-origins
strictness, public 503 page); sqlite `busy_timeout` on all connections;
settings wallet selector shows the bound wallet (`wallet_id` in the
owner-scoped merchant projection); counterpart-scheme background control
+ derived light variant for dark presets; bulk-attach shipping options;
catalog re-import after delete; `docs/` getting-started updates;
dismissable auto-generated-keys warning (ack sidecar bound to keyfile
bytes); product PATCH category reassignment + bulk move-category
(variations follow their parent); Collections product counts;
not-live catalog banner with direct publish; Nostr inbox enable/disable
card gating showcase/nostr_only; reviews #19/#20 fix commits folded in.

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
- HARD-01–08 all verified (archived requirements at `.planning/milestones/v1.0-REQUIREMENTS.md`); Phase 3 UAT item 17 passed 2026-10-13 (live plebeian.market smoke).

### Release Closeout Gates

- [x] Current pre-fix CI observed: run 38194415581 on `a7082c7`, all four Linux SQLite/PostgreSQL profiles plus lint passed. This does not test all F1–F6 regressions.
- [x] Existing account/catalog delivery checked: 70 passed, 1 optional private-Shopify-sample skip, process exit 0; lint passed.
- [x] Historical Phase 4 cutover plans explicitly dispositioned; no removed feature is reinstated.
- [x] F1–F6 fixed and permanently regression-tested on both DB profiles; reopened security threats mitigated per local review — threat closure still gated on 05-06 qualification.
- [x] CI-01 paired-test lifecycle fixed: root cause (cancelled engine checkout orphaning aiosqlite worker thread) demonstrated; bounded subprocess regression + both orders + full suites exit0.
- [x] Fresh repaired-revision database/platform evidence recorded (SQLite 982/8s, PG 987/3s exit0; evidence bundle regenerated). Browser/conformance items tracked separately under open gates.
- [x] Operator read-only historical paid-order audit performed 2026-10-13 on the deployed instance: 14 orders, all demo-product test activity; zero real-customer paid orders; PII envelope-encrypted; disposition recorded in 05-VERIFICATION.md.
- [x] Phase 3 live Plebeian checkout/payment UAT executed 2026-10-13 — Playwright-driven live plebeian.market order, wrap processed on nos.lol, gamma order confirmed after internal invoice settlement; evidence in 03-VERIFICATION.md + conformance run log.

### Blockers/Concerns

- F1–F6 source corrections pass local runtime + independent review (05-REVIEW.md); CI-01 root cause fixed with process-exit regression; full make verify green both profiles; pushed to origin/main (eaf7d64) for the four-profile CI matrix. 05-06 gates reconciled 2026-10-13: live Plebeian passed, paid-order audit performed, F1 + WR-01 operator-accepted in writing; milestone closeout authorized.
- WR-04 token revocation boundary RESOLVED (locked presented-token recheck on status/opt-out/claim; regressions both DBs).
- Historical paid-order audit: completed 2026-10-13 including the deployed instance — zero real-customer paid orders (14 demo/test orders, internal settlements only); disposition recorded in 05-VERIFICATION.md.
- WR-04: resolved 2026-10-12 (eaf7d64 locked presented-token recheck under the order lock, regressions on both DBs).
- F1 pinned-host admin pageerrors DISPOSED 2026-10-13: upstream host defects (untrusted-cert ServiceWorker registration + unguarded g.wallet.id, both unfixed on LNbits main), operator-accepted as documented limitation. WR-01 chronology caveat DISPOSED 2026-10-13: operator-accepted permanent honesty note.
- Security configuration remains unchanged: ASVS level 1, enforcement enabled, block on high. Old zero-open-threat claims are superseded, not treated as waivers.
- CI-01 is test infrastructure debt, not evidence of a production teardown defect; do not call a timed-out test process successful.
- Phase 2 visual-token/screenshot recommendations remain non-blocking UX follow-ups. No further demo reset, old-data migration or live-funds test is authorized by this closeout.
- Release B live external checkout evidence recorded 2026-10-13; operator egress controls still needed for broader deployment claims.
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
