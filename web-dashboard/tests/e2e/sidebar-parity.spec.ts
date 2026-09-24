import { expect, test, type Page } from '@playwright/test'
import { isInstitutionalGreen } from './round41-helpers'

/* Round 4.2 — Farmer and Management render one sidebar (components/Sidebar.tsx)
 * on one width token. Measured on the mock tenant, where the Management shell
 * shows the unassigned viewer's two destinations: the chrome under test —
 * width, padding, row grid, brand, marker, footer — does not depend on how
 * many rows there are. */

const FARMER_SIDE = '.fw-shell > aside.sidebar'
const MANAGER_SIDE = '.shell > aside.sidebar'
const DESKTOP = [1440, 1363, 1280, 1024]
const TOKEN_W = (vw: number) => (vw <= 1024 ? 216 : 240)
const LONG_EMAIL = 'qa-farmer-fw1@agricarbon-demo.local'

const FARMER_ROUTES = [
  '/farmer', '/farmer/journal', '/farmer/farms', '/farmer/performance', '/farmer/carbon', '/farmer/account',
  '/farmer/plots/plot-demo-01', '/farmer/crop-seasons/crop-demo-01', '/farmer/crop-seasons/crop-demo-01/journal',
  '/farmer/crop-seasons/crop-demo-01/performance', '/farmer/crop-seasons/crop-demo-01/carbon',
]
const MANAGER_ROUTES = ['/dashboard', '/seasons', '/data-gaps', '/carbon', '/farms', '/mrv']

interface Geometry {
  side: { x: number; w: number; right: number; h: number }
  padL: number; padR: number
  brand: { x: number; y: number; fs: string; tagFs: string; tagY: number; tagLines: number }
  rows: { label: string; x: number; right: number; h: number; icoX: number; textX: number }[]
  footInside: boolean; footH: number
  mainLeft: number; mainRight: number; vw: number; docOverflow: number
  active: { weight: number; bg: string; marker: string; markerW: number; markerH: number } | null
}

function geometry(page: Page, side: string): Promise<Geometry> {
  return page.evaluate((sel) => {
    const aside = document.querySelector<HTMLElement>(sel)!
    const s = aside.getBoundingClientRect()
    const cs = getComputedStyle(aside)
    const brandEl = aside.querySelector<HTMLElement>('.brand')!
    const word = document.createRange(); word.selectNodeContents(brandEl.firstChild!)
    const wr = word.getBoundingClientRect()
    const tag = brandEl.querySelector('small')!
    const tr = tag.getBoundingClientRect()
    const rows = [...aside.querySelectorAll<HTMLAnchorElement>('nav a')].map((a) => {
      const r = a.getBoundingClientRect()
      const ico = a.querySelector('.nav__ico')!.getBoundingClientRect()
      const range = document.createRange()
      range.selectNodeContents([...a.childNodes].filter((n) => n.nodeType === 3).pop()!)
      return { label: a.textContent!.trim(), x: r.x, right: r.right, h: r.height, icoX: ico.x - r.x, textX: range.getBoundingClientRect().x - r.x }
    })
    const foot = aside.querySelector('.sidebar__foot')!.getBoundingClientRect()
    const inside = (r: DOMRect) => r.left >= s.left - 0.5 && r.right <= s.right + 0.5 && r.top >= s.top - 0.5 && r.bottom <= s.bottom + 0.5
    const footInside = inside(foot) && [...aside.querySelectorAll('.sidebar__foot *')].every((el) => inside(el.getBoundingClientRect()))
    const main = (aside.parentElement!.querySelector('.main, .fw-main') as HTMLElement).getBoundingClientRect()
    const cur = aside.querySelector<HTMLElement>('nav a[aria-current="page"]')
    let active = null
    if (cur) {
      const c = getComputedStyle(cur); const m = getComputedStyle(cur, '::before')
      active = { weight: Number(c.fontWeight), bg: c.backgroundColor, marker: m.backgroundColor, markerW: parseFloat(m.width), markerH: parseFloat(m.height) }
    }
    const vw = document.documentElement.clientWidth
    return {
      side: { x: s.x, w: s.width, right: s.right, h: s.height },
      padL: parseFloat(cs.paddingLeft), padR: parseFloat(cs.paddingRight),
      brand: { x: wr.x - s.x, y: wr.y - s.y, fs: getComputedStyle(brandEl).fontSize, tagFs: getComputedStyle(tag).fontSize, tagY: tr.y - s.y, tagLines: Math.round(tr.height / parseFloat(getComputedStyle(tag).lineHeight)) },
      rows, footInside, footH: foot.height,
      mainLeft: main.left, mainRight: main.right, vw, docOverflow: document.documentElement.scrollWidth - vw,
      active,
    }
  }, side)
}

