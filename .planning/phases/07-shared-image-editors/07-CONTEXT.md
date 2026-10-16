# Phase 7: Shared Image Editors - Context

**Gathered:** 2026-10-16
**Status:** Ready for planning

<domain>
## Phase Boundary

Merchants can manage every in-scope image field with consistent upload,
editing, and persistence behavior without losing existing references or
unrelated settings. This phase delivers the editor UI + API wiring — it
consumes Phase 6's storage layer (`POST /media/upload`, `GET`/`DELETE
/media/unused`). No storage-layer changes beyond what the editors require;
no new protocol work.

Requirements: MEDIA-02, MEDIA-03, MEDIA-08, MEDIA-09, MEDIA-10, MEDIA-11,
MEDIA-12, MEDIA-13, MEDIA-14.

</domain>

<decisions>
## Implementation Decisions

### Locked Owner Decisions (carried from milestone + Phase 6)
- Explicit destination choice per upload when Blossom is configured; local
  is the default; first configured Blossom server only; no dual-write, no
  silent failover — failure gives plain-language error + explicit local
  retry.
- ≤20 product images, consistent across service/spec/UI/tests (MEDIA-14).
- Per-file progress and per-file errors; a failed file never discards
  siblings; cancelling before save discloses possible unreferenced blob.
- Pasted https:// URLs and migration-managed `/images/...` +
  `/library/infinitemarkets/...` references remain supported (MEDIA-11;
  `/library/` became the canonical prefix in Phase 6 gap closure).
- Pasted-URL workflow is preserved alongside the picker — URL entry is
  never removed.
- Upload-vs-save are separate steps; UI copy says which server receives
  bytes.

### Gallery UX (owner-selected: unified list, buttons, first=primary)
- **D-14:** Product gallery is ONE unified thumbnail list mixing uploaded
  files and pasted URLs — every entry gets a thumbnail.
- **D-15:** Ordering via up/down buttons (mobile-reliable, keyboard-
  accessible); first item is the primary image, shown with a "Primary"
  badge.
- **D-16:** Per-item remove × plus an explicit "Clear all" control; an
  "Add image by URL" affordance lives inside the same control.

### Destination Picker UX (owner-selected: in-control selector)
- **D-17:** Each upload control shows its own selector:
  "Save to LNbits" / "Save to Blossom · <server-hostname>". Defaults to
  local every time; the Blossom option renders only when servers are
  configured. Choice is made at the moment of upload — one backend per
  file.

### Unused Uploads (owner-selected: Settings → Media section)
- **D-18:** A dedicated "Media" block in Settings lists unreferenced local
  files (name, size, date) with per-item delete + delete-all, backed by
  Phase 6's `GET`/`DELETE /media/unused`. Include quota usage display.
- **D-19 (deferred copy fix):** the two `admin.html` labels still saying
  "(https or /images/…)" get corrected here — now reads `/library/` per
  Phase 6's mount fix.

### Upload Entry Points (owner-selected: button + drop-zone)
- **D-20:** A dashed drop-zone that doubles as the "Choose files" button —
  drag-drop on desktop, tappable on mobile, identical control shape at all
  six field locations (Quasar-compatible).

### Catalog API semantics (from Phase 6 pitfalls — binding)
- **D-21:** `images` field semantics: OMITTED = preserve existing images;
  EMPTY ARRAY = clear all; populated = replace with ordered list. The
  existing `if (images.length) body.images = images` guard in
  admin_catalog.js must be reworked so explicit clear-all reaches the API.
- **D-22:** Local uploads bound for Nostr profile avatar/banner are blocked
  with a plain-language prompt when `public_base_url` is loopback/private
  (D-05/D-08 — Phase 6 backend gate; the UI must surface it cleanly).

### Post-Research Decision Locks (owner-delegated defaults, confirmed 2026-10-16)
- **D-23:** Extend `GET /media/unused`'s response with `mtime` (date) and
  `used_bytes`/`quota_bytes` rather than adding routes — required by
  D-18's date + quota display; response-shape extension avoids MEDIA-18
  route-parity churn.
- **D-24:** Reusable control = a `gm-media-picker` Vue component registered
  via `window.app.component({template})` in a new `admin_media.js` module
  (pinned host ships `vue.global.prod.js` with the runtime compiler —
  verified). Identical shape at all 7 field sites.
- **D-25:** Uploads use XHR (not fetch) — MEDIA-12 needs upload-progress
  events fetch can't report. Dedicated `gmMediaUpload` helper modeled on
  `admin_migration.js`; FormData fields exactly `usage`, `backend`, `file`;
  CSRF via `X-CSRF-Token` echo of the `gm_csrf` cookie.
- **D-26:** Field-value matrix: profile avatar/banner + product gallery
  store `result.url` (absolute https — validators + NIP-99 verbatim emit);
  Appearance fields store `result.path` (same-origin `/library/...`,
  always passes theme media validation). Blossom results have no `path` —
  branch on `result.backend`.
- **D-27:** Gallery save always sends `body.images` — omitted=preserve,
  `[]=clear, populated=ordered replace` (D-21); remove the
  `if (images.length)` guard.
- **D-28:** No Idempotency-Key header (matches migration precedent; the
  backend accepts but doesn't require it).
- **D-29:** Keep existing URL q-inputs for pasted URLs; pickers render
  adjacent. `test_admin_ui.py` greps served markup verbatim and
  `test_settings_buttons_are_solid` forbids `outline` q-btn in settings —
  assertion updates land in the same commit as markup changes.

### Claude's Discretion
- Thumbnail generation for pasted URLs (load the remote image directly —
  do NOT proxy through backend; SSRF rule stands).
- "Primary" representation — purely visual badge on item 0, no separate
  field unless storefront/Nostr projection needs it.
- How the destination selector collapses when no Blossom is configured
  (hide vs disabled-with-hint — recommend hide + optional hint line).
- Exact upload progress UI (per-file bar vs spinner+state label).
- Whether the Media settings block lives in its own tab/card vs appended
  to an existing settings card — follow existing settings layout.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & roadmap
- `.planning/REQUIREMENTS.md` — MEDIA-02, 03, 08–14 (+ deferred 20–23)
- `.planning/ROADMAP.md` — Phase 7 success criteria (5 items)
- `.planning/STATE.md` — locked owner decisions

### Contract surfaces
- `docs/technical-specification.md` §5 — route table (no new routes
  expected this phase unless the editors need one; MEDIA-18 applies if so)
- `docs/technical-specification.md` §15 — image cap text (now 20)
- `harness/registry.py` — HTTP_ROUTES parity if any route is added

### Research & prior phase
- `.planning/research/FEATURES.md` — shared uploader UX survey
- `.planning/research/ARCHITECTURE.md` — shared uploader state model
- `.planning/research/PITFALLS.md` — empty-array-vs-omitted semantics,
  image-cap mismatch, /images→/library mismatch
- `.planning/phases/06-secure-media-storage/06-CONTEXT.md` — D-01…D-13
- `.planning/phases/06-secure-media-storage/06-VERIFICATION.md` — what the
  storage layer actually does (endpoints, problem codes, response shape)
- `.planning/phases/06-secure-media-storage/06-04-SUMMARY.md` — the
  `/library/` mount fix, dual-prefix rules, deferred admin.html label fix

### Code surfaces
- `infinitemarkets/templates/infinitemarkets/admin.html` — product editor
  `images_text` textarea (~line 619), Appearance brand logo (~973),
  hero image_url (~2468), share custom_image_url (~2540), profile
  picture/banner fields, migration file input precedent (~1208)
- `infinitemarkets/static/infinitemarkets/js/admin_catalog.js` — editor
  state, `gmApi` helper, images serialization (~lines 408–466; the
  `if (images.length)` clear-all bug)
- `infinitemarkets/static/infinitemarkets/js/admin_settings.js` — settings
  editor wiring
- `infinitemarkets/services/catalog.py` — `IMAGES_MAX = 20`,
  `_valid_image_url` (owned-prefix allowlist added in 06-04)
- `infinitemarkets/services/media.py` + `views_api.py` media routes —
  Phase 6 API surface

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `POST /media/upload` returns descriptor `{url, path, sha256, size,
  media_type, backend}` — editors consume `url`/`path` only; no tokens.
- `GET /media/unused` + `DELETE /media/unused/{name}` power D-18.
- `gmApi(method, path, body)` — established authenticated+CSRF JSON helper.
- Migration file input (`type="file"` at admin.html:1208) — precedent for
  file picking in this codebase.
- Quasar components available: q-input, q-btn, q-linear-progress or
  q-circular-progress, q-badge, q-banner, q-menu/select — no build step,
  CDN templates only.

### Established Patterns
- Admin is server-rendered Jinja + Vue 3 (options-API-ish `admin_catalog.js`
  `self`-scoped methods) — components are template + JS state, not SFCs.
- Plain-language merchant copy everywhere; errors via q-banner blocks.
- Product save sends full ordered `images: [{url}]` list (replace semantics).

### Integration Points
- `catalog.py` PATCH/POST `images` validation — `_valid_image_url` accepts
  https + owned `/library/`+`/images/` prefixes (06-04).
- Storefront + Nostr projections re-read `product_images` ordering —
  persistence changes flow automatically once the API accepts them.
- `get_blossom_servers` result drives the destination selector's Blossom
  option (hostname display) — Settings → Merchant already loads it.

</code_context>

<specifics>
## Specific Ideas

- Upload copy must name the destination server ("saving to
  blossom.nostr.build"), separate upload from save, warn on cancel about
  unreferenced blobs, and explain local fallback — plain merchant language.
- Product gallery ordering must persist through the catalog API and appear
  in storefront + Nostr projections (MEDIA-13) — ordering IS the list order.
- Keep the design direction: compact Linear-like merchant control plane;
  16px+ body on mobile; visible focus; no layout shift from thumbnails
  (fixed aspect/reserved space).

</specifics>

<deferred>
## Deferred Ideas

- MEDIA-20…23 (mirroring, kind-10063, remote delete, GIF/transforms).
- Server-side thumbnail generation (storefront uses original URLs).
- Remote-blob management UI beyond the local unused-files list.
- Drag-drop reordering (buttons chosen; drag can be revisited later).

</deferred>

---

*Phase: 7-shared-image-editors*
*Context gathered: 2026-10-16*
