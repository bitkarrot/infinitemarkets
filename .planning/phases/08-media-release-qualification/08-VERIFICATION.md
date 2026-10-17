---
phase: 08-media-release-qualification
verified: "2026-10-17T05:24:33Z"
status: passed
score: 2/2 must-haves verified
covered_files:
  - .planning/REQUIREMENTS.md
  - .planning/ROADMAP.md
  - .planning/phases/08-media-release-qualification/08-01-PLAN.md
  - .planning/phases/08-media-release-qualification/08-VALIDATION.md
  - .planning/phases/07-shared-image-editors/07-VERIFICATION.md
  - infinitemarkets/services/og_images.py
  - infinitemarkets/services/blossom.py
  - tests/runtime/test_og_images.py
  - tests/runtime/test_blossom_upload.py
  - tests/runtime/test_media_upload.py
  - tests/runtime/test_admin_ui.py
  - evidence/REPORT.md
  - evidence/manifest.json
  - manifest.json
behavior_unverified: 0
overrides_applied: 0
human_verification: []
---

# Phase 8: Media Release Qualification Verification Report

**Phase Goal:** Merchants can rely on image uploads and generated share cards behaving safely across the supported local and Blossom paths before release.
**Verified:** 2026-10-17T05:24:33Z
**Status:** passed
**Re-verification:** No — initial verification (qualification audit over already-shipped code; v1.1.0 tagged and published)

This is a release-qualification audit, not a feature phase: every behavior
below was already implemented and regression-tested by Phases 6-7 and
PR #28. This report re-proves the two roadmap success criteria end-to-end
against `main` and records the verdict. No code changed in this phase.

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | SC1 — A Blossom-hosted image that redirects over HTTPS is rendered in generated share cards after PR #28 is merged and verified using bounded, revalidated GET redirects; an upload PUT to a redirecting server fails without forwarding upload bytes or authorization | ✓ VERIFIED | Merge ancestry: `git merge-base --is-ancestor 99df6e8 HEAD` → exit 0 on main (`99df6e8 fix: follow safe redirects for Open Graph product images (#28)`; release commit `48b6aa0 chore: release v1.1.0` is in the ancestry line). Bound read of `infinitemarkets/services/og_images.py`: `_MAX_IMAGE_REDIRECTS = 3` (line 24), redirect loop at lines 100-150 re-runs `resolve_and_check_egress` per hop (114-117), rejects non-https/userinfo/fragment/non-443 targets before dialing (102-110), caps chain + 2048-char Location (137-144); `_MAX_SOURCE_BYTES = 3 MB` (22), `_MAX_SOURCE_PIXELS = 16M` (23), pinned-IP TLS via `_PinnedHTTPSConnection` (34-48). Tests: `test_remote_image_follows_checked_https_redirect`, `test_remote_image_rejects_unsafe_redirect` (parametrized unsafe targets), `test_remote_image_caps_redirect_chain` — all green. Upload side: `infinitemarkets/services/blossom.py` `_put` raises on any 3xx after exactly one request (206-212); `test_redirect_rejected_single_request` proves the redirecting server records one PUT — bytes + BUD-11 auth never forwarded. |
| 2 | SC2 — Automated tests against local storage and a fake Blossom server demonstrate successful uploads, BUD authorization/hash/descriptor validation, primary-server-only targeting, explicit local retry after remote failure, file size/type rejection, URL round-trips, and share-card redirect handling without writing to public Blossom servers | ✓ VERIFIED | Full matrix green — 51 passed (`test_og_images.py` 3 + `test_blossom_upload.py` 15 + `test_media_upload.py` 17 tests, parametrization expands to 51 cases) + `test_admin_ui.py -k media` 4 passed. Mapping: local storage → `test_media_upload_stores_verified_image`, `test_uploaded_path_is_served_over_http`; Blossom success → `test_upload_put_wire_format_and_bud11_auth_event`, `test_descriptor_201_accepted`; BUD-11 auth/hash/descriptor → wire-format test (kind-24242 `Event.verify`, `t=upload`, matching `x`/`X-SHA-256`, `server` tag, ~300s exp, base64url no-pad) + `test_descriptor_poison_rejected`, `test_descriptor_body_bound_rejected`, `test_upload_signs_fresh_event_per_call`; first-configured-server-only → `test_route_upload_blossom_targets_first_configured_server`; failure → explicit local retry → `test_route_upload_blossom_failure_is_explicit` (typed `media-remote`, zero local bytes) + `test_media_upload_backend_dispatch` + `test_admin_media_single_image_ux` (`"Save to LNbits instead"` affordance, test_admin_ui.py:130); size/type/quota → `test_media_upload_rejects_svg_gif_empty_and_nonimage`, `test_media_upload_size_and_file_count_bounds`, `test_media_upload_merchant_quota`; URL round-trips → `test_uploaded_absolute_url_round_trips_through_catalog`, `test_catalog_accepts_owned_relative_image_prefixes`; share-card redirects → `test_og_images.py`. No public writes: `_FakeBlossom` binds `ThreadingHTTPServer(("127.0.0.1", 0), …)` (test_blossom_upload.py:66-67); `_wire_egress` (131-145) monkeypatches `resolve_and_check_egress` → `[127.0.0.1]` (136-140) and `_open_connection` → plain `http.client.HTTPConnection` to the loopback port (141-145). `test_og_images.py` monkeypatches `resolve_and_check_egress` (42/83/102) and stubs `_fetch_image` (43/84/103) — no socket leaves the process. |

