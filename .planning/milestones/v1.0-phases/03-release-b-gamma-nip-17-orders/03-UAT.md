---
status: complete
phase: 03-release-b-gamma-nip-17-orders
source: [03-01-SUMMARY.md, 03-02-SUMMARY.md, 03-03-SUMMARY.md, 03-04-SUMMARY.md]
started: 2026-09-29T00:00:00Z
updated: 2026-10-13T04:35:00+00:00
---

## Current Test
<!-- OVERWRITE each test - shows where we are -->

[testing complete — item 17 (live plebeian.market smoke) executed and passed 2026-10-13; see 03-VERIFICATION.md manual-items section]

## Tests

### 1. m006 schema + kind-10050 activation vertical
expected: m006 schema + kind-10050 enable/publish/ACK→active + disable→tombstone vertical, gating on accepted evidence
result: pass
source: automated — tests/runtime/test_inbox_activation.py (7 tests)

### 2. Keystore NIP-17 wrap/unwrap
expected: Keystore NIP-17 wrap/unwrap explicit §8.5 chain, golden fixtures, tamper matrix, bounded WrapRejection reasons
result: pass
source: automated — tests/runtime/test_keystore_nip17.py + tests/qualification/test_p0_05

### 3. Inbox transport
expected: kind-1059 sessions/admission/cursors, NIP-42 AUTH, paid-relay evidence, egress validation, peer discovery
result: pass
source: automated — tests/runtime/test_inbox_transport.py (14 tests)

### 4. Wrapped type-1 order → canonical pipeline
expected: Wrapped type-1 order → canonical pipeline → gamma order entering the same pricing/inventory/invoice/settlement services as web checkout
result: pass
source: automated — tests/runtime/test_nip17_inbox.py#test_type1_creates_gamma_order_and_type2_intent

### 5. Dual-copy order_msg publication
expected: Recipient copy only to buyer-declared relays, sender copy only to merchant-declared relays, durable per-copy evidence
result: pass
source: automated — tests/runtime/test_nip17_outbox.py (dual-copy, partial-failure, retry)

### 6. Inbound matrix
expected: Buyer cancelled legal/illegal transitions, foreign-sender, replay/dedupe handling across the inbound rumor matrix
result: pass
source: automated — tests/runtime/test_nip17_inbox.py (Task-2 block)

### 7. Intake abuse + durability
expected: Admission ordering, per-author caps, blocklist/mute, crash-recovery drills, retention evidence
result: pass
source: automated — tests/runtime/test_intake_abuse.py (10 tests)

### 8. NIP-07 sign-in vertical
expected: Challenge → kind-22242 verify → revocable hashed session → scoped order list (D-01/D-03/D-06)
result: pass
source: automated — tests/runtime/test_nostr_signin.py + tests/e2e/buyer.spec.ts

### 9. Order claim + attributed checkout
expected: Private-token claim binds buyer_pubkey (no-oracle, audited, idempotent); signed-in web checkout attributed (D-04/D-05)
result: pass
source: automated — tests/runtime/test_nostr_signin.py + tests/e2e/buyer.spec.ts

### 10. Four-state storefront_mode
expected: full/showcase/browse_only/nostr_only mode matrix with D-07..D-11 gates (inbox-required gate, in-flight orders untouched, private links live)
result: pass
source: automated — tests/runtime/test_storefront_modes.py + tests/e2e/{buyer,admin}.spec.ts

### 11. Messages workspace
expected: Fifth nav surface — customer/Unknown folders, unread markers, thread/read/reply/compose, delivery evidence, retry-now, rejected-intake + mute, relay-auth pills
result: pass
source: automated — tests/runtime/test_admin_ui.py + tests/e2e/admin.spec.ts

### 12. Release-B capstone journey
expected: Activation → wrap order → payment/status wrap exchange → settlement → receipt, end-to-end through one canonical authority
result: pass
source: automated — tests/runtime/test_release_b_journey.py

### 13. Reference recipient-gated inbox (nostrrelay)
expected: Anonymous + non-allowlisted REQ gets nothing; authed merchant REQ returns wraps; open kind-1059 writes accepted; paid-write negative OK surfaces payment-required — 8/8 probes on the real gated relay
result: pass
source: automated — tests/conformance/nostrrelay_env.py battery + tests/runtime/test_release_b_drills.py::test_reference_gated_relay_environment

### 14. NIP-42 / paid-write / overload / egress drills
expected: AUTH roundtrip + oversize/foreign-challenge refusal, paid-write surface+retry, >300 wraps/min/relay dropped pre-decrypt, >1000-row bounded backlog, IPv4+IPv6 non-global egress rejection at validate/connect/reconnect — 28 tests
result: pass
source: automated — tests/runtime/test_release_b_drills.py

### 15. Plebeian external-client matrix
expected: Real-checkout digital order through `publishOrderWithDependencies` completes wrap→order→settle→status; strict-rumor dual-copy through `nip17OrderTransport.ts`; physical order rejected with reply; 14/14 probes, 6 recorded known-deltas
result: pass
source: automated — tests/conformance/plebeian_matrix.py + ./run_matrix.sh matrix (exit 0)

### 16. D-33 §9.5 spec amendment
expected: §21 decision 30 records the three-part disposition + operator-responsibility clause verbatim; §9.5 cross-note; PINS.md operator egress MUST + Plebeian/tooling pins
result: pass
source: automated — grep-verified spec/PINS edits (a4bc536)

### 17. Live plebeian.market public-relay smoke
expected: Manual checklist (tests/conformance/README.md) executed against live plebeian.market over public relays — wrap/ACK evidence collected and recorded into 03-VERIFICATION.md
result: pass
source: manual — 2026-10-13 live run on `schedulerlnbits.exe.xyz` (v0.6.3): wrap `f2f378dd273d0142` via `wss://nos.lol` → `processed`; gamma order `afa3499b59fe…` confirmed after internal invoice settlement; type-2 (`9a59aa732253…` recipient-copy) and type-3 `confirmed` (`450ce39d3074…` recipient-copy) wraps accepted on the buyer's declared relays; full evidence in 03-VERIFICATION.md. Known-delta register applied verbatim.

## Summary

total: 17
passed: 17
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps

<!-- YAML format for plan-phase --gaps consumption -->

## Closeout note — 2026-10-11

Tests 1–16 above retain their historical outcomes; they were not rerun as human
UAT during this closeout. In particular, test 14's drain evidence does not prove
the same-scope backlog admission bound (F6), and ordinary dual-copy tests do not
prove the full no-route recovery window (F5). Those assurance gaps, and shared
commerce F1–F3, are reopened in Phase 5. Item 17 was executed live on
2026-10-13 and passed (see 03-VERIFICATION.md); Phase 5 items remain the open
assurance gaps.
