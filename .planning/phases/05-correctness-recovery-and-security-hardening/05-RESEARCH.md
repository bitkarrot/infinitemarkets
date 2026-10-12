---
phase: 05-correctness-recovery-and-security-hardening
researched: 2026-10-11
status: research_complete
scope: complete
---

# Phase 5 Research — Correctness, Recovery, and Security Hardening

## Evidence and execution boundary

Research used independent Devin agents in GSD researcher/pattern-mapper roles,
followed by source checks and corrections by the orchestrator. Planning/checking
will use separate contexts. The working-tree baseline is `8072742616e69c757092fc35fe4ba39e52794b2b`;
the application tree remains the reviewed `a7082c7` implementation. Research is
not test execution or release clearance. No application fixes or new test passes
are claimed here. MemPalace is disabled; native context and source remain primary.

The user authorized planning **all HARD-01 through HARD-08**, then implementing
**F1–F3 only** and pausing before F4–F6/CI-01. The financial dependency order is
**F1 → F3 → F2**: clearing the incidental timeout hold before enforcing inventory
accounting could expose an unaccounted paid order.

## Locked refinements from this planning session

- **Historical orders: audit first.** No background sweep, no automatic clearing of
  already-settled legacy holds, no automatic historical stock repair. Defensive
  read/fulfillment guards must fail closed for unpaid legacy `confirmed` rows.
  Existing damaged records remain an operator-review release gate.
- **Unallocated verified settlement: cancel into the existing review lane.** Keep
  the correlated payment `settled`, atomically release remaining held capacity,
  cancel with an explicit bounded inventory-loss reason, and retain an exception.
  Existing authenticated `accept|refund|confirm-refund` semantics apply; no automatic
  reopening or outgoing refund, and no new accept-state contract.
- **PostgreSQL sandbox explicitly approved.** Create only the new cluster at
  `/tmp/infinitemarkets-phase5-pg-1ae80f8`; the runtime fixtures may run
  `DROP SCHEMA IF EXISTS infinitemarkets CASCADE` only in its synthetic database.
  Stop and remove that specific newly created cluster after checks. Never connect
  these destructive fixtures to an existing database. SQLite remains isolated too.
- Keep `ORDER_TRANSITIONS` literal and unchanged; actor authority belongs around it.
- Automatically resolve only `invoice-creation-unknown`, not
  `invoice-correlation-failed`, amount/wallet/multiple-payment holds, reasonless
  active holds, or a manual refund decision. Do not invent a resolution enum;
  documented values remain `unresolved|accepted|refund_requested|refund_confirmed`.
- No new dependency, security-policy relaxation, production application deployment,
  live relay write, real-funds operation, or push is authorized by this tranche.

## Standard stack and reusable boundaries

The current extension uses Python async services and the pinned LNbits host,
`DomainTransaction`, SQLite `BEGIN IMMEDIATE`, PostgreSQL row locks/CAS,
transactional audit/email/Nostr outbox intents, and FakeWallet runtime fixtures.
No additional library is needed. Follow the cached LNbits AGENTS guidance without
editing cached/vendor files. Use `make host`, focused `uv run pytest` selections,
and `make lint`; only complete qualification emits authoritative release evidence.

Sources: `infinitemarkets/db.py` (`DomainTransaction`, `for_update`, `now`),
`services/orders.py` (`transition_order`, `release_reservations`, `cancel_order`),
`services/catalog.py` (`enqueue_stock_projection`), `tests/runtime/conftest.py`,
`Makefile`, and `.github/workflows/qualification.yml`.

## F1 — payment-backed merchant authority and delivery

`admin_set_status()` currently permits every generic table edge, including unpaid
confirmation and cancellation without stock release. Preserve table parity, but
allow merchant fulfillment commands only through legal paid transitions
`confirmed → processing → completed`, with a verified settled projection and no
active payment exception. Preserve explicit disclosed physical backorder behavior;
`oversold` alone is not a blanket physical-fulfillment ban. Shipping commands need
the same payment/hold authority rather than only shipping-table legality.

Route status cancellation through the existing transactional cancellation service;
do not nest `DomainTransaction`. Preserve merchant ownership and 404 scoping,
422 `invalid-transition`, cookie/bearer/CSRF enforcement, and response shapes.
The existing status body need not gain a new field: pre-confirm cancellation can
use status; reason-bearing exceptional paid cancellation uses `/cancel`. Require
an explicit reason after payment/confirmation and do not imply a refund.

