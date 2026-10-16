# Phase 7: Shared Image Editors - Research

**Researched:** 2026-10-16
**Domain:** No-build-step admin UI (server-rendered Jinja + Vue 3 global build + Quasar 2 UMD) consuming the Phase 6 media API
**Confidence:** HIGH — nearly all load-bearing facts verified in-repo this session; only Quasar API surface details are cited from official docs

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

#### Locked Owner Decisions (carried from milestone + Phase 6)
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

#### Gallery UX (owner-selected: unified list, buttons, first=primary)
- **D-14:** Product gallery is ONE unified thumbnail list mixing uploaded
  files and pasted URLs — every entry gets a thumbnail.
- **D-15:** Ordering via up/down buttons (mobile-reliable, keyboard-
  accessible); first item is the primary image, shown with a "Primary"
  badge.
- **D-16:** Per-item remove × plus an explicit "Clear all" control; an
  "Add image by URL" affordance lives inside the same control.

#### Destination Picker UX (owner-selected: in-control selector)
- **D-17:** Each upload control shows its own selector:
  "Save to LNbits" / "Save to Blossom · <server-hostname>". Defaults to
  local every time; the Blossom option renders only when servers are
  configured. Choice is made at the moment of upload — one backend per
  file.

#### Unused Uploads (owner-selected: Settings → Media section)
- **D-18:** A dedicated "Media" block in Settings lists unreferenced local
  files (name, size, date) with per-item delete + delete-all, backed by
  Phase 6's `GET`/`DELETE /media/unused`. Include quota usage display.
- **D-19 (deferred copy fix):** the two `admin.html` labels still saying
  "(https or /images/…)" get corrected here — now reads `/library/` per
  Phase 6's mount fix.

#### Upload Entry Points (owner-selected: button + drop-zone)
- **D-20:** A dashed drop-zone that doubles as the "Choose files" button —
  drag-drop on desktop, tappable on mobile, identical control shape at all
  six field locations (Quasar-compatible).

#### Catalog API semantics (from Phase 6 pitfalls — binding)
- **D-21:** `images` field semantics: OMITTED = preserve existing images;
  EMPTY ARRAY = clear all; populated = replace with ordered list. The
  existing `if (images.length) body.images = images` guard in
  admin_catalog.js must be reworked so explicit clear-all reaches the API.
- **D-22:** Local uploads bound for Nostr profile avatar/banner are blocked
  with a plain-language prompt when `public_base_url` is loopback/private
  (D-05/D-08 — Phase 6 backend gate; the UI must surface it cleanly).

### Claude's Discretion
- Component organization (shared Vue component vs mixin-style factory —
  codebase is vanilla-JS + Quasar templates, no build step).
- Thumbnail generation for pasted URLs (load the remote image directly —
  do NOT proxy through backend; SSRF rule stands).
- "Primary" representation — purely visual badge on item 0, no separate
  field unless storefront/Nostr projection needs it.
- How the destination selector collapses when no Blossom is configured
  (hide vs disabled-with-hint — recommend hide + optional hint line).
- Exact upload progress UI (per-file bar vs spinner+state label).
- Whether the Media settings block lives in its own tab/card vs appended
  to an existing settings card — follow existing settings layout.

### Deferred Ideas (OUT OF SCOPE)
- MEDIA-20…23 (mirroring, kind-10063, remote delete, GIF/transforms).
- Server-side thumbnail generation (storefront uses original URLs).
- Remote-blob management UI beyond the local unused-files list.
- Drag-drop reordering (buttons chosen; drag can be revisited later).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| MEDIA-02 | Explicit Blossom choice per upload; first configured server only, order preserved, no dual-write/silent retry | `backend=blossom` form field on `POST /media/upload` → `_store_blossom` PUTs `servers[0]` only (media.py:232-241); `set_blossom_servers` dedups first-seen, never sorts (relay.py:211-229); UI reads server list from `GET /merchants/{id}/relay-health` → `blossom_servers` (views_api.py:263-265) |
| MEDIA-03 | Blossom failure → plain-language error + explicit local retry | `_store_blossom` re-raises typed ProblemError whose detail names the server and says "Nothing was stored locally — retry the upload, or upload with backend=local" (media.py:259-267); `media-backend` 422 when none configured (media.py:233-240); UI maps problem → copy via `gmProblemCopy` (admin_app.js:120-130) |
| MEDIA-08 | One reusable upload control across product gallery, profile avatar/banner, brand logo, hero bg, footer logo, custom share image | All 7 field sites located (admin.html:619, 1938, 1941, 2426, 2468, 2517, 2539-2543); `usage` field vocabulary `catalog|profile|appearance` verified (media.py:30); shared-component + shared-mixin approach documented under Architecture Patterns |
| MEDIA-09 | Gallery: multi-file, thumbnails, primary, ordering, per-image remove, clear-all | `product_images` ordered by `sort_order` (catalog.py:784-800, 1131-1132); storefront first-image = `product.images[0]` (public_product.html:69); unified-list state model + button reorder pattern below |
| MEDIA-10 | Single-image fields replace/clear without touching unrelated fields | Profile: PATCH `/merchants/{id}` `profile_json` — client merges onto `profileJson` copy then deletes empty keys (admin_settings.js:557-565); theme: PATCH `theme` rebuilt whole from `gmSettings.theme` (admin_settings.js:1062-1083); server validates `picture`/`banner` https-only (merchant.py:352-362) |
| MEDIA-11 | Pasted https + migration `/images/...`, `/library/...` refs keep working | `_valid_image_url` accepts `https://`, `migration_media.MEDIA_URL_PREFIX` (`/library/infinitemarkets/`), `LEGACY_MEDIA_URL_PREFIX` (`/images/infinitemarkets/`) — verbatim at catalog.py:61-71; theme `_validate_media_url` accepts same-origin `/path` or https (themes.py:191-202) |
| MEDIA-12 | Per-file progress + per-file errors; siblings preserved on failure; cancel disclosure | One-file-per-request FormData (D-03); XHR `upload.onprogress` required — `fetch()` has no upload-progress API; per-file `state:"stored"|"rejected"` + `reason` in `results[]` (media.py:113-131, 246-275); problem codes mapped to copy below |
| MEDIA-13 | Ordering/removal/clear-all persist via catalog API, visible in projections | `images` key presence triggers DELETE+reinsert in list order, `sort_order` defaults to index (catalog.py:782-800); NIP-99 emits sorted image tags verbatim (events.py:101-104); the `if (images.length)` guard bug at admin_catalog.js:466 is the required fix |
| MEDIA-14 | 20-image cap consistent everywhere | `IMAGES_MAX = 20` (catalog.py:43); spec §15 already says ≤20 (technical-specification.md:1867); admin.html:1278 migration copy already says 20 — new gallery control must enforce the same number |
</phase_requirements>

