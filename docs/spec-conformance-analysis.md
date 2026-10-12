# Infinite Markets — Implementation Quality Analysis

**Revised:** 2026-10-11 (local date; test output is dated 2026-10-12 UTC)

**Implementation reviewed:** `a7082c7e21b435af8d420a1d6712b980e399c876`

**Scope:** Infinite Markets LNbits extension against the
[technical specification](technical-specification.md), its recorded decisions,
and the pinned Open Markets protocol.

**Status:** Revised assessment; findings remain open. No implementation fixes
were applied as part of this review.

## Verdict

**Strong foundations and substantial protocol coverage, but several payment and
inventory correctness defects need fixing before a production-readiness
conclusion is defensible.**

The earlier version of this analysis was too optimistic. Its claims that the
financial paths were “production-grade” and that none of the gaps affected
settlement or inventory safety are withdrawn. Centralized state transitions,
careful cryptography, and green CI are valuable, but do not establish that every
caller enforces the necessary payment, inventory, and recovery invariants.

The highest priorities are merchant status commands, invoice-timeout recovery,
and settlement after reservation expiry. Publication ordering, private-message
retry eligibility, and inbox backlog admission also require correction.

## Review baseline and evidence

### Specification baseline

- The implementation contract pins market-spec commit
  `5dc79c5db0d41c0bea774debf445cce041192840` and Nostr NIPs commit
  `a2494f4f81d46684e5814a9bf35e2b1df978f955`.
