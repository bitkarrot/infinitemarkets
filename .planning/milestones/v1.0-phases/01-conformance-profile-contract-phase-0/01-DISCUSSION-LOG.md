# Phase 1: Conformance Profile (Contract Phase 0) - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-09-20
**Phase:** 1-Conformance Profile (Contract Phase 0)
**Areas discussed:** Platform matrix, Harness lifetime, Evidence gate, SDK fallback

---

## Platform Matrix

### Blocking OS and architecture

| Option | Description | Selected |
|--------|-------------|----------|
| Linux x64 only | Fastest MVP claim; macOS/ARM advisory | |
| Linux x64 + ARM | Common servers plus ARM64 deployments | Yes |
| Linux + macOS | Linux x64/ARM64 and macOS ARM64 block | |
| Full wheel matrix | Linux, macOS, and Windows wheel architectures | |

**User's choice:** Linux x64 + ARM.

### Python versions

| Option | Description | Selected |
|--------|-------------|----------|
| 3.12 only | Narrowest matrix | Yes |
| 3.10 and 3.12 | Match LNbits CI range endpoints | |
| 3.10–3.12 all | Test every host-supported minor | |

**User's choice:** Python 3.12 only.
**Notes:** The extension support claim is narrower than the host range and must be explicit.

### Database coverage

| Option | Description | Selected |
|--------|-------------|----------|
| Both DBs everywhere | Full SQLite/PostgreSQL suite on x64 and ARM64 | Yes |
| PostgreSQL on x64 | ARM64 blocks only on SQLite | |
| Tiered suites | Full x64, reduced ARM64 | |

**User's choice:** Both databases on both architectures.

### macOS role

| Option | Description | Selected |
|--------|-------------|----------|
| Advisory smoke | Visible developer smoke, non-blocking | Yes |
| No qualification | Editing environment only | |
| Blocking smoke | Small required macOS gate | |

**User's choice:** Advisory macOS ARM64 smoke.

---

## Harness Lifetime

### Retention

| Option | Description | Selected |
|--------|-------------|----------|
| Permanent suite | Keep all probes/models as regression gates | Yes |
| Hybrid | Keep core probes, archive diagnostics | |
| Evidence only | Discard executable qualification code | |

### Local versus CI

| Option | Description | Selected |
|--------|-------------|----------|
| Fast local, full CI | Local subsets; complete CI matrix | Yes |
| Everything both | Full matrix required locally and in CI | |
| CI authoritative | Local runs optional | |

### Entry point

| Option | Description | Selected |
|--------|-------------|----------|
| One command + subsets | Canonical umbrella plus named subsets | Yes |
| Plan-specific commands | Separate commands per workstream | |
| CI workflow only | Trigger all verification remotely | |

### Fixtures

| Option | Description | Selected |
|--------|-------------|----------|
| Golden + generated | Checked-in vectors plus seeded edge cases | Yes |
| Golden only | Fixed corpus only | |
| Generated only | Seeded builders without checked-in wire files | |

---

## Evidence Gate

### Durable evidence

| Option | Description | Selected |
|--------|-------------|----------|
| Pins + JSON + report | Pins, normalized manifest, concise report, fixtures; raw logs in CI | Yes |
| Human report only | No machine-readable results | |
| Full raw evidence | Commit all logs and outputs | |

### Pass policy

| Option | Description | Selected |
|--------|-------------|----------|
| Clean pass required | Every blocker passes stably | Yes |
| One retry allowed | Retry can convert failure to pass | |
| Quorum pass | Most jobs may pass | |

### Final approval

| Option | Description | Selected |
|--------|-------------|----------|
| Explicit owner approval | Owner approves pins/evidence before Phase 2 | Yes |
| Automatic unlock | Clean CI advances automatically | |
| Independent review | Add mandatory second reviewer | |

### Freshness

| Option | Description | Selected |
|--------|-------------|----------|
| Impact-based + full release | Affected subsets during development; full matrix for release | Yes |
| Any relevant change | Full matrix after every relevant change | |
| Pin changes only | Requalify only on pin/platform changes | |

---

## SDK Fallback

### Candidate failure response

| Option | Description | Selected |
|--------|-------------|----------|
| Evaluate, then approve | Keep blocked, evaluate alternatives, owner approves | Yes |
| Stop immediately | Separate remediation effort | |
| Use newest stable | Automatically select newest release | |

### Candidate selection

| Option | Description | Selected |
|--------|-------------|----------|
| Nearest compatible patch | Smallest compatible patched release | Yes |
| Newest stable | Prefer latest release | |
| Pinned source build | Start with native source build | |

### No safe wheel

| Option | Description | Selected |
|--------|-------------|----------|
| Block release | Require published wheels | |
| Allow source build | Permit reproducible reviewed native build | Yes |
| Platform exception | Narrow the support claim again | |

### Compensating mitigations

| Option | Description | Selected |
|--------|-------------|----------|
| No waiver | Every binary must pass internal regressions | Yes |
| Owner-approved waiver | Temporary documented exception | |
| Disable affected feature | Release with path disabled | |

---

## Claude's Discretion

- Exact test runner, directory layout, marker names, command names, JSON result schema, CI mechanics, and reproducible native-build tooling.

## Deferred Ideas

None.
