---
phase: 05-correctness-recovery-and-security-hardening
plan: "06"
status: complete
recorded: 2026-10-13
requirements-completed: [HARD-08]
requirements-repaired: [GAM-05]
---

# 05-06 — Qualification, security review and operator/live gates

Fresh repaired-revision qualification recorded: `make verify` green on both
profiles (SQLite 982 passed/8 skipped, PG 987 passed/3 skipped); four-profile
Linux CI green on `eaf7d64` (run 38322792120); independent ASVS1 review
passed (`05-REVIEW.md`, `05-SECURITY.md`).

External/operator gates reconciled 2026-10-13:

- **Live Plebeian checkout/payment** — executed on
  `schedulerlnbits.exe.xyz` (v0.6.3) over public relays via Playwright:
  buyer wrap `f2f378dd273d0142` processed on `nos.lol`; gamma order
  `afa3499b59fe…` confirmed after internal bolt11 settlement; type-2 and
  type-3 wraps verified dual-copy on buyer-declared relays. Evidence:
  `03-VERIFICATION.md`, `03-UAT.md` item 17, `tests/conformance/README.md`
  run log.
- **Historical paid-order audit** — read-only scan of the deployed
  instance's `ext_infinitemarkets.sqlite3` + `database.sqlite3`: 14 orders,
  all demo-product test activity, zero real-customer paid orders; PII
  envelope-encrypted. Disposition recorded in `05-VERIFICATION.md`.
- **F1 pinned-host browser errors** — diagnosed as two upstream LNbits
  defects (untrusted-cert ServiceWorker registration, unguarded
  `g.wallet.id`), unfixed on upstream `main`; operator-accepted documented
  limitation.
- **WR-01 chronology caveat** — operator-accepted permanent honesty note.

Milestone audit updated `gaps_found` → `passed` in
`.planning/v1.0-MILESTONE-AUDIT.md`. Governing record:
[05-VERIFICATION.md](05-VERIFICATION.md).
