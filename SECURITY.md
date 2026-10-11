# Security Policy

Infinite Markets is an LNbits extension that holds merchant Nostr keys, buyer
order data and Lightning invoice metadata. Please treat security issues
seriously and report them privately.

## Supported versions

| Version | Supported |
|---|---|
| 0.6.x (latest release in `manifest.json`) | ✓ |
| < 0.6 | ✗ — upgrade first |

Fixes land on `main` and ship in the next release published through
`manifest.json`. The software is **experimental**, and the Gamma marketplace
spec it implements is still a draft. Run it with small amounts.

## Reporting a vulnerability

**Do not open a public issue, PR or Nostr post for a security problem.**

1. Use GitHub private vulnerability reporting:
   **Security → Report a vulnerability** on
   <https://github.com/bitkarrot/infinitemarkets/security/advisories/new>.
2. Include the affected version or commit, your LNbits version, the database
   (SQLite or PostgreSQL), reproduction steps or a proof of concept, and the
   impact you observed.
3. Never include real nsecs, master or privacy keys, wallet keys, buyer
   addresses or private order links. Redact them, or use throwaway values.

What to expect: an acknowledgement within 7 days, an initial assessment within
14 days, and coordinated disclosure once a fix is released. We'll credit you
in the advisory unless you ask us not to. There is no bug bounty.

Vulnerabilities in **LNbits core**, **nostr-sdk** or a **relay** should go to
those projects. If they affect Infinite Markets, tell us too.

## Scope

In scope: everything under `infinitemarkets/` (routes, services, templates,
static JS including `gm-embed.js`), the release archive and `manifest.json`
hash, and the documented configuration.

Especially relevant:
- Merchant key exposure (nsec in a response, log, exception, browser storage or cache)
- Payment integrity: confirming unpaid orders, amount manipulation, replayed
  or cross-merchant payments, duplicate invoices
- Authentication and authorization: cross-merchant data access, CSRF on admin
  or buyer routes, session or magic-link misuse, guessing or leaking private
  order tokens
- Inbound Nostr handling: signature/seal bypass, NIP-44/NIP-59 decode bombs,
  rumor/seal mismatch
- SSRF through relay URLs (including DNS rebinding and IPv6) or any server-side fetch
- XSS through product Markdown, image URLs, embeds or buyer messages
- Data decryptable at rest without the configured keys

Out of scope:
- Denial of inventory by distributed stock reservation. This is an accepted v1
  risk (technical spec §15). Merchants can lower TTLs or caps, or disable web
  checkout.
- Remote image hosts learning viewer IP and time (disclosed; images are never
  fetched server-side)
- Findings that require host or operator compromise. A native extension shares
  the LNbits process privilege, so "no outgoing payments" is enforced by code
  policy and review, not by a sandbox.
- Advisories on `starlette` / `pyjwt` that come in transitively through the
  pinned LNbits host. Their disposition is recorded in `PINS.md` §5.
- The static docs site in `docs/viewer/`, unless it exposes secrets

## Security model (summary)

The normative contract is `docs/technical-specification.md` §§9.5, 11, 15
and 19, and the threat model is in `docs/architecture-proposal.md` §21.
In brief:

- **Payments.** LNbits is the settlement authority. Orders are confirmed only
  by settled LNbits payments bound to that order. Amounts are always computed
  on the server, and Nostr receipts are only hints. The extension never calls
  outgoing-payment APIs. Refunds are recorded as out-of-band merchant
  attestations.
- **Keys.** Merchant nsecs and sensitive fields (addresses, contacts, messages,
  tracking, tokens, outbox payloads, buyer identifiers) are stored encrypted
  with AES-256-GCM. Each record uses a versioned key and per-field AAD.
  Equality indexes and IP pseudonyms use HMAC-SHA256 under a separate privacy
  key. Private-key export is owner-only (`POST /merchants/{id}/keys/export`,
  `Cache-Control: no-store`).
- **Auth.** Admin routes are scoped to the LNbits user and merchant. Cookie
  mutations require an exact `Origin` match plus a double-submit CSRF token.
  User-id-only auth is rejected. Buyer sessions use HttpOnly, Secure,
  SameSite=Strict cookies. Session, magic-link and order tokens are stored
  only as hashes, and magic links are single-use with a ~15-minute TTL.
- **Inbound Nostr.** Everything is untrusted. The order is verify → decrypt →
  dispatch, with size limits applied before decoding and per-author and
  per-relay admission caps.
- **Network.** Relay URLs are an SSRF boundary. They must be `wss://`, raw IPs
  are refused, and DNS-resolved non-global ranges are rejected at validate,
  connect and reconnect.
- **Web.** Markdown goes through an allowlist sanitizer. Images are HTTPS-only
  and never fetched by the server. Admin and order pages load no third-party
  scripts. Public endpoints are rate-limited.
- **Logs.** Logs contain IDs and states only: never keys, decrypted content,
  addresses, full BOLT11 strings or relay AUTH challenges.

## Operator responsibilities

Deployers own these controls. The extension can't enforce them alone.

- **Secrets.** Generate `INFINITEMARKETS_MASTER_KEYS` and
  `INFINITEMARKETS_PRIVACY_KEY` with `openssl rand -base64 32` (see
  `README.md`). Keep them in a secrets store and back them up. **Lost keys
  can't be recovered**, and losing them makes encrypted data unreadable. Never
  commit them or reuse key material between the two.
- **Rotation.** Add a new label to `MASTER_KEYS`, switch
  `ACTIVE_KEY_VERSION`, and keep the old key until no rows still use it and a
  restore drill passes. Don't rotate the privacy key in place.
- **Egress.** Block loopback, private, link-local, multicast, reserved and
  metadata ranges (IPv4 and IPv6, including `169.254.169.254`) at the OS or
  container level, or restrict relays to an allowlist. DNS checks inside the
  app alone can't stop rebinding. This is required to claim Release-B
  conformance (`PINS.md` §8).
- **TLS and proxies.** Serve LNbits over HTTPS. Set
  `INFINITEMARKETS_PUBLIC_BASE_URL` to the public `https://` origin. Only let
  LNbits trust `X-Forwarded-For` from your own reverse proxy.
- **Backups.** Backups contain encrypted PII and inherit its sensitivity.
  Retention erasure can't reach old backups.
- **Email.** Order email uses the host's SMTP settings only. A status-link
  email is a bearer credential: anyone with access to that inbox can read the
  order.
- **Updates.** Install only from the official `manifest.json`. LNbits verifies
  the archive's sha256 against it.

## Verification

The security behaviours above are covered by `make verify` (qualification,
runtime and e2e suites, including relay SSRF, CSRF, token, log-scrubbing and
NIP-59 tests) and by the conformance matrix in `tests/conformance/`. Evidence
is recorded in `evidence/`.