`digital_delivery()` is shared by public-token status, buyer history and confirmed
email. Add explicit settled-projection evidence rather than trusting state alone,
including already-corrupt unpaid confirmed/processing/completed rows. Adjust
merchant action affordances and positive test setup to use real FakeWallet
settlement instead of the faulty merchant-confirm shortcut.

Permanent regressions: unpaid confirmation rejected without state/inventory/
notification change; unpaid legacy delivery and fulfillment blocked; permitted
cancellation releases capacity exactly once across entry points; paid fulfillment
and appropriate shipping still work; holds remain blocked and ownership/CSRF remain.

Sources: `services/orders.py`, `views_api.py`, `views_public_api.py`,
`services/email.py`, `services/order_messages.py`, `static/infinitemarkets/js/admin_orders.js`,
`tests/runtime/test_order_admin.py`, `test_public_contract.py`, `test_nostr_signin.py`,
`test_email_queue.py`, `test_release_a_journey.py`, and browser merchant journeys.

## F3 — complete accounting before normal confirmation

`confirm_settlement()` currently consumes whatever held rows exist. Compare the
full expected quantity map from `order_items` against held reservations before
normal confirmation; empty, partial, extra or inconsistent coverage cannot silently
confirm. Preserve incoming settlement evidence even when fulfillment becomes an
explicit inventory exception. The approved fallback is cancellation plus hold and
atomic release of leftover capacity, not false invoice expiry or automatic acceptance.

Expiry must lock/recheck the order and current reservation deadlines inside its
transaction. A stale pre-attachment expiry selection cannot release freshly aligned
holds or confirmed consumption. For `invoice_pending` whose allocation expires,
cancel with a bounded reservation-expiry reason while retaining the recoverable
projection; subsequent attachment keeps cancellation and suppresses BOLT11 delivery,
and settlement follows the existing manual late-payment lane.

Manual `accept` needs repeat-safe accounting: existing consumed quantities and
prior accepted allocations (`accepted` plus recorded `backordered_qty`) must not be
charged again after paid cancel/reaccept. Account residual own holds, allocate only
unaccounted/outstanding units, preserve other buyers' reservations, keep finite stock
nonnegative, and enqueue stock projections for real changes. Unlimited products
already initialize `backordered_qty` to zero: preserve this, do not claim a nonexistent
unlimited-stock defect. Unknown/malformed accounting must fail closed, not be guessed.

Use deterministic locks covering leaf products and variant parents touched by
stock projection, consistent with checkout's merchant scope and the order/reservation
paths. Avoid order/merchant/product lock inversions. Test PostgreSQL competing
checkout/accept and accept/accept operations, shared variant parents, expiry/attachment/
settlement ordering, partial coverage, duplicate callbacks and repeated reaccept.
Do not alter the literal state machine or broaden `accept` beyond expired/cancelled.

Sources: `services/settlement.py`, `services/checkout.py`, `services/orders.py`,
`services/catalog.py`, `db.py`, `tests/runtime/test_order_saga.py`, `test_checkout.py`,
`test_catalog_variants.py`, and `test_nip17_inbox.py`.

## F2 — verified active-flow recovery without weaker holds erasing stronger ones

`_mark_unknown()` currently updates the payment then overwrites the order's reason.
Use the existing order-lock convention before the projection update and preserve an
active stronger or reasonless hold and any manual resolution/refund decision.
A subsequent timeout must not relabel those holds as auto-clearable uncertainty.

Recover the exact original invoice, never issue a second one. Resolve only the
current `invoice-creation-unknown` condition after successful correlation and an
inventory-safe active recovery boundary. Inspect buyer QR/on-hold behavior: a recovered
unpaid invoice must remain usable, not be circularly blocked until it is paid.
After F3 guards exist, successful new attachment with complete live reservation
coverage may resolve creation uncertainty; verified normal settlement with complete
stock consumption may also resolve it. Never clear on terminal attachment, lost
capacity, mismatches, manual refund decisions, or the already-settled legacy no-op
branch. Clear closed reason/resolution to NULL rather than adding `invoice-recovered`.
Keep transactional message/email snapshots consistent with the resolved state.

Permanent regressions: persist-then-timeout → unique recovery → usable invoice →
verified settlement → stock-accounted delivery; recover/replay does not duplicate an
invoice or consume again; wallet/amount/correlation/multiple-payment/reasonless holds
survive valid recovery; timeout cannot overwrite stronger holds; cancelled/expired or
unallocated recovery stays explicit review; preexisting settled holds are not swept.

