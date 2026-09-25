import { expect, test, type Page } from '@playwright/test'
import { axe, blocking } from './axe-helper'

/* Round 4.4 real-data gate: Management metrics truth and clarity on a real
 * Manager session (hosted Supabase via local FastAPI), checked against the
 * Farmer's own view of the same farm.
 *
 * Read-only. Credentials come from REDESIGN_* in the environment, never from
 * this file; the spec skips itself without them. Run with
 *   REAL_E2E=true npx playwright test --config playwright.real.config.ts tests/e2e/round44-real.spec.ts */

const FARMER = { email: process.env.REDESIGN_FARMER_EMAIL, password: process.env.REDESIGN_FARMER_PASSWORD }
const MANAGER = { email: process.env.REDESIGN_MANAGER_EMAIL, password: process.env.REDESIGN_MANAGER_PASSWORD }
const DEV_TERMS = /\b(endpoint|API|payload|batch|null|undefined|NaN|yield_kg|data_status|dataStatus|farm_id|season_id)\b/
const HARVEST_EMPTY = ['Có vụ chưa ghi sản lượng thu hoạch', 'Chưa có sản lượng thu hoạch']
const SENTENCE = /^(Tính trên \d+\/\d+ nông hộ đủ dữ liệu\.|Chưa công bố chỉ số toàn HTX — (\d+\/\d+ nông hộ còn thiếu dữ liệu|mới có \d+\/\d+ nông hộ đủ dữ liệu|HTX chưa có nông hộ nào)\.)$/

test.describe.configure({ mode: 'serial' })
test.skip(!FARMER.email || !FARMER.password || !MANAGER.email || !MANAGER.password, 'REDESIGN_* credentials not set')

async function signIn(page: Page, who: { email?: string; password?: string }) {
  await page.goto('/login')
  await page.getByLabel('Email').fill(who.email!)
  await page.getByLabel('Mật khẩu').fill(who.password!)
  await page.getByRole('button', { name: /Đăng nhập/ }).click()
  try {
    await page.waitForURL(/\/(farmer|dashboard)/, { timeout: 120_000 })
  } catch (e) {
    // Playwright's failure snapshot prints field values in clear text.
    await page.getByLabel('Mật khẩu').fill('').catch(() => {})
    throw e
  }
}

async function openPerformance(page: Page) {
  await page.goto('/performance')
  await expect(page.getByTestId('aggregate-coverage')).toHaveCount(4, { timeout: 120_000 })
  for (const c of await page.getByTestId('aggregate-coverage').all()) await expect(c).toHaveText(SENTENCE, { timeout: 120_000 })
  await expect(page.locator('.perf-table tbody tr').first()).toBeVisible({ timeout: 120_000 })
}

