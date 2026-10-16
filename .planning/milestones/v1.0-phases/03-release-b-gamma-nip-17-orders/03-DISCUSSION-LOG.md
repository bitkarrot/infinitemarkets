# Phase 3: Release B — Gamma NIP-17 Orders - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-09-27
**Phase:** 3-Release B — Gamma NIP-17 Orders
**Areas discussed:** Buyer history & sign-in, Nostr-only shop, Admin messages UX, Conformance target, Merchant activation flow, Delivery & retry surfacing, Malformed/hostile intake, Relay auth (NIP-42 + paid relays)

---

## Buyer history & sign-in

| Option | Description | Selected |
|--------|-------------|----------|
| Show my Nostr orders | Signed challenge proves pubkey; storefront shows that buyer's past Gamma orders + statuses | ✓ |
| Recover order links only | Lists private order links without order details | |
| Defer sign-in entirely | No NIP-07 in Phase 3 | |

| Option | Description | Selected |
|--------|-------------|----------|
| Merchant resend protocol | Buyer sends status-request rumor; merchant re-sends status | |
| Sign-in covers it | NIP-07 sign-in + order list is the recovery path | ✓ |
| Both paths | Sign-in + resend rumor | |

| Option | Description | Selected |
|--------|-------------|----------|
| Status + link only | Buyer clicks through to private order page for delivery | |
| Show delivery content | Signed-in buyer sees download link/license inline | ✓ |

| Option | Description | Selected |
|--------|-------------|----------|
| Yes — unified history | Attributed web orders appear in sign-in list AND get NIP-17 status copies | ✓ |
| No — web stays anonymous | Web orders stay token-only even when signed in | |

| Option | Description | Selected |
|--------|-------------|----------|
| Yes — link claims order | Pasting a valid private link while signed in binds buyer_pubkey | ✓ |
| No — links stay separate | Private links and Nostr identity never merge | |

| Option | Description | Selected |
|--------|-------------|----------|
| Only when shop uses Nostr | Sign-in appears once merchant has active inbox profile | ✓ |
| Always available | Every storefront offers it | |
| Merchant toggle | Separate visibility setting | |

**Notes:** Sign-in unlock was chosen to directly answer the earlier UAT issue "no means for user to login to see their past orders". Delivery-inline means NIP-07 session is security-equivalent to the private token — gating must be identical.

---

## Nostr-only shop

| Option | Description | Selected |
|--------|-------------|----------|
| Browse + order via Nostr | Catalog browsable; buy button becomes guided Nostr instructions | |
| Full storefront, checkout off | Browsable; 'Web checkout unavailable' only | |
| Storefront disabled too | Public pages return Nostr-only notice | |
| **User override** | "let the user select via admin if they any of the 3 options" — all three behaviors became merchant-selectable modes | ✓ |

| Option | Description | Selected |
|--------|-------------|----------|
| Yes — always work | Order links/invoices/status/delivery work in every mode | ✓ |
| Hard cutoff | Nostr-only also blocks existing order pages | |

| Option | Description | Selected |
|--------|-------------|----------|
| Npub + relay hints | Merchant npub + kind-10050 relays | |
| Npub only | Client resolves relays itself | |
| Guided instructions | Step copy for non-technical buyers + client suggestion | ✓ |

| Option | Description | Selected |
|--------|-------------|----------|
| Independent | Publication continues in every mode | |
| Mode controls it | Some modes pause public Nostr listings | ✓ |

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, matrix is right | Full / Showcase / Browse-only / Nostr-only matrix confirmed | ✓ |

| Option | Description | Selected |
|--------|-------------|----------|
| Stay live in all modes | Sign-in/status/track pages always work | ✓ |
| Only Nostr-capable modes | Only where Nostr ordering is active | |

| Option | Description | Selected |
|--------|-------------|----------|
| Settings → storefront | Section in Settings next to appearance | |
| Dedicated shop-mode panel | Own panel with impact warning | ✓ |

| Option | Description | Selected |
|--------|-------------|----------|
| Blocked until ready | Nostr modes need active inbox profile first | ✓ |
| Allowed with warning | Mode saves, banner warns | |

| Option | Description | Selected |
|--------|-------------|----------|
| Expire naturally | Unpaid checkouts keep normal expiry | ✓ |
| Cancel on mode change | Cancel unpaid invoices immediately | |

