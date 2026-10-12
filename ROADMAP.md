# Roadmap

Forward-looking plan for infinitemarkets. The upstream protocol —
[OpenMarketsFoundation/specification](https://github.com/OpenMarketsFoundation/specification)
(draft, forked from GammaMarkets/market-spec) — is still in flux, so this
roadmap tracks two things: committed next work, and alignment items for the
parts of the spec we don't yet implement. Completed history lives in
[`.planning/ROADMAP.md`](.planning/ROADMAP.md); deliberate divergences already
on record are numbered in `docs/technical-specification.md` §21 ("D-n" below).

## Current spec coverage

Already implemented and shipping: kind-30402 products (title, price +
frequency, type, visibility, stock, summary, spec, image, weight, dim,
location, geohash, `t` categories, `a` parent/collection refs,
`shipping_option` + `extra-cost`), kind-30405 collections, kind-30406
shipping options, kind-0 profile with `payment_preference`, NIP-89
31989/31990, kind-10050 inbox relays, NIP-17 order messaging (kind-16
type 1–4, kind-17 receipts, kind-14 DMs), and kind-5 tombstones.

## Next

### 1. Optional integrations with other Nostr extensions — inventory and shipping

Let merchants optionally source inventory and shipping from external
Nostr-native providers instead of only the local catalog.

- **Shipping:** allow products/collections to reference kind-30406 options
  published by third-party providers (delivery companies, DVMs) — the spec
  explicitly permits merchant *or* third-party shipping publishers. This
  revisits decision D-18 (same-merchant references only in v1); the blocker
  is that mutable third-party pricing can't be quoted authoritatively, so the
  integration needs a re-quote/verify-at-order-time policy rather than
  trusting the referenced event.
- **Inventory:** optional stock sync from an external nostr inventory
  source, so `stock_on_hand` reflects a shared source of truth rather than
  only the extension's own ledger. Needs a defined authority model (who
  wins on conflict) and must keep the existing reservation/settlement
  invariants — external stock can inform availability but cannot bypass
  local reservation safety.

### 2. Shipping imports and post-import binding

Catalog import currently creates hidden draft products with only the CSV
stock number — imported products are not bound to any shipping method or
existing inventory structure.

- Import shipping options alongside products (extend the native CSV format
  and/or a shipping CSV/JSON source), projected as draft 30406 options.
- Bind imported products to existing shipping methods during or after
  import — e.g. an import-time/default shipping assignment and a bulk
  "apply shipping option" action on the draft review surface, so a
  physical product is orderable when published without manual per-product
  setup.
- Same treatment for collections' `shipping_option` refs where the source
  file expresses them.

### 3. Continuous UI/UX usability improvements and security updates

Standing, non-gated workstream — no completion state, folded into every
release rather than shipped as a phase.

- Storefront and admin usability: checkout flow friction, Catalog/Orders/
  Messages workspace ergonomics, mobile/responsive polish, accessibility
  and contrast, empty/loading/error states.
- Security maintenance: dependency and host-pin updates, relay/egress
  hardening, abuse/rate-limit tuning, periodic review of the ASVS-1 threat
  register, and conformance re-runs when the host or SDK pins move.

### 4. Exploratory: Wasm extension runtime (contingent on LNbits core)

Longer-term investigation, not committed work. LNbits extensions are
native Python today with full host privilege; a Wasm-sandboxed extension
model would materially improve the security posture (isolated file/socket/
DB access, no host internals). Feasibility is entirely contingent on
upstream LNbits providing a Wasm extension runtime and a host-API surface —
track LNbits core and revisit if an extension sandbox lands. Known porting
blockers to solve if it does: `nostr-sdk` FFI bindings, direct SQL access,
background task/invoice-listener lifecycle, and SMTP egress all need
Wasm-safe host-call equivalents.

## Spec alignment backlog

