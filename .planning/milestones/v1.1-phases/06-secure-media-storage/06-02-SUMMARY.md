---
phase: 06-secure-media-storage
plan: 02
subsystem: infra
tags: [blossom, bud-02, bud-11, nostr-sdk, ssrf, egress, asyncio, http.client]

requires:
  - phase: 02-relay-admin-surface
    provides: relay.py blossom_servers settings row, validate_blossom_url, relay-health
  - phase: baseline
    provides: security.resolve_and_check_egress, og_images._PinnedHTTPSConnection pattern, keystore.sign_event custody path
provides:
  - infinitemarkets/services/blossom.py — BUD-02 raw PUT /upload client with server-side BUD-11 kind-24242 signing, request-time egress resolution, pinned-IP TLS, no-redirect rule, strict descriptor validation, per-merchant Semaphore(4)
  - order-preserving set_blossom_servers (first configured = primary)
  - tests/runtime/test_blossom_upload.py — loopback fake-Blossom fixture + 20-test protocol/security suite
  - unsorted-order regression in tests/runtime/test_relay_config_api.py
affects: [06-03 dispatch wiring, 07 editor UI, 08 qualification matrix]

actuals:
  tokens: 8424   # chars/4 over realized diff (33,696 chars)
  tasks: 3
  commits: 3
  plan_head_before: 96c3ce0762c78dd77174a42b2fe38031399c7311

tech-stack:
  added: []
  patterns:
    - "BUD-11 token = base64url-NO-PAD JSON of kind-24242 (t=upload, x=sha256, server=lowercase domain, expiration=now+300), signed via MerchantKeyStore.sign_event, one event per upload, never logged/persisted/returned"
    - "Pinned-IP HTTPS PUT: _open_connection/_PinnedHTTPSConnection seam connecting to an egress-checked IP with hostname SNI; module-level seams monkeypatched by tests"
    - "Loopback fake Blossom: ThreadingHTTPServer + scripted handler recording (method, path, headers, body) and in-flight counts"

key-files:
  created:
    - infinitemarkets/services/blossom.py
    - tests/runtime/test_blossom_upload.py
  modified:
    - infinitemarkets/services/relay.py
    - tests/runtime/test_relay_config_api.py

key-decisions:
  - "Canonical MIME map for Content-Type (jpg->image/jpeg) so a jpg upload's wire type satisfies the descriptor type allowlist {image/png,image/jpeg,image/webp} — a literal image/jpg would self-reject against real servers"
  - "Pre-existing blossom_servers rows keep alphabetical order — costly persisted-contract change, documented, no data migration possible"
  - "Per-merchant semaphore is process-local (D-13); a multi-worker PG deployment cannot tighten it further in-process"

requirements-completed: [MEDIA-04, MEDIA-05, MEDIA-15, MEDIA-16]

coverage:
  - id: D1
    description: "set_blossom_servers preserves submission order (first = primary), dedups first-seen, still rejects invalid URLs"
    requirement: "MEDIA-04"
    verification:
      - kind: integration
        ref: "tests/runtime/test_relay_config_api.py#test_blossom_servers_preserve_submission_order"
        status: pass
    human_judgment: false
  - id: D2
    description: "upload_blob emits exact BUD-02 wire format + verifiable BUD-11 kind-24242 event (t=upload, x=sha256, server=domain, expiration~now+300, base64url no-pad) via the real keystore custody path"
    requirement: "MEDIA-15"
    verification:
      - kind: integration
        ref: "tests/runtime/test_blossom_upload.py#test_upload_put_wire_format_and_bud11_auth_event, #test_upload_signs_fresh_event_per_call"
        status: pass
    human_judgment: false
  - id: D3
    description: "request-time egress check on every call; non-public answer aborts before any connection; ALL 3xx rejected without a second request"
    requirement: "MEDIA-16"
    verification:
      - kind: integration
        ref: "tests/runtime/test_blossom_upload.py#test_egress_resolver_consulted_every_call, #test_egress_rejection_precedes_any_connection, #test_redirect_rejected_single_request"
        status: pass
    human_judgment: false
  - id: D4
    description: "descriptor accepted only when sha256/size/type/https same-host url validate; oversized descriptor body refused at the 16KB bound"
    requirement: "MEDIA-05"
    verification:
      - kind: integration
        ref: "tests/runtime/test_blossom_upload.py#test_descriptor_poison_rejected, #test_descriptor_body_bound_rejected"
        status: pass
    human_judgment: false
  - id: D5
    description: "signing stays inside MerchantKeyStore.sign_event; result dict carries descriptor fields only — no token/key material; at most 4 in-flight PUTs per merchant"
    requirement: "MEDIA-04"
    verification:
      - kind: integration
        ref: "tests/runtime/test_blossom_upload.py#test_result_dict_carries_no_key_or_token, #test_in_flight_put_cap_per_merchant"
        status: pass
    human_judgment: false

