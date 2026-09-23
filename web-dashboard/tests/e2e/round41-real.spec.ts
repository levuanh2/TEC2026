import { expect, test, type Page } from '@playwright/test'
import { isInstitutionalGreen, measureRowActions } from './round41-helpers'

/* Round 4.1 real-data gates: /carbon action geometry at the viewport that
 * reproduced the clipping (1363px) and four others, the card layout on tablet
 * and phone, brand green on real pages, and the quick-fix/demo-marker sheet.
 *
 * Skips itself without REDESIGN_* credentials. Never saves anything. Run with
 *   npx playwright test --config playwright.real.config.ts tests/e2e/round41-real.spec.ts
 * (trace off in that config: a trace records fill()). */

const FARMER = { email: process.env.REDESIGN_FARMER_EMAIL, password: process.env.REDESIGN_FARMER_PASSWORD }
const MANAGER = { email: process.env.REDESIGN_MANAGER_EMAIL, password: process.env.REDESIGN_MANAGER_PASSWORD }
const SEASON = process.env.REDESIGN_SEASON_ID ?? '2e63e128-f53d-4f70-9bb4-62b9efc048e3'
const WIDTHS = [1440, 1363, 1280, 768, 390]

async function signIn(page: Page, who: { email?: string; password?: string }) {
  await page.goto('/login')
  await page.getByLabel('Email').fill(who.email!)
  await page.getByLabel('Mật khẩu').fill(who.password!)
  await page.getByRole('button', { name: /Đăng nhập/ }).click()
  await page.waitForURL(/\/(farmer|dashboard)/, { timeout: 120_000 })
}

/** /carbon with every row's readiness read (the list streams in per season). */
async function carbonSettled(page: Page) {
  await page.goto('/carbon')
  await page.waitForFunction(() => document.querySelectorAll('tr[data-carbon-row]').length > 0
    && !document.querySelector('tr[data-carbon-row] .skeleton')
    && !/đang đọc thêm/.test(document.querySelector('.ops-count')?.textContent ?? ''), null, { timeout: 150_000 })
}

