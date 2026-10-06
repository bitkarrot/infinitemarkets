/* Regenerate the About-tab / README screenshots.
 *
 *   uv run python tools/e2e_server.py        # terminal 1 (fresh server)
 *   cd tests/e2e && node capture-screenshots.mjs   # terminal 2
 *
 * Dresses the seeded e2e shop through the real admin API (brand, hero,
 * footer, categories, products, a few settled orders), then captures the
 * admin panel and the public storefront into
 * infinitemarkets/static/infinitemarkets/img/screenshots/. The Messages
 * shot mocks API responses with a clearly fictional demo conversation
 * because the e2e relay has no buyer traffic. */
import {chromium} from 'playwright'
import fs from 'node:fs'
import path from 'node:path'
import {fileURLToPath} from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const seed = JSON.parse(fs.readFileSync(path.join(here, '.seed.json'), 'utf8'))
const OUT = path.resolve(
  here, '../../infinitemarkets/static/infinitemarkets/img/screenshots'
)
fs.mkdirSync(OUT, {recursive: true})

const BASE = seed.base_url
const API = '/infinitemarkets/api/v1'
const IMG = `${BASE}/infinitemarkets/static/infinitemarkets/img`
const shot = name => path.join(OUT, `${name}.jpg`)
const JPEG = {type: 'jpeg', quality: 80}

const browser = await chromium.launch()
const ctx = await browser.newContext({
  ignoreHTTPSErrors: true, viewport: {width: 1700, height: 1000}
})
await ctx.addCookies([
  {name: 'cookie_access_token', value: seed.access_token, url: BASE}
])
const page = await ctx.newPage()
await page.goto(`${BASE}/infinitemarkets/`)
await page.waitForSelector('#gm-admin-root')

const csrf = (await ctx.cookies()).find(c => c.name === 'gm_csrf')?.value || ''
const hdr = {Origin: BASE, 'X-CSRF-Token': csrf}
const api = async (method, url, data, extra = {}) => {
  const res = await ctx.request.fetch(`${BASE}${API}${url}`, {
    method, data, headers: {...hdr, ...extra}
  })
  if (!res.ok()) throw new Error(`${method} ${url} -> ${res.status()} ${await res.text()}`)
  return res.status() === 204 ? null : res.json()
}

/* ---------- dress the shop ------------------------------------------- */
await api('PATCH', `/merchants/${seed.merchant_id}`, {
  display_name: 'Infinite Markets',
  theme: {
    preset: 'warm-market', layout: 'editorial',
    brand: {
      name: 'Infinite Markets', initials: 'IM',
      logo_url: '/infinitemarkets/static/infinitemarkets/img/infinite-markets-blue.png'
    },
    hero: {
      slogan: 'Curated goods for everyday living',
      subtitle: 'Small-batch prints, guides and studio staples — made with ' +
                'care and paid for in a flash over Lightning.',
      primary: {label: 'Shop products', url: '#products'},
      secondary: {label: 'Track an order', url: `/infinitemarkets/order?shop=${seed.pubkey}`}
    },
    footer: {
      tagline: 'An independent studio shop. Pay with any Lightning wallet — ' +
               'no account needed.',
      note: '© 2026 Infinite Markets demo shop'
    }
  }
})

