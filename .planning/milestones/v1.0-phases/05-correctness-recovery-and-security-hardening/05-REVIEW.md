---
phase: 05-correctness-recovery-and-security-hardening
reviewed: 2026-10-12T20:47:48Z
wave_4_5_reviewed: 2026-10-12T23:59:00Z
depth: deep
files_reviewed: 40
files_reviewed_list:
  - infinitemarkets/db.py
  - infinitemarkets/services/catalog.py
  - infinitemarkets/services/checkout.py
  - infinitemarkets/services/email.py
  - infinitemarkets/services/orders.py
  - infinitemarkets/services/outbox.py
  - infinitemarkets/services/settlement.py
  - infinitemarkets/services/order_messages.py
  - infinitemarkets/static/infinitemarkets/js/admin_orders.js
  - infinitemarkets/static/infinitemarkets/js/public_checkout.js
  - infinitemarkets/static/infinitemarkets/js/public_order.js
  - infinitemarkets/views_public_api.py
  - tests/e2e/admin.spec.ts
  - tests/e2e/buyer.spec.ts
  - tests/runtime/test_catalog_variants.py
  - tests/runtime/test_financial_review.py
  - tests/runtime/test_checkout.py
  - tests/runtime/test_email_queue.py
  - tests/runtime/test_nip17_inbox.py
  - tests/runtime/test_nostr_signin.py
  - tests/runtime/test_order_admin.py
  - tests/runtime/test_order_saga.py
  - tests/runtime/test_public_contract.py
  - tests/runtime/test_release_a_journey.py
  - tools/e2e_server.py
  - infinitemarkets/migrations.py
  - infinitemarkets/services/inbox.py
  - infinitemarkets/services/peer_relays.py
  - infinitemarkets/services/relay.py
  - infinitemarkets/services/tasks.py
  - tests/runtime/test_catalog_events.py
  - tests/runtime/test_db.py
  - tests/runtime/test_intake_abuse.py
  - tests/runtime/test_nip17_outbox.py
  - tests/runtime/test_order_saga.py
  - tests/runtime/test_outbox.py
  - tests/runtime/test_relay_config_api.py
  - tests/runtime/test_release_b_drills.py
  - tests/runtime/test_status_api.py
  - tests/test_runtime_process_exit.py
findings:
  critical: 0
  warning: 2
  info: 0
  total: 2
status: passed
source_status: passed
qualification_status: blocked
---

# Phase 05: Final Independent Financial Source Review

## Summary and provenance

**SOURCE REVIEW: PASSED within the finite approved F1/F3/F2 financial scope. No remaining source blocker identified. QUALIFICATION: BLOCKED.** CR-01–06 and source robustness warning WR-02 are resolved on the current tree. Two open warnings track evidence chronology and admin host/browser qualification. WR-04 (pre-existing MEDIUM token revocation/expiry boundary) and the wave-4/5 WR-05 drain residual have since been fixed with permanent regressions and reviewer recheck — see their resolved entries below. The frontmatter pass is local source disposition only: it is not full Phase 05, ASVS-level, requirements, production or release clearance.

This is the final independent continuation of the earlier adversarial review, with no agents or other writers used by the reviewer. Rechecked current implementations, cross-call consumers, current tracked financial diff and new regressions rather than accepting the fixer's disposition. The reviewed source/test list above includes the unchanged consumers/frontend and both new runtime files. `tests/runtime/test_financial_review.py` is now 1,016 lines; the new permanent cases at :621–1015 were read, including real intake/reconciliation, descriptor, cancellation/projection/deadline barriers, non-head proofs, public/resume/cache admission and later-candidate coverage. Earlier source/test review remains applicable to unchanged bytes, not a substitute for rechecking the newly changed paths.

Base: `bf99ec0b252f6ecff38eadb377d16d57def3576a`. Current user-owned HEAD: `a4cb2128eecbbfda1ec3d3a7e0e221df0f5c9fa8`; these were independently checked. User NIP-85 roadmap work and unrelated untracked planning/agent artifacts are preserved and excluded from the financial disposition. No Git mutation was made.

Independently computed all **24** SHA256 fingerprints in `05-FINANCIAL-REVIEW-FIXES.json:54–79`: every current value matches iteration 2's final manifest. `current_attempt` at :4–88 is the latest executor evidence; iteration 1 and both interrupted histories remain preserved, not combined with current counts or rewritten as final verification. Hash agreement ties the inspected files to the supplied final verification, but does not independently prove execution results. The reviewer ran **no runtime tests, browser, server, database calls, installations or live operations**. Paths below are relative to `/Users/bk/github/infinitemarkets`; source shorthand `services/...`, `db.py` and `views_public_api.py` denotes the corresponding file under `infinitemarkets/`.

## Resolved source findings

### CR-05 — RESOLVED: Shared locked payable-invoice admission

**Previous classification:** BLOCKER, financial invoice/request authority; not F5 routing or transport.

**Previously causal defect:** Gamma recovery selected awaiting/pending orders without excluding protected holds, decrypted an unlocked original invoice and admitted type-2 requests later without locking/revalidating current order state. Initial Gamma request admission also trusted its earlier attachment result. This allowed a request despite a preserved hold or cancellation between selection and enqueue.

