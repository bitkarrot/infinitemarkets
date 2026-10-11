# Design — Infinite Markets docs viewer

The locked design system for the static docs site in `docs/viewer/`
(`index.html`, `overview.html`, `architecture.html`, `view.html`, `slides.html`).
Every page reads from this file. Don't restyle one page at a time: amend this
file first, then update the pages. `assets/style.css` is the source of truth for
tokens. `assets/site.css` and `assets/slides.css` build on it and don't add new
tokens.

## System
- Genre · playful
- Theme · custom (vibe: "neo-brutalist sticker zine, hard ink shadows")
- Axes · warm cream paper on a dotted grid / heavy grotesque display / multi-accent sticker palette
- Signature · 2–3 px ink borders, **offset hard shadows (no blur)**, pill shapes, mono uppercase kickers, a 26 px dot-grid background

## Pages and macrostructures
| Page | Body class | Macrostructure | Notes |
|---|---|---|---|
| `index.html` | `site` | Workbench | Split hero with a tilted screenshot collage, then alternating `.band` / `.band.alt` sections built from cards and framed screenshots. The 39 s overview plays in an inverted `.band.screen` right above the Tour; the 2-minute product demo opens in a `dialog.player` from the Go deeper card (and from `#demo` links) |
| `overview.html` | `site` | Long Document | Sticky TOC + one `article.md` card rendered from `overview.md`; each `h2` section gets the next accent from the palette |
| `architecture.html` | `index` | Index-First | A grid of `.card` links, one per diagram in `diagrams/registry.js` |
| `view.html` | `viewer` | Map / Diagram | A full-viewport pan/zoom Mermaid canvas with floating HUD, controls, legend and notes drawer |
| `slides.html` | `deck` | Deck (not in the catalogue) | A 1600×900 stage scaled to fit, rendered from `slides/deck.md` |

Add new marketing or content pages as `body.site`. Add new tool pages with the
floating-chrome pattern (`#hud` / `#controls` / `#notes`).

## Tokens (canonical · `assets/style.css`)
```css
:root {                      /* light */
  --bg: #f4f0e6;             /* page / paper-2 */
  --paper: #fffdf7;          /* cards, nav, bands */
  --ink: #111111;            /* text, borders, shadows */
  --text2: #3c3a34;          /* body copy */
  --muted: #5d5a52;          /* captions, meta */
  --dot: #d9d2c0;            /* dot grid, hairlines */
  --shadow-ink: rgba(17,17,17,.92);   /* drop-shadow() on SVG / images */
  --chip: #c8f53c;           /* inline <code> text */

  /* accents (same in both themes) */
  --lime: #c8f53c;  --yellow: #ffd23d;  --orange: #ff6a1f;
  --pink: #ff5aa8;  --mint: #4fdc9a;    --blue: #2e6bff;
  --purple: #b48cff;         /* declared on .site only */

  --display: 'Bricolage Grotesque', 'Inter', system-ui, sans-serif;
  --sans: 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif;
  --mono: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace;

  --shadow: 4px 4px 0 var(--ink);
  --shadow-lg: 7px 7px 0 var(--ink);
  --radius: 16px;
  --ease: cubic-bezier(.2, .8, .2, 1);
}
html[data-theme="dark"] {
  --paper: #26251f; --bg: #1e1d18; --ink: #f0ead8; --muted: #a39d8d;
  --text2: #cfc9b8; --dot: #33312a; --shadow-ink: rgba(240,234,216,.45); --chip: #111111;
}
```
- The default theme is **dark**. It's set before first paint by the inline
  `<script>` in each `<head>` and saved in `localStorage['imv-theme']`. Every
  page must keep that script and the `#themeBtn` toggle.
- Accent fills always carry **`#111` text** in both themes. They never use
  `var(--ink)`, because ink turns cream in dark mode.
- Per-element accents come in through a local custom property: `--k` (kicker),
  `--c` (card), `--accent` (article section / slide).

## Typography
- Display · Bricolage Grotesque 800, tracking −.03 to −.055em, line-height ~1.0
  - hero `h1` clamp(42px, 4.9vw, 70px) · band `h2` clamp(32px, 4.4vw, 50px) · card `h3` 20–22px
- Body · Inter 400/600/700, 15px base (16px on `.site`), lede 18–19px, line-height 1.55–1.7
- Mono · JetBrains Mono 500, 11.5–12.5px, uppercase, tracking .06–.1em. Used for
  kickers, tags, figcaptions, URL bars and counters.
- Fonts are vendored woff2 (OFL) in `assets/`. Don't load fonts from a CDN.

