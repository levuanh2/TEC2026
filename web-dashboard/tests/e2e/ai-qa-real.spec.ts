import { expect, test, type Page, type Response } from '@playwright/test'

// AI Q&A (RAG V1, D8 strategy B) against a REAL backend and a REAL Supabase: real sign-in,
// real JWT scope, real RLS, the real lexical retriever and the trusted READ composer.
// Intended for a LOCAL isolated stack seeded with SYNTHETIC knowledge ("TEST FIXTURE"
// titles), one prompt-injection chunk and one stored M05 data_task on the season; the
// backend runs with RAG_QA_ENABLED=true and NO provider (strategy B baseline), the web
// build with VITE_AI_QA_ENABLED=true. Never point it at production.
const farmer = { email: process.env.FARMER_REAL_E2E_EMAIL, password: process.env.FARMER_REAL_E2E_PASSWORD }
const manager = { email: process.env.MANAGER_REAL_E2E_EMAIL, password: process.env.MANAGER_REAL_E2E_PASSWORD }
const seasonId = process.env.AI_QA_E2E_SEASON
const enabled = process.env.REAL_E2E === 'true' && process.env.AI_QA_REAL_E2E === 'true'
  && Boolean(farmer.email && farmer.password && manager.email && manager.password && seasonId)

const PROVIDER_HOSTS = /generativelanguage\.googleapis\.com|aiplatform\.googleapis\.com|openai|anthropic/

async function signIn(page: Page, who: { email?: string; password?: string }) {
  await page.goto('/login')
  await page.getByLabel('Email').fill(who.email!)
  await page.getByLabel('Mật khẩu').fill(who.password!)
  await page.getByRole('button', { name: 'Đăng nhập' }).click()
}

function isQuestion(r: Response) {
  return r.request().method() === 'POST' && /\/v1\/crop-seasons\/[^/]+\/questions$/.test(new URL(r.url()).pathname)
}

async function ask(page: Page, text: string, intentLabel?: string) {
  const panel = page.locator('section.aiq')
  if (intentLabel) await panel.getByLabel(intentLabel, { exact: true }).check()
  await panel.getByLabel('Câu hỏi của bạn').fill(text)
  const [response] = await Promise.all([
    page.waitForResponse((r) => isQuestion(r) && JSON.parse(r.request().postData() ?? '{}').question === text),
    panel.getByRole('button', { name: 'Gửi câu hỏi' }).click(),
  ])
  return { response, body: await response.json().catch(() => null), panel }
}

