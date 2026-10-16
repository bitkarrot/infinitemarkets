# Stack Research

**Domain:** Python LNbits extension — merchant image uploads to local LNbits storage or Blossom media servers
**Researched:** 2026-10-16
**Confidence:** HIGH for the existing extension stack and Blossom wire contracts; MEDIUM for the not-yet-decided upload policy

> **Milestone scope:** This is v1.1-specific research. Prior v1.0 project research is preserved under `.planning/research/v1.0-core/`.

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Python | `>=3.12,<3.13` | Upload route, bounded parsing, hashing, local media storage, Blossom HTTP client, validation | The extension and locked host/test environment target Python 3.12. Keep upload/auth logic in the existing backend rather than creating a second client-side protocol implementation. |
| LNbits / FastAPI | Host baseline LNbits `v1.6.2-rc1` at `e336fe1`; FastAPI resolved by the pinned host | Authenticated, CSRF-protected admin upload endpoint and multipart parsing | Reuse the extension's established route, problem-detail, request-stream, and owner-scope patterns. The host is a project constraint, not a new dependency choice. |
| `nostr-sdk` | `0.44.8` (already pinned) | Build/sign Blossom kind-24242 authorization events through merchant custody | `MerchantKeyStore.sign_event(merchant_id, UnsignedEvent)` loads and releases encrypted key material inside one operation. Keep the nsec out of browser code and avoid a new signing stack. |
| Python standard library `http.client` | Python 3.12 stdlib | HTTPS PUT to Blossom and bounded HTTP response handling | Already used by `services/og_images.py`; supports the repository's pinned-IP/TLS-SNI connection pattern without introducing another dependency. Must be wrapped off the async event loop. |
| Browser `File`, `FormData`, and `XMLHttpRequest`/fetch APIs | Current supported browser | File selection, preview, upload progress, and retry UI | The admin app is already Vue/Quasar-style browser JavaScript. Native APIs are sufficient for a backend-proxied multipart request; they do not need to sign Nostr events. |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `nostr-sdk` | `0.44.8` | Nostr event construction/signing | Reuse the installed signer to create the BUD-11 authorization event. Verify the needed kind/tags/serialization against the pinned SDK in tests before assuming a helper exists. |
| `Pillow` | Already pinned by the host environment (`~=12.3.0` in the lock) | Image decode/metadata or thumbnail processing | Optional only if requirements call for server-generated dimensions or robust decoded-image validation. Existing migration media accepts formats by magic bytes and does not require new processing. Do not make server-side transcoding part of the default MVP. |
| Python `asyncio`, `hashlib`, `base64`, `json`, `ssl`, `socket` | Python 3.12 stdlib | Async offload, SHA-256, BUD auth header serialization, TLS and pinned sockets | Use existing stdlib and security patterns; tests should cover canonical base64url without padding and HTTPS host pinning. |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| `make verify-fast` | Required fast qualification and unit gate | Required before a push under repository guidance. Blossom route additions must pass route/spec/registry parity. |
| `uv run pytest` | Runtime and focused tests | Add deterministic fake Blossom HTTP-server tests. Never upload test bytes to a real public Blossom endpoint. |
| `node --check <edited .js files>` | Admin JavaScript syntax check | Run for editor changes. |
| `ruff check .` | Python lint | Run if Python service/route code changes. |

## Installation

No package installation is recommended for v1.1. In particular, do not add a JavaScript Blossom SDK or Python HTTP client by default. The project already pins `nostr-sdk==0.44.8`; prefer stdlib `http.client` unless a demonstrated protocol requirement cannot be implemented safely with it and the owner approves a dependency.

```bash
# No new dependencies.
# Use the repository's normal environment and verification targets.
make verify-fast
```

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| Backend-proxied upload: browser submits bytes to the authenticated extension; backend hashes, signs, and PUTs to Blossom | Browser sends bytes directly with a backend-minted, short-lived BUD-11 authorization event | Consider only if avoiding server bandwidth is an explicit product requirement and server CORS behavior, token scope, expiry, replay exposure, and browser retry behavior are qualified. Never send the merchant nsec to the browser. |
| Python stdlib `http.client`, in a worker thread and with pinned public-IP TLS connections | Existing `httpx`/other async HTTP library | Consider only if a concrete streaming, cancellation, or transport capability gap is demonstrated and dependency approval is obtained. An async client does not remove the need for SSRF/DNS-rebinding controls or redirect policy. |
| Existing `nostr-sdk==0.44.8` + `MerchantKeyStore.sign_event` | A separate Nostr signing package | Consider only if the pinned SDK cannot represent/sign kind 24242 correctly; record a capability probe and security review first. |
| Keep uploaded bytes at the selected Blossom server for MVP; optionally mirror later via BUD-04 | Browser-side upload SDK or direct upload to every server | Consider direct upload only after the owner explicitly accepts browser auth/CORS complexity. Mirror only if availability requirements justify extra storage, latency, and partial-success semantics. |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| Merchant nsec or long-lived private credential in browser storage, JavaScript, or upload form | Any script exposure compromises the merchant's Nostr identity and potentially unrelated event signing. | Backend signs a narrowly-scoped, short-lived kind-24242 BUD-11 event per upload. |
| JavaScript Blossom SDK as the Python backend implementation | Wrong runtime boundary; it duplicates the backend protocol client and does not solve merchant key custody or endpoint SSRF. | Python service using pinned `nostr-sdk` for signing and stdlib HTTP for transport. |
| Automatic HTTP redirects for Blossom PUT | A 307/308 can replay a body and authorization to a different host; redirect semantics are not equivalent to the separate GET-image retrieval fix. | Reject redirects for upload; if a server returns one, surface a safe error and require explicit configuration/owner policy. |
| Unbounded `request.body()` or whole-request buffering without request/file bounds | Enables memory exhaustion and oversized uploads before validation. | Bounded multipart stream parsing, count/size limits, content sniffing, and SHA-256 verification. |
| New image-storage SDK/dependency without a demonstrated capability gap | Adds package/provenance surface for a small HTTP protocol and violates the current dependency constraint. | Existing host and standard-library capabilities; request owner approval for any exception. |

