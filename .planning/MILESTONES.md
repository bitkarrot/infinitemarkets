# Project Milestones: infinitemarkets

## v1.0 Core Commerce and Hardening (Shipped: 2026-10-13)

**Delivered:** One authoritative commerce system in an LNbits extension — a merchant sells a single inventory through LNbits-backed web checkout and Nostr/Gamma (NIP-17) private ordering without duplicate invoices, double allocation, or relay delivery being mistaken for payment truth.

**Phases completed:** 1–5 (+ inserted 03.1) — 24 plans total

**Key accomplishments:**
- Full LNbits extension: catalog + collections publication, durable relay outbox, public storefronts (4 modes), web checkout with reservation→invoice→settlement saga, admin workspace (orders, catalog, publications, messages, settings)
- Private Gamma NIP-17 ordering: kind-1059 inbox with the §8.5 unwrap chain, dual-copy relay-scoped outbox, type-2 payment requests and type-3 statuses through one canonical pricing/inventory/settlement pipeline
- Buyer accounts: email magic-link + NIP-07 Nostr identity on a unified per-shop account with union merge
- Catalog import/export: Shopify/JSON/native CSV into hidden merchant-approved drafts
- Phase 5 hardening: F1–F6 correctness/recovery findings + CI-01 repaired with permanent regressions on SQLite + PostgreSQL, independent review, four-profile CI green
- Live external-client verification: real `plebeian.market` checkout over public relays executed end-to-end on the deployed v0.6.3 host (2026-10-13)

**Stats:**
- ~26.7k lines of extension Python (+ tests, templates, JS)
- 6 phases, 24 plans; 307 commits in the milestone range
- 24 days (2026-09-19 → 2026-10-13)

**Git range:** `da86bf8` (bootstrap) → `eaf7d64` (hardening release) + closeout

**Verified closeout:** milestone audit reconciled `gaps_found` → `passed`; all operator gates exercised or dispositioned in writing (live UAT passed; paid-order audit: zero real-customer records; F1 host limitation + WR-01 chronology caveat accepted).

**What's next:** v1.1 — deferred scope: S1–S4 follow-ups, external integrations, reviews, subscriptions, upstream LNbits/Plebeian divergences.

---
