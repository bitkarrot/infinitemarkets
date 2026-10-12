---
phase: 02-release-a-safe-web-commerce
verified: 2026-09-27T22:49:26Z
status: gaps_found
historical_score: 5/5 acceptance areas passed; 4/4 required Linux profiles passed; human UAT 3/3; security verified
implementation_sha: 021c402d620396b671c3fd919ad2275b4c3072ff
ci_run: 36352552899
historical_behavior_unverified: 0
---

# Phase 2 — Release A Verification

**Current verdict (2026-10-11): acceptance reopened for F1–F4.** The results below are the historical 2026-09-27 sign-off, not current clearance. See the closeout addendum and Phase 5.

## Exact verified profile

| Item | Value |
|------|-------|
| Verified date | 2026-09-27 UTC |
| Implementation | Production extension code remains `021c402d620396b671c3fd919ad2275b4c3072ff`; later commits change closeout evidence and Node/CI policy only, with no diff under `infinitemarkets/`, `tools/`, `harness/`, `pyproject.toml` or `uv.lock` |
| Current CI | [Run 36352552899](https://github.com/bitkarrot/infinitemarkets/actions/runs/36352552899), conclusion `success`, head SHA `021c402d620396b671c3fd919ad2275b4c3072ff` |
| LNbits host | `1.6.2-rc1`, pinned checkout `e336fe14b841d6f0c940e75b3d343e3ab5cf8433`, clean; no LNbits core source changed |
| Language | Python 3.12 |
| Payment backend | LNbits FakeWallet in disposable host installations; no real-funds/provider claim |
| Databases | SQLite and PostgreSQL with the qualified single-process/UTC topology |
| Relay E2E | Owned deterministic LocalRelay with positive/negative/timeout ACK evidence; no external-public-relay claim |

## Automated and human results

| Gate | Result |
|------|--------|
| Linux SQLite x86_64 | **450 passed, 3 skipped** |
| Linux SQLite ARM64 | **450 passed, 3 skipped** |
| Linux PostgreSQL x86_64 | **451 passed, 2 skipped**, one warning from the intentional host auto-commit probe |
| Linux PostgreSQL ARM64 | **451 passed, 2 skipped**, one warning from the intentional host auto-commit probe |
| Lint | Ruff: **all checks passed** |
| Advisory macOS ARM64 SQLite | **450 passed, 3 skipped** |
| Current UAT-fix runtime subset | **13 passed** on SQLite and **13 passed** on isolated UTC PostgreSQL |
| Current browser suite | **19 Chromium tests passed** on a fresh server, including admin state/detail, optional-email invoice, navigation, digital delivery, appearance clipping and mobile compact fallback |
| Port 5099 focused demo | Guided blank-email invoice, distinct order states and digital-order detail checks passed on the current implementation |
| Human UAT | **3/3 passed, 0 issues** |
| Nyquist audit | **16/16 Phase 2 requirements have automated behavioral coverage; 0 gaps** |
| Security audit | **26/26 threats closed, 0 open; ASVS-1 status verified** |
| UI audit | **21/24, no blocker**; typography/spacing token cleanup recorded as non-blocking consistency work |

Skips are the optional external-relay smoke plus topology-specific concurrency drills. They do not remove coverage from the declared Phase 2 local deployment profile. The PostgreSQL warning is from the qualification probe that deliberately demonstrates the host helper's auto-commit behavior; it is not an application warning.

## Goal checks

| Phase 2 success area | Evidence | Status |
|----------------------|----------|--------|
| Merchant identity, wallet, authoritative catalog, shipping, themes and publication | Merchant/catalog/crypto/outbox/theme runtime suites on both dialects; owner-scoped admin browser flows; LocalRelay ACK evidence | passed |
| NIP-89 discovery, authoritative quote, exactly one invoice and private status | NIP-89/public-page/checkout/status tests; quote and invoice correlation; fragment stripping and header-only token polling; buyer Playwright journey | passed |
| Inventory/payment safety under races, retries and failure recovery | Conditional stock claims, idempotency, invoice saga, lease fencing, late/mismatched settlement and reconciliation tests on SQLite/PostgreSQL | passed |
| Legal merchant operations, notifications and digital fulfillment | Order transition, chronology, email queue, retention and post-settlement digital-delivery tests; admin/browser UAT | passed |
| Security, accessibility, responsive UI and qualified deployment constraints | 26-threat register, WCAG/theme gates, current browser checks, 3/3 human UAT, topology/UTC readiness guards and green Linux matrix | passed |

## Release gates

- **Current implementation CI:** passed all required Linux x86_64/ARM64 SQLite/PostgreSQL profiles.
- **Human buyer/merchant UAT:** passed 3/3 after the reported admin cache, order-detail and optional-email regressions were fixed.
- **Security/accessibility review:** verified with `threats_open: 0`; responsive, focus, contrast, theme-isolation and plain-language checks passed UAT.
- **Validation coverage:** Nyquist-compliant with no missing requirement-level automated coverage.
- **UI review:** no blocker; exact typography/spacing-token consolidation and durable screenshot baselines remain recommendations, not Phase 2 acceptance failures.

## Explicit scope limits

Optional external public-relay smoke and real-funding-provider payment tests were not performed. Phase 2's declared reproducible scope uses LocalRelay and FakeWallet; relay ACK remains delivery evidence only, and LNbits settlement remains payment truth. The fresh port 5099 demo is disposable and does not mount the earlier demo database, whose files remain preserved on disk.

## Decision

Phase 2 is verified and may be marked complete. Release A requirements MERC-01, CAT-01/02, PUB-01/02, WEB-01/02, PAY-01/02, INV-01, ORD-01, NOTF-01, SEC-01 and UI-01/02/03 can move from Pending to Complete. Phase 3 may start independently; its NIP-17/NIP-07 and Nostr order-history work was not pulled into Phase 2.

## Closeout addendum — 2026-10-11

The conformance follow-up at `a7082c7` reproduced unpaid merchant confirmation/
delivery and cancellation stock leakage (F1), recovered-invoice hold persistence
(F2), confirmation after reservation expiry without stock consumption (F3), and
stale-revision dependency satisfaction (F4). These reopen current acceptance;
the historical scores, profile and test counts above are not revised into a pass.

Remediation is HARD-01–04/HARD-08 in Phase 5. The security register reopens the
existing T-203-01, T-204-02 and T-205-01 mitigations; Phase 5 also records new
recovery/publication threats. Temporary review probes are not permanent tests.
No code was fixed by this addendum. See `docs/spec-conformance-analysis.md` and
`.planning/v1.0-MILESTONE-AUDIT.md` from the repository root.
