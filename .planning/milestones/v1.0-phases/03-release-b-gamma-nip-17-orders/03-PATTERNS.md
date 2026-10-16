# Phase 3: Release B — Gamma NIP-17 Orders — Pattern Map

**Mapped:** 2026-09-28
**Purpose:** for every file to be created/modified, the closest existing code analog, a concrete excerpt, and exactly what the new code must mimic (tx/lease semantics, owner-scoping, CSRF/Origin, content-hash versioning, DomainTransaction usage).

---

## File Inventory (from 03-CONTEXT.md + 03-RESEARCH.md)

| # | File | Action | Role |
|---|------|--------|------|
| 1 | `infinitemarkets/keystore.py` | MODIFY | `nip17_wrap`/`nip17_unwrap` implementation (stubs at lines 320–324) |
| 2 | `infinitemarkets/migrations.py` | MODIFY | m006+: `peer_relays`, `relay_cursors`, `buyer_sessions`, `nostr_challenges` (or bucket reuse), sender blocklist, `order_messages` read markers, `merchants.inbox_state`, settings rows |
| 3 | `infinitemarkets/services/inbox.py` | NEW | §8.5 admission + durable processing pipeline + cursor advance |
| 4 | `infinitemarkets/services/order_messages.py` | NEW | rumor⇄domain adapters, `order_msg` descriptors, dual-copy intent enqueue, threading |
| 5 | `infinitemarkets/services/peer_relays.py` | NEW | buyer kind-10050 discovery + 24h cache + no-route policy |
| 6 | `infinitemarkets/services/nostr_auth.py` | NEW | NIP-07 challenge/session + per-relay NIP-42 auth state |
| 7 | `infinitemarkets/services/storefront_mode.py` | NEW | `storefront_mode` setting + gate helpers (checkout/pages/publish) |
| 8 | `infinitemarkets/services/transport.py` | MODIFY | `subscribe`/`handle_notifications`, AUTH state, DNS egress checks |
| 9 | `infinitemarkets/services/outbox.py` | MODIFY | `order_msg` publish branch (decrypt descriptor → wrap ×2 → per-copy evidence) |
| 10 | `infinitemarkets/services/relay.py` | MODIFY | inbox-direction targets, seeding, health + auth-status surface, retry surface |
| 11 | `infinitemarkets/services/tasks.py` | MODIFY | `inbox_processor` (leased) + subscription lifecycle registration |
| 12 | `infinitemarkets/services/settlement.py` | MODIFY | reconcile `received`/`validated` inbox rows, type-2 re-enqueue, retention extension |
| 13 | `infinitemarkets/views_public_api.py` | MODIFY | `/nostr/*` endpoints (challenge/verify/orders/claim/logout) + storefront-mode gates on `/quote`, `/checkout` |
| 14 | `infinitemarkets/views_api.py` | MODIFY | Messages / Rejected-intake / relay-auth / blocklist / storefront-mode admin APIs |
| 15 | `infinitemarkets/views.py` | MODIFY | mode-gated public pages, Nostr-only notice, sign-in affordance ctx |
| 16 | `infinitemarkets/static/infinitemarkets/js/admin_messages.js` | NEW | fifth nav surface — split workspace (mirrors `admin_orders.js`) |
| 17 | `infinitemarkets/static/infinitemarkets/js/public_nostr.js` | NEW | NIP-07 sign-in, order list, claim flow, Showcase guidance |
| 18 | `infinitemarkets/static/infinitemarkets/js/admin_settings.js` | MODIFY | inbox relays, storefront-mode panel, relay auth states |
| 19 | `infinitemarkets/static/infinitemarkets/js/admin_app.js` | MODIFY | `gmNav('messages')` case + unread badge plumbing |
| 20 | `infinitemarkets/templates/infinitemarkets/admin.html` | MODIFY | Messages nav item (fifth), Messages/Rejected/mode surfaces, script include |
| 21 | `infinitemarkets/templates/infinitemarkets/public_*.html` | MODIFY | sign-in affordance, Showcase guidance, Nostr-only notice (new template) |
| 22 | `tests/runtime/test_nip17_inbox.py`, `test_nip17_outbox.py`, `test_nostr_signin.py`, `test_storefront_modes.py`, `test_intake_abuse.py` | NEW | per 03-VALIDATION.md Wave-0 list |
| 23 | `tests/e2e/*.spec.ts` | MODIFY | Messages surface, shop-mode panel, sign-in flows |
| 24 | `harness/relay.py` | MODIFY | extend `LocalRelay` with REQ/EOSE serving + gated auth modes |

### Schema truth corrections (verified against `migrations.py`)

- **`peer_relays` and `relay_cursors` do NOT exist yet.** CONTEXT.md §Reusable Assets says they "landed schema-only (m002)" — actually the m002 docstring (migrations.py:451–452) explicitly defers them: *"peer_relays, relay_cursors, and migration_jobs defer to Phase 3/4 migrations."* They must be **created** in m006.
- `inbox_events` (migrations.py:603–622) and `order_messages` (migrations.py:561–578) **do** exist schema-only, plus `UNIQUE(outer_event_id)` and `ix_inbox_rumor` (704–707), `ix_orders_nostr_external_id` (699–703), `orders.buyer_pubkey_enc/buyer_pubkey_hash`, `orders.receipt_verified`, `orders.source_event_id`, `outbox_events.payload_enc`, `relay_publications.delivery_copy`.
- `settings.peer_relay_ttl` (86400) and `settings.inbox_max_event_bytes` (32768) **already exist** (settings.py:144–145, 179–180) — Phase-3-forward config keys are wired.
- `harness/inbox_outbox.py` and `harness/relay_fixtures` (named in CONTEXT.md canonical refs) **do not exist**. The real executable references are `harness/sdk.py` (unwrap chain + dual-copy), `harness/relay.py` (`LocalRelay`), `harness/saga.py` (crash drills). Planner must not assume the named files exist.

