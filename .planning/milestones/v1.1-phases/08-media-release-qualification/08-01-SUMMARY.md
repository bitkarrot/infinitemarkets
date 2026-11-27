---
phase: 08-media-release-qualification
plan: 01
subsystem: testing
tags: [qualification, audit, blossom, og-image, redirect, bud-11, ci-parity, media]

requires:
  - phase: 06-secure-media-storage
    provides: blossom.py upload boundary (single-attempt PUT, BUD-11
      server-side signing, request-time egress check) + local media
      storage matrix in tests/runtime/test_media_upload.py
  - phase: 07-shared-image-editors
    provides: admin UI retry affordance + picker markup pinned by
      test_admin_ui.py -k media; 07-VERIFICATION.md human_needed items
      discharged by owner UAT
  - phase: external
    provides: PR #28 merge commit 99df6e8 on main (bounded revalidated
      share-card GET redirects in og_images.py + test_og_images.py)
provides:
  - 08-VERIFICATION.md — Phase-8 qualification verdict (status passed,
    2/2 must-haves) with goal-backward truth mapping, command-verbatim
    behavioral spot-checks, and the owner UAT record
  - MEDIA-17 and MEDIA-19 marked complete in REQUIREMENTS.md; Phase 8
    recorded complete in ROADMAP/STATE; stale Phase 7 progress row
    repaired; v1.1 requirement set fully closed
  - Regenerated durable evidence bundle (evidence/REPORT.md +
    evidence/manifest.json) from the full-tree make verify run
affects: [v1.1 milestone closeout, ship gate]

actuals:
  tokens: 170184    # chars/4 over realized diff (680,735 chars) — dominated by regenerated evidence/ bundle; hand-authored planning-doc edits ~5k
  tasks: 3
  commits: 1        # measured ledger→HEAD at summary write (docs commit follows)
  plan_head_before: d40c0566b659e1b215c2f5a347a0615bf7c64a0d

tech-stack:
  added: []
  patterns:
    - "Audit-phase qualification: pre-existing permanent suites are the evidence — no new tests, no code changes; requirements tick only in the commit carrying green-run outputs"
    - "Loopback-only Blossom harness: _FakeBlossom ThreadingHTTPServer on (127.0.0.1, 0) + monkeypatched resolve_and_check_egress/_open_connection seams guarantee zero public-network writes"

key-files:
  created:
    - .planning/phases/08-media-release-qualification/08-VERIFICATION.md
  modified:
    - .planning/REQUIREMENTS.md
    - .planning/ROADMAP.md
    - .planning/STATE.md
    - evidence/REPORT.md
    - evidence/manifest.json

key-decisions:
  - "Evidence bundle (evidence/REPORT.md + manifest.json) committed with the verdict — tracked convention for durable qualification output; the report cites it as a required artifact"
  - "ROADMAP 'Release dependency' paragraph updated to past tense (PR #28 merged + verified + released) — leaving 'is open' would contradict the recorded verdict"
  - "Owner UAT transcribed as already-executed evidence (live share-card render + Phase-7 'everything checks out' exercise), not re-run"

requirements-completed: [MEDIA-17, MEDIA-19]

coverage:
  - id: D1
    description: "SC1 — PR #28 merged; share-card GETs follow bounded revalidated HTTPS redirects; upload PUT rejects 3xx after one request"
    requirement: MEDIA-17
    verification:
      - kind: other
        ref: "git merge-base --is-ancestor 99df6e8 HEAD (exit 0); gh release view v1.1.0 → isDraft:false"
        status: pass
      - kind: unit
        ref: "tests/runtime/test_og_images.py (3 tests) + test_blossom_upload.py::test_redirect_rejected_single_request"
        status: pass
    human_judgment: false
  - id: D2
    description: "SC2 — MEDIA-19 matrix green against loopback _FakeBlossom: local storage, Blossom success, BUD auth/hash/descriptor, first-server-only, explicit failure→local retry, size/type/quota, URL round-trips, zero public writes"
    requirement: MEDIA-19
    verification:
      - kind: unit
        ref: "uv run pytest tests/runtime/test_og_images.py tests/runtime/test_blossom_upload.py tests/runtime/test_media_upload.py -q → 51 passed"
        status: pass
      - kind: unit
        ref: "uv run pytest tests/runtime/test_admin_ui.py -q -k media → 4 passed"
        status: pass
    human_judgment: false
  - id: D3
    description: "CI parity — full-tree make verify + lint, evidence bundle emitted"
    verification:
      - kind: other
        ref: "make verify → 1100 passed, 8 skipped in 362.06s; evidence/REPORT.md regenerated 2026-10-17T05:23:12Z; uv run ruff check . → All checks passed"
        status: pass
    human_judgment: false
  - id: D4
    description: "Owner UAT — live share-card render with LNbits-local images (search + share preview); Phase-7 human-check items exercised locally"
    requirement: MEDIA-17
    verification: []
    human_judgment: true
    rationale: "Already executed by the owner on a live instance — recorded in 08-VERIFICATION.md as owner-accepted evidence; no further human action outstanding"

duration: ~14 min
completed: 2026-10-17
status: complete
---

# Phase 8 Plan 01: Media Release Qualification Summary

