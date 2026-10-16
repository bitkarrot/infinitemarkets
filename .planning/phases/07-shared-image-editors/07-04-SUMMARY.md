---
phase: 07-shared-image-editors
plan: 04
subsystem: ui
tags: [media, upload, vue, quasar, settings, blossom, quota, tdd]

requires:
  - phase: 07-shared-image-editors
    plan: 01
    provides: GET /media/unused extended response — files[].mtime +
      used_bytes/quota_bytes (D-23) powering the Media card
  - phase: 07-shared-image-editors
    plan: 02
    provides: gm-media-picker component, gmMedia mixin (servers +
      gmMediaUpload XHR), hero tracer pattern (thumbnail + Remove
      image + Save-to-LNbits retry), media-* ERROR_COPY keys
  - phase: 06-secure-media-storage
    provides: usage=profile media-origin server gate (D-22), DELETE
      /media/unused/{name} referenced re-check + name fullmatch
provides:
  - gm-media-picker at every settings image site — profile avatar +
    banner (usage=profile, result.url binding per https-only
    validators), brand logo + footer logo + share custom image
    (usage=appearance, dotted-path gmMediaThemeUpload binding
    result.path local / result.url blossom)
  - shared gmMediaThemeUpload/gmMediaProfileUpload handlers with
    site-scoped Blossom retry (gmMedia.retrySite) and single-field
    clear (gmMediaSetTheme/gmMediaClearField/gmMediaClearProfile)
  - Settings → Merchant Media card (data-gm=media-card): dated unused
    list, per-item Delete, Delete all unused, quota bar — backed by
    the extended /media/unused response
  - D-19 label fix: footer-logo + share-custom labels name /library/
affects: [phase-7 closure, MEDIA-08/10/11/12 complete]

actuals:
  tokens: 7500      # chars/4 over the realized diff (~30k chars across 4 files)
  tasks: 3
  commits: 2        # measured ledger→HEAD at summary write (docs commit follows)
  plan_head_before: a666edb742afb8e9516e3acf5d62266796d9b639

tech-stack:
  added: []
  patterns:
    - "D-26 field-value matrix completed: profile fields bind result.url ALWAYS (https-only client+server validators — a /library/ path 422s invalid-profile); appearance fields bind result.path|result.url by result.backend"
    - "gmMedia.retrySite scopes the shared Blossom-failure retry to the field whose upload failed — one gmMedia slice serves six pickers without cross-site retry bleed"
    - "Media-card failures collect into the card's own error slot (gmSettings.media.error) and always reload the list — a file can become referenced between list and delete (T-07-04-02)"

key-files:
  created:
    - .planning/phases/07-shared-image-editors/red-evidence/07-04-task3.json
  modified:
    - infinitemarkets/templates/infinitemarkets/admin.html
    - infinitemarkets/static/infinitemarkets/js/admin_settings.js
    - tests/runtime/test_admin_ui.py

key-decisions:
  - "gmMediaHeroUpload is now a thin wrapper over gmMediaThemeUpload('hero.image_url') — the 07-02 markup contract is preserved while every appearance field shares one upload body"
  - "gmMedia.retrySite is a string site key (theme dotted path or profileAvatar/profileBanner) — retry v-if's and the gmMediaRetryLocal dispatch both read it, so the shared retryLocal flag can't offer a retry at the wrong field"
  - "Media card lives between the relay/Blossom card and the inbox card in the Merchant tab — sits with the other media-server controls per RESEARCH open question 2"
  - "Media-card entry shape is normalized in gmMediaUnusedLoad to {name, bytes, mtime} — the card binds only what it renders"

patterns-established:
  - "Per-site upload block = picker + shared progress + site-scoped retry + thumbnail/Remove; the identical block shape at every field (D-20) with only the files-chosen binding, site key, model binding, and alt text varying"
  - "gmMediaProfileUpload(field, payload) is the two-call-site profile body; avatar/banner bind thin named wrappers so markup stays greppable"

requirements-completed: [MEDIA-08, MEDIA-10, MEDIA-11, MEDIA-12]

