---
phase: "05"
slug: correctness-recovery-and-security-hardening
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-10-11
---

# Phase 5 — Regression and Release Validation Contract

Six implementation plans are authored; permanent regressions and runtime fixes
are not implemented by planning. Existing passing suites do not close temporary
probe failures. Only 05-01→05-02→05-03 (F1→F3→F2) may execute now, followed by
independent review and a mandatory pause. 05-04–06 require new approval regardless
of config auto_advance. Use synthetic isolated databases/FakeWallet, never live
customer data. See 05-PATTERNS.md for safe environment and RED evidence rules.

| Requirement | Required negative-path regression / gate | Existing test surface to extend | Status |
|---|---|---|---|
| HARD-01 | Unpaid confirmation denied; settled+paid-state+no-exception missing/partial durable accounting blocks token/history/email and processing/completed/shipping without mutation; cancellation atomic | `test_order_admin.py`, `test_order_saga.py`, `test_public_contract.py`, `test_nip17_inbox.py` | Pending |
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

## Exact per-task validation mapping

Run commands from repo root unless stated; `uv run pytest` inherits parent-set
UV_NO_ENV_FILE=1, UV_NO_SYNC=1 and UV_OFFLINE=1. No dependency installation or
.env reads. Run all DB-sensitive selections twice: fresh isolated SQLite with
empty LNBITS_DATABASE_URL, and only the approved parent-created socket-only PG17
cluster `/tmp/infinitemarkets-phase5-pg-1ae80f8` synthetic database. Parent verifies
identity before destructive fixtures and owns exact-cluster teardown afterward.
Never run fixtures against existing DBs. Node22/24 + already installed Playwright
only; browser commands workdir `tests/e2e`, matrix workdir `tests/conformance`.

