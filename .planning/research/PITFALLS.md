# Pitfalls Research

**Domain:** Blossom-backed product uploads and image-editor changes in a Python LNbits extension
**Researched:** 2026-10-16
**Confidence:** HIGH for protocol, custody, local contract, and SSRF pitfalls; MEDIUM for service-specific behavior not yet implemented

> **Milestone scope:** These findings are specific to v1.1 media planning. Prior v1.0 project research is preserved under `.planning/research/v1.0-core/`.

## Critical Pitfalls

### Pitfall 1: Confusing Safe GET Redirects With Safe Upload Redirects

**What goes wrong:**
The Open Graph image change is applied as a generic redirect-following HTTP policy, so a Blossom `PUT /upload` follows a 307/308 and forwards bytes and the `Authorization` header to an unexpected host.

**Why it happens:**
Both features involve Blossom URLs and HTTPS, but one is a public image GET and the other is an authenticated write. Similar URL symptoms obscure different credential and replay risks.

**How to avoid:**
Keep PR #28's bounded safe redirect logic strictly on remote image GET retrieval. For upload, disable redirects; reject them and report a safe error. Resolve and check all configured targets, enforce port policy, connect to the checked public IP while retaining TLS SNI, and never forward upload authorization to a redirect target.

**Warning signs:**
Shared HTTP helper uses automatic redirects; tests expect a PUT to succeed after a 307; auth header appears in a redirected request.

**Phase to address:**
Phase 1 — protocol/security service and fake-server tests; PR #28 GET behavior is a milestone prerequisite but not the upload redirect policy.

---

### Pitfall 2: BUD-11 Authorization Encoding or Hash Binding Is Wrong

**What goes wrong:**
The remote Blossom server rejects an otherwise valid upload, or accepts an authorization intended for another file/target because the header event's encoding, scope, or hash does not match.

**Why it happens:**
A researcher note reported standard base64, while the current official BUD-11 text requires URL-safe base64 JSON with no padding. Event tag requirements and request-header matching are easy to miss.

**How to avoid:**
Follow the current official raw BUD-11 specification: `Authorization: Nostr <base64url(JSON event)>` with **no padding**; signed kind 24242; human-readable content; `t=upload`; expiration; an `x` tag matching the exact `X-SHA-256`; and a recommended domain-scoped `server` tag. Use `nostr-sdk==0.44.8` through `MerchantKeyStore.sign_event`. Assert exact wire encoding and event fields in deterministic tests.

**Warning signs:**
Base64 padding, standard alphabet `+`/`/`, missing `x`, stale expiration, wrong hash case/value, or an authorization header that differs from the signed event JSON.

**Phase to address:**
Phase 1 — protocol contract and signer probes before UI work.

---

### Pitfall 3: SSRF Through Configured Blossom Endpoint and DNS Rebinding

**What goes wrong:**
The extension sends merchant media or signed auth to a loopback, private, link-local, metadata, or rebinding address.

**Why it happens:**
Current Blossom config validation is weaker than the relay egress controls: it accepts arbitrary ports and path prefixes, and lacks punycode/internal-TLD normalization and runtime DNS checks. A valid-looking hostname does not prove safe egress.

**How to avoid:**
Treat persisted endpoints as untrusted at request time. Require strict HTTPS and an explicit allowed-port policy; reject userinfo/fragments and unsupported path forms; normalize internationalized hostnames; resolve all answers and reject if any answer is not globally routable; connect to a pinned checked IP with TLS SNI for the hostname. Do not rely on URL validation alone or resolve once and let a client re-resolve. Review `security.resolve_and_check_egress` and the pinned HTTPS pattern in `services/og_images.py`; do not add unrestricted redirects.

**Warning signs:**
Transport library receives only a hostname and resolves independently; arbitrary port/path accepted without review; test suite covers literal loopback but not mixed DNS answers or rebinding.

**Phase to address:**
Phase 1 — security design and fake resolver/connection tests before endpoint implementation.

---

### Pitfall 4: Product Image UX Cannot Clear or Round-Trip Existing Data

**What goes wrong:**
Merchants remove images in the editor but a save silently keeps them; or saving a product with imported/local images is rejected or drops paths.

**Why it happens:**
`gmSaveProduct` includes `body.images` only when the newline field has at least one entry. The backend uses key presence to distinguish replacement from omission and can clear with an explicit empty list. Separately, migration media generates local `/images/infinitemarkets/...` paths but product payload validation currently accepts only HTTPS image URLs.

