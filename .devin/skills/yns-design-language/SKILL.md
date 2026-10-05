---
name: yns-design-language
description: Clean gallery-led storefront design language extracted from the yournextstore template (/home/exedev/yournextstore) - tokens, type, spacing, product card, gallery, variant chips, cart drawer, filters, empty/loading states - translated to infinitemarkets' Jinja + vanilla JS + CSS-custom-property stack, with a phased plan to apply it to the public shop templates. Use when restyling or reviewing infinitemarkets storefront, product, collection, cart/checkout chrome, or order pages.
---

<context>
Source: `/home/exedev/yournextstore` (Next.js 16 + Tailwind v4 + shadcn/ui + Radix). Read for: `app/globals.css`, `app/layout.tsx`, `app/navbar.tsx`, `app/footer.tsx`, `components/product-card.tsx`, `components/sections/*`, `components/ui/*`, `app/product/[slug]/*`, `app/cart/cart-sidebar.tsx`, `components/route-error.tsx`.

What makes it feel clean is not a palette - it is **restraint**: a neutral monochrome UI so product photography is the only color, one hairline border weight, medium (500) headings with tight tracking instead of bold, generous vertical rhythm, borderless image-first cards, and a handful of state patterns (skeleton, empty, error, drawer) applied identically everywhere.

**Precedence.** Normative spec, security and payment invariants > `sketch-findings-infinitemarkets` (locked visual contract, merchant theme presets) > `ecommerce-design-guide` > this skill. This skill changes *structure, proportion, weight and state patterns*. It must NOT hard-code a palette: every color stays a `--color-*` token so `services/themes.py` presets (warm-market / clean-minimal / high-contrast) and merchant accent overrides keep working.

**Stack translation.** YNS is React/Tailwind; we are server-rendered Jinja + `GM.h()` vanilla JS + `gm-public.css` scoped under `.gm-public`. Port the *values and structure*, never the tooling: no Tailwind, no Radix, no new dependencies, no external fonts/CDNs (the public pages are privacy-first and CSP-bound). YNS rules that do NOT apply: Next cache/shell rules, `<a>` for /checkout, `track()`, Geist via next/font.
</context>

<extracted_design>
## 1. Layout and rhythm

| Element | YNS value | Notes for us |
|---|---|---|
| Container | `max-w-7xl` (1280px), padding 16 / 24 / 32 at base / sm / lg | ours is 1120px, padding 16 - widen to 1280 on >=1024 |
| Header | sticky, `h-16`, `bg-background/80 backdrop-blur-md`, 1px bottom border, `z-50` | ours is opaque surface; translucent+blur is a pure CSS swap (`color-mix(in srgb, var(--color-bg) 80%, transparent)` + `backdrop-filter`) with an opaque fallback |
| Header composition | brand left; nav **centered** (absolute) on lg; icon cluster right (search, theme, account, cart); below lg a hamburger opens a left drawer holding search + nav | ours: brand+nav left, chip right. Centered nav + icon cluster is the main structural difference |
| Section spacing | `py-16 sm:py-24` between page sections; hero `py-16 sm:py-20 lg:py-28`; footer `py-12 sm:py-16` | ours uses 32-64px; increase |
| Section head | h2 left (2xl-3xl, medium) + muted one-line description; "View all ->" ghost link right-aligned at sm+; `mb-12` | ours: h2 + count chip |
| Grids | product grid `1 / 2 / 3` cols (`sm`/`lg`), `gap-8` (32px); PDP `lg:grid-cols-2 gap-16`; listing `16rem` filter rail + fluid grid, gap 40px | ours: `auto-fill minmax(220px)` gap 16 |

## 2. Typography

- One family (Geist) + mono only where code appears. Ours: keep `--font-body` / `--font-display` tokens; do not add a webfont (system stack only).
- **Headings are weight 500 with `tracking-tight`** (-0.025em), not 650-800. This single choice is most of the "clean" feel.
- Scale: hero h1 `36 -> 48 -> 60px`; PDP h1 `36 -> 48px` with `text-wrap: balance`; page h1 `30 -> 36px`; section h2 `24 -> 30px`; body 16px; nav/links/meta 14px; fine print 12px.
- Secondary text is always the muted token (`--muted-foreground`, L=0.52, tuned to clear AA on the tinted surfaces). Primary text only for names/prices/labels.
- Prices: `font-semibold` (600); PDP price `30px` semibold tracking-tight; compare-at price `line-through` muted at 18px.
- Numbers that change (cart totals, discount) use `font-variant-numeric: tabular-nums`.