**Current source property:** `services/orders.py:404–436` introduces shared `payable_invoice`. It refreshes/locks the current merchant-scoped order, requires awaiting_payment, no payment exception and only approved unresolved resolution; requires exactly one pending projection; obtains complete coherent live inventory coverage under sorted financial product locks; validates the mandatory authenticated original attached snapshot; and checks current decoded invoice and allocation deadlines with DB time. It is read-only and returns the persisted authoritative BOLT11, not a caller override. `services/settlement.py:113–182` supplies fail-closed snapshot validation, including original wallet/source HMACs, version, merchant/order/external/tag/currency/user, exact amount, order/projection/invoice hash, checking ID and decoded expiry. Malformed envelopes deny admission.

`services/order_messages.py:393–439` invokes that authority inside the existing caller-owned transaction, rechecks type-2 dedupe under the held order lock, authenticates the actual buyer key HMAC, obtains a sequence by read-only count (`:291–298`), and rechecks both deadlines before admitting the encrypted descriptor/message/outbox. Caller BOLT11/expiration values are overwritten by the snapshot. Denied cases do not create a message, intent or sequence effect. Recovery at `:899–925` selects only order/merchant hints, performs no pretransaction invoice decryption and counts only actual admissions. Initial Gamma at `services/checkout.py:1681–1689` and attributed web type-2 admission at `:851–861` both reuse this guarded helper. Existing admitted requests are not retrospectively deleted or cleared; publisher/routing behavior is unchanged.

Other invoice consumers were traced: token status and authenticated history reuse their existing transaction for locked current order, delivery and payable authority (`views_public_api.py:359–378,734–739,768–787`). Resume and completed idempotency replay use the same current guard rather than raw decryption or stale cached invoice (`services/checkout.py:717–728,1504–1541`). Initial creating attachment remains separately canonical-core verified and current-coverage gated before invoice exposure (`:1300–1434`), not a wallet-only ordinary-settlement bypass. The raw BOLT11 read at `services/order_messages.py:634–683` is cosmetic inbound receipt evidence; it does not authorize payment, invoice delivery or goods.

**Source-assessed regressions / executor evidence:** `tests/runtime/test_financial_review.py:621–731` uses actual Gamma persist-then-timeout intake, actual reconciliation/type-2 admission, stronger/reasonless/manual/unknown holds, projection/identity and coverage negatives, and decrypts healthy original request tags. `:734–797` interleaves selected-before-cancel/projection/deadline with distinct PG backend PIDs and no denied-side writes. `:916–957` checks actual public status plus resume/completed-cache negatives; `:989–1015` proves the authoritative original invoice wins over an untrusted caller value and dedupes in transaction. These source assertions exercise the formerly bypassing consumer, not merely a goods-delivery helper. Executor reports scoped GREEN; reviewer did not execute these regressions.

### CR-06 — RESOLVED: Post-lock authoritative deadline decisions

**Previous classification:** BLOCKER, live coverage/deadline boundary.

**Previously causal defect:** Attachment and normal confirmation passed caller/pass-start time through potentially blocking order/product locks and core-wallet reads. A decoded invoice or held allocation could expire during that wait but still be treated as live, expose QR or normally consume/confirm.

**Current source property:** `services/orders.py:677–704` acquires the relevant product lockset, reads inventory counter coherence, then samples `tx.now()` and applies it to reservation deadlines; the validated epoch is returned with coverage. `services/checkout.py:1315–1337,1393–1420` refreshes time after canonical core/wallet prerequisites and uses the coverage's post-lock epoch for the final live invoice/allocation decision. `services/settlement.py:413–439` verifies the unique canonical successful original and mandatory attached snapshot before coverage, then uses coverage's fresh epoch for settled CAS, invoice deadline, stock and state decisions. Caller/pass-start time is not authoritative for this final decision. `services/orders.py:432–436` additionally checks decoded/current invoice exposure deadlines, and type-2 admission refreshes time after its extra reads at `services/order_messages.py:414–418`.

Expired or incomplete active allocation enters the existing cancelled-review lane; original correlation is retained, coherent residuals may be safely released and incoherent counters are not guessed/repaired (`services/checkout.py:1395–1420`; `services/settlement.py:486–508`). A genuine core payment arriving after the deadline is recorded into review, not silently normally fulfilled. Already-settled replay still returns before verification or mutation (`services/settlement.py:410–412`). Already-paid goods remain valid after later invoice expiry; the payable gate does not become a goods entitlement deadline.

**Source-assessed regressions / clock limitation:** `tests/runtime/test_financial_review.py:800–875` crosses the actual original decoded FakeWallet deadline while the worker waits for an order/product lock, checks distinct PG backend PIDs, verifies current authoritative epoch exceeds the deadline and asserts cancelled hold, no attachment invoice and coherent stock release. The DB epoch API is explicitly controlled across the barriers; this is not evidence that physical PostgreSQL wall-clock time naturally elapsed past expiry. SQLite uses serialized writer entry, not a fictional row lock. `:960–986` verifies a later reconciliation candidate cannot reuse pass-start time. Existing unexpired, one-time consumption, attachment/expiry winners and already-paid expiry positives remain part of the scoped selection. Reviewer did not execute these cases.

### WR-02 — RESOLVED: Exact types for every merchant ancestor proof

**Previous classification:** WARNING, fail-closed proof robustness; no demonstrated buyer write primitive or additional stock theft.

