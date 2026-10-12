---
phase: 03-release-b-gamma-nip-17-orders
plan: 01
subsystem: nostr-inbox-transport
tags: [nip-17, nip-42, gift-wrap, relay-transport, sqlite, postgresql]

requires:
  - phase: 02-release-a-safe-web-commerce
    provides: durable outbox, relay_configs direction vocabulary, shared
      no-signer transport client, worker task supervisor, keystore custody
provides:
  - m006 inbox schema (inbox_events, relay_cursors, peer_relays,
    inbox_blocklist, merchants.inbox_state, relay_configs auth columns)
  - kind-10050 inbox activation state machine gated on accepted relay
    publication evidence
  - explicit section-8.5 NIP-17 wrap/unwrap chain in the keystore
  - kind-1059 inbox sessions with spec-ordered admission, rumor dedupe,
    EOSE-committed cursors, manual NIP-42 AUTH, and paid-relay evidence
  - peer kind-10050 discovery with DNS egress validation + NO_INBOX_RELAYS
  - /inbox enable/disable/state + /relay-auth admin endpoints
affects: [03-02, 03-03]

actuals:
  tokens: ~48000
  tasks: 3
  commits: 4

tech-stack:
  added: []
  patterns:
    - "Stage-split admission: cheap pre-insert gate (received) then leased
      unwrap drain (validated) — expensive crypto never blocks the socket"
    - "Cursor commits strictly after EOSE + durable admission, never from
      event created_at"
    - "NIP-42 answered manually via keystore.sign_event per connection —
      automatic_authentication stays OFF and no signer rides the client"
    - "DNS egress check (security.resolve_and_check_egress) shared by peer
      discovery, inbox relay_configs writes, and reconnect revalidation"

key-files:
  created:
    - infinitemarkets/services/inbox.py
    - infinitemarkets/services/nostr_auth.py
    - infinitemarkets/services/peer_relays.py
    - tests/runtime/test_inbox_activation.py
    - tests/runtime/test_keystore_nip17.py
    - tests/runtime/test_inbox_transport.py
  modified:
    - infinitemarkets/migrations.py (m006 + rumor dedupe index)
    - infinitemarkets/keystore.py (nip17_wrap/nip17_unwrap, WrapRejection)
    - infinitemarkets/security.py (resolve_and_check_egress)
    - infinitemarkets/services/transport.py (subscribe/fetch/send_msg/remove_relay)
    - infinitemarkets/services/{merchant,relay,outbox,events,tasks,settlement}.py
    - infinitemarkets/views_api.py (inbox + relay-auth routes)
    - infinitemarkets/settings.py (inbox_max_event_bytes, inbox_author_cap)
    - harness/relay.py (REQ/EOSE, AUTH_CHALLENGE, PAID modes)
    - harness/sdk.py + tests/qualification/test_p0_14 (rebrand repair)

key-decisions:
  - "Kind-10050 advertises to the union of public+inbox targets; activation
    requires a durable relay_publications.result='accepted' row — relay
    ACK is evidence, never payment truth."
  - "Deactivate publishes a kind-5 tombstone before inbox_state='off'."
  - "Subscription since = now-30d first session, last_completed_session_start-3d
    thereafter; cursor written only at EOSE."
  - "Two-stage admission: stage-1 (bound/kind/p-tag/verify/blocklist/bucket/
    ON CONFLICT) marks 'received'; the leased inbox_processor unwraps to
    'validated' — domain dispatch is explicitly deferred to 03-02."
  - "Buyer relay discovery returns the NO_INBOX_RELAYS sentinel rather than
    any source-relay fallback."

patterns-established:
  - "Pending-auth stash: AUTH challenges arriving before session
    registration are stashed per relay and answered before the REQ."
  - "nostr-sdk pooled-relay quirk: reconnecting a disconnected-but-pooled
    relay silently swallows REQs — sessions remove and re-add the relay."

requirements-completed: [GAM-01]

