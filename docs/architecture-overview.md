# infinitemarkets — Architecture Overview (as built)

**Status:** Implementation-state document covering Releases A/B/03.1/C and
the post-release merchant operations surfaces. `technical-specification.md` is
the normative contract. Imported products are hidden drafts until explicitly
published from Catalog; the extension has no cutover or old-order
reconciliation workflow.

## 1. Component diagram

```
                                ┌────────────────── LNbits host ───────────────────┐
                                │                                                  │
   Browser (merchant)           │   ┌─────────────── infinitemarkets ───────────────┐ │
   ┌────────────────┐           │   │                                            │ │
   │ Admin SPA      │──session──┼──►│ Admin API  /api/v1/*                       │ │
   │ (Vue3/Quasar)  │  cookie   │   │  (check_user_exists → LNbits user)         │ │
   └────────────────┘           │   │      │                                     │ │
                                │   │      ▼                                     │ │
                                │   │   ┌──────────────────┐                     │ │
                                │   │   │ catalog.py       │ products,           │ │
                                │   │   │ merchant.py      │ collections,        │ │
                                │   │   │ themes.py        │ shipping, keys,     │ │
                                │   │   │ relay.py         │ relays, themes      │ │
                                │   │   └───────┬──────────┘                     │ │
   Browser (buyer, anon)        │   │           │                                │ │
   ┌────────────────┐           │   │           ▼                                │ │
   │ Public pages   │──GET──────┼──►│ views.py (server-rendered HTML)            │ │
   │ /p/{pk}/{d}    │           │   │  · nip89.py = public projections +         │ │
   │ /public/...    │           │   │    availability + rate limits              │ │
   │ /order#token   │           │   │  · themes.emit_css → scoped .gm-public     │ │
   └───────┬────────┘           │   │                                            │ │
           │ XHR                │   │ Public API /api/v1/public/* (no auth)      │ │
           └────────────────────┼──►│  · catalog reads (public projections only) │ │
           X-Order-Token header │   │  · POST /checkout                          │ │
                                │   │  · GET /order-status (bearer token)        │ │
                                │   │      │                                     │ │
                                │   │      ▼                                     │ │
                                │   │   checkout.py ──create_invoice──► LNbits   │ │
                                │   │   orders.py    (bolt11 via       payments  │ │
                                │   │   settlement.py wallet backend)  service   │ │
                                │   │      │                            ▲        │ │
                                │   │      ▼                            │ status │ │
                                │   │   Extension SQLite tables         │        │ │
                                │   │   (same LNbits DB file) ──────────┘        │ │
                                │   └───────┬────────────────────────────────────┘ │
                                └───────────┼──────────────────────────────────────┘
                                            │
              Background workers (tasks.py) │
              outbox_publisher     5s       │
              relay_manager        30s      │
              email_sender         5s       │
              reservation_expiry   30s      │
              reconciliation       60s      │
              retention_pruner     24h      │
                                            ▼
                        ┌─────────────────────────────────┐
                        │ outbox.py (durable intent queue)│
                        │  claim → render event from      │
                        │  CURRENT state → sign via       │
                        │  keystore → send → record ACK   │
                        └───────────────┬─────────────────┘
                                        │ send_to(urls)
                        ┌───────────────▼─────────────────┐
                        │ transport.py — owned Nostr      │
                        │ client (nostr-sdk), wss only,   │
                        │ converges to configured relays  │
                        └───────────────┬─────────────────┘
                                        │ outbound only (Release A)
             ┌──────────────────────────┼──────────────────────────┐
             ▼                          ▼                          ▼
      Merchant-configured        relay_publications table      Blossom/media
      public relays              (per-relay ACK evidence)      endpoints (config
      (wss://...)                                              only — for future
                                                               media uploads)
```

## 2. What's exposed to relays — plain English

**Outbound only, in Release A.** The extension owns its Nostr transport
(`services/transport.py`) — it does not depend on the `nostrclient` extension.
When a merchant edits catalog data, the change is saved to the extension's
tables and an *outbox intent* is queued. A background worker
(`outbox_publisher`, `services/tasks.py`) picks it up, rebuilds the event from
**current** domain state — never a stored snapshot, so retries can't publish
stale data — signs it with the merchant key (`merchant_keys` via the keystore),
sends it to the merchant's configured relays, and records each relay's
ACK/reject/timeout in `relay_publications`. That table is the evidence shown
in the Publications admin tab; relay delivery is never treated as state truth.

**What gets published:**

| Event kind | Content | When |
|---|---|---|
| `30402` | NIP-99 product listing (title, price, stock, images, specs, categories, shipping refs) | create/update, republished on changes |
| `30405` | NIP-99 collection (requires ≥1 active member by contract) | create/update |
| `30406` | Shipping option | create/update |
| `0` | Merchant profile (name, about, picture) | profile save |
| `31990` | NIP-89 handler info — tells clients this merchant serves `/p/{naddr}` product pages | publish |
| `5` | Tombstone / deletion request | product/collection/shipping delete |
| `30017` / `30018` | Optional NIP-15 stall + product projection | Only when a category has NIP-15 publication enabled and the merchant republishes |
| `1059` (inbound) | NIP-17 gift-wrapped buyer orders | **Live (Release B)** — the inbox listener maintains cursors in `inbox_events` on `direction=inbox|both` relays |

