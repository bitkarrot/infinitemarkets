import {expect, test} from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'

/* Merchant-facing journey: the admin shell on the host Vue/Quasar app.
 * Authenticates with the seeded account's cookie_access_token — the
 * same credential the host sets after a real login. */

const seed = JSON.parse(
  fs.readFileSync(path.resolve(__dirname, process.env.GM_E2E_SEED_PATH || '.seed.json'), 'utf8')
)

test.describe.configure({mode: 'serial'})

test.beforeEach(async ({context}) => {
  await context.addCookies([
    {
      name: 'cookie_access_token',
      value: seed.access_token,
      url: seed.base_url
    }
  ])
})

test('admin shell mounts with all five surfaces', async ({page}) => {
  await page.goto('/infinitemarkets/')
  await expect(page.locator('#gm-admin-root')).toBeVisible()
  for (const nav of [
    'orders',
    'catalog',
    'publications',
    'messages',
    'settings'
  ]) {
    await expect(page.locator(`[data-gm-nav="${nav}"]`)).toBeVisible()
  }
  // Existing merchant → workspace (not the first-run setup card)
  await expect(
    page.locator('[data-gm-surface="orders"]')
  ).toBeVisible({timeout: 20_000})
})

test('messages workspace: folders, empty state, health strip', async ({
  page
}) => {
  await page.goto('/infinitemarkets/')
  await page.locator('[data-gm-nav="messages"]').click()
  await expect(
    page.locator('[data-gm-surface="messages"]')
  ).toBeVisible({timeout: 20_000})
  // D-20 connectivity strip + folder toggle + compose/rejected controls.
  await expect(page.locator('[data-gm="messages-health"]')).toBeVisible()
  await expect(page.locator('[data-gm="folder-toggle"]')).toBeVisible()
  /* List renders either the empty state or real conversations — prior
     runs against the live seed may already have order threads. */
  const convRows = page.locator('[data-gm="conversation"]')
  if ((await convRows.count()) === 0) {
    await expect(page.locator('[data-gm="conv-empty"]')).toBeVisible()
  } else {
    await expect(convRows.first()).toBeVisible()
  }
  await expect(
    page.locator('[data-gm-surface="messages"] button:has-text("Compose")')
  ).toBeVisible()
  await expect(
    page.locator(
      '[data-gm-surface="messages"] button:has-text("Rejected intake")'
    )
  ).toBeVisible()
  // Compose dialog opens with the npub field.
  await page
    .locator('[data-gm-surface="messages"] button:has-text("Compose")')
    .click()
  await expect(page.locator('[data-gm="compose-content"]')).toBeVisible()
  await page.keyboard.press('Escape')

  // D-23 rejected intake: the seeded row lists its reject reason; mute
  // confirms then swaps to the durable muted badge. Suite reruns may
  // find it already muted — either state must render honestly.
  await page
    .locator('[data-gm-surface="messages"] button:has-text("Rejected intake")')
    .click()
  const rejectedRow = page
    .locator('[data-gm="rejected-row"]')
    .filter({hasText: 'type-3 missing order tag'})
    .first()
  await expect(rejectedRow).toBeVisible()
  if ((await rejectedRow.locator('[data-gm="mute-sender"]').count()) > 0) {
    await rejectedRow.locator('[data-gm="mute-sender"]').click()
    await page.locator('[data-gm="mute-confirm"]').click()
  }
  await expect(rejectedRow.locator('[data-gm="muted-badge"]')).toBeVisible()
  await page.keyboard.press('Escape')
})

test('storefront mode cards render with the four modes', async ({
  page
}) => {
  await page.goto('/infinitemarkets/')
  await page.locator('[data-gm-nav="settings"]').click()
  await expect(
    page.locator('[data-gm="storefront-mode"]')
  ).toBeVisible({timeout: 20_000})
  for (const mode of ['full', 'showcase', 'browse_only', 'nostr_only']) {
    await expect(
      page.locator(`[data-gm="storefront-mode"] [data-mode="${mode}"]`)
    ).toBeVisible()
  }
})

