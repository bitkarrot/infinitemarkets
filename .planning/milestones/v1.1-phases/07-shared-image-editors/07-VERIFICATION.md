---
phase: 07-shared-image-editors
verified: 2026-10-16T22:11:57Z
status: human_needed
score: 7/8 must-haves verified
covered_files:
  - .planning/phases/07-shared-image-editors/07-01-PLAN.md
  - .planning/phases/07-shared-image-editors/07-01-SUMMARY.md
  - .planning/phases/07-shared-image-editors/07-02-PLAN.md
  - .planning/phases/07-shared-image-editors/07-02-SUMMARY.md
  - .planning/phases/07-shared-image-editors/07-03-PLAN.md
  - .planning/phases/07-shared-image-editors/07-03-SUMMARY.md
  - .planning/phases/07-shared-image-editors/07-04-PLAN.md
  - .planning/phases/07-shared-image-editors/07-04-SUMMARY.md
  - .planning/phases/07-shared-image-editors/07-CONTEXT.md
  - .planning/phases/07-shared-image-editors/07-VALIDATION.md
  - docs/technical-specification.md
  - infinitemarkets/services/media.py
  - infinitemarkets/static/infinitemarkets/js/admin_app.js
  - infinitemarkets/static/infinitemarkets/js/admin_catalog.js
  - infinitemarkets/static/infinitemarkets/js/admin_media.js
  - infinitemarkets/static/infinitemarkets/js/admin_settings.js
  - infinitemarkets/templates/infinitemarkets/admin.html
  - tests/runtime/test_admin_ui.py
  - tests/runtime/test_catalog_api.py
  - tests/runtime/test_media_upload.py
covered_digest: "v1:sha256:91f06b47114cfff7cf2b23195d540e295129cfbecb70398999703b636ca721bd"
behavior_unverified: 1
overrides_applied: 0
behavior_unverified_items:
  - truth: "Upload progress and per-file errors are visible; a failed file does not discard other selected images; cancelling before saving discloses a possible unreferenced blob"
    test: "In a running admin, upload a batch where one file fails (e.g. oversize), confirm siblings still land in the gallery; then close the editor via Cancel and confirm the 'Settings → Media' disclosure notice appears"
    expected: "Per-file progress bars render; the failed tile shows error copy while siblings retain their stored URLs; the unreferenced-upload disclosure notice fires on editor close"
    why_human: "The invariant lives in client-side JS (gmGalleryFiles sequential loop, editor.uploadsUnsaved flag, gmDiscloseUnsavedUploads). This stack has no browser test harness — markup and identifier contracts are proven, but the runtime JS loop/toast behavior is not exercised by any test"
human_verification:
  - test: "Open Settings → Appearance → Hero, drop or pick an image, observe the per-file progress bar and thumbnail, then Save appearance"
    expected: "Progress renders, thumbnail + 'Remove image' appear, field stores a /library/ path (local) or https URL (Blossom); picker's drop-zone copy names the chosen destination"
    why_human: "No browser harness — rendered Vue component interaction is not covered by markup contracts"
  - test: "Catalog → New/Edit product: upload 2+ images (include one that will fail, e.g. >8 MB), use Move up/Move down, Remove, Clear all, Add image by URL; save and confirm ordering on the public product page"
    expected: "Primary badge on tile 0, 21st image refused with 'You can add up to 20 images per product.', failed file errors in place without discarding siblings, persisted order matches editor order"
    why_human: "Gallery interaction (reorder/error tile/progress) is client-side JS; API semantics are proven but rendered behavior is not"
  - test: "Upload an image then close the product editor via Cancel without saving"
    expected: "Notice: 'Images you uploaded are still stored — they weren't attached to a product. You can remove them in Settings → Media.'"
    why_human: "Disclosure toast is runtime Vue state; no test executes it"
  - test: "With a Blossom server configured, choose 'Save to Blossom · <host>' on a profile field, force a failure (e.g. unreachable host), observe the error + 'Save to LNbits instead' retry; retry and confirm it lands"
    expected: "Plain-language media-remote error, explicit site-scoped retry button, retry stores to LNbits; no automatic local write on Blossom failure"
    why_human: "Requires a real/mocked-unreachable Blossom endpoint; the contract (retrySite scoping, no failover path) is code-proven but the end-to-end flow is not"
  - test: "Settings → Merchant → Media card: confirm the dated unused list, quota bar, per-item Delete and 'Delete all unused' behave and refresh"
    expected: "Files show name/size/date; deletes remove entries and update the quota bar; media-referenced 409s surface copy and reload the list"
    why_human: "Card interaction is runtime JS; identifiers are contract-pinned only"
