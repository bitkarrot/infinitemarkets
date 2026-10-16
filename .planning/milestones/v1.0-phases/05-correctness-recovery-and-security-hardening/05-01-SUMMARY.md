---
phase: 05-correctness-recovery-and-security-hardening
plan: "01"
status: complete
recorded: 2026-10-13
requirements-completed: [HARD-01]
requirements-repaired: [ORD-01, SEC-01, PAY-02, INV-01, GAM-02]
---

# 05-01 — F1 merchant command authority

Merchant status/fulfillment commands now require verified payment authority and
complete inventory accounting; cancellation releases reservations exactly once.
Source implemented in the authorized F1 financial tranche, independently
reviewed (CR-01–04 resolved, `05-REVIEW.md`), regression-covered on SQLite and
PostgreSQL (`test_order_saga.py`, `test_order_admin.py`,
`test_public_contract.py`, `test_financial_review.py`; commits `3c0c237`,
`5f48bd9`, `eaf7d64`).

**Residual disposition:** the plan's pinned-host admin no-pageerror
qualification remained open at execution time. Reproduced 2026-10-13 on the
unmodified pinned host `e336fe14` (v1.6.2-rc1): every functional assertion
passed; the only collected pageerrors are two upstream host defects —
untrusted-cert ServiceWorker registration and unguarded `g.wallet.id` in
`lnbits-manage-wallet-list.js` — both unfixed on LNbits `main` (`b717d51d`).
The operator accepted this as a documented host limitation on 2026-10-13; no
pageerror filtering, security weakening or vendor workaround was applied.

Governing record: [05-VERIFICATION.md](05-VERIFICATION.md), progress file
`05-01-PROGRESS.json`.
