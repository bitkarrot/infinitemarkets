---
phase: 02-release-a-safe-web-commerce
plan: "03"
requirements-completed: [WEB-02, PAY-01, PAY-02, INV-01, ORD-01, NOTF-01, SEC-01]
metadata_reconstructed: 2026-10-11
acceptance_scope: historical-delivery
---

**Historical execution record:** metadata reconstructed from the original plan,
summary and phase verification on 2026-10-11. Current Phase 2 acceptance is
reopened; this header does not close F1–F4 or create a new test pass.

# 02-03 Summary — orders, checkout saga, settlement, email queue

## Tasks completed

1. **m002 schema + fx + orders domain + §8.1/§8.2 checkout saga + §5.4 public checkout API**
2. **Settlement listener + leased workers + email worker + readiness gate**
3. **§5.3 admin order API + end-to-end + public contract tests**

## Implementation

- `migrations/m002_orders.py` — literal §4.7–4.9/4.12/4.15/4.18/4.19 tables:
  `orders`, `order_items`, `order_events`, `inventory_reservations`,
  `payments`, `order_fx_quotes`, `idempotency_records`, `email_queue`,
  `task_leases`, `rate_limit_buckets` (schema-only `inbox_events`/
  `order_messages` reserved for Release B).
- `services/fx.py` — `btc_rates` adapter, float→Decimal once at the
  boundary, `order_fx_quotes` provenance snapshot per §3.4, fiat totals
  computed server-side only (client amounts never trusted).
- `services/orders.py` — §7.1 `transition_order` (literal transition
  table shared with `harness/state.py`), CAS + `order_events` audit in
  the caller's tx, §7.2/§7.3 shipping/reservation machines, shared
  §8.8 `enqueue_email_intents` (per-recipient dedupe), admin helpers.
- `services/checkout.py` — §8.1 intake (idempotency claim BEFORE intake,
  encrypted replay responses, crash-lease resume) and §8.2 saga
  (conditional stock updates sorted by product id, held reservations,
  payment projection BEFORE the wallet call, invoice attach in a second
  tx, `creation_unknown` never retries the external call).
- `services/settlement.py` — self-filtered invoice listener
  (extension tag + `infinitemarkets:` external id), §8.3 verification
  (amount/wallet/hash/expiry correlation — mismatches quarantine with
  bounded reasons, never confirm), idempotent `confirm_settlement`,
  §8.4 expiry + late-settlement exception, §8.7 reconcile (resume
  `received`, attach `creating`/`creation_unknown`, confirm settled,
  expire failed), merchant exception resolution
  (accept | refund | confirm-refund — refund is attestation-only, the
  response says infinitemarkets cannot verify outgoing payments), §11.3
  retention pruner.
- `services/email.py` — §8.8 worker: claim-token CAS, suppression
  taxonomy (`host-email-unconfigured`, `email-disabled`,
  `merchant-inactive`, `event-disabled`, `consent-revoked`), per-
  recipient hourly buckets on hashed scopes, SMTP call outside the
  transaction, render-at-send-time subjects carrying display name +
  event only, magic links rendered only while the token AEAD copy lives.
- `services/tasks.py` — registers the invoice listener + outbox
  publisher + relay manager + email sender + leased
  reservation_expiry/reconciliation/retention_pruner; §4.16 leases with
  strictly-increasing fencing tokens.
- `services/readiness.py` — checkout fails closed (503) until the first
  reconcile pass completes.
- `services/metrics.py` — §16 gauges: outbox depth, order health
  (open/stuck/held/exceptions), email depth + outcome counters.
- `views_public_api.py` — `POST /public/checkout` (400 on
  missing/malformed Idempotency-Key, both §15 rate windows before the
  claim), `GET /public/order-status` (token in `X-Order-Token` ONLY,
  exact §5.4 field-set response, bolt11 only while `awaiting_payment`),
  `POST /public/order-email-opt-out` (clears token AEAD copy, suppresses
  queued customer rows). New `public_boundary` maps `ProblemError`
  WITHOUT admin cookie/CSRF enforcement and stamps the §5.4 protective
  headers on error responses too.
- `views_api.py` — §5.3 admin routes: list (`state`/`protocol`/`q` +
  `needs_attention` UI filter), detail (decrypted contact/address for
  owner only), status, shipping, cancel, resolve-exception,
  public-token reissue (old token revoked immediately), events
  chronology.
- `public_product.html` + `public_storefront.js` — optional email field,
  ≥128-bit browser idempotency key, token kept in memory (fragment
  stripped via `history.replaceState`), 5s status polling, invoice +
  expiry rendering, opt-out link, inline errors.

## Fixes found by tests

- `public_boundary` — `problem_boundary` applied admin cookie/CSRF
  enforcement to anonymous public POSTs (403 on checkout); split into a
  public-only boundary that also preserves protective headers on
  problem responses.
- `_maybe_activate_merchant` in `outbox.py` — nothing flipped
  `publication_pending -> active` on successful profile publication;
  checkout gates on `active`. Fixed at both publish-success paths.
- `validate_idempotency_key` — missing key returned 422; §5.4 requires
  400 (`idempotency-key-required`).
- `confirm_settlement` CAS now accepts `expired` projections so late
  settlements record as exceptions instead of failing to persist.
- `send_test_notification` — now enqueues through the durable §8.8 path
  (orderless rows bind recipient decryption to `merchant_id`) instead
  of calling host SMTP directly; `GET /notifications` returns the real
  `queue` array (W-NEW-1 pin).

## Spec deltas (recorded per plan)

- **`public_boundary`** — public routes need problem+json WITHOUT admin
  mutation security; split decorator (recorded, W-NEW-1 precedent).
- **`needs_attention` + `q` on `GET /orders`** — the UI-SPEC filter set
  adds "Needs attention" (`payment_exception OR oversold`) and an
  order-id prefix search over the literal §5.3 `?state=&protocol=`
  contract.
- **Admin order routes are merchant-scoped** —
  `/merchants/{merchant_id}/orders/...` carries the merchant id
  explicitly (unlike §5.2's implicit single-merchant resolution).

## Verification

```
uv run ruff check .                    → all checks passed
uv run pytest tests/runtime -q         → 157 passed
GAMMA_QUAL_EVIDENCE=1 uv run pytest -q → 377 passed, 1 skipped
```

Runtime coverage: `test_checkout` (8 — intake validation, idempotent
replay/conflict/crash-resume, oversell, FX), `test_order_saga` (10 —
settle-once, foreign-payment rejection, late-settlement exception +
accept resolution, buyer cancel, creation_unknown recovery, received-
order resume, kill-before-callback reconcile, amount/wallet quarantine,
lease fencing), `test_status_api` (6 — token contract, restricted field
set, opt-out, readiness gate), `test_email_queue` (7 — dedupe, claim
fencing, suppression taxonomy, send classification, consent revocation,
orderless test send, PII-free subjects), `test_order_admin` (8 —
scoping, transition matrix, cancel-once, refund attestation, token
reissue, owner-only PII, event chronology, admin idempotency keys),
`test_public_contract` (6 — route table, exact field allowlist,
indistinguishable token failures, protective headers, rate windows,
end-to-end journey with FakeWallet settlement).

Not verified: PostgreSQL `SKIP LOCKED` variants (CI exercises them);
real external relay delivery (out of scope — `INFINITEMARKETS_RELAY_IO=off`).
