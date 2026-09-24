import { expect, test, type Browser, type Page } from '@playwright/test'
import fs from 'node:fs'
import { isInstitutionalGreen } from './round41-helpers'

/* Round 4.2 real-data gate: the shared sidebar on a real Farmer and a real
 * Manager session — hosted Supabase through the local FastAPI.
 *
 * Credentials come from REDESIGN_* in the environment, never from this file;
 * the spec skips itself without them. It reads only: the one mutation-free
 * interaction it makes is signing out at the very end. Run with
 *   REAL_E2E=true npx playwright test --config playwright.real.config.ts tests/e2e/sidebar-parity-real.spec.ts
 * (trace off in that config: a trace records fill()). Screenshots go to the
 * gitignored .qa-screenshots/round4-2/real/. */

const FARMER = { email: process.env.REDESIGN_FARMER_EMAIL, password: process.env.REDESIGN_FARMER_PASSWORD }
const MANAGER = { email: process.env.REDESIGN_MANAGER_EMAIL, password: process.env.REDESIGN_MANAGER_PASSWORD }
const SEASON = process.env.REDESIGN_SEASON_ID ?? '2e63e128-f53d-4f70-9bb4-62b9efc048e3'
const OUT = '.qa-screenshots/round4-2/real'
const VIEWPORTS = [1440, 1363, 1280, 1024, 768, 390]
const TOKEN_W = (vw: number) => (vw <= 1024 ? 216 : 240)
const heightFor = (vw: number) => (vw <= 390 ? 844 : vw <= 768 ? 1024 : 900)
const MANAGER_ROUTES = ['/dashboard', '/seasons', '/data-gaps', '/carbon', '/farms', '/mrv']

test.describe.configure({ mode: 'serial' })
test.skip(!FARMER.email || !FARMER.password || !MANAGER.email || !MANAGER.password, 'REDESIGN_* credentials not set')

/** Sidebar width per role per viewport, compared across roles at the end. */
const widths: Record<string, Record<number, number[]>> = { farmer: {}, manager: {} }

async function signIn(page: Page, who: { email?: string; password?: string }) {
  await page.goto('/login')
  await page.getByLabel('Email').fill(who.email!)
  await page.getByLabel('Mật khẩu').fill(who.password!)
  await page.getByRole('button', { name: /Đăng nhập/ }).click()
  try {
    await page.waitForURL(/\/(farmer|dashboard)/, { timeout: 120_000 })
  } catch (e) {
    // A failed sign-in leaves the password in the field, and Playwright's
    // failure snapshot (error-context.md) prints field values in clear text.
    await page.getByLabel('Mật khẩu').fill('').catch(() => {})
    throw e
  }
}