`services/orders.py:347–371` now validates every merchant ancestor's list/cardinality, exact item identity, uniqueness, product identity, exact nonnegative integer quantity fields and quantity/backorder equations before cumulative map equality. A numerically equivalent float/boolean is no longer accepted merely because Python equality coerces it. `tests/runtime/test_financial_review.py:878–913` parameterizes all four non-head fields with float/boolean values, denies shared fulfillment and later accept, and asserts no dirty authority read or guessed history repair. Source property is corrected; executor reports GREEN, not reviewer execution.

### CR-01–04 — corrections preserved

| ID / previous mechanism | Current source and retained regression property | Disposition |
|---|---|---|
| CR-01 future acceptance timestamp fabrication | `services/settlement.py:949–950,979–1002` uses real DB time and causal parent confirmation IDs, not future epochs. `services/orders.py:219–286` validates bounded IDs/time, a unique reachable acyclic/unforked chain independent of second ties. `services/outbox.py:57–98` uses DB time for enqueue/supersession. Same-second cumulative accounting tests and intent-clock regression remain. | Resolved; no ledger timestamp fabrication reinstated. |
| CR-02 merchant/FK lock cycle | `db.py:207–209`; `services/checkout.py:934,1131,1755` use PostgreSQL FOR NO KEY UPDATE for merchant serialization, compatible with the email FK KEY SHARE. Email locks order before queue (`services/email.py:284–296`). Actual configured-recipient accept/competing checkout regression remains at `tests/runtime/test_financial_review.py:241–327`. | Resolved; no implicit merchant FOR UPDATE reintroduced by invoice authority. Not blanket DB lifecycle qualification. |
| CR-03 contradictory identity / optional ordinary verification | `services/orders.py:157–178`; `services/settlement.py:113–182,185–272,413–439` require exact original attached identity and canonical successful core proof for ordinary settlement. Preattachment wallet-only validation is restricted to genuine creating/creation_unknown recovery, not normal pending settlement (`services/checkout.py:1249–1261`). | Resolved; missing/contradictory legacy snapshots fail closed without rewriting records. Valid paid goods survive legitimate merchant wallet changes. |
| CR-04 creating/no-hold failed allocation exposed invoice | `services/checkout.py:1385–1434` cancels into bounded review independently of a prior hold, retains original pending correlation, releases coherent residuals only and suppresses invoice. Released/partial/expired/corrupt/missing allocation tests remain at `tests/runtime/test_financial_review.py:182–238`; expiry fixture now controls authoritative clock (:212–218). | Resolved, including no initial hold; current time and Gamma admission gaps are now separately corrected above. |

## Retained warnings and qualification gates

### WR-01: Retrospective buyer browser RED does not establish original test-first chronology

**Classification:** WARNING — evidence chronology, not financial source defect.
**File:** `.planning/phases/05-correctness-recovery-and-security-hardening/05-BROWSER-BASELINE-EVIDENCE.json:3–8,82–120`.

The actual archived bf99 baseline capture byte-verified 97 production package files, failed the intended buyer creation_unknown→awaiting_payment assertion and exited naturally with one collected failure. It occurred after earlier GREEN and reached only the first desktop scenario; it cannot retroactively prove original RED-before-fix chronology or original baseline mobile/hold results. Iteration 2's genuine targeted source REDs (`05-FINANCIAL-REVIEW-FIXES.json:23–28`) do not erase that earlier browser chronology deviation.

**Action / acceptance evidence:** Preserve both chronology records and seek parent/operator procedural disposition. No fabricated timestamps, reintroduced defect or pageerror filtering. Current hard02 is one test with three scenarios, not three separate browser tests.

### WR-03: F1 admin pinned-host no-pageerror qualification remains OPEN

**Classification:** WARNING — existing host/browser assurance gate, not new financial source bug. Stable WR-02 is reserved for the resolved ancestor finding above; WR-03 names the previously retained admin gate.
**Files:** `.planning/phases/05-correctness-recovery-and-security-hardening/05-BROWSER-BASELINE-EVIDENCE.json:122–148`; `tests/e2e/admin.spec.ts:258–345`.

The unchanged pinned host `e336fe14b841d6f0c940e75b3d343e3ab5cf8433` baseline actually reproduced ServiceWorker SSL registration and null-wallet WebSocket pageerrors. The capture's later optional-locator limitation also prevents claiming a qualified full admin journey. Current buyer GREEN does not close required F1 admin no-pageerror qualification; strict admin/buyer error assertions remain in source.

**Action / acceptance evidence:** An approved host/browser qualification path must complete the actual admin scenarios with the required assertion, without filtering pageerrors, weakening TLS/security controls or declaring a vendor waiver here. Admin journey was not rerun or qualified by this reviewer or iteration 2 executor evidence.

### WR-04 — RESOLVED (was OPEN, medium): presented-token revalidation under the order lock

**Classification:** RESOLVED after user-authorized fix; regression-covered.

**Previous defect:** `_order_for_token` admitted the bearer token outside the content transaction; rotation (`admin_reissue_token`) or expiry committed between admission and content reads could not stop an already-admitted request from disclosing the invoice/digital delivery or mutating opt-out state — contradicting the documented "old token revoked immediately" contract.

