# Phase 3: Release B — Gamma NIP-17 Orders - Context

**Gathered:** 2026-09-27
**Status:** Ready for planning

<domain>
## Phase Boundary

A Nostr buyer can place and follow a Gamma order through declared inbox relays against the same canonical commerce authority. Ships: merchant kind-10050 inbox profile with reachability-gated activation, durable NIP-17 inbox processing (kind-16 order/payment/status/shipping, kind-17 receipt, kind-14 DMs) feeding the existing pricing/inventory/invoice/settlement services, independent sender+recipient copies routed only to declared relays, crash-safe cursors/dedup/retry, buyer-facing NIP-07 sign-in with unified order history, four-mode storefront control, a merchant Messages surface, intake abuse defenses, NIP-42 + paid-relay auth handling, and a Plebeian-client conformance gate closing Release B. No NIP-15/NIP-04 interop or migration (Release C).

</domain>

<decisions>
## Implementation Decisions

### Buyer History & Sign-in (carried from Phase 2 UAT)

- **D-01:** NIP-07 "Sign in with Nostr" on the web storefront proves pubkey ownership via a signed challenge and shows that buyer's past Gamma orders with statuses — answers the UAT "no way to see past orders" issue. Session is server-issued and revocable. — **Reversibility:** costly — introduces a new authenticated buyer session type (schema, cookie handling, revocation) that later claiming/attribution features build on.
- **D-02:** No merchant resend protocol for lost NIP-17 history — sign-in + order list is the recovery path. Buyers who can't sign in have no fallback this phase.
- **D-03:** Signed-in buyers see digital delivery content (download links/license keys) inline — the NIP-07 session grants token-equivalent access; the same paid-state gating rules as the private order page MUST apply.
- **D-04:** Web checkout by a signed-in buyer sets `buyer_pubkey` on the order — it appears in their sign-in list AND receives NIP-17 status copies on their declared kind-10050 relays. One identity, one history. — **Reversibility:** costly — order intake and outbound routing must key on buyer pubkey for attributed web orders.
- **D-05:** Claim flow — pasting a valid private order link while signed in binds `buyer_pubkey` to that order (retroactive lost-link recovery). — **Reversibility:** costly — token-to-identity binding with replay/audit edge cases.
- **D-06:** Sign-in is offered only when the merchant has an active/configured inbox profile — shops without Nostr don't show the button.

### Nostr-only Shop Modes (carried `web_checkout_enabled`, expanded)

- **D-07:** Not a boolean — a four-state **storefront mode** in a dedicated admin panel with an impact warning: **Full** (web browse + checkout + Nostr, default), **Showcase** (web browse; buy controls show guided "Order via Nostr" instructions — merchant npub, inbox relays, suggested client), **Browse-only** (web browse, no sales anywhere), **Nostr-only** (public pages show a Nostr-only notice; Nostr sales remain). — **Reversibility:** costly — the mode permeates every public surface, the checkout API, and publication gating.
- **D-08:** Hard invariant — existing private order links, in-flight invoices, order status, digital delivery, sign-in, and track-order work in **every** mode. Modes gate new purchases and public browse depth only.
- **D-09:** Storefront mode controls Nostr publication per the confirmed matrix — Showcase and Nostr-only publish listings; Browse-only pauses them.
- **D-10:** Showcase and Nostr-only are **blocked** in admin until the merchant has an active kind-10050 inbox profile — prevents advertising Nostr ordering that can't receive orders.
- **D-11:** In-flight unpaid web checkouts expire naturally on mode change — no forced cancellation.

### Admin Messages UX

- **D-12:** New **Messages** nav surface (fifth item) — inbox of kind-14/16/17 conversations; order threads also embedded in order detail.
- **D-13:** Full outbound — merchants reply in threads and compose new DMs to any npub, sent as NIP-17 sender+recipient copies through the outbox.
- **D-14:** Customer-priority inbox — senders whose pubkey matches an order's buyer hash thread/flag as "customer"; unknown senders land in a separate **Unknown** folder, still visible (never dropped silently).
- **D-15:** Unread badge on the Messages nav item, unread markers per conversation, mark-as-read on open or manually.

### Merchant Activation (kind-10050)

- **D-16:** Settings-driven — inbox relays live in a settings table (same pattern as publication relays); an enable action publishes kind-10050 in the background with explicit **pending → error** states. Activation cannot be claimed active until ≥1 inbox relay acknowledges (GAM-01).
- **D-17:** Deactivation publishes a kind-5 tombstone for kind-10050 and stops intake; in-flight orders continue to completion.

### Delivery & Retry Surfacing

- **D-18:** Per-message delivery state — lightweight status markers in-thread plus a detail panel showing per-relay evidence for both recipient and sender copies.
- **D-19:** Automatic backoff retries per spec, plus a manual "retry now" on stuck messages.
- **D-20:** Connectivity health strip in Messages — inbox listener state, per-relay connectivity, outbox backlog depth.