Gaps between the implementation and the OpenMarkets spec, ordered by likely
value. None are mandatory as whole features — the spec's required set
(30402 products, 30405 collections, merchant preferences, NIP-17 ordering)
is fully implemented. The **Spec status** column shows where each row sits:
`optional` (a MAY component or MAY tag), `conditional` (a REQUIRED tag only
inside an optional kind we already publish), or `recommended` (a SHOULD).

| Item | Spec ref | Spec status | Current state |
|---|---|---|---|
| Product reviews (kind 31555) | §5 | optional | Not implemented. Merchant-side display/ingest of reviews on own 30402s is the useful first slice; buyer review authoring is secondary. |
| NIP-37 drafts | §3 Drafts | optional | Local drafts only; NIP-37 deferred by D-13 (needs kind-10013, NIP-65 write relays, expiration, deletion semantics). |
| Service-assisted / automatic payment flow | §4 type-2, §6 | optional | Merchant-initiated type-2 only; inbound type-2 is rejected (`inbound-type2-unsupported`). `payment_preference` hardcoded `manual` (D-7). ecash/lud16 preferences and kind-10019 mint info are unimplemented. |
| `price-distance` on 30406 | §3 | optional tag | `price-weight` and `price-volume` are emitted; `price-distance` is not modeled. |
| `image` sorting-order element | §3 30402 | optional element | Images are emitted pre-sorted as `["image", url, dims]`; the optional third sorting-order element isn't emitted. |
| `country`/`region` tag shape on 30406 | §3 | **conditional** | `country` is REQUIRED once you publish 30406 (we do); `region` is optional. Spec shows one tag carrying multiple codes (`["country","US","CA"]`); we emit one tag per code. If the spec's array reading is confirmed this becomes a must-fix tag shape — see watch items and PR #13. |
| Subscriptions / pre-order purchase path | §3 `price` frequency, `visibility` | optional | Published for discovery (D/W/Y frequency tags) but not purchasable (D-14). |
| NIP-10 reply threading on order messages | §6 notes | recommended | Spec says threading "should follow" NIP-10 when replies are needed. Not implemented; conversations thread internally by sender-hash instead. |

## Watch items (spec in flux)

> **Note on ambiguity:** the upstream spec is a draft and internally
> inconsistent in places — `country`/`region` are documented as an "array"
> inside a single tag while our emit-per-code reading is defensible, and
> collections (30405) appear under *both* required and optional components.
> These are tracked here as watch items, not treated as conformance bugs;
> neither side should churn until the upstream text settles.

Re-verify when the upstream spec next changes:

- Required-vs-optional status of collections (30405) — we treat them as
  required per D-20; the spec lists them under both required and optional.
- `visibility`/`type` defaulting rules and any new 30402 tags.
- Payment-preference semantics (`payment_preference` values, kind-10019
  handling, NIP-89 recommendation requirements) before enabling non-manual
  modes.
- Any tag-shape changes on `shipping_option`, `image`, `country`, `region`
  before shipping import/export format v2.

## Potential specification changes that may impact roadmap

Open PRs on `OpenMarketsFoundation/specification` as of 2026-10-11. All are
experimental proposals stacked on PR #1 (repo reorganization; `SPEC.md`
remains a byte-identical compatibility snapshot) — track, don't implement
yet.

