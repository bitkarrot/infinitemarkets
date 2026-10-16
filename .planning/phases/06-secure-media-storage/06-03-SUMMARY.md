---
phase: 06-secure-media-storage
plan: 03
subsystem: api
tags: [media, blossom, bud-02, bud-11, nostr, kind-0, dispatch]

requires:
  - phase: 06-secure-media-storage/06-01
    provides: services/media.py local adapter (store_local, origin_is_public) + POST /media/upload bounded route
  - phase: 06-secure-media-storage/06-02
    provides: services/blossom.py upload_blob (BUD-02/BUD-11) + order-preserving set_blossom_servers
provides:
  - media.store_upload — single backend dispatch point (local default / blossom-first-server-only)
  - media._store_blossom — remote branch: typed failure naming the server, zero local write, no failover
  - events.merchant_profile_event absolutizes /images/infinitemarkets/ picture+banner via public_base_url
  - route-level Blossom test matrix against the loopback fake (first-server, failure, quota-scope, MEDIA-04)
affects: [phase-07 media editor UI, phase-08 release qualification matrix]

actuals:
  tokens: 8204      # chars/4 over the realized diff (32,815 chars across 8 files)
  tasks: 2
  commits: 4        # measured ledger→HEAD
  plan_head_before: 6c7fb7041b885c2d2cb3877e8b1f8f0f45b18872

tech-stack:
  added: []
  patterns:
    - "One dispatch point behind the route: store_upload(merchant, user, files, *, usage, backend) — the route stays a thin multipart parser"
    - "Iterate FILES, never the server list — no failover loop is the whole point of the locked first-server-only decision"
    - "Remote failure re-raises ProblemError with the original status/code, detail prefixed by the failed server URL"
    - "kind-0 emit-side absolutization: /images/infinitemarkets/ prefix + non-empty public_base_url only — never a broken concatenation"

key-files:
  created:
    - .planning/phases/06-secure-media-storage/red-evidence/06-03-task1.json
    - .planning/phases/06-secure-media-storage/red-evidence/06-03-task2.json
  modified:
    - infinitemarkets/services/media.py
    - infinitemarkets/services/events.py
    - infinitemarkets/services/outbox.py
    - infinitemarkets/views_api.py
    - docs/technical-specification.md
    - tests/runtime/test_media_upload.py
    - tests/runtime/test_blossom_upload.py
    - tests/runtime/test_catalog_events.py

key-decisions:
  - "The D-05/D-08 profile-origin gate moved from the route into store_upload's local branch — usage=profile + backend=blossom is allowed on a private public_base_url because the remote https descriptor URL is the alternative the gate's message itself recommends"
  - "Remote failure surfaces request-level (not per-file): already-PUT blobs are honest orphans under the D-01 unreferenced-blob disclosure"
  - "Response shape names the backend at top level (backend=local|blossom) and per stored result (+server for blossom); local keeps path+url, blossom keeps url only (no path)"
  - "Problem status preserved on remote-failure re-raise (ProblemError(exc.status, ...)) — blossom.py raises only 422 today, but the wrapper never downgrades a future status"

patterns-established:
  - "Host-boot tests in a fast-marked module: module pytestmark drops to runtime and each keystore-level test carries @pytest.mark.fast explicitly — the seconds-scale gate never includes a host boot"

requirements-completed: [MEDIA-01, MEDIA-04, MEDIA-07, MEDIA-15, MEDIA-16, MEDIA-18]

