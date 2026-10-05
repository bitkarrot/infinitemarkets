# Requirements: infinitemarkets

**Defined:** 2026-09-20
**Core Value:** A merchant can sell one authoritative inventory safely through LNbits-backed web and Nostr flows without duplicate invoices, double allocation, or relay delivery being mistaken for payment truth.

## User Stories

- As an operator, I can prove the exact LNbits/SDK/deployment profile before merchants use real funds.
- As a merchant, I can manage one protected catalog and wallet-backed inventory and see whether each publication was acknowledged.
- As a web buyer, I can receive a server-priced Lightning invoice and privately follow order state without exposing an order token in URLs or logs.
- As a Nostr buyer, I can exchange Gamma order messages through my declared inbox relays without public fallback routing.
- As a migrating merchant, I can preview and cut over a legacy catalog without allocating stock already promised by an old payable invoice.
- As an auditor, I can reproduce state, transaction, crypto, relay, notification, and release claims from recorded evidence.

## v1 Requirements

### Phase 0 Qualification

- [x] **QUAL-01**: Operator can reproduce the approved host/SDK dependency set on every supported platform from recorded lockfile paths, wheel hashes, release-source revisions, and native dependency provenance without a silent host downgrade.
- [x] **QUAL-02**: Operator can demonstrate that the tested SDK binary rejects repeated invalid/known-ID events and oversized NIP-44 inputs before trusted processing or unbounded allocation while relay AUTH challenge work remains bounded when signing is paused.
- [x] **QUAL-03**: Implementer can create/query an LNbits invoice with exact `infinitemarkets` extension/external-id/wallet metadata and register/cancel only extension-owned listener/task handles.
- [x] **QUAL-04**: Implementer can distinguish positive relay OK, negative relay OK, and timeout from deterministic local relays without publishing to an unlisted target.
- [x] **QUAL-05**: Implementer can build recipient and sender copies of a fixed kind-16 rumor, preserve rumor identity across retry, and reject every tampered outer/seal/rumor chain without plaintext logging.
- [x] **QUAL-06**: Implementer can prove last-unit reservation atomicity, rollback, FK enforcement, and stale fencing rejection on single-process SQLite and the claimed PostgreSQL topology without an auto-committing helper splitting the transaction.
- [x] **QUAL-07**: Implementer can cancel during every invoice-creation outcome and restart with one stock release, preserved payment correlation, no delivered cancelled-order invoice, no automatic reopen, and no duplicate invoice.
- [x] **QUAL-08**: Implementer can restart at every order/inbox/outbox checkpoint and resume or terminate work explicitly while retrying only relay targets without positive ACK evidence.
- [x] **QUAL-09**: Implementer can represent multiple merchant email recipients and a delayed opted-in customer link beyond idempotency retention with protected token expiry/revocation and no plaintext durable token.
- [x] **QUAL-10**: Implementer can show that only host SMTP `True` enters sent, while `False`/exception/rejection stubs use bounded unclassified retries and logs expose neither recipient PII nor bearer links.
- [x] **QUAL-11**: Operator can resolve a valid local kind-30402 naddr and reject malformed, wrong-kind, and foreign references without fetching embedded relay hints.
- [x] **QUAL-12**: Operator can reject ID-only/cross-origin admin mutations and secret audit capture while approved bearer/CSRF paths, startup readiness, cancellation cleanup, and request redaction pass on the qualified host.
- [x] **QUAL-13**: Implementer can prove Decimal units, provider provenance, five-minute freshness, per-component ceiling, and rejection-before-reservation for stale/invalid FX quotes.
- [x] **QUAL-14**: Implementer can validate that every normative transition, field, route, event fixture, release gate, and `infinitemarkets` identifier closes without an undeclared dependency.

### Release A — Catalog and Web Commerce

