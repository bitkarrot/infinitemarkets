---
phase: 06-secure-media-storage
plan: 04
subsystem: api
tags: [media, storage, nostr, migrations, lnbits, staticfiles]

# Dependency graph
requires:
  - phase: 06-secure-media-storage
    provides: local media adapter, POST /media/upload, D-12 unused listing, kind-0 absolutization (06-01..06-03)
provides:
  - Canonical `/library/infinitemarkets/` emission matching the pinned host's real mount (`{data}/images` -> `/library`)
  - m019 data migration rewriting legacy `/images/infinitemarkets/` references on every boot
  - Dual-prefix D-12 unreferenced detection, kind-0 normalize-then-absolutize, owned-prefix catalog/import validators
  - Host-boot serveability proof: emitted path GETs 200 with byte-identical body
affects: [07-media-editor-ui, release-qualification]

# Actuals (#2632)
actuals:
  tokens: 8280    # chars/4 over the realized diff (33130 chars)
  tasks: 3
  commits: 3
plan_head_before: 1e43ed206a2cfb5907de6e52a7eb0e02e5897176

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Single canonical URL-prefix constant shared by every emitter (migration_media.MEDIA_URL_PREFIX)"
    - "Data-only boot migration pattern: REPLACE + LIKE only, dialect-portable, JSON-string-start needle protects foreign URLs"
    - "Serveability assertion: runtime tests GET the emitted path through the booted ASGI app, not just the disk path"

key-files:
  created: []
  modified:
    - infinitemarkets/services/migration_media.py
    - infinitemarkets/services/media.py
    - infinitemarkets/migrations.py
    - infinitemarkets/services/migration_import.py
    - infinitemarkets/services/catalog.py
    - infinitemarkets/services/events.py
    - docs/technical-specification.md
    - tests/runtime/test_media_upload.py
    - tests/runtime/test_migration_export_media.py
    - tests/runtime/test_catalog_events.py

key-decisions:
  - "Emit /library/infinitemarkets/ — the pinned host (LNbits e336fe1) mounts the data-folder images dir at /library; /images was a dead prefix inherited from v1.0"
  - "m019 REPLACE needle keeps the JSON-string-start quote (\"/images/infinitemarkets/) so a foreign-host absolute URL sharing a JSON row is never corrupted (T-06-04-01)"
  - "catalog._valid_image_url helper applied to ALL four image-URL validation sites (plan named three; the collections-PATCH site at ~line 1941 got the same helper for consistency)"
  - "kind-0 normalizes legacy values to /library/ even when public_base_url is empty — the emitted relative form is at least fetchable same-origin"

patterns-established:
  - "Gap-closure TDD: the RED that reproduces the verifier's empirical failure (HTTP GET -> 404/200) becomes the permanent serveability regression test"

requirements-completed: [MEDIA-06, MEDIA-07]

coverage:
  - id: D1
    description: "Every emitted local media URL uses /library/infinitemarkets/ and a real HTTP GET through the booted host returns 200 byte-exact (closes 06-VERIFICATION blocker)"
    requirement: MEDIA-06
    verification:
      - kind: integration
        ref: "tests/runtime/test_media_upload.py#test_uploaded_path_is_served_over_http"
        status: pass
      - kind: integration
        ref: "tests/runtime/test_media_upload.py#test_media_upload_stores_verified_image"
        status: pass
    human_judgment: false
  - id: D2
    description: "m019 rewrites legacy /images/ references in product_images.url, merchants.profile_json/theme, and settings.value idempotently; foreign-host URLs untouched"
    requirement: MEDIA-06
    verification:
      - kind: integration
        ref: "tests/runtime/test_migration_export_media.py#test_m019_rewrites_legacy_media_urls"
        status: pass
    human_judgment: false
  - id: D3
    description: "D-12 unreferenced detection and DELETE treat /images/ and /library/ prefixes as the same file; relink skips both prefixes"
    requirement: MEDIA-06
    verification:
      - kind: integration
        ref: "tests/runtime/test_media_upload.py#test_dual_prefix_references_keep_file_off_unused"
        status: pass
      - kind: integration
        ref: "tests/runtime/test_migration_export_media.py#test_media_upload_and_relink"
        status: pass
    human_judgment: false
  - id: D4
    description: "kind-0 picture/banner absolutizes /library/ paths and normalizes legacy /images/ values before prepending public_base_url"
    requirement: MEDIA-07
    verification:
      - kind: unit
        ref: "tests/runtime/test_catalog_events.py#test_merchant_profile_absolutizes_local_image_paths"
        status: pass
    human_judgment: false
  - id: D5
    description: "Validators accept owned relative prefixes narrowly — _native_image_url round-trips/normalizes, catalog PATCH accepts owned prefixes while rejecting other relative paths and http://"
    requirement: MEDIA-06
    verification:
      - kind: integration
        ref: "tests/runtime/test_migration_export_media.py#test_native_image_url_library_round_trip"
        status: pass
      - kind: integration
        ref: "tests/runtime/test_media_upload.py#test_catalog_accepts_owned_relative_image_prefixes"
        status: pass
    human_judgment: false

