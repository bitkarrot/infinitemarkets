# Phase 6: Secure Media Storage - Research

**Researched:** 2026-10-16
**Domain:** Secure media upload for an LNbits extension — local merchant-namespaced storage + server-side Blossom (BUD-02/BUD-11) upload
**Confidence:** HIGH (protocol specs fetched this session; signing path verified by execution; all in-repo surfaces read directly)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Every upload selects exactly one backend: LNbits-local by default, or
  Blossom only when explicitly selected. No dual-write, no silent failover.
- Blossom targets only the FIRST server configured in Settings → Merchant,
  preserving saved order — **reversibility: costly** — `set_blossom_servers`
  currently sorts URLs; fixing the stored order changes an already-persisted
  data contract and every read path that assumed sorted order.
- Blossom authorization is signed server-side with `MerchantKeyStore.sign_event`.
  Never expose nsec or reusable signing material to browser code.
- Bounds: ≤16 files per request, ≤25 MB per file, 400 MB per-merchant
  LNbits-local quota. Multipart parsing bounded — no unbounded request-body
  buffering in memory.
- Accept signature-verified PNG/JPEG/WebP only; reject SVG and GIF in v1.1.
- If a remote upload is not saved with its product/setting, disclose that the
  blob may remain unreferenced; never automatically delete remote Blossom
  blobs.
- PR #28's bounded, revalidated HTTPS redirects apply only to share-card
  image GETs. Authenticated upload PUTs must never follow redirects.
- No-Blossom behavior: if no Blossom server is configured, local storage is
  selected automatically (no configuration gate on the upload feature).

#### Leftover Uploads (owner-selected: leave + cleanup control)
- **D-01:** An uploaded-but-unsaved file is left in place; the editor copy
  discloses it may remain unreferenced and it counts toward the local quota.
- **D-02:** Provide a "view unused uploads" capability that lists
  unreferenced local files so the merchant can delete them explicitly.
  Local deletion is allowed; remote Blossom deletion is NOT (deferred
  requirement MEDIA-22 territory — do not implement BUD DELETE).

#### Upload Batching (owner-selected: one file per request)
- **D-03:** Each file is sent as its own multipart request. Per-file progress
  and per-file retry are native; a rejected file never affects siblings.
  The 16-files-per-request ceiling remains as the service-level bound even
  though the UI sends one at a time.

#### Public URL for Local Images (pre-answered by existing code)
- **D-04:** Local images used in Nostr profile avatar/banner resolve to
  `ext_settings().public_base_url` + `/images/infinitemarkets/<ns>/<sha>.<ext>`.
  `public_base_url` is operator config (INFINITEMARKETS_PUBLIC_BASE_URL or
  host `lnbits_baseurl`), already validated as canonical HTTPS — request
  Host headers are never used. Appearance fields may use the safe
  same-origin relative path where the field already supports it.
- **D-05 (owner-selected: block with prompt):** If `public_base_url` cannot
  produce a public HTTPS URL (localhost/http), local uploads bound for
  Nostr-profile fields are blocked with a plain-language prompt suggesting
  INFINITEMARKETS_PUBLIC_BASE_URL or an external HTTPS/Blossom image —
  never silently store a URL that will fail on relays.

#### Quota Scope (owner-selected: local only)
- **D-06:** The 400 MB quota counts LNbits-local bytes only. Blossom bytes
  are not tracked or enforced — remote storage limits are the Blossom
  operator's concern.

### Claude's Discretion
- Shared-service shape: extract/generalize `migration_media` internals into
  a reusable local-storage adapter vs parallel implementation — engineering
  call; must keep migration-media behavior and its `/images/...` URL
  contract stable.
- BUD-11 specifics: expiration window length (short-lived), `server` tag
  normalization (endpoint path/port normalization policy), exact tag set
  beyond the required `t=upload`/`x=<sha256>`/`server`.
- Route naming for the new upload API (must still be added to
  docs/technical-specification.md §5 and `harness/registry.py::HTTP_ROUTES`
  per MEDIA-18).
- Concurrency cap for simultaneous in-flight uploads; asyncio.to_thread /
  bounded worker policy for blocking outbound HTTP.
- Duplicate-file handling (content-addressed naming implies natural
  idempotent dedup — keep or document).
- What counts as "unreferenced" for the unused-uploads listing (sidecar
  ownership vs URL references across products/settings).

### Deferred Ideas (OUT OF SCOPE)
- BUD-04 mirroring, kind-10063 server-list publication, BUD DELETE /
  remote cleanup, GIF support, server-side transforms (MEDIA-20…MEDIA-23).
- Byte-tracking/reporting for Blossom uploads (quota stays local-only per D-06).
- Auto-removal of local leftovers on editor cancel (rejected in favor of
  the explicit unused-uploads control).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| MEDIA-01 | Upload without Blossom configured; local storage default | Local adapter generalizing `migration_media.py` `_media_dir`/`_namespace`/`_sniff`/quota; backend selection helper in a new `services/media.py` |
