# infinitemarkets

## What This Is

infinitemarkets is a standard Python LNbits extension for merchants who want to organize products into merchant-defined categories, publish Infinitemarkets/NIP-99 listings and curated collections, and accept Lightning orders without leaving inventory, payment, or relay reliability to a browser session. LNbits remains the wallet and settlement authority; the extension owns commerce state, inventory, protocol projection, and durable delivery. Development follows the corrected contract in `docs/technical-specification.md`, with `docs/architecture-proposal.md` as supporting rationale.

## Core Value

A merchant can sell one authoritative inventory safely through LNbits-backed web and Nostr flows without duplicate invoices, double allocation, or relay delivery being mistaken for payment truth.

## Requirements

### Validated

(None yet — Phase 0 must qualify the host, SDK, schema, and protocol contracts before runtime implementation.)

### Active

- [ ] Pass every P0-01 through P0-14 conformance criterion with reproducible artifacts.
- [ ] Deliver Release A catalog publication and safe public web checkout on LNbits.
- [ ] Deliver Release B Gamma NIP-17 order messaging with recipient-specific relay routing.
- [ ] Deliver Release C literal NIP-15/NIP-04 compatibility and inventory-safe migration.
- [ ] Preserve one canonical domain model and one inventory/payment authority across all adapters.
- [ ] Enforce key custody, privacy, authentication, transaction, recovery, and deployment gates from the normative specification.

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
- Those corrections are incorporated into `docs/technical-specification.md`: SDK qualification, cancellation/invoice races, partial outbox retries, SMTP/token persistence, NIP-89 routing, NIP-15 DTOs, migration liabilities, worker storage, host boundaries, FX conversion, release scoping, and the plural runtime name.
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
| Standard Python LNbits extension | Durable background work, direct relay transport, migrations, and transactions are required | Pending validation |
| Runtime identifier is `infinitemarkets` | Freeze package/API/payment/AAD identity before persisted data exists | Pending validation |
| Corrected technical specification is authoritative | Prevent rationale or plan drift from inventing behavior | Pending validation |
| Phase 0 precedes runtime implementation | Plausible host/SDK assumptions need executable evidence | Pending validation |
| Direct qualified `nostr-sdk` transport is baseline | NIP-17 requires per-recipient targets and positive ACK evidence | Pending validation |
| LNbits is settlement authority | Avoid a second payment truth source | Pending validation |
| Release sequence is A web, B Gamma, C legacy interop | Later protocol compatibility must not block the safe first vertical slice | Pending validation |
| Migration accounts for payable inventory liabilities under every key strategy | A new pubkey does not partition physical stock | Pending validation |
| SMTP failures are boolean/unclassified in v1 | The pinned host helper erases SMTP failure categories | Pending validation |
| External relay smoke uses `wss://nostr.net` only with ephemeral synthetic events | Useful interoperability signal without becoming a production dependency | Pending validation |
| Public checkout uses bounded Editorial/Guided/Compact presets with responsive fallback | Preserve merchant choice without changing checkout semantics or mobile safety | Pending validation |
| Merchant orders use split list/detail navigation with embedded chronology | Optimize daily triage while keeping payment, inventory, fulfillment, and audit understandable | Pending validation |
| Storefront themes use preset → brand basics → guarded advanced tiers | Allow merchant identity without arbitrary CSS or admin/checkout drift | Pending validation |

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
*Last updated: 2026-09-20 after UI sketch validation*
