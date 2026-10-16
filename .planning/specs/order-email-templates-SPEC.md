# SPEC: Branded Order Email Templates

**Status:** Draft — unassigned to a milestone (candidate: v1.1 or v1.2)
**Authored:** 2026-10-15, branch `spec/order-email-templates`
**Depends on / interacts with:** v1.1 media milestone (Blossom uploads) — see §4.3

---

## 1. Summary

Order emails are currently plain-text bodies rendered by
`services/email.py::_render_body` and sent through the host's
`send_email`, which attaches a single `MIMEText(message, "plain")` part —
there is no HTML or attachment support at the SMTP boundary.

This spec proposes: (a) a branded multipart/alternative email (text +
HTML) rendered from the existing send-time pipeline, and (b) structured
merchant customization — logo, header/footer text, accent color —
editable in the existing admin Notifications section.

## 2. Goals / Non-goals

**Goals**
- `multipart/alternative` send: `text/plain` (existing render, retained)
  + `text/html` (new template) on every order-event email.
- Merchant logo embedded via **CID attachment** (`multipart/related`) —
  no remote `<img>` fetches, no open-tracking vector.
- Structured customization only: logo, header line, footer line, accent
  color. No free-form HTML/CSS (matches the theme-token posture).
- `List-Unsubscribe` header + footer opt-out link on the customer
  channel, backed by the existing token-gated opt-out.
- Test sends and magic-link emails render through the same shell so
  merchants preview branding.

**Non-goals**
- Per-event custom copy / merchant-authored templates.
- Marketing/bulk email; this stays strictly transactional.
- Upstream changes to LNbits `send_email` (see §3).
- RFC 8058 one-click unsubscribe (see §6.2 — incompatible with the
  fragment-token posture).

## 3. Hard constraint: host `send_email` is plain-text only

`lnbits/core/services/notifications.py::send_email` builds
`MIMEMultipart()` and attaches exactly one `MIMEText(message, "plain")`.
The host checkout is pinned (e336fe1); extending it means diverging from
the pin or upstreaming.

**Decision:** implement the SMTP send inside the extension
(`services/email.py`). Two functions, split for testability:

- `_build_message(...) -> EmailMessage` — pure construction: MIME tree,
  headers, CID assembly, HTML render. Unit-testable with no network.
- `_smtp_send(msg)` — thin transport reusing the same host credentials
  (`host_settings.lnbits_email_notifications_*`), the same
  `asyncio.to_thread` + `starttls` + `sendmail` mechanics, and the same
  `asyncio.wait_for(min(30, remaining))` deadline discipline already in
  `worker_tick._send`. ~20 lines of stdlib `smtplib`; no new
  dependencies.

**Headers added** (smtplib adds none of these; the host send doesn't
either):

- `Date` + `Message-ID` (`email.utils.formatdate` / `make_msgid`) —
  baseline deliverability.
- `Auto-Submitted: auto-generated` — suppresses vacation-reply loops.
- `From: "{display_name}" <host-notifications-addr>` — display name is
  merchant-controlled, so it must be encoded via
  `email.headerregistry`/`formataddr` with CR/LF stripped. Fallback to
  the bare address if the name is empty/invalid.
- `Reply-To: notify_emails[0]` (optional but recommended) — customer
  replies currently dead-end at the host notifications address.
- `List-Unsubscribe` on the customer channel only (§4.4).

## 4. Design

### 4.1 MIME structure

```
multipart/alternative
├── text/plain                        # existing _render_body output
└── multipart/related                 # only when a logo is configured
    ├── text/html                     # new _render_html output
    └── image/png|jpeg  (Content-ID: <logo@infinitemarkets>)
```

When no logo is configured, the `related` wrapper collapses to a bare
`text/html` part. Sent rows still wipe `recipient_enc`/`payload_enc`
exactly as today; logo bytes are loaded fresh at send time and never
persisted on the queue row.

### 4.2 HTML template rules

- Table-based single-column layout, 600px max width — required for
  Outlook-family clients.
- **Inline CSS only.** No `<style>` blocks, no classes carrying layout
  (Gmail/Outlook strip inconsistently), no webfonts.
- System font stack: `-apple-system, "Segoe UI", Roboto, Helvetica, Arial`.
- Single light theme (no dark-mode media queries — inconsistent client
  support).
- Hidden preheader span ("Order confirmed — {display_name}") as the
  first element — inbox preview text costs one line.
- Both parts `utf-8`.
- **Every interpolated value passes `html.escape` (incl. `quote=True`
  for attribute contexts like the status-link `href`)** — display name,
  item titles, quantities, totals, delivery content, custom
  header/footer text. This is a hard contract: item titles are
  merchant-controlled, delivery content is merchant-authored, and both
  land in a security surface (email). Add a qualification test
  asserting a stored `<script>`-bearing title renders escaped.
