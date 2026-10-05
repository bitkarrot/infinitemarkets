import {expect, test} from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'

/* Buyer-facing journey (A2 checkout card + A3 order status):
 * product page → checkout → invoice → fragment-token status page →
 * FakeWallet settlement → confirmed. Serial: later tests reuse the
 * status URL minted by the checkout test. */

const seed = JSON.parse(
  fs.readFileSync(path.resolve(__dirname, process.env.GM_E2E_SEED_PATH || '.seed.json'), 'utf8')
)

test.describe.configure({mode: 'serial'})

let statusUrl = ''

async function reachDelivery(page: import('@playwright/test').Page) {
  if (await page.locator('#gm-checkout-card').getAttribute('data-mode') === 'guided') {
    await page.getByRole('button', {name: 'Continue to delivery'}).click()
  }
}

async function reachPayment(page: import('@playwright/test').Page) {
  if (await page.locator('#gm-checkout-card').getAttribute('data-mode') === 'guided') {
    await page.getByRole('button', {name: 'Continue to payment'}).click()
  }
}

test('product page embeds the adaptive checkout card', async ({page}) => {
  const resp = await page.goto(seed.digital_url)
  expect(resp?.status()).toBe(200)
  // §5.4 protective headers on the public document
  const csp = resp?.headers()['content-security-policy'] ?? ''
  expect(csp).toContain("default-src 'self'")
  expect(resp?.headers()['cache-control']).toContain('no-store')

  await expect(page.locator('#gm-checkout-card')).toBeVisible()
  // Persistent Items/Shipping/Total summary — SAT prices seeded
  await expect(page.locator('[data-sum="items"]')).toContainText('2,500')
  await expect(page.locator('[data-sum="total"]')).toContainText('2,500')
  await expect(page.locator('.privacy')).toContainText(
    'never sent in a request path or query'
  )
  // Editorial preset: all section bodies visible, stepper hidden
  await expect(page.locator('#gm-checkout-card')).toHaveAttribute(
    'data-mode',
    'editorial'
  )
  await expect(page.locator('#gm-email')).toBeVisible()
  await expect(
    page.getByText('Send transactional updates. No marketing.')
  ).toBeVisible()
})