## 3. Color, borders, elevation

- Neutral monochrome tokens: background, foreground, card, primary (near-black / inverted in dark), secondary/muted/accent (L=0.97 tint), border (L=0.922, 1px), ring (focus). Color enters only through photography and semantic states.
- **Tint, don't paint:** tinted surfaces are `secondary` at 30-50% opacity (hero `secondary/30`, trust strip `secondary/50`); image tiles sit on `secondary`. Map to `--color-surface-alt` with `color-mix` for the fractional tints.
- Primary CTA is the **inverse of the page** (`foreground` fill, `background` text, pill radius) - not an accent color. Ours uses `--color-primary`; that stays (merchant accent), but keep the pill/size proportions below.
- Semantic tints: sale/discount pill = `destructive` at 10% fill with full-strength destructive text; success text green-700; stars `yellow-400`.
- **Almost no shadow.** Cards are borderless and shadowless; shadow appears only on floating UI (gallery arrows `shadow-lg`, drawers/popovers). Hierarchy comes from whitespace and the tinted tile, not elevation. Ours currently uses border + `shadow-sm` + `shadow-md` on hover on every card.
- Dark mode: border becomes white at 10% alpha, inputs 15%; cards one step lighter than the page. (Optional for us - `high-contrast` preset exists; dark is a non-goal unless requested.)

## 4. Radius scale

Base `--radius: 0.625rem (10px)`; derived sm=6, md=8, lg=10, xl=14. Usage: **image tiles `rounded-2xl` (16px)**, gallery thumbs `rounded-lg`, inputs/UI buttons `rounded-md`, qty stepper `rounded-lg`, **hero CTAs and badges `rounded-full`**, trust strip `rounded-xl`. Ours: `--radius-sm/md/lg/full` already exist - reuse them; add no new radius token.

## 5. Components

**Product card** (`product-card.tsx`) - the signature element.
- No border, no background, no shadow. Structure: `[square tile][name][price]`.
- Tile: `aspect-ratio: 1`, `background: secondary`, `border-radius: 16px`, `overflow: hidden`, `margin-bottom: 16px`, image `object-fit: cover`.
- **Second image crossfades in on hover** (`opacity` transition 500ms) - the card previews an alternate view without layout change. First image `loading=eager/priority` only for index 0.
- Name `16px / 500`; price `16px / 600`, price range "$a - $b" for variants. Whole card is one link; `.group` hover drives the crossfade.
- Quick-add: icon button overlaid on the tile, only for single-variant, in-stock products.
- Sold-out/pre-order: badge on the tile (top-left), not a text row in the body.

**Gallery** (`media-gallery.tsx`)
- Left column `position: sticky; top: 96px` on lg (stays with the buy box while the right column scrolls).
- Main: square, `rounded-2xl`, `bg secondary`; hover reveals round prev/next buttons (`40px`, `background/90`, `backdrop-blur`, `shadow-lg`) and a "zoom" pill bottom-right plus an `n / total` pill bottom-left. Keyboard: arrow keys, container focusable with `outline: none`.
- Thumbs: **horizontal row below**, `80px` squares, `rounded-lg`, gap 12; selected = `2px ring foreground + 2px offset in background`, unselected `opacity: .6 -> 1` on hover. Ours: 86px vertical rail left with shadow - move below on all widths.
- No-image fallback: square secondary tile with muted "No images available".

**Variant selectors** (`variant-selector.tsx`)
- Each option group is a `<fieldset>` + `<legend>` (a11y), label left, selected value muted on the right.
- Color options = **48px circles** filled with the color, selected = ring + offset; light colors get an inner 1px border so white does not vanish.
- Other options = **chips** `rounded-lg`, `border-2`, `px-24 py-12`; selected = inverted fill (foreground bg / background text), idle = border + hover border-muted. 200ms transition.
- Never a bare `<select>` for <= ~8 options.

**Quantity stepper:** one segmented control, `rounded-lg` 1px border, 40px square minus/plus buttons joined to a 56px centered value; label "Quantity" above (14/500).

**Buy box** (right column, `space-y-8`): h1, review summary line (stars + score + underlined count), summary paragraph (muted, relaxed leading), price row (price, compare-at, discount pill, "lowest price in last 30 days" fine print), variant groups, quantity, **full-width pill CTA `h-12`**, then the trust strip, then long description in `prose prose-sm` (muted body, foreground headings) under a top border `mt-16 pt-12`.

