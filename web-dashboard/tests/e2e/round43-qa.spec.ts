import { expect, test, type Page } from '@playwright/test'
import { axe, blocking } from './axe-helper'

/* Round 4.3 mock gate — the Management drawer on phones, the rail everywhere
 * else, the Farmer bottom navigation, and axe on the affected screens. Mock
 * mode has no metrics endpoint (every figure is null), so the metric wording
 * itself is covered by the DOM tests and the real-data gate. */

const SIDE = '.shell > aside.sidebar'
const menu = (page: Page) => page.getByRole('button', { name: 'Mở menu' })
const isOpen = (page: Page) => page.locator(SIDE).evaluate((el) => el.classList.contains('is-open'))
const focusInDrawer = (page: Page) => page.evaluate((sel) => document.querySelector(sel)!.contains(document.activeElement), SIDE)

for (const vw of [768, 430, 390]) {
  test.describe(`Management drawer at ${vw}px`, () => {
    test.beforeEach(async ({ page }) => {
      await page.setViewportSize({ width: vw, height: 844 })
      await page.goto('/dashboard')
      await expect(page.locator('main h1').first()).toBeVisible()
    })

    test('closed: no backdrop, and Tab never enters the drawer', async ({ page }) => {
      await expect(page.getByTestId('drawer-backdrop')).toHaveCount(0)
      await expect(menu(page)).toHaveAttribute('aria-expanded', 'false')
      for (let i = 0; i < 12; i++) {
        await page.keyboard.press('Tab')
        expect(await focusInDrawer(page), `Tab ${i + 1}`).toBe(false)
      }
    })

    test('open: backdrop covers the workspace, focus is in the drawer, workspace inert, body locked', async ({ page }) => {
      await menu(page).click()
      const backdrop = page.getByTestId('drawer-backdrop')
      await expect(backdrop).toBeVisible()
      const box = (await backdrop.boundingBox())!
      expect(box.width).toBeGreaterThanOrEqual(vw - 1)
      await expect(page.getByRole('button', { name: 'Đóng menu' })).toBeFocused()
      await expect(page.locator('.shell > .main')).toHaveAttribute('inert', '')
      expect(await page.evaluate(() => getComputedStyle(document.body).overflow)).toBe('hidden')
      await expect(page.locator(SIDE)).toHaveAttribute('role', 'dialog')
      const target = await page.getByRole('button', { name: 'Đóng menu' }).boundingBox()
      expect(target!.width).toBeGreaterThanOrEqual(44)
      expect(target!.height).toBeGreaterThanOrEqual(44)
    })

    test('a tap on the backdrop closes it and focus returns to the menu button', async ({ page }) => {
      await menu(page).click()
      await page.mouse.click(vw - 20, 400) // outside the 250px drawer
      await expect.poll(() => isOpen(page)).toBe(false)
      await expect(page.getByTestId('drawer-backdrop')).toHaveCount(0)
      await expect(menu(page)).toBeFocused()
      expect(await page.evaluate(() => getComputedStyle(document.body).overflow)).not.toBe('hidden')
    })

    test('Escape closes it and focus returns', async ({ page }) => {
      await menu(page).click()
      await page.keyboard.press('Escape')
      await expect.poll(() => isOpen(page)).toBe(false)
      await expect(menu(page)).toBeFocused()
    })

    test('Tab and Shift+Tab stay inside the open drawer', async ({ page }) => {
      await menu(page).click()
      for (let i = 0; i < 20; i++) {
        await page.keyboard.press('Tab')
        expect(await focusInDrawer(page), `Tab ${i + 1}`).toBe(true)
      }
      for (let i = 0; i < 6; i++) {
        await page.keyboard.press('Shift+Tab')
        expect(await focusInDrawer(page), `Shift+Tab ${i + 1}`).toBe(true)
      }
    })

    test('choosing a destination navigates and closes the drawer', async ({ page }) => {
      await menu(page).click()
      const link = page.locator(`${SIDE} nav a`).nth(1)
      const to = await link.getAttribute('href')
      await link.click()
      await expect(page).toHaveURL(new RegExp(`${to}$`))
      await expect.poll(() => isOpen(page)).toBe(false)
      await expect(page.getByTestId('drawer-backdrop')).toHaveCount(0)
    })

    test('axe: no serious or critical violation with the drawer open', async ({ page }) => {
      await menu(page).click()
      await expect(page.getByRole('button', { name: 'Đóng menu' })).toBeFocused()
      const v = blocking(await axe(page))
      expect(v, JSON.stringify(v, null, 2)).toEqual([])
    })
  })
}

for (const vw of [1363, 1024]) {
  test(`${vw}px: the rail is static — no close button, no backdrop, never inert`, async ({ page }) => {
    await page.setViewportSize({ width: vw, height: 900 })
    await page.goto('/dashboard')
    await expect(page.locator('main h1').first()).toBeVisible()
    await expect(page.getByRole('button', { name: 'Đóng menu' })).toBeHidden()
    await expect(menu(page)).toBeHidden()
    await expect(page.getByTestId('drawer-backdrop')).toHaveCount(0)
    expect(await page.locator(SIDE).getAttribute('inert')).toBeNull()
    expect(await page.locator(SIDE).getAttribute('role')).toBeNull()
    await expect(page.locator(`${SIDE} nav a`).first()).toBeVisible()
  })
}

test('Farmer 390px: bottom navigation unchanged, no drawer chrome at all', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/farmer/performance')
  await expect(page.locator('main h1').first()).toBeVisible()
  const bottom = page.locator('.fw-bottom')
  await expect(bottom).toBeVisible()
  await expect(bottom.locator('a')).toHaveCount(6)
  await expect(bottom.locator('a[aria-current="page"]')).toHaveText('Hiệu suất')
  await expect(page.locator('.fw-shell > aside.sidebar')).toBeHidden()
  await expect(page.getByRole('button', { name: 'Đóng menu' })).toHaveCount(0)
  await expect(page.getByTestId('drawer-backdrop')).toHaveCount(0)
  await bottom.getByRole('link', { name: 'Nhật ký' }).click()
  await expect(page).toHaveURL(/\/farmer\/journal$/)
})

test('Farmer Performance (mock, all null): every metric says it is missing, never 0', async ({ page }) => {
  await page.goto('/farmer/crop-seasons/crop-demo-01/performance')
  await expect(page.getByRole('heading', { name: 'Hiệu suất vụ này' })).toBeVisible()
  await expect(page.locator('.fw-metric__empty')).toHaveCount(4)
  await expect(page.locator('.fw-mrow__value')).toHaveCount(0)
  const btn = page.getByRole('button', { name: /Cách tính và dữ liệu sử dụng/ }).first()
  await expect(btn).toHaveAttribute('aria-expanded', 'false')
  await btn.click()
  await expect(btn).toHaveAttribute('aria-expanded', 'true')
})

for (const path of ['/farmer', '/farmer/performance', '/farmer/carbon', '/dashboard', '/performance']) {
  for (const vw of [1363, 390]) {
    test(`axe ${path} at ${vw}px: no serious or critical violation`, async ({ page }) => {
      await page.setViewportSize({ width: vw, height: 900 })
      await page.goto(path)
      await expect(page.locator('main h1').first()).toBeVisible()
      await page.waitForLoadState('networkidle')
      const v = blocking(await axe(page))
      expect(v, JSON.stringify(v, null, 2)).toEqual([])
    })
  }
}