- The [upstream Open Markets README inspected](https://github.com/OpenMarketsFoundation/specification/blob/24313d75bb6ebf3ba37266a504980340308b4dc8/README.md)
  is at commit `24313d75bb6ebf3ba37266a504980340308b4dc8`. Its specification
  content has the same Git blob, `2ba8ebabbd11d371b3698c91ccdbeef4fc97616b`, as
  `spec.md` at the pinned commit. The rename is not a semantic protocol change.
- Internal implementation-contract requirements and upstream protocol
  requirements are distinct. Optional features, recorded divergences, and
  proposed upstream changes are not automatically missing mandatory features.

### Verification performed during the follow-up review

| Evidence | Result and scope |
|---|---|
| Focused existing tests | **77 passed, 1 skipped**, using fresh temporary SQLite databases and the project's FakeWallet fixtures. The skip is full-profile evidence closure, which cannot run meaningfully in a filtered subset. |
| Additional temporary probes | Eight assertions failed, reproducing the behaviors documented below: seven correctness checks across F1–F6 and one stable-delivery policy check in S1. These probes were removed after the review; they are not committed regression tests. |
| CI for the reviewed commit | [Run 38194415581](https://github.com/bitkarrot/infinitemarkets/actions/runs/38194415581) succeeded: Linux x86_64 and ARM64, each with SQLite and PostgreSQL, plus lint. |
| Historical checked-in evidence | [REPORT.md](../evidence/REPORT.md) records **569/572 passed, 3 skipped, 0 failed** on macOS ARM64/SQLite, generated 2026-09-29. This is not the current implementation's test count or its only database evidence. |
| External-client evidence | Scripted Plebeian runs use a local LNURLp shim and FakeWallet. The recorded live public-relay smoke verified listings only, not checkout/payment. |

The existing-test selection covered `test_order_admin.py`, `test_order_saga.py`,
`test_crypto_keystore.py`, `test_keystore_nip17.py`, `test_nip17_outbox.py`, two
outbox dependency tests, and `test_p0_14_contract_closure.py`. It was not a new
full qualification run, live-funding test, or rerun of every CI topology.

These results describe the preceding source review and test runs; updating this
document does not constitute another test run or a release certification.

## Quality work that remains supported

### Transactional structure and invoice correlation

`transition_order()` centralizes legal transitions, compare-and-swap updates,
audit events, and applicable Gamma status intents in a transaction. The checkout
saga reserves stock before the external invoice call and persists a deterministic
`core_external_id` for recovery. Uncertain creation is distinguished from definite
failure, avoiding automatic creation of a second invoice. The normal settlement
path verifies incoming payment, amount, wallet ownership, and invoice correlation.

These are sound building blocks. F1–F3 show why state-table legality and payment
verification must also be tied to complete business preconditions and side effects.

Sources: [order transitions](../infinitemarkets/services/orders.py#L176-L259),
[invoice saga](../infinitemarkets/services/checkout.py#L1083-L1215),
[settlement verification](../infinitemarkets/services/settlement.py#L62-L189).

### Monetary precision and cryptographic boundaries

The FX service uses Decimal arithmetic, per-component ceiling rounding, provenance
and freshness checks, and checked integer totals. Encryption uses AES-256-GCM with
record/table/column/key-version binding; equality indexes use purpose-separated
HMACs. These choices materially reduce rounding and ciphertext-substitution risks.

Token lookup is hash-based, but the original “hash-only” storage description was
inaccurate: encrypted token copies are retained for supported recovery and delayed
notification behavior. Scoped key access is also not a claim of guaranteed memory
zeroization in Python.

Sources: [FX conversion](../infinitemarkets/services/fx.py#L124-L188),
[crypto primitives](../infinitemarkets/crypto.py#L49-L132),
[token persistence](../infinitemarkets/services/checkout.py#L900-L950).

### Private-message validation and delivery evidence

The inbox validates outer bounds, recipient tags, and signatures before durable
admission and expensive unwrap processing. The keystore checks the seal/rumor
chain, including canonical identity and raw-tag constraints. Durable inbox state
and rumor deduplication support recovery. Session-based cursors account for
backdated NIP-59 wrappers rather than treating event timestamps as arrival times.

Outbound private messages use independent recipient and sender copies, track
accepted relays separately, and require positive ACK evidence in both classes.
Claim tokens and lease checks are valuable safeguards. Those strengths do not
eliminate the dependency and retry-budget defects in F4–F5.

Sources: [inbox](../infinitemarkets/services/inbox.py),
[unwrap validation](../infinitemarkets/keystore.py#L455-L609),
[private outbox](../infinitemarkets/services/outbox.py#L768-L996).

### Access controls and qualification infrastructure

The mutation guard distinguishes cookie and bearer authentication, requires exact
Origin and CSRF checks for cookie mutations, and does not let an added bearer
header bypass cookie rules. Static inspection found all 88 admin route decorators
covered by `problem_boundary`, and all 21 public handlers calling `_guard`.
Authenticated buyer history additionally requires a buyer session.

This confirms boundary coverage, not universal correctness of every response or
operation. In particular, “RFC 9457 everywhere” was too broad: wrapper coverage
alone does not prove every framework- or host-generated error has that format.

The SQLite/PostgreSQL CI matrix, adversarial crypto tests, runtime host fixtures,
and explicit external-client divergence register are meaningful strengths. Their
limits must remain visible rather than treating a successful test run as a blanket
conformance claim.

Sources: [mutation guard](../infinitemarkets/security.py#L111-L159),
[CI matrix](../.github/workflows/qualification.yml),
[conformance documentation](../tests/conformance/README.md).

## Confirmed findings requiring correction

Priority indicates remediation order, not a formal exploitability score.
**High** findings affect payment, inventory, or fulfillment correctness.
**Medium** findings affect protocol ordering, recovery, or resource bounds.
All findings below are open at the reviewed implementation revision.

### F1 — High: merchant status commands bypass payment and inventory rules

**Observed:** An authenticated merchant could request
`awaiting_payment → confirmed` through the status API. The response was HTTP 200;
the order became `confirmed`, payment remained `pending`, and digital delivery
became visible. A separate probe cancelled an order through `/status` and left
its two reserved units reserved.

`admin_set_status()` delegates to the transition table without invoking all the
business operations associated with the target state. `delivery_unlocked()`
trusts the resulting order state and exception flags, not verified settlement.
The dedicated cancellation service releases reservations, but the generic status
path bypasses it.

This requires authenticated access to the merchant's own order. It is not an
anonymous buyer exploit, but it violates the application's payment/fulfillment
contract and can leave inventory inconsistent until another cleanup path runs.

**Required improvement:** Restrict merchant status commands to appropriate
fulfillment transitions. Keep payment confirmation behind verified settlement;
route cancellations through the transactional cancellation operation. Enforce
actor-specific preconditions and side effects, not just membership in a state table.

**Regression acceptance:** Unpaid merchant confirmation cannot unlock delivery;
all permitted cancellation entry points release held stock exactly once. Correct
the existing transition test, which currently expects unpaid confirmation to pass.

Sources: [status command](../infinitemarkets/services/orders.py#L807-L838),
[delivery gate](../infinitemarkets/services/orders.py#L135-L168),
[current test expectation](../tests/runtime/test_order_admin.py#L380-L402).
Contract: technical specification §§7.1, 8.2–8.3; upstream `confirmed` means payment
received and verified.

### F2 — High: recovered invoice timeouts can leave paid orders on hold

**Observed:** A probe let LNbits persist an invoice, then raised a timeout before
returning it to checkout. Reconciliation recovered the invoice and FakeWallet
settled it. The resulting order was `confirmed`, payment was `settled`, but
`payment_exception=true` and digital delivery was empty.

The timeout path sets an uncertainty exception. Successful attachment/settlement
does not resolve that exception. The ordinary `accept` action applies only to
expired/cancelled orders, so it does not directly resolve this confirmed state.

**Required improvement:** Give creation-uncertainty exceptions an explicit,
verified recovery path. Clear only the uncertainty that has actually been
resolved; do not indiscriminately clear amount, wallet, or other review holds.

**Regression acceptance:** Persist-then-timeout followed by recovery and valid
settlement produces a usable paid order, without a second invoice. Genuine
payment-mismatch exceptions must remain blocked.

Sources: [uncertainty flag](../infinitemarkets/services/checkout.py#L1377-L1396),
[settlement confirmation](../infinitemarkets/services/settlement.py#L280-L390),
[accept guard](../infinitemarkets/services/settlement.py#L689-L717).

### F3 — High: expired reservations can be followed by confirmation without stock consumption

**Observed:** While an order remained `invoice_pending`, the probe forced its
held reservations to expire in the isolated database. Reconciliation then attached
the invoice, and a verified FakeWallet settlement confirmed the order. A purchase
of two units left stock at **10 on hand, 0 reserved**, rather than accounting for
the purchase.

The expiry worker releases reservations without changing `invoice_pending`.
Attachment subsequently moves that order to `awaiting_payment`. Settlement
consumes whatever held reservations it finds—even an empty set—and then confirms.
The timeout exception may still block delivery, but that separate hold does not
make the inventory accounting correct.

This is a simulated recovery-ordering test, not a real-time external funding
provider test or a demonstrated production oversell.

**Required improvement:** Validate complete reservation coverage against order
items before normal confirmation. If capacity has been released, use an explicit
late-payment/reallocation procedure, with oversell/backorder handling where needed.
Coordinate expiry, attachment, and settlement under transactional guards.

**Regression acceptance:** Recovery cannot normally confirm an order while
silently omitting its stock consumption. Cover expiry/attachment/settlement
ordering and competing inventory allocation on both supported databases.

Sources: [reservation expiry](../infinitemarkets/services/settlement.py#L435-L475),
[attachment transition](../infinitemarkets/services/checkout.py#L1323-L1344),
[consumption loop](../infinitemarkets/services/settlement.py#L344-L373).
Contract: technical specification §§8.3–8.4.

### F4 — Medium: publication dependencies accept stale revisions

**Observed:** With collection revision 1 published and revision 2 pending, a
child explicitly depending on revision 2 was considered ready to publish.

`_deps_published()` accepts any published revision of the aggregate. That is weaker
than the contract's requirement to rebind superseded dependencies to a current
replacement, never satisfying them with stale content. Reference-removal and
tombstone ordering can consequently be bypassed.

**Required improvement:** Track the required revision/event identity, or its valid
replacement, rather than any historical publication. Avoid fixing supersession
wedges by weakening the ordering invariant.

**Regression acceptance:** Published revision 1 cannot satisfy a dependency on
pending revision 2; superseded dependencies advance only after the appropriate
replacement publishes. Update the test that currently accepts the older revision.

Sources: [dependency check](../infinitemarkets/services/outbox.py#L214-L233),
[current dependency test](../tests/runtime/test_outbox.py#L470-L506),
[contract ordering requirement](technical-specification.md#L1325-L1328).

### F5 — Medium: no-route waits exhaust retry eligibility before 48 hours

**Observed:** After 20 no-route passes, an intent remained `pending` with
`attempts=20`, but the claim query would not select it again. The probe advanced
retry eligibility without waiting for wall-clock intervals; the intent was still
well inside its 48-hour deadline.

No-route waiting consumes the ordinary failed-send budget. At the default
15-minute cadence, 20 attempts exhaust eligibility after approximately five hours,
not 48 hours. A subsequently discovered route does not itself reset that counter.
The 48-hour deadline check in the publish path does not repair this loss of
claim eligibility.

**Required improvement:** Separate no-route waiting from failed-send attempts, or
otherwise keep the intent eligible throughout the documented recovery window.

**Regression acceptance:** Routes appearing after more than 20 discovery waits,
but before the 48-hour deadline, still allow delivery. Deadline expiry must become
an explicit terminal outcome rather than leaving unclaimable pending work.

Sources: [claim eligibility](../infinitemarkets/services/outbox.py#L175-L180),
[attempt increment](../infinitemarkets/services/outbox.py#L271-L290),
[no-route branch](../infinitemarkets/services/outbox.py#L880-L893).
Contract: technical specification §9.3.

### F6 — Medium: the per-merchant/relay inbox backlog bound is missing

**Observed:** With 1,000 `received` rows preloaded for one merchant/relay pair,
admission accepted another valid signed wrap, increasing that same scope to 1,001.
The per-minute rate limit is implemented; the queue-depth limit is not.

The original report cited a 1,300-message drain test as proof, but that test spreads
messages across five relay scopes. It demonstrates bounded draining, not violation
of a 1,000-row per-scope cap. The new same-scope probe establishes the missing bound.

**Required improvement:** Enforce admission depth atomically for the specified
scope before decrypt work, with overload metrics and an appropriate index/locking
strategy. Bounded drain batches do not bound total stored backlog.

**Regression acceptance:** At the cap, the next admission is rejected/counted
without increasing backlog. Cover concurrent admissions and backlog accumulation
across multiple rate-limit windows on SQLite and PostgreSQL.

Sources: [admission](../infinitemarkets/services/inbox.py#L180-L217),
[existing multi-scope drain test](../tests/runtime/test_release_b_drills.py#L462-L486).
Contract: technical specification §15.

## Additional improvements and scope clarifications

### S1 — Define and preserve purchased digital entitlements

The eighth temporary probe confirmed that editing a product's delivery content
changes the content returned for an already-paid order. `digital_delivery()` joins
live product data rather than an order-specific delivery snapshot.

For license keys, fixed deliverables, and dispute evidence, snapshot or version
the purchased entitlement and make revocation/replacement explicit. If delivery
is intentionally a live resource, document that policy instead. This is a confirmed
behavioral risk and product-contract decision, not automatically a violation of an
explicit immutable-delivery requirement in the current specification.

Source: [live delivery lookup](../infinitemarkets/services/orders.py#L148-L168).

### S2 — Align identifier and authenticated-history contracts

- **Confirmed schema-description mismatch:** `orders.source_event_id` receives
  the rumor ID, while §4.7 describes the outer kind-1059/kind-4 ID. Record the
  intended semantics or model both identifiers explicitly; do not confuse this
  internal mismatch with a malformed outbound protocol event.
- **History disclosure was overstated:** `/nostr/orders` requires a buyer session
  and scopes results to that buyer within the merchant. Returning `order_id` and a
  recoverable `status_url` is not demonstrated unauthorized disclosure. Document
  the authenticated history contract separately from the anonymous/token-only
  status projection, and protect returned bearer material from logging. Moving
  URL construction to the client alone would not remove token exposure.

Sources: [rumor ID storage](../infinitemarkets/services/checkout.py#L1683-L1698),
[schema description](technical-specification.md#L352-L358),
[history scoping and projection](../infinitemarkets/views_public_api.py#L750-L821).

### S3 — Improve evidence quality and operational clarity

- **PostgreSQL CI already exists and passed.** Preserve and extend that coverage;
  do not add a supposedly missing CI leg. Database-matrix success is not by itself
  proof of every multi-process deployment or recovery interleaving.
- **Contract closure is narrower than originally claimed.** It compares the
  specification with harness registries, schemas, state models, and fixtures—not
  all production endpoint behavior. Add runtime-level invariant tests, including
  actor permissions and cross-service side effects.
- **External interoperability is still qualified.** The scripted Plebeian matrix
  exercises real client code but uses FakeWallet and a local LNURLp shim. Its
  physical-order case verifies rejection of an unsupported opaque address, not a
  successful physical purchase. The recorded live smoke covers listings only.
  Complete and record live order/payment validation before making broader claims.
- **Optional/deferred scope is not a defect by default.** Live NIP-15/NIP-04
  ordering is absent and intentionally deferred; NIP-04 methods raise
  `ReleaseNotAvailable`. It is not a missing core Open Markets requirement.
  Local-only drafts, reviews, automatic payment modes, and third-party shipping
  should be evaluated against their actual optionality and recorded decisions.
- **Resolve wire-format ambiguity deliberately.** The upstream 30406 examples use
  one multi-value `country`/`region` tag; the implementation emits one tag per
  code. The roadmap already records this interoperability question. Establish the
  accepted encoding with external fixtures or an explicit upstream clarification,
  rather than silently treating it as either proven conformance or a settled bug.

Sources: [CI configuration](../.github/workflows/qualification.yml#L46-L119),
[closure test scope](../tests/qualification/test_p0_14_contract_closure.py#L1-L18),
[external-client verification](../.planning/phases/03-release-b-gamma-nip-17-orders/03-VERIFICATION.md#L25-L76),
[legacy stubs](../infinitemarkets/keystore.py#L410-L414),
[future alignment roadmap](../FUTURE-ROADMAP.md#spec-alignment-backlog).

### S4 — Lower-priority maintainability and hardening

- Parameterize the `list_orders()` ID list instead of interpolating it into SQL.
  The current values come from internal order IDs; SQL injection was not
  demonstrated by this review.
- Replace stale plan-era docstrings and evaluate whether the now-no-op
  `released_product_clause`/`released_product_select` indirection still earns its
  complexity. These are cleanup items, not fixes for F1–F6.
- Replace the fixed AUTH-settle sleep with explicit synchronization where the
  transport permits it. Validate slow-challenge behavior rather than relying on
  a 50 ms scheduling assumption.
- Document trusted-proxy/IP-scoping assumptions and fixed-window burst behavior.
  Keep process-local metrics counters distinct from database-backed queue gauges;
  add aggregation if multi-worker operational visibility is required.

Sources: [SQL interpolation](../infinitemarkets/services/orders.py#L583-L591),
[release predicates](../infinitemarkets/db.py#L104-L114),
[inbox transport](../infinitemarkets/services/inbox.py),
[metrics](../infinitemarkets/services/metrics.py).

## Corrections to the original assessment

| Original claim | Revised conclusion |
|---|---|
| Financial paths are production-grade; remaining issues cannot affect inventory safety | Withdrawn. F1–F3 reproduce payment, fulfillment, and stock-accounting failures. |
| Recorded conformance is SQLite-only; PostgreSQL CI must be added | Incorrect as an overall coverage claim. The historical report is SQLite-only; current CI passes both databases on both Linux architectures. |
| Contract closure establishes runtime-wide bidirectional conformance | Overstated. The gate closes the specification against harness models and registries; production behavior needs separate testing. |
| NIP-17 no-route retries operate throughout the documented 48 hours | Not supported by the implementation's attempt-budget interaction; F5 reproduces early loss of claim eligibility. |
| A 1,300-message drain test proves a per-scope backlog violation | Insufficient evidence because it uses multiple relay scopes. F6 separately confirms the same-scope defect. |
| Public tokens are stored only as hashes | Incomplete. Lookup uses hashes, but supported workflows also retain encrypted recovery copies. |
| `/nostr/orders` returns internal IDs and status links contrary to the public-order contract | The returned fields are confirmed, but the contract scope needs clarification. Buyer authentication and ownership scoping exist; unauthorized disclosure was not demonstrated. |
| All errors necessarily have RFC 9457 formatting | Not established by decorator coverage. Distinguish mapped domain errors from framework/host errors. |
| NIP-15/NIP-04 inbound is absent, not just deferred | It is absent and intentionally deferred. These are compatible descriptions, not a missing mandatory core feature. |

## Recommended improvement sequence

1. **Repair merchant commands (F1):** payment confirmation authority and atomic
   cancellation side effects. Correct tests that currently approve unsafe behavior.
2. **Complete financial recovery (F2–F3):** uncertainty resolution, reservation
   coverage checks, and explicit handling of capacity released before settlement.
3. **Repair protocol recovery and ordering (F4–F5):** revision-aware dependencies
   and no-route eligibility throughout the promised window.
4. **Bound admission (F6):** atomic per-scope backlog enforcement and overload
   observability.
5. **Land permanent regression coverage:** retain the reproduced scenarios in the
   repository, exercise both database profiles, and add relevant concurrency cases.
6. **Clarify product and interoperability contracts (S1–S3):** stable delivery,
   identifier semantics, authenticated history, wire-format decisions, and live
   external-client evidence. Address S4 cleanup after correctness work.

The right next step is targeted invariant repair, not an architectural rewrite.
Preserve the strong transactional, cryptographic, and protocol foundations while
closing the demonstrated gaps between components. Reassess readiness only after
the fixes and permanent regression coverage are in place.

## Remediation status

**2026-10-12 — all six findings repaired and verified; release clearance still
pending.** The Phase 5 hardening tranche in `.planning/` implemented and
independently reviewed the repairs. Fixes below are local verification on the
approved SQLite + disposable PostgreSQL profiles; full detail lives in
`.planning/phases/05-correctness-recovery-and-security-hardening/05-REVIEW.md`.

| Finding | Disposition | Key repair |
|---|---|---|
| F1 — merchant status bypass | **Fixed** — `3c0c237` | Status/fulfillment/delivery share locked payment + inventory authority; cancellation atomically releases reservations; unpaid confirmation refused |
| F2 — recovered timeout stuck on hold | **Fixed** — `3c0c237` | Order-first CAS timeout handling, strict invoice identity correlation, pure-creation-uncertainty resolution, protected-hold preservation, hold-aware public invoice suppression |
| F3 — expired-reservation confirmation | **Fixed** — `3c0c237` | Complete live-coverage requirement before consumption; expired/incomplete settlement routes to the cancelled inventory-review lane; repeat-safe cumulative acceptance proof |
| F4 — stale-revision dependencies | **Fixed** — `5f48bd9` | Dependencies bind to the joined intended row: same merchant/aggregate/kind, published, revision ≥ recorded intent; superseded rows need a real qualifying replacement; pruning preserves retained prerequisites |
| F5 — early no-route exhaustion | **Fixed** — `5f48bd9` | No-route waits no longer consume the 20-attempt send budget; +15 min cadence and exact 48-hour terminal deadline preserved |
| F6 — missing inbox backlog bound | **Fixed** — `5f48bd9` | Atomic per-merchant/relay 1,000 pending cap enforced pre-decrypt inside one transaction (merchant row lock on PostgreSQL, serialized writers on SQLite); additive `m016` index |
| WR-04 — token revocation race (follow-up) | **Fixed** — `eaf7d64` | Presented-token digest/expiry revalidated under the order lock for status, opt-out and claim paths |

Plus **CI-01** (HARD-07): the paired test hang root cause was demonstrated — a
worker cancel landing inside an engine checkout orphaned a non-daemon aiosqlite
worker thread — and fixed by shielding the worker drain; a bounded
process-exit regression covers both file orders.

### Verification evidence

- `make verify-runtime` SQLite: **751 passed, 6 expected PG-only skips**, exit 0.
- `make verify` SQLite: **982 passed, 8 skipped**; PostgreSQL 17.9: **987 passed,
  3 skipped** — both natural exit 0.
- Independent source review of every changed path: **PASSED** for the finite
  scope; review findings CR-01–06, WR-04 and WR-05 all resolved.

### Still open (not release clearance)

- **F1 browser gate:** pinned-host ServiceWorker TLS + null `g.wallet.id`
  websocket errors on the admin order surface — a host-qualification issue,
  reproduced on the baseline; no vendor/security workaround applied.
- **F2 chronology caveat:** the original browser RED was reproduced
  retrospectively after the fix, so test-first chronology evidence is absent
  (recorded, not hidden).
- **Live Plebeian checkout/payment UAT:** remains an operator-authorized
  external gate — listing smoke and FakeWallet evidence are not equivalent.
- **Historical paid-order audit:** a read-only scan of every reachable local
  datastore found **zero actual order records** locally; any deployed/remote
  instance still requires its own operator-authorized audit before release.
- Four-profile Linux CI matrix for the repaired revision was triggered on push
  and is running at the time of this update.
