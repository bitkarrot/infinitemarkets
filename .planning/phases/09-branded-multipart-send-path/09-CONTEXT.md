# Phase 9: Branded Multipart Send Path - Context

**Gathered:** 2026-10-17
**Status:** Ready for planning
**Source:** PRD Express Path (.planning/specs/order-email-templates-SPEC.md)

<domain>
## Phase Boundary

Every `email_queue` send — order-event emails on the `customer` and
`merchant` channels, plus `account` (magic-link) and test sends — leaves the
host's plain-text-only `send_email` for an extension-owned SMTP boundary in
`infinitemarkets/services/email.py`: `_build_message` (pure MIME
construction) and `_smtp_send` (thin stdlib transport). Messages become
`multipart/alternative`: the existing `_render_body` text render is retained,
and a new branded `text/html` part comes from `_render_html`. This phase also
corrects consent gating (`notify_events` gates the merchant channel only),
adds channel-appropriate mandatory footers to both parts, adds the EMAIL-11
header set, and makes test sends render the branded shell with sample content
regardless of `notify_events`.

This phase delivers the send path and the template only. It does NOT deliver:
- Phase 10 (EMAIL-04..07): `merchants.email_*` columns + migration `m020`,
  logo upload/delete route, local-only media picker, header/footer/accent
  settings UI + PATCH fields, `_referenced_names` unused-scan protection,
  `preview_enc` `html` key + sandboxed owner preview.
- Phase 11 (EMAIL-12/13): technical-spec §4/§5/§8.8/§15 contract rewrite,
  `harness/email.py` multipart model, qualification-suite expansion.
- v2 (EMAIL-14/15): `List-Unsubscribe` header / RFC 8058 one-click;
  per-channel `customer_events` toggles.

Requirements: EMAIL-01, EMAIL-02, EMAIL-03, EMAIL-08, EMAIL-09, EMAIL-10,
EMAIL-11.

</domain>

<decisions>
## Implementation Decisions

### Source precedence
- **D-01 [informational]:** The SPEC is the design input. Where it disagrees
  with the later, owner-approved `.planning/REQUIREMENTS.md` and ROADMAP
  Phase 9 success criteria (both 2026-10-17), REQUIREMENTS/ROADMAP win. Known
  resolved conflicts: the `List-Unsubscribe` header is deferred (D-21);
  `notify_events` is decoupled from customer emails rather than documented
  as-is (D-17); branding storage/UI and preview HTML move to Phase 10 (see
  Deferred Ideas).

### SMTP boundary (EMAIL-01)
- **D-02:** The host `lnbits/core/services/notifications.py::send_email` is
  not modified (pinned host e336fe1) and is no longer called for
  `email_queue` sends. The extension owns the send in
  `infinitemarkets/services/email.py` as two functions:
  `_build_message(...) -> email.message.EmailMessage` (pure: MIME tree,
  headers, optional CID assembly, HTML render — no network, unit-testable)
  and `_smtp_send(msg)` (thin transport).
- **D-03:** `_smtp_send` reuses the host SMTP configuration
  (`lnbits_email_notifications_*` settings exactly as the host helper reads
  them) and mirrors the host helper's connection mechanics (TLS/login/
  `sendmail`) inside `asyncio.to_thread`, under the existing
  `asyncio.wait_for(min(30, remaining))` deadline discipline in
  `worker_tick._send`. Stdlib `smtplib`/`email` only — no new dependencies.
- **D-04:** Queue semantics are unchanged. Only a confirmed successful
  `_smtp_send` enters `sent`; an exception or timeout returns the row to
  `pending` with the existing bounded, unclassified backoff. Sent rows still
  wipe `recipient_enc`/`payload_enc`. SMTP stays outside every DB transaction
  (no claim held across network I/O). Rate-limit buckets and the dedupe key
  `UNIQUE(order_id, channel, event_type, recipient_hash)` are unchanged.

### MIME structure (EMAIL-01)
- **D-05:** Every `email_queue` send is `multipart/alternative`. The
  `text/plain` part comes first: the existing `_render_body` output, retained
  apart from the D-26 label fix, plus the mandatory footer lines of D-14. The
  HTML alternative comes last.
  Both parts are `utf-8`. When a logo is supplied, the HTML alternative is a
  `multipart/related` holding `text/html` + `image/png|jpeg` with
  `Content-ID: <logo@infinitemarkets>`. With no logo, it collapses to a bare
  `text/html` part.
