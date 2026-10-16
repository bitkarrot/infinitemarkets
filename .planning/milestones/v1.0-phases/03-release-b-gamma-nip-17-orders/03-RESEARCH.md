# Phase 3: Release B — Gamma NIP-17 Orders - Research

**Researched:** 2026-09-28
**Domain:** Nostr NIP-17 gift-wrapped order protocol on pinned `nostr-sdk==0.44.8` inside an LNbits extension — durable inbox/outbox workers, kind-10050 discovery, NIP-42/paid relays, buyer sign-in, storefront modes, external (Plebeian) conformance
**Confidence:** HIGH for SDK/harness/codebase mechanics; MEDIUM for Plebeian conformance outcome (behavior verified at `master@4bc7f8c`, but the live checkout diverges from the wrapped-rumor model — see §"Plebeian conformance reality")

<user_constraints>
## User Constraints (from CONTEXT.md)

**CRITICAL:** These locked decisions from `03-CONTEXT.md` MUST be honored by the planner.

### Locked Decisions

**Buyer History & Sign-in (carried from Phase 2 UAT)**

- **D-01:** NIP-07 "Sign in with Nostr" on the web storefront proves pubkey ownership via a signed challenge and shows that buyer's past Gamma orders with statuses — answers the UAT "no way to see past orders" issue. Session is server-issued and revocable. — **Reversibility:** costly — introduces a new authenticated buyer session type (schema, cookie handling, revocation) that later claiming/attribution features build on.
- **D-02:** No merchant resend protocol for lost NIP-17 history — sign-in + order list is the recovery path. Buyers who can't sign in have no fallback this phase.
- **D-03:** Signed-in buyers see digital delivery content (download links/license keys) inline — the NIP-07 session grants token-equivalent access; the same paid-state gating rules as the private order page MUST apply.
- **D-04:** Web checkout by a signed-in buyer sets `buyer_pubkey` on the order — it appears in their sign-in list AND receives NIP-17 status copies on their declared kind-10050 relays. One identity, one history. — **Reversibility:** costly — order intake and outbound routing must key on buyer pubkey for attributed web orders.
- **D-05:** Claim flow — pasting a valid private order link while signed in binds `buyer_pubkey` to that order (retroactive lost-link recovery). — **Reversibility:** costly — token-to-identity binding with replay/audit edge cases.
- **D-06:** Sign-in is offered only when the merchant has an active/configured inbox profile — shops without Nostr don't show the button.

**Nostr-only Shop Modes (carried `web_checkout_enabled`, expanded)**

- **D-07:** Not a boolean — a four-state **storefront mode** in a dedicated admin panel with an impact warning: **Full** (web browse + checkout + Nostr, default), **Showcase** (web browse; buy controls show guided "Order via Nostr" instructions — merchant npub, inbox relays, suggested client), **Browse-only** (web browse, no sales anywhere), **Nostr-only** (public pages show a Nostr-only notice; Nostr sales remain). — **Reversibility:** costly — the mode permeates every public surface, the checkout API, and publication gating.
- **D-08:** Hard invariant — existing private order links, in-flight invoices, order status, digital delivery, sign-in, and track-order work in **every** mode. Modes gate new purchases and public browse depth only.
- **D-09:** Storefront mode controls Nostr publication per the confirmed matrix — Showcase and Nostr-only publish listings; Browse-only pauses them.
- **D-10:** Showcase and Nostr-only are **blocked** in admin until the merchant has an active kind-10050 inbox profile — prevents advertising Nostr ordering that can't receive orders.
- **D-11:** In-flight unpaid web checkouts expire naturally on mode change — no forced cancellation.

**Admin Messages UX**

- **D-12:** New **Messages** nav surface (fifth item) — inbox of kind-14/16/17 conversations; order threads also embedded in order detail.
- **D-13:** Full outbound — merchants reply in threads and compose new DMs to any npub, sent as NIP-17 sender+recipient copies through the outbox.
- **D-14:** Customer-priority inbox — senders whose pubkey matches an order's buyer hash thread/flag as "customer"; unknown senders land in a separate **Unknown** folder, still visible (never dropped silently).
- **D-15:** Unread badge on the Messages nav item, unread markers per conversation, mark-as-read on open or manually.

**Merchant Activation (kind-10050)**

- **D-16:** Settings-driven — inbox relays live in a settings table (same pattern as publication relays); an enable action publishes kind-10050 in the background with explicit **pending → error** states. Activation cannot be claimed active until ≥1 inbox relay acknowledges (GAM-01).
- **D-17:** Deactivation publishes a kind-5 tombstone for kind-10050 and stops intake; in-flight orders continue to completion.

**Delivery & Retry Surfacing**

- **D-18:** Per-message delivery state — lightweight status markers in-thread plus a detail panel showing per-relay evidence for both recipient and sender copies.
- **D-19:** Automatic backoff retries per spec, plus a manual "retry now" on stuck messages.
- **D-20:** Connectivity health strip in Messages — inbox listener state, per-relay connectivity, outbox backlog depth.

**Malformed / Hostile Intake**

- **D-21:** Rejected inbound rumors land in an auditable **Rejected intake** view with reason (bad signature, unknown product, replay, oversize) — kept out of the Orders list.
- **D-22:** Rejected-but-parseable rumors get a `status=rejected` protocol reply so a real client's order isn't left hanging; unintelligible payloads log only. Never reveals order existence to strangers.
- **D-23:** "Mute this pubkey" action on rejected entries adds the author to a merchant blocklist — future rumors dropped at intake (still logged).
- **D-24:** Per-author inbound rate cap — excess dropped before validation burns CPU (aligned with §9.5 resource bounds).

**Relay Auth (NIP-42 + paid relays)**

