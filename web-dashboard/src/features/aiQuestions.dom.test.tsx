// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/client'
import type { QuestionAnswer } from '../api/questions'

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

import { QUESTION_TIMEOUT_MS, SeasonQuestionPanel } from './aiQuestions'

const answer = (over: Partial<QuestionAnswer> = {}): QuestionAnswer => ({
  status: 'generated', intent: 'explain', cropSeasonId: 's1',
  answer: 'Tổng phát thải khí nhà kính đã tính cho vụ: 2.900 kg CO2e.',
  limitations: ['Câu trả lời được hệ thống soạn từ dữ liệu đã ghi nhận và tài liệu đã duyệt; đây không phải lời khuyên canh tác.'],
  insufficientReason: null,
  citations: [{ sourceId: 'src', chunkId: 'c1', documentId: 'doc', documentVersion: 'v1', title: 'Hướng dẫn tưới AWD',
                section: 'Tưới nước', sourceType: 'guideline', url: 'https://example.invalid/awd', publishedAt: '2025-11-10' }],
  facts: [{ factId: 'current.carbon.total_co2e_kg', kind: 'carbon_total', value: 2900, unit: 'kg CO2e', source: 'carbon_service' }],
  recommendations: [], answerSource: 'system_composed', model: null, ...over,
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

  it('a farmer may choose it; the server still decides', () => {
    render(<SeasonQuestionPanel seasonId="s1" audience="farmer" />)
    expect(screen.getByLabelText('Gợi ý hành động')).toBeTruthy()
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

  it('insufficient evidence is shown as such, with no citation invented', async () => {
    ask.resolve(answer({ status: 'insufficient_evidence', answer: 'Chưa có tài liệu đã duyệt đủ để trả lời câu hỏi này.',
                                   citations: [], facts: [], insufficientReason: 'no_evidence_retrieved' }))
    render(<SeasonQuestionPanel seasonId="s1" audience="farmer" />)
    fireEvent.click(screen.getByRole('button', { name: /tưới ngập khô xen kẽ/ }))
    expect(await screen.findByText(/Chưa có tài liệu đã duyệt nào khớp/)).toBeTruthy()
    expect(screen.queryByRole('link', { name: /Mở nguồn/ })).toBeNull()
  })

  it.each([
    [503, 'backend_not_configured', /chưa được bật/, false],
    [503, 'generation_unavailable', /chưa sẵn sàng/, false],
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
