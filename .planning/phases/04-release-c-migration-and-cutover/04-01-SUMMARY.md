---
phase: 04-release-c-migration-and-cutover
plan: "01"
status: superseded
requirements-completed: [LEG-03]
recorded: 2026-10-11
---

# 04-01 — Retrospective scope disposition

The original migration/cutover plan is superseded, not executed as written.
Its retained catalog preview/import behavior shipped under the revised
catalog-only contract: bounded files, merchant-owned records and hidden drafts.
See [current verification](04-VERIFICATION.md) and technical specification §13.

Current `test_migration_import.py` checks ran in the 70-pass/1-optional-skip
closeout selection; synthetic supported-format coverage passed. The unconfigured
private Shopify sample is not claimed passed. Old-order/liability reconciliation
is dropped; no extra implementation is needed to close that removed scope.
This is a disposition record, not a reconstructed task/commit execution log.