coverage:
  - id: D1
    description: "POST /media/upload backend field: absent/local -> identical local storage with backend disclosed; invalid value -> 422; blossom with no configured server -> plain-language media-backend 422, zero local bytes"
    requirement: MEDIA-01
    verification:
      - kind: e2e
        ref: "tests/runtime/test_media_upload.py#test_media_upload_backend_dispatch, #test_media_upload_rejects_unknown_fields_and_usage"
        status: pass
    human_judgment: false
  - id: D2
    description: "backend=blossom PUTs ONLY to get_blossom_servers()[0] — verifiable BUD-02/BUD-11 wire at the fake; servers[1] records zero requests; result carries backend/server/descriptor url"
    requirement: MEDIA-15
    verification:
      - kind: e2e
        ref: "tests/runtime/test_blossom_upload.py#test_route_upload_blossom_targets_first_configured_server"
        status: pass
    human_judgment: false
  - id: D3
    description: "Remote failure (HTTP 500 / descriptor mismatch) -> typed media-remote problem naming the server, zero local bytes, second server untouched — no silent failover"
    requirement: MEDIA-16
    verification:
      - kind: e2e
        ref: "tests/runtime/test_blossom_upload.py#test_route_upload_blossom_failure_is_explicit"
        status: pass
    human_judgment: false
  - id: D4
    description: "Upload response discloses backend/server and carries no BUD-11 token, event JSON, or key material; blossom bytes never count toward the 400 MB local quota (D-06)"
    requirement: MEDIA-04
    verification:
      - kind: e2e
        ref: "tests/runtime/test_blossom_upload.py#test_route_upload_blossom_response_carries_no_signing_material, #test_route_upload_blossom_bytes_never_count_toward_local_quota"
        status: pass
    human_judgment: false
  - id: D5
    description: "kind-0 content emits absolute https for /images/infinitemarkets/ picture+banner via public_base_url; absolute values byte-identical; empty base unchanged; unrelated keys untouched"
    requirement: MEDIA-07
    verification:
      - kind: unit
        ref: "tests/runtime/test_catalog_events.py#test_merchant_profile_absolutizes_local_image_paths"
        status: pass
    human_judgment: false
  - id: D6
    description: "Spec §5.6 fenced block + prose document the backend field; HTTP_ROUTES parity unchanged (no new route literals)"
    requirement: MEDIA-18
    verification:
      - kind: unit
        ref: "tests/qualification/test_p0_14_contract_closure.py#test_routes_match_spec_bidirectional"
        status: pass
    human_judgment: false

duration: 10min
completed: 2026-10-16
status: complete
---

# Phase 6 Plan 03: Backend Dispatch + kind-0 Absolutization Summary

**`POST /media/upload` now dispatches on an explicit `backend` field — local default or Blossom PUT to the first configured server only, with typed no-failover failure semantics — and the merchant's kind-0 profile emits absolute https URLs for locally stored picture/banner images.**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-10-16T07:16:29Z
- **Completed:** 2026-10-16T07:26:00Z
- **Tasks:** 2
- **Files modified:** 8 (0 created)

## Accomplishments

- `media.store_upload(merchant_id, user, files, *, usage, backend)` is the single dispatch point: `local` (or absent) keeps the exact 06-01 path including the D-05/D-08 profile-origin gate; `blossom` PUTs each file to `get_blossom_servers()[0]` only — the loop iterates files, never the server list. A remote failure re-raises a typed problem naming the failed server with **zero local bytes written** and the second configured server never contacted (locked no-failover/no-dual-write decisions proven by fake-server assertions).
- `backend=blossom` with no configured server returns a plain-language `media-backend` 422 telling the merchant to configure a Blossom server in Settings → Merchant or upload to local LNbits storage; a `backend` outside `{local, blossom}` is a 422. The 400 MB quota gates the local branch only — a merchant at quota still uploads via Blossom (D-06). Responses disclose `backend` (+ `server` for Blossom, plus the validated descriptor `url`) and carry no token/key material (MEDIA-04/15).
- `merchant_profile_event` gained `public_base_url` (mirroring `handler_info_event`): stored relative `/images/infinitemarkets/` picture/banner values emit as `public_base_url + path` in kind-0 content — the publish-path safety net completing MEDIA-07 alongside 06-01's absolute-URL storage; `outbox.py` passes `_public_base_url()` at the only production call site.
- Spec §5.6 fenced comment + prose document the `backend` field semantics; `test_routes_match_spec_bidirectional` and the full p0_14 file stay green (no new route literals needed).

## Task Commits

Each task was committed atomically (TDD RED→GREEN):

