---
phase: 02-release-a-safe-web-commerce
plan: 04
subsystem: ui
tags: [vue3, quasar, jinja-raw, checkout, order-status, admin-shell, themes]

requires:
  - phase: 02-03
    provides: §5.3 admin order/notification/outbox APIs, §5.4 public
      checkout/status/opt-out APIs, theme backend, relay-health
  - phase: 02-02
    provides: public storefront documents, theme token emission,
      relay-health/outbox routes

provides:
  - >-
    Admin shell (one nav: Orders/Catalog/Publications/Settings) mounted
    on the host Vue 3 app via mixins inside `{% block page %}`
  - B1 Linear Split order workspace (390px list + detail, legal-action
    map, exception banner, order_events timeline, collapsed technical
    details)
  - B2 publication health (per-relay delivery evidence + outbox pills +
    retry) and B3 catalog management (products/collections/shipping
    editors, draft badges, dry-run event viewer, soft-delete dialogs)
  - B4 merchant settings (identity, masked nsec import, wallet selector
    blocked on open orders, relay + Blossom editors, publish/deactivate)
    and B5 notifications (≤5 addresses, per-event toggles, test send,
    queue view) and B6 appearance (Tiered Controls + live contrast +
    public-only preview)
  - A2 embedded adaptive checkout card (Editorial/Guided/Compact,
    ≤560px compact override, persistent summary, idempotent submit) and
    A3 order-status page (fragment token → replaceState → X-Order-Token,
    5s polling, invalid-token identical copy)

affects: [release-a-verify, 03-release-b]

actuals:
  tokens: 102000
  tasks: 3
  commits: 1

tech-stack:
  added: []
  patterns:
    - "Vue mixins via window.app.mixin() — extension modules register in
      `{% block scripts %}` (after Vue.createApp, before mount)"
    - "Jinja `{% raw %}` wraps Vue `{{ }}` markup in the page block"
    - "Run-once guards on mixin mounted hooks (they fire per component)"

key-files:
  created:
    - infinitemarkets/templates/infinitemarkets/admin.html
    - infinitemarkets/static/infinitemarkets/js/admin_app.js
    - infinitemarkets/static/infinitemarkets/js/admin_orders.js
    - infinitemarkets/static/infinitemarkets/js/admin_catalog.js
    - infinitemarkets/static/infinitemarkets/js/admin_publications.js
    - infinitemarkets/static/infinitemarkets/js/admin_settings.js
    - infinitemarkets/static/infinitemarkets/js/admin_notifications.js
    - infinitemarkets/static/infinitemarkets/js/public_checkout.js
    - infinitemarkets/static/infinitemarkets/js/public_order.js
    - tests/runtime/test_buyer_ui.py
    - tests/runtime/test_admin_ui.py
    - tests/runtime/test_release_a_journey.py
  modified:
    - infinitemarkets/views.py (index → admin.html; index.html removed)
    - infinitemarkets/views_public_api.py (payment_exception on status)
    - "infinitemarkets/services/orders.py (list rows: buyer/item summary + q)"
    - infinitemarkets/services/merchant.py (spec_revision on projection)
    - infinitemarkets/services/relay.py (blossom_servers on relay-health)
    - infinitemarkets/templates/infinitemarkets/public_product.html (A2 card)
    - infinitemarkets/templates/infinitemarkets/public_order.html (A3 shell)
    - infinitemarkets/static/infinitemarkets/css/gm-public.css (checkout/order
      styles, stepper, pills, focus/reduced-motion)
    - infinitemarkets/static/infinitemarkets/js/public_storefront.js (shared
      GM helpers only — checkout/status logic moved to page modules)

key-decisions:
  - "Admin JS runs as window.app mixins in `{% block scripts %}` — the
    host mounts AFTER extension scripts, so mixins land pre-mount"
  - "Public checkout/status split into page modules on a shared
    window.GM helper layer (vanilla JS, CSP script-src 'self')"
  - "Vue `{{ }}` markup lives inside `{% raw %}` in admin.html — Jinja
    would otherwise consume Vue interpolation"
  - "payment_exception added to the §5.4 status allowlist (buyer-safe
    boolean only — never the exception reason)"
  - "Verbatim contract copy kept as single-line JS constants so tests
    grep the literal strings"

