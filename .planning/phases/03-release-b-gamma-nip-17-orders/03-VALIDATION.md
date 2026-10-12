---
phase: "03"
slug: "release-b-gamma-nip-17-orders"
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: validated
nyquist_compliant: false
wave_0_complete: true
created: "2026-09-27"
---

# Phase 03 — Validation Strategy

> Retrospective map completed 2026-10-11. Infrastructure exists; current coverage remains partial because F1–F3/F5/F6 need permanent regressions and live UAT is pending.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (uv-locked env) + Playwright/Chromium (Node 22 or 24 only) |
| **Config file** | `pyproject.toml`, `Makefile`, `tests/e2e/playwright.config.ts` |
| **Quick run command** | `make verify-fast` |
| **Full suite command** | `make verify-runtime` once per SQLite/PostgreSQL profile + separate supported-Node Playwright suite |
| **Estimated runtime** | ~90–300 seconds |

---

## Sampling Rate

- **After every task commit:** Run `make verify-fast`
- **After every plan wave:** Run `make verify-runtime`
- **Before `/gsd-verify-work`:** Full suite must be green (SQLite + PostgreSQL + browser)
- **Max feedback latency:** 300 seconds

---

## Per-Task Verification Map

*The original empty template is replaced with actual plan/test links. Historical passing suites are not current clearance of the newly discovered boundary defects.*

| Tasks | Requirements | Threats / behavior | Existing automated coverage | Current disposition |
|---|---|---|---|---|
| 03-01 tasks 1–3 | GAM-01, GAM-04, GAM-05 | T-301-01–07: activation, wrap validation, transport/AUTH/egress | `test_inbox_activation.py`, `test_keystore_nip17.py`, `test_inbox_transport.py` | Existing coverage; same-scope admission still requires F6 |
| 03-02 task 1 | GAM-02, GAM-03 | T-302-02/05: canonical checkout, payment truth | `test_nip17_inbox.py`, `test_release_b_journey.py` | Shared financial boundaries reopened by F1–F3 |
| 03-02 task 2 | GAM-03 | Inbound message semantics; independent delivery copies | `test_nip17_inbox.py`, `test_nip17_outbox.py` | No-route deadline/budget regression missing (F5) |
| 03-02 task 3 | GAM-04 | T-302-01/04/06/07: intake, mute, retention, bounds | `test_intake_abuse.py`, `test_release_b_drills.py` | Atomic per-scope backlog regression missing (F6) |
| 03-03 tasks 1–5 | GAM-02–04 | T-303-01–08: session/claim scoping, modes, Messages | `test_nostr_signin.py`, `test_storefront_modes.py`, `test_admin_ui.py`, `tests/e2e/{buyer,admin}.spec.ts` | Existing account/mode/UI coverage; historical browser results only in this closeout |
| 03-04 tasks 1–2, 4 | GAM-05 | T-304-01–06: gated relay, overload, external-client evidence | `test_release_b_drills.py`, `tests/conformance/run_matrix.sh matrix` | F6 and live checkout remain open; scripted matrix is not a live payment pass |

Runtime filenames above are under `tests/runtime/`. Locked decision checkpoints
in 03-03/03-04 are documented choices, not missing product features.

---

## Wave 0 Requirements

- [x] `tests/runtime/test_nip17_inbox.py` — durable inbox processing (dedup, cursors, crash recovery)
- [x] `tests/runtime/test_nip17_outbox.py` — dual-copy order_msg publication evidence
- [x] `tests/runtime/test_nostr_signin.py` — NIP-07 challenge/session, order list, claiming
- [x] `tests/runtime/test_storefront_modes.py` — four-mode gating invariants
- [x] `tests/runtime/test_intake_abuse.py` — rejected intake, mute, per-author caps
- [x] `tests/e2e/` additions — Messages surface, shop-mode panel, sign-in flows

All listed Wave 0 artifacts exist; the new boundary regressions are tracked in Phase 5.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live plebeian.market smoke run | GAM-05 | External live instance; pinned-clone matrix is scripted | Documented smoke checklist in conformance report |
| Public-relay conformance run | GAM-05 | Real-world relay behavior non-deterministic | Documented run recorded into phase verification |

These rows describe the same carried live external checklist, not two newly invented build tasks.

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [ ] Current feedback latency revalidated after CI-01 is repaired; historical estimates are not a guarantee
- [ ] Current boundary coverage complete; `nyquist_compliant` remains false until Phase 5 regressions and required external evidence pass

**Approval:** partial coverage audit, 2026-10-11. Existing Wave 0 files are no longer open build tasks; missing regression cases and live UAT remain real open work.