# Metrics
duration: 15min
completed: 2026-10-16
status: complete
---

# Phase 6 Plan 04: Media URL Mount Gap Closure Summary

**Canonical `/library/` emission + m019 legacy-prefix rewrite + dual-prefix D-12/kind-0 handling — every emitted media URL is now fetchable on the qualified host, proven by an HTTP GET through the booted runtime fixture.**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-10-16T16:43:22Z
- **Completed:** 2026-10-16T16:54:46Z
- **Tasks:** 3
- **Files modified:** 10

## Accomplishments
- Closed the single 06-VERIFICATION blocker: `migration_media._local_url` and `media.local_path`/`absolute_url` now emit `/library/infinitemarkets/<ns>/<name>` from one shared `MEDIA_URL_PREFIX` constant; a new host-boot test GETs the emitted path and asserts 200 + byte-identical content — the missing assertion that let the dead `/images/` prefix ship.
- `m019_media_library_mount` (auto-discovered by the host's `run_migration`) rewrites legacy `/images/infinitemarkets/` references in `product_images.url`, `merchants.profile_json`, `merchants.theme`, and `settings.value` — idempotent, REPLACE+LIKE only (SQLite + PostgreSQL portable), and foreign-host URLs containing the substring are provably untouched even when sharing a JSON row.
- Dual-prefix coherence end-to-end: `relink_media` skips already-local rows under both prefixes; `_referenced_names`/`GET /media/unused`/`DELETE` treat both prefixes as the same file (pinned by test); `merchant_profile_event` normalizes `/images/` to `/library/` then absolutizes — nothing dead reaches relays even if m019 is bypassed.
- Validators aligned: `migration_import._native_image_url` round-trips `/library/` verbatim and normalizes owned `/images/` input at ingest; `catalog._valid_image_url` accepts the two owned relative prefixes at all image-URL sites while `/library/other`, `/images/other`, `http://`, and arbitrary relative paths still 422.
- Spec corrected: §5.6 and §13.2 name the real `/library` mount; §15 image-URL row documents the owned-relative-prefix exception.

## Task Commits

1. **Task 1: Canonical /library emission + host-boot serveability proof** — `8260e7b` (fix)
2. **Task 2: m019 data migration + import/catalog validator alignment** — `8f2bec5` (feat)
3. **Task 3: kind-0 dual-prefix absolutization + spec/docstring corrections + phase sweep** — `b4ffd78` (feat)

## Test Results

- `uv run pytest tests/runtime/test_media_upload.py tests/runtime/test_migration_export_media.py -q` — 26 passed
- `uv run pytest tests/runtime/test_catalog_events.py -q` — 17 passed
- `uv run pytest tests/runtime/test_media_upload.py test_migration_export_media.py test_blossom_upload.py test_relay_config_api.py -q` — 60 passed
- `uv run pytest tests/qualification/test_p0_14_contract_closure.py -q` — 11 passed, 1 skipped (route↔spec parity intact — no route changes)
- `make verify-fast` — **318 passed, 2 skipped** (46s)
- `uv run ruff check .` — All checks passed

## Files Created/Modified
- `infinitemarkets/services/migration_media.py` — `MEDIA_URL_PREFIX`/`LEGACY_MEDIA_URL_PREFIX` canonical constants; `_local_url` emits `/library/`; relink exclusion extended; docstring corrected
- `infinitemarkets/services/media.py` — `local_path` delegates to the shared constant
- `infinitemarkets/migrations.py` — `m019_media_library_mount` (data-only, idempotent, portable)
- `infinitemarkets/services/migration_import.py` — `_native_image_url` dual-prefix acceptance + owned-prefix normalization
- `infinitemarkets/services/catalog.py` — `_valid_image_url` helper at all four image-URL validation sites
- `infinitemarkets/services/events.py` — normalize-then-absolutize for picture/banner
- `docs/technical-specification.md` — §5.6, §13.2, §15 corrections
- `tests/runtime/test_media_upload.py` — serveability GET test, dual-prefix D-12 test, owned-prefix catalog PATCH test
- `tests/runtime/test_migration_export_media.py` — m019 seed/migrate/idempotency test, native-import round-trip test, relink prefix flips + second-relink idempotency
- `tests/runtime/test_catalog_events.py` — dual-prefix kind-0 absolutization assertions

## Decisions Made
- Followed the locked owner decision verbatim: emit `/library/` + rewrite legacy — no extension-served route, no reverse-proxy documentation.
- m019's REPLACE needle includes the JSON-string-start quote (`"/images/infinitemarkets/`) on JSON columns — stricter than the plan's literal text, required to satisfy the plan's own "foreign-host URL must NOT be touched" behavior when a foreign URL shares a row with a rewritten value (T-06-04-01).
- `catalog._valid_image_url` applied to the collection-PATCH site (`~line 1941`) in addition to the plan's named three — same field semantics; leaving it https-only would make rewritten collections un-PATCH-able.
- Empty-`public_base_url` kind-0 emission now emits the *normalized* `/library/` relative form rather than the raw `/images/` value — still never concatenates, but the emitted prefix is at least fetchable same-origin.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] `_valid_image_url` applied to the collections-PATCH site**
- **Found during:** Task 2 (validator alignment)
- **Issue:** Plan named three `https://` sites; a fourth (collection `image` PATCH, ~line 1941) enforces the same contract — skipping it would leave rewritten collection rows uneditable
- **Fix:** Same helper applied; error message updated consistently
- **Files modified:** `infinitemarkets/services/catalog.py`
- **Verification:** `make verify-fast` green; catalog PATCH tests pass
- **Committed in:** `8f2bec5`