test('digital checkout creates a Lightning invoice', async ({page}) => {
  await page.goto(seed.digital_url)
  await page.locator('#gm-qty').fill('1')
  await reachDelivery(page)
  const email = page.locator('#gm-email')
  const updates = page.locator('input[name=email_opt_in]')
  await expect(email).toHaveValue('')
  await expect(updates).toBeDisabled()
  await expect(updates).not.toBeChecked()
  await email.fill('buyer@example.com')
  await expect(updates).toBeEnabled()
  await updates.check()
  await email.fill('')
  await expect(updates).toBeDisabled()
  await expect(updates).not.toBeChecked()
  await reachPayment(page)
  await page.locator('button[type=submit]').click()

  const panel = page.locator('#gm-invoice-panel')
  await expect(panel).toHaveAttribute(
    'data-invoice-state',
    'awaiting_payment',
    {timeout: 20_000}
  )
  // Same-origin QR + full BOLT11 + countdown + verbatim security copy
  const bolt11 = await panel.locator('textarea.bolt11').inputValue()
  expect(bolt11.toLowerCase()).toMatch(/^ln/)
  await expect(panel.locator('.invoice-qr svg')).toBeVisible()
  await expect(panel.locator('.invoice-countdown')).toContainText(
    'Expires in'
  )
  await expect(panel).toContainText(
    'Invoice is correlated to this order only'
  )
  // The token never lands in the page URL or emitted links
  expect(page.url()).not.toContain('#')
  statusUrl = await page.evaluate(() =>
    (window as unknown as {GM: {statusUrl(): string}}).GM.statusUrl()
  )
  // Token only in the fragment; the optional query is the public shop id.
  expect(statusUrl).toMatch(/\/infinitemarkets\/order(\?shop=[0-9a-f]{64})?#[A-Za-z0-9_-]{43}$/)
  expect(new URL(statusUrl).search).not.toContain(new URL(statusUrl).hash.slice(1))
})

test('order status page: fragment stripped, polls, settles', async ({
  page,
  request
}) => {
  const token = new URL(statusUrl).hash.slice(1)
  expect(token.length).toBeGreaterThan(10)

  await page.goto(statusUrl)
  await expect(page.locator('#gm-order-state')).toContainText(
    'Waiting for payment'
  )
  // Fragment stripped immediately — token is memory-only
  expect(new URL(page.url()).hash).toBe('')
  await expect(page.locator('#gm-order-invoice')).toBeVisible()

  // Settle via the harness route (FakeWallet pay + listener path)
  const settled = await request.post(`${seed.base_url}/_e2e/settle`, {
    headers: {'X-Order-Token': token}
  })
  expect((await settled.json()).ok).toBe(true)

  // 5s poll picks up the confirmed state
  await expect(page.locator('#gm-order-state')).toContainText(
    'Payment confirmed',
    {timeout: 20_000}
  )
  // Invoice panel collapses once paid (bolt11 leaves the DOM)
  await expect(page.locator('#gm-order-invoice')).toBeHidden()
  // Digital delivery appears only now that payment is confirmed
  await expect(page.locator('[data-gm="delivery-item"]')).toContainText('E2E-TOUR-2026')
  await expect(page.locator('[data-gm="delivery-item"] a').first()).toHaveAttribute(
    'href', 'https://files.example/e2e-digital-tour.zip'
  )
})

test('storefront navigation and track-order recovery', async ({page}) => {
  await page.goto(seed.digital_url)
  const nav = page.locator('.store-nav')
  await expect(nav.getByRole('link', {name: 'Shop'})).toBeVisible()
  await expect(nav.getByRole('link', {name: 'Featured'})).toBeVisible()
  await expect(page.locator('[data-gm="trust-list"]')).toContainText('available on your order page right after payment')
  await nav.getByRole('link', {name: 'Track order'}).click()

  await expect(page.locator('.order-title')).toHaveText('Track your order')
  await expect(page.locator('#gm-order-card')).toBeHidden()
  await expect(page.locator('.store-nav').getByRole('link', {name: 'Shop'})).toBeVisible()
  await page.locator('#gm-track-link').fill('not a link')
  await page.getByRole('button', {name: 'Open my order'}).click()
  await expect(page.locator('[data-error-for="order_link"]')).toBeVisible()

  await page.locator('#gm-track-link').fill(statusUrl)
  await page.getByRole('button', {name: 'Open my order'}).click()
  await expect(page.locator('#gm-order-state')).toContainText('Payment confirmed', {timeout: 20_000})
  expect(new URL(page.url()).hash).toBe('')
  await expect(page.locator('#gm-order-state')).toHaveAttribute('data-state', /confirmed|processing|completed/)
})

test('invalid order token shows identical dead-link copy', async ({
  page
}) => {
  await page.goto(
    `${seed.base_url}/infinitemarkets/order#not-a-real-token-e2e-000`
  )
  await expect(page.locator('#gm-order-state')).toContainText(
    'This order link is no longer valid.'
  )
})

test('physical product requires destination + shipping', async ({
  page
}) => {
  await page.goto(seed.physical_url)
  await expect(page.locator('#gm-line1')).toBeVisible()
  await expect(page.locator('#gm-shipping')).toBeVisible()

  // Submit without a destination → inline contract copy, no request
  await page.locator('button[type=submit]').click()
  await expect(
    page.locator('[data-error-for="country"]')
  ).toContainText('Choose a shipping option for this destination.')

  await page.locator('#gm-country').selectOption('US')
  await page.locator('#gm-line1').fill('1 Main St')
  await page.locator('#gm-city').fill('Springfield')
  await page.locator('#gm-region').fill('US-IL')
  await page.locator('#gm-postal').fill('62701')
  await page.locator('#gm-shipping').selectOption({index: 1})

  // Persistent summary reflects item + shipping (7,500 + 500 SAT)
  await expect(page.locator('[data-sum="shipping"]')).toContainText('500')
  await expect(page.locator('[data-sum="total"]')).toContainText('8,000')

  await page.locator('button[type=submit]').click()
  const panel = page.locator('#gm-invoice-panel')
  await expect(panel).toHaveAttribute(
    'data-invoice-state',
    'awaiting_payment',
    {timeout: 20_000}
  )
})

test('quantity stepper drives the server-priced summary', async ({page}) => {
  await page.goto(seed.digital_url)
  await expect(page.locator('.product-price')).toContainText('2,500 sats')
  const minus = page.locator('.qty-btn[data-qty-step="-1"]')
  await expect(minus).toBeDisabled()
  await page.locator('.qty-btn[data-qty-step="1"]').click()
  await expect(page.locator('#gm-qty')).toHaveValue('2')
  await expect(page.locator('[data-sum-qty]')).toHaveText('× 2')
  await expect(page.locator('[data-sum="total"]')).toContainText('5,000')
  await minus.click()
  await expect(page.locator('[data-sum="total"]')).toContainText('2,500')
})

test('physical total needs no region and accepts short region codes', async ({page}) => {
  const quotes: string[] = []
  page.on('request', req => {
    if (req.url().endsWith('/api/v1/public/quote')) quotes.push(req.postData() || '')
  })
  await page.goto(seed.physical_url)
  await expect(page.locator('[data-sum-hint]')).toBeVisible()
  await page.locator('#gm-country').selectOption('US')
  await page.locator('#gm-shipping').selectOption({index: 1})
  await expect(page.locator('[data-sum="total"]')).toContainText('8,000')
  await expect(page.locator('[data-sum-hint]')).toBeHidden()
  expect(JSON.parse(quotes[quotes.length - 1]).address).toEqual({country: 'US'})

  await page.locator('#gm-region').fill('il')
  await expect(page.locator('[data-sum="total"]')).toContainText('8,000')
  await expect.poll(() => JSON.parse(quotes[quotes.length - 1]).address.region).toBe('US-IL')

  await page.locator('#gm-region').fill('Illinois')
  await expect(page.locator('[data-error-for="region"]')).toContainText('state or region code')
})

test('compact layout is forced at <=560px', async ({page}) => {
  await page.setViewportSize({width: 375, height: 800})
  await page.goto(seed.digital_url)
  await expect(page.locator('#gm-checkout-card')).toHaveAttribute(
    'data-mode',
    'compact'
  )
  // Compact: collapsed sections behind disclosure heads
  const heads = page.locator('.co-section-head')
  await expect(heads.first()).toBeVisible()
})

test('checkout retries preserve uncertain requests but allow corrected rejections', async ({page}) => {
  const requests: {key: string; body: string | null}[] = []
  await page.route('**/api/v1/public/checkout', async route => {
    requests.push({key: route.request().headers()['idempotency-key'], body: route.request().postData()})
    await route.fulfill({status: 422, contentType: 'application/problem+json', body: JSON.stringify({
      type: 'urn:infinitemarkets:fx-unavailable', title: 'Price conversion unavailable'
    })})
  })
  await page.goto(seed.digital_url)
  await page.locator('button[type=submit]').click()
  await expect(page.locator('.form-error')).toBeVisible()
  await page.locator('#gm-qty').fill('2')
  await page.locator('button[type=submit]').click()
  await expect.poll(() => requests.length).toBe(2)
  expect.soft(requests[1].key).not.toBe(requests[0].key)

  await page.unroute('**/api/v1/public/checkout')
  requests.length = 0
  await page.route('**/api/v1/public/checkout', async route => {
    requests.push({key: route.request().headers()['idempotency-key'], body: route.request().postData()})
    await route.abort('failed')
  })
  await page.reload()
  await page.locator('button[type=submit]').click()
  await expect(page.locator('.form-error')).toBeVisible()
  await expect.soft(page.locator('#gm-qty')).toBeDisabled({timeout: 750})
  await page.locator('#gm-qty').evaluate((el: HTMLInputElement) => { el.value = '9' })
  await page.locator('button[type=submit]').click()
  await expect.poll(() => requests.length).toBe(2)
  expect(requests[1]).toEqual(requests[0])
})

/* --- Release B: NIP-07 sign-in, claim, storefront modes ------------- */

async function installNostrStub(
  page: import('@playwright/test').Page,
  label?: string
) {
  /* A NIP-07 extension stand-in: getPublicKey + signEvent backed by the
     harness /_e2e/sign route, so verify() runs against a REAL signed
     kind-22242 event. ``label`` picks a different fixed test key —
     needed when the scenario wants an identity that isn't already the
     shared e2e-buyer account. */
  await page.addInitScript(l => {
    const w = window as unknown as {
      nostr?: {getPublicKey: () => Promise<string>; signEvent: (e: unknown) => Promise<unknown>}
    }
    w.nostr = {
      getPublicKey: async () => '',
      signEvent: async (ev: unknown) => {
        const r = await fetch('/_e2e/sign', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({...(ev as object), label: l})
        })
        const data = await r.json()
        return data.event
      }
    }
  }, label || '')
}

