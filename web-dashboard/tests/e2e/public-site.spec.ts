import { expect, test } from './fixtures'
import axe from 'axe-core'

const paths = ['/', '/nen-tang', '/dich-vu', '/bao-cao', '/bang-gia', '/tin-tuc', '/tin-tuc/du-lieu-canh-tac-va-ho-so-mrv']

for (const width of [1440, 1024, 768, 390, 360]) {
  test(`public pages: usable and no private API calls at ${width}px`, async ({ page }) => {
    test.setTimeout(90_000)
    await page.setViewportSize({ width, height: 960 })
    await page.emulateMedia({ reducedMotion: 'reduce' })
    const privateRequests: string[] = []
    page.on('request', (request) => { if (/\/v1\/|\/health(?:\?|$)/.test(request.url())) privateRequests.push(request.url()) })
    for (const path of paths) {
      await page.goto(path)
      await expect(page.locator('h1')).toBeVisible()
      await expect(page.locator('h1')).toHaveCount(1)
      await expect(page.locator('.public-site')).toBeVisible()
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${path} overflow at ${width}`).toBe(true)
      await expect(page.locator('.shell, .fw-shell')).toHaveCount(0)
      if (path === '/') {
        await page.locator('.pub-hero__image').evaluate((el) => (el as HTMLImageElement).decode())
        await page.screenshot({ path: `test-results/public-home-${width}.png`, fullPage: true })
      }
      if (path === '/bang-gia') {
        await expect(page.locator('.pub-plan')).toHaveCount(6)
        await page.screenshot({ path: `test-results/public-pricing-${width}.png`, fullPage: true })
      }
    }
    expect(privateRequests).toEqual([])
  })
}

test('public navigation leads to content, sign-in and back home', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 960 })
  await page.goto('/')
  const navigation = page.getByRole('navigation', { name: 'Điều hướng trang giới thiệu' })
  for (const [name, path] of [['Nền tảng', '/nen-tang'], ['Dịch vụ', '/dich-vu'], ['Báo cáo', '/bao-cao'], ['Bảng giá', '/bang-gia'], ['Tin tức', '/tin-tuc']]) {
    await navigation.getByRole('link', { name, exact: true }).click()
    await expect(page).toHaveURL(new RegExp(`${path}$`))
    await expect(navigation.getByRole('link', { name, exact: true })).toHaveAttribute('aria-current', 'page')
    await expect(page.locator('h1')).toBeVisible()
  }
  await page.locator('.pub-header').getByRole('link', { name: 'Đăng nhập', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Đăng nhập', exact: true })).toBeVisible()
  await page.getByRole('link', { name: /Về trang chủ AgriCarbon/ }).click()
  await expect(page).toHaveURL(/\/$/)
  await expect(page.locator('.pub-hero')).toBeVisible()
  await page.goBack()
  await expect(page.getByRole('heading', { name: 'Đăng nhập', exact: true })).toBeVisible()
  await page.goto('/#%')
  await expect(page.locator('.pub-hero h1')).toBeVisible()
})

test('mobile menu closes on Escape and selecting a page', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  const button = page.getByRole('button', { name: 'Mở menu giới thiệu' })
  const navigation = page.getByRole('navigation', { name: 'Điều hướng trang giới thiệu' })
  await expect(navigation).toBeHidden()
  await button.click()
  await expect(navigation).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(navigation).toBeHidden()
  await expect(button).toBeFocused()
  await button.click()
  await navigation.getByRole('link', { name: 'Bảng giá', exact: true }).click()
  await expect(page.locator('h1')).toHaveText('Giải pháp theo quy mô của bạn.')
  await expect(navigation).toBeHidden()
  await expect(page.getByText('Chưa công bố giá', { exact: true })).toHaveCount(0)
  const farmer = page.getByRole('region', { name: 'Gói dành cho Nông hộ', exact: true })
  const cooperative = page.getByRole('region', { name: 'Gói dành cho Hợp tác xã', exact: true })
  await expect(farmer.getByRole('article')).toHaveCount(3)
  await expect(cooperative.getByRole('article')).toHaveCount(3)
  await expect(farmer.getByText('Miễn phí', { exact: true })).toHaveCount(1)
  await expect(farmer.getByText('999.990', { exact: true })).toHaveCount(1)
  await expect(farmer.getByText('1.999.990', { exact: true })).toHaveCount(1)
  await expect(cooperative.getByText('Miễn phí', { exact: true })).toHaveCount(1)
  await expect(cooperative.getByText('14.990.000', { exact: true })).toHaveCount(1)
  await expect(cooperative.getByText('49.990.000', { exact: true })).toHaveCount(1)
  await expect(cooperative.getByText('Quản lý nông hộ, xuất MRV 300 lượt', { exact: true })).toHaveCount(1)
  await expect(page.getByText('Phổ biến nhất', { exact: true })).toHaveCount(2)
  await expect(farmer.getByRole('link', { name: 'Chọn gói FREE — Nông hộ', exact: true })).toHaveAttribute('href', '/chon-goi?audience=nong-ho&plan=FREE')
  await expect(cooperative.getByRole('link', { name: 'Mua ngay PLUS — Hợp tác xã', exact: true })).toHaveAttribute('href', '/chon-goi?audience=hop-tac-xa&plan=PLUS')
  await page.getByRole('link', { name: 'Cho hợp tác xã', exact: true }).click()
  await expect(page).toHaveURL(/\/bang-gia#hop-tac-xa$/)
  await expect(cooperative.getByRole('heading', { name: 'Gói dành cho Hợp tác xã' })).toBeInViewport()
  await expect(navigation).toBeHidden()
})

test('workflow keyboard, news filters, articles and downloads work', async ({ page }) => {
  await page.goto('/nen-tang')
  const tabs = page.getByRole('tablist', { name: 'Các bước sử dụng AgriCarbon' })
  await tabs.getByRole('tab').first().focus()
  await page.keyboard.press('ArrowRight')
  await expect(tabs.getByRole('tab').nth(1)).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByRole('tabpanel')).toHaveCount(1)
  await page.keyboard.press('End')
  await expect(tabs.getByRole('tab').last()).toHaveAttribute('aria-selected', 'true')
  await page.goto('/dich-vu')
  await page.locator('.pub-footer').getByRole('link', { name: 'Nông hộ', exact: true }).click()
  await expect(page).toHaveURL(/\/dich-vu#nhat-ky$/)
  expect(await page.locator('#nhat-ky').evaluate((el) => el.getBoundingClientRect().top)).toBeGreaterThanOrEqual(70)
  expect(await page.locator('#nhat-ky').evaluate((el) => el.getBoundingClientRect().top)).toBeLessThan(160)
  await page.goto('/tin-tuc')
  await page.getByRole('button', { name: 'Carbon & MRV', exact: true }).click()
  await expect(page.locator('.pub-article-card')).toHaveCount(1)
  await page.locator('.pub-article-card a').click()
  await expect(page.locator('.pub-article > section')).toHaveCount(3)
  await page.getByRole('link', { name: '← Tất cả bài viết' }).click()
  await page.getByRole('searchbox', { name: 'Tìm bài viết' }).fill('tai nguyen')
  await expect(page.locator('.pub-article-card')).toHaveCount(1)
  await page.getByRole('searchbox', { name: 'Tìm bài viết' }).fill('no-matching-article-123')
  await expect(page.getByRole('heading', { name: 'Chưa tìm thấy bài viết phù hợp' })).toBeVisible()
  await page.getByRole('button', { name: 'Xem tất cả bài viết' }).click()
  await expect(page.locator('.pub-article-card')).toHaveCount(4)
  await page.goto('/bao-cao')
  const downloaded = page.waitForEvent('download')
  await page.getByRole('link', { name: 'Tải biểu mẫu CSV' }).click()
  const download = await downloaded
  expect(download.suggestedFilename()).toBe('agricarbon-mau-nhat-ky.csv')
  expect(await download.failure()).toBeNull()
  const introduction = await page.request.get('/downloads/agricarbon-gioi-thieu.md')
  expect(introduction.ok()).toBe(true)
  expect(await introduction.text()).toContain('Số hóa canh tác - Xanh hóa tương lai')
  await page.goto('/tin-tuc/khong-ton-tai')
  await expect(page.getByRole('heading', { name: 'Không tìm thấy bài viết' })).toBeVisible()
})

test('all six plan CTAs send signed-out visitors to login with their exact choice', async ({ page }) => {
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 960 })
    for (const [audience, key] of [['Nông hộ', 'nong-ho'], ['Hợp tác xã', 'hop-tac-xa']]) {
      for (const plan of ['FREE', 'PLUS', 'PRO']) {
        await page.goto('/bang-gia')
        await page.getByRole('link', { name: `${plan === 'FREE' ? 'Chọn gói' : 'Mua ngay'} ${plan} — ${audience}`, exact: true }).click()
        await expect(page.getByRole('heading', { name: 'Đăng nhập', exact: true })).toBeVisible()
        await expect(page).toHaveURL(/\/login\?next=/)
        expect(new URL(page.url()).searchParams.get('next')).toBe(`/chon-goi?audience=${key}&plan=${plan}`)
        await expect(page.getByText(`Bạn đã chọn gói ${plan} — ${audience}. Đăng nhập để tiếp tục với gói đã chọn.`, { exact: true })).toBeVisible()
      }
    }
  }
})

test('public pages meet automated WCAG checks on desktop and mobile', async ({ page }) => {
  test.setTimeout(90_000)
  await page.emulateMedia({ reducedMotion: 'reduce' })
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 960 })
    for (const path of paths) {
      await page.goto(path)
      await expect(page.locator('h1')).toBeVisible()
      await page.addScriptTag({ content: axe.source })
      const violations = await page.evaluate(async () => (await window.axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa'] } })).violations.map((item) => ({ id: item.id, nodes: item.nodes.map((node) => ({ target: node.target, reason: node.failureSummary })) })))
      expect(violations, `${path} at ${width}px`).toEqual([])
    }
  }
})
