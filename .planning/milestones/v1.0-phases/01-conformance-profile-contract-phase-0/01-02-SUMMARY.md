---
phase: 01-conformance-profile-contract-phase-0
plan: 02
subsystem: testing
tags: [sqlite, postgresql, transactions, fencing, saga, outbox, inbox, email, cryptography, state-machines, qualification-harness, pytest]

# Dependency graph
requires:
  - phase: 01-conformance-profile-contract-phase-0
    plan: 01
    provides: dialect-switching qualification harness (LNBITS_DATABASE_URL), section-14 transaction adapter skeleton, evidence plugin + P0 coverage map, markers, fresh-database-per-test fixture
provides:
  - Full normative-subset model schema (16 tables + partial indexes, both dialects) for the executable models
  - Complete section-14 adapter: multi-item sorted-id claims, dialect-specific section-8.6 queue claims (PG FOR UPDATE SKIP LOCKED / SQLite BEGIN IMMEDIATE), task-lease fencing, claim-token leased writes
  - transition_order() enforcing the full section-7.1 table with same-transaction order_events audit rows, plus sections 7.2-7.5 golden tables (D-08)
  - Executable section 8.2/8.3/8.4/8.7 invoice-saga model with the controllable fake LNbits payment boundary (crash window, suppressed callbacks, pause gate, per-order invoice-call counts)
  - Executable section 8.5/8.6/8.7 inbox/outbox/relay-cursor recovery models (durable publication evidence, claim-token CAS requeue, stable rumor ids, EOSE-only cursors)
  - Executable section 8.8 email worker + section 11.3/11.4 crypto models (per-recipient dedupe, boolean SMTP boundary, hashed rate limits, public tokens with AEAD copy, PII-free logs)
  - P0-06..P0-10 evidence suites (60 db tests) recorded in the existing evidence bundle
affects: [01-03-conformance-closure, phase-2-planning]

actuals:
  tokens: 87958   # chars/4 over the realized diff (351,831 chars across 15 files)
  tasks: 3
  commits: 3   # measured: git rev-list --count 4f78225..HEAD

tech-stack:
  added: []   # no new packages; cryptography was already a locked host dependency
  patterns:
    - Dialect-specific queue claims in one transaction: lock-select -> update -> fetch, with PostgreSQL FOR UPDATE SKIP LOCKED (SQLAlchemy 1.4 + asyncpg returns no rows from raw text() UPDATE...RETURNING) and SQLite select-then-update under BEGIN IMMEDIATE
    - ON CONFLICT DO NOTHING for deterministic-id idempotent intent inserts (PostgreSQL aborts transactions on constraint violations, so IntegrityError catch-and-continue is not dialect-portable)
    - Durable evidence split from fenced outcome writes: relay_publications rows are append-only positive-ACK evidence; the outcome-policy state write is the only claim-token-CAS-fenced step
    - Synthetic non-secret BOLT11 in the *_enc projection columns, documented (the section 11.3 envelope discipline is exercised by P0-09 for recipient/token data)
    - AES-256-GCM per-record-AAD envelope + purpose-separated keyed HMAC equality hashes under synthetic test keys (section 11.3 discipline)
    - QualWorker parallel Database handles: one engine + asyncio lock per worker over the same SQLite file / PostgreSQL schema, because the host serializes connections per Database object

key-files:
  created:
    - harness/state.py
    - harness/saga.py
    - harness/queues.py
    - harness/email.py
    - tests/qualification/test_p0_07_cancellation_saga.py
    - tests/qualification/test_p0_08_recovery_closure.py
    - tests/qualification/test_p0_09_email_persistence.py
    - tests/qualification/test_p0_10_smtp_boundary.py
  modified:
    - harness/schema.py
    - harness/tx.py
    - harness/db.py
    - tests/qualification/test_p0_06_transactions.py
    - .gitignore
    - evidence/manifest.json
    - evidence/REPORT.md