**How to avoid:**
Represent an explicit empty image list and send `images: []` when the editor intends to clear. Preserve distinction between unchanged/omitted and intentionally empty. Add regressions for clear-all, reorder, URL round-trip, and local `/images` round-trip. Resolve and document URL validation compatibility without permitting arbitrary local filesystem paths.

**Warning signs:**
Empty textarea produces no `images` key; tests cover only non-empty URL lists; local migration images fail product PATCH.

**Phase to address:**
Phase 2 — catalog contract and editor-state integration.

---

### Pitfall 5: Configured Server Ordering Does Not Match Primary Target

**What goes wrong:**
The user places one Blossom server first in Settings → Merchant, but uploads contact a different endpoint because the backend sorts the list.

**Why it happens:**
`set_blossom_servers` currently de-duplicates and sorts URLs. That behavior erases the user's configured order; the approved v1.1 policy uses only the primary/first server.

**How to avoid:**
The owner chose the primary/first configured Blossom server as the only remote target for an upload. Preserve that order in storage and test that later configured servers are not contacted automatically. If the primary fails, surface the error and offer an explicit LNbits-local retry; BUD-04 mirroring is deferred.

**Warning signs:**
UI presents a first/primary server but backend canonicalization sorts; tests only assert upload success without asserting which configured server received it.

**Phase to address:**
Phase 0 owner decisions, then Phase 1 settings and selection policy.

---

### Pitfall 6: Image Limit Drifts Between Specification, Runtime, and UI

**What goes wrong:**
One layer rejects image 17 while another allows images 17–20, causing failed imports, saves, or mismatched API contract.

**Why it happens:**
Current catalog code and admin UI say maximum 20; technical specification §15 says at most 16. Existing migration media separately limits uploads to 16 files per request, which is not itself the product-image cap.

**How to avoid:**
Get an explicit owner decision on product image count. Change code/UI/spec/tests in the same implementation slice. Keep per-request upload batch limits clearly separate from per-product image count.

**Warning signs:**
“16” and “20” appear in different validation paths; tests test only a low count; migration file limit is used to justify catalog count without a product decision.

**Phase to address:**
Phase 0 — requirements gate before editor/API implementation.

---

### Pitfall 7: Upload Succeeds but Product Save Is Cancelled

**What goes wrong:**
Blobs remain on the server with no product reference, or an image is shown as saved before the product transaction succeeds.

**Why it happens:**
Blossom PUT and local catalog database update cannot be one atomic transaction. New unsaved product uploads make this especially visible.

**How to avoid:**
Make upload status distinct from product save status; only show it attached after the editor list is updated, and explain that cancelling after upload can leave an orphaned blob. Decide whether new-product upload is allowed before the product exists. Do not auto-delete on cancel unless ownership/shared-content semantics are approved.

**Warning signs:**
UI labels the product saved immediately after remote PUT; no cancel disclosure; retries create duplicate uploads without hash idempotency awareness.

