---
phase: 09-branded-multipart-send-path
verified: 2026-10-18T20:08:26Z
status: gaps_found
score: 35/43 must-haves verified
covered_files:
  - .planning/REQUIREMENTS.md
  - .planning/ROADMAP.md
  - .planning/STATE.md
  - .planning/phases/09-branded-multipart-send-path/09-01-PLAN.md
  - .planning/phases/09-branded-multipart-send-path/09-01-SUMMARY.md
  - .planning/phases/09-branded-multipart-send-path/09-02-PLAN.md
  - .planning/phases/09-branded-multipart-send-path/09-02-SUMMARY.md
  - .planning/phases/09-branded-multipart-send-path/09-CONTEXT.md
  - .planning/phases/09-branded-multipart-send-path/09-RESEARCH.md
  - .planning/phases/09-branded-multipart-send-path/09-REVIEW.md
  - .planning/phases/09-branded-multipart-send-path/09-SECURITY.md
  - .planning/phases/09-branded-multipart-send-path/09-UI-REVIEW.md
  - .planning/phases/09-branded-multipart-send-path/09-VALIDATION.md
  - AGENTS.md
  - harness/email.py
  - infinitemarkets/services/email.py
  - infinitemarkets/services/merchant.py
  - infinitemarkets/services/orders.py
  - infinitemarkets/services/themes.py
  - infinitemarkets/static/infinitemarkets/js/public_order.js
  - infinitemarkets/views_public_api.py
  - tests/qualification/test_p0_10_smtp_boundary.py
  - tests/runtime/conftest.py
  - tests/runtime/test_email_queue.py
  - tests/runtime/test_email_render.py
  - tests/runtime/test_email_signin.py
  - tests/runtime/test_financial_review.py
covered_digest: "v1:sha256:0a3c9caf28555e8c98401e6df43e846f0d2dbc0a4174983ce72d0bee88dc6fc3"
behavior_unverified: 1
overrides_applied: 0
gaps:
  - truth: "The branded HTML header remains legible for every accepted theme accent, so a buyer can see the display-name wordmark."
    status: failed
    reason: "For the valid #000000 accent, the header inherits #1f2328 from the outer table instead of the computed on-accent foreground; the reproduced contrast is 1.33:1. This breaks the Plan 02 safe-header must-have and the ROADMAP requirement that buyers see the branded header."
    artifacts:
      - path: "infinitemarkets/services/email.py"
        issue: "The accent band at lines 511-515 does not set a contrast-safe foreground on the header content. _email_colors computes the CTA foreground at lines 285-298, but it is not applied to the header at lines 368-381."
      - path: "tests/runtime/test_email_render.py"
        issue: "test_sections_use_fullmatch_accent_and_readable_cta_contrast at lines 468-498 verifies CTA contrast (including accepted #000000) but does not assert header text contrast."
    missing:
      - "Apply a contrast-safe foreground to the accent header or use the documented accent top-rule on a light header."
      - "Add a header contrast regression for accepted dark accent values, including #000000."
behavior_unverified_items:
  - truth: "Two workers cannot confirm the same claimed row, and a transport thread completing after timeout/cancellation cannot cause an unobserved stale outcome or overlapping retry."
    test: "Run tests/runtime/test_email_queue.py::test_concurrent_email_claims_do_not_overlap on PostgreSQL and exercise a slow multi-stage fake SMTP exchange whose aggregate duration exceeds the wait_for budget."
    expected: "The PostgreSQL competing claims remain disjoint; after a timed-out attempt, the SMTP thread cannot later send while the same queue intent is being retried or commit a stale queue outcome."
    why_human: "The row-lock drill at tests/runtime/test_email_queue.py:869-899 skips on the local SQLite profile, and no test exercises a multi-stage SMTP thread continuing after asyncio.wait_for cancels its await. Local PostgreSQL is unavailable; the CI PostgreSQL matrix remains outstanding. The code-review WR-02 warning is therefore not closed by symbol presence or the current fake transport test."
---

# Phase 9: Branded Multipart Send Path Verification Report

**Phase Goal:** Every order-event email is delivered as a branded `multipart/alternative` message — the existing text render plus an HTML part — through the extension's own SMTP send path, with consent gating corrected.  
**Verified:** 2026-10-18T20:08:26Z  
**Status:** gaps_found  
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

Roadmap success criteria and both plans' `must_haves.truths` are evaluated
below independently of the SUMMARY claims. The three judgment-tier
prohibitions are included in the 43-item score and remain subject to the
interactive human-resolution gate.

#### ROADMAP.md Phase 9 success criteria

