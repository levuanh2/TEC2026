import { expect, test, type Page } from '@playwright/test'

/* Reading one season's Carbon readiness takes seconds against hosted Supabase,
 * and a cooperative screen reads several. */
test.setTimeout(300_000)

/* Visual + behavioural QA for the hybrid redesign, against the real API.
 *
 * Credentials come from the environment (REDESIGN_FARMER_EMAIL/PASSWORD,
 * REDESIGN_MANAGER_EMAIL/PASSWORD) — never from this file. Screenshots land in
 * `.qa-screenshots/redesign/` (gitignored) so before/after can be compared.
 */

const farmer = { email: process.env.REDESIGN_FARMER_EMAIL, password: process.env.REDESIGN_FARMER_PASSWORD }
const manager = { email: process.env.REDESIGN_MANAGER_EMAIL, password: process.env.REDESIGN_MANAGER_PASSWORD }
const OUT = '.qa-screenshots/redesign'
const SEASON = process.env.REDESIGN_SEASON_ID ?? '2e63e128-f53d-4f70-9bb4-62b9efc048e3'

test.skip(process.env.REDESIGN_QA !== 'true' || !farmer.email, 'set REDESIGN_QA=true with the QA credentials')

const VIEWPORTS = [
  { name: 'desktop', width: 1440, height: 1024 },
  { name: 'laptop', width: 1280, height: 900 },
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

async function settle(page: Page, ms = 800) {
  await page.waitForLoadState('networkidle', { timeout: 90_000 }).catch(() => {})
  await page.waitForTimeout(ms)
}

async function shoot(page: Page, name: string, viewport: (typeof VIEWPORTS)[number]) {
  await page.setViewportSize({ width: viewport.width, height: viewport.height })
  // Readiness takes seconds per season: a screenshot of skeletons proves
  // nothing, so wait for the page to stop fetching first.
  await settle(page)
  await page.screenshot({ path: `${OUT}/${name}-${viewport.name}.png`, fullPage: true })
  await expectNoOverflow(page, `${name} @ ${viewport.name}`)
}

/* ---------------------------------------------------------------- Farmer */

test('farmer screens across four viewports', async ({ page }) => {
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

    await page.goto('/farmer/farms')
    await shoot(page, 'farmer-farms', vp)

    await page.goto('/farmer/carbon')
    await page.waitForTimeout(1500)
    await shoot(page, 'farmer-carbon', vp)

    await page.goto('/farmer/performance')
    await shoot(page, 'farmer-performance', vp)

    await page.goto('/farmer/account')
    await shoot(page, 'farmer-account', vp)
  }

  // The phone bottom bar sits above the content, not inside it: a viewport
  // shot (not fullPage) is the only way to see what a farmer actually sees.
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/farmer')
  await settle(page)
  await page.screenshot({ path: `${OUT}/farmer-home-mobile-viewport.png` })
  const bar = page.locator('.fw-bottom')
  await expect(bar).toBeVisible()
  const box = await bar.boundingBox()
  expect(box!.y + box!.height).toBeLessThanOrEqual(845)

  expect(appErrors(errors), `console errors: ${errors.join(' | ')}`).toEqual([])
})

test('farmer home states one season once, with one primary action', async ({ page }) => {
  await signIn(page, farmer)
  await page.setViewportSize({ width: 1440, height: 1024 })
  await page.goto('/farmer')
  await settle(page, 1200)

  // Exactly one next-action block, and exactly one filled button in it.
  await expect(page.locator('.fw-next')).toHaveCount(1)
  await expect(page.locator('.fw-next__cta')).toHaveCount(1)

  // One context bar, and the old hero (with its 62px day count and second
  // green button) is gone for good.
  await expect(page.locator('.fw-ctxbar')).toHaveCount(1)
  await expect(page.locator('.fw-ledger')).toHaveCount(0)

  // The primary action must be the visually dominant control: nothing else on
  // the page may render as a filled primary button.
  const primaries = await page.locator('main .fw-btn:not(.fw-btn--soft):not(.fw-btn--ghost):not(.fw-btn--danger)').count()
  expect(primaries, 'more than one primary button competes on Farmer Home').toBeLessThanOrEqual(1)
})

