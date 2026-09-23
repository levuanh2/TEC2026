import { expect, test, type Page } from '@playwright/test'

const noHorizontalOverflow = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)

/** Quick Entry from Home, where the fixture has two active seasons (like the
 * real QA farmer): the picker appears first and the chosen season is the one
 * the form is opened for. */
/** Round 4: every record starts from the one "Ghi hoạt động" entry point,
 *  whose first step is the activity picker. */
async function quickEntry(page: Page, label: string) {
  await page.getByRole('button', { name: 'Ghi hoạt động', exact: true }).first().click()
  const picker = page.getByRole('dialog', { name: 'Ghi hoạt động' })
  await expect(picker).toBeVisible()
  await picker.getByRole('button', { name: new RegExp(`^${label}`) }).click()
  await expect(picker).toHaveCount(0)
}

test('Farmer V2 shell, navigation, pages and activity forms render correctly (mock data)', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/farmer')
  await expect(page.getByRole('heading', { name: 'Hôm nay trên ruộng của bạn', level: 1 })).toBeVisible()
  // One context bar states which season this is — farm, plot, season, status,
  // day count and both dates. (Round 2 removed the separate ledger hero: it
  // repeated the season a third time and its 62px day count outweighed the
  // page's one action. The figure still never stands alone.)
  const ctx = page.locator('.fw-ctxbar')
  await expect(ctx).toHaveCount(1)
  await expect(ctx.getByText('ngày kể từ gieo sạ')).toBeVisible()
  await expect(page.locator('.fw-ledger')).toHaveCount(0)
  // Which of the two mock seasons is primary is business logic covered by the
  // unit tests; here it only has to be one of them, named once.
  await expect(ctx.locator('#fw-ctxbar-season')).toHaveText(/Hè Thu 2026|Thu Đông 2026/)

  // V2 shell: grouped desktop nav with one icon family (SVG, no emoji glyphs).
  const nav = page.getByRole('navigation', { name: 'Điều hướng nông hộ', exact: true })
  for (const label of ['Tổng quan', 'Nhật ký', 'Ruộng / Vụ mùa', 'Hiệu suất', 'Carbon', 'Tôi']) {
    await expect(nav.getByRole('link', { name: label, exact: true })).toBeVisible()
  }
  await expect(nav.getByRole('link', { name: 'Tổng quan', exact: true })).toHaveAttribute('aria-current', 'page')
  await expect(nav.locator('svg')).toHaveCount(6)
  await expect(page.getByRole('navigation', { name: 'Điều hướng nông hộ trên điện thoại' })).toBeHidden()

  // Round 4: Home has one next action; the six activity types live in the
  // picker that action opens, not as a second grid of buttons on the page.
  await expect(page.locator('main .fw-quick')).toHaveCount(0)
  await page.screenshot({ path: 'test-results/farmer-v2-home-1440.png', fullPage: true })
  await page.getByRole('button', { name: /Ghi hoạt động/ }).first().click()
  const homePicker = page.getByRole('dialog', { name: 'Ghi hoạt động' })
  for (const label of ['Gieo sạ', 'Bón phân', 'Tưới nước', 'Thuốc BVTV', 'Rơm rạ', 'Thu hoạch']) {
    await expect(homePicker.getByRole('button', { name: new RegExp(`^${label}`) })).toBeEnabled()
  }
  await page.keyboard.press('Escape')
  await expect(homePicker).toHaveCount(0)

  // The rest of the forms are reached the way a farmer records: from the journal.
  await page.goto('/farmer/journal')

  await quickEntry(page, 'Bón phân')
  const fertilizer = page.getByRole('dialog', { name: 'Bón phân' })
  await expect(fertilizer).toBeVisible()
  // V2: the form opens on the field operation, not on the schema. Only the two
  // required facts are on the primary screen; everything optional — cost, note
  // and the N/P/K methodology inputs — waits behind one collapsed disclosure.
  await expect(fertilizer.locator('.form-field__required').first()).toBeVisible()
  await expect(fertilizer.getByLabel(/Loại phân/)).toBeVisible()
  await expect(fertilizer.getByLabel(/Lượng bón/)).toBeVisible()
  await expect(fertilizer.getByText('Không bắt buộc').first()).toBeHidden()
  await fertilizer.getByText('Thông tin bổ sung').click()
  await expect(fertilizer.getByLabel(/Hàm lượng đạm/)).toBeVisible()
  await expect(fertilizer.getByText('Không bắt buộc').first()).toBeVisible()
  // The unit sits beside the value rather than inside the label.
  await expect(fertilizer.locator('.fw-num__unit', { hasText: 'kg' }).first()).toBeVisible()
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
  // Selecting "Đốt" (burned) states what actually happens — burning IS counted now
  // (its IPCC factors are verified) and needs the dry-matter fraction — but still
  // shows no CO2e number in the form, because only the server computes one.
  await page.getByLabel('Cách xử lý rơm rạ').selectOption('burned')
  await expect(page.getByText('Đốt rơm phát thải CH₄ và N₂O')).toBeVisible()
  await expect(page.getByText('Tỷ lệ chất khô của rơm').first()).toBeVisible()
  await page.getByRole('button', { name: 'Hủy' }).click()
  await expect(page.getByRole('dialog', { name: 'Rơm rạ' })).toHaveCount(0)

  // CV lives on the season page now (Home is one action only).
  await page.goto('/farmer/crop-seasons/crop-demo-01')
  // CV: picker opens, analyze stays disabled with no file, disclaimer always visible.
  await page.getByRole('button', { name: 'Kiểm tra lá lúa' }).click()
  await expect(page.getByRole('dialog', { name: 'Kiểm tra lá lúa' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Phân tích ảnh' })).toBeDisabled()
  await expect(page.getByText('Kết quả chỉ mang tính hỗ trợ, chưa được xác nhận thực địa.')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog', { name: 'Kiểm tra lá lúa' })).toHaveCount(0)

  // Two active seasons: the journal names which season a record goes to, and
  // the form opens for the season actually chosen — not the primary one.
  await page.goto('/farmer/journal')
  await page.getByRole('group', { name: 'Chọn vụ canh tác' }).getByRole('button', { name: /Thu Đông 2026/ }).click()
  await quickEntry(page, 'Tưới nước')
  const forSecondSeason = page.getByRole('dialog', { name: 'Ghi tưới nước' })
  await expect(forSecondSeason).toBeVisible()
  // The form's own context line, not the sheet subtitle: it is what tells the
  // farmer which season this entry will be written to.
  await expect(forSecondSeason.locator('.fw-fn__target')).toHaveText(/Thu Đông 2026 · Thửa A-02/)
  await page.getByRole('button', { name: 'Hủy' }).click()
  await expect(forSecondSeason).toHaveCount(0)

  await nav.getByRole('link', { name: 'Nhật ký', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Nhật ký canh tác', level: 1 })).toBeVisible()
  await expect(nav.getByRole('link', { name: 'Nhật ký', exact: true })).toHaveAttribute('aria-current', 'page')

  await nav.getByRole('link', { name: 'Ruộng / Vụ mùa', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Các ruộng trong phạm vi của bạn', level: 1 })).toBeVisible()
  await expect(page.getByText(/thửa$/).first()).toBeVisible()
  // Round 3: the farm card lists its plots and the season on each, so the card
  // itself carries farm -> plot -> season; the link out is to the farm record.
  await expect(page.locator('.fw-farm__plot')).toHaveCount(2)
  await expect(page.locator('.fw-farm__plot', { hasText: 'Thửa A-01' })).toContainText('Hè Thu 2026')
  await page.getByRole('link', { name: /Xem hồ sơ nông hộ/ }).first().click()
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
  await expect(nav.getByRole('link', { name: 'Ruộng / Vụ mùa', exact: true })).toHaveAttribute('aria-current', 'page')
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
  // Mock mode has no readiness endpoint, so the tab falls back to the calm
  // generic state rather than inventing a missing-input list of its own.
  await expect(page.getByText('Chưa có kết quả phát thải cho vụ này')).toBeVisible()
  await expect(page.getByTestId('carbon-missing')).toHaveCount(0)
  await expect(page.getByRole('button', { name: /Tính lại/i })).toHaveCount(0)
  // Cost is never presented as a Carbon input.
  await expect(page.getByText(/Chi phí không phải đầu vào của Carbon/)).toBeVisible()

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
  await expect(bottom.getByRole('link')).toHaveCount(6)
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