- **D-06:** Phase 9 has no logo data source: the `email_logo_path` column and
  the upload route are Phase 10. `_build_message`/`_render_html` accept an
  optional logo (bytes + image subtype) so the CID path exists now and is
  unit-tested with synthetic bytes. In Phase 9, production sends pass no logo
  and render the display-name wordmark. A missing or unusable logo never
  fails a send — it renders without the `related` wrapper. Logo bytes are
  never persisted on the queue row.

### HTML template (EMAIL-02, EMAIL-03)
- **D-07:** Markup is email-client-safe: a table-based single-column layout,
  600px max width. Inline CSS only — no `<style>` blocks, no layout classes,
  no webfonts. System font stack
  `-apple-system, "Segoe UI", Roboto, Helvetica, Arial`. Single light theme
  (no dark-mode media queries). A hidden preheader span is the first body
  element (e.g. "Order confirmed — {display_name}"). No remote resources of
  any kind: no remote `<img>`, no tracking pixels, no external CSS or fonts.
- **D-08:** Sections, in order:
  (1) Header band — `<img src="cid:logo@infinitemarkets" height="40">` with
  `alt` = escaped display name when a logo is supplied, otherwise a
  display-name wordmark; the accent color is the band background or a 3px top
  rule.
  (2) Event title + state label.
  (3) Item table — title × quantity with real line totals from `order_items`
  (`unit_price_minor`/`line_total_sat`/`currency_decimals`), plus a
  "backordered" badge when `backordered_qty > 0`; then an order-totals block
  (subtotal / shipping / total sats per EMAIL-02; research confirms the
  source columns).
  (4) Digital-delivery block (D-11).
  (5) Status-link CTA button (D-12).
  (6) Channel footer (D-14).
- **D-09:** In Phase 9 the accent color is the merchant's theme accent; the
  `email_accent` override arrives in Phase 10. Every color interpolated into
  inline CSS must match `^#[0-9a-fA-F]{6}$` at render time; anything else
  falls back to a fixed default. Rationale: `html.escape` alone does not stop
  CSS-context injection. (Derived from SPEC §4.3 accent validation + §4.2
  escaping contract.)
- **D-10:** Hard escaping contract: every interpolated value in the HTML part
  passes `html.escape`, with `quote=True` in attribute contexts such as the
  CTA `href` and logo `alt`. This covers display name, item titles,
  quantities, totals, labels, digital-delivery content, and (from Phase 10)
  custom header/footer text. Digital-delivery content renders inside a
  `white-space: pre-wrap` block after escaping (free text, not markup).
  Merchant text is never autolinked. An item title stored as `<script>`
  renders as `&lt;script&gt;` in the HTML part and as inert literal
  characters in the text part.
- **D-11:** Digital-delivery content appears only in the customer-channel
  `confirmed` email, in both parts — the same gate as the existing text
  render.
- **D-12:** The status-link CTA renders only while the token copy is live,
  reusing `_status_link`'s expiry/AEAD checks (no new token logic). The link
  stays the fragment URL `{public_base_url}/infinitemarkets/order#token`;
  bearer tokens never move into the URL path or query (§5.4 posture).
- **D-13:** Subjects keep their content rule: merchant display name + event
  label only (`_subject`), with no buyer PII, addresses, or internal ids; the
  display name is control-character-sanitized as in D-19. The same rule
  applies to every new header. Neither part ever carries decrypted
  addresses, keys, BOLT11, or preimages. Logs never carry recipients,
  rendered bodies, tokens, or SMTP credentials.

### Channel footers (EMAIL-09)
- **D-14:** Each channel gets a fixed, mandatory transactional footer in BOTH
  parts:
  `customer` — a "you opted in to order emails" notice plus an opt-out line
  linking to the order page. That page is the existing status link and
  already exposes the opt-out button (`public_order.js` →
  `POST /order-email-opt-out`), so no new public page is needed.
  `account` — "you requested a sign-in link".
  `merchant` and test — a neutral "transactional notification" line.
  The mandatory line is fixed copy. Merchant custom footer text (Phase 10)
  supplements it and never replaces it.

### Account and test channels (EMAIL-09, EMAIL-10)
- **D-15:** Account (magic-link) emails use the same shell (header band,
  accent, wordmark) with no order sections and the sign-in footer. The
  sign-in link stays a fragment URL and is escaped with `quote=True` in the
  HTML `href`.
- **D-16:** Test sends (`send_test_notification` → `enqueue_test_send` →
  worker) render the full branded shell with representative,
  clearly marked sample content (sample items and totals, no real order data)
  and are never suppressed by `notify_events` flags. The global gates still
  apply: extension `email_enabled`, host SMTP configured, merchant inactive,
  and the existing ≤5/hour test-send bucket.

