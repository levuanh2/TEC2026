import { expect, test, type Page } from '@playwright/test'

const noHorizontalOverflow = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)

/** Quick Entry from Home, where the fixture has two active seasons (like the
 * real QA farmer): the picker appears first and the chosen season is the one
 * the form is opened for. */
async function quickEntry(page: Page, label: string, season = 'Hè Thu 2026') {
  await page.getByRole('button', { name: label, exact: true }).click()
  const picker = page.getByRole('dialog', { name: 'Chọn vụ cần ghi' })
  await expect(picker).toBeVisible()
  await picker.getByRole('button', { name: new RegExp(season) }).click()
  await expect(picker).toHaveCount(0)
}

test('Farmer V2 shell, navigation, pages and activity forms render correctly (mock data)', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/farmer')
  await expect(page.getByRole('heading', { name: 'Hôm nay trên ruộng của bạn', level: 1 })).toBeVisible()
  await expect(page.getByText('Vụ đang canh tác', { exact: true })).toBeVisible()

  // V2 shell: grouped desktop nav with one icon family (SVG, no emoji glyphs).
  const nav = page.getByRole('navigation', { name: 'Điều hướng nông hộ', exact: true })
  for (const label of ['Tổng quan', 'Nhật ký', 'Ruộng', 'Hiệu suất', 'Tôi']) {
    await expect(nav.getByRole('link', { name: label, exact: true })).toBeVisible()
  }
  await expect(nav.getByRole('link', { name: 'Tổng quan', exact: true })).toHaveAttribute('aria-current', 'page')
  await expect(nav.locator('svg')).toHaveCount(5)
  await expect(page.getByRole('navigation', { name: 'Điều hướng nông hộ trên điện thoại' })).toBeHidden()

  for (const label of ['Gieo sạ', 'Bón phân', 'Tưới nước', 'Thuốc BVTV', 'Rơm rạ', 'Thu hoạch']) {
    await expect(page.getByRole('button', { name: label, exact: true })).toBeEnabled()
  }
  await page.screenshot({ path: 'test-results/farmer-v2-home-1440.png', fullPage: true })

  await quickEntry(page, 'Bón phân')
  const fertilizer = page.getByRole('dialog', { name: 'Bón phân' })
  await expect(fertilizer).toBeVisible()
  await expect(fertilizer.locator('.form-field__required').first()).toBeVisible()
  await expect(fertilizer.getByText('Không bắt buộc').first()).toBeVisible()
  await page.getByRole('button', { name: 'Hủy' }).click()
  await expect(fertilizer).toHaveCount(0)

  await quickEntry(page, 'Tưới nước')
  await expect(page.getByRole('dialog', { name: 'Ghi tưới nước' })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog', { name: 'Ghi tưới nước' })).toHaveCount(0)

  await quickEntry(page, 'Thu hoạch')
  await expect(page.getByRole('dialog', { name: 'Ghi thu hoạch' })).toBeVisible()
  await page.getByRole('button', { name: 'Hủy' }).click()
  await expect(page.getByRole('dialog', { name: 'Ghi thu hoạch' })).toHaveCount(0)

  await quickEntry(page, 'Gieo sạ')
  await expect(page.getByRole('dialog', { name: 'Gieo sạ' })).toBeVisible()
  await page.getByRole('button', { name: 'Hủy' }).click()
  await expect(page.getByRole('dialog', { name: 'Gieo sạ' })).toHaveCount(0)

  await quickEntry(page, 'Thuốc BVTV')
  await expect(page.getByRole('dialog', { name: 'Thuốc BVTV' })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog', { name: 'Thuốc BVTV' })).toHaveCount(0)

  await quickEntry(page, 'Rơm rạ')
  await expect(page.getByRole('dialog', { name: 'Rơm rạ' })).toBeVisible()
  // Selecting "Đốt" (burned) shows a neutral factual notice, never a fake CO2e number.
  await page.getByLabel('Cách xử lý rơm rạ').selectOption('burned')
  await expect(page.getByText('sẽ được ghi nhận cho tính toán phát thải khi phương pháp tính khả dụng')).toBeVisible()
  await page.getByRole('button', { name: 'Hủy' }).click()
  await expect(page.getByRole('dialog', { name: 'Rơm rạ' })).toHaveCount(0)

  // CV: picker opens, analyze stays disabled with no file, disclaimer always visible.
  await page.getByRole('button', { name: 'Kiểm tra lá lúa' }).click()
  await expect(page.getByRole('dialog', { name: 'Kiểm tra lá lúa' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Phân tích ảnh' })).toBeDisabled()
  await expect(page.getByText('Kết quả chỉ mang tính hỗ trợ, chưa được xác nhận thực địa.')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog', { name: 'Kiểm tra lá lúa' })).toHaveCount(0)

  // Two active seasons: Quick Entry must ask which one, and open the form for
  // the season actually chosen — not silently assume the primary one.
  await page.getByRole('button', { name: 'Tưới nước', exact: true }).click()
  const picker = page.getByRole('dialog', { name: 'Chọn vụ cần ghi' })
  await expect(picker).toBeVisible()
  await expect(picker.getByRole('button')).toHaveCount(3)  // 2 seasons + close
  await picker.getByRole('button', { name: /Thu Đông 2026/ }).click()
  const forSecondSeason = page.getByRole('dialog', { name: 'Ghi tưới nước' })
  await expect(forSecondSeason).toBeVisible()
  // The form's own context line, not the sheet subtitle: it is what tells the
  // farmer which season this entry will be written to.
  await expect(forSecondSeason.locator('.fw-form__ctx')).toHaveText(/Thu Đông 2026 · Thửa A-02/)
  await page.getByRole('button', { name: 'Hủy' }).click()
  await expect(forSecondSeason).toHaveCount(0)

  await nav.getByRole('link', { name: 'Nhật ký', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Nhật ký canh tác', level: 1 })).toBeVisible()
  await expect(nav.getByRole('link', { name: 'Nhật ký', exact: true })).toHaveAttribute('aria-current', 'page')

  await nav.getByRole('link', { name: 'Ruộng', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Các ruộng trong phạm vi của bạn', level: 1 })).toBeVisible()
  await expect(page.getByText(/thửa$/).first()).toBeVisible()
  await page.getByRole('link', { name: 'Xem ruộng' }).first().click()
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  await expect(page.getByRole('navigation', { name: 'Breadcrumb' }).getByRole('link', { name: 'Ruộng của tôi' })).toBeVisible()
  // Scoped to the plot card: the topbar season chip and the season card also carry the plot name.
  await page.locator('.fw-plot', { hasText: 'Thửa A-01' }).click()
  await expect(page.getByRole('heading', { name: 'Thửa A-01', level: 1 })).toBeVisible()
  // .last(): the topbar season chip and the "current season" card also carry the name.
  await page.getByRole('link', { name: 'Hè Thu 2026' }).last().click()
  await expect(page.getByRole('tab', { name: 'Nhật ký' })).toBeVisible()
  await expect(page.getByRole('tab', { name: 'Tổng quan' })).toHaveAttribute('aria-current', 'page')
  // Season pages keep the "Ruộng" nav destination active.
  await expect(nav.getByRole('link', { name: 'Ruộng', exact: true })).toHaveAttribute('aria-current', 'page')
  await expect(page.getByRole('heading', { name: 'Mức đầy đủ dữ liệu' })).toBeVisible()

  await page.getByRole('tab', { name: 'Nhật ký' }).click()
  await expect(page.getByRole('heading', { name: 'Nhật ký của vụ này' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Ghi hoạt động' }).first()).toBeVisible()
  await page.locator('.fw-entry__open').first().click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Chỉnh sửa' })).toBeVisible()
  await page.getByRole('button', { name: 'Xóa hoạt động' }).click()
  await expect(page.getByRole('alertdialog')).toBeVisible()
  await page.getByRole('alertdialog').getByRole('button', { name: 'Hủy' }).click()
  await expect(page.getByRole('alertdialog')).toHaveCount(0)
  await page.getByRole('button', { name: 'Đóng' }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)

  await page.getByRole('tab', { name: 'Hiệu suất' }).click()
  await expect(page.getByRole('heading', { name: 'Hiệu suất vụ này' })).toBeVisible()
  // Mock metrics are all null: every card must say so, never show a fabricated 0.
  await expect(page.locator('.fw-metric__empty')).toHaveCount(4)

  await page.getByRole('tab', { name: 'Carbon' }).click()
  await expect(page.getByText('Chưa có kết quả phát thải hợp lệ cho vụ này')).toBeVisible()
  await expect(page.getByRole('button', { name: /Tính lại/i })).toHaveCount(0)

  await nav.getByRole('link', { name: 'Hiệu suất', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Hiệu suất vụ của tôi', level: 1 })).toBeVisible()
  await nav.getByRole('link', { name: 'Tôi', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Phạm vi truy cập' })).toBeVisible()

  for (const width of [1024, 768, 390]) {
    await page.setViewportSize({ width, height: 844 })
    await expect.poll(() => noHorizontalOverflow(page)).toBe(true)
  }

  // 390: real bottom navigation, no squeezed sidebar.
  await page.goto('/farmer')
  const bottom = page.getByRole('navigation', { name: 'Điều hướng nông hộ trên điện thoại' })
  await expect(bottom).toBeVisible()
  await expect(nav).toBeHidden()
  await expect(bottom.getByRole('link')).toHaveCount(5)
  await expect(bottom.getByRole('link', { name: 'Tổng quan' })).toHaveAttribute('aria-current', 'page')
  await expect.poll(() => noHorizontalOverflow(page)).toBe(true)
  await page.screenshot({ path: 'test-results/farmer-v2-home-390.png', fullPage: true })

  await quickEntry(page, 'Bón phân')
  await expect(page.getByRole('dialog', { name: 'Bón phân' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Lưu hoạt động' })).toBeInViewport()
  await expect.poll(() => noHorizontalOverflow(page)).toBe(true)
  await page.keyboard.press('Escape')

  await bottom.getByRole('link', { name: 'Nhật ký' }).click()
  await expect(page.getByRole('heading', { name: 'Nhật ký canh tác', level: 1 })).toBeVisible()
  await expect(bottom.getByRole('link', { name: 'Nhật ký' })).toHaveAttribute('aria-current', 'page')
  await expect.poll(() => noHorizontalOverflow(page)).toBe(true)
})
