import { expect, test, type Page } from '@playwright/test'

/* Round 4 real-data gates: auth boundary and the Carbon quick-fix contract,
 * against a real Supabase session and a real readiness answer.
 *
 * Skips itself without REDESIGN_* credentials. Never saves anything: the
 * quick-fix test types invalid values and closes the sheet. Run with
 *   REDESIGN_FARMER_EMAIL/PASSWORD, REDESIGN_MANAGER_EMAIL/PASSWORD set,
 *   npx playwright test --config playwright.real.config.ts tests/e2e/round4-real.spec.ts
 * (trace and screenshots stay off in that config: a trace records fill()). */

const FARMER = { email: process.env.REDESIGN_FARMER_EMAIL, password: process.env.REDESIGN_FARMER_PASSWORD }
const MANAGER = { email: process.env.REDESIGN_MANAGER_EMAIL, password: process.env.REDESIGN_MANAGER_PASSWORD }

async function signIn(page: Page, who: { email?: string; password?: string }) {
  await page.goto('/login')
  await page.getByLabel('Email').fill(who.email!)
  await page.getByLabel('Mật khẩu').fill(who.password!)
  await page.getByRole('button', { name: /Đăng nhập/ }).click()
  await page.waitForURL(/\/(farmer|dashboard)/, { timeout: 120_000 })
}
const signedOut = async (page: Page) => {
  await expect(page.locator('input[type=password]')).toBeVisible({ timeout: 15_000 })
  await expect(page.locator('.fw-shell, .shell')).toHaveCount(0)
}

test.describe('Round 4 — real session', () => {
  test.skip(!FARMER.email || !FARMER.password || !MANAGER.email || !MANAGER.password, 'REDESIGN_* credentials not set')

  test('Farmer logout leaves the shell, and Back does not bring data back', async ({ page }) => {
    await signIn(page, FARMER)
    await page.goto('/farmer/account')
    await page.getByRole('button', { name: /Đăng xuất/ }).click()
    await signedOut(page)
    await expect(page).toHaveURL(/\/login$/)
    await expect(page.getByText('Bạn đã đăng xuất.')).toBeVisible()
    await page.goBack()
    await signedOut(page)
    await expect(page.getByText('Hộ demo')).toHaveCount(0)
  })

  test('Management logout leaves the shell', async ({ page }) => {
    await signIn(page, MANAGER)
    await page.getByRole('button', { name: 'Đăng xuất' }).click()
    await signedOut(page)
    await expect(page).toHaveURL(/\/login$/)
  })

  test('an expired session lands on login with a re-login action, not a half-signed-in shell', async ({ page }) => {
    await signIn(page, FARMER)
    await page.route(/\/v1\//, (r) => r.fulfill({ status: 401, contentType: 'application/json', body: JSON.stringify({ detail: { error: { code: 'unauthenticated', message: 'Token expired' } } }) }))
    await page.route(/\/auth\/v1\/token/, (r) => r.fulfill({ status: 400, contentType: 'application/json', body: JSON.stringify({ error: 'invalid_grant' }) }))
    await page.goto('/farmer/journal')
    await signedOut(page)
    await expect(page.getByText('Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Đăng nhập lại' })).toBeVisible()
    // No redirect loop: the URL settles on /login and stays there.
    await page.waitForTimeout(2000)
    await expect(page).toHaveURL(/\/login\?next=%2Ffarmer%2Fjournal$/)
  })

  test('the straw quick-fix asks for what readiness says is missing', async ({ page }) => {
    await signIn(page, FARMER)
    await page.goto('/farmer/carbon')
    const fix = page.getByRole('button', { name: /Sửa ngay/ }).first()
    const hasGap = await fix.waitFor({ state: 'visible', timeout: 90_000 }).then(() => true, () => false)
    test.skip(!hasGap, 'no open straw gap on this tenant')
    await fix.click()
    const sheet = page.getByRole('dialog')
    const days = sheet.getByLabel(/Số ngày trước khi làm đất/)
    const dry = sheet.getByLabel(/Tỷ lệ chất khô của rơm/)
    await expect(sheet).not.toContainText('Số ngày trước khi làm đấtKhông bắt buộc')
    await expect(sheet.locator('label', { hasText: 'Tỷ lệ chất khô' })).not.toContainText('Không bắt buộc')
    await expect(days.or(dry).first()).toBeFocused()
    await dry.fill('1,5')
    await expect(sheet.getByText(/không quá 1/)).toBeVisible()
    await days.fill('2,5')
    await expect(sheet.getByText(/số nguyên/)).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(sheet).toHaveCount(0)
  })

  test('the season drawer overlays the table without resizing a single column', async ({ page }) => {
    await signIn(page, MANAGER)
    for (const vp of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
      await page.setViewportSize(vp)
      await page.goto('/seasons')
      await page.locator('table.ops-table tbody tr button').first().waitFor({ timeout: 120_000 })
      const before = await page.locator('table.ops-table thead th').evaluateAll((ths) => ths.map((th) => Math.round(th.getBoundingClientRect().width)))
      const open = page.locator('table.ops-table tbody tr button').first()
      await open.click()
      const dialog = page.getByRole('dialog')
      await expect(dialog).toBeVisible()
      const after = await page.locator('table.ops-table thead th').evaluateAll((ths) => ths.map((th) => Math.round(th.getBoundingClientRect().width)))
      expect(after).toEqual(before)
      // Keyboard: focus starts inside, Tab stays inside, Escape closes, focus returns.
      expect(await dialog.evaluate((d) => d.contains(document.activeElement))).toBe(true)
      for (let i = 0; i < 8; i++) await page.keyboard.press('Tab')
      expect(await dialog.evaluate((d) => d.contains(document.activeElement))).toBe(true)
      await page.keyboard.press('Escape')
      await expect(dialog).toHaveCount(0)
      expect(await open.evaluate((b) => b === document.activeElement)).toBe(true)
      if (vp.width < 900) {
        await open.click()
        const box = await page.locator('.side-drawer').boundingBox()
        expect(Math.round(box!.width)).toBe(vp.width)
        await page.keyboard.press('Escape')
      }
    }
  })
})