test('no raw enum, id or ISO timestamp reaches a farmer', async ({ page }) => {
  await signIn(page, farmer)
  await page.setViewportSize({ width: 1440, height: 1024 })
  for (const path of ['/farmer', '/farmer/journal', '/farmer/carbon', '/farmer/performance', '/farmer/farms', '/farmer/account']) {
    await page.goto(path)
    await settle(page, 1200)
    const text = await page.evaluate(() => document.body.innerText)
    for (const raw of ['active', 'planned', 'draft', 'incorporated', 'awd', 'continuous_flooding',
      'straw_management', 'activity_id', 'created_at', 'updated_at', 'duration_minutes', 'pesticide']) {
      expect(text, `${path} shows the raw value "${raw}"`).not.toMatch(new RegExp(`\\b${raw}\\b`))
    }
    // `diesel` is a loanword inside the Vietnamese label "Dầu diesel", which is
    // what a farmer should read; only the bare stored value is a leak.
    expect(text, `${path} shows the raw value "diesel"`).not.toMatch(/(?<!Dầu )\bdiesel\b/)
    // A stored id or an ISO timestamp is storage, not something a farmer reads.
    expect(text, `${path} shows a raw UUID`).not.toMatch(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/)
    expect(text, `${path} shows a raw ISO timestamp`).not.toMatch(/\d{4}-\d{2}-\d{2}T[\d:]/)
  }
})

test('dates read dd/MM/yyyy', async ({ page }) => {
  await signIn(page, farmer)
  await page.goto('/farmer/journal')
  await settle(page, 1200)
  const text = await page.evaluate(() => document.body.innerText)
  expect(text).toMatch(/\b\d{2}\/\d{2}\/\d{4}\b/)
  // The ISO form must not appear beside it.
  expect(text).not.toMatch(/\b\d{4}-\d{2}-\d{2}\b/)
})

test('a deep link to /farmer/carbon lands on Carbon, not on Home', async ({ page }) => {
  await signIn(page, farmer)
  await page.goto('/farmer/carbon')
  await settle(page, 1500)
  await expect(page).toHaveURL(/\/farmer\/carbon$/)
  await expect(page.locator('main')).toContainText(/Carbon|phát thải/i)
})

test('keyboard reaches the primary action and focus is visible', async ({ page }) => {
  await signIn(page, farmer)
  await page.setViewportSize({ width: 1440, height: 1024 })
  await page.goto('/farmer')
  await settle(page, 1200)
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

test('every farmer control is at least 40px tall', async ({ page }) => {
  await signIn(page, farmer)
  await page.setViewportSize({ width: 1440, height: 1024 })
  await page.goto('/farmer')
  await settle(page, 1200)
  const small = await page.evaluate(() =>
    [...document.querySelectorAll('main button, main a.fw-btn, main a.fw-link, main input, main select')]
      .map((el) => ({ t: (el.textContent || '').trim().slice(0, 30), h: Math.round(el.getBoundingClientRect().height) }))
      .filter((x) => x.h > 0 && x.h < 40))
  expect(small, `controls under 40px: ${JSON.stringify(small)}`).toEqual([])
})

/* ------------------------------------------------------------ Management */

test('management workspace across four viewports', async ({ page }) => {
  // 13 routes x 4 widths against a backend whose per-season readiness read
  // costs 10-16s (see the loading blocker in the round-2 report).
  test.setTimeout(1_200_000)
  const errors: string[] = []
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()) })

  await signIn(page, manager)
  for (const vp of VIEWPORTS) {
    await page.goto('/dashboard')
    await expect(page.getByRole('heading', { name: 'Hôm nay cần xử lý gì?' })).toBeVisible()
    await page.waitForTimeout(8000)
    await shoot(page, 'mgmt-overview', vp)

    await page.goto('/farms')
    await shoot(page, 'mgmt-farms', vp)

    await page.goto('/seasons')
    await expect(page.getByRole('heading', { name: 'Vụ mùa', level: 1 })).toBeVisible()
    await page.waitForTimeout(6000)
    await shoot(page, 'mgmt-seasons', vp)

    await page.goto('/data-gaps')
    await page.waitForTimeout(4000)
    await shoot(page, 'mgmt-data-gaps', vp)

    await page.goto('/carbon')
    await page.waitForTimeout(4000)
    await shoot(page, 'mgmt-carbon', vp)

    await page.goto('/performance')
    await shoot(page, 'mgmt-performance', vp)

    await page.goto('/mrv')
    await shoot(page, 'mgmt-mrv', vp)

    await page.goto('/organizations')
    await shoot(page, 'mgmt-organizations', vp)

    for (const [tab, name] of [['', 'overview'], ['/activities', 'activities'], ['/performance', 'performance'], ['/carbon', 'carbon'], ['/mrv', 'mrv']] as const) {
      await page.goto(`/crop-seasons/${SEASON}${tab}`)
      await page.waitForTimeout(3000)
      await shoot(page, `mgmt-season-${name}`, vp)
    }
  }
  expect(appErrors(errors), `console errors: ${errors.join(' | ')}`).toEqual([])
})

