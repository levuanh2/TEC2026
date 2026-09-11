import { expect, test } from '@playwright/test'

const email = process.env.REAL_E2E_EMAIL
const password = process.env.REAL_E2E_PASSWORD
const enabled = process.env.REAL_E2E === 'true' && Boolean(email && password)

test.describe('authenticated real-data dashboard', () => {
  test.skip(!enabled, 'Set REAL_E2E=true, REAL_E2E_EMAIL, and REAL_E2E_PASSWORD in a local gitignored environment.')

  test('uses Supabase Auth and FastAPI real-domain data without mock fallback', async ({ page }) => {
    const consoleErrors: string[] = []
    const apiPaths: string[] = []
    const failedApiResponses: string[] = []
    const directBusinessRequests: string[] = []

    page.on('console', (message) => {
      if (message.type() === 'error') consoleErrors.push(message.text())
    })
    page.on('request', (request) => {
      const url = request.url()
      const parsed = new URL(url)
      if (parsed.pathname.startsWith('/v1/')) apiPaths.push(parsed.pathname)
      // Auth calls to Supabase are permitted; business-table PostgREST calls are not.
      if (/\/rest\/v1\/(organizations|farms|plots|crop_seasons|activities|carbon_calculations)/.test(parsed.pathname)) {
        directBusinessRequests.push(url)
      }
    })
    page.on('response', (response) => {
      const parsed = new URL(response.url())
      if (parsed.pathname.startsWith('/v1/') && response.status() >= 400) {
        // A crop season with no successful calculation yet returns 404 on the
        // carbon GET by design (seed_demo_data.py deliberately seeds no
        // carbon_calculations — no fabricated CO2e). That is an expected state,
        // not a failure.
        const expectedNoCalc = response.status() === 404 && /\/v1\/crop-seasons\/[^/]+\/carbon$/.test(parsed.pathname)
        if (!expectedNoCalc) failedApiResponses.push(`${response.status()} ${parsed.pathname}`)
      }
    })

    await page.goto('/login')
    await page.getByLabel('Email').fill(email!)
    await page.getByLabel('Mật khẩu').fill(password!)
    await page.getByRole('button', { name: 'Đăng nhập' }).click()

    await expect(page).toHaveURL(/\/dashboard$/)
    await expect(page.getByRole('heading', { name: 'Tổng quan', level: 1 })).toBeVisible()
    await expect(page.getByText('MOCK DATA — NOT PRODUCTION.')).toHaveCount(0)

    // Wait for /v1/me to resolve so the manager scope (org context + nav) is in
    // place before asserting on it — otherwise a slow hosted call races the
    // click-through and the aggregate views are silently skipped. This also
    // guarantees DashboardBody has mounted, so its /v1/organizations/{id}/summary
    // etc. requests have been issued (checked by the apiPaths assertions below).
    // We do NOT wait for the KPI values to render: those aggregate rollups can
    // exceed a minute against hosted Supabase and blocking on them is flaky.
    await expect(page.locator('.org-chip')).not.toHaveText(/Chưa gán tổ chức/)

    // Organization and aggregate performance are real FastAPI views for roles
    // that can navigate there. Farmers may legitimately not see this link.
    const organizationLink = page.getByRole('link', { name: 'Tổ chức / HTX' })
    if (await organizationLink.count()) {
      await organizationLink.click()
      await expect(page.getByRole('heading', { name: 'Tổ chức / HTX', level: 1 })).toBeVisible()
      await page.getByRole('link', { name: 'Tổng quan' }).click()
      await expect(page).toHaveURL(/\/dashboard$/)
    }

    // Dashboard → real farm hierarchy → season subflows.
    await page.getByRole('link', { name: 'Nông hộ' }).click()
    await expect(page.getByRole('heading', { name: 'Nông hộ', level: 1 })).toBeVisible()
    await expect(page.locator('tbody tr').first()).toBeVisible()
    await page.locator('tbody tr').first().click()
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Thửa ruộng' })).toBeVisible()

    await page.locator('tbody tr').first().click()
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Vụ canh tác' })).toBeVisible()
    await page.locator('tbody tr').first().click()
    await expect(page.getByRole('tab', { name: 'Tổng quan' })).toBeVisible()

    await page.getByRole('tab', { name: 'Hoạt động' }).click()
    await expect(page.getByRole('heading', { name: 'Nhật ký hoạt động' })).toBeVisible()
    await expect(page.locator('.act').first()).toBeVisible()
    await page.locator('.act').first().click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await page.getByRole('button', { name: 'Đóng' }).click()

    await page.getByRole('tab', { name: 'Hiệu suất' }).click()
    await expect(page.getByRole('heading', { name: 'Hiệu suất trên mỗi kg thóc' })).toBeVisible()

    await page.getByRole('tab', { name: 'Carbon' }).click()
    await expect(page.getByRole('heading', { name: 'Phát thải carbon' })).toBeVisible()

    await page.goto('/mrv')
    await expect(page.getByRole('heading', { name: 'Hồ sơ MRV', level: 1 })).toBeVisible()

    expect(apiPaths).toEqual(expect.arrayContaining([
      '/v1/me',
      '/v1/farms',
      '/v1/mrv/cases',
    ]))
    expect(apiPaths.some((path) => /\/v1\/organizations\/[^/]+$/.test(path))).toBe(true)
    expect(apiPaths.some((path) => /\/v1\/organizations\/[^/]+\/summary$/.test(path))).toBe(true)
    expect(apiPaths.some((path) => /\/v1\/organizations\/[^/]+\/(metrics|farm-performance)$/.test(path))).toBe(true)
    expect(apiPaths.some((path) => /\/v1\/farms\/[^/]+$/.test(path))).toBe(true)
    expect(apiPaths.some((path) => /\/v1\/farms\/[^/]+\/plots$/.test(path))).toBe(true)
    expect(apiPaths.some((path) => /\/v1\/plots\/[^/]+$/.test(path))).toBe(true)
    expect(apiPaths.some((path) => /\/v1\/crop-seasons\/[^/]+$/.test(path))).toBe(true)
    expect(apiPaths.some((path) => /\/v1\/crop-seasons\/[^/]+\/activities$/.test(path))).toBe(true)
    expect(apiPaths.some((path) => /\/v1\/crop-seasons\/[^/]+\/metrics$/.test(path))).toBe(true)
    expect(apiPaths.some((path) => /\/v1\/crop-seasons\/[^/]+\/carbon$/.test(path))).toBe(true)
    expect(failedApiResponses).toEqual([])
    expect(directBusinessRequests).toEqual([])
    // The browser logs a generic "Failed to load resource … 404" line for the
    // expected carbon-not-calculated state above; anything else is a real error.
    const realConsoleErrors = consoleErrors.filter((e) => !/Failed to load resource.*\b404\b/i.test(e))
    expect(realConsoleErrors).toEqual([])
  })

  // Regression for a real bug found while redesigning the Management shell:
  // App.tsx had two effects both keyed on `session` — when session flipped
  // from null to real on a fresh load, the role-redirect effect ran once
  // with the STILL-default 'farmer' role (a one-commit-flush stale read),
  // spuriously pushing '/farmer' before correcting to '/dashboard' — losing
  // whatever route was actually requested. A full page load/refresh/deep
  // link to any non-farmer route for a non-farmer role therefore always
  // ended up on '/dashboard' instead. Fixed by driving the redirect off the
  // freshly-resolved role value directly, never a value read back from
  // state. This must stay on the route it was given.
  test('a full page load straight to a management route stays on that route', async ({ page }) => {
    await page.goto('/login')
    await page.getByLabel('Email').fill(email!)
    await page.getByLabel('Mật khẩu').fill(password!)
    await page.getByRole('button', { name: 'Đăng nhập' }).click()
    await page.waitForURL((u) => u.pathname !== '/login')

    for (const path of ['/organizations', '/farms', '/performance', '/mrv']) {
      await page.goto(path, { waitUntil: 'networkidle' })
      await page.waitForTimeout(1500)
      expect(new URL(page.url()).pathname).toBe(path)
    }
  })
})