test('orders workspace lists the seeded order + detail pane', async ({
  page
}) => {
  // Create a fresh order first — accumulated rows settle/expire over
  // time, so no prior state can be relied on for the legal-action check.
  const checkout = await page.request.post(
    '/infinitemarkets/api/v1/public/checkout',
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

  await page.goto('/infinitemarkets/')
  await expect(
    page.locator('[placeholder="Search order or buyer"]')
  ).toBeVisible({timeout: 20_000})

  const row = page
    .locator('.gm-order-row')
    .filter({hasText: 'Awaiting payment'})
    .first()
  await expect(row).toBeVisible({timeout: 20_000})
  await expect(page.locator('[data-gm="orders-summary"]')).toContainText(
    'active orders'
  )

  await row.click()
  // Linear Split detail pane: state pill + legal actions + timeline
  await expect(
    page.getByText('Technical delivery details')
  ).toBeVisible({timeout: 15_000})
  // awaiting_payment → Cancel is the only legal state action
  await expect(
    page.getByRole('button', {name: 'Cancel', exact: true})
  ).toBeVisible()
})

test('closed orders can be selected, archived, and restored', async ({page, request}) => {
  await page.goto('/infinitemarkets/')
  await expect(page.locator('[placeholder="Search order or buyer"]')).toBeVisible({
    timeout: 20_000
  })
  const cookies = await page.context().cookies()
  const csrf = cookies.find(cookie => cookie.name === 'gm_csrf')?.value || ''
  const headers = {Origin: seed.base_url, 'X-CSRF-Token': csrf}
  const ordersUrl = `/infinitemarkets/api/v1/merchants/${seed.merchant_id}/orders`
  const before = await page.request.get(ordersUrl)
  const beforeIds = new Set((await before.json()).map((order: {id: string}) => order.id))
  const checkout = await page.request.post('/infinitemarkets/api/v1/public/checkout', {
    headers: {
      'Idempotency-Key': crypto.randomUUID() + crypto.randomUUID(),
      Origin: seed.base_url
    },
    data: {
      merchant_pubkey: seed.pubkey,
      items: [{d_tag: seed.digital.d_tag, quantity: 1}]
    }
  })
  expect(checkout.status()).toBe(201)
  const checkoutBody = await checkout.json()
  const settled = await request.post(`${seed.base_url}/_e2e/settle`, {
    headers: {'X-Order-Token': checkoutBody.public_token}
  })
  expect((await settled.json()).ok).toBe(true)
  const after = await page.request.get(ordersUrl)
  const order = (await after.json()).find(
    (candidate: {id: string; state: string}) =>
      !beforeIds.has(candidate.id) && candidate.state === 'confirmed'
  )
  expect(order).toBeTruthy()
  for (const toState of ['processing', 'completed']) {
    const response = await page.request.post(`${ordersUrl}/${order.id}/status`, {
      headers,
      data: {to_state: toState}
    })
    expect(response.status()).toBe(200)
  }

  await page.reload()
  const row = page.locator('.gm-order-row').filter({hasText: order.id.slice(0, 8)})
  await expect(row).toBeVisible({timeout: 15_000})
  await row.getByRole('checkbox', {name: `Select order ${order.id}`}).click()
  await expect(page.locator('[data-gm="order-bulk-bar"]')).toContainText('1 order selected')
  await page.setViewportSize({width: 390, height: 844})
  await page.getByRole('button', {name: 'Archive selected'}).click()
  const archiveTitle = page.getByText('Archive 1 order', {exact: true})
  await expect(archiveTitle).toBeVisible()
  const archiveDialog = page.locator('.q-dialog .q-card').filter({has: archiveTitle})
  const dialogBox = await archiveDialog.boundingBox()
  expect(dialogBox).not.toBeNull()
  expect(dialogBox!.x).toBeGreaterThanOrEqual(0)
  expect(dialogBox!.x + dialogBox!.width).toBeLessThanOrEqual(390)
  await page.getByRole('button', {name: 'Archive orders'}).click()
  await expect(row).toHaveCount(0)

  await page.getByRole('button', {name: 'Archived', exact: true}).click()
  const archivedRow = page.locator('.gm-order-row').filter({hasText: order.id.slice(0, 8)})
  await expect(archivedRow).toBeVisible()
  await archivedRow.getByRole('checkbox', {name: `Select order ${order.id}`}).click()
  await page.getByRole('button', {name: 'Restore selected'}).click()
  await expect(archivedRow).toHaveCount(0)

  await page.getByRole('button', {name: 'Active', exact: true}).click()
  await expect(page.locator('.gm-order-row').filter({hasText: order.id.slice(0, 8)})).toBeVisible()
})

test('catalog surface lists products with editor CTAs', async ({page}) => {
  await page.goto('/infinitemarkets/')
  await page.locator('[data-gm-nav="catalog"]').click()
  await expect(
    page.getByRole('button', {name: 'New product'})
  ).toBeVisible({timeout: 15_000})
  // Scope to the catalog surface — hidden surfaces keep their DOM
  // (v-show) and the orders list contains the same product titles.
  const catalog = page.locator('[data-gm-surface="catalog"]')
  await expect(
    catalog.getByText('e2e digital tour').first()
  ).toBeVisible()
  await expect(catalog.getByText('e2e poster').first()).toBeVisible()
})

test('catalogs tab: create, rename, and delete guards', async ({page}) => {
  const base = `Seasonal ${Date.now()}`
  const renamed = `${base} drop`
  await page.goto('/infinitemarkets/')
  await page.locator('[data-gm-nav="catalog"]').click()
  const catalog = page.locator('[data-gm-surface="catalog"]')
  await expect(catalog.getByRole('button', {name: 'New catalog'})).toBeVisible({
    timeout: 15_000
  })

  // create a second catalog in-pane (no dialog)
  await catalog.getByRole('button', {name: 'New catalog'}).click()
  const editor = catalog.locator('[data-gm-catalog-editor="catalog"]')
  await expect(editor).toBeVisible()
  await editor.getByLabel('Name').fill(base)
  await editor.getByRole('button', {name: 'Create catalog'}).click()
  const table = catalog.locator('[data-gm-table="catalogs"]')
  await expect(table.getByText(base)).toBeVisible({timeout: 15_000})

  // it is selectable when creating a product
  await catalog.getByRole('button', {name: 'New product'}).click()
  await catalog.locator('[data-gm-catalog-editor="product"] .q-select').first().click()
  await expect(page.getByRole('option', {name: base})).toBeVisible()
  await page.keyboard.press('Escape')
  await catalog.getByRole('button', {name: 'Cancel'}).click()

  // rename
  await catalog.getByRole('tab', {name: 'Catalogs'}).click()
  const row = table.locator('tr', {hasText: base})
  await row.getByRole('button', {name: 'Edit catalog'}).click()
  await editor.getByLabel('Name').fill(renamed)
  await editor.getByRole('button', {name: 'Save catalog'}).click()
  await expect(table.getByText(renamed)).toBeVisible({timeout: 15_000})

  // a catalog that still holds products cannot be deleted
  const main = table.locator('tr', {hasText: 'main', hasNotText: 'Seasonal'})
  await main.getByRole('button', {name: 'Delete catalog'}).click()
  const dialog = page.locator('.q-dialog')
  await dialog.getByRole('button', {name: 'Delete', exact: true}).click()
  await expect(dialog).toContainText('product(s)')
  await expect(
    dialog.getByRole('button', {name: 'Delete and strip references'})
  ).toHaveCount(0)
  await dialog.getByRole('button', {name: 'Keep'}).click()

  // an empty one can
  await row.getByRole('button', {name: 'Delete catalog'}).click()
  await dialog.getByRole('button', {name: 'Delete', exact: true}).click()
  await expect(table.getByText(renamed)).toHaveCount(0, {
    timeout: 15_000
  })
})

test('catalog editors stay in-pane and bulk tools update selected products', async ({page}) => {
  await page.goto('/infinitemarkets/')
  await page.locator('[data-gm-nav="catalog"]').click()
  const catalog = page.locator('[data-gm-surface="catalog"]')
  await expect(catalog.getByRole('button', {name: 'New product'})).toBeVisible({
    timeout: 15_000
  })

  await catalog.getByRole('button', {name: 'New product'}).click()
  await expect(catalog.locator('[data-gm-catalog-editor="product"]')).toBeVisible()
  await expect(page.locator('.q-dialog').getByText('New product', {exact: true})).toHaveCount(0)
  await catalog.getByRole('button', {name: 'Cancel'}).click()

  await catalog.getByRole('button', {name: 'New collection'}).click()
  await expect(catalog.locator('[data-gm-catalog-editor="collection"]')).toBeVisible()
  await catalog.getByRole('button', {name: 'Cancel'}).click()
  const collectionsTable = catalog.locator('[data-gm-table="collections"]')
  const collectionHeading = await collectionsTable.getByRole('columnheader', {name: 'Title'}).boundingBox()
  const firstCollection = await collectionsTable.locator('[data-col="title"]').first().boundingBox()
  expect(Math.abs((collectionHeading?.x || 0) - (firstCollection?.x || 0))).toBeLessThanOrEqual(1)
  expect(Math.abs((collectionHeading?.width || 0) - (firstCollection?.width || 0))).toBeLessThanOrEqual(1)

  await catalog.getByRole('button', {name: 'New shipping option'}).click()
  await expect(catalog.locator('[data-gm-catalog-editor="shipping"]')).toBeVisible()
  await catalog.getByRole('button', {name: 'Cancel'}).click()
  const shippingTable = catalog.locator('[data-gm-table="shipping"]')
  const shippingHeading = await shippingTable.getByRole('columnheader', {name: 'Title'}).boundingBox()
  const firstShipping = await shippingTable.locator('[data-col="title"]').first().boundingBox()
  expect(Math.abs((shippingHeading?.x || 0) - (firstShipping?.x || 0))).toBeLessThanOrEqual(1)
  expect(Math.abs((shippingHeading?.width || 0) - (firstShipping?.width || 0))).toBeLessThanOrEqual(1)
  await page.getByRole('tab', {name: 'Products'}).click()

  const csrf = (await page.context().cookies()).find(c => c.name === 'gm_csrf')?.value || ''
  const headers = {Origin: seed.base_url, 'X-CSRF-Token': csrf}
  for (const [title, amount] of [['bulk alpha', 100], ['bulk beta', 200]] as const) {
    const response = await page.request.post('/infinitemarkets/api/v1/products', {
      headers,
      data: {
        catalog_id: seed.digital.catalog_id,
        title,
        amount_minor: amount,
        currency: 'SAT',
        draft: true
      }
    })
    expect(response.status()).toBe(201)
  }

  await page.reload()
  await page.locator('[data-gm-nav="catalog"]').click()
  const table = catalog.locator('[data-gm-table="products"]')
  await expect(table).toBeVisible({timeout: 15_000})
  const heading = await table.getByRole('columnheader', {name: 'Title'}).boundingBox()
  const firstTitle = await table.locator('[data-col="title"]').first().boundingBox()
  expect(Math.abs((heading?.x || 0) - (firstTitle?.x || 0))).toBeLessThanOrEqual(1)
  expect(Math.abs((heading?.width || 0) - (firstTitle?.width || 0))).toBeLessThanOrEqual(1)

  const rowCount = await table.locator('tbody tr').count()
  await table.getByRole('checkbox').first().click()
  await expect(catalog.locator('[data-gm="bulk-bar"]')).toContainText(
    `${rowCount} products selected`
  )
  await catalog.getByRole('button', {name: 'Clear selection'}).click()

  for (const title of ['bulk alpha', 'bulk beta']) {
    await table.locator('tbody tr').filter({hasText: title}).getByRole('checkbox').click()
  }
  await catalog.getByRole('button', {name: 'Bulk edit'}).click()
  await expect(catalog.locator('[data-gm-catalog-editor="bulk"]')).toBeVisible()
  await catalog.getByLabel('Bulk action').click()
  await page.getByRole('option', {name: 'Increase prices by percentage'}).click()
  await catalog.getByLabel('Markup percentage').fill('10')
  await catalog.getByRole('button', {name: 'Apply to 2 products'}).click()
  await expect(table.locator('tbody tr').filter({hasText: 'bulk alpha'})).toContainText('110 SAT')
  await expect(table.locator('tbody tr').filter({hasText: 'bulk beta'})).toContainText('220 SAT')

  for (const title of ['bulk alpha', 'bulk beta']) {
    await table.locator('tbody tr').filter({hasText: title}).getByRole('checkbox').click()
  }
  await catalog.getByRole('button', {name: 'Delete selected'}).click()
  await expect(page.getByText('Delete 2 products', {exact: true})).toBeVisible()
  await page.getByRole('button', {name: 'Delete products'}).click()
  await expect(table.getByText('bulk alpha')).toHaveCount(0)
  await expect(table.getByText('bulk beta')).toHaveCount(0)

  await page.setViewportSize({width: 390, height: 844})
  await catalog.getByRole('button', {name: 'New product'}).click()
  const editorGrid = catalog.locator('[data-gm-catalog-editor="product"] .gm-editor-grid')
  await expect(editorGrid).toBeVisible()
  await expect.poll(() => editorGrid.evaluate(el =>
    getComputedStyle(el).gridTemplateColumns.split(' ').length
  )).toBe(1)
})

test('publications surface shows relay health + evidence copy', async ({
  page
}) => {
  await page.goto('/infinitemarkets/')
  await page.locator('[data-gm-nav="publications"]').click()
  await expect(
    page.getByText(
      'Relay ACKs are delivery evidence — they never mean payment settled.'
    )
  ).toBeVisible({timeout: 15_000})
  // Local relay seeded for the merchant — real positive-ACK evidence
  // lands here after publish (scoped: settings renders it too)
  await expect(
    page
      .locator('[data-gm-surface="publications"]')
      .getByText(seed.relay_url)
      .first()
  ).toBeVisible()
})

test('settings surface: identity, relays, notifications, appearance', async ({
  page
}) => {
  await page.goto('/infinitemarkets/')
  await page.locator('[data-gm-nav="settings"]').click()
  const settings = page.locator('[data-gm-surface="settings"]')
  await expect(settings.getByText('Relays').first()).toBeVisible({
    timeout: 15_000
  })
  await expect(
    settings.getByText(seed.relay_url).first()
  ).toBeVisible()
  await expect(
    page.getByRole('button', {name: 'Save relay configuration'})
  ).toBeVisible()

  await page.getByRole('tab', {name: 'Notifications'}).click()
  await expect(
    page.getByText('Notification addresses', {exact: true})
  ).toBeVisible()

  await page.getByRole('tab', {name: 'Appearance'}).click()
  await expect(
    page.getByText(/warm|preset/i).first()
  ).toBeVisible()
})

test('storefront is one click away from the admin top level', async ({page}) => {
  await page.goto('/infinitemarkets/')
  const storefront = `/infinitemarkets/public/merchants/${seed.pubkey}`
  await expect(page.locator('[data-gm="view-storefront"]')).toHaveAttribute('href', storefront)
  await expect(page.locator('[data-gm-nav="storefront"]')).toHaveAttribute('href', storefront)
})

test('order states are colour-coded with labels and closed orders explain themselves', async ({page}) => {
  await page.goto('/infinitemarkets/')
  // The CSRF cookie is issued by the shell's first admin API read.
  await expect(page.locator('[data-gm="store-bar"]')).toBeVisible({timeout: 20_000})
  const csrf = (await page.context().cookies()).find(c => c.name === 'gm_csrf')?.value || ''
  const checkout = await page.request.post('/infinitemarkets/api/v1/public/checkout', {
    headers: {'Idempotency-Key': crypto.randomUUID() + crypto.randomUUID(), Origin: seed.base_url},
    data: {merchant_pubkey: seed.pubkey, items: [{d_tag: seed.digital.d_tag, quantity: 1}]}
  })
  expect(checkout.status()).toBe(201)
  const orders = await (await page.request.get(`/infinitemarkets/api/v1/merchants/${seed.merchant_id}/orders?state=awaiting_payment`)).json()
  const cancelled = await page.request.post(
    `/infinitemarkets/api/v1/merchants/${seed.merchant_id}/orders/${orders[0].id}/cancel`,
    {headers: {Origin: seed.base_url, 'X-CSRF-Token': csrf, 'Idempotency-Key': crypto.randomUUID() + crypto.randomUUID()},
     data: {reason: 'e2e closed-order copy'}}
  )
  expect(cancelled.status()).toBe(200)

  await page.reload()
  const awaiting = page.locator('.gm-state[data-state="awaiting_payment"]').first()
  const closed = page.locator('.gm-state[data-state="cancelled"]').first()
  await expect(awaiting).toBeVisible({timeout: 20_000})
  await expect(closed).toContainText('Cancelled')
  const bg = (loc: typeof awaiting) => loc.evaluate(el => getComputedStyle(el).backgroundColor)
  expect(await bg(awaiting)).not.toBe(await bg(closed))

  await page.locator('.gm-order-row').filter({has: closed}).first().click()
  await expect(page.locator('[data-gm="closed-note"]')).toContainText('This order was cancelled.')
  await expect(page.getByText('No legal action')).toHaveCount(0)
})

test('appearance choices are not clipped by the settings panel', async ({page}) => {
  await page.goto('/infinitemarkets/')
  await page.locator('[data-gm-nav="settings"]').click()
  await page.getByRole('tab', {name: 'Appearance'}).click()
  const active = page.locator('.gm-preset-active').first()
  await expect(active).toBeVisible()
  // Polled: the tab panel slides in, so measure once it has settled.
  await expect.poll(() => active.evaluate(el => {
    const panel = el.closest('.q-tab-panels')!.getBoundingClientRect()
    const box = el.getBoundingClientRect()
    return box.left - 2 >= panel.left && box.right + 2 <= panel.right
  }), {timeout: 5_000}).toBe(true)
})

test('unauthenticated admin visit redirects or denies', async ({
  browser
}) => {
  const anon = await browser.newContext()
  const page = await anon.newPage()
  const resp = await page.goto('/infinitemarkets/')
  // check_user_exists rejects anonymous — the shell must not render
  expect([302, 307, 401, 403]).toContain(resp?.status())
  await anon.close()
})
