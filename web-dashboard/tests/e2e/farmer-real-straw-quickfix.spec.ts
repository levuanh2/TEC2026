import { expect, test, type Locator, type Page } from '@playwright/test'

/* Real hosted-Supabase UI smoke: the Carbon straw quick-fix persists.
 *
 * Driven by backend/scripts/hosted_straw_quickfix_smoke.py, which seeds an
 * isolated tenant whose records have NO author (`recorded_by` NULL, exactly as
 * the demo seed writes them — the shape that used to answer 404 on save),
 * passes ids and throwaway credentials here through env, verifies the rows in
 * Postgres afterwards, and deletes everything.
 *
 * "Persisted" is never taken from React state: after every save the record is
 * read back from the API, and at the end the page is hard-refreshed. */

const seasonA = process.env.SQF_SEASON_A
const seasonB = process.env.SQF_SEASON_B
const strawId = process.env.SQF_STRAW_ID
const fertilizerId = process.env.SQF_FERTILIZER_ID
const api = process.env.SQF_API
const token = process.env.SQF_API_TOKEN
const owner = { email: process.env.SQF_OWNER_EMAIL, password: process.env.SQF_OWNER_PASSWORD }

test.skip(process.env.REAL_E2E !== 'true' || !seasonA, 'driven by hosted_straw_quickfix_smoke.py')

async function signIn(page: Page) {
  await page.goto('/login')
  await page.getByLabel('Email').fill(owner.email!)
  await page.getByLabel('Mật khẩu').fill(owner.password!)
  await page.getByRole('button', { name: 'Đăng nhập' }).click()
  await page.waitForURL(/\/farmer(\/|$)/)
}

const issue = (page: Page, title: string): Locator =>
  page.locator('li.fw-repair__item', { has: page.getByRole('heading', { name: title }) })

/** A fresh server read of the stored record — not the page's cache. */
async function stored(page: Page, id: string): Promise<Record<string, unknown>> {
  const r = await page.request.get(`${api}/v1/activities/${id}`, { headers: { Authorization: `Bearer ${token}` } })
  expect(r.status()).toBe(200)
  return (await r.json()).payload
}

const DAYS = 'Thiếu số ngày vùi rơm trước khi làm đất'
const DRY = 'Thiếu tỷ lệ chất khô của rơm'
const NITROGEN = 'Thiếu hàm lượng Nitơ của lần bón phân'

test('straw quick-fix on a seeded record persists, updates readiness, and survives a hard refresh', async ({ page }) => {
  const patches: { url: string; body: unknown; status?: number }[] = []
  page.on('request', (req) => {
    if (req.method() === 'PATCH' && req.url().includes('/v1/activities/')) patches.push({ url: req.url(), body: req.postDataJSON() })
  })
  page.on('response', (res) => {
    const hit = patches.find((p) => p.url === res.url() && p.status === undefined)
    if (hit && res.request().method() === 'PATCH') hit.status = res.status()
  })

  await signIn(page)
  await page.goto(`/farmer/crop-seasons/${seasonA}/carbon`)
  await expect(issue(page, DAYS)).toBeVisible()
  await expect(issue(page, DRY)).toBeVisible()
  await expect(issue(page, NITROGEN)).toBeVisible()

  // 1. days only — the dry-matter card must stay.
  await issue(page, DAYS).getByRole('button', { name: /Sửa ngay/ }).click()
  await expect(page.getByRole('heading', { name: 'Chỉnh sửa rơm rạ' })).toBeVisible()
  await page.getByLabel(/^Số ngày trước khi làm đất/).fill('20')
  await page.getByRole('button', { name: 'Lưu thay đổi' }).click()
  await expect(issue(page, DAYS)).toHaveCount(0)
  await expect(issue(page, DRY)).toBeVisible()
  expect(patches[0].url).toContain(strawId!)
  expect(patches[0].status).toBe(200)
  console.log(`PATCH#1 ${JSON.stringify(patches[0].body)} -> ${patches[0].status}`)
  let straw = await stored(page, strawId!)
  expect(straw.days_before_cultivation).toBe(20)
  expect(straw.dry_matter_fraction).toBeNull()

  // 2. dry matter, typed with the decimal comma the hint shows, plus returned.
  await issue(page, DRY).getByRole('button', { name: /Sửa ngay/ }).click()
  await expect(page.getByLabel(/^Số ngày trước khi làm đất/)).toHaveValue('20')
  await page.getByLabel(/^Tỷ lệ chất khô của rơm/).fill('0,85')
  await page.getByLabel(/^Rơm có được trả lại ruộng không/).selectOption('yes')
  await page.getByRole('button', { name: 'Lưu thay đổi' }).click()
  await expect(issue(page, DRY)).toHaveCount(0)
  expect(patches[1].status).toBe(200)
  console.log(`PATCH#2 ${JSON.stringify(patches[1].body)} -> ${patches[1].status}`)
  straw = await stored(page, strawId!)
  expect(straw.days_before_cultivation).toBe(20)
  expect(straw.dry_matter_fraction).toBe(0.85)
  expect(straw.returned_to_field).toBe(true)

  // 3. fertilizer regression on the same shared edit path.
  await issue(page, NITROGEN).getByRole('button', { name: /Sửa ngay/ }).click()
  await page.getByLabel(/^Hàm lượng đạm/).fill('16')
  await page.getByRole('button', { name: 'Lưu thay đổi' }).click()
  await expect(issue(page, NITROGEN)).toHaveCount(0)
  expect((await stored(page, fertilizerId!)).nitrogen_percent).toBe(16)

  // 4. ready, without a reload.
  await expect(page.getByText('Đã đủ dữ liệu để tính phát thải.')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Tính Carbon' })).toBeVisible()

  // 5. hard refresh: readiness still complete, and the reopened form holds both values.
  await page.reload()
  await expect(page.getByText('Đã đủ dữ liệu để tính phát thải.')).toBeVisible()
  await expect(page.locator('li.fw-repair__item')).toHaveCount(0)
  await page.goto(`/farmer/crop-seasons/${seasonA}/journal`)
  await page.reload()
  await page.getByRole('button', { name: /^Sửa bản ghi .*[Rr]ơm/ }).first().click()
  await expect(page.getByLabel(/^Số ngày trước khi làm đất/)).toHaveValue('20')
  await expect(page.getByLabel(/^Tỷ lệ chất khô của rơm/)).toHaveValue('0.85')
  await expect(page.getByLabel(/^Rơm có được trả lại ruộng không/)).toHaveValue('yes')
})

test('fuel stays a separate, non-editable limitation once straw is complete', async ({ page }) => {
  await signIn(page)
  await page.goto(`/farmer/crop-seasons/${seasonB}/carbon`)
  const fuel = page.locator('li.fw-repair__item', { hasText: /nhiên liệu/ })
  await expect(fuel).toBeVisible()
  await expect(fuel.getByRole('button', { name: /Sửa ngay/ })).toHaveCount(0)
  await expect(issue(page, DAYS)).toHaveCount(0)
  await expect(issue(page, DRY)).toHaveCount(0)
  await expect(page.getByText('Đã đủ dữ liệu để tính phát thải.')).toHaveCount(0)
})
