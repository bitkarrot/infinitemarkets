# Architecture Research

**Domain:** Product media upload and Blossom server integration in a Python LNbits extension
**Researched:** 2026-10-16
**Confidence:** HIGH for existing boundaries and Blossom protocol facts; MEDIUM for the owner-dependent endpoint and failover policy

> **Milestone scope:** This is v1.1-specific research. Prior v1.0 project research is preserved under `.planning/research/v1.0-core/`.

## Standard Architecture

### System Overview

```text
┌────────────────────────────────────────────────────────────────────────────┐
│                           Admin browser (Vue/Quasar)                       │
│  File picker · thumbnails · order/primary · URL list · progress/errors    │
└──────────────────────────────┬─────────────────────────────────────────────┘
                               │ Authenticated + CSRF multipart upload
                               ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                      LNbits / FastAPI extension boundary                   │
│  Owner scope · bounded parser · upload limits · route/problem response     │
└──────────────────────────────┬─────────────────────────────────────────────┘
                               │ bytes + merchant context
                               ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                   Blossom upload service (new focused module)              │
│  Sniff/hash · choose configured server · build BUD-11 auth · safe HTTPS PUT│
└───────────────┬───────────────────────────────────┬────────────────────────┘
                │                                   │
                ▼                                   ▼
┌───────────────────────────────┐      ┌────────────────────────────────────┐
│ MerchantKeyStore / nostr-sdk  │      │ Blossom media server(s)            │
│ kind 24242 signed per upload  │      │ BUD-02 raw bytes + descriptor       │
│ nsec never leaves backend     │      │ BUD-04 mirror optional, later       │
└───────────────────────────────┘      └────────────────────────────────────┘
                │                                   │
                └──────────────────┬────────────────┘
                                   ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ Existing catalog persistence and projections                              │
│ product_images(url, dimensions, sort_order) → public pages / NIP-99 / OG   │
└──────────────────────────────┬─────────────────────────────────────────────┘
                               │ generated card image fetch (GET only)
                               ▼
                Existing safe OG-image retrieval path + PR #28 fix
```

### Component Responsibilities

| Component | Responsibility | Typical Implementation |
|-----------|----------------|------------------------|
| Admin product editor | Pick multiple images, show thumbnails/status, edit ordering/primary, remove or clear, retain URL list and errors | Extend `infinitemarkets/templates/infinitemarkets/admin.html` and `infinitemarkets/static/infinitemarkets/js/admin_catalog.js`; native browser `File`/`FormData` APIs. |
| Upload route | Authenticate the merchant, enforce CSRF, bound incoming multipart bytes/count, validate ownership if route is product-scoped, return stable descriptor/errors | Add route in `infinitemarkets/views_api.py` following bounded migration media parsing and RFC 9457 problem patterns. |
| Blossom service | Validate endpoint and protocol response, sniff image bytes, hash, sign scoped authorization, make bounded HTTPS request | Focused `infinitemarkets/services/blossom.py`; use pinned `nostr-sdk==0.44.8`, stdlib HTTP client and existing egress controls. |
| Merchant key custody | Sign one kind-24242 event without disclosing nsec or persisting short-lived upload authorization | `MerchantKeyStore.sign_event(merchant_id, UnsignedEvent)` in `infinitemarkets/keystore.py`. |
| Product image persistence | Store verified descriptor URL and ordered image list through existing product create/PATCH logic | Existing `product_images` table, `services/catalog.py`; no schema change by default. Ensure empty list means clear. |
| Share-card fetcher | Fetch image URLs to render public 1200×630 cards with strict size and network checks | Existing `services/og_images.py`; preserve PR #28's safe GET redirect behavior without applying redirects to PUT. |
| Contract registry/spec | Keep declared API surface in sync with live routes and qualification harness | `docs/technical-specification.md` §5 and `harness/registry.py::HTTP_ROUTES`; bidirectional parity test in `tests/qualification/test_p0_14_contract_closure.py`. |

