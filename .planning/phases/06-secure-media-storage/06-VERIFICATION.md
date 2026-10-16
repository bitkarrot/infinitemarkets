---
phase: 06-secure-media-storage
verified: "2026-10-16T07:43:51Z"
status: gaps_found
score: 2/4 must-haves verified
covered_files:
  - .planning/REQUIREMENTS.md
  - .planning/ROADMAP.md
  - .planning/phases/06-secure-media-storage/06-01-PLAN.md
  - .planning/phases/06-secure-media-storage/06-01-SUMMARY.md
  - .planning/phases/06-secure-media-storage/06-02-PLAN.md
  - .planning/phases/06-secure-media-storage/06-02-SUMMARY.md
  - .planning/phases/06-secure-media-storage/06-03-PLAN.md
  - .planning/phases/06-secure-media-storage/06-03-SUMMARY.md
  - .planning/phases/06-secure-media-storage/06-CONTEXT.md
  - .planning/phases/06-secure-media-storage/06-VALIDATION.md
  - docs/technical-specification.md
  - harness/registry.py
  - infinitemarkets/security.py
  - infinitemarkets/services/blossom.py
  - infinitemarkets/services/events.py
  - infinitemarkets/services/media.py
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
covered_digest: "v1:sha256:a73bc26c8b07f55ecff3fa9b210758d75039a07fa970f92b1e2d3d066dc42a4f"
behavior_unverified: 0
overrides_applied: 0
gaps:
  - truth: "Locally stored images are served through the host image mount at the emitted /images/infinitemarkets/<ns>/<name> path (SC1) and profile-bound uploads emit a publicly reachable absolute HTTPS URL (SC3/MEDIA-07)"
    status: failed
    reason: >
      The emitted URL path prefix `/images/` does not match any route on the
      qualified host. Pinned LNbits e336fe1 mounts `{lnbits_data_folder}/images`
      at `/library` (`.cache/lnbits/lnbits/app.py:189-193`); no `/images` mount
      or route exists anywhere in the host or the extension (extension routes
      live under `/infinitemarkets`). Empirically proven against a real host
      boot: a file written to `{data}/images/infinitemarkets/probe/probe.png`
      returns HTTP 200 at `/library/infinitemarkets/probe/probe.png` and HTTP
      404 at `/images/infinitemarkets/probe/probe.png`. Every URL the phase
      emits — `results[].path`, `results[].url`, catalog `product_images.url`
      values, and kind-0 picture/banner absolutization — therefore 404s on the
      qualified host. The defect is inherited verbatim from v1.0's
      `migration_media._local_url` (unchanged this phase), but Phase 6 adopted
      the broken path into its new public API surface and success criteria.
    artifacts:
      - path: infinitemarkets/services/media.py
        issue: "local_path()/absolute_url() (lines 40-50) emit `/images/infinitemarkets/...` — the qualified host serves the data-folder images dir at `/library`, not `/images`"
      - path: infinitemarkets/services/migration_media.py
        issue: "_local_url() (line 211-212) emits the same dead `/images/` prefix; docstring line 8 claims a host `/images` mount that does not exist on the pinned host"
      - path: docs/technical-specification.md
        issue: "§5.6 line 817 and §13 line 1805 describe 'the host's `/images` mount' — factually wrong against pinned host e336fe1 (mount is `/library`)"
    missing:
      - "Owner decision + fix: either emit `/library/infinitemarkets/...` (the real mount path — requires a migration/compatibility story for v1.0-stored `/images/...` product_images.url rows and `_referenced_names` matching already handles both via the `infinitemarkets/<ns>/<name>` substring), or add an extension-served route such as `/infinitemarkets/images/...` backed by the data folder, or document a required operator reverse-proxy mapping `/images` -> `/library`"
      - "Correct spec §5.6/§13 and migration_media docstring to name the real mount"
      - "Add one host-boot test that GETs the emitted `path`/`url` and asserts 200 — no existing test ever fetches a stored file over HTTP"
---

# Phase 6: Secure Media Storage Verification Report

