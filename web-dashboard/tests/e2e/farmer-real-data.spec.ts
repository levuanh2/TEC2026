import { expect, test } from '@playwright/test'

const email = process.env.FARMER_REAL_E2E_EMAIL
const password = process.env.FARMER_REAL_E2E_PASSWORD
const enabled = process.env.REAL_E2E === 'true' && process.env.FARMER_REAL_E2E === 'true' && Boolean(email && password)

test.describe('authenticated Farmer real-data experience', () => {
  test.skip(!enabled, 'Set REAL_E2E=true and FARMER_REAL_E2E=true with a dedicated authorized farmer identity; no manager credential is reused as a farmer.')

  test('uses Supabase Auth and FastAPI only, with scoped read-only Farmer data', async ({ page }) => {
    test.setTimeout(360_000)
    const consoleErrors: string[] = []
    const apiPaths: string[] = []
    const unexpectedApi: string[] = []
    const directBusiness: string[] = []
    page.on('console', (message) => { if (message.type() === 'error') consoleErrors.push(message.text()) })
    page.on('request', (request) => {
      const path = new URL(request.url()).pathname
      if (path.startsWith('/v1/')) apiPaths.push(path)
      if (/\/rest\/v1\/(organizations|farms|plots|crop_seasons|activities|carbon_calculations)/.test(path)) directBusiness.push(request.url())
    })
    page.on('response', (response) => {
      const path = new URL(response.url()).pathname
      const allowedNoCalculation = response.status() === 404 && /\/v1\/crop-seasons\/[^/]+\/carbon$/.test(path)
      if (path.startsWith('/v1/') && response.status() >= 400 && !allowedNoCalculation) unexpectedApi.push(`${response.status()} ${path}`)
    })

    await page.goto('/login')
    await page.getByLabel('Email').fill(email!)
    await page.getByLabel('Mật khẩu').fill(password!)
    await page.getByRole('button', { name: 'Đăng nhập' }).click()
    await expect(page).toHaveURL(/\/farmer$/)
    await expect(page.getByRole('heading', { name: 'Hôm nay trên ruộng của bạn', level: 1 })).toBeVisible()
    await expect(page.getByText('MOCK DATA — NOT PRODUCTION.')).toHaveCount(0)
    await expect(page.locator('.fw-ledger')).toBeVisible({ timeout: 60_000 })
    await expect(page.getByRole('button', { name: 'Bón phân', exact: true })).toBeEnabled()
    await page.screenshot({ path: 'test-results/farmer-real-home-1440.png', fullPage: true })

    const nav = page.getByRole('navigation', { name: 'Điều hướng nông hộ', exact: true })
    await nav.getByRole('link', { name: 'Ruộng', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'Các ruộng trong phạm vi của bạn', level: 1 })).toBeVisible()
    await expect(page.locator('.farmer-farm-card').first()).toBeVisible({ timeout: 120_000 })
    await page.getByRole('link', { name: 'Xem ruộng' }).first().click()
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
    await page.locator('.farmer-plot-card').first().click()
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
    await page.locator('.farmer-season-list a').first().click()
    await expect(page.getByRole('tab', { name: 'Nhật ký' })).toBeVisible({ timeout: 60_000 })
    await page.getByRole('tab', { name: 'Nhật ký' }).click()
    await expect(page.getByRole('heading', { name: 'Nhật ký của vụ này' })).toBeVisible()
    await expect(page.locator('.fw-entry').first()).toBeVisible({ timeout: 60_000 })
    await page.locator('.fw-entry__open').first().click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await page.getByRole('button', { name: 'Đóng' }).click()
    await page.getByRole('tab', { name: 'Hiệu suất' }).click()
    await expect(page.getByRole('heading', { name: 'Hiệu suất vụ này' })).toBeVisible()
    await page.getByRole('tab', { name: 'Carbon' }).click()
    await expect(page.locator('.fw-carbon-empty, .fw-carbon-hero').first()).toBeVisible({ timeout: 60_000 })
    await page.setViewportSize({ width: 390, height: 844 })
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    const bottom = page.getByRole('navigation', { name: 'Điều hướng nông hộ trên điện thoại' })
    await expect(bottom).toBeVisible()
    await bottom.getByRole('link', { name: 'Tôi' }).click()
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()

    expect(apiPaths).toEqual(expect.arrayContaining(['/v1/me', '/v1/farmer/scope']))
    // The farms -> plots-per-farm -> seasons-per-plot waterfall is gone.
    expect(apiPaths.filter((path) => /\/v1\/farms\/[^/]+\/plots$/.test(path))).toEqual([])
    expect(apiPaths.filter((path) => /\/v1\/plots\/[^/]+\/crop-seasons$/.test(path))).toEqual([])
    expect(apiPaths.some((path) => /\/v1\/crop-seasons\/[^/]+\/activities$/.test(path))).toBe(true)
    expect(apiPaths.some((path) => /\/v1\/crop-seasons\/[^/]+\/metrics$/.test(path))).toBe(true)
    expect(apiPaths.some((path) => /\/v1\/crop-seasons\/[^/]+\/carbon$/.test(path))).toBe(true)
    expect(unexpectedApi).toEqual([])
    expect(directBusiness).toEqual([])
    expect(consoleErrors.filter((line) => !/Failed to load resource.*\b404\b/i.test(line))).toEqual([])
  })
})
