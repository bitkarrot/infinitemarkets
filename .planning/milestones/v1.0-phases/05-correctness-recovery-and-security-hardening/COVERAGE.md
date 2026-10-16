# Phase 5 multi-source planning coverage

Planning coverage means executable tasks exist, not implementation/testing/security closure. Every HARD01–08 is retained. No numbered D-NN IDs are present in CONTEXT; named locked decisions below are traced verbatim by topic.

## Plans, waves and authorization

| Plan | Wave | Depends on | Scope | Current execution authority |
|---|---:|---|---|---|
|05-01|1|—|F1 payment-backed merchant/cancellation/delivery|Approved financial tranche|
|05-02|2|05-01|F3 complete accounting/expiry/manual accept|Approved financial tranche|
|05-03|3|05-02|F2 original-invoice active recovery/hold preservation/browser|Approved; STOP afterward|
|05-04|4|05-03|F4 revision/pruning + F5 route-wait budget|New approval required|
|05-05|5|05-04|F6 scoped admission + CI-01 diagnosed lifecycle|New approval required|
|05-06|6|05-05|HARD08 qualification/security/operator/live gates|New approval and separate operator/live gates|

Financial order is intentionally F1→F3→F2. Later dependencies also serialize shared tests/outbox and final evidence; all waves have one plan, no shared-file parallel writes. Config auto_advance is not authorization. Parent owns commits and any later approved push/CI coordination; no planning agent launches more agents.

## Multi-source audit

| SOURCE | ID/topic | Contract | Plan/tasks | Status |
|---|---|---|---|---|
|GOAL|ROADMAP05 goal|Restore payment/inventory/publication/private-message invariants with permanent coverage and honest release evidence|05-01–06|COVERED|
|REQ|HARD-01|Payment-backed merchant status/delivery, atomic cancellation|05-01-01–03|COVERED|
|REQ|HARD-02|Original recovered invoice usable/fulfillable, independent holds preserved|05-03-01–03|COVERED|
|REQ|HARD-03|Complete accounting or explicit exception; expiry/accept safety|05-02-01–03|COVERED|
|REQ|HARD-04|Intended revision or valid replacement, not historical publication|05-04-01–02|COVERED|
|REQ|HARD-05|48h no-route recovery separate from20 send failures|05-04-03|COVERED|
|REQ|HARD-06|Atomic1000pending per merchant/relay|05-05-01–02|COVERED|
|REQ|HARD-07|Both DB/install orders and normal suite naturally exit0|05-05-03,05-06-01|COVERED|
|REQ|HARD-08|Fresh profile/browser/conformance/security/operator/live evidence|05-06-01–03|COVERED|
|REQ|PAY-02,INV-01,ORD-01,SEC-01,GAM-02|F1 original acceptance plus final reconciliation|05-01,05-06|COVERED|
|REQ|PAY-02,INV-01,GAM-02|F3 original financial accounting|05-02,05-06|COVERED|
|REQ|PAY-01,PAY-02,GAM-02|F2 original correlation/recovery|05-03,05-06|COVERED|
|REQ|CAT-02,PUB-01|F4 original deletion/publication ordering|05-04,05-06|COVERED|
|REQ|GAM-03,GAM-04|F5 original private-delivery recovery|05-04,05-06|COVERED|
|REQ|GAM-04,GAM-05|F6 original overload/interop assurance|05-05,05-06|COVERED|
|RESEARCH|F1 actor authority|Unchanged ORDER_TRANSITIONS; paid fulfillment, shipping authority; no oversold physical blanket ban|05-01-01–03|COVERED|
|RESEARCH|F1 shared cancellation|No nested tx, existing status body, paid reason via /cancel, owner/404/422/CSRF retained|05-01-01–02|COVERED|
|RESEARCH|F1 delivery consumers|Correlated settled projection AND complete durable consumed/credible accepted proof for token/history/email and processing/completed/shipping; settled/no-exception absent/partial proof fails closed without mutation|05-01-01–03,05-02-03 retention,05-03-03 combined check|COVERED|
|RESEARCH|F3 map/counters|Every item vs held quantities, stock coherence, safe incomplete settlement cancellation|05-02-01|COVERED|
|RESEARCH|F3 expiry|Current locked order/deadlines, pending allocation cancelled with correlation, no terminal invoice delivery|05-02-02|COVERED|
|RESEARCH|F3 acceptance|Own residual holds, consumed/prior accepted/backorder quantities, repeated reaccept, other buyers, finite/unlimited, variant-parent locks/publication|05-02-03|COVERED|
|RESEARCH|F2 uncertainty preservation|Order-first _mark_unknown, stronger AND reasonless holds/manual refunds survive|05-03-02|COVERED|
|RESEARCH|F2 active recovery|New validated full live attachment / newly accounted settlement clears only pure creation uncertainty; QR usable before paying;NULL closed reason/resolution|05-03-01,03|COVERED|
|RESEARCH|F2 historical boundary|No settled hold clearing/no-op consistency mutation; first-class audit OPEN at financial pause, production exposure/disposition/release blocked pending actual separately authorized read-only audit|05-03-02–03 early gate,05-06-03 carried gate|COVERED|
|RESEARCH|F4 corrected schema|Existing FK aggregate_revision, same merchant/aggregate/kind valid revision+ proof; pruning retains prerequisites|05-04-01–02|COVERED|
|RESEARCH|F5 existing mechanism|bump_attempts=False,900s refresh/172800s deadline, real failure20/fencing/copy ACK|05-04-03|COVERED|
|RESEARCH|F6 corrected lifecycle|received+validated pending,processed terminal,serialized count+insert,one additive index|05-05-01–02|COVERED|
|RESEARCH|CI-01 unknown|Diagnostic both orders first,causal cleanup,permanent bounded child exit regression|05-05-03|COVERED|
|RESEARCH|Validation architecture|Permanent RED assertion evidence,isolated DBs,clean exits,focused not full evidence|All plans,05-PATTERNS,05-VALIDATION|COVERED|
|RESEARCH|Whole-phase evidence|Local PG17≠CI PG18,all four existing Linux profiles,browser/conformance/ASVS/live/operator|05-06|COVERED|
|CONTEXT|Permanent F1–F6 regressions|Retain failing-then-passing runtime tests,not removed review probes|05-01–05|COVERED|
|CONTEXT|CI-01 no masking|No forced exit/skips/killed-success/weakened controls|05-05-03,05-06|COVERED|
|CONTEXT|Supported profiles|SQLite single-process/Postgres;preserve four Linux jobs|All tests,05-06-01|COVERED|
|CONTEXT|Dropped/deferred scope|No legacy cutover/live NIP15/NIP04,optional stock/shipping/import,custody,outgoing/automatic refund,S1–S4/account expansion|All plan prohibitions +05-PATTERNS|EXCLUDED by explicit decision|
|CONTEXT|Live Plebeian gate|Required pending until separately approved actual checkout/payment;no listing/shim substitute|05-06-03|COVERED|
|CONTEXT|ASVS1/high blocking|Keep enforcement,severity and current clearance distinction|Every threat_model,05-06-02|COVERED|
|CONTEXT|Independent contexts|Parent independent checking,no false self-review independence|05-03-03,05-06-02|COVERED|
|CONTEXT|Full plan then limited execute|All HARD01–08 planned;only F1→F3→F2 now,mandatory pause|Every authorization field,05-03-03|COVERED|
|CONTEXT|Historical audit first|Current authority only synthetic work and parent-reviewed local commits, no existing DB access; audit OPEN/NOT AUTHORIZED/NOT PERFORMED at05-03 pause and05-06; no real exposure/disposition/release before actual audit, synthetic tests cannot satisfy it|05-01–03,05-06-03,05-VALIDATION early gate|COVERED|
|CONTEXT|Incomplete verified settlement|Settled payment,cancel/release own holds,bounded inventory reason,existing accept/refund,no false expiry/reopen|05-02-01–03|COVERED|
|CONTEXT|Disposable PG approval|Only new socket-only PG17/tmp/infinitemarkets-phase5-pg-1ae80f8 fixture DROP and parent teardown;no existing DB|05-PATTERNS,all profile checks|COVERED|
|CONTEXT|Narrow recoverable reason|Only invoice-creation-unknown,correlation/reasonless/independent/manual preserved,literal table/enum|05-03-01–02|COVERED|
|CONTEXT|No broadened permissions|No installs/security relaxation/push/production deploy/real-funds authorization by local tranche|All prohibitions +05-06 gates|COVERED|