key-decisions:
  - "PostgreSQL queue claims run as lock-select -> update -> fetch inside one transaction instead of a single UPDATE...RETURNING: SQLAlchemy 1.4 + asyncpg returns no rows from raw text() UPDATE...RETURNING (ResourceClosedError); the FOR UPDATE SKIP LOCKED concurrency semantics are preserved exactly."
  - "Idempotent intent inserts use ON CONFLICT DO NOTHING with deterministic ids (obx-<order>-<intent>) instead of catching IntegrityError: PostgreSQL aborts the whole transaction after any constraint violation, so catch-and-continue would poison the surrounding domain transaction."
  - "Outbox publication evidence is durable and append-only, recorded separately from the fenced outcome-policy write: this models the real section 8.6 crash point (relay OKs recorded, outcome write lost) and makes stale-claim reconstruction honest — a stale worker's genuine positive ACK survives while its state write is fenced."
  - "A cancelled order's payment projection is retained (hash/BOLT11/wallet snapshots persisted regardless of state) with BOLT11 delivery and payment-request enqueue only for invoice_pending orders — the late-settlement detection path, exactly section 8.2 step 3 and decision 24."
  - "Products gained created_at/updated_at (present in spec section 4.3) because the reservation release/consume and republication writes need them; email_queue intentionally has NO updated_at per section 4.18, so the shared claim takes a touch_updated_at flag."
  - "Backoff jitter is deterministic (0) in the models: the spec's 0-5s jitter is a deployment property; exact restart assertions are the model's contract (D-08 determinism)."

patterns-established:
  - "Executable-model + controllable-fake discipline: every external boundary (LNbits core, SMTP) is a documented fake whose outcome set mirrors only qualified P0-03 behaviors, with programmable crash points (pause gate, suppressed callback, crash_after_smtp)"
  - "Exactly-once assertions always re-read durable state (reservation rows, stock counters, call counts) after restarts — never trusting the happy-path return values"
  - "No plaintext in the database is proven byte-level (raw SQLite file search) plus per-column scans on every dialect, not just by absence in model APIs"

requirements-completed: [QUAL-06, QUAL-07, QUAL-08, QUAL-09, QUAL-10]

coverage:
  - id: D1
    description: "Full model schema + section-14 transaction adapter + section-7.1 order state machine: last-unit concurrency with exactly one winner and complete loser rollback on both dialects, sorted-id deadlock avoidance, host auto-commit splitting proof, task-lease fencing, FK enforcement, UNIQUE-scope idempotency, exhaustive 7.1 transition table with order_events audit rows"
    requirement: QUAL-06
    verification:
      - kind: unit
        ref: "tests/qualification/test_p0_06_transactions.py (19 tests; make host && make verify-db)"
        status: pass
    human_judgment: false
  - id: D2
    description: "Cancellation/invoice saga model: cancel from every allowed state against every invoice-creation outcome releases stock exactly once, preserves core_external_id correlation, never reopens a cancelled order, never delivers BOLT11 to it, never creates a second invoice; settlement-after-cancel takes the payment_exception path; creation_unknown reconciles by exact external id; multi-match quarantines"
    requirement: QUAL-07
    verification:
      - kind: unit
        ref: "tests/qualification/test_p0_07_cancellation_saga.py (10 tests over the 3x3 cancellation-state x outcome matrix)"
        status: pass
    human_judgment: false
  - id: D3
    description: "Restart-at-checkpoint recovery closure: every section 8.2 saga boundary, inbox checkpoints (admitted-not-validated, validated-not-dispatched), outbox checkpoints (claimed-not-published, partially published with durable accepted targets, lease expired mid-claim), settlement-callback-loss drill recovering exactly once through section 8.3 with duplicate callbacks as no-ops, pre-reservation crash resume idempotency, stable rumor ids, no-regression EOSE cursors, merchant sender-copy recovery without domain dispatch"
    requirement: QUAL-08
    verification:
      - kind: unit
        ref: "tests/qualification/test_p0_08_recovery_closure.py (15 tests)"
        status: pass
    human_judgment: false
  - id: D4
    description: "Email/token persistence: per-recipient dedupe with duplicate-enqueue no-op, consent revocation cancelling queued customer rows, token AEAD copy surviving idempotency retention then erased on expiry, rotation/revocation invalidating the hash immediately, canonical-encoding rejection before lookup, byte-level absence of plaintext (SQLite file) and per-column scans (PostgreSQL), non-reversible purpose-separated hashes"
    requirement: QUAL-09
    verification:
      - kind: unit
        ref: "tests/qualification/test_p0_09_email_persistence.py (7 tests)"
        status: pass
    human_judgment: false
  - id: D5
    description: "SMTP boolean boundary: only True enters sent (with sent_at); False, raised exception, and recipient rejection surface identically as bounded unclassified retries min(2^attempts*30s, 4h) entering failed after EMAIL_MAX_ATTEMPTS=5; suppression without any SMTP call; hashed rate limits (customer 8/h per recipient_hash, merchant 60/h) where excess waits; PII-free logs; crash-after-SMTP exhibiting exactly-once intent with at-least-once delivery"
    requirement: QUAL-10
    verification:
      - kind: unit
        ref: "tests/qualification/test_p0_10_smtp_boundary.py (9 tests)"
        status: pass
    human_judgment: false

