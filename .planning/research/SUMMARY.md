# Project Research Summary

**Project:** infinitemarkets
**Domain:** Merchant commerce extension — product media upload and Blossom integration
**Milestone:** v1.1 Media uploads and Blossom support
**Researched:** 2026-10-16
**Confidence:** HIGH for local integration points and official Blossom request/auth contracts; MEDIUM for unresolved product/security policy

> **Prior research:** The v1.0 project research is preserved under `.planning/research/v1.0-core/`; these files now contain the v1.1 media findings.
>
> **Release boundary:** v1.0.14 (2026-10-16) remains immutable. This is a new v1.1 milestone. PR #28 (`fix/og-image-redirects`) is a fix-in-flight/prerequisite for reliable Blossom-backed share cards; integrate and verify it without treating GET redirects as upload behavior.

## Executive Summary

The v1.1 uploader should be shared across the product gallery, Merchant Nostr profile picture/banner, and Appearance brand logo, hero image, footer logo, and custom share image. Blossom endpoints are already stored in `settings.blossom_servers`. A separate local migration-media path demonstrates bounded multipart parsing, SHA-256 and magic-byte checks, merchant-scoped content-addressed storage under LNbits data, and relinking; it is not yet a general-purpose upload service.

Use local LNbits managed media by default. Let each upload explicitly choose LNbits or Blossom; for Blossom, target only the primary/first configured server. Do not dual-write; if a Blossom upload fails, offer an explicit retry to LNbits. Backend-proxied uploads use existing `nostr-sdk==0.44.8` and `MerchantKeyStore.sign_event`, keeping nsec out of the browser, plus stdlib HTTP and no new dependency by default. Implement BUD-02 raw `PUT /upload` and BUD-11 signed kind-24242 authorization with bounded bytes, hash verification, public-egress pinning, TLS SNI, and no automatic upload redirects. Reuse one uploader with single-image and ordered-gallery modes and preserve existing URL/local media. Remaining choices include limits, formats, orphan handling, remote deletion, image-count reconciliation, and public absolute URLs for local Nostr profile images.

The Open Graph failure is a separate GET-path issue. The shop.lightnin.games handoff reports that the first Blossom image URL redirects with `307` to `image.nostr.build`, leading to a generated 1200×630 placeholder; PR #28 adds bounded safe HTTPS redirect-following for image retrieval and was locally validated against the real image/card. Keep that fix as a prerequisite, but never reuse automatic redirect behavior for authenticated PUTs.

## Key Findings

### Recommended Stack

Use Python 3.12 and the existing LNbits/FastAPI extension boundary. Sign with already-pinned `nostr-sdk==0.44.8` via `MerchantKeyStore.sign_event`; use stdlib `http.client` with the existing pinned-IP/TLS-SNI pattern (off the async event loop) unless a demonstrated capability gap is approved. Browser native file APIs are sufficient for selection and UX; do not add a JavaScript Blossom SDK to the Python backend or add packages by default.

**Core technologies:**
- Python 3.12 / FastAPI: authenticated, CSRF-protected, bounded upload route — matches the locked extension/host architecture.
- `nostr-sdk==0.44.8`: kind-24242 authorization signing — existing version and merchant-key custody.
- stdlib `http.client` + `security.resolve_and_check_egress`: HTTPS PUT transport — no new dependency, but must pin checked public IP and reject redirects.

See [STACK.md](STACK.md) for the stack decision, alternatives, and protocol sources.

### Expected Features

**Must have (table stakes):**
- Reusable upload controls across product galleries, Merchant profile avatar/banner, and Appearance logo/hero/footer/custom share image.
- Multi-file selection, thumbnails, primary/ordered product images, per-image remove, and clear-all; single-image mode for settings fields.
- Backend-proxied, merchant-signed Blossom upload with a verified descriptor; no key is exposed in the browser.
- Progress, retry, per-file errors, browser-side count/size feedback, and safe server-side bounds.
- Local LNbits storage by default; optional per-upload Blossom selection of the first configured server, with explicit local retry on Blossom failure.
- Preserve pasted HTTPS URLs and existing imported/local `/images/...` URLs.
- Disclose the receiving media server and potential orphaned upload when product save is cancelled.
- Keep PR #28's safe GET redirect fix for share cards.

**Should have (competitive):**
- Optional later BUD-04 mirroring if merchants require multi-server resilience.

**Defer (v2+ or explicit follow-up):**
- Automatic remote deletion, anonymous uploads, kind-10063 publication, GIF support, and mirror-all by default.

See [FEATURES.md](FEATURES.md) for dependency graph and MVP boundaries.

### Architecture Approach

Add a shared media upload service with a local LNbits storage adapter and a Blossom adapter. The product gallery uses multi-image ordering; profile and Appearance fields use single-image binding. Local URLs consumed by Nostr profile metadata must be made absolute with the configured public origin. Keep image retrieval for OG cards in its existing GET-only service. A baseline synchronous upload requires no schema migration; only add durable upload state if operational evidence proves it necessary.

