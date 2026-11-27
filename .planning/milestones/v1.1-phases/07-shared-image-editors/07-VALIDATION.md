---
phase: "07"
slug: shared-image-editors
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-10-16
---

# Phase 7 — Shared Image Editors Validation Contract

Four implementation plans are authored (07-01 unused-listing extension,
07-02 shared picker module + hero tracer, 07-03 product gallery, 07-04
settings field sites + Media card). Permanent tests are authored inside
the tasks that change behavior — every test-bearing task carries
`tdd="true"` with `expected_red`/`positive_retention` grammar per the
Phase 6 precedent — not deferred to a separate test-only wave 0. The
research test map (07-RESEARCH.md "Validation Architecture" / "Phase
Requirements → Test Map" / "Wave 0 Gaps") is executed by those tasks.
Contract assertions that pin already-correct server behavior (e.g.
`PATCH` `images: []` clear-all semantics — catalog.py deletes+reinserts
on key presence today) are recorded as positive retention, not
manufactured RED. Existing passing suites do not close new assertions.

| Requirement | Required negative-path regression / gate | Test surface | Status |
|---|---|---|---|
| MEDIA-02 | Picker selector sends `backend=blossom` only when explicitly chosen; Blossom option renders only when `blossom_servers` is non-empty; local is the mount-time default every time | `tests/runtime/test_admin_ui.py` (new markup asserts); `tests/runtime/test_blossom_upload.py` (Phase-6 first-server-only suite, regression-run) | Pending RED/GREEN |
| MEDIA-03 | Blossom failure surfaces problem copy AND an explicit text-labeled "Save to LNbits instead" retry control — no silent local failover path exists | `tests/runtime/test_admin_ui.py` (new copy/identifier asserts); `tests/runtime/test_blossom_upload.py` (server-side failure semantics, regression-run) | Pending RED/GREEN |
| MEDIA-08 | `gm-media-picker` element present at all seven sites (gallery + avatar + banner + brand logo + hero + footer logo + share custom); `admin_media.js` script tag carries the shared `?v=` revision; module registers `window.app.component("gm-media-picker"` | `tests/runtime/test_admin_ui.py` (new) | Pending RED/GREEN |
| MEDIA-09 | Gallery tiles carry Primary badge at index 0, Move up/Move down/Remove labels, Clear all + Add image by URL controls; 21st image refused client-side before upload | `tests/runtime/test_admin_ui.py` (markup + `admin_catalog.js` identifiers); `tests/runtime/test_catalog_api.py` (reorder/clear regressions) | Pending RED/GREEN |
| MEDIA-10 | Avatar/banner + four appearance q-inputs preserved verbatim alongside pickers; Remove-image clears only its own field (profile merge + theme rebuild carry siblings unchanged) | `tests/runtime/test_admin_ui.py` (preserved-label asserts); `tests/runtime/test_merchant_api.py` (profile_json/theme PATCH semantics, regression-run) | Pending RED/GREEN |
| MEDIA-11 | Pasted `https://` + owned `/library/`/`/images/` values round-trip; Add-by-URL rejects foreign relative/`http://` client-side before API | `tests/runtime/test_media_upload.py::test_catalog_accepts_owned_relative_image_prefixes` + `tests/runtime/test_catalog_api.py` dual-prefix cases (Phase-6, regression-run); new UI asserts | Pending RED/GREEN |
| MEDIA-12 | Per-file progress/error identifiers present (`upload.onprogress`, per-entry `error`/`pending`); a rejected file's entry is excluded from save serialization while siblings remain; cancel-after-upload disclosure copy present on every editor close path | `tests/runtime/test_admin_ui.py` (JS-string + copy asserts); `node --check` on edited JS | Pending RED/GREEN |
| MEDIA-13 | `PATCH /products/{id}` `"images": []` empties `product_images`; populated list persists in sent order; omitting `images` preserves rows; ordering reaches NIP-99/public projections unchanged | `tests/runtime/test_catalog_api.py` (new clear-all + reorder + omit-preserve); `tests/runtime/test_catalog_events.py`, `tests/runtime/test_public_pages.py` (regression-run) | Pending RED/GREEN |
| MEDIA-14 | `IMAGES_MAX = 20` unchanged; UI cap copy agrees with the service constant; the existing incremental-limit test stays green | `tests/runtime/test_catalog_api.py::test_product_image_incremental_limit` (existing); `tests/runtime/test_admin_ui.py` (copy assert) | Pending RED/GREEN |
| D-18/D-23 | `GET /media/unused` returns `files[].mtime` + `used_bytes`/`quota_bytes` (quota == `MAX_MERCHANT_BYTES`); sidecar-owned and referenced files still never listed; no route added — parity suite untouched | `tests/runtime/test_media_upload.py` (extend); `tests/qualification/test_p0_14_contract_closure.py` (regression-run) | Pending RED/GREEN |

Runtime filenames above are under `tests/runtime/`. Route-level tests use
the `runtime_env` host-boot fixture; runtime files boot the host and are
NOT part of `make verify-fast`. `node --check` covers syntax on every
edited `.js`; served-markup truth is asserted by the host-boot
`test_admin_ui.py` suite — there is no browser test harness in this
stack, so "the picker works" is proven by markup/module contracts plus
the Phase-6 API suite whose FormData contract the XHR helper emits
(`usage`/`backend`/`file` + `X-CSRF-Token` — verify commands in 07-02
regression-run `test_media_upload.py` for exactly this).

## Exact per-task validation mapping

Run commands from repo root; `uv run` resolves the pinned host via
`tools/checkout_host.py`. No dependency installation. Marker selection:
`-m fast` for the fast gate; host-boot files are excluded from it by
marker, so per-task verification runs the named files directly.

| Task ID | Wave | Req | Permanent target / intended assertion direction | Automated command | Status |
|---|---:|---|---|---|---|
| 07-01-01 | 1 | MEDIA-12 (D-23) | `files[]` entries gain numeric `mtime`; response gains `used_bytes`/`quota_bytes` == `MAX_MERCHANT_BYTES`; RED = missing keys | `uv run pytest tests/runtime/test_media_upload.py -q -k unused` | Pending RED/GREEN |
| 07-01-02 | 1 | MEDIA-12 (D-23) | `list_unused` emits the fields; spec §5.6 prose names them; sorted order + sidecar/referenced exclusions retained | `uv run pytest tests/runtime/test_media_upload.py -q`; `uv run ruff check infinitemarkets/services/media.py`; `uv run pytest tests/qualification/test_p0_14_contract_closure.py -q` | Pending RED/GREEN |
| 07-02-01 | 1 | MEDIA-02/03/08/12 | `admin_media.js` tag + hero `gm-media-picker` + component/XHR/CSRF identifiers in served HTML+JS; RED = absent module/markup | `node --check infinitemarkets/static/infinitemarkets/js/admin_media.js`; `uv run pytest tests/runtime/test_admin_ui.py -q -k "media_picker or shell_document"` | Pending RED/GREEN |
| 07-02-02 | 1 | MEDIA-03/10 | Thumbnail + Remove-image control + "Save to LNbits instead" retry + `media-*` ERROR_COPY keys present | `node --check infinitemarkets/static/infinitemarkets/js/admin_settings.js infinitemarkets/static/infinitemarkets/js/admin_app.js`; `uv run pytest tests/runtime/test_admin_ui.py -q -k "media_picker or shell_document or settings_buttons"` | Pending RED/GREEN |
| 07-03-01 | 2 | MEDIA-09/12/14 | `admin_catalog.js`: no `images_text` remains; `body.images` unconditional; gmSeoImage reads `form.images[0]`; all gallery mutators + close-path disclosure helper present | `node --check infinitemarkets/static/infinitemarkets/js/admin_catalog.js`; grep gates in the task's own verify | Pending GREEN-only (JS logic has no host-boot unit surface; behavior proven by 07-03-02's tests) |
| 07-03-02 | 2 | MEDIA-09/11/13/14 | Clear-all PATCH empties `product_images`; ordered replace persists; omitted `images` preserves; gallery markup/copy asserts | `uv run pytest tests/runtime/test_catalog_api.py -q -k "image or product"`; `uv run pytest tests/runtime/test_admin_ui.py -q -k "media_picker or shell_document or product_editor"` | Pending RED/GREEN (admin_ui asserts RED; catalog_api cases pin already-correct API semantics = positive retention) |
| 07-04-01 | 3 | MEDIA-08/10/11 | Pickers at avatar/banner/brand/footer/share; preserved labels green; `/library/` label copy; `result.url`-only binding for profile | `node --check admin_settings.js`; `uv run pytest tests/runtime/test_admin_ui.py -q -k "settings_key_reveal or settings_buttons or media_picker"` | Pending RED/GREEN |
| 07-04-02 | 3 | MEDIA-12 (D-18) | `gmSettings.media` state + `/media/unused` load/delete/delete-all methods; card markup + quota bar | `node --check admin_settings.js`; `uv run pytest tests/runtime/test_admin_ui.py -q -k "settings_buttons or media"` | Pending RED/GREEN |
| 07-04-03 | 3 | MEDIA-08/10/12 | Same-commit contract asserts: all sites, label copy, Media card markers | `uv run pytest tests/runtime/test_admin_ui.py -q` | Pending RED/GREEN |