| MEDIA-04 | Blossom auth signed server-side via merchant key; no nsec to browser | `MerchantKeyStore.sign_event(merchant_id, UnsignedEvent)` (`keystore.py:225-234`); `EventBuilder(Kind(24242), ...)` verified working in pinned `nostr-sdk==0.44.8` |
| MEDIA-05 | Bounded multipart (≤16 files, ≤25 MB/file), 400 MB local quota, PNG/JPEG/WebP only, SHA-256, descriptor validation | Existing bound constants + `MultiPartParser` streaming pattern (`views_api.py:838-887`); `_sniff` magic bytes (`migration_media.py:36-43`); BUD-02 descriptor contract fetched from spec |
| MEDIA-06 | Merchant-scoped opaque namespace outside extension package, served via host `/images` mount | `_media_dir` = `lnbits_data_folder/images/infinitemarkets/<ns24>/` (`migration_media.py:55-59`); `_namespace` = HMAC privacy-key index (`migration_media.py:46-52`) |
| MEDIA-07 | Local image in Nostr picture/banner emitted as absolute HTTPS URL | `ext_settings().public_base_url` + `/images/...` path (`settings.py:445-453`); D-05 block case = `SettingsError` at `ext_settings()` load (`settings.py:109-124`) |
| MEDIA-15 | BUD-02 raw `PUT /upload` + BUD-11 kind-24242, short expiry, `t=upload`, matching `x`/`X-SHA-256`, `server` tag, base64url no-pad | Current BUD-02/BUD-11 specs fetched verbatim this session — see Protocol Contract below |
| MEDIA-16 | HTTPS egress: request-time public-egress check, pinned-IP TLS, time/size bounds, no upload redirects | `security.resolve_and_check_egress` (`security.py:338-372`) + `_PinnedHTTPSConnection` pattern (`og_images.py:34-48`) — adapt for PUT, no redirect follow |
| MEDIA-18 | New routes in spec §5 AND `harness/registry.py::HTTP_ROUTES`; parity + fake-Blossom tests pass | Bidirectional parity = `tests/qualification/test_p0_14_contract_closure.py:185-193`; route strings are parsed from §5 fenced `text` blocks (`_spec_routes`, lines 87-114) |
</phase_requirements>

## Summary

Phase 6 adds a general merchant media-upload capability on top of two bodies of existing code: `services/migration_media.py` (bounded local ingest with HMAC merchant namespace, sidecar, quota, magic-byte sniffing) and `services/og_images.py` (request-time public-egress resolution + pinned-IP TLS via stdlib `http.client`). The new surface is: a shared local-storage adapter (generalized from migration_media without changing its manifest/relink contract), a `services/blossom.py` client doing BUD-02 raw `PUT /upload` with BUD-11 kind-24242 auth signed through `MerchantKeyStore.sign_event`, and new authenticated routes in `views_api.py` mirrored byte-for-byte into spec §5 fenced blocks and `harness/registry.py::HTTP_ROUTES`.

The current BUD-02 and BUD-11 specs were re-fetched this session and confirm — and in one place sharpen — the milestone research: BUD-11's endpoint table now marks the `x` tag **required** for `PUT /upload` (implied hash = the `X-SHA-256` request header), and the `server` tag MUST be a lowercase domain name only — no scheme, port, or path. The pinned `nostr-sdk==0.44.8` can build and sign kind-24242 events today; this was verified by executing `EventBuilder(Kind(24242), "Upload Blob").tags([...]).build(pk)` → `NostrSigner.sign_event` → `Event.as_json()` → base64url-no-pad token in the project environment.

No new dependencies are needed; the whole phase is built from the pinned stack plus Python stdlib.