| Task ID | Wave | Req | Permanent target / intended baseline assertion direction | Automated command | Status |
|---|---:|---|---|---|---|
|05-01-01|1|HARD-01|`test_hard01_unpaid_status_cannot_unlock_delivery` plus settled/no-exception missing/partial consumption status/token tests: baseline200/exposed content vs422/empty; read-only shared inventory_accounted/fulfillment_authorized, actual healthy consumed positive|`uv run pytest tests/runtime/test_order_admin.py tests/runtime/test_public_contract.py -k 'hard01 or transition_matrix or end_to_end_journey' -q`|Pending RED/GREEN|
|05-01-02|1|HARD-01|Status cancel retains stock; unpaid OR settled/no-exception absent/partial consumed proof exposes token/history/email or permits completion/shipping. Permanent all-paid-state negatives snapshot unchanged flags/states/counters/audit; consumed/credible explicit accepted physical-backorder positives|`uv run pytest tests/runtime/test_order_saga.py tests/runtime/test_nostr_signin.py tests/runtime/test_email_queue.py tests/runtime/test_nip17_inbox.py -q`|Pending RED/GREEN|
|05-01-03|1|HARD-01|Browser actionable unpaid/held fulfillment vs required no action; real paid journey remains usable|`uv run pytest tests/runtime/test_release_a_journey.py -q`; `node --check infinitemarkets/static/infinitemarkets/js/admin_orders.js`; `cd tests/e2e && npx --no-install playwright test admin.spec.ts --grep 'orders\|order states\|hard01'`|Pending runtime/browser|
|05-02-01|2|HARD-03|`test_hard03_missing_coverage_settles_into_inventory_review`: baseline unaccounted confirmed vs settled/cancelled/review/residual-release|`uv run pytest tests/runtime/test_order_saga.py -k 'hard03 or settlement_confirms_once or digital_delivery or duplicate_attachment' -q`|Pending RED/GREEN|
|05-02-02|2|HARD-03|Stale expiry selection releases newly aligned holds; expired invoice_pending allocation stays payable vs current locked deadlines/cancelled correlation|`uv run pytest tests/runtime/test_order_saga.py tests/runtime/test_checkout.py -k 'hard03 or expiry or reconcile or crash or settlement' -q`|Pending RED/GREEN|
|05-02-03|2|HARD-03|Residual hold/reaccept double-decrement/missing publication/competing allocation; new legitimate accept writes cumulative existing-event detail proof consumed+allocated+backordered=quantity, shared all-consumer integration; unlimited backordered0 stays positive|`uv run pytest tests/runtime/test_order_saga.py tests/runtime/test_catalog_variants.py -k 'hard03 or late_settlement or settlement or variation' -q`|Pending RED/GREEN SQLite+PG|
|05-03-01|3|HARD-02|`test_hard02_recovered_original_invoice_is_payable_and_fulfillable`: recovered pure hold remains blocked vs usable original invoice then accounted delivery|`uv run pytest tests/runtime/test_order_saga.py tests/runtime/test_public_contract.py -k 'hard02 or creation_unknown or duplicate_attachment or end_to_end_journey' -q`|Pending RED/GREEN|
|05-03-02|3|HARD-02|_mark_unknown erases stronger/reasonless hold/manual resolution; already-settled no-op must remain green/mutation-free|`uv run pytest tests/runtime/test_order_saga.py -k 'hard02 or mismatch or late_settlement or creation_unknown or duplicate_attachment or hard03' -q`|Pending RED/GREEN SQLite+PG|
|05-03-03|3|HARD-02|Browser checkout remains behind creation hold after valid recovery vs original QR before settlement. Financial feedback excludes DB/install; pause afterward|`cd tests/e2e && npx --no-install playwright test buyer.spec.ts --grep 'hard02\|order status page\|checkout retries'`; `uv run pytest tests/runtime/test_order_admin.py tests/runtime/test_order_saga.py tests/runtime/test_checkout.py tests/runtime/test_catalog_variants.py tests/runtime/test_public_contract.py tests/runtime/test_nostr_signin.py tests/runtime/test_email_queue.py tests/runtime/test_nip17_inbox.py tests/runtime/test_release_a_journey.py -q`|Pending browser/independent review; audit OPEN; production/disposition/release BLOCKED; STOP|
|05-04-01|4|HARD-04|`test_hard04_stale_revision_cannot_publish_dependent`: publishedrev1 wrongly releases rev2 dependency vs blocked actual worker send|`uv run pytest tests/runtime/test_outbox.py tests/runtime/test_catalog_events.py -k 'hard04 or dependency or supersed or delet' -q`|New authorization required|
|05-04-02|4|HARD-04|`test_hard04_prune_preserves_retained_dependencies`: pruning erases retained edge/proof vs still blocked until correct revision|`uv run pytest tests/runtime/test_outbox.py tests/runtime/test_catalog_events.py -k 'hard04 or prune or dependency or delet' -q`|New authorization required|
|05-04-03|4|HARD-05|`test_hard05_route_after_twenty_waits_still_delivers`: pending unclaimable at20 vs eligible until48h; real errors still budgeted|`uv run pytest tests/runtime/test_nip17_outbox.py tests/runtime/test_intake_abuse.py -k 'hard05 or no_route or dual_copy or partial_acceptance' -q`|New authorization required|
|05-05-01|5|HARD-06|`test_hard06_pending_scope_cap_rejects_before_decrypt`: depth1001 accepted vs rejected/depth1000 with received+validated/index|`uv run pytest tests/runtime/test_intake_abuse.py -k 'hard06 or admission_bound or wrap_relay_flood or per_author' -q`|New authorization required|
|05-05-02|5|HARD-06|`test_hard06_concurrent_admission_at999`: both admit/1001 vs exactly one; rollover/different scopes/drain|`uv run pytest tests/runtime/test_intake_abuse.py tests/runtime/test_release_b_drills.py -k 'hard06 or overload or backlog or process_pending or rumor' -q`|New authorization required|
|05-05-03|5|HARD-07|`test_hard07_db_install_orders_exit_cleanly`: bounded child assertion fails on hang; diagnostic both orders FIRST, root cause UNKNOWN until proved|`uv run pytest tests/test_runtime_process_exit.py -q`; `uv run pytest tests/runtime/test_db.py tests/runtime/test_install.py -q`; `uv run pytest tests/runtime/test_install.py tests/runtime/test_db.py -q`; `make verify-runtime`; `make verify` AFTER demonstrated lifecycle repair, all with natural exit0/nonempty collection|New authorization required|
|05-06-01|6|HARD-08|Actual repaired journey, local full evidence and four existing Linux profiles. Old happy paths may pass baseline and are insufficient; new regressions must have earlier RED evidence|`uv run pytest tests/runtime/test_release_a_journey.py tests/runtime/test_order_saga.py tests/test_runtime_process_exit.py -q`; `make lint`; `make verify`; `cd tests/e2e && npx --no-install playwright test admin.spec.ts buyer.spec.ts`; `cd tests/conformance && bash ./run_matrix.sh matrix`|New approval; CI coordinated by parent|
|05-06-02|6|HARD-08|Independent ASVS1/high-blocking review, no old-green/proposed-mitigation closure; supporting auth/crypto positives may pass baseline|`uv run pytest tests/runtime/test_merchant_api.py tests/runtime/test_buyer_accounts.py tests/runtime/test_email_signin.py tests/runtime/test_crypto_keystore.py tests/runtime/test_keystore_nip17.py tests/runtime/test_release_b_drills.py -q`|Independent security review pending|
|05-06-03|6|HARD-08|Operator historical-order audit + actual live Plebeian item17. Automated synthetic green cannot close absent manual evidence|`uv run pytest tests/runtime/test_order_saga.py tests/runtime/test_nip17_outbox.py tests/runtime/test_nip17_inbox.py -q` supporting readiness only|Separate operator/live approvals pending|