**Phase Goal:** Merchants can upload bounded, verified images to durable LNbits-local storage or securely use Blossom through the server-side upload boundary.
**Verified:** 2026-10-16T07:43:51Z
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #   | Truth | Status | Evidence |
| --- | ----- | ------ | -------- |
| 1 | Local upload works with no Blossom configured; files SHA-256-hashed into a merchant-scoped namespace outside the package, **served through the host image mount**; bounded multipart (≤16 files, ≤25 MB/file, 400 MB quota); signature-verified PNG/JPEG/WebP only, SVG/GIF/oversize rejected | ✗ FAILED | Upload/store/hash/bounds all verified by `tests/runtime/test_media_upload.py` (14 tests, host-boot, passing) and `media.py`/`migration_media.py`. **But "served through the host image mount" fails at the emitted-URL level**: pinned host mounts `{data}/images` at `/library`, never `/images`. Empirical: on-disk file → `/library/...` 200, `/images/...` 404. See gap. |
| 2 | Blossom image exposed only after server-side BUD-02 `PUT /upload` authorized by BUD-11 kind-24242 (300s exp, `t=upload`, matching `x`/`X-SHA-256`, target-scoped `server` tag, base64url no-pad); descriptor validated; no key material to browser | ✓ VERIFIED | `services/blossom.py` full implementation; `test_upload_put_wire_format_and_bud11_auth_event` decodes the real wire token and `Event.verify()`s it through the real `MerchantKeyStore.sign_event` custody path; `test_result_dict_carries_no_key_or_token` + route-level no-signing-material test pass. |
| 3 | Locally stored image in kind-0 picture/banner resolves to a **publicly reachable** absolute HTTPS URL; Appearance may use same-origin paths | ✗ FAILED | Emission mechanism verified (`events.py:270-299`, `outbox.py:573-575` wired with `_public_base_url()`; `test_merchant_profile_absolutizes_local_image_paths` passes). But the emitted `https://<host>/images/...` URL is **not reachable** on the qualified host — same `/images`-vs-`/library` root cause as truth 1. |
| 4 | Uploads via authenticated route registered in spec §5 AND `harness/registry.py::HTTP_ROUTES`; Blossom requests use HTTPS, request-time public egress, pinned-IP TLS, strict time/size bounds, never follow redirects | ✓ VERIFIED | `registry.py:272-275` + spec §5.6 fenced block; `test_routes_match_spec_bidirectional` passes. `blossom.py`: https scheme gate, `resolve_and_check_egress` per call (spy test proves per-request consultation), `_PinnedHTTPSConnection` (connect to checked IP, SNI=host), 10s connect / 20s deadline / 16KB descriptor bound, all 3xx rejected with exactly one recorded request. |