**Current source property:** `views_public_api.py:321–369` adds `_token_digest` plus `_locked_order_for_token`, which takes the order `FOR UPDATE` and requires `crypto.tokens_equal(public_token_hash, presented_digest)` and `public_token_expires_at > tx.now()` inside the same `DomainTransaction` as the sensitive work. Applied at `order-status` (:384–392 before items/payment/delivery), `order-email-opt-out` (:414–420 before mutation) and `nostr/claim` (:1042–1049 via `presented_token_hash`). `services/nostr_auth.py:1419–1441` rechecks hash+expiry under its own order lock, refreshes the row and re-verifies bound-value equality before the `already_linked` early return — closing the stale-NULL→fresh-foreign-bound false-success gap the security reviewer found in the first WR-04 iteration. Every failure branch returns the identical 401 body (`_TOKEN_INVALID`/`CLAIM_INVALID` are byte-identical), preserving the no-oracle contract.

**Regressions (executor-verified):** `tests/runtime/test_status_api.py::test_rotated_token_inflight_status_denied` and `::test_rotated_token_inflight_opt_out_denied` were genuine RED on the pre-fix tree (200 with bolt11 / 200 with mutation, now 401/no-op); `tests/runtime/test_nostr_signin.py::test_claim_rotated_token_inflight_denied` and `::test_claim_foreign_bound_during_inflight_window` cover the claim path including the foreign-bound-window residual. SQLite 26+40 and PG 75/59 focused selections pass.

**Reviewer recheck disposition:** independent security reviewer confirmed all three endpoints close the race on both dialects (FOR UPDATE serialization on PG; BEGIN IMMEDIATE writer serialization on SQLite), found and dispositioned the claim early-return residual, and noted only cosmetic items since addressed (bytes annotations, `tokens_equal`).

## Human source/scope checks, not machine-flag assurance

- Shared payment/inventory authority still controls fulfillment, digital delivery, merchant advancement/shipping and confirmed email. Current order stays locked through delivery content decryption (`services/orders.py:378–472,1298,1347`; `services/email.py:284–319`). Token/history transaction reuse avoids a nested financial transaction; invoice authority and delivery authority remain distinct for legitimately paid goods. Gamma goods/status behavior and inbound buyer cancellation retain the prior reviewed authority; buyer receipt/preimage/status strings do not become core payment evidence.
- `ORDER_TRANSITIONS` remains unchanged (`services/orders.py:48–58`). Accept remains merchant-only for expired/cancelled orders with verified settled projection (`services/settlement.py:968–978`). No accept-state widening, automatic correlation clearing, second-invoice recovery, outgoing custody/refund implementation or historical sweep/repair was introduced. Stronger, reasonless and manual/unknown resolutions are preserved; only pure creation uncertainty can be automatically resolved.
- Inventory remains complete, bounded and one-time: 64 item/reservation bounds, product-held counter bound and 128 confirmation-event bound fail closed. Finite stock excludes competing holds; unlimited NULL stock stays NULL; consumed/prior accepted allocations, backorders and residual holds remain coherent. Sorted leaf/variation-parent locksets and transactional parent stock projections remain. Cumulative accepted snapshots are validated rather than repeatedly charged or repaired.
- State/payment/inventory/audit/email/projection/outbox effects remain in caller-owned fenced domain transactions. The actual `services/outbox.py` diff changes only enqueue/supersession time to DB clock; no F4 dependency satisfaction or F5 routing/publisher/transport semantic work. New type-2 admission changes are financial authority, not a publisher redesign. No source migration, dependency, configuration, vendor or security-policy change is in this financial diff. Synthetic harness routes remain under `tools/e2e_server.py`, not shipped production routers; offline seeding is not publication/relay qualification.
- Read-only diff checks confirmed existing comment moves/restorations rather than new explanatory source comments in the reviewed financial changes. The previously missing exact baseline inline `# fresh + replay + crash-resume only` is restored at `tests/runtime/test_checkout.py:341`. Parent-owned NIP-85 roadmap and historical evidence are not overwritten. No unrelated user artifacts were staged or cleaned.
- These are human code/diff assessments of the approved finite tranche. Unwired prohibition/assurance flags are not treated as executed machine gates or grounds for a blanket green claim. Broader security, concurrency, lifecycle and operational qualification remain unperformed here.

## Executor evidence and unresolved release posture

Iteration 2 final evidence (`05-FINANCIAL-REVIEW-FIXES.json:37–51`) reports natural exits:

- Same ten financial runtime files: SQLite **433 passed / 6 existing PG-only skips**; approved disposable PostgreSQL **439 passed / 0 skipped**.
- Focused permanent review file: SQLite **83 passed / 4 existing PG-only skips**; PostgreSQL **87 passed / 0 skipped**. New cases do not add skips.
- Final lint, three JS syntax checks and diff check GREEN; buyer hard02 **1 test / 3 scenarios GREEN**, strict pageerror assertions unchanged.
- Twenty-four fingerprints unchanged across final executor verification and independently matching the inspected tree. Earlier intermediate 431/437 and iteration 1 401/407 results remain historical, not the final counts. Targeted RED provenance and explicit controlled-clock limitations are preserved in evidence rather than overstated.

These are credited as scoped **executor-provided results**, not reviewer execution, full repository suite, full CI or release qualification. Synthetic FakeWallet/browser results establish no live funding/relay or real-record disposition. The reviewer independently performed source tracing, hashes and read-only Git diff/check only.

