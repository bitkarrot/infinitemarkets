# Phase 5 review and revision ledger

## Scope and review provenance

Independent checker `84030b6d` returned three blockers and three warnings. This revision treats the required properties as binding; implementation hints are optional. No new agent was launched. Six plans / six sequential waves / 18 tasks remain; only05-01→05-02→05-03 (F1→F3→F2) are authorized for later synthetic execution, with mandatory pause. This revision changes planning files only. Parent owns reviewed local commits; executors do not commit, push or deploy.

Selected policy: “prevent new failures and block unsafe legacy delivery, but do not automatically clear existing paid-order holds. Record an operator-review gate for historical records.” This is not approval to connect to existing data now.05-CONTEXT.md:97–104 is authoritative.

## Revision disposition

| Review item | Revision / exact dependency | Status |
|---|---|---|
|BLOCKER1 — native failure predicates|Replaced unrecognized baseline tags in all six plans. Every29 automated blocks now pairs with native fails_when, specific assertion/nonzero/natural-exit signal, separate expected_red and positive_retention. Make/lint/old-green supporting checks are not fabricated RED.|Authored; native static probe0 blockers/0 warnings. No command in the plans executed.|
|BLOCKER2 — settled legacy/crash bypass|05-01 declares read-only inventory_accounted and fulfillment_authorized and wires token/history/email, merchant processing/completed/shipping, owner detail/UI. Exact all-item consumed map OR credible accepted allocation plus declared shortfall; absent/partial/malformed proof fails closed even if settled/confirmed/no exception. Permanent synthetic negatives on every surface, unchanged durable snapshots and healthy consumed/explicit accepted positives.05-02 reuses normalized map and records bounded cumulative per-item proof on existing detail_json only during NEW legitimate accept;05-03 reruns all surface regressions and actual new-accept integration. Physical approved backorders remain fulfillable, digital oversold blocked.|Planned, NOT implemented or independently verified. No legacy mutation/sweep/backfill.|
|BLOCKER3 — audit timing and authority|First-class HISTORICAL-PAID-ORDER-AUDIT gate at05-03 financial pause, carried to05-06. Approval/evidence/disposition recorded separately from synthetic local verification. No audit/credentials/access command; no human checkpoint blocks already-authorized synthetic work.|OPEN / NOT AUTHORIZED / NOT PERFORMED; actual-record evidence NONE, disposition NOT DONE; production exposure/real-record disposition/release BLOCKED until separately approved actual read-only audit/review.|
|WARNING1 — executable cwd|Browser automated commands encode cd tests/e2e; matrix encodes cd tests/conformance. Each runs in a fresh root shell to prevent cwd leakage.|All four cwd commands grounded by native static path probe.|
|WARNING2 — suite process exit|05-05-03 verification explicitly includes make verify-runtime AND make verify AFTER demonstrated lifecycle repair, in addition to both file orders and bounded child regression. Natural exit0/nonempty collection required; make SUBSET_OK empty result is failure; timeout/kill never success.|Authored; CI-01 cause still UNKNOWN; execution still separately unauthorized.|
|WARNING3 — file budget|05-01 documents11 existing authority/fixture/surface paths;05-06 documents11 existing evidence/assurance registers. No new plan, broad refactor, router, schema or qualification runtime repair.|Bounded justification recorded in both plans.|
|Parent — structured prohibitions|Used installed single projectProhibitions serializer for all19 flat statement/status:unresolved/verification:judgment markers. No check_* descriptor or dismissal fabricated; native disposition is unverified/flagged true. Independent source/code/security review later assesses binding properties without claiming wired-machine evidence.|All19 remain visibly flagged-unverified.|
|Parent — role-scoped commits/UI adapter|Replaced global no-commit wording with executor-owned prohibition and explicit authorized parent-reviewed local commits, retaining no push/deploy. Used check ui.plan-gate, not query; no global tool/security changes.|Authored; static UI gate result recorded below.|

## Actual source grounding

