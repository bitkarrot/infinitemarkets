# Phase 6: Secure Media Storage - Context

**Gathered:** 2026-10-16
**Status:** Ready for planning

<domain>
## Phase Boundary

Merchants can upload bounded, verified images to durable LNbits-local storage
or securely use Blossom through the server-side upload boundary. This phase
delivers the storage layer only — local adapter, Blossom client, authenticated
upload API route, and the media-service plumbing — not the editor UI
(Phase 7) or release qualification/fake-Blossom test matrix (Phase 8).

Requirements: MEDIA-01, MEDIA-04, MEDIA-05, MEDIA-06, MEDIA-07, MEDIA-15,
MEDIA-16, MEDIA-18.

</domain>

<decisions>
## Implementation Decisions

### Locked Owner Decisions (from milestone discussion; restated for agents)
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

### Leftover Uploads (owner-selected: leave + cleanup control)
- **D-01:** An uploaded-but-unsaved file is left in place; the editor copy
  discloses it may remain unreferenced and it counts toward the local quota.
- **D-02:** Provide a "view unused uploads" capability that lists
  unreferenced local files so the merchant can delete them explicitly.
  Local deletion is allowed; remote Blossom deletion is NOT (deferred
  requirement MEDIA-22 territory — do not implement BUD DELETE).

### Upload Batching (owner-selected: one file per request)
- **D-03:** Each file is sent as its own multipart request. Per-file progress
  and per-file retry are native; a rejected file never affects siblings.
  The 16-files-per-request ceiling remains as the service-level bound even
  though the UI sends one at a time.

### Public URL for Local Images (pre-answered by existing code)
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

### Quota Scope (owner-selected: local only)
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

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & roadmap
- `.planning/REQUIREMENTS.md` — MEDIA-01…MEDIA-19 + deferred MEDIA-20…23
- `.planning/ROADMAP.md` — Phase 6 success criteria; PR #28 release dependency
- `.planning/STATE.md` — locked owner decisions

### Product contract
- `docs/technical-specification.md` §5 — HTTP routes (new route must be added);
  §15 — image cap currently says 16, must be corrected to 20 (MEDIA-14);
  §4.11 — nostr relay schema (blossom_servers is an extension delta)
- `harness/registry.py` — `HTTP_ROUTES` (new route must be registered;
  bidirectional parity test with spec §5)

### Research
- `.planning/research/STACK.md` — backend-proxy approach, BUD-02/BUD-11
  mechanics, stdlib http.client + pinned egress rationale
- `.planning/research/ARCHITECTURE.md` — proposed `services/blossom.py`,
  shared local adapter, no schema migration default
- `.planning/research/PITFALLS.md` — GET-vs-PUT redirects, BUD-11 encoding,
  SSRF/DNS rebinding, empty-image-array semantics, server ordering bug

### Code to reuse
- `infinitemarkets/services/migration_media.py` — local storage adapter
  foundation (namespace, sidecar, bounds, magic-byte sniff, `/images` mount)
- `infinitemarkets/services/og_images.py` — `resolve_and_check_egress`,
  pinned-IP TLS fetch pattern (reuse for Blossom client)
- `infinitemarkets/services/relay.py` — `validate_blossom_url`,
  `get_blossom_servers`, `set_blossom_servers` (ordering fix needed)
- `infinitemarkets/keystore.py` — `MerchantKeyStore.sign_event` for BUD-11
- `infinitemarkets/settings.py` — `ext_settings().public_base_url`
- `infinitemarkets/views_api.py` — existing `/migration/media/upload`
  bounded-multipart pattern to mirror for the new general upload route

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `migration_media.py`: `_sniff` (png/jpg/webp magic bytes), `_namespace`
  (HMAC merchant namespace, 24 chars), `_media_dir` (data-folder
  `images/infinitemarkets/<ns>/`), sidecar ownership map, constants
  MAX_FILES_PER_REQUEST=16 / MAX_FILE_BYTES=25MB / MAX_MERCHANT_BYTES=400MB.
- `og_images.py`: `resolve_and_check_egress` + pinned-IP `http.client`
  pattern — the Blossom client should reuse this egress discipline; only
  the redirect policy differs (reject on PUT).
- `views_api.py` `/migration/media/upload`: bounded multipart parsing
  precedent (part cap, per-file read cap, manifest field handling).
- `relay.py`: blossom URL validation + starter endpoint list
  (`blossom.nostr.build` etc.).

### Established Patterns
- Settings stored per-merchant in `settings` table keyed by name.
- Auth via `check_user_exists` + CSRF on all authenticated API routes.
- Errors via typed `conflict(...)`/validation helpers returning JSON.

### Integration Points
- New `POST` upload route in `views_api.py` (authenticated, CSRF).
- `relay.py::set_blossom_servers` ordering fix touches Settings → Merchant
  save path + tests.
- `merchant.py` Nostr profile publish path needs `public_base_url` +
  local `/images/...` resolution for avatar/banner (MEDIA-07).
- Sidecar/ownership map extends to non-migration uploads so the
  unused-uploads listing can compute "unreferenced".

</code_context>

<specifics>
## Specific Ideas

- Upload UX disclosure copy must name which server receives bytes,
  separate upload-from-save, warn about unreferenced remote blobs, and
  explain the local fallback — plain merchant language (from roadmap).
- PR #28 (`fix/og-image-redirects`) is open and CI-green; merge and verify
  it before release — it is a Phase 8 gate, not Phase 6 scope.

</specifics>

<deferred>
## Deferred Ideas

- BUD-04 mirroring, kind-10063 server-list publication, BUD DELETE /
  remote cleanup, GIF support, server-side transforms (MEDIA-20…MEDIA-23).
- Byte-tracking/reporting for Blossom uploads (rejected: quota stays
  local-only per D-06).
- Auto-removal of local leftovers on editor cancel (rejected in favor of
  the explicit unused-uploads control).

</deferred>

---

*Phase: 6-secure-media-storage*
*Context gathered: 2026-10-16*
