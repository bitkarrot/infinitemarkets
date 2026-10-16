# Walking Skeleton — infinitemarkets (Phase 1: Conformance Profile)

**Phase:** 1
**Generated:** 2026-09-20

> This project's Phase 1 is a QUALIFICATION HARNESS, not an application. The walking
> skeleton below is therefore the qualification-slice skeleton: the thinnest end-to-end
> qualification path, built production-quality and permanent (D-05), that every later
> phase's vertical slices are gated on. It deliberately contains no UI, no routing
> surface beyond probe fixtures, and no deployment scaffolding — the phase context
> forbids production runtime features.

## Capability Proven End-to-End

An operator runs one command (`make verify`) that verifies the pinned LNbits/nostr-sdk
artifacts, exercises one real nostr-sdk crypto/FFI probe and one real SQLite transaction
model check, and emits a recorded evidence result (`evidence/manifest.json` +
`evidence/REPORT.md` with a P0-01..P0-14 coverage map).

## Architectural Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Harness runner | pytest + uv, markers `fast`/`sdk`/`db`/`protocol`/`host` | Mirrors the pinned host's developer experience (uv, pytest, Makefile targets); one canonical command with named subsets (D-06/D-07/D-12) |
| Database models | Raw SQLAlchemy through the LNbits `Database` boundary; SQLite default + PostgreSQL selected by `LNBITS_DATABASE_URL` | §14 dialect rules; one pytest surface selects the dialect exactly like the host's own test suite (D-03) |
| Host integration | Pinned LNbits checkout at `e336fe1` as a uv path source, verified by `tools/checkout_host.py` | No silent host downgrade; content-addressed commit verification is the provenance anchor (P0-01, D-01) |
| SDK | `nostr-sdk==0.44.8` exact overlay pin; API surface verified against the installed package before coding | Host-resolved candidate per §2; fallback rules D-13/D-14/D-15 keep any pin change owner-approved |
| Evidence bundle | `PINS.md` + `evidence/manifest.json` (normalized) + `evidence/REPORT.md` + checked-in golden fixtures | D-09 durable committed bundle; raw output stays a CI artifact; single-run clean-pass policy (D-10) |
| Relay testing | Deterministic in-process local relays (accepting / rejecting / silent / AUTH-flood) on 127.0.0.1 | Authoritative per §9.1; `wss://nostr.net` is an optional, non-authoritative smoke only (§21.27) |
| CI topology | GitHub Actions: ubuntu-24.04 (x86_64) + ubuntu-24.04-arm (ARM64) × {SQLite, PostgreSQL} blocking; macOS ARM64 advisory (`continue-on-error`) | The 4 blocking profiles of D-01/D-03; macOS is visible but non-blocking (D-04) |
| Directory layout | `harness/` (support package), `tests/qualification/test_p0_NN_*.py` (P0 id derivable from module name), `tests/fixtures/golden/`, `tools/`, `evidence/` | Evidence coverage map derives P0 ids mechanically; PINS.md and the evidence bundle live at repo root |

## Stack Touched in Phase 1

- [x] Project scaffold (uv project, pytest config, markers, Makefile, lint)
- [x] One real SDK FFI/crypto probe (nostr-sdk keys, sign/verify, NIP-44 round-trip)
- [x] One real database transaction model check (SQLite conditional reservation, CAS rollback, FK enforcement; PostgreSQL via env switch)
- [x] Evidence emission (normalized manifest + human report, committed)
- [ ] UI / routing / deployment — **deliberately absent**: this phase builds qualification infrastructure only; the phase boundary forbids production runtime features

## Out of Scope (Deferred to Later Slices)

- All production extension runtime: merchant, catalog, checkout, worker, and UI features (Phase 2+)
- Migrations on production schemas (Phase 2 owns real migrations; Phase 1 models use harness-only DDL)
- NIP-17 order transport, NIP-15/NIP-04 production compatibility, migration tooling (Phases 3-4; their gates are planned as fixtures/evidence now)
- Deployed relay SSRF/egress controls and external-client conformance runs (Release B/C gates)

## Subsequent Slice Plan

Each later phase adds one vertical slice on top of this qualified skeleton without
altering its architectural decisions, and reruns the applicable Phase 0 assertions
through the real implementation:

- Phase 2 (Release A): real extension package, catalog publication, and LNbits-backed web checkout
- Phase 3 (Release B): Gamma NIP-17 order messaging on the qualified transport/ACK model
- Phase 4 (Release C): literal NIP-15/NIP-04 interop and inventory-safe migration on the qualified DTO/liability models