### Consent gating (EMAIL-08)
- **D-17:** The `event-disabled` (`notify_events`) check in
  `_suppression_reason` applies only to `channel == 'merchant'` rows (test
  rows excepted per D-16). Customer-channel rows gate solely on the order's
  `email_opt_in`, re-checked at send time (`consent-revoked`). Account rows
  keep skipping consent. The global gates `email-disabled`,
  `host-email-unconfigured`, and `merchant-inactive` are unchanged for every
  channel. This resolves SPEC open question 4 per EMAIL-08, not per the
  SPEC's "document as-is" recommendation; per-channel `customer_events`
  toggles are EMAIL-15 (v2).

### Headers (EMAIL-11)
- **D-18:** Every message carries `Date` (`email.utils.formatdate`),
  `Message-ID` (`email.utils.make_msgid`), and
  `Auto-Submitted: auto-generated`.
- **D-19:** `From: "{display_name}" <host notifications address>`. The
  merchant-controlled display name has CR/LF and other control characters
  stripped and is encoded via `email.headerregistry.Address` /
  `email.utils.formataddr`. An empty or invalid name falls back to the bare
  host address. The sending address itself stays the host notifications
  address.
- **D-20:** No `Reply-To` header in Phase 9. The SPEC marks it optional, and
  EMAIL-11's owner-approved header set omits it (it would expose the
  merchant's notify address to buyers). Adding it is an owner decision.
- **D-21:** No `List-Unsubscribe` or `List-Unsubscribe-Post` header in
  Phase 9. Both are deferred to v2 as EMAIL-14, which needs a non-fragment
  unsubscribe credential compatible with the §5.4 fragment-token posture.
  The customer footer opt-out link (D-14) is the unsubscribe path. This
  supersedes the header items in SPEC §2, §4.4, and §9.

### Phase boundary guards
- **D-22 [informational]:** `preview_enc` keeps its current
  `{"subject","body"}` shape in Phase 9. The SPEC's `"text"` key name is
  stale: research verified `body` at `email.py:224-227` and
  `merchant.py:867-871`, so do not rename it. The redacted `html` key and the
  sandboxed preview are EMAIL-04 (Phase 10). If the sent text part changes
  (footer lines), the stored preview body should still represent the text
  part as actually sent, redacted as today, including the footer opt-out
  link (`[order-status link omitted]`).
- **D-23:** Phase 9 ships tests for what it builds. Tests that do not boot
  the host carry `pytest.mark.fast`. Coverage: `_build_message` unit tests
  with no network (MIME tree, header set, CID wiring, From encoding and
  CR/LF stripping, `<script>`-title escaping, channel footers in both parts);
  suppression tests for D-16/D-17; and updates, in the same change, to any
  existing runtime or qualification assertion that encodes the host
  `send_email` call or channel-agnostic `notify_events` suppression.
  `make verify-fast` stays green before every push (AGENTS.md). Expanding
  `tests/qualification/test_p0_09`/`test_p0_10` and the `harness/email.py`
  multipart model are EMAIL-13 (Phase 11).
- **D-24:** Phase 9 adds no HTTP routes, migrations, or `merchants` columns,
  so the `harness/registry.py::HTTP_ROUTES` ↔ spec §5 and
  `harness/schema.py` ↔ spec §4 parity surfaces stay untouched. Those belong
  to Phase 10/11.

### Owner decisions from research open questions (2026-10-17)
- **D-25:** `_smtp_send` mirrors the host's TLS behaviour exactly:
  `starttls()` with no SSL context, which on Python 3.12 does not verify the
  relay certificate, and no new TLS setting. Its only addition is a socket
  `timeout=` on `smtplib.SMTP`, needed because a cancelled `asyncio.wait_for`
  leaves the worker thread running. A code comment at the `starttls()` call
  records the residual (no certificate verification; ASVS 9.2.1 is Level 2,
  the project runs Level 1) and points at the deferred hardening item in
  `.planning/STATE.md` → Deferred Items.
- **D-26:** Fix the existing text-render wart. `_render_body`'s first line
  `f"Order {label}."` prints "Order order confirmed."; it changes to read
  naturally, e.g. `f"{label.capitalize()}."`, which gives "Order
  confirmed.", "New order received." and "Refund requested.". This is the
  only intended change to the existing text render.
