# Pitfall Research

## Evidence Basis

These pitfalls are the corrected outcomes of the standalone Astra audit. They are requirements and tests, not speculative implementation advice.

| Pitfall | Warning Sign | Prevention | Phase |
|---|---|---|---|
| Unqualified SDK binary | Version string treated as security proof | Freeze wheel hashes/native provenance and run invalid-event, AUTH, NIP-44, FFI, and ACK probes | 1 |
| Cancellation/invoice race | Invoice attachment filters only `invoice_pending` | Persist creating payment projection first; reconcile by external id independent of order state | 1 |
| Stranded partial publication | Worker selects only `pending` | Make `partially_published` retryable; retain positive target evidence and fencing | 1 |
| Invented SMTP categories | Code distinguishes transient/5xx from host boolean | Treat `False`/exception as unclassified bounded retry; only `True` is sent | 1 |
| Irrecoverable magic link | Only a token hash survives delayed email | Keep a valid AEAD-encrypted copy for notification rendering; erase on expiry/revocation | 1 |
| Recipient dedupe collision | One queue row per event regardless of recipient | Include `recipient_hash` in uniqueness and create one row per address | 1 |
| Broken NIP-89 link | Advertised naddr route is undeclared or fetches relay hints | Declare local naddr handler; validate kind/pubkey/d and ignore hints | 1/2 |
| False NIP-15 compatibility | Wrong `specs`, missing `type`/`shipping_id`, opaque addresses accepted | Literal fixtures; reject unsupported physical orders before reservation | 1/4 |
| Old/new store inventory overlap | Imported stock might also be for sale on an old store | Merchant manages old-store intake externally before publishing drafts; extension provides no cross-store reconciliation | 4 |
| Durable-state gaps | Cursors, quota scope, leases, or validated inbox checkpoints are implicit | Map every checkpoint to schema and restart tests | 1 |
| Host behavior assumed | CORS, shutdown, audit redaction, or callback durability treated as guaranteed | Enforce route/task behavior in extension and qualify deployment predicates | 1/2 |
| FX drift/rounding | Cached float helper timestamped as fresh or truncated with `int` | Uncached provider call, explicit float boundary, Decimal mean/units/ceiling and provenance | 1/2 |
| Release/document drift | Release-C tests block A or rationale overrides contract | Normative precedence, A/B/C test mapping, and identifier closure gate | 1 |
| Relay SSRF/privacy | Discovered relay URL is connected after DNS-only checks | Canonical URL validation plus production egress control; no NIP-17 fallback | 3 |
| Spend-sandbox assumption | Native extension policy described as enforced host isolation | Forbid outgoing APIs/credentials by code review and tests; state residual host privilege | 1/2 |

## Stop Conditions

- Do not start Release A if any P0-01–P0-14 criterion lacks evidence.
- Do not claim Release B without deployed egress control and independent Gamma-client proof.
- Do not claim Release C until catalog-only import/export, hidden-draft review and publication are verified; do not imply old-store invoices or inventory are checked.
