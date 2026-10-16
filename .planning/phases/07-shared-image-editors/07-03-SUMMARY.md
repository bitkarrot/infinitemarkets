---
phase: 07-shared-image-editors
plan: 03
subsystem: ui
tags: [media, gallery, vue, quasar, xhr, catalog, blossom, reorder]

requires:
  - phase: 07-shared-image-editors
    plan: 02
    provides: gm-media-picker component (files-chosen {files, backend}
      payload), gmMedia mixin (servers list + gmMediaUpload XHR helper),
      hero tracer proving the end-to-end upload path
  - phase: 06-secure-media-storage
    provides: POST /media/upload catalog usage, _valid_image_url
      dual-prefix allowlist, product_images delete+reinsert on `images`
      key presence (catalog.py:782-800)
provides:
  - admin_catalog.js unified gallery state — form.images[] entries
    {url, thumb, kind, pending, progress, error}; gmGalleryFiles/AddUrl/
    Move/Remove/ClearAll mutators; gmDiscloseUnsavedUploads +
    gmCloseProductEditor
  - unconditional body.images serialization in gmSaveProduct — the D-21
    clear-all fix (omitted=preserve, []=clear, populated=ordered replace)
  - admin.html gallery control: thumbnail tiles, Primary badge at index
    0, text-labeled Move up/down/Remove, N / 20 counter, shared picker
    usage="catalog" multiple, Add-by-URL row, Clear all, disclosure hint
  - catalog API persistence pins: clear-all via [], ordered replace,
    omit-preserves
affects: [07-04 settings field sites + Media card (reuses the same
  picker + disclosure pattern), storefront/Nostr image ordering]

actuals:
  tokens: 5700      # chars/4 over the realized diff (~22.8k chars across source+test files)
  tasks: 2
  commits: 3        # measured ledger→HEAD on shared main
  plan_head_before: 5fa39968b2487c884c245ce1977bf46c180bb792

tech-stack:
  added: []
  patterns:
    - "Unified gallery entry shape {url, thumb, kind, pending, progress, error} — pending placeholder tiles carry per-file XHR progress; pending/error entries are filtered out of the save body"
    - "Cancel-disclosure via shared gmDiscloseUnsavedUploads() invoked from EVERY editor close/replace path (Cancel handler, gmOpenBulkEditor, gmNewProduct, gmEditProduct) — not a Cancel-only hook"
    - "gmOwnedImagePath: owned-prefix check that also unwraps absolute https URLs to their pathname (catalog stores result.url per D-26) so locally-stored images badge as local"

key-files:
  created:
    - .planning/phases/07-shared-image-editors/red-evidence/07-03-task2.json
  modified:
    - infinitemarkets/static/infinitemarkets/js/admin_catalog.js
    - infinitemarkets/templates/infinitemarkets/admin.html
    - tests/runtime/test_catalog_api.py
    - tests/runtime/test_admin_ui.py

key-decisions:
  - "Editor close-path disclosure implemented as gmDiscloseUnsavedUploads + gmCloseProductEditor; flag lives on editor.uploadsUnsaved, cleared on editor open and successful save — never auto-deletes (locked decision)"
  - "gmSeoImage rewired to the first non-pending non-error entry (index 0 IS Primary per D-15) — keeps the SERP preview working after images_text removal"
  - "Per-file upload failures mark the tile's error + keep siblings; the tile carries its own Remove affordance so a rejected upload can be dropped"

patterns-established:
  - "Gallery mutators are pure splices on form.images — ordering IS the save order (sort_order defaults to list index server-side)"
  - "Client-side _valid_image_url mirror: https:// or owned /library/infinitemarkets// /images/infinitemarkets/ prefix — foreign-relative/http values error plainly and never reach the API (T-07-03-01)"

requirements-completed: [MEDIA-08, MEDIA-09, MEDIA-11, MEDIA-12, MEDIA-13, MEDIA-14]

