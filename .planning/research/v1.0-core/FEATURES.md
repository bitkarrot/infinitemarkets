# Feature Research

## Evidence Basis

Features are taken from the corrected contract and completed audit. They are grouped by the staged A/B/C release profile rather than re-researched.

## Table Stakes

### Phase 0 Conformance

- Reproducible host/SDK pins and artifact provenance.
- Executable SDK security, FFI, crypto, and relay ACK tests.
- Host invoice/listener/task/SMTP/auth/audit/FX contract probes.
- SQLite/PostgreSQL transaction, FK, concurrency, and fencing probes.
- Executable order/inbox/outbox/email state and crash-recovery models.
- Frozen runtime identity, routes, event fixtures, release claims, and migration procedure.

### Release A — Web Commerce

- Protected merchant identity and LNbits wallet ownership.
- Canonical catalogs, products, variations, collections, shipping, and inventory.
- Gamma/NIP-99 public events, NIP-89 handler, durable outbox, and relay health.
- Public product pages and token-gated order polling.
- Server-priced checkout, reservation, invoice saga, settlement, late-payment handling, and fulfillment state.
- Best-effort per-recipient email with protected magic links and bounded retries.
- Authentication, CSRF/origin enforcement, rate limits, privacy, logging, and retention controls.

### Release B — Gamma Orders

- Merchant/buyer kind-10050 discovery and publication.
- NIP-17 sender and recipient copies with party-specific routing.
- Kind-16 order/payment/status/shipping and kind-17 receipt behavior.
- Durable encrypted inbox and order-message history.
- Deployed relay egress controls and independent Gamma client interoperability.

### Release C — Catalog Portability

- File-only import is not legacy NIP-04 ordering or a transfer of invoice state.
- File-only CSV/JSON catalog preview and import as hidden drafts.
- Merchant review/edit and explicit publication through Catalog, including imported options.
- Product CSV export and optional merchant-supplied media relink; no old-order, freeze, or cutover workflow.

## Differentiators

- One canonical inventory/payment model projected to modern Gamma and legacy NIP-15.
- Crash-safe invoice creation that never blindly creates a second invoice.
- Positive relay ACK evidence and partial-copy recovery instead of send-success claims.
- NIP-17 sender-copy recovery with stable rumor identity.
- Privacy-preserving encrypted fields and keyed lookup indexes.
- Explicit, testable release claims rather than broad compatibility marketing.

## Anti-Features

- Automated outgoing refunds or spend credentials.
- Relay state as inventory/payment authority.
- Browser-only background processing.
- Arbitrary server-side image or user-URL fetching.
- General NIP-15 physical checkout from opaque addresses.
- New-key migration presented as inventory isolation.
- Exactly-once SMTP delivery claims.
- Production defaults tied to a public external relay.