---

## Per-Area Patterns

### 1. `keystore.py` — `nip17_wrap` / `nip17_unwrap`

**Closest analog:** `sign_event` + `_keys`/`_load_nsec` — the only permitted crypto entry shape (decrypt inside op, release in `finally`).

Excerpt — `infinitemarkets/keystore.py:166–187`:

```python
async def _keys(self, merchant_id: str) -> Keys:
    nsec = await self._load_nsec(merchant_id)
    try:
        return Keys.parse(nsec.hex())
    finally:
        del nsec

async def sign_event(self, merchant_id: str, unsigned: UnsignedEvent):
    """Sign ``unsigned`` with the merchant key; key is released on exit."""
    keys = await self._keys(merchant_id)
    try:
        signer = NostrSigner.keys(keys)
        return await signer.sign_event(unsigned)
    finally:
        del keys
```

**Mimic:** same `try/finally: del keys` discipline. `nip17_wrap` = `EventBuilder.seal(signer, PublicKey.parse(recipient), unsigned_rumor)` (async, returns EventBuilder) → `.sign(signer)` → `gift_wrap_from_seal(recipient, seal)` — **synchronous in 0.44.8** (verified `harness/sdk.py:210–216`). `nip17_unwrap` = the **explicit §8.5 chain**, NOT `UnwrappedGift.from_gift_wrap` — copy `harness/sdk.py:259–368` `unwrap_gift_wrap` stage-for-stage: outer kind 1059 + `verify()` → exactly one `p` == recipient → `nip44_decrypt` → seal kind 13 + empty tags + `verify()` → `nip44_decrypt` → rumor unsigned + canonical-id recompute (`canonical_rumor_id`, sdk.py:232–246 — rebuild via `EventBuilder`, never hand-rolled sha256) + seal-author match + kind ∈ {14,16,17} + **raw-JSON duplicate-tag check** (sdk.py:348–361 — SDK parser dedupes tags, so count tag names on `json.loads` output). Rejections raise a bounded-reason exception like `WrapRejection` (sdk.py:141–147) — never carry plaintext/ciphertext.

### 2. `migrations.py` — m006+

**Closest analog:** m004/m005 column adds + m002 table creation. Conventions: `s = db.references_schema`, `int_t = db.big_int`, `blob_t = db.blob`, integer epoch timestamps, `db.execute` (auto-commit legal outside domain tx).

Excerpt — `migrations.py:772–788`:

```python
async def m004_digital_delivery(db: Connection):
    s = db.references_schema
    await db.execute(f"ALTER TABLE {s}products ADD COLUMN delivery_enc {db.blob}")

async def m005_order_archiving(db: Connection):
    s = db.references_schema
    await db.execute(
        f"ALTER TABLE {s}orders ADD COLUMN archived_at {db.big_int}"
    )
    await db.execute(
        f"CREATE INDEX ix_orders_merchant_archive "
        f"ON {s}orders(merchant_id, archived_at, created_at)"
    )
```

**Mimic:** `CREATE TABLE {s}peer_relays` / `{s}relay_cursors` / `{s}buyer_sessions` / `{s}inbox_blocklist` following the `relay_configs` shape (migrations.py:332–344) — TEXT ids, `{int_t}` epoch columns, FK `REFERENCES {s}merchants(id) ON DELETE RESTRICT`. `ALTER TABLE {s}merchants ADD COLUMN inbox_state TEXT NOT NULL DEFAULT 'off'`; `ALTER TABLE {s}order_messages` for read markers (`read_at`/`conversation_id`); `UNIQUE` indexes for dedupe keys (`buyer_sessions` token hash lookup, blocklist `(merchant_id, author_hash)`). Note `orders` already carries `buyer_pubkey_enc`/`buyer_pubkey_hash` + unique index — **no order columns needed** for D-04.

### 3. `services/inbox.py` (NEW) — durable admission + processing

**Role/data flow:** notification callback → admission (kind-1059, one `p`==merchant, `verify()`, ≤`inbox_max_event_bytes`, per-author rate bucket, blocklist check) → `UNIQUE` insert `inbox_events` (dedupe) → leased drain: keystore unwrap → `processed_state` transition → domain dispatch (order adapter → canonical services; kind-14 → `order_messages`; sender copy → recovery mark only).

**Closest analogs (three, combine):**

(a) **UNIQUE-insert dedupe** — `orders.enqueue_email_intents`, `email.py:375–393`:

```python
rc = await tx.execute(
    f"INSERT INTO {tx.table('email_queue')} "
    "(id, merchant_id, order_id, channel, event_type,"
    " recipient_enc, recipient_hash, state, attempts,"
    " next_attempt_at, claim_token, created_at) "
    "VALUES (:i, :m, :o, :c, :e, :re, :rh, 'pending', 0, :n,"
    " 0, :n) ON CONFLICT DO NOTHING",
    ...)
return rc == 1
```

Also `_claim_idempotency`, `checkout.py:107–117` (`INSERT ... ON CONFLICT DO NOTHING`, conflict = success). **Mimic:** `INSERT INTO inbox_events ... ON CONFLICT (outer_event_id) DO NOTHING`; rc==0 → already admitted, skip dispatch. Never SELECT-then-INSERT (§14 anti-pattern).

