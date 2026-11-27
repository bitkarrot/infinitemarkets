---
phase: 09-branded-multipart-send-path
plan: "02"
subsystem: email-delivery
tags: [smtp, email, multipart, pytest, html]

requires:
  - phase: 09-branded-multipart-send-path
    provides: "Plan 01's extension-owned MIME/SMTP seam and complete cross-channel email path"
provides:
  - "Adversarial boundary coverage for order sections, nullable money, link expiry, and color contrast"
  - "Escaped optional HTML header/footer text seams while preserving mandatory channel footers"
  - "Runtime regressions for test-send isolation, global gates, merchant-only suppression, and preview redaction"
affects: [phase-11-email-contract-release-qualification, transactional-email]

actuals:
  tokens: 5189
  tasks: 2
  commits: 5
plan_head_before: e42006201d6f8f85694b797b88f1e9719f211205

tech-stack:
  added: []
  patterns:
    - "Render missing real-order money as an em dash instead of omitting the totals row."
    - "Keep optional merchant copy escaped and place mandatory channel copy after it."

key-files:
  created: []
  modified:
    - infinitemarkets/services/email.py
    - tests/runtime/test_email_render.py
    - tests/runtime/test_email_queue.py
    - tests/runtime/test_email_signin.py

key-decisions:
  - "Null order and line money is displayed as an em dash; no amount is fabricated."
  - "Optional HTML header/footer copy is escaped plain text and cannot replace mandatory channel copy."

requirements-completed: [EMAIL-01, EMAIL-02, EMAIL-03, EMAIL-08, EMAIL-09, EMAIL-10, EMAIL-11]

coverage:
  - id: D1
    description: "Real-order sections remain accurate for equal rows, empty orders, nullable money, hostile themes, and dead/live status tokens."
    requirement: EMAIL-02
    verification:
      - kind: unit
        ref: "tests/runtime/test_email_render.py#test_sections_keep_adjacent_equal_items_and_render_zero_item_order_totals"
        status: pass
      - kind: unit
        ref: "tests/runtime/test_email_render.py#test_sections_show_em_dash_for_nullable_line_and_order_money"
        status: pass
      - kind: unit
        ref: "tests/runtime/test_email_render.py#test_sections_use_fullmatch_accent_and_readable_cta_contrast"
        status: pass
      - kind: unit
        ref: "tests/runtime/test_email_render.py#test_sections_hide_dead_status_links_and_gate_delivery_exactly"
        status: pass
    human_judgment: true
    rationale: "Automated MIME checks cannot establish client-specific visual fidelity in Gmail, Apple Mail, and Outlook; real-client UAT remains a phase-level manual check."
  - id: D2
    description: "MIME alternatives, optional CID logo fallback, UTF-8 wire encoding, and safe sender headers remain intact."
    requirement: EMAIL-01
    verification:
      - kind: unit
        ref: "tests/runtime/test_email_render.py#test_mime_tree_is_alternative_with_optional_related_logo"
        status: pass
      - kind: unit
        ref: "tests/runtime/test_email_render.py#test_unicode_parts_round_trip_as_ascii_quoted_printable"
        status: pass
      - kind: unit
        ref: "tests/runtime/test_email_render.py#test_header_safety_and_deliverability_headers"
        status: pass
    human_judgment: false
  - id: D3
    description: "Customer/account/merchant/test footers, escaped optional copy, and fragment redaction hold across channels."
    requirement: EMAIL-09
    verification:
      - kind: unit
        ref: "tests/runtime/test_email_render.py#test_footer_optional_copy_is_escaped_and_never_replaces_channel_notice"
        status: pass
      - kind: unit
        ref: "tests/runtime/test_email_render.py#test_customer_footer_escapes_live_fragment_and_has_no_dead_href"
        status: pass
      - kind: integration
        ref: "tests/runtime/test_email_queue.py#test_customer_preview_redacts_order_and_footer_links"
        status: pass
      - kind: integration
        ref: "tests/runtime/test_email_signin.py#test_magic_link_send_renders_fragment_and_wipes"
        status: pass
    human_judgment: false
  - id: D4
    description: "Consent, event preferences, global suppressions, sample-send isolation, and the hourly test-send cap remain effective."
    requirement: EMAIL-08
    verification:
      - kind: integration
        ref: "tests/runtime/test_email_queue.py#test_notify_events_gate_merchant_only"
        status: pass
      - kind: integration
        ref: "tests/runtime/test_email_queue.py#test_merchant_confirmed_delivery_is_not_included"
        status: pass
      - kind: integration
        ref: "tests/runtime/test_email_queue.py#test_orderless_test_send"
        status: pass
      - kind: integration
        ref: "tests/runtime/test_email_queue.py#test_orderless_test_send_respects_global_gates"
        status: pass
      - kind: integration
        ref: "tests/runtime/test_email_queue.py#test_orderless_test_send_rate_limit_remains_five_per_hour"
        status: pass
    human_judgment: false

duration: 14min
completed: 2026-10-18
status: complete
---

# Phase 9 Plan 02: Branded Multipart Send Path Summary

**Branded transactional email preserves distinct order rows and truthful nullable totals, with escaped channel copy and adversarial queue coverage.**

## Performance

