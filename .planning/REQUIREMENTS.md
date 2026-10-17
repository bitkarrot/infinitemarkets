# Requirements: infinitemarkets

**Defined:** 2026-10-16
**Milestone:** v1.1 — Media uploads and Blossom support
**Core Value:** A merchant can sell one authoritative inventory safely through LNbits-backed web and Nostr flows without duplicate invoices, double allocation, or relay delivery being mistaken for payment truth.

## v1 Requirements

Requirements for v1.1. Each maps to one roadmap phase after owner approval.

### Media Storage

- [x] **MEDIA-01**: Merchant can upload an image to this LNbits instance without configuring or accessing a Blossom server; if no Blossom server is configured, local LNbits storage is selected by default.
- [x] **MEDIA-02**: Merchant can explicitly choose Blossom for an upload; the backend targets only the primary/first configured `Media (Blossom)` server, preserves configured order, and does not dual-write or silently retry another remote server.
- [x] **MEDIA-03**: If a chosen Blossom upload fails, the merchant sees a plain-language error and may explicitly retry the same image to LNbits-local storage.
- [x] **MEDIA-04**: Blossom upload authorization is signed server-side with the merchant's stored Nostr key; no nsec or reusable signing key is exposed to browser code.
- [x] **MEDIA-05**: Uploads use bounded multipart parsing (at most 16 files/request and 25 MB/file), avoid unbounded in-memory buffering, enforce a 400 MB per-merchant LNbits-local quota, accept only signature-verified PNG/JPEG/WebP, reject SVG/GIF, compute SHA-256, and validate any returned Blossom descriptor before exposing its URL.
- [x] **MEDIA-06**: LNbits-managed images use a merchant-scoped opaque storage namespace outside the reinstallable extension package and are served through the host image mount.
- [x] **MEDIA-07**: A locally stored image used in Nostr profile picture/banner metadata is emitted as a publicly reachable absolute HTTPS URL; Appearance fields may use a safe same-origin path where supported.

### Image Editor

- [x] **MEDIA-08**: One reusable upload control is available for the product gallery, Merchant Nostr profile avatar/banner, and Appearance brand logo, hero background, footer logo, and custom share image.
- [x] **MEDIA-09**: Product images support multiple files, thumbnails, a visible primary image, ordering, per-image removal, and an explicit clear-all operation.
- [x] **MEDIA-10**: Single-image settings fields support replacing and clearing their image without changing unrelated profile/theme fields.
- [x] **MEDIA-11**: The merchant can continue to paste existing HTTPS image URLs, and editing/saving preserves supported migration-managed local `/images/...` URLs.
- [x] **MEDIA-12**: Upload UI reports per-file progress and errors, preserves other selected images on failure, and explains that cancelling before saving a setting/product can leave an unreferenced uploaded file.
- [x] **MEDIA-13**: Product image ordering, removal, and clear-all persist through the existing catalog API and are reflected in public pages and Nostr projections.
- [x] **MEDIA-14**: Product image count remains at 20, matching current service behavior; update technical-specification, UI, and tests to agree.

### Protocol and Release Safety

- [x] **MEDIA-15**: Blossom uploads use BUD-02 raw `PUT /upload` and BUD-11 kind-24242 authorization with a short expiration, `t=upload`, matching SHA-256 `x` tag and `X-SHA-256` header, a target-scoped `server` tag, and URL-safe base64 JSON without padding.
- [x] **MEDIA-16**: Backend requests to configured Blossom servers use HTTPS with request-time public-egress validation, pinned-IP TLS connections, strict time/size bounds, and reject upload redirects.
- [x] **MEDIA-17**: Blossom share-card image GETs follow only bounded, revalidated HTTPS redirects; upload PUTs do not inherit GET redirect behavior. PR #28 must be merged and verified before release.
- [x] **MEDIA-18**: Any new API route is registered in both `docs/technical-specification.md` §5 and `harness/registry.py::HTTP_ROUTES`; contract parity and fake-Blossom tests pass.
- [x] **MEDIA-19**: Automated tests exercise local storage, Blossom success, BUD auth/hash/descriptor checks, the first-configured-server rule, failure with explicit local retry, size/type rejection, URL round-trips, and share-card redirects without writing to public Blossom servers.

## v2 Requirements

Deferred unless the owner promotes them into v1.1 scope.

### Media Resilience

- **MEDIA-20**: Merchant can mirror Blossom blobs to additional configured servers through BUD-04 with visible partial-success and retry status.
- **MEDIA-21**: Merchant can publish the configured media-server list as a Nostr kind-10063 event.
- **MEDIA-22**: Merchant can view and clean unused Blossom uploads, with best-effort BUD DELETE and explicit shared-blob consequences.
- **MEDIA-23**: Uploads support GIF animation or server-side image transformation.

## Out of Scope

| Feature | Reason |
|---------|--------|
| Uploading each file to LNbits and Blossom simultaneously | Creates duplicate storage and partial-success/canonical-URL ambiguity; one selected backend per file is simpler. |
| Sending merchant nsec to the browser | Violates existing key-custody boundary; BUD-11 signing stays server-side. |
| Server-side fetching of arbitrary pasted image URLs | Creates an SSRF surface and is unnecessary for file uploads; pasted URLs remain references. |
| Automatic remote deletion on image removal or editor cancel | Blossom blobs are content-addressed and may be shared; local form changes and remote deletion cannot be atomic. |

## Deferred Scope

- Blossom mirroring to other servers, kind-10063 server-list publication, automatic remote deletion/cleanup, GIF support, and server-side image transforms remain deferred.
- When a remote upload succeeds but the merchant cancels before saving the product/setting, disclose that the remote file may remain unreferenced; do not attempt automatic deletion in v1.1.

## Traceability

Proposed mapping from the v1.1 roadmap; owner approval is pending.

| Requirement | Phase | Status |
|-------------|-------|--------|
| MEDIA-01 | Phase 6 | Complete |
| MEDIA-02 | Phase 7 | Complete |
| MEDIA-03 | Phase 7 | Complete |
| MEDIA-04 | Phase 6 | Complete |
| MEDIA-05 | Phase 6 | Complete |
| MEDIA-06 | Phase 6 | Complete |
| MEDIA-07 | Phase 6 | Complete |
| MEDIA-08 | Phase 7 | Complete |
| MEDIA-09 | Phase 7 | Complete |
| MEDIA-10 | Phase 7 | Complete |
| MEDIA-11 | Phase 7 | Complete |
| MEDIA-12 | Phase 7 | Complete |
| MEDIA-13 | Phase 7 | Complete |
| MEDIA-14 | Phase 7 | Complete |
| MEDIA-15 | Phase 6 | Complete |
| MEDIA-16 | Phase 6 | Complete |
| MEDIA-17 | Phase 8 | Complete |
| MEDIA-18 | Phase 6 | Complete |
| MEDIA-19 | Phase 8 | Complete |

**Coverage:**

- v1 requirements: 19 total
- Mapped to phases: 19
- Unmapped: 0

---
*Requirements drafted: 2026-10-16*
*Last updated: 2026-10-17 — MEDIA-17/19 verified complete by the Phase 8 qualification audit (08-VERIFICATION.md)*