## Shape, depth, spacing
- Borders: 2px on controls and chips, 2.5px on cards, frames, bands and nav, 3px on slides and the lightbox.
- Radii: 999px for pills · 14–18px for cards and frames · 22px for the article · 26px for slides · 5–6px for code and swatches.
- Shadows are always solid offsets in `--ink`: 2–3px on small chips, 4–7px on
  cards and frames, 9–12px on the article and slides. **No blur, no gradients,
  no glow.**
- Layout: `.container` max 1180px with 24px gutters · `.band` 88px vertical (64px ≤680px) · grid gap 24px.
- Breakpoints: 1180 (nav → menu), 980 (splits stack, grids → 2 columns), 680 (1 column, collage flattens), 520 (compact nav).

## Components
- **Kicker** `.kick` — a mono pill on an accent fill above every section `h2`.
- **Pill button** `.pill-btn` (+ `.big`, `.lime`, `.pink`, `.ink`) — the only button style.
- **Card** `.card-x` / `.card`. The tinted variants (`.pain`, `.lnb`) use a 12px accent band on top and `color-mix(--c 16%, --paper)`.
- **Frame** `.frame` — a screenshot in a browser-chrome bar with pink/yellow/mint dots. Images open in the shared lightbox (`MD.lightbox`).
- **Status tag** `.tag-shipped` mint · `.tag-tested` lime · `.tag-spec-aligned` yellow · `.tag-todo` pink · `.tag-roadmap` orange. Use them for status only, never decoration.
- **Strip** `.strip` — an inverted ink band with `.chip`s.
- **Screening band** `.band.screen` — an inverted ink band (like `.strip`) for video. Frames, kickers and pill buttons inside it swap their ink borders and shadows for `--paper` so they stay visible, the same way the lightbox does.
- **Video frame** — a `.frame` holding `<video controls playsinline preload="metadata" poster>` at 16:9. Never autoplay; sound is part of the videos.
- **Player dialog** `dialog.player` — a native `<dialog>` with a 3px ink border, a 12px offset shadow, a mono title bar and a `.pill-btn` close button. `[data-play="demo"]` links open it (their `href` points at the MP4 as a no-JS fallback), and so does a `#demo` URL hash. Closing pauses the video.
- **Media** — videos and posters live in `media/` and are served by the Vercel deployment. Link to the site (`https://infinitemarkets-docs.vercel.app/#demo`), never to GitHub blob or raw URLs. In the markdown sources (`overview.md`), a `Video:` directive embeds one inline: `Video: <src> | <poster> | <caption>` (poster and caption optional), rendered as an article figure with the same border/shadow as images.
- **Callout / blockquote** — an accent fill, bold 18px, hard shadow.

## CTA voice
- Primary · `.pill-btn.big.lime` · 999px · 12×22px padding · label ends in " →"
- Secondary · `.pill-btn.big` on paper · same shape
- Press feedback: hover moves the button half the shadow offset, active moves it the full offset (the shadow collapses). Cards lift on hover (−2px, larger shadow).

## Motion stance
- Transitions: 120–150ms using `--ease`, on `transform` and `box-shadow` only.
- Page-level effects: smooth anchor scrolling, the slide `slideIn` (fade + 10px rise, 280ms), and the 250ms notes drawer. No scroll-triggered reveals.

## Share cards
- Every page carries OpenGraph + `twitter:card` (`summary_large_image`) meta with **absolute** `media/` URLs. Card image is `media/trailer-poster.jpg` (1600×900); `index.html` and `overview.html` also declare `og:video*` pointing at the trailer MP4 so Discord/Slack/Facebook previews can play it inline.

## Content voice
- Plain and factual. Show status honestly with tags ("tested", "todo",
  "roadmap"). Kickers are short labels, and headlines are statements without
  hype.
- Version strings appear in `index.html`, `overview.md` and `slides/deck.md`.
  Update all three together when releasing.

## Known gaps (fix through this file, not per page)
- No `:focus-visible` styles. Add an ink outline with a 3px offset for all `a`, `button` and `.card`.
- No `prefers-reduced-motion` handling. Turn off `scroll-behavior: smooth`, the
  hover translate and `slideIn` (opacity only, ≤150ms).
- Some values are hard-coded instead of tokenised: the pain-card blue `#8eaeff`
  and the dark link `#7fa9ff`. Inline `style="--k: …"` attributes are fine; raw
  colours are not.
- The version shown in the docs (v0.5) is behind `manifest.json` (0.6.1).

## Exports
`assets/style.css` is the source of truth. For Tailwind v4 `@theme`, DTCG
`tokens.json` or shadcn/ui variables, extend this section from the token block
above.
