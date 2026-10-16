# Architecture Research

## Evidence Basis

This document condenses the corrected normative architecture. `docs/technical-specification.md` wins on every detail.

## Boundaries

1. **LNbits host** — FastAPI mounting, authentication primitives, extension DB lifecycle, incoming invoice creation/query/listener, configured SMTP, and exchange-rate providers.
2. **Domain core** — merchant, catalog, inventory, order, reservation, payment projection, fulfillment, and legal transitions. It imports no FastAPI, LNbits, SQL, SDK, or UI code.
3. **Application services** — catalog publication, checkout, invoice saga, settlement, inbox dispatch, outbox delivery, email, reconciliation, and migration orchestration.
4. **Protocol adapters** — Gamma/NIP-99/NIP-89, NIP-17/NIP-44/NIP-59, retained NIP-15 projections, and file-based catalog parsers.
5. **Infrastructure adapters** — LNbits payments/auth/SMTP/FX, SQL repositories/transactions, key store, and direct relay transport.
6. **HTTP/UI** — merchant administration and public catalog/checkout/status routes.

## Authoritative Data Flow

- Merchant mutation commits canonical state and durable publication intent in one extension-DB transaction.
- Outbox workers build/sign current events, target explicit relays, and persist positive/negative/timeout results.
- Checkout validates catalog/shipping/FX, reserves stock, persists a creating payment projection, then calls LNbits outside the DB transaction.
- LNbits payment records determine settlement; callbacks accelerate processing while periodic reconciliation closes gaps.
- Nostr ingress verifies/bounds outer data, durably admits ciphertext, unwraps through the key store, validates rumor identity, and dispatches idempotent commands.
- Email is a per-recipient durable queue; host boolean success is the only sent signal.

## Reliability Model

- Durable database rows, not memory queues, are recovery truth.
- Row claims carry deadlines and monotonically increasing fencing tokens.
- Partial relay publication retries only targets lacking positive OK evidence.
- Payment creation uncertainty is correlated by deterministic core external id and survives order cancellation.
- Every legal state change and exception resolution is auditable and transactional.

## Build Order

1. Phase 0 proves host/SDK/schema/state contracts with isolated probes and fixtures.
2. Release A builds the first end-to-end web vertical slice and hardens it.
3. Release B adds encrypted Gamma transport over the stable domain/payment core.
4. Release C adds file-only product catalog import/export; the merchant reviews hidden drafts and explicitly publishes products. Old orders are outside the import.

## Adapter Policy

Direct qualified `nostr-sdk` is the baseline. `nostrclient` and `nostrrelay` can be added only behind `NostrTransport` after identical target-routing, authorization, subscription, and positive-ACK tests; no domain service may depend on a specific relay adapter.