coverage:
  - id: D1
    description: "gm-media-picker renders at all six remaining settings sites — profile avatar + banner (usage=profile ×2 with gmMediaAvatarUpload/gmMediaBannerUpload) and brand logo + footer logo + share custom image (gmMediaThemeUpload dotted-path handlers); share picker inside the custom_image v-if; URL q-inputs preserved adjacent (D-29)"
    requirement: MEDIA-08
    verification:
      - kind: e2e
        ref: "tests/runtime/test_admin_ui.py#test_admin_media_settings_sites"
        status: pass
    human_judgment: false
  - id: D2
    description: "Profile fields bind result.url always (https-only); appearance fields bind result.path(local)/result.url(blossom); single-field replace/clear touches only its own key (gmMediaSetTheme/gmMediaClearProfile + profile_json merge)"
    requirement: MEDIA-10
    verification:
      - kind: e2e
        ref: "tests/runtime/test_admin_ui.py#test_admin_media_settings_sites (JS identifiers)"
        status: pass
    human_judgment: false
  - id: D3
    description: "All seven field sites keep the pasted-URL workflow — avatar/banner/brand/footer/share q-inputs verbatim, pickers adjacent"
    requirement: MEDIA-11
    verification:
      - kind: e2e
        ref: "tests/runtime/test_admin_ui.py#test_settings_key_reveal + test_admin_media_settings_sites (preserved-label asserts)"
        status: pass
    human_judgment: false
  - id: D4
    description: "Settings → Merchant Media card: dated unreferenced-file list (gmBytes + mtime via gmTime), per-item Delete, Delete all unused, quota bar from used_bytes/quota_bytes, empty state; 409 media-referenced surfaces copy + reloads"
    requirement: MEDIA-12
    verification:
      - kind: e2e
        ref: "tests/runtime/test_admin_ui.py#test_admin_media_card"
        status: pass
    human_judgment: false
  - id: D5
    description: "Browser-visible behavior — picker/upload/progress/thumbnail at the six sites and the Media card interactions render correctly in the admin shell"
    requirement: MEDIA-12
    verification:
      - kind: manual_procedural
        ref: "open Settings → Merchant + Appearance, upload via a picker, observe progress/thumbnail; open the Media card, delete an unused file"
        status: unknown
    human_judgment: true
    rationale: "No browser test harness in this stack — markup/module contracts are proven; rendered interaction needs human eyes"

duration: 12min
completed: 2026-10-16
status: complete
---

# Phase 07 Plan 04: Settings Field Sites + Media Card Summary