coverage:
  - id: D1
    description: "Unified gallery state in admin_catalog.js: images[] entries seeded in both editor constructors, all mutators, unconditional body.images save (D-21/D-27 fix), 20-cap copy, uploadsUnsaved disclosure on every close path"
    requirement: MEDIA-09
    verification:
      - kind: e2e
        ref: "tests/runtime/test_admin_ui.py#test_product_editor_gallery"
        status: pass
      - kind: other
        ref: "node --check infinitemarkets/static/infinitemarkets/js/admin_catalog.js"
        status: pass
    human_judgment: false
  - id: D2
    description: "admin.html gallery control: thumbnail tiles + Primary badge + Move up/down/Remove labels + N/20 counter + gm-media-picker usage=\"catalog\" multiple + Add-by-URL + Clear all + disclosure hint"
    requirement: MEDIA-08
    verification:
      - kind: e2e
        ref: "tests/runtime/test_admin_ui.py#test_product_editor_gallery"
        status: pass
    human_judgment: false
  - id: D3
    description: "PATCH /products/{id} images semantics: [] clears product_images, populated list persists in sent order (sort_order=list index), omitted key preserves rows — flows to storefront/Nostr projections unchanged"
    requirement: MEDIA-13
    verification:
      - kind: e2e
        ref: "tests/runtime/test_catalog_api.py#test_product_images_clear_all_via_empty_array + test_product_images_ordered_replace_and_omit_preserves (positive-retention pins)"
        status: pass
      - kind: e2e
        ref: "tests/runtime/test_catalog_events.py + tests/runtime/test_public_pages.py (regression)"
        status: pass
    human_judgment: false
  - id: D4
    description: "20-image cap enforced client-side before upload with plain-language copy, matching server IMAGES_MAX"
    requirement: MEDIA-14
    verification:
      - kind: e2e
        ref: "tests/runtime/test_catalog_api.py#test_product_image_incremental_limit (existing, green) + test_admin_ui.py copy assert"
        status: pass
    human_judgment: false
  - id: D5
    description: "Cancel-after-upload disclosure toast renders correctly and browser-visible gallery interaction (thumbnails, reorder, progress bars) behaves in the admin shell"
    requirement: MEDIA-12
    verification:
      - kind: e2e
        ref: "tests/runtime/test_admin_ui.py#test_product_editor_gallery (identifier/copy asserts)"
        status: pass
      - kind: manual_procedural
        ref: "open Catalog → New product, upload an image, hit Cancel, observe the 'Settings → Media' notice toast"
        status: unknown
    human_judgment: true
    rationale: "No browser test harness in this stack — markup/module contracts are proven; the toast firing and tile interaction need human eyes"

duration: 9min
completed: 2026-10-16
status: complete
---

# Phase 7 Plan 03: Product Gallery Summary

**Unified thumbnail gallery replaces the product editor's `images_text` textarea — mixed upload/URL tiles with Primary badge, button ordering, per-file progress/errors, Clear all and Add-by-URL — and product save now always serializes `images`, fixing the Phase-6 clear-all bug where a length-guard made `[]` unreachable.**

## Performance

- **Duration:** ~9 min
- **Started:** 2026-10-16T21:49:31Z
- **Completed:** 2026-10-16T21:58:00Z
- **Tasks:** 2
- **Files modified:** 2 source/template files + 2 test files + 1 red-evidence record

## Accomplishments

- `admin_catalog.js`: `form.images` unified entry list (`{url, thumb, kind, pending, progress, error}`) seeded in `gmNewProduct` (`[]`) and `gmEditProduct` (kind inferred via owned-prefix pathname check — relative `/library/`/`/images/` AND absolute `result.url` forms both badge as local); `gmSeoImage` rewired to the first non-pending entry so the search preview survives the textarea's removal.
- Gallery mutators: `gmGalleryFiles` (20-cap check BEFORE upload, sequential `gmMediaUpload(file, "catalog", backend, onProgress)` per file, pending placeholder → stored `result.url`/error, `uploadsUnsaved` set on stored files, siblings never discarded), `gmGalleryAddUrl` (client-side `_valid_image_url` mirror), `gmGalleryMove`, `gmGalleryRemove`, `gmGalleryClearAll`.
- `gmSaveProduct` sends `body.images` unconditionally — `[{url}]` filtered to non-pending/non-error entries. Omitted=preserve / `[]`=clear-all / populated=ordered-replace (D-21/D-27); the Phase-6 pitfall is dead.
- MEDIA-12 disclosure: `gmDiscloseUnsavedUploads()` pushes the Settings → Media notice when `uploadsUnsaved`; invoked from `gmCloseProductEditor` (new Cancel handler), `gmOpenBulkEditor`, `gmNewProduct`, `gmEditProduct` — every close/replace path. Nothing auto-deleted.
- `admin.html`: gallery control with fixed 96px `q-img` tiles (reserved aspect space), `Primary` badge at index 0 only, text-labeled Move up/Move down/Remove (disabled at bounds), per-tile `q-linear-progress` + error text, `N / 20` counter, `<gm-media-picker usage="catalog" multiple>`, in-control Add-by-URL row, Clear all, and the unchanged remote-host disclosure hint.
- Tests: `test_product_images_clear_all_via_empty_array` + `test_product_images_ordered_replace_and_omit_preserves` (catalog API, positive-retention pins — green on baseline, server already delete+reinserts on key presence); `test_product_editor_gallery` (admin UI markup + JS identifiers).