- [x] **MERC-01**: Merchant can create/import a protected Nostr identity, bind an owned incoming LNbits wallet, configure relays/notifications, and activate/deactivate without exposing raw keys or credentials.
- [x] **CAT-01**: Merchant can create and update canonical catalogs, simple/variable/variation products, collections, images/specifications, shipping options, stock, visibility, and local drafts under the normative validation rules.
- [x] **CAT-02**: Merchant can soft-delete catalog entities with ordered reference removal, durable tombstones, stable protocol addresses, and retained historical order integrity.
- [x] **PUB-01**: Merchant can publish deterministic Gamma/NIP-99 `0`, `30402`, `30405`, `30406`, `31989`, and `31990` events through a durable, ordered outbox with positive per-relay ACK evidence.
- [x] **PUB-02**: Merchant can inspect relay health, pending/partial/failed publication state, and retry/supersession outcomes without reading secret-bearing logs.
- [x] **WEB-01**: Buyer can open a local NIP-89 naddr product page and browse active public products, collections, shipping, price, and availability without seeing merchant internals.
- [x] **WEB-02**: Buyer can submit idempotent web checkout with server-recalculated items/shipping/FX and receive a high-entropy fragment/header status capability that never appears in a request path/query.
- [x] **PAY-01**: Buyer can receive exactly one correlated LNbits invoice after stock reservation; unknown creation is reconciled without blind reissue.
- [x] **PAY-02**: Settled, expired, cancelled, late, mismatched, and manually accepted/refund-attested payments follow the normative state/exception machine without treating buyer claims or receipts as settlement.
- [x] **INV-01**: Concurrent buyers cannot allocate more finite stock than exists; held reservations expire/release once and settlement consumes stock once.
- [x] **ORD-01**: Merchant can inspect orders/audit history and apply legal processing, cancellation, shipping, exception, fulfillment, and public-token rotation actions with owner-scoped authorization.
- [x] **NOTF-01**: Merchant and opted-in web buyer can receive per-recipient transactional emails through host SMTP with explicit suppressed/failed state, bounded retry, protected token rendering, and opt-out.
- [x] **SEC-01**: Release A enforces key/PII encryption, retention, HMAC lookup scopes, CSRF/origin/auth boundaries, rate/input limits, log redaction, unsupported-topology refusal, and cancellation-safe lifecycle behavior.
- [x] **UI-01**: Merchant can choose Editorial, Guided, or Compact public layout presets while responsive safety applies a compact mobile fallback and checkout fields, totals, validation, payment states, and security copy remain invariant.
- [x] **UI-02**: Merchant can triage and process orders through a responsive split list/detail workspace with search, state filters, exception prominence, legal contextual actions, and embedded payment/inventory/fulfillment chronology.
- [x] **UI-03**: Merchant can customize public appearance through Warm Market, Clean Minimal, or High Contrast presets, optional Brand Basics, and opt-in guarded Advanced Tokens while WCAG save gates and public/admin separation remain enforced.

### Release B — Gamma NIP-17 Orders

- [ ] **GAM-01**: Merchant can publish and validate a 1–3 relay kind-10050 inbox profile before claiming Gamma order reachability.
- [ ] **GAM-02**: Buyer can submit a valid NIP-17 kind-16 type-1 order that enters the same canonical pricing, shipping, inventory, invoice, and settlement services as web checkout.
- [ ] **GAM-03**: Buyer and merchant can exchange kind-16 payment/status/shipping and kind-17 receipt messages with stable rumor identity, independent sender/recipient copies, and settlement-independent receipt semantics.
- [ ] **GAM-04**: Durable inbox processing verifies and deduplicates outer/seal/rumor identity, preserves encrypted history, resumes completed-session cursors, and routes each copy only to that party's declared relays.
- [ ] **GAM-05**: Release B passes deployed relay SSRF/egress, recipient-gated relay, NIP-42, overload, and independent external Gamma-client conformance gates.

### Buyer Accounts

- [ ] **ACC-01**: Buyer can hold a unified per-merchant account (`buyer_accounts`) keyed by a verified email and/or Nostr pubkey — each identity nullable, unique-when-present, merchant-scoped HMAC + AEAD — with sessions minted against the account and pre-existing NIP-07 sessions preserved through the schema migration.
- [ ] **ACC-02**: Buyer's order history is the union of pubkey-hash and email-hash bindings: `orders.buyer_email_hash` is written at web and gamma checkout when an email is present, backfilled for existing orders, binds via verified session identity (never the unverified form email), and claims attach whichever identities the account offers with identical no-oracle outcomes.
- [ ] **ACC-03**: Buyer without a Nostr signer can sign in via email magic link — no-oracle request, single-use ~15-minute hash-only token delivered URL-fragment-only through the durable email queue with honest unconfigured degradation, dual per-email/per-IP rate limits, and the identical HttpOnly/Secure/SameSite=Strict session cookie contract.
- [ ] **ACC-04**: Signed-in buyer can link the other identity by proving it (email verify link or NIP-07 link challenge); a verified identity already owned by another account triggers an atomic union merge — identities move, sessions and tokens re-point, the loser retires — while unrepresentable unions reject honestly without partial state.
- [ ] **ACC-05**: Buyer surfaces offer both sign-in methods with honest per-method availability on any shop configuration: two-method modal, email-aware account chip, verified-email/link cards and kind-0 gating on the profile page, and a one-time 'found past orders' note on the orders page.

### Release C — NIP-15 and Migration

- [x] ~~**LEG-01**: Merchant can publish literal NIP-15 `30017`/`30018` projections~~ — **Dropped** (Phase-4 scope amendment: import-only, no live legacy interop).
- [x] ~~**LEG-02**: Legacy buyer literal NIP-04 type 0/1/2 message exchange~~ — **Dropped** (Phase-4 scope amendment).
- [ ] **LEG-03**: Merchant can preview, validate, dry-run, execute, and audit JSON/Nostr legacy catalog import without arbitrary path/URL/database access or private-key leakage. Import sources include nostrmarket JSON/Nostr events AND e-commerce CSV exports (Shopify first; column-mapping extensible to WooCommerce) — file upload only, never URL fetch.
- [ ] **LEG-04**: Merchant can freeze old order intake and reconcile, wait, or partition every still-payable `legacy_liability_qty` before imported stock is sellable, independent of key strategy.
- [ ] **LEG-05**: Release C passes a scarce-stock cutover rehearsal in which an old unpaid invoice and a new catalog can never allocate the same unit twice. *(NIP-15 fixture criterion removed — LEG-01/02 dropped in the Phase-4 scope amendment.)*