async function open(page: Page, path: string, side: string) {
  await page.goto(path)
  await expect(page.locator(side)).toBeVisible()
  await expect(page.locator(`${side} nav a`).first()).toBeVisible()
}

for (const vw of DESKTOP) {
  test(`desktop ${vw}px: Farmer and Management sidebars share width, grid, marker and footer`, async ({ page }) => {
    await page.setViewportSize({ width: vw, height: 900 })
    await open(page, '/farmer', FARMER_SIDE)
    const f = await geometry(page, FARMER_SIDE)
    await open(page, '/dashboard', MANAGER_SIDE)
    const m = await geometry(page, MANAGER_SIDE)

    // Width: one token, both roles, within 1px.
    expect(Math.abs(f.side.w - m.side.w), `farmer ${f.side.w} vs manager ${m.side.w}`).toBeLessThanOrEqual(1)
    expect(Math.abs(f.side.w - TOKEN_W(vw))).toBeLessThanOrEqual(1)
    // Same inner grid.
    expect(f.padL).toBe(m.padL); expect(f.padR).toBe(m.padR)
    // Brand: same wordmark position and size, same tagline type and offset.
    // Only the tagline's length is the role's — Management's may wrap at
    // 216px; the Farmer "Nông hộ" never does.
    expect(Math.abs(f.brand.x - m.brand.x)).toBeLessThanOrEqual(0.5)
    expect(Math.abs(f.brand.y - m.brand.y)).toBeLessThanOrEqual(0.5)
    expect(Math.abs(f.brand.tagY - m.brand.tagY)).toBeLessThanOrEqual(0.5)
    expect([f.brand.fs, f.brand.tagFs]).toEqual([m.brand.fs, m.brand.tagFs])
    expect(f.brand.tagLines).toBe(1)
    expect(f.brand.tagY - f.brand.y, 'wordmark and role label on separate lines').toBeGreaterThanOrEqual(20)
    for (const g of [f, m]) {
      for (const r of g.rows) {
        expect(r.h, `${r.label} row height`).toBeGreaterThanOrEqual(40)
        expect(r.x, `${r.label} inside left`).toBeGreaterThanOrEqual(g.side.x + g.padL - 0.5)
        expect(r.right, `${r.label} inside right`).toBeLessThanOrEqual(g.side.right - g.padR + 0.5)
        expect(Math.abs(r.icoX - m.rows[0].icoX), `${r.label} icon column`).toBeLessThanOrEqual(1)
        expect(Math.abs(r.textX - m.rows[0].textX), `${r.label} label column`).toBeLessThanOrEqual(1)
      }
      expect(g.footInside, 'footer wholly inside the sidebar').toBe(true)
      // Workspace starts where the rail ends and stays in the viewport.
      expect(Math.abs(g.mainLeft - g.side.right)).toBeLessThanOrEqual(1)
      expect(g.mainRight).toBeLessThanOrEqual(g.vw + 0.5)
      expect(g.docOverflow).toBeLessThanOrEqual(0)
    }
    expect(f.rows.map((r) => r.label)).toEqual(['Tổng quan', 'Nhật ký', 'Ruộng / Vụ mùa', 'Hiệu suất', 'Carbon', 'Tôi'])
    // Active row: fill + marker bar + weight — never colour alone — and the
    // same pattern in both roles.
    for (const g of [f, m]) {
      expect(g.active).not.toBeNull()
      expect(g.active!.weight).toBeGreaterThanOrEqual(700)
      expect(g.active!.bg).not.toBe('rgba(0, 0, 0, 0)')
      expect(g.active!.markerW).toBeGreaterThanOrEqual(3)
      expect(g.active!.markerH).toBeGreaterThanOrEqual(20)
    }
    expect(f.active).toEqual(m.active)
  })
}