duration: 10min
completed: 2026-10-16
status: complete
---

# Phase 6 Plan 02: Blossom upload client + server-order fix Summary

**BUD-02 `PUT /upload` client with server-side BUD-11 kind-24242 signing, request-time egress checks, pinned-IP TLS, no redirect following, strict descriptor validation, and the `set_blossom_servers` first-is-primary ordering fix — all proven against a loopback fake Blossom server.**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-10-16T06:59:42Z
- **Completed:** 2026-10-16T07:05:05Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments

- `infinitemarkets/services/blossom.py` — full BUD-02/BUD-11 exchange: raw `PUT {server}/upload` with `X-SHA-256` + `Authorization: Nostr <base64url-no-pad kind-24242>` (tags `t=upload`, `x=<sha256>`, `server=<lowercase domain>`, `expiration=now+300`), signed via `MerchantKeyStore.sign_event`; `resolve_and_check_egress` at request time; pinned-IP TLS with SNI; every 3xx rejected; descriptor gated on sha256/size/type/https same-host url (D-11); per-merchant `Semaphore(4)` (D-13); `asyncio.to_thread` + `wait_for` 20s deadline.
- `set_blossom_servers` now persists submission order (`dict.fromkeys` dedup, no `sorted()`) — the first configured server is the primary every upload consumer trusts.
- 20-test fake-Blossom suite (loopback `ThreadingHTTPServer`, monkeypatched egress/connection seams): wire format, signature/tag verification via `Event.verify()`, descriptor poison matrix, redirect rejection with exactly one recorded request, egress spy + pre-dial rejection, D-13 in-flight cap, no-token-in-result (MEDIA-04).

## Task Commits

1. **Task 1: Preserve configured blossom server order** — `214ba91` (fix)
2. **Task 2: services/blossom.py BUD-02/BUD-11 client** — `73c7588` (feat)
3. **Task 3: fake-Blossom security matrix** — `e8f5f9d` (test)

## TDD Gate Compliance

| Task | RED evidence (named failure) | GREEN |
|------|------------------------------|-------|
| 06-02-01 | `test_blossom_servers_preserve_submission_order` — `AssertionError: ['https://aaa...'] == ['https://zzz...']` (sorted order observed), exit 1 | fix `214ba91`; 9/9 file tests pass |
| 06-02-02 | 12 named failures — `AssertionError: infinitemarkets.services.blossom.upload_blob is not implemented` (lazy import kept collection clean), exit 1 | impl `73c7588`; 12/12 pass |
| 06-02-03 | redirect/egress/cap tests authored after the task-2 impl whose rules they assert — per plan `expected_red`, passing on first run recorded as **positive retention**, no manufactured failure | `e8f5f9d`; 20/20 pass |

## Verification

- `uv run pytest tests/runtime/test_blossom_upload.py -q` — 20 passed
- `uv run pytest tests/runtime/test_relay_config_api.py -q` — 9 passed
- `uv run pytest tests/runtime/test_blossom_upload.py tests/runtime/test_relay_config_api.py -q` — 29 passed
- `make verify-fast` (`uv run pytest -m fast -q`) — **317 passed, 2 skipped** (both pre-existing advisory skips), 755 deselected
- `uv run ruff check` on all touched files — clean
- Zero public-network writes: every test uses the loopback fake; egress/connection seams monkeypatched.

