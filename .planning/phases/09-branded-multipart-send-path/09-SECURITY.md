---
phase: "09-branded-multipart-send-path"
slug: "branded-multipart-send-path"
status: verified
threats_open: 0
asvs_level: 1
created: "2026-10-18"
---

# Phase 9 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| Merchant/order DB → email headers and HTML | Stored names, item titles, delivery content and theme tokens are untrusted output values. | Display name, titles, quantities, totals, delivery strings, accent color |
| Worker → operator SMTP relay | The extension builds and transmits MIME outside database transactions. | SMTP credentials, recipient envelope, message body, bearer-link fragments |
| Queue → owner preview | Encrypted queue payloads are reduced to a persisted redacted text preview. | Subject and body; order/sign-in links and delivery content are replaced with placeholders |
| Test-send endpoint → merchant mailbox | Test mail is limited to configured recipients and an hourly rate bucket. | Fixed synthetic order content; no real order data |

---

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-09-01 | Tampering | `_header_safe` / `_build_message` | high | mitigate | Unicode controls are stripped and names are encoded with `Address`; `test_header_safety_and_deliverability_headers` covers hostile values and bare-address fallback. | closed |
| T-09-02 | Information disclosure | `_smtp_send` / worker logs | high | mitigate | SMTP failures do not log message, recipient or credential values; session-wide fake-SMTP containment prevents live network access in tests. | closed |
| T-09-03 | Denial of service | `_smtp_send` | medium | mitigate | Socket timeout and remaining-lease `wait_for` budget bound transport; fake-SMTP tests assert timeout and error propagation. | closed |
| T-09-04 | Repudiation | `_suppression_reason` / `_leased_write` | high | mitigate | Customer consent is rechecked at send time; merchant event flags apply to merchant alerts only; claim-token and retry behavior remain covered by queue and qualification tests. | closed |
| T-09-05 | Information disclosure | Relay STARTTLS | high | accept | D-25 deliberately mirrors the pinned host's unverified STARTTLS. The accepted deployment assumption and future verified-TLS hardening are recorded in `.planning/STATE.md` Deferred Items. | closed |
| T-09-06 | Tampering | `_render_html` / accent / CTA | high | mitigate | Dynamic HTML is escaped, attribute values are quoted, accent uses six-digit `fullmatch`, and CTA contrast is tested; no remote resources are rendered. | closed |
| T-09-07 | Information disclosure | `preview_enc` / footers | high | mitigate | Customer and account bearer links plus digital content are redacted from the persisted `subject`/`body` preview; runtime preview tests assert no live link remains. | closed |
| T-09-08 | Spoofing | Orderless test sample | medium | mitigate | Test sends use fixed visibly marked sample items and totals, no real order and no CTA; event-toggle exemption and global suppression/rate gates are tested. | closed |
| T-09-09 | Tampering | `_render_html` | high | mitigate | Adversarial title, delivery, URL and optional-copy cases assert context-appropriate escaping across both rendering paths. | closed |
| T-09-10 | Information disclosure | Accent / CID | high | mitigate | Accent validation and 4.5:1 foreground checks, synthetic CID MIME tests, and no-remote-resource assertions cover CSS and image fetch risks. | closed |
| T-09-11 | Information disclosure | `preview_enc` / footers | high | mitigate | Runtime preview tests cover redaction of repeated status and footer links, sign-in links, and delivery content. | closed |
| T-09-12 | Spoofing | `_SAMPLE_ORDER` / `_SAMPLE_ITEMS` | medium | mitigate | Orderless test-send tests prove sample markers, synthetic values, no CTA, disabled-event behavior and the retained global gates. | closed |
| T-09-13 | Denial of service | HTML template | low | accept | Pathological large messages may be clipped by Gmail; input sizes are bounded by existing catalog limits and the plain-text alternative retains the complete footer. | closed |

*Status: open · closed · open — below high threshold (non-blocking)*  
*Severity: critical > high > medium > low — only open threats at or above workflow.security_block_on count toward `threats_open`.*  
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party).*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-09-01 | T-09-05 | Host-compatible unverified STARTTLS is an owner-locked Phase 9 choice (D-25); verified TLS is ASVS L2 hardening and remains deferred. | Project owner, D-25 | 2026-10-17 |
| AR-09-02 | T-09-13 | Extreme email size may cause client-side clipping; catalog limits bound content and the plain alternative retains the required footer. | Phase 9 plan, ASVS L1 | 2026-10-18 |

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-10-18 | 13 | 13 | 0 | execute-phase orchestrator, ASVS L1 artifact audit |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-10-18
