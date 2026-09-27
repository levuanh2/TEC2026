import { expect, test, type Page } from './fixtures'

/* Round 3 regression gates.
 *
 * These run against the mock tenant (playwright.config.ts sets
 * VITE_USE_MOCK_DATA=true), so they need no credentials and can gate every
 * commit — unlike redesign-qa.spec.ts, which skips itself without a real QA
 * login. Each test below pins one thing the round-3 audit found broken.
 */

const F = 'farm-demo-01', P = 'plot-demo-01', S = 'crop-demo-01'

const MGMT = ['/dashboard', '/organizations', '/performance', '/farms', '/seasons', '/data-gaps', '/carbon', '/mrv',
  `/farms/${F}`, `/plots/${P}`, `/crop-seasons/${S}`, `/crop-seasons/${S}/activities`,
  `/crop-seasons/${S}/performance`, `/crop-seasons/${S}/carbon`, `/crop-seasons/${S}/mrv`]
const FARMER = ['/farmer', '/farmer/journal', '/farmer/farms', '/farmer/performance', '/farmer/carbon', '/farmer/account',
  `/farmer/farms/${F}`, `/farmer/plots/${P}`, `/farmer/crop-seasons/${S}`,
  `/farmer/crop-seasons/${S}/journal`, `/farmer/crop-seasons/${S}/performance`, `/farmer/crop-seasons/${S}/carbon`]
const ALL = [...MGMT, ...FARMER]

const settle = async (page: Page, path: string) => {
  await page.goto(path, { waitUntil: 'domcontentloaded' })
  // `networkidle` never arrives on the ops pages, which keep reading season
  // rollups in the background; a fixed settle is what these assertions need.
  await page.waitForTimeout(600)
}

/* ------------------------------------------------- §2 Farmer journal flow */

test('journal offers exactly one way to start a record, and the steps live in one place', async ({ page }) => {
  await settle(page, '/farmer/journal')
  // One primary entry point: no inline six-tile grid, no second button in the
  // empty state, no step indicator sitting on the page behind the overlay.
  await expect(page.locator('.fw-record')).toHaveCount(0)
  await expect(page.locator('.fw-quick')).toHaveCount(0)
  await expect(page.locator('.fw-steps')).toHaveCount(0)
  const cta = page.getByRole('button', { name: 'Ghi hoạt động', exact: true })
  await expect(cta).toHaveCount(1)

  // Step 1 is the picker inside the sheet; step 2 is the form.
  await cta.click()
  const picker = page.getByRole('dialog', { name: 'Ghi hoạt động' })
  await expect(picker).toBeVisible()
  await expect(picker.locator('.fw-steps')).toHaveCount(1)
  await picker.getByRole('button', { name: 'Bón phân' }).click()
  const form = page.getByRole('dialog', { name: 'Bón phân' })
  await expect(form).toBeVisible()
  await expect(form.locator('.fw-steps')).toHaveCount(1)

  // §2: advanced methodology fields are collapsed on a new entry.
  const more = form.locator('details.fw-more')
  await expect(more).toHaveCount(1)
  expect(await more.evaluate((el: HTMLDetailsElement) => el.open)).toBe(false)

  // §9: Escape closes the dialog.
  await page.keyboard.press('Escape')
  await expect(form).toHaveCount(0)
})

test('journal edit and delete controls meet the 44px touch target', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await settle(page, `/farmer/crop-seasons/${S}/journal`)
  const controls = page.locator('.fw-entry__actions .fw-iconbtn')
  const n = await controls.count()
  expect(n).toBeGreaterThan(0)
  for (let i = 0; i < n; i++) {
    const box = await controls.nth(i).boundingBox()
    expect(box!.height).toBeGreaterThanOrEqual(44)
    expect(box!.width).toBeGreaterThanOrEqual(44)
  }
})

test('deleting a record asks first, and names the record it would remove', async ({ page }) => {
  await settle(page, `/farmer/crop-seasons/${S}/journal`)
  await page.locator('.fw-entry__actions .fw-iconbtn--danger').first().click()
  const dialog = page.getByRole('alertdialog')
  await expect(dialog).toBeVisible()
  await expect(dialog).toContainText(/Xóa/)
  await expect(dialog).toContainText(/tưới nước|bón phân|thu hoạch|gieo sạ|thuốc|rơm/i)
})

/* --------------------------------------- §3/§4 Farmer hierarchy + account */

