---
created: 2026-10-08T20:57:39.544Z
title: Select shipping countries and zones by name
area: ui
files:
  - infinitemarkets/templates/infinitemarkets/admin.html:918-921
  - infinitemarkets/static/infinitemarkets/js/admin_catalog.js:599-636
  - infinitemarkets/services/catalog.py:1818-1829
  - infinitemarkets/services/checkout.py:372-414
  - tests/e2e/admin.spec.ts:388-428
---

## Problem

The Shipping editor requires merchants to type two-letter country codes manually. Entering `EU` looks plausible and passes the current input validation, but checkout matches individual destination countries exactly, so `DE` does not match `EU`. Configuring one $20 International Tracked rate for the US, Canada and the 27 EU member countries currently requires entering 29 codes by hand. This is error-prone and not merchant-friendly.

## Solution

Replace the free-text country field with a searchable multi-select that shows country names and codes, plus clearly defined zone presets such as EU (27 member countries). Expanding a zone must store explicit ISO 3166-1 alpha-2 codes, preserve deduplication and existing selections, and show merchants the expanded destinations before save. Do not change shipping prices, checkout requirements, or existing options without merchant approval. Test country/zone selection, the saved and published codes, and quote coverage for representative destinations and exclusions. Keep the membership list maintainable as zones change.
