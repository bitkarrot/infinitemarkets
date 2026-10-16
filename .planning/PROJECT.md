# infinitemarkets

## What This Is

infinitemarkets is a standard Python LNbits extension for merchants who want to organize products into merchant-defined categories, publish Infinitemarkets/NIP-99 listings and curated collections, and accept Lightning orders without leaving inventory, payment, or relay reliability to a browser session. LNbits remains the wallet and settlement authority; the extension owns commerce state, inventory, protocol projection, and durable delivery. Development follows the corrected contract in `docs/technical-specification.md`, with `docs/architecture-proposal.md` as supporting rationale.

## Core Value

A merchant can sell one authoritative inventory safely through LNbits-backed web and Nostr flows without duplicate invoices, double allocation, or relay delivery being mistaken for payment truth.

## Current State

**v1.0 shipped 2026-10-13** — Core Commerce and Hardening. All 50 active
requirements closed; the reopened F1–F6 acceptance findings were repaired
with permanent regressions on both database profiles, independently
reviewed, and verified on a four-profile Linux CI matrix. The live
`plebeian.market` public-relay checkout was executed end-to-end on the
deployed v0.6.3 host (wrap → order → invoice → settlement → status wraps).
Residual items are documented limitations: upstream LNbits pageerrors on
the admin surface (operator-accepted) and the WR-01 retrospective-RED
chronology caveat. Archives: `milestones/v1.0-ROADMAP.md`,
`milestones/v1.0-REQUIREMENTS.md`, `v1.0-MILESTONE-AUDIT.md`.

**Current product release: v1.0.14 (2026-10-16).** Catalog usability,
product search/share previews, and shipping-region selection were polished.
The Blossom redirect fix is under review in PR #28; it is a prerequisite
for reliable share cards using Blossom-hosted product images.

## Current Milestone: v1.1 Media uploads and Blossom support

**Goal:** Let merchants upload product images through configured Blossom
media servers and see those images consistently across the catalog,
storefront, and generated share cards.

**Target features:**
- Product-editor image upload integrated with the merchant's configured
  Blossom media servers.
- Safe, usable upload/authentication behavior, including clear progress,
  failures, and the existing image-URL workflow; exact protocol and server
  selection policy are to be established by research and requirements.
- Preserve the PR #28 redirect fix so Blossom-hosted images render in
  generated Open Graph share cards.

## Requirements

### Delivered and Validated

The records below describe delivered scope verified at v1.0 ship.

- Phase 0 qualification (P0-01 through P0-14) has reproducible artifacts.
- Release A catalog publication and safe public web checkout are implemented and deployed.
- Release B Gamma NIP-17 order messaging with recipient-specific relay routing is implemented and deployed.
- Phase 03.1 buyer accounts provide email magic-link and Nostr identity sign-in.
- Release C catalog import/export is implemented and deployed: CSV/JSON products land as hidden drafts for merchant review and ordinary publication; no cutover or previous-order workflow.
- One canonical domain model and inventory/payment authority remain shared across web and Nostr adapters.
- Key custody, privacy, authentication, transaction, recovery, and deployment gates are enforced by the implementation contract.

### Future Milestone Goals

- Preserve S1–S4 policy, contract, observability and cleanup follow-ups.
- Optional feature expansion: external inventory/shipping
  integrations, reviews, subscriptions/preorders, NIP-37, buyer
  unlink/notification-preference expansion — each gated on its own plan.
- Track the conformance known-delta register (7 entries) — the
  detail-page event-id item-ref divergence is a Plebeian-side candidate
  for upstream reporting/fix.
- Merchant `lud16` on the public profile so Plebeian's native invoice UI
  can render alongside the type-2 wrap path.
- Upstream LNbits: the `g.wallet.id` null-deref and untrusted-cert
  ServiceWorker registration remain open upstream defects.

### Out of Scope

- WASM/browser-relay runtime — superseded by the Python architecture.
- Automated outgoing refunds — v1 records merchant-managed refund requests/attestations only.
- Hosted marketplace, fiat custody, card processing, escrow, or dispute arbitration — LNbits merchant commerce is the target.
- CockroachDB or multi-process SQLite — v1 supports single-process SQLite and qualified PostgreSQL.
- NIP-37 drafts, subscriptions/preorder purchasing, reviews, third-party mutable shipping, and distance pricing — explicitly deferred.
- General automated NIP-15 physical checkout from opaque addresses — machine-readable destination data is required.
- `nostrclient` or `nostrrelay` as a hard dependency — both require the same targeted routing and positive-ACK qualification first.