test('a management season row identifies farm, plot and season', async ({ page }) => {
  await signIn(page, manager)
  await page.setViewportSize({ width: 1440, height: 1024 })
  await page.goto('/seasons')
  const rows = page.locator('.ops-table--seasons tbody tr')
  await expect(rows.first()).toBeVisible({ timeout: 60_000 })
  await expect(page.locator('.ops-badge').first()).toBeVisible({ timeout: 120_000 })

  // The defect: two seasons of one farm sharing a season code rendered as
  // identical rows. Every row must carry its plot, so no two are the same.
  await expect(page.getByRole('columnheader', { name: 'Thửa' })).toBeVisible()
  const signatures = await rows.evaluateAll((trs) =>
    trs.map((tr) => [...tr.querySelectorAll('td')].slice(0, 3).map((td) => (td.textContent || '').trim()).join('|')))
  expect(new Set(signatures).size, `identical rows: ${JSON.stringify(signatures)}`).toBe(signatures.length)
  // …and the status reads in Vietnamese, never as the stored value.
  const text = await page.evaluate(() => document.body.innerText)
  expect(text).not.toMatch(/\bactive\b/)
  expect(text).not.toMatch(/\bplanned\b/)
})

test('season rows are reachable and operable from the keyboard', async ({ page }) => {
  await signIn(page, manager)
  await page.setViewportSize({ width: 1440, height: 1024 })
  await page.goto('/seasons')
  // Real rows only: the "đang đọc danh sách vụ" placeholder is a <tr> too.
  const rows = page.locator('.ops-table--seasons tbody tr:has(button)')
  await expect(rows.first()).toBeVisible({ timeout: 60_000 })

  // One interaction per row, and it is a real button — not a div with onClick.
  const detail = rows.first().getByRole('button', { name: /Chi tiết/ })
  await expect(detail).toHaveCount(1)
  await expect(rows.first().getByRole('button', { name: 'Mở vụ' })).toHaveCount(0)
  await detail.focus()
  await expect(detail).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page.locator('.ops-detail')).toBeVisible()
  await expect(page).toHaveURL(/\/seasons$/)
  // The drawer must not push the table into a horizontal scroll on desktop.
  await expectNoOverflow(page, 'seasons with drawer open @1440')
  await page.screenshot({ path: `${OUT}/mgmt-seasons-detail-desktop.png`, fullPage: true })
})

test('Carbon readiness reads the same on every screen', async ({ page }) => {
  await signIn(page, manager)
  await page.setViewportSize({ width: 1440, height: 1024 })

  // The season hub's "Bước tiếp theo" and its Carbon tab must agree.
  await page.goto(`/crop-seasons/${SEASON}`)
  await settle(page, 4000)
  const overview = await page.evaluate(() => document.body.innerText)

  await page.goto(`/crop-seasons/${SEASON}/carbon`)
  await settle(page, 4000)
  const carbon = await page.evaluate(() => document.body.innerText)

  const state = (t: string) => ['Thiếu dữ liệu', 'Giới hạn hệ số', 'Sẵn sàng tính', 'Đã tính', 'Cần tính lại'].filter((s) => t.includes(s))
  expect(state(overview).length, 'overview names no Carbon state').toBeGreaterThan(0)
  expect(state(carbon), 'overview and the Carbon tab tell different stories')
    .toEqual(expect.arrayContaining(state(overview)))

  // The exact contradiction the audit found: never "đã đủ dữ liệu" while the
  // Carbon screen is naming something the user still has to supply.
  if (carbon.includes('Thiếu dữ liệu')) {
    expect(overview).not.toContain('Đã đủ dữ liệu vụ')
  }
})

