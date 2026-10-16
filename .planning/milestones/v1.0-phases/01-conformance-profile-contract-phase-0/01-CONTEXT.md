# Phase 1: Conformance Profile (Contract Phase 0) - Context

**Gathered:** 2026-09-20
**Status:** Ready for planning

<domain>
## Phase Boundary

Produce permanent, reproducible probes, fixtures, executable models, and evidence that qualify the corrected LNbits/SDK/database/protocol contract before any production extension runtime is implemented. This phase does not build merchant, catalog, checkout, worker, or UI runtime features.

</domain>

<decisions>
## Implementation Decisions

### Platform Matrix

- **D-01:** Release A is blocked on Linux x86_64 and Linux ARM64 qualification. Other architectures are not part of the initial production claim. — **Reversibility:** costly — Broadening or narrowing the claim changes CI coverage, published support policy, and recorded artifact provenance.
- **D-02:** The initial extension supports Python 3.12 only, despite the pinned LNbits host permitting Python 3.10–3.12. `PINS.md`, packaging metadata, startup/install checks, and release documentation must state the narrower claim explicitly.
- **D-03:** The complete Phase 1 suite must pass on both SQLite and PostgreSQL for both blocking Linux architectures: Linux x86_64 + SQLite, Linux x86_64 + PostgreSQL, Linux ARM64 + SQLite, and Linux ARM64 + PostgreSQL.
- **D-04:** macOS ARM64 is an advisory developer smoke profile only. Its failure is visible but does not block Release A.

### Harness Lifetime

- **D-05:** All Phase 1 probes and executable models remain as a permanent regression and release-gate suite; none are treated as disposable qualification code.
- **D-06:** Developers get fast local SDK, protocol, state, and SQLite subsets. CI owns the complete blocking Linux architecture/database matrix.
- **D-07:** Provide one canonical verification command with named subsets for fast, SDK/security, database/state, protocol, and complete profile execution. Exact command names and test-runner mechanics are planner discretion.
- **D-08:** Preserve reviewable checked-in golden protocol/state fixtures and supplement them with deterministic generated edge cases. Generated cases must be seeded/reproducible.

### Evidence Gate

- **D-09:** The durable committed evidence bundle consists of `PINS.md`, a machine-readable normalized result manifest, a concise human report, and the golden fixtures. Raw command output and bulky logs remain CI artifacts linked from the report rather than committed.
- **D-10:** Every blocking profile and P0 acceptance check requires a clean pass. A rerun may diagnose flakiness but cannot turn an unstable test into a passing release result.
- **D-11:** Explicit owner approval of the final pins and evidence summary is required before Phase 2 planning begins. Clean CI alone does not unlock Release A planning.
- **D-12:** During development, relevant changes trigger impact-based subset reruns. Before every release claim, the complete blocking matrix must run again.

### SDK Fallback

- **D-13:** If host-resolved `nostr-sdk==0.44.8` fails any blocking security, FFI, crypto, or ACK check, Phase 1 remains blocked while alternatives are evaluated. No fallback pin becomes authoritative without explicit owner approval.
- **D-14:** Evaluate the nearest host-compatible patched release first. Every alternative receives the complete qualification profile and the same provenance requirements; do not jump automatically to the newest release.
- **D-15:** If no safe published wheel exists for every blocking profile, a source-built SDK may be approved only when the native source revision and toolchain are pinned, the build is reproducible, output artifacts are hashed, review evidence is recorded, and all blocking tests pass. — **Reversibility:** costly — A source-build profile introduces a maintained native toolchain and artifact-production obligation.
- **D-16:** Extension-level input checks are defense in depth only. They cannot waive a failed SDK-internal blocking regression, even if the affected application path appears constrained.

### Claude's Discretion

- Exact repository directories for probes, fixtures, reports, and CI definitions.
- The test-runner, marker names, JSON result schema, and canonical command spelling.
- CI provider mechanics for ARM64 and PostgreSQL, provided all four blocking profiles execute the full suite.
- The exact reproducible native build toolchain when D-15 is activated, subject to the locked provenance and pass requirements.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Normative Contract

- `docs/technical-specification.md` §§2, 3.4, 4, 7–10, 14, 17, 21–22 — dependency qualification, FX boundary, schema/state contracts, algorithms, lifecycle, transaction/topology rules, test requirements, decisions, and P0-01–P0-14 acceptance.
- `docs/architecture-proposal.md` §§6–8, 18, 22–24 — architecture boundaries, package direction, background-work rationale, reliability model, testing strategy, and phased build rationale. The technical specification wins on conflicts.

### Project Scope and Requirements

- `.planning/PROJECT.md` — project constraints, authoritative-document precedence, host/protocol pins, and release sequence.
- `.planning/milestones/v1.0-REQUIREMENTS.md` QUAL-01 through QUAL-14 — Phase 1 requirements and Definition of Done.
- `.planning/ROADMAP.md` Phase 1 — phase goal, success criteria, and three planned workstreams.

### Preserved Research

- `.planning/research/SUMMARY.md` — completed audit synthesis and rule against silently re-deriving delivered findings.
- `.planning/research/STACK.md` — pinned host stack, required adapters, and explicit non-selections.
- `.planning/research/PITFALLS.md` — silent-failure modes Phase 1 must make visible.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- The pinned LNbits source uses `uv`, pytest, `FakeWallet`, and Make targets for unit, wallet, API, and regtest execution; Phase 1 can mirror that developer experience without importing production extension code.
- LNbits reusable CI tests already exercise Python 3.10/3.12 with SQLite and PostgreSQL on Ubuntu; its workflow structure provides a reference for the new Python 3.12 matrix.
- The host lock records hashed `nostr-sdk==0.44.8` wheels for Linux x86_64/ARM variants and macOS ARM64, providing candidate artifact identities for provenance checks.
- Existing corrected P0-01–P0-14 criteria and research pitfalls provide the test taxonomy; planners should not invent a parallel acceptance vocabulary.

### Established Patterns

- LNbits uses `LNBITS_BACKEND_WALLET_CLASS="FakeWallet"` and isolated data folders for deterministic host tests.
- SQLite and PostgreSQL behavior are exercised through the same pytest surface with a database URL selecting the dialect.
- The project currently has no runtime scaffold, package file, test harness, or CI workflow; Phase 1 creates only qualification infrastructure and evidence.

### Integration Points

- Host invoice creation/query/listener and managed-task APIs at pinned LNbits `e336fe1`.
- LNbits extension database connection boundary and dialect-specific raw transaction behavior.
- Python `nostr-sdk` FFI for NIP-44/NIP-59, targeted publication, relay output, and notification handling.
- Local deterministic relay fixtures for positive OK, negative OK, timeout, AUTH pressure, and routing isolation.
- Optional `wss://nostr.net` smoke execution remains non-blocking and cannot replace local relay evidence.

</code_context>

<specifics>
## Specific Ideas

- Initial production qualification is intentionally narrow: Python 3.12 on Linux x86_64 and ARM64, with both SQLite and PostgreSQL.
- The permanent suite should feel like one product: one top-level verification command, named subsets, normalized evidence, and reusable regression fixtures.
- A release result is either clean or blocked; flaky reruns and application-only SDK mitigations do not soften the gate.
- Fallback dependency work remains inside Phase 1 investigation, but every candidate change returns to the owner for an explicit pin decision.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 1-Conformance Profile (Contract Phase 0)*
*Context gathered: 2026-09-20*
