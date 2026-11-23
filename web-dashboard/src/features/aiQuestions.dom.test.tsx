// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import axe from 'axe-core'
import { readFileSync } from 'node:fs'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/client'
import type { QuestionAnswer, QuestionCitation } from '../api/questions'

// A hand-rolled fake: Vitest 5 reports a rejected promise returned by a vi.fn() as
// unhandled even when the component catches it, so the calls are recorded here.
type Impl = (...args: any[]) => Promise<QuestionAnswer>
const fake = vi.hoisted(() => ({ calls: [] as any[][], queue: [] as Impl[], impl: (async () => { throw new Error('unset') }) as Impl }))
vi.mock('../api/questions', () => ({
  askSeasonQuestion: (...args: any[]) => { fake.calls.push(args); return (fake.queue.shift() ?? fake.impl)(...args) },
}))
const ask = {
  get calls() { return fake.calls },
  resolve(value: QuestionAnswer) { fake.impl = async () => value },
  returns(promise: Promise<QuestionAnswer>) { fake.impl = () => promise },
  once(impl: Impl) { fake.queue.push(impl) },
  implement(impl: Impl) { fake.impl = impl },
  reset() { fake.calls.length = 0; fake.queue.length = 0; fake.impl = async () => { throw new Error('unset') } },
}

import { CITATION_SCOPE_NOTE, LINK_WITHHELD_NOTE, QUESTION_TIMEOUT_MS, SeasonQuestionPanel, navigableUrl } from './aiQuestions'

/** The owner's required sentence (2026-11-16), pinned as a literal. */
const CONTESTED = 'Tài liệu đang có nội dung khoa học cần xác minh lại; không sử dụng làm căn cứ hướng dẫn canh tác.'
const CAVEAT = 'Lưu ý: tài liệu này có phát hiện kiểm tra đã được chuyên gia đánh giá là báo động nhầm hoặc khác biệt theo ngữ cảnh; hệ thống không tự xác minh nội dung khoa học.'

const answer = (over: Partial<QuestionAnswer> = {}): QuestionAnswer => ({
  status: 'generated', intent: 'explain', cropSeasonId: 's1',
  answer: 'Tổng phát thải khí nhà kính đã tính cho vụ: 2.900 kg CO2e.',
  limitations: ['Câu trả lời được hệ thống soạn từ dữ liệu đã ghi nhận và tài liệu trong kho tri thức; đây không phải lời khuyên canh tác.'],
  insufficientReason: null,
  citations: [{ sourceId: 'src', chunkId: 'c1', documentId: 'doc', documentVersion: 'v1', title: 'Hướng dẫn tưới AWD',
                section: 'Tưới nước', sourceType: 'guideline', url: 'https://example.invalid/awd', publishedAt: '2025-11-10',
                integrityWarning: null, integrityDetail: null }],
  facts: [{ factId: 'current.carbon.total_co2e_kg', kind: 'carbon_total', value: 2900, unit: 'kg CO2e', source: 'carbon_service' }],
  recommendations: [], storedRecommendations: [], answerSource: 'system_composed', model: null, ...over,
})