**Major components:**
1. Shared admin uploader — multi-image product gallery and single-image Merchant/Appearance fields.
2. Upload route/service — bounded multipart, content sniff/hash, local file storage or pinned HTTPS BUD-02 PUT with BUD-11 signing.
3. Existing URL consumers — persist product ordering and bind single-image values to profile/theme settings; render storefront, Nostr profile and OG cards.

See [ARCHITECTURE.md](ARCHITECTURE.md) for flows and module boundaries.

### Critical Pitfalls

1. **GET vs PUT redirects** — PR #28's safe image GET redirect behavior must not forward upload bytes or authorization to a redirect target; reject upload redirects.
2. **BUD-11 wire details** — current official spec requires URL-safe base64 JSON event without padding and hash-bound `x`/`X-SHA-256`; test exact wire values.
3. **SSRF/DNS rebinding** — current Blossom URL validation is not request-time egress security; resolve/check public IPs, pin connection with TLS SNI, restrict HTTPS/port, and no PUT redirects.
4. **Image editor data loss** — frontend omits `images` when empty, so clear-all does not work; local `/images/...` migration URLs conflict with HTTPS-only validation.
5. **URL-context and image-cap mismatch** — local media may be stored as `/images/...` while profile metadata requires an absolute HTTPS URL; code/UI cap is 20 but technical-spec §15 says 16.

See [PITFALLS.md](PITFALLS.md) for phase mapping and a pre-release checklist.

## Implications for Roadmap

Suggested phase structure; phase names and final scope should be adjusted after the owner resolves the questions below.

### Phase 0: Lock Shared Media Requirements
**Rationale:** The storage policy is chosen, but limits, formats, local URL forms and orphan behavior still affect API and settings fields.
**Delivers:** Requirements across Catalog, Merchant profile, and Appearance; align the product image limit and define local public URL behavior.
**Addresses:** Upload policy, storage destination, field compatibility and editor acceptance criteria.
**Avoids:** Product-only upload API, silent Blossom fallback, inconsistent public profile URLs, and unapproved remote deletion.

### Phase 1: Preserve OG Retrieval Fix and Implement Blossom Protocol Boundary
**Rationale:** The public share-card path is already failing for a real redirecting Blossom image. Safe upload transport/auth must be independently proven before UI integration.
**Delivers:** PR #28 integrated or equivalent approved patch; focused Blossom service; exact BUD-02/11 request behavior; public-egress pinning and redirect rejection; fake-server protocol tests.
**Uses:** Existing Python 3.12 stack, pinned `nostr-sdk==0.44.8`, `MerchantKeyStore.sign_event`, stdlib HTTP.
**Avoids:** Confusing GET redirect-following with authenticated PUT semantics.

### Phase 2: Add Shared Upload API and URL Compatibility
**Rationale:** Catalog and settings fields need one stable upload response for either storage target.
**Delivers:** Bounded authenticated route, local/Blossom target selection, verified Blossom descriptor, canonical public local URLs, clear-all/order/path regressions.
**Implements:** Upload route + shared service + existing `product_images` and settings URL fields.
**Avoids:** Unbounded multipart requests, route parity drift, inability to clear, and breaking migration media URLs.

### Phase 3: Integrate Shared Merchant Image UX
**Rationale:** Build all admin image fields on the same upload API and storage policy.
**Delivers:** Product multi-image picker plus Merchant profile and Appearance single-image upload controls; progress/retry/per-file errors, limits feedback, privacy/orphan disclosures, and retained URL editing.
**Addresses:** All v1.1 table stakes.
**Avoids:** Empty-image omission, loss of existing URL/local path entries, and lost editor state after failed uploads.

### Phase 4: Qualification and Operational Hardening
**Rationale:** Network writes and contract changes need regression evidence before release.
**Delivers:** Fake Blossom server coverage for success, auth failures, hash mismatch, redirects, timeouts, size limits, the configured-first-server rule, and explicit local retry; technical-spec/registry parity; `make verify-fast` and applicable runtime/lint/JS checks.
**Uses:** Deterministic local tests only; never perform test uploads to real public Blossom servers.
**Avoids:** “Works against one server” claims without bounds, fixture coverage, or route registration.

### Phase Ordering Rationale

- Preserve the approved policy: local default, explicit Blossom choice to the first configured server, backend signing, no dual-write, and user-selected local retry on Blossom failure.
- Integrate PR #28 before v1.1 share-card acceptance; preserve its scope as remote image **GET**, not upload.
- Prove BUD signing, exact encoding, SSRF-safe transport, and fake-server behavior before the admin UI depends on them.
- Reuse `product_images` and existing catalog updates first; defer database jobs/migrations and multi-server mirroring until requirements justify them.
- Route changes and spec/registry parity must be delivered together; any schema/state changes require the corresponding DDL/registry work.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 0:** Resolve upload size/count/formats, local public URL representation, unsaved-upload orphan behavior, and remote-delete policy.
- **Phase 1:** Probe `nostr-sdk==0.44.8` event-builder and JSON serialization behavior; test current BUD-11 header contract against a fake server; verify pinned IP/TLS SNI behavior and server-specific response compatibility.
- **Phase 2:** Decide exact route shape for existing and unsaved products; set safe multipart count/size/timeout limits; assess whether custom Blossom server base paths/ports are supported.
- **Phase 3:** Resolve the 16/20 product-image discrepancy and explicit distinction of unchanged vs clear-all across all UI fields before final acceptance.