**Release-qualification audit passed end-to-end: PR #28 merge ancestry proven on main, bounded share-card redirects and single-request upload-PUT refusal verified, MEDIA-19 loopback matrix green, full `make verify` 1100 passed — MEDIA-17/19 closed and v1.1 requirement set complete.**

## Performance

- **Duration:** ~14 min (audit reads + 20s focused matrix + 6m02s full suite + bookkeeping)
- **Started:** 2026-10-17T05:15:52Z
- **Completed:** 2026-10-17T05:30:00Z
- **Tasks:** 3
- **Files modified:** 6 (4 planning docs + 2 regenerated evidence artifacts)

## Accomplishments
- PR #28 release gate cleared: `git merge-base --is-ancestor 99df6e8 HEAD` exit 0; `v1.1.0` tag present; `gh release view` shows published non-draft release; `manifest.json` at 1.1.0
- Redirect bound re-stated from source: `og_images.py` `_MAX_IMAGE_REDIRECTS=3` with per-hop `resolve_and_check_egress` revalidation (lines 100-150), 3 MB byte / 16 Mpx caps; `blossom.py` `_put` rejects any 3xx after exactly one request (lines 206-212) — no redirect-following loop in the upload path
- MEDIA-19 matrix green: `test_og_images.py` + `test_blossom_upload.py` + `test_media_upload.py` → **51 passed in 19.90s**; `test_admin_ui.py -k media` → **4 passed** (retry affordance + picker markup)
- No-public-writes attested at line granularity: `_FakeBlossom` `ThreadingHTTPServer(("127.0.0.1", 0))` at test_blossom_upload.py:66-67; `_wire_egress` monkeypatches both seams at 131-145; `test_og_images.py` patches egress + stubs `_fetch_image` (42-43/83-84/102-103)
- CI parity: `make verify` → **1100 passed, 8 skipped in 362.06s** (skips: 1 env-gated relay smoke, 6 PG-only drills on sqlite, 1 unconfigured Shopify sample); evidence bundle regenerated; `uv run ruff check .` clean
- 08-VERIFICATION.md authored in the 06/07 format — status `passed`, 2/2 must-haves, owner UAT transcribed (live share-card render; Phase-7 "everything checks out" discharging all five 07 `human_needed` items)
- Bookkeeping: MEDIA-17/19 ticked + traceability Complete; ROADMAP Phase 8 checked (1/1) and stale Phase 7 row repaired to Complete; STATE advanced to Phase-8 closeout (3/3 phases, 9/9 plans, 100%)

## Task Commits

Tasks 1-2 were read-only audits (no files modified — evidence output lands in Task 3 per the plan):

1. **Task 1: Release-gate audit** — no commit (read-only: merge ancestry, tag/release, bound read, focused matrix 51+4 green)
2. **Task 2: CI-parity full suite** — no commit (read-only: `make verify` 1100 passed, ruff clean)
3. **Task 3: Record the qualification verdict** — `4730133` (docs)

**Plan metadata:** this SUMMARY + final state updates committed separately below.

## Files Created/Modified
- `.planning/phases/08-media-release-qualification/08-VERIFICATION.md` — qualification verdict report (created)
- `.planning/REQUIREMENTS.md` — MEDIA-17/19 checkboxes + traceability rows → Complete; footer date
- `.planning/ROADMAP.md` — Phase 7/8 checklist ticks, Phase 8 plans 1/1 + plan entry, progress table repaired
- `.planning/STATE.md` — frontmatter position/progress, Current Position prose, metrics row, Roadmap Evolution line, stale PR #28 blocker resolved
- `evidence/REPORT.md`, `evidence/manifest.json` — regenerated by this audit's `make verify` (tracked durable evidence, per repo convention)

## Decisions Made
- Committed the regenerated `evidence/` bundle with the verdict — it is the durable artifact `GAMMA_QUAL_EVIDENCE=1` exists to produce, and prior phases commit evidence refreshes the same way
- Updated ROADMAP's "Release dependency" paragraph from "PR #28 is open" to merged/verified/released — leaving it stale would contradict the recorded verdict
- Owner UAT recorded as already-executed evidence per the plan (not re-run); Human Verification section reports `passed` with none outstanding

## Deviations from Plan

None — plan executed exactly as written. Two read-only tasks produced no commits by design; the single bookkeeping commit carries the green-run outputs as required by the phase's repudiation mitigation (T-08-02).

## Issues Encountered

None. Every gate passed on first execution with natural process exits; no flake-vs-regression disambiguation was needed.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Phase 8 is complete; all v1.1 requirements (MEDIA-01…19) are closed and v1.1.0 is tagged and published
- No blockers. Deferred v2 scope (MEDIA-20…23: mirroring, kind-10063, remote delete, GIF/transforms) remains deferred

---
*Phase: 08-media-release-qualification*
*Completed: 2026-10-17*

## Self-Check: PASSED
- FOUND: .planning/phases/08-media-release-qualification/08-VERIFICATION.md
- FOUND: .planning/phases/08-media-release-qualification/08-01-SUMMARY.md
- FOUND: commit 4730133 (docs(08-01): phase qualification verdict — MEDIA-17/19 verified, v1.1 closed)
