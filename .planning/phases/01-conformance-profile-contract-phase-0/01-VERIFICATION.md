---
phase: 01-conformance-profile-contract-phase-0
verified: "2026-10-12T03:01:39+00:00"
status: passed
score: 14/14 must-haves verified
covered_files:
  - .github/workflows/qualification.yml
  - .planning/phases/01-conformance-profile-contract-phase-0/01-01-PLAN.md
  - .planning/phases/01-conformance-profile-contract-phase-0/01-01-SUMMARY.md
  - .planning/phases/01-conformance-profile-contract-phase-0/01-02-PLAN.md
  - .planning/phases/01-conformance-profile-contract-phase-0/01-02-SUMMARY.md
  - .planning/phases/01-conformance-profile-contract-phase-0/01-03-PLAN.md
  - .planning/phases/01-conformance-profile-contract-phase-0/01-03-SUMMARY.md
  - .planning/phases/01-conformance-profile-contract-phase-0/01-CONTEXT.md
  - .planning/phases/01-conformance-profile-contract-phase-0/01-DISCUSSION-LOG.md
  - .planning/phases/01-conformance-profile-contract-phase-0/01-VALIDATION.md
  - .planning/phases/01-conformance-profile-contract-phase-0/SKELETON.md
  - PINS.md
  - evidence/REPORT.md
  - evidence/manifest.json
covered_digest: "v1:sha256:efb7624bfac121c7d6c0825b120db44d3949fc1d1bbe3b34d84cf506cf902267"
behavior_unverified: 0
---

# Phase 1: Conformance Profile (Contract Phase 0) Verification Report

**2026-10-11 evidence refresh:** current CI run 38194415581 passed the four Linux DB/platform profiles on `a7082c7`; the original counts and owner approval below are historical. This refresh retains only the P0 harness/model claim, not runtime-wide safety or closure of F1–F6. The missing retrospective coverage map is now `01-VALIDATION.md`.

**Phase Goal:** Prove host, SDK, schema, state, security, and protocol assumptions before runtime implementation.
**Verified:** 2026-09-20
**Status:** passed

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | P0-01 pins/provenance reproducible | ✓ VERIFIED | `test_p0_01_pins.py` 33 tests: wheel sha256 parity vs host lock, transitive lock resolution recorded, release-source + Cargo provenance pinned |
| 2 | P0-02 SDK security boundary | ✓ VERIFIED | Non-vacuous bounds: NIP-44 oversized input rejected under 5s wall-time + tracemalloc bound; 200-challenge AUTH flood bounded; tampered events rejected |
| 3 | P0-03 host contracts | ✓ VERIFIED | Invoice metadata persistence, listener lifecycle, owned-task cancellation probed against pinned host |
| 4 | P0-04 relay ACK classification | ✓ VERIFIED | Positive/negative/timeout classified per relay; unlisted-relay test asserts zero EVENT frames with fan-out control |
| 5 | P0-05 NIP-17 gift-wrap chain | ✓ VERIFIED | Buyer/merchant copies, fresh wrapper keys, stable rumor identity across retries, targeted routing, tamper rejection, no plaintext logging |
| 6 | P0-06 transaction/fencing/state | ✓ VERIFIED | FK enforcement, last-unit concurrency, fencing CAS, rollback, state machine — both dialects |
| 7 | P0-07 cancellation/invoice saga | ✓ VERIFIED | Saga outcomes incl. late-settlement projection on cancelled orders |
| 8 | P0-08 inbox/outbox recovery | ✓ VERIFIED | Lease expiry, durable publication evidence, retry-only-missing-targets, cursor continuation; durable-evidence split models §8.6 crash point |
| 9 | P0-09 email persistence | ✓ VERIFIED | Per-recipient dedup, opt-in, token expiry/revocation, protected storage |
| 10 | P0-10 SMTP boolean boundary | ✓ VERIFIED | Retry, suppression, redacted logs, host-owned SMTP only |
| 11 | P0-11 local NIP-89 routing | ✓ VERIFIED | Wrong-kind/foreign/malformed rejected; no relay fetch from embedded hints |
| 12 | P0-12 auth/privacy/lifecycle | ✓ VERIFIED | CSRF/origin, audit privacy, readiness, topology refusal, request redaction (X-Order-Token never in logs) |
| 13 | P0-13 Decimal/FX boundary | ✓ VERIFIED | ROUND_CEILING; measured float bound 7.46e-17 relative / 0 sats absolute, recorded in manifest |
| 14 | P0-14 contract closure | ✓ VERIFIED | Spec↔registry↔schema parity, fixtures, release scoping, frozen identifiers, topology refusal, complete evidence — asserts live on full profile, self-skips honestly on subset runs |