const cats = {}
const main = (await api('GET', '/categories')).find(c => c.name === 'main')
if (main) await api('PATCH', `/categories/${main.id}`, {name: 'Studio Staples'})
for (const name of ['Prints', 'Digital Editions', 'Home & Studio']) {
  cats[name] = (await api('POST', '/categories', {name})).id
}
const products = await api('GET', '/products')
const byTag = t => products.find(p => p.d_tag === t)
await api('PATCH', `/products/${byTag('e2e-digital-tour').id}`, {
  title: 'Field Guide to Quiet Cities (PDF)',
  summary: 'A guided digital tour of twelve quiet cities.',
  description_md: 'A **guided digital tour** of twelve quiet cities — maps, ' +
                  'walking routes and where to eat, in one download.',
  images: [{url: `${IMG}/gallery-demo-guide-spread.svg`}]
})
const poster = products.find(p => p.format === 'physical' && p.d_tag !== 'e2e-digital-tour')
if (poster) {
  await api('PATCH', `/products/${poster.id}`, {
    title: 'Studio Poster No. 3',
    summary: 'Risograph-style print, A2.',
    description_md: 'A2 risograph-style poster printed on 170gsm recycled ' +
                    'stock. Ships rolled in a tube.',
    images: [{url: `${IMG}/gallery-demo-atlas-detail.svg`}]
  })
}
const add = (body) => api('POST', '/products', {
  product_type: 'simple', currency: 'SAT', currency_decimals: 0,
  visibility: 'on-sale', ...body
})
const atlas = await add({
  category_id: cats['Prints'], title: 'Atlas of Small Places — Hardcover',
  summary: 'A hardcover atlas of forty overlooked towns.',
  description_md: 'Forty overlooked towns, hand-drawn maps and short ' +
                  'essays. Cloth-bound hardcover, 212 pages.',
  amount_minor: 21000, format: 'physical', stock_on_hand: 8,
  images: [{url: `${IMG}/gallery-demo-atlas-cover.svg`}, {url: `${IMG}/gallery-demo-atlas-detail.svg`}]
})
await add({
  category_id: cats['Digital Editions'], title: 'Field Guide, Vol. I',
  summary: 'The first volume of our field guide series (PDF).',
  description_md: 'Volume one of the field guide series — instant PDF ' +
                  'delivery after payment.',
  amount_minor: 4200, format: 'digital', stock_on_hand: 500,
  images: [{url: `${IMG}/gallery-demo-guide-cover.svg`}, {url: `${IMG}/gallery-demo-guide-spread.svg`}]
})
await add({
  category_id: cats['Home & Studio'], title: 'Linen Studio Tote',
  summary: 'Heavyweight linen tote — currently sold out.',
  amount_minor: 12500, format: 'physical', stock_on_hand: 0,
  images: [{url: `${IMG}/gallery-demo-atlas-cover.svg`}]
})
await add({
  category_id: cats['Prints'], title: 'Autumn Edition Print',
  summary: 'Limited run — pre-order now.',
  amount_minor: 18000, format: 'physical', visibility: 'pre-order',
  images: [{url: `${IMG}/gallery-demo-atlas-detail.svg`}]
})

/* retire the seed order (placeholder item title): settle, complete, archive */
await ctx.request.post(`${BASE}/_e2e/settle`, {
  headers: {'X-Order-Token': seed.seeded_order_token}
})
for (const o of await api('GET', `/merchants/${seed.merchant_id}/orders`)) {
  for (const to_state of ['processing', 'completed']) {
    await api('POST', `/merchants/${seed.merchant_id}/orders/${o.id}/status`, {to_state})
  }
  await api('POST', `/merchants/${seed.merchant_id}/orders/bulk`, {order_ids: [o.id], action: 'archive'})
}

/* a few orders in different states for the Orders screenshot */
const buy = async d_tag => {
  const res = await ctx.request.post(`${BASE}${API}/public/checkout`, {
    headers: {
      Origin: BASE,
      'Idempotency-Key': crypto.randomUUID() + crypto.randomUUID()
    },
    data: {merchant_pubkey: seed.pubkey, items: [{d_tag, quantity: 1}]}
  })
  return res.json()
}
const settle = async body => ctx.request.post(`${BASE}/_e2e/settle`, {
  headers: {'X-Order-Token': body.public_token}
})
const guide = (await api('GET', '/products')).find(p => p.title === 'Field Guide, Vol. I')
for (const d_tag of [guide.d_tag, 'e2e-digital-tour']) {
  await settle(await buy(d_tag))
}
await buy(guide.d_tag) // left awaiting payment
const orders = await api('GET', `/merchants/${seed.merchant_id}/orders`)
const confirmed = orders.find(o => o.state === 'confirmed')
if (confirmed) {
  await api('POST', `/merchants/${seed.merchant_id}/orders/${confirmed.id}/status`, {to_state: 'processing'})
}