(b) **Per-author rate cap** — fixed-window `rate_limit_buckets` upsert, `email.py:122–136`:

```python
row = await tx.fetch_one(
    f"INSERT INTO {tx.table('rate_limit_buckets')} AS rate_bucket "
    "(scope_hash, bucket, window_start, count, expires_at) "
    "VALUES (:s, :b, :w, 1, :e) "
    "ON CONFLICT (scope_hash, bucket, window_start) DO UPDATE "
    "SET count = rate_bucket.count + 1 WHERE rate_bucket.count < :cap RETURNING count",
    {"s": scope, "b": bucket, "w": window, "e": window + 7200, "cap": cap},
)
return row is not None
```

**Mimic:** bucket `"inbox-author"`, scope = `author_hash` (never raw pubkey in the bucket key — same HMAC posture as `nip89.check_public_rate_limit`, nip89.py:223–224: `hmac_index(privacy_key, "rate-limit", "", client)`). Drop-before-validation when over cap (D-24).

(c) **Cursor + session lifecycle** — no existing analog in production; the pattern is RESEARCH Pattern 2 (§9.2): `since = last_completed_session_start − 3d` persisted per `relay_cursors` row; flip only after EOSE AND durable admission of all delivered events. Worker structure mimics the leased-pass shape — `settlement.reservation_expiry_pass` (settlement.py:435–476): select candidates on `db.connect()`, then per-row `DomainTransaction` processing. Crash-resume mirrors `reconcile`'s `received`-order resume (settlement.py:511–523).

**Reject/quarantine surface:** `processed_state` values `received|validated|processed|rejected|quarantined` + `reject_reason` (bounded codes — reuse `WrapRejection` vocabulary). Retention already prunes `processed` rows after 7d (settlement.py:884–890) — extend the same UPDATE for `rejected`/`quarantined` (30d, `INBOX_QUARANTINE_RETENTION_S` already defined at settlement.py:28).

### 4. `services/order_messages.py` (NEW) — rumor⇄domain adapter + `order_msg` intents

**Role/data flow:** validated kind-16 rumor → checkout-payload dict → `_resolve_cart`/`_price_cart`/`begin_saga` (RESEARCH Pattern 4); domain events → kind-16 type-2/3/4 + kind-14 rumor descriptors → `outbox.enqueue_intent(aggregate_type='order_msg', payload_enc=...)` in the SAME domain transaction.

**Closest analog (builder):** `services/events.py` deterministic dict builders — `{"kind","content","tags"}`, fixed tag order, `json.dumps(..., sort_keys=True, separators=(",",":"))`. The order-rumor construction itself already exists as the executable reference — `harness/sdk.py:160–194` `build_order_rumor` (common tags `p`/`subject`/`type`/`order`/`amount`/`item`).

**Closest analog (payload secrecy):** `outbox_events.payload_enc` exists (migrations.py:358) but is unused — encrypt descriptors with the checkout `_enc` pattern (checkout.py:775–779):

```python
def _enc(plaintext: bytes, column: str) -> bytes:
    return crypto.encrypt(
        plaintext, key, record_id=order_id, table="orders",
        column=column, key_version=ver,
    )
```

Use `record_id=<outbox_event_id>, table='outbox_events', column='payload_enc'` (new AAD binding).

**Closest analog (in-tx enqueue):** `merchant._enqueue_intent` (merchant.py:381–392) → `outbox.enqueue_intent` inside the caller's `DomainTransaction`. **Mimic:** enqueue the `order_msg` intent inside `attach_payment`'s tx (type-2) and `transition_order` callers' txs (type-3/4), same as `enqueue_email_intents` is invoked in-tx today.

**Supersession note:** `enqueue_intent` supersedes only intents with `aggregate_revision < :r` (outbox.py:53–64). `order_msg` intents must all enqueue at `revision=0` — `0 < 0` is false so they never supersede each other (§7.4 "order_msg rows never supersede") — but they WILL be superseded by any `revision>0` intent of the same aggregate; use a distinct `aggregate_id` (e.g. `order_id:msg_seq`) to keep ordering if needed.

**Intake adapter specifics (from RESEARCH Pattern 4, mapped to existing code):**
- `item` `30402:<pk>:<d>` → `{d_tag, quantity}` feeding `_resolve_items` (checkout.py:233–290) — assert `<pk>` == merchant pubkey; split on **first two** colons only.
- `order` → `external_id` validated against `EXTERNAL_ID_RE` (checkout.py:47) **before** hashing; `crypto.normalize` is the exact form `ix_orders_nostr_external_id` sees.
- `rumor.pubkey` → `buyer_pubkey_enc`/`buyer_pubkey_hash` via `crypto.hmac_index(privacy_key, PURPOSE_BUYER_PUBKEY, merchant_id, normalize(pubkey))` — purpose constant already exists (crypto.py:33).
- dedupe: `ix_orders_nostr_external_id` UNIQUE (migrations.py:699–703) — UNIQUE-insert-or-conflict, request-hash on items+qty returns existing order vs `duplicate-order-conflict` (mirrors `_claim_idempotency` request_hash check, checkout.py:124–128).
- Physical `address` JSON `{country,region,...}` → reuse `_resolve_shipping` country/region regexes (checkout.py:48–49, 334–362); opaque strings → reject-before-reservation.
- After intake, `protocol='gamma'` orders skip `public_token` semantics; on `awaiting_payment` enqueue the type-2 `order_msg` intent instead of returning bolt11 to a caller.

### 5. `services/peer_relays.py` (NEW) — buyer kind-10050 + egress

