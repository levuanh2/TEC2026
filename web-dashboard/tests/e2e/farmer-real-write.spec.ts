import { expect, test, type Page } from '@playwright/test'

// FW-2 Part 2 real authenticated Farmer write QA (brief §34-40). Mutates only
// isolated, uniquely-marked rows on the DEMO-FARM-01 QA identity and cleans
// every one of them up before the test ends — every mutating step has a
// matching delete, regardless of PASS/FAIL.
const email = process.env.FARMER_REAL_E2E_EMAIL
const password = process.env.FARMER_REAL_E2E_PASSWORD
const enabled = process.env.REAL_E2E === 'true' && process.env.FARMER_REAL_E2E === 'true' && process.env.FARMER_REAL_WRITE_E2E === 'true' && Boolean(email && password)

/** Timeline rows don't render `note`, only the type-specific summary — so a
 * journal-wide text marker only works for fertilizer (whose summary shows the
 * farmer's free-text fertilizer name). Irrigation/harvest are located by
 * being the chronologically-last row in their group (brief FW-2 journal is a
 * date-sorted farmer log; a "today"-dated QA entry sorts last), then
 * confirmed by opening the drawer and reading the `Ghi chú` marker. */
function lastRowIn(page: Page, groupLabel: string) {
  return page.locator('.timeline__group').filter({ has: page.locator('.timeline__label', { hasText: groupLabel }) }).locator('.act').last()
}

/**
 * React StrictMode (dev server) double-invokes effects, so every
 * `useAsync().reload()` fires two real network requests to the same
 * endpoint — only the second updates app state, but both hit the backend
 * and both land in `log`. Racing a single `waitForResponse` against that is
 * unreliable (an earlier step's orphaned duplicate can be mistaken for a
 * later step's reload).
 *
 * `afterCount` is `log.length` captured right before the action that should
 * trigger a new reload — the function first waits for growth PAST that
 * count (so it never returns stale data if the new request just hasn't
 * landed yet), then waits for growth to stop for a quiet window (so it
 * absorbs the duplicate and any trailing reload before reading the tail).
 */
async function waitForNewMetrics(page: Page, log: any[], afterCount: number, quietMs = 2500, timeoutMs = 90_000): Promise<any> {
  const deadline = Date.now() + timeoutMs
  while (log.length <= afterCount) {
    if (Date.now() > deadline) throw new Error(`no new metrics response arrived within ${timeoutMs}ms (had ${afterCount})`)
    await page.waitForTimeout(250)
  }
  let lastCount = log.length
  let lastChange = Date.now()
  while (Date.now() < deadline) {
    if (log.length !== lastCount) {
      lastCount = log.length
      lastChange = Date.now()
    }
    if (Date.now() - lastChange >= quietMs) return log[log.length - 1]
    await page.waitForTimeout(250)
  }
  throw new Error(`metrics did not settle within ${timeoutMs}ms (saw ${log.length} response(s))`)
}

