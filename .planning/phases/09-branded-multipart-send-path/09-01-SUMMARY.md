---
phase: 09-branded-multipart-send-path
plan: "01"
subsystem: email-delivery
tags: [smtp, email, multipart, pytest]

requires:
  - phase: 08-media-release-qualification
    provides: v1.1 media and release baseline
provides:
  - Extension-owned multipart construction and bounded SMTP transport
  - Complete customer, merchant, account, and test HTML/plain presentations
  - Session-lifetime SMTP containment for runtime tests
  - Merchant-only event suppression in runtime and qualification models
affects: [09-02, phase-11-email-contract, email-queue]

actuals:
  tokens: 19131
  tasks: 3
  commits: 6
plan_head_before: 0bc88136cc752bd28368347aa01da2006126be57

tech-stack:
  added: []
  patterns:
    - Pure EmailMessage builder with a thin asyncio-to-thread SMTP boundary
    - Session-autouse SMTP network guard with function-scoped transport capture
    - Channel-specific transactional footers and merchant-only event gates
patterns-established:
  - "Build both representations before transport, then persist only redacted text preview."
  - "Keep recipient addresses in the SMTP envelope and use module-global transport seams."

key-files:
  created:
    - tests/runtime/test_email_render.py
  modified:
    - infinitemarkets/services/email.py
    - tests/runtime/conftest.py
    - tests/runtime/test_email_queue.py
    - tests/runtime/test_email_signin.py
    - tests/runtime/test_financial_review.py
    - harness/email.py
    - tests/qualification/test_p0_10_smtp_boundary.py

key-decisions:
  - "Recipient addresses stay in the SMTP envelope, not MIME headers; the sender header remains the host notifications address."
  - "The SMTP extension hop mirrors the host's unverified STARTTLS behavior; socket timeout bounds the worker thread."
  - "notify_events gates merchant order alerts only; customer email remains governed by send-time opt-in consent."

requirements-completed: [EMAIL-01, EMAIL-02, EMAIL-03, EMAIL-08, EMAIL-09, EMAIL-10, EMAIL-11]

coverage:
  - id: D1
    description: "Extension-owned multipart/alternative messages, MIME headers, optional CID logo, and fake SMTP transport"
    requirement: EMAIL-01
    verification:
      - kind: unit
        ref: "tests/runtime/test_email_render.py#test_mime_tree_is_alternative_with_optional_related_logo"
        status: pass
      - kind: unit
        ref: "tests/runtime/test_email_render.py#test_smtp_send_mirrors_host_and_propagates_errors"
        status: pass
    human_judgment: false
  - id: D2
    description: "Branded order sections, line/order totals, live-only CTA, delivery gate, escaping, and contrast-safe CSS"
    requirement: EMAIL-02
    verification:
      - kind: unit
        ref: "tests/runtime/test_email_render.py#test_sections_show_real_order_values_and_live_only_cta"
        status: pass
      - kind: unit
        ref: "tests/runtime/test_email_render.py#test_escaping_covers_text_attributes_delivery_and_css"
        status: pass
    human_judgment: false
  - id: D3
    description: "Customer, account, merchant, and test footers, synthetic test content, and redacted previews"
    requirement: EMAIL-09
    verification:
      - kind: unit
        ref: "tests/runtime/test_email_render.py#test_footers_cover_customer_account_merchant_and_test_in_both_parts"
        status: pass
      - kind: integration
        ref: "tests/runtime/test_email_queue.py#test_customer_preview_redacts_order_and_footer_links"
        status: pass
      - kind: integration
        ref: "tests/runtime/test_email_signin.py#test_magic_link_send_renders_fragment_and_wipes"
        status: pass
    human_judgment: false
  - id: D4
    description: "Merchant notification flags suppress merchant alerts without revoking opted-in customer delivery"
    requirement: EMAIL-08
    verification:
      - kind: integration
        ref: "tests/runtime/test_email_queue.py#test_notify_events_gate_merchant_only"
        status: pass
      - kind: integration
        ref: "tests/qualification/test_p0_10_smtp_boundary.py#test_suppressed_rows_never_touch_smtp"
        status: pass
    human_judgment: false
  - id: D5
    description: "Runtime SMTP guard covers host setup, inter-test work, and teardown; live financial-review email remains fake-only"
    verification:
      - kind: integration
        ref: "tests/runtime/test_email_queue.py#test_smtp_guard_active_outside_capture"
        status: pass
      - kind: integration
        ref: "tests/runtime/test_financial_review.py#test_review_public_delivery_snapshot_serializes_cancellation"
        status: unknown
    human_judgment: true
    rationale: "The financial-review background interleaving is PostgreSQL-only and was skipped on the local SQLite profile."

duration: 23min
completed: 2026-10-18
status: complete
---

# Phase 9 Plan 01: Branded Multipart Send Path Summary

**Extension-owned multipart delivery now renders safe, channel-complete email before bounded SMTP transport, with merchant-only event suppression.**

## Performance

- **Duration:** 23 min
- **Started:** 2026-10-18T17:56:21Z
- **Completed:** 2026-10-18T18:19:58Z
- **Tasks:** 3
- **Files modified:** 8

## Accomplishments

