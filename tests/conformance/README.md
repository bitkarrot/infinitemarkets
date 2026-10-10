# Release-B Conformance Suite (GAM-05)

Scripted external-conformance evidence for the Gamma NIP-17 order
channel. Two environments, one command:

```
cd tests/conformance && ./run_matrix.sh matrix
```

Runs (in order) the **nostrrelay reference gated-relay environment**,
the **runtime drill suite**, and the **Plebeian external-client matrix**.
Each battery writes a durable JSON report under `evidence/conformance/`;
`matrix` then merges per-artifact entries into `evidence/manifest.json`
(`conformance.release_b`) and `evidence/REPORT.md` (delimited section).
Any probe failure — or an unrecorded divergence — exits non-zero.

Individual batteries: `./run_matrix.sh env | drills | plebeian`.

## Environments

### nostrrelay reference gated inbox (`nostrrelay_env.py`)

Boots the pinned LNbits host in-process with the real `infinitemarkets`
extension plus a copy of the LNbits `nostrrelay` extension (source:
`.cache/gsd-tmp/nostrrelay`, override with `NOSTRRELAY_SRC`; the checkout
is READ-ONLY — the driver copies it into a throwaway extensions dir).
Three relays are provisioned through nostrrelay's admin API:

| relay | config | purpose |
|---|---|---|
| `gated` | `requireAuthFilter=true`, `isPaidRelay=true`, `costToJoin=21`, `createdAtDaysPast=3`, account allowlist = merchant npub only | the §9.3 recipient-gated inbox — nostrrelay's native p-tag gate is kind-4-only, so kind-1059 read privacy comes from NIP-42 auth + the account allowlist; `createdAtDaysPast>=2` is required or NIP-59's backdated wraps are rejected |
| `open` | no auth, free | open kind-1059 writes (buyer leg) |
| `paywall` | `isPaidRelay=true`, no allowlisted account | the D-27 paid-write surface (negative OK `This is a paid relay: '<id>'` → `payment-required`, surfaced, never paid) |

Probes: `gated_anon_req` (anonymous REQ → AUTH challenge, no events, no
EOSE), `gated_stranger_req` (authed non-allowlisted REQ → paid-relay
NOTICE, no events), `gated_merchant_req` (authed allowlisted merchant →
wraps + EOSE; write OKs matched by event id), `open_write_accepted`,
`gated_paid_write` (negative OK classified `payment-required`),
`extension_gated_inbox` (real inbox session answers AUTH and re-issues
its REQ post-auth), `extension_open_inbox`, `paid_publish_surface`
(durable `relay_publications` rejection carrying the paid-relay reason).

### Plebeian external-client matrix (`plebeian_matrix.py`)

Drives a **pinned** clone of `PlebeianApp/market`
(`master@4bc7f8c0c73ae4ba2ff2a78f0c66d28347d1c1ce` — HEAD re-verified at
run time; drift is recorded and fails the gate) through `bun`, against
`nak serve` (in-memory NIP-01 relay) + the real extension booted
in-process (FakeWallet).

Runs:

- **real-checkout (digital)** — `publishOrderWithDependencies`
  (`src/publish/orders.tsx`, the literal checkout path): recipient-only
  kind-1059 wrap → `orders` row `protocol='gamma'` →
  `received→awaiting_payment` → type-2 payment request published
  dual-copy → payment settled → `confirmed` → type-3 status wraps.
- **strict-rumor** — `publishNip17OrderTransportMessage`
  (`src/lib/orders/nip17OrderTransport.ts` + `nip17Relays.ts`): resolves
  BOTH kind-10050 relay lists and publishes sender + recipient wraps;
  `relay_publications` asserts `delivery_copy` rows in both classes.
- **real-checkout (physical)** — full shipping address → Plebeian's
  newline-joined opaque `address` tag → extension rejects the intake
  pre-reservation (`invalid-shipping-destination`) and publishes the
  D-22 `status=rejected` type-3 reply — asserted, never skipped.
- **buyer read-back** — `unwrapNip17OrderMessages`
  (`src/lib/orders/nip17OrderRead.ts`) proves the merchant's type-2/3
  wraps are readable on the wire even though the live UI never reads
  them.

### Payment path (RESEARCH OQ2 — resolved)