async function setMode(
  request: import('@playwright/test').APIRequestContext,
  mode: string
) {
  const resp = await request.post(`${seed.base_url}/_e2e/mode`, {
    data: {mode}
  })
  expect(resp.status()).toBe(200)
}

test('sign-in affordance renders once the inbox is active', async ({
  page
}) => {
  await page.goto(seed.digital_url)
  await expect(page.locator('[data-gm="signin"]')).toBeVisible()
  await expect(page.locator('[data-gm="signin"]')).toContainText(
    'Sign in'
  )
})

test('sign-in without a signer extension shows friendly guidance', async ({
  page
}) => {
  await page.goto(seed.digital_url)
  await page.locator('[data-gm="signin"]').click()
  await expect(page.locator('#gm-nostr-modal')).toBeVisible()
  await expect(page.locator('#gm-nostr-modal')).toContainText('NIP-07')
  // The chip only opens the method picker — the buyer chooses Nostr.
  await page.locator('#gm-nostr-modal-signin').click()
  await expect(page.locator('#gm-nostr-modal')).toContainText(
    'No Nostr signer found'
  )
  // Escape dismisses the dialog.
  await page.keyboard.press('Escape')
  await expect(page.locator('#gm-nostr-modal')).toBeHidden()
})

test('NIP-07 sign-in, claim, order history, sign out', async ({
  page,
  request
}) => {
  // A fresh anonymous order to claim.
  const checkout = await request.post(
    `${seed.base_url}/infinitemarkets/api/v1/public/checkout`,
    {
      headers: {
        'Idempotency-Key': crypto.randomUUID() + crypto.randomUUID(),
        Origin: seed.base_url
      },
      data: {
        merchant_pubkey: seed.pubkey,
        items: [{d_tag: seed.digital.d_tag, quantity: 1}]
      }
    }
  )
  expect(checkout.status()).toBe(201)
  const token = (await checkout.json()).public_token
  const orderLink =
    `${seed.base_url}/infinitemarkets/order?shop=${seed.pubkey}#${token}`

  await installNostrStub(page)
  await page.goto(seed.digital_url)
  // The chip opens the method picker; the Nostr button starts the
  // signer challenge round-trip.
  await page.locator('[data-gm="signin"]').click()
  await expect(page.locator('#gm-nostr-modal')).toBeVisible()
  await page.locator('#gm-nostr-modal-signin').click()
  // Signed-in state collapses to a header account chip — npub shown.
  await expect(page.locator('#gm-nostr-signin')).toContainText('npub1', {
    timeout: 20_000
  })
  await expect(page.locator('#gm-nostr-modal')).toBeHidden()
  // The chip opens the account dropdown with the account links.
  await page.locator('#gm-nostr-signin').click()
  await expect(page.locator('#gm-nostr-menu')).toBeVisible()
  await expect(page.locator('#gm-nostr-menu')).toContainText('My orders')

  // Orders live on their own page — reached via the account menu.
  await page.locator('#gm-nostr-menu').getByText('My orders').click()
  await page.waitForURL('**/infinitemarkets/orders**')
  await expect(page.locator('#gm-orders-body')).toBeVisible()

  // Claim the private link — the order joins the signed-in history.
  await page.locator('[data-gm="claim-input"]').fill(orderLink)
  await page.locator('#gm-claim-btn').click()
  await expect(page.locator('#gm-claim-msg')).toContainText(
    'Order linked'
  )
  const orderRow = page.locator('[data-gm="nostr-order"]')
  await expect(orderRow.first()).toBeVisible()
  await expect(orderRow.first()).toContainText('e2e digital tour')
  await expect(orderRow.first()).toContainText('2,500')
  await expect(orderRow.first().locator('.status-pill')).toContainText(
    'Waiting for payment'
  )
  await expect(
    orderRow.first().locator('a.nostr-order-link')
  ).toHaveAttribute('href', /\/infinitemarkets\/order/)

  // The profile editor is the account menu's second destination.
  await page.locator('#gm-nostr-signin').click()
  await page.locator('#gm-nostr-menu').getByText('Profile').click()
  await page.waitForURL('**/infinitemarkets/profile**')
  await expect(page.locator('#gm-profile-form')).toBeVisible()
  await expect(page.locator('#gm-profile-name')).toBeVisible()

  // Sign out from the menu — the chip returns to the signed-out CTA.
  await page.locator('#gm-nostr-signin').click()
  await page.locator('#gm-nostr-menu').getByText('Sign out').click()
  await expect(page.locator('#gm-nostr-signin')).toContainText(
    'Sign in'
  )
})