## Summary

The admin shell is a single Jinja template (`admin.html`, 3862 lines) whose page markup lives inside `{% raw %}` and renders through the **host's own Vue app**: `window.app = Vue.createApp({el: '#vue'})` is created by `base.html` *before* extension scripts run, and `window.app.use(Quasar)` + `app.mount('#vue')` happen *after* (`.cache/lnbits/lnbits/templates/base.html:112-121`, `init-app.js:244-249`). Extension JS registers `window.app.mixin(...)` modules — `admin_app.js` provides `gmApi`/`gmProblemCopy`/boot logic; each surface (`admin_catalog.js`, `admin_settings.js`, …) adds one `gm*` state slice and methods. The pinned host (`e336fe1`) vendors **Vue 3.5.34 `vue.global.prod.js`** (full build — runtime template compiler included) and **Quasar 2.22.0 UMD**, so every `q-*` component resolves globally and `window.app.component(name, {template: '...'})` is legal.

The Phase 6 API the editors consume is verified: `POST /media/upload` takes multipart fields `usage` (`catalog|profile|appearance`, default `catalog`), `backend` (`local|blossom`, default `local`), plus file parts; returns `{"uploaded", "results": [{file, state, backend, sha256, bytes, path?, url, server?}], ...}`. `GET /media/unused` returns `{files: [{name, bytes, sha256}]}` — **no date and no quota fields**, a real gap against D-18's "(name, size, date) ... quota usage display" that the planner must close (recommend extending `list_unused` rather than adding a route). `DELETE /media/unused/{name}` is idempotent; `media-referenced` conflicts while in use.

The two known landmines are exactly the ones CONTEXT flags: (1) `admin_catalog.js:466` `if (images.length) body.images = images` makes clear-all unreachable — the gallery must always send the ordered list; (2) `profile_json.picture`/`banner` are validated **https-only** both client-side (admin_settings.js:533-541) and server-side (merchant.py:352-362), so profile-bound uploads must store `result.url` (absolute), while Appearance fields should prefer `result.path` (same-origin `/library/...` passes `themes.py` `_validate_media_url` even when `public_base_url` is an IP-literal host that would fail `_https_url_ok`).

