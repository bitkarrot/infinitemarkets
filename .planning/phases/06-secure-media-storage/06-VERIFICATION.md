---
phase: 06-secure-media-storage
verified: "2026-10-16T19:05:00Z"
status: passed
score: 4/4 must-haves verified
covered_files:
  - .planning/REQUIREMENTS.md
  - .planning/ROADMAP.md
  - .planning/phases/06-secure-media-storage/06-01-PLAN.md
  - .planning/phases/06-secure-media-storage/06-01-SUMMARY.md
  - .planning/phases/06-secure-media-storage/06-02-PLAN.md
  - .planning/phases/06-secure-media-storage/06-02-SUMMARY.md
  - .planning/phases/06-secure-media-storage/06-03-PLAN.md
  - .planning/phases/06-secure-media-storage/06-03-SUMMARY.md
  - .planning/phases/06-secure-media-storage/06-04-PLAN.md
  - .planning/phases/06-secure-media-storage/06-04-SUMMARY.md
  - .planning/phases/06-secure-media-storage/06-CONTEXT.md
  - .planning/phases/06-secure-media-storage/06-VALIDATION.md
  - docs/technical-specification.md
  - harness/registry.py
  - infinitemarkets/migrations.py
  - infinitemarkets/security.py
  - infinitemarkets/services/blossom.py
  - infinitemarkets/services/catalog.py
  - infinitemarkets/services/events.py
  - infinitemarkets/services/media.py
  - infinitemarkets/services/migration_import.py
  - infinitemarkets/services/migration_media.py
  - infinitemarkets/services/outbox.py
  - infinitemarkets/services/relay.py
  - infinitemarkets/views_api.py
  - tests/qualification/test_p0_14_contract_closure.py
  - tests/runtime/test_blossom_upload.py
  - tests/runtime/test_catalog_events.py
  - tests/runtime/test_media_upload.py
  - tests/runtime/test_merchant_api.py
  - tests/runtime/test_migration_export_media.py
  - tests/runtime/test_relay_config_api.py
covered_digest: "v1:sha256:2e32ec8b17647527a67894b61c99b4b88de2dde5346ded259683e808ba535c36"
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 2/4
  gaps_closed:
    - "Emitted /images/infinitemarkets/... URLs 404 on the qualified host — the pinned host mounts {data}/images at /library, not /images"
  gaps_remaining: []
  regressions: []
---

# Phase 6: Secure Media Storage Verification Report

**Phase Goal:** Merchants can upload bounded, verified images to durable LNbits-local storage or securely use Blossom through the server-side upload boundary.
**Verified:** 2026-10-16T19:05:00Z
**Status:** passed
**Re-verification:** Yes — after gap closure (plan 06-04, commits `8260e7b`, `8f2bec5`, `b4ffd78`)

## Gap Closure Summary

The single prior blocker is **closed**. The prior verification proved the emitted `/images/infinitemarkets/<ns>/<name>` path 404'd on the pinned host (mount is `/library`, `lnbits/app.py:189-193`). The closure:

- **`MEDIA_URL_PREFIX = "/library/infinitemarkets/"`** + `LEGACY_MEDIA_URL_PREFIX = "/images/infinitemarkets/"` are canonical constants in `migration_media.py:43-44`; `_local_url` (line 222) and `media.local_path`/`absolute_url` (media.py:40-50) emit `/library/...` from the shared constant.
- **`test_uploaded_path_is_served_over_http`** (test_media_upload.py:124) does a real `client.get(result["path"])` through the booted host — 200 + byte-identical body. This is the genuine serveability proof the gap demanded; not a stub.
- **`m019_media_library_mount`** (migrations.py:1521-1552) rewrites legacy `/images/infinitemarkets/` refs in `product_images.url` (column-start), `merchants.profile_json`/`theme`, and `settings.value` (JSON-string-start needle `"/images/infinitemarkets/` — the leading quote prevents clobbering foreign-host absolute URLs sharing a row). `REPLACE`+`LIKE` only — dialect-portable across the repo's sqlite×postgres CI matrix; idempotent (second run is a no-op, test-asserted).
- **`catalog._valid_image_url`** (catalog.py:61-71) applied at all four image-URL sites (product images PATCH ~710, product-image attach ~1695, collection create ~1836, collection PATCH ~1964): accepts `https://` plus both owned relative prefixes; `/library/other`, `/images/other`, `http://`, and protocol-relative rejected (test-proven).
- **`merchant_profile_event`** (events.py:291-305) normalizes `/images/` → `/library/` then absolutizes via `public_base_url` — nothing dead reaches relays even if m019 is bypassed.
- **D-12 unreferenced detection** is prefix-agnostic by construction (`infinitemarkets/<ns>/<name>` substring needle, media.py:~294) — both prefixes mark a file referenced; `relink_media` skips both prefixes (migration_media.py:258-259).
- **Sweep for remaining `/images/` emission sites:** none. Remaining occurrences are the m019 migration needle, the paired relink exclusion, the LEGACY constant, and docstrings/comments. Two `admin.html` labels still say "(https or /images/…)" — cosmetic field-hint copy, explicitly deferred to Phase 7 editor scope; acceptable.
- **Spec corrected:** §5.6 and §13.2 now name the real `/library` mount; §15 documents the owned-relative-prefix exception.

## Goal Achievement

### Observable Truths

| #   | Truth | Status | Evidence |
| --- | ----- | ------ | -------- |
| 1 | Local upload works with no Blossom configured; files SHA-256-hashed into a merchant-scoped namespace outside the package, served through the host image mount; bounded multipart (≤16 files, ≤25 MB/file, 400 MB quota); signature-verified PNG/JPEG/WebP only, SVG/GIF/oversize rejected | ✓ VERIFIED | `test_media_upload_stores_verified_image` asserts `/library/` path + absolute url; `test_uploaded_path_is_served_over_http` GETs the emitted path → 200 byte-exact through the real mount; bounds/type/quota tests all pass. |
| 2 | Blossom image exposed only after server-side BUD-02 `PUT /upload` authorized by BUD-11 kind-24242 (300s exp, `t=upload`, matching `x`/`X-SHA-256`, target-scoped `server` tag, base64url no-pad); descriptor validated; no key material to browser | ✓ VERIFIED | `test_upload_put_wire_format_and_bud11_auth_event` decodes the real wire token and `Event.verify()`s it through `MerchantKeyStore.sign_event`; no-key/token tests at service + route level. (Regression-checked, unchanged by 06-04.) |
| 3 | Locally stored image in kind-0 picture/banner resolves to a publicly reachable absolute HTTPS URL; Appearance may use same-origin paths | ✓ VERIFIED | `merchant_profile_event` normalizes legacy `/images/` → `/library/` then absolutizes (events.py:295-305); `test_merchant_profile_absolutizes_local_image_paths` asserts `https://shop.example/library/...` emission for both stored prefixes; m019 rewrites stored profile_json/theme rows at boot. |
| 4 | Uploads via authenticated route registered in spec §5 AND `harness/registry.py::HTTP_ROUTES`; Blossom requests use HTTPS, request-time public egress, pinned-IP TLS, strict time/size bounds, never follow redirects | ✓ VERIFIED | `test_routes_match_spec_bidirectional` green; egress spy, pre-dial rejection, single-request redirect rejection, D-13 semaphore cap all exercised by the fake-Blossom suite. (Regression-checked, unchanged.) |

