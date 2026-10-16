---
phase: "01"
slug: conformance-profile-contract-phase-0
status: validated
nyquist_compliant: true
wave_0_complete: true
created: 2026-10-11
---

# Phase 1 — Retrospective qualification coverage map

This closes a missing coverage document, not a new runtime implementation gate.
The executed plans and 01-VERIFICATION.md record the P0 harness/model scope.
Current CI run 38194415581 on `a7082c7` passes the four Linux DB/platform profiles;
the old checked-in evidence counts remain historical. No full local rerun is
claimed by this map, and harness conformance is not runtime-wide correctness.

| Plan/task group | Requirements | Existing qualification tests | Commands |
|---|---|---|---|
| 01-01 tasks 1–3 | QUAL-01–03 | P0-01 pins, P0-02 SDK security, P0-03 host contracts | `make verify-sdk`, `make verify-host`, `make verify` |
| 01-02 tasks 1–3 | QUAL-06–10 | P0-06 transactions, P0-07 saga, P0-08 recovery, P0-09 persistence, P0-10 SMTP | `make verify-db` |
| 01-03 tasks 1–3 | QUAL-04–05, QUAL-11–14 | P0-04 ACK, P0-05 crypto, P0-11 routing, P0-12 auth/lifecycle, P0-13 FX, P0-14 contract closure | `make verify-protocol`, `make verify-host`, `make verify` |

All nine tasks have automated verify steps in their original PLAN files, with
existing tests under `tests/qualification/`; no missing Wave 0 file is inferred
from this previously absent map. D-11 owner approval is historical in PINS.md.
Phase 5 must add runtime boundary regressions and rerun qualification on the
repaired revision; this map does not close F1–F6 or the required live-client gate.