test('showcase mode swaps the checkout card for Nostr guidance', async ({
  page,
  request
}) => {
  await setMode(request, 'showcase')
  try {
    await page.goto(seed.digital_url)
    await expect(
      page.locator('[data-gm="showcase-guidance"]')
    ).toBeVisible()
    await expect(
      page.locator('[data-gm="showcase-guidance"]')
    ).toContainText('Order via Nostr')
    await expect(
      page.locator('[data-gm="showcase-guidance"]')
    ).toContainText('npub1')
    await expect(page.locator('#gm-checkout')).toHaveCount(0)
    // API gate: quote + checkout 422 under showcase.
    const quote = await request.post(
      `${seed.base_url}/infinitemarkets/api/v1/public/quote`,
      {
        data: {
          merchant_pubkey: seed.pubkey,
          items: [{d_tag: seed.digital.d_tag, quantity: 1}]
        }
      }
    )
    expect(quote.status()).toBe(422)
  } finally {
    await setMode(request, 'full')
  }
})

test('nostr_only shows the notice but /order still works', async ({
  page,
  request
}) => {
  await setMode(request, 'nostr_only')
  try {
    for (const url of [
      seed.digital_url,
      `${seed.base_url}/infinitemarkets/public/merchants/${seed.pubkey}`
    ]) {
      await page.goto(url)
      await expect(page.locator('[data-gm="nostr-only"]')).toBeVisible()
      await expect(
        page.locator('[data-gm="nostr-only"]')
      ).toContainText('Nostr')
      await expect(
        page.locator('[data-gm="nostr-only"]')
      ).toContainText('npub1')
    }
    // Track-order + the private status link still work.
    await page.goto(
      `${seed.base_url}/infinitemarkets/order?shop=${seed.pubkey}`
    )
    await expect(page.locator('.order-title')).toHaveText(
      'Track your order'
    )
    const status = await request.get(
      `${seed.base_url}/infinitemarkets/api/v1/public/order-status`,
      {headers: {'X-Order-Token': seed.seeded_order_token}}
    )
    expect(status.status()).toBe(200)
    // New checkout is refused.
    const checkout = await request.post(
      `${seed.base_url}/infinitemarkets/api/v1/public/checkout`,
      {
        headers: {
          'Idempotency-Key': crypto.randomUUID() + crypto.randomUUID(),
          Origin: seed.base_url
        },
        data: {
          merchant_pubkey: seed.pubkey,
          items: [{d_tag: seed.digital.d_tag, quantity: 1}]
        }
      }
    )
    expect(checkout.status()).toBe(422)
  } finally {
    await setMode(request, 'full')
  }
})

