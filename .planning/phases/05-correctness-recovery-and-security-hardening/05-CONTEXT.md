---
phase: 05-correctness-recovery-and-security-hardening
gathered: 2026-10-11
status: ready_for_planning
scope: complete
---

# Phase 5 — Correctness, Recovery, and Security Hardening

## Boundary

Repair existing commerce and delivery invariants before building optional
features. The user explicitly chose **Hardening first** during the 2026-10-11
GSD closeout. This context is approved scope, not an executed implementation plan.
The milestone remains v1.0; app release numbering is independent. Do not archive
or certify completion while required assurance gates remain open.

## Locked decisions

- Fix F1–F6 in `docs/spec-conformance-analysis.md`, with permanent failing-then-
  passing runtime regressions; temporary review probes were removed.
- Include CI-01/HARD-07: the DB/install test pair prints 19 passes then hangs.
  Fix test/runtime resource cleanup, not symptoms via `os._exit`, skipped tests,
  forced-kill success, or weakened security/CI controls.
- Preserve SQLite single-process and PostgreSQL qualified topology coverage;
  all four Linux matrix profiles already exist. Do not add a fictitious missing
  PostgreSQL leg or equate a green matrix with complete invariant coverage.
- Old cutover/freeze/liability/rehearsal and live NIP-15/NIP-04 v1 work is dropped.
  Phase 4 SUMMARY files close obsolete plans, not tests of removed features.
- Defer optional external stock/shipping authority integrations and shipping
  import/binding. No new custody, outgoing payment, legacy order lane or
  automatic-refund capability belongs in this phase.
- Preserve live Plebeian checkout as an explicit pending gate. Listing smoke,
  local client scripts, FakeWallet and the LNURLp shim do not establish it.
  Obtain explicit approval for live relay writes, credentials, deployment changes
  or real-funds operations before attempting that external test.
- Keep ASVS-1 enforcement and the high-severity blocking threshold unchanged.
  Historical all-green security/UAT records are not current clearance.

## Repair contracts

| Finding | Requirements | Required boundary |
|---|---|---|
| F1 | HARD-01; PAY-02, INV-01, ORD-01, SEC-01, GAM-02 | Merchant actor authorization plus verified payment; all cancellations use atomic inventory-aware operations; delivery remains locked through token and buyer-history surfaces |
| F2 | HARD-02; PAY-01, PAY-02, GAM-02 | Recover the same invoice; resolve creation uncertainty only after verification, preserving independent exceptions |
| F3 | HARD-03; PAY-02, INV-01, GAM-02 | Validate all item quantities and account for stock before normal confirmation; explicit exception/reallocation when holds are gone |
| F4 | HARD-04; CAT-02, PUB-01 | Revision-aware dependency satisfaction, including supersession and deletion/reference ordering |
| F5 | HARD-05; GAM-03, GAM-04 | Separate no-route waits from failed sends; route arrival after >20 waits still works inside 48 hours, with deterministic deadline behavior |
| F6 | HARD-06; GAM-04, GAM-05 | Atomic same-merchant/relay admission limit, concurrency-safe and independent of minute-window resets; bounded drop metrics |
| CI-01 | HARD-07 | Clean process exit in both DB/install file orders and normal suite |
| Release evidence | HARD-08; all reopened acceptance | Fresh permanent-regression, platform/DB, browser, conformance and security evidence; explicit live gate |

## Suggested work grouping

1. Financial authority and recovery: F1, F2, F3; do not clear unrelated exceptions
   or allow generic state-table legality to substitute for domain preconditions.
2. Durable outbox correctness: F4 and F5, including revision and retry edge cases.
3. Inbox admission: F6, with atomic multi-connection tests and durable backlog
   semantics distinct from process-local counters.
4. Verification lifecycle and closeout: CI-01 may be fixed earlier if it blocks
   focused feedback; HARD-08 follows the repaired code, not only existing tests.

Plan authors choose the final decomposition; no PLAN files exist yet. Route
repairs to Phase 5 rather than restarting delivered features or superseded plans.
Original Phase 2/3 acceptance remains reopened until its repairs are verified.

## Deferred follow-ups, not silently closed

S1 entitlement immutability/versioning versus intentionally live content is a
product policy decision before a migration. S2 rumor/wrapper identifier semantics
and authenticated history contracts need clarification. S3/S4 evidence, durable
observability, tag-shape ambiguity and focused cleanup remain in root FUTURE-ROADMAP.md.
Buyer-account unlink/preference expansion and optional protocol features remain
outside this phase. Revisit only by an explicit scope decision.

## Baseline evidence

- Reviewed code: `a7082c7e21b435af8d420a1d6712b980e399c876`.
- Conformance review: 77 existing tests passed/1 skipped; eight temporary
  negative assertions exposed F1–F6 and S1. Those probes are not committed tests.
- Closeout: 70 targeted account/catalog tests passed/1 optional private-sample
  skip; process exit 0. Lint passed. DB/install pair: 19 assertions passed but
  process failed to exit at a 60-second diagnostic bound; remains open.
- CI run 38194415581: all four Linux DB/platform jobs and lint passed before
  fixes; no local full suite, new browser run or live funding test in closeout.

## Execution authorization and planning refinements

Approved in the Phase 5 continuation on 2026-10-11:

- Use independent Devin agents with GSD role instructions for research, planning,
  execution and checking. Keep writes disjoint; do not claim independent checks
  when only self-review occurred.
- Plan all HARD-01–HARD-08, then execute F1–F3 only and pause before F4–F6/CI-01.
  Within that tranche, repair stock accounting (F3) before clearing uncertainty
  (F2), so a recovered invoice cannot unlock unaccounted fulfillment.
- Leave existing paid-order records for an operator audit while fixing active
  recovery flows, as selected in the user question. Do not add an automatic legacy
  sweep, clear already-settled holds or repair historical stock without review.
  Current authority covers isolated synthetic implementation/testing only, not
  connecting to an existing database. The read-only operator audit is mandatory
  **before production exposure, real-record disposition or release clearance**;
  local code verification/commits do not satisfy or close it. Record this open gate
  at the financial-tranche pause as well as the eventual release checkpoint.
- For verified settlement with incomplete reservation coverage before expiry,
  **cancel into the existing exception lane**: preserve settled payment, release
  remaining held capacity atomically, retain a bounded inventory exception, and
  require merchant accept/refund. Do not mislabel it as invoice expiry, broaden
  accept states, auto-reopen or initiate an outgoing refund.
- Approve only the disposable PostgreSQL cluster at
  `/tmp/infinitemarkets-phase5-pg-1ae80f8`, its synthetic-database fixture schema
  teardown, and stopping/removing that specific new cluster after checks.
  No existing database, real wallet or live relay is covered by this approval.
- Only `invoice-creation-unknown` is automatically recoverable. Correlation and
  independent/reasonless holds and manual refund decisions must survive.
  Preserve the documented resolution vocabulary and literal order state table.
- No new dependency, security-policy relaxation, push, production application
  deployment or real-funds operation is authorized by this local tranche.
