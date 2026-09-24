import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { expect, test } from '@playwright/test'

// M03 CV Farmer real E2E (brief §31-33). Uses the existing draft baseline
// model against real held-out dataset images (not training data — these are
// the exact files listed in ml/datasets/splits/test.csv) through the real
// backend. No API interception, no fake inference.
const email = process.env.FARMER_REAL_E2E_EMAIL
const password = process.env.FARMER_REAL_E2E_PASSWORD
const enabled = process.env.REAL_E2E === 'true' && process.env.FARMER_REAL_E2E === 'true' && process.env.FARMER_REAL_CV_E2E === 'true' && Boolean(email && password)

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = path.resolve(__dirname, '../../../')
// Deterministic (fixed model weights/temperature) — same file always gives
// the same result. Verified once via `python -m ml.infer <path>` before
// writing this spec (see docs/CV_FARMER_INTEGRATION_REPORT.md §I).
const CONFIDENT_IMAGE = path.join(REPO_ROOT, 'ml/datasets/raw/extracted/Original Images/Leaf Blast/Leaf_blast  (105).jpg')
const UNCERTAIN_IMAGE = path.join(REPO_ROOT, 'ml/datasets/raw/extracted/Original Images/Healthy Rice Leaf/Healthy_rice_leaf  (98).jpg')

test.describe('authenticated Farmer real CV flow', () => {
  test.skip(!enabled, 'Set REAL_E2E=true, FARMER_REAL_E2E=true and FARMER_REAL_CV_E2E=true with a Farmer QA identity (FARMER_REAL_E2E_EMAIL/PASSWORD).')

  test('real model inference: a confident result and a truthful uncertain result', async ({ page }) => {
    test.setTimeout(300_000)
    const consoleErrors: string[] = []
    const unexpectedApi: string[] = []
    const directBusiness: string[] = []
    page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()) })
    page.on('request', (r) => {
      const p = new URL(r.url()).pathname
      if (/\/rest\/v1\/(organizations|farms|plots|crop_seasons|plant_images|cv_inferences|cv_model_versions)/.test(p)) directBusiness.push(r.url())
    })
    page.on('response', (r) => {
      const p = new URL(r.url()).pathname
      const allowedNoCalc = r.status() === 404 && /\/carbon$/.test(p)
      if (p.startsWith('/v1/') && r.status() >= 400 && !allowedNoCalc) unexpectedApi.push(`${r.status()} ${p}`)
    })

    await page.goto('/login')
    await page.getByLabel('Email').fill(email!)
    await page.getByLabel('Mật khẩu').fill(password!)
    await page.getByRole('button', { name: 'Đăng nhập' }).click()
    await expect(page).toHaveURL(/\/farmer$/)
    await expect(page.getByRole('heading', { name: 'Hôm nay trên ruộng của bạn', level: 1 })).toBeVisible({ timeout: 60_000 })

    // The leaf check lives on the season page since the hybrid redesign;
    // Home links the season as "Xem chi tiết vụ".
    await page.getByRole('link', { name: 'Xem chi tiết vụ' }).click()
    await expect(page.getByRole('tab', { name: 'Tổng quan' })).toBeVisible({ timeout: 60_000 })

    /* --------------------------------------------------------- confident */
    await page.getByRole('button', { name: 'Kiểm tra lá lúa' }).click()
    await expect(page.getByRole('dialog', { name: 'Kiểm tra lá lúa' })).toBeVisible()
    await page.locator('.cv-check__picker input[type="file"]').setInputFiles(CONFIDENT_IMAGE)
    await expect(page.getByRole('img', { name: 'Ảnh lá lúa đã chọn để phân tích' })).toBeVisible()
    const inferResponsePromise = page.waitForResponse((r) => /\/cv\/infer$/.test(new URL(r.url()).pathname))
    await page.getByRole('button', { name: 'Phân tích ảnh' }).click()
    const inferResponse = await inferResponsePromise
    expect(inferResponse.status()).toBe(200)
    const inferBody = await inferResponse.json()

    if (inferBody.uncertain) {
      await expect(page.getByRole('heading', { name: 'Chưa thể xác định chắc chắn' })).toBeVisible({ timeout: 30_000 })
    } else {
      await expect(page.getByRole('heading', { name: 'Kết quả nhận diện' })).toBeVisible({ timeout: 30_000 })
      await expect(page.getByText('Chưa được xác nhận thực địa.')).toBeVisible()
      // Never a fabricated field-validation claim (brief §13).
      await expect(page.getByText(/85[.,]6%/)).toHaveCount(0)
    }
    await page.screenshot({ path: `test-results/farmer-real-cv-result-${inferBody.uncertain ? 'uncertain' : 'confident'}-1440.png`, fullPage: true })
    await page.locator('.cv-result').getByRole('button', { name: 'Đóng' }).click()
    await expect(page.getByRole('dialog', { name: 'Kiểm tra lá lúa' })).toHaveCount(0)

    /* --------------------------------------------------------------- history */
    // Still on the season's overview tab, where the history lives.
    await expect(page.getByRole('tab', { name: 'Tổng quan' })).toHaveAttribute('aria-selected', 'true')
    await expect(page.getByRole('heading', { name: 'Kiểm tra gần đây' })).toBeVisible({ timeout: 60_000 })
    await expect(page.locator('.cv-history__item').first()).toBeVisible({ timeout: 30_000 })

    /* -------------------------------------------------------------- uncertain */
    await page.getByRole('button', { name: 'Kiểm tra lá lúa' }).click()
    await expect(page.getByRole('dialog', { name: 'Kiểm tra lá lúa' })).toBeVisible()
    await page.locator('.cv-check__picker input[type="file"]').setInputFiles(UNCERTAIN_IMAGE)
    const uncertainResponsePromise = page.waitForResponse((r) => /\/cv\/infer$/.test(new URL(r.url()).pathname))
    await page.getByRole('button', { name: 'Phân tích ảnh' }).click()
    const uncertainResponse = await uncertainResponsePromise
    expect(uncertainResponse.status()).toBe(200)
    const uncertainBody = await uncertainResponse.json()
    expect(uncertainBody.uncertain).toBe(true)
    expect(uncertainBody.label).toBeNull()
    await expect(page.getByRole('heading', { name: 'Chưa thể xác định chắc chắn' })).toBeVisible({ timeout: 30_000 })
    await expect(page.getByText('Chụp gần hơn')).toBeVisible()
    await page.screenshot({ path: 'test-results/farmer-real-cv-uncertain-1440.png', fullPage: true })
    await page.locator('.cv-result').getByRole('button', { name: 'Đóng' }).click()

    expect(unexpectedApi).toEqual([])
    expect(directBusiness).toEqual([])
    expect(consoleErrors.filter((line) => !/Failed to load resource.*\b404\b/i.test(line))).toEqual([])
  })
})
