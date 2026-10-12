---
phase: "02"
slug: "release-a-safe-web-commerce"
status: validated
nyquist_compliant: false
wave_0_complete: true
created: "2026-09-27"
validated: "2026-09-27"
---

# Phase 2 — Validation Strategy

> Historical 2026-09-27 coverage map. Current validation is partial: F1–F4 require permanent runtime regressions in Phase 5; test-file presence and earlier green runs do not close those gaps.

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Frameworks** | pytest 9.x + pytest-asyncio; Playwright 1.63 Chromium |
| **Node policy** | Node 22.22.3 is pinned locally; browser tooling accepts only Node 22.x or 24.x and CI action runtimes use Node 24 |
| **Config** | `pyproject.toml`, `.nvmrc`, `tests/e2e/package.json`, `tests/e2e/playwright.config.ts` |
| **Quick run** | `make verify-runtime` |
| **Canonical full run** | `make verify` |
| **Browser run** | `cd tests/e2e && npx playwright test` against `tools/e2e_server.py` |
| **Current Linux evidence** | CI run 36352552899 on `021c402`: SQLite 450 passed/3 skipped; PostgreSQL 451 passed/2 skipped on x86_64 and ARM64 |
| **Feedback latency** | Focused runtime files complete in seconds; canonical Linux profiles complete in about 2.5 minutes |

## Sampling Rate

- **After a task change:** run its focused runtime file and `make lint`.
- **After a plan wave:** run `make verify-runtime`; include Playwright when a public/admin surface changed.
- **Before UAT or phase completion:** run canonical SQLite/PostgreSQL qualification, current browser tests and lint.
- **No watch-mode command** is accepted as release evidence.

## Per-Task Verification Map (historical)

| Task ID | Plan | Wave | Requirements | Threat refs | Automated evidence | Status |
|---------|------|------|--------------|-------------|--------------------|--------|
| 02-01-01 | 01 | 1 | MERC-01 | T-201-06 | `tests/runtime/test_install.py`, `test_db.py` | green |
| 02-01-02 | 01 | 1 | MERC-01, SEC-01 | T-201-01, T-201-02 | `tests/runtime/test_crypto_keystore.py`, `test_merchant_api.py`, `test_relay_config_api.py` | green |
| 02-01-03 | 01 | 1 | CAT-01, CAT-02 | T-201-03–05 | `tests/runtime/test_catalog_api.py`, `test_catalog_events.py` | green |
| 02-02-01 | 02 | 2 | PUB-01 | T-202-02–04, T-202-07 | `tests/runtime/test_outbox.py`, `test_catalog_events.py` | green |
| 02-02-02 | 02 | 2 | WEB-01 | T-202-01, T-202-06 | `tests/runtime/test_nip89.py`, `test_public_pages.py` | green |
| 02-02-03 | 02 | 2 | UI-01, UI-03, SEC-01 | T-202-05 | `tests/runtime/test_themes.py`, `test_public_pages.py` | green |
| 02-03-01 | 03 | 3 | WEB-02, PAY-01, INV-01 | T-203-01, T-203-04 | `tests/runtime/test_checkout.py`, `test_status_api.py`, `test_db.py` | green |
| 02-03-02 | 03 | 3 | PAY-02, NOTF-01, SEC-01 | T-203-03, T-203-05, T-203-07 | `tests/runtime/test_order_saga.py`, `test_email_queue.py` | green |
| 02-03-03 | 03 | 3 | ORD-01, WEB-02, SEC-01 | T-203-02, T-203-06 | `tests/runtime/test_order_admin.py`, `test_public_contract.py` | green |
| 02-04-01 | 04 | 4 | UI-01, UI-03 | T-204-03, T-204-04 | `tests/runtime/test_admin_ui.py`, `test_themes.py`, `tests/e2e/admin.spec.ts` | green |
| 02-04-02 | 04 | 4 | WEB-02, UI-01 | T-204-01, T-204-05 | `tests/runtime/test_buyer_ui.py`, `test_public_contract.py`, `tests/e2e/buyer.spec.ts` | green |
| 02-04-03 | 04 | 4 | PUB-02, ORD-01, NOTF-01, UI-02 | T-204-02 | `tests/runtime/test_release_a_journey.py`, `test_admin_ui.py`, `tests/e2e/admin.spec.ts` | green |
| UAT-DELIVERY | post-plan | closeout | WEB-01, PAY-02, SEC-01 | T-205-01 | `test_order_saga.py::test_digital_delivery_revealed_only_after_confirmed_payment`, public-contract tests, `buyer.spec.ts` | green |

Every Phase 2 requirement—MERC-01, CAT-01/02, PUB-01/02, WEB-01/02, PAY-01/02, INV-01, ORD-01, NOTF-01, SEC-01 and UI-01/02/03—has behavioral automated coverage in the current 450/451-test qualification tree. The browser layer adds 19 current Chromium journeys; human UAT passed 3/3.

## Wave 0 Requirements

Original test infrastructure exists. Phase 5 must add the missing negative-path cases; existing fixture/runner availability does not establish complete regression coverage.

## Manual-Only Verifications

No Phase 2 requirement is manual-only. Human UAT supplements automated verification for perceived clarity, responsive usability and visual acceptance; it does not substitute for payment, privacy, inventory or state-machine tests.

## Validation Audit — 2026-09-27

| Metric | Count |
|--------|-------|
| Phase 2 requirements | 16 |
| Requirements with automated behavioral coverage | 16 |
| Missing or partial coverage gaps | 0 |
| Manual-only requirements | 0 |

## Validation Sign-Off

- [x] Every task has an automated verification command and existing behavioral tests.
- [x] Sampling continuity is maintained across all four waves.
- [x] No Wave 0 dependency remains.
- [x] No watch-mode flags are used for release evidence.
- [x] Current SQLite/PostgreSQL Linux x86_64/ARM64 qualification is green.
- [ ] Current regression coverage is complete; F1–F4 remain open and `nyquist_compliant` is false.

**Historical approval:** validated 2026-09-27. **Current status (2026-10-11): partial**; the historical green rows do not cover the newly reproduced F1–F4 boundaries.

## Reopened coverage

| Finding | Missing permanent regression | Remediation owner |
|---|---|---|
| F1 | Unpaid merchant confirmation must fail; every cancellation path releases held stock once; token and authenticated-history delivery remain locked | HARD-01 |
| F2 | Creation timeout, invoice recovery and verified settlement resolve only the originating uncertainty | HARD-02 |
| F3 | Settlement after expiry/release checks all item quantities before confirmation | HARD-03 |
| F4 | Published revision 1 cannot satisfy a dependency on pending revision 2 | HARD-04 |

See Phase 5's validation contract for DB/profile and security closure requirements.