- **D-27 [deferred]:** Frozen single-binary LNbits builds may lack
  `email.policy`, `email.headerregistry` and `email.contentmanager`. Phase 9
  does NOT vendor them. A frozen-binary send-test smoke belongs to Phase 11
  release qualification, which vendors the modules via
  `tools/package_release.py` only if the smoke fails. Tracked in
  `.planning/todos/2026-10-17-frozen-binary-email-smoke.md`.

### Claude's Discretion
- Kill switch (SPEC open question 5): an optional `email_html` ext_settings
  flag that falls back to text-only sends without a redeploy. Include it only
  if it stays a one-line branch in `_build_message`'s caller.
- `Message-ID` domain: prefer the host notifications sender's domain over the
  default local FQDN of `make_msgid()`, which would leak the server
  hostname.
- Template mechanics: Python string building or a dedicated autoescaping
  Jinja environment — whichever keeps D-10 mechanically enforced and
  testable, with no autoescape-off paths.
- Module layout: pure rendering/MIME code may move to a host-import-free
  module (e.g. `services/email_render.py`) if that is needed to unit-test it
  under `pytest.mark.fast` without booting the host.
- Account-row branding: if `channel='account'` rows are not bound to a
  merchant display name/theme, render a neutral instance wordmark and the
  default accent (research confirms how magic-link rows bind).
- Customer footer when the status-link token copy is not live: keep the
  opt-in notice and render the opt-out line without a link. Never invent a
  token-less URL.
- Phase 10 seams: `_render_html` may accept optional header/footer text
  arguments (escaped plain text, unused in Phase 9) so Phase 10 only wires
  data.
- Admin copy: if the Notifications section copy implies `notify_events`
  toggles gate customer emails, a text-only copy correction is allowed. All
  other admin UI work belongs to Phase 10.
- Spec §8.8: update only the one suppression sentence for D-17, and only if
  a contract/spec test needs it to keep verify-fast green. The full contract
  rewrite is EMAIL-12 (Phase 11).
- Plan decomposition and wave layout (granularity: coarse; tracer-first).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope and requirements
- `.planning/specs/order-email-templates-SPEC.md` — design input (PRD) for all of v1.2. Key sections: §3 SMTP boundary, §4.1 MIME tree, §4.2 template rules, §4.4 unsubscribe, §5 channels, §6 invariants, §9 test plan, §10 open questions
- `.planning/REQUIREMENTS.md` — EMAIL-01..03 and EMAIL-08..11 (this phase); EMAIL-14/15 (v2); Out of Scope table
- `.planning/ROADMAP.md` — Phase 9 goal and 5 success criteria; Phase 10/11 boundaries
- `AGENTS.md` — verification gates (`make verify-fast`, contract-surface parity) and the `pytest.mark.fast` convention

### Email send path (primary edit surface)
- `infinitemarkets/services/email.py` — module contract docstring; `_suppression_reason` (`notify_events` + consent gates), `_subject`, `_render_body`, `_status_link`, `worker_tick`/`_send` (host `send_email` call + `asyncio.wait_for` deadline), `enqueue_magic_link`, `enqueue_test_send`, `_EVENT_LABELS`, hourly caps
- `.cache/lnbits/lnbits/core/services/notifications.py` — host `send_email`. Read-only reference for SMTP setting names and the TLS/login mechanics to mirror. MUST NOT be modified (pinned e336fe1; see `.cache/lnbits/AGENTS.md`)
- `infinitemarkets/services/merchant.py` — `send_test_notification` (test-send flow, ≤5/hour bucket) and `get_notifications`
- `infinitemarkets/services/nostr_auth.py` — magic-link minting and the `enqueue_magic_link` callers (account channel)
- `infinitemarkets/settings.py` — `ext_settings()` (`email_enabled`, `public_base_url`, `privacy_key`); the home for an optional kill switch

### Data feeding the template
- `infinitemarkets/migrations.py` and `docs/technical-specification.md` §4 — `orders`, `order_items` (`unit_price_minor`, `line_total_sat`, `currency_decimals`, `backordered_qty`), `merchants` (`display_name`, `theme`, `notify_events`, `notify_emails`), `email_queue` (§4.18)
- `infinitemarkets/services/themes.py` — theme accent token source and validation (the Phase 9 accent source)

### Opt-out and token posture
- `infinitemarkets/views_public_api.py` — `POST /order-email-opt-out`
- `infinitemarkets/static/infinitemarkets/js/public_order.js` — order-page opt-out button
- `docs/technical-specification.md` §5.4 — fragment-only bearer tokens; §8.8 — email notification worker contract