/* --- Phase 03.1: email magic-link sign-in + identity linking --------
   Each scenario uses a FRESH browser context so session cookies never
   leak between tests in the serial chain. The /_e2e/mailbox harness
   decrypts the durable account-queue row — no real SMTP. */

async function mailboxLink(
  request: import('@playwright/test').APIRequestContext,
  email: string
) {
  /* Poll the harness until the newest 'account' row for this
     recipient decrypts — worker timing is not deterministic. */
  let link = ''
  await expect
    .poll(
      async () => {
        const res = await request.get(
          `${seed.base_url}/_e2e/mailbox?to=${encodeURIComponent(email)}`
        )
        const body = await res.json()
        link = body.link || ''
        return link
      },
      {timeout: 20_000}
    )
    .not.toBe('')
  return link
}

test('email magic-link sign-in binds past orders', async ({
  browser,
  request
}) => {
  // An anonymous checkout under the sign-in email — auto-bound to the
  // account when the magic link verifies (D-09).
  const checkout = await request.post(
    `${seed.base_url}/infinitemarkets/api/v1/public/checkout`,
    {
      headers: {
        'Idempotency-Key': crypto.randomUUID() + crypto.randomUUID(),
        Origin: seed.base_url
      },
      data: {
        merchant_pubkey: seed.pubkey,
        items: [{d_tag: seed.digital.d_tag, quantity: 1}],
        email: 'e2e-buyer@example.com'
      }
    }
  )
  expect(checkout.status()).toBe(201)

  const ctx = await browser.newContext({ignoreHTTPSErrors: true})
  const page = await ctx.newPage()
  try {
    await page.goto(seed.digital_url)
    await page.locator('[data-gm="signin"]').click()
    await expect(page.locator('#gm-nostr-modal')).toBeVisible()
    await page
      .locator('[data-gm="email-input"]')
      .fill('e2e-buyer@example.com')
    await page.locator('#gm-email-btn').click()
    // Uniform no-oracle copy — identical for every outcome.
    await expect(page.locator('#gm-nostr-modal')).toContainText(
      'Check your email'
    )

    const link = await mailboxLink(request, 'e2e-buyer@example.com')
    await page.goto(link)
    // The landing verifies the fragment token, mints the cookie and
    // redirects to the orders page.
    await page.waitForURL('**/infinitemarkets/orders**', {
      timeout: 20_000
    })
    // The chip falls back to the verified email (never a npub
    // placeholder) for an email-only account.
    await expect(page.locator('#gm-nostr-signin')).toContainText(
      'e2e-buyer@example.com',
      {timeout: 20_000}
    )
    // The pre-signin order is in the union history, acknowledged once.
    const orderRow = page.locator('[data-gm="nostr-order"]')
    await expect(orderRow.first()).toContainText('e2e digital tour')
    await expect(page.locator('#gm-orders-body')).toContainText(
      'We found'
    )
    await expect(page.locator('#gm-orders-body')).toContainText(
      'linked to your account'
    )
    // One-shot: a second render no longer shows the note.
    await page.reload()
    await expect(page.locator('#gm-orders-body')).not.toContainText(
      'We found'
    )
  } finally {
    await ctx.close()
  }
})

