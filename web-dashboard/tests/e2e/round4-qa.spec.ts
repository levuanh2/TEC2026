import { expect, test, type Page } from '@playwright/test'

/* Round 4 regression gates — mock tenant, no credentials.
 *
 * The mock viewer belongs to no cooperative, so the Management season tables
 * are empty here; the drawer gate runs on real data in round4-real.spec.ts.
 * The CV capability check is a unit test (farmer/cvAvailability.test.ts):
 * mock mode never calls the CV service.
 *
 * Auth (logout, session expiry) and the Carbon quick-fix need a real Supabase
 * session and a real readiness answer, so they live in round4-real.spec.ts
 * and in the DOM tests (api/auth.dom.test.tsx, farmer/quickfix.dom.test.tsx).
 */

const S = 'crop-demo-01'
const VIEWPORTS = [
  { width: 1440, height: 1000 }, { width: 1280, height: 900 }, { width: 768, height: 1024 }, { width: 390, height: 844 },
]
const ROUTES = ['/farmer', '/farmer/journal', '/farmer/farms', '/farmer/performance', '/farmer/carbon', '/farmer/account',
  `/farmer/crop-seasons/${S}`, '/dashboard', '/farms', '/seasons', '/data-gaps', '/carbon', '/mrv', '/organizations',
  '/performance', `/crop-seasons/${S}`, `/crop-seasons/${S}/activities`, `/crop-seasons/${S}/carbon`]

const settle = async (page: Page, path: string) => {
  await page.goto(path, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(700)
}
const headers = (page: Page) => page.locator('table.ops-table thead th').allInnerTexts()

test('Farmer Home carries exactly one primary action and no competing blocks', async ({ page }) => {
  await settle(page, '/farmer')
  const main = page.locator('main')
  // Primary = filled button voice. Links and soft/ghost buttons are secondary.
  const primaries = main.locator('.fw-btn:not(.fw-btn--ghost):not(.fw-btn--soft):visible')
  expect(await primaries.count()).toBeLessThanOrEqual(1)
  // Quick entry, performance snapshot, recommendations and the leaf check
  // each have a page of their own now.
  await expect(main.locator('.fw-quick')).toHaveCount(0)
  await expect(main.locator('.fw-snap')).toHaveCount(0)
  await expect(main.locator('.fw-cvcard')).toHaveCount(0)
  await expect(main.getByText('Kiểm tra lá lúa')).toHaveCount(0)
  await expect(main.getByText('Tạm thời chưa dùng được')).toHaveCount(0)
})

test('/seasons, /data-gaps and /carbon are three different jobs', async ({ page }) => {
  await settle(page, '/seasons')
  const seasons = await headers(page)
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Vụ mùa')
  await settle(page, '/data-gaps')
  const gaps = await headers(page)
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Dữ liệu còn thiếu')
  await expect(page.getByLabel('Hiện cả vụ đã đủ dữ liệu')).not.toBeChecked()
  await settle(page, '/carbon')
  const carbon = await headers(page)
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Carbon theo vụ')

  expect(seasons.map((h) => h.toLowerCase())).toEqual(expect.arrayContaining(['giai đoạn', 'gieo sạ', 'thu hoạch']))
  expect(gaps.map((h) => h.toLowerCase())).toEqual(expect.arrayContaining(['cần bổ sung', 'thông tin còn thiếu']))
  expect(carbon.map((h) => h.toLowerCase())).toEqual(expect.arrayContaining(['sẵn sàng', 'kết quả', 'độ mới', 'tổng co₂e', 'co₂e / kg']))
  expect(new Set([seasons.join('|'), gaps.join('|'), carbon.join('|')]).size).toBe(3)
  // Every view keeps the three identity columns.
  for (const cols of [seasons, gaps, carbon]) expect(cols.slice(0, 3).map((h) => h.toLowerCase())).toEqual(['nông hộ', 'thửa', 'vụ'])
})

test('the Carbon tab never points at itself or at a disabled control', async ({ page }) => {
  await settle(page, `/crop-seasons/${S}/carbon`)
  await page.waitForTimeout(800)
  await expect(page.getByRole('button', { name: 'Xem Carbon' })).toHaveCount(0)
  await expect(page.getByRole('link', { name: 'Xem Carbon' })).toHaveCount(0)
  const text = await page.locator('main').innerText()
  expect(text).not.toMatch(/Tính lại theo kịch bản/)
  // Any control the copy names by its label must be on screen and enabled.
  for (const [, name] of text.matchAll(/(?:Nhấn|Chọn|Bấm) “([^”]+)”/g)) {
    const button = page.getByRole('button', { name, exact: true })
    await expect(button).toBeVisible()
    await expect(button).toBeEnabled()
  }
  await expect(page.locator('main button:disabled', { hasText: /Tính/ })).toHaveCount(0)
})

test('no raw enum, uuid, ISO timestamp or English disclaimer on default screens', async ({ page }) => {
  test.setTimeout(120_000)
  const RAW = /\b(active|planned|draft|incorporated|awd|continuous_flooding|as_recorded|straw_management|in_progress|not_started|photo|default)\b/
  for (const path of ROUTES) {
    await settle(page, path)
    const text = await page.locator('main').innerText()
    expect(text, path).not.toMatch(RAW)
    expect(text, path).not.toMatch(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/)
    expect(text, path).not.toMatch(/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/)
    expect(text, path).not.toMatch(/SYNTHETIC DATA|NOT FIELD DATA|Invalid login/i)
  }
})

test('no horizontal overflow at 1440 / 1280 / 768 / 390', async ({ page }) => {
  test.setTimeout(240_000)
  for (const vp of VIEWPORTS) {
    await page.setViewportSize(vp)
    for (const path of ROUTES) {
      await settle(page, path)
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
      expect(overflow, `${path} @ ${vp.width}`).toBeLessThanOrEqual(0)
    }
  }
})

test('Management sidebar marks the current page by shape and weight, on one line', async ({ page }) => {
  await settle(page, '/dashboard')
  const active = page.locator('.nav a[aria-current="page"]')
  await expect(active).toHaveText('Tổng quan vận hành')
  const style = await active.evaluate((a) => { const s = getComputedStyle(a); return { weight: Number(s.fontWeight), shadow: s.boxShadow, h: a.getBoundingClientRect().height } })
  expect(style.weight).toBeGreaterThanOrEqual(700)
  expect(style.shadow).not.toBe('none')
  expect(style.h).toBeLessThan(48) // one line
})
