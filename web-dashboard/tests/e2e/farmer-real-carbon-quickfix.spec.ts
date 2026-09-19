import { expect, test, type Locator, type Page } from '@playwright/test'

/* Real hosted-Supabase UI smoke for the Carbon repair hub.
 *
 * Driven by backend/scripts/hosted_carbon_quickfix_smoke.py, which seeds an
 * isolated tenant (season with NO methodology, a fertilizer record without N,
 * a burned-straw record without dry matter), passes the ids and throwaway
 * credentials here through env, and deletes everything afterwards.
 *
 * The owner must repair every input and calculate Carbon from the Carbon tab
 * alone — the page may never navigate to the Journal. Clicks are counted:
 * a native <select> is two (open + choose), typing is zero. */

const seasonId = process.env.QF_SEASON_ID
const owner = { email: process.env.QF_OWNER_EMAIL, password: process.env.QF_OWNER_PASSWORD }
const viewer = { email: process.env.QF_VIEWER_EMAIL, password: process.env.QF_VIEWER_PASSWORD }

test.skip(process.env.REAL_E2E !== 'true' || !seasonId, 'driven by hosted_carbon_quickfix_smoke.py')

async function signIn(page: Page, who: { email?: string; password?: string }) {
  await page.goto('/login')
  await page.getByLabel('Email').fill(who.email!)
  await page.getByLabel('Mật khẩu').fill(who.password!)
  await page.getByRole('button', { name: 'Đăng nhập' }).click()
  await page.waitForURL(/\/farmer(\/|$)/)
}

const issue = (page: Page, title: string): Locator =>
  page.locator('li.fw-repair__item', { has: page.getByRole('heading', { name: title }) })

test('viewer sees every missing input but no edit or calculate control', async ({ page }) => {
  await signIn(page, viewer)
  await page.goto(`/farmer/crop-seasons/${seasonId}/carbon`)
  await expect(page.getByText(/Cần bổ sung 5 thông tin để tính phát thải/)).toBeVisible()
  await expect(page.getByText(/chỉ có quyền xem/)).toBeVisible()
  await expect(page.locator('.fw-repair select, .fw-repair input')).toHaveCount(0)
  await expect(page.getByRole('button', { name: /Sửa ngay|Lưu|Tính Carbon/ })).toHaveCount(0)
})

test('owner repairs every input and calculates Carbon from the Carbon tab only', async ({ page }) => {
  await signIn(page, owner)
  await page.goto(`/farmer/crop-seasons/${seasonId}/carbon`)
  await expect(page.getByText('Cần bổ sung 5 thông tin để tính phát thải')).toBeVisible()

  const visited: string[] = []
  page.on('framenavigated', (f) => { if (f === page.mainFrame()) visited.push(new URL(f.url()).pathname) })
  let clicks = 0
  const click = async (l: Locator) => { clicks += 1; await l.click() }
  const choose = async (l: Locator, value: string) => { clicks += 2; await l.selectOption(value) }

  // 1. cultivation days — inline
  const days = issue(page, 'Thiếu số ngày canh tác')
  await days.getByLabel('Số ngày canh tác', { exact: true }).fill('100')
  await click(days.getByRole('button', { name: 'Lưu' }))
  await expect(days).toHaveCount(0)

  // 2. both water regimes — inline
  const water = issue(page, 'Thiếu chế độ nước trong vụ')
  await choose(water.getByLabel('Chế độ nước trong vụ', { exact: true }), 'irrigated_continuous_flooding')
  await click(water.getByRole('button', { name: 'Lưu' }))
  await expect(water).toHaveCount(0)
  const pre = issue(page, 'Thiếu chế độ nước trước vụ')
  await choose(pre.getByLabel('Chế độ nước trước vụ', { exact: true }), 'non_flooded_pre_season_lt_180d')
  await click(pre.getByRole('button', { name: 'Lưu' }))
  await expect(pre).toHaveCount(0)

  // 3. fertilizer nitrogen — the exact record, in the shared edit sheet
  const nitrogen = issue(page, 'Thiếu hàm lượng Nitơ của lần bón phân')
  await click(nitrogen.getByRole('button', { name: /Sửa ngay/ }))
  await page.getByLabel(/^Hàm lượng đạm/).fill('16')
  await click(page.getByRole('button', { name: 'Lưu thay đổi' }))
  await expect(nitrogen).toHaveCount(0)

  // 4. straw dry matter — the exact record
  const dry = issue(page, 'Thiếu tỷ lệ chất khô của rơm')
  await click(dry.getByRole('button', { name: /Sửa ngay/ }))
  await page.getByLabel(/^Tỷ lệ chất khô của rơm/).fill('0.85')
  await click(page.getByRole('button', { name: 'Lưu thay đổi' }))
  await expect(dry).toHaveCount(0)

  // 5. readiness complete → 6. calculate
  await expect(page.getByText('Đã đủ dữ liệu để tính phát thải.')).toBeVisible()
  await click(page.getByRole('button', { name: 'Tính Carbon' }))
  await expect(page.getByText('Tổng phát thải của vụ')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Tính lại Carbon' })).toBeVisible()

  expect(visited.filter((p) => p.includes('/journal'))).toEqual([])
  expect(page.url()).toContain(`/farmer/crop-seasons/${seasonId}/carbon`)
  console.log(`QUICKFIX_CLICKS=${clicks}`)
})
