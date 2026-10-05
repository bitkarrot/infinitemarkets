# Infinite Markets

<img width="160" height="160" alt="Infinite Markets" align="right" src="infinitemarkets/static/infinitemarkets/img/infinite-markets-blue.png" />

An [LNbits](https://github.com/lnbits/lnbits) extension that gives a merchant one authoritative inventory across two storefronts: a classic web shop with Lightning checkout, and a native Nostr/Gamma commerce channel with encrypted (NIP-17) ordering.

**One inventory, two rails.** Web and Nostr orders flow through the same pricing, reservation, invoice, and settlement pipeline — no duplicate invoices, no double allocation, and relay delivery is never mistaken for payment truth.

## Demo

<video src="https://github.com/bitkarrot/infinitemarkets/raw/main/docs/assets/infinitemarkets_demo.mp4" controls muted playsinline width="100%"></video>

[▶ Watch the demo](docs/assets/infinitemarkets_demo.mp4) (~3.5 min) — merchant key import, catalog publish to public relays, a live Lightning purchase, and encrypted order messaging, all on a live host.

## Features

### Catalog & web commerce (Release A)
- Products, collections, shipping options, and visibility flags (`on-sale`, `hidden`, `pre-order`, draft)
- Public storefront with private per-order links — no buyer accounts required
- Lightning checkout: quote → reservation → invoice → settlement saga with late-settlement reconciliation
- Reversible order archiving, bulk catalog operations, order notifications over host SMTP
- NIP-99 catalog publication to public relays with durable per-relay outbox evidence

### Gamma Nostr orders (Release B)
- **Kind-10050 inbox profile**: merchants publish declared inbox relays and activate only after reachability is proven
- **NIP-17 encrypted ordering**: kind-16 order/payment/status messages and kind-17 receipts over gift-wrapped (kind-1059) transport
- **Dual-copy protocol**: independent sender and recipient copies routed only to each party's declared relays
- **Durable inbox**: verified/deduplicated outer-seal-rumor identity, encrypted history, resumable cursors, overload shedding before decrypt
- **NIP-42 relay authentication** and paid-relay support (`payment-required` surfaces the invoice for external payment — the extension never spends)
- **NIP-07 sign-in** for buyers: order history, retroactive order claiming via private links, token-equivalent access to digital delivery
- **Storefront modes**: `full`, `showcase`, `browse_only`, `nostr_only` — private order links and in-flight invoices keep working in every mode
- **Admin Messages workspace**: customer/unknown folders, unread markers, thread reply/compose, per-relay delivery evidence, retry, rejected-intake review with mute

## Requirements

- LNbits ≥ **1.6.0** (developed and conformance-tested against `v1.6.2-rc1`, host pin `e336fe14`)
- Python extension support enabled on the host (standard LNbits extension loader)
- A bound merchant wallet (Lightning funding source) for invoice creation
- For Nostr flows: outbound websocket access to buyer/merchant declared relays; a recipient-gated relay (e.g. the LNbits `nostrrelay` extension) is the reference inbox deployment but is **not** a runtime dependency

## Installation

### Remote install (extension manifest)

Add the release manifest URL to the host's extension sources — LNbits admin UI → **Server → Extensions → Manifest sources**, or the `LNBITS_EXTENSIONS_MANIFESTS` setting:

```
https://raw.githubusercontent.com/bitkarrot/infinitemarkets/main/manifest.json
```

The extension then appears in the extension manager and installs with sha256 verification against the release archive. The zip layout follows the LNbits contract: a single top-level `infinitemarkets/` directory containing `config.json` and the package.

> Note: use the `raw.githubusercontent.com` manifest URL, not the GitHub release-asset URL — LNbits fetches manifests with redirects disabled, and `releases/download/...` URLs 302 to a signed asset host. `main/manifest.json` always points at the latest release; the manifest embeds the sha256 of that release's zip.

### Local / development install

```bash
git clone https://github.com/bitkarrot/infinitemarkets.git
cd infinitemarkets
make host        # checks out the pinned LNbits host into .cache/lnbits
```

Symlink or copy `infinitemarkets/` into the host's extensions directory, or run the harness/e2e tooling which boots a disposable host (see `tools/e2e_server.py`).

## Configuration

All extension settings use the `INFINITEMARKETS_` prefix and are read from the **host** environment — i.e. the environment of the LNbits process itself (its `.env`, systemd unit, Docker env, or shell — wherever `LNBITS_*` settings already live), not a file inside the extension.

The extension **refuses to start** until the four required values below are present and valid.

### Generating the required secrets

Run each `openssl` command once per environment and store the output somewhere safe (a password manager or secrets store). The values are random 32-byte keys — they are **not** recoverable if lost, and losing them makes previously stored encrypted fields (buyer identifiers, Nostr payloads, private-link token hashes) unreadable.

```bash
# 1. Generate a master key (32 random bytes, base64-encoded)
openssl rand -base64 32
# example output: 9f3kD2mZ8xQ1wLp+vR7tYuN0cBhG4sJdEaF6iKoPq5M=

# 2. Generate the privacy key — must be DIFFERENT key material
openssl rand -base64 32
# example output: Kx9vN2mQp8wR4tYuLcE0sG6hJdB3fA1iZoPqM5eX7kT=
```

Then assemble the four variables:

```bash
# JSON object mapping version label -> base64 key. One key is normal;
# add a second entry (e.g. "v2") only when rotating keys. The JSON must
# be a single line — quote it in single quotes in .env files.
INFINITEMARKETS_MASTER_KEYS='{"v1": "9f3kD2mZ8xQ1wLp+vR7tYuN0cBhG4sJdEaF6iKoPq5M="}'

# Which key in the map is currently used for new writes.
# Must exactly match a key label from MASTER_KEYS.
INFINITEMARKETS_ACTIVE_KEY_VERSION=v1

# Independent key for privacy-sensitive fields. Same format (base64
# 32-byte or 64-hex), MUST NOT equal any master key.
INFINITEMARKETS_PRIVACY_KEY=Kx9vN2mQp8wR4tYuLcE0sG6hJdB3fA1iZoPqM5eX7kT=

# Public https origin where buyers reach this host — port allowed,
# no path, no userinfo/query/fragment.
INFINITEMARKETS_PUBLIC_BASE_URL=https://shop.example.com
```

**Format rules enforced at startup** (a violation aborts extension boot with a clear error):

| Variable | Rules |
|---|---|
| `INFINITEMARKETS_MASTER_KEYS` | Valid JSON object, non-empty; every version label a non-empty string; every value strict base64 decoding to **exactly 32 bytes**; duplicate key material under two versions is rejected (it breaks rotation semantics) |
| `INFINITEMARKETS_ACTIVE_KEY_VERSION` | Must be a label present in `MASTER_KEYS` |
| `INFINITEMARKETS_PRIVACY_KEY` | base64 (32 bytes) **or** 64-char hex; must not match any master key's material |
| `INFINITEMARKETS_PUBLIC_BASE_URL` | `https://` origin only — `https://shop.example.com` and `https://shop.example.com:8443` valid; `http://…`, `…/shop`, `…?x=1`, `user:pass@host` all rejected |

**Common mistakes**

- `openssl rand 32` (no `-base64`) emits raw bytes — always use `openssl rand -base64 32`.
- Multi-line JSON or smart quotes in `MASTER_KEYS` fail JSON parsing — keep it one line, ASCII quotes.
- Don't reuse the same generated value for the privacy key and a master key — boot rejects it.
- Behind a reverse proxy, `PUBLIC_BASE_URL` is still the **public** https origin, not the internal listen address.

**Key rotation**: add the new key under a new label (`"v2": "…"`) in `MASTER_KEYS`, keep `v1` present, then set `INFINITEMARKETS_ACTIVE_KEY_VERSION=v2`. Old data stays decryptable via `v1`; new writes use `v2`.

### Optional tuning

| Variable | Default | Purpose |
|---|---|---|
| `INFINITEMARKETS_RESERVATION_TTL` | `900` | Inventory hold seconds |
| `INFINITEMARKETS_OUTBOX_MAX_ATTEMPTS` | `20` | Relay publish retry bound |
| `INFINITEMARKETS_OUTBOX_BATCH` | `32` | Relay publish batch size |
| `INFINITEMARKETS_PEER_RELAY_TTL` | `86400` | Discovered peer-relay record TTL (s) |
| `INFINITEMARKETS_INBOX_MAX_EVENT_BYTES` | `32768` | Inbound wrap size cap |
| `INFINITEMARKETS_INBOX_AUTHOR_CAP` | `60` | Per-author wraps/minute pre-validation |
| `INFINITEMARKETS_CHECKOUT_RATE_LIMIT` | `10` | Checkout requests/min per IP |
| `INFINITEMARKETS_CHECKOUT_RATE_LIMIT_HOURLY` | `100` | Checkout requests/hour per IP |
| `INFINITEMARKETS_EMAIL_ENABLED` | `true` | Order notification email |
| `INFINITEMARKETS_EMAIL_MAX_ATTEMPTS` | `5` | Email retry bound |

## Storefront modes

| Mode | Web browse | Web checkout | Nostr listings | Nostr orders |
|---|---|---|---|---|
| `full` (default) | ✓ | ✓ | ✓ | ✓ |
| `showcase` | ✓ | guided "Order via Nostr" | ✓ | ✓ |
| `browse_only` | ✓ | — | paused | — |
| `nostr_only` | notice only | — | ✓ | ✓ |

Switching to `showcase`/`nostr_only` requires proven Nostr inbox readiness. Existing private order links, in-flight invoices, and sign-in work in every mode.

## Security posture

- Relay-target egress screening: discovered/inbox relay targets are DNS-resolved and non-global ranges (private, loopback, link-local, multicast, reserved, metadata incl. `169.254.169.254`, CGNAT) rejected at validate, connect, and reconnect — IPv4 and IPv6
- Bounded relay churn: inbox sessions re-open under per-(merchant, relay) exponential backoff (30 s → 15 min, reset on EOSE); a relay that repeatedly rejects NIP-42 auth is disabled after 10 rejections and flagged `auth-failed` on the relay-health surface (retryable via `POST /merchants/{id}/relay-auth/retry/{relay_url}`); when no enabled inbox relay is usable the merchant admin shows an urgent "inbox unreachable" warning
- The extension **never** invokes outgoing-payment APIs — paid-relay invoices are surfaced for external payment only
- Encrypted at rest: NIP-17 payloads and buyer identifiers are stored encrypted; rejected intake is auditable
- OS/container egress policy remains an operator responsibility when claiming Release-B conformance (see `PINS.md` §8 and spec decision 30)

## Conformance status

Release-B evidence is reproducible: the scripted conformance matrix (`tests/conformance/run_matrix.sh matrix`) runs a real recipient-gated `nostrrelay` environment, egress/NIP-42/paid-write/overload drills, and an independent external-client matrix against a pinned `PlebeianApp/market` clone — 14/14 probes with a recorded 6-entry known-delta register (`evidence/conformance/`).

**Outstanding manual gate**: the live `plebeian.market` public-relay smoke is a manual checklist (`tests/conformance/README.md`) recorded as pending in `.planning/phases/03-release-b-gamma-nip-17-orders/03-VERIFICATION.md`.

## Development

```bash
make verify          # full suite + durable evidence (SQLite or Postgres per env)
make verify-runtime  # extension runtime tests only
make verify-fast     # fast subset
make lint            # ruff
make package         # build dist/infinitemarkets-<v>.zip + dist/manifest.json
```

- Node **22 or 24** required for the Playwright suite (`tests/e2e/`) — enforced by `.nvmrc` and engines
- Use an isolated `LNBITS_DATA_FOLDER` for parallel test runs; the shared `.cache/qual-data/` database is not safe for concurrent use
- Pinned host/SDK/tooling: `PINS.md`. Normative protocol contract: `docs/technical-specification.md`

## Repository layout

```
infinitemarkets/        # the extension package (installed unit)
  services/             # commerce, relay, inbox, outbox, auth services
  static/  templates/   # Quasar/Vue admin + public surfaces
docs/                   # technical specification
tests/                  # qualification, runtime, e2e, conformance suites
tools/  harness/        # host checkout, e2e server, test harness
evidence/               # conformance + qualification evidence bundles
.planning/              # GSD project plans, decisions, verification records
```

## License

[MIT](LICENSE)