Permanent tests are created in each tracer/behavior task, not deferred to a
schema/test-only wave0. Target RED must be an intentional named assertion failure;
fixture/import/discovery failures are INVALID_RED. Persist command/exit/expected/
actual and GREEN clean exit; use installed tdd-red-evidence checker where available.
Repeated tests must remain permanent. Status/nyquist/security closure stays draft
until implementation evidence, independent review and required manual gates exist.
Every execution task runs `make lint` after its focused checks; broader named
`make verify-db`/`make verify-protocol` checks support relevant DB/protocol work.
Do not call full `make verify-runtime` financial-only coverage before CI-01 repair;
if the hang blocks feedback, report and request authorization instead of moving05-05
into the financial tranche. CI-01 printed assertions plus hang remain failure.

## Execution checks

- For each repair: first retain a failing regression, implement the smallest
  domain fix, then rerun its focused test files and `make lint`.
- Run focused affected runtime files during the financial tranche; only after
  authorized CI-01 repair run full `make verify-runtime`. Use applicable
  `make verify-db` / `make verify-protocol` checks in their authorized scope.
  Treat process termination and exit status as part
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

## Early historical-record gate at financial pause (05-03), carried to05-06

HISTORICAL-PAID-ORDER-AUDIT: **OPEN / NOT AUTHORIZED / NOT PERFORMED**; actual-record evidence **NONE**, historical disposition **NOT DONE**. **Production exposure, real-record disposition and release clearance BLOCKED** until separately approved actual read-only operator audit/review.05-03-SUMMARY must record these exact distinctions and operator/parent ownership. Synthetic proof guards, local financial review and parent-reviewed local commits do not satisfy the audit. No existing DB/credentials/access is authorized now; do not add a checkpoint blocking already-authorized synthetic work. No legacy sweep/flag/state/counter/ledger repair. Eventual disposition requires separate reviewed authorization.

## Static planning verification contract

Every29 automated commands have native fails_when, with nonzero assertion/failure signal and natural exit required; expected_red and positive_retention are separate. Missing tests/tools or fixture failure is INVALID_RED; make SUBSET_OK empty runtime selection is not success. Each command is run in its own fresh repo-root shell; cwd is encoded for browser/conformance.05-05-03 explicitly runs both make verify-runtime and make verify AFTER diagnosed repair; this does not close05-06 supported-profile/security/operator gates. Native plan checks only validate authored structure/predicates, not runtime passes.

All19 descriptor-less structured prohibitions remain unresolved and flagged-unverified under the single projectProhibitions/dispositionForProhibition owner. Independent source/code/security review must assess them; no fabricated check_* descriptors, auto-dismissals or silent machine-green claim. The native UI adapter is `check ui.plan-gate 5 --raw`, not query; actual frontend=false/hasUiSpec=true/block=false result is a static gate, not evidence the UI behavior passed. See05-REVIEWS.md for the revision/check ledger.

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
