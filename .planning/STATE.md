---
gsd_state_version: "1.0"
milestone: v1.1
milestone_name: Media uploads and Blossom support
current_phase: 6
current_phase_name: Secure Media Storage
status: planning
stopped_at: Phase 6 complete — verified passed
last_updated: "2026-10-16T16:59:39.523Z"
last_activity: 2026-10-16
last_activity_desc: v1.1 roadmap and requirement traceability drafted
state_head: fbe72aecc69248d5f965e3902e37f0fb64ba2275
progress:
  total_phases: 3
  completed_phases: 1
  total_plans: 4
  completed_plans: 4
  percent: 33
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-10-16)

**Core value:** A merchant can sell one authoritative inventory safely through LNbits-backed web and Nostr flows without duplicate invoices, double allocation, or relay delivery being mistaken for payment truth.
**Current focus:** v1.1 media uploads and Blossom support, starting at Phase 6 after owner approval of the roadmap.

## Current Position

Phase: 6 of 8 — Secure Media Storage (roadmap drafted; awaiting owner approval)
Plan: —
Status: Planning complete; implementation not started
Last activity: 2026-10-16 — v1.1 roadmap and requirement traceability drafted

## Performance Metrics

**Current milestone (v1.1) velocity:**

- Executed plans: 0
- Average duration: -
- Total execution time: 0 hours

**v1.0 historical plans by phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 1 | 3 | - | - |
| 2 | 4 | - | - |
| 3 | 4 | - | - |
| 03.1 | 3 | - | - |
| 4 | 4 historical disposition records | - | - |
| 5 | 6/6 plans complete; closeout gates closed 2026-10-13 | - | - |

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
| Phase 06 P02 | 10min | 3 tasks | 4 files |
| Phase 06 P01 | 12min | 3 tasks | 8 files |
| Phase 06 P03 | 10min | 2 tasks | 8 files |
| Phase 06-secure-media-storage P04 | 15min | 3 tasks | 10 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md and the normative specification.

#### v1.1 Locked Owner Decisions

- Every upload selects exactly one backend: LNbits-local by default or Blossom only when explicitly selected; there is no dual-write.
- Blossom uses only the first server configured in Settings → Merchant, preserving the saved order. Do not auto-fail over; show a clear failure and let the merchant explicitly retry to local storage.
- Blossom authorization is signed server-side with the merchant's stored key. Never expose nsec or reusable signing material to browser code.
- Product galleries support up to 20 images; align the technical specification with the current service implementation.
- Upload bounds are at most 16 files per request, 25 MB per file, and 400 MB per merchant for local storage. Multipart parsing must be bounded and must not buffer unbounded request bodies in memory.
- Accept only signature-verified PNG/JPEG/WebP; reject SVG and GIF in v1.1.
- If a remote upload is not saved with its product or setting, disclose that the blob may remain unreferenced; never automatically delete remote Blossom blobs.
- Keep PR #28's bounded, revalidated HTTPS redirects scoped to share-card image GETs. Merge and verify PR #28 before release; never follow upload PUT redirects.
- BUD-04 mirroring, kind-10063 publication, remote deletion, GIF support, and image transforms remain deferred.

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
- [Phase 6]: 06-02: Blossom upload uses canonical MIME map (jpg->image/jpeg); set_blossom_servers persists submission order (first=primary), pre-existing rows stay alphabetical; per-merchant upload semaphore is process-local (D-13)
- [Phase 6]: 06-01: media.py reuses migration_media internals (one namespace/quota); general uploads never write the sidecar; absolute public_base_url URLs (D-07)
- [Phase 6]: 06-01: spec 5.6 Admin-media added; error model renumbered 5.7; spec image cap corrected to 20
- [Phase 6]: 06-03: profile-origin gate is local-branch-only — usage=profile+backend=blossom allowed on private public_base_url (remote https descriptor is the recommended alternative)
- [Phase 6]: 06-03: remote blossom failure is request-level typed problem naming the server; earlier PUT blobs are honest orphans per D-01
- [Phase 6]: 06-04: emit /library/infinitemarkets/ (real host mount) and rewrite legacy /images/ references via m019 — owner-locked gap closure

### Pending Todos

- No loose files in `.planning/todos/pending/`; the shipping picker is already completed.
- HARD-01–08 all verified (archived requirements at `.planning/milestones/v1.0-REQUIREMENTS.md`); Phase 3 UAT item 17 passed 2026-10-13 (live plebeian.market smoke).
- v1.1 implementation plans begin only after owner approval of the roadmap.

### Release Closeout Gates

- [x] Current pre-fix CI observed: run 38194415581 on `a7082c7`, all four Linux SQLite/PostgreSQL profiles plus lint passed. This does not test all F1–F6 regressions.
- [x] Existing account/catalog delivery checked: 70 passed, 1 optional private-Shopify-sample skip, process exit 0; lint passed.
- [x] Historical Phase 4 cutover plans explicitly dispositioned; no removed feature is reinstated.
- [x] F1–F6 fixed and permanently regression-tested on both DB profiles; independent review and 05-06 qualification closed 2026-10-13, with accepted residuals recorded.
- [x] CI-01 paired-test lifecycle fixed: root cause (cancelled engine checkout orphaning aiosqlite worker thread) demonstrated; bounded subprocess regression + both orders + full suites exit0.
- [x] Fresh repaired-revision database/platform evidence recorded (SQLite 982/8s, PG 987/3s exit0; evidence bundle regenerated); remaining browser/conformance gates are reconciled in the v1.0 closeout record.
- [x] Operator read-only historical paid-order audit performed 2026-10-13 on the deployed instance: 14 orders, all demo-product test activity; zero real-customer paid orders; PII envelope-encrypted; disposition recorded in 05-VERIFICATION.md.
- [x] Phase 3 live Plebeian checkout/payment UAT executed 2026-10-13 — Playwright-driven live plebeian.market order, wrap processed on nos.lol, gamma order confirmed after internal invoice settlement; evidence in 03-VERIFICATION.md + conformance run log.

### Blockers/Concerns

- PR #28 (`fix/og-image-redirects`) is open and all CI checks have passed; merge and verification remain a v1.1 release prerequisite. Its redirect handling is GET-only, never upload PUT behavior.
- The 400 MB quota applies to LNbits-local storage; Blossom requests still require strict per-request/file bounds and safe request-time egress validation.

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

- 2026-10-16: v1.1 roadmap created as Phases 6–8: secure media storage, shared image editors for all merchant image fields, and media release qualification. MEDIA-01–MEDIA-19 are each assigned to exactly one phase.
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

Last session: 2026-10-16T16:59:39.489Z
Stopped at: Phase 6 complete — verified passed
Resume file: .planning/phases/06-secure-media-storage/06-VERIFICATION.md
