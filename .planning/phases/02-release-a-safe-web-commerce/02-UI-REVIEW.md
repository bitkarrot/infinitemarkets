# Phase 2 — UI Review

**Audited:** 2026-09-27  
**Baseline:** `02-UI-SPEC.md`, approved sketch findings and ecommerce design guide  
**Visual evidence:** live 5099 review plus current Playwright desktop/375px assertions; screenshot binaries were not retained  
**Human result:** UAT 3/3 passed after the cache-coherency, optional-email and appearance fixes

## Pillar Scores

| Pillar | Score | Key finding |
|--------|-------|-------------|
| 1. Copywriting | 4/4 | Payment, closed-order, recovery and digital-delivery copy is plain, specific and action-oriented. |
| 2. Visuals | 4/4 | Product hierarchy, persistent checkout summary and Linear-style order workspace are clear across desktop/mobile modes. |
| 3. Color | 4/4 | Theme contrast is save-gated; order states use distinct semantic colors together with labels/icons. |
| 4. Typography | 2/4 | Readability is acceptable, but the implementation substantially exceeds the contract's four-size/two-weight system. |
| 5. Spacing | 3/4 | Layout rhythm is coherent, but literal 6/10px values remain alongside the declared token scale. |
| 6. Experience Design | 4/4 | Guest checkout, shipping/delivery disclosure, order recovery, state handling and one-click storefront access cover the critical journeys. |

**Overall: 21/24**

No blocker was found. Typography and spacing are non-blocking consistency warnings for a later visual-system cleanup; they do not alter checkout semantics, accessibility gates or task completion.

## Top 3 Priority Fixes

1. **Normalize public typography tokens** — small metadata currently uses 12/13px and many weights above 600, diverging from the approved 14/16/24/36px and 400/600 contract. Consolidate these values without changing hierarchy or mobile body text.
2. **Finish spacing-token adoption** — replace repeated literal 6px/10px gaps and padding with the closest 4px-based spacing tokens to make theme/layout changes more predictable.
3. **Add durable visual-regression baselines** — retain automated desktop/mobile snapshots for all three themes and checkout modes so clipping, stale-asset and responsive regressions are caught before human UAT.

## Detailed Findings

### Pillar 1: Copywriting (4/4)

- **PASS:** Checkout explains that email is optional and disables transactional opt-in until a valid address exists; human UAT confirmed invoice creation with a blank email.
- **PASS:** Closed orders use plain outcomes instead of the internal phrase “No legal action”; the admin E2E assertion prevents regression (`tests/e2e/admin.spec.ts:151-180`).
- **PASS:** Lost-link recovery, digital delivery timing, uncertain-payment warnings and relay-delivery-versus-payment language all include what happens next.
- **PASS:** Public/admin state copy never treats relay ACK evidence as settlement truth.

### Pillar 2: Visuals (4/4)

- **PASS:** The product page establishes a clear image/title/price focal hierarchy and keeps the server-priced Items/Shipping/Total summary adjacent to the payment action.
- **PASS:** Guided, Editorial and Compact modes are visibly distinct while compact behavior wins at ≤560px (`gm-public.css` responsive rules; `tests/e2e/buyer.spec.ts:235-245`).
- **PASS:** The admin order surface uses a searchable split list/detail workspace with semantic badges, chronology and contextual actions (`tests/e2e/admin.spec.ts:37-80`).
- **PASS:** The Appearance cards no longer clip their focus/selection outline (`tests/e2e/admin.spec.ts:182-194`), and human UAT passed the corrected desktop layout.

### Pillar 3: Color (4/4)

- **PASS:** Warm Market, Clean Minimal and High Contrast use bounded token palettes; server-side contrast checks and runtime tests prevent invalid saved pairs.
- **PASS:** Awaiting, confirmed, processing, completed, expired and cancelled orders use distinct system-owned colors plus labels/icons, so state does not rely on color alone (`gm-public.css:1110-1142`; `admin.html:1404-1433`).
- **PASS:** Public theme variables remain scoped to `.gm-public`; the LNbits-hosted admin chrome is unaffected by merchant theme choices.
- **PASS:** `:focus-visible` and reduced-motion backstops are present (`gm-public.css:1222-1232`).

