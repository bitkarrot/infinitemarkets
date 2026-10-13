---
phase: 05-correctness-recovery-and-security-hardening
plan: "04"
status: complete
recorded: 2026-10-13
requirements-completed: [HARD-04, HARD-05]
requirements-repaired: [CAT-02, PUB-01, GAM-03, GAM-04]
---

# 05-04 — F4 revision-bound dependencies + F5 no-route recovery

Outbox dependency satisfaction is bound to the intended publication revision
(or a proved same-scope replacement), `relay.py:prune_outbox` protects the
dependency fixpoint, and no-route intents remain claimable for the documented
48-hour window without consuming the ordinary failed-send budget
(`_cas_state(bump_attempts=False)`). Independently reviewed; regressions on
both DB profiles (`test_outbox.py`, `test_catalog_events.py`,
`test_nip17_outbox.py::test_hard05_*`).

Governing record: [05-VERIFICATION.md](05-VERIFICATION.md), progress file
`05-04-PROGRESS.json`, RED records `05-04-RED-*.json`.
