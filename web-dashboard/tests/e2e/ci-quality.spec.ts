import { axe, blocking } from './axe-helper'
import { expect, test, type Page } from './fixtures'

/* CI quality gates on the key Farmer and Management screens (mock data):
 *   - axe (WCAG 2.1 A/AA): zero serious or critical violations; moderate and
 *     minor ones are attached to the report, not failed on (yet);
 *   - no horizontal document overflow at 390 / 768 / 1024 / 1440 px -- the
 *     layout regressions this project has actually shipped before;
 *   - console errors, page errors, failed requests and 5xx fail through the
 *     page-health fixture in ./fixtures.ts. */
const SCREENS = [
  { name: 'Farmer Home', path: '/farmer' },
  { name: 'Farmer Journal', path: '/farmer/journal' },
  { name: 'Farmer Carbon', path: '/farmer/carbon' },
  { name: 'Management Overview', path: '/dashboard' },
  { name: 'Management Seasons', path: '/seasons' },
  { name: 'Farmer account provisioning', path: '/accounts/farmers/new' },
]
const WIDTHS = [390, 768, 1024, 1440]

async function open(page: Page, path: string) {
  await page.goto(path)
  await page.waitForLoadState('networkidle')
  await expect(page.locator('main').first()).toBeVisible()
}

for (const screen of SCREENS) {
  test(`a11y: ${screen.name} has no serious or critical axe violation`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 1440, height: 900 })
    await open(page, screen.path)
    const violations = await axe(page)
    const minor = violations.filter((v) => !blocking([v]).length)
    if (minor.length) {
      await testInfo.attach('axe-moderate-minor.json', { body: JSON.stringify(minor, null, 2), contentType: 'application/json' })
    }
    expect(blocking(violations), `serious/critical axe violations on ${screen.path}`).toEqual([])
  })

  test(`layout: ${screen.name} has no horizontal overflow at ${WIDTHS.join('/')}px`, async ({ page }) => {
    const overflowing: string[] = []
    for (const width of WIDTHS) {
      await page.setViewportSize({ width, height: 900 })
      await open(page, screen.path)
      const { scroll, client } = await page.evaluate(() => ({
        scroll: document.documentElement.scrollWidth,
        client: document.documentElement.clientWidth,
      }))
      if (scroll > client + 1) overflowing.push(`${width}px: scrollWidth ${scroll} > ${client}`)
    }
    expect(overflowing, `horizontal overflow on ${screen.path}`).toEqual([])
  })
}
