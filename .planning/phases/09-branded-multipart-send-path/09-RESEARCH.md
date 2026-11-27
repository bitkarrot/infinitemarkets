# Phase 9: Branded Multipart Send Path - Research

**Researched:** 2026-10-17
**Domain:** Python 3.12 stdlib MIME/SMTP (`email`, `smtplib`) inside an async LNbits-extension queue worker; transactional HTML email templating; consent gating
**Confidence:** HIGH for codebase facts and stdlib behavior (read from source this session + live probes on the pinned 3.12.13 interpreter); MEDIUM for HTML email-client rendering specifics; LOW items are tagged `[ASSUMED]` and listed in the Assumptions Log.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

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
  `text/plain` part comes first: the existing `_render_body` output, retained,
  plus the mandatory footer lines of D-14. The HTML alternative comes last.
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
- **D-13:** Subjects are unchanged: merchant display name + event label only
  (`_subject`), with no buyer PII, addresses, or internal ids. The same rule
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
  `{"subject","text"}` shape in Phase 9; the redacted `html` key and the
  sandboxed preview are EMAIL-04 (Phase 10). If the sent text part changes
  (footer lines), the stored preview text should still represent the text
  part as actually sent, redacted as today.
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

### Deferred Ideas (OUT OF SCOPE)

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

### v2 (not in v1.2)
- EMAIL-14: `List-Unsubscribe` header / RFC 8058 one-click (needs a
  non-fragment credential).
- EMAIL-15: per-channel `customer_events` toggles.
- `Reply-To: notify_emails[0]` (SPEC "optional but recommended") — not in
  EMAIL-11; needs an owner decision.

### Out of scope (REQUIREMENTS)
- Merchant-authored HTML / free-form templates; per-event custom copy; remote
  `<img>` logos; marketing/bulk email; host `send_email` changes.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| EMAIL-01 | Order-event emails are delivered as `multipart/alternative` — the existing `text/plain` render plus a branded `text/html` part — through an extension-owned SMTP boundary (`_build_message`/`_smtp_send`) that reuses the host SMTP configuration and existing timeout/retry discipline. | Host helper mechanics read verbatim (§"Host `send_email` (what to mirror)"); single call site `email.py:424-439`; verified stdlib tree `add_alternative`→`add_related`; `sendmail` ASCII rule → QP CTE; `wait_for` does not stop the thread → pass `smtplib.SMTP(timeout=)`; Pattern 1–2 + Code Examples 1–3. |
| EMAIL-02 | HTML part renders a merchant-branded template: logo or display-name header with accent color, event title + state label, item table (title, quantity, line totals), order totals (subtotal/shipping/total sats), status-link CTA while the token copy is live, channel-appropriate footer copy. | Source columns confirmed: `orders.subtotal_sat/shipping_sat/total_sat`, `order_items.line_total_sat/backordered_qty` (migrations.py:478-480, 506-519); items query must be widened (email.py:310-314 selects only `title, quantity`); accent source `resolve_tokens(parse_theme(...))["--color-accent"]`; contrast probe → computed on-accent text color; Pattern 4–5, Code Example 5. |
| EMAIL-03 | Every interpolated value in the HTML part is escaped; digital delivery only in customer-channel `confirmed`; subjects display name + event label, no PII/ids. | Jinja2 `autoescape=True` probe (escapes `< > & " '`, NOT CSS context); `re.fullmatch` for hex; delivery already gated at load (email.py:316-319) — add a render-side double gate; `display_name` has zero validation (merchant.py:418-419) → sanitize for headers; Pitfalls 6–9. |
| EMAIL-08 | `notify_events` gates merchant-channel emails only; customer-channel gates solely on `email_opt_in` re-checked at send time. | Enqueue already merchant-only (orders.py:858-863); the bug is send-time `_suppression_reason` (email.py:156-160); test rows = `channel='merchant' AND order_id IS NULL` (email.py:524); `harness/email.py:442-449` + `test_p0_10` case (2) encode channel-agnostic gating → minimal D-23 update; Code Example 4. |
| EMAIL-09 | Customer footer: order-page opt-out link + opt-in notice; account: sign-in copy; merchant/test: neutral transactional notice — each in both parts. | Opt-out button lives on the status page (`public_order.js:181-182,220-229`); existing text already ends with the neutral line (email.py:201-203); customer footer link IS the bearer status link → must be redacted in `preview_enc` (Pitfall 4); Pattern 6. |
| EMAIL-10 | Test sends render the branded template with representative sample content; not suppressed by `notify_events`. | `enqueue_test_send` inserts `NULL, 'merchant', 'order_received'` (email.py:524) → today suppressed if `order_received` is toggled off; sample content injected after suppression; Pattern 3. |
| EMAIL-11 | Encoded `From` display name (CR/LF-stripped), `Date`, `Message-ID`, `Auto-Submitted: auto-generated`. | Probes: CR/LF → `ValueError` (sanitize first); TAB/NUL/ESC/U+2028 pass through → strip Unicode `Cc/Cf/Zl/Zp`; `make_msgid()` default leaked FQDN and blocked 5.0 s → `domain=`; `formatdate(localtime=True)`; RFC 3834 §5; Code Example 1. |
</phase_requirements>

## Summary

The send-path swap itself is small and well-bounded. There is exactly one SMTP call site — `worker_tick._send` awaits the host `send_email(...)` under `asyncio.wait_for(..., timeout=min(30, remaining))` (`infinitemarkets/services/email.py:424-439`). The host helper it replaces has no branches: it builds a compat32 `MIMEMultipart()` with one `MIMEText(message, "plain")`, then in `asyncio.to_thread` runs `smtplib.SMTP(server, port)` → `starttls()` → `login(username or from_email, password)` → `sendmail(from_email, to_emails, msg.as_string())`, returning `True`, or logging `str(e)` and returning `False` (`.cache/lnbits/lnbits/core/services/notifications.py:205-240`). There is no SMTPS/465 path, no plaintext path, no socket timeout, and on Python 3.12 `starttls()` with no context is **unverified TLS**. `_smtp_send` should mirror exactly that sequence (D-03) and add only `smtplib.SMTP(..., timeout=)`, because `asyncio.wait_for` cancelling an `asyncio.to_thread` call leaves the thread running (verified by probe). It should never log.

The biggest planning risk is the test migration, not the feature. Eight runtime test functions patch `lnbits.core.services.notifications.send_email` and read positional args (`args[5]` for the recipient list, `args[7]` for the body). One of them, `test_hard01_settled_without_accounting_email`, is parametrized into 18 cases. After the swap those patches stop applying. Some tests would then pass while testing nothing — `test_expired_claim_never_calls_smtp` asserts `sent == []`. Others would make real SMTP connections to the host default `smtp.protonmail.ch:587`. D-23 requires migrating them in the same change. The new seam is `infinitemarkets.services.email._smtp_send`, looked up on the module object returned by `importlib.import_module`. Migrated tests must also set a valid `lnbits_email_notifications_email`, because `_build_message` validates the sender the way the host does. Add a fail-closed `smtplib.SMTP` guard to `tests/runtime/conftest.py`.

The consent fix is send-side only. Enqueue already gates `notify_events` on the merchant channel alone (`orders.py:858-863`). The bug is `_suppression_reason` (`email.py:156-160`), which applies the flag to every channel. Test sends are the only orderless merchant rows (`email.py:524`), so `channel == 'merchant' and order_id is None` identifies them without a schema change. No contract test parses spec §8.8, so the spec stays untouched in Phase 9. However, `harness/email.py:442-449` and `test_p0_10` case (2) encode channel-agnostic event suppression on a *customer* row, so D-23 requires a minimal update to both.

**Primary recommendation:** Keep everything in `services/email.py`; it imports with no host boot in 1.42 s, so no new module is needed. Use:
- **Message:** stdlib `EmailMessage` with explicit `cte="quoted-printable"` on both parts; headers sanitized by stripping Unicode `Cc/Cf/Zl/Zp`; `make_msgid(domain=<sender domain>)`.
- **Template:** a dedicated Jinja2 `Environment(autoescape=True, undefined=StrictUndefined)`. Jinja2 is host-provided, so this adds no dependency, and ASVS 5.3.3 prefers automated escaping. Validate every CSS color with `re.fullmatch` and compute the on-accent text color by WCAG contrast.
- **Delivery:** the test-seam migration ships in the same plan as the transport swap.

## Project Constraints (from AGENTS.md)

There is no `./CLAUDE.md`. `/Users/bk/github/infinitemarkets/AGENTS.md` is the binding equivalent (orchestrator-confirmed). Its directives:

- **Verification gates (before every push):** `make verify-fast` (= `uv run pytest -m fast -q`, currently 320 of 1108 tests collected); `uv run pytest tests/runtime -q` (~6 min); `uv run ruff check .`; `node --check <edited .js>` (only if admin JS is touched). [VERIFIED: AGENTS.md; collection count from `pytest -m fast --collect-only` this session]
- **`pytest.mark.fast`** on every new test that does not boot the host. Precedent: `pytestmark = [pytest.mark.runtime, pytest.mark.fast]` in `tests/runtime/test_crypto_keystore.py:15`, `test_catalog_events.py:14`, `test_keystore_nip17.py:19`. [VERIFIED: grep + read]
- **Contract surfaces must be touched together, never alone:** spec §5 ↔ `registry.HTTP_ROUTES`, §7 ↔ `STATE_MACHINES`, §4 ↔ `schema.py`. Phase 9 touches none of them (D-24). [VERIFIED: AGENTS.md]
- **Delivery:** features/fixes land via PR; docs commits go directly to main.
- **`_public_merchant` must never leak `*_enc`/`*_hash`** (unaffected here).
- **Public theme tokens never style admin chrome; no arbitrary CSS, scripts, or remote URLs.** The email accent is a validated token and the HTML carries no remote URLs, consistent with this posture.
- **Host is read-only.** `.cache/lnbits/AGENTS.md` forbids editing the pinned host. D-02 and the REQUIREMENTS out-of-scope table also exclude host `send_email` changes.
- **Ruff:** `line-length = 100`, `select = ["E", "F", "I", "W"]` (`pyproject.toml`). E501 also applies to lines inside triple-quoted template strings (verified by probe; see Pitfall 13). [VERIFIED: pyproject.toml read + ruff probe]
- **Identifier closure.** `test_p0_14_contract_closure.py:395-415` scans `harness/*.py` and `tests/qualification/*.py` for `(?i)(?:gamma|infinite)[-_ ]?markets?`. Only the spelling `infinitemarkets` may appear, so a fallback wordmark such as "Infinite Markets" must never be written into those trees. Reuse the existing fallback `"Infinitemarkets"` (`email.py:171`). [VERIFIED: read]

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Suppression / consent gating (D-16/D-17) | API / Backend (`services/email.py::_suppression_reason`) | Database (`orders.email_opt_in` re-read under the order row lock) | Send-time decision must re-check consent inside the claim transaction |
| Message rendering (text, HTML, footers, sample content) | API / Backend (`services/email.py`, pure functions) | — | Rendered at send time from current DB state; no browser involvement |
| MIME assembly + headers (`_build_message`) | API / Backend (pure, event-loop thread) | — | CPU-light, no I/O; must not call blocking `socket.getfqdn()` |
| SMTP transport (`_smtp_send`) | API / Backend (worker thread via `asyncio.to_thread`) | External: operator's SMTP relay (host settings) | Blocking `smtplib` must never run on the event loop; outside every DB transaction |
| Theme accent → email color | API / Backend (`services/themes.py` read-only reuse) | Database (`merchants.theme` JSON) | Same token resolution as the storefront; email validates again at render |
| Opt-out action | Browser (`public_order.js` button on the status page) | API (`POST /order-email-opt-out`) | Already exists; the email only links to the status page (fragment token) |
| Preview persistence (`preview_enc`) | Database (AEAD blob) | API (`get_email_preview`) | Shape unchanged `{"subject","body"}`; text-as-sent, redacted |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `email.message.EmailMessage` (stdlib) | CPython 3.12.13 (project pin `requires-python = ">=3.12,<3.13"`) | MIME tree, `set_content`/`add_alternative`/`add_related`, header objects | Official modern API; D-02 locks the return type [VERIFIED: pyproject.toml read; probe on `.venv/bin/python` 3.12.13] |
| `email.headerregistry.Address`, `email.utils.formatdate`/`make_msgid` (stdlib) | 3.12.13 | Encoded `From`, `Date`, `Message-ID` | D-18/D-19 lock these helpers [CITED: docs.python.org/3.12/library/email.utils.html, email.headerregistry.html] |
| `smtplib` (stdlib) | 3.12.13 | STARTTLS/login/sendmail transport | Exactly what the host helper uses (D-03) [VERIFIED: notifications.py:229-234] |
| `asyncio.to_thread` / `asyncio.wait_for` (stdlib) | 3.12.13 | Non-blocking transport + existing deadline | Existing discipline at email.py:425-437 |
| Jinja2 (host-provided, **not installed by this phase**) | 3.1.6 (uv.lock:689-690; host pins `jinja2~=3.1.6` at `.cache/lnbits/pyproject.toml:15`) | Autoescaping HTML template | ASVS 5.3.3 "context-aware, preferably automated" escaping; already loaded in-process by the host's `template_renderer` (views.py:26) [VERIFIED: uv.lock + probe] |
| MarkupSafe (Jinja2's escaper, host-provided) | 3.0.3 (uv.lock:903-904) | Escapes `& < > " '` | Used implicitly by Jinja2 autoescape [VERIFIED: probe output `&#34;`, `&#39;`] |

### Supporting (in-repo, reuse — do not re-implement)
| Helper | Location | Purpose | When to Use |
|--------|----------|---------|-------------|
| `themes.parse_theme`, `themes.resolve_tokens`, `themes.contrast_ratio` | `services/themes.py:764-773, 519-531, 259-262` | Accent lookup + WCAG ratio | Email accent + on-accent text color |
| `lnbits.helpers.is_valid_email_address` | `.cache/lnbits/lnbits/helpers.py:161-163` | Same address validation as the host | Validate sender/recipient in `_build_message` (mirrors host ValueError semantics) |
| `_status_link`, `_subject`, `_render_body`, `_render_signin_body` | `services/email.py:169-257` | Existing token/expiry, subject, text renders | Keep signatures; extend around them |
| `nip89.price_label` | `services/nip89.py:181-189` | `"2,500 sats"` / `"15.00 USD"` formatting | Optional unit-price display; line totals use `f"{n:,} sats"` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Jinja2 autoescape env | `html.escape` string building (precedent: `nip89.render_markdown`, nip89.py:310-316) | No new import, but escaping depends on discipline at every interpolation; Phase 10 adds two more free-text fields. Acceptable fallback **only** with the same per-field payload tests. Neither option protects CSS context. |
| Explicit `cte="quoted-printable"` | Default CTE heuristics | Heuristics pick `8bit` for short non-ASCII lines (probe: `[None, '8bit', '8bit']`), so the in-memory object diverges from the wire and `send_message`/`as_bytes` would emit raw 8-bit. Explicit QP is deterministic and assertable. |
| `sendmail(from, [to], msg.as_string())` (host parity) | `smtp.send_message(msg, from_addr=…, to_addrs=[…])` | `send_message` uses BytesGenerator CRLF; equivalent for ASCII wire. Keep `sendmail` for D-03 parity. |
| Separate `services/email_render.py` | — | Not needed: `infinitemarkets.services.email` imports host-free (probe), and any `infinitemarkets.*` import runs the package `__init__` anyway. A split would complicate the monkeypatch seams tests rely on (`email._render_body`, `email._smtp_send`). |

**Installation:** None. The phase installs no packages. Stdlib modules ship with the interpreter; Jinja2/MarkupSafe are already locked transitively through the pinned host.

**Version verification:** `uv.lock:689-690` → `name = "jinja2"`, `version = "3.1.6"`; `uv.lock:903-904` → `name = "markupsafe"`, `version = "3.0.3"`; interpreter `Python 3.12.13`. [VERIFIED: read/probe this session]

## Package Legitimacy Audit

This phase installs no external packages. It only references packages already in `uv.lock` through the pinned host. The seam was run for completeness:

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| jinja2 | PyPI | locked 3.1.6 (latest publish 2025-03-05) | unknown (seam had no stats) | github.com/pallets/jinja | [SUS] (`unknown-downloads`) | Not installed — already present via host `jinja2~=3.1.6`; no checkpoint needed |
| markupsafe | PyPI | locked 3.0.3 (the seam's `too-new` refers to the *latest* publish 2026-10-02, not the locked version) | unknown | github.com/pallets/markupsafe | [SUS] (`too-new`, `unknown-downloads`) | Not installed — locked transitively; no checkpoint needed |

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** jinja2, markupsafe. Both are flagged only by metadata gaps, both are the host's own pinned dependencies, and nothing is installed or upgraded. If the planner chooses string building instead, neither is referenced.

## Architecture Patterns

### System Architecture Diagram

```
 producers (unchanged)                       email_queue (unchanged schema)
 ─────────────────────                       ─────────────────────────────
 orders.enqueue_email_intents ──┐  merchant rows (notify_events-gated at ENQUEUE)
 (merchant + customer rows)     ├─────────►  customer rows (email_opt_in at ENQUEUE)
 merchant.send_test_notification├─────────►  test row: channel='merchant', order_id NULL,
   → email.enqueue_test_send    │                      event_type='order_received'
 nostr_auth.request_email_*  ───┘─────────►  account row: channel='account', 'signin_link'
                                                         │
 tasks.email_sender (every 5 s) ─► worker_tick ─► claim_batch (claim_token CAS)
                                                         │
          ┌──────────── DomainTransaction (order row lock + live-claim re-read) ─────────┐
          │ load merchant, order, items(+line totals), delivery (customer+confirmed)     │
          │ _suppression_reason:                                                         │
          │   email-disabled ─► host-email-unconfigured ─► merchant-inactive             │
          │   ─► [NEW] event-disabled ONLY if channel=='merchant' AND order_id NOT NULL  │
          │   ─► consent-revoked if channel=='customer' and not order.email_opt_in       │
          │ rate bucket (account / customer / merchant)                                  │
          └──────────────────────────────────────────────────────────────────────────────┘
                     │ suppressed / rate-deferred → leased write, return
                     ▼  (no DB transaction held from here)
   decrypt recipient ─► [test row? substitute SAMPLE order/items] ─► render:
     subject  = _subject(...)              (display-name sanitized)
     text     = _render_body(...) | _render_signin_body(...)  + channel footer lines
     preview  = redacted text (status/sign-in links → "[... omitted]", incl. footer link)
     view     = branding (name, accent, on-accent), title, state, items, totals,
                delivery (double-gated), CTA (live link only), footer, sample flag
                         │
   remaining = deadline − monotonic();  budget = min(30, remaining)
   try:
     msg  = _build_message(subject, text, view, from=host addr, to=recipient,
                           with_html=settings.email_html, logo=None)   ← pure, no I/O
            └─ validates addrs · From=Address(name) · Date · Message-ID(domain=sender)
               · Auto-Submitted · text/plain(QP) ─ add_alternative(text/html QP)
               ─ [logo] add_related(image/png|jpeg, cid=<logo@infinitemarkets>)
     sent = await wait_for(_smtp_send(msg, to=recipient, timeout=budget), budget)
            └─ to_thread: SMTP(server, port, timeout) → starttls() → login() → sendmail()
   except Exception: sent = False                         (never logs)
                         │
   DomainTransaction ─► sent: wipe recipient_enc/payload_enc, store preview
                     ─► else: attempts+1 → pending (backoff) | failed (max attempts)
```

### Recommended Project Structure
```
infinitemarkets/
├── services/email.py        # ALL Phase 9 code: sanitizers, _render_html (Jinja env),
│                            # _build_message, _smtp_send, D-16/D-17 suppression, sample data
├── settings.py              # +1 field email_html: bool = True, +1 _bool_env line (kill switch)
└── (no new modules, routes, migrations, or columns — D-24)
harness/email.py             # minimal: event gate merchant-only (D-23); multipart model is Phase 11
tests/
├── runtime/test_email_render.py   # NEW, pytest.mark.fast + runtime, no host boot
├── runtime/conftest.py            # + fail-closed smtplib.SMTP guard (+ optional smtp_capture)
├── runtime/test_email_queue.py    # migrate host send_email patches → _smtp_send
├── runtime/test_email_signin.py   # migrate
├── runtime/test_financial_review.py # migrate
└── qualification/test_p0_10_smtp_boundary.py  # case (2): merchant row + customer-not-gated
```

### Pattern 1: Pure builder + thin transport (D-02/D-03)
**What:** `_build_message` performs every decision with no I/O and runs on the event loop. `_smtp_send` does only network work, in a thread.
**When to use:** Every `email_queue` send (customer, merchant, account, test).
**Key rules:**
- Call `_build_message` **inside** the existing `try:` that wraps the send. Invalid sender/recipient then becomes `sent = False` → bounded retry, which preserves today's semantics (the host raises `ValueError` for invalid addresses inside `wait_for`).
- Keep `_render_body` / `_render_signin_body` **outside** the try, as today. `test_worker_errors_do_not_log_private_exception_text` expects a broken `_render_body` to yield outcome `"error"` (test_email_queue.py:545-567).
- `_build_message` renders the HTML itself (D-02) so it alone decides whether the logo is usable. It must never emit `cid:` without the related part.

### Pattern 2: Mirror host transport, add only a socket timeout
**What:** `smtplib.SMTP(server, port, timeout=budget)` → `starttls()` → `login(username or from_addr, password)` → `sendmail(from_addr, [to], msg.as_string())`. Return `True`. Let exceptions propagate.
**Why the timeout:** `wait_for` cancels the awaiting coroutine but the worker thread keeps running (probe: thread finished 1 s after a 0.2 s timeout). Without a socket timeout, a hung relay leaks default-executor threads, and a late completion delivers a message already scheduled for retry.

### Pattern 3: Test-row discriminator + sample content (D-16)
- `is_test = row["channel"] == "merchant" and not row["order_id"]`. This is unique: `orders.enqueue_email_intents` always binds `order["id"]` (orders.py:838-855), and the only orderless merchant insert is `enqueue_test_send` (email.py:519-528).
- Substitute a fixed `_SAMPLE_ORDER` and `_SAMPLE_ITEMS` **after** suppression and rate-limiting. Never feed sample data into `_suppression_reason`.
- Render through the same `_render_body`, so the text part also shows sample lines.
- Add a clear marker line in both parts, e.g. "Test email — sample content, not a real order."
- No CTA link. A styled non-link placeholder is acceptable; never invent a URL.

### Pattern 4: Accent and on-accent color (D-08/D-09)
- `accent = themes.resolve_tokens(themes.parse_theme(merchant.get("theme")))["--color-accent"]`, then `accent = accent if _HEX6.fullmatch(accent or "") else _DEFAULT_ACCENT`, where `_DEFAULT_ACCENT = "#d69a3a"` is the warm-market preset accent.
- `on_accent = "#ffffff" if themes.contrast_ratio("#ffffff", accent) >= 4.5 else "#111111"`.
- **Every** preset accent fails white text (probe: warm-market/clean-minimal `#d69a3a` 2.46:1, high-contrast `#63d2ff` 1.72:1, lightnin-dark `#fce477` 1.27:1). `#111111` passes for all (7.68–14.84:1). `--color-accent` is not in themes `_GATED_PAIRS` (themes.py:137-149), so its contrast is never checked at write time.
- Use the accent as a 3px top rule on a white header band with dark wordmark text, and as the CTA fill with `on_accent` text.

### Pattern 5: Item/totals view model (EMAIL-02)
- Widen the items query to `SELECT title, quantity, line_total_sat, backordered_qty, unit_price_minor, currency, currency_decimals FROM order_items WHERE order_id = :o`. Today it is `SELECT title, quantity` (email.py:310-314).
- Format in Python before templating: `f"{n:,} sats"`, or `"—"` when `None` (all three money columns are nullable in the DDL).
- Totals come from `orders.subtotal_sat`, `shipping_sat`, `total_sat`. The badge shows when `backordered_qty > 0`.

### Pattern 6: Channel footer copy defined once, used in both parts (D-14)
- Module-level constants, e.g. `_FOOTER_CUSTOMER_OPTIN`, `_FOOTER_CUSTOMER_OPTOUT` (link variant + no-link variant), `_FOOTER_ACCOUNT`, `_FOOTER_TRANSACTIONAL`, `_SAMPLE_MARKER`. They are appended to the text render and passed into the HTML context.
- Merchant/test text already ends with "This is a transactional order notification." (email.py:201-203). Do not append it twice.
- Write copy **without apostrophes**, or have tests compare `html.unescape(html_part)`. MarkupSafe renders `'` as `&#39;` (Pitfall 10).

### Anti-Patterns to Avoid
- **Patching the host `send_email` in new or migrated tests.** It is no longer on the path, so the test passes vacuously or dials the network.
- **`make_msgid()` without `domain=`.** It leaks the FQDN and called `socket.getfqdn()`, which blocked 5.0 s per call (uncached) on this machine — on the event loop if `_build_message` runs there.
- **`re.compile(r"^#…$").match(x)` for the CSS guard.** `$` matches before a trailing newline (probe: `"#ffffff\n"` passes). Use `re.fullmatch`.
- **`|safe`, `Markup(...)`, or `{% autoescape false %}` in the template.** Each bypasses escaping (probe: `{{ x|safe }}` emits raw `<b>`).
- **Logging `str(exc)` from smtplib.** `SMTPRecipientsRefused` carries recipient addresses. The host helper logs `f"Sending Email failed. {e!s}"` (notifications.py:239); the new path must not. Never call `set_debuglevel`.
- **Changing `_render_body`'s signature or reading `row["channel"]` inside it.** `test_order_saga.py:295-298` calls it with `{"event_type": "confirmed"}` (no `channel` key) and positional args.
- **Renaming the preview key.** `get_email_preview` reads `payload["body"]` (merchant.py:867-871); D-22's `{"subject","text"}` wording is inaccurate — keep `body`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| RFC 2047 header encoding / quoting of display names | Manual `=?utf-8?…?=` or quoting | `email.headerregistry.Address(display_name=…, addr_spec=…)` | Probe: quotes, commas, and non-ASCII are encoded correctly; CR/LF rejected |
| MIME boundaries, CTE, CRLF | Hand-written multipart strings | `EmailMessage.set_content/add_alternative/add_related` | Probe-verified tree; QP keeps the wire ASCII for `sendmail` |
| Message-ID | uuid strings | `make_msgid(domain=…)` | RFC-shaped `<time.pid.rand@domain>` (stdlib email/utils.py:301-309) |
| Date header | `strftime` | `formatdate(localtime=True)` | RFC 5322 numeric zone; never `usegmt=True` (obsolete `GMT`) |
| HTML escaping | Ad-hoc `.replace()` | Jinja2 autoescape (or `html.escape`) | Covers `& < > " '`; ASVS 5.3.3 prefers automated |
| WCAG contrast | New luminance math | `themes.contrast_ratio` | Already used for theme gates |
| Address validation | New regex | `lnbits.helpers.is_valid_email_address` | Identical to the host helper's rule → identical accept/reject set |
| Sats formatting | Locale code | `f"{n:,} sats"` / `nip89.price_label` | Existing project convention |

**Key insight:** Every hard part — encoding, folding, CTE selection, CR/LF refusal — is already solved by the stdlib modern `email` API, provided three inputs are handled: sanitize text before it reaches a header, pin the CTE, and pass `domain=`. The remaining risk is test hygiene and context-specific escaping (CSS), not MIME.

## Runtime State Inventory

The phase swaps the transport under a live durable queue, so runtime state was checked.

| Category | Items Found | Action Required |
|----------|-------------|-----------------|
| Stored data | `email_queue` rows already `pending`/`claimed` at deploy are rendered at send time, so they go out multipart automatically. Existing `preview_enc` blobs are `{"subject","body"}` and stay readable (shape unchanged). Customer rows previously `suppressed` with `event-disabled` are terminal and stay suppressed — D-17 is not retroactive. | None (code-only). Document the non-retroactivity in the summary. |
| Live service config | LNbits admin → Notifications → Email (`lnbits_email_notifications_enabled/email/username/password/server/port`) is reused verbatim. Host defaults: `server="smtp.protonmail.ch"`, `port=587` (`.cache/lnbits/lnbits/settings.py:506-512`). SMTPS/465 was never supported (host always STARTTLS). | None |
| OS-registered state | None — verified: no schedulers/units; workers are in-process asyncio tasks (`tasks.py`). | None |
| Secrets/env vars | SMTP credentials remain host settings, read at call time and never stored or logged by the extension (§8.8 "MUST NOT store SMTP credentials"). Optional new `INFINITEMARKETS_EMAIL_HTML` (default true) if the kill switch is adopted. | Code edit only; doc row is a Phase 11 item |
| Build artifacts | Release zip packages git-tracked files (`tools/package_release.py:143-151`), so the edited `email.py` ships automatically. **Frozen single-binary LNbits builds** ship an incomplete stdlib: `_vendored.py` already back-fills `html.parser`/`_markupbase` (`tools/package_release.py:116-139`). `email.policy`/`email.headerregistry`/`email.contentmanager` (needed by `EmailMessage`) are not vendored. They are *likely* bundled — host-bundled `email.message` statically references `email.policy` (stdlib message.py:991), as do `aiohttp/helpers.py:24` and `packaging/metadata.py:7` — but this is unverified on the frozen binary. | Release smoke test on the frozen build (Open Question 2) |

## Host `send_email` (what to mirror) and current worker facts

Verbatim host helper (read this session, `.cache/lnbits/lnbits/core/services/notifications.py:205-240`):

```python
# DATA_Xq4m8RtZ_START
    if not is_valid_email_address(from_email):
        raise ValueError(f"Invalid from email address: {from_email}")
    if len(to_emails) == 0:
        raise ValueError("No email addresses provided")
    for email in to_emails:
        if not is_valid_email_address(email):
            raise ValueError(f"Invalid email address: {email}")
    msg = MIMEMultipart()
    msg["From"] = from_email
    msg["To"] = ", ".join(to_emails)
    msg["Subject"] = subject
    msg.attach(MIMEText(message, "plain"))
    username = username if len(username) > 0 else from_email

    def _send() -> bool:
        with smtplib.SMTP(server, port) as smtp_server:
            smtp_server.starttls()
            smtp_server.login(username, password)
            smtp_server.sendmail(from_email, to_emails, msg.as_string())
        return True

    try:
        return await asyncio.to_thread(_send)
    except Exception as e:
        logger.warning(f"Sending Email failed. {e!s}")
        return False
# DATA_Xq4m8RtZ_END
```

Findings (Q1):
- **Settings it reads** (passed by the worker, email.py:427-431): `lnbits_email_notifications_server`, `_port`, `_username`, `_password`, `_email`.
- **`host_email_ready`** = `host_settings.is_email_notifications_configured()` (email.py:277), defined as `return self.lnbits_email_notifications_enabled and bool(self.lnbits_email_notifications_email)` (`.cache/lnbits/lnbits/settings.py:539-542`). It does **not** validate the address format; the format check happens at send time (above).
- **TLS:** single branch — always `starttls()`. A server without STARTTLS raises `SMTPNotSupportedError`. No SMTPS (port 465 would fail), no plaintext.
- **Login:** always, with `username` falling back to `from_email`.
- **Validation:** regex `r"[A-Za-z0-9\._%+-]+@[A-Za-z0-9\.-]+\.[A-Za-z]{2,63}"` with `re.fullmatch` (helpers.py:161-163).
- **Python 3.12 `starttls()` with no context** → `context = ssl._create_stdlib_context()` (stdlib smtplib.py:777-778), and `_create_stdlib_context = _create_unverified_context` (ssl.py:791), which defaults to `cert_reqs=CERT_NONE, check_hostname=False` (ssl.py:732-735). **The host's STARTTLS does not verify the relay certificate.** [VERIFIED: stdlib source on disk]
- **`smtplib.SMTP(local_hostname=None)`** calls `socket.getfqdn()` for EHLO (stdlib smtplib.py, `__init__`), inside the thread, so it consumes part of the timeout budget (5.0 s on this machine).

Worker facts (Q2, email.py read this session):
- Lease `CLAIM_LEASE_S = 120`; caps `CUSTOMER_HOURLY_CAP = 8`, `MERCHANT_HOURLY_CAP = 60`, `ACCOUNT_HOURLY_CAP = 8` (email.py:33-39). Loop cadence `EMAIL_INTERVAL_S = 5` (tasks.py:30).
- Deadline (email.py:282, 298, 421-437): `deadline = time.monotonic()` → `deadline += row["claimed_until"] - db_now` → `remaining = deadline - time.monotonic()`. If `remaining <= 0`, return `"lost_claim"`; otherwise `timeout=min(30, remaining)`.
- Outcome writes: `sent` wipes `recipient_enc = :empty, payload_enc = :empty, preview_enc = :preview` (email.py:444-449). Failure → `attempts+1`; `failed` at `email_max_attempts`, else `pending` with `next_attempt_at = now + _backoff(attempts)` and `last_error = 'send-failed'` (email.py:451-469).
- Preview: `json.dumps({"subject": subject, "body": body}, …)` AEAD-encrypted with `record_id=row["id"]`, `column="preview_enc"` (email.py:224-232). The redacted body uses `"[order-status link omitted]"` / `"[digital content omitted]"` / `"[sign-in link omitted]"` (email.py:401-419).
- Logging: per-row isolation logs only `f"infinitemarkets email row {row['id']} failed: {type(exc).__name__}"` (email.py:474-478). The send `except Exception: sent = False` logs nothing (email.py:438-439).
- Events: `_EVENT_LABELS = {"order_received": "new order received", "confirmed": "order confirmed", "processing": "order processing", "shipped": "order shipped", "delivered": "order delivered", "cancelled": "order cancelled", "expired": "order expired", "on_hold": "order on hold", "refund_requested": "refund requested", "signin_link": "your sign-in link"}` (email.py:41-52).
- Existing text-render wart: `_render_body` emits `f"Order {label}."`, which produces "Order order confirmed." (probe). D-05 retains the render; see Open Question 4.

Row binding (Q5):
- **Test rows:** `enqueue_test_send` → `VALUES (:i, :m, NULL, 'merchant', 'order_received', :re, :rh, 'pending', 0, :n, 0, :n)` (email.py:524-525). `recipient_enc` is bound to `record_id=merchant_id` (email.py:507-511); decrypt already handles `row["order_id"] or row["merchant_id"]` (email.py:371).
- **Account rows:** `enqueue_magic_link` → `VALUES (:i, :m, NULL, 'account', 'signin_link', …)` (email.py:570), always with a real shop `merchant_id` (callers `nostr_auth.py:705-708` and `1139-1142` pass the shop merchant). The worker already loads that merchant row for every row (email.py:299-302), so account emails can use the merchant display name and theme. A neutral "Infinitemarkets" wordmark plus default accent is needed only as a defensive fallback.

### Test inventory — every patch site that must migrate (Q3)

| File:lines | Today | Breaks how after swap | Migration |
|------------|-------|-----------------------|-----------|
| test_email_queue.py:187-201 (`test_hard01_settled_without_accounting_email`, 3 states × 6 damages = 18 parametrized cases) | patches `notifications.send_email`; `args[5]` recipients, `args[7]` body; asserts `secret in body` | fake never called → `assert sent` fails, and the real `_smtp_send` runs | capture via `_smtp_send`; check the text/plain part (`get_body(("plain",)).get_content()`); set a valid host from-address |
| test_email_queue.py:297-391 (`test_send_classification`) | sets enabled + `shop@example.com`; patches with True/False fakes | not intercepted → real SMTP dial | `_smtp_send` fake returns True, then raises/returns False; preview asserts stay |
| test_email_queue.py:415-432 (`test_consent_revocation_suppresses`) | manual swap of `notif.send_email`; merchant rows are actually **sent** | merchant rows hit real `_smtp_send` → network | monkeypatch `_smtp_send` |
| test_email_queue.py:463-490 (`test_orderless_test_send`) | `sent_to[0][5]` contains recipient | fails | assert `to`/`msg["To"]`; add HTML sample-marker assertion (EMAIL-10) |
| test_email_queue.py:512-542 (`test_expired_claim_never_calls_smtp`) | asserts the fake is never called | **passes vacuously (false green)** | patch `_smtp_send` with a recorder |
| test_email_queue.py:545-567 (`test_worker_errors_do_not_log_private_exception_text`) | breaks `_render_body`; host configured; no send patch | still `error`; hermeticity gap | add the fail-closed SMTP guard; keep the `_render_body` call in `email.py` |
| test_email_signin.py:397-448 (`test_magic_link_send_renders_fragment_and_wipes`) | `args[5]`, `args[6]`, `args[7]`; token appears exactly once in body | fails | capture msg; `text.count(token) == 1` on the text part; HTML `href` contains the escaped link. **Decide:** token in text + HTML href means the full MIME contains it twice — assert per-part. |
| test_email_signin.py:478-523 (`test_account_channel_uses_email_account_bucket`) | fake returns True | real SMTP | monkeypatch `_smtp_send` |
| test_financial_review.py:386-402 (`read_surface("email")`) | `args[5]`/`args[7]`; **module does not cancel `_owned_tasks`** (background `email_sender` may run concurrently) | real SMTP from both explicit and background ticks | patch `_smtp_send` on the live module object (affects the background loop too); assert on the text part |
| test_order_saga.py:295-299 | calls `_render_body(...)` directly, positional, row without `channel` | breaks only if the signature/behavior changes | keep `_render_body` unchanged |

Not affected (verified): `test_email_signin.py:451-475` (suppressed before send), `test_email_signin.py:1284-1314` (page render only), `test_admin_ui.py:524-539` (copy strings: keep "Recent email queue", "Email preview", "Clear history", "Bearer links and digital content are redacted"), e2e (`tools/e2e_server.py:87-96` points SMTP at `127.0.0.1:10025` → connection refused → bounded retry; `/_e2e/mailbox` reads `payload_enc` from queue rows, `e2e_server.py:686-740`), conformance (outbox only).

**Patch seam:** `monkeypatch.setattr(importlib.import_module("infinitemarkets.services.email"), "_smtp_send", fake)`. `runtime_env` purges and reimports `infinitemarkets*` per module (conftest.py:151-155), so always resolve the module object at test time. `worker_tick` must call `_smtp_send` through the module global, never a captured alias.

### Contract-test exposure (Q4)
- **Spec §8.8** step 2 ("the merchant disabled the event type") and step 4 ("Deliver via `lnbits.core.services.notifications.send_email`") become stale prose. **No test parses them.** `test_p0_14_contract_closure.py` diffs only routes, state machines, §5.7 error codes, §10 task names, §12 settings (one-way: `registry.SETTINGS ⊆ §12`, lines 248-249), identifiers, and §6.8 (lines 185-252). Do not edit the spec in Phase 9; this follows the discretion rule ("only if a test needs it").
- **`registry.SETTINGS`** = `{"INFINITEMARKETS_MASTER_KEYS", "INFINITEMARKETS_ACTIVE_KEY_VERSION", "INFINITEMARKETS_PUBLIC_BASE_URL", "INFINITEMARKETS_PRIVACY_KEY", "RESERVATION_TTL", "OUTBOX_MAX_ATTEMPTS", "OUTBOX_BATCH", "PEER_RELAY_TTL", "INBOX_MAX_EVENT_BYTES", "CHECKOUT_RATE_LIMIT", "INFINITEMARKETS_EMAIL_ENABLED", "EMAIL_MAX_ATTEMPTS", "SPEC_REVISION"}` (registry.py:314-330). An unregistered `INFINITEMARKETS_EMAIL_HTML` breaks no test. Precedent: `INFINITEMARKETS_NSEC_SIGNIN`/`ADMIN_ORIGINS` are parsed in settings.py:470-471 but absent from §12 (spec.md:1739-1752).
- **`harness/email.py:442-449`** suppresses `event-type-disabled` for any channel, and **`test_p0_10_smtp_boundary.py:207-218`** asserts it on a **customer** row (`_enqueue_customer(..., event_type="shipped")`). This is the one qualification assertion encoding channel-agnostic suppression → D-23 "update in the same change":
  - harness: `if row["channel"] == "merchant" and row["event_type"] not in self.enabled_event_types:`
  - test case (2): use a merchant row for the suppressed assertion and add a customer row that is **not** suppressed by the disabled event.
  - Keep `SmtpStub`/`send_email(*, to, subject, body)` naming. The multipart model is Phase 11.
- `test_p0_09` is model-only and unaffected. Neither qualification file imports production `services/email.py` (both use `from harness import email as email_module`).

## Common Pitfalls

### Pitfall 1: Migrated tests silently stop testing (or dial the internet)
**What goes wrong:** host-`send_email` patches no longer intercept anything. `assert sent == []` passes vacuously; other tests make real SMTP connections to `smtp.protonmail.ch:587` (host default) under a 30 s timeout.
**How to avoid:** migrate all patch sites in the table above in the same plan as the transport swap. Add a function-scoped autouse fixture in `tests/runtime/conftest.py` that replaces `smtplib.SMTP` with a callable raising `ConnectionRefusedError`; tests that need the transport override it. A static guard test can assert `services/email.py` no longer references `notifications import send_email`.
**Warning signs:** runtime email tests slow down by ~30 s; `last_error='send-failed'` where `sent` was expected.

### Pitfall 2: Sender validation fails in migrated tests
**What goes wrong:** `_build_message` mirrors the host's `is_valid_email_address(from)` check. Several tests only monkeypatch `is_email_notifications_configured` and leave `lnbits_email_notifications_email` at its default `""`. Rows then go to `pending` instead of `sent`.
**How to avoid:** the shared fixture sets `monkeypatch.setattr(host_settings, "lnbits_email_notifications_email", "shop@example.com")` alongside the configured flag.

### Pitfall 3: Building the message outside the `try`
**What goes wrong:** an invalid address or a template bug raised outside the send `try` escapes to the per-row isolation → outcome `"error"`. The row stays `claimed` until lease recovery, and recovery never increments `attempts`, so it retries forever.
**How to avoid:** `_build_message` (validation + HTML render + MIME) goes inside `try: … except Exception: sent = False`. Only the pre-existing `_render_body` stays outside, because a test pins that behavior.

### Pitfall 4: The customer opt-out footer leaks the bearer link into `preview_enc`
**What goes wrong:** the opt-out link *is* `_status_link` (`…/infinitemarkets/order#<token>`). If the preview text is built from the sent text, the token lands in the owner preview, violating spec §4.18 ("bearer status links … omitted").
**How to avoid:** build preview text from the redacted render plus footer lines carrying `"[order-status link omitted]"`. Add a runtime test: customer preview has no `/infinitemarkets/order#`.

### Pitfall 5: `make_msgid()` blocks the event loop and leaks the hostname
**What goes wrong:** the default domain is `socket.getfqdn()` (stdlib email/utils.py:307-308). Probe: `<…@bks-MacBook-Air.local>`, and `getfqdn()` took **5.01 s, then 5.00 s** (uncached).
**How to avoid:** `make_msgid(domain=from_addr.rpartition("@")[2])` after validating `from_addr`. Test: the Message-ID ends with `@<sender domain>>` and does not contain `socket.gethostname()`.

### Pitfall 6: CR/LF or control characters in `display_name` make every send fail
**What goes wrong:** `display_name` has no validation at all (`merchant.py:418-419` stores `patch["display_name"]` verbatim). Probes:
- CR/LF in `msg["Subject"]` → `ValueError: Header values may not contain linefeed or carriage return characters`.
- `Address(display_name="…\r\n…")` → `ValueError: invalid arguments; address parts cannot contain CR or LF`.
- `formataddr` passes CR/LF through unchanged.
- TAB, NUL, ESC, and U+2028 are accepted and encoded (U+2028 decodes as a visual line break).

Today's compat32 path also fails, at serialization: `HeaderParseError: header value appears to contain an embedded header`.
**How to avoid:** one `_header_safe(text, limit)` that replaces Unicode categories `Cc` (controls), `Cf` (bidi overrides U+202A–E/U+2066–9, zero-width), `Zl`, and `Zp` with a space, collapses whitespace, strips, and truncates. Apply it to the display name in **both** `From` and `_subject` (normal names are unchanged, so `test_subject_has_no_pii` still passes). Fall back to the bare address when the result is empty.

### Pitfall 7: Escaping does not cover CSS context
**What goes wrong:** both Jinja autoescape and `html.escape` leave `;`, `:`, and `(` untouched. Probe: `style="background:{{ accent }}"` with `#fff;background:url(https://evil/x)` rendered a remote URL — a tracking pixel in a "no remote resources" email.
**How to avoid:** every CSS-interpolated value is either a template literal or passes `re.fullmatch(r"#[0-9a-fA-F]{6}", v)`, falling back to `#d69a3a`.

### Pitfall 8: `$` in the hex regex accepts a trailing newline
**What goes wrong:** `re.compile(r'^#[0-9a-fA-F]{6}$').match('#ffffff\n')` → `True` (probe). themes.py `_HEX_COLOR` (line 115) has the same property at write time, so stored accents may carry `\n`.
**How to avoid:** use `fullmatch` at render time (D-09). Do not "fix" themes.py in this phase.

### Pitfall 9: Template escape bypasses
**What goes wrong:** `|safe`, `Markup()`, or `{% autoescape false %}` silently disables D-10.
**How to avoid:** a fast test asserts the template source contains none of `"|safe"`, `"Markup"`, `"autoescape"`. Inject `<script>alert(1)</script>"'&` into display name, every item title, delivery content, labels, and the Phase 10 header/footer args. Assert no raw `<script` anywhere in the HTML part and `&lt;script&gt;` present.

### Pitfall 10: Tests comparing copy against escaped HTML
**What goes wrong:** MarkupSafe renders `'` → `&#39;` and `"` → `&#34;` (probe), so `assert "You're …" in html_part` fails.
**How to avoid:** footer copy without apostrophes, or compare `html.unescape(part)` for copy while checking escaping on the raw part.

### Pitfall 11: `set_content` appends a trailing newline
**What goes wrong:** `get_content()` returns `render + "\n"` (probe: `'Order shipped.\n- <script> x2\n'`). An equality assertion "text part == `_render_body` output" fails.
**How to avoid:** compare `.rstrip("\n")`, or assert `startswith(render)`.

### Pitfall 12: `sendmail` with non-ASCII str raises
**What goes wrong:** `smtplib.sendmail` does `msg = _fix_eols(msg).encode('ascii')` for `str` (stdlib smtplib.py:863-864). The docs state the same: "msg may be a string containing characters in the ASCII range".
**How to avoid:** explicit `cte="quoted-printable"` for both text parts. Default-policy headers are RFC 2047-encoded (probe: `as_string()` is pure ASCII with non-ASCII subject, name, and body). Assert `msg.as_string().isascii()` in a fast test.

### Pitfall 13: Ruff E501 inside the HTML template string
**What goes wrong:** inline-CSS lines easily exceed 100 chars; ruff flags long lines inside triple-quoted strings (probe: `E501 Line too long (133 > 100)`).
**How to avoid:** wrap template lines at ≤100 chars (HTML is whitespace-tolerant), or store the template as a git-tracked file next to the module and load it with `jinja2.FileSystemLoader`. Git-tracked files are packaged automatically.

### Pitfall 14: Gmail clips HTML over ~102 KB
**What goes wrong:** the footer, including the opt-out notice, can be hidden behind "[Message clipped]". The pathological case is 64 items (`MAX_ITEMS = 64`, checkout.py:57) × 200-char titles (`TITLE_MAX = 200`, catalog.py:38) plus delivery content (`DELIVERY_MAX = 4000` per product, catalog.py:898), all inflated by escaping.
**How to avoid:** keep per-cell inline CSS short and render repeated styles once per row, not per cell. The text part always carries the full footer; Gmail counts only the HTML. [CITED: vendor docs]

### Pitfall 15: The model and production drift on gating
**What goes wrong:** production gates merchant-only while `harness/email.py` gates all channels, and `test_p0_10` keeps proving the old behavior.
**How to avoid:** apply the minimal harness/test update described under Contract-test exposure.

### Pitfall 16: Frozen single-binary hosts missing stdlib modules
**What goes wrong:** the extension loads at runtime from disk, so any stdlib module the frozen host never bundled is absent. Precedent: `html.parser` was missing (`_vendored.py` docstring; package_release.py:116-120).
**How to avoid:** add a release-smoke item that sends a test notification on the frozen build (Open Question 2).

## Code Examples

Verified against CPython 3.12.13 behavior (probes in this session) and official docs (docs.python.org/3.12).

### 1. `_build_message` core (pure; no I/O)
```python
# services/email.py — absolute imports resolve to the stdlib `email` package even though
# this module is itself named email.py (PEP 328; verified: the host's stdlib email.mime
# imports keep working with infinitemarkets.services.email loaded).
import re
import unicodedata
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

LOGO_CID = "logo@infinitemarkets"               # D-05: Content-ID <logo@infinitemarkets>
_HEX6 = re.compile(r"#[0-9a-fA-F]{6}")           # ALWAYS .fullmatch (Pitfall 8)
_STRIP = frozenset({"Cc", "Cf", "Zl", "Zp"})     # controls, bidi/format, line/para seps

def _header_safe(text: str | None, *, limit: int) -> str:
    cleaned = "".join(" " if unicodedata.category(ch) in _STRIP else ch for ch in text or "")
    return " ".join(cleaned.split())[:limit].strip()

def _build_message(*, subject: str, text: str, view: "_EmailView", from_addr: str,
                   to_addr: str, with_html: bool = True,
                   logo: tuple[bytes, str] | None = None) -> EmailMessage:
    from lnbits.helpers import is_valid_email_address   # same rule as the host helper
    if not (is_valid_email_address(from_addr) and is_valid_email_address(to_addr)):
        raise ValueError("invalid sender or recipient")   # never echo the address
    if logo is not None and (not logo[0] or logo[1] not in ("png", "jpeg")):
        logo = None                                       # D-06: never fail over branding
    msg = EmailMessage()
    msg["Subject"] = _header_safe(subject, limit=150)
    name = _header_safe(view.display_name, limit=64)
    msg["From"] = Address(display_name=name, addr_spec=from_addr) if name else from_addr
    msg["To"] = to_addr
    msg["Date"] = formatdate(localtime=True)              # never usegmt=True (RFC 5322 §4)
    msg["Message-ID"] = make_msgid(domain=from_addr.rpartition("@")[2])
    msg["Auto-Submitted"] = "auto-generated"              # RFC 3834 §5
    msg.set_content(text, subtype="plain", charset="utf-8", cte="quoted-printable")
    if with_html:                                          # kill switch: one branch in caller
        html = _render_html(view, has_logo=logo is not None)
        msg.add_alternative(html, subtype="html", charset="utf-8", cte="quoted-printable")
        if logo is not None:
            msg.get_payload()[1].add_related(
                logo[0], maintype="image", subtype=logo[1],
                cid=f"<{LOGO_CID}>", disposition="inline",
            )
    return msg
```
Verified tree (probe): `['multipart/alternative', 'text/plain', 'multipart/related', 'text/html', 'image/png']` with a logo, and `['multipart/alternative', 'text/plain', 'text/html']` without. The image part has `Content-ID: <logo@infinitemarkets>`, CTE base64, disposition inline. The HTML references `src="cid:logo@infinitemarkets"` (no angle brackets — Python docs example "peel the <> off the msgid for use in the html").

### 2. `_smtp_send` (mirrors host; adds only `timeout=`)
```python
import asyncio
import smtplib

async def _smtp_send(msg: EmailMessage, *, to: str, timeout: float) -> bool:
    """Thin transport mirroring lnbits.core.services.notifications.send_email (e336fe1).
    Never logs; any exception propagates to worker_tick (→ bounded retry)."""
    from lnbits.settings import settings as host_settings
    server = host_settings.lnbits_email_notifications_server
    port = host_settings.lnbits_email_notifications_port
    from_addr = host_settings.lnbits_email_notifications_email
    username = host_settings.lnbits_email_notifications_username or from_addr
    password = host_settings.lnbits_email_notifications_password
    wire = msg.as_string()   # ASCII: QP bodies + RFC 2047 headers (sendmail ascii-encodes str)

    def _send() -> bool:
        with smtplib.SMTP(server, port, timeout=timeout) as smtp:   # bounds the thread
            smtp.starttls()               # host parity: no context → unverified (OQ 1)
            smtp.login(username, password)
            smtp.sendmail(from_addr, [to], wire)
        return True

    return await asyncio.to_thread(_send)
```

### 3. Worker wiring (replaces email.py:420-439)
```python
        preview = _preview_enc(row, subject, preview_text, settings)   # key stays "body"
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return "lost_claim"
        budget = min(30, remaining)
        try:
            msg = _build_message(
                subject=subject, text=text, view=view,
                from_addr=host_settings.lnbits_email_notifications_email,
                to_addr=recipient, with_html=settings.email_html,
            )
            sent = await asyncio.wait_for(
                _smtp_send(msg, to=recipient, timeout=budget), timeout=budget,
            )
        except Exception:
            sent = False
```

### 4. Suppression (D-16/D-17), replacing email.py:156-160
```python
    # D-17: notify_events gates merchant ALERTS only. Orderless merchant rows are
    # test sends (enqueue_test_send) and are never event-gated (D-16).
    if row["channel"] == "merchant" and row["order_id"]:
        events = json.loads(merchant["notify_events"]) if merchant["notify_events"] else {}
        if row["event_type"] in events and not events[row["event_type"]]:
            return "event-disabled"
    if row["channel"] == "customer":
        if order is None or not order["email_opt_in"]:
            return "consent-revoked"
    return None
```

### 5. Jinja environment + template skeleton (sketch; wrap lines ≤100 chars)
```python
from jinja2 import Environment, StrictUndefined

_JINJA = Environment(autoescape=True, undefined=StrictUndefined,
                     trim_blocks=True, lstrip_blocks=True)
# Literal font stack (D-07) lives in the template, never interpolated.
_HTML = _JINJA.from_string("""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>{{ subject }}</title></head>
<body style="margin:0;padding:0;background:#f4f4f5;">
<span style="display:none;max-height:0;overflow:hidden;mso-hide:all;">{{ preheader }}</span>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
<td align="center" style="padding:24px 12px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0"
 style="width:100%;max-width:600px;background:#ffffff;border-top:3px solid {{ accent }};
 font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#1f2328;">
<tr><td style="padding:20px 24px;">
{% if has_logo %}<img src="cid:logo@infinitemarkets" height="40" alt="{{ display_name }}"
 style="display:block;height:40px;border:0;">
{% else %}<div style="font-size:20px;font-weight:600;">{{ display_name }}</div>{% endif %}
</td></tr>
...  title/state · items (title, ×qty, line total, backordered badge) · totals ·
...  delivery <div style="white-space:pre-wrap;">{{ entry.content }}</div> (customer+confirmed)
{% if cta_url %}<tr><td style="padding:8px 24px 24px;"><table role="presentation"><tr>
<td style="background:{{ accent }};border-radius:6px;"><a href="{{ cta_url }}"
 style="display:inline-block;padding:12px 20px;color:{{ on_accent }};font-weight:600;
 text-decoration:none;">{{ cta_label }}</a></td></tr></table></td></tr>{% endif %}
...  footer lines (+ optional link) · Phase 10 header_text/footer_text slots
</table></td></tr></table></body></html>""")
```
Probe-verified behavior: `{{ }}` escapes `<script>` → `&lt;script&gt;`, `"` → `&#34;`, and `'` → `&#39;` in text and attributes. A missing variable raises `UndefinedError` (inside the send `try` → bounded retry). `|safe` bypasses escaping and is banned.

### 6. Test helpers (runtime fixture + fast parse)
```python
# tests/runtime/conftest.py (or a local fixture)
@pytest.fixture
def smtp_capture(monkeypatch):
    import importlib
    from lnbits.settings import settings as host_settings
    svc = importlib.import_module("infinitemarkets.services.email")
    monkeypatch.setattr(type(host_settings), "is_email_notifications_configured",
                        lambda self: True)
    monkeypatch.setattr(host_settings, "lnbits_email_notifications_email", "shop@example.com")
    sent: list[dict] = []
    async def fake(msg, *, to, timeout):
        sent.append({"to": to, "msg": msg})
        return True
    monkeypatch.setattr(svc, "_smtp_send", fake)
    return sent

def text_part(msg):  return msg.get_body(preferencelist=("plain",)).get_content()
def html_part(msg):  return msg.get_body(preferencelist=("html",)).get_content()
# Round-trip as a receiver sees it (probe-verified):
#   email.message_from_string(msg.as_string(), policy=email.policy.default)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| compat32 `MIMEMultipart`/`MIMEText` (host helper) | `EmailMessage` + `email.policy.default` content manager | Python 3.6 (contentmanager added in 3.4 provisional) | `add_alternative`/`add_related`, header objects, CR/LF refusal at assignment |
| `starttls(keyfile=, certfile=)` | `starttls(context=…)` only | Python 3.12 removed keyfile/certfile | No-context call = unverified context (smtplib.py:777-778) |
| compat32 header serialization accepted embedded newlines | Generators refuse embedded headers (`HeaderParseError`/`HeaderWriteError`) | security fix in 3.12.x (probe on 3.12.13 confirms refusal) | Today's host path already fails on CR/LF names; the new path fails at assignment unless sanitized |
| `email.utils.parseaddr` lenient | `strict=True` default | Python 3.12.6 | Not used by this phase; noted for any address parsing |
| One-click unsubscribe "nice to have" | Required for bulk/marketing by Gmail/Yahoo; **transactional exempt** | 2024 sender requirements | Supports D-21 deferral (Gmail FAQ: "Transactional messages are excluded from this requirement") |

**Deprecated/outdated:**
- `formatdate(usegmt=True)` for email: emits the obsolete `GMT` zone, which RFC 5322 §4 says "MUST NOT be generated". Use the numeric offset.
- `smtpd` stdlib module: removed in 3.12 (absent from the venv); `aiosmtpd` is not installed. Test the transport with a fake `smtplib.SMTP` class, not a local server.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Frozen (Nuitka) LNbits builds bundle `email.policy`/`email.headerregistry`/`email.contentmanager`, because host-bundled `email.message` statically imports `email.policy` inside `EmailMessage.__init__` | Runtime State Inventory, Pitfall 16 | On a frozen host every send raises `ModuleNotFoundError` → bounded retries → `failed`; email dead on that distribution |
| A2 | Outlook desktop (Word engine) honors the `width="600"` table attribute while ignoring CSS `max-width` (caniemail lists max-width unsupported/partial for Outlook Windows) | Code Example 5 | Cosmetic: email renders full-width in Outlook desktop |
| A3 | Spam filters may penalize large text/HTML divergence (e.g., SpamAssassin multipart-alternative difference rules) | Pattern 6 / D-05 | Minor deliverability score; keep both parts semantically aligned |
| A4 | Display names containing `@` are a spoofing/phishing signal worth stripping | Pitfall 6 (optional hardening) | Low; optional `.replace("@", "")` on the display name |
| A5 | Production hosts run in UTC, so `formatdate(localtime=True)` yields RFC 5322's preferred `+0000` | Code Example 1 | None functionally; on non-UTC hosts the header reveals the server's offset (not buyer PII) |
| A6 | Mail clients auto-link URL-looking text in delivery content regardless of our markup | D-10 notes | None for us (we never emit `<a>` for merchant text); client behavior is out of our control |

## Open Questions

1. **STARTTLS certificate verification [NEEDS DECISION — owner].**
   - What we know: mirroring the host (D-03) means `starttls()` with no context, which on 3.12 is `CERT_NONE`, no hostname check (verified in stdlib source). An on-path attacker between the LNbits server and its relay could read magic sign-in links (account takeover) and order bearer links. This is a **pre-existing** property of today's host path. ASVS 9.2.1 (trusted TLS certificates for server connections) is Level 2; the project runs Level 1.
   - What's unclear: whether operators rely on relays with self-signed or private-CA certificates, or on frozen/minimal images without a CA bundle.
   - Recommendation: Phase 9 mirrors the host exactly, with an explicit code comment and a deferred hardening item. If the owner wants verification now, it is a one-argument change: `starttls(context=ssl.create_default_context())`.
2. **Frozen-build stdlib coverage (A1).**
   - What we know: the project has evidence of missing lazily-used stdlib modules on the Nuitka single-file build, and back-fills `html.parser`/`_markupbase` only.
   - What's unclear: whether `email.policy` and its imports are present there.
   - Recommendation: add a release smoke item (send-test on the frozen binary). If it fails, extend `STDLIB_MODULES`/`STDLIB_FILES` with `email/policy.py`, `email/headerregistry.py`, `email/contentmanager.py`, `email/_header_value_parser.py`, `email/_encoded_words.py`. That is Phase 11 or release work.
3. **Preview key naming (D-22 wording).**
   - What we know: actual shape `{"subject","body"}` (email.py:224-227; merchant.py:867-871).
   - Recommendation: keep `body`. Treat D-22's "text" as a paraphrase; do not rename.
4. **"Order order confirmed." text wart.**
   - What we know: `_render_body` emits `f"Order {label}."` with labels that already begin with "order".
   - What's unclear: D-05 says the render is "retained".
   - Recommendation: retain in Phase 9 (no test depends on the first line). Raise a one-line fix (`f"{label.capitalize()}."`) as an owner-approved micro-change if desired.
5. **Kill switch documentation.**
   - Recommendation: include `INFINITEMARKETS_EMAIL_HTML` (default `true`) now as a one-argument branch, with no `registry.SETTINGS` entry. Add the §12 row in Phase 11 alongside the §8.8 rewrite.
6. **Test-send CTA.**
   - Recommendation: render a styled non-link "Order status button (sample)" placeholder so merchants see the accent on the button without an invented URL. Omitting it is also acceptable.
7. **Magic-link token occurrences.**
   - What we know: with an HTML part, the token appears once in the text part and once in the HTML `href`.
   - Recommendation: update `test_magic_link_send_renders_fragment_and_wipes` to assert exactly one occurrence **per part**, and none in the subject or any header.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| CPython | everything | ✓ | 3.12.13 (`.venv`, pin `>=3.12,<3.13`) | — |
| uv | `make verify*` | ✓ | 0.11.6 | — |
| pytest / pytest-asyncio | tests | ✓ | 9.1.1 / 1.4.0 | — |
| ruff | lint gate | ✓ | 0.16.8 (`ruff~=0.14` satisfied) | — |
| Jinja2 / MarkupSafe | HTML template | ✓ (host-provided) | 3.1.6 / 3.0.3 | `html.escape` string building |
| Pinned LNbits host checkout | runtime tests | ✓ | `e336fe14b841d6f0c940e75b3d343e3ab5cf8433` | — |
| PostgreSQL server | PG profile + PG-only drills (`test_concurrent_email_claims_do_not_overlap`, `test_email_rate_limit_is_atomic`) | ✗ locally (`pg_isready`: no response) | client 17 installed | SQLite profile locally (`LNBITS_DATABASE_URL` unset); PG covered by the CI matrix |
| Local SMTP server (`smtpd`/`aiosmtpd`) | — | ✗ (`smtpd` removed in 3.12; `aiosmtpd` not installed) | — | Fake `smtplib.SMTP` class in fast tests (recommended anyway) |
| node | `node --check` (only if admin JS changes) | ✓ | v25.8.2 | — |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** PostgreSQL (CI), local SMTP server (fake class).

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1 + pytest-asyncio 1.4.0 (`asyncio_mode = "auto"`) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (markers `fast`, `runtime`, `db`, `protocol`, `host`, `sdk`); `tests/conftest.py` pins `LNBITS_DATA_FOLDER` to `.cache/qual-data`; `tests/runtime/conftest.py` boots the host per module |
| Quick run command | `uv run pytest tests/runtime/test_email_render.py -q` (new, no host boot; expect a few seconds) |
| Fast gate | `make verify-fast` (= `uv run pytest -m fast -q`; 320 tests today, ~50 s per AGENTS.md) |
| Targeted runtime | `uv run pytest tests/runtime/test_email_queue.py tests/runtime/test_email_signin.py tests/runtime/test_financial_review.py -q` |
| Full suite command | `make verify` (= `uv run pytest -q`), plus `uv run ruff check .` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| EMAIL-01 | Tree = alternative{plain, html}; with synthetic logo = alternative{plain, related{html, image}} with `Content-ID: <logo@infinitemarkets>`; unusable logo → no related part and no `cid:` | unit (fast) | `uv run pytest tests/runtime/test_email_render.py -k tree -q` | ❌ Wave 0 |
| EMAIL-01 | `_smtp_send` call order SMTP(server, port, timeout)→starttls→login(username or from)→sendmail(from, [to], ASCII wire); exceptions propagate; no `set_debuglevel` in source | unit (fast, fake SMTP) | `… -k smtp_send -q` | ❌ Wave 0 |
| EMAIL-01 | Worker: fake `_smtp_send` True → `sent` + wipe; False/raise → `pending` + backoff; exhaustion → `failed`; expired claim never calls `_smtp_send` | runtime (host boot) | `uv run pytest tests/runtime/test_email_queue.py -q` | ✅ migrate |
| EMAIL-02 | HTML has wordmark/logo, accent rule, title + state, item rows with line totals + backordered badge, subtotal/shipping/total, CTA iff live link | unit (fast) | `… -k sections -q` | ❌ Wave 0 |
| EMAIL-03 | `<script>"'&` payload in name/title/delivery/labels/header/footer args → escaped; template has no `|safe`/`Markup`/`autoescape`; no `src="http`, `url(`, `<link`, `<script` | unit (fast) | `… -k escap -q` | ❌ Wave 0 |
| EMAIL-03 | Delivery content only in customer `confirmed` (both parts); merchant `confirmed` row lacks it; subject unchanged | runtime | `uv run pytest tests/runtime/test_email_queue.py -k "hard01 or delivery" -q` | ✅ migrate + add |
| EMAIL-08 | notify_events `{"shipped": false}`: customer shipped row **sent**; merchant shipped row suppressed `event-disabled`; consent revocation still `consent-revoked` | runtime | `… -k "notify_events or consent" -q` | ❌ add (consent ✅) |
| EMAIL-08 | Model parity: event gate merchant-only; customer row not gated | qualification (fast) | `uv run pytest tests/qualification/test_p0_10_smtp_boundary.py -q` | ✅ update case (2) |
| EMAIL-09 | Footers in BOTH parts: customer opt-in + opt-out link (no-link variant when token dead); account sign-in copy; merchant/test neutral line; preview carries redacted footer link | unit (fast) + runtime (preview) | `… -k footer -q` | ❌ Wave 0 |
| EMAIL-10 | `notify_events {"order_received": false}` + POST `/notifications/test` → `sent`; HTML has sample marker + sample items; no real order data | runtime | `uv run pytest tests/runtime/test_email_queue.py -k orderless -q` | ✅ extend |
| EMAIL-11 | Date parses; Message-ID `@<sender domain>>`, no hostname; `Auto-Submitted: auto-generated`; From display decoded == sanitized name; CR/LF/NUL/ESC/U+2028/bidi stripped; empty → bare address; no Reply-To / List-Unsubscribe | unit (fast) | `… -k header -q` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/runtime/test_email_render.py -q` + `uv run ruff check infinitemarkets tests harness`
- **Per wave merge:** `make verify-fast` + the targeted runtime command above
- **Phase gate:** `make verify` (full) green before `/gsd-verify-work`; CI runs sqlite + postgres × amd64/arm

### Wave 0 Gaps
- [ ] `tests/runtime/test_email_render.py`: new, `pytestmark = [pytest.mark.runtime, pytest.mark.fast]`, no host boot. Covers EMAIL-01/02/03/09/11 unit behavior. Import lazily via `importlib.import_module("infinitemarkets.services.email")` (catalog_events pattern) or at module top (crypto_keystore precedent).
- [ ] `tests/runtime/conftest.py`: fail-closed autouse `smtplib.SMTP` guard; optional shared `smtp_capture` fixture (Code Example 6).
- [ ] Migrate the 8 host-`send_email` patch sites listed in the test inventory, plus the hermeticity fix for `test_worker_errors_do_not_log_private_exception_text`, in the same plan as the transport swap.
- [ ] `harness/email.py` event gate merchant-only + `test_p0_10` case (2) update (D-23).
- [ ] New runtime cases: EMAIL-08 scenario, EMAIL-10 scenario, customer-preview redaction, merchant-`confirmed` no-delivery.

## Security Domain

`security_enforcement: true`, ASVS level 1, block on high (`.planning/config.json`).

### Applicable ASVS Categories (4.0.3)

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no (magic-link minting unchanged; link stays fragment-only) | — |
| V3 Session Management | no | — |
| V4 Access Control | no (test sends still restricted to configured `notify_emails`, merchant.py:898-903) | — |
| V5 Validation, Sanitization and Encoding | **yes** | 5.2.3 (L1): "sanitizes user input before passing to mail systems to protect against SMTP or IMAP injection" → `_header_safe` + `Address`. 5.3.1 (L1): context-relevant encoding (HTML, attributes, SMTP) → autoescape + hex `fullmatch` for CSS. 5.3.3 (L1): "context-aware, preferably automated … output escaping" → Jinja2 autoescape |
| V6 Stored Cryptography | no new crypto (existing AEAD for recipient/preview reused) | `crypto.encrypt/decrypt` unchanged |
| V7 Error Handling and Logging | **yes** | 7.1.1/7.1.2 (L1): never log credentials or sensitive data → no `str(exc)`, no `set_debuglevel`, class names only |
| V8 Data Protection | yes | Bearer tokens only in URL fragments; preview redaction includes the footer link |
| V9 Communications | partial | 9.2.1 (trusted certs for server connections) is **L2** → unverified STARTTLS is a documented residual (Open Question 1) |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SMTP header injection via merchant `display_name` (unvalidated, merchant.py:418-419) | Tampering | Strip `Cc/Cf/Zl/Zp`, cap length, encode via `Address`; default policy refuses CR/LF (probe) |
| Stored XSS in HTML email via item titles/display name/delivery content | Tampering / Elevation | Jinja2 autoescape; banned `|safe`/`Markup`; payload tests per field |
| CSS-context injection via accent → remote fetch (tracking) | Information disclosure | `re.fullmatch(r"#[0-9a-fA-F]{6}")` else default; no other CSS interpolation |
| Remote-resource tracking (pixels, remote `<img>`, fonts) | Information disclosure | CID-only images; template literal styles; test asserts no `http` in `src`/`url(` |
| Bearer-token leakage (path/query/subject/headers/logs/preview) | Information disclosure / Spoofing | Fragment URLs only (`…/order#token`, `…/auth/email?shop=…#token`); preview placeholders incl. footer; no tokens in headers |
| PII/credential leakage in logs | Information disclosure | `_smtp_send` never logs; worker logs `type(exc).__name__` only; host's `{e!s}` warning (notifications.py:239) is no longer on the path |
| Server hostname leak via `Message-ID` | Information disclosure | `make_msgid(domain=<sender domain>)` |
| Display-name brand spoofing (bidi overrides, look-alike names) | Spoofing | Strip `Cf` (bidi/zero-width); optional `@` removal (A4); sending address is always the host address (DMARC unaffected) |
| Auto-reply/vacation loops | Denial of service | `Auto-Submitted: auto-generated` (RFC 3834 §2/§5.2) |
| Hung relay exhausting worker threads | Denial of service | `smtplib.SMTP(timeout=budget)`; existing `wait_for` |
| Consent bypass (customer mail after opt-out) | Repudiation / Privacy | Customer rows gate on `email_opt_in` re-read under the order lock at send time; opt-out also erases `public_token_enc` (views_public_api.py:424-428) |
| STARTTLS MITM on the server→relay hop | Information disclosure | Residual (host parity); owner decision OQ1 |

## Sources

### Primary (HIGH confidence)
- **Codebase, read this session:**
  - `infinitemarkets/services/email.py` (full); `services/merchant.py:800-969`; `services/orders.py:36-118, 430-472, 770-874, 1130-1189`; `services/themes.py:1-160, 240-329, 505-574, 740-795`; `services/nostr_auth.py:640-719, 1095-1149`; `services/checkout.py:55-58, 625-691`; `services/catalog.py:36-41, 896-899`; `services/nip89.py:170-199`; `services/tasks.py:24-33, 160-219`; `settings.py` (full); `views_public_api.py:411-436, 735-764`; `migrations.py:36-75, 462-531, 665-729`; `__init__.py` (full).
  - `harness/email.py` (full); `harness/registry.py:310-331`; `tests/qualification/test_p0_09*`, `test_p0_10*`, `test_p0_14*` (full); `tests/runtime/test_email_queue.py` (full); `test_email_signin.py:380-543, 1280-1314`; `test_financial_review.py:370-419`; `test_order_saga.py:270-309`; `test_admin_ui.py:515-544`; `tests/runtime/conftest.py` (full).
  - `.cache/lnbits/lnbits/core/services/notifications.py:1-30, 175-249`; `.cache/lnbits/lnbits/settings.py:500-549`; `.cache/lnbits/lnbits/helpers.py:159-164`; `docs/technical-specification.md` §4.18, §8.8, §12, §21; `tools/package_release.py:1-160`; `infinitemarkets/_vendored.py` (full); `pyproject.toml`; `uv.lock:689-690, 903-904`.
- **CPython 3.12.13 stdlib source on disk:** `smtplib.py:229-275, 752-790, 863-864, 912-975`; `ssl.py:732-735, 791`; `email/utils.py:290-309`; `email/policy.py:5-11`; `email/message.py:187, 984, 991`.
- **Live probes on `.venv/bin/python` 3.12.13:** MIME tree, CTE/ASCII wire, header injection behaviors, `getfqdn()` 5.0 s, `wait_for`+`to_thread`, regex `$`, Jinja2 3.1.6 autoescape/StrictUndefined/`|safe`, `get_body` extraction + round-trip parse, preset contrast ratios, host-free import of `infinitemarkets.services.email` (1.42 s), ruff E501 in strings, `pytest -m fast --collect-only` (320/1108).

### Secondary (MEDIUM confidence)
The research-plan seam rates `webfetch` LOW. These are official docs, and each claim was independently confirmed by the probes or stdlib source above.
- docs.python.org/3.12: `email.examples` (alternative + related + CID recipe), `email.utils` (`make_msgid` domain default, `formatdate`), `smtplib` (timeout, `sendmail` ASCII rule, `send_message`, 3.12 keyfile/certfile removal), `email.contentmanager` (`set_content` cte/cid/disposition), `email.headerregistry` (`Address`), `asyncio-task` (`wait_for`, `to_thread`).
- RFC 3834 §2, §5 (rfc-editor.org text): Auto-Submitted values/semantics.
- RFC 5322 §3.3, §3.5, §4 (rfc-editor.org text): numeric zones, 998/78 line limits, obsolete syntax MUST NOT be generated.
- OWASP ASVS 4.0.3 V5/V7/V9 markdown (github.com/OWASP/ASVS, tag v4.0.3): 5.2.3, 5.3.1, 5.3.3, 7.1.1, 7.1.2, 9.1.1, 9.2.1 wording and levels.
- Gmail Help, Email sender guidelines FAQ (support.google.com/mail/answer/14229414): transactional mail excluded from one-click unsubscribe.

### Tertiary (LOW confidence)
- caniemail.com `css-max-width` (Outlook Windows partial/unsupported) — A2.
- Vendor docs (AWeber, Mailchimp, SendGrid, Blueshift) on Gmail's ~102 KB clipping — Pitfall 14.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — stdlib on the pinned interpreter, verified by source and probes; Jinja2/MarkupSafe versions read from uv.lock.
- Architecture: HIGH — every touched function, call site, query, row shape, and test seam read this session.
- Pitfalls: HIGH for stdlib/test-migration items (reproduced by probe or read); MEDIUM for email-client rendering (Gmail clipping, Outlook width); LOW for A1 (frozen-build stdlib coverage).

**Research date:** 2026-10-17
**Valid until:** 2026-11-16 (30 days; stdlib + pinned host are stable; re-check only if the host pin or Python minor changes)

**Suggested decomposition (coarse, tracer-first; sequential because every plan edits `services/email.py` and the project uses worktrees):**
1. **09-01 Tracer — extension-owned boundary + gating:**
   - `_smtp_send`; `_build_message` with the full header set, existing text, and a minimal HTML shell; worker wiring inside `try`; `_header_safe` in `_subject`/From.
   - D-16/D-17 suppression; harness + `test_p0_10` update.
   - Migrate **all** test patch sites, plus the SMTP guard; fast tests for tree/headers/transport.
2. **09-02 Branded template + channels:**
   - Jinja template sections (D-07/D-08); accent/on-accent; escaping (D-10); delivery double gate (D-11); CTA (D-12).
   - Footers in both parts (D-14); account shell (D-15); test sample content (D-16 render side); preview footer redaction (D-22); Phase 10 seams; kill switch.
   - Widened items query; fast escaping/sections/footer tests; runtime EMAIL-08/10 scenarios.