**Primary recommendation:** Add one `admin_media.js` module that (a) registers a `gm-media-picker` component via `window.app.component` — hidden `<input type="file">` + dashed drop-zone + in-control destination selector + disclosure copy — and (b) mixes in shared `gmMedia` state/methods: lazy Blossom-server fetch from `relay-health`, an `XMLHttpRequest`-based `gmMediaUpload` (needed for per-file progress — `fetch()` cannot report upload progress), and `gmMediaUnused` list/delete helpers. Keep each field's own list/scalar state in the owning mixin (`gmCatalog.editor` / `gmSettings`); the picker only emits files + the chosen backend.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| File picking, drop-zone, thumbnails, ordering, remove/clear-all | Browser / Client | — | Pure DOM state; backend already orders by `sort_order` = list index |
| Destination selector (local/Blossom) | Browser / Client | API / Backend | UI sends `backend` field; server enforces first-server-only rule |
| Upload transport + progress | Browser / Client | — | XHR `upload.onprogress`; CSRF header + cookie auth |
| Image storage, sniffing, hashing, quota, Blossom PUT | API / Backend | Database / Storage | Phase 6 complete — no rework this phase |
| Image list persistence (replace/clear semantics) | API / Backend | Database / Storage | `product_images` replace on `images` key presence — exists |
| Profile/theme field persistence | API / Backend | — | Existing `PATCH /merchants/{id}` `profile_json`/`theme` paths — merge client-side, preserve unrelated keys |
| Unused-file listing + delete | API / Backend | Browser / Client | `GET`/`DELETE /media/unused` exist; response likely needs `mtime`/quota fields added (gap — see Open Questions) |
| Plain-language error mapping | Browser / Client | API / Backend | `gmProblemCopy` + typed problem codes (`media-origin`, `media-backend`, `media-quota`, `media-referenced`) |
| NIP-99/kind-0 projection of saved images | API / Backend | — | Automatic once persisted; NIP-99 image tags emit `img["url"]` verbatim (events.py:101-104) |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Vue (global build) | 3.5.34 `vue.global.prod.js` | Admin reactivity; in-DOM + string templates | Host-vendored; compiler included so `window.app.component({template})` works [VERIFIED: .cache/lnbits/package.json deps `"vue": "3.5.34"`; `lnbits/static/vendor.json` lists `vendor/vue.global.prod.js`; `base.html:112` `window.app = Vue.createApp({el:'#vue'})`] |
| Quasar (UMD) | 2.22.0 `quasar.umd.prod.js` | `q-input`, `q-btn`, `q-select`, `q-banner`, `q-badge`, `q-linear-progress`, `q-img`, `q-checkbox`, `q-dialog` | Host-vendored, globally registered via `app.use(Quasar)` (init-app.js:245) [VERIFIED: package.json `"quasar": "2.22.0"`; `QUploader` present at quasar.umd.js:33573] |
| Native `XMLHttpRequest` | browser | Multipart upload with per-file progress events | `fetch()` has no upload-progress callback; QUploader itself uses `xhr.upload.addEventListener('progress')` internally (quasar.umd.js:33485) |
| Native `FormData` + `<input type="file" multiple>` | browser | Multipart body + file picking | Precedent: `admin_migration.js:100-133` `gmShopifyUpload` posts FormData with only `X-CSRF-Token` header (browser sets the boundary) |
| `gmApi` / `gmProblemCopy` | in-repo | JSON API calls + problem→copy mapping | Established helper; JSON-only — multipart needs the separate XHR helper |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Quasar `QUploader` | 2.22.0 | Self-contained uploader w/ internal XHR + `factory` prop | Considered — its built-in file-list chrome fights D-14/D-20's unified-thumbnail + dashed-drop-zone design; not recommended (see Alternatives) |
| `q-img` | 2.22.0 | Fixed-ratio thumbnails (no layout shift) | Gallery tiles — reserve space per the design direction |
| `q-linear-progress` / `q-circular-progress` | 2.22.0 | Per-file progress | Inside gallery tile / single-field upload row |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Custom drop-zone + hidden file input + XHR | `QUploader` with `factory`/slots | QUploader is verified present and supports `factory`, `headers`, `form-fields`, `with-credentials` [CITED: quasar.dev/vue-components/uploader], but ships its own queued-file list chrome — you'd hide its UI to build D-14's unified list anyway, keeping none of its value except the XHR (10 lines). Custom control = identical shape at all 7 sites, less code. |
| `window.app.component("gm-media-picker", {template})` | Shared mixin methods + copy-pasted markup block | Mixin-only is the codebase's existing idiom (zero registered components today), but 7 near-identical markup blocks drift. Component-with-template-string is legal here (full Vue build) and keeps "identical control shape" (D-20) structurally enforced. |
| XHR upload helper | `fetch()` + FormData | `fetch()` cannot report upload progress — MEDIA-12 requires per-file progress. XHR is required. |
| Extend `GET /media/unused` response | New quota/route endpoints | A new route triggers MEDIA-18 spec §5 + `harness/registry.py` parity work; extending the existing response shape does not. |

**Installation:** none — zero new packages; everything is host-vendored or in-repo.

## Package Legitimacy Audit

No external packages installed this phase — N/A (all dependencies host-vendored or browser-native).

## Architecture Patterns

### System Architecture Diagram

```text
admin.html ({% raw %} Vue markup)
 ├── product editor: gmCatalog.editor.form.images[] unified gallery list
 │     (thumbnails · up/down · Primary badge · remove · Clear all · Add-by-URL)
 ├── Settings→Merchant: profileAvatar / profileBanner fields
 └── Settings→Appearance: brand.logo_url / hero.image_url /
        footer.logo_url / share.custom_image_url
            │
            ▼  all seven use the same control
<gm-media-picker usage="catalog|profile|appearance" :multiple="bool">
   dashed drop-zone + hidden <input type=file> + destination selector
            │ emits files + chosen backend (default "local")
            ▼
gmMediaUpload(file, {usage, backend}) — XHR multipart
   fields: usage, backend, file           (≤4 non-file fields OK)
   headers: X-CSRF-Token (gm_csrf cookie)  Origin (browser-set)
            │
            ▼
POST /infinitemarkets/api/v1/media/upload
   local  → result.{path=/library/…, url=<public_base_url>/library/…}
   blossom→ result.{url=https://<server>/…, server}  (first server only)
            │
            ▼  editors bind the returned value
   catalog/product gallery → images[].url ← result.url   (D-07 absolute form)
   profile picture/banner  → profile_json.{picture,banner} ← result.url (https required)
   appearance fields       → theme.* ← result.path (local) or result.url (blossom)
            │
            ▼
existing saves: PATCH /products/{id} {images:[…]} · PATCH /merchants/{id}
{profile_json|theme} — project to storefront + Nostr automatically
```

### Recommended Project Structure