test('modal offers both methods with honest availability', async ({
  browser
}) => {
  const ctx = await browser.newContext({ignoreHTTPSErrors: true})
  const page = await ctx.newPage()
  try {
    await page.goto(seed.digital_url)
    await page.locator('[data-gm="signin"]').click()
    const modal = page.locator('#gm-nostr-modal')
    await expect(modal).toBeVisible()
    // Both method affordances render — Nostr button + email form.
    await expect(modal.locator('#gm-nostr-modal-signin')).toBeVisible()
    await expect(modal.locator('[data-gm="email-input"]')).toBeVisible()
    await expect(modal.locator('#gm-email-btn')).toBeVisible()
    // The e2e host has (dummy) SMTP configured: the email method is
    // enabled even with no window.nostr present.
    await expect(modal.locator('[data-gm="email-input"]')).toBeEnabled()
  } finally {
    await ctx.close()
  }
})

test('unconfigured email shows the honest hint, not a dead form', async ({
  browser
}) => {
  const ctx = await browser.newContext({ignoreHTTPSErrors: true})
  const page = await ctx.newPage()
  try {
    // Force the capability flag off — the email method must say WHY.
    await page.route('**/api/v1/public/nostr/challenge**', async route => {
      const res = await route.fetch()
      const body = await res.json()
      body.email_signin = false
      await route.fulfill({response: res, json: body})
    })
    await page.goto(seed.digital_url)
    await page.locator('[data-gm="signin"]').click()
    const modal = page.locator('#gm-nostr-modal')
    await expect(modal.locator('[data-gm="email-input"]')).toBeDisabled()
    await expect(modal.locator('#gm-email-btn')).toBeDisabled()
    await expect(modal).toContainText(
      "Email sign-in isn't configured on this host"
    )
  } finally {
    await ctx.close()
  }
})