**Notes:** The user redirected the original boolean question into the four-state mode matrix — the core product shape of this phase's storefront work.

---

## Admin messages UX

| Option | Description | Selected |
|--------|-------------|----------|
| New Messages surface | Fifth nav item; order threads also embedded in order detail | ✓ |
| Order detail only | Threads in order pane + unmatched bucket | |
| You decide | Fit the admin sketch contract | |

| Option | Description | Selected |
|--------|-------------|----------|
| Reply in threads only | Reply to existing counterparties | |
| Reply + new conversations | Also compose new DM to any npub | ✓ |
| Read-only inbox | Merchants reply from own client | |

| Option | Description | Selected |
|--------|-------------|----------|
| All in inbox, blocklist | Every DM lands; merchant can block | |
| Customer-priority inbox | Order-matching pubkeys flag customer; unknown → Unknown folder | ✓ |
| Hide unknown entirely | Only known buyers shown | |

| Option | Description | Selected |
|--------|-------------|----------|
| Unread badge + markers | Nav badge, per-conversation markers, mark-as-read | ✓ |
| Newest-first, no read state | No read tracking | |

---

## Conformance target

| Option | Description | Selected |
|--------|-------------|----------|
| Build reference client | Minimal standalone Gamma buyer client in-repo | |
| Client dev session | Separate agent session builds it | |
| **User override** | https://github.com/PlebeianApp/market + https://plebeian.market/ | ✓ |

| Option | Description | Selected |
|--------|-------------|----------|
| Real public relays | Shared public relays both sides reach | |
| Local relay first | Local matrix; documented public run closes gate | ✓ |

| Option | Description | Selected |
|--------|-------------|----------|
| FakeWallet/regtest OK | Protocol flows proven; documented no-real-sats caveat | ✓ |
| Real sats required | Small real payment | |

| Option | Description | Selected |
|--------|-------------|----------|
| Pinned local clone | Recorded commit, repeatable | |
| Live plebeian.market | Unpinned live only | |
| Pinned clone + live check | Matrix pinned + live smoke | ✓ |

| Option | Description | Selected |
|--------|-------------|----------|
| Ship egress fixture | Reference deployment artifact + probe | |
| Code + docs only | In-code checks; deployment operator's — §9.5 conflict | ✓ |

| Option | Description | Selected |
|--------|-------------|----------|
| Probe + document | Document relay gating posture | |
| Self-hosted gated relay | Reference gated relay deployment | ✓ |
| You decide | Researcher picks | |

| Option | Description | Selected |
|--------|-------------|----------|
| Record spec delta | Amend §9.5 — code checks + docs + gated-relay evidence satisfy claim | ✓ |
| Keep spec strict | Deployment must enforce demonstrable egress policy | |

| Option | Description | Selected |
|--------|-------------|----------|
| strfry | C++ relay with policy hooks | |
| nostr-rs-relay | Rust config-based restrictions | |
| **User override** | "nostrrelay extension on lnbits" — same-instance reference gated relay | ✓ |

| Option | Description | Selected |
|--------|-------------|----------|
| Full purchase must pass | Validation adapts to Plebeian | |
| Pass + documented deltas | Core flow passes; literal divergences documented | ✓ |

| Option | Description | Selected |
|--------|-------------|----------|
| Pin + qualify it | nostrrelay gets PINS.md qualification | |
| Reference only | No formal nostrrelay qualification | ✓ |

| Option | Description | Selected |
|--------|-------------|----------|
| Same LNbits instance | nostrrelay alongside infinitemarkets | ✓ |
| Separate instance | Own LNbits install/container | |

| Option | Description | Selected |
|--------|-------------|----------|
| Manual, recorded | Manual per-release runs | |
| Scripted + CI-ish | Automated local flow + manual live smoke | ✓ |

**Notes:** nostrrelay is the conformance deployment target, NOT a runtime dependency — extension keeps own transport per Phase-2 D-04. The §9.5 spec delta is a required phase artifact (recorded in CONTEXT D-33).

---

## Merchant activation flow

| Option | Description | Selected |
|--------|-------------|----------|
| Guided setup card | Activation card with relay picker + ack gating | |
| Settings-driven | Relay settings table + enable toggle publishing in background | ✓ |
| Two-tier | Settings + separate 'Go live' | |

