# Roadmap: infinitemarkets

## Overview

The project advances through four gated vertical stages. GSD Phase 1 executes the normative contract's Phase 0 conformance profile without production runtime code. Phase 2 delivers safe Gamma/NIP-99 catalog publication and LNbits-backed web commerce. Phase 3 adds private Gamma NIP-17 orders after the commerce core is stable. Phase 4 adds file-based catalog import/export into hidden drafts for merchant review and ordinary publication; no old-order reconciliation or cutover is provided.

## Phases

**Phase Numbering:**

- GSD integer phases are execution stages.
- GSD Phase 1 corresponds to the specification's named "Phase 0" qualification gate.
- Decimal phases are reserved for urgent inserted work.

- [x] **Phase 1: Conformance Profile (Contract Phase 0)** - Prove host, SDK, schema, state, security, and protocol assumptions before runtime implementation. (completed 2026-09-20)
- [x] **Phase 2: Release A — Safe Web Commerce** - Ship catalog publication and LNbits-backed public checkout as the first production vertical slice. (completed 2026-09-27)
- [x] **Phase 3: Release B — Gamma NIP-17 Orders** - Add encrypted recipient-specific Gamma order messaging and external-client conformance. (completed 2026-09-29)
- [x] **Phase 4: Release C — Catalog Import and Export** - Import file-based catalogs as hidden drafts for merchant review and publication; no extension-managed cutover. (completed 2026-10-09)

## Phase Details

### Phase 1: Conformance Profile (Contract Phase 0)

**Goal:** Produce reproducible evidence that the corrected contract can be implemented safely on the selected host/SDK/platform/topology profile.
**Mode:** mvp
**Depends on:** Nothing
**Requirements:** QUAL-01, QUAL-02, QUAL-03, QUAL-04, QUAL-05, QUAL-06, QUAL-07, QUAL-08, QUAL-09, QUAL-10, QUAL-11, QUAL-12, QUAL-13, QUAL-14
**Success Criteria** (what must be TRUE):

1. Exact host/SDK artifacts and native provenance are reproducible, and executable SDK security/FFI/crypto/ACK tests pass on every claimed platform.
2. Host invoice/listener/task/SMTP/auth/audit/FX probes pass with documented lifecycle and failure semantics.
3. SQLite and PostgreSQL executable models prove transaction atomicity, FK behavior, fencing, last-unit concurrency, cancellation/invoice recovery, and restart closure.
4. Protocol fixtures prove NIP-89 routing, NIP-17 wrap validation/routing, literal NIP-15 DTOs, and release-scoped compatibility restrictions.
5. P0-01 through P0-14 have recorded evidence and no undeclared state, field, route, identifier, or release dependency remains.

**Plans:** 3/3 plans complete

Plans:

- [x] 01-01-PLAN.md
- [x] 01-02-PLAN.md
- [x] 01-03-PLAN.md
- [x] 01-01: Freeze pins, artifact provenance, and host/SDK contract harness
- [x] 01-02: Build executable state, transaction, fencing, crash, and notification models
- [x] 01-03: Build protocol, relay, auth/privacy, FX, and contract-closure fixtures

### Phase 2: Release A — Safe Web Commerce

**Goal:** A merchant can publish a protected Gamma/NIP-99 catalog and complete a safe LNbits-backed web order end to end.
**Mode:** mvp
**Depends on:** Phase 1
**Requirements:** MERC-01, CAT-01, CAT-02, PUB-01, PUB-02, WEB-01, WEB-02, PAY-01, PAY-02, INV-01, ORD-01, NOTF-01, SEC-01, UI-01, UI-02, UI-03
**Success Criteria** (what must be TRUE):

1. Merchant can configure a protected identity/wallet, manage canonical catalog/inventory/shipping, select a bounded public layout/theme tier, and publish valid public events with visible per-relay outcomes.
2. Buyer can open the local NIP-89 handler, use an adaptive responsive checkout with a complete visible total, receive one correlated invoice, and poll private status without token leakage.
3. Concurrent, cancelled, expired, late, duplicated, and mismatched payment paths preserve stock and state invariants with no blind invoice reissue.
4. Merchant can triage and manage legal order/fulfillment/exception actions in a responsive split list/detail workspace with embedded chronology and per-recipient notifications.
5. Release-A security, accessibility/contrast, public/admin theme separation, retention, logging, unsupported-topology, failure-drill, and applicable Phase 0 assertions pass through the real implementation.