- **D-25:** Extension signs NIP-42 AUTH challenges with the merchant's Nostr identity automatically via the keystore — no manual merchant step.
- **D-26:** Per-relay auth status in admin (authenticated / auth-required / auth-failed); auth-rejected shows remediation guidance (e.g., "add npub X to this relay's allowlist").
- **D-27:** Paid relays (L402-style, e.g. Plebeian's relay) show "payment required" with the invoice displayed — the merchant pays externally from their own wallet; the extension never spends (no-spend policy). On expiry the row re-prompts with a fresh invoice.
- **D-28:** Relay auth model covers both NIP-42 pubkey auth and paid-write gating — marketplace relays may require payment before accepting posts (owner note).

**Conformance (GAM-05)**

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

### Deferred Ideas (OUT OF SCOPE)

- Merchant resend protocol for NIP-17 history (rejected D-02 — sign-in covers Phase 3).
- Paid-relay subscription/expiry tracking beyond re-prompt-on-rejection.
- nostrrelay formal qualification (reference deployment only).
- Real-sats conformance payment.
- Historical Phase-3 forecast of NIP-15/NIP-04 interop and cutover rehearsal for Release C — superseded: current Phase 4 is file-only catalog import as hidden drafts, merchant review and normal publication, with no old-order audit.
- NIP-37 draft sync, subscriptions/preorders, automated refunds, transport adapters — v2 per STATE.md deferred table.
</user_constraints>

<architectural_responsibility_map>
## Architectural Responsibility Map

Extension is a single backend tier (LNbits native extension, async Python) + thin admin/public JS. "Frontend Server" below = LNbits FastAPI routes owned by this extension.

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| kind-10050 publish + reachability gate | API/Backend (outbox worker + relay_configs) | Frontend Server (settings UI) | Publication evidence is durable per-relay ACK, mirroring `publish`/`merchant_profile` activation |
| Inbox subscription + cursor persistence | API/Backend (leased `inbox_processor` + `relay_manager` + `relay_cursors`) | — | §10 worker lifecycle; cursors advance only after EOSE + durable admission |
| NIP-17 wrap/unwrap crypto | API/Backend (`keystore.py` — `nip17_wrap`/`nip17_unwrap`) | — | §11 custody: nsec decrypted inside keystore op only; SDK primitives do the crypto |
| Order-message domain dispatch | API/Backend (`services/orders.py`, `checkout.py`, `settlement.py`) | Database (UNIQUE dedupe) | GAM-02: identical canonical services as web checkout |
| Dual-copy outbound + peer relay discovery | API/Backend (outbox `order_msg` branch + `peer_relays` cache) | — | §6.9/§8.6/§9.3 routing rules; declared relays only |
| NIP-42 AUTH + paid-relay handling | API/Backend (inbox transport + keystore sign) | Frontend Server (auth status surface) | D-25/D-26/D-27: keystore signs; admin shows per-relay auth/paywall state |
| Rejected intake / blocklist / per-author caps | Database + API/Backend | Frontend Server (Rejected intake view) | `inbox_events` rejected/quarantined rows + `rate_limit_buckets` + new blocklist table |
| Messages surface + unread markers | Frontend Server (admin API + `admin_messages.js`) | Database (`order_messages` + read markers) | Mirrors `admin_orders.js` split workspace |
| NIP-07 sign-in, sessions, order list, claiming | Frontend Server (public API) + Browser/Client (`window.nostr`) | Database (`buyer_sessions`, `orders.buyer_pubkey_*`) | Challenge → signed event → server-issued revocable cookie session |
| Storefront mode gating | API/Backend (mode setting + guards on checkout/quote/publish) | Browser/Client (public page states) | D-07..D-11: mode permeates public API, pages, and outbox gating; existing links/invoices invariant |
| Buyer kind-10050 egress safety | API/Backend (relay URL + DNS validation at connect/discovery) | — | §9.5 SSRF boundary; attacker-controlled peer relays |
| Conformance matrix (Plebeian) | Test harness (`tests/` + pinned clone + local relays) | — | D-30/D-35: scripted local runs; live smoke documented |
</architectural_responsibility_map>

<research_summary>
## Summary

Phase 3 turns the schema-only `inbox_events`/`order_messages`/`peer_relays`/`relay_cursors` tables (m002) into a working NIP-17 commerce channel. The technical core is small and already de-risked: the pinned `nostr-sdk==0.44.8` exposes every primitive needed — `EventBuilder.seal`, `gift_wrap_from_seal`, `nip44_*`, `UnwrappedGift.from_gift_wrap`, `Client.subscribe`/`handle_notifications`/`fetch_events_from`, `ClientMessage.auth`, and a Python-implementable `CustomNostrSigner`/`HandleNotification` trait surface — and `harness/sdk.py` is a verified executable reference for the §8.5 unwrap chain and §6.9 dual-copy construction. The keystore's `nip17_wrap`/`nip17_unwrap` stubs (currently `ReleaseNotAvailable`) are the natural home: decrypt nsec inside the operation, use SDK primitives, release immediately — preserving the "no signer attached to transport" invariant. NIP-42 should be done **manually** (`handle_notifications` sees `RelayMessageEnum.AUTH` → `EventBuilder.auth` → `keystore.sign_event` → `send_msg_to`) rather than `ClientOptions.automatic_authentication`, because auto-auth requires a client-attached signer.

The highest-risk finding is **conformance**: the live Plebeian checkout (`PlebeianApp/market@4bc7f8c`) does NOT send orders as NIP-17 wraps end-to-end. It publishes a *signed public* kind-16 type-1 event, plus (only when delivery details are required) a *single* recipient-only kind-1059 wrap carrying a type-1 rumor with delivery tags (`subject='order-info'`, `name`, newline-joined `address`, `email`, `phone`, `shipping`=`30406:<pk>:<d>`); the buyer then publishes public signed type-2 payment requests (seller `lud16`, not BOLT11) and a public signed kind-17 receipt. Plebeian's UI reads orders from public `{kinds:[16,14,17]}` filters — it never reads our wrapped type-2/3/4 replies. The repo DOES contain a tested dual-copy rumor transport (`src/lib/orders/nip17OrderTransport.ts` + `nip17Relays.ts`) that resolves both parties' kind-10050 and wraps both copies — unwired in checkout but directly usable by the conformance harness. Plan for: accepting Plebeian's private-details wrap as a valid type-1 order (lenient `subject`, tolerate `name` tag, opaque `address` → physical orders take the documented rejection path; digital orders complete), and recording the receipt/public-reply visibility gaps as D-32 known-deltas.

nostrrelay (the reference gated inbox, D-34) mechanics are fully mapped: `wss://<domain>/nostrrelay/<id>`, NIP-42 via `["AUTH", challenge]` / kind-22242 response, paid-write gating returns `["OK",id,false,"This is a paid relay: '<id>'"]` (no HTTP 402 — detection is message-text-based, payment happens on the relay's public page), and — critically — its p-tag recipient gating applies **only to kind 4**; kind-1059 is not recipient-gated server-side, so the merchant-inbox relay must be configured `require_auth_filter` + account allowlist = merchant npub only (open writes for 1059, merchant-only reads) to satisfy §9.3's "serve 1059 only to the authenticated p-tagged recipient". Its `created_at_days_past` NIP-22 limit must be ≥2 days or unset or it rejects randomized gift-wrap timestamps.

**Primary recommendation:** Structure the phase as (1) keystore NIP-17 primitives + kind-10050 activation + inbox transport (subscription, cursors, manual NIP-42, egress checks), (2) durable inbox processor + `order_msg` dual-copy outbox path reusing `relay_publications.delivery_copy`, (3) buyer-facing surfaces (sign-in, modes, Messages, rejected intake), (4) Plebeian conformance on local relays with known-delta recording. Treat the `harness/sdk.py` unwrap chain and `services/outbox.py` claim/evidence machinery as the two immovable anchors everything else bolts onto.
</research_summary>

<standard_stack>
## Standard Stack

All primitives exist in the pinned stack — **no new dependencies** (host constraint + PINS.md). JS tooling Node 22/24 only.

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `nostr-sdk` (Python/uniffi over rust-nostr) | `0.44.8` (pinned wheel per PINS.md §3) | NIP-17/NIP-59 wrap+unwrap, NIP-44 v2, relay pool, subscriptions, NIP-42 auth events, kind-10050 fetch | Host-resolved pin; P0-02 already qualified its wrap/unwrap/bounded-input behavior |
| LNbits `v1.6.2-rc1` @ `e336fe14b841` | pinned | Extension host: task_manager, invoice listener, extension DB, extension router, Vue admin shell | Pinned host contract (P0-03); no core modifications |
| `pycryptodomex` AES-256-GCM (via `infinitemarkets/crypto.py`) | host-provided | Field encryption (`author_enc`, `content_enc`, `payload_enc`, session/token envelopes) + HMAC equality indexes | §11.2/§11.3 custody model already qualified |
| SQLAlchemy raw-text via `DomainTransaction` | host 1.4 line | Transactions, fencing, SKIP LOCKED / BEGIN IMMEDIATE | §14; host auto-commit helpers forbidden in domain tx |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `harness/sdk.py` | repo | Verified §8.5 unwrap chain + §6.9 wrap construction reference | Mirror its stage order + bounded rejection reasons in production code |
| `harness/relay.py` `LocalRelay` | repo | Deterministic accepting/rejecting/silent/AUTH_FLOOD relay on 127.0.0.1 | Inbox/outbox worker tests; extend with EOSE/REQ support + gated modes for conformance |
| nostrrelay (LNbits ext) | `main` (reference only) | Self-hosted recipient-gated-ish inbox relay for conformance env | D-34: reference deployment, not a runtime dep |
| Plebeian `market` (pinned clone) | `master@4bc7f8c0c73a…` + lock | External Gamma client for GAM-05 | bun-driven; uses `nak serve` local relay (ws://localhost:10547) |
| `nak` (Go) | any recent | `nak serve` local NIP-01 relay for Plebeian | Conformance relay when nostrrelay not under test |
| Playwright (`tests/e2e`) | existing | Admin Messages / storefront-mode / sign-in UI checks | Node 22/24; follows existing spec patterns |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Manual NIP-42 via `ClientMessage.auth` | `ClientOptions.automatic_authentication` + `NostrSigner.custom(keystore-backed)` | Auto-auth needs a client-attached signer (violates no-signer-on-transport); custom signer is viable but adds a second keystore entry path. Manual keeps one signing path + explicit per-relay auth state needed for D-26 anyway |
| Explicit §8.5 unwrap chain in keystore | `UnwrappedGift.from_gift_wrap(signer, wrap)` | Composite unwrap doesn't enforce p-tag count/recipient, seal empty tags, canonical rumor id, or raw-JSON duplicate-tag rejection — the explicit chain (proven in harness) is required for spec §8.5 steps 5–8 anyway |
| `Client.gift_wrap_to` for outbound | keystore `nip17_wrap` + `transport.send_to` | `gift_wrap_to` constructs+signs+sends inside SDK (needs signer on client, gives no per-copy control of evidence). Two separate wraps via keystore → `send_to` gives per-copy `SendEventOutput` → `relay_publications(delivery_copy)` rows, which §4.10/§8.6 require |
| `Client.subscribe` + notification handler | `fetch_events` polling | Subscribe matches §9.2 (session-scoped `since`, EOSE cursor semantics); polling is a fallback shape — the spec's cursor rule is EOSE-driven so subscribe+EOSE is the faithful path |
| nostrrelay as transport dep | own transport + nostrrelay only as test inbox | D-34 locks: reference-only, no runtime dependency, extension keeps own transport |

**Installation:** nothing new. Conformance needs only `bun` (Plebeian) + `nak` (local relay) — dev/test tooling, not runtime deps.
</standard_stack>

<architecture_patterns>
## Architecture Patterns

### System Architecture Diagram

```
                         ┌──────────────────────── INFINITEMARKETS EXTENSION ─────────────────────────┐
                         │                                                                          │
 Buyer (Plebeian/NIP-17) │   INBOUND                                                   OUTBOUND       │
      kind-1059 #p=merch │                                                                          │
              ┌──────────▼──────────┐   EOSE→cursor   ┌────────────────┐                             │
  buyer kind- │  inbox transport    │  relay_cursors  │ inbox_processor │                            │
  10050 relays│  (nostr-sdk Client, │◄────────────────│ (leased task)  │                             │
  merchant    │  REQ kinds:[1059]   │                 │ 1s drain       │                             │
  inbox relays│  #p:[merchant],     │                 └──────┬─────────┘                             │
      ▲       │  since=cursor−3d)   │                        │ §8.5 chain (keystore unwrap)           │
      │       └──────────▲──────────┘                        ▼                                      │
      │                  │ AUTH challenge         ┌──────────────────┐   dedupe outer_id/rumor_id    │
      │                  └────────────────────────│ NIP-42 responder  │   inbox_events states        │
      │                                     keystore.sign_event(22242)│   received→validated→processed│
      │                                          └──────────────────┘   rejected | quarantined       │
      │                                                                          │                  │
      │                                 ┌── sender copy recovery (no dispatch) ◄─┤                  │
      │                                 │                                          │ rumor kinds     │
      │                                 ▼                                          ▼ 14|16|17        │
      │                       order_messages (enc)                        §8.1 intake adapter        │
      │                                 ▲                       ┌────────────────────────────┐      │
      │                                 │ inserts/threads        │ item→d_tag, shipping→option │      │
      │                                 │                        │ country/region, buyer_pubkey│      │
      │                                 │                        └────────────┬───────────────┘      │
      │                                 │                                     ▼                     │
      │                                 │                        orders/payments/reservations       │
      │                                 │                        (SAME services as web: checkout.py,│
      │                                 │                         orders.py, settlement.py)         │
      │                                 │                                     │                     │
      │                                 │                        begin_saga → invoice → settlement  │
      │                                 │                                     ▼                     │
      │                                 │                        order_msg outbox intents (type2/3/4)│
      │                                 │                                     │                     │
      │                                 │                        ┌──────────────▼───────────┐         │
      │                                 └──────── descriptor ── │ outbox worker (claim/CAS) │        │
      │                                    payload_enc          │ rumor fixed id/created_at │        │
      │                                                         │ nip17_wrap ×2 (recipient+ │        │
      │              peer_relays (buyer kind-10050, 24h) ───────►│ sender copies)             │        │
      │              merchant inbox relay set ─────────────────►│ send_to → relay_publications│       │
      └─────────────────────────────────────────────────────────│ (delivery_copy=recipient|  ────────┘
                                                                │  sender); published iff    │
                                                                │  ≥1 OK each class          │
                                                                └────────────────────────────┘

  PUBLIC API (buyer):  GET challenge → sign(kind-22242) → POST verify → buyer_sessions cookie
                       GET /nostr/orders (session-scoped)   POST /nostr/claim {token}
  STOREFRONT MODE:     setting storefront_mode → gates checkout API, public pages, publish intents
  ADMIN:               Messages nav (conversations + Unknown + unread) | Rejected intake | Relay auth
```

### Recommended Project Structure (extensions to existing package)

```
infinitemarkets/
├── keystore.py                  # implement nip17_wrap/nip17_unwrap (currently ReleaseNotAvailable)
├── migrations.py                # m004+: peer_relays, relay_cursors, buyer_sessions, blocklist,
│                                #   message read markers, merchants.inbox_state, settings rows
├── services/
│   ├── transport.py             # extend: subscribe/handle_notifications, AUTH state, egress checks
│   ├── inbox.py            NEW  # §8.5 admission + processing pipeline + relay_cursors
│   ├── order_messages.py   NEW  # rumor⇄domain adapters (§6.9 tags, type 1-4, kind-17, kind-14),
│                                #   order_msg descriptors, dual-copy intent enqueue
│   ├── peer_relays.py      NEW  # buyer kind-10050 discovery + 24h cache + no-route policy
│   ├── nostr_auth.py       NEW  # NIP-07 challenge/verify/session, per-relay NIP-42 auth state
│   ├── storefront_mode.py  NEW  # mode setting + gate helpers (checkout, pages, publish)
│   ├── outbox.py                # add order_msg branch: decrypt descriptor → wrap×2 → per-copy evidence
│   ├── relay.py                 # inbox-direction targets, relay health + auth status surface
│   ├── tasks.py                 # + inbox_processor (leased), inbox subscription lifecycle
│   └── settlement.py            # reconcile: resume received|validated inbox rows; type-2 re-enqueue
├── views_public_api.py          # + nostr challenge/verify/orders/claim; mode gates on checkout/quote
├── views_api.py                 # + messages/rejected-intake/relay-auth/blocklist/mode APIs
├── views.py                     # mode-gated public pages + Nostr-only notice + sign-in affordance
├── static/infinitemarkets/js/
│   ├── admin_messages.js   NEW  # fifth nav surface (split workspace pattern from admin_orders.js)
│   ├── public_nostr.js     NEW  # NIP-07 sign-in, order list, claim flow, showcase guidance
│   └── admin_settings.js        # inbox relays + storefront mode panel + relay auth states
└── tests/runtime/               # + test_inbox.py, test_order_messages.py, test_nostr_auth.py,
                                 #   test_storefront_mode.py, conformance scripts
```

### Pattern 1: Keystore-scoped NIP-17 wrap/unwrap (nsec never leaves the op)
**What:** `MerchantKeyStore.nip17_wrap/nip17_unwrap` load the encrypted nsec inside the operation, run SDK primitives, release.
**When to use:** every outbound copy and every inbound unwrap — the ONLY crypto entry points.
**Example** (verified API shapes — `harness/sdk.py` lines 197-246):
```python
# inside MerchantKeyStore, keys = await self._keys(merchant_id) (released in finally)
async def nip17_wrap(self, merchant_id, unsigned_rumor, recipient_pubkey):
    from nostr_sdk import EventBuilder, NostrSigner, PublicKey, gift_wrap_from_seal
    keys = await self._keys(merchant_id)
    try:
        signer = NostrSigner.keys(keys)
        builder = await EventBuilder.seal(
            signer, PublicKey.parse(recipient_pubkey), unsigned_rumor)
        seal = await builder.sign(signer)
        return gift_wrap_from_seal(PublicKey.parse(recipient_pubkey), seal)  # SYNC in 0.44.8
    finally:
        del keys

# Unwrap: mirror harness/sdk.py unwrap_gift_wrap stages 1–8 with
# nip44_decrypt(keys.secret_key(), peer, content) + Event.verify()
# + canonical_rumor_id recompute + RAW-JSON duplicate-tag checks
# (SDK parses dedupe tags — dupes must be checked pre-parse).
```
`UnwrappedGift.from_gift_wrap(signer, wrap)` exists as a composite shortcut but does NOT enforce outer-p-tag count/recipient equality, seal-empty-tags, canonical rumor id, or duplicate common tags — so the explicit chain is required, and the harness version is already the proven template.

### Pattern 2: Session-cursor inbox (EOSE-bound durable admission)
**What:** per-`relay_cursors` row `since = last_completed_session_start − 3d` (never event `created_at` — wraps are randomly backdated ≤2d); persist new session start at subscribe; flip to `last_completed_session_start` only after EOSE arrives AND every delivered event is durably in `inbox_events`. First use defaults `now − 30d`. Event-id dedupe absorbs overlap.
**Example:**
```python
# transport handle_notifications (Python HandleNotification impl):
#   handle(relay_url, sub_id, event)      -> admission: kind1059 + one p==merchant
#                                          + verify() + ≤32KB + rate bucket
#                                          -> UNIQUE insert inbox_events(outer_event_id)
#   handle_msg(relay_url, msg):
#     RelayMessageEnum.END_OF_STORED_EVENTS -> session drained?
#                                            advance relay_cursors.last_completed_session_start
#     RelayMessageEnum.AUTH(challenge)      -> EventBuilder.auth(challenge, url)
#                                            -> keystore.sign_event -> ClientMessage.auth
#                                            -> client.send_msg_to([url], msg)
filter = (Filter().kinds([Kind(1059)])
          .pubkey(PublicKey.parse(merchant_pubkey))   # '#p' tag filter
          .since(Timestamp.from_secs(cursor_since)))
await client.subscribe(filter)   # persistent; SDK re-REQs on reconnect
```

### Pattern 3: `order_msg` outbox intents with two evidence classes
**What:** `outbox_events.aggregate_type='order_msg'`, `payload_enc` = fixed descriptor (canonical rumor created_at/id, recipient pubkey, semantic payload). The publish step decrypts, rebuilds the SAME rumor, calls `nip17_wrap` twice (buyer copy → `peer_relays` targets; sender copy → merchant inbox targets), sends each via `transport.send_to`, records `relay_publications(delivery_copy='recipient'|'sender')`. `published` requires ≥1 positive OK in EACH class. Retries reuse the rumor (stable id), fresh seal/wrap/outer ids; `order_msg` rows never supersede (§7.4 already says so).
**When to use:** type-2 payment requests (saga step 3 enqueue), type-3 status, type-4 shipping, kind-14 merchant replies.
**No-route policy (§9.3):** no buyer kind-10050 → `pending` + `last_error='no_inbox_relays'`, refresh every 15min for 48h → `failed`. NEVER route a wrap to non-declared relays.

### Pattern 4: Gamma intake adapter into the canonical pipeline
**What:** a rumor→checkout-payload adapter feeding `_resolve_cart`/`_price_cart`/`begin_saga` semantics unchanged:
- `item` tags `30402:<pk>:<d>` → `{d_tag, quantity}` (must assert `<pk>` == merchant pubkey — spec §8.5 step 8: "Every item address must carry merchant pubkey"; web path resolves by d_tag only)
- `shipping` tag `30406:<pk>:<d>` → `shipping_option_d`
- `country`/`region` companion tags OR `address` JSON object `{country, region, ...}` → `address` dict; opaque `address` strings → reject-before-reservation for physical (§8.1 step 7 + Plebeian sends newline-joined opaque address — expect rejection path)
- `order` → `external_id` (`^[A-Za-z0-9_-]{1,64}$`), `amount` → `buyer_amount_sat` (never trusted), `email`/`phone` → contact_enc
- `rumor.pubkey` → `buyer_pubkey_enc`/`buyer_pubkey_hash` (PURPOSE_BUYER_PUBKEY exists in crypto.py)
- dedupe: `UNIQUE(merchant_id, buyer_pubkey_hash, external_id_hash)` index already exists; request-hash on items+qty returns existing order vs `duplicate-order-conflict`
- §8.1 step 3: resolve buyer kind-10050 BEFORE creating order — no route → reject immediately (source relay is never a fallback)
- After intake: `begin_saga` → on `awaiting_payment`, enqueue type-2 `order_msg` intent instead of returning `public_token`/bolt11 to caller. `orders.protocol='gamma'`; web orders keep `public_token` semantics.

### Pattern 5: NIP-07 challenge→session (buyer auth)
**What:** `GET /api/v1/public/nostr/challenge` returns a one-time ≥128-bit challenge bound to merchant+IP scope + ~5min TTL (new `nostr_challenges` table or reuse `rate_limit_buckets`-style row). Storefront JS calls `window.nostr.signEvent({kind:22242, created_at, content: <challenge>, tags:[["challenge",c]]})`; `POST /nostr/verify` verifies `Event.verify()` (signature+id), challenge single-use match, `created_at` freshness, then inserts `buyer_sessions(token_hash, merchant_id, buyer_pubkey_enc/hash, expires_at, revoked)` and sets `HttpOnly; Secure; SameSite=Strict` cookie (`gm_nostr_session`, path `/infinitemarkets`). Mutating endpoints under the session cookie reuse the cookie-auth posture: exact-Origin check (canonical base URL) — same rule as admin cookie path; public GETs stay anonymous-safe.
**Endpoints:** `GET /nostr/orders` (session buyer_pubkey_hash → orders list, same §5.4 field set + paid-gated digital delivery per D-03), `POST /nostr/claim {token}` (valid private link binds buyer_pubkey per D-05; idempotent), `POST /nostr/logout` (revoke), checkout carries session → sets buyer_pubkey per D-04.
**D-06:** render the sign-in affordance only when merchant inbox profile is active (`merchants.inbox_state='active'` or settings flag).

### Pattern 6: Storefront-mode gates (single source of truth)
**What:** `storefront_mode` in `settings` table per merchant: `full`(default)|`showcase`|`browse_only`|`nostr_only`.
**Gate points (invariants per D-08/D-09):**
- public checkout POST + quote POST: blocked in showcase/browse_only/nostr_only (Showcase still shows "Order via Nostr" guidance — merchant npub + inbox relays + suggested client)
- public pages: nostr_only renders the Nostr-only notice page (browse depth zero)
- publication gating: browse_only pauses catalog intent enqueue/publish; showcase+nostr_only keep publishing listings (D-09)
- private order links/invoices/order-status/digital-delivery/sign-in/track-order: UNGATED in every mode
- admin mode panel: showcase/nostr_only disabled until inbox profile active (D-10); in-flight unpaid checkouts expire naturally (D-11)

### Anti-Patterns to Avoid
- **Deriving inbox `since` from event timestamps:** wrap `created_at` is randomized ≤2d in the past — session-start cursors only (§9.2 explicit).
- **Treating relay OK / wrap delivery as order/message truth:** OKs are delivery evidence only; payment truth stays LNbits; receipt kind-17 is cosmetic (`receipt_verified`), never settlement (§6.9).
- **Fallback routing:** never send a wrap to the source relay or any non-declared relay on no-route — `pending` + `no_inbox_relays` is the only correct state (§9.3).
- **Dispatching the merchant's own sender copy as an inbound command:** §8.5 step 7 — merchant-authored rumors match known outbound rumor ids and only mark recovery state.
- **Check-then-insert dedupe:** `outer_event_id`/`rumor_id` dedupe is UNIQUE-insert-or-no-op only (§14).
- **Attaching any signer to the shared transport client:** preserve the Phase-2 invariant; sign per-event via keystore (also required so AUTH/messages sign with the correct merchant identity per merchant).
- **Auto-commit helpers inside domain tx** (`Connection.execute/insert/update`) — existing §14 rule, applies to all new worker writes.
- **Logging rumor plaintext / AUTH challenges / relay secrets** — §16/§9.5.
</architecture_patterns>

<dont_hand_roll>
## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| NIP-59 seal/wrap construction | custom crypto, manual timestamp randomization, ephemeral keys | `EventBuilder.seal` + `gift_wrap_from_seal` (SDK) — via keystore | P0-05 qualified; randomization/ephemeral-key rules are subtle (fresh per copy, ≤2d past) |
| NIP-44 decrypt in unwrap | manual ChaCha/HKDF | `nip44_decrypt` module fn (or `UnwrappedGift.from_gift_wrap` after explicit checks) | audited primitive; §11.2 forbids custom crypto |
| Canonical rumor id check | manual sha256 serialization | rebuild via `EventBuilder` and compare `.id()` (harness `canonical_rumor_id`) | NIP-01 hash serialization edge cases (unicode escaping) already handled by SDK |
| Duplicate-tag detection | parsed-event tag counting | RAW-JSON tag-name counting before parse | SDK tag dedupe hides duplicates — proven footgun in harness |
| Inbox dedupe | `SELECT` then `INSERT` | UNIQUE insert on `outer_event_id`/`rumor_id`, treat conflict as success | §14 races; same discipline as idempotency_records |
| Per-relay evidence / retry | in-memory retry set | `relay_publications` append-only rows + `_accepted_targets` subtraction (existing outbox) | durable evidence survives crash; already implemented for `public` copy — extend to copy classes |
| Worker fencing | ad-hoc locks | `task_leases` + claim-token CAS (`outbox.claim_batch`/`_publication_transaction`) | multi-worker + crash safety already proven |
| NIP-07 signature verify | custom schnorr | `Event.from_json` + `event.verify()` | same SDK primitive as admission |
| kind-10050 fetch | raw websocket client | `client.fetch_events_from(urls, Filter().kind(Kind(10050)).author(pk), timeout)` | bounded, validated, reuses transport |
| Rejected-intake storage | new log files | `inbox_events.processed_state='rejected'|'quarantined'` + `reject_reason` | schema exists; retention pruner already covers it (settlement.py ~885-925) |

**Key insight:** almost every hard part already has a qualified implementation or schema in this repo — the work is wiring (`inbox.py`, `order_messages.py`, `nostr_auth.py`, `storefront_mode.py`) plus the new outbox copy-class branch. The trap is rebuilding crypto/dedupe/retry that already exists.
</dont_hand_roll>

<common_pitfalls>
## Common Pitfalls

### Pitfall 1: Assuming Plebeian's checkout sends wrapped orders
**What goes wrong:** Planning assumes a Plebeian checkout drops a kind-1059 wrap containing a clean type-1 order into the merchant inbox; the order "just works".
**Why it happens:** The gamma-market spec describes the rumor model, and Plebeian's `src/lib/orders/nip17*` library implements it — but the LIVE checkout (`publishOrderWithDependencies` in `src/publish/orders.tsx`) publishes a **signed public kind-16** order marker plus (only when delivery details are required) a single recipient-only wrap carrying the delivery-details rumor; payment flows through buyer-published public type-2 requests with `lud16` (not BOLT11), and the kind-17 receipt is a public signed event.
**How to avoid:** Treat the private-details wrap as the actual order intake for Plebeian buyers: tolerate `subject='order-info'` on type-1 (spec already tolerates missing subject — keep tolerating non-'order' values as a compat allowance or known-delta), tolerate the extra `name` tag, expect `address` to be a newline-joined opaque string (physical orders → §8.1 rejection path with `status=rejected` type-3 reply — that's the D-22 flow doing real work). Digital orders (email-only delivery) can complete end-to-end. Record as known-deltas: (a) Plebeian publishes no sender copy; (b) it doesn't read our wrapped type-2/3/4 — payment must be driven by FakeWallet against the LNbits invoice or a merchant `lud16` on kind-0; (c) public kind-17 receipts never reach our inbox (`receipt_verified` may stay false — document or extend inbox to public-filter optionally, NOT recommended). Consider driving the strict-rumor flow through Plebeian's own `nip17OrderTransport.ts` for the protocol-level matrix, and the UI checkout for the "real" run.
**Warning signs:** conformance run shows orders created from wraps but buyer UI never progresses; receipts absent.

### Pitfall 2: kind-10050 published to the wrong relay set / no reachability gate
**What goes wrong:** The kind-10050 event is published to the inbox relays themselves (it should be discoverable where buyers fetch it — the merchant's public/discovery relay set per NIP-17), or activation claims success without a positive OK (violates GAM-01).
**Why it happens:** "Inbox relays" and "relays where the 10050 advertisement lives" are easy to conflate; ACK wiring is new for a non-public aggregate.
**How to avoid:** Publish kind-10050 through the same outbox machinery to the merchant's **public + configured discovery** relay set (planner: confirm against spec §9.3 — buyers resolve it from "multiple configured discovery relays"); gate `inbox_state` `pending → active` on ≥1 positive `relay_publications` OK; `error` state on failure (D-16). Deactivation enqueues kind-5 tombstone for `10050:<pk>:` (protocol_addresses `d_tag=''` for non-addressable replaceable kinds, §4.13).
**Warning signs:** `protocol_addresses` row for kind 10050 missing after publish; buyers resolving empty relay sets.

### Pitfall 3: nostrrelay treated as p-gated for kind 1059
**What goes wrong:** Claiming recipient-gated inbox because nostrrelay "gates DMs" — but its `_is_direct_message_for_other` recipient gating is `kind == 4` ONLY; any authed+joined account can REQ `{kinds:[1059],'#p':[merchant]}` and receive the merchant's wraps (can't decrypt, but gets ciphertext/metadata).
**Why it happens:** README says "if AUTH enabled: send only to the intended target" — for NIP-04 only.
**How to avoid:** Compose the reference deployment: `require_auth_filter=true` + account allowlist = merchant npub only (merchant reads everything; nobody else reads anything) + 1059 writes open (buyers need to post wraps without accounts) or paid/allowed. Also set `created_at_days_past ≥ 2` (or unset) — NIP-22 created_at window must admit ≤2d-randomized wrap timestamps or every wrap is rejected.
**Warning signs:** wraps rejected with "created_at is too much into the past"; reads work anonymously.

### Pitfall 4: Cursor derived from wrap created_at (missed/lost events)
**What goes wrong:** `since = last_event_created_at + 1` silently drops wraps (randomized up to 2 days back).
**Why it happens:** NIP-59 backdating violates the usual "events arrive in time order" assumption.
**How to avoid:** Session-start cursors only — `since = last_completed_session_start − 3d`, advanced only after EOSE+admission; dedupe by `outer_event_id` absorbs overlap (§9.2 verbatim).
**Warning signs:** orders "lost" after worker restart with cursors set near now.

### Pitfall 5: Egress/SSRF via buyer-declared relays
**What goes wrong:** Connecting to arbitrary kind-10050 relay URLs lets any buyer point the merchant's client at internal services (DNS rebinding too — `validate_relay_url` is syntactic only: rejects raw-IP hosts + internal-looking names but does NOT resolve DNS).
**Why it happens:** Phase-2 relays were merchant-configured (trusted-ish); peer relays are attacker-supplied.
**How to avoid:** At connect/discovery time resolve the hostname (getaddrinfo) and reject loopback/private/link-local/multicast/reserved/metadata ranges IPv4+IPv6; revalidate on reconnect; redirects disabled. D-33 narrows the claim: in-code checks + documented operator egress requirement + self-hosted gated-relay evidence satisfy Release-B conformance — OS/container egress stays operator responsibility and MUST be recorded as an explicit §21-register delta in the phase summary.
**Warning signs:** a peer relay URL resolving to 127./10./169.254./::1 at connect time passes validation.

### Pitfall 6: Order-id/tag normalization breaks dedupe or interop
**What goes wrong:** `external_id` rejects Plebeian UUIDs or the item-address prefix; `subject` strictness rejects real orders.
**Why it happens:** `external_id` MUST be `^[A-Za-z0-9_-]{1,64}$` — Plebeian `uuidv4()` (36 chars incl. hyphens) fits; but e.g. colon-containing ids must reject. Item refs `30402:<pk>:<d>` — Plebeian `d` may itself contain characters needing careful split (split first two `:`).
**How to avoid:** Validate charset early (reject → rejected/quarantined + reason), never normalize `external_id` before hashing (`crypto.normalize` = exact form the UNIQUE index sees); item `pk` must equal merchant pubkey; `subject` tolerated, not value-enforced.
**Warning signs:** valid client orders landing in Rejected intake with `external-id` reason.

### Pitfall 7: Treating any OK/receipt/DM as state mutation
**What goes wrong:** Buyer type-3 statuses other than `cancelled`, type-2 payment requests from buyers, or kind-17 receipts mutate orders.
**Why it happens:** Symmetry with outbound types suggests inbound parity — spec explicitly forbids it.
**How to avoid:** Buyer inbound: type-3 only `cancelled` actionable (and only via §7.1 + constant-time buyer-hash match), all other statuses audit-only; type-2 inbound rejected (manual mode); kind-17 sets cosmetic `receipt_verified` only when bolt11+preimage hash match — never settlement; kind-14 threads only when sender hash == order buyer hash else lands unthreaded/Unknown.
**Warning signs:** order state changes driven by inbound rumor content.

### Pitfall 8: `claim`/session endpoints leak order existence or sessions
**What goes wrong:** claim/bind endpoints return different responses for valid-vs-invalid tokens → token guessing oracle; session cookies ride along to CSRF'd public mutations.
**How to avoid:** identical 401 for every bad token (same `_order_for_token` pattern); session cookie mutations enforce exact-Origin like admin cookie path; sessions revocable server-side (`buyer_sessions.revoked`/delete); challenge one-time + short TTL + bound to merchant+IP scope.
**Warning signs:** distinct error codes/timing for token lookups; session cookie works cross-origin.

</common_pitfalls>

<code_examples>
## Code Examples

Verified API shapes from the installed wheel + harness (all paths verified against `.venv/lib/python3.12/site-packages/nostr_sdk/nostr_sdk.py` and `harness/sdk.py`).

### Inbox subscription + notification handling
```python
from nostr_sdk import (Client, Filter, Kind, PublicKey, Timestamp,
                       RelayMessageEnum, EventBuilder, ClientMessage, HandleNotification)

class InboxNotifications(HandleNotification):
    def __init__(self, admit, on_eose, on_auth_challenge):
        self._admit, self._eose, self._auth = admit, on_eose, on_auth_challenge
    async def handle(self, relay_url, subscription_id, event):
        await self._admit(str(relay_url), event)   # §8.5 pre-persist admission
    async def handle_msg(self, relay_url, msg):
        if msg.is_END_OF_STORED_EVENTS():
            await self._eose(str(relay_url))
        elif msg.is_AUTH():
            await self._auth(str(relay_url), msg.as_enum().challenge)

f = (Filter()
     .kinds([Kind(1059)])
     .pubkey(PublicKey.parse(merchant_hex))          # '#p' tag filter
     .since(Timestamp.from_secs(session_start - 3*86400)))
await client.subscribe(f)                            # persistent (auto-close NOT wanted)
await client.handle_notifications(InboxNotifications(...))
```

### Manual NIP-42 (keystore-signed, no signer on transport)
```python
from nostr_sdk import EventBuilder, ClientMessage, RelayUrl
async def answer_auth(client, keystore, merchant_id, relay_url: str, challenge: str):
    url = RelayUrl.parse(relay_url)
    unsigned = EventBuilder.auth(challenge, url).build(
        PublicKey.parse(await keystore.public_key(merchant_id)))
    signed = await keystore.sign_event(merchant_id, unsigned)   # kind 22242
    await client.send_msg_to([url], ClientMessage.auth(signed))
    # NIP-42 guard (§9.4): sign only when the challenge's relay URL
    # == the live connection URL; challenge bounded to 1 KiB.
```

### Buyer kind-10050 discovery + cache (§9.3)
```python
# fetch latest valid kind-10050 from multiple configured discovery relays
events = await client.fetch_events_from(
    [RelayUrl.parse(u) for u in discovery_relays],
    Filter().kind(Kind(10050)).author(PublicKey.parse(buyer_hex)),
    Duration(seconds=10))
latest = max(events.to_vec(), key=lambda e: e.created_at().as_secs())
relays = [validate_relay_target(t.as_vec()[1])
          for t in latest.tags().to_vec()
          if t.as_vec()[0] == "relay"]           # 1–3 normalized wss URLs
# -> peer_relays row (pubkey_hash, pubkey_enc, relay_url, fetched_at, expires_at=+24h)
# none -> order rejected at §8.1 step 3 / intent stays pending 'no_inbox_relays'
```

### Dual-copy publish inside `publish_intent` order_msg branch (sketch)
```python
desc = decrypt_descriptor(row["payload_enc"], settings, row["merchant_id"])
rumor = rebuild_rumor(desc)                          # fixed created_at => stable id
recipient_wrap = await keystore.nip17_wrap(row["merchant_id"], rumor, desc["buyer_pubkey"])
sender_wrap    = await keystore.nip17_wrap(row["merchant_id"], rumor, merchant_pubkey)
out_r = await transport.send_to(buyer_relays, recipient_wrap)     # peer_relays only
out_s = await transport.send_to(merchant_inbox, sender_wrap)      # merchant inbox only
# record each copy under delivery_copy='recipient'/'sender';
# state='published' iff >=1 accepted in BOTH classes
```

### NIP-07 sign-in verify (server side)
```python
from nostr_sdk import Event
ev = Event.from_json(signed_event_json)
if not ev.verify():                     raise _TOKEN_INVALID   # id+sig
if ev.kind().as_u16() != 22242:         raise _TOKEN_INVALID
if abs(now - ev.created_at().as_secs()) > 300: raise _TOKEN_INVALID
challenge = single_use_challenge_lookup(ev)
if not challenge or challenge.expired:  raise _TOKEN_INVALID
# create buyer_sessions row + Set-Cookie gm_nostr_session
#   HttpOnly, Secure, SameSite=Strict, path=/infinitemarkets
```
</code_examples>

<sota_updates>
## State of the Art (repo/ecosystem drift worth noting)

| Old Approach | Current Approach | When | Impact |
|--------------|------------------|------|--------|
| nostrmarket/NIP-15 kind-4 DMs + public product ordering | Gamma NIP-99 + NIP-17 wrapped order channel | market-spec era | Phase 3's whole job; NIP-04 interop deferred to Release C |
| Plebeian NIP-15 client | Plebeian mid-migration to NIP-99/NIP-17: public kind-16 events + private-details wrap today; full rumor transport in `src/lib/orders/nip17*` (unwired) | `market@4bc7f8c` | Conformance must match what the client ACTUALLY sends — expect known-deltas |
| Relay OK = delivery confidence | NIP-42-gated + paid-write relays ("This is a paid relay" negative OKs) | current relay ecosystem (nostrrelay, marketplace relays) | D-26..D-28 admin auth/paywall states become first-class UX, not edge cases |
| Public/open inbox relays | Recipient-scoped reads (NIP-42 + #p gating) | NIP-17 norm | §9.3 requires ≥1 inbox relay proven recipient-gated; open inbox relays labeled "degraded" |
| `UnwrappedGift` composite API | Explicit §8.5 verification chain | spec §8.5 + harness | Don't shortcut: composite misses p-tag/seal-tag/canonical-id/dup-tag checks |

**New tools/patterns to consider:**
- `CustomNostrSigner` trait (0.44.8): keystore-backed signer if auto-AUTH or `gift_wrap_to` ever wanted — keep as option, don't adopt yet.
- `RelayBuilderNip42`/`RelayBuilderNip42Mode`: relay-side auth knobs (running your own relay), only relevant for the nostrrelay reference env understanding.
- `Filter().pubkey()` as `#p` filter — cleaner than `custom_tag(SingleLetterTag, …)`.

**Deprecated/outdated:**
- `nostrclient` fan-out for private messaging — never supported per-recipient routing (spec §9.1).
- NIP-04 DMs as the DM channel — deprecated-insecure; Release C compat only.
- Polling-based inbox — spec mandates subscription + EOSE cursor semantics.
</sota_updates>

## Validation Architecture

How each requirement will be proven (test types, fixtures, evidence). Follows the existing discipline: `tests/runtime` (real host boot, marker `runtime`, `make verify-runtime`), `tests/qualification` reruns, `tests/e2e` (Playwright), `harness/` models, `evidence/` bundle for release-gate claims.

| Req | Validation approach | Fixtures / evidence |
|-----|--------------------|---------------------|
| **GAM-01** (kind-10050 publish + reachability gate) | Runtime tests: enable → outbox intent → positive `relay_publications` OK → `inbox_state=active`; zero/failed ACK → `error`; deactivation → kind-5 tombstone + intake stop | `LocalRelay` ACCEPTING/REJECTING; `protocol_addresses` row for `10050:<pk>:`; admin API state assertions |
| **GAM-02** (valid kind-16 type-1 → same canonical pipeline) | Runtime tests driving a constructed wrap through the full §8.5 chain → order `received` → saga → `awaiting_payment` → type-2 intent; shared-service assertions (pricing/inventory/invoice identical to web); charset/dedupe/conflict matrix; physical country/region requirements (opaque address → rejected) | Golden NIP-17 fixtures (`tests/fixtures/golden/nip17/`) + harness `build_order_rumor`/`wrap_order_copy` to synthesize valid + tampered wraps; `FakeWallet`-equivalent invoice stub already used by runtime tests |
| **GAM-03** (type-2/3/4 + kind-17 + kind-14 flows w/ dual copies + stable rumor id) | Runtime tests: outbound `order_msg` intents produce TWO wraps to DISTINCT relay sets; `relay_publications` rows carry `delivery_copy='recipient'|'sender'`; retry keeps rumor id, changes outer ids; `published` only when ≥1 OK per class; inbound type-3 cancel legality; kind-17 `receipt_verified` only on bolt11+preimage hash match; buyer type-2 inbound rejected; kind-14 threading by buyer-hash | Two `LocalRelay`s (buyer inbox, merchant inbox) recording received events — assert no wrap crosses sets; golden retry fixtures (`retry/`) |
| **GAM-04** (durable inbox: verify/dedupe/cursors/declared-only routing/retention) | Runtime + drill tests: kill between admission/processed/cursor points → restart → no duplicate domain commands (UNIQUE no-op semantics proven by re-delivery); `received|validated` resumed by reconciliation; EOSE→cursor advance only post-admission; merchant-authored wrap → sender-copy recovery (no dispatch); quarantine/reject reasons; retention pruner erases ciphertext (7d processed/30d quarantined) | `LocalRelay` variants incl. SILENT + a REQ/EOSE-capable fixture (extend `harness/relay.py` or nostrrelay); `harness/saga.py`-style crash-point drills; `task_leases` fencing tests |
| **GAM-05** (release gates: egress, recipient-gated relay, NIP-42, overload, external client) | (a) egress unit tests — DNS-resolve-reject matrix (private/link-local/metadata/IPv6) on discovered+configured targets; (b) nostrrelay-in-LNbits reference env: NIP-42 write/read gating + merchant-allowlist inbox serving 1059 only to authed merchant — scripted evidence; (c) AUTH challenge handling on `LocalRelay` AUTH mode extended to real challenge/response; (d) overload: admission caps (300/min wraps, queue 1000, per-author cap) → counted/dropped metrics; (e) Plebeian pinned clone on `nak serve` local relay: scripted buyer flow → order lands as wrap → invoice → FakeWallet payment → status; known-delta register for divergences; (f) documented live `plebeian.market` smoke (manual, recorded) | nostrrelay extension in test host (D-34 reference); Plebeian clone commit pinned in PINS.md-style record; conformance matrix doc; evidence entries in `evidence/manifest.json` / `evidence/REPORT.md` + D-33 spec-delta recorded in §21-register |
| Carried UAT items | Playwright + runtime: NIP-07 sign-in → order list scoped to buyer (+digital delivery under same paid gating); four-state storefront mode across public pages/checkout API/publish gating with in-flight-link invariant; Messages surface (folders, unread, compose, thread-in-order-detail); Rejected intake + mute | `tests/e2e/*.spec.ts` additions; admin API tests |
| Cross-cutting | `make verify` full suite stays green (D-05 regression); `make verify-runtime` covers new worker/task lifecycle; lint (`make lint`) | existing evidence discipline; CI matrix unchanged |


<open_questions>
## Open Questions

1. **Where does kind-10050 get published?**
   - What we know: §9.3 says buyers resolve the merchant's 10050 "from multiple configured discovery relays"; D-16 says publish through outbox with reachability gate. NIP-17 semantics = advertise it where buyers look (the merchant's public/discovery relay set), not necessarily on the inbox relays themselves.
   - What's unclear: whether the spec intends 10050 on the public relay set, the inbox set, or both — the reachability gate ("≥1 inbox relay acknowledges") suggests ACK from the inbox/target set is what matters for D-16.
   - Recommendation: planner resolves from spec §9.3 text (publish to the set buyers query — treat `direction='public'+'inbox'` targets as the publish set and record ACK against the declared inbox relays for the activation gate); verify against market-spec pinned commit during planning if ambiguity remains.

2. **Plebeian payment completion path in conformance**
   - What we know: Plebeian pays a seller `lud16`/Lightning address via buyer's wallet and does not read our wrapped type-2 BOLT11.
   - What's unclear: whether the conformance run should (a) attach an LNbits `lnurlp` lud16 to the merchant kind-0 so the live checkout can pay for real, or (b) pay the LNbits invoice directly via FakeWallet and treat UI payment as a known-delta.
   - Recommendation: Prefer (a) if an lnurlp-style address can be exposed on the merchant profile — it makes the real checkout complete literally; otherwise (b) + documented delta. Both satisfy D-32 but (a) minimizes recorded deltas.

3. **Inbound public kind-16/17 (signed, unwrapped) handling**
   - What we know: Plebeian publishes signed public order/status/receipt events our kind-1059 inbox never sees.
   - What's unclear: whether Release B should optionally subscribe to public `{kinds:[16,17],'#p':[merchant]}` to capture receipts/orders, or treat them as non-scope (Gamma = NIP-17 only per domain boundary).
   - Recommendation: Keep scope strict (NIP-17 inbox only) — subscribing to public order events reintroduces the metadata-exposure + unauthenticated-intake problems NIP-17 solves. Record "Plebeian receipt via public event invisible" as known-delta unless planner finds a spec hook.

4. **Multi-merchant NIP-42 identity on shared transport**
   - What we know: transport is one Client per worker; AUTH must sign per-merchant keys.
   - What's unclear: whether one subscription/pool multiplexes all merchants' inbox relays (AUTH per relay per merchant = sign each merchant's AUTH on their own relays — feasible manually) vs per-merchant client.
   - Recommendation: single transport; manual AUTH signs with the merchant whose inbox relays require it (merchant lookup by relay → `relay_configs`). Per-merchant clients are a fallback if the shared-client model fights the SDK's per-relay auth state.

5. **`order_messages` threading identity for web-attributed orders (D-04)**
   - What we know: attributed web orders get NIP-17 status copies; `order_messages.sender_hash/recipient_hash` + `participant_keys_enc` exist schema-only.
   - What's unclear: exact conversation threading model (order-bound threads vs pubkey threads) and whether sign-in orders list reads from `orders` or `order_messages`.
   - Recommendation: threads keyed by `order_id` when resolvable else by sender_hash (D-14: buyer-hash match → customer thread, else Unknown folder); sign-in list reads `orders` by `buyer_pubkey_hash` (orders are the authority; messages are the channel).
</open_questions>

<sources>
## Sources

### Primary (HIGH confidence)
- `docs/technical-specification.md` §4.9-4.12, §6.8-6.9, §7.4-7.5, §8.1-8.7, §9, §10, §11, §12, §15, §17-19, §21 — normative contract, read in full for these sections
- `.venv/lib/python3.12/site-packages/nostr_sdk/nostr_sdk.py` (installed 0.44.8 wheel) — API signatures verified: `EventBuilder.seal` (36978), `gift_wrap`/`gift_wrap_from_seal` module fns (49245/49280), `UnwrappedGift.from_gift_wrap` (48689), `Client.gift_wrap_to`/`send_event_to`/`send_msg_to`/`subscribe`/`fetch_events_from`/`handle_notifications`, `ClientMessage.auth` (34767), `EventBuilder.auth` (36147), `ClientOptions.automatic_authentication` (34961), `CustomNostrSigner` trait (30912), `HandleNotification` trait (31676), `RelayMessageEnum.{END_OF_STORED_EVENTS,AUTH,NOTICE,OK}` (20371+), `Filter.kinds/pubkey/since` (38098), `KindStandard.INBOX_RELAYS/SEAL/GIFT_WRAP` (16460), `RelayUrl.is_local_addr`, `RelayBuilderNip42*` (20309)
- `harness/sdk.py` — full §8.5 explicit unwrap chain + §6.9 dual-copy construction (executable reference, already qualified)
- `harness/relay.py` — `LocalRelay` modes ACCEPTING/REJECTING/SILENT/AUTH_FLOOD
- `tests/fixtures/golden/nip17/` — golden rumor/seal/wrap/sender/retry fixtures + README semantics
- `infinitemarkets/keystore.py` — `nip17_wrap`/`nip17_unwrap` stubs (lines 320-324) + nsec-inside-op custody pattern
- `infinitemarkets/services/{transport,relay,outbox,tasks,checkout,orders,settlement,nip89,merchant}.py` — read in full/relevant parts; outbox `publish_intent` evidence flow (523-667), worker/lease patterns (tasks.py), intake pipeline `_run_checkout`/`_insert_order_intake` (checkout.py 662-903), public API boundary (`views_public_api.py`), retention pruner presence for inbox_events/order_messages (settlement.py ~885-925)
- `infinitemarkets/migrations.py` m002 — orders/`inbox_events`/`order_messages`/`relay_publications`/`task_leases`/`rate_limit_buckets` + UNIQUE indexes already landed
- `infinitemarkets/security.py` — `validate_relay_url` syntactic posture (no DNS resolution), cookie/Origin/CSRF boundary
- `infinitemarkets/settings.py` — `peer_relay_ttl`, `inbox_max_event_bytes` already provisioned
- `PINS.md` — nostr-sdk 0.44.8 wheel identities + platform matrix
- Plebeian `market` local clone @ `4bc7f8c0c73ae4ba2ff2a78f0c66d28347d1c1ce` (`/tmp/plebeian-market`): `src/publish/orders.tsx` (live checkout: signed public kind-16 + private-details wrap + lud16 payment requests), `src/lib/orders/{orderMessageRumor,privateOrderMessage,nip17OrderPublish,nip17OrderRead,nip17OrderTransport}.ts`, `src/lib/nostr/{nip17,nip17Relays,nip59}.ts`, `src/lib/schemas/order.ts` (zod schemas incl. tag unions + `name`/`address`/`email`/`phone`/`shipping`), `src/queries/orders.tsx` (public-filter order reads + 1059 private-details only), `src/publish/payment.tsx` (public signed kind-17 receipt), `src/lib/checkout/deliveryRequirements.ts`
- nostrrelay `main` (`raw.githubusercontent.com/lnbits/nostrrelay`): `relay/client_connection.py` (AUTH challenge + `_is_direct_message_for_other` kind-4 gating + `require_auth_filter` REQ gating + "paid relay" NOTICE/OK), `relay/event.py` (`is_direct_message` = kind 4 only), `relay/relay.py` (`AuthSpec`/`PaymentSpec`/`EventSpec` created_at windows), `relay/event_validator.py` (auth event validation: relay-tag domain + challenge match; paid-write `"This is a paid relay: '<id>'"` negative OK), `README.md` (paid plans, account allow/block, wss path URL)

### Secondary (MEDIUM confidence)
- NIP-17/NIP-59/NIP-42 semantics as pinned in PINS.md (`nips@a2494f4`) — cross-checked against SDK behavior and harness notes, not re-read upstream this session
- `web_search` result for lnbits/nostrrelay — corroborated by raw file fetches

### Tertiary (LOW confidence — needs validation during implementation)
- Live `plebeian.market` behavior — researched code may differ from the deployed instance (live smoke check is the documented probe, D-30)
- Whether nostr-sdk `subscribe()` REQ is re-issued with the same `since` on reconnect (assumed; verify in inbox worker tests — reconnect semantics affect cursor safety)
- Whether `handle_notifications` delivers AUTH messages for relays that challenge on REQ (expected via `handle_msg`; verify against AUTH fixture)
</sources>

<metadata>
## Metadata

**Research scope:**
- Core technology: nostr-sdk 0.44.8 NIP-17/NIP-59/NIP-44/NIP-42 Python API surface (wheel-inspected)
- Ecosystem: Plebeian Market client checkout/orders/messaging code path (master clone); LNbits nostrrelay extension mechanics (main, raw sources); LNbits host v1.6.2-rc1 extension conventions
- Patterns: durable inbox/outbox workers, session cursors, dual-copy evidence, per-author caps + blocklist, NIP-07 sessions, storefront-mode gating, paid-relay UX
- Pitfalls: protocol drift between gamma-spec and live Plebeian, NIP-59 backdating vs cursors/created_at windows, SSRF via peer relays, nostrrelay kind-4-only gating, composite-vs-explicit unwrap verification

**Confidence breakdown:**
- Standard stack: HIGH — pinned wheel API introspected directly; no new deps
- Architecture: HIGH — maps onto existing outbox/inbox schema + worker patterns with named seams
- Pitfalls: HIGH for protocol/cursor/SSRF/nostrrelay (code-verified); MEDIUM for Plebeian deployed behavior
- Code examples: HIGH — all API names/signatures verified in the installed wheel and harness

**Research date:** 2026-09-28
**Valid until:** 2026-10-28 (Plebeian checkout path may change — re-pin clone commit and re-verify checkout semantics at conformance time)
</metadata>

---

*Phase: 03-release-b-gamma-nip-17-orders*
*Research completed: 2026-09-28*
*Ready for planning: yes*
