---
phase: 05-correctness-recovery-and-security-hardening
plan: "02"
subsystem: payments
status: complete
scope: synthetic-F3-only
commit-status: included-in-parent-local-financial-commit
requires:
  - phase: "05-01"
    provides: Inherited read-only fulfillment/payment/inventory gates; F1 browser gate remains open
provides:
  - Complete coherent live-reservation coverage before new normal settlement consumption
  - Atomic settled/cancelled inventory review and current locked expiry decisions
  - Repeat-safe merchant acceptance with cumulative version1 existing-event accounting evidence
  - Deterministic leaf/variant-parent locking and real PostgreSQL contention regressions
affects: ["05-03", financial-review]
actuals:
  tasks: 3
  commits: 0
tech-stack:
  added: []
  patterns: [order-first settlement, deterministic inventory union locks, cumulative acceptance evidence]
key-files:
  created:
    - tests/runtime/test_catalog_variants.py
    - .planning/phases/05-correctness-recovery-and-security-hardening/05-02-EVIDENCE.json
    - .planning/phases/05-correctness-recovery-and-security-hardening/05-02-RED-01.json
    - .planning/phases/05-correctness-recovery-and-security-hardening/05-02-RED-01-TAP.json
    - .planning/phases/05-correctness-recovery-and-security-hardening/05-02-RED-02.json
    - .planning/phases/05-correctness-recovery-and-security-hardening/05-02-RED-03.json
  modified:
    - infinitemarkets/services/orders.py
    - infinitemarkets/services/settlement.py
    - infinitemarkets/services/checkout.py
    - infinitemarkets/services/catalog.py
    - tests/runtime/test_order_saga.py
    - tests/runtime/test_checkout.py
    - tests/runtime/test_order_admin.py
key-decisions:
  - Only newly authorized accept writes accounting evidence; legacy reason-only/malformed history remains fail closed
  - Incoherent counters retain settled review and own holds rather than guessed counter repair
  - DB-authoritative epochs and bounded parent_confirmation_id event lineage replace the rejected future-timestamp strategy
patterns-established:
  - Live coverage and durable accounting reuse the same normalized all-item map
  - Checkout retains merchant scope; financial callbacks acquire no inverse merchant lock; all stock writers prelock the sorted leaf/parent union
requirements-completed: []
requirements-tested-locally: [HARD-03, PAY-02, INV-01, GAM-02]
duration: 40min
completed: 2026-10-12
---

# 05-02: F3 financial accounting summary

**New verified payment cannot normally confirm unaccounted stock; explicit merchant acceptance records complete cumulative evidence without charging units twice.**

This completes the three approved **local synthetic F3 tasks**, not F1/browser closure, F2, independent financial/security review, a requirement-wide certification or production/release clearance. The parent owns requirement dispositions and commits. Inherited F1 edits and `05-01-PROGRESS.json` were preserved.

## Accomplishments and source map

- `orders.py:178,213,476`: retained F1's read-only fail-closed consumer contract; extracted the accepted-proof parser and normalized item map for producer reuse. No legacy proof synthesis/backfill.
- `orders.py:447,500,517,543,562`: deterministic union locks, exact live coverage, coherent global held/reserved counters and atomic consume/release operations. Finite stock remains nonnegative; unlimited stock stays NULL.
- `settlement.py:280,303`: new settlement checks the entire allocation before any consumption. Safely incomplete coverage commits settled payment plus cancelled/on-hold inventory review and releases own residual holds once. Counter corruption retains holds and explicit high-severity review, without guessing a repair. Independent/reasonless/manual refund holds survive. The already-settled CAS return remains a pure no-op before inventory work.
- `settlement.py:435,473`: expiry selection is a hint. Current order, payment and held deadlines are re-read under the same transaction/order-first convention. Pending allocation expiry cancels with `reservation-expired-before-invoice-attachment` and retains original creating/unknown correlation. Terminal recovered attachment remains nonpayable; no creation-uncertainty clearing was added.
- `settlement.py:743,833`: merchant accept remains verified-paid plus expired/cancelled only. It resolves own residual holds before allocation, reuses consumed evidence and the latest credible cumulative acceptance snapshot, protects other buyers and preserves declared physical backorders/unlimited zero shortfall. The new legitimate transition event atomically records version1 per-item `consumed_qty + accepted_allocated_qty + backordered_qty = quantity`, then verifies the shared predicate before success. Reason-only/malformed/contradictory history rejects without mutation.
- `checkout.py:332,1087` and `catalog.py:326`: stock claims prelock all leaves/parents and publish real reservation changes as well as consume/release/accept changes, including the parent revision/projection. No new schema or dependencies.
- `test_order_saga.py:1321–1720`: permanent missing/partial/extra/expired/corrupt coverage, multi-item/unlimited consumption, independent-hold preservation, expiry interleavings, pending correlation and cumulative/rejected-history acceptance tests.
- `test_catalog_variants.py:54,157`: bounded real PostgreSQL accept/accept and checkout/accept races with two independent backend PIDs, one-unit shortfall fallback, same-order repeat rejection and shared-parent allocation. SQLite uses its actual single-writer topology; it is not represented as PostgreSQL contention.