test('Manager /performance: partial harvest is never "no harvest", one sentence per aggregate, no developer copy', async ({ page }) => {
  await signIn(page, MANAGER)
  await page.waitForLoadState('networkidle')
  const seasonMetrics: string[] = []
  const api: string[] = []
  page.on('request', (r) => {
    if (/\/v1\//.test(r.url()) && r.method() !== 'OPTIONS') api.push(r.url())
    if (/\/v1\/crop-seasons\/[^/]+\/metrics/.test(r.url())) seasonMetrics.push(r.url())
  })
  await page.setViewportSize({ width: 1348, height: 900 })
  await openPerformance(page)
  const main = page.locator('main')

  // The false copy is gone, and every empty yield cell is one of the two
  // truthful states.
  await expect(main).not.toContainText('Chưa ghi thu hoạch')
  for (const cell of await page.locator('.perf-table td[data-label="Sản lượng"]').all()) {
    const t = (await cell.innerText()).trim()
    if (!/kg$/.test(t)) expect(HARVEST_EMPTY).toContain(t)
  }
  // A farm whose yield is incomplete is never shown as complete.
  for (const row of await page.locator('.perf-table tbody tr').all()) {
    if (await row.locator('[data-harvest]').count()) await expect(row).not.toContainText('Đầy đủ dữ liệu')
  }
  // A withheld aggregate shows no figure.
  for (const card of await page.getByTestId('aggregate-metric').all()) {
    const withheld = /^Chưa công bố/.test(await card.getByTestId('aggregate-coverage').innerText())
    expect(await card.locator('.agg__value').count()).toBe(withheld ? 0 : 1)
  }
  // Every disclosure opens exactly its farms, each with a reason and a link to that farm.
  for (const card of await page.getByTestId('aggregate-metric').all()) {
    const toggle = card.getByRole('button', { name: /^\d+ nông hộ thiếu dữ liệu$/ })
    if (!(await toggle.count())) continue
    const n = Number((await toggle.innerText()).match(/(\d+)/)![1])
    await expect(toggle).toHaveAttribute('aria-expanded', 'false')
    await toggle.focus()
    await page.keyboard.press('Enter')
    await expect(toggle).toHaveAttribute('aria-expanded', 'true')
    await expect(card.locator('.agg__list li')).toHaveCount(n)
    for (const li of await card.locator('.agg__list li').all()) {
      await expect(li.getByRole('link')).toHaveAttribute('href', /^\/farms\/[0-9a-f-]{36}$/)
      await expect(li.locator('small')).not.toBeEmpty()
    }
  }
  const text = await main.innerText()
  expect(text.match(DEV_TERMS)?.[0] ?? null).toBeNull()

  await page.waitForLoadState('networkidle')
  expect(seasonMetrics, 'no per-season /metrics on Management Performance').toEqual([])
  // Distinct endpoints, not raw requests: the real config serves the Vite dev
  // server, where React StrictMode fires every useAsync twice. A production
  // preview makes exactly these five calls once each (Round 4.4 report §9).
  const distinct = [...new Set(api.map((u) => new URL(u).pathname.replace(/[0-9a-f-]{36}/g, '{id}')))].sort()
  expect(distinct).toEqual([
    '/v1/farmer/scope', '/v1/me', '/v1/organizations/{id}', '/v1/organizations/{id}/farm-performance', '/v1/organizations/{id}/metrics',
  ])
  const v = blocking(await axe(page))
  expect(v, JSON.stringify(v, null, 2)).toEqual([])
})

test('Manager /performance layout: cost and Carbon share a row on desktop, one column below; no overflow anywhere', async ({ page }) => {
  await signIn(page, MANAGER)
  for (const vw of [1440, 1348, 1024, 768, 390]) {
    await page.setViewportSize({ width: vw, height: 900 })
    await openPerformance(page)
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth), `${vw}px overflow`).toBeLessThanOrEqual(0)
    const [cost, carbon] = await page.locator('.perf-pair > .section').all()
    const a = (await cost.boundingBox())!
    const b = (await carbon.boundingBox())!
    if (vw >= 1100) expect(Math.abs(a.y - b.y), `${vw}px: same row`).toBeLessThan(2)
    else expect(b.y, `${vw}px: stacked`).toBeGreaterThan(a.y + a.height - 1)
    if (vw === 1024 || vw === 390) {
      const v = blocking(await axe(page))
      expect(v, `${vw}px ` + JSON.stringify(v, null, 2)).toEqual([])
    }
  }
})

test('Farmer and Manager agree: a farm the Farmer sees harvested is not "no harvest" for the Manager', async ({ browser }) => {
  const f = await browser.newPage()
  await signIn(f, FARMER)
  await f.goto('/farmer/performance')
  await expect(f.getByRole('heading', { name: 'Bối cảnh vụ mùa' })).toBeVisible({ timeout: 120_000 })
  await expect(f.locator('[aria-busy="true"]')).toHaveCount(0, { timeout: 120_000 })
  const farmerHasYield = /\d[\d.]* kg thóc/.test(await f.locator('main').innerText())
  await f.close()

  const m = await browser.newPage()
  await signIn(m, MANAGER)
  await openPerformance(m)
  // The QA Farmer belongs to "Hộ demo 1" (DEMO-FARM-01).
  const row = m.locator('.perf-table tbody tr', { has: m.getByRole('link', { name: /Hộ demo 1/ }) })
  const cell = (await row.locator('td[data-label="Sản lượng"]').innerText()).trim()
  if (farmerHasYield) expect(cell).not.toBe('Chưa có sản lượng thu hoạch')
  expect(cell).not.toBe('Chưa ghi thu hoạch')
  await m.close()
})
