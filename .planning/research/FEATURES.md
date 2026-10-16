# Feature Research

**Domain:** Shared merchant image uploads across Catalog, Merchant profile, and Appearance settings
**Researched:** 2026-10-16
**Confidence:** HIGH for existing integration points and protocol expectations; MEDIUM for policy-sensitive scope

> **Milestone scope:** This is v1.1-specific research. Prior v1.0 project research is preserved under `.planning/research/v1.0-core/`.

## Feature Landscape

### Table Stakes (Users Expect These)

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Multi-file image picker and thumbnail tiles | Product editors conventionally show selected images, not only raw URL strings | MEDIUM | Use browser-native file selection and previews. Confirm selected count and byte size before transfer; enforce real limits server-side. |
| Single-image uploads for settings fields | Merchant avatar/banner and store logos/backgrounds are standard branding assets | LOW–MEDIUM | Reuse the uploader in Merchant profile picture/banner and Appearance brand logo, hero background, footer logo, and custom share-card fields. |
| Explicit primary and ordering controls | First image is used by existing catalog projections and share-card behavior | MEDIUM | At minimum provide move-up/down and visibly identify the primary image. Preserve `sort_order` when saving. |
| Per-image removal and “clear all” | Merchants must correct mistakes and remove prior images | LOW | PATCH supports replacing image details with `images: []`; current `gmSaveProduct` omits `images` when empty, so the UI currently cannot clear all images. |
| Upload progress, retry, and per-file errors | Uploads are network operations and may fail independently | MEDIUM | Explain safe retry/hash behavior; distinguish local validation, authorization, server rejection, timeout, and transport errors without exposing signed tokens. |
| Keep the existing HTTPS URL workflow | Existing catalog data and merchant workflows already use URL text input | LOW–MEDIUM | Preserve pasted URLs alongside uploaded media; do not force existing images through a re-upload path. |
| Round-trip local `/images/...` URLs | Migration media can relink catalog images to host-served local paths | MEDIUM | There is a current contract mismatch to settle: migration creates `/images/infinitemarkets/...`, while catalog payload validation currently insists on `https://`. Ensure edit/save does not lose or make these images uneditable. |
| Clear disclosure and understandable no-server state | The configured media server receives merchant-uploaded content and can associate requests with the merchant | LOW | State which server receives bytes and that cancelling after upload but before save may leave an unreferenced blob. |
| Useful failure without losing editor state | Upload and final product save are separate operations | MEDIUM | Keep the selected/ordered image list and URL text stable on errors; allow retry or cancel without silently mutating product data. |

### Differentiators (Competitive Advantage)

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Blossom-native upload and hash identity | Produces portable content-addressed media rather than requiring a proprietary store | HIGH | BUD-02 descriptor returns URL, hash, size, type, and upload time. Verify descriptor against bytes sent. |
| Server-side delegated signing | Merchants can upload with their Nostr identity without exporting keys to their browser | HIGH | Backend-proxy flow is the recommended default; a per-upload kind-24242 event is narrowly scoped and expires. |
| Local default with explicit Blossom option | Merchants without Blossom access still need image uploads | MEDIUM | Save to this LNbits instance by default; when Blossom is selected, use only the primary/first configured server. On failure, offer an explicit local retry. No dual-write in v1.1. |
| Resilience via BUD-04 mirroring | Optional redundancy without requiring duplicate browser uploads | HIGH | Defer until required; define partial success and durable retry behavior before shipping mirror-all. |
| Share-card reliability for Blossom redirects | Public Open Graph cards can display remote images whose HTTPS retrieval URL redirects safely | MEDIUM | PR #28 `fix/og-image-redirects` is the fix-in-flight prerequisite. Its GET-only redirect handling is separate from upload transport policy. |
| Image dimensions for layout stability | Catalog and preview layouts can reserve stable space before an image loads | LOW–MEDIUM | Existing `product_images` stores dimensions. Capture only when useful; browser-reported dimensions are hints, not proof of decoded image safety. |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|----------------|-------------|
| Put merchant private key in the browser for direct upload | Seems like the shortest path to Blossom auth | Exposes durable signing authority to frontend code and browser extensions | Backend signs per-upload authorization, or owner-approved short-lived delegated auth only. |
| Upload every image to every configured server synchronously | Appears to guarantee availability | Multiplies upload time and failure modes; partial success and URL selection become ambiguous | Store each file in one selected backend. Defer BUD-04 mirroring until availability needs justify its retry and partial-success policy. |
| Automatically delete remote blobs whenever an image is removed | Avoids apparent unused storage | Blossom blobs may be shared/content-addressed; deletion may affect other references and can fail independently from local save | Treat product-image removal as catalog detachment. Consider best-effort BUD DELETE only after owner confirms ownership, sharing, and failure semantics. |
| Automatically upload images for unsaved product drafts | Smooth first-time editing | If the product is cancelled or save fails, the remote blob is orphaned; upload and catalog transaction cannot be atomic | Explain orphan behavior, allow save-and-upload staging, or require product creation before upload. Owner decision. |
| Accept every image format, including arbitrary SVG | Broad format support | SVG can contain active content or remote references and may render inconsistently across consumers | Recommend sniffed PNG/JPEG/WebP; owner decides GIF. Reject SVG in the initial upload path. |
| Replace the existing URL field with upload-only UI | Simplifies the screen | Breaks pasted URLs, imports, and existing product data | Offer upload controls alongside a URL list that remains editable and round-trippable. |

