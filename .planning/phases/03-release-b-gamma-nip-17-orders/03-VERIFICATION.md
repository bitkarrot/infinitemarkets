---
phase: 03-release-b-gamma-nip-17-orders
verified: 2026-09-29
status: passed
reconciled: 2026-10-13 — reopened findings repaired via Phase 5; live external UAT executed and passed; see 05-VERIFICATION.md
verified_by: gsd-executor (plan 03-04)
---

# Phase 3: Release B — Gamma NIP-17 Orders — Verification Record

Maps the five phase success criteria (`.planning/ROADMAP.md`, Phase 3) to
their evidence. All scripted evidence is reproducible via
`cd tests/conformance && ./run_matrix.sh matrix` plus
`make verify-runtime` / `make verify` (isolated `LNBITS_DATA_FOLDER`).

## Success criteria

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 1 | Merchant activation publishes a valid kind-10050 profile only after configured inbox reachability is acknowledged | ✅ VERIFIED | `tests/runtime/test_inbox_activation.py` (pending→active only on ≥1 durable `accepted` relay_publications row; failure → `error`); journey capstone `tests/runtime/test_release_b_journey.py` step 1; matrix `env_bootstrap` probe (`inbox_state=active` on a real nak OK) — `evidence/conformance/plebeian-matrix.json` |
| 2 | Valid kind-16 orders enter the same pricing, inventory, invoice, settlement, and exception services as web checkout | ✅ VERIFIED | `tests/runtime/test_nip17_inbox.py` + `test_release_b_journey.py` (wrap → `gamma_order_intake` → shared `_resolve_cart`/`_price_cart`/`begin_saga`); external proof: `plebeian-matrix` probes `real_checkout_intake` + `strict_rumor_intake` (a real Plebeian wrap lands `orders.protocol='gamma'`, `awaiting_payment`) |
| 3 | Payment, status, shipping, receipt, and general-message flows use verified NIP-17 chains, stable rumor identity, independent party copies, and declared-relay-only routing | ✅ VERIFIED | `tests/runtime/test_nip17_outbox.py` (dual-copy `delivery_copy` recipient/sender rows, stable rumor id across retries, declared-only targets); matrix `strict_rumor_settlement` (4 accepted publication rows — type-2 + type-3, both classes); `buyer_readback` (Plebeian's own `nip17OrderRead.ts` unwraps the merchant's type-2/3 wraps; type-2 payment tag carries the settled bolt11 verbatim) |
| 4 | Inbox/outbox cursors, deduplication, overload handling, retry, sender recovery, and encrypted retention recover across crashes without duplicate domain commands | ✅ VERIFIED | `tests/runtime/test_nip17_inbox.py` (EOSE-cursor, dedupe, crash/resume), `test_release_b_drills.py` overload battery (>300 wraps/min/relay dropped pre-decrypt and counted; >1000-row backlog drains in bounded `DRAIN_BATCH` passes; `inbox.admission.*`/`inbox.drain.*` metrics) |
| 5 | Deployed egress controls, recipient-gated relay behavior, NIP-42, and an independent Gamma client conformance run pass before the Release-B claim | ✅ VERIFIED (scripted half) | Egress: `test_release_b_drills.py` — 20-address IPv4+IPv6 matrix (loopback/private/link-local/CGNAT/metadata 169.254.169.254/reserved/multicast/unspecified) rejected at validate AND at the dial boundary (`_open` spy asserts zero dials) + reconnect revalidation on DNS flip. Gated relay: `evidence/conformance/nostrrelay-env.json` — anon/stranger REQ yields nothing; authed allowlisted merchant REQ serves wraps + EOSE (nostrrelay `requireAuthFilter` + merchant-npub allowlist; kind-4-only p-gate compensated). NIP-42: real challenge→kind-22242→authed REQ roundtrip; oversize/foreign challenges never signed. Paid-write: negative OK → `payment-required` surface, never paid (D-27). External client: `plebeian-matrix` — see below. |

## Independent external-client run (GAM-05, D-29..D-35)

- **Client:** `PlebeianApp/market` @ `4bc7f8c0c73ae4ba2ff2a78f0c66d28347d1c1ce`
  (HEAD re-verified at run time — matches pin). Tooling: bun `1.3.11`,
  `nak serve` (`nak version` → `debug`, unversioned Go build).
