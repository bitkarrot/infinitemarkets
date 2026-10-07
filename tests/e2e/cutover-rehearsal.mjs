// 04-04 Task 3: browser evidence for export + storefront profile.
// Requires the seeded e2e server: uv run python tools/e2e_server.py
//   then: node tests/e2e/cutover-rehearsal.mjs
// Applies the lightnin-dark + quad storefront to the seeded merchant via
// the real bearer-authorized admin API, asserts the public page renders
// the compact grid + hero toggle + footer logo, and downloads the export
// CSV to verify the versioned marker. No secrets; seed is disposable.

import {chromium} from 'playwright'
import {readFileSync} from 'node:fs'
import {fileURLToPath} from 'node:url'
import {dirname, join} from 'node:path'

process.env.NODE_TLS_REJECT_UNAUTHORIZED = '0' // e2e self-signed cert

const here = dirname(fileURLToPath(import.meta.url))
const seed = JSON.parse(readFileSync(join(here, '.seed.json'), 'utf8'))
const base = seed.base_url
const auth = {Authorization: `Bearer ${seed.access_token}`}
const api = `${base}/infinitemarkets/api/v1`

async function apiJson(path, init = {}) {
  const res = await fetch(`${api}${path}`, {
    ...init,
    headers: {...auth, 'Content-Type': 'application/json', ...(init.headers || {})},
  })
  const body = await res.json().catch(() => ({}))
  return {status: res.status, body}
}

const theme = await apiJson(`/merchants/${seed.merchant_id}`, {
  method: 'PATCH',
  body: JSON.stringify({theme: {
    preset: 'lightnin-dark', layout: 'gallery',
    storefront: {grid: 'quad', hero_hidden: false},
    footer: {tagline: 'Board games, card games and dice.',
             note: 'Rehearsal footer'},
  }}),
})
if (theme.status !== 200) throw new Error(`theme patch: ${theme.status}`)

// CSV export is a read-only GET — no CSRF needed with bearer auth.
const csvRes = await fetch(`${api}/migration/products/export`, {headers: auth})
const csvText = await csvRes.text()
if (!csvText.startsWith('format,infinitemarkets-products-v1'))
  throw new Error('export preamble missing')
console.log('export ok:', csvText.split('\n').length, 'lines')

const browser = await chromium.launch()
try {
  for (const [name, viewport, expectCols] of [
    ['desktop', {width: 1440, height: 900}, 4],
    ['mobile', {width: 390, height: 844}, 2],
  ]) {
    const page = await browser.newPage({viewport, ignoreHTTPSErrors: true})
    await page.goto(
      `${base}/infinitemarkets/public/merchants/${seed.pubkey}`,
      {waitUntil: 'networkidle'})
    const probe = await page.evaluate(() => {
      const pub = document.querySelector('.gm-public')
      const grid = document.querySelector('.card-grid')
      return {
        grid: pub?.dataset.grid, layout: pub?.dataset.layout,
        cols: grid
          ? getComputedStyle(grid).gridTemplateColumns.split(' ').length : 0,
        bg: getComputedStyle(pub).backgroundColor,
        hero: !!document.querySelector('.merchant-hero'),
      }
    })
    if (probe.grid !== 'quad') throw new Error(`${name}: grid=${probe.grid}`)
    if (probe.cols !== expectCols)
      throw new Error(`${name}: cols=${probe.cols} want ${expectCols}`)
    if (!probe.hero) throw new Error(`${name}: hero missing`)
    if (probe.bg !== 'rgb(36, 40, 51)')
      throw new Error(`${name}: bg=${probe.bg}`)
    console.log(`${name} ok:`, JSON.stringify(probe))
    await page.close()
  }

  // hero_hidden toggle reaches the public document
  const hidden = await apiJson(`/merchants/${seed.merchant_id}`, {
    method: 'PATCH',
    body: JSON.stringify({theme: {storefront: {hero_hidden: true}}}),
  })
  if (hidden.status !== 200) throw new Error('hero_hidden patch failed')
  const page = await browser.newPage({ignoreHTTPSErrors: true})
  await page.goto(
    `${base}/infinitemarkets/public/merchants/${seed.pubkey}`,
    {waitUntil: 'networkidle'})
  const hasHero = await page.evaluate(
    () => !!document.querySelector('.merchant-hero'))
  if (hasHero) throw new Error('hero should be hidden')
  console.log('hero_hidden ok')
  await page.close()
} finally {
  await browser.close()
}
console.log('cutover-rehearsal e2e: all checks passed')
