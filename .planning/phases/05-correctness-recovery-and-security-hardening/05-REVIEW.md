---
phase: 05-correctness-recovery-and-security-hardening
reviewed: 2026-10-12T20:47:48Z
depth: deep
files_reviewed: 25
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
findings:
  critical: 0
  warning: 3
  info: 0
  total: 3
status: passed
source_status: passed
qualification_status: blocked
---

# Phase 05: Final Independent Financial Source Review

## Summary and provenance

**SOURCE REVIEW: PASSED within the finite approved F1/F3/F2 financial scope. No remaining source blocker identified. QUALIFICATION: BLOCKED.** CR-01–06 and source robustness warning WR-02 are resolved on the current tree. Three open warnings track evidence chronology, admin host/browser qualification and a pre-existing MEDIUM token-revocation/expiry follow-up (WR-04), not a newly introduced CR-05/06 financial source regression. WR-04 is not fixed or security-waived by this finite pass. The frontmatter pass is local source disposition only: it is not full Phase 05, ASVS-level, requirements, production or release clearance.

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

### WR-04: OPEN pre-existing token revocation/expiry boundary — separate security follow-up

**Classification:** MEDIUM security concern, tracked as WARNING for this finite financial commit disposition; OPEN / NOT FIXED / NOT WAIVED. Not a new CR-05/06 financial source blocker or global security pass.
**Files:** `infinitemarkets/views_public_api.py:321–345,359–378`; `infinitemarkets/services/orders.py:439–454,1444–1485`.

**Concrete source-derived interleave:** A request matches its still-valid presented token hash and passes expiry in `_order_for_token`. Before its later content transaction takes the order lock, token reissue commits a replacement hash (or the token deadline passes). Delivery/payable helpers refresh by order/merchant ID, not by the presented token digest/current token expiry. Thus an already token-admitted in-flight request can return otherwise financially authorized content after rotation/expiry. The documented reissue promise at `orders.py:1447–1448` says the old token is revoked immediately; the source does not implement the stronger interpretation that all previously admitted but unfinished requests lose content authority at rotation. This is an honest revocation-contract/privacy risk, not dismissed because it predates the tranche.

**Lineage and linearization:** Independently read `git show bf99ec0b252f6ecff38eadb377d16d57def3576a:infinitemarkets/views_public_api.py`. Baseline :321–345 has the same token lookup/expiry check outside the later content reads; baseline :359–377 resolves once then retrieves goods/invoice by order ID without revalidating the presented credential. Current financial locks do not introduce that authentication-admission separation, though lock waits can lengthen its window. The shown interleave is an overlapping request admitted at the earlier valid-token lookup, not evidence that a fresh old-token lookup begun after committed rotation succeeds. With lookup as the authorization linearization point, rotation rejects subsequent lookups but does not retract admitted requests; with content acquisition as the intended boundary, the missing recheck is a defect requiring separate authorization hardening. Expiry has the same admission-versus-use distinction. No runtime reproduction, real-record incidence or after-rotation new admission was demonstrated in this disposition.

**Follow-up property / regression criteria, not work authorized now:** Explicitly settle the immediate-revocation contract and, if strict content-boundary revocation is required, retain/revalidate the presented digest and current token expiry within the caller-owned locked transaction before private content use. Separately authorized barrier coverage should distinguish lookup-before-rotation/expiry from lookup-after-rotation/expiry, inspect actual private content, and preserve generic token failure behavior and valid positives. No auth code or tests are changed/run here; this paragraph records the open concern, not a new implementation task or waiver.

**Finite commit threshold:** This pre-existing MEDIUM issue does not reopen resolved CR-01–06 or require unauthorized broad auth changes before the user's scoped local financial commit. Local commit is appropriate after parent-owned final checks/scope review, with WR-04 explicitly retained OPEN, then pause. Production/security/release remain blocked; baseline lineage alone never clears the security concern.

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