## Feature Dependencies

```text
PR #28 safe GET redirects for OG image retrieval
    └──required for──> Reliable share cards for Blossom image URLs

Remaining owner decisions (formats, limits, orphan policy, and cleanup)
    └──required for──> Blossom upload contract and endpoint
                           └──requires──> Bounded bytes + SHA-256 + BUD-11 signer
                                              └──requires──> Pinned-safe HTTPS PUT

Blossom upload endpoint
    └──enables──> Shared Catalog / Merchant / Appearance uploader
                      └──requires──> Single-image and ordered-gallery modes
                                         └──requires──> URL/local-path round-trip validation
```

### Dependency Notes

- **PR #28 precedes share-card acceptance:** the live shop.lightnin.games case has an Open Graph card image that returns a 1200×630 placeholder because its first Blossom URL returns `307` to `image.nostr.build`. The fix-in-flight is for bounded safe HTTPS **GET** image redirects and was locally validated with the real image/card per milestone handoff. It must not cause upload PUTs to follow redirects.
- **Upload route requires resolved auth and transport policy:** BUD-11 details (kind 24242, `t=upload`, expiration, `x` hash, optional `server`) and the exact Authorization encoding need regression tests before UI integration.
- **Editor integration requires state replacement to be fixed:** current frontend omits `images` from product PATCH if the text area is empty. The backend's present replacement path can clear with an explicit empty list, but the editor never sends that list.
- **Local-path compatibility is required before round-trip claims:** the existing migration media flow creates local `/images/...` URLs, whereas catalog validation currently restricts image payloads to `https://`. Requirements must decide/describe supported local URLs and align code/spec.
- **Primary selection requires changing settings semantics:** current `set_blossom_servers` sorts/deduplicates values, so the configured sequence cannot currently encode the primary/first server chosen by the merchant.
- **No schema migration is inherently required:** `product_images` already stores URL, dimensions, and sort order. A new durable upload-job table would be a separate reliability decision, not an automatic requirement.

## MVP Definition

### Launch With (v1.1)

- [ ] Preserve/integrate PR #28 safe redirect following for GET-based OG image retrieval; keep it distinct from uploads.
- [ ] Reusable uploader for product galleries, Merchant profile picture/banner, and Appearance brand logo, hero, footer, and custom share-card image.
- [ ] Multi-file product picker with thumbnails, primary/order adjustment, per-image removal, and clear-all; single-image mode for settings fields.
- [ ] Local LNbits storage as the default, plus explicit Blossom selection using only the primary/first configured server; never dual-write.
- [ ] Backend-proxied, authenticated Blossom upload with no nsec in the browser; Blossom failure remains visible and offers an explicit local-storage retry.
- [ ] Bounded multipart requests, upload size/count feedback, PNG/JPEG/WebP sniffing, SHA-256, and BUD-11 authorization verified by a fake Blossom server.
- [ ] Progress, retry, per-file errors, and preservation of editor state on failure.
- [ ] Keep pasted HTTPS URLs and supported imported/local `/images/...` URLs round-trippable.
- [ ] Explicit owner-facing disclosure of the selected receiving server and the unsaved-upload/orphan case.
- [ ] Align the code and technical specification image-count limit (existing service/UI says 20; §15 says 16) before implementation is declared complete.
- [ ] Document upload route in `docs/technical-specification.md` §5 and `harness/registry.py::HTTP_ROUTES`; add fake-server and contract tests.