Phases with standard patterns (skip broad research-phase):
- **Phase 3 UI mechanics:** Native browser file APIs, preview tiles, and explicit per-file status are established patterns once API and policy are fixed.
- **Phase 4 contract tests:** Existing fake-host/runtime and route-parity harness patterns should be extended, not replaced.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Python version, SDK pin, key custody, existing stdlib HTTPS pattern, and no-new-dependency constraint verified in local sources. |
| Features | HIGH | Current editor/API, product image fields, migration path, and protocol outcomes verified; final prioritization depends on owner scope. |
| Architecture | HIGH | Existing route/service/catalog boundaries and Blossom request shape are direct evidence; route shape and local public URL representation remain to be planned. |
| Pitfalls | HIGH | Protocol encoding, host validator behavior, empty-list omission, sorting, and image-cap drift are directly evidenced; deployment-specific egress remains to test. |

**Overall confidence:** HIGH on technical constraints and protocol facts; MEDIUM on product policy until owner decisions are recorded.

### Gaps to Address

- **Storage policy (resolved):** Local LNbits storage is the default; Blossom is explicit per upload to the primary/first configured server. No dual-write. If Blossom fails, the merchant can explicitly retry to LNbits.
- **Blossom configuration order (resolved):** Use the primary/first server configured in Settings → Merchant; preserve that order because the current setter sorts URLs.
- **Anonymous upload:** Recommend merchant signing by default; any anonymous mode requires explicit abuse/custody decision.
- **New unsaved product uploads:** Decide whether allowed and whether orphan disclosure is enough or staging is required.
- **Remote deletion:** Decide whether image removal should ever issue best-effort BUD DELETE. Default recommendation: catalog detachment only.
- **kind-10063 publication:** Optional; local settings are not published and upload MVP does not require publication.
- **Formats:** Recommend sniffed PNG/JPEG/WebP and reject SVG; decide GIF.
- **Image count:** Code/UI allow 20; technical spec §15 says ≤16. Select one and align code, spec, tests, and UI.
- **Upload limits:** Choose per-file size, per-request count, concurrency and local per-merchant quota across all upload surfaces; clarify which existing migration bounds (16 files, 25 MB/file, 400 MB/merchant) should carry over.
- **Local URL validation:** Existing migration relink creates `/images/...`, while product payload validation currently accepts only HTTPS. Decide precise allowed host-local path contract.
- **Local profile URLs:** Nostr kind-0 picture/banner values require an absolute public HTTPS URL. Define how local managed-media paths become canonical, publicly reachable URLs.
- **Endpoint normalization:** Decide whether custom configured path prefixes/ports are supported; current Blossom validator accepts them, but server-side transport should enforce strict HTTPS and port policy.
- **PR #28 validation:** Confirm merge/verification state and retain the live image/card regression. The inspected branch is still pre-merge; the milestone handoff reports local real-image validation.

## Sources

### Primary (HIGH confidence)

- [BUD-02](https://github.com/hzrd149/blossom/blob/master/buds/02.md) — raw upload method, request headers, success codes, and descriptor.
- [BUD-11](https://github.com/hzrd149/blossom/blob/master/buds/11.md) — event authorization, base64url without padding, expiration, upload scope, hash binding.
- [BUD-06](https://github.com/hzrd149/blossom/blob/master/buds/06.md) — advisory upload preflight.
- [BUD-04](https://github.com/hzrd149/blossom/blob/master/buds/04.md) — server-side blob mirroring.
- [BUD-03](https://github.com/hzrd149/blossom/blob/master/buds/03.md) — ordered kind-10063 server list.
- [NIP-B7](https://github.com/nostr-protocol/nips/blob/master/B7.md) — Blossom media usage and server discovery context.
- Local source: `infinitemarkets/services/relay.py`, `infinitemarkets/services/catalog.py`, `infinitemarkets/services/migration_media.py`, `infinitemarkets/services/og_images.py`, `infinitemarkets/security.py`, `infinitemarkets/keystore.py`, `infinitemarkets/views_api.py`, `infinitemarkets/static/infinitemarkets/js/admin_catalog.js`, and `infinitemarkets/templates/infinitemarkets/admin.html`.
- Local contract: `docs/technical-specification.md` §§5, 11, 13.2, 15; `harness/registry.py`; `tests/qualification/test_p0_14_contract_closure.py`.

### Secondary (MEDIUM confidence)

- PR #28 `fix/og-image-redirects` and milestone handoff report — GET-only redirect fix, real image redirect and local card validation. Checked-out `main` does not yet contain the redirect-following fix.
- Current live shop.lightnin.games behavior reported by the research handoff: image URL redirects to `image.nostr.build` and generated card uses a placeholder until safe GET redirect support is present. Treat as reported live observation, not independently re-fetched during this synthesis.

---
*Research completed: 2026-10-16*
*Ready for roadmap: yes, after Phase 0 owner questions are recorded*