## Context

- The architecture pivoted from a WASM proposal to a standard Python LNbits extension because durable tasks, direct relay connections, real migrations, and transactional inventory are required while the merchant UI is closed.
- A standalone GPT-6 Astra Max audit reviewed the contract against pinned LNbits, Nostr NIPs, Infinitemarkets, `nostrmarket`, `nostrclient`, and release-source SDK evidence. The audit found the architecture viable but required 13 contract corrections before Phase 0.
- The qualification-era corrections were incorporated into `docs/technical-specification.md`. Its current §13 supersedes the old migration-liability design: import only products, review hidden drafts, publish through Catalog. Invoice and stock safety within Infinite Markets remains unchanged.
- `nostr-sdk==0.44.8` is only the host-resolved Phase 0 candidate. Exact wheel hashes, native provenance, and executable security/FFI/ACK behavior must be recorded before implementation.
- Deterministic local relays are authoritative tests. `wss://nostr.net` is allowed only as an optional ephemeral, non-sensitive public-relay smoke target.
- Relay fact (owner, 2026-09-22): `relay.nostr.band` is defunct; `relay.nostr.net` replaces it in the starter default relay set.

## Constraints

- **Normative contract**: `docs/technical-specification.md` overrides rationale and planning summaries.
- **Host baseline**: LNbits `v1.6.2-rc1` at commit `e336fe1`; other revisions need explicit qualification.
- **Protocol pins**: Infinitemarkets `5dc79c5` and Nostr NIPs `a2494f4`; changes require a recorded specification decision.
- **Runtime identity**: package, routes, hooks, environment variables, AAD, and payment correlation use `infinitemarkets` before any migration/publication.
- **Payments**: LNbits incoming payment records are authoritative; receipts and buyer amounts never settle an order.
- **Database**: single-process SQLite and PostgreSQL only; domain transactions must not use LNbits auto-committing helpers.
- **Security**: no production implementation begins until the relevant Phase 0 evidence passes; Release B additionally requires deployed egress controls.
- **Delivery**: relay/WebSocket send success is never publication evidence; positive relay OK results are required.
- **Repository**: runtime code is built here, not in the proposal-site repository; commits remain local unless the user explicitly asks to push.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Standard Python LNbits extension | Durable background work, direct relay transport, migrations, and transactions are required | Implemented and verified |
| Runtime identifier is `infinitemarkets` | Freeze package/API/payment/AAD identity before persisted data exists | Implemented and verified |
| Corrected technical specification is authoritative | Prevent rationale or plan drift from inventing behavior | Implemented and verified |
| Phase 0 precedes runtime implementation | Plausible host/SDK assumptions need executable evidence | Implemented and verified |
| Direct qualified `nostr-sdk` transport is baseline | NIP-17 requires per-recipient targets and positive ACK evidence | Implemented and verified |
| LNbits is settlement authority | Avoid a second payment truth source | Implemented and verified |
| Release sequence is A web, B Gamma, C catalog portability | Later imports must not block safe web/Gamma checkout | Implemented and verified |
| Catalog imports are merchant-approved drafts, not a transfer of inventory authority | Old orders are ignored; merchants handle overlap with another store before publishing | Implemented and verified |
| SMTP failures are boolean/unclassified in v1 | The pinned host helper erases SMTP failure categories | Implemented and verified |
| External relay smoke uses `wss://nostr.net` only with ephemeral synthetic events | Useful interoperability signal without becoming a production dependency | Superseded in daily operations by the authenticated live relay catalog check |
| Public checkout uses bounded Editorial/Guided/Compact presets with responsive fallback | Preserve merchant choice without changing checkout semantics or mobile safety | Implemented and verified |
| Merchant orders use split list/detail navigation with embedded chronology | Optimize daily triage while keeping payment, inventory, fulfillment, and audit understandable | Implemented and verified |
| Storefront themes use preset → brand basics → guarded advanced tiers | Allow merchant identity without arbitrary CSS or admin/checkout drift | Implemented and verified |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition:**
1. Move verified requirements to Validated with the phase reference.
2. Move invalidated requirements to Out of Scope with the reason.
3. Add newly discovered requirements and decisions.
4. Recheck that the project description and core value remain accurate.

**After each milestone:**
1. Review every section against shipped behavior and verification evidence.
2. Recheck the core value and scope boundaries.
3. Update context, constraints, and decision outcomes.

---
*Last updated: 2026-10-16 — v1.1 media-upload planning started*
