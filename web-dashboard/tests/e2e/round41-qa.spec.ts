import { expect, test, type Page } from '@playwright/test'
import { isInstitutionalGreen } from './round41-helpers'

/* Round 4.1 gates on the mock tenant — no credentials.
 *
 * The mock viewer belongs to no cooperative, so the /carbon action geometry
 * runs on real data in round41-real.spec.ts. Here: the institutional green
 * stays in navigation, and the irrigation form's disclosure means what it
 * says. Data-loss and decimal rules for the forms are DOM tests
 * (farmer/round41.dom.test.tsx, utils/demoMarker.test.ts). */

const S = 'crop-demo-01'
const TEXT = 0.04

test('the detector recognises Round 4 colours and passes the Round 4.1 slate', () => {
  // Round 4 values, as Chrome reports them: CTA fill, active-tab marker,
  // link ink (accent-deep), workspace accent — and the sidebar.
  for (const c of ['oklch(0.26 0.022 165)', 'oklch(0.3 0.02 165)', 'oklch(0.31 0.095 163)', 'oklch(0.45 0.13 160)', 'oklch(0.31 0.068 160)']) {
    expect(isInstitutionalGreen(c), c).toBe(true)
  }
  for (const c of ['oklch(0.28 0.035 257)', 'oklch(0.33 0.045 257)', 'oklch(0.34 0.05 257)', 'rgb(255, 255, 255)']) {
    expect(isInstitutionalGreen(c), c).toBe(false)
  }
})
const colours = (page: Page, selector: string) => page.locator(selector).first().evaluate((el) => {
  const cs = getComputedStyle(el)
  return { bg: cs.backgroundColor, border: cs.borderBottomColor, color: cs.color }
})

test('institutional green: in the Farmer navbar, not on the workspace CTA or active tab', async ({ page }) => {
  await page.goto('/farmer/journal')
  await expect(page.locator('main').getByRole('button', { name: 'Ghi hoạt động' }).first()).toBeVisible()

  const side = await colours(page, '.fw-side')
  expect(isInstitutionalGreen(side.bg), `navbar ${side.bg}`).toBe(true)

  const cta = await colours(page, 'main .fw-btn:not(.fw-btn--ghost):not(.fw-btn--soft)')
  expect(isInstitutionalGreen(cta.bg), `CTA fill ${cta.bg}`).toBe(false)
  expect(isInstitutionalGreen(cta.border), `CTA edge ${cta.border}`).toBe(false)

  const pill = await colours(page, 'main .fw-pill[aria-pressed="true"]')
  expect(isInstitutionalGreen(pill.border), `active filter marker ${pill.border}`).toBe(false)
})

test('institutional green: in the Management sidebar, not on the season tabs or buttons', async ({ page }) => {
  await page.goto(`/crop-seasons/${S}/carbon`)
  await expect(page.locator('.tab[aria-current="page"]').first()).toBeVisible()

  const side = await colours(page, '.sidebar')
  expect(isInstitutionalGreen(side.bg), `sidebar ${side.bg}`).toBe(true)

  const tab = await colours(page, '.tab[aria-current="page"]')
  expect(isInstitutionalGreen(tab.border), `active tab ${tab.border}`).toBe(false)
  expect(isInstitutionalGreen(tab.color, TEXT), `active tab ink ${tab.color}`).toBe(false)

  // Every filled button and every link the workspace draws.
  const leaks = await page.locator('main').evaluate((main) => [...main.querySelectorAll<HTMLElement>('.btn:not(.btn--ghost):not(.btn--quiet), a:not(.btn)')]
    .filter((el) => el.getBoundingClientRect().width > 0)
    .map((el) => { const cs = getComputedStyle(el); return `${el.textContent!.trim().slice(0, 30)}|${cs.backgroundColor}|${cs.color}` }))
  for (const l of leaks) {
    const [, bg, ink] = l.split('|')
    expect(isInstitutionalGreen(bg) || isInstitutionalGreen(ink, TEXT), l).toBe(false)
  }
})

test('irrigation form: essentials visible, the disclosure holds exactly what it names', async ({ page }) => {
  await page.goto('/farmer/journal')
  await page.locator('main').getByRole('button', { name: 'Ghi hoạt động' }).first().click()
  await page.getByRole('dialog').getByRole('button', { name: /^Tưới nước/ }).first().click()
  const form = page.getByRole('dialog').locator('form')
  const details = form.locator('details.fw-more')

  await expect(details).not.toHaveAttribute('open', '')
  await expect(details.locator('summary')).toContainText('Thông tin kỹ thuật và chi phí')
  await expect(details.locator('summary')).toContainText('Thời gian tưới, mực nước, máy bơm · chi phí')

  // Essentials and the farmer's own note: always on screen, never inside.
  for (const label of [/^Ngày thực hiện/, /^Hình thức tưới/, /^Lượng nước/, /^Ghi chú/]) {
    const input = form.getByLabel(label)
    await expect(input).toBeVisible()
    expect(await input.evaluate((el) => Boolean(el.closest('details')))).toBe(false)
  }
  // Nothing visible sits after the closed disclosure except the footer.
  const after = await details.evaluate((d) => {
    const out: string[] = []
    for (let n = d.nextElementSibling; n; n = n.nextElementSibling) if ((n as HTMLElement).offsetHeight && !n.matches('.fw-form__footer')) out.push(n.className)
    return out
  })
  expect(after).toEqual([])

  await details.locator('summary').click()
  for (const label of [/^Thời gian tưới/, /^Mực nước ruộng/, /^Chi phí/]) {
    const input = form.getByLabel(label)
    await expect(input).toBeVisible()
    expect(await input.evaluate((el) => Boolean(el.closest('details.fw-more')))).toBe(true)
  }
})