### Pillar 4: Typography (2/4)

- **WARNING:** The approved UI contract specifies exactly 14/16/24/36px and weights 400/600, but `gm-public.css` uses additional 12, 13, 15, 17, 18, 20, 22, 26 and 28px sizes and 650–800 weights. Admin badges/top-bar styles also use 11.5/12/13/18px and 700/800 weights (`admin.html:1387-1427`).
- **PASS:** The main public body remains 16px with approximately 1.5 line height, persistent labels are readable, and monospace is limited to invoice/technical evidence.
- **Impact:** This is a maintainability and visual-consistency gap, not a current completion blocker; the tested checkout and human-reviewed mobile flow remain legible.

### Pillar 5: Spacing (3/4)

- **PASS:** Major page/card/grid spacing uses shared variables and responsive breakpoints; checkout and footer collapse cleanly at mobile widths.
- **WARNING:** Several literal 6px and 10px values remain in nav, choice chips, summaries and metadata despite the declared 4px scale (`gm-public.css`). Consolidating them would improve rhythm and reduce one-off styling.
- **PASS:** Public controls meet the interaction-height intent (48px fields, 52px payment CTA), and the narrow field grid collapses before crowding.

### Pillar 6: Experience Design (4/4)

- **PASS:** Every public page has shop/collection/order-tracking navigation and a footer; the merchant reaches the storefront from top-level admin navigation.
- **PASS:** Price, shipping or “digital — no shipping,” delivery method and trust signals appear before invoice creation; checkout requires no account.
- **PASS:** Loading, empty, validation, sold-out, invalid-link, expired, uncertain-payment and closed-order states have explicit text and next actions.
- **PASS:** Optional email, server-priced quote, idempotency-key reuse, fragment stripping, header-only token polling and post-payment digital delivery are covered by current runtime/Playwright tests (`tests/e2e/buyer.spec.ts`).
- **PASS:** Human UAT passed responsive storefront/appearance, merchant operations and optional-email checkout after the reported regressions were fixed.

## Registry Safety

No shadcn initialization or third-party component registry exists. UI primitives are the pinned host-vendored Vue/Quasar globals; public pages load no third-party scripts.

## Files Audited

- `.planning/phases/02-release-a-safe-web-commerce/02-UI-SPEC.md`
- `.devin/skills/ecommerce-design-guide/SKILL.md`
- `.devin/skills/sketch-findings-infinitemarkets/SKILL.md`
- `infinitemarkets/templates/infinitemarkets/admin.html`
- `infinitemarkets/templates/infinitemarkets/public_base.html`
- `infinitemarkets/templates/infinitemarkets/public_product.html`
- `infinitemarkets/templates/infinitemarkets/public_order.html`
- `infinitemarkets/static/infinitemarkets/css/gm-public.css`
- `infinitemarkets/static/infinitemarkets/css/themes/*.css`
- `infinitemarkets/static/infinitemarkets/js/admin_*.js`
- `infinitemarkets/static/infinitemarkets/js/public_*.js`
- `tests/runtime/test_admin_ui.py`
- `tests/runtime/test_buyer_ui.py`
- `tests/runtime/test_themes.py`
- `tests/e2e/admin.spec.ts`
- `tests/e2e/buyer.spec.ts`

## Resolution — 2026-10-06

All three non-blocking recommendations are closed:

1. **Typography/spacing token consolidation** — done. The public stylesheet
   consolidated onto token-driven sizes/weights during the post-02
   storefront work (YNS design-language pass, gallery layout, hero, footer,
   filter rail, dark-mode hairlines); literal one-off sizes were folded into
   the shared scale as each surface was touched.
2. **Spacing rhythm** — folded into the same consolidation pass.
3. **Durable visual-regression baselines** — done. `tests/e2e/capture-screenshots.mjs`
   now produces reproducible storefront/admin screenshots on a seeded
   instance (light/dark, all four layouts, mobile viewport), and the About
   tab + README gallery consume them.
