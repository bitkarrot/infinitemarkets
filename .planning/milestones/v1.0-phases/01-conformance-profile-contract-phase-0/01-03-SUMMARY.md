---
phase: 01-conformance-profile-contract-phase-0
plan: 03
subsystem: testing
tags: [nostr, relay-ack, nip17, nip89, nip15, auth, csrf, origin, redaction, decimal, fx, contract-closure, qualification-harness, pytest, evidence]

# Dependency graph
requires:
  - phase: 01-conformance-profile-contract-phase-0
    plan: 01
    provides: harness skeleton, SDK/relay probes, evidence plugin, markers, CI matrix
  - phase: 01-conformance-profile-contract-phase-0
    plan: 02
    provides: schema/state/transaction models that the closure gate diffs against the registry
provides:
  - Deterministic local relay fixtures classifying positive OK / negative OK / timeout per relay (P0-04)
  - NIP-17 golden + generated fixtures validating outer/seal/rumor chains, tamper rejection, stable rumor ids across retries (P0-05)
  - NIP-89 local naddr resolution with malformed/wrong-kind/foreign rejection and no relay-hint fetching (P0-11)
  - Host auth/privacy/lifecycle probes: bearer/CSRF/origin boundaries, ID-only and cross-origin mutation rejection, X-Order-Token + secret redaction, unsupported-topology refusal (P0-12)
  - Literal NIP-15 DTO golden fixtures (stall/product + invalid cases) (P0-12 scope)
  - Decimal/FX boundary model: single Decimal(str()) crossing, per-component ROUND_CEILING, provenance/freshness/validity rejections, measured float-boundary error recorded in evidence (P0-13)
  - Contract-closure gate: bidirectional spec<->registry<->schema<->state parity, exhaustive transition classification, fixture coverage, release scoping, identifier closure, topology registration, live P0-01..P0-14 evidence closure (P0-14)
  - PINS.md qualification-results section (NIP-32 namespace, security/ACK/FX summaries, platform matrix) — Approval stays PENDING (D-11)
affects: [phase-1-verification, phase-2-planning]

actuals:
  tokens: ~110000   # estimated; executor task 3 completed in lead session after infra interruption
  tasks: 3
  commits: 3

tech-stack:
  added: []
  patterns:
    - LocalRelay deterministic fixtures (ACCEPTING/REJECTING/SILENT modes) — per-relay ACK classification is the only publication evidence; WebSocket send alone is never evidence
    - Golden fixtures + seeded generated cases: NIP-17 recipient/sender/retry wrap chains, NIP-89 31989/31990 pair + naddr, NIP-15 stall/product + invalid DTOs
    - P0-14 closure gate reads the spec at test time: §5 routes from fenced blocks, §7 machines from arrow notation + evidence-gated prose rules, §4 tables from heading/introduction patterns — bidirectional diffs both directions
    - Evidence-closure assertion consumes the plugin's live in-session accumulator (never the serialized manifest) and self-skips whenever a -m/-k/positional selection narrows the run

key-files:
  created:
    - harness/nip89.py
    - harness/authprobe.py
    - harness/fx.py
    - harness/registry.py
    - tests/qualification/test_p0_04_relay_ack.py
    - tests/qualification/test_p0_05_encrypted_fixtures.py
    - tests/qualification/test_p0_11_nip89_route.py
    - tests/qualification/test_p0_12_auth_privacy_lifecycle.py
    - tests/qualification/test_p0_13_decimal_fx.py
    - tests/qualification/test_p0_14_contract_closure.py
    - tests/fixtures/golden/nip17/ (rumor + recipient/sender/retry seal+wrap, keys)
    - tests/fixtures/golden/nip89/ (recommendation_31989, handler_31990, naddr)
    - tests/fixtures/golden/nip15/ (stall_30017, product_30018 variants, invalid DTOs)
  modified:
    - harness/sdk.py
    - harness/relay.py
    - harness/evidence.py
    - harness/pins.py
    - harness/schema.py
    - harness/state.py
    - harness/host.py
    - PINS.md
    - evidence/manifest.json
    - evidence/REPORT.md

