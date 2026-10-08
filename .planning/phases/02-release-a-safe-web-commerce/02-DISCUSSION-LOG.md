# Phase 2: Release A — Safe Web Commerce - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-09-20
**Phase:** 2-Release A — Safe Web Commerce
**Areas discussed:** Workflow and process (research depth, UI contract timing, package layout)

---

## Preamble

Phase 2's "what" is almost entirely locked upstream: the normative specification
decides schema, API surface, event construction, state machines, algorithms,
key custody, configuration, limits, and test requirements; the decisions
register (§21, 29 decisions) closes prior design questions; the sketch
findings decide presentation; the roadmap pre-sketches the three plans.
Discussion therefore focused on execution approach, not scope.

---

## Research Depth

### Researcher before planning?

| Option | Description | Selected |
|--------|-------------|----------|
| Run researcher | Map pinned-host extension conventions (routes, Vue/static assets, migrations, lifecycle, CRUD, manifest) before planning | Yes |
| Skip, like Phase 1 | Planner works from CONTEXT + spec + host checkout | |
| Decide later | Defer to end of discussion | |

**User's choice:** Run researcher.
**Notes:** Phase 1's skip succeeded against a test harness; production runtime code against host conventions warrants verified patterns.

## UI Contract Timing

### When is the generated+approved Phase 2 UI contract produced?

| Option | Description | Selected |
|--------|-------------|----------|
| Before planning | Planner references concrete components/themes/states; satisfies roadmap "UI prerequisite" early | Yes |
| After planning | Roadmap minimum — produce between planning and execution | |

**User's choice:** Before planning.
**Notes:** Via the ui-phase step with `.devin/skills/sketch-findings-infinitemarkets/` + `.planning/sketches/` as guideline and the normative spec as authority.

## Package Layout

### Runtime package organization and host mounting

| Option | Description | Selected |
|--------|-------------|----------|
| Standard LNbits layout in-repo | `infinitemarkets/` package (`__init__.py`, views/API, `static/`, migrations), mounted into pinned host for dev/UAT | Yes |
| Discuss it | Explore layout/mount options | |
| Planner discretion | Resolve from host conventions | |

**User's choice:** Standard LNbits layout in-repo.
**Notes:** Mount mechanics (symlink vs extension-path) remain planner/researcher discretion.

---

## Carried Forward (not re-asked)

- All 16 Phase-1 decisions; frozen identifiers; spec decisions register 1–29; sketch findings (Adaptive Blend / Linear Split / Tiered Controls); Dependabot dispositions (JSON-only bodies, APIRouter only, no FileResponse/StaticFiles, no request.url trust).

## Claude's Discretion

- Internal package decomposition, host mount mechanics, runtime test layout beyond §17, migration framework mechanics, CI changes to extend the blocking matrix.

## Deferred Ideas

- NIP-17 intake / kind-10050 / NIP-42 / egress controls → Phase 3 (Release B).
- Historical Phase-2 discussion of NIP-15/NIP-04 interop and cutover → Phase 4 (Release C); superseded by catalog-only draft import and merchant publication, with no old-order workflow.
- NIP-37 drafts, preorders/subscriptions, automated refunds, multi-shop, transport adapters — per spec decisions.
