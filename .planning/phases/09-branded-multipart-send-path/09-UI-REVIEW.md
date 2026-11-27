# Phase 9 — UI Review

**Audited:** 2026-10-18
**Baseline:** Abstract six-pillar standards adapted to the locked transactional-email constraints; no Phase 9 UI-SPEC.md exists.
**Screenshots:** Not captured — code-only audit of transactional HTML email. Phase 9 changed no storefront, admin, or browser UI; no live mail-client rendering was inspected.
**Scope:** Transactional HTML email only. No website UI review or redesign recommendations.

---

## Pillar Scores

| Pillar | Score | Key Finding |
|--------|-------|-------------|
| 1. Copywriting | 3/4 | Channel-specific copy and fallback notices are clear; missing state data is rendered as the vague “unknown.” |
| 2. Visuals | 3/4 | Email-safe single-column shell and ordered sections; the four-column order table has no narrow-client reflow treatment. |
| 3. Color | 2/4 | CTA contrast is selected safely, but header wordmark text can be low-contrast against an accepted dark accent. |
| 4. Typography | 3/4 | Restrained system-font styling; body size and line-height are left to client defaults. |
| 5. Spacing | 3/4 | Consistent outer gutters and section padding; table headings have no explicit padding or visual separation. |
| 6. Experience Design | 3/4 | Live-link gating, channel-specific notices, and sample labeling are present; item-table headers lack explicit column scope. |

**Overall: 17/24**

---

## Top 3 Priority Fixes

1. **Set a contrast-safe foreground on the accent header band** — dark merchant accents can make the wordmark unreadable (for example, accepted `#000000` with inherited `#1f2328` is about 1.33:1) — use the already computed `on_accent` foreground for header text and verify contrast against every accepted accent.
2. **Associate item-table headers explicitly** — assistive technology gets less reliable column context without explicit scope — add `scope="col"` to each item-table `<th>` and retain the existing concise labels.
3. **Improve the order table at narrow email-client widths** — four columns can become cramped when the 600px shell contracts on mobile — use email-safe fluid column sizing/wrapping or a narrow-width stacked presentation while preserving inline-only CSS.

---

## Detailed Findings

### Pillar 1: Copywriting (3/4)

- **WARNING:** Transactional labels are specific, channel copy is differentiated, the test message is explicitly marked, and the customer footer explains how to opt out even when no live link is available (`infinitemarkets/services/email.py:355-363`, `472-490`). However, missing order state is shown as `State: unknown` (`infinitemarkets/services/email.py:360-363`), which is vague and can read as an actual state. Prefer a clearer unavailable-state phrase or omit the state row when absent.

### Pillar 2: Visuals (3/4)

- **WARNING:** The message uses a centered, table-based shell with a 600px width attribute, fluid `width:100%`, `max-width:600px`, an accent header band, ordered content sections, and a footer (`infinitemarkets/services/email.py:397-447`, `503-520`). The content remains a single-column layout and does not rely on remote resources.
- **WARNING:** The item table is four columns wide (`infinitemarkets/services/email.py:402-406`) but declares no column sizing or narrow-client arrangement. At mobile email widths, quantity and price columns may compress and long item names may wrap unpredictably. Improve fluid sizing/wrapping or provide a narrow-width presentation.
- The optional logo is CID-based and has escaped display-name alt text; without a logo, a text wordmark is used (`infinitemarkets/services/email.py:368-381`). This satisfies the Phase 9 no-remote-asset constraint.

### Pillar 3: Color (2/4)

- **WARNING:** Theme accents are full-match validated and the CTA receives a foreground selected for at least 4.5:1 contrast (`infinitemarkets/services/email.py:285-298`, `459-469`). This is a strong CTA treatment.
- **WARNING:** The accent is also used as the header background, but the header wordmark/header text does not receive the computed contrast foreground; it inherits `#1f2328` from the outer table (`infinitemarkets/services/email.py:368-381`, `511-515`). The renderer accepts `#000000` as an accent, for which inherited `#1f2328` is approximately 1.33:1, so the brand name can be nearly illegible. Apply a contrast-safe header foreground, independently of the CTA.
- The light canvas (`#f4f4f5` around `#ffffff`) and muted footer color keep the overall email in a safe light theme (`infinitemarkets/services/email.py:506`, `517-518`); there are no dark-mode overrides.

### Pillar 4: Typography (3/4)

- **WARNING:** The shell uses the requested system-font stack, with a restrained set of explicit sizes and weight (`20px`/`600` for key headings, `13px` for supplemental/footer text, and `12px` for the backorder badge; `infinitemarkets/services/email.py:374-376`, `397-399`, `417-420`, `513-518`). This is appropriate for broad email-client compatibility and avoids webfonts.
- **WARNING:** The shell does not establish a base font size or line-height; only the footer explicitly sets `line-height:1.5` (`infinitemarkets/services/email.py:511-518`). Body and table text therefore rely on client defaults, so line rhythm may vary between clients. Set a consistent inline base size and line-height on the content shell or cells.

### Pillar 5: Spacing (3/4)

- **WARNING:** The shell has balanced outer padding (`24px 12px`), 24px horizontal content gutters, and recurring 8/16/24px vertical section padding; the footer is separated by a border and 16px padding (`infinitemarkets/services/email.py:397-447`, `463-469`, `509-519`).
- **WARNING:** The item-table headings have no inline padding, line-height, or separating rule, unlike the padded item rows (`infinitemarkets/services/email.py:402-425`). This makes the table header visually tight against its content. Add modest header-cell padding and a restrained divider without changing the overall email-client-safe layout.

### Pillar 6: Experience Design (3/4)

- **WARNING:** The renderer gives account messages sign-in content without order sections, marks synthetic test content, gates digital delivery to confirmed customer mail, and renders the status CTA only when a link is present (`infinitemarkets/services/email.py:352-400`, `449-469`, `493-501`). The customer footer also preserves a no-link opt-out explanation (`infinitemarkets/services/email.py:472-490`).
- **WARNING:** Item headers use `<th>` and have concise labels, but omit explicit `scope="col"` (`infinitemarkets/services/email.py:402-406`). Add column scope so assistive technology can associate the item, quantity, unit-price, and line-total values with their headers reliably.
- Code inspection and the recorded test coverage establish structural behavior, not rendered fidelity in Gmail, Apple Mail, or Outlook. No email-client screenshots were captured for this code-only review; verify representative messages in target clients before relying on client-specific layout behavior.

---

## Files Audited

- `.planning/phases/09-branded-multipart-send-path/09-01-PLAN.md`
- `.planning/phases/09-branded-multipart-send-path/09-02-PLAN.md`
- `.planning/phases/09-branded-multipart-send-path/09-01-SUMMARY.md`
- `.planning/phases/09-branded-multipart-send-path/09-02-SUMMARY.md`
- `.planning/phases/09-branded-multipart-send-path/09-CONTEXT.md`
- `infinitemarkets/services/email.py`
- `tests/runtime/test_email_render.py`
- `AGENTS.md`