**Primary recommendation:** Extract a merchant-scoped local-storage service from `migration_media.py` internals (keep its public functions untouched), add `services/blossom.py` (egress-check → pin IP → sign kind-24242 → raw PUT → validate descriptor), and expose `POST /media/upload` + `GET /media/unused` + `DELETE /media/unused/{name}` behind the existing `problem_boundary`/`check_user_exists` wrapper, registering all three in spec §5 and `HTTP_ROUTES`.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Multipart bounds, auth, CSRF | API / Backend (`views_api.py`) | — | `problem_boundary` enforces mutation security; `check_user_exists` authenticates; stream bounded before parse |
| File verification (sniff, SHA-256, quota) | API / Backend service (`services/media*.py`) | — | Same trust boundary as migration_media; never trust browser filename/MIME |
| Local persistence + public path | Storage (host data folder `/images` mount) | — | Outside reinstallable package; opaque per-merchant namespace |
| Blossom protocol + auth signing | API / Backend service (`services/blossom.py`) | Database/Storage (keystore rows) | Server-side signing is locked (MEDIA-04); egress rules locked (MEDIA-16) |
| Blossom server list ordering | Database / Storage (`settings` row) | API (PATCH merchant) | `set_blossom_servers` ordering fix touches persisted contract |
| Unused-upload listing/deletion | API / Backend | Storage | Computes "unreferenced" across product_images + settings URLs + sidecar |
| Absolute-URL emission for Nostr profile | API / Backend (`merchant.py` publish path) | — | `public_base_url` + `/images/...`; D-05 block when unavailable |
| Upload UX copy/progress | Browser / Client | — | Phase 7 mostly; Phase 6 only returns JSON the editor consumes |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python | `>=3.12,<3.13` (`pyproject.toml:5`); `uv.lock` pins `==3.12.*` | Route, parsing, hashing, storage, Blossom client | Project constraint; host-pinned |
| LNbits host / FastAPI / Starlette | Pinned host `e336fe1` (v1.6.2-rc1 line); `starlette.formparsers` in-repo | APIRouter, `check_user_exists`, `MultiPartParser`/`UploadFile` | Existing route conventions — `views_api.py:20` imports `MultiPartParser` |
| `nostr-sdk` | `0.44.8` (`pyproject.toml:12` pin) | Build/sign kind-24242 BUD-11 auth event | Already pinned; `MerchantKeyStore.sign_event` custody boundary; verified working this session |
| Python stdlib `http.client`/`ssl`/`socket`/`asyncio` | 3.12 stdlib | Blossom HTTPS PUT with pinned-IP TLS | Same transport discipline as `og_images.py`; no new dependency |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `hashlib`, `base64`, `json`, `re`, `ipaddress` | stdlib | SHA-256, base64url-no-pad auth header, descriptor parse, hostname checks | Always in this phase |
| `Pillow` | `~=12.3.0` (host-locked; already used by `og_images.py:16`) | (Optional) image decode for validation | Only if magic-byte sniff proves insufficient — not needed for v1.1 (sniff + hash is the contract) |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| stdlib `http.client` + pinned IP | `httpx` async client | httpx cannot pin a resolved IP while keeping TLS SNI without custom transport; adds dependency surface for zero gain at these bounds |
| `MerchantKeyStore.sign_event` + kind-24242 builder | Separate blossom/nostr client lib | Wrong runtime boundary; a JS or third-party lib does not solve key custody — locked decision |
| Generalize `migration_media.py` internals into shared adapter | Duplicate the bounds/sniff/quota code in a parallel module | Generalizing keeps one source of truth for namespace/sniff/quota; required anyway for the unused-uploads listing to see both flows |

**Installation:**
```bash
# No new packages. Verification only:
make verify-fast
uv run ruff check .
```

**Version verification:** `nostr-sdk==0.44.8` confirmed pinned (`pyproject.toml:12`, `uv.lock:960`). SDK capability was probed by execution (see Code Examples) rather than by registry lookup — no new package to verify.

## Package Legitimacy Audit

No external packages are installed by this phase — the Package Legitimacy Gate has no inputs. All libraries in the Standard Stack are already pinned in `pyproject.toml`/`uv.lock` or are Python stdlib.

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```text
Admin browser (Vue/Quasar)                    Blossom operator (external)
        │                                            ▲
        │ multipart/form-data (≤16 files, ≤25MB ea)  │ raw bytes PUT /upload
        ▼                                            │ Authorization: Nostr <b64url>
┌──────────────────────────────────────┐             │
│ views_api.py  POST /media/upload     │             │
│  check_user_exists + CSRF (          │             │
│    problem_boundary)                 │             │
│  bounded_stream → MultiPartParser    │             │
└──────────────┬───────────────────────┘             │
               │ (filename, bytes) per file          │
               ▼                                     │
┌──────────────────────────────────────┐             │
│ services/media.py (new shared svc)   │             │
│  _sniff magic bytes → sha256 →       │             │
│  choose backend {local | blossom}    │             │
└──────┬───────────────────┬───────────┘             │
       │ local (default)   │ blossom (explicit)      │
       ▼                   ▼                         │
┌──────────────────┐  ┌───────────────────────────┐  │
│ local_media      │  │ services/blossom.py       │  │
│ adapter          │  │  resolve_and_check_egress │  │
│  data_folder/    │  │  → pinned-IP TLS connect  │  │
│   images/        │  │  → kind-24242 sign        │──┤
│   infinitemarkets│  │    (MerchantKeyStore)     │  │
│   /<ns>/<sha>.   │  │  → PUT /upload, no        │  │
│   <ext>          │  │    redirects, bound resp  │  │
│  +manifest.json  │  │  → validate descriptor    │  │
│  sidecar + quota │  └───────────────────────────┘  │
└──────────────────┘                                 │
       │ public path  /images/infinitemarkets/<ns>/<sha>.<ext>
       ▼
 catalog images · profile picture/banner (absolute https via public_base_url)
 · appearance (same-origin relative path)
```

### Recommended Project Structure
```text
infinitemarkets/
├── views_api.py                    # POST /media/upload, GET /media/unused,
│                                   # DELETE /media/unused/{name} (names TBD)
├── services/
│   ├── media.py                    # NEW shared upload service: sniff/hash/
│   │                               # backend selection/unused-listing logic
│   ├── blossom.py                  # NEW BUD-02 PUT + BUD-11 signing + egress
│   ├── migration_media.py          # keep API stable; share internals via
│   │                               # media.py or private helpers
│   ├── relay.py                    # set_blossom_servers ordering fix (D: first
│   │                               # configured = primary)
│   ├── merchant.py                 # profile publish: local /images → absolute
│   │                               # https URL (MEDIA-07, D-05 block)
│   └── og_images.py                # reuse _PinnedHTTPSConnection shape only
├── keystore.py                     # sign_event — unchanged
└── settings.py                     # public_base_url — unchanged
tests/
├── runtime/test_media_upload.py        # NEW — route + local adapter (fast-marked
│                                       # subset where host boot not required)
├── runtime/test_blossom_upload.py      # NEW — fake Blossom HTTP server tests
└── runtime/test_relay_config_api.py    # ordering regression for blossom_servers
docs/technical-specification.md         # §5 fenced route block additions
harness/registry.py                     # HTTP_ROUTES additions
```