Sources: `services/checkout.py`, `services/settlement.py`, `services/orders.py`,
`static/infinitemarkets/js/public_order.js`, `public_checkout.js`, and
`tests/runtime/test_order_saga.py`.

## F4/F5 — future durable outbox plan

For F4, the existing FK-bound dependency row already carries `aggregate_revision`:
no `required_revision` column is necessary. Bind satisfaction to the intended row or
an actually published valid replacement at/after its revision, scoped to merchant,
aggregate and kind. A stale revision or kind-5 deletion cannot substitute. Cover
supersession, reference removal and tombstone ordering. Manual `relay.prune_outbox()`
currently deletes edges on both sides; preserve prerequisites still needed by retained
intents rather than allowing pruning to erase ordering. Do not fake replacement proof.

For F5, `_cas_state(..., bump_attempts=False)` is an existing mechanism for waits.
No-route waiting should not consume ordinary send failures; continue claim eligibility
through the 48-hour deadline, retain 15-minute discovery cadence and deterministic
terminal behavior, and keep genuine send-failure budgets/fencing/copy evidence intact.
Test >20 waits, route arrival within the window, exact boundary, send failures and stale
claim recovery without changing enforcement or live relay behavior.

Sources: `services/outbox.py`, `services/relay.py`, `migrations.py`,
`tests/runtime/test_outbox.py`, `test_nip17_outbox.py`, and `test_catalog_events.py`.

## F6/CI-01 — future bounded admission and process-lifecycle plan

Pending inbox work is `processed_state IN ('received','validated')`; successful
`processed` and other terminal states do not count. Serialize merchant/scope before
count-then-insert inside `DomainTransaction` (SQLite writer serialization; PostgreSQL
merchant-row lock consistent with current patterns), enforce 1,000 at admission before
decrypt, add the scoped backlog index in a small additive migration, and use bounded
metrics. Preserve dedupe, rate/blocklist limits, other scopes and minute-window resets.
Test same-scope 999/1000 boundaries and multi-connection races, not merely total 1,300
messages across five relays.

CI-01 is **not diagnosed**: 19 assertions followed by failure to exit is a failed
process run. Plan first reproduces both file orders, captures pending resources/tasks,
fixes the demonstrated lifecycle cause, then requires exit 0 in both orders and the
normal suite. Candidate resources are not an established root cause. No forced exits,
skips, weakened controls or treating timeout termination as success.

Sources: `services/inbox.py`, `db.py`, `migrations.py`, `tests/runtime/test_intake_abuse.py`,
`test_release_b_drills.py`, `test_db.py`, `test_install.py`, and both conftest files.

## Validation Architecture

Each financial repair gets permanent failing-then-passing runtime regressions, with
baseline failure cause and post-fix process exit recorded. Use focused existing file
selections for feedback; avoid the known DB/install pair until HARD-07 is repaired
unless deliberately diagnosing that gate. Such exclusion is a scoped feedback run,
not full-suite qualification or closure of CI-01.

- F1: order-admin, public-contract, buyer-history, email, Nostr cancellation and paid
  merchant browser journeys; node syntax for changed application JS.
- F3: saga/checkout/variants and deterministic competing allocation + expiry ordering
  on both SQLite single-process and the approved disposable PostgreSQL profile.
- F2: saga timeout/recovery, invoice uniqueness, usable buyer payment request, exception
  preservation and F3 interaction on both supported databases.
- Financial tranche: `make host`, explicit affected runtime files, `make lint`, relevant
  FakeWallet browser paths and independent code/security review; clean exit required.
- Whole phase/HARD-08 later: full durable qualification and all existing Linux
  SQLite/PostgreSQL × x86_64/ARM64 CI profiles, relevant conformance and browser tests,
  ASVS L1 with high-severity blocking unchanged, and separately authorized live Plebeian
  checkout/payment. No listing-only, local shim or FakeWallet substitution.

Evidence must name revision, topology, command, counts/skips and process exit. Local
financial evidence does not close later plans, live gates, existing-order operator audit,
or restore the withdrawn production-readiness claim.

## Open/closed design questions

Execution extent, legacy repair policy, disposable PostgreSQL teardown, and stock-review
state were explicitly decided by the user. Implementation choices must respect those
boundaries. F4 required-revision identity and F6 pending-state definitions are resolved
by current schema/lifecycle; no speculative schema expansion or policy fork is needed.
S1–S4 and optional integrations remain deferred. Full financial code review must revisit
concurrency and independent holds before declaring the tranche verified.