**Closest analog:** `relay.relay_targets` + `get/set_blossom_servers` (relay.py:45–61, 144–167) — settings/row read-write shape; new `peer_relays` table rows keyed `(pubkey_hash, relay_url)` with `fetched_at`/`expires_at = fetched_at + settings.peer_relay_ttl` (already 86400, settings.py:144).

**Fetch:** `client.fetch_events_from(urls, Filter().kind(Kind(10050)).author(pk), Duration(seconds=10))` on the shared transport (RESEARCH code example) — **no signer attached** (invariant below).

**Egress/SSRF — the critical new check:** `validate_relay_url` (security.py:185–265) is **syntactic only** — it rejects raw-IP hosts, userinfo, fragments, single-label/internal TLDs, punycode, non-NFC, but does NOT resolve DNS. Buyer-declared relays are attacker-controlled (RESEARCH Pitfall 5), so `peer_relays` must add `getaddrinfo` resolution and reject loopback/private/link-local/multicast/reserved/metadata IPv4+IPv6 answers at connect/discovery AND revalidate on reconnect. `transport.validate_relay_target` (transport.py:41–59) is the call-site wrapper — extend it or gate peer relays through a stricter `validate_peer_relay_target` that also enforces the insecure-test hatch only for `ws://` loopback.

**No-route policy:** zero valid relays → intent stays `pending` with `last_error='no_inbox_relays'` (mirror `'no-relay-targets'`, outbox.py:596); refresh every 15min for 48h → `failed`. NEVER fall back to the source relay (§9.3).

### 6. `services/nostr_auth.py` (NEW) — NIP-07 sessions + NIP-42 relay auth

**Closest analogs (three):**

(a) **Session cookie + Origin posture** — admin cookie path in `security.enforce_mutation_security` (security.py:111–158) and `issue_csrf_cookie` (161–177). Buyer session mutations (claim, logout, attributed checkout) must enforce the same exact-`Origin == public_base_url` check when the session cookie is present. Cookie: `HttpOnly; Secure; SameSite=Strict; path=/infinitemarkets` — differs from `gm_csrf` (`httponly=False` because admin JS echoes it; the buyer session is never echoed). Session token stored hashed like `public_token_hash` — `crypto.token_lookup_hash` (crypto.py:147–157) is the strict-canonical lookup pattern; `generate_public_token`/`TOKEN_BYTES` for token minting.

(b) **No-oracle lookups** — `_order_for_token` (views_public_api.py:208–238): identical 401 `_TOKEN_INVALID` for missing/malformed/unknown/expired — apply verbatim to claim-token and session lookups (Pitfall 8).

(c) **Challenge rows** — fixed-window `rate_limit_buckets` upsert (nip89.py:227–240) for the challenge nonce *or* a dedicated `nostr_challenges` table: single-use, ~5min TTL, scope = `hmac_index(privacy_key, "nostr-challenge", merchant_id, client_ip)` — same HMAC-scope posture. Verify with `Event.from_json` + `event.verify()` + kind 22242 + `created_at` freshness ≤300s (RESEARCH code example — no custom schnorr).

**(d) NIP-42 per-relay auth state** — manual, never `ClientOptions.automatic_authentication` (auto-auth needs a client-attached signer, violating the transport invariant). `handle_notifications` sees `RelayMessageEnum.AUTH` → `EventBuilder.auth(challenge, RelayUrl.parse(relay_url))` → `keystore.sign_event(merchant_id, ...)` (keystore.py:180–187) → `client.send_msg_to([url], ClientMessage.auth(signed))`. Guard: sign only when challenge relay URL == live connection URL; challenge ≤1KiB (§9.4). Auth state per relay row persisted for the D-26 admin surface (see §10). Paid-relay detection: `["OK",id,false,"...paid relay..."]` message-text match → `auth-failed`/`payment-required` + invoice display; never spend (D-27).

### 7. `services/storefront_mode.py` (NEW) — mode setting + gates

**Closest analog:** `get/set_blossom_servers` (relay.py:144–167) — `settings` table `DELETE` + `INSERT` per `(merchant_id, key)` in a `DomainTransaction`; key `storefront_mode`, value `full|showcase|browse_only|nostr_only` (default `full`).

**Gate insertion points (existing code to hook):**
- `public_checkout` + `public_quote` in views_public_api.py:170–205 — insert mode check beside `readiness.assert_checkout_ready()`; raise `unprocessable`/`not_found` family like `_merchant_for_checkout` does (checkout.py:221–230).
- `render_intent` in outbox.py:283+ — catalog aggregates return `None` → superseded when `browse_only` (D-09 pause); `order_msg`/`merchant_profile` intents unaffected. The existing `catalog.publish_nip15` gate (outbox.py:347–352, 434–438) is the exact shape: render returns None when the mode forbids.
- Public pages in views.py — mode ctx injected in `_public_response`/`_store_ctx`; `nostr_only` renders a notice template like `public_unavailable.html` (244-byte template) or the Nostr-only notice page while keeping `/order`, `/order-status`, sign-in, track-order reachable (D-08 invariant).
- Admin mode gate (D-10): reject `showcase`/`nostr_only` until inbox profile active — same conflict-409 posture as wallet-change blocking (merchant.py:253–258).

### 8. `services/transport.py` — subscribe + notifications + AUTH

**Closest analog:** `RelayTransport` itself (transport.py:62–133) — owned client lifecycle, `send_to` (103–119) is the model for the new `subscribe(filters)` + `handle_notifications(handler)` methods: validate all targets through `validate_relay_target` first, connect on demand like `send_to` does (`add_relay` + `connect_relay` per target).

