# Requirements: infinitemarkets

**Defined:** 2026-10-17
**Milestone:** v1.2 — Branded Order Emails
**Core Value:** A merchant can sell one authoritative inventory safely through LNbits-backed web and Nostr flows without duplicate invoices, double allocation, or relay delivery being mistaken for payment truth.

Spec input: `.planning/specs/order-email-templates-SPEC.md` (reviewed
2026-10-15, updated for shipped v1.1 media library).

## v1 Requirements

Requirements for v1.2. Each maps to one roadmap phase after owner approval.

### Email Delivery & Template

- [x] **EMAIL-01**: Order-event emails are delivered as `multipart/alternative` — the existing `text/plain` render plus a branded `text/html` part — through an extension-owned SMTP boundary (`_build_message`/`_smtp_send`) that reuses the host SMTP configuration and existing timeout/retry discipline.
- [x] **EMAIL-02**: The HTML part renders a merchant-branded template: logo or display-name header with accent color, event title + state label, item table (title, quantity, line totals), order totals (subtotal/shipping/total sats), status-link CTA while the token copy is live, and channel-appropriate footer copy.
- [x] **EMAIL-03**: Every interpolated value in the HTML part is escaped (item titles, display name, custom text, digital-delivery content); digital delivery appears only in the customer-channel `confirmed` email; subjects remain display name + event label with no PII or internal ids.
- [ ] **EMAIL-04**: The owner email preview reflects what was actually sent — subject, redacted text, and redacted HTML — and renders the HTML in a sandboxed preview surface.

### Merchant Branding

- [ ] **EMAIL-05**: Merchant can upload one email logo through a local-backend-only media picker (≤256 KB, PNG/JPEG/WebP accepted, Pillow-verified with a pixel cap, stored PNG/JPEG); the logo embeds as a CID attachment in the HTML part and is never a remote `<img>` fetch.
- [ ] **EMAIL-06**: Merchant can set email header text (≤120 chars), footer text (≤240 chars), and accent color (#rrggbb, defaulting to the theme accent) via Notifications settings; the custom footer supplements — never replaces — the mandatory channel footer copy.
- [ ] **EMAIL-07**: A logo referenced by `merchants.email_logo_path` is recognized by the media unused-scan and cannot be deleted through Settings → Media cleanup while configured.

### Notification Semantics

- [x] **EMAIL-08**: `notify_events` flags gate merchant-channel emails only; customer-channel emails gate solely on the order's `email_opt_in` consent (suppression reason re-checked at send time).
- [x] **EMAIL-09**: The customer-channel footer carries the order-page opt-out link and opt-in notice; the account channel carries sign-in copy; merchant/test channels carry a neutral transactional notice — each in both parts.
- [x] **EMAIL-10**: Test sends render the branded template with representative sample content and are not suppressed by `notify_events` event flags.
- [x] **EMAIL-11**: Outbound headers gain an encoded `From` display name (CR/LF-stripped merchant display name on the host notifications address), `Date`, `Message-ID`, and `Auto-Submitted: auto-generated`.

### Contract & Verification

- [ ] **EMAIL-12**: Technical-spec §4 (new `merchants` columns), §5 (logo upload/delete routes), §8.8 (multipart send, CID, preview shape), and §15 (no-remote-`img` rationale) are updated together with `harness/registry.py`, `harness/schema.py`, and migration `m020`.
- [ ] **EMAIL-13**: `harness/email.py` models the multipart send path so PII/log-exposure assertions cover both parts; qualification tests cover MIME structure, escaping, channel gating, preview redaction, and validation rejections; `make verify-fast` passes.

## v2 Requirements

Deferred unless the owner promotes them into v1.2 scope.

- **EMAIL-14**: `List-Unsubscribe` header / RFC 8058 one-click unsubscribe — requires a non-fragment unsubscribe credential that does not violate the §5.4 fragment-token posture.
- **EMAIL-15**: Per-channel `customer_events` toggles — separate customer-facing event switches, only if merchants request control beyond merchant alerts.

## Out of Scope

| Feature | Reason |
|---------|--------|
| Merchant-authored HTML / free-form templates | Arbitrary markup in emails is an unbounded injection surface; structured fields only |
| Remote `<img>` logos (Blossom or hosted URL) | Mail-client fetch leaks buyer open-time + IP — a tracking vector outside the consent model |
| `List-Unsubscribe` one-click (RFC 8058) | Requires the bearer token in URL path/query — forbidden by §5.4 fragment-only posture |
| Marketing/bulk email | Transactional order notifications only |
| LNbits host `send_email` changes | Host is pinned (e336fe1); the extension owns the SMTP boundary |
| Upstream/conformance delta work | Revisited after this milestone per owner direction |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| EMAIL-01 | 9 | Complete |
| EMAIL-02 | 9 | Complete |
| EMAIL-03 | 9 | Complete |
| EMAIL-04 | 10 | Pending |
| EMAIL-05 | 10 | Pending |
| EMAIL-06 | 10 | Pending |
| EMAIL-07 | 10 | Pending |
| EMAIL-08 | 9 | Complete |
| EMAIL-09 | 9 | Complete |
| EMAIL-10 | 9 | Complete |
| EMAIL-11 | 9 | Complete |
| EMAIL-12 | 11 | Pending |
| EMAIL-13 | 11 | Pending |

**Coverage:**

- v1 requirements: 13 total
- Mapped to phases: 13
- Unmapped: 0 ✓

---
*Requirements defined: 2026-10-17*
