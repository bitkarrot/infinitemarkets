---
phase: "05"
slug: correctness-recovery-and-security-hardening
status: gaps_found
threats_open: 6
asvs_level: 1
created: 2026-10-11
---

# Phase 5 — Open Security and Correctness Register

This is a scoped register of **six open review findings**, not a complete new
ASVS certification. Three are high-priority financial findings in the assessment.
Historical threat classifications are retained; in particular T-203-01 remains
critical and T-302-01 remains high. Related rows across registers overlap and
must not be summed as distinct vulnerabilities. No finding is accepted or waived.

| Finding | Assessment priority | Existing threat relationship | Boundary and required evidence | Status |
|---|---|---|---|---|
| F1 | High | Reopens T-204-02 and T-205-01 | Authenticated merchant status cannot confirm unpaid orders or release buyer delivery; cancellation releases held stock once; test owner/API, token and authenticated-history surfaces | Open; HARD-01 |
| F2 | High | Additional recovery-availability failure, not covered by a blanket old closure | Invoice created then response lost; recover the same invoice, settle, clear only the resolved uncertainty and retain unrelated holds | Open; HARD-02 |
| F3 | High | Reopens critical T-203-01 inventory assurance | Expire/release holds before recovery/settlement; verify complete stock accounting or explicit exception, duplicate-callback safety and concurrency | Open; HARD-03 |
| F4 | Medium | Additional publication-ordering failure; claim fencing alone is insufficient | Published revision 1 cannot satisfy pending revision 2; cover superseded dependency, reference removal and tombstone ordering | Open; HARD-04 |
| F5 | Medium | Additional private-delivery liveness failure | >20 no-route waits, late route arrival before 48h, exact deadline and separate send-error budget; preserve independent copy routing and no public fallback | Open; HARD-05 |
| F6 | Medium | Reopens backlog portion of high T-302-01; also T-304-04 | Atomic 1,000-pending limit per merchant/relay, two concurrent admitters at 999, other-scope isolation, rate-window rollover, counted pre-decrypt drops | Open; HARD-06 |

F1 requires authenticated merchant access; it is not a demonstrated anonymous
buyer exploit. CI-01 is separate test-lifecycle debt, not a demonstrated
production security vulnerability. S1 is an entitlement policy risk; S2 is not
proof of unauthorized history disclosure. Preserve those distinctions.

## Security checks required before closure

- [ ] Permanent runtime regressions reproduce each F1–F6 failure on unpatched
  behavior, then pass with the fix; correct the test that currently approves
  unpaid merchant confirmation rather than preserving its wrong expectation.
- [ ] Re-test shared web/Gamma settlement, token status, buyer history and digital
  delivery; verify all items, duplicates, late payment, cancellation and unrelated
  payment exceptions. Audit events must match the atomic state/inventory result.
- [ ] Exercise DB-sensitive admission, reservation and dependency concurrency on
  disposable SQLite and PostgreSQL; retain all existing platform/matrix jobs.
- [ ] Re-check owner/merchant isolation, cookie-plus-bearer CSRF precedence,
  buyer session/magic-link scope, replay, identity merge rollback and no-oracle
  responses (`test_merchant_api.py`, `test_buyer_accounts.py`, `test_email_signin.py`).
- [ ] Re-check post-Phase-2 surfaces: owner-only key export/no-store, embed/public
  projections and CSP/CORS, catalog-import ownership/limits, CSV safety and media
  traversal/type/hash validation. Existing tests are evidence inputs, not a new
  unqualified ASVS sign-off.
- [ ] Re-test cryptographic chain validation, positive relay ACK semantics,
  per-party routing, NIP-42, SSRF/DNS/IPv6/reconnect boundaries and abuse limits;
  keep operator egress controls explicit.
- [ ] Ensure logs, metrics, audit history and failure evidence omit raw keys,
  tokens, decrypted payloads, buyer PII and full invoice material. Distinguish
  hash-based lookup from retained encrypted recovery/queued-delivery copies.
- [ ] Review host/dependency advisory dispositions in PINS.md; retain pins and
  security controls unless a separately reviewed update is authorized. This
  closeout does not install dependencies or grant new risk waivers.
- [ ] Record actual repaired revision, test commands, topology, backend, skips,
  process exit and remaining manual gates. Reconcile all affected requirements
  and registers; high/critical mitigations must not remain open at sign-off.
- [ ] Complete authorized live Plebeian checkout/payment UAT before full
  Release-B interoperability claims; neither scripted/local evidence nor
  listing visibility closes that gate.

## Verification ownership

[05-VALIDATION.md](05-VALIDATION.md) defines regression and evidence gates.
[02-SECURITY.md](../02-release-a-safe-web-commerce/02-SECURITY.md) preserves
historical threat history and reopens three original rows. Runtime filenames in
this checklist are under `tests/runtime/`. No new tests or fixes have been
implemented during this planning closeout; all unchecked requirements remain open.
