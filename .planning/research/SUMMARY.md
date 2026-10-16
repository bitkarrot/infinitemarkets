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

Infinite Markets already has the right extension points for v1.1: merchant Blossom endpoints are stored in `settings.blossom_servers`, the settings UI/API exist, product images are ordered HTTPS URLs, the admin product editor has a URL list, and image changes flow through existing product persistence and public projections. There is also a distinct, robust local migration-media path: bounded multipart parsing, SHA-256 and magic-byte checks, 25 MB/file, 400 MB/merchant, content-addressed LNbits data-folder storage, and relinking. It is not a Blossom uploader and should remain a separate capability.

For v1.1, recommend a backend-proxied, authenticated upload using existing `nostr-sdk==0.44.8` and `MerchantKeyStore.sign_event`, with Python stdlib HTTP and no new dependency by default. Implement exact BUD-02 raw `PUT /upload` and BUD-11 signed kind-24242 authorization, bounded bytes, hash verification, public-egress pinning, TLS SNI, and no automatic upload redirects. The admin should combine a multi-file picker and thumbnails with explicit ordering/primary, removal/clear-all, progress/retry/errors, and the existing URL workflow. The key risk is not protocol discovery but unresolved ownership/security policy: proxy vs direct delegated auth, server selection, fallback, limits, unsaved uploads, local storage fallback, deletion, and image format/count need owner decisions before locking requirements.

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
- Multi-file selection, thumbnails, primary/ordered images, per-image remove, and clear-all.
- Progress, retry, per-file errors, browser-side count/size feedback, and safe server-side bounds.
- Preserve pasted HTTPS URLs and existing imported/local `/images/...` URLs.
- Disclose the receiving media server and potential orphaned upload when product save is cancelled.
- Keep PR #28's safe GET redirect fix for share cards.

**Should have (competitive):**
- Backend-signed Blossom uploads with validated descriptor/hash and explicit primary/fallback policy.
- Optional later BUD-04 mirroring if merchants require multi-server resilience.

**Defer (v2+ or explicit follow-up):**
- Automatic remote deletion, anonymous uploads, kind-10063 publication, GIF support, and mirror-all by default.

See [FEATURES.md](FEATURES.md) for dependency graph and MVP boundaries.

### Architecture Approach

Add a focused Blossom service and an authenticated upload route, then let the existing product editor place the returned descriptor URL into its ordered image state and save through existing product POST/PATCH persistence. Keep image retrieval for OG cards in its existing GET-only service. A baseline synchronous upload requires no schema migration; only add durable upload state if operational evidence proves it necessary.

**Major components:**
1. Admin editor — file picker, previews, ordering, URL round-trip, status/retry, clear-all.
2. Upload route/service — bounded multipart, content sniff/hash, BUD-11 signer, pinned HTTPS BUD-02 PUT, descriptor validation.
3. Existing catalog and OG projections — persist ordered URL/dimensions/sort order, render storefront/catalog/cards, preserve GET redirect fix.

See [ARCHITECTURE.md](ARCHITECTURE.md) for flows and module boundaries.

### Critical Pitfalls

1. **GET vs PUT redirects** — PR #28's safe image GET redirect behavior must not forward upload bytes or authorization to a redirect target; reject upload redirects.
2. **BUD-11 wire details** — current official spec requires URL-safe base64 JSON event without padding and hash-bound `x`/`X-SHA-256`; test exact wire values.
3. **SSRF/DNS rebinding** — current Blossom URL validation is not request-time egress security; resolve/check public IPs, pin connection with TLS SNI, restrict HTTPS/port, and no PUT redirects.
4. **Image editor data loss** — frontend omits `images` when empty, so clear-all does not work; local `/images/...` migration URLs conflict with HTTPS-only validation.
5. **Undecided server order and image cap** — current setter alphabetically sorts Blossom URLs; code/UI cap is 20 but technical-spec §15 says 16.

See [PITFALLS.md](PITFALLS.md) for phase mapping and a pre-release checklist.

## Implications for Roadmap

Suggested phase structure; phase names and final scope should be adjusted after the owner resolves the questions below.

### Phase 0: Lock Product and Security Requirements
**Rationale:** Several choices change endpoint design and cannot be silently inferred from BUDs or current settings.
**Delivers:** Decision record for backend proxy, server ordering/failover, no-server behavior, upload scope/limits, media formats, local URL support, and orphan/deletion behavior; reconciled image-count limit.
**Addresses:** Upload policy and editor acceptance criteria.
**Avoids:** Building an unordered “primary” setting, incompatible file/URL validation, or unapproved remote deletion.

### Phase 1: Preserve OG Retrieval Fix and Implement Blossom Protocol Boundary
**Rationale:** The public share-card path is already failing for a real redirecting Blossom image. Safe upload transport/auth must be independently proven before UI integration.
**Delivers:** PR #28 integrated or equivalent approved patch; focused Blossom service; exact BUD-02/11 request behavior; public-egress pinning and redirect rejection; fake-server protocol tests.
**Uses:** Existing Python 3.12 stack, pinned `nostr-sdk==0.44.8`, `MerchantKeyStore.sign_event`, stdlib HTTP.
**Avoids:** Confusing GET redirect-following with authenticated PUT semantics.

