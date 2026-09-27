import { expect, test } from './fixtures'

// Runs against the mock tenant (playwright.config.ts sets VITE_USE_MOCK_DATA=true),
// so this is the PUBLIC/MOCK browser smoke. A real authenticated run needs a
// Supabase session + live FastAPI and is tracked separately (NOT RUN here).

test('redesigned IA: no dead sidebar links, domain states, hierarchy drill-down', async ({ page }) => {
  await page.goto('/dashboard')
  // The landing screen is the operations queue now, not a second dashboard.
  await expect(page.getByRole('heading', { name: 'Hôm nay cần xử lý gì?', level: 1 })).toBeVisible()

  // No hardcoded hierarchy ids leak into the sidebar before the user is in context.
  const navHrefs = await page.locator('nav.nav a').evaluateAll((els) => els.map((e) => e.getAttribute('href')))
  expect(navHrefs).not.toContain('/plots/plot-demo-01')
  expect(navHrefs).not.toContain('/crop-seasons/crop-demo-01')

  // Farm → Plot → Crop Season hub (FR-1c-01).
  await page.getByRole('link', { name: 'Nông hộ' }).click()
  await expect(page.getByRole('heading', { name: 'Nông hộ', level: 1 })).toBeVisible()

  await page.locator('tbody tr').first().click()
  await expect(page.getByRole('heading', { name: 'Nguyễn Văn An', level: 1 })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Thửa ruộng' })).toBeVisible()

  await page.locator('tbody tr').first().click()
  await expect(page.getByRole('heading', { name: 'Thửa A-01', level: 1 })).toBeVisible()

  await page.locator('tbody tr').first().click()
  await expect(page.getByRole('heading', { name: 'Hè Thu 2026', level: 1 })).toBeVisible()

  // Crop Season hub tabs.
  await expect(page.getByRole('tab', { name: 'Tổng quan' })).toBeVisible()
  await page.getByRole('tab', { name: 'Hoạt động' }).click()
  await expect(page.getByRole('heading', { name: 'Nhật ký hoạt động' })).toBeVisible()
  await expect(page.getByText('Tưới AWD · 32 mm')).toBeVisible()

  await page.getByRole('tab', { name: 'Carbon' }).click()
  await expect(page.getByRole('heading', { name: 'Phát thải carbon' })).toBeVisible()

  // MRV workflow.
  await page.goto('/mrv')
  await expect(page.getByRole('heading', { name: 'Hồ sơ MRV', level: 1 })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Tiến trình 6 bước' })).toBeVisible()
  await expect(page.getByText('Chuẩn bị', { exact: true })).toBeVisible()
  await expect(page.getByText('Thẩm định', { exact: true })).toBeVisible()
  await expect(page.getByText('Hoàn thành').first()).toBeVisible()
  await expect(page.getByText('Đang thực hiện').first()).toBeVisible()

  // Unknown route → not-found state, not a blank screen.
  await page.goto('/no-such-page')
  await expect(page.getByText('Không tìm thấy trang')).toBeVisible()
})