coverage:
  - id: D1
    description: "m006 schema + kind-10050 enable/publish/ACK->active +
      disable->tombstone vertical, gating on accepted evidence"
    verification:
      - kind: integration
        ref: tests/runtime/test_inbox_activation.py (7 tests)
        status: pass
    human_judgment: false
  - id: D2
    description: "Keystore NIP-17 wrap/unwrap explicit section-8.5 chain,
      golden fixtures, tamper matrix, bounded WrapRejection reasons"
    verification:
      - kind: integration
        ref: tests/runtime/test_keystore_nip17.py + tests/qualification/test_p0_05
        status: pass
    human_judgment: false
  - id: D3
    description: "Inbox transport: kind-1059 sessions/admission/cursors,
      NIP-42 AUTH, paid-relay evidence, egress validation, peer discovery"
    verification:
      - kind: integration
        ref: tests/runtime/test_inbox_transport.py (14 tests)
        status: pass
    human_judgment: false
---

## Accomplishments

### Task 1 — m006 schema + kind-10050 activation vertical (`4597db6`)

- `migrations.m006` adds `peer_relays`, `relay_cursors`,
  `inbox_blocklist`, `merchants.inbox_state`, `relay_configs.auth_state/
  auth_note/paid_invoice/auth_updated_at`,
  `order_messages.conversation_id/read_at`, and the
  `ux_inbox_events_merchant_rumor` unique index (retry dedupe — added in
  Task 3, same migration).
- `build_kind10050()` produces the deterministic `10050:<pubkey>:`
  descriptor with 1–3 normalized relay tags from
  `DEFAULT_INBOX_RELAYS`/config.
- Merchant flows: `enable_inbox` -> `off->pending` + kind-10050 outbox
  intent to the union of public+inbox targets; `pending->active` only on
  a durable `relay_publications.result='accepted'`; `disable` ->
  `deactivating` + kind-5 tombstone -> `off` on accepted evidence;
  exhaustion lands `error`.
- API: `POST /merchants/{id}/inbox/enable|disable`,
  `GET /merchants/{id}/inbox-state`.

### Task 2 — Keystore NIP-17 wrap/unwrap (`8baa4ee`)

- `MerchantKeyStore.nip17_wrap/nip17_unwrap` implement the explicit
  section-8.5 chain (outer kind/p-tag/sig -> decrypt -> seal kind13/empty
  tags/sig -> decrypt -> canonical rumor id + author match -> kind
  allowlist {14,16,17} -> duplicate common-tag rejection + exactly one
  valid rumor `p`), returning only domain-safe fields
  (`rumor_json/rumor_id/kind/author_pubkey`).
- `WrapRejection` carries bounded reason codes; custody discipline keeps
  decrypted key material inside the op (`finally`-released); logs carry
  ids/reasons only. NIP-04 path raises `ReleaseNotAvailable`.
- Golden fixtures verified for recipient/sender copies, retry (stable
  rumor id, fresh outer ids), and a tamper/rejection matrix.

### Task 3 — Inbox transport (`5005409`)

- `services/inbox.py`: `admit_event` (stage-1 §8.5 order: bound -> kind
  1059 -> exactly-one `p` == merchant -> `event.verify()` -> blocklist ->
  `inbox-author` bucket (60/min, `settings.inbox_author_cap`) ->
  `INSERT ... ON CONFLICT (outer_event_id)` as `received`); the leased
  `drain_received` (`inbox_processor` worker) unwraps to
  `validated`/`rejected`/`duplicate` with rumor-level dedupe via the
  m006 unique index. Sessions: `InboxRuntime` over the shared transport
  client, `since` = now-30d / `last_completed_session_start`-3d, cursor
  committed only at EOSE after durable admission.
- `services/nostr_auth.py`: manual `answer_auth_challenge` (guards:
  ≤1KiB, live-connection URL, merchant owns inbox relay_config),
  `classify_relay_ok` (paid-write -> `payment-required` + bolt11
  capture), `classify_closed`, `update_relay_auth_state` (bounded D-26
  vocabulary).