1. **Task 1: backend dispatch on POST /media/upload**
   - `a5db704` test(06-03): RED — 6 named dispatch failures (backend field rejected as invalid file field / no media-backend or media-remote codes)
   - `fef3d6f` feat(06-03): store_upload + _store_blossom + route backend field + spec §5.6 update
2. **Task 2: kind-0 absolutization**
   - `1b22e4c` test(06-03): RED — relative path emitted verbatim (`/images/...` == expected `https://shop.example/images/...`)
   - `cb6db61` feat(06-03): public_base_url kwarg + outbox call site

## Verification

- `uv run pytest tests/runtime/test_media_upload.py tests/runtime/test_blossom_upload.py -q` — **40 passed** (34 pre-existing + 6 new)
- `uv run pytest tests/runtime/test_catalog_events.py -q` — **17 passed**
- `uv run pytest tests/qualification/test_p0_14_contract_closure.py -q` — **11 passed, 1 skipped** (parity intact)
- `make verify-fast` — **318 passed, 2 skipped** (+1 over wave-1 baseline: the new catalog_events unit test is fast-marked; route-level host-boot tests correctly stay out of the gate)
- `uv run ruff check .` — clean
- Zero public-network writes: every Blossom exchange runs against the loopback `ThreadingHTTPServer` fake with monkeypatched egress/connection seams.

## Files Created/Modified

- `infinitemarkets/services/media.py` — `MEDIA_BACKENDS` vocabulary, `store_upload` dispatcher, `_store_blossom` remote branch (first-server-only, typed failure naming the server, per-file MEDIA-05 gates retained, no quota accounting); local stored results now name `backend: "local"`
- `infinitemarkets/views_api.py` — `media_upload` reads/validates the optional `backend` field (allowlist → 422 otherwise) and calls `store_upload`; profile-origin gate moved into the service
- `infinitemarkets/services/events.py` — `merchant_profile_event` absolutizes `/images/infinitemarkets/` picture/banner via `public_base_url`
- `infinitemarkets/services/outbox.py` — kind-0 build passes `public_base_url=_public_base_url()`
- `docs/technical-specification.md` — §5.6 fenced comment + prose for `backend` semantics (`media-backend`/`media-remote`, no failover, D-06 quota scope)
- `tests/runtime/test_media_upload.py` — `test_media_upload_backend_dispatch`; rejects test updated for the new field vocabulary (+ arbitrary non-file field assertion)
- `tests/runtime/test_blossom_upload.py` — 5 route-through-fake-server dispatch tests (first-server-only, failure naming, no-signing-material, D-06 quota scope); per-test `fast` marks (see Deviations)
- `tests/runtime/test_catalog_events.py` — `test_merchant_profile_absolutizes_local_image_paths` (+ signature-gating helper so RED fails on the verbatim-emission assertion, not a TypeError)

## Decisions Made

- **Profile-origin gate is local-only.** `usage=profile` + `backend=blossom` is allowed on a private `public_base_url`: the gate exists because local URLs derive from `public_base_url`, while a Blossom descriptor URL is remote https — the exact "external https/Blossom image" alternative the gate's own message recommends. The gate moved from the route into `store_upload`'s local branch.
- **Request-level remote failure.** If file N of a multi-file blossom request fails, the request raises the typed problem; earlier files remain stored remotely (honest unreferenced-blob orphans under the D-01 disclosure) rather than silently re-homed.
- **Response naming.** Top-level `backend` on both branches; per-file stored results carry `backend` (+ `server`/`url` for Blossom, `path`/`url` for local). MEDIA-04's no-secrets contract is test-asserted structurally.
- **Signature-gated RED helper.** `merchant_profile_event` gained a new kwarg, so the test helper inspects the signature and drops the kwarg on baseline — the RED failure is the planned verbatim-emission assertion rather than a TypeError (which the plan marks INVALID_RED).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking contract conflict] Per-test `fast` marks in `test_blossom_upload.py`**
- **Found during:** Task 1 test authoring
- **Issue:** The plan assigns route-through-fake-server tests to `test_blossom_upload.py`, whose module `pytestmark` carried `fast`. `runtime_env` tests boot a real host — a host boot inside the "runs in seconds" `-m fast` gate would violate the documented marker contract (AGENTS.md: non-host-boot files only) and slow the quick gate.
- **Fix:** Module `pytestmark` dropped to `runtime`; each of the 11 keystore-level test functions now carries `@pytest.mark.fast` explicitly (identical 20-test fast selection). New route tests are runtime-only.
- **Files modified:** `tests/runtime/test_blossom_upload.py`
- **Verification:** `make verify-fast` = 318 passed (20 blossom service tests still selected; the +1 is the new fast-marked catalog_events unit test)
- **Committed in:** `a5db704`