test.describe('Round 4.1 — real session', () => {
  test.skip(!FARMER.email || !FARMER.password || !MANAGER.email || !MANAGER.password, 'REDESIGN_* credentials not set')

  test('/carbon: every primary and secondary action is wholly inside its container and the viewport', async ({ page }) => {
    test.setTimeout(300_000)
    await signIn(page, MANAGER)
    await carbonSettled(page)
    const rows = await page.locator('tr[data-carbon-row]').count()
    for (const width of WIDTHS) {
      await page.setViewportSize({ width, height: width < 800 ? 844 : 900 })
      await page.waitForTimeout(400)
      const m = await measureRowActions(page)
      expect(m.wrapOverflow, `${width}px: the table wrapper scrolls sideways`).toBeLessThanOrEqual(0)
      expect(m.docOverflow, `${width}px: the page scrolls sideways`).toBeLessThanOrEqual(0)
      // One detail control per row, and a primary wherever the state allows one.
      expect(m.boxes.filter((b) => b.kind === 'secondary')).toHaveLength(rows)
      expect(m.boxes.filter((b) => b.kind === 'primary').length).toBeGreaterThan(0)
      for (const b of m.boxes) {
        expect(b.w, `${width}px ${b.kind} "${b.name}" width`).toBeGreaterThan(0)
        expect(b.h, `${width}px ${b.kind} "${b.name}" height`).toBeGreaterThan(0)
        expect(b.right, `${width}px ${b.kind} "${b.name}" right edge`).toBeLessThanOrEqual(b.limitRight + 0.5)
        expect(b.left, `${width}px ${b.kind} "${b.name}" left edge`).toBeGreaterThanOrEqual(b.containerLeft - 0.5)
        expect(b.hit, `${width}px ${b.kind} "${b.name}" is covered or clipped`).toBe(true)
        if (width <= 768) expect(b.h, `${width}px touch target`).toBeGreaterThanOrEqual(40)
      }
    }
  })

  test('/seasons and /data-gaps share the table: no sideways scroll, no clipped action at 1363 and 1280px', async ({ page }) => {
    test.setTimeout(300_000)
    await signIn(page, MANAGER)
    for (const route of ['/seasons', '/data-gaps']) {
      await page.setViewportSize({ width: 1440, height: 900 })
      await page.goto(route)
      await page.waitForFunction(() => document.querySelectorAll('tbody tr').length > 0 && !document.querySelector('.ops-table .skeleton')
        && !/đang đọc thêm/.test(document.querySelector('.ops-count')?.textContent ?? ''), null, { timeout: 150_000 })
      for (const width of [1363, 1280]) {
        await page.setViewportSize({ width, height: 900 })
        await page.waitForTimeout(400)
        const wrap = await page.locator('.ops-table__wrap').evaluate((w) => w.scrollWidth - w.clientWidth)
        expect(wrap, `${route} ${width}px wrapper scrolls sideways`).toBeLessThanOrEqual(0)
        const clipped = await page.locator('td.ops-act button, td.ops-act a').evaluateAll((els) => {
          const wr = document.querySelector('.ops-table__wrap')!.getBoundingClientRect()
          return els.filter((el) => { const r = el.getBoundingClientRect(); return r.right > Math.min(wr.right, innerWidth) + 0.5 || r.width === 0 }).length
        })
        expect(clipped, `${route} ${width}px clipped actions`).toBe(0)
      }
    }
  })

  test('/carbon at 1363px: the detail button opens the season, Escape returns focus to it', async ({ page }) => {
    await page.setViewportSize({ width: 1363, height: 900 })
    await signIn(page, MANAGER)
    await carbonSettled(page)
    const detail = page.locator('[data-row-action="secondary"]').first()
    await expect(detail).toHaveAccessibleName(/^Chi tiết vụ /)
    await detail.click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await expect(detail).toBeFocused()
    // The primary is reachable by keyboard and is a real link.
    const primary = page.locator('[data-row-action="primary"]').first()
    await primary.focus()
    await expect(primary).toBeFocused()
    await expect(primary).toHaveAttribute('href', /\/crop-seasons\//)
  })

  test('/carbon at 768 and 390px: rows are cards that keep Nông hộ → Thửa → Vụ', async ({ page }) => {
    await signIn(page, MANAGER)
    await carbonSettled(page)
    for (const width of [768, 390]) {
      await page.setViewportSize({ width, height: 844 })
      await page.waitForTimeout(400)
      await expect(page.locator('.ops-table--carbon thead')).toHaveCSS('position', 'absolute')
      const cards = await page.locator('tr[data-carbon-row]').evaluateAll((trs) => trs.map((tr) => {
        const r = tr.getBoundingClientRect()
        const cell = (label: string) => (tr.querySelector(`td[data-label="${label}"] b`) as HTMLElement | null)
        const shown = (el: HTMLElement | null) => Boolean(el && el.offsetWidth > 0 && el.textContent!.trim())
        return {
          display: getComputedStyle(tr).display, left: r.left, right: r.right,
          farm: shown(cell('Nông hộ')), plot: shown(cell('Thửa')), season: shown(cell('Vụ')),
          state: Boolean(tr.querySelector('.ops-crow__state .ops-badge')),
        }
      }))
      expect(cards.length).toBeGreaterThan(0)
      for (const c of cards) {
        expect(c.display, `${width}px row is a card`).toBe('grid')
        expect(c.left).toBeGreaterThanOrEqual(0)
        expect(c.right).toBeLessThanOrEqual(width)
        expect(c, `${width}px card keeps its context`).toMatchObject({ farm: true, plot: true, season: true, state: true })
      }
    }
  })

  test('brand green stays in the sidebar on real Management and Farmer pages', async ({ browser }) => {
    const m = await browser.newPage()
    await signIn(m, MANAGER)
    await m.goto(`/crop-seasons/${SEASON}/carbon`)
    const tab = m.locator('.tab[aria-current="page"]').first()
    await expect(tab).toBeVisible()
    expect(isInstitutionalGreen(await tab.evaluate((el) => getComputedStyle(el).borderBottomColor))).toBe(false)
    expect(isInstitutionalGreen(await m.locator('.sidebar').evaluate((el) => getComputedStyle(el).backgroundColor))).toBe(true)
    const cta = m.locator('main .btn:not(.btn--ghost):not(.btn--quiet)').first()
    if (await cta.count()) expect(isInstitutionalGreen(await cta.evaluate((el) => getComputedStyle(el).backgroundColor))).toBe(false)
    await m.close()

    const f = await browser.newPage()
    await signIn(f, FARMER)
    const home = f.locator('main .fw-btn:not(.fw-btn--ghost):not(.fw-btn--soft)').first()
    await expect(home).toBeVisible({ timeout: 60_000 })
    expect(isInstitutionalGreen(await home.evaluate((el) => getComputedStyle(el).backgroundColor))).toBe(false)
    expect(isInstitutionalGreen(await f.locator('.fw-side').evaluate((el) => getComputedStyle(el).backgroundColor))).toBe(true)
    await f.close()
  })

  test('quick-fix: -1 blocks the save at the button, decimals with , and . are accepted, demo marker is a badge', async ({ page }) => {
    await signIn(page, FARMER)
    const writes: string[] = []
    page.on('request', (r) => { if (/\/v1\/activities\//.test(r.url()) && r.method() !== 'GET') writes.push(`${r.method()} ${r.url()}`) })
    await page.goto('/farmer/carbon')
    const fix = page.getByRole('button', { name: /Sửa ngay/ }).first()
    await expect(fix).toBeVisible({ timeout: 90_000 })
    await fix.click()
    const sheet = page.getByRole('dialog')
    const days = sheet.getByLabel(/Số ngày trước khi làm đất/)
    const save = sheet.getByRole('button', { name: 'Lưu thay đổi' })

    await days.fill('-1')
    await expect(days).toHaveAttribute('aria-invalid', 'true')
    const errId = (await days.getAttribute('aria-describedby'))!.split(' ')[0]
    await expect(page.locator(`[id="${errId}"]`)).toContainText('âm')
    await expect(save).toHaveAttribute('aria-disabled', 'true')
    const whyId = await save.getAttribute('aria-describedby')
    await expect(page.locator(`[id="${whyId}"]`)).toContainText('Chưa lưu được')
    // aria-disabled, not disabled: Playwright's actionability check refuses it,
    // so force the click — the point is that a real click writes nothing.
    await save.click({ force: true })
    await page.waitForTimeout(800)
    expect(writes, 'an invalid quick-fix reached the API').toEqual([])

    const dry = sheet.getByLabel(/Tỷ lệ chất khô của rơm/)
    for (const typed of ['0,85', '0.85']) {
      await dry.fill(typed)
      await expect(dry).not.toHaveAttribute('aria-invalid', 'true')
    }
    await days.fill('14')
    await expect(save).not.toHaveAttribute('aria-disabled', 'true')

    // Seeded straw record: the marker is a badge, the note box holds only the farmer's words.
    const marker = sheet.getByTestId('demo-marker')
    if (await marker.count()) {
      await expect(marker).toContainText('Dữ liệu minh họa')
      await expect(sheet.getByLabel(/^Ghi chú/)).not.toHaveValue(/SYNTHETIC/)
    }
    await expect(sheet).not.toContainText('SYNTHETIC')

    await sheet.getByRole('button', { name: 'Hủy' }).click()
    expect(writes, 'the gate saved something').toEqual([])
  })
})
