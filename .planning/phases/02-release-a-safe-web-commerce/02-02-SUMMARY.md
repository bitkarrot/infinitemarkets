---
phase: 02-release-a-safe-web-commerce
plan: "02"
requirements-completed: [PUB-01, WEB-01, UI-03]
metadata_reconstructed: 2026-10-11
acceptance_scope: historical-delivery
---

**Historical execution record:** metadata reconstructed from the original plan,
summary and phase verification on 2026-10-11. Current Phase 2 acceptance is
reopened; this header does not close F1–F4 or create a new test pass.

# 02-02 Summary — relay transport, outbox publisher, public storefront, themes

## Tasks completed

1. **OQ6 probe + owned transport + §8.6 publisher + relay health + tasks + metrics**
2. **NIP-89 handler + public read API + standalone storefront pages**
3. **Theme token backend + presets + `.gm-public` scoping**

## OQ6 findings (pinned in tests/runtime/test_outbox.py)

| # | Question | Pinned behavior (nostr-sdk 0.44.8) |
|---|---|---|
| A | Does `send_event_to` require a prior connect? | **Yes.** A relay added but never connected lands in `output.failed` as `'relay is initialized but not ready'` — no exception, no EVENT reaches the relay. `RelayTransport.send_to` therefore `add_relay`+`connect_relay`s every validated target before sending. |
| B | Unreachable relay outcome? | `client.connect()` swallows connection-refused; `send_event_to` returns `failed: 'relay not connected'`. **Never an exception, never in `success`.** Transient transport failures share the failed map with real negative-OK rejections — the worker classifies `{timeout, relay not connected, relay is initialized but not ready}` as retryable `timeout` and preserves any other message verbatim as `rejected`. |
| C | Unregistered target? | `send_event_to` to a URL never `add_relay`'d **raises** `Generic no relays` — the only observed exception path. The worker converts any residual exception into timeout evidence; one relay failure never crashes the claim batch. |

## Implementation

- `services/transport.py` — owned `Client` (no signer ever attached; signing is per-event via `MerchantKeyStore`), bounded `RelayLimits`, `autoconnect(False)`, revalidation of every target on connect/reconnect/send. Test-only escape hatches: `INFINITEMARKETS_ALLOW_INSECURE_RELAYS=1` (ws:// loopback only, for `LocalRelay`) and `INFINITEMARKETS_RELAY_IO=off` (host-boot tests never dial real relays).
- `services/relay.py` — target resolution (`public|inbox|both` + enabled; `merchant_id NULL` server-wide defaults supplement merchant rows), starter defaults seeded on first publish (`ensure_default_relays`), Blossom endpoint config (see deltas), health aggregation from `relay_publications`, owner-scoped outbox listing + retry.
- `services/outbox.py` — §8.6 worker: atomic claim (`BEGIN IMMEDIATE` bounded select/update on SQLite; `FOR UPDATE SKIP LOCKED` on PG), dependency gate, newer-live-revision supersession, render-from-current-state, per-event keystore signing, `created_at = max(now, latest+1)` with clock-skew pause, `send_event_to`, one durable `relay_publications` row per copy+relay with verbatim evidence, quorum/outcome policy, `min(2^n·5s, 30min)+jitter` backoff, claim-token CAS on every leased write, lease-expiry recovery reconstructing accepted targets, `worker_db()` per-worker handle, per-attempt metrics counters.
- `services/tasks.py` — `outbox_publisher` (5s) + `relay_manager` (30s health tick) registered via host `task_manager`, handles tracked by `register_owned_task`, cancelled by `infinitemarkets_stop` (now async — closes the transport; the host awaits coroutine stop hooks).
- `services/metrics.py` — outbox depth, oldest-pending age, per-state counts, outcome counters.
- `services/readiness.py` — gate structure; checkout fails closed (503) until 02-03.
- `services/nip89.py` + `views.py` + `views_public_api.py` — naddr decode/resolve (local only, hints never fetched), canonical product page, collection/merchant pages, §5.4 JSON reads, 120/min/IP rate limit on HMAC'd scope (raw IPs never stored), `no-store`/`no-referrer`/restrictive-CSP standalone documents, all UI-SPEC A1 states.
- `services/themes.py` + `static/infinitemarkets/css/{gm-public,themes/*}.css` — three presets, bounded Brand Basics, opt-in Advanced Tokens over an allowlist, server-side WCAG ≥4.5:1 gates naming pair+ratio, `.gm-public`-scoped emission never on admin docs.
- `templates/infinitemarkets/public_*.html` + `public_storefront.js` — standalone docs; buy form POSTs the real `/api/v1/public/checkout` contract (route lands in 02-03; errors surface honestly); order shell strips the fragment token via `history.replaceState`.

## Spec deltas (recorded per plan)

- **W-NEW-1**: two admin routes beyond §5.1 — `GET /merchants/{id}/outbox` (owner-scoped, ≤100 rows, intents + per-relay publications + dependency markers) and `POST /merchants/{id}/outbox/{intent_id}/retry` (failed/partially_published only; accepted targets never resent).
- **Blossom delta**: `blossom_servers` is a merchant `settings`-table entry (`PATCH /merchants/{id}` field + `GET …/relay-health` surface), not a `relay_configs` row — Blossom is an HTTPS media protocol, not a nostr relay. Strict `https://` validation, no userinfo/fragments/raw IPs/internal hosts, starter default `blossom.nostr.build`.
- **Starter defaults**: merchants publishing with zero configured relays are seeded with visible, editable rows (`relay.damus.io`, `nos.lol`, `relay.nostr.net`) — no hidden fallback (owner directive 2026-09-22).
- **§10 lease deviation (as planned)**: `relay_manager` ticks unleased per worker — each worker owns its own `Client` and manages only its own connections; publication evidence remains claim-fenced in the publisher.
- **`relay_configs.direction`** uses the normative `public|inbox|both` vocabulary (fixed an earlier `outbox` default in `merchant.py`).

## Deferred by design

- NIP-17 inbox/subscription duties (Release B), `POST /public/checkout` + order-status polling (02-03), admin UI (02-04), full checkout flow wiring (02-03 enables; the A1 buy form posts the real contract and surfaces errors honestly meanwhile).

## Verification

```
uv run ruff check .                    → all checks passed
uv run pytest tests/runtime -q         → 112 passed
GAMMA_QUAL_EVIDENCE=1 uv run pytest -q → 332 passed, 1 skipped
```

Not verified: PostgreSQL `FOR UPDATE SKIP LOCKED` path (CI exercises it); real external relay behavior beyond the pinned local evidence (advisory smoke remains opt-in).