**2. [Rule 2 - Missing critical semantics] Profile-origin gate scoped to the local branch**
- **Found during:** Task 1 GREEN
- **Issue:** The plan's signature passes `usage` into `store_upload` but doesn't say where the D-05/D-08 gate lives. Keeping it unconditionally in the route would block `usage=profile` + `backend=blossom` on private origins — contradicting the gate's own remediation message ("use an external https/Blossom image instead").
- **Fix:** Gate moved into `store_upload`, applied on the local branch only.
- **Files modified:** `infinitemarkets/services/media.py`, `infinitemarkets/views_api.py`
- **Verification:** `test_media_upload_profile_usage_requires_public_origin` still green (local gate intact); blossom dispatch tests green
- **Committed in:** `fef3d6f`

**3. [Environment override — inherited] Commits on `main`**
- Same as 06-01/06-02: `branching_strategy: "none"` + `git.allow_default_branch_commits: true` in `.planning/config.json`; the spec's protected-branch gate resolves `main` as unprotected under this override.

**Total deviations:** 2 auto-fixed + 1 inherited environment override
**Impact on plan:** Marker restructure preserves the fast gate exactly; the gate scoping is required for the plan's own semantics. No scope creep.

## Issues Encountered

- None beyond the deviations. The fake-server wiring reused 06-02's seams (`resolve_and_check_egress` + `_open_connection` monkeypatch points) extended to a per-host map so the no-failover assertion observes which configured host was dialed.

## User Setup Required

None - no external service configuration required.

## TDD Gate Compliance

| Task | RED commit | GREEN commit | Evidence |
|------|-----------|--------------|----------|
| 1 | `a5db704` | `fef3d6f` | RED_EVIDENCE_OK — 6 named failures: `test_media_upload_backend_dispatch` (422 on `backend=local`) + 5 route tests (`media-remote`/`200` assertions) — `.planning/.../red-evidence/06-03-task1.json` |
| 2 | `1b22e4c` | `cb6db61` | RED_EVIDENCE_OK — `test_merchant_profile_absolutizes_local_image_paths` fails asserting emitted `/images/...` == expected `https://shop.example/images/...` (verbatim emission) — `06-03-task2.json` |

No violations. (Note: `tdd_mode` is disabled in project config; the gate evidence was still produced per the plan's `tdd="true"` task attributes.)

## Next Phase Readiness

- `POST /media/upload` is the full-featured seam Phase 7's editor UI calls: `usage` + `backend` fields, per-file results naming the backend/server, plain-language `media-backend`/`media-remote`/`media-origin` problems for disclosure copy.
- MEDIA-07 is closed on both sides: uploads store absolute URLs (D-07) and kind-0 emission absolutizes any residual relative path (D-04).
- Phase-6 success criteria all demonstrable: local default + bounds (06-01), BUD-02/11 server-side-signed remote (06-02), first-server-only dispatch + no failover (this plan), absolute profile URLs, spec/registry parity green.

## Self-Check: PASSED

All modified files verified on disk; commits `a5db704`, `fef3d6f`, `1b22e4c`, `cb6db61` verified in `git log`. `git rev-list --count 6c7fb70..HEAD` = 4, all this plan's.

---
*Phase: 06-secure-media-storage*
*Completed: 2026-10-16*