key-decisions:
  - "Relay ACK classification is the relay_publications vocabulary (accepted/rejected/timeout): SendEventOutput.success/.failed per-relay sets; a missing OK classifies as timeout — never inferred from send success."
  - "P0-14 spec extraction is literal: §5 fenced route blocks (with the member-vs-collection [/{id}] convention), §7 arrow notation + prose rules gated on evidence substrings, §4 tables from heading/bullet/colon introductions — every registered literal positively appears in the spec."
  - "Evidence closure consumes the live accumulator via the evidence_results fixture (shared p0_coverage derivation with the serializer) and self-skips under any selection — marker, -k, or positional args beyond testpaths."
  - "Section-4 table scope is explicit in the registry: every spec table is classified modeled / fk-subset / not-modeled — a missing classification is a registry bug that fails the gate."

requirements-completed: [QUAL-04, QUAL-05, QUAL-11, QUAL-12, QUAL-13, QUAL-14]

coverage:
  - id: D1
    description: "Relay ACK classification: positive OK, negative OK (verbatim relay message), and timeout distinguished per relay; send_event_to targets only listed relays (unlisted pool member receives nothing); advisory external smoke opt-in"
    requirement: QUAL-04
    verification:
      - kind: unit
        ref: "tests/qualification/test_p0_04_relay_ack.py (3 tests)"
        status: pass
    human_judgment: false
  - id: D2
    description: "NIP-17 encrypted fixtures: golden + generated seal/wrap chain validation, tamper rejection before trusted processing, stable rumor ids across retries, recipient+sender copies"
    requirement: QUAL-05
    verification:
      - kind: unit
        ref: "tests/qualification/test_p0_05_encrypted_fixtures.py (22 tests)"
        status: pass
    human_judgment: false
  - id: D3
    description: "NIP-89 local naddr routing: bech32 decode, kind-30402 requirement, local merchant registry, d validation, malformed/wrong-kind/foreign rejection, no relay-hint fetching"
    requirement: QUAL-11
    verification:
      - kind: unit
        ref: "tests/qualification/test_p0_11_nip89_route.py (14 tests)"
        status: pass
    human_judgment: false
  - id: D4
    description: "Auth/privacy/lifecycle: bearer vs cookie+Origin+CSRF boundaries, ID-only and cross-origin admin mutation rejection, X-Order-Token/secret redaction in request+audit logs, topology refusal, NIP-15 literal DTOs"
    requirement: QUAL-12
    verification:
      - kind: unit
        ref: "tests/qualification/test_p0_12_auth_privacy_lifecycle.py (17 tests) + tests/fixtures/golden/nip15/"
        status: pass
    human_judgment: false
  - id: D5
    description: "Decimal/FX: single Decimal(str()) float boundary, per-component ROUND_CEILING, provenance/freshness/zero/nonfinite/failed-quote rejection before reservation, measured float-boundary error recorded (max rel 7.46e-17, 0 sat abs)"
    requirement: QUAL-13
    verification:
      - kind: unit
        ref: "tests/qualification/test_p0_13_decimal_fx.py (21 tests) + evidence manifest fx_measurement"
        status: pass
    human_judgment: false
  - id: D6
    description: "Contract closure: bidirectional spec<->registry parity (routes/states/literals), schema+state parity with registry, exhaustive transition classification, fixture coverage, Release-A exclusion of B/C kinds, identifier closure, topology registration, complete-profile P0-01..P0-14 evidence assertion"
    requirement: QUAL-14
    verification:
      - kind: unit
        ref: "tests/qualification/test_p0_14_contract_closure.py (12 tests; evidence closure self-skips on subset runs)"
        status: pass
    human_judgment: false

# Metrics
duration: ~50 min (tasks 1-2 by executor; task 3 completed in lead session after infra interruption)
completed: 2026-09-20
status: complete
---

# Phase 01 Plan 03: Protocol Fixtures + Closure Gate Summary

**Deterministic protocol evidence and the contract-closure gate: relay ACK classification, NIP-17/NIP-89/NIP-15 golden fixtures, auth/privacy/lifecycle probes, the Decimal/FX boundary with a measured float error, and the P0-14 gate proving spec<->registry<->implementation closure plus complete P0-01..P0-14 evidence — 220/220 on SQLite and PostgreSQL**

## Performance

