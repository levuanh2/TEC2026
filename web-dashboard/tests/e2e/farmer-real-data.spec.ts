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
    // Signed in as a farmer: on the Farmer home, one h1 that names it, the
    // Farmer navigation (never Management's), and no login form left.
    await expect(page).toHaveURL(/\/farmer$/)
    await expect(page.getByRole('heading', { level: 1 })).toHaveCount(1)
    await expect(page.getByRole('heading', { name: 'Hôm nay trên ruộng của bạn', level: 1 })).toBeVisible()
    const nav = page.getByRole('navigation', { name: 'Điều hướng nông hộ', exact: true })
    await expect(nav.getByRole('link', { name: 'Tổng quan' })).toHaveAttribute('aria-current', 'page')
    await expect(page.getByRole('navigation', { name: 'Điều hướng chính' })).toHaveCount(0)
    await expect(page.getByLabel('Mật khẩu')).toHaveCount(0)
    await expect(page.getByText('MOCK DATA — NOT PRODUCTION.')).toHaveCount(0)

    // Recent activity has loaded into one of its two valid states — rows, or
    // the deliberate empty state — and is neither still loading nor an error.
    const recent = page.getByRole('region', { name: 'Hoạt động gần đây' })
    await expect(recent).toBeVisible()
    await expect(recent.locator('[aria-busy="true"]')).toHaveCount(0)
    await expect(recent.getByRole('alert')).toHaveCount(0)
    await expect(recent.getByRole('link', { name: 'Xem toàn bộ nhật ký' })).toHaveAttribute('href', '/farmer/journal')
    const rows = await recent.getByRole('listitem').count()
    const empty = await recent.getByText('Chưa có hoạt động nào được ghi nhận cho vụ này.').count()
    expect(rows > 0 !== (empty > 0), `recent activity: ${rows} rows, ${empty} empty states — exactly one must hold`).toBe(true)
    await page.screenshot({ path: 'test-results/farmer-real-home-1440.png', fullPage: true })

    await nav.getByRole('link', { name: 'Ruộng / Vụ mùa', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'Các ruộng trong phạm vi của bạn', level: 1 })).toBeVisible()
    await page.getByRole('link', { name: /^Xem hồ sơ nông hộ / }).first().click()
    await expect(page.getByRole('heading', { level: 1 })).toHaveCount(1)
    await expect(page.getByRole('heading', { name: 'Thửa ruộng' })).toBeVisible()
    await page.getByRole('main').getByRole('link', { name: /^Thửa .*Mã thửa/ }).first().click()
    await expect(page.getByRole('heading', { level: 1 })).toHaveCount(1)
    await page.getByRole('main').getByRole('link', { name: /^Vụ đang canh tác/ }).first().click()
    await expect(page.getByRole('tab', { name: 'Nhật ký' })).toBeVisible()
    // Recording is available to this farm member.
    await expect(page.getByRole('button', { name: 'Ghi hoạt động' }).first()).toBeEnabled()
    await page.getByRole('tab', { name: 'Nhật ký' }).click()
    await expect(page.getByRole('heading', { name: 'Nhật ký của vụ này' })).toBeVisible()
    const entry = page.getByRole('list', { name: 'Nhật ký theo ngày' }).getByRole('button', { name: /^(?!Sửa bản ghi|Xóa bản ghi)/ })
    await expect(entry.first()).toBeVisible()
    await entry.first().click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await page.getByRole('button', { name: 'Đóng' }).click()
    await page.getByRole('tab', { name: 'Hiệu suất' }).click()
    await expect(page.getByRole('heading', { name: 'Hiệu suất vụ này' })).toBeVisible()
    await page.getByRole('tab', { name: 'Carbon' }).click()
    // A result, or the honest no-result state — never an estimate.
    await expect(page.getByRole('heading', { name: 'Chưa có kết quả phát thải cho vụ này' }).or(page.getByText('Tổng phát thải vụ này'))).toBeVisible()
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

// M07 part 3: the Management export controls must not exist for a farmer. The
// app keeps a farmer inside /farmer, so a deep link to /mrv never renders them.
test.describe('authenticated Farmer cannot reach Management MRV export', () => {
  const exportEnabled = enabled && process.env.REAL_MRV_EXPORT_E2E === 'true'
  test.skip(!exportEnabled, 'Set REAL_E2E=true, FARMER_REAL_E2E=true and REAL_MRV_EXPORT_E2E=true with the Farmer QA identity.')

  test('a farmer deep-linking to /mrv stays in the Farmer shell with no export controls', async ({ page }) => {
    test.setTimeout(180_000)
    await page.goto('/login')
    await page.getByLabel('Email').fill(email!)
    await page.getByLabel('Mật khẩu').fill(password!)
    await page.getByRole('button', { name: 'Đăng nhập' }).click()
    await expect(page).toHaveURL(/\/farmer/, { timeout: 120_000 })

    await page.goto('/mrv')
    await expect(page).toHaveURL(/\/farmer/, { timeout: 120_000 })
    for (const name of ['Xuất PDF', 'Xuất Excel (.xlsx)', 'Xuất JSON']) {
      await expect(page.getByRole('button', { name })).toHaveCount(0)
    }
    await expect(page.getByText('Lịch sử xuất')).toHaveCount(0)
  })
})