```text
infinitemarkets/
├── static/infinitemarkets/js/
│   ├── admin_media.js              # NEW: gm-media-picker component + gmMedia mixin
│   ├── admin_catalog.js            # EDIT: gallery state replaces images_text;
│   │                             #       always send body.images (D-21 fix at :466)
│   ├── admin_settings.js           # EDIT: wire pickers to profile/theme fields;
│   │                             #       Media (unused uploads) block state
│   └── admin_app.js                # MAYBE: ERROR_COPY additions for media-* codes
├── templates/infinitemarkets/
│   └── admin.html                  # EDIT: 7 field sites + Media card + script tag;
│                                 #       D-19 label fixes at :2519, :2542
├── services/media.py               # LIKELY EDIT: list_unused → add mtime + quota
│                                 #   fields (D-18 gap — no new route)
└── docs/technical-specification.md # EDIT only if list_unused response is extended
                                    #   (prose §5.6) — no new routes needed
tests/
└── runtime/test_admin_ui.py        # EDIT: assertions for new markup/JS strings
    runtime/test_media_upload.py    # EDIT: if list_unused response extended
    runtime/test_catalog_api.py     # ADD: images:[] clear-all PATCH regression
```

### Pattern 1: Registered component for the shared control

**What:** `window.app.component("gm-media-picker", { props, emits, template })` in a new `admin_media.js`, loaded with the other admin scripts.

**When to use:** The seven upload sites need identical chrome (D-20). The codebase has no registered components today — only mixins — but a template-string component is legal because the host ships the full Vue build, and it is the only way to keep the drop-zone markup in exactly one place.

**Example:**
```js
// Source: pattern derived from host boot order (base.html:112-121) +
// Vue global-build component registration (vue.global.prod.js verified).
// admin_media.js — registered before mount, same as existing mixins.
window.app.component("gm-media-picker", {
  props: {
    usage: { type: String, default: "catalog" },   // media.MEDIA_USAGES
    multiple: { type: Boolean, default: false },
    disabled: { type: Boolean, default: false },
    blossomServers: { type: Array, default: function () { return []; } }
  },
  emits: ["files-chosen"],   // (files: File[], backend: "local"|"blossom")
  data: function () { return { backend: "local", drag: false }; },
  computed: {
    blossomHost: function () {
      try { return new URL(this.blossomServers[0] || "").hostname; }
      catch (e) { return ""; }
    }
  },
  methods: {
    pick: function () { this.$refs.input.click(); },
    onFiles: function (list) {
      var files = Array.prototype.slice.call(list || []);
      if (files.length) this.$emit("files-chosen", files, this.backend);
      this.$refs.input.value = "";
    }
  },
  template:
    '<div class="gm-drop" :class="{drag: drag}" role="button" tabindex="0"' +
    ' @click="pick" @keydown.enter.prevent="pick" @keydown.space.prevent="pick"' +
    ' @dragover.prevent="drag = true" @dragleave="drag = false"' +
    ' @drop.prevent="drag = false; onFiles($event.dataTransfer.files)">' +
    '  <input ref="input" type="file" hidden :multiple="multiple"' +
    '        accept="image/png,image/jpeg,image/webp"' +
    '        @change="onFiles($event.target.files)">' +
    '  <span>Drop images here or choose files — saved to ' +
    '    {{ backend === "blossom" ? "Blossom · " + blossomHost : "this LNbits" }}' +
    '    when you upload. Uploading is not saving; save the form to keep it.' +
    '  </span>' +
    '  <q-select v-if="blossomServers.length" v-model="backend" dense borderless' +
    '    :options="[{value:\'local\',label:\'Save to LNbits\'},' +
    '               {value:\'blossom\',label:\'Save to Blossom · \' + blossomHost}]"' +
    '    emit-value map-options @click.stop></q-select>' +
    '</div>'
});
```

### Pattern 2: XHR upload helper (shared mixin method)

**What:** One-file-per-request (D-03) `XMLHttpRequest` with `upload.onprogress`, CSRF header, FormData `usage`/`backend`/`file`.

**When to use:** Every upload — `fetch()` cannot report upload progress.

**Example:**
```js
// Source: admin_migration.js:100-133 precedent (FormData + X-CSRF-Token,
// no Content-Type — the browser sets the multipart boundary).
gmMediaUpload: function (file, usage, backend, onProgress) {
  var self = this;
  return new Promise(function (resolve, reject) {
    var fd = new FormData();
    fd.append("usage", usage);      // catalog|profile|appearance
    fd.append("backend", backend);  // local|blossom — ONE backend per file
    fd.append("file", file);
    var xhr = new XMLHttpRequest();
    xhr.open("POST", "/infinitemarkets/api/v1/media/upload");
    xhr.withCredentials = true;
    xhr.setRequestHeader("X-CSRF-Token", self.gmCsrf());
    xhr.upload.onprogress = function (e) {
      if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total);
    };
    xhr.onload = function () {
      var body = {};
      try { body = JSON.parse(xhr.responseText || "{}"); } catch (e) {}
      if (xhr.status >= 200 && xhr.status < 300) resolve(body);
      else reject(Object.assign(new Error(
        (body && (body.detail || body.title)) || "Upload failed"
      ), { status: xhr.status, problem: body }));
    };
    xhr.onerror = function () { reject(new Error("Upload failed")); };
    xhr.send(fd);
  });
}
```

### Pattern 3: Gallery list state → save body

**What:** `gmCatalog.editor.form.images` becomes an ordered array of `{url, kind}` entries (kind: `local`/`blossom`/`remote` for copy + thumbnail-src choice); save always serializes it.

**When to use:** Product save — replaces the textarea + the `if (images.length)` guard.

**Example:**
```js
// admin_catalog.js — replaces lines 461-466. ALWAYS send the list:
// omitted = preserve, [] = clear-all, populated = ordered replace (D-21).
body.images = (f.images || []).map(function (img) {
  return { url: img.url };   // sort_order defaults to list index server-side
});
```

### Anti-Patterns to Avoid