## v2 Requirements

### Deferred Protocol and Commerce

- **V2-01**: Merchant can synchronize drafts through complete NIP-37/private-relay semantics.
- **V2-02**: Merchant can offer subscription or preorder purchasing with explicit billing/backorder policy.
- **V2-03**: Merchant can use independently mutable third-party shipping providers after an authoritative quote/security design.
- **V2-04**: Buyer can publish/retrieve product reviews after a moderation/trust design.
- **V2-05**: Deployment can use an externally qualified signer or NIP-46 custody backend.

## Out of Scope

| Feature | Reason |
|---------|--------|
| WASM/browser-relay commerce authority | Cannot provide the required durable task and transaction lifecycle |
| Automated outgoing refunds | Would add spend authority; v1 uses merchant-managed wallet UI flow |
| Hosted marketplace, fiat custody, cards, escrow | Outside the LNbits merchant-extension goal |
| CockroachDB or multi-process SQLite | Not qualified v1 topologies |
| General opaque-address NIP-15 physical auto-checkout | Destination coverage cannot be machine validated |
| Public relay as production default | Availability/privacy policy must remain operator- and recipient-specific |
| Hard dependency on current `nostrclient` or uninspected `nostrrelay` | Neither currently satisfies the qualified transport contract |

## Acceptance Criteria

- Every v1 requirement maps to exactly one roadmap phase and to normative contract evidence.
- Phase 1 passes P0-01 through P0-14 before any production extension runtime implementation begins.
- Each later phase reruns its applicable Phase 0 domain, host, security, and failure assertions through the real implementation.
- Release labels are claimed only when their release-specific interoperability/deployment gates pass.
- Verification artifacts identify exact tested revisions, binaries, platform, topology, and external systems.

## Definition of Done

A requirement is complete only when implementation (or Phase 0 probe/model), automated tests, required manual/external conformance, security review, and a local commit all exist. A phase is complete only when its mapped requirements pass verification and no HIGH-severity security gate remains open.

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| QUAL-01 | Phase 1 | Complete |
| QUAL-02 | Phase 1 | Complete |
| QUAL-03 | Phase 1 | Complete |
| QUAL-04 | Phase 1 | Complete |
| QUAL-05 | Phase 1 | Complete |
| QUAL-06 | Phase 1 | Complete |
| QUAL-07 | Phase 1 | Complete |
| QUAL-08 | Phase 1 | Complete |
| QUAL-09 | Phase 1 | Complete |
| QUAL-10 | Phase 1 | Complete |
| QUAL-11 | Phase 1 | Complete |
| QUAL-12 | Phase 1 | Complete |
| QUAL-13 | Phase 1 | Complete |
| QUAL-14 | Phase 1 | Complete |
| MERC-01 | Phase 2 | Complete |
| CAT-01 | Phase 2 | Complete |
| CAT-02 | Phase 2 | Complete |
| PUB-01 | Phase 2 | Complete |
| PUB-02 | Phase 2 | Complete |
| WEB-01 | Phase 2 | Complete |
| WEB-02 | Phase 2 | Complete |
| PAY-01 | Phase 2 | Complete |
| PAY-02 | Phase 2 | Complete |
| INV-01 | Phase 2 | Complete |
| ORD-01 | Phase 2 | Complete |
| NOTF-01 | Phase 2 | Complete |
| SEC-01 | Phase 2 | Complete |
| UI-01 | Phase 2 | Complete |
| UI-02 | Phase 2 | Complete |
| UI-03 | Phase 2 | Complete |
| GAM-01 | Phase 3 | Pending |
| GAM-02 | Phase 3 | Pending |
| GAM-03 | Phase 3 | Pending |
| GAM-04 | Phase 3 | Pending |
| GAM-05 | Phase 3 | Pending |
| ACC-01 | Phase 03.1 | Pending |
| ACC-02 | Phase 03.1 | Pending |
| ACC-03 | Phase 03.1 | Pending |
| ACC-04 | Phase 03.1 | Pending |
| ACC-05 | Phase 03.1 | Pending |
| LEG-01 | Phase 4 | Dropped — Phase-4 scope amendment |
| LEG-02 | Phase 4 | Dropped — Phase-4 scope amendment |
| LEG-03 | Phase 4 | Pending |
| LEG-04 | Phase 4 | Pending |
| LEG-05 | Phase 4 | Pending |

**Coverage:**

- v1 requirements: 45 total
- Mapped to phases: 45
- Unmapped: 0

---
*Requirements defined: 2026-09-20*
*Last updated: 2026-10-05 — ACC-01..05 minted for Phase 03.1 Buyer Accounts*
