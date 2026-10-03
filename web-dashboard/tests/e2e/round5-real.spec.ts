import { expect, test, type Page } from '@playwright/test'

/* Round 5 real-data gate: Carbon integrity on a real Farmer + Manager session.
 *
 * Read-only. Needs a Farmer season that already has an actual result AND at
 * least one stored simulation (the Round 5 UAT season does). Credentials come
 * from the environment only; the spec skips itself without them:
 *   ROUND5_FARMER_EMAIL / ROUND5_FARMER_PASSWORD
 *   REDESIGN_MANAGER_EMAIL / REDESIGN_MANAGER_PASSWORD
 * Run: REAL_E2E=true npx playwright test --config playwright.real.config.ts tests/e2e/round5-real.spec.ts */

const FARMER = { email: process.env.ROUND5_FARMER_EMAIL, password: process.env.ROUND5_FARMER_PASSWORD }
const MANAGER = { email: process.env.REDESIGN_MANAGER_EMAIL, password: process.env.REDESIGN_MANAGER_PASSWORD }
const API = process.env.REAL_E2E_API_BASE_URL ?? 'http://127.0.0.1:8010'
const RAW = /\b(undefined|NaN|as_recorded|continuous_flooding|irrigation_ch4|fertilizer_n2o|ch4_rice_cultivation|n2o_fertilizer_direct)\b|Kịch bản:\s*actual|Nguồn khác/
const UUID = /\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/i

test.describe.configure({ mode: 'serial' })
test.skip(!FARMER.email || !FARMER.password || !MANAGER.email || !MANAGER.password, 'ROUND5_FARMER_* / REDESIGN_MANAGER_* not set')

async function signIn(page: Page, who: { email?: string; password?: string }) {
  await page.goto('/login')
  await page.getByLabel('Email').fill(who.email!)
  await page.getByLabel('Mật khẩu').fill(who.password!)
  await page.getByRole('button', { name: /Đăng nhập/ }).click()
  try {
    await page.waitForURL(/\/(farmer|dashboard)/, { timeout: 120_000 })
  } catch (e) {
    // Playwright's failure snapshot prints field values in clear text.
    await page.getByLabel('Mật khẩu').fill('', { timeout: 2_000 }).catch(() => {})
    throw e
  }
}

const token = async (page: Page) => {
  await page.locator('main h1').first().waitFor({ timeout: 120_000 })
  return page.evaluate(() => {
    for (const k of Object.keys(localStorage)) if (/auth-token/.test(k)) return JSON.parse(localStorage.getItem(k)!).access_token as string
    return null
  })
}

let seasonId = ''
let actual: { id: string; total: number; perKg: number | null; at: string } | null = null

test('API: the default read is the actual result; simulations are separate and labelled', async ({ page }) => {
  await signIn(page, FARMER)
  const t = await token(page)
  const get = async (p: string) => {
    const r = await page.request.get(API + p, { headers: { Authorization: `Bearer ${t}` } })
    return { status: r.status(), body: await r.json() }
  }
  const scope = (await get('/v1/farmer/scope')).body
  for (const s of scope.crop_seasons as { id: string }[]) {
    const a = await get(`/v1/crop-seasons/${s.id}/carbon`)
    const f = await get(`/v1/crop-seasons/${s.id}/carbon?scenario=continuous_flooding`)
    if (a.status === 200 && f.status === 200) { seasonId = s.id; break }
  }
  test.skip(!seasonId, 'no season with both an actual result and a continuous-flooding simulation')
  const a = (await get(`/v1/crop-seasons/${seasonId}/carbon`)).body
  const named = (await get(`/v1/crop-seasons/${seasonId}/carbon?scenario=as_recorded`)).body
  const flood = (await get(`/v1/crop-seasons/${seasonId}/carbon?scenario=continuous_flooding`)).body
  expect(a.calculation_kind).toBe('actual')
  expect(a.scenario).toBe('as_recorded')
  expect(a.calculation_id).toBe(named.calculation_id)
  expect(flood.calculation_kind).toBe('scenario')
  expect(flood.calculation_id).not.toBe(a.calculation_id)
  // Provenance on the stored result.
  expect(a.ef_config_version).toBeTruthy()
  expect(a.engine_version).toBeTruthy()
  for (const line of a.breakdown) expect(line.source).toMatch(/^(ch4_rice_cultivation|n2o_fertilizer_direct|straw_burning|fuel(_\w+)?)$/)
  const sum = a.breakdown.reduce((s: number, b: { co2e_kg: number }) => s + Number(b.co2e_kg), 0)
  expect(Math.abs(sum - Number(a.total_co2e_kg))).toBeLessThan(0.01)
  actual = { id: a.calculation_id, total: Number(a.total_co2e_kg), perKg: a.co2e_per_kg, at: a.calculated_at }
})