- **fetch() for uploads:** no `upload.onprogress` — per-file progress (MEDIA-12) is impossible. Use XHR.
- **QUploader as the control:** its queued-file chrome duplicates and conflicts with the unified gallery list; you'd suppress its UI and keep only its XHR — strictly worse than 10 lines of XHR.
- **Storing `result.path` in `profile_json`:** `_validate_profile` requires `https://` (merchant.py:352-362) and the client check does too (admin_settings.js:533-541) — profile fields MUST take `result.url`.
- **Storing `result.url` in Appearance fields when `public_base_url` is IP-literal:** `_https_url_ok` rejects IP-literal hosts (themes.py:161-175) — `result.path` always passes `_HERO_PATH`. Prefer `path` for local, `url` for Blossom.
- **Sending `images` only when non-empty:** recreates the clear-all bug — always send the array.
- **Reusing `images_text` as a second source of truth:** two editors on one field drift; the unified list is the single state (textarea is replaced; "Add image by URL" lives inside the control per D-16).
- **Icon-only mutators:** UI-SPEC requires a text label on every mutating control (admin.html:4-5 comment) — "Move up"/"Move down"/"Remove"/"Clear all" need text.
- **`outline` buttons inside the settings section:** `test_settings_buttons_are_solid` asserts no `outline` on any `<q-btn` line under `data-gm-surface="settings"` (test_admin_ui.py:197-204).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Multipart parsing, sniffing, hashing, quota, Blossom PUT | Any client-side duplicate | Phase 6 `POST /media/upload` | Already verified end-to-end (06-VERIFICATION: live GET 200 byte-exact) |
| Problem→copy mapping | Per-site error strings | `gmProblemCopy(e.problem)` + `ERROR_COPY` additions | Established RFC 9457 mapping; media codes carry plain-language `detail` already |
| Thumbnail rendering for remote URLs | Backend thumbnail proxy | Direct `<img src>` / `q-img` | Locked: no proxying (SSRF rule); remote host sees viewer IP — disclose |
| File drop handling | `useDropZone`/`v-drop-zone` | `@dragover.prevent`/`@drop.prevent` on the zone | **Verified absent** in bundled Quasar 2.22.0 (`grep -c useDropZone` → 0) — added post-2.22 |
| CSRF | Header juggling | `gm_csrf` cookie → `X-CSRF-Token` (admin_migration.js:4-7 precedent) | Double-submit contract enforced at `security.py:184-192`; cookie issued to admin viewers |
| Drag-reorder | Sortable lib | Up/down buttons (locked D-15) | Owner chose buttons; deferred drag reordering |
| Unused-files list/delete | New endpoints | `GET`/`DELETE /media/unused` + response extension | Adding a route costs spec§5+registry parity; extending the response is free |

## Common Pitfalls