| # | Truth | Status | Evidence |
|---|---|---|---|
| R1 | An order-event email is constructed as plain + HTML alternatives and routed through the extension SMTP seam with host configuration and timeout/retry handling; host helper unchanged. | ? UNCERTAIN (external receipt) | `infinitemarkets/services/email.py:524-612, 643-880` constructs the message, reads host SMTP settings, sends via `_smtp_send` under `asyncio.wait_for`, and classifies outcomes. Fake transport tests verify call order and queue results (`tests/runtime/test_email_render.py:155-212`, `tests/runtime/test_email_queue.py:290-403`). No operator relay/inbox is configured, so actual receipt is not proven; see Human Verification Required. The host `send_email` implementation was not edited and is no longer called by this queue path. |
| R2 | A buyer sees the branded HTML shell, including a legible logo-or-display-name header with the accent, event/state, real item/order totals, live-only CTA, and channel footer. | ✗ FAILED | Shell sections and values are present in `infinitemarkets/services/email.py:318-520`; renderer tests cover them at `tests/runtime/test_email_render.py:249-367, 372-498, 542-600`. However, an accepted `#000000` accent produces a black header band with inherited `#1f2328` wordmark text. A direct render probe emitted that markup and `themes.contrast_ratio("#1f2328", "#000000") == 1.33`; the name is effectively unreadable. This is the single blocking gap, also captured in the Plan 02 truth below. |
| R3 | A stored `<script>` title is inert in both parts; digital delivery is customer/confirmed-only; subject contains display name + event, not PII/IDs. | ✓ VERIFIED | HTML escaping uses `html.escape(..., quote=True)` at `email.py:280-282` and dynamic fields are escaped through `_render_html` at `318-520`. Delivery is loaded only for customer-confirmed at `email.py:695-700` and gated again in rendering at `449-456`; subject uses only sanitized display name/event at `188-201`. `tests/runtime/test_email_render.py:372-465, 500-540` checks the channel/event gate and escaped HTML; the plain part keeps inert literal text as specified by D-10. |
| R4 | Merchant `notify_events` disables merchant shipped alerts without suppressing an opted-in customer; customer consent is rechecked at send time. | ✓ VERIFIED | Runtime suppression is merchant-order-only at `email.py:172-185`; consent is read in the worker transaction before transport (`643-710`). The runtime event test passed and asserts customer `sent` / merchant `suppressed` at `tests/runtime/test_email_queue.py:495-560`; revocation is checked at `467-493`. The qualification model matches at `harness/email.py:442-469` and `tests/qualification/test_p0_10_smtp_boundary.py:207-250`. |
| R5 | Received messages have safe encoded From, Date, sender-domain Message-ID, Auto-Submitted; send-test delivers the full sample shell despite event flags. | ? UNCERTAIN (external receipt) | The header builder is at `email.py:550-585`; parsing/sanitization assertions are at `tests/runtime/test_email_render.py:214-232`. `send_test_notification` validates configured recipients and hourly limits, then enqueues an orderless test row (`infinitemarkets/services/merchant.py:887-961`); the worker marks it as a test and renders synthetic content (`email.py:799-829, 912-940`). Runtime tests cover event-flag bypass/sample/gates at `tests/runtime/test_email_queue.py:604-790`. Those tests use a fake SMTP seam, not an operator relay, so receipt remains unverified. |

#### Plan 09-01 `must_haves.truths`

