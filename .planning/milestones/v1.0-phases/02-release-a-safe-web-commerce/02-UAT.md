---
status: complete
phase: 02-release-a-safe-web-commerce
source:
  - 02-01-SUMMARY.md
  - 02-02-SUMMARY.md
  - 02-03-SUMMARY.md
  - 02-04-SUMMARY.md
started: 2026-09-27T07:17:00Z
updated: 2026-09-27T22:44:58Z
---

## Current Test

[testing complete]

**Redesign delivered for re-test (2026-09-27):** admin store bar with View storefront + Storefront nav item; semantic, labelled state badges and readable history; plain-language closed-order note; Appearance panel no longer clips its left edge (tab-panel inset + grid choice cards). Storefront: header nav on every page (Shop, collections, Track order) and a footer; a Track-order page that accepts a pasted order link and explains lost-link recovery; shipping/delivery and trust signals before checkout; colour-coded order status. Digital delivery: merchants add encrypted delivery content per digital product; buyers see it on the order page, checkout card and confirmation email only after LNbits-confirmed payment (T-205-01).

**Re-test issue and fix (2026-09-27):** the user still saw grey order states, selecting a digital order rendered a blank detail page, and a blank optional email appeared to block invoice rendering. Investigation reproduced the first two when current HTML loaded a cached pre-redesign `admin_orders.js` (`gmStateStyle is not a function`); first-party assets had unversioned URLs. The fix gives one content revision to every first-party asset URL and marks the admin document `no-store`. Email remains optional: updates are disabled and cleared until a valid email is entered, including browser-restored form state. The fresh 5099 demo passed digital detail, distinct state colours, and blank-email invoice checks in Guided layout; all three human UAT tests subsequently passed.

## Tests

### 1. Buyer price and checkout clarity
expected: The updated storefront shows a correct, readable server-priced quote and invoice amount. Shipping and quantity changes update the total; unavailable quotes do not initiate a payment. Retry/error messages do not invite a second payment.
result: pass

### 2. Order link and merchant operations
expected: Opening a private order link removes the URL fragment immediately; the status remains private. The merchant sees that order in a split list/detail workspace, including lawful actions, audit chronology and publication evidence without buyer secrets.
result: pass

### 3. Responsive storefront and appearance
expected: Editorial, Guided and Compact remain visually distinct, mobile checkout remains usable, a multi-image product has accessible gallery controls where the layout shows thumbnails, and each theme has readable text, focus and button states. Admin chrome is unaffected by a merchant's public theme.
result: pass

## Summary

total: 3
passed: 3
issues: 0
pending: 0
skipped: 0
blocked: 0

Machine evidence is separate: 13 Chromium tests passed against each isolated SQLite and PostgreSQL server; seven Chromium smoke tests passed on the fresh port 5099 demo without creating or settling an order, and its quote route returned HTTP 200 with a 2,500-sat total. Neither those tests nor earlier demo screenshots count as a new human response to the tests above. The user-requested 5099 replacement runs current code on a fresh disposable database; the prior demo's database files were left untouched but are not mounted in this demo.

**Buyer UI refinement before UAT (2026-09-27):** the product/checkout pages were polished after the green CI run — major-unit prices (`2,500 sats` / `15.00 USD`), checkout column beside the gallery (sticky when it fits), compact/guided thumbnail header, quantity stepper, option chips, clearer summary and quote-error messages, guided Pay step with a single invoice CTA, and an invoice view with “Open in wallet”. Blank or short state codes (`IL` → `US-IL`) no longer break the shipping quote. Checkout semantics, totals, payment states and security copy are unchanged. SQLite/PostgreSQL public/checkout runtime tests (77 each), the full SQLite suite (448 passed, 3 skipped) and 15 Chromium tests passed locally.

**Latest UAT-fix evidence (2026-09-27):** current-head CI run 36352552899 passed lint and all SQLite/PostgreSQL Linux x86_64/ARM64 profiles for `021c402`. The cache/email fix also passed 13 buyer/admin runtime tests on SQLite and 13 on isolated UTC PostgreSQL, all 19 Chromium tests on a fresh server, and focused checks on the current 5099 Guided demo. Ruff, JavaScript syntax and diff checks passed. Human UAT passed 3/3.

## Gaps

- truth: "The merchant can open the live storefront in one click from the admin's top-level navigation"
  status: resolved
  reason: "User reported: the view public storefront link should be on top level navigation"
  severity: minor
  test: 2
  resolved_by: 021c402
  resolved_at: 2026-09-27
- truth: "Closed-order copy is plain language, not state-machine jargon"
  status: resolved
  reason: "User reported: What does \"No Legal Action\" mean?"
  severity: minor
  test: 2
  resolved_by: 021c402
  resolved_at: 2026-09-27
- truth: "Order states are visually distinct (color plus label) in admin and buyer views"
  status: resolved
  reason: "User reported: the order status labels are all grey"
  severity: minor
  test: 2
  resolved_by: 021c402
  resolved_at: 2026-09-27
- truth: "Settings → Appearance lays out without clipping at desktop widths"
  status: resolved
  reason: "User reported: the left side of the content is cutoff"
  severity: major
  test: 3
  resolved_by: 021c402
  resolved_at: 2026-09-27
- truth: "Storefront has top-level navigation, a way back to the shop and to order tracking"
  status: resolved
  reason: "User reported: there's no navigation bar ... no way for users to navigate back to their product if they lose the link to their order"
  severity: major
  test: 3
  resolved_by: 021c402
  resolved_at: 2026-09-27
- truth: "A buyer can tell how a digital product is delivered and receives it after payment"
  status: resolved
  reason: "User reported: its unclear how does one download a digital product"
  severity: major
  test: 1
  resolved_by: 021c402
  resolved_at: 2026-09-27
- truth: "A blank optional email never blocks Lightning invoice creation"
  status: resolved
  reason: "User reported: email is required or else the Lightning invoice is not rendered"
  severity: major
  test: 1
  resolved_by: 021c402
  resolved_at: 2026-09-27

Decisions from this session (2026-09-27): web buyers keep per-order private links (no accounts); a "Track order" page and nav are added now. Nostr buyer order history via NIP-17, a NIP-07 sign-in, and a merchant `web_checkout_enabled` switch for Nostr-only shops are deferred to Phase 3. Digital delivery: merchant-entered, encrypted per-product delivery content revealed only after LNbits-confirmed payment.
