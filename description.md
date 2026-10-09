# Infinite Markets

**One inventory, two rails.** A classic web shop with Lightning checkout and a
native Nostr commerce channel with encrypted (NIP-17) ordering — built as an
[LNbits](https://github.com/lnbits/lnbits) extension.

Web and Nostr orders flow through the same pricing, reservation, invoice, and
settlement pipeline — no duplicate invoices, no double allocation, and relay
delivery is never mistaken for payment truth.

## Features

- Merchant-defined categories, curated collections, shipping options, and
  visibility flags (`on-sale`, `hidden`, `pre-order`, draft)
- Public storefront with category/collection browsing, price filters,
  sorting, and private per-order links
- Lightning checkout: quote → reservation → invoice → settlement, with
  late-settlement reconciliation
- Nostr-native ordering: NIP-17 encrypted DMs, recipient-gated relays,
  NIP-42 relay auth, and a merchant Messages center
- NIP-89 handler routing — a Nostr client can deep-link straight into
  product and collection pages
- Buyer accounts: NIP-07 "Sign in with Nostr" and email magic links with
  unified order history and identity linking
- Merchant theme system: presets, four layouts, brand name/logo, hero,
  footer, and point-and-click Fine-tune for colors, corners, and spacing —
  with WCAG contrast gates and a shopper dark/light toggle
- Embeddable shop: a JavaScript component that renders product cards into
  any static page (including the WebPages extension), an in-page product
  modal mode, and a chrome-free iframe embed
- Email notifications for order events with per-address test sends,
  owner-only redacted queue previews, and terminal-history cleanup
- Publications outbox with per-relay delivery evidence, live relay catalog
  reconciliation, filters/sorting, prune control, and fresh kind-5 deletion
  reissues for stale relay copies
- Merchant Nostr profile controls for avatar, bio, header image, NIP-05 and
  Lightning address, plus explicit owner-only store-key reveal
- Messages show counterparty names/NIP-05/avatars with nostr.at links when a
  verified kind-0 profile is available from configured relays
- CSV/JSON product catalog upload with preview; imports land as hidden drafts for
  merchant review and normal Catalog publication (including size options).
  There is no old-order reconciliation, cutover, or physical stock-count gate;
  overlapping inventory with another store is the operator's responsibility

## Links

- Source, issues and releases:
  https://github.com/bitkarrot/infinitemarkets
- Demo video (~3.5 min):
  https://github.com/bitkarrot/infinitemarkets/blob/main/docs/assets/infinitemarkets_demo.mp4

Created by [bitkarrot](https://github.com/bitkarrot) · MIT licensed
