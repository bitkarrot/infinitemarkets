---
phase: "04"
slug: release-c-migration-and-cutover
status: validated
nyquist_compliant: true
wave_0_complete: true
created: 2026-10-11
scope: catalog-only
---

# Phase 4 — Catalog-only validation map

This map applies to the revised LEG-03/LEG-06 scope, not the historical cutover
plans. The four SUMMARY files are explicit dispositions; no removed requirement
is counted as implemented or tested.

| Requirement | Current automated coverage | Evidence |
|---|---|---|
| LEG-03 | `tests/runtime/test_migration_import.py`: bounded supported files, ownership, preview, hidden drafts, no liability import | Included in current 70-pass/1-optional-skip selection; CI four-profile pass |
| LEG-06 | `tests/runtime/test_migration_export_media.py`: CSV round-trip/formula safety, media manifest/relink and owner isolation | Included in current selection; historical deployed catalog observations in 04-VERIFICATION.md |

The optional private Shopify sample is unconfigured and skipped, not silently
passed; synthetic supported-format coverage remains. `make lint` passes. There
is no new browser/deployment run in this closeout. Core checkout safety is a
separate, reopened Phase 5 gate, not established by catalog import tests.