**Phase to address:**
Phase 0 owner decision and Phase 2 editor acceptance tests.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Use plain high-level HTTPS client without pinned IP | Less transport code | DNS rebinding can route credentials or content to private/internal targets | Never for server-side upload to merchant-configured hosts |
| Follow all redirects for any HTTPS request | Makes one Blossom redirect work | Upload body/auth can be replayed to a new host | Never for PUT; GET redirect behavior only where separately bounded and tested |
| Keep sorting Blossom server URLs while treating the first as primary | Reuses existing setter | The upload may go to a different server than the merchant selected first | Only if the UI explicitly says server order is irrelevant |
| Reuse migration-media local 25 MB limit without requirements review | Fast size bound | Wrong policy for external Blossom, aggregate quotas, and host memory model may be inherited accidentally | Candidate only; owner approves product upload size/count and implementation enforces it |
| Omit `images` when list is empty | Avoids accidental patching | Makes clear-all impossible | Never when the user explicitly cleared images |
| Add `images` only as URLs and discard returned descriptor hash/size/type | Minimal editor changes | Loses evidence for validation/debugging and makes retry/preview states weaker | MVP may store only URL in catalog, but validate descriptor before returning it |
| Add a new JS SDK to Python backend | Quick API convenience | Dependency duplication and unclear custody/runtime boundary | Never without approved, demonstrated capability gap |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| BUD-02 upload | Send multipart body directly to `/upload` or trust response without checking | Send raw bytes with `Content-Type`, `Content-Length`, and `X-SHA-256`; accept 200/201 only; validate descriptor fields. |
| BUD-11 auth | Use standard padded base64, omit `x`, or accept mismatch between tag and header | URL-safe base64 without padding; kind 24242; `t=upload`, expiry, matching `x` and `X-SHA-256`; recommended `server` scope. |
| BUD-06 preflight | Treat successful `HEAD` as guarantee of a successful PUT | Treat it as advisory only; handle upload result independently. |
| BUD-04 mirror | Mirror all configured servers without failure semantics | Defer. V1.1 writes to one selected target; add mirroring only after defining partial success, retry, and URL policy. |
| Blossom settings | Assume local setting is the published kind-10063 list or an ordered list | Local settings are separate; setter currently sorts. Make kind-10063 and order explicit decisions. |
| OG image retrieval | Let PR #28's GET redirect behavior apply to upload | Keep safe redirect handling limited to image GET; never blindly follow upload PUT redirect. |
| Product PATCH | Use an empty list to mean “leave unchanged” | Omitted key means unchanged; present empty array means clear. Client must preserve this distinction. |
| Local image URLs | Validate every image as HTTPS despite existing relink flow | Reconcile accepted local `/images/...` URLs with the technical spec and add regression coverage. |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Unbounded multipart body buffered in memory | Spiky RAM, host timeouts, requests compete with checkout | Enforce stream, per-file, total-request, count, and time limits before materializing bytes; avoid duplicate copies | A few concurrent near-limit uploads can be enough; do not wait for high user counts |
| Blocking `http.client` on async event loop | Slow APIs and delayed unrelated host requests during remote upload | Run bounded blocking operations off-loop with explicit timeouts and concurrency limits | First slow remote server |
| Mirror every file to every server in foreground | Long save delays and more partial failures | First-success MVP; optional asynchronous/durable BUD-04 only after need is proven | Latency grows with server count and slowest endpoint |
| Decode untrusted huge image while generating card | CPU/memory spike during public OG request | Preserve existing source byte/pixel limits and safe format allowlist in OG image code | A crafted oversized image or burst of cold cache misses |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Trust `validate_blossom_url` as egress enforcement | Current validation allows arbitrary port/path and does not perform request-time DNS pinning; SSRF | Strict HTTPS/port policy; normalize host; resolve and reject any non-public answer; pinned IP connection with TLS SNI; no upload redirects |
| Put nsec or reusable auth in browser | Merchant identity compromise or replay | Sign each upload backend-side; short expiration; never log Authorization value; no nsec in HTML/JS/response. |
| Follow a PUT redirect | Body and signed auth leakage to destination controlled by redirect | Reject; make host explicit and re-run endpoint validation if user config changes. |
| Trust filename/MIME supplied by browser | Malformed file accepted, unsafe type propagated | Derive type by content sniff; safe allowlist; ignore filename for storage/protocol identity. |
| Accept SVG without sanitization | Active-content, remote-resource, and inconsistent renderer risks | Reject SVG for initial upload; decide whether GIF is allowed. |
| Log signed authorization event or raw upload bytes | Exposes replayable short-term token or user content | Redact auth headers, hash only where safe, keep logs bounded and metadata-only. |
| Treat upload response URL as trusted | Malicious/incorrect descriptor can point to unexpected host or mismatched content | Validate descriptor schema, digest/size/type and URL HTTPS/host policy before returning to UI. |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Keeping only a URL textarea | Upload requirement feels absent and ordering is opaque | Add thumbnails, picker, order controls, per-image remove, and retain URL input. |
| No all-clear action | User cannot remove final image because empty form is omitted | Explicit clear-all action and send `images: []`. |
| Whole-form spinner only | User cannot tell which upload failed or retry one file | Per-file progress, status, error, and retry while preserving current order. |
| Hide receiving server | Merchant cannot make an informed privacy/custody choice | Show server name/URL and explain it receives image bytes and request metadata. |
| Pretend remote upload and save are atomic | User believes cancelled uploads are undone | Distinguish “uploaded” from “saved to product”; disclose possible orphan on cancel. |
| Upload control treats Blossom as mandatory | Merchants without an accessible Blossom account cannot add images | Keep local LNbits storage available by default; show Blossom as optional and explain how to configure it. |

## "Looks Done But Isn't" Checklist