- `services/peer_relays.py`: `resolve_buyer_inbox_relays` via
  `fetch_events_from` on public targets, signature + 1–3 wss + DNS-public
  validation, TTL cache, `NO_INBOX_RELAYS` sentinel (never a
  source-relay fallback), `refresh_stale_peer_relays` (decrypts pubkey_enc
  inside the op only).
- `security.resolve_and_check_egress` (getaddrinfo off-loop, public-space
  only incl. 169.254.169.254, 60s TTL cache) shared by
  `transport.validate_peer_relay_target` and inbox-direction
  relay_configs writes.
- `transport.py`: `subscribe_to`, `handle_notifications`,
  `send_msg_to`, `unsubscribe`, `disconnect_relay`, `remove_relay`
  (pooled-relay reconnect quirk), `fetch_from`; `subscribe_to` +
  `send_msg_to` validate targets; `automatic_authentication(False)` +
  no signer anywhere.
- `tasks.py`: `infinitemarkets_inbox_listener` (session reconcile, 5s)
  + `infinitemarkets_inbox_processor` (leased drain); `settlement.reconcile`
  re-drives `received` rows (§8.7) — `validated` rows park for 03-02
  dispatch (documented TODO seam).
- `views_api.py`: `GET /merchants/{id}/relay-auth` (D-26 surface +
  connection state) and `POST /merchants/{id}/relay-auth/retry/{url}`
  clearing failed/paid states to `auth-required`.
- `harness/relay.py`: LocalRelay REQ->canned events + EOSE,
  AUTH_CHALLENGE (challenge + kind-22242 acceptance), PAID (negative-OK
  paid wording + payment-required CLOSED), AUTH_FLOOD, REQ/EOSE counters.

### Qualification-suite repair (`594e795`)

`make verify` gates this plan on the full suite; the earlier
gammamarkets->infinitemarkets rebrand had silently broken it before this
plan began:

- `harness/sdk.fixed_test_keys` now returns the fixture-pinned secrets
  for buyer/merchant (keys.json is fixture identity) and keeps
  deterministic derivation for other labels.
- `test_p0_14` identifier-closure regex widened for the post-rebrand
  spelling (it previously matched nothing and could never pass).

## Verification

- `make verify-runtime`: **265 passed, 2 skipped** (incl. 7 activation +
  14 transport tests).
- `make verify` (full suite incl. qualification): **485 passed,
  3 skipped**.
- `make verify-fast`: 33 passed. `make lint` (ruff): clean.
- `make host`: pinned host confirmed at `e336fe14`.

## Deviations / notes

- Admission splits stage-1 (socket path) vs stage-2 (leased drain)
  exactly per §8.5 — rows land `validated`, NOT dispatched; order-message
  handling is 03-02's seam (flagged TODO in code, not a hidden gap).
- NIP-42 answered per-connection via keystore signing; the SDK's
  `automatic_authentication` is disabled and no `NostrSigner` is attached
  to any transport client (source-level assertion in tests).
- nostr-sdk quirk discovered: `disconnect_relay` leaves a pooled relay
  whose reconnect silently swallows REQs — session teardown removes the
  relay entirely (`remove_relay`) so re-subscribe lands on the wire.
- `insecure_relays_allowed` hatch admits only genuine loopback `ws://`
  (`is_local_addr` also matches private ranges — re-checked against
  `ipaddress.is_loopback`).
- Pending: `inbox_blocklist`/`peer_relays` currently lack admin
  management endpoints beyond retry (mutes arrive via 03-02 domain flow).

## Metadata closeout — 2026-10-11

The empty requirement list omitted GAM-01 despite the kind-10050 activation
implementation and seven activation tests recorded above and the phase-level
verification. That link and the old Phase 2 dependency name are corrected here.
This does not close shared-commerce, retry/backlog or live-checkout findings;
current Phase 3 acceptance remains reopened in 03-VERIFICATION.md and Phase 5.
