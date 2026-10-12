---
phase: 03-release-b-gamma-nip-17-orders
plan: 02
subsystem: nostr-orders
tags: [nip-17, gift-wrap, order-messaging, inbox, outbox, dual-copy, abuse-defenses, retention]

requires:
  - phase: 03-release-b-gamma-nip-17-orders/03-01
    provides: m006 inbox schema, keystore nip17_wrap/unwrap, kind-1059
      sessions/admission/cursors, peer kind-10050 discovery, durable outbox
      with relay_publications.delivery_copy
provides:
  - >-
    rumor<->domain adapter (order_messages.py): build_checkout_payload,
    canonical rumor descriptors frozen at enqueue, enqueue_order_msg at
    revision 0 with per-order msg_seq aggregate ids
  - gamma_order_intake reusing the canonical _resolve_cart/_price_cart/
    begin_saga pipeline — protocol='gamma', buyer_pubkey_enc/hash,
    ix_orders_nostr_external_id request-hash dedupe, no public token,
    buyer amount stored as buyer_amount_sat and never trusted
  - >-
    full validated-row dispatch: type-1 intake, type-3 buyer status
    (cancelled-only, constant-time sender-hash match, §7.1 legality),
    kind-17 receipt (cosmetic receipt_verified only), kind-14 DM
    threading (order vs Unknown), merchant-authored sender-copy recovery,
    D-22 status=rejected replies
  - >-
    order_msg outbox branch: two independent nip17_wraps per attempt,
    recipient copy to buyer peer_relays, sender copy to merchant inbox,
    delivery_copy-scoped accepted evidence, published iff >=1 accepted in
    EACH class, class-scoped partial retry, §9.3 no-route pending/15-min
    refresh/48h failed
  - type-2/3/4 outbound enqueues in-transaction on every legal gamma
    transition; merchant compose/reply kind-14 admin routes
  - rejected-intake admin surface + idempotent mute -> inbox_blocklist
  - >-
    admission-abuse ordering: blocklist + per-author cap before
    validation, muted-author bounded growth, per-inner-buyer DM cap
  - §8.7 reconcile resume of received|validated inbox rows + type-2
    re-enqueue; refresh_stale_peer_relays no-route sweep (fresh 10050
    re-resolution + 48h fail) on a 15-min cadence under the
    reconciliation lease
  - >-
    retention: processed inbox ciphertext 7d, rejected/quarantined 30d,
    expired peer_relays purged
affects: [03-03, 03-04]

actuals:
  tokens: ~150000
  tasks: 3
  commits: 3

tech-stack:
  added: []
  patterns:
    - "Frozen descriptor + revision-0 aggregate ids: order_msg intents
      rebuild the SAME canonical rumor id on every retry while
      seal/wrap/outer ids stay fresh; <order_id>:<msg_seq> keeps
      per-order ordering without supersession"
    - "delivery_copy-scoped evidence: relay_publications rows carry
      recipient|sender so one class's acceptance can never satisfy the
      other; retries subtract accepted targets per class"
    - "No-oracle intake: identical outcome for known-vs-unknown order
      tags; threading only on constant-time sender-hash match"
    - "Bounded drop rows: muted/over-cap inner authors leave ONE
      auditable rejected row per burst window carrying author_hash/
      author_enc (mute-able); later drops are metric-only deletes"

key-files:
  created:
    - infinitemarkets/services/order_messages.py
    - tests/runtime/test_nip17_inbox.py
    - tests/runtime/test_nip17_outbox.py
    - tests/runtime/test_intake_abuse.py
  modified:
    - infinitemarkets/services/inbox.py (stage-3 dispatch, muted-drop rows
      carry author_hash/author_enc, inbox.drain.unwrap metric)
    - infinitemarkets/services/checkout.py (gamma_order_intake)
    - infinitemarkets/services/outbox.py (order_msg dual-copy branch)
    - infinitemarkets/services/orders.py (type-3/4 in-tx enqueues)
    - infinitemarkets/services/settlement.py (inbox resume, type-2
      re-enqueue, rejected/quarantined retention + peer_relays purge)
    - infinitemarkets/services/peer_relays.py (no-route sweep)
    - infinitemarkets/services/tasks.py (15-min peer-relay refresh
      cadence under the reconciliation lease)
    - infinitemarkets/views_api.py (rejected-intake/mute + compose/reply
      routes; source_relay_url + package-relative crypto import fixes)
    - infinitemarkets/keystore.py (sender-copy p-tag relaxation)

