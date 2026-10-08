# Phase 2: Release A — Safe Web Commerce - Context

**Gathered:** 2026-09-20
**Status:** Ready for planning

<domain>
## Phase Boundary

Ship the production `infinitemarkets` LNbits extension as the first vertical slice: protected merchant identity/wallet configuration, canonical catalog/inventory/shipping management, deterministic Gamma/NIP-99 publication through a durable outbox with per-relay evidence, a local NIP-89 handler with adaptive buyer checkout, the reservation→invoice→settlement saga, merchant order administration, and per-recipient email — all through the real implementation, on the qualified pins, with the Phase 1 harness kept green as the regression gate. No NIP-17 order intake (Release B), no NIP-15/NIP-04 interop or migration (Release C).

</domain>

<decisions>
## Implementation Decisions

### Workflow and Process

- **D-01:** Run a phase researcher before planning. Production runtime code warrants verified host conventions — map the pinned host's extension patterns (route registration, Vue/static asset loading, migrations, lifecycle hooks, CRUD, extension manifest/install mechanics) rather than discovering them during execution. — **Reversibility:** reversible — research output is read-only context.
- **D-02:** Generate and approve the Phase 2 UI contract **before planning** via the ui-phase step, using `.devin/skills/sketch-findings-infinitemarkets/` + `.planning/sketches/` as the guideline and the normative spec as authority. Plans 02-02/02-03 then reference concrete components, themes, and states rather than placeholders. This satisfies the roadmap's "UI prerequisite" ahead of its minimum (before execution). — **Reversibility:** costly — a contract revision after plans are written forces a replan cycle.
- **D-03:** Production source uses the standard LNbits extension layout inside this repository (`infinitemarkets/` package: `__init__.py`, views/API modules, `static/`, `templates/` as needed, migrations), mounted into the pinned host's extension directory for development and UAT. — **Reversibility:** costly — relocating the package after migrations/routes exist touches imports, manifest, and docs.
- **D-04 (owner directive, 2026-09-20):** The admin interface must be intuitive — the reference anti-pattern is the legacy nostrmarket flow, which forced merchants through a separate `nostrclient` extension and felt clunky/complicated. Consequences already implied by the spec and now explicit: no dependency on any other extension (own transport, own settings surface), single self-contained admin area, sensible defaults, minimal setup steps, and every operation reachable without Nostr expertise. Binding on 02-04's B-surface work. — **Reversibility:** cheap — a UX bar, not an architecture change.

### Carried Forward (unchanged — no re-litigation)

- All 16 Phase-1 decisions (D-01..D-16): pins, Python 3.12, Linux x86_64/ARM64 blocking matrix, permanent harness, single-run clean-pass, evidence discipline, SDK fallback ladder, extension-checks-as-defense-in-depth.
- Frozen identifiers (spec decision 25): package `infinitemarkets`, `/infinitemarkets` route prefix, `/infinitemarkets/api/v1`, `infinitemarkets_start`/`_stop` hooks, `INFINITEMARKETS_` env prefix, `infinitemarkets:` payment correlation, `infinitemarkets` AAD prefix, `org.infinitemarkets.protocol` NIP-32 namespace.
- Spec decisions register 1–29 (§21) in full — including 1:1 merchant per user, manual payment_preference, local-only drafts, SQLite single-process / PostgreSQL multi-worker topology, order bearer tokens never in path/query, host-SMTP boolean boundary, and refund-as-attestation.
- UI findings: Adaptive Blend checkout (Editorial/Guided/Compact presets + compact mobile fallback, invariant checkout semantics), Linear Split admin workspace (list/detail + embedded chronology), Tiered Controls themes (Warm Market default / Clean Minimal / High Contrast + bounded Brand Basics + guarded Advanced Tokens), public theme never styles admin or alters checkout semantics, Vue/Quasar-compatible primitives only (no React/Tailwind/shadcn).
- Dependabot disposition recorded in `PINS.md` §5: extension code uses JSON-only request bodies, `APIRouter` only (no `HTTPEndpoint` subclassing), no `FileResponse`/`StaticFiles`, and never derives security decisions or absolute URLs from `request.url`/Host.

