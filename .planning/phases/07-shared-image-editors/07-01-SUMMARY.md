---
phase: 07-shared-image-editors
plan: 01
subsystem: api
tags: [media, quota, unused-uploads, response-shape, tdd]

requires:
  - phase: 06-secure-media-storage
    provides: GET /media/unused (list_unused), _dir_bytes quota accounting, migration_media.MAX_MERCHANT_BYTES
provides:
  - GET /media/unused files[] entries now carry `mtime` (epoch seconds from stat().st_mtime)
  - GET /media/unused top-level `used_bytes`/`quota_bytes` quota summary (D-23)
  - spec §5.6 prose documenting the extended response shape
affects: [07-04-settings-media-card, MEDIA-12]

actuals:
  tokens: 1527
  tasks: 2
  commits: 3
  plan_head_before: 986a6d9c5c135cc8ee3b4a818c2621722c5b0ccb

tech-stack:
  added: []
  patterns:
    - "Additive response-shape extension on an existing route instead of a new route (D-23) — avoids spec §5 ↔ registry parity churn"
    - "Single stat() per unreferenced file supplies both bytes and mtime"

key-files:
  created: []
  modified:
    - infinitemarkets/services/media.py
    - docs/technical-specification.md
    - tests/runtime/test_media_upload.py

key-decisions:
  - "used_bytes reuses _dir_bytes over the whole namespace dir — referenced and unreferenced bytes both count (D-01), matching the quota the upload path enforces"
  - "New focused test (test_unused_listing_reports_mtime_and_quota) rather than extending the lifecycle test — keeps the RED legible and the lifecycle test untouched"

requirements-completed: []

coverage:
  - id: D1
    description: "GET /media/unused files[] entries carry name, bytes, sha256, and numeric mtime (epoch seconds, stat().st_mtime semantics)"
    requirement: MEDIA-12
    verification:
      - kind: integration
        ref: "tests/runtime/test_media_upload.py#test_unused_listing_reports_mtime_and_quota"
        status: pass
    human_judgment: false
  - id: D2
    description: "GET /media/unused top-level used_bytes (full namespace total incl. referenced bytes) and quota_bytes (== MAX_MERCHANT_BYTES, 400 MB)"
    requirement: MEDIA-12
    verification:
      - kind: integration
        ref: "tests/runtime/test_media_upload.py#test_unused_listing_reports_mtime_and_quota"
        status: pass
    human_judgment: false
  - id: D3
    description: "No route added or changed — spec §5.6 prose extension only; route parity untouched"
    requirement: MEDIA-12
    verification:
      - kind: other
        ref: "uv run pytest tests/qualification/test_p0_14_contract_closure.py -q"
        status: pass
    human_judgment: false

duration: 5min
completed: 2026-10-16
status: complete
---

# Phase 07 Plan 01: Unused-listing mtime + quota summary Summary

**`GET /media/unused` response extended with per-file `mtime` and top-level `used_bytes`/`quota_bytes` (D-23) — the backend plumbing the Settings → Media card in 07-04 renders as a date column and quota bar.**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-10-16T21:39:30Z
- **Completed:** 2026-10-16T21:42:16Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- `list_unused` now stats each unreferenced file once and emits `mtime` (epoch seconds) alongside the existing `name`/`bytes`/`sha256`
- Response gains `used_bytes` (full namespace total via `_dir_bytes` — referenced files included, D-01) and `quota_bytes` (`migration_media.MAX_MERCHANT_BYTES`, 400 MB)
- Spec §5.6 prose names the new fields; the §5 route table is byte-identical — no MEDIA-18 parity churn (D-23)

## Task Commits

Each task was committed atomically:

1. **Task 1: Failing assertions for the extended unused-listing response** — `5be347c` (test)
2. **Task 2: Emit mtime + quota fields from list_unused; spec §5.6 prose** — `91b9e4f` (feat)

**Plan metadata:** pending (docs commit for this SUMMARY + STATE/ROADMAP updates)

_Concurrent-execution note: the measured `commits:` count of 3 since `plan_head_before` includes `3a63cfc` — a RED-test commit authored by the parallel 07-02 executor on the same branch; this plan owns `5be347c` and `91b9e4f` only._

## RED → GREEN evidence

- **RED:** `uv run pytest tests/runtime/test_media_upload.py -q -k unused` → exit 1 with `KeyError: 'quota_bytes'` in `test_unused_listing_reports_mtime_and_quota` only (named failure on absent keys, per `expected_red`); the other 3 `-k unused` tests stayed green.
- **GREEN:** same file, full run → `19 passed`; `uv run ruff check infinitemarkets/services/media.py` → clean.

## Files Created/Modified

- `infinitemarkets/services/media.py` — `list_unused` emits `mtime` per entry + `used_bytes`/`quota_bytes` top-level; docstring extended
- `tests/runtime/test_media_upload.py` — new `test_unused_listing_reports_mtime_and_quota` (61 lines)
- `docs/technical-specification.md` — §5.6 `GET /media/unused` prose names `mtime`, `used_bytes`, `quota_bytes`

## Decisions Made

- `used_bytes` reuses `_dir_bytes(media_dir)` verbatim — it already counts every byte under the namespace including referenced and unsaved leftovers, which is exactly the quota accounting the upload path enforces (D-01). An orphan-only sum would under-report.
- One `stat()` per unreferenced file supplies both `bytes` and `mtime` — list comprehension refactored to a plain loop to avoid a double stat.
- `requirements-completed: []`: the plan's frontmatter scopes MEDIA-12 across 07-02/03/04 for the UI-facing behaviors; this plan delivers only the backend slice, so `requirements mark-complete` was intentionally NOT run.

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None. A parallel 07-02 executor interleaved one commit (`3a63cfc`) on `main` between this plan's commits — it touches only 07-02-owned files and required no handling.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- `GET /media/unused` response is now the complete backend contract for the Settings → Media card (07-04): `{files: [{name, bytes, sha256, mtime}], used_bytes, quota_bytes}`.
- Route parity untouched: `test_p0_14_contract_closure` green; `make verify-fast` green (318 passed, 2 skipped).

## Self-Check: PASSED

- FOUND: `.planning/phases/07-shared-image-editors/07-01-SUMMARY.md`
- FOUND: `5be347c` (test commit) — `git log` verified
- FOUND: `91b9e4f` (feat commit) — `git log` verified

---
*Phase: 07-shared-image-editors*
*Completed: 2026-10-16*
