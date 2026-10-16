# Stack Research

## Evidence Basis

This is a synthesis of the completed pinned-source Astra audit and corrected contract, not a new upstream derivation. The normative source is `docs/technical-specification.md`.

## Required Stack

| Layer | Selection | Qualification |
|---|---|---|
| Host | LNbits `v1.6.2-rc1` / `e336fe1` | Phase 0 verifies lifecycle, migrations, invoice metadata/query/listener behavior, SMTP, auth, audit, DB, and FX boundaries |
| Language | Python supported by the pinned host (`>=3.10,<3.13`) | Exact CI matrix frozen in `PINS.md` |
| Web/API | LNbits FastAPI extension router and host auth dependencies | infinitemarkets adds merchant scoping, bearer/cookie-origin/CSRF enforcement, and audit redaction predicates |
| Persistence | LNbits extension DB boundary with raw SQLAlchemy transaction adapter | Single-process SQLite and qualified PostgreSQL; no auto-committing host helpers inside domain transactions |
| Nostr | Direct Python `nostr-sdk`; host-resolved `0.44.8` is the candidate | Wheel/native provenance plus security, FFI, event-loop, NIP-44/NIP-59, targeted routing, and positive-ACK tests required |
| Cryptography at rest | Host-approved `pycryptodomex` AES-256-GCM plus HMAC-SHA256 equality indexes | Versioned operator keyring, field/record AAD, rotation and backup/restore drill |
| Payments | LNbits `create_invoice`, payment queries, and invoice listener | Deterministic `infinitemarkets:<order.id>` correlation; reconciliation remains authoritative after callback gaps |
| Notifications | Host `send_email(...) -> bool` | Only `True` means sent; failures are unclassified and bounded |
| Relay testing | Deterministic local accepting/rejecting/silent relays | Optional `wss://nostr.net` ephemeral smoke event is non-authoritative |
| Reference code | `nostrmarket` and `nostrclient` | Reuse patterns only; do not inherit unsafe domain/key/state assumptions or current fan-out limitations |

## Explicit Non-Selections

- WASM runtime for the commerce authority.
- Custom NIP-44/NIP-59 cryptography.
- Current `nostrclient` fan-out as NIP-17 transport.
- `nostrrelay` without an inspected API and contract tests.
- Host `fiat_amount_as_satoshis` for domain conversion.
- Multi-process SQLite or CockroachDB for v1.

## Confidence

- Python/LNbits extension viability: high, supported by pinned host source.
- SDK source API availability: high at source level; runtime artifact behavior remains Phase 0 evidence.
- Production relay/privacy behavior: gated on deployment and external-client tests.
