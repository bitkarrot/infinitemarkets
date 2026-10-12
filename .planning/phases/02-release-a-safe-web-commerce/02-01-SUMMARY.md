---
phase: 02-release-a-safe-web-commerce
plan: 01
subsystem: extension
tags: [lnbits-extension, migrations, aes-gcm, keystore, csrf, rfc9457, catalog, nip99, nip15, outbox, deterministic-events, runtime-tests]

# Dependency graph
requires:
  - phase: 01-conformance-profile-contract-phase-0
    plan: 03
    provides: pinned host checkout, harness db/schema/tx adapters, qualification evidence pipeline
provides:
  - Production `infinitemarkets` package discovered/migrated/route-mounted by the REAL host loader (LNBITS_EXTENSIONS_PATH + config.json + m001 through migrate_extension_database)
  - "m001 schema: all 21 §4 merchant/catalog/outbox tables + indexes, literal column names/constraints"
  - "DomainTransaction: explicit BEGIN IMMEDIATE (raw aiosqlite) on SQLite / conn.begin() on PG; markdown-safe write path avoiding rewrite_values stripping"
  - Strict §12 settings validation + topology refusal + OQ3 audit-capture startup warning in infinitemarkets_start
  - "crypto.py: AES-256-GCM envelopes (key_version + 96-bit nonce + tag) with length-prefixed AAD, purpose-separated HMAC-SHA256 privacy indexes, canonical public tokens"
  - "keystore.py: generate/import/sign/public_key/delete/rewrap/stale_merchants + encrypted export/restore; no raw nsec persisted/logged/returned"
  - "security.py: RFC 9457 problem+json boundary, cookie Origin+CSRF vs bearer mutation rules (cookie wins when both present), relay URL validator"
  - §5.1 merchant API (create/get/patch/import-key/publish/relay-health/notifications/test-send/deactivate) + §5.2 catalog API (catalogs/products/collections/shipping CRUD + images + events dry-run)
  - "services/events.py: deterministic unsigned builders — 30402/30405/30406/0/31989/31990/5 + NIP-15 30017/30018 projection with CompatibilityError on currency mismatch"
  - "services/outbox.py: shared transactional enqueue with revision supersession + dependency edges (portable select-then-insert SQL)"
affects: [02-02 publication worker consumes outbox intents + event builders; 02-03 orders reuse DomainTransaction + security boundary; 02-04 admin UI consumes §5.1/5.2 routes]

actuals:
  tokens: ~140000   # executed in lead session; subagent layer unavailable, work done inline
  tasks: 3
  commits: 1

tech-stack:
  added: []
  patterns:
    - "Real-loader install fixture: symlink package into tmp LNBITS_EXTENSIONS_PATH, reset extension install rows in shared core DB, host's own enable endpoint per user"
    - DomainTransaction for every multi-statement write; raw connection preserves markdown/JSON byte fidelity (Pitfall 3)
    - sys.modules purge + importlib re-import so module-level Database() binds the per-test data folder
    - "problem_boundary decorator: mutation enforcement + RFC 9457 conversion inside the route (dependency-raised errors bypass handlers); CSRF cookie issued on success AND error responses"
    - "Publishable-mutation pattern: bump revision, enqueue outbox intent, wire dependency edges — all in one DomainTransaction"

key-files:
  created:
    - infinitemarkets/__init__.py, config.json, db.py, migrations.py, settings.py
    - infinitemarkets/crypto.py, keystore.py, security.py, models.py
    - infinitemarkets/services/{__init__,merchant,catalog,events,outbox}.py
    - infinitemarkets/views.py, views_api.py
    - infinitemarkets/templates/infinitemarkets/index.html, static/infinitemarkets/probe.txt
    - tests/runtime/{conftest,test_install,test_db,test_crypto_keystore,test_merchant_api,test_catalog_api,test_catalog_events}.py
  modified:
    - tests/conftest.py (runtime marker)
    - Makefile (verify-runtime target)
    - evidence/{REPORT.md,manifest.json} (regenerated, 296/297)