### Pattern 1: Backend-Proxied BUD-02 Upload With Server-Side BUD-11 Signing
**What:** Browser sends bytes to the authenticated extension route; backend hashes, signs a short-lived kind-24242 event via `MerchantKeyStore.sign_event`, and PUTs raw bytes to the first configured Blossom server.
**When to use:** Default (and only) remote path — locked by MEDIA-04/MEDIA-15.
**Example:** see Code Examples below.

### Pattern 2: Resolve-and-Pin Egress (adapted for PUT, no redirects)
**What:** `resolve_and_check_egress(host, 443)` returns only globally-routable IPs (any non-public answer rejects); connect to a checked IP while retaining the hostname as TLS SNI via an `http.client.HTTPSConnection` subclass; reject ALL 3xx for uploads.
**When to use:** Every outbound Blossom request.
**Example:** `security.py:338-372` + `og_images.py:34-48` (verbatim below).

### Pattern 3: Bounded Streaming Multipart
**What:** Wrap `request.stream()` in a counting generator that aborts past `MAX_FILES_PER_REQUEST * (MAX_FILE_BYTES + 8192)`, feed it to `MultiPartParser` with `max_files`/`max_fields`, then `item.read(MAX_FILE_BYTES + 1)` per part.
**When to use:** The new upload route; identical to `/migration/media/upload` (`views_api.py:849-887`).

### Pattern 4: Content-Addressed Local Storage With Write-Verify
**What:** Store as `<sha256>.<ext>` under `images/infinitemarkets/<ns24>/`; write `.<sha>.<ext>.tmp`, re-hash before `tmp.replace(dest)`; dedup by hash makes retries idempotent; sidecar `manifest.json` maps known URLs → filenames.
**When to use:** Local backend for every upload; generalize the sidecar so non-migration uploads are recorded for the unused-uploads listing.