### Tests that exercise the send path
- `tests/runtime/test_email_queue.py`, `tests/runtime/test_email_signin.py`, `tests/runtime/test_buyer_accounts.py` — host-boot runtime tests that touch the send path
- `tests/qualification/test_p0_09_email_persistence.py`, `tests/qualification/test_p0_10_smtp_boundary.py` — current qualification contract (expansion is Phase 11)
- `harness/email.py` — the executable §8.8 model the qualification tests run against (multipart modeling is Phase 11)

### Phase 10/11 surfaces (boundary awareness only — do not implement here)
- `infinitemarkets/services/media.py` (`store_local`, `_referenced_names`), `infinitemarkets/services/og_images.py` (`_MAX_SOURCE_PIXELS`), `infinitemarkets/views_api.py` (`PatchNotificationsBody`, notifications routes), `infinitemarkets/static/infinitemarkets/js/admin_notifications.js` (the SPEC's `admin_settings.js` reference is stale), `harness/registry.py`, `harness/schema.py`

</canonical_refs>

<specifics>
## Specific Ideas

- MIME tree (SPEC §4.1):
  ```
  multipart/alternative
  ├── text/plain              # existing _render_body output + mandatory footer
  └── multipart/related       # only when a logo is supplied
      ├── text/html           # new _render_html output
      └── image/png|jpeg      # Content-ID: <logo@infinitemarkets>
  ```
- Preheader example: "Order confirmed — {display_name}".
- Font stack: `-apple-system, "Segoe UI", Roboto, Helvetica, Arial`.
- Logo `<img>`: `src="cid:logo@infinitemarkets"`, `height="40"`, `alt` = escaped display name.
- Accent regex: `^#[0-9a-fA-F]{6}$`.
- SPEC §9 test intents for this phase's slice: `multipart/alternative`
  structure; text part = existing render + footer; CID part present iff a
  logo is supplied; `<script>` title escaped; suppression unchanged except
  D-17; no token/PII in either part; From display-name CR/LF stripping.
- SPEC §11 notes that `services/orders.py` needs no change (rendering happens
  at send time).

</specifics>

<deferred>
## Deferred Ideas

### Phase 10 — Merchant Email Branding Controls (EMAIL-04..07)
- `merchants.email_logo_path`, `email_header_text` (≤120, single line,
  control chars stripped), `email_footer_text` (≤240), and `email_accent`
  (`#rrggbb` or NULL → theme accent), via migration `m020` plus `models.py`
  `Merchant` fields.
- Logo: single slot via `media.py::store_local`; ≤256 KB; Pillow verify +
  pixel cap; stored as PNG/JPEG. Store new → update pointer → best-effort
  delete old. `POST/DELETE .../notifications/logo`. `gm-media-picker`
  local-backend-only mode. Send-time logo load with fallback.
- `_referenced_names` haystack gains `email_logo_path` (path form
  `infinitemarkets/<ns>/<name>`).
- `PatchNotificationsBody` and the `merchant_service.patch_merchant`
  allowlist gain header/footer/accent (not `PatchMerchantBody`).
  `_public_merchant` never exposes `email_*`.
- `preview_enc` gains redacted `html`; sandboxed owner preview; logo bytes
  absent from the preview.

### Phase 11 — Email Contract & Release Qualification (EMAIL-12/13)
- Technical-spec §4/§5/§8.8/§15 (CID-only / no-remote-`img` rationale) plus
  `harness/registry.py::HTTP_ROUTES` and `harness/schema.py` parity.
- `harness/email.py` multipart model so PII/log-exposure assertions cover
  both parts; qualification tests for MIME structure, escaping, channel
  gating, preview redaction, and validation rejections.
- Frozen-binary send-test smoke (D-27); vendor the `email.*` stdlib modules
  in `tools/package_release.py` only if it fails.

### Future hardening (owner-deferred)
- Verified STARTTLS (`starttls(context=ssl.create_default_context())`) on
  the extension SMTP hop — ASVS 9.2.1 (Level 2). v1.2 keeps host parity
  (D-25).

### v2 (not in v1.2)
- EMAIL-14: `List-Unsubscribe` header / RFC 8058 one-click (needs a
  non-fragment credential).
- EMAIL-15: per-channel `customer_events` toggles.
- `Reply-To: notify_emails[0]` (SPEC "optional but recommended") — not in
  EMAIL-11; needs an owner decision.

### Out of scope (REQUIREMENTS)
- Merchant-authored HTML / free-form templates; per-event custom copy; remote
  `<img>` logos; marketing/bulk email; host `send_email` changes.

</deferred>

---

*Phase: 09-branded-multipart-send-path*
*Context gathered: 2026-10-17 via PRD Express Path*