test('farmer pages state the running season once', async ({ page }) => {
  await settle(page, `/farmer/farms/${F}`)
  // The farm page used to end with a "Vụ đang canh tác" section repeating the
  // seasons the plot cards above already named.
  await expect(page.getByRole('heading', { name: 'Vụ đang canh tác' })).toHaveCount(0)
  await expect(page.locator('.fw-idcard__action')).toHaveCount(1)

  await settle(page, `/farmer/plots/${P}`)
  const featured = page.locator('.fw-current')
  await expect(featured).toHaveCount(1)
  const name = (await featured.locator('b').first().innerText()).trim()
  // The featured season must not also appear as a row in the list below.
  await expect(page.locator('.farmer-season-list').getByText(name, { exact: true })).toHaveCount(0)
})

test('the farms list carries farm -> plot -> season, as links', async ({ page }) => {
  await settle(page, '/farmer/farms')
  const rows = page.locator('.fw-farm__plot')
  await expect(rows).toHaveCount(2)
  for (const el of await rows.all()) {
    expect(await el.evaluate((n) => n.tagName)).toBe('A')
  }
  await expect(rows.first()).toContainText('Đang canh tác')
})

test('the account page never uses the sign-in email as its heading', async ({ page }) => {
  await settle(page, '/farmer/account')
  const h1 = await page.getByRole('heading', { level: 1 }).innerText()
  expect(h1).not.toMatch(/@/)
  // One sign-out per viewport: the sidebar links to this page instead.
  await expect(page.getByRole('button', { name: /Đăng xuất/ })).toHaveCount(1)
  // Scope is readable without opening another page.
  await expect(page.locator('.fw-scope__plot')).toHaveCount(2)
})

/* --------------------------------------- §5 Management semantic navigation */