| PR | Proposal | Impact on this repo |
|---|---|---|
| [#12](https://github.com/OpenMarketsFoundation/specification/pull/12) Private structured messages (kind 1327) | **Highest impact.** Replaces kind-16/17 numeric types with a kind-1327 envelope and named types (`payment_request`, `payment_proof`, `payment_confirmed`, `payment_rejected`, refund, fulfillment, shipping) — the numeric kinds collide with NIP-18/NIP-25. | Our entire rumor layer (`order_messages`, inbox dispatch, dual-copy outbox) is built on 16/17 type 1–4. If merged: dual-read legacy 16/17 + 1327 per its own migration guidance; named types also cover refund/fulfillment states we don't model. |
| [#10](https://github.com/OpenMarketsFoundation/specification/pull/10) Orders (kind 32122) | Public payment/order lifecycle events (payment, ack, settle, cancel, nack) + private negotiation via signed child events; trade-key privacy; hooks into arbitration. | A parallel order-lifecycle lane on top of (not replacing) the private flow. Interacts with #12. Large surface — reassess scope if it stabilizes. |
| [#13](https://github.com/OpenMarketsFoundation/specification/pull/13) Composable destination constraints | `destination_schema` marker + typed `destination` include/exclude selectors on 30406 (country, ISO subdivision, postal exact/prefix), with union/subtraction and fail-closed semantics. | Directly shapes roadmap items 1–2: our `shipping_options` model (countries + regions) and emit-per-code tags predate this grammar. It also explicitly addresses the `country`/`region` compatibility flagged in watch items — may resolve that ambiguity. Gate shipping-import format v2 on this. |
| [#16](https://github.com/OpenMarketsFoundation/specification/pull/16) LNURLcash (LUD-25) payment medium | `["payment","lnurlcash",…]` options in type-2 payment requests and kind-17 receipt proofs; rides under the lud16/LNURL family, no `payment_preference` change. | Affects the non-manual-payment backlog item: receipt verification would need a redeem-before-confirm step for bearer notes (never treat the note as settlement). |
| [#9](https://github.com/OpenMarketsFoundation/specification/pull/9) Marketplace listing extension | Generic NIP-99 listing tags: `autoAccept`, negotiability, `quantity`, duration limits, deposit, min payment, cancellation policy, promoted `t` profiles. | New optional 30402 tags if adopted; `autoAccept`/`cancellationPolicy` interact with our order state machine and D-14. Other proposals (#15, #17) build on these field names. |
| [#14](https://github.com/OpenMarketsFoundation/specification/pull/14) Offer-code commitments | `["offer","1","<sha256>"]` on 30402 — client-verifiable percentage discounts via committed secret codes, no registry. | Checkout pricing + product schema changes if adopted; experimental, percentage-only v1. |
| [#15](https://github.com/OpenMarketsFoundation/specification/pull/15) Event markets | NIP-52-backed markets (kind 30409/3841/30410) assigning existing 30402s to dated occurrences with per-occurrence pickup allocations. | Optional lane; would split stock accounting into ordinary vs pickup allocations if ever adopted. |
| [#17](https://github.com/OpenMarketsFoundation/specification/pull/17) Bookings (kind 1331) | Time-based purchases (tables, rooms, services) via kind-1331 rumors; bookable NIP-99 listings using #9's `quantity`/`minDuration`/`autoAccept`. | New vertical; adjacent to the deferred subscriptions/pre-order path (D-14) but a different protocol surface. |
| [#11](https://github.com/OpenMarketsFoundation/specification/pull/11) Marketplace auctions | kind-30421 auction events + kind-1023 bids/1024 completion on NIP-99 listings. | Optional sale mechanism; reuses the payment lifecycle. Low priority for a fixed-price storefront. |
| [#8](https://github.com/OpenMarketsFoundation/specification/pull/8) Arbitration services | kind-30303 arbiter ads + kind-17388 policy/method events; escrow-backed settlement (EVM examples). | Settlement-lane optionality; conflicts with the "extension never spends" policy (D-3) if escrow were ever in scope. |
| [#7](https://github.com/OpenMarketsFoundation/specification/pull/7) Accommodation profile | Lodging profile tags on NIP-99 listings (check-in/out, H3 `g` indexing). | Vertical profile — not applicable to a goods storefront; shows the promoted-tag convention to mirror. |
| [#1](https://github.com/OpenMarketsFoundation/specification/pull/1) Spec repo reorganization | `SPEC.md` compatibility snapshot + pillar/lane file structure; no semantic changes. | Doc anchors only — update links/references when it merges; everything else stacks on it. |

(PRs #2–#6 are closed earlier drafts of #7–#11.)