- [ ] **BUD-11 auth:** Verify exact kind/tags/expiry, URL-safe base64 with no padding, and matching SHA-256 tag/header.
- [ ] **BUD-02 PUT:** Verify raw body, content headers, 200/201, descriptor validation, timeout, and explicit rejection of 3xx.
- [ ] **SSRF controls:** Test public host, IPv4/IPv6 private answers, mixed DNS answers, rebinding behavior, strict port, TLS SNI, and no request to the unpinned hostname.
- [ ] **Editor clear/reorder:** Verify omission preserves, empty array clears, and order/primary survives a reload.
- [ ] **Existing URL workflows:** Verify pasted HTTPS and migration-created `/images/...` URL edit/save round trips.
- [ ] **Image caps:** Resolve and test the 16-vs-20 mismatch; distinguish product count from per-request file count.
- [ ] **Blossom target:** Verify only the first configured server receives the upload; a failure offers an explicit LNbits retry and does not silently target another server.
- [ ] **Local default:** Confirm uploads work with no Blossom servers configured and no silent remote upload occurs.
- [ ] **OG fix:** Verify GET redirect card for the real Blossom redirect case; ensure upload PUT does not inherit GET redirect behavior.
- [ ] **Contracts:** Route is present in both spec §5 and harness registry; parity test passes.
- [ ] **No external writes in tests:** All upload, auth, redirect, and failure cases use fake Blossom servers.
- [ ] **Verification:** Run `make verify-fast`, targeted runtime tests, `ruff check .`, and `node --check` on changed JavaScript as applicable.

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Wrong BUD-11 serialization | MEDIUM | Reproduce against a local fake server, capture a non-secret synthetic event fixture, correct encoding/tags, and add a protocol regression before retrying live integration. |
| Unsafe redirect/egress shipped | HIGH | Disable Blossom uploads, patch host pinning/redirect rejection, review logs and affected server targets, then re-enable after security tests and owner review. |
| Product images not cleared | LOW–MEDIUM | Send explicit empty array, add UI state distinction, verify DB replacement and generated catalog projection, and restore images if save was expected to preserve. |
| Server order lost | MEDIUM | Confirm persisted list and observed attempt order; restore settings from merchant input if available; change setter/UI to preserve stable order and test. |
| Orphaned uploaded blobs | LOW for display; potentially MEDIUM for provider quota | Leave catalog unchanged; tell merchant remote blob may remain; avoid speculative DELETE. Add a cleanup policy only if service ownership and BUD authorization are established. |
| Local `/images` URLs cannot be edited | MEDIUM | Preserve database values, add narrowly-scoped validation for host-served paths, update spec, and add editor PATCH regression. Do not broaden to arbitrary local paths. |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| GET vs PUT redirect confusion | Phase 1 — protocol/service | Fake server returns 307 to a second host; assert no second request and no auth/body forwarding. |
| BUD-11 auth mismatch | Phase 1 — protocol/service | Exact event/header assertions using SDK-generated synthetic key and fake server verifier. |
| SSRF/rebinding | Phase 1 — security transport | Resolver injection tests for private/mixed results and pinned connection host/SNI. |
| Clear-all and local URL round-trip | Phase 2 — catalog/editor | Runtime tests for omitted/empty images, sort order, HTTPS URL, and owned `/images` path. |
| Server ordering | Phase 0 decision; Phase 1 settings | Config save/load and ordered attempt sequence regression. |
| 16-vs-20 image limit | Phase 0 requirements | One selected requirement value appears in code, UI, spec and tests. |
| Unsaved product/orphans | Phase 0 decision; Phase 2 UX | Cancel/failed-save interaction test and exact disclosure text review. |
| Bounded upload and host load | Phase 1 service; Phase 3 hardening | Oversized/chunked upload, slow server, concurrency, and memory-safe error behavior. |

## Sources

- Local code: `infinitemarkets/services/relay.py`, `infinitemarkets/security.py`, `infinitemarkets/services/og_images.py`, `infinitemarkets/services/catalog.py`, `infinitemarkets/services/migration_media.py`, `infinitemarkets/keystore.py`, `infinitemarkets/views_api.py`, `infinitemarkets/static/infinitemarkets/js/admin_catalog.js`.
- Local contract: `docs/technical-specification.md` §5, §11, §13.2, §15; `harness/registry.py`; `tests/qualification/test_p0_14_contract_closure.py`.
- [BUD-02](https://github.com/hzrd149/blossom/blob/master/buds/02.md), [BUD-03](https://github.com/hzrd149/blossom/blob/master/buds/03.md), [BUD-04](https://github.com/hzrd149/blossom/blob/master/buds/04.md), [BUD-06](https://github.com/hzrd149/blossom/blob/master/buds/06.md), [BUD-11](https://github.com/hzrd149/blossom/blob/master/buds/11.md), [NIP-B7](https://github.com/nostr-protocol/nips/blob/master/B7.md).
- PR #28 `fix/og-image-redirects` is a prerequisite/fix-in-flight per milestone handoff; the inspected `main` code remains the pre-merge state.

---
*Pitfalls research for: Infinite Markets v1.1 media uploads and Blossom support*
*Researched: 2026-10-16*