test('management rows are links a keyboard can reach and Enter follows', async ({ page }) => {
  const hops = [['/farms', `/farms/${F}`], [`/farms/${F}`, `/plots/${P}`], [`/plots/${P}`, `/crop-seasons/${S}`]] as const
  for (const [path, expected] of hops) {
    await settle(page, path)
    // No `<tr onClick>` survives anywhere.
    await expect(page.locator('tr.is-clickable')).toHaveCount(0)
    const link = page.locator('tr.has-rowlink .rowlink').first()
    await expect(link).toHaveAttribute('href', expected)
    await link.focus()
    await page.keyboard.press('Enter')
    await expect(page).toHaveURL(new RegExp(expected.replace(/\//g, '\\/') + '$'))
  }
})

test('management farm detail names the plot of each season and says the status in Vietnamese', async ({ page }) => {
  await settle(page, `/farms/${F}`)
  const seasons = page.locator('table.data').last()
  await expect(seasons).toContainText('Thửa A-01')
  await expect(seasons).toContainText('Đang canh tác')
  await expect(seasons).not.toContainText(/\bactive\b/)
})

test('the farms register can be searched', async ({ page }) => {
  await settle(page, '/farms')
  const box = page.getByRole('searchbox', { name: 'Tìm nông hộ' })
  await expect(box).toBeVisible()
  await box.fill('khong-co-ho-nao-ten-nhu-vay')
  await expect(page.getByText(/Không có nông hộ nào khớp/)).toBeVisible()
})

/* ----------------------------------- §7 data-gaps + technical detail */

test('data-gaps names its action the same way its instructions do', async ({ page }) => {
  await settle(page, '/data-gaps')
  const copy = await page.evaluate(() => document.body.innerText)
  const instructsXuLy = /bấm Xử lý/.test(copy)
  expect(instructsXuLy, 'the /data-gaps instruction should name the action').toBe(true)
  // The empty-state placeholder is a <tr> as well, so only count real rows.
  const rows = await page.locator('table.ops-table tbody tr:not(:has(.ops-empty))').count()
  if (rows > 0) {
    // Whenever the copy says "Xử lý", a season with something missing has to
    // carry a button with exactly that label — the old page said "bấm Xử lý"
    // beside a button labelled "Chi tiết".
    await expect(page.getByRole('button', { name: /^Xử lý/ }).first()).toBeVisible()
  } else {
    // Nothing to handle: there must be no orphan "Chi tiết" button either.
    expect(await page.getByRole('button', { name: /^Chi tiết/ }).count()).toBe(0)
  }
})

test('technical fields are disclosed, closed, and only in Management', async ({ page }) => {
  await settle(page, `/crop-seasons/${S}/activities`)
  await page.locator('.act').first().click()
  const drawer = page.getByRole('dialog')
  await expect(drawer).toBeVisible()
  const tech = drawer.locator('details.tech-detail')
  await expect(tech).toHaveCount(1)
  expect(await tech.evaluate((el: HTMLDetailsElement) => el.open)).toBe(false)
  // The stored id lives inside the disclosure, not in the visible summary.
  await expect(drawer.locator('dl.dl').first()).not.toContainText('act-demo-01')

  // The farmer's own activity drawer has no technical section at all.
  await settle(page, `/farmer/crop-seasons/${S}/journal`)
  await page.locator('.fw-entry__open').first().click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await expect(page.locator('details.tech-detail')).toHaveCount(0)
})

/* ----------------------------------------------- §8 visual system pass */

test('no institutional dark green, no emoji and no serif in the workspace', async ({ page }) => {
  test.setTimeout(180_000)
  for (const path of ALL) {
    await settle(page, path)
    const found = await page.evaluate(() => {
      const main = document.querySelector('main')
      if (!main) return { green: ['no main element'], emoji: [] as string[], serif: [] as string[] }
      const els = Array.from(main.querySelectorAll('*')).slice(0, 4000)
      // TDMU institutional green is a dark BLUE-green (the sidebar family).
      // The yellow-green ink paired with the sanctioned pastel #E2F0CB is a
      // different hue and is allowed, so blue >= red is the discriminator.
      const institutional = (c: string) => {
        const m = c.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/)
        if (!m) return false
        const [r, g, b] = [+m[1], +m[2], +m[3]]
        return g > r + 18 && g < 130 && r + g + b > 20 && b >= r
      }
      const green: string[] = []
      const serif: string[] = []
      for (const el of els) {
        const cs = getComputedStyle(el)
        for (const prop of ['backgroundColor', 'color', 'borderBottomColor', 'borderLeftColor'] as const) {
          if (institutional(cs[prop])) { green.push(`${el.tagName}.${String(el.className).slice(0, 40)}:${prop}`); break }
        }
        if (/serif/i.test(cs.fontFamily) && !/sans-serif/i.test(cs.fontFamily) && el.textContent?.trim()) {
          serif.push(`${el.tagName}.${String(el.className).slice(0, 40)}`)
        }
      }
      const emojiRe = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u
      const emoji: string[] = []
      for (const el of Array.from(document.body.querySelectorAll('*'))) {
        for (const n of Array.from(el.childNodes)) {
          if (n.nodeType === 3 && emojiRe.test(n.nodeValue ?? '')) emoji.push((n.nodeValue ?? '').trim().slice(0, 24))
        }
      }
      return { green: [...new Set(green)].slice(0, 5), emoji: [...new Set(emoji)].slice(0, 5), serif: [...new Set(serif)].slice(0, 5) }
    })
    expect(found.green, `institutional green in main on ${path}`).toEqual([])
    expect(found.emoji, `emoji glyph on ${path}`).toEqual([])
    expect(found.serif, `serif type on ${path}`).toEqual([])
  }
})

/* ------------------------------------------------- §9 responsive + a11y */

test('no horizontal page overflow at 1440, 1280, 768 or 390', async ({ page }) => {
  test.setTimeout(300_000)
  for (const width of [1440, 1280, 768, 390]) {
    await page.setViewportSize({ width, height: 900 })
    for (const path of ALL) {
      await settle(page, path)
      const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
      expect(over, `${path} at ${width}px overflows by ${over}px`).toBeLessThanOrEqual(0)
    }
  }
})

test('every page offers skip-to-content as its first tab stop', async ({ page }) => {
  for (const path of ['/dashboard', '/farms', '/farmer', '/farmer/journal']) {
    await settle(page, path)
    await page.keyboard.press('Tab')
    const first = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null
      return { cls: String(el?.className ?? ''), href: el?.getAttribute('href') ?? '' }
    })
    expect(first.cls, `first tab stop on ${path}`).toContain('skip-link')
    expect(first.href).toBe('#main')
  }
})

test('no raw uuid, ISO timestamp or database field name is on screen', async ({ page }) => {
  test.setTimeout(180_000)
  const UUID = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i
  const ISO = /\d{4}-\d{2}-\d{2}T[\d:.]+(Z|[+-]\d{2}:?\d{2})/
  const SNAKE = /\b[a-z]+_[a-z_]{2,}\b/
  for (const path of ALL) {
    await settle(page, path)
    const text = await page.evaluate(() => document.body.innerText)
    expect(UUID.test(text), `${path} shows a raw uuid`).toBe(false)
    expect(ISO.test(text), `${path} shows a raw ISO timestamp`).toBe(false)
    expect(SNAKE.test(text), `${path} shows a database field name`).toBe(false)
  }
})