- Added a pure `EmailMessage` builder and extension-owned SMTP sender with host-compatible configuration, STARTTLS/login/sendmail order, socket timeout, and the worker's remaining-lease deadline.
- Rendered customer/merchant order detail, customer-only confirmed delivery, live-only status links, account sign-in content, channel-specific footers, and marked synthetic test-order content in both plain and HTML parts.
- Added escaping, accent fullmatch validation, contrast-safe CTA text, safe sender headers, redacted customer/account previews, and a session-autouse runtime SMTP guard.
- Corrected event suppression in both runtime and qualification models so merchant event preferences do not suppress opted-in customer mail.

## Verification

- `uv run pytest tests/runtime/test_email_render.py -q` — **8 passed**.
- `uv run pytest tests/qualification/test_p0_10_smtp_boundary.py -q` — **9 passed**.
- `uv run pytest tests/runtime/test_email_queue.py tests/runtime/test_email_signin.py tests/runtime/test_financial_review.py -q` — **136 passed, 6 skipped**. The skips are PostgreSQL-only lock/interleaving tests on the local SQLite profile.
- `make verify-fast` — **326 passed, 2 skipped, 791 deselected**.
- `uv run ruff check .` — **passed**.
- No test opened a real SMTP connection; the test session guard remained active through host setup and teardown.

## Task Commits

1. **Task 1 RED:** `51ffd3b` — add failing multipart rendering tests.
2. **Task 1 RED:** `6e68414` — migrate runtime send observations and add SMTP containment.
3. **Task 1 GREEN:** `5576c21` — implement complete cross-channel multipart delivery.
4. **Task 2:** `99c43c5` — deepen account/header/preview and background-worker assertions.
5. **Task 3 RED:** `3310407` — prove customer consent is independent of merchant event flags.
6. **Task 3 GREEN:** `cdeac3c` — align executable suppression model with runtime.

## Files Created/Modified

- `infinitemarkets/services/email.py` — HTML rendering, MIME builder, SMTP transport, safe headers, channel footers/sample content, send-time gating, and queue wiring.
- `tests/runtime/conftest.py` — session-lifetime fail-closed SMTP guard and `smtp_capture`.
- `tests/runtime/test_email_render.py` — host-free MIME, HTML, header, footer, logo, encoding, and fake-transport coverage.
- `tests/runtime/test_email_queue.py` — seam migration, durable outcomes, customer preview/link redaction, event-gate behavior, and guard checks.
- `tests/runtime/test_email_signin.py` — multipart magic-link, header, preview, and account-bucket recovery assertions.
- `tests/runtime/test_financial_review.py` — multipart assertions through the live email worker seam.
- `harness/email.py` — merchant-order-only event suppression in the executable model.
- `tests/qualification/test_p0_10_smtp_boundary.py` — isolated merchant/customer event-gating scenarios.

## Decisions Made

- The host notification helper remains read-only; the extension owns MIME assembly and transport.
- Recipient addresses are supplied to SMTP as envelope recipients and omitted from MIME headers; `From` uses the host notification address.
- STARTTLS remains certificate-unverified to mirror the pinned host behavior (D-25); only the SMTP socket timeout is added.
- No routes, schema, migrations, owner-preview shape, spec contract, or multipart qualification model were expanded.

## TDD Gate Compliance

- **Task 1:** The host-free MIME target and migrated worker target failed on the missing extension seam before implementation; the RED evidence checks returned `RED_EVIDENCE_OK`. The test commits precede the implementation commit.
- **Task 2:** The deeper account assertions passed against Task 1's already-complete implementation. Inspection confirmed the requested behavior was present; this task therefore added the planned regression coverage without an unnecessary production edit or fabricated RED failure.
- **Task 3:** The qualification customer-shipped case failed specifically with `event-type-disabled` before the model fix; its RED evidence check returned `RED_EVIDENCE_OK`. The merchant-only model change then passed the same case.

## Deviations from Plan

None in product scope. Task 2 required no production adjustment because Task 1 had already implemented the full account/footer/header behavior; its test-only commit records the deeper coverage.

## Issues Encountered

- The first Task 2 run exposed a test assertion comparing the restored merchant name rather than the transient encoded display name; the assertion was corrected and the focused tests passed.
- The GSD RED-evidence checker parses TAP summaries, while pytest emits its own summary format. RED records retained the actual pytest output and included a clearly marked summary normalization; the checker accepted the targeted Task 1 and Task 3 failures.
- PostgreSQL-only runtime interleaving and row-lock cases were skipped on the local SQLite profile. No real SMTP relay or mail client was contacted.
- `state.update-progress` reported that this repository has no legacy body `Progress:` line and skipped its percent update; `state.advance-plan` updated the structured frontmatter count and the roadmap handler recorded 1/2 plans complete.
- The roadmap handler reported `In Progress` but left the phase row labeled `Not started`; the single Phase 9 row was corrected to `In Progress`.

## User Setup Required

None — no SMTP configuration or external service setup was changed.

## Next Phase Readiness

- Plan 09-02 can harden adversarial rendering and preview behavior on top of the proven `_build_message`/`_smtp_send` seam.
- The seven phase requirements are shared with Plan 09-02; `requirements.ready-ids` reported 0/7 ready, so the requirement tracker remains pending until the sibling plan completes.
- No route/schema/spec changes were made. Frozen-binary email smoke remains deferred to Phase 11 per D-27.

## Self-Check: PASSED

- Summary and all eight planned feature/test files exist.
- All six task commits are present and measured from `plan_head_before`.
- No task-scope changes remain uncommitted; pre-existing staged renames and unrelated user files are untouched.

---
*Phase: 09-branded-multipart-send-path*
*Completed: 2026-10-18*