**Hard invariants (docstring transport.py:5–7 — MUST be preserved):** no signer ever attached; nsec never reaches the transport; `ClientOptions.autoconnect(False)` (line 83) — the relay_manager tick owns cadence; `relay_io_enabled()`/`insecure_relays_allowed()` test hatches (30–38) must keep honoring `INFINITEMARKETS_RELAY_IO=off` for the inbox path too (tests must be able to run the worker without dialing).

**Mimic:** `subscribe` issues `Client.subscribe(Filter().kinds([Kind(1059)]).pubkey(merchant).since(...))` per merchant inbox relay (subscription survives SDK reconnect); `handle_notifications` runs a Python `HandleNotification` impl dispatching `handle` → admission callback and `handle_msg` → EOSE/AUTH callbacks (RESEARCH code example). The notification handler is a long-lived task → register as owned task in `tasks.start_workers` (see §11) so `infinitemarkets_stop` cancels it and `transport().close()` (`__init__.py:78–86`) shuts the client down.

### 9. `services/outbox.py` — `order_msg` dual-copy branch

**This is the phase's center of gravity — everything already exists; add a copy-class branch.**

Reusable machinery (do not rebuild):
- `_publication_transaction` (outbox.py:505–520): merchant `FOR UPDATE` lock + claim-token/lease re-check; yields `(tx, row)` — reuse verbatim for each evidence write.
- `_cas_state` (234–256): every leased write compares `claim_token` + `claimed_by` + `claimed_until`.
- `_record_publications` (259–280): inserts `(id, outbox_event_id, delivery_copy, relay_url, event_id, attempt_no, result, message, attempted_at)` — **`delivery_copy` column already exists** (migrations.py:385–399); pass `'recipient'`/`'sender'` instead of `'public'`.
- `_accepted_targets` (225–231): currently sums ALL accepted rows — **needs a per-copy variant**: `WHERE delivery_copy = :copy` so recipient-set acceptance doesn't satisfy the sender class.
- `_backoff`/`TRANSIENT_REASONS`/result classification (132–143, 617–639): reuse verbatim; paid-relay negative-OK text maps to `rejected` (verbatim `message` preserved → the auth surface reads it).

**Branch shape (inside `publish_intent`):**
- `aggregate_type == 'order_msg'` skips `render_intent`'s domain-state rebuild (like the kind-5 early-return at outbox.py:294–300): decrypt `payload_enc` descriptor → rebuild the SAME rumor (fixed `created_at` → stable canonical id) → `keystore.nip17_wrap` twice (recipient copy → `peer_relays` targets; sender copy → merchant `direction='inbox'` targets) → two `transport.send_to` calls → `_record_publications` per copy class → `published` iff ≥1 `accepted` in EACH class (§8.6); one class OK → `partially_published`; zero → `pending`/`failed` per existing attempt logic.
- `event_address` is NULL for `order_msg` (non-addressable rumor) — the clock-skew/`last_signed_at` logic (outbox.py:553–577) scopes by `aggregate_type+aggregate_id+event_kind` and still applies.
- `worker_tick` (753–800) resolves targets via `relay_service.relay_targets(merchant_id, "public")` — branch to `peer_relays` for `order_msg` recipient copy and `relay_targets(m, "inbox")` for sender copy.

### 10. `services/relay.py` — inbox targets + auth status surface

**Already works:** `relay_targets(merchant_id, direction)` accepts `"inbox"` (relay.py:45–61) and `merchant._replace_relay_configs` already validates `direction in ("public","inbox","both")` (merchant.py:348–352). `admin_settings.js` already exposes the direction dropdown (DIRECTIONS at admin_settings.js:99–103).

**To add:**
- `ensure_default_inbox_relays(merchant_id)` — mirror `ensure_default_relays` (relay.py:75–100) but `direction='inbox'` + inbox starter set; invoked by the kind-10050 enable action (D-16 settings-driven).
- Extend `relay_health` (relay.py:173–214): per-relay `auth_state` (`authenticated|auth-required|auth-failed|payment-required`), remediation copy, and `paid_invoice` field — the join pattern (configs + `relay_publications` evidence aggregate) is the template; add the auth-state table columns read.
- `retry_intent` (relay.py:256–283) already covers "retry now" for any intent including `order_msg` (D-19) — no change needed except it must not resurrect `superseded`.
- `list_outbox` (217–253) already returns `relay_publications` incl. `delivery_copy` — the Messages detail panel reads this verbatim for D-18 per-copy evidence.

### 11. `services/tasks.py` — `inbox_processor` + subscription lifecycle

**Closest analogs:**
- Leased worker: `reservation_expiry`/`reconciliation` (tasks.py:173–242) — `_acquire_lease(name)` (40–72, UPDATE/INSERT fencing-token CAS on `task_leases`) + `_run_leased` (81–102 — `ACTIVE_TASK_LEASE` ContextVar checked by every `DomainTransaction` open/commit via `_check_fence`, db.py:167–177). Use a lease for the inbox drain pass (single-writer on `inbox_events` processing).
- Unleased per-worker loop: `relay_manager` (tasks.py:125–143) — owns transport convergence; the inbox subscription handler is also per-worker (each worker owns its Client) → same unleased shape.
- Registration: `start_workers` (266–288) — `task_manager.create_task(func(), name="infinitemarkets_inbox_processor")` + append to handles (already tracked by `register_owned_task` in `__init__.py:40–43` and cancelled in `infinitemarkets_stop`, 78–86).
- `worker_db()` per-worker handle (db.py:40–47) — inbox worker gets its own `Database` handle like outbox/email (`worker_tick` finally `await wdb.engine.dispose()`, outbox.py:800; email tasks.py:170).