## Recommended Project Structure

```text
infinitemarkets/
├── views_api.py                         # Authenticated/CSRF upload route
├── services/
│   ├── blossom.py                       # New Blossom upload/auth/transport boundary
│   ├── catalog.py                       # Existing product image validation and replacement
│   ├── relay.py                         # Existing Blossom server configuration
│   ├── og_images.py                     # Existing remote image GET and card rendering
│   └── migration_media.py               # Existing, distinct local media import flow
├── keystore.py                          # Existing merchant event signer
├── static/infinitemarkets/js/
│   └── admin_catalog.js                 # Upload controls and ordered image state
└── templates/infinitemarkets/
    └── admin.html                       # Image picker, preview tiles, status and controls
tests/
├── runtime/test_blossom_upload.py        # New fake-server protocol and route tests
├── runtime/test_catalog_api.py           # Product image clear/order/path regressions
└── qualification/test_p0_14_contract_closure.py  # Existing API parity gate
docs/
└── technical-specification.md           # §5 route and relevant limits/contract
```

### Structure Rationale

- **`services/blossom.py`:** isolates outbound media protocol and security from relay WebSocket transport and the catalog domain. Blossom is HTTPS and is already intentionally configured separately from Nostr relays.
- **`views_api.py`:** maintains existing authenticated extension routing, CSRF, request-size, and problem-detail conventions.
- **`catalog.py` and `product_images`:** reuse the existing canonical image URL/dimensions/sort-order model; avoid introducing a second persistence authority without a demonstrated need.
- **`migration_media.py` stays distinct:** it accepts merchant-provided bytes for URLs already in the catalog, verifies manifest hashes, and writes local host files. It is not a Blossom client and should not be silently repurposed.
- **Tests and spec change together:** every route requires technical-spec §5 and registry parity. Database/state changes also require DDL/state-machine registry parity, but the baseline upload should not require a new state machine or schema.

## Architectural Patterns

### Pattern 1: Backend-Proxied, Per-Upload Delegated Signing

**What:** The browser submits the selected file to an owner-authenticated extension route. The backend hashes the bytes, signs a short-lived BUD-11 kind-24242 event via merchant custody, and sends the raw bytes with BUD-02 headers.

**When to use:** Default MVP. It avoids exposing nsec, sidesteps media-server browser CORS requirements, and lets the extension uniformly enforce upload bounds and safe egress.

**Trade-offs:** Extension carries upload bandwidth and needs strict outbound networking, timeouts, per-file bounds, and careful event/token logging. Browser-direct upload is an alternative only if bandwidth is a product concern and delegated-auth/CORS risks are explicitly accepted.

**Example:**

```text
bytes = bounded multipart file
sha256 = SHA256(bytes)
event = merchant_sign(kind=24242, tags=[t=upload, x=sha256, expiration, server?])
PUT https://configured-server/upload
  Authorization: Nostr <unpadded-base64url(event-json)>
  Content-Type: <sniffed media type>
  Content-Length: len(bytes)
  X-SHA-256: sha256
  body: bytes
```

The exact BUD-11 auth value uses URL-safe base64 with **no padding**. The tag `x` must equal the request `X-SHA-256`. A `server` tag scoped to the target domain is recommended.

### Pattern 2: Resolve, Pin, and Reject Upload Redirects

**What:** Validate HTTPS and port policy, resolve configured host to public IP addresses, connect to a checked IP while retaining the configured host as TLS SNI, bound response handling, and do not automatically follow upload redirects.

**When to use:** Every backend outbound PUT and any optional BUD-06/04 call.

**Trade-offs:** More transport code than a default high-level client, but it prevents DNS rebinding and accidental body/auth forwarding to a redirect target. The current Blossom URL validator is not sufficient for runtime egress controls.

### Pattern 3: Upload First, Then Attach Through Existing Ordered Product Data

