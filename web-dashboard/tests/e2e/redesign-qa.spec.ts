import { expect, test, type Page } from '@playwright/test'

/* Reading one season's Carbon readiness takes seconds against hosted Supabase,
 * and a cooperative screen reads several. */
test.setTimeout(240_000)

/* Visual + behavioural QA for the hybrid redesign, against the real API.
 *
 * Credentials come from the environment (REDESIGN_FARMER_EMAIL/PASSWORD,
 * REDESIGN_MANAGER_EMAIL/PASSWORD) — never from this file. Screenshots land in
 * `.qa-screenshots/redesign/` (gitignored) so before/after can be compared.
 */

const farmer = { email: process.env.REDESIGN_FARMER_EMAIL, password: process.env.REDESIGN_FARMER_PASSWORD }
const manager = { email: process.env.REDESIGN_MANAGER_EMAIL, password: process.env.REDESIGN_MANAGER_PASSWORD }
const OUT = '.qa-screenshots/redesign'

test.skip(process.env.REDESIGN_QA !== 'true' || !farmer.email, 'set REDESIGN_QA=true with the QA credentials')

const VIEWPORTS = [
  { name: 'desktop', width: 1440, height: 1024 },
  { name: 'tablet', width: 768, height: 1024 },
  { name: 'mobile', width: 390, height: 844 },
] as const

async function signIn(page: Page, who: { email?: string; password?: string }) {
  await page.goto('/login')
  await page.getByLabel('Email').fill(who.email!)
  await page.getByLabel('Mật khẩu').fill(who.password!)
  await page.getByRole('button', { name: 'Đăng nhập' }).click()
  await page.waitForURL(/\/(farmer|dashboard)/)
}

/** No horizontal overflow at any width: a phone must never scroll sideways. */
async function expectNoOverflow(page: Page, label: string) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow, `${label} overflows horizontally by ${overflow}px`).toBeLessThanOrEqual(1)
}

/** A 404 from `GET /carbon` is the documented "no_calculation" answer, not a
 * failure: the browser logs it anyway. Everything else counts. */
function appErrors(errors: string[]): string[] {
  return errors.filter((e) => !e.includes('favicon') && !e.includes('404'))
}

async function shoot(page: Page, name: string, viewport: (typeof VIEWPORTS)[number]) {
  await page.setViewportSize({ width: viewport.width, height: viewport.height })
  // Readiness takes seconds per season: a screenshot of skeletons proves
  // nothing, so wait for the page to stop fetching first.
  await page.waitForLoadState('networkidle', { timeout: 90_000 }).catch(() => {})
  await page.waitForTimeout(800)
  await page.screenshot({ path: `${OUT}/${name}-${viewport.name}.png`, fullPage: true })
  await expectNoOverflow(page, `${name} @ ${viewport.name}`)
}

test('farmer screens across viewports', async ({ page }) => {
  const errors: string[] = []
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()) })

  await signIn(page, farmer)
  for (const vp of VIEWPORTS) {
    await page.goto('/farmer')
    await expect(page.getByRole('heading', { name: 'Hôm nay trên ruộng của bạn' })).toBeVisible()
    await shoot(page, 'farmer-home', vp)

    await page.goto('/farmer/journal')
    await expect(page.getByRole('heading', { name: 'Nhật ký canh tác' })).toBeVisible()
    await shoot(page, 'farmer-journal', vp)

    await page.goto('/farmer/carbon')
    await page.waitForTimeout(1500)
    await shoot(page, 'farmer-carbon', vp)

    await page.goto('/farmer/performance')
    await shoot(page, 'farmer-performance', vp)
  }

  // The phone bottom bar sits above the content, not inside it: a viewport
  // shot (not fullPage) is the only way to see what a farmer actually sees.
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/farmer')
  await page.waitForLoadState('networkidle', { timeout: 90_000 }).catch(() => {})
  await page.screenshot({ path: `${OUT}/farmer-home-mobile-viewport.png` })
  const bar = page.locator('.fw-bottom')
  await expect(bar).toBeVisible()
  const box = await bar.boundingBox()
  expect(box!.y + box!.height).toBeLessThanOrEqual(845)

  // One primary action, never two competing buttons on the home screen.
  await page.setViewportSize({ width: 1440, height: 1024 })
  await page.goto('/farmer')
  await page.waitForTimeout(1200)
  await expect(page.locator('.fw-next')).toHaveCount(1)
  expect(appErrors(errors), `console errors: ${errors.join(' | ')}`).toEqual([])
})

test('management operations workspace across viewports', async ({ page }) => {
  const errors: string[] = []
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()) })

  await signIn(page, manager)
  for (const vp of VIEWPORTS) {
    await page.goto('/dashboard')
    await expect(page.getByRole('heading', { name: 'Hôm nay cần xử lý gì?' })).toBeVisible()
    await page.waitForTimeout(8000)
    await shoot(page, 'mgmt-overview', vp)

    await page.goto('/seasons')
    await expect(page.getByRole('heading', { name: 'Danh sách nông hộ và vụ mùa' })).toBeVisible()
    await page.waitForTimeout(6000)
    await shoot(page, 'mgmt-seasons', vp)

    await page.goto('/data-gaps')
    await page.waitForTimeout(2000)
    await shoot(page, 'mgmt-data-gaps', vp)

    await page.goto('/mrv')
    await page.waitForTimeout(1200)
    await shoot(page, 'mgmt-mrv', vp)
  }
  expect(appErrors(errors), `console errors: ${errors.join(' | ')}`).toEqual([])
})

test('season row opens a detail panel without leaving the list', async ({ page }) => {
  await signIn(page, manager)
  await page.setViewportSize({ width: 1440, height: 1024 })
  await page.goto('/seasons')
  const rows = page.locator('.ops-table--seasons tbody tr')
  await expect(rows.first()).toBeVisible({ timeout: 60_000 })
  // Rows appear before their per-season detail finishes loading.
  await expect(page.locator('.ops-badge').first()).toBeVisible({ timeout: 120_000 })
  await rows.first().getByRole('button', { name: 'Chi tiết' }).click()
  await expect(page.locator('.ops-detail')).toBeVisible()
  await expect(page).toHaveURL(/\/seasons$/)
  await page.screenshot({ path: `${OUT}/mgmt-seasons-detail-desktop.png`, fullPage: true })
})

test('keyboard reaches the primary action and focus is visible', async ({ page }) => {
  await signIn(page, farmer)
  await page.setViewportSize({ width: 1440, height: 1024 })
  await page.goto('/farmer')
  await page.waitForTimeout(1200)
  const cta = page.locator('.fw-next__cta')
  if (await cta.count()) {
    await cta.focus()
    const outline = await cta.evaluate((el) => {
      const s = getComputedStyle(el)
      return `${s.outlineStyle} ${s.outlineWidth} ${s.boxShadow}`
    })
    expect(outline).not.toBe('none 0px none')
  }
})
