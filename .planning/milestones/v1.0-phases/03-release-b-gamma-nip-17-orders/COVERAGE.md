# API Coverage — Nostr relay protocol + nostr-sdk 0.44.8 + Gamma/Plebeian client surface

> Full coverage by default. Opt-outs are explicit, reasoned decisions.
> Phase 3 integrates three external surfaces: the pinned `nostr-sdk` 0.44.8
> client API, the Nostr wire protocol as deployed on arbitrary relays (incl.
> LNbits `nostrrelay` and `nak serve`), and the Gamma order DTO surface as
> implemented by the independent Plebeian client (`PlebeianApp/market`
> @ `4bc7f8c0c73ae4ba2ff2a78f0c66d28347d1c1ce`).

## nostr-sdk / wire-protocol transport

| capability | decision | reason |
|---|---|---|
| Client connect / relay add-remove | INTEGRATE | |
| REQ subscriptions + EOSE + per-session cursors | INTEGRATE | |
| EVENT publish + OK classification | INTEGRATE | paid-relay negative OK surfaces `payment-required` |
| CLOSED / NOTICE handling | INTEGRATE | |
| NIP-42 AUTH challenge (kind-22242) | INTEGRATE | post-AUTH REQ re-issue covers require-auth filters |
| NIP-17 wrap/unwrap (kind-1059 gift wrap, kind-13 seal, unsigned rumor) | INTEGRATE | |
| NIP-59 timestamp randomization | INTEGRATE | exercised inside SDK wrap; nostrrelay `created_at_days_past` window evidence in conformance env |
| kind-10050 inbox-relay declaration publish + peer resolution | INTEGRATE | |
| kind-0 merchant profile (`lud16`) | INTEGRATE | payment-path resolution for real-client checkout |
| Filter `kinds`/`#p`/`since` | INTEGRATE | |
| Relay-target egress screening | INTEGRATE | syntactic + DNS private-range reject at validate/connect/reconnect |
| NIP-11 relay metadata reads | OPT-OUT | not needed — capability is negotiated by probe outcomes (AUTH challenge, negative OK), not advertised docs |
| NIP-65 relay list metadata | OPT-OUT | inbox declaration is kind-10050 per NIP-17; NIP-65 adds no routing information for this flow |
| COUNT / NEG-entropy sync / ephemeral kinds | OPT-OUT | out of scope — subscription + cursor admission already covers durable intake |
| Relay management/admin RPCs | OPT-OUT | operator concern; extension only publishes/subscribes |

## Gamma order messaging (kind-16/17/14 DTO surface)

| capability | decision | reason |
|---|---|---|
| kind-16 type-1 order intake → canonical checkout pipeline | INTEGRATE | |
| kind-16 type-2 payment request/response | INTEGRATE | |
| kind-16 type-3 status/shipping | INTEGRATE | |
| kind-17 receipt | INTEGRATE | settlement-independent semantics |
| kind-14 DM threading | INTEGRATE | |
| Dual sender+recipient copy publishing to declared relays | INTEGRATE | |
| Rejected-intake record + `status=rejected` reply | INTEGRATE | |
| Sender-copy requirement on the peer side | OPT-OUT | Plebeian publishes no sender copy — recorded known-delta `no-sender-copy`; extension cannot force peer behavior |
| Public (unsigned/plaintext) kind-16/17 events on the wire | OPT-OUT | by protocol design the inbox admits only NIP-17 wraps; recorded known-delta `public-order-events-unread` |
| `subject='order-info'` + `name` tag envelope | INTEGRATE | tolerated variant, recorded delta |
| Opaque freeform `address` (physical orders) | OPT-OUT | physical shipping not supported on this surface — rejected pre-reservation with rejected reply (delta `opaque-address-physical-rejected`) |
| NIP-15/NIP-04 literal legacy interop | OPT-OUT | Live legacy ordering dropped from v1; Phase 4 retains file-based catalog import only |

## Plebeian client surface (conformance target)

| capability | decision | reason |
|---|---|---|
| `publishOrderWithDependencies` real-checkout digital order | INTEGRATE | |
| `nip17OrderTransport.ts` / `nip17Relays.ts` strict dual-copy transport | INTEGRATE | |
| `nip17OrderRead.ts` merchant-side wrap read | INTEGRATE | |
| `lud16` lightning-address payment resolution | INTEGRATE | via loopback LNURLp shim → order bolt11; FakeWallet settle with no-real-sats caveat (delta `payment-path-lnurlp-shim`) |
| Plebeian app-level relay defaults | OPT-OUT | app publishes to its own relay set; recorded delta `real-checkout-app-relay-only` |
| Live `plebeian.market` public-relay smoke | OPT-OUT | manual-only checklist authored in tests/conformance/README.md — outcome lands in 03-VERIFICATION.md when executed |