### Claude's Discretion

- Exact file/module decomposition inside the `infinitemarkets/` package, mount mechanics into the host (symlink vs extension-path), and local dev-loop tooling — resolved from pinned-host conventions during research/planning.
- Test layout and fixtures for the runtime implementation beyond what §17 and the Phase 1 harness already mandate.
- Migration framework mechanics consistent with LNbits extension conventions.
- CI workflow changes needed to run runtime tests in the existing blocking matrix (the harness suite must stay green — D-05).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Normative Contract (authoritative on conflicts)

- `docs/technical-specification.md` — the contract. Phase 2 reads §2.1 (host boundary), §3 (identifiers/money), §4 (persistence schema), §5 (HTTP API), §6 (Nostr event construction: kinds 0/30402/30405/30406/31989/31990 + drafts/deletion §6.7), §7 (state machines), §8.1–8.4/8.6–8.8 (order intake, invoice saga, settlement, late payment, outbox publish, reconciliation, email worker), §9.1/9.5 (transport interface, relay URL/egress security), §10 (background tasks), §11 (key custody/tokens), §12 (configuration), §14–§18 (idempotency/transactions, limits, observability, test requirements, release gates), §19 (threat model), §21 (decisions register).
- `docs/architecture-proposal.md` §§6–8 — architecture boundaries and background-work rationale (spec wins conflicts).

### Qualification Evidence and Pins

- `PINS.md` — approved pins, platform matrix, qualification results, Dependabot disposition, D-11 approval record.
- `evidence/manifest.json` + `evidence/REPORT.md` — canonical qualification evidence (CI run 35535526249).
- `harness/` + `tests/qualification/` — permanent regression suite; Phase 2 must keep it green (D-05) and reuse its models (schema DDL, state machines, tx/fencing adapters, saga/recovery harness, email boundary, relay fixtures) as the executable reference for the real implementation.

### UI Findings (binding for presentation layer)

- `.devin/skills/sketch-findings-infinitemarkets/SKILL.md` + `references/buyer-experience.md`, `references/merchant-operations.md`, `references/theme-system.md` — validated UI decisions and constraints.
- `.planning/sketches/` — raw sketch sources: `001-buyer-checkout/`, `002-order-operations/`, `003-theme-controls/`, `MANIFEST.md`, `UI-RESEARCH.md`, `WRAP-UP-SUMMARY.md`, `themes/` presets.
- `.devin/skills/sketch-findings-infinitemarkets/sources/themes/` — `default.css` (Warm Market), `clean-minimal.css`, `high-contrast.css` preset sources.

### Project Scope

- `.planning/ROADMAP.md` Phase 2 — goal, 16 requirements (MERC-01, CAT-01/02, PUB-01/02, WEB-01/02, PAY-01/02, INV-01, ORD-01, NOTF-01, SEC-01, UI-01/02/03), success criteria, plan skeleton.
- `.planning/REQUIREMENTS.md` — requirement definitions and Definition of Done.
- `.planning/research/` — STACK/ARCHITECTURE/PITFALLS (silent-failure modes the runtime must not reintroduce).

### Host Reference

- `.cache/lnbits/` @ `e336fe14b841` — pinned host source; extension conventions, `db.py` boundary, `task_manager` APIs, invoice services, extension examples to mirror.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- `harness/` package — Phase 1's executable models ARE the reference implementations: `harness/schema.py` (§14-conformant DDL), `harness/state.py`/`tx.py` (transaction adapter, fencing, last-unit concurrency), `harness/saga.py`/`inbox_outbox.py` (cancellation saga, durable publication evidence, recovery), `harness/email_queue.py`/`smtp_boundary.py` (email model), `harness/relay_fixtures`/`sdk.py` (deterministic relay/SDK patterns), `harness/registry.py` (contract registry the closure gate checks — must stay in parity with the real implementation).
- `Makefile`/`pyproject.toml`/`uv.lock` — canonical verify command and locked env to extend (runtime deps land in the same lock; `package = false` flips when the real package lands — planner decides packaging mechanics).
- `.github/workflows/qualification.yml` — blocking matrix to extend for runtime tests.
- LNbits host conventions (`.cache/lnbits/`): `FakeWallet` test backend, extension examples, `uv`/pytest/Make developer experience.

