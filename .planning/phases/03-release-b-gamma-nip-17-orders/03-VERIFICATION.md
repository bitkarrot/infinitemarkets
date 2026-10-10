---
phase: 03-release-b-gamma-nip-17-orders
verified: 2026-09-29
status: passed-with-manual-items
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
- **Known-delta register (D-32, 6 entries):** `no-sender-copy`,
  `public-order-events-unread`, `order-info-envelope`,
  `opaque-address-physical-rejected`, `payment-path-lnurlp-shim`,
  `real-checkout-app-relay-only`. Full text + evidence refs:
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

- **Live `plebeian.market` public-relay smoke** — checklist authored at
  `tests/conformance/README.md` §"Live `plebeian.market` smoke
  checklist". **Status: PARTIAL — listing verified, checkout/order
  pending.** Record results here when run (date, host, merchant npub,
  product naddr, order id, wrap ids, pass/fail, notes).
  - **2026-10-09 — steps 1–2 (listing only): pass.** The merchant
    profile ("Infinite Markets", `npub10rtl…779uxx`) and its kind-30402
    listings (name, image, sat price, stock) render on
    `plebeian.market`. Steps 3–4 (live checkout, order intake, payment
    request, settlement, status wraps) were not run, so no order id or
    wrap ids exist for this run.

## Verification commands run

- `make host && make verify-runtime && make verify && make lint` — see
  `evidence/manifest.json` for the recorded suite result (this run's
  profile is darwin-arm64 + SQLite, advisory; the blocking matrix is
  per PINS.md §2).
- `cd tests/conformance && ./run_matrix.sh matrix` — exit 0; three
  evidence entries under `conformance.release_b` in
  `evidence/manifest.json`; zero unrecorded divergences.