- `infinitemarkets/services/orders.py:140–170`: delivery currently trusts state/exception/oversold, not durable consumption. `orders.py:807–838,841+`: merchant commands need the same proof. `orders.py:641–684` owns scoped detail; shared boolean avoids a second frontend policy.
- `orders.py:176–245`: existing transition detail_json can carry bounded accounting provenance. `infinitemarkets/services/settlement.py:689–787`: existing accept updates allocation/backorders and accepted resolution but does not persist a complete attributable allocation map; reason-only/flag-only history is not sufficient proof. New-operation evidence is planned, not a historical repair.
- Installed native predicate grammar: `/Users/bk/.claude/gsd-core/bin/lib/verify-command-grounding.cjs:124–253` pairs each fails_when with preceding automated in the same task.
- `/Users/bk/.claude/gsd-core/references/specless-probe-fallback.md:150–169` requires descriptor-less flagged-unverified fallback. The requested bin/lib/spec.cjs does not exist in this installation; the actual single serializer is `/Users/bk/.claude/gsd-core/bin/lib/probe-core.cjs:292–339`, with fail-closed disposition at358–375. Read and invoked that owner; no global tool changes.

## Static checks performed

All commands run from `/Users/bk/github/infinitemarkets` using installed tools, without dependencies or runtime execution:

- `node /Users/bk/.claude/gsd-core/bin/gsd-tools.cjs query frontmatter.validate <each05-01–06-PLAN.md> --schema plan`: all six valid.
- `node /Users/bk/.claude/gsd-core/bin/gsd-tools.cjs verify plan-structure <each05-01–06-PLAN.md>`: all six valid, three tasks each, no errors/warnings.
- `node /Users/bk/.claude/gsd-core/bin/gsd-tools.cjs check verify-failure-directions 5 --raw`: status ok,29 commands,0 blockers,0 warnings, readError null.
- `node /Users/bk/.claude/gsd-core/bin/gsd-tools.cjs check verify-command-paths 5 --raw`: status ok,0 blockers/warnings; three browser and one conformance cwd grounded. Other commands are recognizer not_applicable, not runtime-validated.
- `node /Users/bk/.claude/gsd-core/bin/gsd-tools.cjs check ui.plan-gate 5 --raw`: frontend=false, hasUiSpec=true, block=false; uiSpecPath points to the actual phase05-UI-SPEC.md. This static classification does not remove authored UI requirements or establish browser success.
- Invoked projectProhibitions and dispositionForProhibition on the19 descriptor-less items: all projected markers remain unresolved/judgment; all dispositions unverified/flagged true.
- `git diff --check`: exit0. Scoped scan found no baseline tags, invented check_* scalars, global no-commit wording or trailing whitespace; git status lists planning artifacts only (05-CONTEXT/05-RESEARCH are inherited parent inputs, not edited in this revision).
- Final repeat: all six frontmatter/structure checks valid;29 native predicates still ok. A reporting pipe initially assumed frontmatter --raw returned JSON, but that command emits scalar `valid`; removed --raw for those JSON validation reports and reran all six successfully. No global tool changes or gate bypass.

No runtime tests, make targets, browser/conformance runs, existing DB access/audit, live operations, config/vendor/runtime edits or commits were performed. No implementation/security/release success claimed. Parent should independently recheck revised plans, preserve flagged source properties, own reviewed local commits and report the still-open real-record/live gates.

## Parent independent recheck and execution adapter

Independent checker84030b6d re-read revisions and returned VERIFICATION PASSED
for planning only: all HARD01–08/reopened requirements covered, durable read-only
accounting guards and early real-record audit gate explicit, permissions/budgets
resolved. Parent reran native command-path and failure-direction probes:29 each,
zero blockers/warnings; UI static gate block=false; GSD health healthy with no
errors/warnings. There are still zero executed plans and no runtime clearance.

Existing8072742 is a docs-viewer navigation commit, not parent Phase5 work;
financial service/test sources remain unchanged from the reviewed baseline.
Native worktree.base-check observed HEAD80727426 differing from origin/HEAD1ae80f80
and required sequential main-tree execution. The documented auto-degrade to
none isolation is used for this run; no runtime/project/security config is altered,
no harness-native worktree flag is falsely claimed, no parallel writers dispatch.
Parent retains git ownership and will commit only reviewed local changes.