requirements-completed:
  - PUB-02
  - ORD-01
  - NOTF-01
  - UI-01
  - UI-02
  - UI-03
  - WEB-01
  - WEB-02
---

# 02-04 Summary — buyer surfaces + merchant admin shell

## Tasks completed

1. **Admin shell + surfaces** — `admin.html` mounts inside the host
   shell; `admin_app.js` provides shared state/API/CSRF/navigation plus
   first-run merchant setup, topology + audit-warning banners. B1 order
   workspace (`admin_orders.js`), B2 publication health
   (`admin_publications.js`), B3 catalog (`admin_catalog.js`), B4
   merchant settings + B5 notifications + B6 appearance
   (`admin_settings.js`, `admin_notifications.js`).
2. **Buyer surfaces** — A2 adaptive checkout card embedded in
   `public_product.html` (`public_checkout.js`), A3 order-status page
   (`public_order.js`), shared token/format helpers in
   `public_storefront.js`, and the full checkout/order CSS set.
3. **Runtime UI tests + Release-A journey** — `test_buyer_ui.py` (5),
   `test_admin_ui.py` (8), `test_release_a_journey.py` (1 journey).

## Implementation notes

- **Host integration** — `window.app = Vue.createApp` precedes
  `{% block scripts %}`; `init-app.js` (in INCLUDED_COMPONENTS) mounts
  after, so extension mixins register before mount. Each module guards
  its `mounted`/`$watch` with a run-once flag — mixin hooks fire for
  every component instance.
- **B1 legal-action map** mirrors §7.1/§7.2: confirmed → Start
  processing / Cancel with reason; processing → Start fulfillment /
  Mark shipped / Mark delivered / Mark complete / Cancel;
  pre-payment states → Cancel; payment_exception → Accept / Request
  refund / Confirm refund sent; terminal → disabled "No legal action"
  with reason. Reissue revokes the old token and shows the new link once.
- **B6 theme editor** mirrors `services/themes.py` exactly — preset
  palettes, Brand Basics bounds, allowlisted advanced tokens behind the
  opt-in, client-side WCAG ≥4.5:1 meters that block save before the
  server gate runs. `validate_theme` replaces the whole object, so the
  save always sends `brand` and only sends `advanced` while opted in.
- **Token contract** — the order token arrives as a URL fragment only,
  is stripped via `history.replaceState`, lives in memory, and travels
  as `X-Order-Token`. Status links re-attach it as a fragment only when
  the user explicitly copies the link.
- **Invoice states** — creating skeleton → awaiting_payment (QR + full
  BOLT11 + countdown + verbatim security copy) → confirmed/processing/
  completed → expired/cancelled; `creation_unknown`/`payment_exception`
  render the on-hold hold state with NO second-invoice affordance.

## Fixes found by tests

- `relay_health` lacked `blossom_servers` — added so B2/B4 share one
  response shape.
- `list_orders` lacked buyer/item summary fields — extended (decrypted
  buyer handle post-filter for the `q` search arm).
- `outbox_events` has no `relay_targets` column — `gmMissingRelays`
  derives partial-publication gaps from configured enabled public relays
  minus accepted `relay_publications`.
- `payment_exception` added to `GET /public/order-status` (plan
  allowlist) — the strict field-set test now names it explicitly.
- `index.html` removed — `admin.html` is the admin surface.
- 02-02 test updated: the A2 CTA is "Review payment" (UI-SPEC), not the
  placeholder "Buy with Lightning".

## Spec deltas (recorded per plan)

- **`payment_exception` on §5.4 order-status** — buyer-safe boolean for
  the "On hold — the merchant is reviewing a payment issue." label.
- **B4 relay/blossom editing** uses `PATCH /merchants/{id}` with
  `relay_configs`/`blossom_servers` — the config fields land in the
  merchant document, not a separate route (W-NEW-1 precedent).

## Verification

```
uv run ruff check .                    → all checks passed
node --check on all 9 JS modules       → clean
uv run pytest tests/runtime -q         → 171 passed
GAMMA_QUAL_EVIDENCE=1 uv run pytest -q → 391 passed, 1 skipped
```

