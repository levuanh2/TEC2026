import { expect, test } from './fixtures'
import AxeBuilder from 'axe-core'

const routes = [
  '/dashboard', '/farms', '/seasons', '/data-gaps', '/carbon', '/performance', '/mrv',
  '/farmer', '/farmer/journal', '/farmer/farms', '/farmer/performance', '/farmer/carbon', '/farmer/account',
]

for (const width of [1440, 1024, 768, 390, 360]) {
  test(`visual refresh: routes remain usable at ${width}px`, async ({ page }) => {
    test.setTimeout(90_000)
    await page.setViewportSize({ width, height: 960 })
    await page.emulateMedia({ reducedMotion: 'reduce' })
    for (const route of routes) {
      await page.goto(route)
      await expect(page.locator('h1')).toBeVisible()
      await expect(page.locator('h1')).toHaveCount(1)
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), { message: `${route} overflows at ${width}px` }).toBe(true)
      await expect(page.locator('main#main')).toBeVisible()
      if (route === '/dashboard' || route === '/farmer') {
        await expect(page.locator('.field-banner')).toBeVisible()
        await expect.poll(() => page.locator('.field-banner img').evaluate((img) => (img as HTMLImageElement).naturalWidth)).toBeGreaterThan(0)
        await page.screenshot({ path: `test-results/refresh-${route === '/farmer' ? 'farmer' : 'management'}-${width}.png`, fullPage: true })
      }
    }
  })
}

test('visual refresh: home accessibility and reduced motion', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  for (const route of ['/dashboard', '/farmer']) {
    await page.goto(route)
    await expect(page.locator('h1')).toBeVisible()
    await page.addScriptTag({ content: AxeBuilder.source })
    const violations = await page.evaluate(async () => {
      const result = await window.axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa'] } })
      return result.violations.map((v) => ({ id: v.id, nodes: v.nodes.map((n) => n.target) }))
    })
    expect(violations).toEqual([])
    expect(await page.locator('.field-banner').evaluate((el) => getComputedStyle(el).animationName)).toBe('none')
  }
})

test('visual refresh: entry animation leaves fixed overlays anchored to the viewport', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'no-preference' })
  await page.goto('/dashboard')
  await expect(page.locator('.ops')).toBeVisible()
  await expect.poll(() => page.locator('.ops').evaluate((el) => getComputedStyle(el).transform)).toBe('none')
  await page.goto('/farmer/journal')
  await expect(page.locator('h1')).toBeVisible()
  await page.getByRole('button', { name: 'Ghi hoạt động', exact: true }).first().click()
  const dialog = page.getByRole('dialog', { name: 'Ghi hoạt động', exact: true })
  await expect(dialog).toBeVisible()
  await expect.poll(() => dialog.evaluate((el) => getComputedStyle(el).transform)).toBe('none')
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
})

test('visual refresh: login artwork, keyboard access and mobile layout', async ({ page }) => {
  test.setTimeout(60_000)
  await page.emulateMedia({ reducedMotion: 'reduce' })
  for (const width of [1440, 1024, 768, 390, 360]) {
    await page.setViewportSize({ width, height: 960 })
    await page.goto('/login')
    await expect(page.getByRole('heading', { name: 'Đăng nhập', exact: true })).toBeVisible()
    await page.locator('.login-landscape__image').evaluate((img) => (img as HTMLImageElement).decode())
    await expect(page.getByLabel('Email', { exact: true })).toBeVisible()
    await expect(page.getByLabel('Mật khẩu', { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Đăng nhập', exact: true })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.addScriptTag({ content: AxeBuilder.source })
    const violations = await page.evaluate(async () => (await window.axe.run(document, {
      runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa'] },
    })).violations.map((v) => ({ id: v.id, nodes: v.nodes.map((n) => n.target) })))
    expect(violations).toEqual([])
    await page.screenshot({ path: `test-results/refresh-login-${width}.png`, fullPage: true })
    await page.keyboard.press('Tab')
    await expect(page.getByLabel('Email', { exact: true })).toBeFocused()
    await page.keyboard.press('Tab')
    await expect(page.getByLabel('Mật khẩu', { exact: true })).toBeFocused()
    expect(await page.locator('.login-slogan span').first().evaluate((el) => getComputedStyle(el).animationName)).toBe('none')
  }
})