**HISTORICAL-PAID-ORDER-AUDIT: OPEN / NOT AUTHORIZED / NOT PERFORMED. Actual real-record evidence: NONE. Historical disposition: NOT DONE. Production exposure, real-record disposition and release clearance: BLOCKED.** Missing original snapshots/proofs intentionally fail closed; actual historical incidence is unknown until a separately authorized read-only operator audit. No automatic historical repair is authorized by this pass. ASVS-1 and high-severity blocking policy remain unchanged.

F4–F6, CI01, DB/install lifecycle/full qualification, the full four-profile Linux/main matrix, live Plebeian UAT/checkout/funding/relay and wider phase/security certification remain pending, outside this review. Source PASSED is **not** Phase 05 completion, production readiness or a release waiver.

**Parent next action:** Parent may evaluate the user's locally authorized commit only after its own final checks and staging/scope review; this reviewer neither commits nor supplies release clearance. Preserve the user-owned roadmap and historical evidence, keep the audit/admin/chronology gates explicit, then pause as instructed. Parent owns approved disposable PG/scratch teardown; reviewer did not connect to or stop them.

**Reviewer actions:** Read-only Git status, rev-parse, diffs/stat/comment-move inspection and diff check (exit 0), SHA256 computation, UTC date and source/test/evidence reads. Only this canonical `05-REVIEW.md` rewritten. No runtime/test/Git/config/vendor/credential changes, tests, agents, servers, database calls, installs or commits.

---

# Wave 4/5: Independent Source Review — F4/F5 outbox correctness, F6 inbox cap, CI-01 lifecycle

**WAVE 4/5 SOURCE REVIEW: PASSED (the one new warning WR-05, low, has since been resolved by the parent-applied drain fix and its permanent regressions). QUALIFICATION: remains BLOCKED.** The uncommitted wave-4/5 tranche against base `3c0c237` (the reviewed F1–F3 HEAD) was independently re-read end to end: `services/outbox.py`, `services/relay.py`, `services/inbox.py`, `services/tasks.py`, `migrations.py`, the nine touched runtime test files, the new process-exit test, and the six RED plus two PROGRESS evidence records. All prior financial-tranche content above stands; nothing below modifies, re-opens or closes it. This pass is local source disposition only — not Phase 05 completion, ASVS-level, production or release clearance, and not reviewer test execution.

## Scope and provenance

Reviewed the current uncommitted working-tree diff only (base HEAD `3c0c237`, "Require verified authority for paid fulfillment"). Changed source files: `infinitemarkets/services/outbox.py` (+19/−8), `infinitemarkets/services/relay.py` (+54/−7), `infinitemarkets/services/inbox.py` (+26), `infinitemarkets/services/tasks.py` (+100/−18), `infinitemarkets/migrations.py` (+10). Changed/new test files: `tests/runtime/test_outbox.py`, `test_catalog_events.py`, `test_nip17_outbox.py`, `test_intake_abuse.py`, `test_release_b_drills.py`, `test_db.py`, `test_relay_config_api.py`, `test_status_api.py`, new `tests/test_runtime_process_exit.py`. Evidence: `05-04-{PROGRESS,RED-01..03}.json`, `05-05-{PROGRESS,RED-01..03}.json`. Also modified but not line-reviewed: regenerated `evidence/REPORT.md`/`evidence/manifest.json` (make verify output; the recorded 982/990 result is internally consistent with the post-fix PROGRESS counts). Untracked `.gsd/dispatch-isolation-sentinel.json` is an agent sentinel, excluded. `tests/runtime/conftest.py`, `tests/conftest.py`, `tests/runtime/test_install.py` — listed as 05-05 candidates but correctly left untouched.

## F4 / HARD-04 — revision-bound `_deps_published` (outbox.py:215–240)

**Verdict: correct, plan-conformant.** The joined intended row `e` (the FK-bound `depends_on_outbox_event_id`) is now the authority: the edge is unmet unless some row `p` exists with `p.merchant_id = e.merchant_id AND p.aggregate_type/aggregate_id/event_kind = e's AND p.state='published' AND p.aggregate_revision >= e.aggregate_revision` (outbox.py:224–239).

- **Stale publication** (published rev1 vs bound rev2): `p.aggregate_revision >= e.aggregate_revision` excludes it — verified against the rewritten `test_dependency_met_when_aggregate_has_published_revision` and `test_hard04_stale_revision_cannot_publish_dependent`.
- **Wrong kind / tombstone**: `event_kind` equality excludes a published kind-5 covering a bound kind-30405 edge (`test_hard04_dependency_scope_kind_merchant_and_failed` case a). Conversely a bound tombstone edge is satisfied only by a published tombstone — ordering preserved.
- **Foreign publication**: `merchant_id` equality excludes another merchant's row of identical aggregate identity (case b). Cross-merchant `depends_on` bindings are real (tests bind `mid`→`dep`), so this clause is load-bearing, not decorative.
- **Failed/pending/superseded p**: `state='published'` excludes all non-published proofs (case c: failed rev3 + stale published rev1 cannot satisfy).
- **Superseded intended row**: satisfied iff a real published replacement covers it — same merchant/aggregate/kind at rev ≥ bound rev. `p` may be `e` itself (a directly published bound row trivially qualifies), so the intended path is preserved.
- **NULL/type**: `aggregate_revision` is `{int_t} NOT NULL DEFAULT 0` (migrations.py:360) — no NULL-comparison wedge; both sides integer.
- **Multiple edges / vanished target**: `COUNT(*)` over unmet JOINed edges requires every edge satisfied; a JOIN that drops a deleted target would make the dependent dependency-free — that hole exists only if the target row can be deleted, which the FK (ON DELETE RESTRICT) and the new prune protection jointly prevent.

