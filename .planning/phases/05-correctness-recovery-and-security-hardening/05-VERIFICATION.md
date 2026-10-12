---
phase: 05-correctness-recovery-and-security-hardening
status: gates_partially_closed
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
| HARD-08 | Permanent regressions + fresh qualification + security review + required live evidence | ⚠️ PARTIAL | Regressions permanent; local `make verify` green (982/8 SQLite, 987/3 PG); **four-profile Linux CI green on `eaf7d64`** (run 38322792120); independent review PASSED. Live external checkout evidence deferred by operator decision — see open gates |

## Open gates (not closed by this record)

- **Live Plebeian checkout/payment UAT — DEFERRED 2026-10-12 by operator
  decision.** UAT item 17 remains outstanding; release v0.6.3 was cut with this
  explicitly documented limitation. Scripted/shim/FakeWallet evidence is not a
  substitute; the item is deferred, not passed or waived.
- **F1 pinned-host browser errors** — ServiceWorker TLS + null `g.wallet.id`
  websocket errors on the admin surface, reproduced on the unmodified baseline
  host; unresolved host-qualification issue. No filtering or vendor workaround.
- **WR-01 chronology caveat** — original browser RED for the F2 path was
  reproduced retrospectively; test-first chronology evidence is absent.
- **Historical paid-order audit** — authorized read-only scan of every
  reachable local datastore found **zero actual order records**; a
  deployed/remote instance (if any) still requires its own operator audit.
- **WR-04/WR-05** — resolved (`eaf7d64` locked token recheck; `tasks.py`
  drain preserves cancellation). See `05-REVIEW.md`.

## Release posture

v0.6.3 cut 2026-10-12 with the open gates above documented in the release
notes. Milestone closeout stays open until the deferred live UAT is performed
or the operator formally accepts the residual risk in writing here.