function deferred<T>() {
  let resolve!: (v: T) => void
  let reject!: (e: unknown) => void
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

beforeEach(() => ask.reset())
afterEach(() => { cleanup(); vi.useRealTimers() })

describe('SeasonQuestionPanel', () => {
  it('sends only the question and intent, then shows answer, provenance, citations and facts', async () => {
    ask.resolve(answer())
    render(<SeasonQuestionPanel seasonId="s1" audience="farmer" />)
    fireEvent.change(screen.getByLabelText('Câu hỏi của bạn'), { target: { value: 'Vụ này thế nào?' } })
    fireEvent.click(screen.getByRole('button', { name: 'Gửi câu hỏi' }))
    expect(await screen.findByText(/2\.900 kg CO2e/)).toBeTruthy()
    expect(ask.calls[0].slice(0, 2)).toEqual(['s1', { question: 'Vụ này thế nào?', intent: 'explain' }])
    expect(ask.calls[0][2]).toBeInstanceOf(AbortSignal)
    expect(screen.getByText(/không dùng mô hình AI/)).toBeTruthy()
    const link = screen.getByRole('link', { name: /Mở nguồn/ })
    expect(link.getAttribute('href')).toBe('https://example.invalid/awd')
    expect(link.getAttribute('rel')).toBe('noopener noreferrer')
    expect(screen.getByText(/current\.carbon\.total_co2e_kg/)).toBeTruthy()
  })

  it('a suggested question asks at once with its intent', async () => {
    ask.resolve(answer({ intent: 'data_gap' }))
    render(<SeasonQuestionPanel seasonId="s1" audience="farmer" />)
    fireEvent.click(screen.getByRole('button', { name: 'Vụ này còn thiếu dữ liệu gì?' }))
    await waitFor(() => expect(ask.calls[0]?.slice(0, 2)).toEqual(['s1', { question: 'Vụ này còn thiếu dữ liệu gì?', intent: 'data_gap' }]))
  })

  it('Enter submits; Shift+Enter does not', async () => {
    ask.resolve(answer())
    render(<SeasonQuestionPanel seasonId="s1" audience="farmer" />)
    const box = screen.getByLabelText('Câu hỏi của bạn')
    fireEvent.change(box, { target: { value: 'Câu hỏi' } })
    fireEvent.keyDown(box, { key: 'Enter', shiftKey: true })
    expect(ask.calls).toHaveLength(0)
    fireEvent.keyDown(box, { key: 'Enter' })
    await waitFor(() => expect(ask.calls).toHaveLength(1))
  })

  it('a manager is never offered the action intent', () => {
    render(<SeasonQuestionPanel seasonId="s1" audience="manager" />)
    expect(screen.queryByLabelText('Gợi ý hành động')).toBeNull()
    expect(screen.getByLabelText('Giải thích vụ')).toBeTruthy()
  })

  it('a farmer may choose it when the action tier is on; the server still decides', () => {
    render(<SeasonQuestionPanel seasonId="s1" audience="farmer" actionTier />)
    expect(screen.getByLabelText('Gợi ý hành động')).toBeTruthy()
  })

  it('READ-only build (default): a farmer is not offered the action intent', () => {
    render(<SeasonQuestionPanel seasonId="s1" audience="farmer" />)
    expect(screen.queryByLabelText('Gợi ý hành động')).toBeNull()
    expect(screen.getByLabelText('Giải thích vụ')).toBeTruthy()
  })

  it('READ-only build: an action question is not auto-routed to recommend and says why', async () => {
    render(<SeasonQuestionPanel seasonId="s1" audience="farmer" />)
    fireEvent.change(screen.getByLabelText('Câu hỏi của bạn'), { target: { value: 'Tôi nên làm gì để giảm phát thải?' } })
    expect(screen.getByText(/Giai đoạn thử nghiệm chưa có gợi ý hành động/)).toBeTruthy()
    expect(screen.queryByText(/chỉ dành cho nông hộ có quyền ghi/)).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Gửi câu hỏi' }))
    await waitFor(() => expect(ask.calls[0]?.[1]).toEqual({ question: 'Tôi nên làm gì để giảm phát thải?', intent: 'explain' }))
  })

  it('shows a loading state while waiting', async () => {
    const pending = deferred<QuestionAnswer>()
    ask.returns(pending.promise)
    render(<SeasonQuestionPanel seasonId="s1" audience="farmer" />)
    fireEvent.click(screen.getByRole('button', { name: 'Vụ này đang thế nào?' }))
    expect(await screen.findByRole('status', { name: 'Đang soạn câu trả lời' })).toBeTruthy()
    await act(async () => { pending.resolve(answer()) })
    expect(screen.queryByRole('status', { name: 'Đang soạn câu trả lời' })).toBeNull()
  })

  it('shows the server integrity warning on the citation it is about (M7 E3, D-E3-3)', async () => {
    const base = answer().citations[0]
    ask.resolve(answer({ intent: 'evidence', citations: [
      { ...base, integrityWarning: CONTESTED, integrityDetail: 'Phát hiện kiểm tra: mâu thuẫn với tài liệu tham chiếu.' },
      { ...base, chunkId: 'c2', title: 'Sổ tay ghi chép', integrityWarning: null, integrityDetail: null },
    ] }))
    render(<SeasonQuestionPanel seasonId="s1" audience="farmer" />)
    fireEvent.change(screen.getByLabelText('Câu hỏi của bạn'), { target: { value: 'Tài liệu nào nói về AWD?' } })
    fireEvent.click(screen.getByRole('button', { name: 'Gửi câu hỏi' }))
    const note = await screen.findByRole('note')
    expect(note.textContent).toBe(CONTESTED)
    expect(note.closest('li')?.textContent).toContain('Hướng dẫn tưới AWD')       // inside its own citation
    expect(screen.getAllByRole('note')).toHaveLength(1)                             // the clean citation has none
    expect(document.body.textContent).not.toContain('reference_conflict')
  })

  it('insufficient evidence is shown as such, with no citation invented', async () => {
    ask.resolve(answer({ status: 'insufficient_evidence', answer: 'Chưa có tài liệu đã duyệt đủ để trả lời câu hỏi này.',
                                   citations: [], facts: [], insufficientReason: 'no_evidence_retrieved' }))
    render(<SeasonQuestionPanel seasonId="s1" audience="farmer" />)
    fireEvent.click(screen.getByRole('button', { name: /tưới ngập khô xen kẽ/ }))
    expect(await screen.findByText(/Chưa có đoạn tài liệu nào trong kho tri thức khớp/)).toBeTruthy()
    expect(screen.queryByRole('link', { name: /Mở nguồn/ })).toBeNull()
  })

  it.each([
    [503, 'backend_not_configured', /chưa được bật/, false],
    [503, 'generation_unavailable', /chưa sẵn sàng/, false],
    [503, 'action_tier_disabled', /chỉ hỗ trợ câu hỏi giải thích/, false],
    [429, 'question_rate_limited', /hỏi quá nhiều câu/, false],
    [503, 'question_rate_limit_unavailable', /tạm thời chưa nhận câu hỏi/, false],
    [404, 'not_found', /không có quyền/, false],
    [502, 'citation_mismatch', /kiểm tra nguồn dẫn/, true],
    [0, 'offline', /Không có kết nối/, true],
  ] as const)('error %s %s: a Vietnamese message, retry only when it can help', async (status, code, text, retry) => {
    ask.implement(async () => { throw new ApiError(status, code, 'internal detail') })
    render(<SeasonQuestionPanel seasonId="s1" audience="farmer" />)
    fireEvent.click(screen.getByRole('button', { name: 'Vụ này đang thế nào?' }))
    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toMatch(text)
    expect(!!screen.queryByRole('button', { name: 'Thử lại' })).toBe(retry)
    expect(alert.textContent).not.toContain('internal detail')
  })

  it('times out on its own and offers a retry with the same intent', async () => {
    vi.useFakeTimers()
    ask.implement((_s: string, _r: unknown, signal: AbortSignal) => new Promise((_res, rej) => {
      signal.addEventListener('abort', () => rej(new DOMException('aborted', 'AbortError')))
    }))
    render(<SeasonQuestionPanel seasonId="s1" audience="farmer" />)
    fireEvent.click(screen.getByRole('button', { name: 'Vụ này còn thiếu dữ liệu gì?' }))
    await act(async () => { vi.advanceTimersByTime(QUESTION_TIMEOUT_MS + 1) })
    expect(screen.getByRole('alert').textContent).toMatch(/Quá thời gian/)
    ask.resolve(answer({ intent: 'data_gap' }))
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Thử lại' })) })
    expect(ask.calls[1][1]).toEqual({ question: 'Vụ này còn thiếu dữ liệu gì?', intent: 'data_gap' })
  })

  it('an answer for the previous season never appears after switching season', async () => {
    const first = deferred<QuestionAnswer>()
    ask.once(() => first.promise)
    const { rerender } = render(<SeasonQuestionPanel seasonId="s1" audience="farmer" />)
    fireEvent.click(screen.getByRole('button', { name: 'Vụ này đang thế nào?' }))
    rerender(<SeasonQuestionPanel seasonId="s2" audience="farmer" />)
    await act(async () => { first.resolve(answer({ cropSeasonId: 's1' })) })
    expect(screen.queryByText(/2\.900 kg CO2e/)).toBeNull()
    expect((ask.calls[0][2] as AbortSignal).aborted).toBe(true)
  })

  it('a newer question wins over a slower older one', async () => {
    const slow = deferred<QuestionAnswer>()
    ask.once(() => slow.promise); ask.once(async () => answer({ answer: 'Câu trả lời mới' }))
    render(<SeasonQuestionPanel seasonId="s1" audience="farmer" />)
    fireEvent.click(screen.getByRole('button', { name: 'Vụ này đang thế nào?' }))
    const box = screen.getByLabelText('Câu hỏi của bạn')
    fireEvent.change(box, { target: { value: 'Câu khác' } })
    fireEvent.keyDown(box, { key: 'Enter' })
    expect(await screen.findByText('Câu trả lời mới')).toBeTruthy()
    await act(async () => { slow.resolve(answer({ answer: 'Câu trả lời cũ' })) })
    expect(screen.queryByText('Câu trả lời cũ')).toBeNull()
  })

  // -- typed questions (not only the suggestion chips) -------------------------

  it('a typed question pre-selects the matching intent until the user picks one', async () => {
    ask.resolve(answer({ intent: 'data_gap' }))
    render(<SeasonQuestionPanel seasonId="s1" audience="farmer" />)
    const box = screen.getByLabelText('Câu hỏi của bạn')
    fireEvent.change(box, { target: { value: 'Ruộng tôi còn thiếu số liệu nào?' } })
    expect((screen.getByLabelText('Dữ liệu còn thiếu') as HTMLInputElement).checked).toBe(true)
    expect(screen.getByText(/theo nội dung câu hỏi/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Gửi câu hỏi' }))
    await waitFor(() => expect(ask.calls[0]?.[1]).toEqual({ question: 'Ruộng tôi còn thiếu số liệu nào?', intent: 'data_gap' }))
    // an explicit choice is never overridden by later typing
    fireEvent.click(screen.getByLabelText('So sánh'))
    fireEvent.change(box, { target: { value: 'Tài liệu nào nói về AWD?' } })
    expect((screen.getByLabelText('So sánh') as HTMLInputElement).checked).toBe(true)
  })

  it('a manager asking for an action is told it is farmer-only and never gets the action intent', () => {
    render(<SeasonQuestionPanel seasonId="s1" audience="manager" />)
    fireEvent.change(screen.getByLabelText('Câu hỏi của bạn'), { target: { value: 'HTX nên làm gì để giảm phát thải?' } })
    expect(screen.getByText(/chỉ dành cho nông hộ có quyền ghi/)).toBeTruthy()
    expect(screen.queryByLabelText('Gợi ý hành động')).toBeNull()
    expect((screen.getByLabelText('Giải thích vụ') as HTMLInputElement).checked).toBe(true)
  })

  // -- deterministic vs AI vs stored M05 ------------------------------------------

  it('a system-composed answer says it is a fixed template, not AI, and names the intent answered', async () => {
    ask.resolve(answer({ intent: 'data_gap' }))
    render(<SeasonQuestionPanel seasonId="s1" audience="farmer" />)
    fireEvent.click(screen.getByRole('button', { name: 'Vụ này còn thiếu dữ liệu gì?' }))
    expect(await screen.findByText('Hệ thống soạn — không dùng AI')).toBeTruthy()
    expect(screen.getByText(/mẫu cố định/)).toBeTruthy()
    expect(screen.getByText(/Loại câu hỏi: Dữ liệu còn thiếu/)).toBeTruthy()
    expect(screen.queryByText('Trợ lý AI viết')).toBeNull()
  })

  it('an AI explanation is labelled as such and tied to the stored M05 recommendation it explains', async () => {
    ask.resolve(answer({
      intent: 'recommend', answerSource: 'model_generated', model: 'm',
      answer: 'Tài liệu đã duyệt mô tả tưới ngập khô xen kẽ.',
      recommendations: [{ title: 'Cân nhắc tưới ngập khô xen kẽ', actions: ['Theo dõi mực nước'], ruleCode: 'water.awd_from_continuous_flooding' }],
      storedRecommendations: [{ ruleCode: 'water.awd_from_continuous_flooding', type: 'optimization', title: 'Chuyển sang tưới AWD', status: 'generated' }],
    }))
    render(<SeasonQuestionPanel seasonId="s1" audience="farmer" actionTier />)
    fireEvent.click(screen.getByLabelText('Gợi ý hành động'))
    fireEvent.change(screen.getByLabelText('Câu hỏi của bạn'), { target: { value: 'Tôi nên làm gì?' } })
    fireEvent.click(screen.getByRole('button', { name: 'Gửi câu hỏi' }))
    expect(await screen.findByText('Trợ lý AI viết')).toBeTruthy()
    expect(screen.getByText(/Dựa trên khuyến nghị đã lưu: Chuyển sang tưới AWD/)).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Khuyến nghị đã lưu của hệ thống quy tắc' })).toBeTruthy()
    expect(screen.queryByText(/mẫu cố định/)).toBeNull()
  })

  it('no stored rule: the action request is insufficient and shows no suggestion', async () => {
    ask.resolve(answer({
      status: 'insufficient_evidence', intent: 'recommend', insufficientReason: 'no_rule_signal', citations: [], facts: [],
      answer: 'Vụ này chưa có khuyến nghị nào do hệ thống quy tắc ghi nhận, nên trợ lý không đưa ra gợi ý hành động.',
    }))
    render(<SeasonQuestionPanel seasonId="s1" audience="farmer" actionTier />)
    fireEvent.click(screen.getByLabelText('Gợi ý hành động'))
    fireEvent.change(screen.getByLabelText('Câu hỏi của bạn'), { target: { value: 'Tôi nên làm gì?' } })
    fireEvent.click(screen.getByRole('button', { name: 'Gửi câu hỏi' }))
    expect(await screen.findByText(/chưa có khuyến nghị nào/)).toBeTruthy()
    expect(screen.queryByRole('heading', { name: /Trợ lý AI giải thích/ })).toBeNull()
  })

  it('unmount (sign-out / identity change remounts the tree) aborts and drops the answer', async () => {
    const pending = deferred<QuestionAnswer>()
    ask.returns(pending.promise)
    const { unmount } = render(<SeasonQuestionPanel seasonId="s1" audience="farmer" />)
    fireEvent.click(screen.getByRole('button', { name: 'Vụ này đang thế nào?' }))
    unmount()
    expect((ask.calls[0][2] as AbortSignal).aborted).toBe(true)
    render(<SeasonQuestionPanel seasonId="s1" audience="farmer" />)
    await act(async () => { pending.resolve(answer()) })
    expect(screen.queryByText(/2\.900 kg CO2e/)).toBeNull()
  })
})

// -- M7 READ-tier citation UX (docs/rag/RAG_V15_E1_E4_SOURCE_EXPERT_GOVERNANCE_PLAN.md §3) --------------------
describe('READ-tier contested citations', () => {
  const base = answer().citations[0]
  const cite = (over: Partial<QuestionCitation>): QuestionCitation => ({ ...base, ...over })
  const contested = cite({ chunkId: 'k1', title: 'Tài liệu AWD bị tranh chấp', url: 'https://example.invalid/contested',
                           integrityWarning: CONTESTED, integrityDetail: 'Phát hiện kiểm tra: mâu thuẫn với tài liệu tham chiếu.' })
  const caveated = cite({ chunkId: 'k2', title: 'Tài liệu có lưu ý', url: 'https://example.invalid/caveat',
                          integrityWarning: CAVEAT, integrityDetail: 'Phát hiện kiểm tra: hướng dẫn đã hết hiệu lực.' })
  const clean = cite({ chunkId: 'k3', title: 'Tài liệu sạch', url: 'https://example.invalid/clean' })

  async function show(citations: QuestionCitation[], audience: 'farmer' | 'manager' = 'farmer') {
    ask.resolve(answer({ intent: 'evidence', citations }))
    const view = render(<SeasonQuestionPanel seasonId="s1" audience={audience} />)
    fireEvent.change(screen.getByLabelText('Câu hỏi của bạn'), { target: { value: 'Tài liệu nào nói về AWD?' } })
    fireEvent.click(screen.getByRole('button', { name: 'Gửi câu hỏi' }))
    await screen.findByText('Nguồn tài liệu')
    return view
  }
  const groupOf = (title: string) => screen.getByRole('group', { name: title })

  it('puts the exact owner sentence directly after the title, as the citation group\'s accessible description', async () => {
    await show([contested, clean])
    const group = groupOf('Tài liệu AWD bị tranh chấp')
    const title = within(group).getByText('Tài liệu AWD bị tranh chấp')
    const warning = title.nextElementSibling as HTMLElement
    expect(warning.getAttribute('role')).toBe('note')
    expect(warning.textContent).toBe(CONTESTED)                                       // verbatim, nothing added
    expect(group.getAttribute('aria-describedby')?.split(' ')[0]).toBe(warning.id)
    // accessible description: the sentence first, then the separate finding description
    const description = (group.getAttribute('aria-describedby') ?? '').split(' ')
      .map((id) => document.getElementById(id)?.textContent).join(' ')
    expect(description).toBe(`${CONTESTED} Phát hiện kiểm tra: mâu thuẫn với tài liệu tham chiếu.`)
    expect(warning.nextElementSibling?.textContent).toBe('Phát hiện kiểm tra: mâu thuẫn với tài liệu tham chiếu.')
    // a clean citation has no warning and no description
    expect(within(groupOf('Tài liệu sạch')).queryByRole('note')).toBeNull()
    expect(groupOf('Tài liệu sạch').hasAttribute('aria-describedby')).toBe(false)
  })

  it('is visible without hover: no tooltip, not hidden, not collapsed, not colour alone', async () => {
    await show([contested])
    const warning = screen.getByRole('note')
    for (let el: HTMLElement | null = warning; el; el = el.parentElement) {
      expect(el.hidden).toBe(false)
      expect(el.getAttribute('aria-hidden')).not.toBe('true')
      expect(el.tagName).not.toBe('DETAILS')
    }
    expect(document.querySelector(`[title*="xác minh lại"]`)).toBeNull()             // never only a tooltip
    expect(screen.getByText(CONTESTED)).toBe(warning)                                 // real text, not an icon
    // the stylesheet never hides it, at any width
    const css = readFileSync('src/features/aiQuestions.css', 'utf8')
    const rules = [...css.matchAll(/([^{}]*\.aiq__cite-warning[^{}]*)\{([^}]*)\}/g)]
    expect(rules.length).toBeGreaterThan(0)
    for (const [, , body] of rules) expect(body).not.toMatch(/display:\s*none|visibility:\s*hidden|opacity:\s*0[;\s]|clip/)
    expect(rules[0][2]).toMatch(/overflow-wrap:\s*anywhere/)                          // no overflow at 320 px
    expect(rules[0][2]).toMatch(/border-left:\s*3px solid/)                           // a non-colour cue
  })

  it('meets WCAG AA contrast with the shared tokens (text on the warning background, detail on the panel)', () => {
    const tokens = readTokens()
    expect(contrast(tokens('--ink'), tokens('--warning-bg'))).toBeGreaterThanOrEqual(4.5)
    expect(contrast(tokens('--ink-body'), tokens('--surface'))).toBeGreaterThanOrEqual(4.5)
    expect(contrast(tokens('--ink-muted'), tokens('--surface'))).toBeGreaterThanOrEqual(4.5)
    expect(contrast(tokens('--warning-line'), tokens('--warning-bg'))).toBeGreaterThanOrEqual(3)  // non-text cue
  })

  it('passes axe (WCAG 2 A/AA rules; contrast is checked from the tokens above, jsdom has no layout)', async () => {
    const { container } = await show([contested, caveated, clean])
    const result = await axe.run(container, { runOnly: ['wcag2a', 'wcag2aa'], rules: { 'color-contrast': { enabled: false } } })
    expect(result.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.html).join(' | ')}`)).toEqual([])
  })

  it('keeps an integrity caveat distinct from a scientific contradiction', async () => {
    await show([contested, caveated])
    const notes = screen.getAllByRole('note').map((n) => n.textContent)
    expect(notes).toEqual([CONTESTED, CAVEAT])
    expect(within(groupOf('Tài liệu có lưu ý')).queryByText(/khoa học cần xác minh lại/)).toBeNull()
  })

  it('never offers a warned citation as a link, and shows no URL in or near the warning', async () => {
    await show([contested, caveated, clean])
    for (const title of ['Tài liệu AWD bị tranh chấp', 'Tài liệu có lưu ý']) {
      const group = groupOf(title)
      expect(within(group).queryByRole('link')).toBeNull()
      expect(group.textContent).not.toMatch(/https?:|example\.invalid/)
      expect(within(group).getByText(LINK_WITHHELD_NOTE)).toBeTruthy()
      expect(within(group).getByText(title)).toBeTruthy()                             // the authorized title stays
    }
    const links = screen.getAllByRole('link', { name: /Mở nguồn/ })
    expect(links.map((l) => l.getAttribute('href'))).toEqual(['https://example.invalid/clean'])
    expect(links[0].getAttribute('rel')).toBe('noopener noreferrer')
    expect(links[0].getAttribute('target')).toBe('_blank')
  })

  it('still warns when the warned citation has no URL at all', async () => {
    await show([{ ...contested, url: null }])
    expect(screen.getByRole('note').textContent).toBe(CONTESTED)
    expect(screen.queryByRole('link')).toBeNull()
  })

  it('decides navigation from the structured warning state, never from the wording', async () => {
    // a warning whose wording mentions nothing about science still withholds the link
    await show([cite({ title: 'Tài liệu X', integrityWarning: 'Lưu ý.', integrityDetail: null })])
    expect(screen.queryByRole('link')).toBeNull()
    expect(screen.getByRole('note').textContent).toBe('Lưu ý.')
  })

  it.each([
    'javascript:alert(1)', 'JAVASCRIPT:alert(1)', ' javascript:alert(1)', 'data:text/html,<script>alert(1)</script>',
    'vbscript:msgbox(1)', 'http://example.invalid/a', '//example.invalid/a', '/relative', 'https://exa mple.invalid',
    'https://', 'HTTPS://example.invalid/a', 'ftp://example.invalid/a', '',
  ])('a clean citation never renders an unsafe or non-https URL as a link: %j', async (url) => {
    expect(navigableUrl(url)).toBeNull()
    await show([cite({ title: 'Tài liệu sạch', url })])
    expect(screen.queryByRole('link')).toBeNull()
    expect(document.querySelector('a[href]')).toBeNull()
  })

  it('a clean https citation keeps its safe link', async () => {
    expect(navigableUrl('https://example.invalid/a?b=1#c')).toBe('https://example.invalid/a?b=1#c')
    await show([clean])
    expect(screen.getByRole('link', { name: /Mở nguồn/ }).getAttribute('href')).toBe('https://example.invalid/clean')
  })

  it('renders server text as text, never as HTML', async () => {
    await show([cite({ title: '<img src=x onerror=alert(1)>', integrityWarning: '<b>x</b>', integrityDetail: '<a href="javascript:1">y</a>' })])
    expect(document.querySelector('img, b, a[href^="javascript"]')).toBeNull()
    expect(screen.getByText('<img src=x onerror=alert(1)>')).toBeTruthy()
  })

  it('a manager sees the same warning, title and withheld link', async () => {
    await show([contested], 'manager')
    expect(screen.getByRole('note').textContent).toBe(CONTESTED)
    expect(screen.queryByRole('link')).toBeNull()
  })

  it('uses neutral wording: no "đã duyệt" endorsement anywhere in the panel, and says approval is not verification', async () => {
    const { container } = await show([contested, clean])
    expect(container.textContent).not.toMatch(/đã (được )?duyệt/)
    expect(screen.getByText(CITATION_SCOPE_NOTE)).toBeTruthy()
    for (const o of container.querySelectorAll('[title]')) expect(o.getAttribute('title')).not.toMatch(/đã (được )?duyệt/)
  })
})

// --- contrast helpers: the shared tokens (theme.css oklch values, styles.css aliases) -------------------------
/** vitest runs from web-dashboard/ (under jsdom a URL object is not a file URL for node:fs). */
function readTokens() {
  const css = ['src/theme.css', 'src/styles.css'].map((f) => readFileSync(f, 'utf8')).join('\n')
  const defs = new Map<string, string>()
  for (const [, name, value] of css.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) if (!defs.has(name)) defs.set(name, value.trim())
  const resolve = (name: string, depth = 0): string => {
    const v = defs.get(name)
    if (!v || depth > 10) throw new Error(`token ${name} not found`)
    const ref = /^var\(\s*(--[\w-]+)/.exec(v)
    return ref ? resolve(ref[1], depth + 1) : v
  }
  return resolve
}

function luminance(color: string): number {
  const m = /^oklch\(\s*([\d.]+)%\s+([\d.]+)\s+([\d.]+)\s*\)$/.exec(color)
  let rgb: number[]
  if (m) {
    const L = Number(m[1]) / 100, C = Number(m[2]), h = (Number(m[3]) * Math.PI) / 180
    const a = C * Math.cos(h), b = C * Math.sin(h)
    const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    const mm = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    const s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3
    rgb = [4.0767416621 * l - 3.3077115913 * mm + 0.2309699292 * s,
      -1.2684380046 * l + 2.6097574011 * mm - 0.3413193965 * s,
      -0.0041960863 * l - 0.7034186147 * mm + 1.707614701 * s].map((x) => Math.min(1, Math.max(0, x)))
  } else if (/^#[0-9a-f]{6}$/i.test(color)) {
    rgb = [1, 3, 5].map((i) => parseInt(color.slice(i, i + 2), 16) / 255)
      .map((c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4))
  } else if (/^#fff(fff)?$/i.test(color) || color === 'white') {
    rgb = [1, 1, 1]
  } else {
    throw new Error(`unsupported colour ${color}`)
  }
  return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]
}

function contrast(fg: string, bg: string): number {
  const [a, b] = [luminance(fg), luminance(bg)].sort((x, y) => y - x)
  return (a + 0.05) / (b + 0.05)
}