**Accepted strictness (observation, not defect):** `enqueue_intent` supersession (outbox.py:59–70) does not filter `event_kind`, so a bound kind-30405 intent superseded by a kind-5 tombstone (or any different-kind newer revision) can never be satisfied — dependents of a tombstoned aggregate wedge permanently at `pending, attempts=0`. This is the plan's demanded semantic ("only a revision that truly landed unblocks"), strictly safer than wrong-order publication. Pre-existing consequence: blocked rows requeue with `next_attempt_at=now` and are re-claimed every tick under `ORDER BY created_at LIMIT 32`, so a large population of permanently wedged intents could crowd the claim batch — a scale note, unchanged by this diff.

## F4 / HARD-04 — dependency-safe `prune_outbox` (relay.py:1063–1158)

**Verdict: correct.** The fixpoint computes `protected` ⊆ `candidates` (this merchant's terminal rows inside the 7–3650-day window): (i) `protected` only grows → termination bounded by |candidates|; (ii) any edge whose dependent is retained (not a candidate, or itself protected) protects its target if the target is a candidate — transitively, since protected candidates feed later iterations; (iii) for every such edge, every *candidate* published row matching the target's merchant/aggregate/kind at rev ≥ is protected — exactly the `_deps_published` proof relation.

- **A retained dependent cannot lose an edge**: edges are deleted only where an endpoint is in the final delete set; every target of a retained dependent is protected. A blocked child can never come back dependency-free (test_hard04_prune_preserves_retained_dependencies asserts chain A→B→D, proof chain A2→B2(superseded)→P2(published rev3) all survive, `pruned == 1`).
- **Published replacement proofs**: protected whenever a retained dependent's bound target could be proved by them — including proofs belonging to retained rows of *other* merchants' edges (edges fetched globally, required because cross-merchant `depends_on` exists).
- **`pruned` count**: truthful — the delete set is `rows − protected`, deletes run in one `DomainTransaction`, and `deleted` accumulates the actual event-row rowcount after edge/evidence deletes; any concurrent edge insert racing the snapshot fails FK RESTRICT and rolls the whole tx back (pre-existing failure mode, error surfaces as 500 — retriable, never a partial or over-reported count).
- **Validation/scope**: `7 <= days <= 3650` bound unchanged; candidate filter still `merchant_id = :m` + terminal states + `updated_at <= cutoff`; in-flight states untouched; order/financial/audit tables out of scope.
- **Performance note (observation):** the fixpoint reads the *entire* `outbox_dependencies` table and all dependency-target rows (unbounded by merchant — necessary for cross-merchant correctness), then iterates edges × published-candidates per round inside the write transaction; on SQLite the BEGIN IMMEDIATE write lock is held for the whole computation. A manual admin op on a very large multi-merchant history could stall writers. Not a correctness defect; flag for scale.

## F5 / HARD-05 — no-route wait vs failed send (outbox.py:887–922)

**Verdict: correct.** Verified every branch:

- `not recipient_accepted and no_route` (outbox.py:887): past `created_at + 172800` → terminal `failed`; otherwise `pending` with `next_attempt_at = now + ORDER_MSG_NO_ROUTE_REFRESH_S` (900s), `last_error='no_inbox_relays'`, **`bump_attempts=False`** (the added line 899) — frozen attempts keep the row claimable through the 48h window (test asserts `attempts == 0` across 21 waits).
- Real send failures still bump: `_cas_state` defaults `bump_attempts=True` (outbox.py:296), the post-send settle at :1003 and the `worker_tick` exception path at :1193 both consume budget; `attempt_no >= OUTBOX_MAX_ATTEMPTS` (20) → `failed` with verbatim per-relay evidence retained (`test_hard05_real_send_failures_still_exhaust_budget`).
- **No attempts drift**: `attempts` is set to `row["attempts"] + (0|1)` inside one CAS — the no-route path can never increment; `claim_batch` eligibility (`attempts < 20`) is therefore preserved for exactly the deadline window.
- **No public fallback**: `buyer_routes` is `NO_INBOX_RELAYS` or a validated non-empty list — `resolve_buyer_inbox_relays` (peer_relays.py:110–166) returns the sentinel on every empty/failed/non-public path and `_extract_routes` requires 1–3 relay tags; the `no_inbox_relays` label in the :919-920 ternary is unreachable dead code (empty `recipient_targets` without recipient accepts implies `no_route`, already handled at :887) — harmless.
- **Dual-copy/ACK/fencing intact**: phase-0 descriptor/route resolution outside the claim tx, per-copy `_accepted` evidence subtraction, `delivery_copy`-scoped `relay_publications`, `_publication_transaction` claim_token CAS + merchant FOR UPDATE — all untouched. Sender copy is always merchant inbox relays; recipient only declared validated routes.
- The `peer_relays.refresh_stale_peer_relays` sweep (peer_relays.py:232–256) independently fails `pending`/`partially_published` `no_inbox_relays` rows past the exact created_at+48h deadline — belt-and-suspenders consistent with the worker path.

## F6 / HARD-06 — atomic 1,000-scope backlog cap (inbox.py:204–239, migrations.py:1427–1434)

**Verdict: correct.** Inside one `DomainTransaction`: merchant-row `SELECT id ... FOR NO KEY UPDATE` → dedupe pre-check → `COUNT(*) WHERE merchant_id AND source_relay_url AND processed_state IN ('received','validated')` → reject at ≥ `SCOPE_BACKLOG_CAP` (1000) → `INSERT ... ON CONFLICT DO NOTHING`.

- **Atomicity**: on PG the `FOR NO KEY UPDATE` row lock self-conflicts, so two admissions for the same merchant serialize on the merchant row before either counts — the contested test asserts exactly `["received","rejected"]` and durable depth 1000 across distinct `pg_backend_pid`s. `FOR NO KEY UPDATE` (not `FOR UPDATE`) is the right mode: it serializes contenders while leaving merchant non-key column updates elsewhere unblocked, and mirrors the established checkout-scope cap pattern (checkout.py:934–947, :1755–1767). On SQLite, BEGIN IMMEDIATE serializes all writers. Lock-before-count in the same tx: verified; no deadlock surface (single shared lock ordering point; inbox_events has exactly one INSERT site).
- **States**: `received`+`validated` are precisely the two non-terminal backlog states; `processed`/`rejected`/`duplicate`/`quarantined` excluded — terminal transitions free capacity (verified by both cap tests).
- **Placement**: after the cheap outer bounds (size/kind/p-tag/signature), relay minute-bucket, blocklist and author cap; **before** the INSERT and before any decrypt/unwrap (drain stays post-admission) — a rejected wrap leaves no row and no unwrap metric.
- **Dedupe consistency**: pre-check returns `"duplicate"` before the cap is evaluated (a resend of an admitted wrap stays duplicate at cap), and the `ON CONFLICT DO NOTHING RETURNING` post-check remains as belt — both paths converge on `"duplicate"`.
- **Metrics**: fixed-key `inbox.admission.backlog_limited` / `inbox.admission.merchant_gone` — bounded cardinality, no relay/buyer/payload labels.
- **Migration m016**: `CREATE INDEX IF NOT EXISTS idx_inbox_scope_backlog ON {s}inbox_events(merchant_id, source_relay_url, processed_state)` — additive, idempotent, dialect-neutral (references_schema resolves `""` on SQLite / `infinitemarkets.` on PG), columns exactly cover the count predicate; auto-discovered by the sequential `m0xx` runner convention; covered by the repeat-run/record-preservation test in test_db.py.

## CI-01 / HARD-07 — `_guarded` cancellation shield (tasks.py:108–127)

**Verdict: the diagnosed root cause is fixed; the narrow residual edge this review reported (WR-05) has since been fixed and regression-covered — see the resolved entry below.** `ensure_future` + `shield` let an in-flight `worker_tick`/`DomainTransaction` checkout complete and close its handles before the worker's CancelledError unwinds — directly addressing the evidenced `Database.connect()` `__aenter__` cancellation that orphaned the aiosqlite non-daemon thread. Every DB-bearing worker operation is wrapped (worker ticks, lease acquisition, `_run_leased`, reconcile epoch/marker reads, peer-relay refresh, email recover+tick, inbox reconcile, transport target list). The loop-local `import asyncio as real_asyncio` is correct and additionally immune to `tasks.asyncio` monkeypatching (module-level `import asyncio` also exists — the alias is defensive, harmless). `infinitemarkets_stop` cancels each owned handle once and clears `_owned_tasks`; `asyncio.run`-style shutdown gathers cancelled tasks, so the drained inner gets its chance to finish — no new lifecycle leak on the normal path.

### WR-05 — RESOLVED (was OPEN, low): drain preserves cancellation; second cancel absorbed

**Classification:** RESOLVED. Narrow residual lifecycle defect in the CI-01 shield, found by this review and fixed before commit. No financial/security surface.

**File:** `infinitemarkets/services/tasks.py:120-134`.

The original drain awaited `inner` unshielded: an inner exception raised inside the drain was re-raised in place of the consumed CancelledError (ghost-worker path), and a second `task.cancel()` propagated into `inner`, recreating the CI-01 orphaned-connection scenario. The parent-applied fix drains with `await real_asyncio.wait({inner})`: `asyncio.wait` neither propagates inner's result/exception nor cancels the futures in its set when the awaiting task is cancelled, so an inner failure cannot substitute for the cancellation and a repeated cancel is absorbed at the wait point rather than reaching the in-flight operation. `.exception()` is retrieved (guarded by `not inner.cancelled()`) for a debug log — also preventing a "Task exception was never retrieved" warning — and the bare `raise` in the outer `except CancelledError` re-raises the original cancellation. Verified against both causal chains; `wait` (not a re-shield) is the right primitive here.

**Accepted residual properties (observations, not defects):** a genuinely hung inner is now intentionally unkillable by repeated cancel — the old double-cancel escape *was* the bug; an inner self-cancel surfaces as worker cancellation exactly as before; a raise inside the log expression is unreachable in practice.

**Regressions (executor-verified RED→GREEN, reviewer did not execute):** `tests/runtime/test_db.py::test_hard07_guarded_inner_error_still_cancels_worker` and `::test_hard07_guarded_second_cancel_cannot_reach_inner` — baseline produced `RuntimeError`-substituted cancellation and a cancelled inner respectively; post-fix both pass. The bounded child process-exit regression still reports natural exit 0 in both file orders (`test_runtime_process_exit.py` + `test_db.py`, 14 passed).

## tests/test_runtime_process_exit.py — bounded process-exit regression

**Verdict: meets every stated requirement.** `sys.executable -m pytest <explicit pair>` as the direct signallable child (no `uv run` wrapper that would orphan the pytest grandchild); fresh `tempfile.mkdtemp` `LNBITS_DATA_FOLDER` per child; `GAMMA_QUAL_EVIDENCE` popped so the child can never overwrite the durable bundle; 120s `communicate` deadline → SIGABRT diagnostic capture → 15s drain → `kill()`+reap fallback → `pytest.fail` (timeout/kill is never success); asserts `returncode == 0` **and** a nonempty `N passed` summary without hardcoding the count; parametrized over both file orders; argv lists only `test_db.py`/`test_install.py` — never itself, never the tree (no recursion); owns only its spawned child. Minor: temp dirs accumulate in `/tmp` (negligible).

## test_status_api.py fixture correction — faithful

`tests/runtime/test_status_api.py:221–225` replaces `confirm_settlement(source='test')` — an unpaid confirmation the F1 canonical-originals gate (`originals[0].success`) correctly rejects — with `test_order_saga._settle_core_payment(order_id, total_sat)` + `settlement.invoice_listener(paid)`. Verified `_settle_core_payment` performs a real FakeWallet `pay_invoice` then `update_invoice_from_paid_invoices_stream` — the identical consumer function the host's paid_invoices_stream invokes — so the correction exercises the true settle path rather than approximating it. It is the justified out-of-scope correction the PROGRESS blocker records (pre-existing stale test, proven against reverted HEAD); it strengthens, not weakens, the assertion.

## Human source/scope checks (wave 4/5)

- `ORDER_TRANSITIONS` unchanged — `services/orders.py`, `checkout.py`, `settlement.py`, `views_public_api.py` untouched by this diff; no financial gate weakened. The `_deps_published` docstring/docstring edits are the only comment-level changes; **no new inline comments** in runtime source (verified by diff scan); new/changed functions carry codebase-consistent docstrings.
- No secrets, keys, tokens, decrypted payloads or raw identifiers in logs/metrics; all new metric keys are fixed strings.
- No vendor/pin/dependency/config edits; `PINS.md` untouched; no migration of existing columns (m016 is index-only); no `AGENTS.md` change.
- No scope creep beyond the 05-04/05-05 plan file lists except the justified `test_status_api.py` fixture correction assessed above. `tests/runtime/conftest.py`, `tests/conftest.py`, `tests/runtime/test_install.py` correctly unmodified.
- RED evidence is genuine: 05-04-RED-01/02 show baseline worker releasing dependents off stale/foreign/wrong-kind publications and baseline prune deleting 5/1 (TAP-captured assertion failures, natural exit); 05-05-RED-03 shows both file orders printing 20 passed then hanging 120s with faulthandler stacks naming the aiosqlite `_connection_worker_thread` + `threading._shutdown` join — a demonstrated, not guessed, root cause consistent with the fix.
- Executor-reported evidence credited without rerun: SQLite verify-runtime 751p/6s exit0; full `make verify` SQLite 982p/8s exit0; PG 987p/3s exit0; focused both-DB selections green; RED artifacts checker-validated. One earlier parallel-load flake on `test_public_pages` resolved clean on rerun (isolated + file + full clean PG verify all pass) — consistent with a load flake, recorded not concealed.

## Wave 4/5 gate posture — all open gates stay open

Wave 4/5 source scope **PASSED** (wave-local warning WR-05 since resolved with permanent regressions). Explicitly still open and unaffected by this pass:

- **WR-01** retrospective browser RED chronology — OPEN.
- **WR-03** F1 pinned-host admin no-pageerror qualification — OPEN.
- ~~WR-04~~ MEDIUM token revocation/expiry admission-vs-content boundary — **RESOLVED** (locked presented-token recheck; regressions on both DBs).
- **HISTORICAL-PAID-ORDER-AUDIT** — OPEN / NOT AUTHORIZED / NOT PERFORMED; real-record evidence NONE.
- Live Plebeian UAT/checkout/funding/relay — PENDING.
- Full platform matrix, browser/conformance qualification, ASVS-1 sign-off, production and release clearance — BLOCKED; local source pass is none of these.

**Wave 4/5 reviewer actions:** read-only `git status`/`git diff HEAD`/`git show` inspection, source reads of the five changed source files plus `peer_relays.py`, `db.py`, `checkout.py` lock-pattern context, all nine changed test files, the new process-exit test, `_settle_core_payment`/`invoice_listener` provenance in `test_order_saga.py`/`settlement.py`, lnbits `db.py` dialect/lock/schema behavior, and the eight planning/evidence JSONs. Only `05-REVIEW.md` extended (frontmatter counts and file list updated; all prior content preserved). No tests run, no DB connections, no agents, no Git mutations, no installs, no servers.