### Add After Validation (v1.x)

- [ ] BUD-04 mirror to additional configured servers — only if merchants need redundancy and partial/mirror retry semantics are defined.
- [ ] Persisted upload job/retry state — only if real deployment evidence shows synchronous bounded upload is insufficient.
- [ ] Optional BUD-06 preflight — if supported servers reliably implement it and failure handling remains best-effort.
- [ ] Dimension-aware layout hints — if actual storefront layout shifts justify the added metadata work.

### Future Consideration (v2+)

- [ ] Publish merchant kind-10063 Blossom server lists — optional Nostr discoverability scope; not required to use the local `blossom_servers` setting for uploads.
- [ ] Best-effort remote deletion (BUD DELETE) — defer until shared-blob consequences, authorization, and retry semantics are approved.
- [ ] Anonymous upload mode — default to merchant signing; anonymous upload should require explicit product and abuse-policy approval.
- [ ] GIF uploads — decide based on animation need and downstream storefront/card compatibility.

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Bounded authenticated Blossom upload with server-side signing | HIGH | HIGH | P1 |
| Ordered thumbnails, primary selection, removal, clear all | HIGH | MEDIUM | P1 |
| Preserve pasted and local/imported image URLs | HIGH | MEDIUM | P1 |
| Progress, retry, and per-file feedback | HIGH | MEDIUM | P1 |
| PR #28 OG redirect behavior | HIGH | MEDIUM | P1 |
| BUD-04 mirror to all servers | MEDIUM | HIGH | P2 |
| kind-10063 publication | LOW–MEDIUM | MEDIUM | P3 |
| Automatic remote deletion | LOW | HIGH | P3 |

**Priority key:**
- P1: Must have for v1.1 acceptance
- P2: Should have, add when possible
- P3: Nice to have, future consideration

## Competitor / Ecosystem Feature Analysis

No comparative product UX audit is claimed in these four research passes. The directly verified ecosystem contracts inform the approach below:

| Feature | Blossom protocol | Existing Infinite Markets | Our Approach |
|---------|------------------|---------------------------|--------------|
| Upload | BUD-02 raw-byte `PUT /upload`; descriptor includes content hash and media metadata | Existing admin surfaces accept image URLs; migration media has separate local multipart upload | One reusable uploader stores to local LNbits by default or to the first configured Blossom server when selected; retain existing URLs. |
| Authorization | BUD-11 signed kind-24242 event and hash-bound request | Merchant keys are encrypted and signing is an operation on `MerchantKeyStore` | Sign in backend per upload and never expose nsec in browser. |
| Server choice | BUD-03 ordered kind-10063 server tags, first preferred | Local Blossom configuration is in settings; setter sorts URLs; no kind-10063 publication | Use the first Settings → Merchant Blossom server as the only remote target; preserve list order; kind-10063 publication remains separate and deferred. |
| Media fallback | BUD-04 server-side mirror exists | Existing migration flow stores verified images locally in LNbits data folder | Local LNbits is the default and explicit retry target; do not dual-write or silently switch backends. |

## Sources

- Local admin workflow: `infinitemarkets/templates/infinitemarkets/admin.html`, `infinitemarkets/static/infinitemarkets/js/admin_catalog.js`.
- Existing product image persistence and validation: `infinitemarkets/services/catalog.py`, `infinitemarkets/views_api.py`.
- Existing migration media: `infinitemarkets/services/migration_media.py`, `docs/technical-specification.md` §13.2.
- Blossom config: `infinitemarkets/services/relay.py`, `infinitemarkets/static/infinitemarkets/js/admin_settings.js`.
- Share-card source retrieval: `infinitemarkets/services/og_images.py`; current in-flight fix: PR #28 `fix/og-image-redirects` (per project handoff; not merged in the inspected `main` working tree).
- [BUD-02](https://github.com/hzrd149/blossom/blob/master/buds/02.md), [BUD-03](https://github.com/hzrd149/blossom/blob/master/buds/03.md), [BUD-04](https://github.com/hzrd149/blossom/blob/master/buds/04.md), [BUD-06](https://github.com/hzrd149/blossom/blob/master/buds/06.md), [BUD-11](https://github.com/hzrd149/blossom/blob/master/buds/11.md), [NIP-B7](https://github.com/nostr-protocol/nips/blob/master/B7.md).

---
*Feature research for: Infinite Markets v1.1 media uploads and Blossom support*
*Researched: 2026-10-16*