### 12. `services/settlement.py` — reconcile + retention

- `reconcile` (498–620) docstring says "web scope (order_msg machinery is Release B)". Add: resume `inbox_events` rows in `received|validated` (mirror the `received`-order resume loop, 511–523 — select candidates on `db.connect()`, per-row processing, exception → report entry, never raise); re-enqueue type-2 `order_msg` intents for gamma orders stuck `awaiting_payment` without a live intent (check `outbox_events` live-intent query pattern, outbox.py:66–75).
- `retention_prune` (865–930): `inbox_events` ciphertext already erased 7d after `processed` (884–890). Extend: `rejected`/`quarantined` rows at 30d (`INBOX_QUARANTINE_RETENTION_S` already defined, line 28); `buyer_sessions`/`nostr_challenges`/`peer_relays` expiry deletes; `order_messages` PII already covered (925–929).
- `invoice_listener`/`_handle_core_payment`/`confirm_settlement` are protocol-agnostic — gamma orders settle identically (shared canonical path per GAM-02). The type-3 status `order_msg` intent enqueue goes inside `transition_order` callers here (in-tx, like `enqueue_email_intents` at 375–380).

### 13. `views_public_api.py` — `/nostr/*` + mode gates

**Closest analog:** the file itself — `public_boundary` (33–52), `_guard` (55–59: rate limit + `PUBLIC_HEADERS`), `_TOKEN_INVALID`/`_order_for_token` (208–238).

- `GET /nostr/challenge`, `POST /nostr/verify`, `GET /nostr/orders`, `POST /nostr/claim`, `POST /nostr/logout` — all under `public_boundary`; mutations (verify/claim/logout/checkout-with-session) get Origin-enforcement via `nostr_auth` helper (§6a) since session cookies ride along.
- `GET /nostr/orders` returns the same §5.4 field set as `public_order_status` (281–300) filtered to session `buyer_pubkey_hash`, with `digital_delivery` gated by `orders.delivery_unlocked`/`digital_delivery` (orders.py:140–170) — D-03's "same paid-state gating" is literal reuse.
- `/checkout` (179–205): insert the session-cookie read → set `buyer_pubkey` on the order (D-04) + `storefront_mode` gate (D-07) before `_claim_idempotency`. `/quote` (170–176) gates identically. `claim` response: identical-401 bad-token posture (Pitfall 8).
- Headers: session cookie set via `response.set_cookie(..., httponly=True, secure=True, samesite="strict", path="/infinitemarkets")`.

### 14. `views_api.py` — Messages / Rejected / auth / mode routes

**Closest analog:** the §5.3 order routes (611–751): `@problem_boundary` + `check_user_exists` + `merchant_service.get_merchant_row(merchant_id, str(user.id))` owner-scoping (404 not 403, merchant.py:138–147) + `_Strict` pydantic bodies (72–76, `extra="forbid"`).

New routes (all `/merchants/{merchant_id}/...`):
- `GET /messages/conversations` (+`?folder=customer|unknown`), `GET /messages/conversations/{id}` (thread), `POST /messages/conversations/{id}/reply`, `POST /messages/compose`, `POST /messages/{id}/read`, `GET /messages/unread-count` (nav badge), `GET /messages/{id}/delivery` (per-relay evidence for both copy classes — reads `relay_publications` via `list_outbox` join).
- `GET /rejected-intake` (inbox_events `rejected|quarantined` + `reject_reason`), `POST /rejected-intake/{id}/mute` → blocklist insert (D-23).
- `GET /relay-auth` (per-relay auth status + paid-relay invoice fields), maybe `POST /relay-auth/{relay}/retry`.
- `GET/PUT /storefront-mode` (+ inbox-state read for D-10 gating), `POST /inbox/enable` / `POST /inbox/disable` (kind-10050 publish → `pending`; kind-5 tombstone on disable, D-17).

**Mimic:** mutation security is automatic inside `problem_boundary` (views_api.py:31–66 — `enforce_mutation_security` runs for every non-safe method; cookie → Origin+CSRF; bearer → pass; usr-only → reject). Strict-body classes for all POST bodies.

### 15. `views.py` — mode-gated pages + sign-in affordance

**Closest analog:** existing page handlers — `merchant_page`/`collection_page`/`product_page` check merchant state + `_public_guard` rate-limit + `_public_response` ctx (views.py:133–160, 212–364). `order_page` (367–391) + `public_order_status` semantics stay UNGATED in every mode (D-08).

- `storefront_mode` ctx flag into `_store_ctx`/`_public_response`; `nostr_only` renders a new `public_nostr_only.html` notice template (pattern: `public_unavailable.html`, 334-byte file) for browse pages while `/order`, sign-in API, and order-status keep working.
- Sign-in affordance: `ctx["nostr_signin"]` boolean = merchant `inbox_state == 'active'` (D-06) — rendered in `public_base.html` chrome.
- **`_asset_revision` (views.py:33–42) is content-hash over ALL files under `static/infinitemarkets/`** — new JS files (`public_nostr.js`, `admin_messages.js`) automatically change the hash; add script tags with `?v={{ asset_revision }}` exactly like admin.html:1559–1564 and `public_base.html`'s `public_storefront.js?v={{ asset_revision }}` (last line).

### 16. `admin_messages.js` (NEW) — fifth nav surface

**Closest analog:** `admin_orders.js` verbatim — `window.app.mixin`, `gmMessages` data namespace, split list+detail workspace, `gmApi` calls, `gmProblemCopy`, state→style maps, dialog model, `$watch("gm.merchant", ...)` bootstrap with `window._gmMessagesWired` + `#vue._vnode.component` root resolution (admin_orders.js:538–557).