key-decisions:
  - "msg_seq = order_messages count + 1 inside the enqueueing tx; the
    aggregate id <order_id>:<seq> preserves order while revision 0 keeps
    order_msg intents immune to supersession (§7.4)"
  - "Recipient resolution happens at publish time inside the order_msg
    branch (never at enqueue) so a buyer's fresh kind-10050 is honored;
    refresh_stale_peer_relays force re-resolves no-route recipients on
    the 15-min cadence and fails intents 48h after first enqueue"
  - "Rejected-reply intents use aggregate_id 'rejected:<inbox_event_id>'
    — deterministic, self-deduping, and carry only the buyer's own
    external id (D-22)"
  - "Inbound type-2 is rejected 'inbound-type2-unsupported'; kind-17
    verifies bolt11 equality + sha256(preimage)==payment_hash and only
    sets the cosmetic receipt_verified badge — settlement stays
    LNbits-listener only"

patterns-established:
  - "Dual-copy publish: one descriptor -> two nip17_wraps -> two
    disjoint declared-relay target sets -> per-class evidence ->
    published only when both classes hold >=1 accepted"
  - "Crash-replay dedupe stack: outer_event_id UNIQUE at admission,
    (merchant, rumor_id) guarded update at drain,
    ix_orders_nostr_external_id + request_hash compare at intake —
    replaying any checkpoint is a no-op"

requirements-completed: [GAM-02, GAM-03, GAM-04]

coverage:
  - id: D1
    description: "Wrapped type-1 order -> canonical pipeline -> gamma
      order (server-priced, buyer amount stored-not-trusted) ->
      awaiting_payment -> type-2 order_msg intent"
    requirement: GAM-02
    verification:
      - kind: integration
        ref: tests/runtime/test_nip17_inbox.py#test_type1_creates_gamma_order_and_type2_intent
        status: pass
    human_judgment: false
  - id: D2
    description: "Dual-copy order_msg publication: recipient copy only
      to buyer kind-10050 relays, sender copy only to merchant inbox,
      delivery_copy evidence, published needs both classes, partial
      retry is class-scoped, no-route 15-min/48h policy"
    requirement: GAM-03
    verification:
      - kind: integration
        ref: tests/runtime/test_nip17_outbox.py (dual-copy, partial
          acceptance, no-route policy tests)
        status: pass
    human_judgment: false
  - id: D3
    description: "Inbound matrix: buyer cancelled legal/illegal, foreign
      sender no-oracle, buyer type-2 rejected, kind-17 cosmetic receipt,
      kind-14 sender-hash threading + Unknown folder, DM rate cap,
      merchant compose/reply, sender-copy recovery, revision-0
      non-supersession"
    requirement: GAM-03
    verification:
      - kind: integration
        ref: tests/runtime/test_nip17_inbox.py (Task-2 block)
        status: pass
    human_judgment: false
  - id: D4
    description: "Intake abuse + durability: admission ordering, per-
      relay/per-author caps dropping before validation, muted-author
      bounded growth, rejected-intake + idempotent mute surface,
      crash-resume (received|validated replay = single order), same
      rumor via two relays = one message, retention erasure schedule"
    requirement: GAM-04
    verification:
      - kind: integration
        ref: tests/runtime/test_intake_abuse.py (10 tests)
        status: pass
    human_judgment: false

duration: ~3h across two executor sessions
completed: 2026-09-28
status: complete
---

# Plan 03-02 Summary

**Wrapped NIP-17 kind-16 orders now ride the identical pricing/inventory/invoice
pipeline as web checkout, with every merchant reply published as two
independently-evidenced wraps to disjoint declared-relay sets — plus hostile-
intake bounding, crash-resume, and ciphertext retention.**

## Performance

- **Duration:** ~3h (two executor sessions — interrupted mid-Task-3, resumed)
- **Tasks:** 3
- **Files modified:** 11 production + 3 test files (35 new runtime tests)

## Accomplishments

- `services/order_messages.py` (919 lines): `build_checkout_payload` §6.9 tag
  decode with cross-merchant/opaque-address/charset rejections; canonical
  frozen-`created_at` rumor descriptors; `enqueue_order_msg` writing
  record-bound `payload_enc` + revision-0 intents + 'out' `order_messages`
  rows in the caller's transaction; `handle_inbound_status`/`handle_receipt`/
  `handle_dm`/`thread_message`; `enqueue_payment_request`/`enqueue_status`/
  `enqueue_shipping`/`enqueue_rejected_reply`; `compose_dm`/`reply_dm`;
  `reenqueue_payment_requests` for §8.7.
