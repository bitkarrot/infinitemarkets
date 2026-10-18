# Roadmap: infinitemarkets

## v1.0 — Core Commerce and Hardening

**✅ SHIPPED 2026-10-13** — full phase detail: [milestones/v1.0-ROADMAP.md](milestones/v1.0-ROADMAP.md); requirements archive: [milestones/v1.0-REQUIREMENTS.md](milestones/v1.0-REQUIREMENTS.md); audit: [v1.0-MILESTONE-AUDIT.md](v1.0-MILESTONE-AUDIT.md).

One authoritative commerce system in an LNbits extension: one inventory sold safely through LNbits-backed web checkout and Nostr/Gamma (NIP-17) private ordering — no duplicate invoices, no double allocation, relay delivery never mistaken for payment truth.

| Phase | Plans | Status | Completed |
|-------|-------|--------|-----------|
| 1. Conformance Profile (Contract Phase 0) | 3/3 | Complete | 2026-09-20 |
| 2. Release A — Safe Web Commerce | 4/4 | Complete | Delivered 2026-09-27; acceptance restored 2026-10-13 |
| 3. Release B — Gamma NIP-17 Orders | 4/4 | Complete | Delivered 2026-09-29; live UAT passed 2026-10-13 |
| 03.1. Buyer accounts (INSERTED) | 3/3 | Complete | 2026-10-07 |
| 4. Release C — Catalog Import and Export | 4/4 | Complete | 2026-10-09 |
| 5. Correctness, Recovery, and Security Hardening | 6/6 | Complete | Gates closed 2026-10-13 (v0.6.3) |

## v1.1 — Media uploads and Blossom support

**✅ SHIPPED 2026-10-17** — full phase detail: [milestones/v1.1-ROADMAP.md](milestones/v1.1-ROADMAP.md); phase artifacts: [milestones/v1.1-phases](milestones/v1.1-phases/).