test.describe('authenticated Farmer real write flows', () => {
  test.skip(!enabled, 'Set REAL_E2E=true, FARMER_REAL_E2E=true and FARMER_REAL_WRITE_E2E=true with FARMER_REAL_E2E_EMAIL/PASSWORD for the dedicated DEMO-FARM-01 Farmer QA identity (backend/scripts/create_farmer_qa_identity.py). No manager credential is reused as a farmer; no production/demo reference data is mutated.')

  test('create, edit and delete fertilizer, irrigation and harvest through the real API', async ({ page }) => {
    test.setTimeout(600_000)
    const marker = `QA-FW2-${Date.now()}`
    const consoleErrors: string[] = []
    const unexpectedApi: string[] = []
    const directBusiness: string[] = []
    const activityPosts: string[] = []
    const metricsLog: any[] = []
    page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()) })
    page.on('request', (r) => {
      const p = new URL(r.url()).pathname
      if (/\/rest\/v1\/(organizations|farms|plots|crop_seasons|activities|carbon_calculations)/.test(p)) directBusiness.push(r.url())
      if (r.method() === 'POST' && /\/crop-seasons\/[^/]+\/activities$/.test(p)) activityPosts.push(p)
    })
    page.on('response', (r) => {
      const p = new URL(r.url()).pathname
      const allowedNoCalc = r.status() === 404 && /\/carbon$/.test(p)
      if (p.startsWith('/v1/') && r.status() >= 400 && !allowedNoCalc) unexpectedApi.push(`${r.status()} ${p}`)
      if (r.status() === 200 && /\/metrics$/.test(p)) r.json().then((body) => metricsLog.push(body)).catch(() => {})
    })

    await page.goto('/login')
    await page.getByLabel('Email').fill(email!)
    await page.getByLabel('Mật khẩu').fill(password!)
    await page.getByRole('button', { name: 'Đăng nhập' }).click()
    await expect(page).toHaveURL(/\/farmer$/)
    await expect(page.getByRole('heading', { name: 'Hôm nay trên ruộng của bạn', level: 1 })).toBeVisible({ timeout: 60_000 })

    await page.getByRole('link', { name: 'Xem vụ' }).click()
    await expect(page.getByRole('tab', { name: 'Nhật ký' })).toBeVisible({ timeout: 60_000 })
    await page.getByRole('tab', { name: 'Nhật ký' }).click()
    await expect(page.getByRole('heading', { name: 'Nhật ký canh tác' })).toBeVisible()
    await expect(page.getByRole('button', { name: '+ Ghi hoạt động' })).toBeVisible({ timeout: 60_000 })

    /* ------------------------------------------------------------- fertilizer */
    await page.getByRole('button', { name: '+ Ghi hoạt động' }).click()
    await page.getByRole('button', { name: 'Bón phân', exact: true }).click()
    await expect(page.getByRole('dialog', { name: 'Bón phân' })).toBeVisible()
    await page.getByLabel('Loại phân').fill(`QA Urê ${marker}`)
    await page.getByLabel(/^Lượng bón/).fill('12')
    await page.getByLabel(/^Ghi chú/).fill(marker)
    await page.getByRole('button', { name: 'Lưu hoạt động' }).click()
    await expect(page.getByRole('dialog', { name: 'Bón phân' })).toHaveCount(0, { timeout: 30_000 })
    await expect(page.getByText('Đã lưu hoạt động.')).toBeVisible()

    let row = page.locator('.act', { hasText: `QA Urê ${marker}` })
    await expect(row).toBeVisible({ timeout: 30_000 })
    await row.click()
    await expect(page.getByRole('dialog')).toContainText(marker)
    await expect(page.getByRole('dialog')).toContainText('12')
    await page.getByRole('button', { name: 'Chỉnh sửa' }).click()
    await expect(page.getByRole('dialog', { name: 'Chỉnh sửa bón phân' })).toBeVisible()
    await page.getByLabel(/^Lượng bón/).fill('18')
    await page.getByRole('button', { name: 'Lưu thay đổi' }).click()
    await expect(page.getByRole('dialog', { name: 'Chỉnh sửa bón phân' })).toHaveCount(0, { timeout: 30_000 })
    await expect(page.getByText('Đã lưu thay đổi.')).toBeVisible()

    row = page.locator('.act', { hasText: `QA Urê ${marker}` })
    await row.click()
    await expect(page.getByRole('dialog')).toContainText('18')
    await page.getByRole('button', { name: 'Xóa hoạt động' }).click()
    await expect(page.getByRole('alertdialog')).toBeVisible()
    await page.getByRole('alertdialog').getByRole('button', { name: 'Xóa' }).click()
    await expect(page.getByRole('alertdialog')).toHaveCount(0, { timeout: 30_000 })
    await expect(page.getByText('Đã xóa hoạt động.')).toBeVisible()
    await expect(page.locator('.act', { hasText: `QA Urê ${marker}` })).toHaveCount(0)

    /* ------------------------------------------------------------- irrigation */
    await page.getByRole('button', { name: '+ Ghi hoạt động' }).click()
    await page.getByRole('button', { name: 'Tưới nước', exact: true }).click()
    await expect(page.getByRole('dialog', { name: 'Ghi tưới nước' })).toBeVisible()
    await page.getByLabel('Hình thức tưới').selectOption('awd')
    // Blank-vs-zero (brief §12): water volume left blank on create.
    await page.getByLabel(/^Ghi chú/).fill(marker)
    await page.getByRole('button', { name: 'Lưu hoạt động' }).click()
    await expect(page.getByRole('dialog', { name: 'Ghi tưới nước' })).toHaveCount(0, { timeout: 30_000 })

    row = lastRowIn(page, 'Nước')
    await expect(row).toBeVisible({ timeout: 30_000 })
    await row.click()
    await expect(page.getByRole('dialog')).toContainText(marker)
    await expect(page.getByRole('dialog').getByText('Lượng nước (m³)')).toBeVisible()
    await expect(page.getByRole('dialog').locator('dd', { hasText: '—' }).first()).toBeVisible()
    await page.getByRole('button', { name: 'Chỉnh sửa' }).click()
    await expect(page.getByRole('dialog', { name: 'Chỉnh sửa tưới nước' })).toBeVisible()
    await page.getByLabel(/^Lượng nước/).fill('0')
    await page.getByRole('button', { name: 'Lưu thay đổi' }).click()
    await expect(page.getByRole('dialog', { name: 'Chỉnh sửa tưới nước' })).toHaveCount(0, { timeout: 30_000 })

    row = lastRowIn(page, 'Nước')
    await row.click()
    // An explicit 0 persists as 0, distinct from the earlier blank/unknown state.
    await expect(page.getByRole('dialog')).toContainText(marker)
    const irrigationSnapshot = await page.getByRole('dialog').innerText()
    expect(irrigationSnapshot).toMatch(/\b0\b/)
    // Deleting the irrigation row also triggers a metrics reload (FarmerSeason
    // wires onMutated to both activities.reload() and metrics.reload()) — use
    // its settled value as the harvest section's "before" baseline instead of
    // a tab click, which reads cached state and triggers no new fetch at all.
    let beforeCount = metricsLog.length
    await page.getByRole('button', { name: 'Xóa hoạt động' }).click()
    await page.getByRole('alertdialog').getByRole('button', { name: 'Xóa' }).click()
    await expect(page.getByRole('alertdialog')).toHaveCount(0, { timeout: 30_000 })
    await expect(page.locator('.act', { hasText: marker })).toHaveCount(0)
    const metricsBefore = await waitForNewMetrics(page, metricsLog, beforeCount)

    /* --------------------------------------------------------------- harvest */
    await page.getByRole('button', { name: '+ Ghi hoạt động' }).click()
    await page.getByRole('button', { name: 'Thu hoạch', exact: true }).click()
    await expect(page.getByRole('dialog', { name: 'Ghi thu hoạch' })).toBeVisible()
    await page.getByLabel(/^Sản lượng thu hoạch/).fill('5')
    await page.getByLabel(/^Ghi chú/).fill(marker)
    beforeCount = metricsLog.length
    await page.getByRole('button', { name: 'Lưu thu hoạch' }).click()
    await expect(page.getByRole('dialog', { name: 'Ghi thu hoạch' })).toHaveCount(0, { timeout: 30_000 })
    // Harvest confirmation copy (brief §14) — never claims Carbon updated automatically.
    await expect(page.getByText(/Đã ghi nhận thu hoạch 5 kg\. Các chỉ số hiệu suất đã được cập nhật\./)).toBeVisible()
    const metricsAfterCreate = await waitForNewMetrics(page, metricsLog, beforeCount)
    expect(metricsAfterCreate.yield_kg - metricsBefore.yield_kg).toBeCloseTo(5, 5)

    row = lastRowIn(page, 'Thu hoạch')
    await expect(row).toBeVisible({ timeout: 30_000 })
    await row.click()
    await expect(page.getByRole('dialog')).toContainText(marker)
    await expect(page.getByRole('dialog')).toContainText('5')
    await page.getByRole('button', { name: 'Chỉnh sửa' }).click()
    await expect(page.getByRole('dialog', { name: 'Chỉnh sửa thu hoạch' })).toBeVisible()
    await page.getByLabel(/^Sản lượng thu hoạch/).fill('8')
    beforeCount = metricsLog.length
    await page.getByRole('button', { name: 'Lưu thay đổi' }).click()
    await expect(page.getByRole('dialog', { name: 'Chỉnh sửa thu hoạch' })).toHaveCount(0, { timeout: 30_000 })
    const metricsAfterEdit = await waitForNewMetrics(page, metricsLog, beforeCount)
    // Performance changes according to the backend response only (brief §21) —
    // no ratio is recomputed client-side; this compares two raw backend replies.
    expect(metricsAfterEdit.yield_kg - metricsBefore.yield_kg).toBeCloseTo(8, 5)

    row = lastRowIn(page, 'Thu hoạch')
    await row.click()
    await expect(page.getByRole('dialog')).toContainText(marker)
    await expect(page.getByRole('dialog')).toContainText('8')
    await page.getByRole('button', { name: 'Xóa hoạt động' }).click()
    await expect(page.getByRole('alertdialog')).toContainText('trên mỗi kg sản phẩm')
    beforeCount = metricsLog.length
    await page.getByRole('alertdialog').getByRole('button', { name: 'Xóa' }).click()
    await expect(page.getByRole('alertdialog')).toHaveCount(0, { timeout: 30_000 })
    const metricsAfterDelete = await waitForNewMetrics(page, metricsLog, beforeCount)
    expect(metricsAfterDelete.yield_kg ?? 0).toBeCloseTo(metricsBefore.yield_kg ?? 0, 5)
    await expect(page.locator('.act', { hasText: marker })).toHaveCount(0)

    /* ------------------------------------------------------------ regression */
    expect(activityPosts.length).toBeGreaterThanOrEqual(3) // fertilizer + irrigation + harvest, one POST per Save click
    expect(unexpectedApi).toEqual([])
    expect(directBusiness).toEqual([])
    expect(consoleErrors.filter((line) => !/Failed to load resource.*\b404\b/i.test(line))).toEqual([])
  })
})
