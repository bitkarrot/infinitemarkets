# Phase 04 — Catalog Import and Export Verification

**Date:** 2026-10-09
**Status:** Complete — catalog-only scope verified and deployed through `main`.
**Current scope:** file upload/preview/import into hidden drafts, merchant
review in Catalog, ordinary publication, product CSV export, and optional
owned-media relink. No cutover, old-order audit, attestation, source freeze, or
physical-count activation gate is part of the current workflow.

The earlier cutover experiment was removed. Any document or test reference to
liability reconciliation, frozen intake, attestation, or stock-count release is
historical only, not current acceptance criteria.

## Verified behavior

- Shopify CSV, native CSV, nostrmarket JSON, and signed NIP-15 event files
  preview and import as hidden drafts through merchant-owned API actions.
- Imports preserve product titles, descriptions, prices, source currency,
  bounded stock values, size options, image references, and variable-product
  relationships without publishing relay events.
- Merchants review/edit imported drafts and publish them through normal
  Catalog actions; publishing a variable parent publishes its imported draft
  options with it.
- Native product CSV export is merchant-owned, spreadsheet-safe, and
  reimportable as hidden drafts; it contains no keys, orders, buyer PII, or
  reservation internals.
- Optional media relink uses uploaded files and manifests; URL-to-file hashes
  and file types are verified before product image references change.
- Searchable shipping destinations, including the 27-country European Union
  preset, work independently of catalog import; Shopify shipping rates/zones
  are not imported.
- Merchant Nostr Profile saves and publishes `name`, `about`, `picture`,
  `banner`, `nip05`, and `lud16`; generated/imported keys remain encrypted and
  the owner can explicitly reveal the `nsec`.
- Publications exposes a read-only live relay check that verifies signed
  catalog events and tombstones, reports missing/divergent/stale copies, and
  can reissue bounded fresh kind-5 deletion requests for locally deleted
  addresses.
- Messages resolve verified kind-0 counterparty names, NIP-05 identifiers,
  avatars, and `nostr.at` links with an `npub` fallback.
- Email queue history exposes redacted owner-only previews and clears only
  terminal `sent|suppressed|failed` rows.

## Verification commands

- `make verify-runtime` — **428 passed, 3 skipped, 233 deselected** on
  2026-10-09.
- `make lint` — passed.
- Focused relay-check/tombstone and admin UI tests passed.
- Deployed source matched the reviewed extension files on the live host.
- Git `main` was pushed through `d0e2c22` before release packaging.

## Honest limitations

- Relay ACK proves historical delivery acceptance only; it does not prove a
  relay currently serves an event. The live relay check is required for that
  observation.
- Kind-5 deletion is a request, not a relay command. Relays or clients such
  as Plebeian Market may retain or ignore stale catalog copies until they
  implement deletion handling or receive a newer hidden/out-of-stock revision.
- Shopify exports do not provide shipping rates/zones or a product-to-shipping
  assignment; merchants configure those in Infinite Markets after import.
- Public marketplace filters vary. In particular, a regular product without a
  `stock` tag can be treated as out of stock even when it appears in the
  marketplace dashboard.