test('Farmer Carbon shows the actual result, names its sources, keeps simulations labelled beside it', async ({ page }) => {
  test.skip(!seasonId || !actual)
  await signIn(page, FARMER)
  await page.goto(`/farmer/crop-seasons/${seasonId}/carbon`)
  await expect(page.getByTestId('carbon-result-state')).toContainText('Kết quả vận hành', { timeout: 120_000 })
  const total = (await page.getByTestId('carbon-actual-total').innerText()).replace(/\./g, '').replace(',', '.')
  expect(Math.abs(Number(total) - actual!.total)).toBeLessThan(0.01)
  await expect(page.getByTestId('carbon-scenario-continuous_flooding')).toContainText('Kịch bản mô phỏng')
  await expect(page.getByText(/không phải kết quả đã ghi nhận/)).toBeVisible()
  // Result → methodology → factor/source in at most three actions (here: one).
  await page.getByText('Phương pháp và hệ số sử dụng').click()
  await expect(page.getByTestId('carbon-methodology')).toContainText(/Phiên bản bộ hệ số\s*\S+/)
  await expect(page.getByTestId('carbon-methodology')).toContainText('Nguồn hệ số')
  const text = await page.locator('main').innerText()
  expect(text).not.toMatch(RAW)
  expect(text).not.toMatch(UUID)
})

test('Manager surfaces show the same actual result; the season is not claimed as an MRV member', async ({ page }) => {
  test.skip(!seasonId || !actual)
  await signIn(page, MANAGER)
  const perKg = actual!.perKg == null ? null : actual!.perKg.toLocaleString('vi-VN', { maximumFractionDigits: 3, minimumFractionDigits: 3 })
  await page.goto(`/crop-seasons/${seasonId}/carbon`)
  await expect(page.getByTestId('carbon-result-meta')).toContainText('Kết quả vận hành', { timeout: 120_000 })
  if (perKg) await expect(page.locator('main')).toContainText(perKg)
  await page.getByText('Phương pháp và hệ số sử dụng').click()
  let text = await page.locator('main').innerText()
  expect(text).not.toMatch(RAW)
  expect(text).not.toMatch(UUID)
  await page.goto('/carbon')
  await expect(page.locator('main table tbody tr, main .ops-table tbody tr').first()).toBeVisible({ timeout: 120_000 })
  await page.waitForLoadState('networkidle')
  if (perKg) await expect(page.locator('main')).toContainText(perKg)
  await page.goto(`/crop-seasons/${seasonId}/mrv`)
  await expect(page.getByTestId('season-mrv-membership')).toHaveAttribute('data-linked', /true|false/, { timeout: 120_000 })
  text = await page.locator('main').innerText()
  expect(text).not.toContain('tham gia hồ sơ MRV của tổ chức thông qua')
  if ((await page.getByTestId('season-mrv-membership').getAttribute('data-linked')) === 'false') {
    await expect(page.locator('main')).toContainText('Vụ này chưa thuộc hồ sơ MRV nào.')
  }
})
