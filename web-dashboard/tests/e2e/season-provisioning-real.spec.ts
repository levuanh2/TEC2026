import { writeFileSync } from 'node:fs'
import { expect, test, type Browser, type Page } from '@playwright/test'

/* Real hosted-Supabase smoke: manager-provisioned farmer → first season → first
 * record → closed season. Driven by backend/scripts/hosted_season_provisioning_smoke.py,
 * which creates a DISPOSABLE cooperative and manager, checks the database
 * between the two phases, closes the season, and deletes everything.
 *
 * Credentials arrive only through the process environment. The temporary
 * password the manager is shown is handed back to the driver through a file
 * in its scratch directory (never logged); the driver deletes it. */

const phase = process.env.SP_PHASE
const tag = process.env.SP_TAG ?? ''
const manager = { email: process.env.SP_MANAGER_EMAIL, password: process.env.SP_MANAGER_PASSWORD }
const farmerEmail = process.env.SP_FARMER_EMAIL
const secretFile = process.env.SP_SECRET_FILE

test.skip(process.env.REAL_E2E !== 'true' || !phase, 'driven by hosted_season_provisioning_smoke.py')
test.describe.configure({ mode: 'serial' })

async function signIn(page: Page, email: string, password: string) {
  await page.goto('/login')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Mật khẩu').fill(password)
  await page.getByRole('button', { name: 'Đăng nhập' }).click()
  await page.waitForURL((u) => u.pathname !== '/login')
  // Clear the field's value from the DOM in case a later failure dumps it.
  await page.evaluate(() => document.querySelectorAll('input[type=password]').forEach((i) => { (i as HTMLInputElement).value = '' }))
}

async function asFarmer(browser: Browser, password: string) {
  const context = await browser.newContext()
  const page = await context.newPage()
  await signIn(page, farmerEmail!, password)
  await page.waitForURL(/\/farmer(\/|$)/)
  return { page, close: () => context.close() }
}