| # | Truth (plan shorthand) | Status | Evidence |
|---|---|---|---|
| P1-1 | D-02/03/05/07/08: complete multipart content for every channel; real order lines/totals and live CTA; `sent` only after confirmed transport success. | ✓ VERIFIED | Message construction and worker wiring are substantive at `email.py:318-586, 643-880`; queue success/failure and captured multipart parts are asserted in `test_email_queue.py:290-348`; MIME tree and parts are checked in `test_email_render.py:96-136`. |
| P1-2 | D-09/10/11/12: accent fullmatch and CTA contrast; HTML context escaping; delivery only customer-confirmed; live fragment-token checks. | ✓ VERIFIED | Accent uses `_EMAIL_HEX_COLOR.fullmatch` and computes CTA foreground (`email.py:65-68, 285-299`); token validation is `_status_link` (`615-637`). `test_email_render.py:372-498, 500-540` covers live/dead/corrupt tokens, delivery gate, accepted colors and escaping. Header contrast is a separate Plan 02 gap, not a failure of this truth's explicit CTA contrast assertion. |
| P1-3 | D-14/15/16/22: channel footers in both parts, dead-token no-link notice, account shell/link, synthetic test content, redacted preview. | ✓ VERIFIED | Text/HTML channel copy is in `email.py:204-263, 345-490`; preview substitutions are at `800-829`. Tests assert all channel footers in both parts (`test_email_render.py:542-600`), account fragment/wiping (`test_email_signin.py:398-493`), and redaction (`test_email_queue.py:426-465`). |
| P1-4 | D-04: false/exception/builder failure/timeouts retry or fail; expired claims do not send; sent wipes recipient/payload ciphertext; network outside DB transaction. | ✓ VERIFIED | Worker checks expiry before transport, exits the transaction before `_smtp_send`, and commits only after its result (`email.py:658-710, 745-746, 830-880`). `test_send_classification` passed and asserts sent/wipe/retry/failure (`test_email_queue.py:290-403`); expired claim check is `811-833`. |
| P1-5 | D-17: disabled merchant shipped alert is suppressed while opted-in customer sends; later revocation suppresses customer. | ✓ VERIFIED | `email.py:172-185`; passing runtime test at `test_email_queue.py:467-560`; qualification scenario at `test_p0_10_smtp_boundary.py:207-250`. |
| P1-6 | D-18/19/20/21: host From address with sanitized encoded name, Date, sender-domain Message-ID, Auto-Submitted; no Reply-To/List-Unsubscribe. | ✓ VERIFIED | Header assembly at `email.py:550-564`; `test_header_safety_and_deliverability_headers` checks parsed values, no recipient header, and omitted Reply-To/List-Unsubscribe (`test_email_render.py:214-232`). |
| P1-7 | D-25: host-compatible STARTTLS/login/sendmail, socket timeout, fail-closed session SMTP guard across setup/inter-test/teardown. | ✓ VERIFIED | `_smtp_send` mirrors the host order and supplies `timeout` (`email.py:589-612`); the accepted no-context `starttls()` choice is documented at `604-606`. The session guard and lifecycle assertions are at `tests/runtime/conftest.py:40-53, 125-135, 255-267`; the fake seam is at `465-501`. D-25's owner-locked unverified STARTTLS is not treated as a gap. WR-02 is a separate timeout/thread-lifetime warning, recorded below. |
| P1-8 | D-26: existing text event label reads “Order confirmed.” without doubled wording. | ✓ VERIFIED | `_render_body` composes the label at `email.py:204-248`; `test_plain_event_label_does_not_repeat_order` is at `test_email_render.py:235-246`. |
| P1-9 | EMAIL-01/boundary: expired lease sends nothing; positive budget is `min(30, remaining)` for `wait_for` and socket timeout, including 30 seconds. | ✓ VERIFIED | Expired-budget short-circuits and shared unrounded `budget` are visible at `email.py:830-848`; `_smtp_send` passes the same timeout to `smtplib.SMTP` at `589-612`. Fake transport verifies a fractional timeout is passed without rounding at `test_email_render.py:155-201`; expired claims are tested at `test_email_queue.py:811-833`. |
| P1-10 | EMAIL-01/empty: absent logo yields bare HTML; valid PNG/JPEG yields related HTML+image; missing items do not block message. | ✓ VERIFIED | Logo validation/fallback and related part assembly are at `email.py:524-586`; MIME test covers PNG, JPEG, unusable logo and no dangling CID at `test_email_render.py:96-136`; empty-order cases are at `297-345`. |
| P1-11 | EMAIL-01/encoding: Unicode parts round-trip as UTF-8 quoted-printable and serialized SMTP string is ASCII. | ✓ VERIFIED | Explicit charset/CTE and serialization path at `email.py:565-585`; `test_unicode_parts_round_trip_as_ascii_quoted_printable` and MIME test at `test_email_render.py:96-151`. |
| P1-12 | EMAIL-01/precision: positive remaining float is not rounded; text currency/quantity semantics remain stable. | ✓ VERIFIED | The deadline is monotonic and `budget=min(30, remaining)` is passed unchanged (`email.py:661, 830-848`); fractional transport timeout is asserted at `test_email_render.py:181-201`; integer sats and currency formatting are implemented at `301-317, 405-447` and covered by renderer value tests. |
| P1-13 | EMAIL-01/idempotency: duplicate intent is deduped; crash after SMTP acceptance remains explicitly at-least-once, not exactly-once delivery. | ✓ VERIFIED | Queue uniqueness/dedupe path is tested at `test_email_queue.py:201-223`; qualification explicitly demonstrates accepted-then-crash redelivery while retaining one intent (`test_p0_10_smtp_boundary.py:402-490`). |
| P1-14 | EMAIL-01/concurrency: two workers cannot confirm one row; claim-token CAS protects outcomes when a transport thread finishes after cancellation. | ⚠️ PRESENT_BEHAVIOR_UNVERIFIED | Claim-token CAS is implemented at `email.py:123-137, 855-880`; the PostgreSQL concurrency drill exists at `test_email_queue.py:869-899` but is skipped on SQLite. It does not test a slow multi-stage SMTP thread continuing after `wait_for` cancellation. The behavior is wired but not exercised in available PostgreSQL/timeout-race evidence. |
| P1-15 | EMAIL-11/empty: empty/all-control merchant name falls back to host sender address and safe subject. | ✓ VERIFIED | `_header_safe` and address fallback at `email.py:195-201, 550-560`; empty-name assertions at `test_email_render.py:221-232`. |
| P1-16 | EMAIL-11/encoding: Unicode, punctuation, bidi/control display names do not break headers or leak hostname. | ✓ VERIFIED | Unicode control stripping and sender-domain Message-ID at `email.py:195-201, 550-564`; assertions at `test_email_render.py:214-232` and `test_email_signin.py:398-468`. |
| P1-17 | EMAIL-09/empty: dead status token keeps opt-out explanation without invented href; preview contains no live order/account bearer fragment. | ✓ VERIFIED | `_status_link` checks expiry/decryption (`email.py:615-637`); dead link cases at `test_email_render.py:372-465, 656-670`; redacted queue/account previews at `test_email_queue.py:426-465` and `test_email_signin.py:398-468`. |

#### Plan 09-02 `must_haves.truths`