## RED → GREEN evidence

Every RED below is an intentional assertion in a retained runtime test, not a fixture/import/collection failure. The installed native RED classifier accepts Node TAP only. Real Node `node:test` wrappers ran the exact pytest regression and naturally failed on its actual behavioral assertion; no TAP was fabricated. Native `check tdd-red-evidence` returned `RED_EVIDENCE_OK` for `05-02-RED-01-TAP.json`, `05-02-RED-02.json` and `05-02-RED-03.json`. The initial genuine pytest-only record and its parser rejection remain recorded in `05-02-RED-01.json`.

| Task | Intentional pre-fix result | Final SQLite | Final PG17.9 UTC |
|---|---|---|---|
|01|Missing/partial/extra/expired allocations confirmed instead of cancelled; corrupt counters rolled back verified settlement. 5 failures, exit1, 4.04s.|24 passed /126 deselected, 5.62s, exit0|24 passed /126 deselected, 3.44s, exit0|
|02|Stale attachment candidate released held stock (`expired != held`); expired pending allocation remained payable (`invoice_pending != cancelled`). 2 failed /1 passed, exit1, 3.21s.|32 passed /157 deselected, 7.15s, exit0|32 passed /157 deselected, 5.13s, exit0|
|03|Consumed cancel/reaccept charged stock again (4 vs7); partial/unlimited accept omitted durable proof; residual accept retained reserved3. 4 failed, exit1, 2.87s. Real PG competing accept/checkout produced finite-stock CheckViolation exceptions rather than clean shortfall fallback:2 failed, exit1, 2.36s.|29 passed /125 deselected, 7.69s, exit0|29 passed /125 deselected, 5.19s, exit0|

All task selections have **zero skips** and natural exits. PG warnings are the expected credential-lookup-disabled `/dev/null` password-file warnings. Exact commands, shell/log references, identity and earlier failures/reruns are in `05-02-EVIDENCE.json` and the RED records.

### Combined financial retention

Command:

```text
uv run pytest tests/runtime/test_order_admin.py tests/runtime/test_order_saga.py tests/runtime/test_checkout.py tests/runtime/test_catalog_variants.py tests/runtime/test_public_contract.py tests/runtime/test_nostr_signin.py tests/runtime/test_email_queue.py tests/runtime/test_nip17_inbox.py tests/runtime/test_release_a_journey.py -q --tb=short --show-capture=no
```

- SQLite: **304 passed, 2 skipped**, 43.97s, natural exit0 (`82bfe4`). Both skips are pre-existing PostgreSQL-only email row-lock/rate-bucket drills at `test_email_queue.py:570,602`, not added or masked F3 failures.
- PG17.9: **306 passed, no skips**, 30.05s, natural exit0 (`fd28df`),11 expected password-file warnings.
- Includes unchanged `test_hard01_fresh_accept_retains_authoritative_fulfillment` at `test_order_saga.py:664`: real cancel → FakeWallet settlement → actual accept → fulfillment now passes without synthetic proof substitution. Real accepted physical shortfall also processes, ships and completes; inherited digital-oversold/unproven-history guards pass.
- After the combined run, the expiry test was strengthened to assert genuinely overlapping independent PG backend PIDs. All three exact final task selections above include this test-only enhancement and pass; no subsequent production changes.
- `make lint`: exit0, all checks passed. `node --check infinitemarkets/static/infinitemarkets/js/admin_orders.js`: exit0. Read-only `git diff --check`: exit0. No JS edits made here.

## Deviations and resolved verification issues

1. The plan referenced `test_catalog_variants.py`, which did not exist. Created the required permanent suite reusing the existing real-host saga fixture, without new infrastructure/dependencies.
2. The exact task2 `-k` selection exposed `test_idempotency_crash_resume` depending on earlier tests' hardcoded total3. `test_checkout.py:299` now asserts its own one-order delta, preserving duplicate-order detection in both isolated and combined runs.
3. Existing expiry fixtures in saga/admin had expired still-valid invoices. They now supply their actual persisted invoice deadline. `test_order_admin.py:346` is the sole F3 change in that inherited F1 file; no assertion was relaxed.
4. PG checkout-winning contention correctly caught absent parent publication. Reservation acquisition now bumps/publishes the leaf and parent under the prelocked union, just as release/consume/allocation do. Tests were not weakened.
5. Cumulative accepted events use `max(now, previous_confirmed.created_at + 1)` at `settlement.py:786` so immediate cancel/reaccept produces an unambiguous latest proof without changing historical rows or relaxing F1's ambiguous-history denial. This logical timestamp behavior should be included in parent review.

