---
phase: "05"
slug: correctness-recovery-and-security-hardening
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-10-11
---

# Phase 5 — Regression and Release Validation Contract

No implementation plans or permanent F1–F6 regressions have been written yet.
Existing passing suites do not close the failures reproduced by temporary probes.
Use disposable databases/FakeWallet for automated work, not live customer data.

| Requirement | Required negative-path regression / gate | Existing test surface to extend | Status |
|---|---|---|---|
| HARD-01 | Unpaid merchant confirmation rejected and delivery locked; cancellation releases stock exactly once through every API path | `test_order_admin.py`, `test_order_saga.py`, `test_public_contract.py`, `test_nip17_inbox.py` | Pending |
| HARD-02 | External invoice created then response timeout; recover/settle without duplicate invoice or stale uncertainty; preserve independent exceptions | `test_order_saga.py` | Pending |
| HARD-03 | Reservations expire before recovered settlement; all quantities must be consumed/reallocated or held as exception, including duplicate/concurrent callbacks | `test_order_saga.py`, `test_checkout.py` | Pending |
| HARD-04 | Revision 1 published, required revision 2 pending; supersession and tombstone/reference ordering | `test_outbox.py`, `test_catalog_events.py` | Pending |
| HARD-05 | >20 route waits, route appears inside 48h, deterministic exact deadline, separate failed-send budget, independent sender/recipient copies | `test_nip17_outbox.py` | Pending |
| HARD-06 | At depth 999 two concurrent same-scope admissions admit at most one; row 1001 rejected, other scopes unaffected, minute resets cannot bypass bound | `test_intake_abuse.py`, `test_release_b_drills.py` | Pending |
| HARD-07 | Both DB/install file orders and normal runtime suite finish with exit 0; no hang masking or forced-exit success | `test_db.py`, `test_install.py`, test fixtures | Reproduced open CI-01 |
| HARD-08 | Repaired-revision qualification, relevant browser/conformance, ASVS review and required live UAT; reopen/close original requirements explicitly | Existing CI matrix, browser specs and conformance checklist | Pending |

Runtime filenames above are under `tests/runtime/`. Use controlled time in
no-route tests rather than waiting 48 hours. Concurrency tests must prove
admission/stock invariants, not serialize away the contested interleaving.

## Execution checks

- For each repair: first retain a failing regression, implement the smallest
  domain fix, then rerun its focused test files and `make lint`.
- Run `make verify-runtime` and applicable `make verify-db` / `make verify-protocol`
  checks during implementation. Treat process termination and exit status as part
  of success; printed passing assertions do not close CI-01.
- At release review: `make verify` on the existing four Linux x86_64/ARM64 ×
  SQLite/PostgreSQL profiles; it emits durable evidence. Preserve provenance and
  classify skips explicitly. Focused runs must not overwrite full-profile evidence.
- Browser checks are separate: Node 22/24 per `tests/e2e/package.json`, then
  `cd tests/e2e && npx playwright test` against the disposable `tools/e2e_server.py`
  setup. `make verify` does not itself run Playwright.
- Run the documented `tests/conformance/run_matrix.sh matrix` from its directory
  for scripted interoperability; keep its local relay/FakeWallet/shim scope clear.
- Re-audit ASVS mitigations using `05-SECURITY.md`; include post-Phase-2 account,
  key-export, embed, import/media and relay-management surfaces.

## Manual gate carried from Phase 3

UAT item 17 is the live Plebeian public-relay checkout/payment smoke. Obtain
operator authorization for external writes/funds first, then record revision,
date, environment, order correlation and redacted wrap/ACK/settlement outcomes
in `03-VERIFICATION.md` and update `03-UAT.md` only from actual evidence.
Do not mark it passed, skipped-as-success or waived to close the milestone.

## Sign-off

- [ ] F1–F6 permanent regressions and fixes pass in supported profiles.
- [ ] CI-01 has a clean process-exit regression in both file orders.
- [ ] Browser/conformance and security evidence are current and precisely scoped.
- [ ] Required live external gate passes with recorded operator-approved evidence.
- [ ] Original reopened requirements, security rows, UAT and milestone audit reconciled.
- [ ] `nyquist_compliant` and security closure are set only after the evidence exists.