**What's never exposed:** orders, invoices, buyers' data, or internal state.
The nsec lives in `merchant_keys`, is used only for event signing, and leaves
the keystore only for the one-time TLS nsec import or an authenticated
merchant's explicit **Show private key** export. Blossom/media endpoints are
merchant-configurable but config-only today (no uploads yet).

## 3. How listings and orders flow within LNbits

**Catalog.** Merchant edits via the admin API → validated DTOs → extension
tables (same LNbits DB file, `infinitemarkets_*` tables) → outbox intents →
signed NIP-99 events to relays. The database is authoritative; relay events
are projections of it. Nostr clients read the relay copies; buyers read the
public pages/API, which serve public-safe projections (`nip89.py` filters out
draft, hidden, deleted, and merchant-internal fields — never raw rows).

**Catalog import.** `migration_import.py` validates local CSV/JSON uploads and
creates merchant-scoped hidden drafts with a signed import record. Prior orders
and invoice status are ignored. The admin Migration tab previews file content;
Catalog offers draft-page preview, editing, and ordinary publication. Imported
variable products publish their draft options with the parent. No cutover or
physical-count workflow runs; existing cutover schema is retained only for
older databases.

**Orders.** Buyer checks out on the public product page → `checkout.py`
reserves inventory inside a transaction → calls LNbits `create_invoice`
(bolt11 via the configured wallet backend) → order + payment rows → 201
returns a bearer token. The order-status page keeps the token in the URL
fragment (never sent in paths or queries) and polls `/order-status` with an
`X-Order-Token` header. **Payment truth comes only from LNbits payment
state — never from relay delivery.** Background workers expire stale
reservations (releasing stock), reconcile payment status, send notification
emails, and prune retained data on fixed intervals.

**Deletion.** Soft-delete in the DB → a kind-5 tombstone is published so the
relay copy stops advertising the item — the row is kept for order and audit
history. `Publications → Check relays` verifies current relay copies without
mutating them; if a relay still serves a deleted address, **Re-request
deletions** queues a fresh kind-5 event through the outbox. Relays and clients
may still ignore NIP-09, so the check is the audit tool rather than a delete
command.

## 4. Post-03.1 surfaces (ad-hoc, released as v0.1–v0.4)

These shipped after 03.1, alongside the Phase-4 implementation — committed on
`main` and covered by runtime + browser tests, but not part of a phase plan.

**Public embedding.** Three ways to put a shop on an external page:

- `GET /infinitemarkets/api/v1/public/merchants/{pubkey}/products` —
  unauthenticated, rate-limited card data with `Access-Control-Allow-Origin: *`
  (reads only; mutations still require the normal controls).
- `infinitemarkets/static/infinitemarkets/js/gm-embed.js` — a drop-in
  component that renders product cards into the host page's own DOM (no
  iframe). `data-gm-*` attributes select collection/category/limit/title/
  scheme; `data-gm-mode="modal"` adds an in-page product dialog. Cards and
  the Buy button land on hosted product/checkout pages.
- `GET /infinitemarkets/public/embed/merchants/{pubkey}` — a chrome-free
  iframe listing (browse + filters only) whose CSP is
  `frame-ancestors 'self' https:`; all other public pages remain `'none'`.
  It broadcasts height via `postMessage` for auto-sizing.

**Theme system additions** (`services/themes.py`, `views.py::_brand_ctx`):
brand `logo_url` (same bounded URL rules as hero images — `/path` or
`https:`), `footer.tagline`/`footer.note` (plain text, escaped, bounded),
a derived dark-scheme token set emitted alongside light tokens with a
shopper `data-scheme` toggle persisted in localStorage, and the point-and-click
Fine-tune admin panel which writes the same allowlisted advanced tokens
(the Lightning accent lives in `brand.accent` and is edited there).

**Admin surfaces.** About + More nav section (version from `config.json`,
creator credit, screenshot gallery, link cards), the Embed snippets tab,
Messages redesigned as conversation list + chat thread, Publications rows
carrying timestamps and clickable detail, and single-column merchant
settings.

**v0.3–v0.4 merchant operations.** Settings → Merchant Nostr Profile manages
`name`, bio, avatar, header image, NIP-05, and Lightning address, links to the
public `nostr.at` profile, and offers explicit owner-only `nsec` reveal/import
while keeping private key material encrypted at rest. Catalog tables expose
sortable product columns and keep Edit/Preview actions visible before Title;
the shipping editor uses a searchable country list with a 27-member European
Union preset. Settings → Notifications provides redacted, owner-only email
previews and clears only terminal queue rows. Messages resolves verified
counterparty kind-0 profiles into name/NIP-05/avatar/link fields with a safe
`npub` fallback. Publications adds a read-only live relay catalog check,
sort/filter controls, and bounded fresh kind-5 reissue for stale deleted
copies.

**Outbox history prune.** `POST /api/v1/merchants/{id}/outbox/prune`
(`{older_than_days}`, 7–3650) deletes terminal intents — published,
superseded, failed — plus their `relay_publications` evidence and
`outbox_dependencies` edges on either side. In-flight rows are never
touched; the daily `retention_prune` still covers inbox ciphertext, token
copies, peer-relay cache, and terminal-order PII.