- **Real-checkout run (digital):** `publishOrderWithDependencies` — the
  literal checkout path — produced the recipient-only kind-1059 wrap →
  extension intake → `orders` row `protocol='gamma'` →
  `awaiting_payment` → type-2 payment request dual-copy → settled →
  `confirmed` → type-3 status wraps. Payment leg: merchant kind-0
  `lud16` → loopback LNURLp shim → the order's own bolt11 → FakeWallet
  settlement (no real sats — D-31).
- **Strict-rumor run:** Plebeian's own `nip17OrderTransport.ts` +
  `nip17Relays.ts` resolved BOTH kind-10050 sets and published sender +
  recipient wraps; `relay_publications` shows `delivery_copy` rows in
  both classes for the type-2 and type-3 intents; the buyer unwrapped
  the merchant's type-2 via `nip17OrderRead.ts` and the embedded bolt11
  matched the settled invoice exactly.
- **Physical run:** Plebeian's opaque newline `address` → extension
  intake rejected pre-reservation (`invalid-shipping-destination`) and
  the D-22 `status=rejected` type-3 reply published dual-copy —
  asserted, not skipped.
- **Known-delta register (D-32, 7 entries):** `no-sender-copy`,
  `public-order-events-unread`, `order-info-envelope`,
  `opaque-address-physical-rejected`, `payment-path-lnurlp-shim`,
  `real-checkout-app-relay-only`; `detail-page-item-uses-event-id` added
  from the 2026-10-13 live run. Full text + evidence refs:
  `tests/conformance/README.md` + `evidence/conformance/plebeian-matrix.json`.

## Spec amendment (D-33)

`docs/technical-specification.md` §21 decision **30** records the
Release-B §9.5 disposition verbatim — in-code egress checks + documented
operator egress requirement (PINS.md §8) + self-hosted gated-relay
evidence satisfy Release-B conformance; OS/container egress policy
remains an operator deployment responsibility. §9.5 carries the
cross-note. Checkpoint selection: `locked-d33` (first-listed option under
`auto_advance`); `strict-95` not taken (rejected by CONTEXT — the
conformance env cannot ship an OS-level egress policy).

## Manual-only items (per 03-VALIDATION.md — never a scripted pass)