Target RED must be an intentional named assertion failure (absent markup
strings/module identifiers for UI contracts; missing response keys for
07-01). Import/fixture/collection failures and `node --check` syntax
errors are INVALID_RED — fix first, never record as behavioral RED.
Persist command/exit/expected/actual and the GREEN clean exit. Repeated
tests remain permanent. `nyquist_compliant` and `status` stay `draft`
until implementation evidence exists.

## Execution checks

- Each test-bearing task authors its assertions in the same commit as the
  markup/JS they cover (D-29 — `test_admin_ui.py` greps served output
  verbatim; `test_settings_buttons_are_solid` forbids `outline` q-btn
  inside `data-gm-surface="settings"`).
- Per-task: `node --check` every edited `.js`; `uv run ruff check .` when
  Python is touched (07-01 only).
- Per-plan merge gate: `make verify-fast` green. Phase gate before
  `/gsd-verify-work`: `make verify-fast` plus focused runtime files
  (`test_admin_ui.py`, `test_catalog_api.py`, `test_media_upload.py`,
  `test_catalog_events.py`, `test_public_pages.py`) green on SQLite (and
  PG when the CI matrix runs).
- No new routes this phase — `test_routes_match_spec_bidirectional` is a
  regression-run only; the §5.6 change is prose inside an existing
  route's description (D-23).
- No public-network writes in any test; the only "upload" assertions are
  markup/module contracts — byte-level upload behavior was proven in
  Phase 6 and is regression-run here.

## Sign-off

- [ ] All task-level RED→GREEN transitions recorded with named failures (positive-retention cases labeled, not manufactured).
- [ ] `make verify-fast` green.
- [ ] Focused runtime files green: `test_admin_ui.py`, `test_catalog_api.py`, `test_media_upload.py`, `test_catalog_events.py`, `test_public_pages.py`.
- [ ] `node --check` clean on `admin_media.js`, `admin_catalog.js`, `admin_settings.js`, `admin_app.js`.
- [ ] `nyquist_compliant` and `status` updated only after evidence exists.