| # | Truth (plan shorthand) | Status | Evidence |
|---|---|---|---|
| P2-1 | D-07/08/09: 600px inline-CSS shell, preheader, safe theme-accent header, real values/backorder, live CTA and section order. | ✗ FAILED | Layout, preheader, values, CTA and section order exist (`email.py:318-520`) and are tested (`test_email_render.py:249-367, 372-498`). The header text is not contrast-safe for an accepted dark accent: the render probe for `#000000` produced `background:#000000` and inherited `#1f2328` text; computed contrast was 1.33:1. Existing contrast tests only inspect the CTA foreground. |
| P2-2 | D-05/06: existing text render plus D-26 and footer; synthetic valid logo creates one CID related part; invalid/absent logo falls back without dangling CID. | ✓ VERIFIED | Text render and logo paths at `email.py:204-263, 524-586`; MIME/logo tests at `test_email_render.py:96-136`; footer tests at `542-600`. |
| P2-3 | D-10/11/12/13: all HTML values escaped; delivery is customer-confirmed-only; no PII in subject/headers; bearer URLs remain fragments. | ✓ VERIFIED | Escaping and delivery gates at `email.py:280-282, 318-520, 695-700`; subject/header construction at `188-201, 550-564`; token links at `615-637, 776-799`. Tests at `test_email_render.py:372-465, 500-540`, `test_email_queue.py:798-809`, and `test_email_signin.py:398-493`. |
| P2-4 | D-14/15: fixed customer/account/merchant/test footer in both parts; expired customer link has no href; account has no order sections. | ✓ VERIFIED | Channel footer branches at `email.py:472-490`; tests at `test_email_render.py:542-600, 656-670` and `test_email_signin.py:398-493`. |
| P2-5 | D-16/17: orderless test send bypasses merchant event flag but keeps sample/gates/rate cap; customer remains opt-in-only. | ✓ VERIFIED | Test row is identified as `channel=merchant` with no order (`email.py:827-828, 912-940`); suppression gates at `160-185`; send-test API verifies recipient and hourly limit at `merchant.py:887-961`. Runtime coverage at `test_email_queue.py:495-560, 604-790`; named event-gate test passed. |
| P2-6 | D-18/19: encoded safe From, Date, sender-domain Message-ID, Auto-Submitted; no Reply-To/List-Unsubscribe. | ✓ VERIFIED | `email.py:550-564`; `test_email_render.py:214-232`. |
| P2-7 | EMAIL-02/adjacency: equal-valued adjacent item rows remain distinct and totals follow. | ✓ VERIFIED | Renderer iterates rows independently at `email.py:405-432`; `test_sections_keep_adjacent_equal_items_and_render_zero_item_order_totals` at `test_email_render.py:297-344`. |
| P2-8 | EMAIL-02/empty: account has no order totals; test has sample data; zero-item real order has indication and actual totals. | ✓ VERIFIED | Account view is orderless at `email.py:785-798`; test sample is rendered at `204-248, 493-500`; empty real orders show “No items in this order” at `427-447`. Coverage at `test_email_render.py:297-345, 542-600`. |
| P2-9 | EMAIL-02/encoding: Unicode display names/titles survive MIME encoding; HTML metacharacters remain inert. | ✓ VERIFIED | UTF-8 QP builder at `email.py:565-585`; tests at `test_email_render.py:138-151, 500-540` and `test_email_signin.py:398-493`. |
| P2-10 | EMAIL-02/ordering: items query is deterministic; header/event/items/totals/delivery/CTA/footer order is stable. | ✓ VERIFIED | Query orders by item id at `email.py:684-693`; render sections are appended in order at `318-520`; test checks ordering at `test_email_render.py:318-344`. |
| P2-11 | EMAIL-03/adjacency: only `channel=customer AND event_type=confirmed` admits delivery. | ✓ VERIFIED | Worker fetch and renderer both gate on that conjunction (`email.py:695-700, 449-456`); `test_sections_hide_dead_status_links_and_gate_delivery_exactly` at `test_email_render.py:372-465` and merchant delivery runtime test at `test_email_queue.py:563-602`. |
| P2-12 | EMAIL-03/empty: absent delivery gives no block; missing/expired/corrupt token yields no CTA or fabricated URL. | ✓ VERIFIED | `_status_link` returns no link on missing/dead token (`email.py:615-637`); rendering omits empty delivery/CTA (`449-469`). Tests at `test_email_render.py:372-465`. |
| P2-13 | EMAIL-03/encoding: hostile text and attributes are escaped; accent fullmatch rejects newline/CSS injection. | ✓ VERIFIED | `html.escape(..., quote=True)` at `email.py:280-282`; strict color match at `66, 285-299`; hostile input and newline/CSS assertions at `test_email_render.py:468-540, 601-655`. |
| P2-14 | EMAIL-03/ordering: delivery lines retain fetched order and appear after totals, before CTA/footer, without duplication. | ✓ VERIFIED | Delivery uses the order returned by `digital_delivery` and appends after totals (`email.py:695-700, 449-456`); ordering and exact channel gate covered by `test_email_render.py:318-344, 372-465`. |
| P2-15 | EMAIL-09/adjacency: account and orderless merchant test are distinguished by channel/event and get their correct footer/sample marker. | ✓ VERIFIED | Account view and test-send discriminator at `email.py:757-798, 815-828`; cross-channel assertions at `test_email_render.py:542-600` and real orderless send at `test_email_queue.py:604-674`. |
| P2-16 | EMAIL-09/empty: no live status token retains explanation without opt-out href; preview redacts repeated fragments. | ✓ VERIFIED | Customer footer no-link branch at `email.py:472-485`, preview replacements at `805-829`; tests at `test_email_render.py:433-465, 656-670`, `test_email_queue.py:426-465`, and `test_email_signin.py:398-493`. |
| P2-17 | EMAIL-09/ordering: mandatory channel footer follows optional copy and cannot be replaced. | ✓ VERIFIED | Optional copy is escaped and prepended while fixed footer stays last (`email.py:472-490`); `test_footer_optional_copy_is_escaped_and_never_replaces_channel_notice` at `test_email_render.py:601-655`. |
| P2-18 | EMAIL-02/contrast: accepted `#777777` uses black CTA text and tested CTA colors meet 4.5:1. | ✓ VERIFIED | `_email_colors` selects black when white fails (`email.py:285-299`); `test_sections_use_fullmatch_accent_and_readable_cta_contrast` passed and asserts this boundary at `test_email_render.py:468-498`. This verifies CTA contrast only, not the failed header contrast in P2-1. |