---

# Phase 7: Shared Image Editors Verification Report

**Phase Goal:** Merchants can manage every in-scope image field with consistent upload, editing, and persistence behavior without losing existing references or unrelated settings.
**Verified:** 2026-10-16T22:11:57Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | SC1 — Reusable upload control at all seven image fields (gallery, profile avatar, banner, brand logo, hero, footer logo, custom share image) | ✓ VERIFIED | `admin.html`: `<gm-media-picker` at lines 655 (`usage="catalog" multiple`), 1992/2019 (`usage="profile"`), 2584/2650/2723/2771 (`usage="appearance"`); `admin_media.js` registers `window.app.component("gm-media-picker")` (line 31) and loads via `admin_media.js?v={{ asset_revision }}` (admin.html:3606). Pinned by `test_admin_media_picker`, `test_admin_media_settings_sites`, `test_product_editor_gallery`. |
| 2 | SC2 — Explicit local/Blossom choice per upload; Blossom targets only the first configured server; failure gives plain error + explicit local retry, no silent failover | ✓ VERIFIED | Picker `data.backend` defaults `"local"` on every mount (admin_media.js:45); Blossom `q-select` renders only `v-if="blossomServers.length"` (line 111) and labels `Save to Blossom · <hostname>`; backend resolves `server = servers[0]` (media.py:241) — no reordering/dual-write. `gmMediaRetryLocal` re-dispatches `{files:[file], backend:"local"}` scoped by `retrySite` (admin_settings.js:1224-1236); `Save to LNbits instead` buttons at six sites (admin.html:2003/2030/2595/2661/2734/2782). Server-side first-server/failure semantics proven by `test_blossom_upload.py` (25 passed). |
| 3 | SC3 — Gallery ≤20 images, thumbnails, visible primary, ordering, per-image removal, explicit clear-all; persists via catalog API to public pages + Nostr projections; 20-cap agrees service/spec/UI/tests | ✓ VERIFIED | Gallery markup: `v-for` thumbnail tiles, `Primary` q-badge at `i === 0`, Move up/Move down/Remove buttons, `N / 20` counter, Clear all, Add-by-URL (admin.html:619-672). `IMAGES_MAX = 20` in catalog.py:43 and admin_catalog.js:111; spec §15 line 1872. `body.images` sent unconditionally, filtering pending/error entries (admin_catalog.js:515-517); server delete+reinsert on key presence (catalog.py:782-800). Behavioral: `test_product_images_clear_all_via_empty_array`, `test_product_images_ordered_replace_and_omit_preserves`, `test_product_image_incremental_limit` all pass; `test_catalog_events.py` + `test_public_pages.py` regression green (114 passed). |
| 4 | SC4 — Single-image replace/clear touches only its own field; pasted HTTPS + owned `/images/…`/`/library/…` URLs still work | ✓ VERIFIED | `gmMediaSetTheme` dotted-path setter mutates exactly one theme key (admin_settings.js:1241-1251); `gmMediaClearProfile` clears only avatar/banner (1259-1263); `profile_json` merge preserves unrelated keys (asserted `Object.assign({}, self.gmSettings.profileJson`). All URL q-inputs preserved verbatim adjacent to pickers (labels confirmed in markup + `test_settings_key_reveal`). `_valid_image_url` accepts https + `MEDIA_URL_PREFIX` + `LEGACY_MEDIA_URL_PREFIX` (catalog.py:61-71); client mirror `OWNED_IMAGE_PREFIXES` (admin_catalog.js:115-118). |
| 5 | SC5 — Per-file progress/errors visible; failed file keeps siblings; cancel-before-save discloses unreferenced uploads; remote Blossom blobs never auto-deleted | ⚠️ PRESENT_BEHAVIOR_UNVERIFIED | Present + wired: XHR `upload.onprogress` (admin_media.js:169), per-entry `pending`/`progress`/`error` tiles (admin.html:630-638), sequential `gmGalleryFiles` loop marks the failed entry and continues (admin_catalog.js:550-586), `gmDiscloseUnsavedUploads` fires on every close path — `gmCloseProductEditor`, `gmOpenBulkEditor`, `gmNewProduct`, `gmEditProduct` (lines 634-644, 393, 419, 667). No Blossom delete path exists anywhere. BUT: no test executes the client-side JS loop/toast — see Human Verification items 2-4. |
| 6 | GET /media/unused returns files[].mtime + top-level used_bytes/quota_bytes (D-23) | ✓ VERIFIED | `list_unused` emits `mtime` (stat().st_mtime), `used_bytes` (`_dir_bytes`), `quota_bytes` (`MAX_MERCHANT_BYTES`) — media.py:317-357. `test_unused_listing_reports_mtime_and_quota` passes (test_media_upload.py:458). |
| 7 | No route added or changed — spec §5 ↔ registry parity untouched (D-23) | ✓ VERIFIED | Only §5.6 prose extended (spec lines 839-842); route table unchanged; `test_p0_14_contract_closure.py` green inside `make verify-fast` (318 passed). |
| 8 | Settings → Merchant Media card: dated unused list, per-item delete, delete-all, quota bar (D-18) | ✓ VERIFIED | `data-gm="media-card"` at admin.html:2228 — caption, `q-linear-progress` quota bar bound to `usedBytes/quotaBytes`, `q-list` entries with `gmBytes`/`gmTime(f.mtime)`, per-item Delete, `Delete all unused`, empty state. `gmMediaUnusedLoad/Delete/DeleteAll` consume the extended response and reload after mutations (admin_settings.js:1274-1329); wired into `gmLoadSettings` (line 527). Pinned by `test_admin_media_card`. |