- Digital-delivery content renders inside a `pre-wrap` block after
  escaping — it's free text (codes/links), not markup.
- Item table uses `order_items.unit_price_minor`/`line_total_sat`/
  `currency_decimals` for real line totals (today's text only shows
  title × qty) and a "backordered" badge when `backordered_qty > 0`.
- Sections:
  1. Header band — logo (`height="40"`, `alt` = escaped display name)
     or display-name wordmark when no logo; accent color as band
     background or 3px top rule.
  2. Event title + state label.
  3. Item table: title × quantity; totals block (`total_sat` formatted).
  4. Digital-delivery block — **customer channel + `confirmed` only**,
     same gate as the text render.
  5. Status-link CTA button (only while the token copy is live —
     reuse `_status_link`'s expiry/AEAD checks).
  6. Footer: merchant name + mandatory transactional notice — customer
     channel gets "you opted in to order emails" plus an opt-out line
     pointing at the order page; account channel gets "you requested a
     sign-in link"; merchant/test channels get a neutral "transactional
     notification" line. The mandatory line is fixed copy —
     `email_footer_text` *supplements* it, never replaces it. Custom
     header/footer text is plain text: escaped, no autolinking.
     The text/plain footer carries the same mandatory lines.

### 4.3 Merchant customization fields

New nullable columns on `merchants` (new migration, next `m0xx`):

| Column | Type | Validation |
|---|---|---|
| `email_logo_path` | TEXT | namespaced media filename, written only by the upload route |
| `email_header_text` | TEXT | ≤120 chars, control chars stripped, single line |
| `email_footer_text` | TEXT | ≤240 chars |
| `email_accent` | TEXT | `#[0-9a-fA-F]{6}` or NULL → falls back to `theme` accent |

**Logo storage — single-slot semantics** (resolves open question 3):
one logo per merchant, `logo-<sha256>.<ext>` in the existing
merchant-namespaced media dir, bounded multipart upload, magic-byte
sniff (PNG/JPEG/WebP only), cap ≤256 KB. Re-upload atomically replaces
and deletes the previous file; clearing the field deletes it too. No
accounting path needed — the file nominally shares the media dir's
400 MB budget, which is immaterial at 256 KB. Logo uploads are *not*
gated on URLs already in the catalog (unlike migration media) — it's a
dedicated kind.

**v1.1 interaction:** the in-flight media milestone adds Blossom-hosted
product media. Email logos stay **local-bytes-only** for CID embedding:
remote `<img src>` (Blossom or `/images` URL) is rejected because the
buyer's mail client fetch leaks open-time + IP — a tracking vector the
consent model doesn't cover. If v1.1 lands a general local-media
library first, the logo picker may reuse it; the contract is "bytes
available locally at send time," not a storage location.

**Send-time fallback:** unreadable/missing logo → render without the
`related` wrapper; never fail the send over branding.

### 4.4 Unsubscribe

- Customer-channel footer link + `List-Unsubscribe` header both point at
  the existing status link (`{public_base_url}/infinitemarkets/order#token`),
  which already exposes the opt-out button (`public_order.js` →
  `POST /order-email-opt-out`). **No new public page needed.**
- Fragments are legal in the RFC 2369 URI but some clients strip them —
  acceptable degradation; the footer link is the primary path.
- No RFC 8058 `List-Unsubscribe-Post` one-click: it requires the token
  in URL path/query, which §5.4 forbids (fragment-only bearer tokens).
  Document as an accepted limitation.
- Merchant-channel and test emails: no unsubscribe footer/header.

## 5. Channels

| Channel | Template | Extras |
|---|---|---|
| `customer` | full order template | unsubscribe footer + `List-Unsubscribe`; delivery block on `confirmed` |
| `merchant` | full order template | none |
| `account` (magic link) | same shell (logo/accent/header) | no order sections; sign-in footer copy; link stays fragment-URL |
| test send | full shell with sample content | marked preview content |

## 6. Invariants (unchanged)

- Subjects: display name + event label only — no PII/ids (extend to
  headers: no addresses in `List-Unsubscribe` beyond the order URL).
- Bodies never carry decrypted addresses, keys, BOLT11/preimage.
- `preview_enc` gains the redacted HTML render:
  `{"subject","text","html"}` — the owner preview must represent what
  was actually sent, and text-only preview under-serves that once HTML
  goes out. Additive JSON key, backward compatible with existing rows.
- Suppression gates unchanged: `email_enabled`, host SMTP configured,
  merchant active, `notify_events` flags, per-order `email_opt_in`,
  consent re-checked at send time.
- Rate-limit buckets unchanged; dedupe `UNIQUE(order_id, channel,
  event_type, recipient_hash)` unchanged.
- SMTP stays outside the transaction (no claim held across network I/O).
- `_public_merchant` must not expose the new `email_*` columns to
  unauthenticated projections (owner-scoped fields are fine to add to
  the owner projection).

## 7. API surface

- `PATCH .../notifications` — extend `PatchNotificationsBody`
  (`extra=forbid`, so it rejects unknown fields today) with
  `email_header_text`, `email_footer_text`, `email_accent`. The handler
  funnels through `merchant_service.patch_merchant`, so the allowlist
  there (`merchant.py` ~L391) gains the same three keys. Keep the
  fields notifications-scoped only — do **not** add them to
  `PatchMerchantBody` (which also carries `notify_*` today; leaving
  them off keeps one canonical settings surface).
- `POST .../notifications/logo` — bounded multipart upload (reuse
  `MultiPartParser` + bounded-stream pattern from `_catalog_upload`),
  single file, sniffs to png/jpeg/webp, writes to media dir, updates
  `email_logo_path`. `DELETE` on the same route clears it and removes
  the file.
- **`harness/registry.py::HTTP_ROUTES` + technical-spec §5 must be
  updated in the same change** (bidirectional parity test).

## 8. Admin UI

Notifications section (`admin.html` ~2218+, `admin_settings.js`):
logo picker w/ preview + remove, header/footer text inputs, accent
swatch (default = theme accent), and the existing "send test" button
already exercises the branded render end-to-end.

## 9. Test plan

- **`harness/email.py` must be updated in parallel** — it's the
  executable §8.8 model the qualification tests run against (SmtpStub
  mirrors claim/suppress/rate-limit/backoff). Model the multipart
  shape (or at minimum pass a structured message instead of a bare
  `body: str`) so the PII/log-exposure assertions cover *both* parts.
  This is the easiest gap to miss — the model isn't in the service
  tree.
- `tests/qualification/test_p0_09_email_persistence.py`: MIME
  alternative structure; text part equals existing render; CID part
  present iff logo configured; escaping of `<script>` titles;
  suppression unchanged.
- `tests/qualification/test_p0_10_smtp_boundary.py`: no token/PII in
  either part; `List-Unsubscribe` on customer channel only; logo bytes
  absent from preview_enc; From display-name encoding strips CR/LF.
- Unit tests on `_build_message` directly (no network): MIME tree,
  header set, CID wiring.
- Route parity for the new logo route (auto-covered).
- Validation tests: accent regex, header/footer caps, logo sniff/size
  rejections, missing-logo fallback send.
- All new tests carry `pytest.mark.fast`; run `make verify-fast`.

## 10. Open questions

Resolved (2026-10-15 review):

1. ~~header/footer text vs logo+accent only~~ → **ship all three**;
   the custom footer supplements the mandatory footer line, never
   replaces it (§4.2.6).
2. ~~magic-link shell~~ → **same shell, channel-appropriate footer**
   ("you requested a sign-in link") — consistent sender identity aids
   phishing recognition.
3. ~~logo budget~~ → **single-slot semantics**, one file replaced
   atomically (§4.3); no accounting path needed.

New — discovered during review:

4. `notify_events` currently gates the **customer** channel too —
   `_suppression_reason` checks the flag channel-agnostically, so a
   merchant disabling "shipped" silently stops customer shipped emails
   (rows enqueue, then suppress). Options: (a) document as-is — one
   toggle gates all order email — and fix admin copy to say so;
   (b) add a `customer_events` map for per-channel control. Recommend
   (a) for v1 and revisit if merchants ask.
5. Optional kill-switch: an `email_html` ext_settings flag that falls
   back to text-only without a redeploy. Cheap insurance if the HTML
   render misbehaves in production; include only if it stays a one-line
   branch in `_build_message`'s caller.

## 11. Files touched

- `services/email.py` — `_build_message`, `_smtp_send`, `_render_html`,
  CID assembly, headers; logo bytes read after suppression/rate-limit
  checks (no wasted disk I/O; ≤256 KB sync read, wrap in `to_thread` if
  it grows)
- `services/orders.py` — none (render is at send time)
- `services/merchant.py` — patch/validate new fields, `get_notifications`
- `services/migration_media.py` — extract sniff/save helper or reuse
- `migrations.py` — new `m0xx` for the four columns
- `models.py` — new `Merchant` fields
- `views_api.py` — `PatchNotificationsBody` + logo upload/delete route
- `templates/admin.html`, `js/admin_settings.js` — settings UI
- `harness/email.py` — multipart modeling (see §9)
- `harness/registry.py`, `docs/technical-specification.md` §4/§5/§8.8 +
  §15 note recording the CID-only / no-remote-`img` rationale
- `tests/qualification/test_p0_09_email_persistence.py`,
  `test_p0_10_smtp_boundary.py`