## Stack Patterns by Variant

**If implementing the recommended backend-proxy MVP:**
- Use the existing authenticated/CSRF-protected FastAPI route family and a focused `infinitemarkets/services/blossom.py` service.
- Stream/bound the incoming multipart body, enforce a per-file byte ceiling, sniff allowed image formats, calculate SHA-256, create the BUD-11 event, and PUT raw bytes with the BUD-02 headers.
- Run blocking `http.client` operations via `asyncio.to_thread` or another bounded worker; do not block the host event loop.

**If owner chooses direct browser upload:**
- Backend may mint only short-lived, upload-scoped BUD-11 authorization; browser uses native APIs and receives no private key.
- Treat server CORS, origin behavior, token leakage, retry/replay window, and user-visible server failures as explicit requirements and test them against a fake server before relying on public servers.

**Configured Blossom target (owner decision):**
- Use only the primary/first `Media (Blossom)` server configured in Settings → Merchant.
- Preserve the merchant's configured order; `set_blossom_servers` currently sorts URLs alphabetically and must change before the first item can reliably mean primary.
- Do not automatically fail over to another Blossom server or mirror. If the primary fails, expose the error and let the merchant explicitly retry to local LNbits storage.

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| `nostr-sdk==0.44.8` | Python `3.12` host resolution | Existing exact pin. Probe event builder support for kind 24242, expiration tags, and canonical JSON event serialization. |
| Python `http.client` | Python `3.12` stdlib | Already used for outbound OG-image GETs. Upload code must set explicit connect/read deadlines, bound response bytes, use TLS SNI for the configured hostname, and disable redirects. |
| Admin JavaScript | Existing LNbits host webview and bundled extension assets | Keep native file APIs compatible with the current Vue/Quasar-style admin surface; no new frontend package by default. |

## Sources

### Local implementation and contract evidence

- `pyproject.toml` and `uv.lock` — Python 3.12 and `nostr-sdk==0.44.8` pin.
- `infinitemarkets/keystore.py` — `MerchantKeyStore.sign_event` loads the merchant key and releases it on operation exit.
- `infinitemarkets/services/og_images.py` — existing stdlib HTTPS, public-egress resolution, pinned-IP/TLS-SNI pattern for GET-only remote image retrieval.
- `infinitemarkets/security.py` — `resolve_and_check_egress` rejects hosts resolving to any non-public address.
- `infinitemarkets/services/relay.py` — Blossom server setting validation and persistence; setter currently sorts/deduplicates.
- `infinitemarkets/services/migration_media.py` and `infinitemarkets/views_api.py` — bounded multipart and media verification patterns.

### Primary protocol sources (directly verified)

- [BUD-02 — Upload](https://github.com/hzrd149/blossom/blob/master/buds/02.md) — raw-byte `PUT /upload`, request headers, accepted 200/201 responses, descriptor.
- [BUD-11 — Authorization](https://github.com/hzrd149/blossom/blob/master/buds/11.md) — kind 24242 auth, URL-safe base64 event without padding, upload scope, expiry, matching `x` tag and `X-SHA-256`.
- [BUD-06 — Check](https://github.com/hzrd149/blossom/blob/master/buds/06.md) — optional `HEAD /upload` preflight; it is not a guarantee that the subsequent upload succeeds.
- [BUD-04 — Mirror](https://github.com/hzrd149/blossom/blob/master/buds/04.md) — destination `PUT /mirror` fetches an existing blob and verifies its hash.
- [BUD-03 — User server list](https://github.com/hzrd149/blossom/blob/master/buds/03.md) — ordered kind-10063 `server` tags, first server preferred.
- [NIP-B7 — Blossom media](https://github.com/nostr-protocol/nips/blob/master/B7.md) — client media discovery and use of Blossom server lists.

---
*Stack research for: Infinite Markets v1.1 media uploads and Blossom support*
*Researched: 2026-10-16*