## Task Commits

1. **Task 1: Gallery state + mutators + unconditional serialization** — `7fb18c0` feat(07-03)
2. **Task 2 (TDD):**
   - `64823bd` test(07-03) — RED: `test_product_editor_gallery` named assertion failure on `images_text` still rendered (RED_EVIDENCE_OK, persisted at `red-evidence/07-03-task2.json`); the two catalog_api cases recorded as positive-retention GREEN
   - `f403905` feat(07-03) — GREEN: gallery markup + `gmCloseProductEditor` Cancel wiring

## TDD Gate Compliance

| Task | RED commit | GREEN commit | Evidence |
|------|-----------|--------------|----------|
| 2 | `64823bd` | `f403905` | RED_EVIDENCE_OK — `test_product_editor_gallery` failed on `assert "images_text" not in editor` (textarea still present). New `test_catalog_api.py` cases are positive-retention pins per the plan's `expected_red` — recorded in the evidence JSON, not manufactured RED. |

## Files Created/Modified

- `infinitemarkets/static/infinitemarkets/js/admin_catalog.js` — unified gallery state, mutators, disclosure helper, unconditional serialization
- `infinitemarkets/templates/infinitemarkets/admin.html` — gallery markup replacing the textarea; Cancel → `gmCloseProductEditor`; `.gm-gallery*` CSS
- `tests/runtime/test_catalog_api.py` — clear-all + ordered-replace + omit-preserve pins
- `tests/runtime/test_admin_ui.py` — `test_product_editor_gallery` markup/identifier contract
- `.planning/phases/07-shared-image-editors/red-evidence/07-03-task2.json` — RED evidence

## Decisions Made

- `gmOwnedImagePath` unwraps absolute https URLs to their pathname before the owned-prefix check — catalog uploads store `result.url` (absolute) per D-26, so locally-stored files must badge as "local", not "remote". Slightly broader than the plan's literal prefix match; same intent, more correct classification.
- Disclosure flag on `editor.uploadsUnsaved` (per plan text) rather than the mixin root; cleared inside `gmDiscloseUnsavedUploads`, on editor open (fresh object literal), and on successful save.
- Tile buttons stack in a `column` under a 96px thumb inside a 112px tile — dense but fully text-labeled per UI-SPEC.

## Deviations from Plan

**1. [Rule 3 - Verify-command adjustment] The plan's literal catalog verify `-k "image or product"` deselects a fixture-providing test**
- **Found during:** Task 2 RED/positive-retention run
- **Issue:** `test_membership_enqueues_collection_and_product_dep` matches `-k "product"` but consumes `runtime_env["empty_col"]` provisioned by `test_collection_zero_members_no_intent`, which does NOT match the filter — a pre-existing intra-file ordering coupling, unrelated to this plan's changes (INVALID_RED territory: fixture error, not an assertion failure).
- **Fix:** Ran the whole file instead — `uv run pytest tests/runtime/test_catalog_api.py -q` → 25 passed (superset of the plan's selection). The admin_ui half of the verify ran as written.
- **Files modified:** none (verification-only adjustment; the coupling itself is a pre-existing test-design choice — session-scoped env accumulation — logged here rather than "fixed" per scope boundary)

## Issues Encountered

- None beyond the -k ordering coupling above. No host-boot races this wave.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- 07-04 can mount `<gm-media-picker>` verbatim at the remaining five sites (avatar, banner, brand logo, footer logo, share custom) — `gmMediaUpload`, `gmMediaLoadServers`, `gmMediaClearField`, and the disclosure helper pattern are all proven.
- The gallery's `images[]` contract is fully pinned by runtime tests; storefront/Nostr projections inherit ordering unchanged (regression-green: catalog_events + public_pages).
- No blockers. Watch item for the whole phase: runtime test files carry session-scoped `runtime_env` coupling — `-k` subsets must include provider tests or run whole files.

---
*Phase: 07-shared-image-editors*
*Completed: 2026-10-16*

## Self-Check: PASSED

- Created files exist: 07-03-SUMMARY.md, red-evidence/07-03-task2.json
- Commits exist: 7fb18c0 (Task 1), 64823bd (Task 2 RED), f403905 (Task 2 GREEN)
