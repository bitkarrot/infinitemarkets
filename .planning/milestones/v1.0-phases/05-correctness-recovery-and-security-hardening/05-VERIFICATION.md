---
phase: 05-correctness-recovery-and-security-hardening
status: passed
reconciled: 2026-10-13 — all open gates closed or operator-disposed (live UAT, paid-order audit, F1 limitation, WR-01 caveat)
created: 2026-10-12
---

# Phase 5 — Verification Record

Repaired-revision evidence matrix. Every row cites actual executed evidence;
local synthetic verification never substitutes for an operator or live gate.

## Requirement / evidence matrix

| Req | Claim | Status | Evidence |
|---|---|---|---|
| HARD-01 | Merchant status/fulfillment requires verified payment + inventory authority; cancellation releases reservations once | ✅ VERIFIED | `orders.py` `fulfillment_authorized`/`payment_settled`/`inventory_accounted` + `_cancel_order_in_tx`; regressions in `test_order_saga.py`, `test_order_admin.py`, `test_public_contract.py`, `test_financial_review.py`; financial ten-file selection 433p/6s SQLite, 439p/0s PG; independent review CR-01–04 resolved (`05-REVIEW.md`) |
| HARD-02 | Recovered invoice timeout becomes fulfillable after verified settlement; independent holds preserved | ✅ VERIFIED | `settlement.py`/`checkout.py` pure-creation-uncertainty resolution, strict snapshot correlation, hold-aware invoice suppression; `test_financial_review.py` hard02 cases; buyer `hard02` browser regression green (3 scenarios) |
| HARD-03 | Settlement requires complete live reservation coverage or takes the explicit review path | ✅ VERIFIED | `settlement.py` coverage gate + cancelled inventory-review lane; `test_order_saga.py` missing/partial/extra/corrupt coverage battery; `test_catalog_variants.py` real PG contention |
| HARD-04 | Dependencies require the intended revision or a proved same-scope replacement | ✅ VERIFIED | `outbox.py:_deps_published` bound to joined row (merchant/aggregate/kind, published, rev≥intent); `relay.py:prune_outbox` fixpoint protection; `test_outbox.py`/`test_catalog_events.py` hard04 cases; 05-04 RED records |
| HARD-05 | No-route waits stay claimable for the documented 48h without consuming send budget | ✅ VERIFIED | `outbox.py` `_cas_state(bump_attempts=False)` on no-route requeue; `test_nip17_outbox.py::test_hard05_*` controlled-time coverage (21 waits → deliver; exact deadline terminal; real failures still exhaust) |
| HARD-06 | Atomic 1,000 pending-wrap bound per merchant/relay before decrypt | ✅ VERIFIED | `inbox.py` locked count+insert in one DomainTransaction (PG `FOR NO KEY UPDATE`; SQLite writer serialization); `m016_inbox_scope_backlog` index; `test_intake_abuse.py` hard06 cap + contested-999 proofs; `test_release_b_drills.py` rollover |
| HARD-07 | DB/install pair exits cleanly in both orders and within the normal suite | ✅ VERIFIED | Root cause demonstrated (cancelled engine checkout orphaned non-daemon aiosqlite worker thread); `tasks.py:_guarded` shield+drain; `tests/test_runtime_process_exit.py` bounded child regression; `make verify-runtime`/`make verify` natural exit 0 |
| HARD-08 | Permanent regressions + fresh qualification + security review + required live evidence | ✅ VERIFIED | Regressions permanent; local `make verify` green (982/8 SQLite, 987/3 PG); **four-profile Linux CI green on `eaf7d64`** (run 38322792120); independent review PASSED; live external checkout evidence recorded 2026-10-13 (wrap→order→invoice→settlement→status over public relays) — see open gates for residual host/procedural items |

## Open gates (not closed by this record)

- **Live Plebeian checkout/payment UAT — CLOSED 2026-10-13.** Full public-relay
  run executed on `schedulerlnbits.exe.xyz` (v0.6.3): Playwright-driven live
  plebeian.market checkout, wrap `f2f378dd273d0142` processed via `nos.lol`,
  gamma order `afa3499b59fe…` confirmed after internal bolt11 settlement, type-2
  and type-3 wraps verified dual-copy on buyer-declared relays. Complete
  evidence in `03-VERIFICATION.md` + `03-UAT.md` item 17 + conformance run log.
- **F1 pinned-host browser errors — DISPOSED 2026-10-13, operator-accepted
  documented host limitation.** Reproduced live on the pinned host `e336fe14`
  (v1.6.2-rc1) via `tests/e2e` admin spec: every functional assertion passed
  (settlement, controls, no token leak); the only failure is
  `expect(errors).toEqual([])` collecting two upstream host defects — (a)
  `SecurityError` ServiceWorker registration fails because the e2e harness
  serves a throwaway self-signed cert (`tools/e2e_server.py` `ssl_certfile`)
  and the deployed exe.dev proxy also presents a self-signed cert; (b)
  `TypeError: null.id` in `lnbits-manage-wallet-list.js:55` —
  `this.g.wallet.id` is unguarded on non-wallet pages when a payment websocket
  message arrives. **Both are unfixed upstream on LNbits `main` (`b717d51d`
  HEAD checked 2026-10-13)** — a host-version bump does not resolve them, and
  extension admin functionality is verified unaffected. **Operator accepted
  in writing 2026-10-13** as a documented host limitation; no pageerror
  filtering, security weakening, or vendor workaround was applied.
- **WR-01 chronology caveat — DISPOSED 2026-10-13, operator-accepted
  permanent caveat.** Original browser RED for the F2 path was reproduced
  retrospectively; test-first chronology evidence is absent and cannot be
  fabricated. **Operator accepted in writing 2026-10-13**: the honesty note
  remains permanently recorded in `05-REVIEW.md` and
  `05-BROWSER-BASELINE-EVIDENCE.json`; actual regression coverage and
  independent review stand on their own.
- **Historical paid-order audit — PERFORMED 2026-10-13 on the deployed
  instance.** Read-only scan of `ext_infinitemarkets.sqlite3` +
  `database.sqlite3` on `schedulerlnbits.exe.xyz`: 14 orders total, all on the
  demo Node Report at 210 sats; all contacts are `example.com` placeholders or
  empty; buyer PII columns are envelope-encrypted at rest; 9 successful
  "Infinitemarkets order" inbound wallet payments (1,890 sats) are internal
  test settlements including today's live UAT order; all other wallet inflows
  are funding/test memos ("Admin credit", ZapGoals E2E, "LNbits"). 5 settled
  payment rows attached to cancelled/expired orders are the designed
  late-settlement projection retention. **Zero real-customer paid orders; no
  exposure concern.**
- **WR-04/WR-05** — resolved (`eaf7d64` locked token recheck; `tasks.py`
  drain preserves cancellation). See `05-REVIEW.md`.

## Release posture

v0.6.3 cut 2026-10-12 with the open gates above documented in the release
notes; the milestone-closing product release is **v1.0.0** (2026-10-13). As of 2026-10-13 every open gate is closed or dispositioned: live UAT
executed and passed, paid-order audit performed on the deployed instance,
F1 host-browser errors and WR-01 chronology caveat accepted in writing by
the operator as documented residual limitations.
