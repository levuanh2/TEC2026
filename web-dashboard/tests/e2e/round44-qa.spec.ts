import { expect, test } from './fixtures'

/* Round 4.4 mock gate — the pieces that do not need a real tenant: no
 * Fraunces download, one sans face on headings and body, no developer
 * vocabulary on any audited route, and no horizontal overflow. The partial-
 * harvest fixture itself is exercised on the real page component in
 * src/pages/round44.dom.test.tsx and on real data in round44-real.spec.ts
 * (mock mode has no organisation, so /performance is an empty state here). */

const ROUTES = ['/farmer', '/farmer/performance', '/farmer/carbon', '/dashboard', '/performance', '/seasons', '/data-gaps', '/carbon']
const DEV_TERMS = /\b(endpoint|API|payload|batch|null|undefined|NaN|yield_kg|data_status|dataStatus|farm_id|season_id)\b/

test('no Fraunces request; headings and body are Be Vietnam Pro', async ({ page }) => {
  const fonts: string[] = []
  page.on('request', (r) => { if (/fonts\.(googleapis|gstatic)\.com/.test(r.url())) fonts.push(r.url()) })
  for (const path of ['/farmer', '/dashboard']) {
    await page.goto(path)
    await expect(page.locator('main h1').first()).toBeVisible()
    await page.waitForLoadState('networkidle')
    const [head, body] = await page.evaluate(() => [getComputedStyle(document.querySelector('main h1')!).fontFamily, getComputedStyle(document.body).fontFamily])
    expect(head).toMatch(/^"?Be Vietnam Pro/)
    expect(body).toMatch(/^"?Be Vietnam Pro/)
  }
  expect(fonts.filter((u) => /Fraunces/i.test(u))).toEqual([])
})

for (const path of ROUTES) {
  test(`${path}: no developer vocabulary in the rendered workspace`, async ({ page }) => {
    await page.setViewportSize({ width: 1348, height: 900 })
    await page.goto(path)
    await expect(page.locator('main h1').first()).toBeVisible()
    await page.waitForLoadState('networkidle')
    expect(await page.locator('main h1').count()).toBe(1)
    const text = await page.locator('main').innerText()
    expect(text.match(DEV_TERMS)?.[0] ?? null).toBeNull()
    // Management aggregates several seasons per farm, where "Chưa ghi thu
    // hoạch" was false for a partly harvested farm. On the Farmer pages it
    // describes one season and stays.
    if (!path.startsWith('/farmer')) expect(text).not.toContain('Chưa ghi thu hoạch')
  })
}

for (const vw of [1440, 1348, 1024, 768, 390]) {
  test(`/performance at ${vw}px: no horizontal overflow`, async ({ page }) => {
    await page.setViewportSize({ width: vw, height: 900 })
    await page.goto('/performance')
    await expect(page.locator('main h1').first()).toBeVisible()
    await page.waitForLoadState('networkidle')
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0)
  })
}