### Established Patterns

- Host serializes connections per `Database` object; concurrent work uses separate handles (per `QualWorker` model). PG queue claims: lock-select→update→fetch in one tx (SQLAlchemy 1.4+asyncpg limitation); idempotent inserts via `ON CONFLICT DO NOTHING`; SQLite `BEGIN IMMEDIATE`.
- Payment correlation `infinitemarkets:` external_id, payment projection separate from settlement truth; relay ACKs are durable append-only evidence, never payment truth.
- Durable publication evidence split from fenced outcome write (§8.6 crash point model).
- No raw secrets in logs; request redaction (X-Order-Token pattern); single-run clean-pass test policy.

### Integration Points

- LNbits extension loader + `infinitemarkets_start`/`infinitemarkets_stop` lifecycle hooks.
- Host `db.py` extension boundary; `task_manager` invoice listener/owned tasks; `create_invoice` (keyword-only); host exchange-rate provider (FX adapter boundary); host SMTP `send_email` (boolean boundary).
- `nostr-sdk` 0.44.8 direct transport: `gift_wrap`/`nip44_*`, `send_event_to`/`send_private_msg_to`/`send_msg_to` targeted sends, `SendEventOutput` per-relay output, `Nip19Coordinate` naddr parsing, `LocalRelay`/`WebSocketAdapterWrapper` for tests.

</code_context>

<specifics>
## Specific Ideas

- The Phase 1 harness is not scaffolding to throw away — it is the executable reference the runtime must stay faithful to and the permanent regression gate (D-05). The P0-14 contract-closure gate's registry parity should keep holding as real code lands.
- UI presentation must trace to the sketch findings — `.planning/sketches/` is the guideline the user named explicitly; the ui-phase contract is generated and approved before planning.
- Dev-loop should feel like the harness: one canonical command, named subsets, real evidence.

</specifics>

<deferred>
## Deferred Ideas

- NIP-17 order intake, kind-10050 inbox discovery, NIP-42, egress controls — Release B (Phase 3).
- Historical Phase-2 forecast of NIP-15/NIP-04 compatibility and cutover for Release C — superseded: current Phase 4 imports CSV/JSON catalogs as hidden drafts and publishes only after merchant review; no old-order gate.
- NIP-37 drafts sync, preorders/subscriptions purchasing, automated refunds, multi-shop, transport adapters (`nostrclient`/`nostrrelay`) — deferred per spec decisions 13/14/5/26.
- Windows support — out of the platform claim (Dependabot disposition).

</deferred>

---

*Phase: 2-Release A — Safe Web Commerce*
*Context gathered: 2026-09-20*

## Owner directive — relay endpoint configurability (2026-09-22)

Merchant-configurable endpoint sets with starter defaults:
- Publication/outbox relays: `relay_configs` rows, `direction=public|both`, editable; seed starter defaults when a merchant first publishes with no configured relays.
- Blossom media endpoints: merchant settings (`settings` table key `blossom_servers`), `https://`-only, same SSRF validation posture as relays; starter defaults exposed for the UI. Actual media-upload plumbing is a later scope — 02-02 ships config + defaults only.
- Inbox relays: `direction=inbox` rows (schema exists; consumed in Release B).
- Spec delta: blossom endpoints and starter relay defaults are beyond the spec's §4.11/§12 literals — record in the 02-02 summary.
- Starter relay correction (2026-09-22): `relay.nostr.band` is defunct — use `relay.nostr.net` in the default relay set.