**Trust strip:** 3-column grid, `rounded-xl`, `secondary/50`, `p-16`; each cell centered: 20px muted icon, 12px/500 title, 10px muted description. Ours: `trust-list` bullet rows - convert to the 3-up strip on >=560px; keep honest copy (shipping cost, delivery method, Lightning payment) - never fake guarantees.

**Cart drawer** (`cart-sidebar.tsx`): right sheet `max-w-lg`; header "Your Cart (n items)" with bottom border; empty state = 80px muted circle with bag icon, 18px/500 message, muted hint, outline "Continue Shopping"; items `divide-y`; footer pinned with top border: optional discount field, subtotal/discount/total rows (discount in green with a true minus sign), 12px tax/shipping note that matches tax behavior, **`h-12` full-width primary CTA**, centered text-link "Continue Shopping". CTA shows an inline spinner + "Updating..." and is `pointer-events: none` while a write is in flight (prevents navigating before the cart is committed).

**Listing page:** h1 + muted subtitle; left filter rail (`16rem`) on lg with accordion groups (Categories / Collections / options / Brands / Price slider) and a "Clear" text-link; below lg the rail becomes a "Filters" outline button (with active-count pill) opening a left sheet; sort select top-right; pagination centered `mt-12`; "No products match these filters." centered `py-24` muted.

**Hero:** `secondary/30` band, left-aligned `max-w-2xl` block, h1 (36-60px/500/tight), 18-20px muted lead, two CTAs `h-12 px-32` pill (solid inverse + outline), subtle right-side gradient wash `from-secondary/50 to-transparent` on lg only.

**Footer:** top border; brand + one-line pitch left; link columns (Collections / Support / Legal) with 14/600 foreground headings and 14px muted links (`space-y-12`); bottom bar: `(c) year name` left, accepted-payment marks right.

**Account affordance:** icon-only in the header cluster (24px min target), account area separate from the cart; ours is the sign-in chip -> account menu already; keep it but align its size/position to the icon cluster.

## 6. States and motion

- **Skeletons mirror the real layout** (same aspect-ratio tile + two text bars, same grid) - a layout-matching skeleton, never a spinner. `animate-pulse` on `secondary`.
- **Image shimmer** while loading: neutral gradient `0.90 -> 0.95 -> 1.0` at 200% width, 1.2s ease-in-out infinite. Disable under `prefers-reduced-motion`.
- **Error / 404:** centered column, `min-height: 60-90dvh`, 64px icon in `muted/50` with `stroke-width: 1.5`, h1 24/500, muted 14px description (`max-w-md`), two actions (solid inverse `rounded-md` + outline).
- **Transitions:** `transition-colors` on links/buttons (150ms), 200ms on selection rings/chips, 500ms on image crossfade. No bounce, no parallax.
- **Focus:** 3px ring at 50% alpha (`ring-ring/50`) plus border-color change; never `outline: none` without a replacement.

## 7. Accessibility baseline carried over (already compatible)

Touch targets >= 24px (icon buttons 32-40px); text/surface token pairs >= 4.5:1 (YNS enforces this with a unit test over every token pair - we should add the equivalent to `tests/` for each preset); fieldset/legend for option groups; `aria-label` on icon-only controls; decorative icons `aria-hidden`; `sr-only` titles on drawers.
</extracted_design>

<application_plan>
## Plan: apply to the infinitemarkets public templates

Target files: `infinitemarkets/static/infinitemarkets/css/gm-public.css` (scoped under `.gm-public`), `templates/infinitemarkets/public_{base,merchant,collection,product,order,orders,signin,profile,invalid,unavailable}.html`, `static/.../js/public_storefront.js`, `public_checkout.js`. Admin surfaces are out of scope.

**Open decision (ask before Phase C):** ship as the new default structure for every shop, or as a fourth `layout` option (`LAYOUTS = ("editorial","guided","compact")` in `services/themes.py`, rendered via `data-layout` on `.gm-public`)? A new layout value is the safer rollout (existing shops unchanged, per-merchant opt-in, trivial rollback) but needs a `themes.py` + admin settings change and a registry/spec touch. Default recommendation: add `gallery` layout, make it the default for new shops only after one release.