- `checkout.gamma_order_intake` — buyer kind-10050 resolves BEFORE any insert;
  `ix_orders_nostr_external_id` dedupe with request-hash compare else
  `duplicate-order-conflict`; per-buyer open-order cap; `protocol='gamma'`,
  `buyer_pubkey_enc/hash`, `source_event_id`, `buyer_amount_sat`, no
  `public_token`.
- `outbox._publish_order_msg` — exactly two `nip17_wrap` calls per attempt,
  `delivery_copy` 'recipient'/'sender' evidence, `published` iff ≥1 accepted
  in EACH class, accepted targets subtracted per class on retry, §9.3
  `no_inbox_relays` pending with 15-min next-attempt and 48h deadline.
- `inbox._dispatch_validated` — routes kinds 16 (type 1/2/3), 17, 14, plus
  merchant-authored sender-copy recovery (`sender-copy-recovered` mark, zero
  domain writes) and D-22 rejected replies.
- `settlement.reconcile` — resumes `received`+`validated` inbox rows via
  `drain_and_process` and re-enqueues type-2 payment requests for
  `awaiting_payment` gamma orders missing the out-message.
- `settlement.retention_prune` — `rejected|quarantined` ciphertext erased at
  30d (`INBOX_QUARANTINE_RETENTION_S`), expired `peer_relays` purged, counts
  reported.
- `views_api` — `GET /merchants/{id}/rejected-intake` (bounded page, author
  npub handle) + `POST .../mute` (idempotent `inbox_blocklist` insert) +
  `POST /messages/compose` + `POST /messages/conversations/{id}/reply`.
- `peer_relays.refresh_stale_peer_relays` — extended with the §9.3 no-route
  sweep: pending `no_inbox_relays` `order_msg` intents get a descriptor-bound
  recipient decrypt + cache-busted re-resolve; intents past the 48h deadline
  are marked `failed`. Scheduled every 15 min under the `reconciliation`
  lease (`tasks.PEER_RELAY_REFRESH_INTERVAL_S`).

## Task Commits

1. **Tasks 1–2 (tracer + rumor matrix)** — `c608c23`
   `feat(03-02): gamma order intake + validated dispatch + dual-copy
   order_msg publishing` (prior session; 14 runtime tests)
2. **Task 3 (abuse + durability + retention)** — this session:
   `feat(03-02): intake abuse defenses + durability drills + retention
   evidence` (10 abuse tests + 11 Task-2 inbox tests; three committed-code
   fixes described under Deviations)
3. **Evidence refresh** — `chore(03-02): refresh qualification evidence`
   (regenerated by `GAMMA_QUAL_EVIDENCE=1 make verify`)

## Files Created/Modified (this session)

- `infinitemarkets/services/peer_relays.py` — no-route sweep in
  `refresh_stale_peer_relays` (+83 lines)
- `infinitemarkets/services/tasks.py` — 15-min refresh cadence
- `infinitemarkets/services/inbox.py` — `inbox.drain.unwrap` metric;
  `author_hash`/`author_enc` on rate-limited/blocked drop rows
- `infinitemarkets/views_api.py` — `source_relay_url` column fix;
  `from . import crypto` fix
- `tests/runtime/test_intake_abuse.py` — NEW, 10 tests
- `tests/runtime/test_nip17_inbox.py` — +457 lines (Task-2 matrix:
  cancel legality, oracle-freedom, receipts, DM threading/caps,
  compose/reply, revision-0)

## Decisions Made

- No-route sweep lives in `peer_relays.refresh_stale_peer_relays` (per the
  plan text) but the deadline constant stays owned by `outbox.py`
  (`ORDER_MSG_NO_ROUTE_DEADLINE_S`) — function-level import avoids the
  peer_relays<->outbox module cycle.
- The 15-min cadence rides the existing `reconciliation` leased loop rather
  than a ninth worker — lease discipline is preserved and no new task row
  is needed.
- Cursor crash-drills (j) remain covered by 03-01's `test_inbox_transport`
  EOSE/cursor tests; the dispatch path adds no new cursor semantics, so no
  duplicate drill was added — noted rather than silently dropped.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule — blocking] `source_relay` vs `source_relay_url` column mismatch**