test('nostr account links an email from the profile page', async ({
  browser,
  request
}) => {
  const ctx = await browser.newContext({ignoreHTTPSErrors: true})
  const page = await ctx.newPage()
  try {
    await installNostrStub(page)
    await page.goto(seed.digital_url)
    await page.locator('[data-gm="signin"]').click()
    await page.locator('#gm-nostr-modal-signin').click()
    await expect(page.locator('#gm-nostr-signin')).toContainText(
      'npub1',
      {timeout: 20_000}
    )

    await page.goto(
      `${seed.base_url}/infinitemarkets/profile?shop=${seed.pubkey}`
    )
    // Nostr-only account: npub row + the symmetric link-an-email card.
    await expect(page.locator('[data-gm="account-card"]')).toContainText(
      'npub1'
    )
    await expect(
      page.locator('[data-gm="link-email-card"]')
    ).toBeVisible()
    await page
      .locator('[data-gm="link-email-input"]')
      .fill('e2e-link@example.com')
    await page.locator('#gm-link-email-btn').click()
    await expect(page.locator('#gm-link-email-msg')).toContainText(
      'Check your email'
    )

    const link = await mailboxLink(request, 'e2e-link@example.com')
    await page.goto(link)
    // Link tokens prove without minting a session — the landing shows
    // the linked state, then Continue returns to the profile.
    await expect(
      page.locator('[data-gm="email-auth-linked"]')
    ).toBeVisible({timeout: 20_000})
    await page
      .locator('[data-gm="email-auth-linked"]')
      .getByRole('link', {name: 'Continue'})
      .click()
    await page.waitForURL('**/infinitemarkets/profile**')
    // Both identities now show, and the kind-0 editor is still live.
    const card = page.locator('[data-gm="account-card"]')
    await expect(card).toContainText('e2e-link@example.com')
    await expect(card).toContainText('npub1')
    await expect(page.locator('#gm-profile-form')).toBeVisible()
  } finally {
    await ctx.close()
  }
})

test('email account links a Nostr key from the profile page', async ({
  browser,
  request
}) => {
  const ctx = await browser.newContext({ignoreHTTPSErrors: true})
  const page = await ctx.newPage()
  try {
    // Sign in by magic link (fresh email-only account).
    await page.goto(seed.digital_url)
    await page.locator('[data-gm="signin"]').click()
    await page
      .locator('[data-gm="email-input"]')
      .fill('e2e-linker@example.com')
    await page.locator('#gm-email-btn').click()
    await expect(page.locator('#gm-nostr-modal')).toContainText(
      'Check your email'
    )
    const link = await mailboxLink(request, 'e2e-linker@example.com')
    await page.goto(link)
    await page.waitForURL('**/infinitemarkets/orders**', {
      timeout: 20_000
    })

    // Email-only profile: verified email row, link-nostr card, and a
    // LOCKED kind-0 state — never a dead editor. A FRESH key: the
    // shared e2e-buyer key already holds an email identity, so linking
    // it here would be an honest merge conflict.
    await installNostrStub(page, 'e2e-linker-key')
    await page.goto(
      `${seed.base_url}/infinitemarkets/profile?shop=${seed.pubkey}`
    )
    await expect(page.locator('[data-gm="account-card"]')).toContainText(
      'e2e-linker@example.com'
    )
    await expect(
      page.locator('[data-gm="link-nostr-card"]')
    ).toBeVisible()
    await expect(
      page.locator('[data-gm="profile-locked"]')
    ).toBeVisible()
    await expect(page.locator('#gm-profile-form')).toHaveCount(0)

    // Real challenge -> signEvent -> verify round-trip (the stub signs
    // through /_e2e/sign; the server verifies a REAL signature).
    await page.locator('#gm-link-nostr-btn').click()
    const card = page.locator('[data-gm="account-card"]')
    await expect(card).toContainText('npub1', {timeout: 20_000})
    await expect(page.locator('#gm-profile-body')).toContainText(
      'Nostr key linked'
    )
    // The editor unlocks once a key is linked.
    await expect(page.locator('#gm-profile-form')).toBeVisible()
    await expect(
      page.locator('[data-gm="profile-locked"]')
    ).toHaveCount(0)
  } finally {
    await ctx.close()
  }
})