test('a long address wraps after "@", stays inside the rail and keeps its full text', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 })
  for (const [path, side] of [['/farmer', FARMER_SIDE], ['/dashboard', MANAGER_SIDE]] as const) {
    await open(page, path, side)
    // Layout stress on the real component's markup: the mock tenant has no
    // signed-in address, so write the QA farmer's in the way AccountName does.
    const name = page.locator(`${side} .sidebar__name`)
    await name.evaluate((el, email) => {
      const at = email.indexOf('@')
      el.textContent = ''
      el.append(email.slice(0, at + 1), document.createElement('wbr'), email.slice(at + 1))
      el.setAttribute('title', email)
    }, LONG_EMAIL)
    const g = await geometry(page, side)
    expect(g.footInside, `${path} footer inside`).toBe(true)
    const box = await name.evaluate((el) => {
      const r = el.getBoundingClientRect(); const lh = parseFloat(getComputedStyle(el).lineHeight)
      return { lines: Math.round(r.height / lh), clipped: el.scrollHeight > el.clientHeight + 1 }
    })
    expect(box.lines, `${path}: local part and domain on two lines`).toBe(2)
    expect(box.clipped, `${path}: nothing hidden at 1280px`).toBe(false)
    await expect(name).toHaveText(LONG_EMAIL)
    await expect(name).toHaveAttribute('title', LONG_EMAIL)
  }
  // The Farmer block is one link whose accessible name is the whole identity.
  const acct = page.locator(`${FARMER_SIDE} .sidebar__acct`)
  await page.goto('/farmer')
  await expect(acct).toHaveAccessibleName(/^Tài khoản của /)
  expect((await acct.boundingBox())!.height).toBeGreaterThanOrEqual(44)
})

test('keyboard: Farmer Tab order walks brand, all six destinations, then the account; ring is the light marker', async ({ page }) => {
  await page.setViewportSize({ width: 1363, height: 900 })
  await open(page, '/farmer/carbon', FARMER_SIDE)
  await page.keyboard.press('Tab')
  await expect(page.getByRole('link', { name: 'Bỏ qua điều hướng, tới nội dung chính' })).toBeFocused()
  const seen: string[] = []
  for (let i = 0; i < 8; i++) {
    await page.keyboard.press('Tab')
    const f = await page.evaluate(() => {
      const a = document.activeElement as HTMLElement; const c = getComputedStyle(a)
      return { name: a.getAttribute('aria-label') ?? a.textContent!.trim(), inSide: !!a.closest('aside.sidebar'), ring: c.outlineStyle, w: parseFloat(c.outlineWidth), color: c.outlineColor }
    })
    expect(f.inSide).toBe(true)
    expect(f.ring).toBe('solid'); expect(f.w).toBeGreaterThanOrEqual(2)
    // Light marker, not the workspace blue (~2:1 on forest) and not forest.
    expect(isInstitutionalGreen(f.color)).toBe(false)
    expect(f.color).toMatch(/oklch\(0\.78 0\.16 140\)/)
    seen.push(f.name)
  }
  expect(seen.slice(0, 7)).toEqual(['AgriCarbonNông hộ', 'Tổng quan', 'Nhật ký', 'Ruộng / Vụ mùa', 'Hiệu suất', 'Carbon', 'Tôi'])
  expect(seen[7]).toMatch(/^Tài khoản của /)
})

