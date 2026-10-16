# Phase 2: Release A — Safe Web Commerce - Research

**Researched:** 2026-09-20
**Domain:** LNbits extension development (Python/FastAPI/Vue-Quasar) + Nostr publication + Lightning payment saga
**Confidence:** HIGH

<user_constraints>
## User Constraints (from 02-CONTEXT.md)

### Locked Decisions

- **D-01:** Run a phase researcher before planning. Production runtime code warrants verified host conventions — map the pinned host's extension patterns (route registration, Vue/static asset loading, migrations, lifecycle hooks, CRUD, extension manifest/install mechanics) rather than discovering them during execution.
- **D-02:** Generate and approve the Phase 2 UI contract **before planning** via the ui-phase step, using `.devin/skills/sketch-findings-infinitemarkets/` + `.planning/sketches/` as the guideline and the normative spec as authority. Plans 02-02/02-03 then reference concrete components, themes, and states rather than placeholders. *(Satisfied: `02-UI-SPEC.md` committed at `f219ba5`.)*
- **D-03:** Production source uses the standard LNbits extension layout inside this repository (`infinitemarkets/` package: `__init__.py`, views/API modules, `static/`, `templates/` as needed, migrations), mounted into the pinned host's extension directory for development and UAT.
- All 16 Phase-1 decisions (D-01..D-16): pins, Python 3.12, Linux x86_64/ARM64 blocking matrix, permanent harness, single-run clean-pass, evidence discipline, SDK fallback ladder, extension-checks-as-defense-in-depth.
- Frozen identifiers (spec decision 25): package `infinitemarkets`, `/infinitemarkets` route prefix, `/infinitemarkets/api/v1`, `infinitemarkets_start`/`_stop` hooks, `INFINITEMARKETS_` env prefix, `infinitemarkets:` payment correlation, `infinitemarkets` AAD prefix, `org.infinitemarkets.protocol` NIP-32 namespace.
- Spec decisions register 1–29 (§21) in full — including 1:1 merchant per user, manual payment_preference, local-only drafts, SQLite single-process / PostgreSQL multi-worker topology, order bearer tokens never in path/query, host-SMTP boolean boundary, and refund-as-attestation.
- UI findings: Adaptive Blend checkout (Editorial/Guided/Compact presets + compact mobile fallback, invariant checkout semantics), Linear Split admin workspace (list/detail + embedded chronology), Tiered Controls themes (Warm Market default / Clean Minimal / High Contrast + bounded Brand Basics + guarded Advanced Tokens), public theme never styles admin or alters checkout semantics, Vue/Quasar-compatible primitives only (no React/Tailwind/shadcn).
- Dependabot disposition recorded in `PINS.md` §5: extension code uses JSON-only request bodies, `APIRouter` only (no `HTTPEndpoint` subclassing), no `FileResponse`/`StaticFiles`, and never derives security decisions or absolute URLs from `request.url`/Host.

### Claude's Discretion

- Exact file/module decomposition inside the `infinitemarkets/` package, mount mechanics into the host (symlink vs extension-path), and local dev-loop tooling — resolved from pinned-host conventions during research/planning.
- Test layout and fixtures for the runtime implementation beyond what §17 and the Phase 1 harness already mandate.
- Migration framework mechanics consistent with LNbits extension conventions.
- CI workflow changes needed to run runtime tests in the existing blocking matrix (the harness suite must stay green — D-05).

### Deferred Ideas (OUT OF SCOPE)

- NIP-17 order intake, kind-10050 inbox discovery, NIP-42, egress controls — Release B (Phase 3).
- Historical Phase-2 forecast of NIP-15/NIP-04 compatibility and cutover for Release C — superseded: current Phase 4 imports CSV/JSON catalogs as hidden drafts and publishes only after merchant review; no old-order gate.
- NIP-37 drafts sync, preorders/subscriptions purchasing, automated refunds, multi-shop, transport adapters (`nostrclient`/`nostrrelay`) — deferred per spec decisions 13/14/5/26.
- Windows support — out of the platform claim (Dependabot disposition).
</user_constraints>

<architectural_responsibility_map>
## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Merchant admin UI (orders, catalog, publications, settings) | Frontend Server (host-rendered `base.html` + extension Vue/Quasar) | Browser/Client | Extension pages extend the host shell; authed via host session [VERIFIED: `.cache/lnbits/lnbits/core/views/generic.py:203-214` — `index` renders `"base.html"` with `"user": user.json()`] |
| Public storefront (product page, checkout, order status) | Frontend Server (extension-owned standalone documents) | Browser/Client | 02-UI-SPEC §A: "All public pages are standalone HTML documents: `Cache-Control: no-store`, `Referrer-Policy: no-referrer`, restrictive CSP" — they must NOT inherit admin chrome [VERIFIED: `.planning/phases/02-release-a-safe-web-commerce/02-UI-SPEC.md:190-192`] |
| Checkout/reservation/invoice saga | API/Backend (extension routes + service layer) | Database/Storage | Atomic claim in one extension transaction; `create_invoice` call outside the tx [VERIFIED: `docs/technical-specification.md` §8.2 saga; host API `.cache/lnbits/lnbits/core/services/payments.py:261-376`] |
| Outbox/relay publication | API/Backend (`outbox_publisher` permanent task) | Database/Storage | Durable outbox rows claimed per worker; `Client.send_event_to` returns per-relay evidence |
| Settlement detection | API/Backend (`register_invoice_listener` callback) | Database/Storage (reconciliation) | Listener is memory-only; durable reconciliation by exact `external_id` is the truth path [VERIFIED: `tests/qualification/test_p0_03_host_contract.py:19-30` docstring + `:197` `test_no_durable_callback_delivery_across_restart`] |
| Persistence (all extension tables) | Database/Storage | API/Backend | `Database("ext_infinitemarkets")` → SQLite file `ext_infinitemarkets.sqlite3` or PG schema `infinitemarkets` [VERIFIED: `.cache/lnbits/lnbits/db.py:292-315`] |
| Email delivery | API/Backend (`email_sender` task) | Database/Storage (queue rows) | Host `send_email` boolean boundary; per-recipient rows [VERIFIED: `.cache/lnbits/lnbits/core/services/notifications.py:205-240`] |
</architectural_responsibility_map>

<research_summary>
## Summary

Phase 2 delivers a real LNbits extension (`infinitemarkets/`) that runs inside the pinned host `v1.6.2-rc1` (`e336fe14b841`). The host's extension machinery is conventional and well-defined: a directory `{lnbits_extensions_path}/extensions/infinitemarkets/` containing `config.json` is auto-discovered at startup, imported as module `infinitemarkets`, its `infinitemarkets_ext` `APIRouter` is included with no added prefix, `infinitemarkets_start`/`infinitemarkets_stop` lifecycle hooks are invoked, and `infinitemarkets/migrations.py` functions matching `m\d\d\d_` run automatically against `Database("ext_infinitemarkets")` [VERIFIED: `.cache/lnbits/lnbits/app.py:336-352,495-554`; `.cache/lnbits/lnbits/core/helpers.py:34-69`; `.cache/lnbits/lnbits/core/models/extensions.py:267-271,545-566`].

The critical correctness surfaces are all verified: `create_invoice` is keyword-only and raises `InvoiceError` with `status="pending"` on unknown outcomes (the `creation_unknown` mapping); `external_id` is persisted but only non-unique-indexed — the extension's own payment projection must enforce single-invoice; `task_manager.register_invoice_listener` delivers settled payments in-memory only (reconciliation by exact `external_id` is mandatory); `Database.connect()` serializes on a per-object asyncio lock so concurrent queue workers need separate `Database` handles; and `Connection.rewrite_values` HTML-strips string parameters on `execute`/`fetch*` paths while `insert`/`update` model helpers bypass it — a real data-corruption hazard for markdown/JSON payloads that must be designed around.

The frontend is Vue 3 global build + Quasar UMD served from the host's own `/static/vendor/` bundle — same-origin, no CDN — which aligns exactly with the locked "Vue/Quasar-compatible primitives only" decision [VERIFIED: `.cache/lnbits/lnbits/static/vendor.json` — `"vendor/vue.global.prod.js"`, `"vendor/quasar.umd.prod.js"`; mount at `.cache/lnbits/lnbits/app.py:187` `app.mount("/static", StaticFiles(directory=Path("lnbits", "static")), name="static")`]. Public buyer pages should be standalone Jinja documents (not `base.html` — it mounts the host admin chrome), while admin pages extend `base.html` per the extension convention.

