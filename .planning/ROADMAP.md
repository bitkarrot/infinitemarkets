# Roadmap: infinitemarkets

## v1.0 — Core Commerce and Hardening

**✅ SHIPPED 2026-10-13** — full phase detail: [milestones/v1.0-ROADMAP.md](milestones/v1.0-ROADMAP.md); requirements archive: [milestones/v1.0-REQUIREMENTS.md](milestones/v1.0-REQUIREMENTS.md); audit: [v1.0-MILESTONE-AUDIT.md](v1.0-MILESTONE-AUDIT.md).

One authoritative commerce system in an LNbits extension: one inventory sold safely through LNbits-backed web checkout and Nostr/Gamma (NIP-17) private ordering — no duplicate invoices, no double allocation, relay delivery never mistaken for payment truth.

| Phase | Plans | Status | Completed |
|-------|-------|--------|-----------|
| 1. Conformance Profile (Contract Phase 0) | 3/3 | Complete | 2026-09-20 |
| 2. Release A — Safe Web Commerce | 4/4 | Complete | Delivered 2026-09-27; acceptance restored 2026-10-13 |
| 3. Release B — Gamma NIP-17 Orders | 4/4 | Complete | Delivered 2026-09-29; live UAT passed 2026-10-13 |
| 03.1. Buyer accounts (INSERTED) | 3/3 | Complete | 2026-10-07 |
| 4. Release C — Catalog Import and Export | 4/4 | Complete | 2026-10-09 |
| 5. Correctness, Recovery, and Security Hardening | 6/6 | Complete | Gates closed 2026-10-13 (v0.6.3) |

## v1.1 — Media uploads and Blossom support

**Goal:** Merchants can upload images for products, their Nostr profile, and Appearance settings, choosing LNbits-local storage by default or Blossom explicitly when configured.

Each upload uses exactly one backend. Blossom uploads target only the first server configured in Settings → Merchant, in its saved order; a remote failure is reported and local storage is available only as an explicit retry. Blossom authorization is signed on the server with the merchant's stored key. v1.1 supports signature-verified PNG/JPEG/WebP only; it does not mirror, publish kind 10063, remotely delete blobs, or add GIF/transformation support. If a remote upload is not saved with its product or setting, the editor discloses that the blob may remain unreferenced and does not delete it automatically.

**Release dependency:** PR #28 (`fix/og-image-redirects`) is open with all CI checks passed. It must be merged and verified before v1.1 release; its bounded, revalidated HTTPS redirects apply only to share-card image GETs. Authenticated upload PUTs must reject redirects.

### Phases

- [ ] **Phase 6: Secure Media Storage** - Merchants can store uploads locally or use a secure server-side Blossom upload service.
- [ ] **Phase 7: Shared Image Editors** - Merchants can manage product, profile, and Appearance images through reusable upload controls.
- [ ] **Phase 8: Media Release Qualification** - Merchants' uploads and share-card images meet the documented protocol and release safety contract.

### Phase Details

### Phase 6: Secure Media Storage

**Goal**: Merchants can upload bounded, verified images to durable LNbits-local storage or securely use Blossom through the server-side upload boundary.
**Depends on**: Phase 5 (v1.0 correctness, recovery, and security hardening; shipped)
**Requirements**: MEDIA-01, MEDIA-04, MEDIA-05, MEDIA-06, MEDIA-07, MEDIA-15, MEDIA-16, MEDIA-18
**Success Criteria** (what must be TRUE):

  1. A merchant can upload without configuring Blossom and LNbits-local storage is selected by default; local files are SHA-256 hashed, stored in a merchant-scoped namespace outside the extension package, served through the host image mount, and accepted through bounded multipart parsing that avoids unbounded memory buffering. Requests are limited to 16 files and 25 MB/file, with a 400 MB per-merchant local quota. Only signature-verified PNG/JPEG/WebP are accepted; SVG/GIF and invalid or oversized files are rejected.
  2. A Blossom image is exposed only after a server-side BUD-02 raw `PUT /upload` has been authorized with the merchant's stored key using a short-lived BUD-11 kind-24242 event, URL-safe unpadded encoding, matching SHA-256 `x` tag and `X-SHA-256` header, upload scope, and a target-scoped server tag; the returned descriptor is validated and no signing key is sent to browser code.
  3. A locally stored image used for Nostr profile picture/banner metadata resolves to a publicly reachable absolute HTTPS URL, while supported Appearance references can use a safe same-origin path.
  4. Uploads go through an authenticated route present in both technical-specification §5 and `harness/registry.py::HTTP_ROUTES`; Blossom requests use HTTPS, request-time public-egress checks, pinned-IP TLS, strict time/size bounds, and never follow upload redirects.

**Plans**: 4/4 plans executed

- [x] 06-04-PLAN.md

- [x] 06-01-PLAN.md — Local media storage adapter + bounded upload/unused API with contract registration
- [x] 06-02-PLAN.md — Blossom server-order preservation + BUD-02/BUD-11 server-side-signed upload client
- [x] 06-03-PLAN.md — Backend dispatch (local default / first-configured Blossom only) + absolute-URL profile emission

### Phase 7: Shared Image Editors

**Goal**: Merchants can manage every in-scope image field with consistent upload, editing, and persistence behavior without losing existing references or unrelated settings.
**Depends on**: Phase 6
**Requirements**: MEDIA-02, MEDIA-03, MEDIA-08, MEDIA-09, MEDIA-10, MEDIA-11, MEDIA-12, MEDIA-13, MEDIA-14
**Success Criteria** (what must be TRUE):

  1. The reusable upload control is available for the product gallery, Merchant Nostr profile picture and banner, and Appearance brand logo, hero background, footer logo, and custom share image.
  2. For each upload, the merchant can explicitly select local storage or Blossom; Blossom targets only the first configured server without reordering or dual-writing, and a failure gives a plain-language error with an explicit retry to local storage rather than automatic failover.
  3. A product gallery supports up to 20 images, thumbnails, a visible primary image, ordering, per-image removal, and explicit clear-all; those changes persist through the catalog API and appear in public pages and Nostr projections. The 20-image cap agrees across service, specification, UI, and tests.
  4. A merchant can replace or clear a single-image setting without changing other profile or theme fields, and can continue using pasted HTTPS URLs and supported migration-managed `/images/...` URLs.
  5. Upload progress and per-file errors are visible; a failed file does not discard other selected images, and cancelling before saving explains that an uploaded file may remain unreferenced. Remote Blossom blobs are not automatically deleted.

**Plans**: TBD
**UI hint**: yes

### Phase 8: Media Release Qualification

**Goal**: Merchants can rely on image uploads and generated share cards behaving safely across the supported local and Blossom paths before release.
**Depends on**: Phase 7; PR #28 must be merged and verified before release
**Requirements**: MEDIA-17, MEDIA-19
**Success Criteria** (what must be TRUE):

  1. A Blossom-hosted image that redirects over HTTPS is rendered in generated share cards after PR #28 is merged and verified using bounded, revalidated GET redirects; an upload PUT to a redirecting server fails without forwarding upload bytes or authorization.
  2. Automated tests against local storage and a fake Blossom server demonstrate successful uploads, BUD authorization/hash/descriptor validation, primary-server-only targeting, explicit local retry after remote failure, file size/type rejection, URL round-trips, and share-card redirect handling without writing to public Blossom servers.

**Plans**: TBD

### Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 6. Secure Media Storage | 4/4 | Not started | - |
| 7. Shared Image Editors | 0/TBD | Not started | - |
| 8. Media Release Qualification | 0/TBD | Not started | - |