**Score:** 4/4 truths verified (0 present, behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `infinitemarkets/services/media.py` | Local storage adapter + dispatch | ✓ VERIFIED | `local_path` now delegates to `MEDIA_URL_PREFIX`; all prior behaviors intact |
| `infinitemarkets/services/blossom.py` | BUD-02 PUT + BUD-11 + egress/pinned-IP/no-redirect + D-13 | ✓ VERIFIED | Unchanged; suite green |
| `infinitemarkets/services/migration_media.py` | Canonical prefix constants; `_local_url` emits `/library/`; relink skips both prefixes | ✓ VERIFIED | Lines 37-44, 222-223, 258-259 |
| `infinitemarkets/migrations.py` | m019 idempotent dialect-portable rewrite with foreign-URL guard | ✓ VERIFIED | REPLACE+LIKE only; quote-needle on JSON columns; test proves foreign URL survives byte-identical + second-run no-op |
| `infinitemarkets/services/catalog.py` | `_valid_image_url` at all 4 image-URL validation sites | ✓ VERIFIED | Sites at ~710, ~1695, ~1836, ~1964; rejects non-owned relative/http |
| `infinitemarkets/services/migration_import.py` | `_native_image_url` dual-prefix: `/library/` verbatim, owned `/images/` normalized | ✓ VERIFIED | Lines 355-380; `..`/`//` guards retained |
| `infinitemarkets/services/events.py` + `outbox.py` | kind-0 normalize-then-absolutize | ✓ VERIFIED | Normalize always; absolutize when `public_base_url` set; empty base emits normalized relative form |
| `infinitemarkets/services/relay.py` | Order-preserving `set_blossom_servers` | ✓ VERIFIED | Unchanged; round-trip test green |
| `docs/technical-specification.md` + `harness/registry.py` | Spec/registry parity, `/library` mount named | ✓ VERIFIED | §5.6/§13.2/§15 corrected; parity test green |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| Fast gate | `make verify-fast` | 318 passed, 2 skipped, 46s | ✓ PASS |
| Lint | `uv run ruff check .` | All checks passed | ✓ PASS |
| Targeted runtime suite | `uv run pytest tests/runtime/test_media_upload.py test_blossom_upload.py test_catalog_events.py test_relay_config_api.py test_migration_export_media.py -q` | **77 passed** (+5 new: serveability, m019, dual-prefix, native round-trip, owned-prefix catalog) | ✓ PASS |
| Emitted path served (prior 404) | `test_uploaded_path_is_served_over_http` — real HTTP GET of `results[].path` via booted host | 200, byte-identical | ✓ PASS (gap closed) |
| Route↔spec parity | `test_routes_match_spec_bidirectional` | passed | ✓ PASS |

### Requirements Coverage

| Requirement | Status | Evidence delta |
| ----------- | ------ | -------------- |
| MEDIA-01 | ✓ SATISFIED | unchanged — local default dispatch |
| MEDIA-04 | ✓ SATISFIED | unchanged — server-side signing, no key material |
| MEDIA-05 | ✓ SATISFIED | unchanged — bounds, sniff, sha256, descriptor validation |
| MEDIA-06 | ✓ SATISFIED | **was BLOCKED → now satisfied**: `/library/` emission matches the real host mount; serveability proven by live GET; m019 repairs legacy rows |
| MEDIA-07 | ✓ SATISFIED | **was BLOCKED → now satisfied**: emitted absolute URLs resolve on the qualified host; kind-0 normalizes legacy prefix |
| MEDIA-15 | ✓ SATISFIED | unchanged — BUD-02/BUD-11 wire format verified |
| MEDIA-16 | ✓ SATISFIED | unchanged — egress/pinned-IP/bounds/redirect rejection |
| MEDIA-18 | ✓ SATISFIED | unchanged — spec §5.6 ↔ HTTP_ROUTES parity green |

### Anti-Patterns Found

None. Stub scan on all 06-04-modified source files: no TODO/FIXME/placeholder markers; no stub implementations.

### Deferred-scope check

Still clean: no BUD-04 mirroring, kind-10063, remote/BUD DELETE, GIF uploads, or transforms. No public-network writes in tests (loopback fake + monkeypatched egress/connection seams).

### Human Verification Required

None.

### Gaps Summary

None — the prior blocker is closed with behavior-level proof (live HTTP GET → 200 byte-exact through the real host mount). Phase goal achieved.

---
_Verified: 2026-10-16T19:05:00Z_
_Verifier: Claude (gsd-verifier)_