### Malformed / Hostile Intake

- **D-21:** Rejected inbound rumors land in an auditable **Rejected intake** view with reason (bad signature, unknown product, replay, oversize) — kept out of the Orders list.
- **D-22:** Rejected-but-parseable rumors get a `status=rejected` protocol reply so a real client's order isn't left hanging; unintelligible payloads log only. Never reveals order existence to strangers.
- **D-23:** "Mute this pubkey" action on rejected entries adds the author to a merchant blocklist — future rumors dropped at intake (still logged).
- **D-24:** Per-author inbound rate cap — excess dropped before validation burns CPU (aligned with §9.5 resource bounds).

### Relay Auth (NIP-42 + paid relays)

- **D-25:** Extension signs NIP-42 AUTH challenges with the merchant's Nostr identity automatically via the keystore — no manual merchant step.
- **D-26:** Per-relay auth status in admin (authenticated / auth-required / auth-failed); auth-rejected shows remediation guidance (e.g., "add npub X to this relay's allowlist").
- **D-27:** Paid relays (L402-style, e.g. Plebeian's relay) show "payment required" with the invoice displayed — the merchant pays externally from their own wallet; the extension never spends (no-spend policy). On expiry the row re-prompts with a fresh invoice.
- **D-28:** Relay auth model covers both NIP-42 pubkey auth and paid-write gating — marketplace relays may require payment before accepting posts (owner note).

### Conformance (GAM-05)

- **D-29:** External Gamma client = **Plebeian Market** (`github.com/PlebeianApp/market`, live `plebeian.market`).
- **D-30:** Conformance matrix runs on local relays for repeatability; a documented public-relay run closes the release gate. Plebeian runs as a **pinned local clone** for the matrix plus a documented live-instance smoke check.
- **D-31:** FakeWallet/regtest payment is acceptable for conformance — asserts protocol flows with a documented "no real sats" caveat.
- **D-32:** The core order flow must pass end-to-end with a real Plebeian checkout; literal divergences are recorded as known-deltas with evidence (PINS.md precedent), not papered over.
- **D-33:** **Spec delta on §9.5** — the Release-B conformance claim is satisfied by in-code egress checks + documented operator egress requirement + self-hosted gated-relay evidence; OS/container egress policy remains operator responsibility. — **Reversibility:** one-way — amends the normative spec; must be recorded as an explicit decisions-register delta in the phase summary.
- **D-34:** Reference recipient-gated inbox = the LNbits **nostrrelay** extension running in the same LNbits instance. nostrrelay is reference-only — no formal qualification — and NOT a runtime dependency; the extension keeps its own transport (D-04 Phase 2 unchanged).
- **D-35:** Conformance execution is scripted + CI-ish on local relays (repeatable buyer-flow automation where feasible); the live-instance smoke stays manual with recorded evidence.

### Claude's Discretion

- NIP-07 challenge/session mechanics (challenge freshness, cookie design, revocation, session lifetime) — must satisfy the same cookie/CSRF posture as existing auth.
- Inbox worker internals: subscription multiplexing, reconnect/backoff, cursor persistence shape — consistent with §10 worker/lease patterns.
- Rejected-intake storage shape and retention.
- Exact UI copy/labels for modes, states, and remediation guidance.
- Mutation/migration naming and the mode-setting key name (`storefront_mode` or equivalent).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Normative Contract (authoritative on conflicts)

- `docs/technical-specification.md` — Phase 3 reads: §2 (payment/order flow), §3 (identifiers), §4.9–4.12 (inbox_events, order_messages, peer_relays, relay_cursors — schema already landed), §6.8–6.9 (merchant prefs + order rumors: dual copies, randomized timestamps, unsigned rumors), §8 (order intake/invoice saga — shared with web), §9 (transport, declared-relay routing, egress security — NOTE D-33 spec delta on §9.5), §10 (background workers/leases), §11 (key custody/encryption at rest), §12 (configuration), §14–§18 (idempotency/transactions, limits, observability, tests, release gates), §19 (threat model), §21 (decisions register).
- `docs/architecture-proposal.md` — background-work and transport rationale (spec wins conflicts).

### External Conformance Target

- `https://github.com/PlebeianApp/market` — external Gamma client; pinned local clone for the conformance matrix (record the commit).
- `https://plebeian.market/` — live instance for the final documented smoke run.

### Qualification Evidence and Pins

- `PINS.md` — approved pins, platform matrix, known-divergence precedent for D-32.
- `evidence/manifest.json` + `evidence/REPORT.md` — qualification evidence pattern to extend.
- `harness/` + `tests/qualification/` — permanent regression suite (D-05); `harness/sdk.py` (full §8.5 unwrap chain + dual-copy construction), `harness/relay.py` (`LocalRelay` — needs REQ/EOSE + NIP-42 extension), `harness/saga.py` (crash drills) are the executable reference. Golden NIP-17 fixtures exist at `tests/fixtures/golden/nip17/`.

### Project Scope

- `.planning/ROADMAP.md` Phase 3 — goal, requirements GAM-01..GAM-05, success criteria, 3-plan skeleton, carried UAT items.
- `.planning/REQUIREMENTS.md` — requirement definitions and Definition of Done.
- `.planning/phases/02-release-a-safe-web-commerce/02-CONTEXT.md` — carried decisions (frozen identifiers, spec register 1–29, transport/UI constraints).
- `.planning/research/` — STACK/ARCHITECTURE/PITFALLS.

### UI Findings (binding for presentation layer)

- `.devin/skills/sketch-findings-infinitemarkets/SKILL.md` + `references/` — validated UI decisions; the Messages surface and mode panel must trace to these.
- `.devin/skills/ecommerce-design-guide/SKILL.md` — conversion/usability guidance for the Showcase "Order via Nostr" guidance.
- `.planning/sketches/` — raw sketch sources.

### Host Reference

- `.cache/lnbits/` @ `e336fe14b841` — pinned host conventions; nostrrelay extension (reference gated inbox, D-34) ships with LNbits extensions.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- `infinitemarkets/services/relay.py` — `relay_configs` rows already support `direction=inbox`; starter-default seeding pattern exists and must extend to inbox defaults.
- `infinitemarkets/keystore.py` — `nip17_wrap`/`nip17_unwrap` interface already defined; merchant identity key custody is the AUTH/order-message signing path.
- `infinitemarkets/migrations.py` — `inbox_events` and `order_messages` schema landed (m002); `peer_relays`/`relay_cursors` are explicitly deferred and must be **created** this phase (per 03-PATTERNS.md); plus new fields/tables for buyer sessions, blocklist, storefront mode, read markers.
- `infinitemarkets/services/outbox.py` — durable publication evidence, per-relay `relay_publications`, fencing — the dual-copy NIP-17 publish path plugs in here.
- `infinitemarkets/services/orders.py`, `checkout.py`, `settlement.py` — canonical order/inventory/invoice/settlement services the Gamma adapter MUST reuse (GAM-02: same pipeline as web).
- `infinitemarkets/services/tasks.py` — leased background worker pattern for the inbox worker.
- `infinitemarkets/static/infinitemarkets/js/admin_orders.js` — split list/detail workspace the Messages surface mirrors.
- `tests/e2e/`, `harness/relay_fixtures`, `LocalRelay` — deterministic relay test plumbing.

### Established Patterns

- Relay ACK evidence is durable append-only evidence, never payment truth; NIP-17 `published` needs ≥1 recipient-copy AND ≥1 sender-copy positive OK (spec §8.6).
- No outgoing-payment APIs (code policy) — paid relays settle externally (D-27).
- Public themes never alter admin chrome or checkout semantics; new admin surfaces follow the Linear-style workspace contract.
- Owner-scoped authorization, CSRF/Origin, rate limits — new admin/buyer routes inherit the same boundary.
- Content-hash asset versioning + `no-store` admin shell (deployment-safety fix from Phase 2 UAT).

### Integration Points

- `infinitemarkets_start`/`_stop` hooks — inbox worker + relay subscription lifecycle.
- LNbits `task_manager` invoice listener — shared settlement path for Gamma orders.
- Public storefront templates + `public_storefront.js` — mode gating, sign-in, order list, claiming.
- Admin nav + `admin.html` — Messages surface, shop-mode panel, rejected-intake view, relay auth status.

</code_context>

<specifics>
## Specific Ideas

- The nostrrelay-in-LNbits reference deployment mirrors a real single-instance merchant — the conformance environment, not a required deployment shape.
- Plebeian divergences are fixed where the core flow breaks, documented as known-deltas where literal incompatibility is acceptable — same discipline as the `D|W|Y` frequency decision.
- L402 paid relays are real marketplace relays (Plebeian's); the pay-externally flow keeps the no-spend invariant while staying compatible.
- The Rejected intake view is the merchant's window into hostile/broken traffic — auditable, actionable (mute), never silent.

</specifics>

<deferred>
## Deferred Ideas

- Merchant resend protocol for NIP-17 history (rejected D-02 — sign-in covers Phase 3).
- Paid-relay subscription/expiry tracking beyond re-prompt-on-rejection.
- nostrrelay formal qualification (reference deployment only).
- Real-sats conformance payment.
- Historical Phase-3 forecast of NIP-15/NIP-04 interop and cutover rehearsal for Release C — superseded: current Phase 4 is file-only catalog import as hidden drafts, merchant review and normal publication, with no old-order audit.
- NIP-37 draft sync, subscriptions/preorders, automated refunds, transport adapters — v2 per STATE.md deferred table.

</deferred>

---

*Phase: 3-Release B — Gamma NIP-17 Orders*
*Context gathered: 2026-09-27*