- **Duration:** ~50 min (executor tasks 1-2 committed `ce15184`, `e03cef7`; task 3 finished in the lead session after the executor's connection dropped mid-task)
- **Tasks:** 3
- **Commits:** 3 (`ce15184`, `e03cef7`, `6af5485`)

## Accomplishments
- P0-04 (3 tests): one fan-out exercises positive OK / negative OK (verbatim relay message) / timeout against deterministic `LocalRelay` modes; per-relay classification recorded as a structured `relay_ack_classification` evidence observation; `send_event_to` never delivers to unlisted pool relays; external wss smoke stays opt-in advisory.
- P0-05 (22 tests): golden + generated NIP-17 fixtures prove wrap-chain construction (1059→13→rumor), tamper rejection before trusted processing, stable rumor identity across retries with fresh outer ids, and separate recipient/sender copies.
- P0-11/P0-12 (31 tests): local naddr resolution rejects malformed/wrong-kind/foreign references without fetching relay hints; auth probes enforce bearer vs cookie+Origin+CSRF boundaries, reject ID-only and cross-origin admin mutations, prove X-Order-Token/secret redaction in request and audit logs, and refuse unsupported topology (multi-process SQLite, CockroachDB); literal NIP-15 stall/product DTOs plus invalid-case fixtures.
- P0-13 (21 tests): one `Decimal(str(value))` boundary, per-line/per-shipping `ROUND_CEILING`, rejection of stale/empty/zero/nonfinite/failed/provenance-free quotes before reservation; measured float bound recorded deterministically (max rel `7.46e-17`, max abs `0` sat).
- P0-14 (12 tests): the closure gate diffs spec<->registry<->schema.py<->state.py both directions, proves exhaustive transition classification and fixture coverage, enforces Release-A kind exclusion, checks frozen-identifier spellings, registers the topology refusal, and asserts complete P0-01..P0-14 evidence on the live accumulator — self-skipping on any subset selection.
- PINS.md gained the spec-§2 qualification-results section (NIP-32 namespace `org.infinitemarkets.protocol` pinned, security/ACK/FX summaries, platform matrix); the D-11 Approval section remains PENDING for owner sign-off.
- Final suite: `make verify` 220/220 on SQLite and on PostgreSQL (`postgres://localhost/gamma_qual`); `make verify-protocol` runs 69 protocol-scoped tests with the evidence-closure assertion correctly self-skipping; ruff clean.

## Task Commits

1. **Task 1: Relay ACK classification + NIP-17 encrypted fixtures (P0-04, P0-05)** — `ce15184`
2. **Task 2: NIP-89 routing + auth/privacy/lifecycle probes + NIP-15 DTOs (P0-11, P0-12)** — `e03cef7`
3. **Task 3: Decimal/FX boundary + contract-closure gate + PINS results (P0-13, P0-14)** — `6af5485`

**Plan metadata:** base `4d46a48` → `6af5485` (3 commits).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Closure gate spec-extraction edge cases**
- **Found during:** Task 3 (P0-14 test development, lead session)
- **Issue:** §4 table extraction false-positived on field enumerations (`` `state` (`pending|…`) ``), column parsing dropped digit-bearing names (`bolt11_enc`), the §14 topology anchor wraps across lines, and `config.args` is never empty under `testpaths` config — the evidence-closure skip would have been unconditional.
- **Fix:** table introductions require PK|FK|UNIQUE evidence in the paren; column regex admits digits; §14 anchor checked on whitespace-normalized text; selection state compares `config.args` against configured `testpaths` so bare `pytest` counts as complete but `pytest <path>` self-skips.
- **Files modified:** tests/qualification/test_p0_14_contract_closure.py, harness/evidence.py
- **Verification:** 12/12 P0-14 tests pass; evidence closure asserts live on `make verify` and self-skips on `-m protocol` and file-targeted runs
- **Committed in:** 6af5485

**2. [Rule 2 - Missing] `note_observation` defined but never wired**
- **Found during:** Task 3 (PINS.md qualification-results authoring)
- **Issue:** the evidence plugin's structured-observation hook existed but no test used it, so per-relay ACK results lacked a citable manifest record.
- **Fix:** `test_positive_negative_and_timeout_acks_classified_per_relay` records the per-relay `relay_ack_classification` observation; PINS.md points at it.
- **Files modified:** tests/qualification/test_p0_04_relay_ack.py
- **Committed in:** 6af5485

**3. [Rule 1 - Lint] unused LifespanManager binding + import order**
- **Found during:** Task 3 closeout (`ruff check .`)
- **Fix:** dropped the unused `as manager` binding in `harness/host.py` (comment clarified); ruff-sorted test imports.
- **Committed in:** 6af5485

### Infrastructure Note

The `gsd-executor` subagent (beeff68d) completed Tasks 1-2 and most of Task 3 before a connection error ended the session; the resume attempt failed twice on the same error. Task 3 was finished in the lead session following the same plan/executor protocol: uncommitted work assessed, the P0-14 closure module written and iterated to green, PINS.md completed, full suite verified on both dialects, committed as `6af5485`.