#### Plan prohibitions (judgment tier)

| # | Must NOT happen | Status | Evidence |
|---|---|---|---|
| H1 | Transactional email must not become open tracking or leak recipient identity. | ? UNCERTAIN — human resolution required | No remote content is emitted by `_render_html` (`email.py:318-520`); recipient is passed as SMTP envelope argument and omitted from MIME headers (`email.py:436-438, 550-585`); `test_email_render.py:214-232` and `test_email_queue.py:835-842` provide supporting evidence. Interactive judgment sign-off is still required by the verifier contract. |
| H2 | A test/sample email must not appear to be a real buyer purchase or contain real order data. | ? UNCERTAIN — human resolution required | Orderless test discriminator and fixed synthetic content are at `email.py:204-248, 493-500, 827-828, 912-940`; `test_email_queue.py:604-674` asserts sample markers and absence of real order/recipient content. Human resolution remains outstanding. |
| H3 | An expired protected status token must not be presented as an actionable opt-out link. | ? UNCERTAIN — human resolution required | Dead-token handling and no-link footer are at `email.py:615-637, 472-485`; tests at `test_email_render.py:433-465, 656-670` verify no `href`. Human resolution remains outstanding. |

**Score:** 35/43 must-haves verified (35 verified, 2 failed, 2 uncertain,
1 present/behavior-unverified, and 3 judgment-tier prohibitions awaiting human
resolution).

### Deferred Items

None. The later Phase 10 roadmap covers merchant branding controls and
preview UI; Phase 11 covers contracts/release qualification. Neither
explicitly addresses the failed header foreground contrast, so this is not
deferred.

## Required Artifacts

Every artifact named in both plans' `must_haves.artifacts` exists and is
substantive. Levels 1–3 (existence, substance, wiring) pass except for the
scoped header contrast issue in the shared renderer.

| Artifact | Expected | Status | Details |
|---|---|---|---|
| `infinitemarkets/services/email.py` | MIME builder, renderer, SMTP transport, worker wiring and suppression | PASS WITH GAP | Pure `_build_message`, substantive `_render_html`, `_smtp_send`, worker call path and DB outcomes at lines 318-880; wired from queue worker. Header foreground gap is documented above. |
| `tests/runtime/test_email_render.py` | Fast MIME, HTML safety, header, footer, fake SMTP tests | PASS | `pytestmark` includes `fast`; substantive value/behavior assertions at lines 96-670; exact header-contrast assertion is missing. |
| `tests/runtime/conftest.py` | Session-lifetime fail-closed SMTP guard and capture seam | PASS | Guard is autouse for session and is asserted before host startup and through teardown (`40-53, 125-135, 255-267`); `smtp_capture` patches the live module global (`465-501`). |
| `tests/runtime/test_email_queue.py` | Durable outcome, suppression, preview, test-send, concurrency tests | PASS WITH BEHAVIOR LIMIT | Queue state and gates are behaviorally covered; PostgreSQL claim concurrency drill at `869-899` skips on local SQLite. |
| `tests/runtime/test_email_signin.py` | Account multipart magic link, fragment and wipe assertions | PASS | Live module seam and both MIME parts checked at `398-493`. |
| `tests/runtime/test_financial_review.py` | Background review delivery observes extension send seam | PASS | `test_review_public_delivery_snapshot_serializes_cancellation` uses `smtp_capture` at lines 342-399. Its PostgreSQL interleaving variant is part of the stated skip set. |
| `harness/email.py` | Merchant-only event suppression model | PASS | Model gate applies to merchant order alerts and rechecks customer consent (`442-469`). |
| `tests/qualification/test_p0_10_smtp_boundary.py` | Qualification cases for suppression, outcomes and at-least-once semantics | PASS | Separate merchant/customer scenarios at `194-250`; crash-after-acceptance behavior at `402-490`. |

No route, schema, migration, admin UI or host notification-helper changes are
required by this phase. The code path is extension-owned; test-send input is
wired through `merchant.send_test_notification` into `enqueue_test_send` and
the same worker as order events.

## Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| `infinitemarkets/services/email.py` | `tests/runtime/conftest.py` | Module-global `_smtp_send` capture and `smtplib.SMTP` guard | WIRED | `worker_tick` resolves `_smtp_send` at call time (`email.py:845-848`); `smtp_capture` patches the imported live module (`conftest.py:465-501`); session guard spans host setup and teardown (`40-53, 125-135, 255-267`). |
| `infinitemarkets/services/email.py` | `harness/email.py` | Matching merchant-only event and send-time customer-consent semantics | WIRED | Runtime gate at `email.py:172-185`; harness counterpart at `harness/email.py:442-469`; qualification coverage at `test_p0_10_smtp_boundary.py:207-250`. |
| `harness/email.py` | `tests/qualification/test_p0_10_smtp_boundary.py` | Separate merchant/customer row scenarios | WIRED | Qualification test exercises merchant suppression and customer send with same disabled event (`207-240`); named test passed. |
| `infinitemarkets/services/email.py` | `infinitemarkets/services/themes.py` | `parse_theme` / `resolve_tokens` / `contrast_ratio` | WIRED WITH GAP | Theme accent resolves at `email.py:285-299`; CTA has contrast check. Header does not use the computed foreground (the sole blocking gap). |
| `infinitemarkets/services/email.py` | `infinitemarkets/services/orders.py` | Ordered DB item query and `digital_delivery` only for customer-confirmed | WIRED | `email.py:684-700` queries actual line values ordered by item ID and calls delivery only under the exact channel/event conjunction. |
| `infinitemarkets/services/email.py` | `infinitemarkets/views_public_api.py` / public order page | Status/opt-out fragment link | WIRED | `_status_link` creates only fragment links (`email.py:615-637`); the existing opt-out API at `views_public_api.py:411-435` locks the order, clears consent/token and suppresses queued customer rows; front-end action path is `static/infinitemarkets/js/public_order.js:16` and the existing status page. |
| `infinitemarkets/services/email.py` | Host SMTP configuration | `lnbits_email_notifications_*` settings | WIRED | `_smtp_send` reads server, port, sender, username fallback and password (`email.py:589-612`); it never calls the host `send_email` helper. |
| Test-send endpoint/service | Queue worker | Configured recipient + hourly cap → orderless queue row → sample render | WIRED | `merchant.py:887-961` validates/configures and enqueues; `email.py:912-940` creates the row; `worker_tick` marks it as test (`799-829`). |

## Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|---|---|---|---|---|
| `email.py::_render_html` | `items`, line prices/totals, order totals, state | Current `orders` and `order_items` rows selected inside `worker_tick` (`684-693`) | Yes | FLOWING; ordered DB values feed text and HTML render. |
| `email.py::_render_html` | `delivery` | Existing `digital_delivery(tx, order)` (`695-700`) | Yes | FLOWING only for customer + confirmed; render repeats the gate (`449-456`). |
| `email.py::_email_colors` | `accent` | Merchant `theme` parsed and resolved by `services/themes.py` (`285-299`) | Yes | FLOWING and injection-validated; CTA contrast passes. Header text contrast does not. |
| `email.py::_status_link` | Buyer status/opt-out token | Protected `orders.public_token_enc`, AEAD/expiry checks (`615-637`) | Yes, while live | FLOWING; fragment-only; dead token yields `None`, and preview substitutes the token. |
| `email.py` account rendering | Sign-in token/link | Encrypted `payload_enc`, decrypted in send path (`757-799`) | Yes | FLOWING in sent body fragment; preview substitutes `[sign-in link omitted]`; sent row wipes ciphertext (`853-860`). |
| `email.py` test rendering | Sample title/items/totals | Deliberate fixed synthetic sample for an orderless merchant row (`204-248`) | No DB order by design | FLOWING as explicitly labeled sample; no real order data or CTA. |
| `email.py::_smtp_send` | SMTP message, recipient, transport settings | `_build_message` plus host SMTP settings (`524-612`) | Yes | FLOWING through the extension's `smtplib` call; real relay receipt not observed. |

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|---|---|---|---|
| MIME alternative, UTF-8/CID structure; valid theme colors and CTA contrast; live/dead token and delivery channel gating | `uv run pytest tests/runtime/test_email_render.py::test_mime_tree_is_alternative_with_optional_related_logo tests/runtime/test_email_render.py::test_sections_use_fullmatch_accent_and_readable_cta_contrast tests/runtime/test_email_render.py::test_sections_hide_dead_status_links_and_gate_delivery_exactly -q` | 3 passed in 0.16s | PASS |
| Merchant toggle disabled while customer shipped remains delivered | `uv run pytest tests/runtime/test_email_queue.py::test_notify_events_gate_merchant_only -q` | 1 passed in 2.16s | PASS |
| Durable success/retry/failure and qualification suppression semantics | `uv run pytest tests/runtime/test_email_queue.py::test_send_classification tests/qualification/test_p0_10_smtp_boundary.py::test_suppressed_rows_never_touch_smtp -q` | 2 passed in 2.42s | PASS |
| Accepted dark accent header foreground | `uv run python -c` rendering test helper with accent `#000000`, then `contrast_ratio("#1f2328", "#000000")` | Rendered header contains `background:#000000` and no text-color override; contrast 1.33:1 | FAIL — blocker |

The complete final suite and project gates below are independent evidence
provided for this verification, not rerun here. The verifier ran only the
named checks shown above, consistent with the keep-fast rule.

## Probe Execution