**Score:** 2/4 truths verified (0 present, behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `infinitemarkets/services/media.py` | Local storage adapter + dispatch | ✓ VERIFIED | `store_local`/`store_upload`/`_store_blossom`/`list_unused`/`delete_unused` — substantive, wired, all behavior-tested. Caveat: `local_path` emits dead `/images` prefix (gap). |
| `infinitemarkets/services/blossom.py` | BUD-02 PUT + BUD-11 signing + egress/pinned-IP/no-redirect + D-13 cap | ✓ VERIFIED | 296 lines, all seams real; 25-test fake-Blossom suite green. |
| `infinitemarkets/views_api.py` media routes | POST /media/upload, GET /media/unused, DELETE /media/unused/{name} | ✓ VERIFIED | Lines 902-994; `check_user_exists` + `problem_boundary` (Origin+CSRF enforced); bounded stream + `MultiPartParser` caps + per-file `read(MAX+1)`. |
| `infinitemarkets/services/relay.py` ordering | `set_blossom_servers` order-preserving dedup | ✓ VERIFIED | Line 217 `dict.fromkeys`, no `sorted()`; round-trip test proves unsorted order survives. |
| `infinitemarkets/services/events.py` + `outbox.py` | kind-0 absolutization | ✓ VERIFIED | Prefix-conditional absolutization; production call site passes `public_base_url`. |
| `docs/technical-specification.md` §5.6 + `harness/registry.py` | Route parity | ✓ VERIFIED | Parity test green; media problem codes correctly stay out of `ERROR_CODES` per documented precedent. |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | -- | --- | ------ | ------- |
| `POST /media/upload` | `media.store_upload` | route → dispatch | WIRED | `views_api.py:965` |
| `store_upload` → `_store_blossom` | `blossom.upload_blob` targeting `get_blossom_servers()[0]` | first-server-only, iterate files never servers | WIRED | `media.py:232-241`; route test asserts servers[1] untouched |
| `upload_blob` | `keystore.sign_event` | real custody path, one event per upload | WIRED | spy test counts 2 sign calls / 2 uploads |
| `upload_blob` | `resolve_and_check_egress` + `_PinnedHTTPSConnection` | request-time egress → pinned-IP TLS | WIRED | resolver spy + pre-dial rejection test |
| `outbox` kind-0 build | `events.merchant_profile_event` | `public_base_url=_public_base_url()` | WIRED | `outbox.py:573-575` |
| Stored file ↔ emitted URL ↔ host serving | `/images/...` → host `/library` mount | **NOT_WIRED** | emitted path 404s on qualified host — the single blocker gap |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| -------- | ------------- | ------ | ------------------ | ------ |
| `store_local` results | `path`/`url`/`sha256`/`namespace` | real sha256 of stored bytes + `_namespace()` HMAC + `ext_settings().public_base_url` | ✓ | FLOWING — but `url` points at an unserved route (gap) |
| `upload_blob` result | `url`/`sha256`/`size`/`type`/`server` | validated remote descriptor | ✓ | FLOWING |
| `list_unused` | `files` | disk scan minus sidecar minus `_referenced_names` DB scan (product_images.url, profile_json, theme) | ✓ | FLOWING |
| `merchant_profile_event` | `picture`/`banner` | `profile_json` + `public_base_url` | ✓ | FLOWING — emitted absolute URL unreachable (gap) |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| Fast gate green incl. contract tests | `make verify-fast` | 318 passed, 2 skipped, 42.5s | ✓ PASS |
| Lint | `uv run ruff check .` | All checks passed | ✓ PASS |
| Targeted runtime suite | `uv run pytest tests/runtime/test_media_upload.py test_blossom_upload.py test_catalog_events.py test_relay_config_api.py test_migration_export_media.py -q` | 72 passed | ✓ PASS |
| Route↔spec parity | `pytest tests/qualification/test_p0_14_contract_closure.py::test_routes_match_spec_bidirectional` | 1 passed | ✓ PASS |
| Emitted `/images` URL actually served? | scratch host-boot probe: write `{data}/images/infinitemarkets/probe/probe.png`, GET both paths | `/images/...` → **404**; `/library/...` → **200** | ✗ FAIL → gap |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ---------- | ----------- | ------ | -------- |
| MEDIA-01 | 06-01, 06-03 | Local default when no Blossom configured | ✓ SATISFIED | `store_upload` default local; `test_media_upload_backend_dispatch` |
| MEDIA-04 | 06-02, 06-03 | Server-side signing; no key/token to browser | ✓ SATISFIED | `keystore.sign_event` custody; no-signing-material tests at service + route level |
| MEDIA-05 | 06-01, 06-02 | Bounded multipart 16/25MB/400MB; png/jpg/webp only; sha256; descriptor validated | ✓ SATISFIED | `test_media_upload_*` bounds/quota/type tests; `test_descriptor_poison_rejected` (8 cases) |
| MEDIA-06 | 06-01 | Merchant-scoped opaque namespace outside package, served via host image mount | ✗ BLOCKED | Files land under `{data}/images/infinitemarkets/<ns24>/` — inside the mounted tree — but the emitted `/images/...` URL is not the mount (`/library` is); emitted URL 404s on qualified host |
| MEDIA-07 | 06-01, 06-03 | Profile picture/banner emitted as publicly reachable absolute https URL | ✗ BLOCKED | Emission verified, reachability fails — `https://<host>/images/...` 404s (same root cause) |
| MEDIA-15 | 06-02 | BUD-02 PUT /upload + BUD-11 kind-24242, 300s, t=upload, x==X-SHA-256, server tag, base64url no-pad | ✓ SATISFIED | `test_upload_put_wire_format_and_bud11_auth_event` verifies every field on the wire |
| MEDIA-16 | 06-02 | HTTPS + request-time egress + pinned-IP TLS + strict bounds + redirect rejection | ✓ SATISFIED | `test_egress_*`, `test_redirect_rejected_single_request`, `test_in_flight_put_cap_per_merchant` |
| MEDIA-18 | 06-01, 06-03 | Routes in spec §5 + HTTP_ROUTES; parity + fake-Blossom tests pass | ✓ SATISFIED | `test_routes_match_spec_bidirectional` green; 25-test fake-Blossom suite green |

No orphaned requirements: REQUIREMENTS.md maps exactly these 8 IDs to Phase 6.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| — | — | none | — | No TBD/FIXME/XXX/TODO/HACK/placeholder markers in any phase-touched file; no stub implementations detected. |

### Deferred-scope check

Confirmed absent: BUD-04 mirroring, kind-10063 publication, remote/BUD DELETE (`delete_unused` is local-filesystem only, explicitly documented), GIF acceptance in uploads, server-side transforms. `og_images.py` `Accept: image/gif` (line 60) is the pre-existing share-card GET fetch path, not upload scope.

**No public-network writes in tests:** all Blossom traffic targets a loopback `ThreadingHTTPServer` fake; `resolve_and_check_egress` and `_open_connection` seams are monkeypatched to `127.0.0.1`; the route-level resolver even asserts the host is in the expected fake map, so `media.example.com`/`second.example.com` can never be dialed.

### Gaps Summary

**One blocker, one root cause, inherited from v1.0.**

Everything the phase built — bounded upload, dispatch, Blossom client, ordering fix, kind-0 absolutization, parity registration — is real, wired, and behaviorally tested (72 targeted runtime tests + 318 fast-gate tests green). The single failure is a host-integration contract error that predates the phase: the extension emits `/images/infinitemarkets/<ns>/<name>` paths, but the pinned LNbits host (e336fe1, verified by `git log` and by a live host-boot probe) mounts the data-folder `images` directory at **`/library`**. The newer research checkout (74cccac) mounts `/library` too — no known host serves `/images`.

Concretely: an uploaded file exists on disk at `{data}/images/infinitemarkets/<ns>/<sha>.png` and is served at `/library/infinitemarkets/<ns>/<sha>.png`, while every URL the system emits (`results[].path`, `results[].url`, catalog `product_images.url`, kind-0 picture/banner) uses `/images/...` and 404s. SC1's "served through the host image mount" and MEDIA-07's "publicly reachable" therefore fail on the qualified host. This also means v1.0 migration-relinked `product_images.url` rows carry the same dead prefix — a pre-existing defect worth surfacing to the owner regardless of phase scoping.

**Owner decision needed** (cannot be resolved by verifier):
1. Emit `/library/infinitemarkets/...` (the real mount) — needs a compatibility story for v1.0-stored `/images/...` URLs; `_referenced_names` matching is already prefix-agnostic.
2. Or add an extension-served route (e.g. `/infinitemarkets/images/...`) backed by the data folder and emit that path.
3. Or document a required operator reverse-proxy mapping `/images` → `/library` — if the production deployment already does this, treat as an override + spec-text correction only.

**This may look intentional.** To accept the deviation, add to this file's frontmatter:

```yaml
overrides:
  - must_have: "Locally stored images are served through the host image mount at the emitted /images/... path"
    reason: "Production deployment fronts LNbits with a reverse proxy mapping /images -> /library (or equivalent); qualified-host 404 is not representative"
    accepted_by: "<owner>"
    accepted_at: "<ISO timestamp>"
```

Minor informational notes (non-blocking):
- `blossom._put_once` PUTs to literal `/upload` while `validate_blossom_url` permits a configured server URL with a path component — per BUD-02 the upload endpoint is origin-rooted, so this is correct for well-formed servers but a path-carrying config would silently lose its path on the wire.
- `_SEMAPHORES` dict is process-local and grows with distinct merchant_ids — documented in-code; acceptable.

---
_Verified: 2026-10-16T07:43:51Z_
_Verifier: Claude (gsd-verifier)_
