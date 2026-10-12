---
phase: "02"
slug: "release-a-safe-web-commerce"
status: gaps_found
threats_open: 3
asvs_level: 1
created: "2026-09-27"
---

# Phase 2 — Security

This register retains the 26-threat historical Phase 2 review. **Current status (2026-10-11): three original threats are reopened** by F1/F3; the old 26/26 closure is not current clearance. The new recovery, publication, retry and admission findings are tracked in Phase 5 `05-SECURITY.md`; this register is not a complete current-system threat inventory. Historical CI/UAT entries below retain their original dates and scope.

## Trust Boundaries

| Boundary | Data crossing | Control |
|----------|---------------|---------|
| Merchant browser → admin API | Session, configuration, identity import, order actions | Host owner authentication plus extension Origin/CSRF validation, legal actions and ciphertext key custody |
| Anonymous browser → public API | Cart, delivery information, idempotency key and private order token | Server-priced quote, stock claim, bounded rates, fragment-to-memory token extraction and header-only status access |
| Extension → LNbits wallet/database | Invoice request and authoritative payment record | UTC readiness, wallet/amount/hash/expiry correlation before invoice delivery and again at settlement; no retrying an uncertain invoice creation |
| Workers → extension database | Durable outbox, settlement, email and reservation writes | Conditional state changes, fencing tokens and per-recipient claims |
| Extension → Nostr relays | Signed public catalog/profile projections and relay ACKs | Validated relay targets, recipient-limited sending and durable ACK evidence; no order or payment authority crosses this boundary |
| Public theme → admin interface | Merchant-controlled token values | Allowlist, contrast gates and `.gm-public` CSS scope |

## Threat Register

All statuses below describe local implementation evidence, not deployed-platform certification. Severity and disposition are transcribed from the phase plans.

| Threat ID | Category | Component | Severity | Disposition | Mitigation and evidence | Status |
|-----------|----------|-----------|----------|-------------|-------------------------|--------|
| T-201-01 | Information disclosure | nsec import/key storage | high | mitigate | `keystore.py`, `crypto.py`; encrypted storage and log-redaction regressions in `test_crypto_keystore.py` | closed |
| T-201-02 | Elevation | cross-origin admin mutation | high | mitigate | `security.py` and admin API owner/Origin/CSRF guards; runtime auth probes and P0-12 | closed |
| T-201-03 | Tampering | catalog write without outbox | high | mitigate | `services/catalog.py` enqueues in the domain transaction; `test_catalog_api.py`, `test_outbox.py` | closed |
| T-201-04 | Information disclosure | markdown/JSON persistence or injection | medium | mitigate | Bounded catalog DTOs and sanitized rendering; catalog round-trip and public-page tests | closed |
| T-201-05 | Denial of service | oversized catalog input | medium | mitigate | `services/catalog.py` input bounds; `test_catalog_api.py` | closed |
| T-201-06 | Elevation | unsupported deployment topology | medium | mitigate | `services/readiness.py` refuses incompatible database/process timezones; `test_db.py`, `test_checkout.py` | closed |
| T-202-01 | Information disclosure | public pages expose internals | high | mitigate | `services/nip89.py` public projections; `test_public_contract.py`, `test_catalog_api.py` exclude draft, hidden and deleted data | closed |
| T-202-02 | Tampering | forged publication state | high | mitigate | `services/outbox.py` claim-token/lease CAS and durable relay evidence; `test_outbox.py` | closed |
| T-202-03 | Repudiation | lost or misattributed relay ACK | medium | mitigate | Per-target `relay_publications` evidence and positive LocalRelay ACK in isolated browser harness; `test_outbox.py` | closed |
| T-202-04 | Denial of service | stalled relay send | medium | mitigate | Bounded transport/retry and independent relay failures; `services/transport.py`, `test_outbox.py` | closed |
| T-202-05 | Elevation | CSS/script theme injection | medium | mitigate | `services/themes.py` allowlist and contrast checks, scoped emitted CSS/CSP; `test_themes.py` | closed |
| T-202-06 | Information disclosure | NIP-89 relay-hint fetch | medium | mitigate | `services/nip89.py` resolves local identifiers without fetching embedded hints; `test_nip89.py` and P0-11 | closed |
| T-202-07 | Tampering | relay URL changed or redirected after validation | medium | mitigate | `services/transport.py` revalidates before sync, connect and send; `test_relay_config_api.py` | closed |
| T-203-01 | Tampering | duplicate invoice/double allocation | critical | mitigate | `services/checkout.py` idempotency claim, conditional reservation, single Core external ID, invoice correlation and no blind reissue; `test_checkout.py`, `test_order_saga.py` on both databases | reopened — F3: reservation coverage can be absent at confirmation; Phase 5 |
| T-203-02 | Information disclosure | bearer token in path/query/log | critical | mitigate | `views_public_api.py` accepts `X-Order-Token`; browser immediately removes inbound fragment with `replaceState`; redaction/dead-token and Playwright tests | closed |
| T-203-03 | Tampering | buyer or relay evidence as payment | high | mitigate | `services/settlement.py` trusts only verified LNbits rows, not client or relay state; `test_order_saga.py` | closed |
| T-203-04 | Denial of service | stock squatting/checkout flood | high | mitigate | Bounded open orders/held stock and transactional rate buckets, TTL expiry; `test_checkout.py`, `test_email_queue.py` | closed |
| T-203-05 | Information disclosure | buyer address/contact | high | mitigate | AEAD fields, restricted public response and retention erasure; `test_order_saga.py`, `test_public_contract.py` | closed |
| T-203-06 | Repudiation | unproven refund claim | medium | mitigate | Merchant refund attestation is an audit event, not an automatic refund; `services/orders.py`, `test_order_admin.py` | closed |
| T-203-07 | Tampering | expired worker lease | high | mitigate | `services/tasks.py`, `services/email.py` and `services/outbox.py` guard leased writes; stale-claim tests | closed |
| T-204-01 | Information disclosure | fragment/history/referrer token leak | critical | mitigate | `public_order.js` strips fragment to memory; no token path/query in shipped API or E2E settle route; `test_buyer_ui.py`, `buyer.spec.ts` | closed |
| T-204-02 | Tampering | illegal action from admin UI | high | mitigate | `services/orders.py` legal transitions and admin action map; `test_order_admin.py` | reopened — F1: merchant status commands bypass payment/cancellation side effects; Phase 5 |
| T-204-03 | Information disclosure | admin renders secrets | high | mitigate | Redacted admin projections and technical details; `test_admin_ui.py`, `test_order_admin.py` | closed |
| T-204-04 | Elevation | merchant theme crosses into admin | medium | mitigate | `.gm-public`-scoped CSS and no admin theme token emission; `test_themes.py`, `test_admin_ui.py` | closed |
| T-204-05 | Denial of service | buyer induced to pay twice | critical | mitigate | `public_checkout.js` preserves uncertain idempotency keys and offers no second invoice; invoice/expiry text avoids claiming unpaid without proof; `buyer.spec.ts`, `test_order_saga.py` | closed |
| T-205-01 | Information disclosure | digital delivery content released before payment or published | high | mitigate | Added after UAT (2026-09-27). `products.delivery_enc` AEAD at rest (`services/catalog.py`); only the owner-scoped admin API decrypts it; `services/orders.py::digital_delivery` returns content only for `confirmed/processing/completed` without payment exception or oversell; never in public product JSON/HTML or NIP-99 events; buyer UI renders it as text with http(s) links only (no innerHTML). `test_order_saga.py::test_digital_delivery_revealed_only_after_confirmed_payment`, `test_public_contract.py`, `buyer.spec.ts` | reopened — F1: unpaid confirmation unlocks digital delivery; Phase 5 |

