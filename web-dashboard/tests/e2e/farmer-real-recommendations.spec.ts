import { expect, test } from '@playwright/test'

// M05 real Farmer recommendations QA (brief §B29-B30). REAL CO2e is
// currently blocked (missing gwp.ch4 — docs/CARBON_METHOD.md OI-05), so the
// AWD optimization rule is expected to be suppressed for every real season
// today; a data-completeness nudge or the honest empty state are BOTH valid
// PASS outcomes here — this test asserts truthful behavior, not a specific
// non-empty result (never seeds a fake recommendation to make it look
// populated).
const email = process.env.FARMER_REAL_E2E_EMAIL
const password = process.env.FARMER_REAL_E2E_PASSWORD
const enabled = process.env.REAL_E2E === 'true' && process.env.FARMER_REAL_E2E === 'true' && process.env.FARMER_REAL_RECOMMENDATIONS_E2E === 'true' && Boolean(email && password)

test.describe('authenticated Farmer real recommendations flow', () => {
  test.skip(!enabled, 'Set REAL_E2E=true, FARMER_REAL_E2E=true and FARMER_REAL_RECOMMENDATIONS_E2E=true with a Farmer QA identity (FARMER_REAL_E2E_EMAIL/PASSWORD).')

  test('recommendations render truthfully against the real API', async ({ page }) => {
    test.setTimeout(300_000)
    const consoleErrors: string[] = []
    const unexpectedApi: string[] = []
    const directBusiness: string[] = []
    let generateResponseBody: any = null
    const generateRequests: string[] = []
    page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()) })
    page.on('request', (r) => {
      if (r.method() === 'POST' && /\/recommendations\/generate$/.test(new URL(r.url()).pathname)) generateRequests.push(r.url())
    })
    page.on('request', (r) => {
      const p = new URL(r.url()).pathname
      if (/\/rest\/v1\/(organizations|farms|plots|crop_seasons|activities|carbon_calculations|season_recommendations)/.test(p)) directBusiness.push(r.url())
    })
    page.on('response', (r) => {
      const p = new URL(r.url()).pathname
      const allowedNoCalc = r.status() === 404 && /\/carbon$/.test(p)
      if (p.startsWith('/v1/') && r.status() >= 400 && !allowedNoCalc) unexpectedApi.push(`${r.status()} ${p}`)
    })
    page.on('response', async (r) => {
      if (/\/recommendations\/generate$/.test(new URL(r.url()).pathname) && r.status() === 200) {
        generateResponseBody = await r.json().catch(() => null)
      }
    })

    await page.goto('/login')
    await page.getByLabel('Email').fill(email!)
    await page.getByLabel('Mật khẩu').fill(password!)
    await page.getByRole('button', { name: 'Đăng nhập' }).click()
    await expect(page).toHaveURL(/\/farmer$/)
    await expect(page.getByRole('heading', { name: 'Hôm nay trên ruộng của bạn', level: 1 })).toBeVisible({ timeout: 60_000 })

    // Recommendations live on the season page since the hybrid redesign;
    // Home links the season as "Xem chi tiết vụ".
    await page.getByRole('link', { name: 'Xem chi tiết vụ' }).click()
    const seasonTitle = page.getByRole('heading', { level: 1 })
    await expect(page.getByRole('tab', { name: 'Tổng quan' })).toBeVisible({ timeout: 60_000 })
    const section = page.locator('section.fw-section', { has: page.getByRole('heading', { name: 'Khuyến nghị' }) })
    await expect(section).toBeVisible({ timeout: 60_000 })
    // Either a truthful empty state or real cards — never a fabricated number.
    await expect(section.getByText('Chưa có khuyến nghị định lượng').or(section.locator('.recommendation-card').first())).toBeVisible({ timeout: 60_000 })

    // Generation is NOT part of loading the page. Measured at 7.3-9.5s and 33
    // Supabase round trips, it was ~7s of Home's time to full content; the page
    // now renders what is stored and regenerates only on request or when the
    // stored set is actually out of date.
    expect(generateRequests, 'a page load must not trigger recommendation generation').toEqual([])

    // Explicit refresh: the section updates, the rest of the page keeps working
    // while it runs, and one click means exactly one generation run.
    await section.getByRole('button', { name: 'Cập nhật khuyến nghị' }).click()
    await expect(seasonTitle).toBeVisible()
    await expect(page.getByRole('button', { name: 'Ghi hoạt động' }).first()).toBeEnabled()
    await expect.poll(() => generateResponseBody, { timeout: 120_000 }).not.toBeNull()
    expect(generateRequests, 'one click must not fan out into several runs').toHaveLength(1)

    const items: any[] = generateResponseBody.items
    // REAL CO2e is blocked today -> the AWD optimization rule must not have
    // produced a fabricated quantified carbon result for this real season.
    for (const item of items) {
      if (item.type === 'optimization' && item.impact_status === 'available') {
        expect(item.co2e_total_kg_delta).toBeGreaterThan(0)
      }
      if (item.type === 'optimization' && item.impact_status === 'unavailable') {
        expect(item.co2e_total_kg_delta).toBeNull()
      }
      if (item.type === 'data_task') {
        expect(item.co2e_total_kg_delta).toBeNull()
        expect(item.impact_status).toBe('unavailable')
      }
    }

    const cards = section.locator('.recommendation-card')
    const cardCount = await cards.count()
    if (cardCount > 0) {
      const first = cards.first()
      const title = await first.locator('h3').innerText()
      await first.getByRole('button', { name: 'Đã hiểu' }).click()
      await expect(first).toHaveCount(0, { timeout: 30_000 })
      // Accepting a genuine, real recommendation is an honest, low-stakes,
      // non-destructive interaction (only a status/timestamp on that one
      // rule row) — not fabricated QA data, so there is nothing to delete
      // afterward; regeneration will keep evaluating the rule normally for
      // any future data change.
      console.log(`Accepted real recommendation: ${title}`)
    }

    expect(unexpectedApi).toEqual([])
    expect(directBusiness).toEqual([])
    expect(consoleErrors.filter((line) => !/Failed to load resource.*\b404\b/i.test(line))).toEqual([])
  })
})
