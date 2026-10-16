---
phase: 01-conformance-profile-contract-phase-0
plan: 01
subsystem: testing
tags: [lnbits, nostr-sdk, qualification-harness, provenance, sqlite, postgresql, uv, pytest, evidence, ci]

# Dependency graph
requires:
  - phase: 00-contract
    provides: normative technical specification (pinned inputs, sections 2/8/14/17/22)
provides:
  - Permanent qualification harness (harness/*) with one canonical verify command (make verify) and named subsets
  - P0-01 pin freeze + provenance verification suite (host-lock wheel parity, tested-binary hash, release-source + native Cargo pins)
  - P0-02 SDK security probe set with mechanical D-16 subcheck attribution
  - P0-03 host contract probes (invoice metadata/listener lifecycle/owned-handle cancellation/callback non-durability)
  - Section 8.2 step-1 transaction-model executable check (SQLite BEGIN IMMEDIATE + PostgreSQL begin() paths)
  - Deterministic local NIP-01 relay fixture (ACCEPTING/REJECTING/SILENT/AUTH_FLOOD)
  - Evidence bundle tooling (evidence/manifest.json + evidence/REPORT.md, P0-01..P0-14 coverage map)
  - CI blocking matrix workflow (4 blocking Linux profiles + macOS advisory)
  - PINS.md pin freeze with pending owner approval (D-11)
affects: [01-02-relay-ack-concurrency, 01-03-protocol-fixtures, phase-2-planning]

actuals:
  tokens: 120643   # chars/4 over the realized diff (482,573 chars across 23 files)
  tasks: 3
  commits: 5   # 3 feat + docs + chore, measured: git rev-list --count 7882e79..HEAD

tech-stack:
  added:
    - uv project (Python >=3.12,<3.13) with lnbits path source at e336fe1 and nostr-sdk==0.44.8 exact pin
    - pytest 9 + pytest-asyncio (auto mode; session loop for host probes)
    - websockets 15 (local relay fixture), asgi-lifespan (host app boot)
    - GitHub Actions qualification workflow (ubuntu-24.04 / ubuntu-24.04-arm, postgres:18 service)
  patterns:
    - Section-14 transaction adapter: one Database.connect() context, SQLite BEGIN IMMEDIATE on the raw aiosqlite connection with named :params, PostgreSQL conn.conn.begin() with schema-qualified tables; host auto-committing helpers never called inside domain transactions
    - Evidence plugin: GAMMA_QUAL_EVIDENCE=1 gates durable evidence emission; subsets never overwrite the bundle
    - Fresh-database-per-test via unique Database names (SQLite tmp file / PostgreSQL per-test schema)
    - Verified-API-first coding: every host/SDK signature introspected against the pinned checkout/installed wheel before use
    - P0 id derived from module filename (test_p0_NN_*) driving the coverage map

key-files:
  created:
    - tools/checkout_host.py
    - harness/evidence.py
    - harness/pins.py
    - harness/db.py
    - harness/schema.py
    - harness/tx.py
    - harness/sdk.py
    - harness/relay.py
    - harness/host.py
    - tests/conftest.py
    - tests/qualification/test_p0_01_pins.py
    - tests/qualification/test_p0_02_sdk_security.py
    - tests/qualification/test_p0_03_host_contract.py
    - tests/qualification/test_p0_06_transactions.py
    - .github/workflows/qualification.yml
    - PINS.md
    - Makefile
    - evidence/manifest.json
    - evidence/REPORT.md
  modified:
    - pyproject.toml
    - uv.lock
    - .gitignore

key-decisions:
  - "SQLite transaction path uses a plain-named host Database and the raw aiosqlite connection (BEGIN IMMEDIATE, named params, explicit commit/rollback): the host's ext_ prefix ATTACHes the same file twice, and SQLite rejects BEGIN IMMEDIATE on such a connection ('database is locked') — verified empirically against the pinned stack."
  - "nostr-sdk 0.44.8 is wheels-only (no sdist on PyPI; host lock agrees), so release-source provenance is pinned from rust-nostr/nostr-sdk-ffi commit a600c2a7 (the 'Release v0.44.8' commit on the v0.44 maintenance branch — no git tag exists for 0.44.8), with native Cargo pins parsed from its Cargo.lock."
  - "Host probes run in a session-scoped event loop: the pinned host keeps module-level asyncio singletons (task_manager queues, FakeWallet queue) that assume one long-lived loop, exactly as the host's own test suite runs."
  - "host_app chdirs into the pinned checkout for the app lifetime: the host resolves static/extensions paths relative to process cwd, and its own tests run from the checkout root; the harness LNBITS_DATA_FOLDER is absolute so the core database is unaffected."
  - "Named subsets treat pytest exit 5 (no tests collected) as an explicit empty-subset no-op; only make verify and the CI profiles produce durable evidence."

patterns-established:
  - "Verified-API-first: introspect the installed package/pinned checkout before coding against any host/SDK signature (recorded in module docstrings)"
  - "Evidence pins block carries only verified values (recorders are idempotent and invoked by the verifying tests)"
  - "Dialect-appropriate statements: one named-:param SQL set, SQLite unqualified / PostgreSQL schema-qualified tables and FK references"

requirements-completed: [QUAL-01, QUAL-02, QUAL-03]

coverage:
  - id: D1
    description: "Pinned host checkout + full P0-01 pin/provenance verification (installed SDK identity, wheel-hash parity against the host lock for the executing platform, tested-binary native library hash, release-source revision + native Cargo pins, Python 3.12-only claim, host revision)"
    requirement: QUAL-01
    verification:
      - kind: unit
        ref: "tests/qualification/test_p0_01_pins.py (33 tests: wheel parity, wheels-only fact, release-source/Cargo pins, D-15 needles, evidence pins block)"
        status: pass
    human_judgment: false
  - id: D2
    description: "P0-02 SDK security probes: invalid-event rejection before trusted processing, known-ID admission dedupe (admission-modeled), oversized NIP-44 input rejected with bounded wall time and no allocation amplification, paused-signing AUTH flood boundedness, tested binary recorded, D-16 subcheck attribution"
    requirement: QUAL-02
    verification:
      - kind: unit
        ref: "tests/qualification/test_p0_02_sdk_security.py (10 tests incl. tracemalloc allocation bound and no-signer AUTH_FLOOD client probe)"
        status: pass
    human_judgment: false
  - id: D3
    description: "P0-03 host contract probes: invoice extension/external-id/wallet/amount metadata persisted and exactly queryable, listener registration + real FakeWallet settlement delivery, owned-handle scoped cancellation with unrelated tasks surviving, and no durable callback delivery across simulated restart (query is the only recovery route)"
    requirement: QUAL-03
    verification:
      - kind: integration
        ref: "tests/qualification/test_p0_03_host_contract.py (3 tests booting the pinned host twice)"
        status: pass
    human_judgment: false
  - id: D4
    description: "One canonical verification command with named subsets over a single pytest tree, emitting the durable evidence bundle (manifest + report with P0-01..P0-14 coverage map, no credentials, rerun-policy statement)"
    verification:
      - kind: other
        ref: "make verify (49/49 on SQLite AND PostgreSQL locally); make verify-fast/-sdk/-db/-protocol/-host subsets; evidence/manifest.json + evidence/REPORT.md"
        status: pass
    human_judgment: false
  - id: D5
    description: "Section 8.2 step-1 transaction-model check: conditional stock claim + CAS order transition + held reservation in one section-14 transaction, with full rollback on CAS loss and FK enforcement"
    verification:
      - kind: unit
        ref: "tests/qualification/test_p0_06_transactions.py (3 tests, passing on SQLite and PostgreSQL)"
        status: pass
    human_judgment: false
  - id: D6
    description: "CI blocking matrix workflow (4 blocking Linux profiles + macOS advisory) uploading evidence and raw pytest output as CI artifacts"
    verification:
      - kind: other
        ref: "uv run --with pyyaml python -c 'yaml.safe_load(.github/workflows/qualification.yml)' (workflow-yaml-ok); make verify verified locally on both dialects the profiles invoke"
        status: pass
    human_judgment: true
    rationale: "The workflow executes only on GitHub runners; YAML validity and the exact command it runs are verified locally, but a real CI execution on ubuntu-24.04/ubuntu-24.04-arm with the postgres:18 service has not yet been observed."

# Metrics
duration: 20 min
completed: 2026-09-20
status: complete
---

# Phase 01 Plan 01: Conformance Profile Walking Skeleton + P0-01/02/03 Qualification Summary

**Permanent uv/pytest qualification harness proving the pinned LNbits e336fe1 + nostr-sdk 0.44.8 contract: pins/provenance (P0-01), SDK security boundary (P0-02), host contract boundary (P0-03), with one canonical `make verify` and a committed evidence bundle**

## Performance

- **Duration:** ~20 min (planning/session), execution 06:39–06:59 UTC 2026-09-20
- **Started:** 2026-09-20T06:39:57Z
- **Completed:** 2026-09-20T06:59:50Z
- **Tasks:** 3 (1 tracer + 2 auto)
- **Files modified:** 23

## Accomplishments
- Walking skeleton landed as permanent infrastructure (D-05): one `make verify` runs host checkout verification → pinned-set resolution → 49 probes → evidence/manifest.json + REPORT.md with the P0-01..P0-14 coverage map (49/49 passing on the local SQLite profile AND on PostgreSQL via `LNBITS_DATABASE_URL`, same command surface).
- P0-01 provenance proven, not assumed: harness-lock wheel sha256 parity against the pinned host lock for the executing platform tag, tested native-library hash recorded, and — because nostr-sdk 0.44.8 is wheels-only on PyPI — release-source provenance pinned from `rust-nostr/nostr-sdk-ffi` commit `a600c2a7` (no tag exists for 0.44.8) with native Cargo pins (secp256k1 0.29.1, chacha20poly1305 0.10.1, nostr 0.44.7, uniffi 0.29.4) verified against its Cargo.lock.
- P0-02 SDK security boundary qualified with mechanical D-16 disclosure: tampered/malformed events rejected cleanly, oversized NIP-44 input rejected in bounded time without allocation amplification (tracemalloc), 200-challenge AUTH flood against a no-signer client bounded with the client responsive; the known-ID dedupe is attributed admission-modeled (defense in depth only).
- P0-03 host contract boundary qualified against the real host: invoice metadata persisted and exactly queryable by external_id, listeners receive settled payments through the real FakeWallet pipeline, scoped (owned-handle) cancellation proven, and callback non-durability across restart demonstrated with the query path as the only recovery route.
- CI owns the complete blocking matrix: 4 blocking profiles (Linux x86_64/ARM64 × SQLite/PostgreSQL, postgres:18) + macOS ARM64 advisory (continue-on-error), each uploading the evidence bundle and raw pytest output.

## Task Commits

1. **Task 1: End-to-end qualification tracer (walking skeleton)** — `f627f81` (feat)
2. **Task 2: Freeze pins + artifact provenance + canonical subsets + CI blocking matrix (P0-01, QUAL-01)** — `cd53895` (feat)
3. **Task 3: SDK security probes + host contract probes with local relay fixture (P0-02/P0-03, QUAL-02/QUAL-03)** — `0a95246` (feat)

**Plan metadata:** base `7882e79` → `0a95246` (3 commits, measured via the plan ledger).

## Files Created/Modified
- `tools/checkout_host.py` — idempotent pinned-host checkout; hard-fails unless HEAD == e336fe1
- `pyproject.toml` / `uv.lock` — Python >=3.12,<3.13; lnbits path source; nostr-sdk==0.44.8; dev group
- `Makefile` — canonical `verify` + named subsets (D-06/D-07/D-12)
- `PINS.md` — pin freeze, platform claim, artifact identities, release-source/native provenance, D-15 contingency, approval pending
- `harness/pins.py` — pin recording + provenance verification (host/harness lock parsing, wheel parity, native library, release-source Cargo pins)
- `harness/evidence.py` — pytest plugin emitting manifest + report with P0 coverage map and D-16 subcheck split
- `harness/db.py` / `harness/schema.py` / `harness/tx.py` — dialect-switching fresh DB per test + section-14 transaction adapter
- `harness/sdk.py` — verified nostr-sdk 0.44.8 helpers + admission-modeled IdRegistry
- `harness/relay.py` — deterministic local NIP-01 relay fixture (4 modes)
- `harness/host.py` — host app fixture (FakeWallet, LifespanManager, funded wallets)
- `tests/conftest.py` — markers, env conventions, evidence plugin, DB fixture factory
- `tests/qualification/test_p0_01_pins.py` (33 tests), `test_p0_02_sdk_security.py` (10), `test_p0_03_host_contract.py` (3), `test_p0_06_transactions.py` (3)
- `.github/workflows/qualification.yml` — lint + 4 blocking profiles + macOS advisory
- `evidence/manifest.json` / `evidence/REPORT.md` — committed durable evidence bundle (D-09)

## Decisions Made
See key-decisions in the frontmatter. Additional execution decisions:
- Oversized-NIP-44 probe bounds set from measured behavior (~0.09s/MB wall, ~1.05x input-size peak allocation): 4MB within 5s and peak allocation under 4x input — catches hangs/amplification without tautological tightness.
- `verify-protocol` reports "subset empty" explicitly (pytest exit 5) rather than failing: the protocol marker is registered now (D-06 surface complete); plan 01-02 fills it.
- The local PostgreSQL runs (both dialects, 49/49) are recorded as developer evidence; per D-03/D-04 the 4 blocking profiles remain CI's job and the macOS local run is advisory.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] nostr-sdk 0.44.8 has no sdist; release-source provenance re-pinned**
- **Found during:** Task 2 (P0-01 provenance)
- **Issue:** Plan item (f) assumed the nostr-sdk sdist URL+sha256 from the host lock; the host lock records wheels only and PyPI confirms 0.44.8 is a wheels-only release — there is no sdist artifact to fetch, hash, or parse Cargo.lock from.
- **Fix:** Pinned the release-source revision from the source repository the package metadata points to (`rust-nostr/nostr-sdk-ffi` commit `a600c2a7` — the "Release v0.44.8" commit on the `v0.44` maintenance branch, identified by history because no git tag exists for 0.44.8, committed 11 minutes before the PyPI upload), fetched its Cargo.lock (cached under `.cache/nostr-sdk-src/`), and recorded the native Cargo dependency revisions in PINS.md + the evidence pins block; P0-01 tests verify the recorded pins against the cached Cargo.lock. Not a D-13 stop: no blocking security/FFI/ACK check failed — this is a provenance-availability fact, recorded honestly.
- **Files modified:** harness/pins.py, tests/qualification/test_p0_01_pins.py, PINS.md
- **Verification:** test_release_source_and_native_cargo_provenance + PINS.md needles (pass)
- **Committed in:** cd53895

**2. [Rule 3 - Blocking] Host app requires checkout-relative cwd and per-boot superuser**
- **Found during:** Task 3 (host fixture)
- **Issue:** The pinned host mounts `lnbits/static` and resolves extension paths relative to process cwd (its own tests run from the checkout root), and the module-level core database is shared across boots, so a fixed first_install username collides on the second boot.
- **Fix:** `harness/host.py` chdirs into the pinned checkout for the app lifetime (the harness `LNBITS_DATA_FOLDER` is absolute, so the core DB is unaffected) and uses a unique superuser per boot; test wallets are funded via `update_wallet_balance` mirroring the host's own fixtures.
- **Files modified:** harness/host.py
- **Verification:** all P0-03 probes pass, including the two-boot restart probe
- **Committed in:** 0a95246

---

**Total deviations:** 2 auto-fixed (2 blocking)
**Impact on plan:** Both required for a truthful, passing implementation; no scope creep, no D-13/D-14 stops.

## Issues Encountered
- SQLite `ext_`-prefixed databases ATTACH the same file under a schema alias, and SQLite rejects `BEGIN IMMEDIATE` on such a connection ("database is locked") — resolved by using plain-named databases with unqualified tables on SQLite (schema-qualified names remain on PostgreSQL per section 14); documented in harness/db.py.
- SQLAlchemy 1.4 (the host's pin) has no SERIALIZABLE→BEGIN IMMEDIATE isolation mapping (a 2.0 feature) and its autobegin stays open after raw SELECTs — resolved with the raw-driver SQLite path (exactly the section 14 wording) and a commit-hygienic fetch helper for PostgreSQL.
- pytest-asyncio function-scoped loops conflict with the host's module-level asyncio singletons — resolved with a session-scoped loop for host-marker tests (documented in the module header).
- Python 3.9 system `python3` lacks tomllib (used only by ad-hoc probes, not the harness) and an early ad-hoc probe created a stray `data/` directory — removed; the harness sets an absolute `LNBITS_DATA_FOLDER` under gitignored `.cache/`.

## User Setup Required
None — no external service configuration required for the harness. (CI runs on push/pull_request automatically.)

## Next Phase Readiness
- Ready for plan 01-02 (relay ACK/concurrency): the marker set, DB fixture factory, relay fixture, and evidence tooling are in place; `make verify-protocol` reports the empty subset explicitly until protocol probes land.
- The CI workflow has not yet executed on real GitHub runners (repo-local run only) — the first push will validate the 4 blocking profiles; local runs on both dialects (49/49) are advisory developer evidence per D-04.
- nostr-sdk 0.44.8 passed every blocking SDK-internal probe (P0-02) on this machine; qualification of the remaining platforms is CI's job (D-03).
- Owner approval of PINS.md + the evidence bundle (D-11) remains PENDING and is required before Phase 2 planning.

---
*Phase: 01-conformance-profile-contract-phase-0*
*Completed: 2026-09-20*

## Self-Check: PASSED