- **Found during:** Task 3 (admin-surface test run)
- **Issue:** `_list_rejected_intake` selected `source_relay` — no such column
  (schema: `source_relay_url`); the GET endpoint would have 500'd on first
  call. The in-flight test inherited the same wrong name in its INSERT.
- **Fix:** views_api selects `source_relay_url` (JSON key `source_relay`
  retained); test INSERT corrected; dropped a second phantom column
  (`outer_author`) from the same INSERT.
- **Files modified:** `infinitemarkets/views_api.py`,
  `tests/runtime/test_intake_abuse.py`
- **Verification:** `test_rejected_intake_admin_surface_and_mute` passes.
- **Committed in:** Task-3 commit

**2. [Rule — blocking] `from .. import crypto` beyond top-level package**
- **Found during:** Task 3 (admin-surface test run)
- **Issue:** `views_api.py` (top level of the `infinitemarkets` package)
  used `from .. import crypto` — `ImportError` on first call of the
  rejected-intake/mute handlers.
- **Fix:** `from . import crypto` in both helper functions.
- **Files modified:** `infinitemarkets/views_api.py`
- **Verification:** admin-surface + mute tests pass.
- **Committed in:** Task-3 commit

**3. [Rule — missing critical] muted/capped drop rows lacked `author_hash`/`author_enc`**
- **Found during:** Task 3 (`test_muted_author_bounded_growth` failed with
  3 kept rows instead of 1)
- **Issue:** the drain's `author-blocked`/`author-rate-limited` UPDATEs
  never set `author_hash`, so the burst-window `prior` lookup could never
  match — every muted wrap kept a row (unbounded growth), and the kept row
  was un-muteable from the admin surface (no author handle).
- **Fix:** both marks now write `author_hash` + `author_enc`.
- **Files modified:** `infinitemarkets/services/inbox.py`
- **Verification:** muted test passes (1 auditable row, 2 metric-only
  deletes); admin mute works on drop rows.
- **Committed in:** Task-3 commit

**4. [Rule — missing critical] `inbox.drain.unwrap` metric never incremented**
- **Found during:** Task 3 test review — the flood-cap assertion
  `unwrap_delta <= cap` was vacuous (counter absent).
- **Fix:** `metrics.incr("inbox.drain.unwrap")` added at the top of
  `_process_received`, making the drop-before-validation bound real.
- **Files modified:** `infinitemarkets/services/inbox.py`
- **Verification:** `test_per_author_flood_drop_before_validation` passes
  with a non-vacuous bound.
- **Committed in:** Task-3 commit

---

**Total deviations:** 4 auto-fixed (all correctness bugs in committed code or
vacuous assertions — no scope creep)
**Impact on plan:** Required for the acceptance criteria to be honestly met.

## Issues Encountered

- Previous executor session ended mid-Task-3 with the test files uncommitted.
  Evaluation found them structurally sound; the failures traced to two
  committed-code bugs (above), not the tests.
- `test_reconcile_resumes_inbox_rows` initially admitted both wraps before
  draining — `drain_received` drains the whole batch, so the 'received' park
  required admitting wrap B *after* the drain. Fixed by reordering.
- `outbox_events.next_attempt_at` is NOT NULL — the 48h fail UPDATE uses `0`
  (the outbox's own convention).
- `infinite-markets-blue.gif` (user asset, untracked) disappeared from the
  working tree between session start and end without any action from this
  executor; the `.png` remains untouched and uncommitted as instructed.

## User Setup Required

None.

## Next Phase Readiness

- 03-03 (Messages surface, attributed-web-order copies) can consume
  `order_messages` rows, `compose_dm`/`reply_dm`, and the rejected-intake
  endpoints directly.
- Inbound PUBLIC kind-16/17 events remain explicitly out of scope (03-04
  known-delta, per plan scope note).

## Self-Check: PASSED

- `make verify-runtime`: **300 passed, 2 skipped** (was 265)
- `make verify` (full incl. qualification): **520 passed, 3 skipped** (was 485)
- `make verify-fast`: 33 passed. `make lint`: ruff clean.
- All three tasks' acceptance criteria verified (gamma order `protocol`/`NULL`
  public token, dual `nip17_wrap` + `delivery_copy` classes, dedupe/no-oracle/
  sender-copy semantics, admin surface, reconcile resume, retention bounds,
  no-route lifecycle).

---
*Phase: 03-release-b-gamma-nip-17-orders*
*Completed: 2026-09-28*