**Primary recommendation:** Implement the extension exactly on the host's own extension conventions — `infinitemarkets_ext` router with `prefix="/infinitemarkets"`, `infinitemarkets_static_files` declaration (host-mounted; the PINS ban applies to extension code instantiating `FileResponse`/`StaticFiles` — see Open Question 1), `Database("ext_infinitemarkets")`, `mNNN_*` migrations, sync `infinitemarkets_start()` doing only `task_manager` registrations — and put every spec invariants (single-invoice, reservation atomicity, token-in-fragment) behind extension-owned enforcement because the host guarantees none of them.

</research_summary>

<standard_stack>
## Standard Stack

### Core (all pinned — do NOT re-resolve)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| LNbits (host) | `v1.6.2-rc1` @ `e336fe14b841` | Host app, extension loader, payment pipeline | Approved pin [VERIFIED: `PINS.md` — "LNbits `v1.6.2-rc1` @ `e336fe14b841`"]; project dep is path source [VERIFIED: `pyproject.toml:32` — `lnbits = { path = ".cache/lnbits" }`] |
| `nostr-sdk` | `0.44.8` | Nostr transport, event signing, NIP-44, naddr parse | Approved pin with wheel sha256 manifest [VERIFIED: `PINS.md:22,63-65,72-84` — wheels-only release, rust-nostr `nostr-sdk-ffi` @ `a600c2a7`]; already in project deps [VERIFIED: `pyproject.toml:12` — `"nostr-sdk==0.44.8"`] |
| Python | `3.12` (only) | Runtime | Narrower project claim inside host's `>=3.10,<3.13` [VERIFIED: `PINS.md`] |
| FastAPI/Starlette | host-provided | HTTP surface | Transitively pinned by host [VERIFIED: host `pyproject.toml` — do not version-pin separately] |
| SQLAlchemy async | host-provided | Under `lnbits.db` `AsyncEngine`/`AsyncConnection`/`text` | [VERIFIED: `.cache/lnbits/lnbits/db.py:15-16`] |
| Vue 3 + Quasar UMD | host vendored | Admin + public UI | Host vendor bundle [VERIFIED: `.cache/lnbits/lnbits/static/vendor.json`] |
| `pydantic` v1-era API | host-provided | Models, `FilterModel` | Host models use `BaseModel`, `root_validator`, `Field(no_database=...)` [VERIFIED: `.cache/lnbits/lnbits/db.py:14`, `.cache/lnbits/lnbits/core/models/payments.py`] |

### Supporting (host-provided helpers — use, don't reimplement)

| Helper | Location | Purpose |
|--------|----------|---------|
| `lnbits.core.services.payments.create_invoice` | `services/payments.py:261-278` | Invoice creation w/ `extension`/`external_id`/`expiry`/`extra` |
| `lnbits.core.crud.payments.get_payments` + `Filters`/`Filter.parse_query` | `crud/payments.py:188-225`, `db.py:464-526` | Exact `external_id` reconciliation queries |
| `lnbits.task_manager` | `task_manager.py` | `create_permanent_task`, `register_invoice_listener`, `cancel_task` |
| `lnbits.db.Database`/`Connection` | `db.py:134-410` | Extension DB, dialect compat helpers |
| `lnbits.helpers.template_renderer` | `helpers.py:60-97` | Jinja templates + `static_url_for`, `INCLUDED_*` globals |
| `lnbits.decorators.check_user_exists` / `check_admin` / `require_admin_key` | `decorators.py:324-335,390-405,180-189` | Auth dependencies |
| `lnbits.core.services.notifications.send_email` | `notifications.py:205-240` | Host SMTP boolean boundary |
| `lnbits.utils.exchange_rates.btc_rates` / `get_fiat_rate_and_price_satoshis` | `exchange_rates.py:238-336` | FX with per-provider provenance + host cache |
| `bolt11.decode` (re-exported `lnbits.bolt11`) | `bolt11.py` | BOLT11 verify: `payment_hash`, `expiry_date` [VERIFIED: `.cache/lnbits/lnbits/core/services/payments.py:352-360`] |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `task_manager.create_permanent_task` | `lnbits.tasks.create_permanent_unique_task` | **Deprecated** — old helpers exist only for backward compat [VERIFIED: `.cache/lnbits/lnbits/tasks.py:1-89` deprecation comments] |
| `register_invoice_listener` | polling `get_payments` only | Listener gives low-latency settlement; polling alone misses nothing durable but adds latency — spec requires BOTH (listener + reconciliation) |
| `Database("ext_infinitemarkets")` | raw SQLAlchemy/ORM | Host DB layer handles SQLite↔PG dialect + schema isolation; ORM would fight `rewrite_values`/compat layer |
| Host vendor Vue/Quasar | bundled SPA (React etc.) | Locked decision: Vue/Quasar primitives only; host CSP/same-origin story is built around vendored assets |
| Host `send_email` | own SMTP stack | Spec fixes the boundary at host SMTP boolean semantics (decision 21) |

**Installation:** none — all dependencies are already pinned in `pyproject.toml`/`uv.lock`. New runtime deps are NOT expected; if any arise, run a package-legitimacy check (registry metadata, provenance, wheel audit) per the agent protocol before proposing.

</standard_stack>

<architecture_patterns>
## Architecture Patterns

### Extension Layout, Discovery, and Mounting (all VERIFIED against `.cache/lnbits`)