## Independent checker84030b6d revision coverage

| Item | Binding property / revision | Task/artifact | Planning status |
|---|---|---|---|
|BLOCKER1|Each automated command has native fails_when with specific assertion/nonzero/natural-exit signal; separate expected_red and positive_retention|All18 task verify blocks;29 commands;05-VALIDATION|Authored; native static check0 blockers/0 warnings|
|BLOCKER2|Read-only durable proof, not paid/status/flags alone; absent/partial/malformed proof blocks ALL delivery and merchant fulfillment surfaces, unchanged legacy snapshots|05-01 helper/wiring and permanent surface regressions;05-02 new accept provenance via existing detail_json;05-03 combined retention|Authored, not runtime verified|
|BLOCKER3|No existing DB approval now; first-class actual-record audit gate BEFORE production exposure/disposition/release, without blocking authorized synthetic local work|05-03 pause and05-06 gate;05-PATTERNS/VALIDATION|OPEN / NOT AUTHORIZED / NOT PERFORMED; evidence NONE|
|WARNING1|Executable browser/conformance cwd, not prose-only|05-01-03,05-03-03,05-06-01|Native path probe grounded all4 cwd commands|
|WARNING2|Both make verify-runtime and make verify executable AFTER demonstrated CI-01 repair; pair-only success insufficient|05-05-03|Authored, execution still unauthorized|
|WARNING3|11-file plans bounded to existing shared fixtures/surfaces and evidence registers, no cosmetic split/new scope|05-01 and05-06 budget sections|Justified, scope remains six plans|
|Parent formatting|Single projectProhibitions flat serializer markers, descriptor-less, no check_* or auto-dismiss; executor commits prohibited while parent-reviewed local commits authorized|All19 prohibition markers;05-PATTERNS;05-REVIEWS|Unresolved; native disposition flagged-unverified, independent source review pending|

## New artifact/source grounding

05-PATTERNS lists current interfaces and physical paths. Each plan's “Artifacts this phase produces” explicitly declares intended helpers/test names/migration/evidence outputs. Executors must not reject planned helpers as missing baseline source, or treat old files as proof their new behaviors already pass. Every implementation task carries locked TDD behavior, exact automated command and intended baseline failure direction. Existing protective green invariants are distinguished from negative targets. Plans contain no runtime changes or security clearance.
