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

- **Payments (required policy, currently under repair).** LNbits must be the
  settlement authority. F1–F3 below show that current command/recovery paths do
  not fully enforce confirmation by a settled, correlated LNbits payment with
  complete inventory accounting. Amounts are always computed
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
  SameSite=Strict cookies. Credential lookup uses hashes. Order tokens also have
  encrypted recovery copies; queued magic-link delivery uses encrypted payloads
  until send-time cleanup. Magic links are single-use with a ~15-minute TTL.
- **Inbound Nostr.** Everything is untrusted. The order is verify → decrypt →
  dispatch, with size limits applied before decoding and per-author/per-relay
  rate limits. The durable per-scope backlog bound remains open as F6 below.
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

Existing Python qualification/runtime checks run through `make verify`, including
relay SSRF, CSRF, token, log-scrubbing and NIP-59 tests. Playwright is separate:
`cd tests/e2e && npx playwright test` against the disposable E2E server, using the
Node versions declared in `tests/e2e/package.json`. The scripted client matrix is
in `tests/conformance/`. Full-profile evidence is recorded in `evidence/`.

Passing existing tests is not sufficient: the open findings below require new
permanent negative-path regressions and repaired-revision verification.

## Current assurance gaps and required security checks

**Reviewed 2026-10-11 at `a7082c7`; fixes not yet implemented.** The historical
Phase 2 ASVS-1 sign-off is not current zero-open-threat clearance. See the
[assessment](docs/spec-conformance-analysis.md),
[open finding register](.planning/phases/05-correctness-recovery-and-security-hardening/05-SECURITY.md)
and [validation contract](.planning/phases/05-correctness-recovery-and-security-hardening/05-VALIDATION.md).

| Finding | Check required before closure |
|---|---|
| F1 | Reject unpaid merchant confirmation; keep digital delivery locked across token/history surfaces; cancellation releases reserved stock exactly once |
| F2 | Recover a creation-timeout invoice and verified settlement without a stale uncertainty hold, while preserving unrelated exceptions |
| F3 | Late settlement after reservation expiry never confirms without complete stock consumption/reallocation or explicit exception handling |
| F4 | A published old revision cannot satisfy an unpublished newer dependency |
| F5 | No-route waits remain eligible for the promised 48 hours rather than exhausting send attempts early |
| F6 | Concurrent same-merchant/relay admission cannot exceed 1,000 pending wraps, including across rate-window resets |

F1 is a merchant-authenticated authority defect, not a demonstrated anonymous
buyer exploit. The paired-test exit hang (CI-01) is separately tracked as test
infrastructure debt; an assertion-pass summary followed by timeout is not a pass.

Recheck owner/buyer isolation, CSRF, magic-link replay/merge, encrypted recovery
copies and redaction; include newer key-export, embed, import/media and relay
management surfaces in the ASVS review. Preserve the current security enforcement,
pins and CI profiles; do not weaken controls to clear the checklist. Live Plebeian
checkout/payment is still unverified, and public listing/local FakeWallet evidence
must not be presented as full external payment interoperability.