test('a calculation that cannot succeed is never offered', async ({ page }) => {
  await signIn(page, manager)
  await page.setViewportSize({ width: 1440, height: 1024 })
  await page.goto(`/crop-seasons/${SEASON}/carbon`)
  await settle(page, 5000)
  const recalc = page.getByRole('button', { name: /Tính lại theo kịch bản/ })
  if (await recalc.count()) {
    const blocked = await page.evaluate(() => {
      const t = document.body.innerText
      return t.includes('Thiếu dữ liệu') || t.includes('Giới hạn hệ số')
    })
    if (blocked) await expect(recalc).toBeDisabled()
  }
})

test('MRV never reports a status its own steps contradict', async ({ page }) => {
  await signIn(page, manager)
  await page.setViewportSize({ width: 1440, height: 1024 })
  await page.goto('/mrv')
  await settle(page, 2000)
  const text = await page.evaluate(() => document.body.innerText)

  // `draft` reached the screen before; the case status now reads "Bản nháp".
  expect(text).not.toMatch(/\bdraft\b/)

  const progress = text.match(/(\d)\/(\d)/)
  if (progress) {
    const done = Number(progress[1])
    const active = /Đang thực hiện/.test(text)
    if (done > 0 || active) {
      // The reported defect: "Chưa bắt đầu" above a step already under way.
      const aggregate = await page.locator('.hero .badge, .hero__meta .badge').first().innerText().catch(() => '')
      expect(aggregate, 'aggregate status contradicts the steps').not.toBe('Chưa bắt đầu')
    }
  }

  // No review/approve endpoint exists, so no screen may offer one.
  await page.goto('/dashboard')
  await page.waitForTimeout(8000)
  const dash = await page.evaluate(() => document.body.innerText)
  expect(dash).not.toContain('Duyệt MRV')
})

test('empty, loading and error states are distinct', async ({ page }) => {
  await signIn(page, manager)
  await page.setViewportSize({ width: 1440, height: 1024 })
  await page.goto('/seasons')
  await expect(page.locator('.ops-table--seasons tbody tr').first()).toBeVisible({ timeout: 60_000 })
  // While rows are still resolving each one shows a skeleton; wait for the
  // last of them to go, so the filter's own empty state is what gets asserted
  // rather than the "đang đọc" one. (Polling the count text races: it reads
  // "no pending" both before the reads start and after they finish.)
  await expect(page.locator('.ops-table--seasons .skeleton')).toHaveCount(0, { timeout: 240_000 })

  // A filter that matches nothing offers the way out, rather than a dead end.
  await page.getByLabel('Tìm nông hộ hoặc vụ mùa').fill('zzz-không-có-gì')
  await expect(page.locator('.ops-empty')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Xóa bộ lọc' })).toBeVisible()
  await page.getByRole('button', { name: 'Xóa bộ lọc' }).click()
  await expect(page.locator('.ops-table--seasons tbody tr').first()).toBeVisible()

  // A loading value is never a resting "…".
  const text = await page.evaluate(() => document.body.innerText)
  expect(text).not.toMatch(/^…$/m)
})

test('the organisation is never reported wrong while it is still loading', async ({ page }) => {
  await signIn(page, manager)
  await page.setViewportSize({ width: 1440, height: 1024 })
  await page.goto('/dashboard')
  // Sampled during the first seconds, before the organisation name arrives.
  for (let i = 0; i < 10; i++) {
    const chip = await page.locator('.org-chip').innerText().catch(() => '')
    expect(chip, 'claimed "Chưa gán tổ chức" while the name was still loading')
      .not.toContain('Chưa gán tổ chức')
    await page.waitForTimeout(300)
  }
})