async function session(browser: Browser, who: { email?: string; password?: string }) {
  const page = await browser.newPage({ viewport: { width: 1363, height: 900 } })
  const errors: string[] = []
  page.on('console', (m) => { if (m.type() === 'error') errors.push(`${m.text()} @ ${m.location().url}`) })
  page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`))
  await signIn(page, who)
  return { page, errors }
}

/** App-origin errors. The browser logs a failed resource load for every
 *  non-2xx response; the documented ones are the favicon the app does not
 *  declare and GET /carbon's 404 "no calculation yet". */
function appErrors(errors: string[]): string[] {
  return errors.filter((e) => !/favicon\.ico/.test(e) && !/status of 404 .*\/carbon(\?|\s|$)/.test(e))
}

async function settle(page: Page) {
  await page.waitForLoadState('networkidle', { timeout: 120_000 }).catch(() => {})
  await expect(page.locator('main h1').first()).toBeVisible({ timeout: 120_000 })
  await page.waitForTimeout(300)
}

async function shoot(page: Page, name: string) {
  fs.mkdirSync(OUT, { recursive: true })
  await page.mouse.move(page.viewportSize()!.width - 4, page.viewportSize()!.height - 4)
  await page.screenshot({ path: `${OUT}/${name}.png` })
}

/** Everything that must hold for the rail at one viewport, measured on the
 *  rendered page. Returns the rail width (0 when there is no desktop rail). */
async function checkRail(page: Page, role: 'farmer' | 'manager', label: string): Promise<number> {
  const vw = page.viewportSize()!.width
  const m = await page.evaluate(() => {
    const aside = document.querySelector<HTMLElement>('aside.sidebar')!
    const cs = getComputedStyle(aside)
    const s = aside.getBoundingClientRect()
    const shown = cs.display !== 'none' && cs.visibility !== 'hidden' && s.width > 0 && s.right > 0
    const inside = (r: DOMRect) => r.left >= s.left - 0.5 && r.right <= s.right + 0.5 && r.top >= s.top - 0.5 && r.bottom <= s.bottom + 0.5
    const links = [...aside.querySelectorAll<HTMLAnchorElement>('nav a')]
    const bad: string[] = []
    for (const a of links) {
      const name = a.textContent!.trim()
      if (!inside(a.getBoundingClientRect())) bad.push(`${name}: row outside`)
      if (!inside(a.querySelector('.nav__ico')!.getBoundingClientRect())) bad.push(`${name}: icon outside`)
      if (a.scrollWidth > a.clientWidth + 0.5) bad.push(`${name}: label clipped (${a.scrollWidth} > ${a.clientWidth})`)
    }
    let active = null
    const cur = aside.querySelector<HTMLElement>('nav a[aria-current="page"]')
    if (cur) {
      const c = getComputedStyle(cur); const b = getComputedStyle(cur, '::before'); const r = cur.getBoundingClientRect()
      const markerLeft = r.left + parseFloat(b.left)
      active = { weight: Number(c.fontWeight), bg: c.backgroundColor, markerW: parseFloat(b.width), markerH: parseFloat(b.height), markerInside: markerLeft >= s.left + parseFloat(cs.paddingLeft) - 0.5 && markerLeft + parseFloat(b.width) <= s.right }
    }
    const foot = aside.querySelector('.sidebar__foot')!
    const footBad = [foot, ...foot.querySelectorAll('*')].filter((el) => !inside(el.getBoundingClientRect())).map((el) => el.className || el.tagName)
    const name = aside.querySelector<HTMLElement>('.sidebar__name')!
    const main = document.querySelector<HTMLElement>('.main, .fw-main')!.getBoundingClientRect()
    const bottom = document.querySelector<HTMLElement>('.fw-bottom')
    return {
      shown, w: s.width, bad, active, footBad,
      nameClipped: name.scrollWidth > name.clientWidth + 0.5 || name.scrollHeight > name.clientHeight + 1,
      mainLeft: main.left, mainRight: main.right, railRight: s.right,
      docOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      bottomShown: !!bottom && getComputedStyle(bottom).display !== 'none',
      focusableInsideRail: shown ? 0 : [...aside.querySelectorAll<HTMLElement>('a, button')].filter((el) => { el.focus(); return document.activeElement === el }).length,
      menuBtn: !!document.querySelector('.menu-btn') && getComputedStyle(document.querySelector('.menu-btn')!).display !== 'none',
    }
  })
  expect(m.docOverflow, `${label}: horizontal overflow`).toBeLessThanOrEqual(0)
  expect(m.mainRight, `${label}: workspace past the viewport`).toBeLessThanOrEqual(vw + 0.5)
  if (vw > 768) {
    expect(m.shown, `${label}: rail shown`).toBe(true)
    expect(Math.abs(m.w - TOKEN_W(vw)), `${label}: rail ${m.w}px`).toBeLessThanOrEqual(1)
    expect(m.bad, `${label}`).toEqual([])
    expect(m.footBad, `${label}: footer parts outside the rail`).toEqual([])
    expect(m.nameClipped, `${label}: account name clipped`).toBe(false)
    expect(Math.abs(m.mainLeft - m.railRight), `${label}: workspace starts at the rail`).toBeLessThanOrEqual(1)
    expect(m.bottomShown, `${label}: no bottom bar on desktop`).toBe(false)
    if (m.active) {
      expect(m.active.weight, `${label}: active weight`).toBeGreaterThanOrEqual(700)
      expect(m.active.bg, `${label}: active fill`).not.toBe('rgba(0, 0, 0, 0)')
      expect(m.active.markerW, `${label}: marker`).toBeGreaterThanOrEqual(3)
      expect(m.active.markerH).toBeGreaterThanOrEqual(20)
      expect(m.active.markerInside, `${label}: marker inside the rail`).toBe(true)
    }
    return m.w
  }
  // Phones and small tablets: no desktop rail, and nothing in it can take focus.
  expect(m.shown, `${label}: desktop rail on a ${vw}px screen`).toBe(false)
  expect(m.focusableInsideRail, `${label}: closed navigation takes focus`).toBe(0)
  if (role === 'farmer') {
    expect(m.bottomShown, `${label}: Farmer bottom bar`).toBe(true)
    expect(m.menuBtn, `${label}: Farmer has no Management menu button`).toBe(false)
  } else {
    expect(m.bottomShown, `${label}: Management has no Farmer bottom bar`).toBe(false)
    expect(m.menuBtn, `${label}: Management menu button`).toBe(true)
  }
  return 0
}

async function sweep(page: Page, role: 'farmer' | 'manager', path: string) {
  for (const vw of VIEWPORTS) {
    await page.setViewportSize({ width: vw, height: heightFor(vw) })
    await page.waitForTimeout(250)
    const w = await checkRail(page, role, `${role} ${path} @${vw}`)
    ;(widths[role][vw] ??= []).push(w)
  }
}

/** Hovering a row must not move or resize anything: rows, rail or workspace. */
async function expectHoverStable(page: Page, label: string) {
  const snap = () => page.evaluate(() => [...document.querySelectorAll('aside.sidebar nav a, aside.sidebar, .main, .fw-main')]
    .map((el) => { const r = el.getBoundingClientRect(); return [r.x, r.y, r.width, r.height].map((v) => Math.round(v * 10) / 10).join(',') + '|' + getComputedStyle(el).fontWeight }))
  const before = await snap()
  const rows = page.locator('aside.sidebar nav a:not([aria-current])')
  for (let i = 0; i < await rows.count(); i++) {
    await rows.nth(i).hover()
    await page.waitForTimeout(200)
    expect(await snap(), `${label}: hover on row ${i} shifted layout`).toEqual(before)
  }
  await page.mouse.move(page.viewportSize()!.width - 4, page.viewportSize()!.height - 4)
}

/** A dialog/drawer must be on top of the rail: every sampled point inside it
 *  hits the dialog, and the rail under the backdrop is not clickable. */
async function expectAboveRail(page: Page, dialogSel: string, label: string) {
  // Sample the resting position: the drawer enters with a 180ms slide + fade.
  await page.waitForFunction(() => document.getAnimations().every((a) => a.playState !== 'running'))
  const r = await page.evaluate((sel) => {
    const d = document.querySelector<HTMLElement>(sel)!
    const b = d.getBoundingClientRect()
    const pts = [[b.left + 8, b.top + 8], [b.left + b.width / 2, b.top + b.height / 2], [b.left + 8, b.bottom - 8], [b.right - 8, b.top + 8]]
    const onTop = pts.every(([x, y]) => { const t = document.elementFromPoint(x, y); return !!t && d.contains(t) })
    const rail = document.querySelector<HTMLElement>('aside.sidebar')!.getBoundingClientRect()
    let railClickable = false
    if (rail.width > 0 && rail.right > 0) {
      const t = document.elementFromPoint(rail.left + rail.width / 2, rail.top + 140)
      railClickable = !!t && !!t.closest('aside.sidebar')
    }
    return { onTop, railClickable }
  }, dialogSel)
  expect(r.onTop, `${label}: dialog covered`).toBe(true)
  expect(r.railClickable, `${label}: rail above the backdrop`).toBe(false)
}

test('Farmer, real session: rail on the token at every viewport and route, email, hover, keyboard, overlays', async ({ browser }) => {
  test.setTimeout(1_800_000)
  const { page, errors } = await session(browser, FARMER)

  // Resolve a real plot from the real season.
  await page.goto(`/farmer/crop-seasons/${SEASON}`)
  await settle(page)
  const plotHref = await page.locator('main a[href^="/farmer/plots/"]').first().getAttribute('href')
  expect(plotHref, 'season page links its plot').toBeTruthy()
  const routes = ['/farmer', '/farmer/journal', '/farmer/farms', '/farmer/performance', '/farmer/carbon', '/farmer/account', plotHref!,
    `/farmer/crop-seasons/${SEASON}`, `/farmer/crop-seasons/${SEASON}/journal`, `/farmer/crop-seasons/${SEASON}/performance`, `/farmer/crop-seasons/${SEASON}/carbon`]

  for (const path of routes) {
    await page.setViewportSize({ width: 1363, height: 900 })
    await page.goto(path)
    await settle(page)
    await sweep(page, 'farmer', path)
  }

  // Footer: the real address, whole, in the accessible name and the title.
  await page.setViewportSize({ width: 1363, height: 900 })
  await page.goto('/farmer')
  await settle(page)
  const acct = page.locator('aside.sidebar .sidebar__acct')
  const name = page.locator('aside.sidebar .sidebar__name')
  const shown = (await name.textContent())!.trim()
  console.log(`Farmer footer shows: ${shown === FARMER.email ? 'the account email' : 'a full name'}`)
  await expect(name).toHaveAttribute('title', shown)
  await expect(acct).toHaveAccessibleName(`Tài khoản của ${shown}`)
  if (shown === FARMER.email) await expect(acct).toHaveAccessibleName(new RegExp(FARMER.email!.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')))
  expect((await acct.boundingBox())!.height).toBeGreaterThanOrEqual(44)
  await shoot(page, 'farmer-home-1363-real')
  await expectHoverStable(page, 'farmer /farmer @1363')

  // Keyboard: skip link, brand, six destinations in order, the account.
  await page.keyboard.press('Tab')
  const order: string[] = []
  for (let i = 0; i < 8; i++) {
    await page.keyboard.press('Tab')
    order.push(await page.evaluate(() => { const a = document.activeElement!; return a.closest('aside.sidebar') ? (a.getAttribute('aria-label') ?? a.textContent!.trim()) : `OUTSIDE:${a.textContent!.trim().slice(0, 20)}` }))
    const ring = await page.evaluate(() => { const c = getComputedStyle(document.activeElement!); return { s: c.outlineStyle, w: parseFloat(c.outlineWidth) } })
    expect(ring.s).toBe('solid'); expect(ring.w).toBeGreaterThanOrEqual(2)
  }
  expect(order.slice(1, 7)).toEqual(['Tổng quan', 'Nhật ký', 'Ruộng / Vụ mùa', 'Hiệu suất', 'Carbon', 'Tôi'])
  expect(order[7]).toBe(`Tài khoản của ${shown}`)

  // Workspace keeps its colours: no institutional green on CTA or links.
  const leaks = await page.locator('main').evaluate((main) => [...main.querySelectorAll<HTMLElement>('.fw-btn:not(.fw-btn--ghost):not(.fw-btn--soft), a')]
    .filter((el) => el.getBoundingClientRect().width > 0)
    .map((el) => { const cs = getComputedStyle(el); return { t: el.textContent!.trim().slice(0, 30), bg: cs.backgroundColor, c: cs.color } }))
  for (const l of leaks) {
    expect(isInstitutionalGreen(l.bg), `workspace fill "${l.t}" ${l.bg}`).toBe(false)
    expect(isInstitutionalGreen(l.c, 0.04), `workspace ink "${l.t}" ${l.c}`).toBe(false)
  }

  // Activity form over the rail. Opened from the journal: on real data Home's
  // one action follows the season's state (here "Bổ sung ngay", Carbon inputs
  // missing), so "Ghi hoạt động" is not always on Home.
  await page.goto('/farmer/journal')
  await settle(page)
  await page.locator('main').getByRole('button', { name: 'Ghi hoạt động' }).first().click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await expectAboveRail(page, '[role="dialog"]', 'farmer activity picker @1363')
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)

  // Carbon page: its quick-fix sheet over the rail; shots at 1363 and 390.
  await page.goto('/farmer/carbon')
  await settle(page)
  await shoot(page, 'farmer-carbon-1363-real')
  const fix = page.getByRole('button', { name: /Sửa ngay/ }).first()
  if (await fix.count()) {
    await fix.click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await expectAboveRail(page, '[role="dialog"]', 'farmer Carbon quick-fix @1363')
    await page.keyboard.press('Escape')
  } else {
    console.log('Farmer Carbon: no "Sửa ngay" on this season — quick-fix overlay not exercised')
  }
  await page.setViewportSize({ width: 390, height: 844 })
  await page.waitForTimeout(300)
  await expect(page.locator('main h1').first()).toBeInViewport()
  await expect(page.locator('.fw-bottom a[aria-current="page"]')).toHaveText('Carbon')
  await shoot(page, 'farmer-carbon-390-real')

  // Phone Home: the next action's CTA — whichever the season's state picks —
  // is on screen, not under the bottom bar.
  await page.goto('/farmer')
  await settle(page)
  const cta = page.locator('main section.fw-next').locator('a, button').first()
  await expect(cta).toBeInViewport()
  const ctaBox = (await cta.boundingBox())!; const barTop = (await page.locator('.fw-bottom').boundingBox())!.y
  expect(ctaBox.y + ctaBox.height, 'CTA above the bottom bar').toBeLessThanOrEqual(barTop)
  // Keyboard on a phone: nothing in the hidden rail takes focus.
  for (let i = 0; i < 12; i++) {
    await page.keyboard.press('Tab')
    expect(await page.evaluate(() => !!document.activeElement?.closest('aside.sidebar'))).toBe(false)
  }

  // Season at 1024.
  await page.setViewportSize({ width: 1024, height: 900 })
  await page.goto(`/farmer/crop-seasons/${SEASON}`)
  await settle(page)
  await shoot(page, 'farmer-season-1024-real')

  // Account navigation and sign-out.
  await page.setViewportSize({ width: 1363, height: 900 })
  await page.locator('aside.sidebar .sidebar__acct').click()
  await expect(page).toHaveURL(/\/farmer\/account$/)
  await expect(page.locator('aside.sidebar nav a[aria-current="page"]')).toHaveText('Tôi')
  console.log('Farmer app-origin console errors:', JSON.stringify(appErrors(errors)))
  console.log('Farmer all console errors:', errors.length)
  expect(appErrors(errors)).toEqual([])
  await page.getByRole('button', { name: 'Đăng xuất' }).click()
  await expect(page).toHaveURL(/\/login/)
  await page.close()
})

test('Management, real session: rail on the token at every viewport and route, no clipping, drawer, menu', async ({ browser }) => {
  test.setTimeout(1_800_000)
  const { page, errors } = await session(browser, MANAGER)

  for (const path of MANAGER_ROUTES) {
    await page.setViewportSize({ width: 1363, height: 900 })
    await page.goto(path)
    await settle(page)
    if (path === '/carbon') {
      await page.waitForFunction(() => document.querySelectorAll('tr[data-carbon-row]').length > 0 && !document.querySelector('tr[data-carbon-row] .skeleton'), null, { timeout: 150_000 }).catch(() => {})
    }
    await sweep(page, 'manager', path)
  }
  // The full manager menu is on screen (the mock tenant shows two rows).
  await page.setViewportSize({ width: 1024, height: 900 })
  const labels = await page.locator('aside.sidebar nav a').allTextContents()
  console.log('Manager menu:', labels.join(' | '))
  expect(labels.length).toBeGreaterThanOrEqual(8)
  expect(labels).toContain('Tổng quan vận hành')

  await page.setViewportSize({ width: 1363, height: 900 })
  await page.goto('/dashboard')
  await settle(page)
  // The manager's address is whole in the DOM and in the title.
  const name = page.locator('aside.sidebar .sidebar__name')
  await expect(name).toHaveText(MANAGER.email!)
  await expect(name).toHaveAttribute('title', MANAGER.email!)
  await shoot(page, 'management-dashboard-1363-real')
  await expectHoverStable(page, 'manager /dashboard @1363')

  // Season drawer over the rail.
  await page.goto('/seasons')
  await page.locator('table.ops-table tbody tr button').first().waitFor({ timeout: 120_000 })
  await page.locator('table.ops-table tbody tr button').first().click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await expectAboveRail(page, '.side-drawer', 'manager season drawer @1363')
  await page.keyboard.press('Escape')

  // /carbon at 1024: shot, and its season drawer over the rail.
  await page.setViewportSize({ width: 1024, height: 900 })
  await page.goto('/carbon')
  await page.waitForFunction(() => document.querySelectorAll('tr[data-carbon-row]').length > 0 && !document.querySelector('tr[data-carbon-row] .skeleton'), null, { timeout: 150_000 })
  await shoot(page, 'management-carbon-1024-real')
  await page.locator('[data-row-action="secondary"]').first().click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await expectAboveRail(page, '.side-drawer', 'manager Carbon drawer @1024')
  await page.keyboard.press('Escape')

  // Phone: the menu slides in; closed, it takes no focus.
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/dashboard')
  await settle(page)
  const menu = page.getByRole('button', { name: 'Mở menu' })
  await expect(menu).toHaveAttribute('aria-expanded', 'false')
  await page.keyboard.press('Tab')
  await page.keyboard.press('Tab')
  await expect(menu).toBeFocused()
  await menu.click()
  await expect(menu).toHaveAttribute('aria-expanded', 'true')
  const first = page.locator('aside.sidebar nav a').first()
  await expect(first).toBeInViewport()
  await page.waitForTimeout(300)
  await shoot(page, 'management-menu-390-real')
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0)
  // A destination closes the menu and navigates.
  await page.locator('aside.sidebar nav a', { hasText: 'Vụ mùa' }).click()
  await expect(page).toHaveURL(/\/seasons$/)
  await expect(menu).toHaveAttribute('aria-expanded', 'false')

  console.log('Manager app-origin console errors:', JSON.stringify(appErrors(errors)))
  console.log('Manager all console errors:', errors.length)
  expect(appErrors(errors)).toEqual([])
  // Sign-out from the sidebar footer.
  await page.setViewportSize({ width: 1363, height: 900 })
  await page.getByRole('button', { name: 'Đăng xuất' }).click()
  await expect(page).toHaveURL(/\/login/)
  await page.close()
})

test('both roles: the same rail width at every viewport, within 1px', () => {
  const rows: string[] = []
  for (const vw of VIEWPORTS) {
    const f = [...new Set(widths.farmer[vw] ?? [])]; const m = [...new Set(widths.manager[vw] ?? [])]
    rows.push(`${vw}px farmer=${f.join('/')} manager=${m.join('/')}`)
    expect(f.length, `${vw}: farmer measured`).toBeGreaterThan(0)
    expect(m.length, `${vw}: manager measured`).toBeGreaterThan(0)
    for (const a of f) for (const b of m) expect(Math.abs(a - b), `${vw}px farmer ${a} vs manager ${b}`).toBeLessThanOrEqual(1)
    if (vw > 768) for (const a of [...f, ...m]) expect(Math.abs(a - TOKEN_W(vw))).toBeLessThanOrEqual(1)
  }
  console.log(rows.join('\n'))
})