### Phase A - Tokens and proportion (CSS only, zero markup change, low risk)
1. Container 1120 -> 1280 at >=1024; section rhythm to `64 / 96px`; grid gap 16 -> 32px.
2. Headings weight 650-800 -> 500 with `letter-spacing: -0.025em`; h1/h2 scale per section 2; `text-wrap: balance` on `.product-title`.
3. Elevation diet: remove `--shadow-sm` from `.product-card`, drop hover `--shadow-md`; reserve shadows for menus, drawers, gallery arrows.
4. Header: translucent + `backdrop-filter` with opaque fallback; keep a11y focus + skip-link.
5. Verify every preset still clears AA (add the per-preset token-pair contrast test described in section 7).

### Phase B - Product card and listing (template + CSS)
1. `.product-card` -> borderless; `.card-art` square (`aspect-ratio:1`), `--color-surface-alt` tile, 16px radius; body text below the tile (name 500, price 600).
2. Sold-out / pre-order / digital move from body text to a tile badge (top-left pill).
3. Second-image crossfade: only if the product feed exposes >=2 images on the list path - check `services` list query first; do not add extra queries per card. Otherwise skip, never fetch N extra rows.
4. Grid `1 / 2 / 3` columns, `gap: 32px`; layout-matching skeleton for client-rendered lists (`public_storefront.js`).
5. Section head: h2 + muted description + "View all" link; fix empty-state copy.

### Phase C - Product detail (template + CSS + JS)
1. Gallery: square main with `--radius-lg`, horizontal 80px thumb row with ring+offset selection, `n / total` pill, hover arrows, arrow-key support in the existing gallery handler; sticky left column on >=1024.
2. Buy box spacing `space-y: 32px`; price 30/600; sale/compare-at only if the product model actually has one (do not invent discounts).
3. Variant presentation: if variants/options exist on the Gamma product, render chips (and color circles for color attributes) - gate on real data in `services/catalog`; otherwise skip.
4. Trust list -> 3-up strip with honest copy (shipping from X / delivery / Lightning).
5. Pill primary CTA `h-48px` full-width in the buy box.

### Phase D - Cart / checkout chrome and order pages
1. Cart/summary surface adopts drawer anatomy: header with count, `divide-y` lines, pinned footer totals, tax note keyed to the store's tax behavior, full-width pill CTA with in-flight lock (maps to the existing checkout double-submit protection - keep the idempotency behavior untouched).
2. Empty cart / invalid / unavailable / expired-link pages use the centered error pattern (64px muted icon, h1 24/500, muted copy, two actions).
3. Order status + orders list: tabular numerals for totals, `status-pill` already compatible.
4. Sign-in/profile pages: align to the same card + form proportions (input `h-36px`, 3px focus ring).

### Phase E - Footer and header composition
1. Footer: brand + pitch, link columns (collections / support / legal), bottom bar with accepted payment (Lightning mark - draw from existing assets, no third-party logos).
2. Header: centered nav on >=1024 with icon cluster right; hamburger sheet below; keep the account chip.

### Verification (every phase)
- `node --check` on JS; seeded e2e (`tests/e2e/buyer.spec.ts`, 20 specs) green - selectors that rely on `data-gm` hooks must not move.
- Visual pass at 360 / 768 / 1280 on product, collection, order, signin; check each theme preset and a merchant accent override.
- Lighthouse a11y >= 0.98 on a live product page (YNS bar); no CLS from image tiles (fixed aspect ratios).
- `tests/qualification` contract closure unaffected (no route changes expected in A-E).
- Never regress: private-link order privacy, no external requests added, CSP unchanged, `referrerpolicy="no-referrer"` kept on merchant images.

### Non-goals
Dark mode, Tailwind/React, webfonts, chat widget, newsletter popup, reviews (V2), quick-add (no cart object in our no-account flow), cookie banner.
</application_plan>

<usage>
## When to load
Before restyling or reviewing any public storefront template. Read `sketch-findings-infinitemarkets` first for the locked contract, then use section 5 as the component reference and `application_plan` as the sequencing. When a YNS value conflicts with a theme token or the spec, the token/spec wins and the value is a proportion hint only.

To re-extract after the template changes: `cd /home/exedev/yournextstore && git log --oneline -5` then diff `app/globals.css`, `components/product-card.tsx`, `app/product/[slug]/media-gallery.tsx`, `variant-selector.tsx`, `app/cart/cart-sidebar.tsx`.
</usage>