**What:** Treat remote blob upload and product save as separate effects. On successful upload, append the returned URL to the editor's ordered list; save the whole list through existing product create/PATCH logic. Explicitly send `images: []` to clear all images.

**When to use:** Baseline product editor path, including existing URL and local import paths.

**Trade-offs:** A user who uploads and then cancels can leave an unreferenced remote blob. Explain this; do not pretend the blob and catalog update are an atomic transaction. A server-owned staging workflow would need additional complexity and is an owner decision.

## Data Flow

### Request Flow

```text
Merchant selects image(s)
    ↓
Browser checks count/size and displays local previews
    ↓
CSRF-protected multipart route (bounded before accepting all bytes)
    ↓
Owner-scope check → content sniff → SHA-256
    ↓
Select explicitly configured server → public-egress DNS check/pin
    ↓
MerchantKeyStore signs short-lived BUD-11 kind 24242 event
    ↓
Raw-byte BUD-02 PUT /upload (no automatic redirect)
    ↓
Verify status 200/201 + descriptor hash/size/type/url consistency
    ↓
Return safe descriptor → editor updates ordered image list
    ↓
Product POST/PATCH persists URL, dimensions and sort order
    ↓
Existing product projections feed storefront, catalog event and OG card
```

### State Management

```text
Editor state: existing URLs + selected local files + upload status
      │ upload success
      ├── append descriptor URL / preserve user-selected order
      │ save product
      ├── POST or PATCH with complete `images` array (including [])
      │ cancel after upload
      └── disclose possible orphaned Blossom blob; no implied remote delete
```

### Key Data Flows

1. **Blossom upload:** input bytes are supplied by the merchant, not fetched from an arbitrary image URL. Validate the content type from magic bytes, calculate SHA-256 from the same bounded bytes, and verify the returned descriptor matches the submitted content.
2. **Catalog update:** keep `product_images` as the ordered canonical set. Product PATCH already replaces details when `images` is present; client must distinguish omitted (leave unchanged) from present-but-empty (clear).
3. **OG card rendering:** remote image GET is a separate trust boundary. PR #28 handles bounded safe HTTPS GET redirects for the encountered `307`; do not reuse that redirect-following policy for upload PUT.
4. **Migration local media:** its `/images/infinitemarkets/...` URLs are existing media and must remain editable. Resolve the current HTTPS-only validation mismatch before claiming full round-trip support.

## Scaling Considerations

| Scale | Architecture Adjustments |
|-------|--------------------------|
| 0–1k merchants | Single extension process is adequate. Use conservative file/total request limits, bounded workers/timeouts, first-success upload, and no durable job queue until evidence justifies it. |
| 1k–100k merchants | Measure host request occupancy, upload concurrency, and timeouts. Add bounded concurrency/backpressure or a durable task only if synchronous upload harms normal LNbits request capacity. |
| 100k+ users | Outside current project assumptions. Reassess media proxy bandwidth, host egress, quotas, and upload jobs, but do not preemptively add distributed storage or queue architecture. |

### Scaling Priorities

1. **First bottleneck:** large or concurrent byte uploads consume memory, request slots, and outbound bandwidth. Bound body/file/count/time/concurrency and avoid duplicate full-body copies.
2. **Second bottleneck:** retrying slow/multi-server uploads can tie up the host. Keep MVP to one chosen server or bounded fallback; mirror asynchronously only if durable retry guarantees become a requirement.

## Anti-Patterns

### Anti-Pattern 1: Treating Merchant Settings as Nostr Server Discovery

**What people do:** Assume `settings.blossom_servers` is automatically a published kind-10063 server list.

**Why it's wrong:** Existing settings are local configuration and the endpoint does not publish kind 10063. Conflating these concepts silently expands scope and creates an event-publication requirement.

**Do this instead:** Use configured server list for uploads. Make kind-10063 publication an explicit optional decision.

### Anti-Pattern 2: Reusing GET Redirect Policy for PUT