/* ---------- admin ------------------------------------------------------ */
const root = page.locator('#gm-admin-root')
const shotRoot = async name => {
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.waitForTimeout(700)
  const box = await root.boundingBox()
  await page.screenshot({
    path: shot(name), ...JPEG,
    clip: {x: box.x, y: box.y, width: box.width, height: Math.min(box.height, 940)}
  })
}
await page.reload()
await page.waitForSelector('.gm-order-row')
await page.locator('.gm-order-row').first().click()
await page.waitForTimeout(900)
await shotRoot('admin-orders')

await page.locator('[data-gm-nav="catalog"]').click()
await page.waitForSelector('text=Linen Studio Tote')
await shotRoot('admin-categories')

await page.locator('[data-gm-nav="publications"]').click()
await page.waitForTimeout(1500)
await shotRoot('admin-publications')

/* Messages — fictional demo conversation (no buyer traffic on e2e relay) */
const orderId = confirmed ? confirmed.id : orders[0].id
const npub1 = 'npub1' + 'q8zv4k2m7x9d3c5w6r0t1y2u3i4o5p6a7s8d9f0g1h2j3k4l5z6x7c8v'.slice(0, 58)
const npub2 = 'npub1' + 'w3e4r5t6y7u8i9o0p1a2s3d4f5g6h7j8k9l0z1x2c3v4b5n6m7q8w9e0'.slice(0, 58)
const now = Math.floor(Date.now() / 1000)
await page.route(/\/messages\//, route => {
  const url = route.request().url()
  const method = route.request().method()
  const json = body => route.fulfill({contentType: 'application/json', body: JSON.stringify(body)})
  if (/\/messages\/health/.test(url)) {
    return json({
      inbox_state: 'active', outbox_pending: 0,
      relays: [
        {relay_url: 'wss://relay.damus.io', direction: 'both', connected: true, auth_state: 'none'},
        {relay_url: 'wss://nos.lol', direction: 'inbox', connected: true, auth_state: 'none'}
      ]
    })
  }
  if (/\/messages\/unread-count/.test(url)) return json({total: 1, customer: 1, unknown: 0})
  if (/conversations\?folder=/.test(url)) {
    return json({conversations: [
      {conversation_id: `order:${orderId}`, counterparty_npub: npub1, order_ref: orderId,
       preview: 'Thanks! Could you let me know when the guide has shipped?', unread: 1},
      {conversation_id: 'order:demo-2', counterparty_npub: npub2, order_ref: 'a41f09c2e7b3d856',
       preview: 'Received it — it looks wonderful, thank you.', unread: 0}
    ]})
  }
  if (method === 'POST') return json({})
  if (/\/messages\/conversations\//.test(url)) {
    return json({order_id: orderId, messages: [
      {id: 'm1', direction: 'in', read: true, semantic_kind: 'message', created_at: now - 7200,
       content: 'Hi! I just paid for the Field Guide — is it available to download straight away?'},
      {id: 'm2', direction: 'out', read: true, semantic_kind: 'status_update', created_at: now - 6900,
       content: 'Payment confirmed — your download link is on your order page. Enjoy!'},
      {id: 'm3', direction: 'in', read: false, semantic_kind: 'message', created_at: now - 600,
       content: 'Thanks! Could you let me know when the guide has shipped?'}
    ]})
  }
  return route.continue()
})
await page.locator('[data-gm-nav="messages"]').click()
await page.waitForSelector('[data-gm="conversation"]')
await page.locator('[data-gm="conversation"]').first().click()
await page.waitForSelector('[data-gm="message"]')
await shotRoot('admin-messages')
await page.unroute(/\/messages\//)

await page.locator('[data-gm-nav="settings"]').click()
await page.getByRole('tab', {name: 'Appearance'}).click()
await page.waitForTimeout(700)
await shotRoot('admin-appearance')
await page.getByRole('tab', {name: 'Embed'}).click()
await page.waitForSelector('.gm-snippet')
await shotRoot('admin-embed')

/* ---------- storefront ------------------------------------------------- */
const pub = await browser.newContext({
  ignoreHTTPSErrors: true, viewport: {width: 1440, height: 1150}
})
const pp = await pub.newPage()
const home = `${BASE}/infinitemarkets/public/merchants/${seed.pubkey}`
const view = async (name, url = home) => {
  await pp.goto(url)
  await pp.waitForLoadState('networkidle')
  await pp.waitForTimeout(500)
  await pp.screenshot({path: shot(name), ...JPEG})
}
await view('store-home')
await view('store-product', `${BASE}/infinitemarkets/p/${seed.pubkey}/${atlas.d_tag}`)

await api('PATCH', `/merchants/${seed.merchant_id}`, {
  theme: {
    preset: 'warm-market', layout: 'gallery',
    brand: {name: 'Infinite Markets', initials: 'IM',
            logo_url: '/infinitemarkets/static/infinitemarkets/img/infinite-markets-blue.png'},
    hero: {slogan: 'Curated goods for everyday living',
           subtitle: 'Small-batch prints, guides and studio staples — made with care and paid for in a flash over Lightning.',
           primary: {label: 'Shop products', url: '#products'}},
    footer: {tagline: 'An independent studio shop. Pay with any Lightning wallet — no account needed.',
             note: '© 2026 Infinite Markets demo shop'}
  }
})
await view('store-gallery')
await api('PATCH', `/merchants/${seed.merchant_id}`, {theme: {preset: 'warm-market', layout: 'editorial',
  brand: {name: 'Infinite Markets', initials: 'IM',
          logo_url: '/infinitemarkets/static/infinitemarkets/img/infinite-markets-blue.png'},
  hero: {slogan: 'Curated goods for everyday living',
         subtitle: 'Small-batch prints, guides and studio staples — made with care and paid for in a flash over Lightning.',
            primary: {label: 'Shop products', url: '#products'}},
  footer: {tagline: 'An independent studio shop. Pay with any Lightning wallet — no account needed.',
           note: '© 2026 Infinite Markets demo shop'}}})

await pp.addInitScript(() => localStorage.setItem('gm-scheme', 'dark'))
await view('store-dark')

const mob = await browser.newContext({
  ignoreHTTPSErrors: true, viewport: {width: 390, height: 844}, deviceScaleFactor: 2
})
const mp = await mob.newPage()
await mp.goto(home)
await mp.waitForLoadState('networkidle')
await mp.waitForTimeout(500)
await mp.screenshot({path: shot('store-mobile'), ...JPEG})

const emb = await pub.newPage()
await emb.setViewportSize({width: 1200, height: 860})
await emb.route(`${BASE}/webpages/studio`, route => route.fulfill({
  contentType: 'text/html',
  body: `<!DOCTYPE html><html><head><meta charset="utf-8"></head><body style="margin:0;background:#f4efe8;font-family:system-ui,sans-serif;color:#2b241f">
  <div style="max-width:1000px;margin:0 auto;padding:48px 24px">
    <p style="margin:0;text-transform:uppercase;letter-spacing:.12em;font-size:12px;font-weight:700;color:#a34f2a">My studio website</p>
    <h1 style="margin:6px 0 8px;font-size:40px">Shop the studio</h1>
    <p style="max-width:56ch;line-height:1.6;margin:0 0 28px">This page is plain static HTML — the product grid below is the
    Infinite Markets component, rendered right in the page with two lines of code. No iframe.</p>
    <div data-gm-shop="${seed.pubkey}" data-gm-limit="6" data-gm-title="Latest products" data-gm-mode="modal"></div>
  </div>
  <script src="/infinitemarkets/static/infinitemarkets/js/gm-embed.js" defer></script></body></html>`
}))
await emb.goto(`${BASE}/webpages/studio`)
await emb.waitForSelector('.gmx-card')
await emb.waitForTimeout(700)
await emb.screenshot({path: shot('store-embed'), ...JPEG})

await browser.close()
console.log('screenshots written to', OUT)
for (const f of fs.readdirSync(OUT).sort()) {
  console.log(' ', f, (fs.statSync(path.join(OUT, f)).size / 1024).toFixed(0) + ' KB')
}