**Score:** 14/14 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `Makefile` / `pyproject.toml` / `uv.lock` | canonical verify command + reproducible env | ✓ EXISTS + SUBSTANTIVE | `make verify` + 5 named subsets; uv-locked |
| `PINS.md` | normative pins + qualification results + D-11 | ✓ EXISTS + SUBSTANTIVE | Approved 2026-09-20 (§7) |
| `harness/` (pins, db, tx, sdk, relay, evidence, registry, …) | qualification support package | ✓ EXISTS + SUBSTANTIVE | ~15 modules, package=false (no runtime drift) |
| `tests/qualification/` | P0-01..P0-14 executable proofs | ✓ EXISTS + SUBSTANTIVE | 220/221 pass, 1 optional-relay skip, both dialects |
| `evidence/manifest.json` + `REPORT.md` | committed durable bundle | ✓ EXISTS + SUBSTANTIVE | refreshed from canonical CI run 35535526249 (linux-x86_64+postgres) |
| `.github/workflows/qualification.yml` | blocking 4-profile matrix | ✓ EXISTS + SUBSTANTIVE | all 4 blocking + advisory green on run 35535526249 |

**Artifacts:** 6/6 verified

## Requirements Coverage

| Requirement | Status | Blocking Issue |
|-------------|--------|----------------|
| QUAL-01..QUAL-14 | ✓ SATISFIED | All marked complete in REQUIREMENTS.md |

**Coverage:** 14/14 requirements satisfied

## Anti-Patterns Found

None. Confirmed: no retry/flaky-green mechanism (single-run clean-pass policy in manifest), no committed raw logs (D-09), no production runtime code (probe router isolated on `/infinitemarkets-qual-probe`).

**Anti-patterns:** 0 found

## Human Verification Required

None — all items verified programmatically. D-11 owner approval was the human gate and was granted 2026-09-20 (PINS.md §7).

## Gaps Summary

**No gaps found.** Phase goal achieved.

### Documented caveats (non-blocking)

1. `harness/pins.py` fetches the release-source `Cargo.lock` from a commit-pinned URL when `.cache/` is cold — a second network dependency beyond the optional relay smoke test; commit-addressed and required by CI anyway.
2. External-client interoperability remains deferred and unclaimed (Release B/C scope).
3. Deviation fixes confirmed in code: SQLAlchemy 1.4+asyncpg `UPDATE…RETURNING` workaround, `ON CONFLICT DO NOTHING` inserts, durable-evidence split from fenced outcome write, per-worker `QualWorker` DB handles, libc-aware wheel platform tag (CI-caught, fixed `c8b68c2`).

## Verification Metadata

**Verification approach:** Goal-backward (independent read-only verifier + CI blocking matrix)
**Must-haves source:** 01-01/01-02/01-03 PLAN.md frontmatter + spec P0 table
**Automated checks:** 220 passed, 1 skipped (optional external relay smoke) per profile; CI run 35535526249 all green
**Human checks required:** 0
**Total verification time:** ~25 min

---
*Verified: 2026-09-20*
*Verifier: gsd-verifier subagent (verdict persisted post-run)*

## Closeout evidence boundary

The current CI workflow runs canonical `make verify` with evidence enabled on
SQLite/PostgreSQL × Linux x86_64/ARM64. Its successful status was rechecked from
GitHub during this closeout. The coverage fingerprint is refreshed for the
reviewed current artifacts, including the retrospective validation map; the old
checked-in report is historical and was not regenerated. No new local full-suite
run is claimed. Runtime financial/delivery defects remain open in Phase 5 and
are not disproved by the P0 harness/model proofs.