**What people do:** Follow all redirects because the OG image GET fix needs a redirect from one Blossom host to another.

**Why it's wrong:** A redirecting PUT may replay image bytes and an Authorization header to a different host. The GET use case and upload authorization are not equivalent.

**Do this instead:** Keep GET redirect behavior bounded and HTTPS-only; reject upload redirects and let the merchant configure the actual endpoint or choose another server.

### Anti-Pattern 3: Add a New Media Table Before Requirements Need One

**What people do:** Persist upload records, retry states, authorization tokens, or storage metadata preemptively.

**Why it's wrong:** Existing `product_images` already captures catalog URL/dimensions/order, and tokens should be short-lived and nonpersistent. Additional state means migrations and recovery semantics without a proven use case.

**Do this instead:** Start with synchronous bounded upload returning a descriptor. Add durable jobs or asset ownership only if operational evidence requires them.

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| Blossom server | HTTPS BUD-02 raw-byte `PUT /upload`, signed BUD-11 auth | BUD-02 success is 200 (already present) or 201 (new). No redirects; verify JSON descriptor. |
| Optional Blossom preflight | BUD-06 `HEAD /upload` | Hash/type/size preflight is informative only; upload can still fail afterward. |
| Optional mirror target | BUD-04 `PUT /mirror` | Destination server fetches and verifies an existing blob. Defer pending owner approval on redundancy and partial success. |
| Open Graph image host | Bounded HTTPS GET through `services/og_images.py` | PR #28 specifically addresses safe redirect-following on GET. Separate from upload transport. |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| Admin UI ↔ upload API | CSRF-protected multipart request / JSON descriptor | Use progress/retry and don't lose image-list edits on failure. Exact route and product ownership/staging behavior are owner decisions. |
| Upload API ↔ Blossom service | Python function call with bytes, server list, merchant identity | Route owns auth and request bounds; service owns protocol, signing, SSRF-safe transport, and descriptor validation. |
| Blossom service ↔ `MerchantKeyStore` | `sign_event(merchant_id, UnsignedEvent)` | Private key is loaded/released per operation and never returned to UI. |
| Admin API ↔ catalog service | Existing product POST/PATCH with full image array | Empty list must clear; omission must preserve. Resolve HTTPS-only vs local `/images` support. |
| Runtime route ↔ docs/harness | Route registry and specification parity | New route must be added to spec §5 and `harness/registry.py::HTTP_ROUTES`; tests enforce both directions. |

## Sources

- `infinitemarkets/services/relay.py` — configuration in `settings.blossom_servers`, current endpoint validation, alphabetical sorting.
- `infinitemarkets/services/catalog.py` and `views_api.py` — product image replacement and current `POST /products/{id}/images` URL attachment route.
- `infinitemarkets/services/migration_media.py` — separate bounded local media ingest.
- `infinitemarkets/keystore.py` — per-operation merchant event signing.
- `infinitemarkets/security.py` and `services/og_images.py` — public-egress check and pinned TLS connection pattern.
- `infinitemarkets/static/infinitemarkets/js/admin_catalog.js` — image textarea serialization, with empty list omitted.
- `docs/technical-specification.md` §5, §11, §13.2, §15; `harness/registry.py`; `tests/qualification/test_p0_14_contract_closure.py`.
- [BUD-02](https://github.com/hzrd149/blossom/blob/master/buds/02.md), [BUD-03](https://github.com/hzrd149/blossom/blob/master/buds/03.md), [BUD-04](https://github.com/hzrd149/blossom/blob/master/buds/04.md), [BUD-06](https://github.com/hzrd149/blossom/blob/master/buds/06.md), [BUD-11](https://github.com/hzrd149/blossom/blob/master/buds/11.md), [NIP-B7](https://github.com/nostr-protocol/nips/blob/master/B7.md).

---
*Architecture research for: Infinite Markets v1.1 media uploads and Blossom support*
*Researched: 2026-10-16*