No executable `probe-*.sh` path is declared in either plan or summary.
The plans' “Fallback probe EMAIL-…” entries are behaviors, not script paths;
each was checked against source and the named/unit/runtime evidence above.
No missing-probe failure is inferred.

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|---|---|---|---|---|
| EMAIL-01 | 09-01, 09-02 | Plain + branded HTML MIME via extension-owned SMTP and queue timeout/retry path | UNCERTAIN for live relay receipt; code path verified | MIME/transport/queue tests; `email.py:524-612, 830-880`. Actual operator SMTP receipt is manual-only in `09-VALIDATION.md:75-82`. |
| EMAIL-02 | 09-01, 09-02 | Branded HTML sections, real totals, live status CTA and channel footer | PARTIAL — blocking header contrast gap | Renderer tests establish content/CTA/footer; direct `#000000` probe demonstrates 1.33:1 wordmark contrast. |
| EMAIL-03 | 09-01, 09-02 | Context-safe HTML, customer-confirmed delivery only, no PII/internal IDs in subject | VERIFIED | Escaping and delivery gating tests at `test_email_render.py:372-540`; queue subject assertion at `test_email_queue.py:798-809`; account headers/previews at `test_email_signin.py:398-493`. |
| EMAIL-08 | 09-01, 09-02 | Merchant event flags affect merchant channel only; customer consent rechecked at send time | VERIFIED | Runtime event and revocation tests `test_email_queue.py:467-560`; qualification scenario `test_p0_10_smtp_boundary.py:207-250`. |
| EMAIL-09 | 09-01, 09-02 | Correct customer/account/merchant/test footer in both parts | VERIFIED | `test_email_render.py:542-670`, `test_email_signin.py:398-493`, preview test `test_email_queue.py:426-465`. |
| EMAIL-10 | 09-01, 09-02 | Test sends use representative sample and ignore merchant event flags, subject to global gates/rate cap | UNCERTAIN for live relay receipt; sample queue path verified | `merchant.py:887-961`; `test_email_queue.py:604-790` proves fake-transport send, sample isolation, global suppressions and five-per-hour limit. |
| EMAIL-11 | 09-01, 09-02 | Sanitized encoded From, Date, sender-domain Message-ID and Auto-Submitted | VERIFIED at built-message/transport boundary | `email.py:550-564`; parsed header assertions at `test_email_render.py:214-232`; live receipt remains manual-only. |

Requirements EMAIL-04..07 are Phase 10 and EMAIL-12..13 are Phase 11; they
are explicitly outside Phase 9 scope and are not counted as gaps.

## Test Quality Audit

| Test File(s) | Linked Requirement(s) | Active / Skipped Evidence | Circular | Assertion Level | Verdict |
|---|---|---|---|---|---|
| `tests/runtime/test_email_render.py` | EMAIL-01/02/03/09/11 | 14 renderer tests; 3 named checks passed in this verification | No write/generate-under-test patterns found | Value + behavior: MIME tree, exact header values, escaped output, section order, link states | Effective; missing header-specific contrast assertion is the reported gap. |
| `tests/runtime/test_email_queue.py`, `test_email_signin.py`, `test_financial_review.py` | EMAIL-01/03/08/09/10/11 | Supplied combined targeted suites: 141 passed, 6 PostgreSQL-only skips | No circular fixture-generation patterns found | Multi-step queue transitions, send seam, state/wipe/preview and gate assertions | Effective for covered profiles; PostgreSQL row-lock/interleaving evidence remains pending. |
| `tests/qualification/test_p0_10_smtp_boundary.py` | EMAIL-08 and queue outcome/idempotency supporting EMAIL-01 | Plan evidence: 9 passed; a named suppression scenario passed here | No circular patterns found | Behavioral model outcomes and row-state assertions | Effective; documents at-least-once send semantics. |

No static `skip` decorators or disabled tests were found in linked email
tests. Conditional `pytest.skip` calls exist for PostgreSQL-only drills
(`test_email_queue.py:869-907`) and unrelated profile-specific runtime
interleavings; the local SQLite run therefore does not prove those behaviors.
The phase-level test quality scan found 0 circular patterns and 0 unreferenced
TBD/FIXME/XXX debt markers in the changed implementation/test files.

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|---|---:|---|---|---|
| `infinitemarkets/services/email.py` | 368-381, 511-515 | Header wordmark inherits `#1f2328` on accepted `#000000` accent (1.33:1). | BLOCKER | Fails legible branded-header must-have for a supported accent; see structured gap. |
| `infinitemarkets/services/email.py` | 589-612, 841-880 | `asyncio.to_thread` await can be canceled while its blocking SMTP thread continues; socket timeout is per blocking operation, not one absolute exchange deadline. | WARNING / behavior not closed | WR-02 is relevant to timeout/retry discipline, but no named red test was run. Track with the unverified concurrency truth and verify with a slow multi-stage transport test. This is distinct from the accepted D-25 STARTTLS certificate-verification choice. |
| `infinitemarkets/services/email.py` | 402-425 | Email table headings omit explicit `scope="col"` and the four-column table lacks narrow-client reflow. | INFO | UI review recommendation; not an explicit Phase 9 must-have and does not change the status. Real-client UAT remains required. |
| `infinitemarkets/services/email.py` | 604-606 | STARTTLS has no SSL context, so host-compatible behavior does not verify relay certificates. | ACCEPTED — not a gap | Explicit D-25 owner decision, documented in `.planning/STATE.md:189` and `09-SECURITY.md` accepted-risk log. Do not rewrite this choice as part of Phase 9 verification. |