### Phase 2: Add Contracted Upload API and Catalog Compatibility
**Rationale:** UI needs a stable descriptor and validated image contract; align persistence before introducing rich editor state.
**Delivers:** Bounded authenticated route, owner scope, upload limits and safe errors; server selection; verified descriptor; clear-all/order/local-URL regressions.
**Implements:** Upload route + service + existing `product_images` replacement.
**Avoids:** Unbounded multipart requests, route parity drift, inability to clear, and breaking migration media URLs.

### Phase 3: Integrate Product Editor UX
**Rationale:** Build on the stable upload descriptor/API and chosen product behavior.
**Delivers:** Multi-file picker, thumbnail tiles, primary/order controls, remove/clear, progress/retry/per-file errors, limits feedback, privacy/orphan disclosures, and retained URL editing.
**Addresses:** All v1.1 table stakes.
**Avoids:** Empty-image omission, loss of existing URL/local path entries, and lost editor state after failed uploads.

### Phase 4: Qualification and Operational Hardening
**Rationale:** Network writes and contract changes need regression evidence before release.
**Delivers:** Fake Blossom server coverage for success, auth failures, hash mismatch, redirects, timeouts, size limits, failover, and partial results; technical-spec/registry parity; `make verify-fast` and applicable runtime/lint/JS checks.
**Uses:** Deterministic local tests only; never perform test uploads to real public Blossom servers.
**Avoids:** “Works against one server” claims without bounds, fixture coverage, or route registration.

### Phase Ordering Rationale

- Resolve product/security policy before implementation because browser-direct auth, unsaved uploads, and mirroring change API/state shape.
- Integrate PR #28 before v1.1 share-card acceptance; preserve its scope as remote image **GET**, not upload.
- Prove BUD signing, exact encoding, SSRF-safe transport, and fake-server behavior before the admin UI depends on them.
- Reuse `product_images` and existing catalog updates first; defer database jobs/migrations and multi-server mirroring until requirements justify them.
- Route changes and spec/registry parity must be delivered together; any schema/state changes require the corresponding DDL/registry work.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 0:** Owner decision workshop; no protocol research can determine local fallback, browser-vs-proxy custody, orphan policy, limits, or deletion policy.
- **Phase 1:** Probe `nostr-sdk==0.44.8` event-builder and JSON serialization behavior; test current BUD-11 header contract against a fake server; verify pinned IP/TLS SNI behavior and server-specific response compatibility.
- **Phase 2:** Decide exact route shape for existing and unsaved products; set safe multipart count/size/timeout limits; assess whether custom Blossom server base paths/ports are supported.
- **Phase 3:** Resolve the 16/20 product-image discrepancy and explicit distinction of unchanged vs clear-all before final acceptance.

Phases with standard patterns (skip broad research-phase):
- **Phase 3 UI mechanics:** Native browser file APIs, preview tiles, and explicit per-file status are established patterns once API and policy are fixed.
- **Phase 4 contract tests:** Existing fake-host/runtime and route-parity harness patterns should be extended, not replaced.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Python version, SDK pin, key custody, existing stdlib HTTPS pattern, and no-new-dependency constraint verified in local sources. |
| Features | HIGH | Current editor/API, product image fields, migration path, and protocol outcomes verified; final prioritization depends on owner scope. |
| Architecture | HIGH | Existing route/service/catalog boundaries and Blossom request shape are direct evidence; final server selection and route shape are not decided. |
| Pitfalls | HIGH | Protocol encoding, host validator behavior, empty-list omission, sorting, and image-cap drift are directly evidenced; deployment-specific egress remains to test. |

**Overall confidence:** HIGH on technical constraints and protocol facts; MEDIUM on product policy until owner decisions are recorded.

### Gaps to Address

- **Backend proxy vs backend-minted short-lived auth for browser-direct upload:** Recommend backend proxy for custody and avoiding CORS dependence; owner must decide whether host upload bandwidth changes that choice.
- **Primary/fallback vs mirror-all:** Recommend explicit ordered primary/fallback, first-success MVP, optional BUD-04 mirror later. Current `set_blossom_servers` sorts URLs and must change if order matters.
- **No configured server:** Decide whether uploads are disabled with guidance, use an automatic default, or fall back to local managed storage. Existing local migration storage is not currently an upload fallback.
- **Anonymous upload:** Recommend merchant signing by default; any anonymous mode requires explicit abuse/custody decision.
- **New unsaved product uploads:** Decide whether allowed and whether orphan disclosure is enough or staging is required.
- **Remote deletion:** Decide whether image removal should ever issue best-effort BUD DELETE. Default recommendation: catalog detachment only.
- **kind-10063 publication:** Optional; local settings are not published and upload MVP does not require publication.
- **Formats:** Recommend sniffed PNG/JPEG/WebP and reject SVG; decide GIF.
- **Image count:** Code/UI allow 20; technical spec §15 says ≤16. Select one and align code, spec, tests, and UI.
- **Upload limits:** Choose product upload count/size/concurrency and clarify how (if at all) existing migration limits of 16 files, 25 MB/file, and 400 MB/merchant apply to external Blossom uploads.
- **Local URL validation:** Existing migration relink creates `/images/...`, while product payload validation currently accepts only HTTPS. Decide precise allowed host-local path contract.
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