test.describe('AI Q&A against a real local stack', () => {
  test.skip(!enabled, 'Set REAL_E2E=true, AI_QA_REAL_E2E=true, FARMER_/MANAGER_REAL_E2E_EMAIL/PASSWORD and AI_QA_E2E_SEASON (local isolated stack only).')

  test('farmer and manager: typed questions, provenance, citations, no hidden model call, no stale answer', async ({ page }) => {
    test.setTimeout(300_000)
    const providerCalls: string[] = []
    const consoleErrors: string[] = []
    page.on('request', (r) => { if (PROVIDER_HOSTS.test(r.url())) providerCalls.push(r.url()) })
    page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()) })

    // -- Farmer ---------------------------------------------------------------------
    await signIn(page, farmer)
    await expect(page).toHaveURL(/\/farmer$/)
    await page.goto(`/farmer/crop-seasons/${seasonId}`)
    const panel = page.locator('section.aiq')
    await expect(panel.getByRole('heading', { name: 'Hỏi đáp về vụ này' })).toBeVisible()

    // A typed (not chip) data-gap question pre-selects its intent and is answered by the system.
    await panel.getByLabel('Câu hỏi của bạn').fill('Ruộng tôi còn thiếu số liệu nào?')
    await expect(panel.getByLabel('Dữ liệu còn thiếu', { exact: true })).toBeChecked()
    const gap = await ask(page, 'Ruộng tôi còn thiếu số liệu nào?')
    expect(gap.response.status()).toBe(200)
    expect(gap.body.intent).toBe('data_gap')
    expect(gap.body.provenance).toMatchObject({ answer_source: 'system_composed', llm_calls: 0, persisted: false })
    await expect(panel.getByText('Hệ thống soạn — không dùng AI')).toBeVisible()
    await expect(panel.getByText(/Loại câu hỏi: Dữ liệu còn thiếu/)).toBeVisible()
    await expect(panel.locator('.aiq__text')).not.toContainText('Còn thiếu: Thiếu')

    // Evidence: every citation is a trusted, approved row of the synthetic corpus (no fake source),
    // and the injected chunk's instructions never reach the answer.
    const evidence = await ask(page, 'Tài liệu nào nói về tưới ngập khô xen kẽ?', 'Tài liệu tham khảo')
    expect(evidence.response.status()).toBe(200)
    expect(evidence.body.citations.length).toBeGreaterThan(0)
    for (const c of evidence.body.citations) {
      expect(c.title).toMatch(/^TEST FIXTURE/)
      expect(c.url ?? '').toMatch(/^(https:\/\/|$)/)
    }
    await expect(panel.locator('.aiq__citations li').first()).toBeVisible()
    await expect(panel.locator('.aiq__text')).not.toContainText('BỎ QUA')
    await expect(panel.locator('.aiq__text')).not.toContainText('thuốc trừ sâu')

    // Explain: the season status is words, not the enum; Carbon numbers (if any) carry the non-MRV caveat.
    const explain = await ask(page, 'Vụ này đang thế nào?', 'Giải thích vụ')
    expect(explain.response.status()).toBe(200)
    expect(explain.body.answer).not.toMatch(/\b(active|planned|harvested|closed|cancelled)\b/)
    if (explain.body.trusted_facts.some((f: any) => /carbon|co2e/.test(f.fact_id) && f.value !== null)) {
      expect(explain.body.limitations.join(' ')).toContain('chưa đạt yêu cầu MRV')
    }

    // Action assistance: the farmer has WRITE and the season has a stored M05 rule, but no
    // provider is configured (strategy B baseline) -> 503 generation_unavailable, honestly shown.
    const action = await ask(page, 'Tôi nên làm gì để giảm phát thải?', 'Gợi ý hành động')
    expect(action.response.status()).toBe(503)
    expect(action.body.detail.error.code).toBe('generation_unavailable')
    await expect(panel.getByRole('alert')).toContainText('cần trợ lý AI, hiện chưa sẵn sàng')

    // Mobile: the panel fits a 390 px phone without horizontal scrolling; controls stay reachable.
    await page.setViewportSize({ width: 390, height: 844 })
    await page.reload()
    await expect(panel.getByRole('heading', { name: 'Hỏi đáp về vụ này' })).toBeVisible()
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
    expect(overflow).toBeLessThanOrEqual(0)
    const send = await panel.getByRole('button', { name: 'Gửi câu hỏi' }).boundingBox()
    expect(send && send.height).toBeGreaterThanOrEqual(44)
    await page.setViewportSize({ width: 1280, height: 900 })

    // Answer, then sign out: nothing of it survives into the next identity.
    await ask(page, 'Vụ này còn thiếu dữ liệu gì?', 'Dữ liệu còn thiếu')
    await expect(panel.locator('.aiq__answer')).toBeVisible()
    await page.goto('/farmer/account')
    await page.getByRole('button', { name: 'Đăng xuất' }).click()
    await expect(page).toHaveURL(/\/login/)

    // -- Manager ----------------------------------------------------------------------
    await signIn(page, manager)
    await expect(page).not.toHaveURL(/\/login/)
    await page.goto(`/crop-seasons/${seasonId}`)
    const mpanel = page.locator('section.aiq')
    await expect(mpanel.getByRole('heading', { name: 'Hỏi đáp về vụ này' })).toBeVisible({ timeout: 60_000 })
    await expect(mpanel.locator('.aiq__answer')).toHaveCount(0) // no stale farmer answer
    await expect(mpanel.getByLabel('Gợi ý hành động', { exact: true })).toHaveCount(0)

    // A typed action request: told it is farmer-only; asking stays READ (explain), never action.
    await mpanel.getByLabel('Câu hỏi của bạn').fill('HTX nên làm gì để giảm phát thải?')
    await expect(mpanel.getByText(/chỉ dành cho nông hộ có quyền ghi/)).toBeVisible()
    const read = await ask(page, 'HTX nên làm gì để giảm phát thải?')
    expect(read.response.status()).toBe(200)
    expect(read.body.intent).toBe('explain')
    expect(read.body.recommendations).toEqual([])
    expect(read.body.signals).toEqual([]) // READ never carries stored-recommendation data
    expect(read.body.provenance.llm_calls).toBe(0)

    // Compare: only seasons the manager may read; with none comparable it says so instead of inventing.
    const compare = await ask(page, 'So sánh với các vụ khác của cùng thửa', 'So sánh')
    expect(compare.response.status()).toBe(200)
    if (compare.body.status === 'insufficient_evidence') {
      expect(compare.body.insufficient_reason).toBe('no_comparison_basis')
      await expect(mpanel.locator('.aiq__text')).toContainText('Không có benchmark hoặc vụ đối chiếu')
    } else {
      for (const f of compare.body.trusted_facts) expect([null, compare.body.trusted_facts[0].organization_id]).toContain(f.organization_id)
    }

    // (A manager forcing intent=recommend through the API is refused server-side with 404:
    // backend/tests/test_rag_questions_route_db.py::test_read_callers_can_ask_but_never_get_action_capability.)

    expect(providerCalls).toEqual([]) // the browser never talks to a model provider
    expect(consoleErrors.filter((e) => !/503|Failed to load resource/.test(e))).toEqual([])
  })
})