Runtime coverage: `test_buyer_ui` (checkout card contract, physical vs
digital field sets, order-page shell, JS contracts — ≤560px override,
idempotency key, creation_unknown guard, verbatim copy, scoped theme
emission), `test_admin_ui` (shell mount, verbatim copy, workspace grid
CSS, no-secrets boundaries, legal-action map, B2/B5/B6 module checks),
`test_release_a_journey` (full merchant+buyer pass: catalog → page →
checkout → replay → status → settle → admin action → publications →
notifications → appearance → themed page).

## Browser E2E (Playwright)

Harness: `tools/e2e_server.py` boots the pinned host over local HTTPS
(`https://localhost:5099`, per-run self-signed cert — the §5.1 Origin
invariant requires an https:// canonical origin), FakeWallet, relay IO
off, real extension install discovery. Seeds account/wallet/merchant/
catalog/products/order via the real HTTP APIs plus `ensure_default_relays`
(the publish-path starter set). Harness-only routes: `/_e2e/seed`,
`/_e2e/settle` (FakeWallet pay + the listener's settlement calls). Not
shipped.

```
cd tests/e2e && npm install && npx playwright test
→ 12 passed (Chromium): 6 buyer + 6 admin specs
```

Bugs found by the browser run and fixed in shipped code:

- `views.py` — admin context must pass `user.json()` (string); the host
  renders it into `JSON.parse({{ user | tojson }})` and a dict produced
  `"[object Object]" is not valid JSON`.
- Admin mixins — global-mixin `mounted`/`$watch` hooks must target the
  component that owns `#vue` (`vueEl._vnode.component.proxy`), not
  `this`: hooks fire for every component, and standalone Vue roots on
  the page also satisfy `$root === this`. The bug loaded merchant state
  on a stray uid-0 component, leaving the rendered root on skeletons.
- `admin.html` — `q-markup-table` with `thead`/`tr` cannot survive
  in-DOM template compilation (HTML parser foster-parents table
  children out of unknown elements); relay health now uses `q-table`.

Not verified at the time of this plan's original execution: PostgreSQL `SKIP LOCKED` variants (CI); real relay publish/ACK round-trips (RELAY_IO=off in the initial E2E harness).

## Post-plan Phase 2 closeout review (2026-09-27)

This section supersedes the earlier test totals and initial-execution caveat; it does not retroactively mark Phase 2 released. The browser harness now uses an owned local relay with a real positive ACK and supports both SQLite and a separate UTC-configured PostgreSQL database. The extension was tightened for PostgreSQL transaction locking/timezones, catalog privacy, shipping unit/currency precision, stale-worker fencing, quote/invoice agreement, advanced theme contrast, gallery accessibility (all 16 permitted images), buyer retry safety and pre-delivery signed-invoice/wallet correlation. Invoice uncertainty never creates a second invoice, and relay delivery remains separate from payment truth.

- Canonical SQLite qualification: **447 passed, 3 skipped**.
- Canonical PostgreSQL qualification: **448 passed, 2 skipped**, 1 warning from the deliberate host auto-commit probe.
- Chromium admin/buyer browser journey: **13 passed** on SQLite and **13 passed** on PostgreSQL, with LocalRelay publication ACKs; the PostgreSQL browser run preceded the last gallery-only change, which passed separately on PostgreSQL.
- Ruff and changed JS syntax checks: passed. The pinned LNbits checkout remained clean and unchanged.

The 25 planned threat mitigations have local implementation/test evidence in `02-SECURITY.md`. Post-plan [CI run 36303338957](https://github.com/bitkarrot/infinitemarkets/actions/runs/36303338957) passed the four required Linux profiles; a fresh user-requested demo on port 5099 now serves the quote route. The prior disposable database was left on disk but not mounted in the new demo. Phase 2 completion is still **blocked** by human buyer/merchant UAT and security/accessibility review. `02-VERIFICATION.md` records exact profiles, source fingerprint, skips and remaining gates; `02-UAT.md` tracks unanswered human checks. No Phase 3 work was started.