- **Live `plebeian.market` public-relay smoke** — Checklist authored at
  `tests/conformance/README.md` §"Live `plebeian.market` smoke
  checklist". **Status: PASS — full checkout/intake/payment/settlement
  verified 2026-10-13** (runs below; was deferred 2026-10-12, now
  executed).
  - **2026-10-09 — steps 1–2 (listing only): pass.** The merchant
    profile ("Infinite Markets", `npub10rtl…779uxx`) and its kind-30402
    listings (name, image, sat price, stock) render on
    `plebeian.market`.
  - **2026-10-13 — steps 1–4 complete: PASS.**
    - Date/host: 2026-10-13 ~04:23–04:29 UTC, host
      `https://schedulerlnbits.exe.xyz` (extension v0.6.3, local
      `http://127.0.0.1:5000`).
    - Merchant: `npub10rtlr7g97dyctxn6xwyp9x9may4k32mmtk9hyae34vt96yard5fs779uxx`
      (pubkey `78d7f1f9…36d13`), `inbox_state=active`, inbox relay
      `wss://nos.lol` (`both`), discovery relays include
      `relay.damus.io`, `relay.nostr.net`, `relay.primal.net`.
    - Product: kind-30402 "Node Report — 2026 Lightning Analysis
      (Demo)", d-tag `8ac4ffff390d405198d1a71c64647853`, event
      `9636c82b…8c58`, naddr
      `naddr1qqsrsctrx3nxvenxxvunqep5xq6nzwfcvsckzde3vvmrgd35xuur2vczypud0u0eqhe5npv60gecsy5ch05jk69t0dwckunhxx43vhgn5dk3xqcyqqq8dssgztyyp`
      — 210 SAT, digital delivery.
    - Buyer: ephemeral key `npub1qp9kxaq4…366uu2`
      (`004b6374…5e0388`); buyer kind-10050 published to `wss://nos.lol`
      + `wss://relay.plebeian.market` before ordering.
    - Flow: Playwright drove live `plebeian.market` — private-key login,
      product added from the merchant profile card (d-tag path), cart →
      checkout, shipping "International Tracked" selected, digital
      email contact, order published. Public kind-16 order marker
      `1e2a712b…` (type-1, order `df79551f-c755-4b58-aadb-e6e9460fec10`)
      confirmed on `nos.lol`, `relay.nostr.net`, `relay.plebeian.market`,
      `relay.damus.io`.
    - Wrap evidence: kind-1059 `f2f378dd273d0142` (p=merchant) received
      via `wss://nos.lol` 04:27:28 →
      `inbox_events.processed_state='processed'` (rumor
      `30470a88…0de2ab`, kind 16, type 1).
    - Intake: `orders` row `afa3499b59fe416680399ba0aaab166f`,
      `protocol='gamma'` — authoritative pricing applied:
      `total_sat=210` vs buyer-claimed `buyer_amount_sat=24216`
      (type-2 content explicitly notes the recalculation). State
      `awaiting_payment` → invoice created via `begin_saga`.
    - Type-2 payment request: rumor `49e3b228…5fee`; wrap
      `9a59aa732253…8b6b8b` `delivery_copy=recipient` → accepted on
      `nos.lol`, `relay.nostr.net`, `relay.plebeian.market` (buyer's
      declared 10050 relays); sender copy `b4eee6a4f9ec…01933` →
      `nos.lol` — both `delivery_copy` classes recorded. Buyer-side
      unwrap confirmed `['payment','lightning','lnbc2100n1p4vmve5…']`.
    - Settlement: bolt11 paid internally through the host's superadmin
      wallet (`checking_id internal_5b6803c8…88e839` = order
      `payment_hash`); `payments.status='settled'`; order →
      `state='confirmed'` at 04:28:08, `shipping_state='not_required'`.
    - Type-3 status: wrap `450ce39d30745a92…` `delivery_copy=recipient`
      → accepted on all three buyer relays; sender copy
      `697b7c0c8e9c…da60` → `nos.lol`. Buyer-side unwrap: rumor kind 16
      `type=['3']`, `status=['confirmed']`, order tag matches the
      plebeian external id.
    - Known-delta register applies verbatim: `no-sender-copy` (buyer
      wrap recipient-only), `public-order-events-unread`
      (`receipt_verified=0` on the order row),
      `order-info-envelope`, `real-checkout-app-relay-only` (wrap
      posted via plebeian's connected relay set, reached merchant
      through `nos.lol`), `payment-path-lnurlp-shim` not applicable —
      real invoice paid with real LNbits internal settlement.
    - Additional live delta observed (recorded for Phase 5/backlog
      triage, not a checklist failure): when checkout is initiated from
      the product **detail page**, plebeian emits
      `item=30402:<merchant-pk>:<event-id>` (route-param id) rather than
      the d-tag; intake correctly rejected that attempt
      (`inbox_events` `63eab2a9…0df2`, `reject_reason='unauthorized'`
      from the product-not-found 404 code) and the D-22
      `status=rejected` type-3 reply wrap `d41185e8bf68…` was delivered
      to the buyer. Reordering via the product card (NDKEvent path →
      d-tag) succeeded end-to-end.
    - Merchant kind-0 carries no `lud16`, so plebeian could not render
      an invoice itself ("Creating payment request without payment
      method") — the authoritative bolt11 arrived via the type-2 wrap
      as designed. Merchant kind-10050 was not observed on the checked
      public relays; intake still functions since wraps arrive on the
      configured inbox relay `nos.lol`.

## Verification commands run

- `make host && make verify-runtime && make verify && make lint` — see
  `evidence/manifest.json` for the recorded suite result (this run's
  profile is darwin-arm64 + SQLite, advisory; the blocking matrix is
  per PINS.md §2).
- `cd tests/conformance && ./run_matrix.sh matrix` — exit 0; three
  evidence entries under `conformance.release_b` in
  `evidence/manifest.json`; zero unrecorded divergences.

## Current closeout override — 2026-10-11

The preceding observations are historical. Current acceptance is **gaps_found**:
shared commerce has F1–F3 boundary defects, no-route retries stop early (F5), and
the 1,000-row same-merchant/relay admission bound is not implemented (F6). A
bounded drain of a larger multi-scope queue is not proof of bounded admission.
The temporary same-scope probe admitted row 1,001; earlier overload claims must
not be read as closing that invariant.

Phase 5 owns permanent regressions and repairs. Live UAT item 17 (live
`plebeian.market` public-relay smoke) was executed and passed 2026-10-13 —
see the manual-items section for wrap/order/settlement evidence. The earlier
listing-only caveat no longer applies; a real LNbits invoice was settled via
the merchant wallet on the live host (internal payment within the host, no
external funds moved).
