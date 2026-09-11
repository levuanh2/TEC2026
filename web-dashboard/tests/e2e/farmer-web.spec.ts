import { expect, test } from '@playwright/test'

test('Farmer shell navigation and Quick Entry write UI render correctly (mock data)', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/farmer')
  await expect(page.getByRole('heading', { name: 'Hôm nay trên ruộng của bạn', level: 1 })).toBeVisible()
  await expect(page.getByText('Vụ đang canh tác', { exact: true })).toBeVisible()

  // FW-2 Part 3: seeding/pesticide/straw_management are no longer "Sắp có" —
  // all six Quick Entry types are enabled buttons.
  await expect(page.getByRole('button', { name: 'Gieo sạ', exact: true })).toBeEnabled()
  await expect(page.getByRole('button', { name: 'Bón phân', exact: true })).toBeEnabled()
  await expect(page.getByRole('button', { name: 'Tưới nước', exact: true })).toBeEnabled()
  await expect(page.getByRole('button', { name: 'Thuốc BVTV', exact: true })).toBeEnabled()
  await expect(page.getByRole('button', { name: 'Rơm rạ', exact: true })).toBeEnabled()
  await expect(page.getByRole('button', { name: 'Thu hoạch', exact: true })).toBeEnabled()
  await page.screenshot({ path: 'test-results/farmer-home-1440.png', fullPage: true })

  await page.getByRole('button', { name: 'Bón phân', exact: true }).click()
  await expect(page.getByRole('dialog', { name: 'Bón phân' })).toBeVisible()
  await page.screenshot({ path: 'test-results/farmer-fertilizer-form-1440.png', fullPage: true })
  await page.getByRole('button', { name: 'Hủy' }).click()
  await expect(page.getByRole('dialog', { name: 'Bón phân' })).toHaveCount(0)

  await page.getByRole('button', { name: 'Tưới nước', exact: true }).click()
  await expect(page.getByRole('dialog', { name: 'Ghi tưới nước' })).toBeVisible()
  await page.screenshot({ path: 'test-results/farmer-irrigation-form-1440.png', fullPage: true })
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog', { name: 'Ghi tưới nước' })).toHaveCount(0)

  await page.getByRole('button', { name: 'Thu hoạch', exact: true }).click()
  await expect(page.getByRole('dialog', { name: 'Ghi thu hoạch' })).toBeVisible()
  await page.screenshot({ path: 'test-results/farmer-harvest-form-1440.png', fullPage: true })
  await page.getByRole('button', { name: 'Hủy' }).click()
  await expect(page.getByRole('dialog', { name: 'Ghi thu hoạch' })).toHaveCount(0)

  // FW-2 Part 3: seeding / pesticide / straw_management forms.
  await page.getByRole('button', { name: 'Gieo sạ', exact: true }).click()
  await expect(page.getByRole('dialog', { name: 'Gieo sạ' })).toBeVisible()
  await page.screenshot({ path: 'test-results/farmer-seeding-form-1440.png', fullPage: true })
  await page.getByRole('button', { name: 'Hủy' }).click()
  await expect(page.getByRole('dialog', { name: 'Gieo sạ' })).toHaveCount(0)

  await page.getByRole('button', { name: 'Thuốc BVTV', exact: true }).click()
  await expect(page.getByRole('dialog', { name: 'Thuốc BVTV' })).toBeVisible()
  await page.screenshot({ path: 'test-results/farmer-pesticide-form-1440.png', fullPage: true })
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog', { name: 'Thuốc BVTV' })).toHaveCount(0)

  await page.getByRole('button', { name: 'Rơm rạ', exact: true }).click()
  await expect(page.getByRole('dialog', { name: 'Rơm rạ' })).toBeVisible()
  // Selecting "Đốt" (burned) shows a neutral factual notice, never a fake CO2e number.
  await page.getByLabel('Cách xử lý rơm rạ').selectOption('burned')
  await expect(page.getByText('sẽ được ghi nhận cho tính toán phát thải khi phương pháp tính khả dụng')).toBeVisible()
  await page.screenshot({ path: 'test-results/farmer-straw-form-1440.png', fullPage: true })
  await page.getByRole('button', { name: 'Hủy' }).click()
  await expect(page.getByRole('dialog', { name: 'Rơm rạ' })).toHaveCount(0)

  // M03 CV entry point (brief FW M03 §19) — opens, shows the picker, closes
  // cleanly. No file is chosen: usingMockData guards uploadAndInferLeaf from
  // ever hitting the real API in mock mode.
  await page.getByRole('button', { name: 'Kiểm tra lá lúa' }).click()
  await expect(page.getByRole('dialog', { name: 'Kiểm tra lá lúa' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Phân tích ảnh' })).toBeDisabled()
  await page.screenshot({ path: 'test-results/farmer-cv-check-1440.png', fullPage: true })
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog', { name: 'Kiểm tra lá lúa' })).toHaveCount(0)

  await page.getByRole('link', { name: /Ruộng/ }).first().click()
  await expect(page.getByRole('heading', { name: 'Các ruộng trong phạm vi của bạn', level: 1 })).toBeVisible()
  await page.screenshot({ path: 'test-results/farmer-farms-1440.png', fullPage: true })
  await page.getByRole('link', { name: 'Thửa A-01' }).click()
  await expect(page.getByRole('heading', { name: 'Thửa A-01', level: 1 })).toBeVisible()
  await page.screenshot({ path: 'test-results/farmer-plot-1440.png', fullPage: true })
  await page.getByRole('link', { name: 'Hè Thu 2026' }).click()
  await expect(page.getByRole('tab', { name: 'Nhật ký' })).toBeVisible()
  await page.screenshot({ path: 'test-results/farmer-season-1440.png', fullPage: true })

  await page.getByRole('tab', { name: 'Nhật ký' }).click()
  await expect(page.getByRole('heading', { name: 'Nhật ký canh tác' })).toBeVisible()
  await expect(page.getByRole('button', { name: '+ Ghi hoạt động' })).toBeVisible()
  await page.screenshot({ path: 'test-results/farmer-journal-1440.png', fullPage: true })

  // Journal row detail drawer -> supported-type Edit/Delete affordances (FW-2 §19/§22).
  await page.getByRole('button', { name: /Tưới nước|irrigation/i }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.screenshot({ path: 'test-results/farmer-journal-detail-1440.png', fullPage: true })
  await expect(page.getByRole('button', { name: 'Chỉnh sửa' })).toBeVisible()
  await page.getByRole('button', { name: 'Xóa hoạt động' }).click()
  await expect(page.getByRole('alertdialog')).toBeVisible()
  await page.screenshot({ path: 'test-results/farmer-delete-confirm-1440.png', fullPage: true })
  await page.getByRole('alertdialog').getByRole('button', { name: 'Hủy' }).click()
  await expect(page.getByRole('alertdialog')).toHaveCount(0)
  await page.getByRole('button', { name: 'Đóng' }).click()

  await page.getByRole('tab', { name: 'Hiệu suất' }).click()
  await expect(page.getByRole('heading', { name: 'Hiệu suất vụ này' })).toBeVisible()
  await page.screenshot({ path: 'test-results/farmer-performance-1440.png', fullPage: true })

  await page.getByRole('tab', { name: 'Carbon' }).click()
  await expect(page.getByText('Chưa có kết quả Carbon')).toBeVisible()
  await expect(page.getByRole('button', { name: /Tính lại/i })).toHaveCount(0)
  await page.screenshot({ path: 'test-results/farmer-carbon-1440.png', fullPage: true })
  for (const width of [1024, 768, 390]) {
    await page.setViewportSize({ width, height: 844 })
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  }
  await page.screenshot({ path: 'test-results/farmer-carbon-390.png', fullPage: true })

  await page.goto('/farmer')
  await page.screenshot({ path: 'test-results/farmer-home-390.png', fullPage: true })
  await page.getByRole('button', { name: 'Bón phân', exact: true }).click()
  await expect(page.getByRole('dialog', { name: 'Bón phân' })).toBeVisible()
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: 'test-results/farmer-fertilizer-form-390.png', fullPage: true })
  await page.keyboard.press('Escape')

  await page.getByRole('button', { name: 'Thu hoạch', exact: true }).click()
  await expect(page.getByRole('dialog', { name: 'Ghi thu hoạch' })).toBeVisible()
  await page.screenshot({ path: 'test-results/farmer-harvest-form-390.png', fullPage: true })
  await page.keyboard.press('Escape')

  await page.getByRole('button', { name: 'Kiểm tra lá lúa' }).click()
  await expect(page.getByRole('dialog', { name: 'Kiểm tra lá lúa' })).toBeVisible()
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: 'test-results/farmer-cv-check-390.png', fullPage: true })
})
