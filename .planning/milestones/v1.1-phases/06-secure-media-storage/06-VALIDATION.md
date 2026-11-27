---
phase: "06"
slug: secure-media-storage
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-10-16
---

# Phase 6 — Secure Media Storage Validation Contract

Three implementation plans are authored (06-01 local adapter + routes,
06-02 ordering fix + Blossom client, 06-03 dispatch + kind-0 emission);
permanent tests are created inside each code task (every task is
`tdd="true"` — RED via a named assertion failure before implementation),
not deferred to a separate schema/test-only wave 0. The research test map
(06-RESEARCH.md "Validation Architecture" / "Phase Requirements → Test
Map" / "Wave 0 Gaps") is executed by those tasks; there is no Wave-0-only
test scaffold. Existing passing suites do not close new assertions.

| Requirement | Required negative-path regression / gate | Test surface | Status |
|---|---|---|---|
| MEDIA-01 | Upload with no Blossom configured selects local; bytes land under the merchant namespace; default `backend` absent behaves identically | `tests/runtime/test_media_upload.py` (new) | Pending RED/GREEN |
| MEDIA-04 | Response JSON contains no token/key-shaped values; auth event signed server-side via real `MerchantKeyStore.sign_event` custody path; one event per upload | `tests/runtime/test_blossom_upload.py` (new) | Pending RED/GREEN |
| MEDIA-05 | 17th file → 422; >25 MB part rejected; SVG/GIF/empty/non-image bytes rejected without storing; >400 MB merchant quota → 409; descriptor sha256/size/type/url-mismatch each rejected | `tests/runtime/test_media_upload.py`, `tests/runtime/test_blossom_upload.py` | Pending RED/GREEN |
| MEDIA-06 | Stored name matches `[0-9a-f]{64}\.(png\|jpg\|webp)` under `images/infinitemarkets/<ns24>/`; namespace opaque (≠ merchant id) and stable; file served via the host `/images` mount path | `tests/runtime/test_media_upload.py` | Pending RED/GREEN |
| MEDIA-07 | Profile-bound upload on private/loopback/.local `public_base_url` → 422 plain-language problem (D-05/D-08); `merchant_profile_event` absolutizes `/images/infinitemarkets/` picture/banner to `https://` in kind-0 content | `tests/runtime/test_media_upload.py`, `tests/runtime/test_catalog_events.py` (extend) | Pending RED/GREEN |
| MEDIA-15 | Fake Blossom records exact PUT `/upload` headers; decoded `Authorization` is kind-24242 with `t=upload`, `x` == `X-SHA-256`, lowercase-domain `server`, expiration ≈ now+300 (D-09), base64url no padding; signature verifies | `tests/runtime/test_blossom_upload.py` | Pending RED/GREEN |
| MEDIA-16 | Private/loopback egress answers rejected before dialing; resolver consulted per request (spy); 307/308 → exactly one recorded request, body+auth never forwarded; descriptor `url` off-host rejected (D-11) | `tests/runtime/test_blossom_upload.py` | Pending RED/GREEN |
| MEDIA-18 | `test_routes_match_spec_bidirectional` green with `POST /media/upload`, `GET /media/unused`, `DELETE /media/unused/{name}` in a §5 fenced `text` block AND `HTTP_ROUTES` in the same commits | `tests/qualification/test_p0_14_contract_closure.py` (existing gate) | Pending RED/GREEN |
| D-ordering | Unsorted `blossom_servers` PATCH round-trips unsorted through relay-health; dedup preserves first position (reversibility: costly) | `tests/runtime/test_relay_config_api.py` (extend) | Pending RED/GREEN |

Runtime filenames above are under `tests/runtime/`. Route-level tests use
the `runtime_env` host-boot fixture (one real-loader boot per module);
service-level Blossom tests use `keystore_env` (migrated tmp DB, real
signing path) and carry `pytest.mark.fast` alongside `runtime` — no fake
server ever dials a public Blossom endpoint; egress/connection seams are
monkeypatched (`resolve_and_check_egress` → `127.0.0.1`,
`_open_connection` → plain `http.client.HTTPConnection` to the threaded
fixture) while URL validation, tag domains, and descriptor host checks
exercise the real `https://media.example.com` code path.

## Exact per-task validation mapping

Run commands from repo root; `uv run` resolves the pinned host via
`tools/checkout_host.py`. No dependency installation. Bound constants are
monkeypatched small for quota/size tests rather than allocating real
25 MB/400 MB bodies. Marker selection: `-m fast` for the fast gate;
runtime files boot the host and are NOT part of `make verify-fast`.

| Task ID | Wave | Req | Permanent target / intended assertion direction | Automated command | Status |
|---|---:|---|---|---|---|
| 06-01-01 | 1 | MEDIA-01/05/06/07/18 | `POST /media/upload` png→200 with path+absolute url, file on disk, namespace opaque/stable vs 404 pre-implementation; type/size/count/quota/origin-gate rejections | `uv run pytest tests/runtime/test_media_upload.py -q`; `uv run pytest tests/qualification/test_p0_14_contract_closure.py::test_routes_match_spec_bidirectional -q`; `uv run ruff check infinitemarkets/services/media.py infinitemarkets/views_api.py` | Pending RED/GREEN |
| 06-01-02 | 1 | D-02/D-12 | Unused listing shows unreferenced only; sidecar-owned and referenced files absent vs 404 pre-implementation; DELETE 409-referenced/200-idempotent/422-traversal | `uv run pytest tests/runtime/test_media_upload.py -q`; `uv run pytest tests/qualification/test_p0_14_contract_closure.py -q` | Pending RED/GREEN |
| 06-01-03 | 1 | D-07/MEDIA-05 | Catalog PATCH accepts uploaded absolute `https://` URL; sidecar-owned file never listed; migration suite unchanged-green | `uv run pytest tests/runtime/test_media_upload.py tests/runtime/test_migration_export_media.py -q`; `make verify-fast` | Pending RED/GREEN |
| 06-02-01 | 1 | locked order | Unsorted submission preserved vs sorted() baseline; dedup keeps first position; invalid URLs still rejected | `uv run pytest tests/runtime/test_relay_config_api.py -q` | Pending RED/GREEN |
| 06-02-02 | 1 | MEDIA-04/15/16 | Fake-server recorded PUT carries exact BUD-02 headers + verifiable kind-24242 event vs absent `upload_blob` pre-implementation | `uv run pytest tests/runtime/test_blossom_upload.py -q`; `uv run ruff check infinitemarkets/services/blossom.py` | Pending RED/GREEN |
| 06-02-03 | 1 | MEDIA-04/16 | 307 → single request/no auth forward; egress spy + private-answer rejection; descriptor poison matrix; in-flight ≤4 (D-13) | `uv run pytest tests/runtime/test_blossom_upload.py -q`; `uv run pytest -m fast -q` | Pending RED/GREEN |
| 06-03-01 | 2 | MEDIA-01/04/15 | `backend=blossom` targets `servers[0]` only; failure → typed problem, zero local bytes, `servers[1]` untouched; no-config → plain problem; invalid backend → 422; quota local-only (D-06) | `uv run pytest tests/runtime/test_media_upload.py tests/runtime/test_blossom_upload.py -q`; `uv run pytest tests/qualification/test_p0_14_contract_closure.py -q` | Pending RED/GREEN |
| 06-03-02 | 2 | MEDIA-07 | kind-0 content emits absolute https for relative `/images/` profile values vs verbatim baseline; absolute values byte-identical; empty base unchanged | `uv run pytest tests/runtime/test_catalog_events.py -q`; `uv run pytest tests/runtime/test_media_upload.py tests/runtime/test_blossom_upload.py -q`; `make verify-fast` | Pending RED/GREEN |

Target RED must be an intentional named assertion failure (route-level
404 for missing routes; lazy-imported module naming `upload_blob` for the
new client); fixture/import/collection failures are INVALID_RED. Persist
command/exit/expected/actual and the GREEN clean exit. Repeated tests
remain permanent. `nyquist_compliant` and `status` stay `draft` until
implementation evidence exists.

## Execution checks

- Each task authors its RED assertions first, implements to GREEN, then
  reruns its focused files; `uv run ruff check` on touched modules each
  commit.
- Per-wave merge gate: `make verify-fast` green. Phase gate before
  `/gsd-verify-work`: `make verify-fast` plus the three focused runtime
  files green on SQLite (and PG when the CI matrix runs).
- The fake Blossom server is `http.server`-based, loopback-only; no test
  writes to public Blossom servers — formal matrix coverage is Phase 8
  (MEDIA-19) scope.
- New problem codes (`media-origin`, `media-referenced`, `media-backend`,
  `media-remote`) stay out of `registry.ERROR_CODES` per the
  `invalid-content`/`media-scope` precedent; registering one would
  require a literal mention in §5 text to satisfy
  `test_registered_literals_appear_in_spec`.
- `set_blossom_servers` ordering is a costly persisted-contract change:
  pre-existing rows keep alphabetical order; document, never migrate.

## Sign-off

- [ ] All eight task-level RED→GREEN transitions recorded with named failures.
- [ ] `make verify-fast` green including the §5↔registry parity test.
- [ ] Fake-Blossom matrix green with zero public-network writes.
- [ ] Migration media suite unchanged-green (coexistence proven).
- [ ] `nyquist_compliant` and `status` updated only after evidence exists.