key-decisions:
  - "Template name resolution (OQ2 verified): template_renderer(['infinitemarkets']) resolves literal 'templates/infinitemarkets/index.html' relative to the extension dir — the spike renders 200 through the real loader."
  - "Static files (OQ1 disposition): infinitemarkets_static_files declarative list is host-mounted and allowed — the PINS ban covers extension code instantiating FileResponse/StaticFiles, not the declaration; mount verified via /infinitemarkets/static/probe.txt."
  - "Install mechanics (OQ5): fixture symlinks the repo package into a tmp LNBITS_EXTENSIONS_PATH/extensions dir; core-DB install rows are reset per boot for fresh-install semantics."
  - "config.json permissions (OQ4): parsed and accepted by the loader; no runtime enforcement observed for Python extensions — recorded, no code depends on it."
  - "Migration split (OQ7): m001 covers merchant/catalog/outbox-intent tables; m002 (02-03) adds orders/payments/inventory/idempotency/email + schema-only inbox_events/order_messages; peer_relays/relay_cursors/migration_jobs defer to Phase 3/4."
  - "Audit capture (OQ3): deployment-level disposition — qualified deployments keep lnbits_audit_log_request_body/query_params/path_params disabled; start hook emits structured warning, admin banner surfaces it, test flips flags on and asserts the warning."
  - "Cookie-vs-bearer: a request carrying a cookie uses cookie rules even with a bearer header present — prevents bearer bypass of Origin/CSRF."
  - "Kind-5 tombstone enqueues carry the bumped aggregate revision so supersession retires older pending publish intents for the same aggregate."
  - "Collection losing its last active member enqueues a kind-5 tombstone but keeps the local row — §6.2 forbids publishing an empty collection, and the merchant may re-add members later."
  - "Product intent enqueues AFTER collection republish intents so dependency edges bind to live (non-superseded) rows — matches §8.6 ordering 30406 -> 30405 -> 30402."

requirements-completed: [MERC-01, CAT-01, CAT-02, SEC-01]

coverage:
  - id: T1
    description: "Real-loader install: discovery, m001 applied by host migration runner, route mount, static mount, sync start hook, deactivation; DomainTransaction commit/rollback/atomicity"
    requirement: MERC-01
    verification:
      - kind: unit
        ref: "tests/runtime/test_install.py (8), tests/runtime/test_db.py (13)"
        status: pass
    human_judgment: false
  - id: T2
    description: "Settings/crypto/keystore/security + §5.1 merchant API: strict env validation, AES-GCM+AAD, HMAC privacy indexes, public tokens, key lifecycle/rotation/backup, cookie-vs-bearer mutation rules, RFC 9457, audit posture"
    requirement: SEC-01
    verification:
      - kind: unit
        ref: "tests/runtime/test_crypto_keystore.py (16), tests/runtime/test_merchant_api.py (15)"
        status: pass
    human_judgment: false
  - id: T3
    description: "Catalog domain + §5.2 API: all §15 bounds, variation depth-1/parent rules, draft exclusion, zero-member collection publish block, soft-delete + 409 reference report + strip, tombstone intents with ordering deps, same-tx outbox rows, deterministic dry-run, markdown round-trip, owner scoping, published_at preserved on edits"
    requirement: CAT-01
    verification:
      - kind: unit
        ref: "tests/runtime/test_catalog_api.py (13)"
        status: pass
    human_judgment: false
  - id: T4
    description: "Event builders + outbox primitives: byte-identical deterministic renders, required/optional tag ordering, recurring/sold/variation/unlimited-stock cases, kind-0/31989/31990 label exclusion, NIP-15 stall/product projection incl. digital zone + hidden->quantity 0 + currency-mismatch error, outbox supersession/idempotency/dependency edges"
    requirement: CAT-02
    verification:
      - kind: unit
        ref: "tests/runtime/test_catalog_events.py (15)"
        status: pass
    human_judgment: false

# Verification
#   uv run ruff check .                          -> All checks passed
#   python3 tools/checkout_host.py               -> pinned e336fe1 confirmed
#   uv run pytest tests/runtime -q               -> 76 passed
#   GAMMA_QUAL_EVIDENCE=1 uv run pytest -q       -> 296 passed, 1 skipped (advisory relay smoke)

# Spec deltas / deferred
# - NIP-15 30017 stall builder + catalog publish_nip15 flag exist; stall
#   intents enqueue on catalog/product changes but the publisher worker is
#   02-02. Variation nip15_product_id persistence happens at publish time
#   (builder computes deterministically; dry-run does not persist).
# - rate_limit_buckets / task_leases tables exist but are unused until
#   02-02/02-03 workers land.
# - GET /merchants/{id}/outbox + retry delta routes deferred to 02-02 with
#   the worker (B2 consumes them).
---

# 02-01 — Historical execution record

The original evidence and notes above are preserved. The missing closing
frontmatter delimiter was restored during the 2026-10-11 closeout; this does not
reapprove the reopened Phase 2 acceptance or security gaps.