**Score:** 2/2 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `infinitemarkets/services/og_images.py` | Bounded revalidated GET redirects only | ✓ VERIFIED | `_MAX_IMAGE_REDIRECTS=3`; per-hop egress re-check; byte/pixel caps; unsafe-URL rejection pre-dial |
| `infinitemarkets/services/blossom.py` | Single-attempt PUT; 3xx rejected without forwarding | ✓ VERIFIED | `_put` lines 192-224; no redirect-following loop anywhere in the upload path |
| `tests/runtime/test_og_images.py` | Checked-redirect follow / unsafe reject / chain cap | ✓ VERIFIED | 3 tests, all green in the focused run and the full suite |
| `tests/runtime/test_blossom_upload.py` | Loopback fake, wire-format/descriptor/dispatch/redirect matrix | ✓ VERIFIED | 15 tests green; loopback + monkeypatched seams at cited lines |
| `tests/runtime/test_media_upload.py` | Local-storage + dispatch + bounds + round-trip matrix | ✓ VERIFIED | 17 tests green |
| `tests/runtime/test_admin_ui.py` | Retry affordance + picker markup (`-k media`) | ✓ VERIFIED | 4 passed, 29 deselected: `test_admin_media_picker`, `test_admin_media_single_image_ux`, `test_admin_media_settings_sites`, `test_admin_media_card` |
| `manifest.json` + tag `v1.1.0` + published release | Release evidence for the shipped line being audited | ✓ VERIFIED | `git tag -l v1.1.0` non-empty; `gh release view v1.1.0` → `{"isDraft":false,"tagName":"v1.1.0"}`; `manifest.json` version `1.1.0`; release commit `48b6aa0` |
| `evidence/REPORT.md` + `evidence/manifest.json` | Durable qualification evidence from `make verify` | ✓ VERIFIED | Regenerated by this audit run — REPORT.md header `Generated (UTC): 2026-10-17T05:23:12Z`, command `make verify`, sqlite/arm64 profile |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| og_images.py redirect loop | bounded, revalidated GETs | `_MAX_IMAGE_REDIRECTS=3` + per-hop `resolve_and_check_egress` | PROVEN | merge commit 99df6e8 is ancestor of HEAD; the three redirect tests green — had the merge been absent or the cap regressed, SC1 fails |
| blossom.py upload PUT | 3xx → single-request refusal | `_put` raises on `300 <= status < 400` (206-212) | PROVEN | `test_redirect_rejected_single_request` — a redirect never triggers a second request, so bytes + Authorization can never leak to a redirect target |
| _FakeBlossom loopback | zero public Blossom writes | `ThreadingHTTPServer("127.0.0.1", 0)` + monkeypatched egress/connection seams | PROVEN | test_blossom_upload.py:66-67, 131-145 — the no-public-writes guarantee rests on these seams and they are exercised by every fake test |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| PR #28 merge ancestry | `git merge-base --is-ancestor 99df6e8 HEAD` | exit 0 (ancestor); `git log --oneline -3 99df6e8` → `99df6e8 fix: follow safe redirects for Open Graph product images (#28)`, `20fe475 chore: release v1.0.14`, `15a35df fix: admin catalog polish` | ✓ PASS |
| Release tag + published release | `git tag -l v1.1.0`; `gh release view v1.1.0 --json tagName,isDraft` | `v1.1.0`; `{"isDraft":false,"tagName":"v1.1.0"}` (published, non-draft); `manifest.json` version 1.1.0 at `48b6aa0` | ✓ PASS |
| MEDIA-19 matrix (og_images + blossom_upload + media_upload) | `uv run pytest tests/runtime/test_og_images.py tests/runtime/test_blossom_upload.py tests/runtime/test_media_upload.py -q` | **51 passed in 19.90s** | ✓ PASS |
| Admin media subset (retry affordance + picker markup) | `uv run pytest tests/runtime/test_admin_ui.py -q -k "media"` | **4 passed, 29 deselected in 2.37s** | ✓ PASS |
| Full-tree CI parity | `make verify` (= `GAMMA_QUAL_EVIDENCE=1 uv run pytest -q`) | **1100 passed, 8 skipped in 362.06s (0:06:02)**; evidence bundle regenerated at `evidence/REPORT.md` + `evidence/manifest.json` (2026-10-17T05:23:12Z). Skips: 1 advisory relay smoke (env-gated), 6 PostgreSQL-only concurrency drills on the sqlite profile, 1 unconfigured private Shopify sample | ✓ PASS |
| Lint | `uv run ruff check .` | `All checks passed!` | ✓ PASS |

