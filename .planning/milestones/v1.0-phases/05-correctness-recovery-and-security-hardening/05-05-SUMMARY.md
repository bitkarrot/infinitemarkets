---
phase: 05-correctness-recovery-and-security-hardening
plan: "05"
status: complete
recorded: 2026-10-13
requirements-completed: [HARD-06, HARD-07]
requirements-repaired: [GAM-04, GAM-05, SEC-01]
---

# 05-05 — F6 atomic inbox admission bound + CI-01 process-exit fix

Inbox admission enforces the 1,000-pending-wrap bound per merchant/relay
atomically inside one DomainTransaction (PG `FOR NO KEY UPDATE`, SQLite
writer serialization) with the `m016_inbox_scope_backlog` index;
concurrency and rate-window contention regressions cover the boundary
(`test_intake_abuse.py` hard06 cases, `test_release_b_drills.py` rollover).

CI-01: the DB/install pytest hang root cause was demonstrated — a cancelled
engine checkout orphaned a non-daemon aiosqlite worker thread — and fixed
(`tasks.py:_guarded` shield+drain) with a bounded subprocess regression
(`tests/test_runtime_process_exit.py`); `make verify-runtime` / `make verify`
exit 0 naturally in both file orders.

Governing record: [05-VERIFICATION.md](05-VERIFICATION.md), progress file
`05-05-PROGRESS.json`, RED records `05-05-RED-*.json`.