# Metrics
duration: 21 min
completed: 2026-09-20
status: complete
---

# Phase 01 Plan 02: State/Transaction/Fencing/Crash/Notification Models Summary

**Executable database-contract models proving the corrected specification: 16-table normative schema with the §14 adapter and §7 state machines, the invoice saga with a controllable LNbits fake, inbox/outbox recovery closure, and the email/token crypto surface — P0-06..P0-10 evidence (60 db tests) green on both SQLite and PostgreSQL**

## Performance

- **Duration:** ~21 min (execution), 07:02–07:23 UTC 2026-09-20
- **Started:** 2026-09-20T07:02:26Z
- **Completed:** 2026-09-20T07:23:30Z
- **Tasks:** 3 (all auto)
- **Files modified:** 15

## Accomplishments
- P0-06 (19 tests): last-unit concurrency yields exactly one held reservation with complete loser rollback on SQLite (BEGIN IMMEDIATE serialization via parallel worker Databases) and PostgreSQL (row locking); sorted-id locking provably avoids the multi-item deadlock; the host's auto-committing helper is *executably* proven to tear an open domain transaction (its row AND the domain rows survive the intended rollback) while the adapter alone rolls back cleanly and never calls the helpers in-transaction (mechanically proven with raising stubs); task-lease fencing rejects stale tokens with zero affected rows; FK orphans and UNIQUE-scope duplicates conflict; the exhaustive §7.1 table (81 pairs) passes with order_events audit rows.
- P0-07 (10 tests): the full cancellation race matrix — cancel from received (claim CAS loses, no invoice ever), cancel during in-flight creation for all three outcomes (success attaches the projection but keeps the order cancelled with no delivery; rejection fails the projection only for invoice_pending orders; unknown sets creation_unknown + payment_exception with no second invoice), and cancel from awaiting_payment followed by late settlement (exception path, never reopening, duplicate callback no-op). Double cancellation releases stock exactly once; multi-match core payments quarantine the order with nothing auto-delivered.
- P0-08 (15 tests): the restart matrix over every §8.2 saga boundary — after-reservation (uncertainty window respected, then failed+rejected), after-invoice-before-attach (the crash window recovered by exact external id with expiry alignment and idempotent type-2 enqueue), between-settlement-and-callback (§17 drill: reconciliation confirms exactly once — stock decremented once, audit row written, type-3 + stock-republication intents — and the late callback is a no-op), plus inbox/outbox checkpoints (durable-evidence requeue via claim-token CAS, missing-targets-only retry, NIP-17 recipient+sender quorum, stable rumor ids with fresh outer event ids, backoff + MAX_ATTEMPTS, dependency-gated claims, supersede never touching order_msg, EOSE-only non-regressing cursors) and the pre-reservation crash resume that neither double-reserves nor double-invoices.
- P0-09/P0-10 (16 tests): per-recipient dedupe with independent delivery, consent revocation cancelling queued customer rows, tokens whose AEAD copy outlives idempotency retention and is erased on expiry/rotation/revocation, byte-level absence of plaintext in the SQLite file, purpose-separated non-reversible hashes, True-only sent semantics with identical unclassified bounded retries for False/exception/recipient-rejection, suppression without any SMTP call, hashed rate limits where excess waits, PII-free logs, and the crash-after-SMTP point exhibiting exactly-once intent with at-least-once delivery.
- Everything flows through the existing single command: `make verify` runs 106/106 (SQLite profile) and the same suite runs 106/106 under `LNBITS_DATABASE_URL` (local PostgreSQL); the evidence manifest records P0-06..P0-10 all passing.

## Task Commits

1. **Task 1: Full model schema + §14 transaction adapter + state machine (P0-06, QUAL-06)** — `665d0a1` (feat)
2. **Task 2: Cancellation/invoice saga model + inbox/outbox recovery closure (P0-07, P0-08; QUAL-07, QUAL-08)** — `41c252a` (feat)
3. **Task 3: Email persistence + SMTP boolean boundary models (P0-09, P0-10; QUAL-09, QUAL-10)** — `3a48b93` (feat)

**Plan metadata:** base `4f78225` → `3a48b93` (3 commits, measured via the plan ledger).