| Option | Description | Selected |
|--------|-------------|----------|
| Pending → error states | 'activating…' then 'unreachable — check relays' with per-relay status | ✓ |
| Background with banner | Toggle flips immediately, banner reports | |

| Option | Description | Selected |
|--------|-------------|----------|
| Deactivate + tombstone | kind-5 for 10050, stops intake, in-flight completes | ✓ |
| Pause intake only | Stops listening, profile stays published | |

---

## Delivery & retry surfacing

| Option | Description | Selected |
|--------|-------------|----------|
| Per-message status | In-thread delivery ticks | |
| Detail panel only | Evidence in per-message panel | |
| Both | Ticks + detailed relay evidence | ✓ |

| Option | Description | Selected |
|--------|-------------|----------|
| Auto-retry + manual nudge | Backoff retries + 'retry now' | ✓ |
| Auto-retry only | Merchant can't force | |
| Retry + relay edit | Also edit recipient relays | |

| Option | Description | Selected |
|--------|-------------|----------|
| Health strip in Messages | Listener state, relay connectivity, outbox depth where traffic lives | ✓ |
| Settings diagnostics | Health in Settings relay tables | |
| You decide | Planner picks | |

---

## Malformed / hostile intake

| Option | Description | Selected |
|--------|-------------|----------|
| Auditable rejected list | 'Rejected intake' view with reasons | ✓ |
| Metrics only | Counters/logs only | |
| Rejected list + alert | List + spike alert | |

| Option | Description | Selected |
|--------|-------------|----------|
| Reply when identifiable | status=rejected to parseable rumors; log unintelligible | ✓ |
| No reply ever | Never reply to failed validation | |
| You decide | Planner follows spec | |

| Option | Description | Selected |
|--------|-------------|----------|
| Mute author action | 'Mute this pubkey' → merchant blocklist | ✓ |
| No mute in Phase 3 | Inspect-only | |

| Option | Description | Selected |
|--------|-------------|----------|
| Per-author cap | Bounded processing per author per window | ✓ |
| Global cap only | One intake budget | |
| You decide | Researcher picks bounds | |

---

## Relay auth (NIP-42 + paid relays)

| Option | Description | Selected |
|--------|-------------|----------|
| Merchant key, automatic | Extension signs AUTH via keystore transparently | ✓ |
| Explicit consent per relay | Merchant approves each relay first | |

| Option | Description | Selected |
|--------|-------------|----------|
| Auth status per relay | authenticated / auth-required / auth-failed column | ✓ |
| Folded into health | Auth inside health strip only | |

| Option | Description | Selected |
|--------|-------------|----------|
| Error + remediation | 'add npub X to relay allowlist' style guidance | ✓ |
| Error state only | 'auth failed' without steps | |
| You decide | Planner picks detail | |

**User addition (free text):** "some relays may be marketplaces like plebian market which may require a payment in order post, e.g. a L402 payment required before allowing write access. keep this in mind in addition to NIP-42 auth" → recorded as D-28.

| Option | Description | Selected |
|--------|-------------|----------|
| Pay externally, then works | L402 invoice shown; merchant pays from own wallet; extension retries | ✓ |
| Paid relays unsupported | L402 relays out of scope | |

| Option | Description | Selected |
|--------|-------------|----------|
| Re-prompt on expiry | Fresh invoice when relay rejects again | ✓ |
| Subscription-style | Track expiry, prompt before lapse | |

---

## Claude's Discretion

- NIP-07 challenge/session mechanics (freshness, cookie design, revocation, lifetime)
- Inbox worker internals (subscription multiplexing, backoff, cursor persistence)
- Rejected-intake storage shape and retention
- Exact UI copy for modes, states, remediation
- Migration/setting key naming (`storefront_mode` or equivalent)

## Deferred Ideas

- Merchant resend protocol for lost NIP-17 history (rejected — sign-in covers)
- Paid-relay subscription tracking beyond re-prompt-on-rejection
- nostrrelay formal qualification (reference deployment only)
- Real-sats conformance payment
- NIP-15/NIP-04 literal interop + migration — Phase 4
- NIP-37 drafts, subscriptions/preorders, automated refunds, transport adapters — v2