**The shared picker now covers every settings image field — profile avatar/banner bind https `result.url` through the D-22 origin-gated `usage="profile"` path while brand/footer-logo/share bind per-backend `result.path`/`result.url` — and Settings → Merchant gains a Media card (dated unused list, per-item + delete-all, quota bar) fed by 07-01's extended `/media/unused`.**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-10-16T22:02:07Z
- **Completed:** 2026-10-16T22:14:00Z
- **Tasks:** 3 (folded into one commit slice per the plan's D-29 note)
- **Files modified:** 2 source/template files + 1 test file + 1 red-evidence record

## Accomplishments

- Profile avatar + banner: `gm-media-picker usage="profile"` adjacent to the preserved `Avatar URL (https)`/`Header image URL (https)` inputs; `gmMediaProfileUpload` binds `result.url` ALWAYS (both validators are https-only — a `/library/` path 422s `invalid-profile`), surfaces `media-origin` copy when the server blocks a private-origin upload (D-22), thumbnail + text-labeled "Remove image" (`gmMediaClearProfile`), and the explicit "Save to LNbits instead" Blossom retry.
- Appearance brand logo + footer logo + share custom image: pickers bound to `gmMediaThemeUpload('<dotted path>', $event)` storing `result.path` (local) / `result.url` (blossom — a remote result never gets a synthesized path, T-07-04-01); the share picker sits inside the `card_image === 'custom_image'` v-if.
- `gmMediaHeroUpload` refactored into the shared `gmMediaThemeUpload` body (hero = `'hero.image_url'` wrapper); `gmMediaSetTheme` extracted as the generic dotted setter with `gmMediaClearField` delegating — single-key mutation, siblings preserved through the whole-object theme save (MEDIA-10).
- Blossom retry is site-scoped: `gmMedia.retrySite` records the failing field (theme path or `profileAvatar`/`profileBanner`); each site's retry block renders only for its own failure and `gmMediaRetryLocal` re-dispatches to the correct handler — never a silent failover (MEDIA-03).
- Settings → Merchant Media card (`data-gm="media-card"`): plain-language caption, `q-linear-progress` quota bar ("{{ gmBytes(usedBytes) }} of {{ gmBytes(quotaBytes) }} stored" — quota never hardcoded), `q-list` of unused files (truncated name + formatted bytes + mtime date), per-item Delete, "Delete all unused" (sequential, failures collected into the card error), empty state; `media-referenced` 409s surface `gmProblemCopy` and refresh (T-07-04-02). `gmMediaUnusedLoad` wired into `gmLoadSettings`.
- D-19: footer-logo and share-custom labels now read `(https or /library/…)`; brand logo's `/path` hint untouched per plan scope.

## Task Commits

Each task was committed atomically (TDD RED→GREEN; Tasks 1–3 folded into one commit slice per the plan's test-placement note):

1. **Task 3 RED: failing assertions for sites + Media card** — `9283c8b` (test)
2. **Tasks 1+2 GREEN: pickers + Media card markup/JS** — `2a52d60` (feat)

**Plan metadata:** pending (docs commit for this SUMMARY + STATE/ROADMAP updates)

## TDD Gate Compliance

| Task | RED commit | GREEN commit | Evidence |
|------|-----------|--------------|----------|
| 3 (covers 1+2 markup) | `9283c8b` | `2a52d60` | RED_EVIDENCE_OK — `test_admin_media_settings_sites` failed `assert 0 == 2` on `usage="profile"` count; `test_admin_media_card` failed on absent `data-gm="media-card"` |

Record persisted at `.planning/phases/07-shared-image-editors/red-evidence/07-04-task3.json` (verified `RED_EVIDENCE_OK` via `check tdd-red-evidence` — `targetTest` had to name a single failing test; initial combined string rejected as `no_target_test_failure`, corrected). Positive retention on baseline: `test_admin_media_picker`, `test_settings_key_reveal` (avatar/banner labels verbatim), `test_settings_buttons_are_solid` — all green.

## Files Created/Modified

- `infinitemarkets/templates/infinitemarkets/admin.html` — pickers + per-site upload blocks at avatar/banner/brand/footer/share; Media card after the relay card; `/library/` label fixes; hero retry scoped to `retrySite`
- `infinitemarkets/static/infinitemarkets/js/admin_settings.js` — `gmMediaThemeUpload`/`gmMediaProfileUpload`/`gmMediaAvatarUpload`/`gmMediaBannerUpload`/`gmMediaSetTheme`/`gmMediaClearProfile`, site-scoped `gmMediaRetryLocal`, `gmSettings.media` slice + `gmBytes`/`gmMediaUnusedLoad`/`gmMediaUnusedDelete`/`gmMediaUnusedDeleteAll`, `gmLoadSettings` wiring
- `tests/runtime/test_admin_ui.py` — `test_admin_media_settings_sites` + `test_admin_media_card`
- `.planning/phases/07-shared-image-editors/red-evidence/07-04-task3.json` — RED evidence

## Decisions Made

- One shared `gmMedia` upload-state slice serves all six pickers; only the retry control needed site scoping (`retrySite`) — progress/uploading stay shared since one upload runs at a time.
- Profile-card progress renders per-picker (same hero pattern); retry is additionally gated on `retrySite` so a failed banner upload can't show a retry under the avatar.
- Media card placed between the relay/Blossom card and the inbox card — with the other media-server controls (RESEARCH open question 2 discretion).
- `gmMediaUnusedDeleteAll` runs sequential per-file DELETEs and counts failures into the card error — partial success stays truthful rather than aborting.
- `files_modified` honored: `gmBytes` and `retrySite` live inside `admin_settings.js`/dynamic `gmMedia` keys (Vue 3 reactivity handles new keys) — no `admin_media.js`/`admin_app.js` edits needed.

## Deviations from Plan

None — plan executed as written. Two sequencing details, not behavior changes: (a) Tasks 1–3 folded into the single commit slice the plan explicitly authorizes for D-29; (b) `gmMediaHeroUpload` kept as a named wrapper so the 07-02 markup/test contract survived the shared-body refactor.

## Issues Encountered

- First `check tdd-red-evidence` run returned `INVALID_RED/no_target_test_failure` — `targetTest` must name one failing test; corrected to `test_admin_media_settings_sites` and the record verified `RED_EVIDENCE_OK`. No code impact.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- All seven image-field sites now share the one control (gallery + avatar + banner + hero + brand + footer + share): MEDIA-08 fully covered; MEDIA-10/11/12 contract-pinned by `test_admin_ui.py`.
- Phase 7 implementation is complete — remaining work is phase-level verification (`make verify-fast` green: 318 passed, 2 skipped; focused runtime files green: `test_admin_ui.py` 33, `test_media_upload.py` 19).
- No blockers.

## Self-Check: PASSED

- FOUND: `.planning/phases/07-shared-image-editors/07-04-SUMMARY.md`
- FOUND: `9283c8b` (test RED commit) — `git log` verified
- FOUND: `2a52d60` (feat GREEN commit) — `git log` verified
- FOUND: `.planning/phases/07-shared-image-editors/red-evidence/07-04-task3.json`

---
*Phase: 07-shared-image-editors*
*Completed: 2026-10-16*
