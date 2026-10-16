---
phase: 04-release-c-migration-and-cutover
plan: "03"
status: superseded
requirements-completed: [LEG-06]
recorded: 2026-10-11
---

# 04-03 — Retained export/media behavior under revised scope

Product CSV export/reimport and optional owned-media validation/relink shipped
under the catalog-only scope. The original cutover dependencies are obsolete;
this record does not claim the old plan was executed exactly as written.

See [04-VERIFICATION.md](04-VERIFICATION.md). `test_migration_export_media.py`
ran in the current 70-pass/1-optional-skip closeout selection, which exited 0;
all four current Linux qualification jobs also passed. No new browser or live
merchant deployment claim is made. Shipping-import/binding expansion is deferred
until after Phase 5, not silently included in this delivered export feature.