test('mobile 390 / tablet 768: Farmer keeps its bottom bar, no rail, no overflow; the CTA stays in view', async ({ page }) => {
  for (const vw of [390, 768]) {
    await page.setViewportSize({ width: vw, height: 844 })
    await page.goto('/farmer/carbon')
    await expect(page.locator('.fw-bottom')).toBeVisible()
    await expect(page.locator(FARMER_SIDE)).toBeHidden()
    const tabs = page.locator('.fw-bottom a')
    await expect(tabs).toHaveCount(6)
    for (const box of await tabs.evaluateAll((els) => els.map((e) => e.getBoundingClientRect().toJSON()))) {
      expect(box.left).toBeGreaterThanOrEqual(0); expect(box.right).toBeLessThanOrEqual(vw + 0.5)
    }
    await expect(page.locator('.fw-bottom a[aria-current="page"]')).toHaveText('Carbon')
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0)
    await page.goto('/farmer')
    const cta = page.locator('main').getByRole('button', { name: 'Ghi hoạt động' }).first()
    await expect(cta).toBeInViewport()
  }
})

test('Management drawer ≤768px: closed, its links are out of the tab order; open, they are reachable', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/dashboard')
  const menu = page.getByRole('button', { name: 'Mở menu' })
  await expect(menu).toHaveAttribute('aria-expanded', 'false')
  await page.keyboard.press('Tab') // skip link
  await page.keyboard.press('Tab')
  await expect(menu).toBeFocused()
  await menu.click()
  await expect(menu).toHaveAttribute('aria-expanded', 'true')
  const first = page.locator(`${MANAGER_SIDE} nav a`).first()
  await expect(first).toBeInViewport()
  await first.focus()
  await expect(first).toBeFocused()
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0)
})

for (const vw of [1363, 1024, 390]) {
  test(`every Farmer route at ${vw}px: sidebar on token (or hidden on phones), no horizontal overflow, no app errors`, async ({ page }) => {
    await page.setViewportSize({ width: vw, height: 900 })
    const errors: string[] = []
    page.on('pageerror', (e) => errors.push(String(e)))
    for (const path of FARMER_ROUTES) {
      await page.goto(path)
      await expect(page.locator('main h1').first()).toBeVisible()
      if (vw > 768) {
        const w = await page.locator(FARMER_SIDE).evaluate((el) => el.getBoundingClientRect().width)
        expect(Math.abs(w - TOKEN_W(vw)), path).toBeLessThanOrEqual(1)
      } else {
        await expect(page.locator(FARMER_SIDE)).toBeHidden()
      }
      const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
      expect(over, `${path} overflow`).toBeLessThanOrEqual(0)
    }
    expect(errors).toEqual([])
  })
}

for (const vw of [1363, 1024]) {
  test(`Management routes at ${vw}px keep the same rail and no overflow`, async ({ page }) => {
    await page.setViewportSize({ width: vw, height: 900 })
    const errors: string[] = []
    page.on('pageerror', (e) => errors.push(String(e)))
    for (const path of MANAGER_ROUTES) {
      await page.goto(path)
      await expect(page.locator('main h1').first()).toBeVisible()
      const w = await page.locator(MANAGER_SIDE).evaluate((el) => el.getBoundingClientRect().width)
      expect(Math.abs(w - TOKEN_W(vw)), path).toBeLessThanOrEqual(1)
      const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
      expect(over, `${path} overflow`).toBeLessThanOrEqual(0)
      const clipped = await page.locator(`${MANAGER_SIDE} nav a`).evaluateAll((els) => els.filter((a) => a.scrollWidth > a.clientWidth).map((a) => a.textContent))
      expect(clipped, `${path} nav labels clipped`).toEqual([])
    }
    expect(errors).toEqual([])
  })
}