**Mimic:** customer/Unknown folders ↔ `archiveView` toggle (admin_orders.js:74–78 + `gmSwitchOrderView` 246–254); unread badge ↔ state pill rendering; reply/compose ↔ dialog+`gmApi POST` patterns (gmDoAction 401–464); thread-in-order-detail ↔ `gmSelectOrder`'s Promise.all detail+events fetch (369–396 — order detail API will gain a `/messages` sibling endpoint).
**Also modify `admin_app.js`:** `gmNav` gains `if (view === "messages" && this.gmLoadMessages) this.gmLoadMessages();` (pattern at admin_app.js:170–178) + unread badge count refresh.

### 17. `public_nostr.js` (NEW) — sign-in + order list + claim + showcase

**Closest analog:** `public_storefront.js` — `window.GM` namespace, `GM.h` DOM-safe builder (never innerHTML, public_storefront.js:12–35), `GM.api` fetch wrapper (55–72), `GM.problemCopy` RFC-9457 → copy (187–198), `GM.orderToken` memory-only token posture (74–103).

**Mimic:** vanilla JS only (CSP `script-src 'self'`, views.py:44–48 — `window.nostr` is an injected browser object, not a script tag, so CSP-safe); sign-in flow `GET challenge → window.nostr.signEvent({kind:22242, content:challenge, tags:[["challenge",c]]}) → POST /nostr/verify`; order list renders via `GM.h`; claim input posts `{token}` — the token may come from `GM.orderToken()` when the buyer pasted their private link (D-05). Showcase mode renders the "Order via Nostr" guidance (merchant npub + inbox relays + suggested client) inside the checkout card region (`#gm-checkout-card` — see buyer.spec.ts `data-mode="guided"` usage).

### 18. `admin_settings.js` — inbox relays + mode panel + auth status

**Closest analog:** its own relay editor (admin_settings.js:304–337 — `gmAddRelay`/`gmRemoveRelay`/`gmSaveRelays` mapping `relay_configs` to the PATCH body — direction already supported) + the deactivation two-step dialog (364–394 — 409 blocker-list pattern → the mode-change impact warning mirrors it: first call returns blockers/warning copy, second confirms).

**Mimic:** inbox relays = same `relay_configs` PATCH with `direction:"inbox"`; `storefront_mode` panel = new `gmSettings.storefrontMode` select + `gmApi("PUT", "/merchants/"+mid+"/storefront-mode", {mode})` with a confirmation dialog listing D-07 impact copy; relay-auth rows render `relay_health`'s new auth fields with remediation text (D-26) + invoice display for `payment-required` (D-27); blocked modes disabled with reason until `inbox_state=='active'` (D-10 — the disabled-with-reason pattern matches `walletBlocked` at 288–302).

### 19. `admin.html` — nav + surfaces

- Fifth `<q-item>` in the nav `q-list` (admin.html:76–95), `data-gm-nav="messages"`, icon + `Messages` label + `<q-badge>` unread count (D-15). `admin.spec.ts` asserts the four existing `data-gm-nav` values — extend the list.
- New `<section v-show="gm.view === 'messages'" data-gm-surface="messages">` (pattern: sections at 110, 423, 814, 921) containing the split workspace + Unknown folder + connectivity health strip (D-20 — inbox listener state, per-relay connectivity, outbox backlog from `metrics.outbox_depth`, metrics.py:26–48).
- Rejected-intake + storefront-mode panels: either new `q-tab`s inside Settings surface (pattern at 923–927) or separate surfaces.
- Script include: `<script src="/infinitemarkets/static/infinitemarkets/js/admin_messages.js?v={{ asset_revision }}"></script>` in the `{% block scripts %}` list (1558–1564).

### 20. tests — runtime + e2e

- **`tests/runtime/conftest.py` is the fixture authority:** `runtime_env` (273–346) boots the real host loader per module (symlinked ext dir, `_EXT_ENV` incl. `INFINITEMARKETS_RELAY_IO=off`, FakeWallet, authed httpx client). New tests either reuse `runtime_env` (host-level API flows) or `keystore_env` (227–271 — fresh module import + direct migration runs; add new `mNNN_*` calls to its import line, 257). For relay IO tests, override `INFINITEMARKETS_RELAY_IO`/`INFINITEMARKETS_ALLOW_INSECURE_RELAYS` and start `harness.relay.LocalRelay` (`ws://127.0.0.1:<ephemeral>`, ACCEPTING/REJECTING/SILENT/AUTH_FLOOD — records every message/event for assertions, harness/relay.py:44–143).
- **Golden fixtures already exist:** `tests/fixtures/golden/nip17/` — `keys.json`, `rumor.json`, `recipient/{seal,wrap}.json`, `sender/{seal,wrap}.json`, `retry/{seal,wrap}.json` (same canonical rumor id, fresh seal/wrap), `rumor_kind14.json`, `rumor_kind17.json`. Regenerate via `tests/fixtures/golden/generate_fixtures.py`. These are normative D-08 references — wrap/unwrap tests assert against them.
- **e2e:** `admin.spec.ts`/`buyer.spec.ts` — `.seed.json` + `cookie_access_token` context cookies, `test.describe.configure({mode:'serial'})`, `data-gm-*` selectors. New specs follow the same file conventions; Node 22/24 only.
- **`harness/saga.py`** remains the crash-drill reference model (kill-between-points resume semantics); **`harness/sdk.py`** is the unwrap/wrap executable reference — production `nip17_unwrap` tests should assert the same reject-reason vocabulary for tampered wraps.