The code-review advisory has 0 critical and 2 warnings. WR-01 is promoted to
the single blocker because it defeats the plan's safe branded header for an
accepted accent. WR-02 is relevant to the timeout surface but is reported as
a behavior-evidence warning rather than a second failed truth: the promised
wait-for/socket-timeout path exists, while post-cancellation transport
ordering is not exercised. The user-approved D-25 unverified STARTTLS policy
is not the WR-02 finding and remains accepted.

## Human Verification Required

The external and judgment checks below remain open. Because a deterministic
must-have failure exists, overall status is `gaps_found` rather than
`human_needed`; these items are preserved for resolution after gap closure.

### 1. Fix and inspect the branded header in real clients

**Test:** After correcting the header foreground, send a sample to Gmail web,
Apple Mail and Outlook desktop using both a default accent and an accepted
dark accent such as `#000000`.  
**Expected:** The display-name wordmark/logo fallback is clearly legible on
the accent band; the item table and footer remain visible at desktop/mobile
widths.  
**Why human:** Mail-client rendering differs, and the current contrast
failure is deterministic in the generated HTML but visual fidelity requires
client inspection.

### 2. Verify live SMTP delivery and received MIME

**Test:** With an operator-configured host SMTP relay and test inbox, use the
existing Notifications send-test action. Inspect the received raw message.  
**Expected:** One received message with `multipart/alternative`, plain then
HTML (and both parts readable), encoded From, Date, sender-domain Message-ID,
Auto-Submitted, labeled synthetic sample content, and no remote resources.  
**Why human:** No operator relay/inbox is configured; automated tests capture
a fake SMTP transport and do not prove relay acceptance or receipt.

### 3. Close PostgreSQL concurrency evidence

**Test:** Run `test_concurrent_email_claims_do_not_overlap` and
`test_email_rate_limit_is_atomic` in the PostgreSQL CI profile; also add/run
the slow multi-stage fake-transport scenario called out by WR-02.  
**Expected:** Concurrent claims/rate buckets remain disjoint/atomic and a
timed-out transport cannot later send during a retry or write stale state.  
**Why human:** The local SQLite profile skips the PostgreSQL drills and no
current test exercises thread continuation after `wait_for` cancellation.

### 4. Resolve judgment-tier prohibitions

**Test:** Human reviewer explicitly confirms each must-not constraint against
the implementation and evidence:
1. no tracking/remote content or recipient identity leakage;
2. test messages cannot be mistaken for real purchases or disclose real
   order data;
3. expired status-token notices never claim an actionable opt-out link.
**Expected:** Record an explicit human resolution for all three Plan
prohibitions; source and tests provide supporting evidence but do not replace
this judgment-tier checkpoint.  
**Why human:** Both plans classify these as `verification: judgment`, for
which the verifier contract requires interactive human resolution.

### 5. Disposition the unclassified fallback assumptions

**Test:** Review the plans' flagged unresolved fallback probes
EMAIL-08/unclassified and EMAIL-10/unclassified against the shipped
runtime/qualification cases and record their explicit disposition.  
**Expected:** Confirm the tests cover consent revocation, merchant/customer
event separation, test sample isolation, event-flag bypass and global gates;
do not claim the probe itself was classified by its missing classifier.  
**Why human:** The plans intentionally leave these fallback labels without a
class or testable predicate and request manual review.

## Gaps Summary

The extension-owned path is substantively implemented and wired: real queue
rows feed `EmailMessage`, host SMTP settings feed the `smtplib` transport,
channel footers and preview redaction are present, and consent gates are
independently exercised. All seven Phase 9 requirement areas have code/test
coverage; EMAIL-02 is partial for one supported dark accent.

One must-have fails deterministically: the branded wordmark is rendered at
1.33:1 contrast on an accepted black accent. Two ROADMAP criteria that
promise an actually received email remain externally unverified because no
relay/inbox is configured. One concurrency/timeout invariant remains
behavior-unverified pending the PostgreSQL profile and a cancellation-race
test. Three judgment-tier prohibitions and the two flagged unclassified
assumptions need explicit human disposition. Phase 10/11 do not explicitly
defer the header-contrast defect.

## Verification Evidence

**Independent evidence supplied for this verification (not rerun):**

- Final unwrapped `uv run python -m pytest -x -q`: **1122 passed, 8 skipped**.
  Skips include PostgreSQL-only drills, external relay smoke disabled, and a
  private Shopify sample unavailable.
- `make verify-fast`: **332 passed, 2 skipped**.
- Targeted Plan 02 runtime email suites: **141 passed, 6 PostgreSQL-only
  skips**.
- Ruff and post-wave Python compilation gate clean.
- Build gate: bare `python` was unavailable on PATH; rerunning with
  `uv run python` passed. An earlier timeout-wrapped full pytest attempt
  exited 124 at 44%; the same full one-shot suite then completed green, so
  the wrapper exit is not reported as a test failure.

**Verifier-run checks:** the named behavioral checks above passed, except for
the deterministic header contrast probe. No full test suite was rerun.

---

_Verified: 2026-10-18T20:08:26Z_  
_Verifier: Claude (gsd-verifier)_