## Provenance, commits and boundaries

- Main-tree base: `bf99ec0b252f6ecff38eadb377d16d57def3576a`; dirty inherited F1 plus uncommitted F3. Pinned host: `e336fe14b841d6f0c940e75b3d343e3ab5cf8433`. Local macOS, SQLite single process and PostgreSQL17.9 Homebrew; not Linux/ARM64/PG18 matrix equivalence.
- Before destructive fixtures, verified `current_database=infinitemarkets_phase5`, `data_directory=/tmp/infinitemarkets-phase5-pg-1ae80f8/data`, empty listen addresses, timezone UTC and version17.9 using `psql -X`. Only this approved synthetic cluster was used. Parent owns stop/removal; cluster remains running.
- Used `UV_NO_ENV_FILE=1`, `UV_NO_SYNC=1`, `UV_OFFLINE=1`, `TZ=UTC`; SQLite URL explicitly empty; PG exact approved socket DSN and `/dev/null` credential lookup files. FakeWallet and relay I/O off; existing local relay fixtures only.
- **No commits/staging/Git mutations, dependencies, vendor/config/.env/security-policy changes, production/live/real-DB/outgoing/refund operations or new runtime comments.** `ORDER_TRANSITIONS` unchanged. No F2/F4–6/CI01 implementation, no STATE/ROADMAP/REQUIREMENTS/security edits. `make host` was not run because vendor writes are prohibited and the existing pinned checkout was verified read-only.

## Remaining gates and handoff

- F1's generic browser no-pageerror gate remains **OPEN**: unchanged pinned-host ServiceWorker TLS and null `g.wallet.id` websocket errors. Not patched, filtered, security-relaxed, or claimed closed. Parent coordinates F1 closure.
- F2 remains unimplemented and belongs to the next parent-coordinated tranche step. Incidental invoice-creation uncertainty remains active here.
- Independent financial/code/security review pending; source-prohibition markers are not machine-clearance claims. Requirements dispositions and parent-reviewed commits remain parent-owned.
- **HISTORICAL-PAID-ORDER-AUDIT: OPEN / NOT AUTHORIZED / NOT PERFORMED. Actual-record evidence NONE; historical disposition NOT DONE. Production exposure, real-record disposition and release clearance BLOCKED** pending separately approved operator audit/review. No legacy sweep or automatic repair was performed.
- Live Plebeian gate remains separately unauthorized/unperformed. Full DB/install/known-hang checks, conformance, browsers and four Linux qualification profiles were not run; focused financial evidence does not close CI01/HARD08 or release/security gates.
- Stop after F3. Parent owns exact approved PG cleanup, F1 closure, review, commits and F2 coordination.

## Self-check

**PASS for the three scoped F3 task checks and combined financial retention; broader gates remain unverified/open as listed.** No completed requirement or production readiness is asserted by this plan artifact.

## Parent financial-tranche closeout

The preceding executor counts and source locations are historical F3 evidence,
not the final tree. Independent review rejected the timestamp increment in
deviation 5 above; it was removed, not accepted or waived. Current accepted
proof uses bounded, strictly typed causal event-ID lineage and DB-authoritative
epochs. Merchant NO KEY UPDATE serialization addresses the implicit PostgreSQL
foreign-key lock cycle; all live deadline checks refresh time after required
locks and verification prerequisites. Missing immutable payment identity fails
closed. Gamma, public, history and resume invoice exposure share locked payable
authority.

Final ten-file financial retention: **433 passed / 6 PostgreSQL-only skips on
SQLite; 439 passed / no skips on PostgreSQL**, natural exit 0. Parent separately
re-ran the review file: **83 passed / 4 PG-only skips; 87 passed / no skips**.
Lint, JS syntax and buyer hard02 (one test, three scenarios) pass.
`05-FINANCIAL-REVIEW-FIXES.json` retains exact commands, hashes and RED/GREEN
history; `05-REVIEW.md` independently passes the finite source scope, including
CR-01–06 and WR-02. Source pass is not qualification or release clearance.

F2 is now implemented, not pending implementation as in the original handoff.
F1 host-browser qualification and F2 browser test-first chronology remain open;
WR-04 records a pre-existing in-flight token-revocation follow-up, not waived.
No actual historical records were accessed or repaired: operator audit remains
OPEN / NOT AUTHORIZED / NOT PERFORMED, evidence NONE. Production exposure,
record disposition and release remain BLOCKED. F4–F6, CI-01, broader matrix and
live qualification are not executed. Parent commits locally and pauses.