### 21. `harness/relay.py` — extension needed

`LocalRelay` currently answers `REQ` with `CLOSED` (relay.py:137–139) and has no EOSE/`EVENT`-back-fill. The inbox worker needs a REQ/EOSE-capable fixture: serve stored `received_events` matching `{kinds:[1059],'#p':[merchant],'#p'}` filters then `["EOSE", sub_id]`; a gated mode that emits `["AUTH", challenge]` then accepts only after a valid kind-22242; a paid mode replying `["OK",id,false,"This is a paid relay: '<id>'"]`. Keep the deterministic recording surface (`received_messages`, `received_events`, `connections`).

---

## Cross-Cutting Invariants Checklist (every new code path)

| Invariant | Where it lives today | Phase-3 application |
|---|---|---|
| `DomainTransaction` for all multi-statement writes; no `conn.execute/insert/update` inside domain tx | `db.py:104–237`; `_check_fence` enforces lease token on open+commit | inbox admission, cursor advance, sessions, blocklist, mode writes |
| Claim-token CAS on every leased write | `outbox._cas_state` (234–256), `email._leased_write` (105–119) | `order_msg` publish evidence + retry; inbox row processing |
| `task_leases` fencing for single-writer passes | `tasks._acquire_lease` + `_run_leased` (40–102) | `inbox_processor` drain |
| `worker_db()` per-worker handle | `db.py:40–47`; used by outbox/email ticks | inbox worker handle |
| UNIQUE-insert dedupe (never check-then-insert) | `enqueue_email_intents`, `_claim_idempotency` | `outer_event_id`/`rumor_id` admission; `buyer_sessions` claim; blocklist |
| Owner-scoped 404 (not 403) | `get_merchant_row` merchant.py:138–147 | all new admin routes |
| Cookie mutations → exact Origin + double-submit CSRF | `enforce_mutation_security` security.py:111–158 | buyer session mutations get the SAME Origin check (custom CSRF not required — Origin check + SameSite=Strict is the agreed posture) |
| Identical-401 no-oracle lookups | `_order_for_token` views_public_api.py:208–238 | session token + claim token lookups |
| AEAD envelope w/ AAD `record_id+table+column+version`; purpose-separated HMAC indexes | `crypto.py`; `_enc` pattern checkout.py:775–779 | `payload_enc` descriptors, `buyer_pubkey_enc`, `author_enc`, session token enc, `order_messages.content_enc`/`participant_keys_enc` |
| `PUBLIC_HEADERS` no-store/no-referrer on every public response | `views_public_api.py:26–58` | all `/nostr/*` responses |
| Content-hash asset versioning `?v={{ asset_revision }}` | `views.py:33–42` | auto-covers new JS; add script tags only |
| `problem_boundary`/`public_boundary` RFC 9457 | `views_api.py:31–66`, `views_public_api.py:33–52` | all new routes |
| No signer on transport; keystore-scoped signing | `transport.py` docstring; `keystore.sign_event` | manual NIP-42 + both wrap copies |
| Relay OK ≠ truth; evidence is append-only `relay_publications` | `outbox._record_publications` | `delivery_copy='recipient'|'sender'`; `published` iff ≥1 OK per class |
| Declared-relay routing only — no fallback to source relay | §9.3 (new) | `pending` + `no_inbox_relays` is the only no-route state |
| Session-start cursors — NEVER event `created_at` | §9.2 (new; wraps backdated ≤2d) | `relay_cursors.since = last_completed_session_start − 3d`, advanced post-EOSE+admission |
| Bounded rejection vocabulary; no plaintext/challenge logging | `WrapRejection` sdk.py:141–147; `reject_reason` column | inbox reject/quarantine; AUTH handling |
| Test-only hatches stay test-only | `insecure_relays_allowed`/`relay_io_enabled` transport.py:30–38 | peer-relay + inbox paths honor the same env gates |
| `Idempotency-Key` on admin mutations | `admin_app.js` `gmApi` (66–91) + `_IDEMPOTENCY_RE` | new admin POSTs inherit via `problem_boundary` automatically |

## Key Gap Notes for the Planner

1. **`peer_relays`/`relay_cursors` are NOT landed** — create in m006 (CONTEXT.md's claim is wrong; m002 docstring confirms deferral).
2. **`harness/inbox_outbox.py`/`relay_fixtures` don't exist** — the real references are `harness/sdk.py`, `harness/relay.py`, `harness/saga.py`.
3. **`orders.buyer_pubkey_*`, `orders.receipt_verified`, `orders.protocol` ('gamma' already in the admin filter allowlist at orders.py:549), `inbox_events`, `order_messages`, `outbox_events.payload_enc`, `relay_publications.delivery_copy`, `rate_limit_buckets`, `settings.peer_relay_ttl`, `settings.inbox_max_event_bytes`, `direction='inbox'` relay config + admin dropdown** — all already exist; Phase 3 is wiring, not schema invention.
4. **`_accepted_targets` needs a per-`delivery_copy` variant** — current implementation lumps all copy classes together.
5. **`LocalRelay` can't serve REQ/EOSE** — extend it before inbox tests; `AUTH_FLOOD` exists but a real challenge→verify round-trip mode is needed.
6. **`validate_relay_url` doesn't resolve DNS** — peer relays need a new `getaddrinfo`-based egress check (D-33 records the boundary of this claim).
7. **`retention_prune` only erases `processed` inbox rows** — extend to `rejected`/`quarantined` (30d constant already defined) + new Phase-3 tables.