## Files Created/Modified
- `harness/schema.py` — full normative-subset DDL (16 model tables + §4.19 partial indexes), literal for the 01-03 P0-14 closure diff
- `harness/tx.py` — complete §14 adapter + §8.6 dialect claim helpers, task-lease acquire/fenced writes, claim-token leased writes, multi-item sorted-id claim with pause hook
- `harness/state.py` — `transition_order()` enforcing §7.1 with same-transaction order_events rows; §7.2-7.5 golden tables
- `harness/db.py` — `QualWorker` parallel Database handles (concurrency proofs) + `file_path` (byte-level plaintext search)
- `harness/saga.py` — §8.2/8.3/8.4/8.7 saga model + `FakeLNbitsCore` (programmable outcomes, crash window, suppressed callbacks, pause gate, call counts)
- `harness/queues.py` — §8.6 outbox (durable evidence + fenced outcomes, quorum policy, requeue CAS, supersede), §8.5 inbox (checkpoints, sender-copy recovery, bounded quarantine), §9.2 cursors
- `harness/email.py` — §8.8 worker + §11.3/11.4 crypto (envelope, purpose-separated hashes, public tokens, hashed rate limits, boolean SMTP stub, log discipline)
- `tests/qualification/test_p0_06_transactions.py` (19), `test_p0_07_cancellation_saga.py` (10), `test_p0_08_recovery_closure.py` (15), `test_p0_09_email_persistence.py` (7), `test_p0_10_smtp_boundary.py` (9)
- `evidence/manifest.json` / `evidence/REPORT.md` — P0-06..P0-10 coverage, 106/106
- `.gitignore` — stray host runtime `data/` artifact

