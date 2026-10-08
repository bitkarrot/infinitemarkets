---
name: shopify-migration
description: Export Shopify products and media for CSV catalog import into Infinite Markets as hidden drafts; preserve indexed URLs via an external redirect map. Use when preparing a Shopify CSV import or reviewing a product catalog before publication.
---

# Shopify → infinitemarkets migration export

Produces a complete migration package: catalog CSV, per-product SEO capture,
image backup, shipping profile, and a redirect map for preserving
Google-indexed `/products/<handle>` URLs.

Reference package: `/home/exedev/shopify-archive/` (shop.lightnin.games).

## Step 1 — get the data out of Shopify

- **Products**: admin → Products → Export → all products, CSV. This is the file
  infinitemarkets' `/migration/shopify/preview` accepts (Handle/Title/Price/…).
- **Sitemap**: `GET https://<store>/sitemap.xml` → fetch each sub-sitemap.
  `sitemap_products_*.xml` lists exactly the product URLs Google was told to
  index. Sub-sitemaps may 404 for empty resource types (pages/blogs) — fine.
- **Shipping**: NOT exportable. Admin → Settings → Shipping and delivery →
  print each profile to PDF, then extract text
  (`gs -sDEVICE=txtwrite -o out.txt profile.pdf`) and hand-structure it into
  `shipping-profile.json` — zone→countries, rate→price/weight bounds/delivery
  window. Flag "orders ≥ $X" conditional rates (infinitemarkets can't express
  them) and truncated country lists ("+12 more") for manual verification.
- **Store policies**: `/policies/{privacy-policy,refund-policy,terms-of-service,
  contact-information}` — save HTML or recreate as content.

## Step 2 — crawl rendered pages (rate limits apply)

Storefronts 429 aggressive scraping. Plain `urllib`/`curl` batches get blocked;
headless Chromium at ~1 req / 3 s succeeds. Working scripts:
`/home/exedev/shopify-archive/extract_seo.mjs` (Playwright via the infinitemarkets
e2e deps) and `capture_store.mjs` (screenshots).

Per product URL capture: HTTP status + final URL (detect handle renames),
`<title>`, `<meta name="description">`, `rel=canonical`, `og:*`,
`application/ld+json` (`ProductGroup` + `hasVariant` = variants/SKUs/prices/
availability), plus every internal link for collection/page discovery.

Shopify auto-generates meta description when the admin SEO fields are blank —
the rendered page is the only record of what Google indexes.

## Step 3 — build the artifacts

- `shopify-url-map.csv` — every original URL → status, title tag, meta
  description, canonical, product info, suggested new URL, redirect action.
- `redirect-map.csv` — `old_url,new_url,301` rows for edge deployment.
- `products_full.json` — per-product variants incl. `?variant=` deep links
  (301 via the same handle rule; canonicals already strip variants).
- `manifest.json` + `images/` — every `cdn.shopify.com` image (they die with
  the store) with sha256 and owning handles.
- `shipping-profile.json` — structured zones/rates mapped to
  `shipping_options` fields.
- `MIGRATION-NOTES.md` — inventory, gaps, Search Console checklist.

## Step 4 — infinitemarkets side

- Product URLs are `/infinitemarkets/p/{pubkey}/{d_tag}`; imports store the
  Shopify handle in `products.import_legacy_id`. SEO/redirect preservation
  work is spec'd in `shopify-archive/SHOPIFY-IMPORT-PROPOSAL.md` (slug d_tags,
  `/infinitemarkets/legacy/{handle}` 301 route, meta/JSON-LD emission,
  sitemap, redirect export, shipping-profile import).
- Edge rule for moving a storefront domain (outside the extension):
  `^/products/([a-z0-9-]+)$ → 301 /infinitemarkets/legacy/$1`, deployed wherever
  the old domain's DNS lands. Keep 180+ days.
- Import flow: Migration tab → select Shopify CSV and currency → Preview products
  → Import as drafts; or use `POST /infinitemarkets/api/v1/migration/shopify/preview`
  then `/execute` with the preview hash. Products land as hidden drafts in an
  "Imported — review" category. Review images, prices, size options and stock
  in Catalog, then publish approved products normally. There is no attestation,
  stock-count gate, or old-order reconciliation; the operator must ensure
  overlapping old-store inventory is managed before publishing.

## Pitfalls

- d_tag constraint: `[a-z0-9-]{8,64}` — handles over 64 chars or under 8 need
  fallback slugs (collision-safe: check `_check_d_tag` + merchant uniqueness).
- Shopify serves the same product under `/collections/<c>/products/<handle>` —
  wildcard redirects must match the `/products/` segment anywhere in path.
- Re-host images: rewrite og:image and JSON-LD image URLs before switching the external storefront domain.
- Keep the old domain's redirects alive after Shopify closes — rules must live
  wherever DNS points next.