Merchant kind-0 carries `lud16`; the matrix resolves it through a
loopback **LNURLp shim** (`matrix@conf.test` → `http://127.0.0.1:<port>`)
whose callback returns the order's own LNbits invoice — the
lud16→LNURLp→bolt11 read path is exercised literally, and payment is
settled through `FakeWallet` (no real sats — D-31). The strict-rumor run
pays the bolt11 the merchant's type-2 wrap actually carried. Both are
recorded as the payment-path resolution.

### Tooling

- `bun` (runs the Plebeian driver — dev/test tooling only, never a
  runtime dep)
- `nak` (`nak serve` local relay — dev/test tooling only)
- Pinned clone location: `$PLEBEIAN_SRC`, else `/tmp/plebeian-market`,
  else `.cache/gsd-tmp/plebeian-market` (cloned on demand). The driver TS
  (`tests/conformance/plebeian/driver.ts`) is staged into the clone's
  untracked `.conformance/` dir at run time — the clone stays clean.

## Known-delta register (D-32)

Every literal divergence between Plebeian's live checkout and the strict
rumor model is recorded — never papered over. The matrix FAILS if any
named divergence is missing. Current register (evidence refs live in
`evidence/conformance/plebeian-matrix.json`):

1. **no-sender-copy** — the live checkout publishes a single
   recipient-only kind-1059; no buyer sender copy exists. The strict
   transport (`nip17OrderTransport.ts`) publishes both.
2. **public-order-events-unread** — the signed public kind-16 type-1
   marker, public type-2 lud16 payment request, and kind-17 receipt are
   invisible to the NIP-17 inbox (kind-1059 `#p` filter);
   `receipt_verified` may stay false — recorded, not fixed.
3. **order-info-envelope** — the type-1 rumor carries
   `subject='order-info'` + a `name` tag; tolerated (subject is not
   value-enforced).
4. **opaque-address-physical-rejected** — the `address` tag is a
   newline-joined opaque string; physical orders are rejected
   pre-reservation with a `status=rejected` reply (D-22 path).
5. **payment-path-lnurlp-shim** — lud16 is resolved via a loopback LNURLp
   shim returning the order's own invoice; settlement is FakeWallet (no
   real sats, D-31).
6. **real-checkout-app-relay-only** — the live checkout posts the private
   wrap to the connected app relay, not the merchant's resolved
   kind-10050 set (the strict transport does resolve it; both coincide
   on `nak` in this env).

## Live `plebeian.market` smoke checklist (manual-only, D-30)

The public-relay run is a MANUAL gate artifact — it is never part of the
scripted pass. Record results into
`.planning/phases/03-release-b-gamma-nip-17-orders/03-VERIFICATION.md`.

1. Deploy the extension on a public LNbits host; create the merchant,
   import the merchant nsec, configure ≥1 public inbox relay + ≥1 public
   discovery relay, enable the Gamma inbox (await `inbox_state=active`
   with a durable kind-10050 OK).
2. Publish a digital product (delivery content set) reachable from a
   public relay; confirm the kind-30402 listing is served.
3. On `plebeian.market`, locate the product/stall, add to cart, check
   out with a digital-delivery contact (email).
4. Evidence to collect: the kind-1059 wrap id on the merchant inbox
   relay; `inbox_events` row `processed_state='processed'`; `orders` row
   `protocol='gamma'`; type-2 payment-request `relay_publications` rows
   in both `delivery_copy` classes; settlement → `confirmed` → type-3
   status wraps.
5. Record: date, host URL, merchant npub, product naddr, order
   external id, wrap ids, pass/fail + notes. Expected divergences: the
   known-delta register above applies verbatim.

### Run log

| Date | Steps covered | Result | Notes |
|---|---|---|---|
| 2026-10-09 | 1–2 (listing only) | pass | Merchant profile ("Infinite Markets", `npub10rtl…779uxx`) and its kind-30402 listings (name, image, sat price, stock) render on `plebeian.market`. Checkout and order steps 3–4 not run; no order id or wrap ids to record. |

## D-33 note

§9.5's literal "OS/container egress policy" is narrowed for Release-B
conformance per the locked D-33 disposition — see
`docs/technical-specification.md` §21 decision 30: in-code egress checks
(drill-proven at the dial boundary in `test_release_b_drills.py`), a
documented operator egress requirement (PINS.md), and the self-hosted
gated-relay evidence above satisfy the Release-B claim; OS/container
egress policy remains an operator deployment responsibility.
