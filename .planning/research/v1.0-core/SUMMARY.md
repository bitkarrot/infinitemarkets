# Project Research Summary

## Key Findings

### Stack

A standard Python LNbits extension is viable. LNbits supplies the necessary extension lifecycle, migrations, incoming invoices/payment queries/listeners, authentication primitives, configured SMTP, DB boundary, and exchange-rate providers. Direct `nostr-sdk` exposes the needed source-level crypto and targeted publication APIs, but exact wheel/native behavior remains a Phase 0 qualification.

### Table Stakes

The project needs more than event serialization: a canonical commerce domain, atomic reservations, a recoverable invoice saga, durable inbox/outbox/email queues, positive relay ACK evidence, encrypted key/PII storage, explicit host auth/lifecycle enforcement, and restart closure. Release claims remain staged: A web commerce, B Gamma NIP-17, and C catalog import/export.

### Watch Out For

The highest-risk failures are plausible but silent: duplicate invoices after unknown creation, stock release followed by late settlement, stranded partial delivery, SMTP failures marked sent, stale/rounded FX quotes, NIP-17 privacy leaks, and migration double-allocation from old payable invoices. P0-01–P0-14 are designed to make these fail visibly before runtime implementation.

## Implications for Roadmap

1. Make conformance qualification the first phase, with no production extension code.
2. Build Release A as the first complete vertical slice after the gate passes.
3. Add NIP-17 only after domain/payment/recovery behavior is stable.
4. The final v1 phase shipped file-only catalog import/export as hidden drafts; old-order reconciliation and cutover were removed from extension scope.
5. Re-run relevant Phase 0 assertions through each real release implementation.

## Sources

- `docs/technical-specification.md` — normative corrected contract.
- `docs/architecture-proposal.md` — synchronized rationale.
- Standalone Astra review completed against Infinitemarkets `5dc79c5`, Nostr NIPs `a2494f4`, LNbits `e336fe1` (rechecked after source drift), `nostrmarket`, `nostrclient`, and SDK release-source evidence.

## Research Policy

This summary preserves already-delivered audit results. Planning and presentation must not silently re-derive or weaken those findings; new upstream research is appropriate only when a Phase 0 test encounters a changed artifact or an undocumented API.
