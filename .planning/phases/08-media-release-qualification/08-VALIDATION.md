---
phase: "08"
slug: media-release-qualification
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-10-17
---

# Phase 8 — Media Release Qualification Validation Contract

One qualification plan is authored (08-01: release-gate audit + full-suite
parity + verdict bookkeeping). This phase introduces NO new behavior and
authors NO new tests — its contract surface is entirely pre-existing:
the permanent Phase-6/7 suites plus PR #28's `test_og_images.py` are the
MEDIA-17/MEDIA-19 evidence, regression-run whole. Per the Nyquist rule
applied to audit phases, the required assertions already exist and are
named per-criterion below; "RED" is not manufactured — a missing/renamed
covering test or a non-ancestor merge commit IS the failing condition
the audit would report. Any genuine gap found during execution is a stop
condition (report to the orchestrator), never silent scope expansion.

| Requirement | Required negative-path regression / gate | Test surface | Status |
|---|---|---|---|
| MEDIA-17 | Share-card GET follows ≤3 redirects, each hop egress-revalidated, HTTPS only, unsafe target rejected; upload PUT rejects 3xx after exactly one request — bytes + BUD-11 auth never forwarded; merge commit 99df6e8 ancestor of HEAD | `tests/runtime/test_og_images.py` (3 tests), `tests/runtime/test_blossom_upload.py::test_redirect_rejected_single_request`, `git merge-base` | Pending audit |
| MEDIA-19 | Matrix green: local storage store+serve, Blossom success, kind-24242 wire format (`Event.verify`, `t=upload`, matching `x`/`X-SHA-256`, `server` tag, ~300s exp, base64url no-pad), descriptor poison/201/body-bound cases, first-configured-server-only dispatch, typed `media-remote` failure with zero local bytes (explicit local retry path), size/type/quota rejection, absolute+owned-relative URL round-trips, share-card redirects — all against loopback `_FakeBlossom`, zero public-network writes | `tests/runtime/test_media_upload.py` (17), `tests/runtime/test_blossom_upload.py` (15), `tests/runtime/test_og_images.py` (3), `tests/runtime/test_admin_ui.py -k media` (retry affordance) | Pending audit |
| CI parity | `make verify` (`GAMMA_QUAL_EVIDENCE=1 uv run pytest -q` over the ENTIRE tree incl. host-boot runtime files) exits 0; `uv run ruff check .` clean | whole tree | Pending audit |
| Bookkeeping | MEDIA-17/19 ticked + traceability Complete; ROADMAP Phase 8 checked with plan list + progress row (Phase 7 stale row repaired); STATE at phase 8; 08-VERIFICATION.md authored | `.planning/REQUIREMENTS.md`, `.planning/ROADMAP.md`, `.planning/STATE.md`, `08-VERIFICATION.md` | Pending audit |

Runtime filenames above are under `tests/runtime/`. Route-level tests use
the `runtime_env` host-boot fixture; service-level Blossom tests use
`keystore_env` with the real `MerchantKeyStore.sign_event` custody path.
The fake Blossom is `http.server.ThreadingHTTPServer` bound to
("127.0.0.1", 0) with `resolve_and_check_egress` and `_open_connection`
monkeypatched to loopback — no test writes to public Blossom servers.
`og_images.py` GET redirects are capped (`_MAX_IMAGE_REDIRECTS = 3`) and
revalidated per hop; the upload PUT path has no redirect-following loop.

## Exact per-task validation mapping

Run commands from repo root; `uv run` resolves the pinned host via
`tools/checkout_host.py` (`make host` is the idempotent fallback). No
dependency installation. `make verify` is the full-tree CI-parity run
with durable evidence emission — it is required, not `verify-fast`.

| Task ID | Wave | Req | Permanent target / intended assertion direction | Automated command | Status |
|---|---:|---|---|---|---|
| 08-01-01 | 1 | MEDIA-17/19 | Merge ancestry + v1.1.0 tag/release confirmed; media-matrix files green (expected ~35 + admin_ui media subset); loopback/no-public-write seams cited by line | `git merge-base --is-ancestor 99df6e8 HEAD && test -n "$(git tag -l v1.1.0)" && uv run pytest tests/runtime/test_og_images.py tests/runtime/test_blossom_upload.py tests/runtime/test_media_upload.py -q && uv run pytest tests/runtime/test_admin_ui.py -q -k "media"` | Pending audit |
| 08-01-02 | 1 | CI parity | Entire suite exits 0 with evidence bundle emitted; lint clean; flake-vs-regression disambiguation recorded if needed | `make verify && uv run ruff check .` | Pending audit |
| 08-01-03 | 1 | Bookkeeping | 08-VERIFICATION.md names both criteria verified with test-name evidence + owner-UAT record; REQUIREMENTS ticks + traceability; ROADMAP/STATE current | `test -f` + `grep -q` gates per 08-01 Task 3 verify block | Pending audit |

An audit run is honest only if a red suite stays red in the record:
requirements are ticked ONLY in the commit carrying the green-run
outputs. A missing covering test, a non-ancestor 99df6e8, or any suite
failure is a reported gap — not something to patch over.

## Execution checks

- Task 1 records actual test counts and cites the loopback/monkeypatch
  line numbers; owner-UAT evidence is transcribed, not re-run.
- Task 2 must be `make verify` (full tree, ~6+ min host-boot included) —
  `verify-fast` alone does not satisfy CI parity. A killed/timed-out
  pytest process is not success.
- Task 3's report follows the 06/07 VERIFICATION.md shape; the owner UAT
  (live share-card render + Phase-7 "everything checks out" exercise of
  the five 07 human_needed items) is recorded as already-executed human
  evidence.
- ROADMAP bookkeeping repairs the stale Phase 7 progress row in the same
  pass — Phase 7's plans are all executed and owner-accepted.
- No code changes, no new tests, no dependency changes are authorized by
  this phase; discovering a real evidence gap halts execution for
  orchestrator review.

## Sign-off

- [ ] PR #28 merge ancestry + published v1.1.0 release confirmed on main.
- [ ] Media-matrix files green with recorded counts; seam line numbers cited.
- [ ] `make verify` full-tree green with evidence bundle; `ruff check` clean.
- [ ] 08-VERIFICATION.md authored; MEDIA-17/19 ticked Complete; ROADMAP/STATE updated.
- [ ] `nyquist_compliant` and `status` updated only after evidence exists.