**Module identity & discovery:**
- `Extension.module_name` is `f"lnbits.extensions.{code}"` only when `settings.has_default_extension_path` (`lnbits_extensions_path == "lnbits"`); otherwise it is the bare package name `"infinitemarkets"` [VERIFIED: `.cache/lnbits/lnbits/core/models/extensions.py:267-271` — `return f"lnbits.extensions.{self.code}"` / `return self.code`; `settings.py:1167` — `return self.lnbits_extensions_path == "lnbits"`].
- Installed location: `ext_dir = Path(settings.lnbits_extensions_path, "extensions", self.id)` [VERIFIED: `models/extensions.py:545-546`].
- Recognition predicate: `has_installed_version` requires `Path(self.ext_dir, "config.json").is_file()` [VERIFIED: `models/extensions.py:562-566`].
- Startup auto-discovery: the host scans `{lnbits_extensions_path}/extensions/*/`; any dir with `config.json` is registered via `InstallableExtension.from_ext_dir` (which sets `active=True`), `create_installed_extension`, and `migrate_extension_database` [VERIFIED: `.cache/lnbits/lnbits/app.py:336-352` — `ext_info = InstallableExtension.from_ext_dir(ext_id)` → `await create_installed_extension(ext_info)` → `await migrate_extension_database(ext_info, current_version)`].
- With a non-default `LNBITS_EXTENSIONS_PATH`, the host appends `{path}/extensions` to `sys.path` [VERIFIED: `.cache/lnbits/lnbits/app.py:443-445` — `extensions_dir = Path(settings.lnbits_extensions_path, "extensions")` / `sys.path.append(str(extensions_dir))`]. Since `infinitemarkets` is also a proper package in the project venv, both resolution paths work.
- `config.json` schema (as parsed): `name`, `version`, `short_description`, `tile` (→ icon), `permissions` (list of `{id, description}`), `min_lnbits_version`, `max_lnbits_version` [VERIFIED: `models/extensions.py:880-902` `from_ext_dir` field extraction; `ExtensionConfig` model at `:111-119` adds `warning`, `extension_type`]. A real-world `config.json` also carries `donate`, `contributors`, `images`, `description_md`, `terms_and_conditions_md`, `license` [CITED: https://raw.githubusercontent.com/lnbits/example/main/config.json].
- Release `manifest.json` (extension-source side, not the per-release `config.json`): `{"repos": [{"id": "example", "organisation": "lnbits", "repository": "example"}]}` [CITED: https://raw.githubusercontent.com/lnbits/example/main/manifest.json]. `LNBITS_EXTENSIONS_MANIFESTS` (list) and `LNBITS_EXTENSIONS_DEFAULT_INSTALL` are the host settings for manifest-driven installs [VERIFIED: `.cache/lnbits/lnbits/settings.py:89` `lnbits_extensions_manifests: list[str]`; `app.py:357-377` default-install flow].

**Route mounting:**
- `register_ext_routes` fetches `infinitemarkets_ext` (`getattr(ext_module, f"{ext.code}_ext")`) and `app.include_router(router=ext_route)` — **no prefix is added**; the extension router itself must carry `prefix="/infinitemarkets"` [VERIFIED: `.cache/lnbits/lnbits/app.py:520,554`].
- Optional `{code}_redirect_paths` → `settings.activate_extension_paths` for outside-prefix redirects (e.g., `/.well-known`) [VERIFIED: `app.py:522-528`; `middleware.py:92-110` `ExtensionsRedirectMiddleware`].
- Optional `{code}_static_files` → host does `app.mount(s["path"], StaticFiles(directory=Path(settings.lnbits_extensions_path, "extensions", *s["path"].split("/"))), s["name"])` [VERIFIED: `app.py:545-551`]. Note the mount dir is `{extensions_path}/extensions/<path-segments>` — i.e., the declared `path` (e.g. `/infinitemarkets/static`) doubles as the on-disk subdirectory **relative to the extensions root**, not relative to the extension dir. Real example: satspay declares `[{"path": "/satspay/static", "name": "satspay_static"}]` and its files live at `<extensions>/satspay/static/...` [CITED: https://raw.githubusercontent.com/lnbits/satspay/main/__init__.py].
- On re-registration, all routes whose path is `/{code}` or `/{code}/*` are purged and OpenAPI cache invalidated [VERIFIED: `app.py:532-543`].
- Deactivation 404s the whole `/{code}` top path (including public pages and `…/static`) via `InstalledExtensionMiddleware` [VERIFIED: `.cache/lnbits/lnbits/middleware.py:41-47` — `if top_path in settings.lnbits_deactivated_extensions`]. Planning implication: merchant deactivation = storefront offline; the spec's deactivation flow (tombstone then deactivate) is the graceful path.

**Lifecycle hooks:**
- `{code}_start` is called from two paths: (a) startup restore via `register_ext_tasks` → `ext_start_func()` called **synchronously, never awaited** [VERIFIED: `app.py:486-492` — `ext_start_func = getattr(ext_module, f"{ext.code}_start")` / `ext_start_func()`]; (b) admin activation via `start_extension_background_work` which `await`s iff `asyncio.iscoroutinefunction` [VERIFIED: `.cache/lnbits/lnbits/core/services/extensions.py:728-733`]. **Conclusion: `infinitemarkets_start` MUST be a synchronous `def`** — an `async def` would produce an un-awaited coroutine on the startup path. This matches the spec's "synchronous, bounded registration" mandate [VERIFIED: `docs/technical-specification.md:1383-1385` — "`infinitemarkets_start()` performs only synchronous, bounded registration ... it performs no network or reconciliation work inline"].
- `{code}_stop` is **mandatory** when start exists: `stop_extension_background_work` raises `ValueError(f"No stop function found for '{module_name}'.")` if absent (caught and logged, deactivation still proceeds) [VERIFIED: `extensions.py:673-704`].
- Stop is invoked on deactivate and uninstall [VERIFIED: `extensions.py:665-670,639-651`]. Process shutdown may bypass it entirely — every worker needs `finally` cleanup (spec §10, verified by P0-12 `test_cleanup_under_direct_task_cancellation`).

### Database Layer (all VERIFIED against `.cache/lnbits/lnbits/db.py`)

- Dialect selection at module import: `lnbits_database_url` starting `cockroachdb://` → `COCKROACH`; `postgres://` → `POSTGRES` (any other scheme → `ValueError`); unset → `SQLITE` and data folder created [VERIFIED: `db.py:31-46`].
- `Database("ext_infinitemarkets")`: name → `schema = "infinitemarkets"` (strips `ext_`) for PG/CR; SQLite file `{data_folder}/ext_infinitemarkets.sqlite3` [VERIFIED: `db.py:292-321` — `if self.name.startswith("ext_"): self.schema = self.name[4:]`; `f"{self.name}.sqlite3"`].
- **`connect()` serializes**: `await self.lock.acquire()` around `engine.connect()` — one `Database` object processes one connection at a time [VERIFIED: `db.py:323-343`]. Concurrent workers (outbox/email/reconciliation running simultaneously) need either separate `Database` instances or `conn`-passing discipline — the Phase-1 context already calls this out ("concurrent work uses separate handles").
- SQLite schema namespacing: on each `connect()` it runs `ATTACH '{path}' AS {schema}` [VERIFIED: `db.py:338-339`]; PG runs `CREATE SCHEMA IF NOT EXISTS` [VERIFIED: `db.py:334-336`].
- **`Connection.execute` auto-commits** (`await self.conn.commit()` at `db.py:288`) — multi-statement atomicity requires explicit transaction handling. The host `Connection` exposes no explicit `begin()`/`rollback` wrapper in `db.py:134-289`; the underlying `conn.conn` is an `AsyncConnection`, so atomic reservation blocks should go through `conn.conn` SQLAlchemy transaction APIs or be structured as single-statement CAS. **[ASSUMED]** — planners should confirm the harness `tx.py` adapter's approach (SQLite `BEGIN IMMEDIATE`, PG lock-select-update in one tx) translates through this layer; that is exactly what `harness/tx.py` modeled.
- **`rewrite_values` HTML-strips every string parameter** on `execute`/`fetchall`/`fetchone`/`fetch_page` [VERIFIED: `db.py:147-162` — `clean_regex = re.compile("<.*?>|&(...)...")` → `re.sub(clean_regex, "", raw_value)`]. `insert`/`update` (the pydantic-model helpers at `db.py:194-206`) pass `model_to_dict(model)` **without** `rewrite_values`. **Pitfall:** markdown descriptions or event JSON containing `<...>`/entities stored via raw `execute` are silently mangled — persist payloads via `insert`/`update` or pre-encode (see Pitfalls).
- `rewrite_values` also converts `datetime` → epoch (int for SQLite, float elsewhere) [VERIFIED: `db.py:154-159`].
- Compat helpers on `Database`/`Connection`: `serial_primary_key` (`SERIAL PRIMARY KEY` / `INTEGER PRIMARY KEY AUTOINCREMENT`), `big_int` (`BIGINT`/`INT`), `blob` (`BYTEA`/`BLOB`), `timestamp_now`, `timestamp_column_default`, `timestamp_placeholder(key)`, `references_schema`, `interval_seconds`, `datetime_to_timestamp`, `datetime_grouping` [VERIFIED: `db.py:62-131`]. Extension DDL must use these for dialect portability — exactly what `harness/schema.py` modeled.
- Param style: write queries with `:named` params; `rewrite_query` converts `?`→`%s` and escapes `%` for asyncpg [VERIFIED: `db.py:141-145`].
- Pagination/filtering infra: `Filters`/`Filter`/`FilterModel`/`Page` + `parse_filters(model)` FastAPI dependency for `?field[op]=v` query params and `search` [VERIFIED: `db.py:412-609`; `decorators.py:422-454`]. Reuse for admin list endpoints (orders, outbox).
- Uninstall cleanup: `Database.clean_ext_db_files(ext_id)` removes `ext_{id}.sqlite3` [VERIFIED: `db.py:397-409`] — extension tables are dropped on uninstall for SQLite; the host's `drop_extension_db` handles PG schema drop.

**Migrations:**
- `migrate_py_extension_database` imports `{module_name}.migrations` and `{module_name}` (reads `.db` attribute — so `infinitemarkets/__init__.py` must re-export `db`), opens `ext_db.connect()`, runs `run_migration` [VERIFIED: `.cache/lnbits/lnbits/core/helpers.py:34-45`].
- `run_migration` iterates module attrs matching `^m(\d\d\d)_`, runs those with `version > current`, records each in shared `dbversions` (written to **core** db when `db.schema` set) [VERIFIED: `helpers.py:48-69`].
- Migration signature: `async def m001_initial(db: Database)` / `(db: Connection)` — real extensions use `from lnbits.db import Database` [CITED: https://raw.githubusercontent.com/lnbits/satspay/main/migrations.py]. Migrations run at startup for every installed extension and on restore [VERIFIED: `helpers.py:118-131`, `app.py:351-352,418`]. Failure logs and continues (`logger.exception` per ext) — a broken migration does not block host boot; the extension surfaces it via readiness instead.

### Payments (all VERIFIED against `.cache/lnbits/lnbits/core/services/payments.py` unless noted)

- **Signature** (`:261-278`): `async def create_invoice(*, wallet_id, amount: float, currency="sat", memo, description_hash=None, unhashed_description=None, expiry=None, extra=None, webhook=None, internal=False, payment_hash=None, extension=None, labels=None, external_id=None, conn=None) -> Payment`.
- Behavior: rejects non-positive amounts (`InvoiceError status="failed"`, `:279-280`); verifies wallet + `can_receive_payments` (`:282-290`); converts fiat amounts via `calculate_fiat_amounts` when `currency != "sat"`; enforces `lnbits_max_incoming_payment_amount_sats` and wallet-balance cap (`:306-319`); calls `funding_source.create_invoice(..., expiry=expiry or settings.lightning_invoice_expiry)` (`:336-342`).
- **Unknown vs definite failure**: non-ok/empty backend response → `InvoiceError(message, status="pending")` (`:343-351`) → map to `creation_unknown`. Definite validation errors → `status="failed"`. `InvoiceError`/`PaymentError` carry `.message`/`.status` [VERIFIED: `.cache/lnbits/lnbits/exceptions.py:16-26`].
- Persistence: `create_payment(checking_id=invoice_response.checking_id, data=CreatePayment(..., external_id=external_id, extension=extension, extra=extra, ...))` (`:354-374`). `create_payment` rejects a duplicate `checking_id` (`ValueError("Payment already exists")`) **after** the backend invoice exists [VERIFIED: `crud/payments.py:243-258`].
- **`external_id` is NOT unique**: m045 adds it as `TEXT` + `CREATE INDEX` (not `UNIQUE`) [VERIFIED: `.cache/lnbits/lnbits/core/migrations.py:807-816`]. Single-invoice-per-order is enforced ONLY by the extension's own projection unique constraint — exactly as the spec saga does.
- Validation: `is_valid_external_id` ≤256 chars, no space/newline [VERIFIED: `helpers.py:176-181`].
- `Payment` fields: `checking_id, payment_hash, bolt11, wallet_id, amount` (msat; `.sat` = `amount//1000`), `fee, status, expiry, preimage, tag, extension, extra, external_id, labels` + `is_in`/`is_expired`/`is_internal`/`pending`/`success`/`failed` [VERIFIED: `models/payments.py:80-141`]. `payment_request` property prefers `extra["fiat_payment_request"]` else `bolt11` (`:100-103`).
- `PaymentFilters` supports `external_id` in `__search_fields__`, `__sort_fields__`, and as a filter field [VERIFIED: `models/payments.py:158-192`] — the reconciliation query `get_payments(filters=Filters(filters=[Filter.parse_query("external_id", [ext], PaymentFilters)], model=PaymentFilters))` is proven in the harness [VERIFIED: `tests/qualification/test_p0_03_host_contract.py:87-98`].
- Settlement pipeline: `fundingsource_invoice_producer` → `paid_invoices_stream()` → `update_invoice_from_paid_invoices_stream` (verifies `get_invoice_status` success, sets `SUCCESS`) → `task_manager.invoice_queue.put_nowait(payment)` [VERIFIED: `payments.py:1122-1147,1150-1162`]. `_invoice_listener_consumer` → `_invoice_dispatcher` → `put_nowait` into **every** listener queue [VERIFIED: `task_manager.py:444-450,485-493`].
- Poll path (`update_pending_payment` / `check_pending_payments`, `payments.py:379-407+`) marks expired invoices `FAILED` + label `"expired"` (`:392-396`) and success via `update_payment_success_status` — which does **not** itself enqueue to `invoice_queue` (`:906-920`); listener delivery rides on the funding-source stream/internal queue. Reconciliation-by-`external_id` remains the truth source.
- BOLT11 verify: `from bolt11 import decode` (re-exported via `lnbits.bolt11`); `create_invoice` uses `invoice.payment_hash`, `invoice.expiry_date` [VERIFIED: `payments.py:6,352-360`; `lnbits/bolt11.py:1-7`]. Settlement verification (spec §8.4) should decode the stored BOLT11 the same way.
- Outgoing payments (`pay_invoice`, `payments.py:58+`) are out of scope — spec forbids outbound payment APIs.

### Task Manager (all VERIFIED against `.cache/lnbits/lnbits/task_manager.py`)

- `create_permanent_task(func, name=None, interval=0, invoice_queue=None, ...) -> Task`: wraps `func` in `while settings.lnbits_running: _catch_everything_and_restart(func); sleep(interval)`; restarts on exception after 5s (`:133-158,381-400`). `CancelledError` is re-raised (`:390-391`) — safe for `cancel_task`.
- `register_invoice_listener(func, name=None) -> Task`: name becomes `"{name}_invoice_listener"`; each listener gets its own `asyncio.Queue`; dispatcher `put_nowait`s every settled `Payment` to every listener (`:160-175,402-409,444-450`). Fan-out is unfiltered — **the callback must self-filter** on `extension`/`external_id` (spec already requires this).
- `cancel_task(task)` removes the `Task` from `self.tasks` and cancels `task.task` (`:95-101`); `cancel_all_tasks()` exists but is forbidden by spec (P0-12 proved unrelated tasks survive `cancel_task`).
- `Task` fields: `coro, name, created_at, task: asyncio.Task, invoice_queue` (`:32-60`) — retain the returned `Task` handles.
- Deprecated wrappers (`create_permanent_unique_task` etc.) still exist in `lnbits/tasks.py` for compat [VERIFIED: `lnbits/tasks.py:1-89`] — use `task_manager` directly.
- Host's own periodic pattern: `task_manager.create_permanent_task(check_pending_payments, interval=settings.lnbits_funding_source_pending_interval_seconds)` [VERIFIED: `app.py:581-584`] — `interval` sleeps BETWEEN runs, so the spec's tick cadences (30s/5s/1s/60s/daily) map directly to `interval=...`.
- Registration timing: `task_manager.init()` and host listeners are created inside `register_async_tasks` during lifespan startup [VERIFIED: `app.py:571-614`]; `register_ext_tasks` runs inside `check_and_register_extensions` at app startup (`:557-568`, `:102`).

### Auth, Middleware, and Request Security (all VERIFIED)

- Merchant-facing deps: `check_user_exists` → `User` (JWT cookie `cookie_access_token`, bearer, or `usr=` when `user_id_only` auth allowed) [VERIFIED: `decorators.py:324-335,286-321`]. `check_admin`/`check_super_user` gate server-admin (`:390-419`). `require_admin_key`/`require_invoice_key` resolve `X-API-KEY` header or `api-key` query → `WalletTypeInfo` (`:180-225`) — useful for wallet-binding validation, not for merchant session auth.
- Per-request extension access: `_check_user_extension_access` extracts ext id from the **first path segment** and requires the extension to be active for that user when it is a known installed ext [VERIFIED: `decorators.py:457-503`] — authed routes under `/infinitemarkets/...` inherit "extension enabled" enforcement; public routes must NOT use `check_user_exists` (buyers have no account).
- **No CSRF/origin middleware in the host.** CORS is `allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]` [VERIFIED: `app.py:196`]. Cookie-auth mutations therefore need extension-side Origin/`Sec-Fetch-Site` enforcement — Phase 1's probe did exactly this [VERIFIED: `harness/authprobe.py:163` — `"cross-origin or missing Origin rejected"`] and P0-12 verified cookie-only/cross-origin rejection.
- Rate limiting: SlowAPI `SlowAPIMiddleware` + `app.state.limiter` (`Limiter` with `default_limits=[f"{lnbits_rate_limit_no}/{lnbits_rate_limit_unit}"]`) [VERIFIED: `middleware.py:201-209`; `app.py:473-483`]. Extension routes can opt into `app.state.limiter` decorators; spec-level input limits remain extension-owned.
- **Audit middleware can log path params, query params, and request bodies** when `lnbits_audit_log_*` settings are enabled [VERIFIED: `middleware.py:180-198`]. Reinforces: bearer tokens never in path/query; checkout bodies may be audit-logged (PII note → Open Questions).
- Exception handlers map `HTTPException`/`ValueError`/`RequestValidationError`/`PaymentError`/`InvoiceError` to JSON (or `error.html` for browser UA) [VERIFIED: `exceptions.py:71-165`]. Public pages get HTML error pages; API paths under `api/v1` always get JSON (`_is_browser_request` returns False when `"api/v1" in path`, `:169-170`) — keep public API routes under `/infinitemarkets/api/v1/...` for consistent JSON errors.

### Frontend (all VERIFIED unless noted)

- `template_renderer(["infinitemarkets"])` searches `lnbits/templates` + builder dir + `{extensions_path}/extensions/infinitemarkets` — templates live at `infinitemarkets/templates/infinitemarkets/*.html` resolved as `infinitemarkets/...`? No: the added folder is the extension dir itself, so template names are relative to the extension root (e.g. `templates/infinitemarkets/index.html` → lookup `"templates/infinitemarkets/index.html"`). Convention from example ext: `templates/example/index.html` referenced as `"example/index.html"` is wrong — the example renders `"index.html"`? **[ASSUMED]** — satspay's installed tree maps `templates/satspay/*.html` and template_renderer gets `"satspay"` appended so lookup is `templates/satspay/...`? The mechanism: `additional_folders += [Path(extensions_path,"extensions",f)]` → folder is `extensions/satspay`; template name `"satspay/index.html"` resolves to `extensions/satspay/satspay/index.html` — i.e., templates must live at `extensions/{ext}/{ext}/`?? No — satspay's `views.py` calls `template_renderer(["satspay"])` then `.get_template("satspay/index.html")`? **Resolve during plan 02-01 spike: check any extension's TemplateResponse call.** What IS verified: `template_renderer(additional_folders)` appends `Path(lnbits_extensions_path, "extensions", f)` per folder name [VERIFIED: `helpers.py:60-72`]; globals injected: `static_url_for`, `normalize_path`, `SITE_TITLE`, `SETTINGS`, `CURRENCIES`, `INCLUDED_JS/CSS/COMPONENTS`, `LNBITS_DENOMINATION` (`:73-95`).
- `static_url_for(static, path)` → `f"/{static}/{path}?v={settings.server_startup_time}"` [VERIFIED: `helpers.py:56-57`] — extension JS/CSS URLs like `static_url_for('infinitemarkets/static', 'js/x.js')` → `/infinitemarkets/static/js/x.js?v=...` served by the host-mounted `infinitemarkets_static_files` mount.
- `base.html` blocks available to extension templates: `styles`, `head_scripts`, `title`, `page_container`, `page`, `vue_templates`, `scripts`, `footer` [VERIFIED: `templates/base.html:4-117`]. Globals `RENDERED_ROUTE`, `SETTINGS`, `CURRENCIES`, `window.g` (user, wallets, `isPublicPage`) [VERIFIED: `base.html:87-114`].
- Admin pages convention: `{% extends "base.html" %}`, `{% from "macros.jinja" import window_vars %}`, `{{ window_vars(user) }}` in `{% block scripts %}`, load ext JS via `static_url_for` [CITED: https://raw.githubusercontent.com/lnbits/example/main/templates/example/index.html]. Satspay wires `GET /` → `index` (authed tile page) and `GET /{charge_id}` → `index_public` via `add_api_route` [CITED: https://raw.githubusercontent.com/lnbits/satspay/main/views.py].
- Vendor bundle includes `vue.global.prod.js`, `quasar.umd.prod.js`, `axios`, `vue-router`, `vue-i18n`, `qrcode.vue.browser.js`, `vue-qrcode-reader`, `showdown.js`, `purify.js`, `nostr.bundle.js`, `chart.umd.js` [VERIFIED: `vendor.json`]. `bundle.min.*` used when `settings.bundle_assets` [VERIFIED: `helpers.py:82-92`].
- Public pages should NOT extend `base.html` — it mounts `lnbits-header`, drawer, wallet components keyed off `g.user`/`g.isPublicPage` [VERIFIED: `base.html:50-85`]. 02-UI-SPEC §A mandates standalone documents with restrictive CSP — write a minimal `public_*.html` template (own `<html>` doc, only needed vendor assets, e.g., vue+quasar+axios, or even no-JS forms + progressive enhancement) rather than inheriting admin chrome. [ASSUMED: CSP headers must be set per-response by the extension — no host CSP middleware exists.]

### Settings & Configuration

- Host settings: pydantic `BaseSettings`, `env_file=".env"`, `case_sensitive=False`, **no `env_prefix`** — env names are full field names (`LNBITS_EXTENSIONS_PATH`, `LNBITS_DATABASE_URL`, `LNBITS_EXTENSIONS_MANIFESTS`, `LNBITS_ALLOWED_CURRENCIES`, `LNBITS_EXCHANGE_RATE_CACHE_SECONDS`…) [VERIFIED: `settings.py:1311-1316,1149,1193,89,327,399`]. Mutable `EditableSettings` are admin-writable; `ReadOnlySettings` only via env/.env.
- **No extension-settings hook exists** — `INFINITEMARKETS_*` must be a separate extension-side `pydantic BaseSettings(env_prefix="INFINITEMARKETS_")` or `os.environ` reads with strict startup validation (spec §12: `INFINITEMARKETS_MASTER_KEYS`, `INFINITEMARKETS_ACTIVE_KEY_VERSION`, `INFINITEMARKETS_PRIVACY_KEY` — reject missing/duplicate/short/malformed before merchant services activate). [ASSUMED for the exact validation API; the host offers no registry for it.]
- `settings.lnbits_running` gates all permanent-task loops [VERIFIED: `task_manager.py:146,387`]; `settings.to_public()` powers `SETTINGS` template global [VERIFIED: `helpers.py:79`].
- Extension activation state also keyed by `settings.lnbits_deactivated_extensions` / `lnbits_admin_extensions` / `is_admin_extension` [VERIFIED: `settings.py:1332-1336`; `middleware.py:42`; `decorators.py:464-476`] — `infinitemarkets` is NOT an admin extension by default; merchant-auth model is host-user-scoped, 1:1 merchant per user (spec decision).

### FX Boundary (VERIFIED: `.cache/lnbits/lnbits/utils/exchange_rates.py`)

- `btc_rates(currency) -> list[tuple[str, float]]` — per-provider (name, price) tuples, trimmed-mean filtered, providers from `settings.lnbits_exchange_rate_providers`; 3s httpx timeout per provider [VERIFIED: `:238-289`]. **Best fit for spec provenance**: per-provider names travel with the quote.
- `btc_price` → optional price-aggregator (`lnbits_price_aggregator_*`) with provider fallback; returns mean float (`:292-326`).
- `get_fiat_rate_and_price_satoshis` wraps `btc_price` in `cache.save_result` keyed `btc-price-{currency}` TTL `lnbits_exchange_rate_cache_seconds` (default 60s) (`:329-336`); `fiat_amount_as_satoshis(amount, currency) -> int` raises `ValueError` on missing rate (`:344-348`).
- `allowed_currencies()` restricts to `settings.lnbits_allowed_currencies` when configured (`:180-187`); `btc_rates` raises `ValueError` for disallowed currency (`:239-240`).
- Extension boundary per spec: convert float→`Decimal` once at the adapter, own freshness/provenance/persistence; `btc_rates` already returns provider names — persist `provider_names`, fetched_at, and the rate. Host cache is process-local (`lnbits.utils.cache`) — extension must persist quote snapshots per order anyway (spec §16 provenance).

### Email Boundary (VERIFIED: `.cache/lnbits/lnbits/core/services/notifications.py`)

- `send_email(server, port, username, password, from_email, to_emails: list, subject, message) -> bool` — validates addresses (`is_valid_email_address`, raises `ValueError`), `smtplib.SMTP` → `starttls()` → `login` → `sendmail`, executed via `asyncio.to_thread`; returns `True`/`False` (False on any send failure — never raises SMTP errors) [VERIFIED: `:205-240`].
- Config source is extension-owned or host `lnbits_email_notifications_*` settings [VERIFIED: `settings.py` fields used at `:186-198`]. Spec fixes "host-SMTP boolean boundary" — plan should decide whether to reuse host SMTP settings or `INFINITEMARKETS_SMTP_*`; the helper's signature takes all params explicitly so either works.
- Per-recipient semantics: `to_emails` is a list sent in one `To:` header — spec requires per-recipient rows/emails (privacy: don't co-address buyers); call once per recipient.

### Nostr SDK Surface (pinned `nostr-sdk==0.44.8`, verified via installed wheel introspection)

- `Client` methods: `add_relay`, `add_relay_with_opts`, `connect`, `connect_relay`, `send_event`, `send_event_to(urls: list[RelayUrl], event: Event) -> SendEventOutput`, `send_event_builder`, `send_private_msg_to`, `send_msg_to`, `fetch_events`, `fetch_events_from`, `stream_events*`, `try_connect`, `wait_for_connection`, `disconnect*` [VERIFIED: `uv run python` introspection of `nostr_sdk.Client`].
- `SendEventOutput(id: EventId, success: list[RelayUrl], failed: dict[RelayUrl, str])` — the per-relay ACK evidence object for the outbox publisher [VERIFIED: introspection `inspect.signature`].
- `LocalRelay(builder: RelayBuilder)` with `.url`, `.run()`, `.shutdown()`, `.notify_event` — local relay for tests [VERIFIED: introspection]; the harness already ships a websockets-based `LocalRelay` fixture [VERIFIED: `harness/relay.py:45-103`].
- `Nip19Coordinate.from_bech32` parses naddr — used for NIP-89 local resolution [VERIFIED: `harness/nip89.py:82` `coord = Nip19Coordinate.from_bech32(naddr.strip())`].
- Event construction/verification: `Event`, `UnsignedEvent`, `EventBuilder`, `Keys`, `EventId`; NIP-44 via `nip44_*` and gift wrap `gift_wrap` (Phase 1 verified `seal_rumor`/`wrap_order_copy`/`unwrap_gift_wrap` in `harness/sdk.py:197-269`).
- Release A needs only: `Keys`/`EventBuilder` (build+sign kinds 0/30402/30405/30406/31989/31990), `Client`+`RelayUrl`+`send_event_to` (targeted per-relay publish), `Nip19Coordinate` (naddr parse), `LocalRelay`/`RelayBuilder` (tests). NIP-17 `gift_wrap` plumbing stays dormant per deferred scope.

### In-Host Testing Pattern (VERIFIED: `harness/host.py`, `tests/qualification/`)

- `host_app` fixture: isolated `data_folder`, `settings.lnbits_data_folder`, `settings.lnbits_backend_wallet_class = "FakeWallet"`, `settings.first_install = True`, `os.chdir(host_checkout_dir())` (host resolves paths relative to CWD), `create_app()` + `asgi_lifespan.LifespanManager(startup_timeout=30)`, `first_install(...)` creates super user [VERIFIED: `harness/host.py:35-90`].
- `create_test_wallet` → wallet for `pay_invoice`-driven settlement [VERIFIED: `harness/host.py:95-100`]; `FakeWallet` funding source implements `create_invoice`/`paid_invoices_stream` over an asyncio queue [VERIFIED: `.cache/lnbits/lnbits/wallets/fake.py:33-90`].
- HTTPX: `httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=...)`.
- Phase 2 additions: register `infinitemarkets` by placing `config.json` + package under a temp `LNBITS_EXTENSIONS_PATH` (or symlink into `lnbits/extensions/`) before `create_app()` — the startup scan + migration path then exercises the real loader, no mocks. `[ASSUMED]` — exact fixture mechanics to be proven in plan 02-01's first task.
- Session-scoped event loop caveat: host singletons (`task_manager`, `db` engines, `settings`) are bound at import/loop — the harness keeps one long-lived loop [VERIFIED: `test_p0_03_host_contract.py:47` comment "assume ONE long-lived event loop"].

</architecture_patterns>

<dont_hand_roll>
## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Invoice creation | Own payment plumbing | `create_invoice(..., extension="infinitemarkets", external_id=...)` | Host handles funding-source quirks, fiat conversion, wallet caps, `CreatePayment` persistence [VERIFIED: `payments.py:261-376`] |
| Settlement detection | Custom polling only | `register_invoice_listener` + `external_id` reconciliation | Listener = latency; reconciliation = durability (P0-03 proved both) |
| Task supervision | Own `asyncio` loops | `task_manager.create_permanent_task(func, name, interval)` | Restart-on-failure, `lnbits_running` gating, owned-handle cancellation |
| Extension persistence | ORM/raw SQLAlchemy | `Database("ext_infinitemarkets")` + `insert`/`update`/`execute` + compat helpers | Schema/file namespacing, dialect portability, uninstall cleanup |
| Migration runner | Alembic/own runner | `migrations.py` `mNNN_*` + host `run_migration` | Automatic at startup, `dbversions` bookkeeping |
| FX rates | Direct provider calls | `btc_rates`/`get_fiat_rate_and_price_satoshis` | Provider fan-out, outlier filtering, cache — extension only adds Decimal/provenance wrap |
| Email | Own SMTP client | `send_email` host helper | Boolean boundary, address validation, thread offload |
| Template/static serving | Own file endpoints | `template_renderer` + `infinitemarkets_static_files` mount + `static_url_for` | Cache-busted URLs, vendor reuse, host mount mechanics |
| List endpoint filtering | Hand query params | `Filters`/`FilterModel`/`parse_filters` | Validated operators, pagination, `search` across `__search_fields__` |
| BOLT11 parse/verify | Own decoder | `bolt11.decode` (host dep) | Same decoder the host trusts (`payments.py:352`) |
| naddr parsing | bech32 by hand | `Nip19Coordinate.from_bech32` | nostr-sdk canonical (harness already uses it) |

**Key insight:** the pinned host already provides every risky primitive (payments, tasks, DB dialecting, templates, FX, SMTP). Extension code should be *orchestration + invariants*, not reimplementation — every hand-rolled equivalent is a new silent-failure surface the harness explicitly tested against.

</dont_hand_roll>

<common_pitfalls>
## Common Pitfalls

### Pitfall 1: `create_invoice` unknown-vs-failed ambiguity
**What goes wrong:** treating every `InvoiceError`/network exception as "invoice not created" and reissuing.
**Why it happens:** backend timeout/5xx → `InvoiceError(status="pending")` is indistinguishable from "invoice created but response lost"; `create_payment` may even succeed while the caller saw an error.
**How to avoid:** map `status=="pending"` (and any non-InvoiceError exception mid-call) to `creation_unknown`; reconcile by exact `external_id`; never auto-reissue (spec §8.3, PAY-01).
**Warning signs:** duplicate `apipayments` rows sharing an `external_id` (possible — column is only indexed, not unique [VERIFIED: `migrations.py:807-816`]).

### Pitfall 2: `Connection.execute` auto-commit inside saga steps
**What goes wrong:** reservation claim + order CAS + payment projection insert need one atomic tx, but each `conn.execute` commits independently (`db.py:288`).
**How to avoid:** drive the transaction through the underlying `conn.conn` (AsyncConnection) or structure claims as single-statement CAS/`UPDATE ... WHERE stock >= n`; mirror `harness/tx.py` (SQLite `BEGIN IMMEDIATE`, PG lock-select→update→fetch in one tx).
**Warning signs:** stock claimed but order row unchanged under concurrent checkout tests (INV-01).

### Pitfall 3: HTML stripping of stored payloads
**What goes wrong:** product markdown, event JSON, or addresses containing `<tag>`-looking text get silently rewritten on `execute`/`fetch` param binding (`db.py:147-162`).
**How to avoid:** persist structured payloads via `insert`/`update` (no `rewrite_values`) or encode (JSON with escaped content); never pass user markdown through raw `execute` params expecting fidelity.
**Warning signs:** round-trip test shows `<b>` removed from a description.

### Pitfall 4: Per-`Database` lock serialization
**What goes wrong:** `db.connect()` serializes on `self.lock` (`db.py:320,325`) — outbox publisher + email sender + reconciliation sharing one `Database` object effectively serialize all extension DB access.
**How to avoid:** separate `Database("ext_infinitemarkets")` handles per worker (each gets own engine+lock), as the QualWorker model did; measure before optimizing.
**Warning signs:** workers' DB phases never overlap in timing logs.

### Pitfall 5: Trusting invoice listener delivery
**What goes wrong:** listener registration is in-memory; restart misses settlements; `_invoice_dispatcher` fans out to *all* listeners unfiltered.
**How to avoid:** startup reconciliation by exact `external_id` before readiness; callback filters `extension`/`external_id`/wallet/amount before acting; idempotent settlement (P0-03, spec §8.4).
**Warning signs:** settled-but-unprocessed orders after app restart test.

### Pitfall 6: `infinitemarkets_start` async def
**What goes wrong:** startup-restore path calls `ext_start_func()` without awaiting (`app.py:486-492`) → coroutine never runs, silent no-op.
**How to avoid:** `def infinitemarkets_start()` synchronous; `async def` only safe for the admin-activation path which awaits coroutine functions (`extensions.py:730-733`).
**Warning signs:** tasks registered on admin toggle but not on process boot.

### Pitfall 7: Cookie-auth mutation without Origin check
**What goes wrong:** host has CORS `*` and no CSRF middleware; cookie session + `Origin: evil` succeeds unless extension rejects.
**How to avoid:** extension dependency that requires `Origin`/`Sec-Fetch-Site` same-origin (or absent-Origin only for non-cookie auth) on all mutating merchant routes — as `authprobe.py:163` did.
**Warning signs:** P0-12-style cross-origin probe returning 2xx.

### Pitfall 8: Token/PII leakage into host audit + logs
**What goes wrong:** `AuditMiddleware` may record path params, query params, and request bodies (`middleware.py:180-198`); loguru logs full payment objects.
**How to avoid:** bearer token in `X-Order-Token` header + URL fragment only (never path/query/body); redact in extension logs; evaluate whether checkout bodies carry PII under `lnbits_audit_log_request_body` (open question).
**Warning signs:** token string appearing in audit/log output.

### Pitfall 9: `template_renderer` folder semantics / template namespacing
**What goes wrong:** `additional_folders` entries are resolved under `{extensions_path}/extensions/{name}` — template lookup names and the on-disk `templates/` layout must agree; getting this wrong yields `TemplateNotFound` only at first render.
**How to avoid:** mirror the example extension layout exactly (`templates/{ext_id}/...` inside the ext dir) and spike-render one template in the first 02-01 task; verify lookup name form against a real ext `views.py` (open question).
**Warning signs:** `jinja2.exceptions.TemplateNotFound` on the index route.

### Pitfall 10: Treating relay ACK as payment/publication truth
**What goes wrong:** conflating `SendEventOutput.success` relays with durable business state; or UI labeling ACK as "paid".
**How to avoid:** outbox rows record per-relay evidence (`SendEventOutput.success`/`failed` verbatim); settlement truth only from host payment rows; UI spec labels ACKs "delivery evidence" [VERIFIED: `02-UI-SPEC.md:235`].
**Warning signs:** health dashboard implying "published == settled".

</common_pitfalls>

<code_examples>
## Code Examples

### Extension module contract (`infinitemarkets/__init__.py`)
```python
# Verified convention — mirror of lnbits/example + lnbits/satspay __init__.py
# [CITED: https://raw.githubusercontent.com/lnbits/example/main/__init__.py]
# [CITED: https://raw.githubusercontent.com/lnbits/satspay/main/__init__.py]
from fastapi import APIRouter
from .db import db                      # Database("ext_infinitemarkets")
from .views import infinitemarkets_generic_router
from .views_api import infinitemarkets_api_router

infinitemarkets_ext: APIRouter = APIRouter(prefix="/infinitemarkets", tags=["infinitemarkets"])
infinitemarkets_ext.include_router(infinitemarkets_generic_router)
infinitemarkets_ext.include_router(infinitemarkets_api_router)

infinitemarkets_static_files = [
    {"path": "/infinitemarkets/static", "name": "infinitemarkets_static"},
]

_owned_tasks: list = []

def infinitemarkets_start():                # SYNC — startup path never awaits
    from lnbits.tasks import task_manager
    _owned_tasks.append(task_manager.register_invoice_listener(
        on_settled_payment, name="infinitemarkets"))
    for fn, name, interval in _WORKERS:  # e.g. outbox_publisher, interval=5
        _owned_tasks.append(task_manager.create_permanent_task(
            fn, name=f"infinitemarkets.{name}", interval=interval))

def infinitemarkets_stop():                 # sync or async — host awaits if coroutine
    from lnbits.tasks import task_manager
    for t in _owned_tasks:
        task_manager.cancel_task(t)
    _owned_tasks.clear()

__all__ = ["db", "infinitemarkets_ext", "infinitemarkets_start",
           "infinitemarkets_static_files", "infinitemarkets_stop"]
```

### Invoice creation per spec §8.3 (verified signature)
```python
# [VERIFIED: .cache/lnbits/lnbits/core/services/payments.py:261-278]
from lnbits.core.services.payments import create_invoice
payment = await create_invoice(
    wallet_id=wallet.id,
    amount=order.total_sat,
    currency="sat",
    memo="Infinitemarkets order",
    expiry=RESERVATION_TTL,
    extra={"tag": "infinitemarkets", "order_id": order.id},
    extension="infinitemarkets",
    external_id=f"infinitemarkets:{order.id}",
)
# InvoiceError.status == "pending"  → creation_unknown (reconcile, never reissue)
# InvoiceError.status == "failed"   → definite failure (release reservation)
# [VERIFIED: .cache/lnbits/lnbits/exceptions.py:22-25]
```

### Exact external_id reconciliation query (harness-proven)
```python
# [VERIFIED: tests/qualification/test_p0_03_host_contract.py:87-98]
from lnbits.core.crud import get_payments
from lnbits.core.models import PaymentFilters
from lnbits.db import Filter, Filters
rows = await get_payments(filters=Filters(
    filters=[Filter.parse_query("external_id", [external_id], PaymentFilters)],
    model=PaymentFilters))
# len(rows) > 1 → critical manual exception (external_id is indexed, NOT unique)
```

### Settlement callback self-filter (listener receives EVERY settled payment)
```python
# [VERIFIED: task_manager.py:160-175,444-450 — per-listener queue, unfiltered fan-out]
async def on_settled_payment(payment) -> None:
    if payment.extension != "infinitemarkets":
        return
    if not (payment.external_id or "").startswith("infinitemarkets:"):
        return
    # then: verify wallet_id, amount, bolt11 payment_hash/expiry,
    # extra.tag, order idempotency before consuming reservation
```

### Migration skeleton
```python
# [VERIFIED: helpers.py:48-69 — ^m(\d\d\d)_ naming, dbversions tracking]
# [CITED: https://raw.githubusercontent.com/lnbits/satspay/main/migrations.py]
from lnbits.db import Database

async def m001_initial(db: Database):
    await db.execute(f"""
        CREATE TABLE infinitemarkets.orders (
            id TEXT PRIMARY KEY,
            ...
            created_at TIMESTAMP NOT NULL DEFAULT {db.timestamp_now}
        )
    """)
```

### Per-relay publish evidence
```python
# [VERIFIED: nostr_sdk.Client.send_event_to signature via introspection]
out: SendEventOutput = await client.send_event_to(
    urls=[RelayUrl.parse(r) for r in relay_urls], event=event)
# out.success: list[RelayUrl]; out.failed: dict[RelayUrl, str]
# → persist verbatim per-relay rows (ack/nack + error) as evidence
```

</code_examples>

<sota_updates>
## State of the Art (2025-2026, this codebase's horizon)

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `lnbits.tasks.create_permanent_unique_task` helpers | `task_manager.create_permanent_task` / `register_invoice_listener` | host ≥v1.x | deprecated path; new code uses `task_manager` [VERIFIED: `lnbits/tasks.py:1-89`] |
| Extension `websocket` handlers common | spec fixes JSON-only request bodies + APIRouter | PINS §5 disposition | no `HTTPEndpoint`, no `FileResponse`/`StaticFiles` in extension code |
| Extensions mutating global state freely | `check_user_extension_access` per-request enforcement | pinned host | ext routes get enabled-check for free when authed [VERIFIED: `decorators.py:485-503`] |
| WASM extensions | first-class in this host (`is_wasm_extension_id`, wasm perms) | v1.6.x | `infinitemarkets` stays a Python extension; wasm path ignored |

**New tools/patterns to consider:**
- `ExtensionBackgroundPaymentGrant`/`ExtensionWalletPaymentsWatchGrant` models exist in the host (`models/extensions.py:160-204`) — host-side grant model for background payments/watchers. **[ASSUMED]** relevance: likely wiring for extension permissions UI; confirm whether `config.json` `permissions` entries gate anything at runtime for Python extensions (open question — likely informational for Python exts, enforced for wasm).

**Deprecated/outdated:**
- `get_current_extension_name` helper — deprecated in favor of literal name [VERIFIED: `helpers.py:100-124`].
- `payment.check_status()` — deprecated; use `check_payment_status` service [VERIFIED: `models/payments.py:143-148`].
- Old `tasks.py` module-level helpers — deprecated shims.

</sota_updates>

<phase_requirements>
## Phase Requirement → Research Support Map

| Req | What research established |
|-----|---------------------------|
| MERC-01 | Host `check_user_exists` gives merchant session (1:1 merchant per user is spec-side); `Wallet.user`/`can_receive_payments`/`source_wallet_id` for wallet binding + ownership revalidation [VERIFIED: `models/wallets.py:114-141,189-198`]; `INFINITEMARKETS_*` config has no host hook → own `BaseSettings` module; deactivation kills `/{ext}` routes via middleware (`middleware.py:41-47`) → graceful tombstone flow required |
| CAT-01/02 | Extension `Database` + `mNNN_*` migrations + compat helpers (`serial_primary_key`, `big_int`, `timestamp_now`) support §4 schema; `insert`/`update` vs `execute` payload-fidelity pitfall informs CRUD shape; `Filters`/`parse_filters` for admin lists |
| PUB-01 | `Client.send_event_to` + `SendEventOutput(success, failed)` = per-relay evidence; outbox rows + claim fencing map to `create_permanent_task` workers (no global singleton for publishers per spec §10); `Nip19Coordinate`/EventBuilder for deterministic events |
| PUB-02 | Per-relay rows + outbox state pills map directly onto `SendEventOutput` fields + B2 dashboard spec; middleware deactivation + restart semantics inform health display |
| WEB-01 | `index_public`-style public endpoints + standalone templates (not `base.html`); naddr parse via `Nip19Coordinate.from_bech32` [VERIFIED: `harness/nip89.py:82`]; `/infinitemarkets/p/{naddr}` route shape per UI-SPEC A1 |
| WEB-02 | JSON-only bodies; `Idempotency-Key` header contract; `X-Order-Token` header-only + fragment URL (never path/query — audit logs query/path params [VERIFIED: `middleware.py:186-190`]); `no-store`/`no-referrer` headers per authprobe |
| PAY-01 | `create_invoice` full contract: kw-only args, `InvoiceError.status` pending/failed split, `external_id` persisted non-unique → own projection uniqueness; deterministic `infinitemarkets:{id}` |
| PAY-02 | Settlement via listener (self-filtered) + reconciliation by `external_id`; `Payment` fields incl. `sat`, `is_expired`, `payment_hash`, `bolt11`; `bolt11.decode` verify; `update_payment_success_status` does not re-dispatch → reconciliation covers poll-settled payments |
| INV-01 | `db.lock` serialization + `execute` autocommit → single-statement CAS / explicit `conn.conn` tx; SQLite `BEGIN IMMEDIATE` + PG lock-select patterns from harness `tx.py` |
| ORD-01 | `check_user_exists` + extension-scoped queries; `Filters`/`parse_filters` for list/search; `check_user_extension_access` gives enabled-enforcement on authed routes |
| NOTF-01 | `send_email(...)->bool` boolean boundary; per-recipient calls (no co-addressing); `to_thread` offload; validate addresses pre-queue via `is_valid_email_address` |
| SEC-01 | Origin enforcement extension-side (no host CSRF); CORS `*` untrusted; audit-middleware leakage surface; token-in-header/fragment; `rewrite_values` strip behavior; topology refusal = `DB_TYPE`/`db.type` checks at startup [VERIFIED: `db.py:20-46`]; owned-handle task cancellation |
| UI-01/02/03 | Host vendor Vue/Quasar UMD same-origin; `base.html` blocks for admin; standalone public docs + `.gm-public` token scoping per UI-SPEC §A/Boundary; `static_url_for` cache-busting; `infinitemarkets_static_files` mount for extension JS/CSS |

</phase_requirements>

<open_questions>
## Open Questions

1. **`{code}_static_files` vs PINS "no StaticFiles in extension code"** — RESOLVED (plan 02-01): the PINS ban covers extension code instantiating `FileResponse`/`StaticFiles`; the declarative `infinitemarkets_static_files` list is host-mounted and IS the convention — declared, disposition recorded in the 02-01 summary.

2. **`template_renderer` template-name ↔ on-disk layout** — RESOLVED (plan 02-01 Task 1 spike): render `index.html` through the real loader before committing the layout; verified rule recorded in the 02-01 summary.

3. **Host audit middleware vs checkout PII** — RESOLVED (plan 02-01 Task 2 step 4b): deployment-level disposition — qualified deployments MUST keep `lnbits_audit_log_request_body`/`_query_params`/`_path_params` disabled; the extension surfaces a blocking admin warning + startup log when capture is enabled, and a runtime test asserts both postures. This satisfies spec §5's audit-capture MUST.

4. **Extension `permissions`/`ExtensionBackgroundPaymentGrant` runtime effect for Python extensions** — RESOLVED (plan 02-01 Task 1): `permissions` block included in `config.json` for transparency; runtime enforcement verified during the install spike and recorded in the 02-01 summary.

5. **Dev/test install mechanics** — RESOLVED (plan 02-01 Task 1): temp `LNBITS_EXTENSIONS_PATH` + `config.json` + on-disk package copy in the host fixture — exercises the real discovery path end to end.

6. **`send_event_to` semantics under partial connectivity** — RESOLVED (plan 02-02 Task 1): early `LocalRelay` + dead-URL probe pins behavior before the publisher depends on it; publish evidence stays verbatim.

7. **First-plan vs later-plan split of `migrations.py`** — RESOLVED (plan-level increments, adjusted): `m001` (02-01) = merchant/catalog/outbox-intent + task/rate tables; `m002` (02-03) = orders/payments/inventory/idempotency/email cluster + schema-only `inbox_events`/`order_messages`; no migration in 02-02/02-04; `peer_relays`/`relay_cursors`/`migration_jobs` defer to Phase 3/4.

</open_questions>

<sources>
## Sources

### Primary (HIGH confidence — pinned checkout `.cache/lnbits` @ `e336fe14b841`)
- `lnbits/app.py:102,187,196,280-352,411-568` — extension discovery, route registration, static mount, start-task call, middleware wiring
- `lnbits/core/models/extensions.py:111-141,259-282,516-566,860-942` — `ExtensionConfig`, `Extension.module_name`, `ext_dir`, `config.json` parsing
- `lnbits/core/services/extensions.py:639-739` — activate/deactivate/uninstall + start/stop hook contract
- `lnbits/core/helpers.py:24-69,89-133` — `migrate_py_extension_database`, `run_migration`, `dbversions`
- `lnbits/db.py:20-46,134-410` — dialects, `Database`/`Connection`, compat, `rewrite_values`, `Filters`
- `lnbits/task_manager.py:63-175,381-450` — `TaskManager` API surface
- `lnbits/core/services/payments.py:261-376,379-407,906-960,1122-1162` — `create_invoice`, pending-update, success-status, producer→queue
- `lnbits/core/crud/payments.py:37-225` — payment lookup/query helpers
- `lnbits/core/models/payments.py:80-192` — `Payment`, `PaymentFilters`
- `lnbits/core/migrations.py:807-816` — `external_id` index (non-unique)
- `lnbits/exceptions.py:16-26,71-165` — `InvoiceError`/`PaymentError` status, exception mapping
- `lnbits/decorators.py:180-225,324-335,390-454,457-503` — auth deps, `parse_filters`, per-path ext access
- `lnbits/middleware.py:23-110,180-219` — installed-ext gate, redirects, audit logging, rate limit
- `lnbits/helpers.py:56-97,176-181` — `template_renderer`, `static_url_for`, `is_valid_external_id`
- `lnbits/templates/base.html` — blocks/globals; `lnbits/static/vendor.json` — vendored Vue/Quasar stack
- `lnbits/settings.py:89,327,399,1149-1167,1193,1311-1336` — env/settings model
- `lnbits/utils/exchange_rates.py:180-348` — FX provider API + cache
- `lnbits/core/services/notifications.py:183-240` — `send_email` boolean boundary
- `lnbits/wallets/fake.py:33-90` — `FakeWallet` test funding source

### Primary — project repo
- `PINS.md` — pins, wheel sha256s, Dependabot disposition
- `docs/technical-specification.md` — §§4–18, 21 (saga, tasks, schema, gates)
- `.planning/phases/02-release-a-safe-web-commerce/02-CONTEXT.md`, `02-UI-SPEC.md`
- `harness/host.py:35-100` — in-host fixture pattern; `harness/authprobe.py:117-180` — origin/token probe; `harness/relay.py`, `harness/nip89.py`, `harness/sdk.py` — relay/naddr/SDK fixtures
- `tests/qualification/test_p0_03_host_contract.py:58-200` — create_invoice/listener/external_id probes
- `pyproject.toml:9,12,32` — dep pins incl. path-sourced lnbits

### Secondary (MEDIUM confidence — external, fetched this session)
- `https://raw.githubusercontent.com/lnbits/example/main/__init__.py`, `config.json`, `manifest.json`, `templates/example/index.html` — canonical extension layout
- `https://raw.githubusercontent.com/lnbits/satspay/main/__init__.py`, `views.py`, `migrations.py` — real-extension conventions (routers, static files, migrations)

### Tertiary (LOW confidence)
- nostr-sdk API surface — verified by runtime introspection of installed wheel (authoritative for the pin, but not source-cited)
</sources>

<metadata>
## Metadata

**Research scope:**
- Core technology: LNbits `v1.6.2-rc1` extension contract end-to-end (discovery, routes, lifecycle, DB, payments, tasks, templates, settings, FX, SMTP)
- Ecosystem: `nostr-sdk 0.44.8` surface needed for Release A; host vendor frontend
- Patterns: extension layout, migrations, saga/payment correlation, outbox, auth/origin, testing fixture
- Pitfalls: DB-layer semantics (lock, autocommit, HTML strip), listener non-durability, hook sync/async asymmetry, middleware leakage

**Confidence breakdown:**
- Standard stack: HIGH — all pins verified in `PINS.md`/`pyproject.toml`/`uv.lock`
- Architecture: HIGH — every host mechanism read at source with line refs
- Pitfalls: HIGH — derived from pinned source + Phase 1 probes
- Code examples: HIGH — mirror verified host/extension conventions; MEDIUM for template-name detail (open question 2)

**Research date:** 2026-09-20
**Valid until:** 2026-10-20 (pinned host — stable until re-pin)
</metadata>

---

*Phase: 02-release-a-safe-web-commerce*
*Research completed: 2026-09-20*
*Ready for planning: yes*
