---
phase: "05"
slug: correctness-recovery-and-security-hardening
status: gaps_found
threats_open: 6
asvs_level: 1
created: 2026-10-11
---

# Phase 5 — Open Security and Correctness Register

This is a scoped register of **six assessment findings plus the later open WR-04 authorization follow-up**, not a complete new
ASVS certification. Three are high-priority financial findings in the assessment.
Historical threat classifications are retained; in particular T-203-01 remains
critical and T-302-01 remains high. Related rows across registers overlap and
must not be summed as distinct vulnerabilities. No finding is accepted or waived.

| Finding | Assessment priority | Existing threat relationship | Boundary and required evidence | Status |
|---|---|---|---|---|
| F1 | High | Reopens T-204-02 and T-205-01 | Authenticated merchant status cannot confirm unpaid orders or release buyer delivery; cancellation releases held stock once; test owner/API, token and authenticated-history surfaces | Open; HARD-01 |
| F2 | High | Additional recovery-availability failure, not covered by a blanket old closure | Invoice created then response lost; recover the same invoice, settle, clear only the resolved uncertainty and retain unrelated holds | Open; HARD-02 |
| F3 | High | Reopens critical T-203-01 inventory assurance | Expire/release holds before recovery/settlement; verify complete stock accounting or explicit exception, duplicate-callback safety and concurrency | Open; HARD-03 |
| F4 | Medium | Additional publication-ordering failure; claim fencing alone is insufficient | Published revision 1 cannot satisfy pending revision 2; cover superseded dependency, reference removal and tombstone ordering | Mitigated 2026-10-12 (local, both DBs; independent review PASSED); HARD-04 |
| F5 | Medium | Additional private-delivery liveness failure | >20 no-route waits, late route arrival before 48h, exact deadline and separate send-error budget; preserve independent copy routing and no public fallback | Mitigated 2026-10-12 (local, both DBs; independent review PASSED); HARD-05 |
| F6 | Medium | Reopens backlog portion of high T-302-01; also T-304-04 | Atomic 1,000-pending limit per merchant/relay, two concurrent admitters at 999, other-scope isolation, rate-window rollover, counted pre-decrypt drops | Mitigated 2026-10-12 (local, both DBs; contested 999 proof; independent review PASSED); HARD-06 |

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
this checklist are under `tests/runtime/`. The original planning checklist remains unchecked where whole-phase or release
evidence is still required. Local financial implementation evidence below does
not waive those gates.

## Authorized financial-tranche disposition

F1–F3 source mitigation is implemented and independently reviewed locally.
Final synthetic financial retention is SQLite 433 passed/6 PG-only skips and
PostgreSQL 439 passed/no skips, natural exit 0; buyer hard02 passes one test
covering three scenarios. CR-01–06 and WR-02 are resolved in source; see
`05-REVIEW.md` and `05-FINANCIAL-REVIEW-FIXES.json` for exact evidence.
The original F1–F3 rows remain open for qualification, not as claims that their
original source failure mechanisms still pass the current tests. ASVS level 1
and high/critical blocking policy are unchanged.

- **WR-04: RESOLVED 2026-10-12.** Presented-token digest and expiry are now
  revalidated under the order lock inside the content/mutation transaction
  (`_locked_order_for_token`) for status, opt-out and claim; the claim path
  also re-verifies bound-value equality on the fresh row. Permanent regressions
  on both DBs; no-oracle identical 401 preserved.
- F1 pinned-host admin no-pageerror qualification remains OPEN. No errors were
  filtered; no vendor, certificate, dependency or security-policy change.
- F2 original browser RED chronology remains absent; actual baseline RED was
  captured retrospectively after GREEN and is not recast as test-first proof.
- **HISTORICAL-PAID-ORDER-AUDIT: authorized read-only scan performed
  2026-10-12.** Every reachable local datastore was inspected read-only
  (`.cache/qual-data*`, `phase2-closeout-sqlite-*`, `lnbits/data`, Downloads
  backup, /tmp, phase-5 sandbox): **zero actual infinitemarkets order records
  exist locally** — only host core DBs and an empty legacy `ext_gammamarkets`
  file. Dispositions needed locally: NONE. If a deployed/remote instance
  exists, its audit remains a separate operator gate; production exposure and
  release clearance still require that evidence. No automatic repair/refund or
  live-funds/relay operation was performed.
- F4–F6, CI-01, full platform/matrix/qualification and live Plebeian remain
  pending. Local commit authorizes neither deployment nor further execution.

## Wave 4/5 disposition (F4/F5/F6 + CI-01)

F4 revision-bound dependencies, F5 no-route retry eligibility and F6 atomic
inbox backlog bound are implemented and independently reviewed; CI-01's
lifecycle root cause (cancelled engine checkout orphaning an aiosqlite worker
thread) is demonstrated and fixed, including the WR-05 drain residual. Full
`make verify` passes on both profiles (SQLite 982/8 skips; PG 987/3 skips).
These rows are mitigations verified locally — threat rows close only under the
05-06 qualification gates. WR-04 token revocation/expiry remains
MEDIUM / OPEN / NOT FIXED / NOT WAIVED. Historical audit remains
OPEN / NOT AUTHORIZED / NOT PERFORMED (evidence NONE). Live Plebeian,
browser host qualification and release clearance remain pending.