### Pitfall 1: Profile fields reject relative paths — wrong result key
**What goes wrong:** Avatar/banner upload succeeds but identity save 422s `invalid-profile`, or the client-side guard fires "Use an https:// image address".
**Why it happens:** Both validators are https-only (admin_settings.js:533-541; merchant.py:352-362); `result.path` is `/library/...`.
**How to avoid:** Bind `result.url` for `usage=profile` (already absolute — the backend's `media-origin` gate guarantees a public base, and Blossom URLs are remote https).
**Warning signs:** 422 `invalid-profile` on Save identity after a successful upload.

### Pitfall 2: Blossom results have no `path`
**What goes wrong:** Appearance/catalog code that unconditionally reads `result.path` gets `undefined` for Blossom uploads.
**Why it happens:** Blossom results carry `{state, backend, server, sha256, bytes, url}` — no `path` key (media.py:268-275); local results carry `path`+`url` (media.py:124-131).
**How to avoid:** Choose the value key per `result.backend` (field matrix in Code Examples).
**Warning signs:** Empty/`undefined` image src after a Blossom upload.

### Pitfall 3: `GET /media/unused` lacks date + quota (D-18 gap)
**What goes wrong:** The Media block can't show "name, size, date" or quota usage — the response is only `{files:[{name,bytes,sha256}]}` (media.py:338-347).
**Why it happens:** D-02/D-12 listing was built for delete eligibility, not display metadata.
**How to avoid:** Extend `list_unused` to include file `mtime` and a `{used_bytes, quota_bytes}` summary (`_dir_bytes` + `migration_media.MAX_MERCHANT_BYTES` already exist) — response-shape change, no route/spec-parity cost beyond a prose line. Confirm scope with owner if treating backend edits as out of phase bounds.
**Warning signs:** Media card renders without date/quota — D-18 acceptance fails.

### Pitfall 4: Multipart form-field budget
**What goes wrong:** Adding extra text fields to the upload FormData 422s `invalid-content` / "invalid upload form".
**Why it happens:** `MultiPartParser(max_fields=4)` counts non-file fields (starlette formparsers.py:217-220); route allows only `usage`+`backend` semantically — a third text part raises "invalid file field" (views_api.py:955-960).
**How to avoid:** Send exactly `usage`, `backend`, and one `file` part per request.
**Warning signs:** 422 on uploads that carry extra fields (e.g., a CSRF or name field appended to the form).

### Pitfall 5: New scripts/markup break `test_admin_ui` string assertions
**What goes wrong:** Replacing `label="Avatar URL (https)"` or renaming JS identifiers fails the host-boot contract tests (test_admin_ui.py:132-156 asserts those exact labels + `profileAvatar`/`profileBanner` identifiers).
**Why it happens:** The suite greps served HTML/JS verbatim.
**How to avoid:** Keep the existing q-inputs for pasted-URL entry (MEDIA-11 already requires preserving them) and add the picker adjacent; update the module list/assertions in the same commit as new markup (`test_admin_shell_document` asserts each admin_*.js tag is present — presence-based, additions are safe).
**Warning signs:** Assertions on `images_text`, avatar/banner labels, or solid-button rules fail.

### Pitfall 6: Orphan blobs on cancel — disclosure, not deletion
**What goes wrong:** Merchant uploads, cancels the editor, and files sit unreferenced (counting toward the 400 MB local quota).
**Why it happens:** Upload and save are separate effects by design (D-01 — no auto-delete).
**How to avoid:** Cancel/close paths show the plain-language disclosure and point at Settings → Media; never auto-delete remote blobs (MEDIA-22 deferred).
**Warning signs:** UI that implies uploaded = saved.

## Code Examples

### Upload result → field value matrix (verified keys)

```text
// media.py:113-131 (local):   result = {file, state:"stored",
//   backend:"local", sha256, bytes, path:"/library/infinitemarkets/<ns>/<sha>.<ext>",
//   url:"<public_base_url>/library/infinitemarkets/<ns>/<sha>.<ext>"}
// media.py:268-275 (blossom): result = {file, state:"stored",
//   backend:"blossom", server, sha256, bytes, url:"https://<server>/..."}
// Rejected: {file, state:"rejected", reason:"size"|"not-an-image"|"write-verify-failed"}
// Response envelope local:   {uploaded, results[], namespace, backend:"local"}
// Response envelope blossom: {uploaded, results[], backend:"blossom", server}

usage=profile    (avatar, banner)         -> result.url   // https required
usage=appearance (brand/footer logo,      -> result.path if backend==="local"
                  hero bg, share custom)      else result.url
usage=catalog    (product gallery)        -> result.url   // D-07 absolute form;
                                          //  path also passes _valid_image_url
```

### Problem codes the editors must map (verified)

```text
// views_api.py media routes + media.py — all problem+json via problem_boundary:
invalid-content   422  bad multipart/usage/backend/file-type/oversize/quota shape
media-origin      422  usage=profile + non-public public_base_url (D-22 gate)
media-backend     422  backend=blossom + no configured server
media-remote      (blossom PUT failure — detail names server, suggests local retry)
media-quota       409  400 MB local quota exceeded
media-referenced  409  DELETE /media/unused/{name} on a still-referenced file
// gmProblemCopy strips urn:infinitemarkets: → ERROR_COPY else detail/title;
// each of these already carries plain-language detail — add ERROR_COPY
// entries only where friendlier copy is wanted.
```

### Gallery unified-list entry shape (recommended)

```js
// One entry per image, whatever the origin — drives thumbnail + ordering:
{ url: "<stored-or-pasted url>",        // authoritative save value
  thumb: "<img src>",                   // path|url|pasted url — never proxied
  kind: "local" | "blossom" | "remote", // disclosure + badge copy
  pending: false, progress: 0, error: null }  // upload state (MEDIA-12)
// Primary = index 0 — badge only, no extra field (D-15 + discretion).
```

### Single-image field wiring (replace/clear without clobbering siblings)

```js
// Profile (admin_settings.js) — merge onto profileJson copy, delete empty keys
// (existing pattern at :557-565 — keep it; only the value SOURCE changes):
fields.picture = uploadedUrl;   // "" clears via delete profile[key]
// Theme (gmSaveTheme :1062-1083) — theme object rebuilt whole; setting one
// field just mutates gmSettings.theme.brand.logo_url etc. before save.
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `images_text` newline textarea | Unified thumbnail list + in-control URL add | This phase | D-14…D-16; textarea retired for gallery |
| `if (images.length) body.images` | Always send `body.images` | This phase | Clear-all becomes possible (D-21) |
| `/images/` emitted URLs | `/library/` emission + `/images/` legacy read | Phase 6 m019 | Labels must say `/library/` (D-19) |
| Blossom list sorted | First-seen order preserved | Phase 6 set_blossom_servers | `blossom_servers[0]` IS the primary (MEDIA-02) |

**Deprecated/outdated:**
- `useDropZone`/`v-drop-zone`/`createUploaderComponent`: NOT in Quasar 2.22.0 [VERIFIED: grep of vendored quasar.umd.js returns 0 matches] — hand-rolled drop handlers are the only option.

## Project Constraints (from AGENTS.md)

- `make verify-fast` (~50 s, qualification+fast runtime) required before push; `uv run ruff check .`; `node --check` every edited `.js`.
- Spec §5 ↔ `harness/registry.py::HTTP_ROUTES` bidirectional parity — only touched if a route is added (none expected; extending `list_unused` response avoids it).
- `_public_merchant` projections must never leak `*_enc`/`*_hash`; public theme tokens never style admin chrome; arbitrary CSS/scripts/remote URLs prohibited in public surfaces.
- Admin surfaces: host palette only, no merchant theme tokens (admin.html header comment).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Response-shape extension of `GET /media/unused` (mtime + quota fields) is acceptable in-scope vs. "no storage-layer changes beyond what the editors require" | Pitfall 3, Open Questions | If owner rules backend edits out, D-18's date+quota columns can't render — acceptance gap |
| A2 | First registered component (`window.app.component`) is acceptable despite zero precedent — codebase idiom is mixins-only | Pattern 1 | If reviewers prefer mixin+partial markup, plan reverts to a canonical markup block duplicated 7× — still works, drifts easier |
| A3 | Product gallery stores `result.url` (absolute) for local uploads per D-07's stored-representation lock | Code Examples | If `path` were preferred, NIP-99 would still emit it verbatim — relative URLs on relays are worse, so `url` is the safer default either way |
| A4 | Idempotency-Key on upload requests is optional (shape-validated only, never uniqueness-checked for uploads) | Pattern 2 | Including it is harmless; omitting matches the migration-upload precedent — either satisfies `enforce_mutation_security` |

## Open Questions — RESOLVED at planning (2026-10-16)

1. **`GET /media/unused` response lacks `date` and quota fields for D-18** →
   **RESOLVED by D-23 / plan 07-01**: `list_unused` gains per-file `mtime`
   and top-level `used_bytes`/`quota_bytes` (existing `_dir_bytes` +
   `MAX_MERCHANT_BYTES`); response-shape extension, no new route, spec §5.6
   prose updated in the same commit.
   - What we know: response is `{files:[{name,bytes,sha256}]}` only (media.py:338-347); `_dir_bytes` + `MAX_MERCHANT_BYTES` exist for a quota summary; `f.stat().st_mtime` is available for date.
   - Recommendation adopted: extend the response in the same plan — smallest change satisfying D-18 verbatim; no route parity work needed.

2. **Where the Media block lands in Settings** → **RESOLVED by Claude's
   discretion / plan 07-04 Task 2**: a "Media" `q-card` inside the Merchant
   `q-tab-panel`, placed after the relay/Blossom configuration card — the
   surface merchants already associate with media servers; follows the
   existing card layout.
   - What we know: Settings tabs are Merchant / Notifications / Appearance / Embed (admin.html:1914-1918); the Merchant tab already hosts Blossom server config and is a `q-card` list.

3. **Avatar/banner q-inputs: replace or augment** → **RESOLVED by D-29 /
   plan 07-04 Task 1**: keep the URL q-inputs verbatim (pasted-URL entry
   preserved per MEDIA-11 + `test_admin_ui.py:138-139` label stability);
   the picker + thumbnail + Remove-image control render adjacent. Same
   pattern for the four appearance fields.
   - What we know: `test_admin_ui.py:138-139` asserts the exact `Avatar URL (https)`/`Header image URL (https)` labels; MEDIA-11 requires keeping URL entry.

## Environment Availability

Step 2.6: SKIPPED (no external dependencies — code-only phase; verification uses repo-pinned `uv`/`pytest`/`node` which the developer environment already provides per AGENTS.md).

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (host-boot runtime + qualification tiers) |
| Config file | `pyproject.toml` — markers `fast`, `runtime`, `sdk`, `db`, `protocol`, `host` |
| Quick run command | `make verify-fast` (`uv run pytest -m fast -q`) + `node --check <edited .js>` + `uv run ruff check .` |
| Full suite command | `make verify` (`uv run pytest -q` — host-boot ~6 min) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|--------------|
| MEDIA-02 | backend=blossom hits first server only | runtime (exists) | `uv run pytest tests/runtime/test_blossom_upload.py -q` | ✅ (backend covered Phase 6; UI selector = markup asserts in test_admin_ui) |
| MEDIA-03 | Blossom failure → plain error + local retry copy | runtime | `uv run pytest tests/runtime/test_blossom_upload.py -q` | ✅ backend; UI copy → test_admin_ui string asserts (edit) |
| MEDIA-08 | shared control at all 7 sites | runtime markup | `uv run pytest tests/runtime/test_admin_ui.py -q` | ❌ add asserts for `gm-media-picker`/`admin_media.js` script tag |
| MEDIA-09 | gallery order/remove/clear persists | runtime API | `uv run pytest tests/runtime/test_catalog_api.py -q` | ❌ add `images: []` clear-all + reorder regression |
| MEDIA-10 | single-field replace/clear preserves siblings | runtime API | `uv run pytest tests/runtime/test_merchant_api.py -q` | partial — add profile_json merge regression if absent |
| MEDIA-11 | pasted + `/images/`+`/library/` round-trip | runtime (exists) | `uv run pytest tests/runtime/test_catalog_api.py -q` | ✅ dual-prefix covered 06-04; add admin-side assert |
| MEDIA-12 | per-file progress/errors; siblings survive | manual + markup | `node --check` + test_admin_ui asserts; progress is browser-only (manual verify) | partial |
| MEDIA-13 | persistence → public + Nostr projections | runtime (exists) | `uv run pytest tests/runtime/test_catalog_events.py test_public_pages.py -q` | ✅ projection paths unchanged — regression-run |
| MEDIA-14 | 20-cap consistent | runtime (exists) | `uv run pytest tests/runtime/test_catalog_api.py -q` | ✅ (`test_product_image_incremental_limit`) + new UI copy assert |

### Sampling Rate
- **Per task commit:** `make verify-fast` + `node --check` edited JS + `uv run ruff check .`
- **Per wave merge:** targeted `uv run pytest tests/runtime/test_admin_ui.py test_catalog_api.py test_media_upload.py -q`
- **Phase gate:** full `make verify` green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/runtime/test_catalog_api.py` — `PATCH /products/{id}` with `"images": []` clear-all + reorder round-trip regression (MEDIA-09/13)
- [ ] `tests/runtime/test_admin_ui.py` — assertions for `admin_media.js` script tag, `gm-media-picker` usage at the 7 sites, `/library/` label copy (D-19), Media settings block
- [ ] `tests/runtime/test_media_upload.py` — update if `list_unused` response extended (Pitfall 3)

## Security Domain

### Applicable ASVS Categories (level 1)

| ASVS Category | Applies | Standard Control |
|---------------|---------|------------------|
| V2 Authentication | yes | Existing `check_user_exists` + `cookie_access_token`; no new auth surface |
| V3 Session Management | no | — |
| V4 Access Control | yes | All media routes merchant-scoped via `_merchant_owned` (already enforced server-side) |
| V5 Input Validation | yes | Server-side: magic-byte sniff, size/quota, `usage`/`backend` allowlists, `_valid_image_url`, `_validate_profile`, `_validate_media_url`; client-side: `accept=` hint + size precheck only (never trusted) |
| V6 Cryptography | no | Signing stays server-side (`MerchantKeyStore`) — nsec never reaches the browser |
| V13 API / file upload | yes | CSRF double-submit (`X-CSRF-Token`), Origin check, bounded multipart, content-addressed names — all Phase 6 backend controls; UI must not bypass them |

### Known Threat Patterns for {Jinja + Vue-UMD admin}

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| XSS via pasted image URL / filename | Tampering/Info Disclosure | Vue `{{ }}` auto-escapes; never `v-html` user URLs; `q-img`/`img :src` binding is attribute-safe; `_valid_image_url` blocks `javascript:`/`data:` |
| SSRF via thumbnail proxy | Info Disclosure | None exists — thumbnails load the remote URL directly (locked); never add a backend thumbnail fetch |
| CSRF on upload | Tampering | `X-CSRF-Token` echo of `gm_csrf` cookie + canonical Origin — enforced at `security.py:174-192` |
| Credential leak to remote host | Info Disclosure | Blossom PUT happens server-side; browser only sees the returned `url` — no `Authorization`/nsec in JS (backend already guarantees) |
| Stored-path traversal in delete | Tampering | `DELETE /media/unused/{name}` fullmatch `[0-9a-f]{64}\.(png|jpg|webp)` — pass the server-provided `name` verbatim, never client-composed paths |

## Sources

### Primary (HIGH confidence — read in-repo this session)
- `infinitemarkets/templates/infinitemarkets/admin.html:619, 1208, 1278, 1938-1943, 2426-2429, 2468-2471, 2517-2520, 2539-2543, 3353-3362` — all seven image-field sites, file-input precedent, script manifest
- `infinitemarkets/static/infinitemarkets/js/admin_app.js:94-130` — `gmApi`/`gmProblemCopy` contract (JSON-only, CSRF+Idempotency-Key on mutations)
- `infinitemarkets/static/infinitemarkets/js/admin_migration.js:95-133` — FormData+XHR-adjacent upload precedent
- `infinitemarkets/static/infinitemarkets/js/admin_catalog.js:408-479` — `images_text` serialization + the `if (images.length)` clear-all bug
- `infinitemarkets/static/infinitemarkets/js/admin_settings.js:443-583, 1038-1091` — settings load, `profileJson` merge pattern, https-only client guard, whole-object theme save, `blossom_servers` source
- `infinitemarkets/views_api.py:902-994` — media route contract incl. `MultiPartParser(max_fields=4)`
- `infinitemarkets/services/media.py` (whole file) — usages/backends vocab, result shapes, profile-origin gate, unused list/delete
- `infinitemarkets/services/catalog.py:43, 61-71, 702-715, 782-800, 1131-1132` — `IMAGES_MAX=20`, `_valid_image_url` verbatim, omitted/empty/replace semantics, sort_order
- `infinitemarkets/services/merchant.py:342-362, 389-492` — profile https-only validation, PATCH allowed-fields, profile/theme write path
- `infinitemarkets/services/themes.py:155-202, 205-222, 315-346, 381-396` — appearance URL validation (same-origin `/path` or non-IP https)
- `infinitemarkets/services/relay.py:163-229` — Blossom URL validation + order-preserving setter
- `infinitemarkets/services/events.py:101-104, 291-305` — NIP-99 image tags verbatim; kind-0 normalize+absolutize
- `infinitemarkets/security.py:150-219` — mutation security: Origin + CSRF + Idempotency-Key shape
- `.cache/lnbits/` — pinned host `e336fe1`: `package.json` (quasar 2.22.0, vue 3.5.34), `static/vendor.json` (`vue.global.prod.js`, `quasar.umd.prod.js`), `templates/base.html:99-121` (createApp→extension scripts→mount), `static/js/init-app.js:244-249`, `quasar.umd.js` (QUploader present :33573, `useDropZone` absent, XHR progress :33485)
- `tests/runtime/test_admin_ui.py` (whole file) — verbatim markup/JS assertions that constrain edits
- `docs/technical-specification.md:805-842, 1867` — §5.6 route prose, §15 cap = 20

### Secondary (MEDIUM confidence)
- [CITED: https://quasar.dev/vue-components/uploader] — QUploader `factory`/`headers`/`form-fields`/`with-credentials`/`send-raw` props (evaluated, not recommended)

### Tertiary (LOW confidence)
- none

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — versions verified in the pinned host's own files
- Architecture: HIGH — every contract surface (route fields, response keys, validators, save paths) read at source this session
- Pitfalls: HIGH — each pitfall cites verified code; only the D-18 response gap is flagged for planner/owner resolution

**Research date:** 2026-10-16
**Valid until:** 2026-11-15 (stable — pinned host, no external deps)