## Files Created/Modified

- `infinitemarkets/services/blossom.py` — BUD-02 PUT client (new)
- `tests/runtime/test_blossom_upload.py` — fake-Blossom fixture + protocol/security suite (new)
- `infinitemarkets/services/relay.py` — `set_blossom_servers` order-preserving dedup + persisted-contract comment
- `tests/runtime/test_relay_config_api.py` — unsorted-order regression test
- `.planning/config.json` — `git.allow_default_branch_commits: true` (spec-sanctioned override; see Deviations)

## Decisions Made

- Canonical MIME map `{png→image/png, jpg→image/jpeg, webp→image/webp}` for the wire `Content-Type` — a literal `image/{ext}` would emit nonstandard `image/jpg` and self-reject against the descriptor type allowlist on real servers.
- `_open_connection(host, address, port=443)` honors an explicit `:port` in the configured endpoint URL (validate_blossom_url preserves ports) while defaulting to 443.
- Redirect rejection names the rule plainly ("Upload endpoint redirected") at 422/`media-remote` — consistent with the `media-remote` code used for all remote-failure modes and kept out of `registry.ERROR_CODES` per the documented precedent.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Canonical `image/jpeg` instead of literal `image/jpg`**
- **Found during:** Task 2 (blossom.py implementation)
- **Issue:** Plan's `Content-Type: image/{ext}` literal emits `image/jpg` for jpeg bodies — a nonstandard MIME a real server may echo back as descriptor `type`, which the required allowlist `{image/png, image/jpeg, image/webp}` would then reject (self-breaking jpg uploads).
- **Fix:** `_MIME_BY_EXT` maps sniffed ext to the canonical MIME.
- **Files modified:** infinitemarkets/services/blossom.py
- **Verification:** wire-format test asserts `image/png`; allowlist stays plan-exact
- **Committed in:** 73c7588

**2. [Rule 1 - Test correctness] Same-second uploads produce identical events**
- **Found during:** Task 2 GREEN run
- **Issue:** Two uploads of identical bytes within one second legitimately produce identical signed events (event id covers content + created_at at second granularity) — the first draft asserted distinct ids and failed despite correct behavior.
- **Fix:** Spy on the real `sign_event` (count == 2 proves per-call signing) and use distinct bodies so `x` tags/ids differ.
- **Files modified:** tests/runtime/test_blossom_upload.py
- **Verification:** 20/20 suite green
- **Committed in:** 73c7588

**3. [Environment override] Commits on `main`**
- **Found during:** setup — executor spec refuses commits on the protected default branch unless `git.allow_default_branch_commits` is set; the orchestrator deliberately runs both wave-1 executors in this same tree on `main` (`branching_strategy: "none"`).
- **Fix:** Added `git.allow_default_branch_commits: true` to `.planning/config.json` (the override the spec names).
- **Committed in:** plan docs commit

**Total deviations:** 2 auto-fixed + 1 environment override
**Impact on plan:** MIME fix required for correctness against real servers; test fix corrects a mis-specified assertion; config override is the spec-sanctioned path for this execution topology. No scope creep.

## Issues Encountered

- None beyond the deviations above. The egress private-answer test asserts rejection propagates BEFORE any connection (delegation contract: `resolve_and_check_egress` owns the public-IP check — `upload_blob` cannot re-check answers because the loopback fake legitimately resolves to 127.0.0.1); per-call consultation is proven by the resolver spy.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- Plan 06-03 can wire `POST /media/upload` dispatch to `upload_blob` targeting `get_blossom_servers()[0]` — ordering is now contract-correct and the client is fully tested at service level.
- Threat register mitigations T-06-02-01…07 all implemented and test-asserted.

## Self-Check: PASSED

All files exist (`blossom.py`, `test_blossom_upload.py`, this SUMMARY);
commits `214ba91`, `73c7588`, `e8f5f9d` verified in `git log`.

---
*Phase: 06-secure-media-storage*
*Completed: 2026-10-16*
