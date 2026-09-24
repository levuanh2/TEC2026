import { expect, test, type Page } from '@playwright/test'
import { axe, blocking } from './axe-helper'

/* Round 4.3 real-data gate: meaningful metrics and the Management drawer on a
 * real Farmer and a real Manager session (hosted Supabase via local FastAPI).
 *
 * Read-only. Credentials come from REDESIGN_* in the environment, never from
 * this file; the spec skips itself without them. Run with
 *   REAL_E2E=true npx playwright test --config playwright.real.config.ts tests/e2e/round43-real.spec.ts */

const FARMER = { email: process.env.REDESIGN_FARMER_EMAIL, password: process.env.REDESIGN_FARMER_PASSWORD }
const MANAGER = { email: process.env.REDESIGN_MANAGER_EMAIL, password: process.env.REDESIGN_MANAGER_PASSWORD }
const JUDGEMENT = ['tốt', 'xấu', 'tiết kiệm', 'lãng phí', 'đạt chuẩn', 'vượt chuẩn']

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

const settled = (page: Page) => expect(page.locator('[aria-busy="true"]')).toHaveCount(0, { timeout: 120_000 })

test('Farmer: Performance explains every metric from real data, without a grade', async ({ page }) => {
  await signIn(page, FARMER)
  await page.goto('/farmer/performance')
  await expect(page.getByRole('heading', { name: 'Bối cảnh vụ mùa' })).toBeVisible({ timeout: 120_000 })
  await settled(page)
  const main = page.locator('main')
  // Four groups in order, cost apart from Carbon.
  await expect(main.locator('.fw-mgroup__title')).toHaveText(['Bối cảnh vụ mùa', 'Hiệu quả tài nguyên', 'Chi phí trực tiếp đã ghi', 'Phát thải Carbon'])
  expect(await main.locator('.fw-mgroup--cost .fw-mrow--carbon').count()).toBe(0)

  const water = main.locator('[data-metric="water"]')
  if (await water.locator('.fw-mrow__value').count()) {
    await expect(water.locator('.fw-mrow__value')).toContainText('lít nước / kg lúa')
    await expect(water).toContainText('m³ / kg lúa')
    await expect(water).toContainText(/Tính từ .* m³ nước và .* kg thóc đã ghi\./)
  } else {
    await expect(water.locator('.fw-metric__empty')).toContainText('Chưa đủ dữ liệu')
  }
  await expect(main.getByText('Chưa có mốc để đánh giá cao hay thấp.').first()).toBeVisible()

  const text = (await main.innerText()).toLowerCase()
  for (const w of JUDGEMENT) expect(text, w).not.toContain(w)
  expect(text).not.toMatch(/(^|\s)0 ₫/)

  // Carbon: a figure, or the count of what is missing with the quick-fix link.
  const carbon = main.locator('[data-metric="carbon"]')
  if (!(await carbon.locator('.fw-mrow__value').count())) {
    await expect(carbon.getByRole('link', { name: /Bổ sung \d+ thông tin|Xem Carbon/ })).toHaveAttribute('href', '/farmer/carbon')
  }
  for (const btn of await main.getByRole('button', { name: /Cách tính và dữ liệu sử dụng/ }).all()) {
    await expect(btn).toHaveAttribute('aria-expanded', 'false')
  }
  const v = blocking(await axe(page))
  expect(v, JSON.stringify(v, null, 2)).toEqual([])

  // The "Xem hoạt động tưới" link lands on the filtered journal.
  const link = water.getByRole('link', { name: 'Xem hoạt động tưới' })
  if (await link.count()) {
    await link.click()
    await expect(page).toHaveURL(/\/farmer\/journal\?loai=irrigation$/)
    await expect(page.locator('.fw-pill', { hasText: 'Tưới nước' })).toHaveAttribute('aria-pressed', 'true', { timeout: 60_000 })
  }
})

test('Farmer: Home keeps the count as a journal line and stays short', async ({ page }) => {
  await signIn(page, FARMER)
  await settled(page)
  await expect(page.locator('.fw-journal-line')).toContainText(/Nhật ký: (\d+ hoạt động đã ghi|chưa có hoạt động nào)/, { timeout: 120_000 })
  expect(await page.locator('.fw-summary .fw-role--positive').count()).toBe(0)
  await expect(page.locator('.fw-cost__label')).toHaveText('Chi phí trực tiếp đã ghi')
  const v = blocking(await axe(page))
  expect(v, JSON.stringify(v, null, 2)).toEqual([])
  await page.goto('/farmer/carbon')
  await settled(page)
  const v2 = blocking(await axe(page))
  expect(v2, JSON.stringify(v2, null, 2)).toEqual([])
})

test('Manager: every aggregate states its coverage and opens its missing seasons', async ({ page }) => {
  await signIn(page, MANAGER)
  await page.goto('/performance')
  const coverage = page.getByTestId('aggregate-coverage')
  await expect(coverage).toHaveCount(4, { timeout: 120_000 })
  for (const c of await coverage.all()) await expect(c).toContainText(/^Dựa trên \d+\/\d+ vụ đủ dữ liệu/, { timeout: 180_000 })
  for (const card of await page.getByTestId('aggregate-metric').all()) {
    const toggle = card.getByRole('button', { name: /\d+ vụ thiếu dữ liệu/ })
    if (!(await toggle.count())) continue
    const n = Number((await toggle.innerText()).match(/(\d+) vụ/)![1])
    await expect(card.locator('.agg__list')).toBeHidden()
    await toggle.click()
    await expect(toggle).toHaveAttribute('aria-expanded', 'true')
    await expect(card.locator('.agg__list a')).toHaveCount(n)
    await expect(card.locator('.agg__list')).toBeVisible()
  }
  const v = blocking(await axe(page))
  expect(v, JSON.stringify(v, null, 2)).toEqual([])
  await page.goto('/dashboard')
  await expect(page.getByTestId('ops-scope')).toContainText(/Phạm vi: toàn HTX · \d+ vụ/, { timeout: 180_000 })
  const v2 = blocking(await axe(page))
  expect(v2, JSON.stringify(v2, null, 2)).toEqual([])
})

test('Manager 390px: drawer opens over a backdrop, and a tap outside closes it', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await signIn(page, MANAGER)
  const menu = page.getByRole('button', { name: 'Mở menu' })
  await menu.click()
  await expect(page.getByTestId('drawer-backdrop')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Đóng menu' })).toBeFocused()
  await page.mouse.click(370, 420)
  await expect(page.getByTestId('drawer-backdrop')).toHaveCount(0)
  await expect(menu).toBeFocused()
})