A shareable order link intentionally contains a token in its **URL fragment** until the receiving page strips it. The protection is that the fragment is not sent in HTTP paths, queries or referrers; the link itself must be kept private. No broader claim that the token never appears in a URL is made.

## Accepted Risks Log

No accepted risks. A relay can retain already-public catalog events despite a kind-5 deletion; checkout always checks the canonical database instead of trusting relay availability or stock.

## Security Audit Trail

| Audit Date | Threats Total | Closed locally | Open at/above high | Run By |
|------------|---------------|----------------|--------------------|--------|
| 2026-09-27 | 25 | 25 | 0 | Devin, source review + SQLite/PostgreSQL qualification and Chromium |
| 2026-09-27 | 25 | 25 | 0 | Linux CI run 36303338957: x86_64/ARM64 × SQLite/PostgreSQL all passed on `b12e350` |
| 2026-09-27 | 26 | 26 | 0 | Current implementation CI run 36352552899: x86_64/ARM64 × SQLite/PostgreSQL all passed on `021c402` |
| 2026-09-27 | 26 | 26 | 0 | Human UAT 3/3: checkout/payment wording, private order/admin workflow, responsive accessibility and theme isolation passed |

## Sign-Off

- [ ] Each planned threat has a mitigation verified against the current runtime, including the reopened cases.
- [x] No risk was silently accepted as a substitute for a missing mitigation.
- [ ] Current local mitigations are closed; `threats_open: 3` until the reopened Phase 2 threats are repaired and retested.
- [x] Current-revision Linux x86_64 and ARM64 CI evidence reviewed.
- [x] Historical human security/UX and accessibility review completed through UAT 3/3; not rerun in this closeout.

**Historical approval:** verified for Phase 2 on 2026-09-27. **Current approval: withheld** pending Phase 5 repairs. The old external-test scope limits remain unchanged; no required gate has been waived.

## 2026-10-11 reopening

Three original rows are reopened, retaining their original severities, including
the critical T-203-01 classification. F2/F4/F5/F6 are additional findings in the
[Phase 5 register](../05-correctness-recovery-and-security-hardening/05-SECURITY.md).
Do not sum the two registers as distinct vulnerabilities: finding/threat mappings
overlap. Existing security enforcement and the high-severity blocking threshold
are unchanged. No risk acceptance substitutes for the missing fixes.