**Score:** 7/8 truths verified (1 present, behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `infinitemarkets/static/infinitemarkets/js/admin_media.js` | gm-media-picker component + gmMediaUpload XHR + gmMedia state | ✓ VERIFIED | 199 lines; component + mixin + CSRF + progress; `node --check` clean |
| `infinitemarkets/templates/infinitemarkets/admin.html` | Script tag, 7 picker sites, gallery markup, Media card, retry controls | ✓ VERIFIED | All sites + `?v=` script tag present |
| `infinitemarkets/static/infinitemarkets/js/admin_catalog.js` | Unified gallery state, mutators, unconditional `body.images` | ✓ VERIFIED | `images_text` fully removed (0 hits); D-21/D-27 serialization |
| `infinitemarkets/static/infinitemarkets/js/admin_settings.js` | Profile/theme upload handlers, retry, clear helpers, Media card methods | ✓ VERIFIED | All identifiers present |
| `infinitemarkets/static/infinitemarkets/js/admin_app.js` | media-* ERROR_COPY entries | ✓ VERIFIED | `media-quota`, `media-backend`, `media-origin`, `media-remote` at lines 43-46 |
| `infinitemarkets/services/media.py` | list_unused emits mtime + quota fields | ✓ VERIFIED | Lines 317-357 |
| `tests/runtime/test_admin_ui.py` | Markup/module contracts | ✓ VERIFIED | New tests pass (33 in file) |
| `tests/runtime/test_media_upload.py` | Unused-listing extension assertions | ✓ VERIFIED | 19 passed incl. `test_unused_listing_reports_mtime_and_quota` |
| `tests/runtime/test_catalog_api.py` | images semantics pins | ✓ VERIFIED | 25 passed incl. clear-all/ordered-replace/omit-preserve/incremental-limit |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| gm-media-picker | POST /media/upload | `gmMediaUpload` XHR, FormData `usage`/`backend`/`file`, `X-CSRF-Token` | WIRED | admin_media.js:159-195; FormData contract matches server parser (Phase-6 suite green) |
| Picker `files-chosen` | Field handlers | `{files, backend}` payload → `gmGalleryFiles`/`gmMediaThemeUpload`/`gmMediaProfileUpload` | WIRED | Bindings confirmed in markup for all 7 sites |
| Picker `servers-needed` | `gmMediaLoadServers` | Lazy `GET /merchants/{id}/relay-health` → `blossom_servers` | WIRED | admin_media.js:73, 138-156 |
| Gallery save | catalog API | `body.images` always sent ([]=clear, populated=ordered replace) | WIRED | admin_catalog.js:515-517 → catalog.py:782-800 |
| Media card | GET/DELETE /media/unused | `gmMediaUnusedLoad/Delete/DeleteAll` via `gmApi` | WIRED | admin_settings.js:1279/1303/1318 |
| Blossom failure | Local retry | `retryFile`/`retrySite` → `gmMediaRetryLocal` re-dispatch | WIRED | admin_settings.js:1224-1236; site-scoped `v-if` gates |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| Media card | `gmSettings.media.files`/`usedBytes`/`quotaBytes` | `GET /media/unused` | Yes | ✓ FLOWING |
| Gallery tiles | `gmCatalog.editor.form.images` | `GET /products/{id}` (`d.images`) + upload `result.url` + pasted URL | Yes | ✓ FLOWING |
| Destination selector | `gmMedia.servers` | relay-health `blossom_servers` / `gmSettings.blossom` seed | Yes | ✓ FLOWING |
| Quota bar | `usedBytes / quotaBytes` | response fields (07-01) | Yes | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Fast gate (contract + unit) | `make verify-fast` | 318 passed, 2 skipped (43s) | ✓ PASS |
| Focused runtime files | `pytest test_admin_ui test_media_upload test_catalog_api test_catalog_events test_public_pages -q` | 114 passed (34s) | ✓ PASS |
| Blossom first-server/failure suite | `pytest tests/runtime/test_blossom_upload.py -q` | 25 passed (16s) | ✓ PASS |
| Lint | `uv run ruff check .` | All checks passed | ✓ PASS |
| JS syntax | `node --check` on admin_media/admin_catalog/admin_settings/admin_app | all OK | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| MEDIA-02 | 07-02 | Explicit Blossom choice; first configured server only, no dual-write/reorder | ✓ SATISFIED | backend=`servers[0]` (media.py:241); picker local-default + conditional Blossom option; test_blossom_upload.py 25 green |
| MEDIA-03 | 07-02 | Blossom failure → plain error + explicit local retry | ✓ SATISFIED | `media-remote`/`media-backend` ERROR_COPY; site-scoped `Save to LNbits instead` retry; no failover path in code |
| MEDIA-08 | 07-02/03/04 | One reusable control at all seven image fields | ✓ SATISFIED | 7 `<gm-media-picker>` sites, one shared component definition |
| MEDIA-09 | 07-03 | Multi-file gallery: thumbnails, primary, ordering, per-image removal, clear-all | ✓ SATISFIED | Gallery markup + mutators; `test_product_editor_gallery` green |
| MEDIA-10 | 07-04 | Single-image replace/clear without disturbing siblings | ✓ SATISFIED | Dotted-path setters; profile_json merge; preserved inputs |
| MEDIA-11 | 07-03/04 | Pasted https + owned `/library/`/`/images/` URLs keep working | ✓ SATISFIED | Client `OWNED_IMAGE_PREFIXES` + server `_valid_image_url` dual-prefix; labels preserved |
| MEDIA-12 | all | Per-file progress/errors; siblings preserved; cancel discloses unreferenced blob | ✓ SATISFIED (markup/contracts) | XHR progress, per-entry error state, `gmDiscloseUnsavedUploads` on all close paths; rendered behavior → human list |
| MEDIA-13 | 07-03 | Ordering/removal/clear-all persist via catalog API → public pages + Nostr | ✓ SATISFIED | catalog_api pins green; catalog_events + public_pages regression green |
| MEDIA-14 | 07-03 | 20-image cap agrees service/spec/UI/tests | ✓ SATISFIED | `IMAGES_MAX=20` in catalog.py:43 + admin_catalog.js:111; spec line 1872; incremental-limit test green |

No orphaned requirements — every Phase-7-mapped ID (MEDIA-02/03/08-14) is claimed by at least one plan's `requirements:` field.

### Deferred-Scope Exclusion Check

| Deferred item | Evidence it stayed out |
|---------------|------------------------|
| Drag-drop reordering | No `draggable`/sortable attribute on gallery tiles — ordering is Move up/Move down buttons only (D-15) |
| Remote-blob management UI | Media card reads only `GET /media/unused` (local filesystem listing); no Blossom blob list/delete UI anywhere |
| Server-side thumbnail generation | `grep thumbnail media.py` empty; tiles use the original URL as `img.thumb` |
| MEDIA-20…23 (mirroring, kind-10063, remote delete, transforms) | No related code added |

### Upload-Copy Obligations (07-CONTEXT specifics)

| Obligation | Evidence |
|-----------|----------|
| Names the destination server | `"saved to {{ destinationLabel }}"` → `"Blossom · <hostname>"` / `"this LNbits"` (admin_media.js:56-59, 107-109) |
| Upload-vs-save separation | `"Uploading is not saving; save the form to keep it."` (admin_media.js:109); per-site `"Image uploaded — save appearance/identity to keep it."` |
| Unreferenced-blob warning on cancel | `UNSAVED_UPLOADS_COPY` → Settings → Media pointer (admin_catalog.js:119-121) fired by `gmDiscloseUnsavedUploads` on all close paths |
| Local fallback explanation | `Save to LNbits instead` retry + `media-quota`/`media-backend`/`media-remote` copy recommending the fallback (admin_app.js:43-46) |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| — | — | — | — | None. `TBD`/`FIXME`/`XXX`/`TODO`/`HACK`/`PLACEHOLDER` scan over all phase-edited files: no hits. No stub returns; all dynamic values flow from real queries/uploads. |

### Human Verification Required

### 1. Hero upload end-to-end

**Test:** Settings → Appearance → Hero: drop or pick an image, observe progress bar + thumbnail, save.
**Expected:** Progress renders; thumbnail + "Remove image" appear; field stores `/library/…` (local) or https (Blossom).
**Why human:** No browser test harness — rendered component behavior isn't covered by markup contracts.

### 2. Gallery interaction + 20-cap + persistence

**Test:** Catalog product editor: upload ≥2 images (incl. one that fails, e.g. >8 MB), reorder via buttons, Remove, Clear all, Add-by-URL; save and check public page ordering.
**Expected:** Primary badge on tile 0; "You can add up to 20 images per product." refusal; failed file errors in place without discarding siblings; saved order matches.
**Why human:** Client-side JS loop/reorder behavior is proven by contract, not execution.

### 3. Cancel disclosure toast

**Test:** Upload an image, close the editor via Cancel without saving.
**Expected:** Notice that uploaded images remain stored and can be removed in Settings → Media.
**Why human:** Toast is runtime Vue state — no test executes it.

### 4. Blossom failure → explicit local retry

**Test:** With Blossom configured, choose "Save to Blossom · <host>" on a profile field, force a failure, observe error + retry; retry stores locally.
**Expected:** Plain `media-remote` copy; site-scoped "Save to LNbits instead"; no silent local write.
**Why human:** Needs a real/unreachable Blossom endpoint; contract proven, flow unexercised.

### 5. Media card interactions

**Test:** Settings → Merchant → Media: unused list shows name/size/date; Delete and Delete all unused work; quota bar updates.
**Expected:** Entries refresh; referenced-409 surfaces copy + reload.
**Why human:** Card interaction is runtime JS.

### Gaps Summary

No gaps. All automated checks pass; the only unverified surface is rendered browser behavior, which this stack cannot test without a browser harness — five human items above cover it. The phase's must-have on per-file failure semantics (SC5) is present + wired but its JS-level invariant is unexercised, hence `human_needed` rather than `passed`.

---

_Verified: 2026-10-16T22:11:57Z_
_Verifier: Claude (gsd-verifier)_
