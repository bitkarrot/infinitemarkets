---
phase: 04-release-c-migration-and-cutover
plan: "04"
status: superseded
requirements-completed: []
requirements-dropped: [LEG-04, LEG-05]
recorded: 2026-10-11
---

# 04-04 — Dropped old/new-store rehearsal

The original scarce-stock cutover rehearsal presupposed removed freeze,
liability partition and old-invoice reconciliation features. It is no longer a
release criterion. This disposition closes obsolete planning, not a test run.

Normal local checkout concurrency, inventory and settlement safety remain
required. F1–F3 reopen those real invariants and are repaired in Phase 5; dropping
LEG-05 does not waive local stock safety. Catalog-only delivery has its own
[verification](04-VERIFICATION.md). Do not regenerate the removed cutover system.