**2. [Rule 2 - Missing Critical] m019 JSON-column REPLACE needle includes the quote**
- **Found during:** Task 2 (m019 implementation)
- **Issue:** Plan's literal REPLACE on `/images/infinitemarkets/` would also rewrite foreign-host absolute URLs embedded in the same JSON row that passes the WHERE guard
- **Fix:** REPLACE needle is `"/images/infinitemarkets/` (quote included) on profile_json/theme/settings.value — the column-start form suffices for the bare `product_images.url` column
- **Files modified:** `infinitemarkets/migrations.py`
- **Verification:** `test_m019_rewrites_legacy_media_urls` proves a foreign URL sharing a rewritten row survives byte-identical
- **Committed in:** `8f2bec5`

**3. [Rule 1 - Bug] Sorted-comparison assertion order in the m019 test**
- **Found during:** Task 2 GREEN run
- **Issue:** `urls == [foreign, live_pic]` compared a sorted result against an unsorted literal (`/library/` sorts before `https://`)
- **Fix:** `sorted([foreign, live_pic])` on both sides
- **Files modified:** `tests/runtime/test_migration_export_media.py`
- **Verification:** suite green
- **Committed in:** `8f2bec5`

**4. [Rule 1 - Bug] Spec §15 "URL scheme `https` only" claim**
- **Found during:** Task 3 (spec sweep)
- **Issue:** Validator widening made the §15 limits-table claim factually wrong
- **Fix:** Row now reads "`https` URLs or an owned `/library/infinitemarkets/` (legacy `/images/infinitemarkets/`) local path"
- **Files modified:** `docs/technical-specification.md`
- **Verification:** parity suite + verify-fast green
- **Committed in:** `b4ffd78`

---

**Total deviations:** 4 auto-fixed (2 missing-critical, 2 bug/test-fixes)
**Impact on plan:** All within the plan's stated behavior; the quote-needle refinement strengthens the plan's own threat mitigation. No scope creep.

## Issues Encountered
- `test_dual_prefix_references_keep_file_off_unused` passed at RED stage — expected: `_referenced_names` was already prefix-agnostic by construction; the test is positive-retention proof, not a RED witness. RED was carried by the `/library/` path assertion and the serveability 404.
- Out-of-scope observation logged to deferred items: `admin.html` field labels still say "(https or /images/…)" — UI copy only, Phase 7 editor scope.

## User Setup Required
None — no external service configuration required. m019 runs automatically on boot via the host's `run_migration` discovery.

## Next Phase Readiness
- Phase 6 gap closed; MEDIA-06/MEDIA-07 re-verifiable — emitted `/library/` URLs are fetchable and kind-0 absolute URLs resolve on the qualified host.
- Phase 7 (editor UI) can rely on `results[].path`/`url` being serveable and on catalog accepting owned relative prefixes service-side.

---
*Phase: 06-secure-media-storage*
*Completed: 2026-10-16*

## Self-Check: PASSED

- FOUND: `.planning/phases/06-secure-media-storage/06-04-SUMMARY.md`
- FOUND: `8260e7b` (task 1), `8f2bec5` (task 2), `b4ffd78` (task 3)
- Stub scan on all modified source files: no TODO/FIXME/placeholder markers; all new code wired and behavior-tested.