### Anti-Patterns to Avoid
- **Following redirects on upload PUT:** A 307/308 replays body + `Authorization` to a different host — locked rejection (CONTEXT; PITFALLS #1).
- **Trusting `validate_blossom_url` as runtime egress control:** config-time check has no DNS pinning — always `resolve_and_check_egress` at request time (PITFALLS #3).
- **Sorting `blossom_servers`:** `set_blossom_servers` currently does `sorted({...})` (`relay.py:212`) — breaks "first configured = primary"; must preserve insertion order while still deduping.
- **Persisting BUD-11 tokens or logging `Authorization`:** tokens are replayable until expiration — keep short-lived, never log.
- **New DB table for uploads:** sidecar file + existing `product_images`/settings references suffice; no schema migration needed (ARCHITECTURE anti-pattern 3).
- **`request.body()` / `await request.form()` without bounds:** unbounded memory — keep the streaming parser pattern.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Multipart parsing | Custom boundary parser | `starlette.formparsers.MultiPartParser` + bounded stream wrapper | Boundary/edge-case correctness is subtle; existing precedent at `views_api.py:861-865` |
| Nostr event signing / canonical id | Hand-rolled sha256 + JSON | `nostr_sdk.EventBuilder`/`Tag`/`NostrSigner` via `MerchantKeyStore.sign_event` | `_canonical_rumor_id` docstring warns against hand-rolled sha256 (unicode escaping edges) — `keystore.py:453-468` |
| Magic-byte type detection | Filename/`Content-Type` header trust | `_sniff` magic bytes (`migration_media.py:36-43`) | Browser-supplied names/types are untrusted |
| DNS-safe egress | `urllib`/`requests`/default socket connect | `resolve_and_check_egress` + `_PinnedHTTPSConnection` | Prevents DNS rebinding + SSRF to private space |
| base64url auth header | `base64.b64encode` (wrong alphabet/padding) | `base64.urlsafe_b64encode(...).rstrip(b"=")` | BUD-11 requires URL-safe, unpadded |

**Key insight:** this phase is mostly *composition* — the dangerous code paths (DNS pinning, bounded parse, key custody, write-verify) already exist and are tested; new code should delegate to them, not re-implement.

## Runtime State Inventory

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `settings` rows with `key = 'blossom_servers'` contain a **sorted** JSON URL list (`relay.py:211-223`). After the ordering fix, "first" for pre-existing merchants means alphabetically-first, not user-intended-first — values are unchanged, only ordering semantics change. | No data migration possible (original order is lost). Document: existing merchants should review/re-save their Blossom list. Code edit only — preserve submitted order going forward. |
| Stored data | Sidecar `manifest.json` files under `images/infinitemarkets/<ns>/` hold `url → filename` for migration uploads. Unused-listing must treat migration-owned files as referenced-or-owned per D-02 semantics. | Code: extend sidecar schema or add parallel index for non-migration uploads (Claude's discretion on "unreferenced" definition). |
| Live service config | None — Blossom endpoints live in the extension's own `settings` table, not an external service. | none |
| OS-registered state | None — no OS-level registrations. | none |
| Secrets/env vars | `INFINITEMARKETS_PUBLIC_BASE_URL` governs D-04/D-05 behavior; unchanged name/contract. | none |
| Build artifacts | None relevant — no rename. | none |

## Common Pitfalls

### Pitfall 1: Sorted `blossom_servers` silently retargets the "primary"
**What goes wrong:** Merchant lists `media.example.com` first, but `set_blossom_servers` persists `sorted(...)` so uploads go to `blossom.primal.net`.
**Why it happens:** `validated = sorted({validate_blossom_url(u) for u in urls})` (`relay.py:212`) — dedup via set also loses order.
**How to avoid:** Dedup while preserving order (`dict.fromkeys` on validated URLs); assert in tests that `get_blossom_servers` returns submission order. Note the existing test `test_blossom_servers_configurable_with_https_only` (`tests/runtime/test_relay_config_api.py:167-187`) happens to submit an already-sorted pair — add a deliberately-unsorted case.
**Warning signs:** Test only asserts success, not which server received bytes.

### Pitfall 2: BUD-11 encoding drift (padding, wrong alphabet, missing `x`)
**What goes wrong:** Server rejects the upload (401) or accepts auth meant for a different blob.
**Why it happens:** `base64.b64encode` emits `+/` and `=` padding; spec requires URL-safe **without** padding. `x` tag must be **lowercase hex** matching `X-SHA-256` — and per the current endpoint table it is **required** for `PUT /upload`.
**How to avoid:** Assert exact header format and tag set in fake-server tests; never reuse a token across files (one sign per upload).
**Warning signs:** `=` at end of Authorization value; uppercase hex in `x`; `server` tag containing `https://` or a port — spec says lowercase domain only.

### Pitfall 3: Route registered in code but not spec/registry (or vice versa)
**What goes wrong:** `test_routes_match_spec_bidirectional` fails — it parses §5 fenced `text` blocks only (`test_p0_14_contract_closure.py:87-114`), so a route documented in prose (like the migration routes in §13.2) doesn't count, and a registry entry without a fenced §5 line fails the other direction.
**How to avoid:** Add each new route as a `METHOD /path` line inside a ```` ```text ```` fence in §5 (a new subsection like `### 5.6 Media` or within an existing admin section) AND as a string in `HTTP_ROUTES` in the same commit.
**Warning signs:** Route exists in `views_api.py` but absent from both — that's the *current* state of `/migration/media/{upload,relink}` (documented in §13.2 prose only), so the parity gate does not force them; the new routes MUST be in the fenced block per MEDIA-18.

### Pitfall 4: Blocking `http.client` stalls the event loop
**What goes wrong:** Slow Blossom server ties up the host's single loop; unrelated merchant requests stall.
**Why it happens:** `http.client` is synchronous.
**How to avoid:** `asyncio.to_thread` (precedent: `og_images.py:127-129`) with `asyncio.wait_for` deadlines and a bounded concurrency semaphore (Claude's discretion — recommend ≤4 in-flight Blossom PUTs per process).

### Pitfall 5: Descriptor trust
**What goes wrong:** Malicious/buggy server returns a descriptor pointing elsewhere, wrong `sha256`/`size`/`type`, or a non-HTTPS URL, and the extension stores that URL into the catalog/profile.
**Why it happens:** Treating HTTP-200 JSON as truth.
**How to avoid:** Validate: JSON object, `sha256` equals computed lowercase-hex digest, `size` equals byte count, `type` in the allowed image set, `url` is https, ≤2048 chars, ideally on the same origin as the target server (require same host or https subdomain — recommend same-origin host match).

### Pitfall 6: `public_base_url` failure mode (D-05)
**What goes wrong:** On an `http://` host, `ext_settings()` raises `SettingsError` — not a soft failure inside the upload route.
**Why it happens:** `_parse_base_url` requires https (`settings.py:109-124`); it runs at settings load for the whole request.
**How to avoid:** The D-05 "block with prompt" check can't rely on `ext_settings().public_base_url` succeeding — catch `SettingsError` (the route's `problem_boundary` already maps it via `config_problem`, `views_api.py:58-61`) and return a plain-language problem; or probe `host_settings.lnbits_baseurl` for scheme when deciding whether local→profile upload is permissible. [ASSUMED: that `config_problem` output is acceptable UX for this block — confirm copy with owner if it matters.]

### Pitfall 7: `images` validation rejects local `/images/...` paths
**What goes wrong:** A product saved with a local uploaded image fails `PATCH /products/{id}` because catalog validation requires `url.startswith("https://")` (`catalog.py:696-698`, `1679-1681`).
**Why it happens:** MEDIA-06 local paths are same-origin relative (`/images/infinitemarkets/...`) which fails the https check; the migration relink flow already writes such paths, so the mismatch predates this phase.
**How to avoid:** Either store absolute `public_base_url + /images/...` URLs into `product_images` (keeps https invariant; simplest — recommended), or narrowly allow the `/images/infinitemarkets/` prefix. Decide in planning; Phase 7's editor round-trip depends on it.

## Code Examples

### BUD-11 auth event build + sign (verified by execution this session)
```python
# Source: executed against pinned nostr-sdk==0.44.8 in project env — output confirmed
# kind:24242, tags [t=upload, expiration, x, server], signature verifies.
import base64, json, time
from nostr_sdk import EventBuilder, Kind, PublicKey, Tag

sha256 = "b1674191a88ec5cdd733e4240a81803105dc412d6c6708d53ab94fc248f4f553"  # computed digest
server_domain = "cdn.example.com"  # lowercase domain only — NO scheme/port/path
unsigned = (
    EventBuilder(Kind(24242), "Upload Blob")   # content MUST be human-readable
    .tags([
        Tag.parse(["t", "upload"]),
        Tag.parse(["expiration", str(int(time.time()) + 300)]),  # short-lived; 300s suggested
        Tag.parse(["x", sha256]),              # required for PUT /upload per endpoint table
        Tag.parse(["server", server_domain]),  # scopes token to one server
    ])
    .build(PublicKey.parse(pubkey_hex))
)
signed = await keystore.sign_event(merchant_id, unsigned)   # keystore.py:225-234
auth = "Nostr " + base64.urlsafe_b64encode(
    signed.as_json().encode()                  # Event.as_json() — verified method
).decode().rstrip("=")                         # URL-safe, NO padding
```

### BUD-02 PUT with pinned-IP TLS (adapted from og_images.py:34-48)
```python
# Source: infinitemarkets/services/og_images.py:34-48 — adapt GET→PUT, drop redirect handling
class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Connect to a checked IP while retaining the original TLS hostname."""
    def __init__(self, host: str, address: str, port: int = 443):
        super().__init__(host, port=port, timeout=10.0,
                         context=ssl.create_default_context())
        self._address = address
    def connect(self):
        sock = socket.create_connection((self._address, self.port), timeout=self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)

# In the async upload path:
addresses = await resolve_and_check_egress(parsed.hostname, 443)   # security.py:338-372
# ... run in asyncio.to_thread:
conn.request("PUT", upload_path, body=data, headers={
    "Content-Type": f"image/{ext}",          # from _sniff, not the browser
    "Content-Length": str(len(data)),
    "X-SHA-256": sha256,                     # lowercase hex of body
    "Authorization": auth,                   # BUD-11 token from example above
})
resp = conn.getresponse()
# REJECT any 3xx — never follow upload redirects (locked decision)
# Accept 200 (already stored) or 201 (new); validate JSON descriptor
```

### Bounded multipart route skeleton (mirror of views_api.py:838-887)
```python
@infinitemarkets_api_router.post("/media/upload")
@problem_boundary
async def media_upload(request: Request, user: User = Depends(check_user_exists)):
    merchant_id = await _mid(user)
    if not request.headers.get("content-type", "").startswith("multipart/form-data;"):
        raise unprocessable("invalid-content", "multipart upload required")

    async def bounded_stream():
        received = 0
        limit = MAX_FILES_PER_REQUEST * (MAX_FILE_BYTES + 8192)   # 16 * ~25MB
        async for chunk in request.stream():
            received += len(chunk)
            if received > limit:
                raise unprocessable("invalid-content", "upload exceeds limit")
            yield chunk

    form = await MultiPartParser(
        request.headers, bounded_stream(),
        max_files=MAX_FILES_PER_REQUEST + 1, max_fields=2,   # + fields: backend target, usage hint
    ).parse()
    # per part: item.read(MAX_FILE_BYTES + 1); pass (filename, bytes) to service
```

### Local storage write-verify (from migration_media.py:190-205)
```python
dest = media_dir / f"{sha256}.{ext}"
tmp = media_dir / f".{sha256}.{ext}.tmp"
tmp.write_bytes(content)
if hashlib.sha256(tmp.read_bytes()).hexdigest() != sha256:   # re-verify what landed
    tmp.unlink(missing_ok=True)
    # reject
tmp.replace(dest)                                            # atomic promote
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Milestone research said BUD-11 `x` tag "matching `X-SHA-256`" | Current BUD-11 endpoint table marks `x` **required** for `PUT /upload` (implied hash = `X-SHA-256` header) | BUD-11 spec (fetched 2026-10-16) | `x` is non-negotiable — always emit it |
| `server` tag treated as loosely "target-scoped" | Spec: lowercase **domain name only** — not a URL, no port/path | BUD-11 spec (fetched 2026-10-16) | Normalize `urlparse(url).hostname` (already lowercase via urlparse for ASCII; apply `.lower()` defensively for IDN) |
| `set_blossom_servers` sorted URLs | Must preserve submitted order (first = primary) | Locked Phase-6 decision | Changes a persisted contract; old rows keep alphabetical order |
| spec §15 "images per product ≤ 16" | Code says `IMAGES_MAX = 20` (`catalog.py:42`); spec correction to 20 is MEDIA-14 (Phase 7) | pre-existing drift | Phase 6 must NOT confuse the ≤16 *files per request* bound with the per-product image cap |

**Deprecated/outdated:**
- Nothing new deprecated; BUD-02 lists `GET /list` and `DELETE /<sha256>` as moved to BUD-12 in current spec text (previously BUD-03) — irrelevant here since DELETE is out of scope.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | 300 s is an acceptable "short-lived" BUD-11 expiration window | Code Examples | Server may demand shorter; trivially tunable constant |
| A2 | `config_problem`/`SettingsError` rendering is acceptable merchant UX for the D-05 public_base_url block | Pitfall 6 | Owner may want dedicated copy; error still surfaces correctly |
| A3 | Three routes (`POST /media/upload`, `GET /media/unused`, `DELETE /media/unused/{name}`) is the right surface; exact naming is Claude's discretion | Recommended Structure | Cosmetic — but every variant must still land in spec §5 + HTTP_ROUTES |
| A4 | Descriptor `url` should be validated as https on the target server's host (same-origin) | Pitfall 5 | A server legitimately returning a CDN URL on another host would be rejected — may need host-suffix rule |
| A5 | "Unreferenced" = file present in namespace but its `/images/infinitemarkets/<ns>/<name>` path not found in `product_images.url`, merchant `theme`/`profile_json` settings JSON | D-02 | If theme JSON embeds the path differently, listing may over-report unused files |
| A6 | ≤4 concurrent Blossom PUTs per process is a sane default cap | Pitfall 4 | Arbitrary; adjust under load evidence |

## Open Questions

All three questions are RESOLVED by CONTEXT.md decisions and the phase
plans (annotation added during planning revision):

1. **Absolute vs relative URL stored in `product_images` for local uploads**
   - RESOLVED by D-07: new uploads store absolute `public_base_url +
     /images/...` URLs — preserves the `https://` catalog invariant and
     satisfies MEDIA-07 in one representation. Implemented in 06-01 task 1;
     legacy relative `/images/...` acceptance is Phase 7's MEDIA-11.
2. **Should local uploads be permitted when `ext_settings()` raises `SettingsError`?**
   - RESOLVED by D-08 + the A2 assumption: the D-05 block fires only when the
     https-scheme `public_base_url` host is loopback/private/.local
     (`usage=profile`); `http://` schemes still fail earlier via
     `problem_boundary`→`config_problem`; catalog/appearance usages proceed.
     Implemented in 06-01 task 1 (`origin_is_public` + `media-origin` problem).
3. **Response shape for `GET /media/unused` and idempotency of DELETE**
   - RESOLVED: recommendation adopted verbatim in 06-01 task 2 —
     `{files: [{name, bytes, sha256}]}` listing; DELETE fullmatches
     `[0-9a-f]{64}\.(png|jpg|webp)`, 409 if referenced/sidecar-owned, 200
     idempotent if absent.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| uv | env/test runner | ✓ | 0.11.6 | — |
| Python (project) | all code | ✓ | 3.12 via uv.lock (`==3.12.*`) | — |
| node | `node --check` on JS, gsd-tools | ✓ | v25.8.2 | — |
| Pinned LNbits host | runtime tests | ✓ | `.cache/lnbits` @ `e336fe1` | `tools/checkout_host.py` (make host) |
| Outbound HTTPS to real Blossom | fake-server tests only — never required | — | — | Local fake Blossom (`http.server`-based fixture) — Phase 8 formalizes matrix |

**Missing dependencies with no fallback:** none
**Missing dependencies with fallback:** none

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1 (from test pyc headers) + pytest-asyncio; configured in `pyproject.toml` `[tool.pytest.ini_options]` |
| Config file | `pyproject.toml` lines 41-50 (`testpaths = ["tests"]`, markers: `fast`, `sdk`, `db`, `protocol`, `host`, `runtime`) |
| Quick run command | `make verify-fast` (`uv run pytest -m fast -q`) |
| Full suite command | `make verify` (`GAMMA_QUAL_EVIDENCE=1 uv run pytest -q`) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|--------------|
| MEDIA-01 | Upload with no Blossom configured → local, file lands under namespace | integration | `uv run pytest tests/runtime/test_media_upload.py -x` | ❌ Wave 0 |
| MEDIA-04 | Blossom path signs via keystore; no key material in response | unit+integration | `uv run pytest tests/runtime/test_blossom_upload.py -x` | ❌ Wave 0 |
| MEDIA-05 | Bounds: 17th file rejected; 25MB+1 rejected; SVG/GIF rejected; quota enforced | unit/integration | same file(s) — mark fast where no host boot | ❌ Wave 0 |
| MEDIA-06 | Stored path `/images/infinitemarkets/<ns>/<sha>.<ext>`; ns stable + opaque | unit | `uv run pytest tests/runtime/test_media_upload.py -x` | ❌ Wave 0 |
| MEDIA-07 | Profile publish emits absolute https URL for local image; D-05 block | integration | `uv run pytest tests/runtime/test_merchant_api.py -x` (extend) | ⚠️ extend existing |
| MEDIA-15 | Fake Blossom asserts exact BUD-02 headers + decodes/verifies kind-24242 auth | integration (fake server) | `uv run pytest tests/runtime/test_blossom_upload.py -x` | ❌ Wave 0 |
| MEDIA-16 | Private/loopback/mixed-DNS answers rejected; 307 → no second request, no auth forward | unit (resolver/conn injection) | `uv run pytest tests/runtime/test_blossom_upload.py -x` | ❌ Wave 0 |
| MEDIA-18 | Route in §5 fenced block AND `HTTP_ROUTES` | contract | covered by `tests/qualification/test_p0_14_contract_closure.py` | ✅ |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/runtime/test_media_upload.py tests/runtime/test_blossom_upload.py -q` (+ `ruff check .`)
- **Per wave merge:** `make verify-fast`
- **Phase gate:** `make verify-fast` green + targeted runtime suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/runtime/test_media_upload.py` — MEDIA-01/05/06 + route bounds
- [ ] `tests/runtime/test_blossom_upload.py` — MEDIA-04/15/16 + fake Blossom fixture (stdlib `http.server` in a thread; never hits public servers)
- [ ] Ordering regression case in `tests/runtime/test_relay_config_api.py` (unsorted input → preserved order)
- [ ] D-05/profile-path cases in `tests/runtime/test_merchant_api.py`

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|------------------|
| V2 Authentication | yes | `check_user_exists` dependency + `_merchant_owned`/`_mid` owner scope on every route |
| V3 Session Management | yes | Existing cookie + double-submit CSRF (`enforce_mutation_security` via `problem_boundary`) |
| V4 Access Control | yes | Merchant scoping on namespace dir, sidecar, settings rows; `_namespace` HMAC-derived, opaque |
| V5 Input Validation | yes | Magic-byte sniff (never filename/MIME), bounds, strict regexes for stored names and manifest |
| V6 Cryptography | yes | SHA-256 content addressing; HMAC namespace; secp256k1 signing via `nostr-sdk` — never hand-rolled |
| V12 File Upload | yes | Bounded stream parse, per-file cap, quota, allowlisted types, storage outside package |
| V13 (SSRF/egress adj.) | yes | `resolve_and_check_egress` + pinned-IP TLS + no PUT redirects |

### Known Threat Patterns for {Python/FastAPI LNbits extension + Blossom}

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SSRF via configured Blossom endpoint (DNS rebinding, private IPs) | Tampering/InfoDisclosure | `resolve_and_check_egress` rejects any non-public answer; connect pinned IP + TLS SNI; no redirects on PUT |
| Auth-token replay (leaked BUD-11 token) | Spoofing | Short `expiration`, `server`+`x` scoping, one token per upload, never log `Authorization` |
| Upload-body memory exhaustion | DoS | Bounded stream + per-file cap + part cap (existing pattern) |
| Malicious descriptor (URL poison, hash mismatch) | Tampering | Validate `sha256`/`size`/`type`/`url` before returning |
| Active content (SVG) / polyglot images | Tampering | PNG/JPEG/WebP allowlist by magic bytes only |
| Key exfiltration to browser | InfoDisclosure | Server-side `sign_event`; nsec never leaves backend |
| Quota bypass via orphan files | DoS | Every stored byte counts toward 400 MB local quota (D-01) |

## Sources

### Primary (HIGH confidence)
- `https://raw.githubusercontent.com/hzrd149/blossom/master/buds/02.md` — fetched this session; PUT /upload contract, descriptor fields, status codes
- `https://raw.githubusercontent.com/hzrd149/blossom/master/buds/11.md` — fetched this session; kind-24242, required `x` for PUT /upload, `server`=domain-only, base64url-no-pad header
- Executed probe in project env: `EventBuilder(Kind(24242), "Upload Blob").tags([t,expiration,x,server]).build(pk)` → `NostrSigner.sign_event` → `as_json()` → base64url — signature verified ✓
- `infinitemarkets/services/migration_media.py:27-43,46-59,126-213` — bounds, sniff, namespace, write-verify, `_local_url` (verbatim values quoted above)
- `infinitemarkets/security.py:320-372` — `is_public_ip`/`resolve_and_check_egress`
- `infinitemarkets/services/og_images.py:22-93` — `_PinnedHTTPSConnection`, bounds, redirect policy
- `infinitemarkets/services/relay.py:163-224` — `validate_blossom_url`, `get_/set_blossom_servers` (sorted at :212)
- `infinitemarkets/views_api.py:36-78,838-887` — `problem_boundary`, bounded multipart precedent
- `infinitemarkets/settings.py:109-124,445-453` — `_parse_base_url`/`public_base_url`
- `harness/registry.py:178+` `HTTP_ROUTES`; `tests/qualification/test_p0_14_contract_closure.py:87-114,185-193` — route parity mechanics

### Secondary (MEDIUM confidence)
- `.planning/research/{STACK,ARCHITECTURE,PITFALLS}.md` — prior milestone research (consistent with re-fetched specs)

### Tertiary (LOW confidence)
- Expiration-window length, concurrency cap, unused-listing definition — Claude's discretion items (see Assumptions Log)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — pinned deps verified by file read + execution probe; no new packages
- Architecture: HIGH — all reused surfaces read directly; diagrams trace real data flow
- Pitfalls: HIGH — each pitfall cites the current spec text or a verified code line

**Research date:** 2026-10-16
**Valid until:** ~30 days (BUD specs are `draft` status — re-fetch before Phase 8 qualification)