test('onboard: manager provisions, farmer starts a season and records the first activity', async ({ page, browser }) => {
  test.skip(phase !== 'onboard')
  /* ---------------------------------------------------------- manager */
  await signIn(page, manager.email!, manager.password!)
  await page.goto('/accounts/farmers')
  await expect(page.getByRole('heading', { name: 'Tài khoản nông hộ' })).toBeVisible()
  await page.getByRole('button', { name: /Thêm nông hộ/ }).first().click()
  await page.waitForURL('**/accounts/farmers/new')
  await page.getByLabel(/Họ và tên/).fill(`Nông dân ${tag}`)
  await page.getByLabel(/Email đăng nhập/).fill(farmerEmail!)
  await page.getByLabel(/Tên nông hộ/).fill(`Hộ ${tag}`)
  await page.getByLabel(/Mã hộ/).fill(`${tag}-FARM`)
  await page.getByLabel(/Tên thửa/).fill(`Thửa ${tag}`)
  await page.getByLabel(/Mã thửa/).fill(`${tag}-PLOT`)
  await page.getByLabel(/Diện tích/).fill('1,25')
  await page.getByRole('button', { name: 'Tạo tài khoản nông hộ' }).click()
  const code = page.getByTestId('temporary-password')
  await expect(code).toBeVisible({ timeout: 60_000 })
  const temporary = (await code.textContent())!.trim()
  writeFileSync(secretFile!, temporary, { encoding: 'utf-8' })
  await expect(page.getByText(/chỉ hiển thị một lần/)).toBeVisible()
  await expect(page.getByRole('button', { name: /Bắt đầu vụ cho thửa này/ })).toBeVisible()
  // Repeated submit is impossible from here (the form is gone); the list shows the new farmer at the right stage.
  await page.goto('/accounts/farmers')
  const row = page.locator('tr', { hasText: farmerEmail! })
  await expect(row).toBeVisible()
  await expect(row.getByText('Sẵn sàng bắt đầu vụ')).toBeVisible()
  await expect(row.getByRole('button', { name: 'Tạo vụ' })).toBeVisible()

  /* ----------------------------------------------------------- farmer */
  const farmer = await asFarmer(browser, temporary)
  const f = farmer.page
  // Only its own farm is in scope.
  await f.goto('/farmer/farms')
  await expect(f.locator('.farmer-farm-card')).toHaveCount(1)
  await expect(f.getByRole('heading', { name: `Hộ ${tag}` })).toBeVisible()

  await f.goto('/farmer/journal')
  await expect(f.getByText('Bạn chưa có vụ đang canh tác')).toBeVisible()
  await expect(f.getByText(/Bạn cần bắt đầu một vụ trên thửa ruộng trước khi ghi nhật ký hoạt động/)).toBeVisible()
  await expect(f.getByRole('button', { name: /^Ghi hoạt động/ })).toHaveCount(0)
  await f.getByRole('button', { name: /Bắt đầu vụ mới/ }).click()
  await f.getByLabel(/Tên vụ/).fill(`${tag}-HT`)
  await f.getByLabel(/Giống lúa/).fill('OM5451')
  await f.getByLabel(/Ngày gieo sạ/).fill('2026-09-01')
  await f.getByRole('button', { name: 'Bắt đầu vụ', exact: true }).click()
  await f.waitForURL(/\/farmer\/crop-seasons\/[^/?]+\?vu-moi=1$/, { timeout: 60_000 })
  const seasonId = new URL(f.url()).pathname.split('/')[3]
  writeFileSync(secretFile!, `${temporary}\n${seasonId}`, { encoding: 'utf-8' })

  await f.getByRole('button', { name: /Ghi hoạt động đầu tiên/ }).click()
  await f.getByRole('group', { name: 'Chọn loại hoạt động' }).getByRole('button', { name: /^Tưới nước/ }).click()
  await expect(f.getByRole('dialog', { name: 'Ghi tưới nước' })).toBeVisible()
  await f.getByLabel('Hình thức tưới').selectOption('awd')
  await f.getByLabel(/^Ghi chú/).fill(`${tag}-FIRST`)
  await f.getByRole('button', { name: 'Lưu hoạt động' }).click()
  await expect(f.getByRole('dialog', { name: 'Ghi tưới nước' })).toHaveCount(0, { timeout: 60_000 })
  await f.goto(`/farmer/crop-seasons/${seasonId}/journal`)
  await expect(f.getByText(`${tag}-FIRST`)).toBeVisible({ timeout: 60_000 })
  await expect(f.getByRole('button', { name: /^Ghi hoạt động/ }).first()).toBeVisible()
  // Resource Metrics and Carbon readiness render for the new season.
  await f.goto(`/farmer/crop-seasons/${seasonId}/performance`)
  await expect(f.getByRole('heading', { name: 'Hiệu suất vụ này' })).toBeVisible()
  await f.goto(`/farmer/crop-seasons/${seasonId}/carbon`)
  await expect(f.getByText(/Cần bổ sung \d+ thông tin để tính phát thải/)).toBeVisible({ timeout: 60_000 })
  await farmer.close()
})

test('closed: a harvested season stays readable and is never a write target', async ({ browser }) => {
  test.skip(phase !== 'closed')
  const password = process.env.SP_FARMER_PASSWORD!
  const seasonId = process.env.SP_SEASON_ID!
  const farmer = await asFarmer(browser, password)
  const f = farmer.page
  await f.goto('/farmer/journal')
  await expect(f.getByText('Bạn chưa có vụ đang canh tác')).toBeVisible()
  await expect(f.getByText('Nhật ký các vụ trước')).toBeVisible()
  await expect(f.getByText(`${tag}-FIRST`)).toBeVisible({ timeout: 60_000 })
  await expect(f.getByRole('button', { name: /^Ghi hoạt động/ })).toHaveCount(0)
  await f.goto(`/farmer/crop-seasons/${seasonId}/journal`)
  await expect(f.getByText(`${tag}-FIRST`)).toBeVisible({ timeout: 60_000 })
  await expect(f.getByRole('button', { name: /^Ghi hoạt động/ })).toHaveCount(0)
  await expect(f.getByRole('button', { name: /Sửa bản ghi|Xóa bản ghi/ })).toHaveCount(0)
  // The plot can start its next season.
  await f.goto('/farmer/farms')
  await f.locator('.fw-farm__plot').first().click()
  await expect(f.getByRole('button', { name: /Bắt đầu vụ mới/ })).toBeVisible()
  await farmer.close()
})