No rerun disambiguation was needed — every gate passed on first
execution with natural process exits.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| MEDIA-17 | 08-01 | Blossom share-card GETs follow only bounded, revalidated HTTPS redirects; upload PUTs do not inherit GET redirect behavior; PR #28 merged and verified before release | ✓ SATISFIED | Merge ancestry proven; og_images.py bound confirmed (`_MAX_IMAGE_REDIRECTS=3`, per-hop egress re-check); `test_og_images.py` 3 green; `test_redirect_rejected_single_request` proves PUT single-request refusal; v1.1.0 tag + published release |
| MEDIA-19 | 08-01 | Automated tests exercise local storage, Blossom success, BUD auth/hash/descriptor, first-configured-server rule, failure with explicit local retry, size/type rejection, URL round-trips, share-card redirects — without writing to public Blossom servers | ✓ SATISFIED | 51+4 focused tests green; per-criterion test-name mapping in Truth 2; loopback fixture + monkeypatched seams cited by line |

No orphaned requirements — MEDIA-17 and MEDIA-19 are the only IDs mapped
to Phase 8, and both are claimed by 08-01's `requirements:` field.

### Deferred-Scope Exclusion Check

| Deferred item | Evidence it stayed out |
|---------------|------------------------|
| New feature work | Zero code changes this phase — audit + bookkeeping only (diff confined to `.planning/`) |
| New tests | None authored; the pre-existing permanent suites are the evidence, per the Nyquist rule for audit phases |
| Public Blossom writes | Loopback-only discipline re-attested at test_blossom_upload.py:66-67, 131-145 |
| MEDIA-20…23 (mirroring, kind-10063, remote delete, transforms) | No related code added |

### Human Verification

**Status:** passed — no outstanding items; owner UAT already executed and recorded.

| Item | Owner evidence |
|------|----------------|
| Share-card render outcome (MEDIA-17 behavioral outcome) | Owner confirmed on a live instance that generated share cards render correctly with LNbits-local uploaded images in both the search preview and the share preview |
| Phase 7 `human_needed` residue (07-VERIFICATION.md items 1-5: hero upload render, gallery interactions incl. ordering, Blossom failure→retry UX, cancel-disclosure toast, Media card interactions) | Owner exercised the Phase-7 human-check items locally — "everything checks out"; recorded here as owner-accepted, discharging the five outstanding human items on the Phase-7 record |

### Gaps Summary

No gaps. Both roadmap success criteria are verified end-to-end against
`main`: PR #28's bounded redirect work is in the release line and green;
the MEDIA-19 matrix is green against the loopback fake with zero public
writes; the full tree (`make verify`, 1100 passed) and lint are clean —
matching CI parity per AGENTS.md. MEDIA-17 and MEDIA-19 are marked
complete in REQUIREMENTS.md in the same commit that carries this record.

---

_Verified: 2026-10-17T05:24:33Z_
_Verifier: Claude (gsd-executor, qualification audit per 08-01-PLAN.md)_