**Plans:** 4/4 plans complete
**UI prerequisite:** Before Phase 2 plan execution, generate and approve the Phase 2 UI contract using `.devin/skills/sketch-findings-infinitemarkets/` and the normative technical specification. *(Satisfied: `02-UI-SPEC.md` approved.)*

Plans:

- [x] 02-01-PLAN.md
- [x] 02-02-PLAN.md
- [x] 02-03-PLAN.md
- [x] 02-04-PLAN.md

- [x] 02-01: Extension skeleton, key custody, database/migrations, merchant and catalog domain
- [x] 02-02: Relay transport + durable outbox publication, NIP-89 handler, public storefront, theme backend
- [x] 02-03: Checkout, reservation + invoice saga, settlement/reconciliation, order admin API, email
- [x] 02-04: Buyer checkout/status UI and merchant admin surfaces (orders, catalog, publications, settings, appearance)

**Release gate:** Complete. [Current implementation CI run 36352552899](https://github.com/bitkarrot/infinitemarkets/actions/runs/36352552899) passed lint and all four required Linux x86_64/ARM64 × SQLite/PostgreSQL profiles on `021c402`; current local Chromium passed 19/19, human UAT passed 3/3, Nyquist coverage is 16/16 requirements, and the ASVS-1 register is verified with 26/26 threats closed. Port 5099 serves the fresh quote-capable demo; the old disposable database files were preserved but are not mounted. See `02-VERIFICATION.md`, `02-VALIDATION.md`, `02-SECURITY.md`, `02-UI-REVIEW.md` and `02-UAT.md`.

*Plan count revised 3→4 during plan-checker revision: order-backend and UI layers split to keep each executor under the context budget.*

### Phase 3: Release B — Gamma NIP-17 Orders

**Goal:** A Nostr buyer can place and follow a Gamma order through declared inbox relays against the same canonical commerce authority.
**Mode:** mvp
**Depends on:** Phase 2
**Requirements:** GAM-01, GAM-02, GAM-03, GAM-04, GAM-05
**Success Criteria** (what must be TRUE):

1. Merchant activation publishes a valid kind-10050 profile only after configured inbox reachability is acknowledged.
2. Valid kind-16 orders enter the same pricing, inventory, invoice, settlement, and exception services as web checkout.
3. Payment, status, shipping, receipt, and general-message flows use verified NIP-17 chains, stable rumor identity, independent party copies, and declared-relay-only routing.
4. Inbox/outbox cursors, deduplication, overload handling, retry, sender recovery, and encrypted retention recover across crashes without duplicate domain commands.
5. Deployed egress controls, recipient-gated relay behavior, NIP-42, and an independent Gamma client conformance run pass before the Release-B claim.

**Plans:** 4/4 plans complete

**Carried from Phase 2 UAT (2026-09-27):** Nostr buyers retrieve order status and history from their NIP-17 message history (order keyed by buyer pubkey + order id); an optional NIP-07 "Sign in with Nostr" for the web storefront; and a merchant `web_checkout_enabled` setting so a shop can run Nostr-only once Gamma ordering exists. Web buyers keep per-order private links — no buyer accounts.

*Plan count revised 3→4 during plan-checker revision: buyer/merchant surfaces (sign-in, storefront modes, Messages) split from the conformance gate to keep each executor under the context budget — matching the research's recommended 4-part structure.*

Plans:
**Wave 1**

- [x] 03-01: m006 schema, keystore NIP-17, kind-10050 activation, inbox transport/cursors, NIP-42, egress

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 03-02: Rumor⇄domain adapters, dual-copy outbox, inbound matrix, intake abuse and recovery

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 03-03: NIP-07 sign-in/sessions/claiming, attributed checkout, storefront modes, Messages/Rejected surfaces

**Wave 4** *(blocked on Wave 3 completion)*

- [x] 03-04: nostrrelay gated-inbox env, security drills, Plebeian conformance matrix, §21 spec amendment

### Phase 03.1: Buyer accounts — email magic-link sign-in and Nostr identity linking (INSERTED)

**Goal:** Buyers without a Nostr signer register/sign in via email magic link while Nostr buyers keep NIP-07 sign-in — both are identities on a unified per-shop account that sees order history (new + auto-bound by verified email), claims private links, and links the other identity by union merge.
**Mode:** mvp
**Depends on:** Phase 3
**Requirements:** ACC-01, ACC-02, ACC-03, ACC-04, ACC-05
**Success Criteria** (what must be TRUE):

1. `buyer_accounts` holds email/pubkey identities (nullable, unique-when-present, merchant-scoped HMAC + AEAD); sessions mint against `account_id` and pre-migration NIP-07 sessions keep working.
2. `orders.buyer_email_hash` is written at checkout and backfilled; order history is the pubkey+email union; claims bind whichever identities the account offers.
3. Magic-link sign-in is no-oracle end to end — single-use hash-only fragment-delivered tokens, dual rate limits, email_queue transport with honest unconfigured degradation, identical cookie contract.
4. Both identity-link directions work; owned-elsewhere identities union-merge atomically (sessions re-point, loser retires) or reject honestly when unrepresentable.
5. Sign-in affordance offers both methods with honest availability; profile shows linked identities and gates kind-0 on a real key; orders page acknowledges found history once.

**Plans:** 3/3 plans complete

Plans:

- [x] 03.1-01-PLAN.md
- [x] 03.1-02-PLAN.md
- [x] 03.1-03-PLAN.md

**Wave 1**

- [x] 03.1-01: m008 schema (buyer_accounts, email_signin_tokens, buyer_sessions rebuild, orders.buyer_email_hash, email_queue.payload_enc) + backfill + account-scoped sessions + union history/claim/attribution

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 03.1-02: magic-link transport + no-oracle request/verify + fragment landing + identity linking/union merge + spec amendment + runtime suite

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 03.1-03: two-method modal + widened render gate + profile link cards + orders note + /_e2e/mailbox harness + buyer e2e flows

### Phase 4: Release C — Catalog Import and Export

**Goal:** Merchants upload product files, preview them, review hidden drafts in Catalog and publish only approved products through the normal workflow. No old-store order or invoice status is consulted.
**Mode:** mvp
**Depends on:** Phase 3
**Requirements:** LEG-03, LEG-06 (LEG-04/05 dropped)
**Success Criteria** (what must be TRUE):

1. Merchant can preview and execute bounded CSV/JSON file imports without arbitrary fetch/database access or secret leakage; Shopify variants and image-only rows are supported, and imported products remain hidden drafts until the merchant publishes them.
2. Merchant can export a round-trippable product CSV and optionally upload/relink owned media; currency is requested only for formats without currency, and source identifiers/Shopify mapping are optional.
3. Variable parents and imported draft options become visible together on approval; normal checkout stock reservation, publication and settlement still enforce local inventory safety.
4. Documentation clearly states the extension does not inspect old orders or offer cutover, attestation, old-store freeze, or a physical-count activation gate. Operators handle any overlapping old-store stock independently.

**Plans:** Historical plan files remain in `.planning/phases/04-release-c-migration-and-cutover/` as execution records. Their cutover designs are superseded by the catalog-only scope.

Plans:

- [x] 04-01: File-only catalog preview, import records, Shopify/JSON/native parsing and signed commitment; current behavior creates ordinary hidden drafts.
- [x] 04-02: Historical cutover implementation, subsequently removed; not a current phase gate.
- [x] 04-03: Product CSV export, media upload/relink, storefront profile and native CSV reimport.
- [x] 04-04: Superseded rehearsal plan; no longer a current release criterion.
- [x] Closeout: catalog-only workflow, tests, live deployment, merchant operations surfaces, and relay reconciliation verified for release packaging.

## Progress

**Execution Order:** Phase 1 → Phase 2 → Phase 3 → Phase 03.1 → Phase 4

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Conformance Profile | 3/3 | Complete    | 2026-09-20 |
| 2. Release A — Safe Web Commerce | 4/4 | Complete    | 2026-09-27 |
| 3. Release B — Gamma NIP-17 Orders | 4/4 | Complete    | 2026-09-29 |
| 03.1. Buyer accounts (INSERTED) | 3/3 | Complete   | 2026-10-05 |
| 4. Release C — Catalog Import and Export | Catalog workflow implemented and verified | Complete | 2026-10-09 |
