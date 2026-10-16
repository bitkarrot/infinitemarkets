---
phase: 03-release-b-gamma-nip-17-orders
plan: 04
subsystem: nostr-orders
tags: [nip-17, conformance, plebeian, nostrrelay, nip-42, egress,
  overload, evidence, release-gate]

requires:
  - phase: 03-release-b-gamma-nip-17-orders/03-01
    provides: keystore NIP-17 primitives, kind-10050 activation,
      inbox transport/cursors, manual NIP-42, egress checks
  - phase: 03-release-b-gamma-nip-17-orders/03-02
    provides: rumor dispatch, dual-copy order_msg outbox,
      rejected-intake path, peer_relays discovery
  - phase: 03-release-b-gamma-nip-17-orders/03-03
    provides: buyer surfaces + Release-B journey harness
provides:
  - tests/conformance/nostrrelay_env.py — reference gated inbox
    provisioning (requireAuthFilter + merchant allowlist + paid tier +
    createdAtDaysPast) + 8-probe battery incl. the real extension inbox
    session on the gated relay
  - >-
    tests/conformance/plebeian_matrix.py — scripted external-client
    matrix on a PINNED PlebeianApp/market clone: real-checkout
    (publishOrderWithDependencies), strict-rumor
    (nip17OrderTransport.ts), physical-rejection, buyer read-back
    (nip17OrderRead.ts) + explicit known-delta register
  - tests/conformance/plebeian/driver.ts — bun-side driver executed
    inside the pinned clone (staged into .conformance/)
  - tests/conformance/run_matrix.sh — matrix/env/plebeian/drills/emit
    driver; merges manifest.json + REPORT.md conformance entries
  - tests/conformance/README.md — env docs, delta register, live
    plebeian.market smoke checklist (manual-only), D-33 note
  - >-
    tests/runtime/test_release_b_drills.py — 28-test drill suite:
    gated-relay env subprocess, NIP-42 roundtrip/oversize/foreign,
    paid-write surface+retry, wrap admission cap, bounded drain, egress
    DNS matrix at the dial boundary, reconnect revalidation
  - docs/technical-specification.md §21 decision 30 (D-33 §9.5
    disposition) + §9.5 cross-note
  - PINS.md §8 — operator-egress requirement + external-client/tooling
    pins
  - evidence/manifest.json conformance.release_b + REPORT.md section +
    evidence/conformance/*.json durable reports
  - 03-VERIFICATION.md — all 5 phase criteria mapped to evidence
affects: [release-b-claim]

actuals:
  tokens: ~95000
  tasks: 4
  commits: 5

tech-stack:
  added: []
  patterns:
    - "External-client conformance = pinned clone + own code paths:
      drive Plebeian's real checkout function and its unwired strict
      transport through bun against nak serve; record every divergence
      in a gated known-delta register (missing entry fails the matrix)"
    - "nostrrelay gated inbox needs composed gating: requireAuthFilter +
      merchant-npub account allowlist + createdAtDaysPast>=2 — the
      native p-tag gate is kind-4-only and never covers kind-1059"
    - "Payment leg via merchant kind-0 lud16 -> loopback LNURLp shim ->
      the order's own bolt11 -> FakeWallet settlement; the strict run
      pays the bolt11 the type-2 wrap actually carried"

key-decisions:
  - "checkpoint D-33 selected: locked-d33 — in-code egress checks +
    documented operator egress requirement + self-hosted gated-relay
    evidence satisfy §9.5 for Release B; OS/container egress policy
    stays an operator responsibility (recorded verbatim as §21 decision
    30). strict-95 not taken (CONTEXT rejects blocking Release B on
    infra the extension does not control)"
  - "Payment-path resolution (RESEARCH OQ2): lud16 exercised literally —
    merchant kind-0 lud16 -> loopback LNURLp shim -> order bolt11 ->
    FakeWallet settle; strict-rumor run additionally pays the exact
    bolt11 read from the merchant's type-2 wrap via Plebeian's own
    nip17OrderRead unwrap (no real sats — D-31)"
  - "Physical-order run asserts the rejected intake + D-22 rejected
    reply (never skipped)"

key-files:
  created:
    - tests/conformance/nostrrelay_env.py
    - tests/conformance/plebeian_matrix.py
    - tests/conformance/plebeian/driver.ts
    - tests/conformance/run_matrix.sh
    - tests/conformance/README.md
    - tests/runtime/test_release_b_drills.py
    - .planning/phases/03-release-b-gamma-nip-17-orders/03-VERIFICATION.md
    - evidence/conformance/nostrrelay-env.json
    - evidence/conformance/plebeian-matrix.json
  modified:
    - infinitemarkets/services/inbox.py (post-AUTH REQ re-issue —
      _Session keeps the REQ filter, _maybe_resubscribe replays it once
      auth_answered lands; verified by extension_gated_inbox)
    - infinitemarkets/security.py (is_public_ip -> ip.is_global positive
      check)
    - docs/technical-specification.md (§21 decision 30 + §9.5 cross-note)
    - PINS.md (§8 operator egress + conformance pins)
    - evidence/manifest.json + evidence/REPORT.md (Release-B entries)
    - .gitignore (conformance run logs never committed)

patterns-established:
  - "WsProbe JSON-lines websocket probes + bounded outcome report —
    every claim is a recorded probe, exit code is the gate"
  - "Known-delta register is enforced, not aspirational: the matrix
    script's delta checklist fails the run if a named divergence lacks
    a recorded entry (D-32)"
  - "Evidence merge survives make verify regeneration: durable JSON
    reports under evidence/conformance/ + `run_matrix.sh emit`
    re-merges manifest/REPORT sections"

requirements-completed: [GAM-05]

coverage:
  - id: D1
    description: "Reference recipient-gated inbox (nostrrelay): anon and
      authed-stranger REQ get nothing; authed merchant REQ serves wraps;
      open writes accepted; paid-write negative OKs surface
      payment-required (never paid)"
    requirement: GAM-05
    verification:
      - kind: integration
        ref: tests/conformance/nostrrelay_env.py run battery (8 probes,
          evidence/conformance/nostrrelay-env.json)
        status: pass
      - kind: integration
        ref: tests/runtime/test_release_b_drills.py::test_reference_gated_relay_environment
        status: pass
    human_judgment: false
  - id: D2
    description: "NIP-42 + paid-write + overload + egress drills on the
      runtime suite (incl. connect-path egress, not just validation)"
    requirement: GAM-05
    verification:
      - kind: integration
        ref: tests/runtime/test_release_b_drills.py (28 tests)
        status: pass
    human_judgment: false
  - id: D3
    description: "Plebeian external-client matrix: real-checkout digital
      order end-to-end + strict-rumor dual-copy + physical rejection +
      known-delta register"
    requirement: GAM-05
    verification:
      - kind: integration
        ref: tests/conformance/plebeian_matrix.py run battery (14
          probes, evidence/conformance/plebeian-matrix.json)
        status: pass
      - kind: other
        ref: "cd tests/conformance && ./run_matrix.sh matrix (exit 0;
          evidence entries merged)"
        status: pass
    human_judgment: false
  - id: D4
    description: "D-33 §9.5 spec amendment recorded as §21 decision 30 +
      operator egress requirement in PINS.md + phase verification doc"
    requirement: GAM-05
    verification:
      - kind: other
        ref: "grep '30. **Release-B' docs/technical-specification.md;
          PINS.md §8; 03-VERIFICATION.md"
        status: pass
    human_judgment: false
  - id: D5
    description: "Live plebeian.market public-relay smoke — manual gate
      artifact (checklist authored; outcome pending)"
    requirement: GAM-05
    verification: []
    human_judgment: true
    rationale: "D-30/D-35: the live-instance smoke is manual-only per
      03-VALIDATION.md; the scripted matrix is the reproducible gate and
      is green"

duration: ~3h (resumed mid-verification)
completed: 2026-09-29
status: complete
---

# Phase 3 Plan 04: Conformance gate — nostrrelay env, drills, Plebeian matrix, §21 amendment Summary

**Release-B external claims are now evidenced to an outsider's standard: a real pinned Plebeian client completes the order flow through the production intake on local relays, the reference nostrrelay gated inbox is probed end-to-end (including the extension's own authed inbox session), egress/overload/NIP-42 are drill-proven at the dial boundary, every literal divergence is a recorded known-delta, and the D-33 §9.5 disposition is a normative §21 register entry.**

## Performance

- **Duration:** ~3h (resumed mid-verification after the prior executor
  landed Task 1's implementation)
- **Tasks:** 4 (1 checkpoint:decision gate + 3 implementation tasks)
- **Files:** 7 created, 6 modified

## Accomplishments

- **nostrrelay reference gated inbox** (`nostrrelay_env.py`): the pinned
  host boots with the real extension + a read-only-copied nostrrelay;
  gated/open/paywall relays provisioned (`requireAuthFilter`, merchant-
  npub allowlist, `costToJoin`, `createdAtDaysPast=3`). All 8 probes pass:
  anonymous REQ gets AUTH+nothing, authed stranger gets the paid-relay
  NOTICE+nothing, the authed allowlisted merchant gets wraps+EOSE, open
  writes are accepted, paid writes classify `payment-required`, the real
  extension inbox session answers AUTH and re-issues its REQ (the
  post-auth resubscribe fix), and a real outbox publish to the paywall
  relay lands a durable `rejected` publication carrying the paid reason.
- **Drill suite** (`test_release_b_drills.py`, 28 tests): real
  challenge→kind-22242→served REQ roundtrip; oversize/foreign challenges
  never signed; paid-write → `payment-required` → relay-auth API → retry;
  >300 wraps/min/relay dropped pre-decrypt with metrics; >1000-row
  backlog drains in bounded DRAIN_BATCH passes; the 20-address IPv4+IPv6
  egress matrix rejects at validate AND at the connect boundary (spy
  asserts zero dials) with reconnect revalidation on a DNS flip.
- **Plebeian matrix** (`plebeian_matrix.py`, 14 probes, all pass) on
  `PlebeianApp/market@4bc7f8c0c73ae4ba2ff2a78f0c66d28347d1c1ce` (HEAD
  re-verified at run time), bun `1.3.11`, `nak serve` (`nak version`
  reports `debug`):
  - *real-checkout (digital):* the literal `publishOrderWithDependencies`
    path → recipient-only kind-1059 wrap → `orders` row
    `protocol='gamma'` → `awaiting_payment` → dual-copy type-2 → settled
    → `confirmed` → dual-copy type-3.
  - *strict-rumor:* Plebeian's own `nip17OrderTransport.ts` resolves both
    kind-10050 sets and publishes sender+recipient wraps; 4 accepted
    `relay_publications` rows across both `delivery_copy` classes.
  - *buyer read-back:* `nip17OrderRead.ts` unwraps the merchant's
    type-2/type-3 wraps off nak; the type-2 payment tag's bolt11 matched
    the settled invoice byte-for-byte.
  - *physical:* opaque newline `address` → `invalid-shipping-destination`
    rejected intake + the D-22 `status=rejected` reply published
    dual-copy — asserted, not skipped.
- **Payment path (OQ2 resolved):** merchant kind-0 `lud16` → loopback
  LNURLp shim (`matrix@conf.test` → metadata → callback returns the
  order's own bolt11) → FakeWallet settlement; the strict run pays the
  bolt11 lifted from the merchant's type-2 wrap. No real sats (D-31).
- **D-33 recorded:** §21 decision **30** carries the verbatim three-part
  disposition + operator-responsibility clause; §9.5 cross-references it;
  PINS.md §8 states the operator egress MUST and records the Plebeian
  pin + nak/bun tooling.
- **Evidence chain:** `run_matrix.sh matrix` exits 0; three
  `conformance.release_b` entries (nostrrelay-env, release-b-drills,
  plebeian-matrix) with tested revisions + platform merged into
  `evidence/manifest.json` + the REPORT.md section; durable JSON reports
  under `evidence/conformance/`.

### Known-delta register (complete — D-32)

| # | Delta | Handling |
|---|---|---|
| 1 | `no-sender-copy` — live checkout publishes a single recipient-only kind-1059; no buyer sender copy | recorded; strict transport proves dual-copy |
| 2 | `public-order-events-unread` — public kind-16/17 (order marker, lud16 payment request, receipt) invisible to the NIP-17 inbox; `receipt_verified` may stay false | recorded |
| 3 | `order-info-envelope` — type-1 rumor subject='order-info' + `name` tag | tolerated (subject not value-enforced) |
| 4 | `opaque-address-physical-rejected` — newline `address` → physical intake rejected pre-reservation + rejected reply | asserted in the physical run |
| 5 | `payment-path-lnurlp-shim` — lud16 resolved via loopback shim returning the order's invoice; FakeWallet settlement | recorded |
| 6 | `real-checkout-app-relay-only` — wrap posted to the connected app relay, not the resolved kind-10050 set (strict transport does resolve; both coincide on nak) | recorded |

## Task Commits

| Task | Commit | Description |
|---|---|---|
| 1 | fdfde9c | feat(03-04): gated-relay env, AUTH resubscribe, drill suite (nostrrelay_env.py + test_release_b_drills.py + inbox._maybe_resubscribe + is_public_ip) |
| 2 | 729820f | test(03-04): Plebeian conformance matrix — real-checkout + strict-rumor + delta register |
| 2 | c1232c6 | test(03-04): run_matrix.sh driver + conformance README + evidence entries |
| 2 | 805531c | chore(03-04): drop conformance run logs — JSON reports are the durable artifacts |
| 3+4 | a4bc536 | docs(03-04): D-33 §21 decision 30 + PINS egress/tooling pins + Release-B evidence + phase verification |
| 4 | (this commit) | 03-04-SUMMARY.md |

## Checkpoint Selections

- **checkpoint D-33 → `locked-d33`** (auto_advance → first-listed option
  selected without pause): in-code relay-target egress checks +
  documented operator egress requirement (PINS.md §8) + self-hosted
  gated-relay evidence satisfy §9.5 for Release B; OS/container egress
  policy remains an operator deployment responsibility. Recorded as
  §21 decision 30 verbatim + §9.5 cross-note.
  Rejected `strict-95` (CONTEXT explicitly: the conformance env cannot
  ship an OS-level egress policy; real-world hosts already satisfy it).

## Deviations from Plan

### Auto-fixed Issues

- **Orchestrator fix (landed in fdfde9c):** `probe_gated_merchant_req`
  now matches the write OKs by the wrap event id — the kind-22242 AUTH
  OK arrives first on the gated socket and the original counted framing
  mis-assigned it.
- **Matrix probe fix (this executor):** `physical_rejected_intake`
  detected the rejected row by diffing inbox ids — the wrap races the
  `before` snapshot through the live subscription. Fixed to match the
  wrap's `outer_event_id` directly. First full run: 13/14 pass; second
  run: 14/14.

No rules-based or scope deviations; no blocker findings.

## Issues Encountered

- `test_storefront_modes.py::test_mode_matrix` flaked once in the
  `make verify-runtime` full-suite run (checkout 503 — the same
  cold-data-folder readiness race documented in the 03-03 summary:
  owned tasks cancelled before the reconcile worker's first pass).
  Passed standalone, in the focused rerun, and in the `make verify`
  full-suite run — pre-existing harness flake, unrelated to this plan.
- `nak --version` reports `nak version debug` (unversioned go-install
  build) — recorded literally in the evidence revisions.
- `.cache/lnbits` remains read-only / outside agent scope — untouched
  (allowed-read); the `infinite-markets-blue.png` tree file stays
  untracked as required.

## Verification

- `cd tests/conformance && ./run_matrix.sh matrix` — **exit 0**:
  nostrrelay env 8/8 probes, drill suite 28/28, Plebeian matrix 14/14
  probes, zero unrecorded divergences.
- `make verify-runtime` — 348 passed + 1 flaky-race fail (see Issues);
  focused reruns all green.
- `make verify` — **569 passed, 3 skipped, 0 failed**
  (darwin-arm64 + SQLite advisory profile; blocking matrix per PINS.md §2).
- `make lint` — clean.
- Evidence greps: `30. **Release-B §9.5 egress disposition` at
  `docs/technical-specification.md:1831`; PINS.md §8 records
  `PlebeianApp/market @ 4bc7f8c0…`, bun 1.3.11, nak debug; manifest
  `conformance.release_b` carries 3 entries all `pass`.

## User Setup Required

- Optional env vars: `PLEBEIAN_SRC` (override the clone location),
  `NOSTRRELAY_SRC` (override the nostrrelay checkout). `bun` and `nak`
  must be on PATH for the matrix (dev/test tooling only).
- The live `plebeian.market` public-relay smoke is a manual-only gate
  item — checklist in `tests/conformance/README.md`; results record into
  `03-VERIFICATION.md`.

## Next Phase Readiness

- Release-B scripted conformance evidence is complete and green — the
  phase's external-claims gate (GAM-05) is satisfied for everything the
  harness can prove on loopback.
- Open manual item: the live plebeian.market smoke (checklist authored;
  PENDING — record into 03-VERIFICATION.md when run).
- Phase 4 (Release C) can start: all Plan-04 deliverables are in and the
  verification record maps every success criterion to evidence.

## Self-Check: PASSED