LNbits-local + Blossom image uploads, shared media picker, Settings → Media cleanup, bounded share-card redirects (PR #28). v1.1.0 tagged and published.

| Phase | Plans | Status | Completed |
|-------|-------|--------|-----------|
| 6. Secure Media Storage | 4/4 | Complete | 2026-10-16 |
| 7. Shared Image Editors | 4/4 | Complete | 2026-10-16 |
| 8. Media Release Qualification | 1/1 | Complete | 2026-10-17 |

## v1.2 — Branded Order Emails

**Goal:** Merchants send branded multipart order emails (text + HTML) with logo/accent customization through the existing durable queue — without weakening consent or privacy invariants.

Order-event emails leave the host's plain-text-only `send_email` behind for an extension-owned SMTP boundary (`_build_message`/`_smtp_send`) that reuses host SMTP configuration and the existing timeout/retry discipline. The HTML part embeds the merchant's logo as a CID attachment — never a remote `<img>` fetch — and carries structured header/footer/accent branding. Merchant `notify_events` toggles gate merchant-channel alerts only; customer emails gate solely on the order's `email_opt_in` consent. `List-Unsubscribe`/RFC 8058 one-click stays deferred: the §5.4 fragment-token posture forbids bearer tokens in URL path/query.

Spec: [.planning/specs/order-email-templates-SPEC.md](specs/order-email-templates-SPEC.md) (reviewed 2026-10-15, updated for shipped v1.1 media library).

### Phases

- [ ] **Phase 9: Branded Multipart Send Path** - Order emails ship as branded multipart/alternative through an extension-owned SMTP boundary.
- [ ] **Phase 10: Merchant Email Branding Controls** - Merchants configure logo, header/footer text, and accent color in Notifications settings with a truthful sandboxed preview.
- [ ] **Phase 11: Email Contract & Release Qualification** - Spec/registry/schema parity and the qualification suite prove both MIME parts safe before release.

### Phase Details

### Phase 9: Branded Multipart Send Path

**Goal**: Every order-event email is delivered as a branded `multipart/alternative` message — the existing text render plus an HTML part — through the extension's own SMTP send path, with consent gating corrected.
**Depends on**: Phase 8 (v1.1 media library; shipped)
**Requirements**: EMAIL-01, EMAIL-02, EMAIL-03, EMAIL-08, EMAIL-09, EMAIL-10, EMAIL-11
**Success Criteria** (what must be TRUE):

  1. An order-event email arrives as `multipart/alternative` — the existing `text/plain` render plus a `text/html` part — sent through `_build_message`/`_smtp_send` using the host SMTP configuration and the existing `asyncio.wait_for` timeout/retry discipline; the host `send_email` helper is unchanged.
  2. A buyer opening the HTML part sees a branded email: logo-or-display-name header with accent color, event title + state label, item table with real line totals and order totals, a status-link CTA while the token copy is live, and channel-appropriate footer copy — customer emails carry the opt-out link + opt-in notice, account emails carry sign-in copy, merchant/test emails carry a neutral transactional notice.
  3. An email triggered by an order whose item title stores `<script>` renders it escaped in both parts; digital-delivery content appears only in the customer-channel `confirmed` email; subjects carry only display name + event label — no PII or internal ids.
  4. With the merchant's `notify_events` "shipped" toggle off, the merchant stops receiving shipped alerts while an opted-in customer still receives theirs; customer-channel suppression keys solely on `email_opt_in` re-checked at send time.
  5. Received emails carry an encoded `From` display name (CR/LF-stripped), `Date`, `Message-ID`, and `Auto-Submitted: auto-generated` headers; the existing send-test button delivers the full branded shell with representative sample content regardless of `notify_events` flags.

**Plans**: 2/2 plans executed in 2 sequential waves

- [x] 09-01-PLAN.md
- [x] 09-02-PLAN.md

- **Wave 1** — `09-01-PLAN.md`: a safe, complete cross-channel multipart send tracer, durable queue outcomes, SMTP test containment, and consent gating.
- **Wave 2** *(blocked on Wave 1 completion)* — `09-02-PLAN.md`: adversarial rendering, contrast, channel-footers, and preview-redaction coverage.

### Phase 10: Merchant Email Branding Controls

**Goal**: Merchants can set email branding — one local media logo, header/footer text, accent color — through Notifications settings, with the owner preview truthfully rendering what will be sent.
**Depends on**: Phase 9
**Requirements**: EMAIL-04, EMAIL-05, EMAIL-06, EMAIL-07
**Success Criteria** (what must be TRUE):

  1. A merchant can upload one email logo through the shared media picker constrained to the local backend — Blossom is not offered — and files over 256 KB or failing Pillow verification/pixel cap are rejected; the stored logo embeds as a CID attachment in sent HTML, never a remote `<img>` fetch.
  2. A merchant can set email header text (≤120 chars), footer text (≤240 chars), and accent color (`#rrggbb`, defaulting to the theme accent) via Notifications settings; invalid values are rejected and the custom footer supplements — never replaces — the mandatory channel footer line.
  3. A logo referenced by `merchants.email_logo_path` never appears as deletable in Settings → Media cleanup; replacing the logo swaps the file atomically and deleting it clears the pointer.
  4. The owner email preview shows subject plus redacted text and redacted HTML parts and renders the HTML in a sandboxed surface that matches what was actually sent.

**Plans**: TBD
**UI hint**: yes

### Phase 11: Email Contract & Release Qualification

**Goal**: The documented contract, harness models, and qualification suite agree with the shipped behavior — both MIME parts covered by the same safety assertions as the text-only path.
**Depends on**: Phase 10
**Requirements**: EMAIL-12, EMAIL-13
**Success Criteria** (what must be TRUE):

  1. Technical-spec §4 (`merchants.email_*` columns), §5 (logo upload/delete routes), §8.8 (multipart send, CID, preview shape), and §15 (CID-only / no-remote-`img` rationale) match `harness/registry.py::HTTP_ROUTES`, `harness/schema.py`, and migration `m020` — the bidirectional parity tests pass.
  2. `harness/email.py` models the multipart send path so existing PII/log-exposure assertions cover both the text and HTML parts.
  3. Qualification tests cover MIME structure, escaping, channel gating, preview redaction, and validation rejections — all marked `pytest.mark.fast` — and `make verify-fast` is green.

**Plans**: TBD

### Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 9. Branded Multipart Send Path | 2/2 | In Progress | - |
| 10. Merchant Email Branding Controls | TBD | Not started | - |
| 11. Email Contract & Release Qualification | TBD | Not started | - |