## Decisions Made
See key-decisions in the frontmatter. Additional execution decisions:
- The cancellation matrix is structured per state (received / in-flight invoice_pending / awaiting_payment) rather than a literal 3×3 loop, because awaiting_payment is unreachable from rejected/unknown creation outcomes — the awaiting_payment cell exercises the meaningful post-cancel axis (late settlement with suppressed callback, duplicate callback, expiry) instead of an artificial combination.
- `state.TransitionConflict` subclasses `tx.SagaConflict`: a lost CAS is exactly the §8.2 "rowcount != 1 → roll back the entire transaction" precondition, preserving the tracer's exception semantics.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] PostgreSQL claim SQL: UPDATE...RETURNING returns no rows**
- **Found during:** Task 2 (P0-08 outbox claim, PostgreSQL profile)
- **Issue:** SQLAlchemy 1.4 + asyncpg raises `ResourceClosedError` ("This result object does not return rows") for a raw `text()` UPDATE...RETURNING — the single-statement PG claim could not fetch the claimed rows.
- **Fix:** Restructured `claim_due_rows` as lock-select → update → fetch inside the SAME transaction, with `FOR UPDATE SKIP LOCKED` appended to the PostgreSQL candidate select (a concurrent worker's select skips locked rows; SQLite keeps the plain select-then-update under BEGIN IMMEDIATE). Concurrency semantics are unchanged — verified by the stale-claim CAS tests on both dialects.
- **Files modified:** harness/tx.py
- **Verification:** 44→60 db tests green on SQLite AND PostgreSQL
- **Committed in:** 41c252a

**2. [Rule 3 - Blocking] PostgreSQL aborts transactions on constraint violations**
- **Found during:** Task 2 (P0-08 inbox duplicate admission, PostgreSQL profile)
- **Issue:** The models caught `IntegrityError` and continued in the same transaction (fine on SQLite); PostgreSQL aborts the transaction (`InFailedSQLTransactionError`), poisoning the surrounding domain transaction.
- **Fix:** Deterministic-id intent inserts (saga/queues enqueue) use `ON CONFLICT DO NOTHING` (atomic, idempotent, no exception); `InboxModel.admit` performs the duplicate lookup in a fresh transaction after the failed insert rolls back.
- **Files modified:** harness/saga.py, harness/queues.py
- **Verification:** duplicate-admission and idempotent-enqueue tests pass on both dialects
- **Committed in:** 41c252a

**3. [Rule 1 - Bug] PostgreSQL rejects schema-qualified CREATE INDEX names**
- **Found during:** Task 1 (PostgreSQL profile first run)
- **Issue:** `CREATE INDEX schema.name ON schema.table` is a PostgreSQL syntax error (indexes are always created in the table's schema).
- **Fix:** Index names are unqualified in the DDL; the ON clause keeps the qualified table.
- **Files modified:** harness/schema.py
- **Verification:** full db suite green on PostgreSQL
- **Committed in:** 665d0a1

**4. [Rule 2 - Missing critical] products lacked created_at/updated_at**
- **Found during:** Task 2 (reservation release/consume writes)
- **Issue:** The models' stock updates write `updated_at`, and the republication intents read `revision` alongside it; spec §4.3 defines both columns but the tracer's minimal products table omitted them.
- **Fix:** Added `created_at`/`updated_at` (NOT NULL DEFAULT 0) to products, literal per §4.3.
- **Files modified:** harness/schema.py
- **Verification:** all suites green on both dialects
- **Committed in:** 41c252a

**5. [Rule 3 - Blocking] Parallel workers need per-worker Database handles**
- **Found during:** Task 1 (last-unit concurrency test)
- **Issue:** The host's `Database.connect()` serializes all connections through one asyncio lock per Database object — N parallel buyers cannot hold connections concurrently, so the plan's "concurrent connections with row locking" was inexpressible. `db.py` was not in the plan's files_modified list.
- **Fix:** Added `QualDatabase.worker()` returning a `QualWorker` (own `Database` over the same SQLite file / PostgreSQL schema, own engine + lock, per-connection SQLite FK pragma), disposed in teardown.
- **Files modified:** harness/db.py
- **Verification:** last-unit concurrency + sorted-locking deadlock tests pass on both dialects (exactly one winner, forced interleaving completes)
- **Committed in:** 665d0a1

**6. [Rule 1 - Bug] Durable publication evidence was atomic with the outcome write**
- **Found during:** Task 2 (partially-published restart test)
- **Issue:** `record_outcomes` inserted relay_publications and applied the outcome policy in one transaction, so a crash between the relay OKs and the outcome write was inexpressible — the §8.6 step-6/step-8 crash point (durable positive evidence, lost state write) could not be modeled.
- **Fix:** Split into `record_publications` (append-only durable evidence) and `apply_outcome` (the fenced claim-token CAS write); `record_outcomes` composes them. A stale worker's genuine positive ACK survives requeue (accepted targets never resent) while its state write is fenced.
- **Files modified:** harness/queues.py
- **Verification:** stale-claim CAS + missing-targets-only retry tests pass on both dialects
- **Committed in:** 41c252a

---

**Total deviations:** 6 auto-fixed (2 blocking dialect, 2 bugs, 1 missing critical, 1 blocking scope-enabling)
**Impact on plan:** All were required for a truthful, dialect-portable implementation of exactly what the plan specified; no scope creep beyond `db.py`'s worker support (the minimal enabling change), no D-13/D-14 stops.

## Issues Encountered
- SQLAlchemy 1.4's asyncpg dialect cannot return rows from raw `text()` UPDATE...RETURNING — resolved with the lock-select/update/fetch claim (deviation 1); this is the same class of pinned-stack constraint 01-01 documented.
- Local PostgreSQL connection requires the `postgres://` scheme (the host rejects `postgresql://`) — the harness dialect switch accepts both, matching CI's URL spelling.
- The committed evidence bundle records the SQLite profile (developer evidence per D-04); the blocking four-profile matrix remains CI's job and the local PostgreSQL run (106/106) is advisory developer evidence.
- A stray `data/.lnbits_auth_key` appears when the host boots with cwd at the repo root — added `data/` to .gitignore (generated runtime output, consistent with 01-01's cleanup).
- The fake's persisted-unknown outcome originally returned the invoice to the extension; corrected to persist in core and still raise the timeout — recovery is only ever the external-id query (the whole point of §8.2 step 5).

## User Setup Required
None — no external service configuration required (local PostgreSQL at the standard URL is optional developer evidence; CI runs the blocking profiles).

## Next Phase Readiness
- Ready for plan 01-03 (conformance closure: protocol fixtures / P0-04, P0-05, P0-11..P0-14): the schema, state machines, saga/queue/email models, and their §7 golden tables are in place and diffable; `make verify-protocol` still reports the empty subset explicitly until the protocol probes land.
- P0-06..P0-10 evidence suites are permanent regression assets (D-05); the harness's fake payment boundary and SMTP stub give 01-03's closure probes deterministic crash points to compose with.
- The four blocking Linux profiles must still run in CI over these models (D-03/D-10); owner approval of PINS.md + the evidence bundle (D-11) remains PENDING and is required before Phase 2 planning.
- Actuals vs estimate: 87,958 tokens against a 52,000 estimate (confidence: low) — the model surface (5 harness modules + 5 test modules, 7,308 insertions) was larger than the estimate anticipated; future estimates for executable-model plans should scale from this data point.

---
*Phase: 01-conformance-profile-contract-phase-0*
*Completed: 2026-09-20*

## Self-Check: PASSED
