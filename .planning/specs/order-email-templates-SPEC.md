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
(`services/email.py::_smtp_send`). It reuses the same host credentials
(`host_settings.lnbits_email_notifications_*`), the same
`asyncio.to_thread` + `starttls` + `sendmail` mechanics, and the same
`asyncio.wait_for(min(30, remaining))` deadline discipline already in
`worker_tick._send`. ~20 lines of stdlib `smtplib`; no new dependencies.

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
- **Every interpolated value passes `html.escape`** — display name, item
  titles, quantities, totals, delivery content, custom header/footer
  text. This is a hard contract: item titles are merchant-controlled,
  delivery content is merchant-authored, and both land in a security
  surface (email). Add a qualification test asserting a stored
  `<script>`-bearing title renders escaped.
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
  6. Footer: merchant name, "you opted in to order emails" notice, and
     on the customer channel an opt-out line pointing at the order page.

### 4.3 Merchant customization fields

New nullable columns on `merchants` (new migration, next `m0xx`):

| Column | Type | Validation |
|---|---|---|
| `email_logo_path` | TEXT | namespaced media filename, written only by the upload route |
| `email_header_text` | TEXT | ≤120 chars, control chars stripped, single line |
| `email_footer_text` | TEXT | ≤240 chars |
| `email_accent` | TEXT | `#[0-9a-fA-F]{6}` or NULL → falls back to `theme` accent |

**Logo storage:** reuse the `migration_media` local store pattern —
bounded multipart upload, magic-byte sniff (PNG/JPEG/WebP only),
SHA-256 content-addressed filename under the merchant-namespaced media
dir, cap ≤256 KB, and the existing per-merchant 400 MB budget applies.
Logo uploads are *not* gated on URLs already in the catalog (unlike
migration media) — it's a dedicated `email-logo` kind.

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
- No RFC 8058 `List-Unsubscribe-Post` one-click: it requires the token
  in URL path/query, which §5.4 forbids (fragment-only bearer tokens).
  Document as an accepted limitation.
- Merchant-channel and test emails: no unsubscribe footer/header.

## 5. Channels

| Channel | Template | Extras |
|---|---|---|
| `customer` | full order template | unsubscribe footer + `List-Unsubscribe`; delivery block on `confirmed` |
| `merchant` | full order template | none |
| `account` (magic link) | header/footer shell only | no order sections; link stays fragment-URL |
| test send | full shell with sample content | marked preview content |

## 6. Invariants (unchanged)

- Subjects: display name + event label only — no PII/ids (extend to
  headers: no addresses in `List-Unsubscribe` beyond the order URL).
- Bodies never carry decrypted addresses, keys, BOLT11/preimage.
- `preview_enc` keeps storing the redacted subject+text-body pair —
  owner preview does not gain the raw HTML (it shows the redacted text
  render; note "branded HTML also sent" in preview UI if trivial).
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

- `PATCH .../notifications` — extend body with `email_header_text`,
  `email_footer_text`, `email_accent` (validated above).
- `POST .../notifications/logo` — bounded multipart upload (reuse
  `MultiPartParser` + bounded-stream pattern from `_catalog_upload`),
  single file, sniffs to png/jpeg/webp, writes to media dir, updates
  `email_logo_path`. `DELETE` on the same route clears it.
- **`harness/registry.py::HTTP_ROUTES` + technical-spec §5 must be
  updated in the same change** (bidirectional parity test).

## 8. Admin UI

Notifications section (`admin.html` ~2218+, `admin_settings.js`):
logo picker w/ preview + remove, header/footer text inputs, accent
swatch (default = theme accent), and the existing "send test" button
already exercises the branded render end-to-end.

## 9. Test plan

- `tests/qualification/test_p0_09_email_persistence.py`: MIME
  alternative structure; text part equals existing render; CID part
  present iff logo configured; escaping of `<script>` titles;
  suppression unchanged.
- `tests/qualification/test_p0_10_smtp_boundary.py`: no token/PII in
  either part; `List-Unsubscribe` on customer channel only; logo bytes
  absent from preview_enc.
- Route parity for the new logo route (auto-covered).
- Validation tests: accent regex, header/footer caps, logo sniff/size
  rejections, missing-logo fallback send.
- All new tests carry `pytest.mark.fast`; run `make verify-fast`.

## 10. Open questions

1. Should `email_header_text`/`footer_text` ship at all in v1, or is
   logo+accent enough? (Recommend shipping all three — trivial cost.)
2. Magic-link shell: same accent/logo, or deliberately plain to look
   credential-like? (Recommend same shell — consistent sender identity.)
3. Does the logo upload share the migration-media 400 MB budget or get
   its own small bucket (e.g. 2 MB total, one logo)? (Recommend the
   shared budget — simpler, already enforced.)

## 11. Files touched

- `services/email.py` — `_smtp_send`, `_render_html`, CID assembly,
  unsubscribe header
- `services/orders.py` — none (render is at send time)
- `services/merchant.py` — patch/validate new fields, `get_notifications`
- `services/migration_media.py` — extract sniff/save helper or reuse
- `migrations.py` — new `m0xx` for the four columns
- `views_api.py` — notifications patch body + logo upload/delete route
- `templates/admin.html`, `js/admin_settings.js` — settings UI
- `harness/registry.py`, `docs/technical-specification.md` §4/§5/§8.8
- `tests/qualification/test_p0_09_email_persistence.py`,
  `test_p0_10_smtp_boundary.py`