- **Duration:** 14 min
- **Started:** 2026-10-18T19:01:24Z
- **Completed:** 2026-10-18T19:15:36Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Added adversarial renderer checks for equal-valued adjacent items, empty orders, nullable line/order money, Unicode content, deterministic query ordering, backorder boundaries, safe CID alt text, and accepted/hostile accents.
- Corrected real-order totals so missing values remain visible as em dashes rather than disappearing or being fabricated; CTA foreground remains contrast-safe, including black on `#777777`.
- Exercised live, expired, missing, and corrupt AEAD status-token variants, customer-confirmed-only delivery, section ordering, hidden preheader, and the 600px inline-CSS presentation.
- Added escaped plain-text header/footer seams while keeping mandatory channel notices intact and last; expanded account fragment, preview-redaction, sample-isolation, suppression-gate, and hourly-bucket regressions.

## Verification

- `uv run pytest tests/runtime/test_email_render.py -q` — **14 passed**.
- `uv run pytest tests/runtime/test_email_queue.py -k "notify_events or consent or orderless or delivery" -q` — **8 passed, 29 deselected**.
- `uv run pytest tests/runtime/test_email_signin.py -k magic_link_send_renders_fragment_and_wipes -q` — **1 passed, 22 deselected**.
- `uv run pytest tests/runtime/test_email_queue.py tests/runtime/test_email_signin.py tests/runtime/test_financial_review.py -q` — **141 passed, 6 skipped** (PostgreSQL-only drills skipped on the local SQLite profile).
- `make verify-fast` — **332 passed, 2 skipped, 796 deselected**.
- `uv run ruff check .` — **passed**.
- All SMTP tests remained fake-only under the session-autouse connection guard; no real SMTP network access occurred.
- The full `make verify` suite was not run; the post-wave gate owns that check.

## Task Commits

1. **Task 1 RED:** `4c2d761` — add failing boundary email presentation tests.
2. **Task 1 GREEN:** `f427791` — render nullable order totals explicitly.
3. **Task 2 RED:** `a5eb31c` — add adversarial channel footer regressions.
4. **Task 2 GREEN:** `3b1ce98` — add escaped optional email copy seams.
5. **Task 2 regression follow-up:** `3d05f76` — assert dead links stay absent from text.

**Plan metadata:** included with the shared state, roadmap, and requirements update in the final close-out commit.

## Files Created/Modified

- `infinitemarkets/services/email.py` — renders nullable order totals explicitly and accepts escaped optional header/footer text without moving or replacing fixed channel copy.
- `tests/runtime/test_email_render.py` — validates presentation boundaries, MIME/CID fallback, encoding, token liveness, color contrast, and footer escaping.
- `tests/runtime/test_email_queue.py` — validates merchant-only event gating, delivery privacy, orderless sample isolation, global gates, redacted previews, and the five-per-hour test-send limit.
- `tests/runtime/test_email_signin.py` — verifies hostile account-link attributes remain escaped and bearer tokens stay out of headers/previews.

## Decisions Made

- Real-order nullable money is shown as an em dash; the renderer never invents prices.
- Optional Phase 10 copy is plain text, context-escaped, and supplementary; the fixed channel footer remains mandatory and follows it.
- Preserve the `{"subject","body"}` preview shape, fragment-only bearer links, D-25 host-compatible unverified STARTTLS, D-26 text wording, and D-27 frozen-binary deferral.
- No schema, route, UI, harness multipart model, spec contract, or host notification helper changes were needed.

## TDD Gate Compliance

- **Task 1:** `test_sections_show_em_dash_for_nullable_line_and_order_money` failed on the intended missing-total assertion before the implementation commit. `check tdd-red-evidence` returned `RED_EVIDENCE_OK`; Task 1 RED preceded GREEN.
- **Task 2:** `test_footer_optional_copy_is_escaped_and_never_replaces_channel_notice` failed on the intended missing renderer-argument assertion before implementation. `check tdd-red-evidence` returned `RED_EVIDENCE_OK`; Task 2 RED preceded GREEN. The final test-only follow-up extended the dead-link plain-text assertion.
- No refactor commit was needed.
- The checker consumes TAP summaries while the project uses pytest; persisted RED records used a normalized one-test TAP summary derived from the captured pytest assertion output.

## Deviations from Plan

None - implementation and tests stayed within the four Plan 02 files and the explicitly planned edge-hardening scope.

## Issues Encountered

- An initial equal-row test assertion expected four line-total displays when the renderer correctly emitted two; the test expectation was corrected before the GREEN implementation commit.
- The cross-plan static key-link probe's `views_public_api.py` path is a link-only relationship: email rendering intentionally does not import the opt-out route module. Owner approved continuing without fake imports or unnecessary coupling.
- `state.update-progress` warned that STATE.md has no legacy body `Progress:` line; structured plan progress advanced to 2/2 and the roadmap plan count is 2/2.
- Six PostgreSQL-only concurrency/interleaving tests were skipped under the local SQLite profile. The full suite and PostgreSQL CI matrix remain outside this Plan 02 gate.

## User Setup Required

None - no external SMTP configuration or other service setup changed.

## Next Phase Readiness

- Both Phase 9 plans are complete; the post-wave full-suite gate can now verify the combined send path.
- Phase 10 branding persistence/UI and Phase 11 harness/spec qualification remain untouched.
- Real SMTP delivery/client rendering and frozen-binary smoke were not claimed; D-27 remains deferred to Phase 11.

## Self-Check: PASSED

- All four planned source/test files and this summary exist.
- All five measured Plan 02 task commits are present after `plan_head_before`.
- The Plan 02 diff contains only the four explicitly scoped files; all 39 pre-existing archive renames remain staged.
