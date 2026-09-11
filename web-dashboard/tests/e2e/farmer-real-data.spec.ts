import { expect, test } from '@playwright/test'

const email = process.env.FARMER_REAL_E2E_EMAIL
const password = process.env.FARMER_REAL_E2E_PASSWORD
const enabled = process.env.REAL_E2E === 'true' && process.env.FARMER_REAL_E2E === 'true' && Boolean(email && password)

test.describe('authenticated Farmer real-data experience', () => {
  test.skip(!enabled, 'Set REAL_E2E=true and FARMER_REAL_E2E=true with a dedicated authorized farmer identity; no manager credential is reused as a farmer.')

  test('uses Supabase Auth and FastAPI only, with scoped read-only Farmer data', async ({ page }) => {
    // The current hosted read path resolves a Farmer hierarchy through RLS.
    // Wait for the actual card, not just the progressively rendered heading.
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
    await expect(page.getByRole('button', { name: 'Bón phân — sắp có' })).toBeDisabled()
    await page.screenshot({ path: 'test-results/farmer-real-home-1440.png', fullPage: true })

    await page.getByRole('link', { name: /Ruộng/ }).first().click()
    await expect(page.getByRole('heading', { name: 'Các ruộng trong phạm vi của bạn', level: 1 })).toBeVisible()
    await expect(page.locator('.farmer-farm-card').first()).toBeVisible({ timeout: 120_000 })
    await page.screenshot({ path: 'test-results/farmer-real-farms-1440.png', fullPage: true })
    await page.getByRole('link', { name: 'Xem ruộng' }).first().click()
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
    await page.locator('.farmer-plot-card').first().click()
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
    await page.screenshot({ path: 'test-results/farmer-real-plot-1440.png', fullPage: true })
    await page.locator('.farmer-season-list a').first().click()
    await page.screenshot({ path: 'test-results/farmer-real-season-1440.png', fullPage: true })
    await page.getByRole('tab', { name: 'Nhật ký' }).click()
    await expect(page.getByRole('heading', { name: 'Nhật ký canh tác' })).toBeVisible()
    await expect(page.locator('.act').first()).toBeVisible()
    await page.screenshot({ path: 'test-results/farmer-real-journal-1440.png', fullPage: true })
    await page.locator('.act').first().click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await page.getByRole('button', { name: 'Đóng' }).click()
    await page.getByRole('tab', { name: 'Hiệu suất' }).click()
    await expect(page.getByRole('heading', { name: 'Hiệu suất vụ này' })).toBeVisible()
    await page.screenshot({ path: 'test-results/farmer-real-performance-1440.png', fullPage: true })
    await page.getByRole('tab', { name: 'Carbon' }).click()
    await expect(page.getByText('Chưa có kết quả Carbon')).toBeVisible()
    await page.screenshot({ path: 'test-results/farmer-real-carbon-1440.png', fullPage: true })
    await page.setViewportSize({ width: 390, height: 844 })
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    await page.screenshot({ path: 'test-results/farmer-real-carbon-390.png', fullPage: true })
    await page.getByRole('link', { name: /Tôi/ }).last().click()
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()

    expect(apiPaths).toEqual(expect.arrayContaining(['/v1/me', '/v1/farms']))
    expect(apiPaths.some((path) => /\/v1\/farms\/[^/]+\/plots$/.test(path))).toBe(true)
    expect(apiPaths.some((path) => /\/v1\/crop-seasons\/[^/]+\/activities$/.test(path))).toBe(true)
    expect(apiPaths.some((path) => /\/v1\/crop-seasons\/[^/]+\/metrics$/.test(path))).toBe(true)
    expect(apiPaths.some((path) => /\/v1\/crop-seasons\/[^/]+\/carbon$/.test(path))).toBe(true)
    expect(unexpectedApi).toEqual([])
    expect(directBusiness).toEqual([])
    expect(consoleErrors.filter((line) => !/Failed to load resource.*\b404\b/i.test(line))).toEqual([])
  })
})
