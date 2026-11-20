import { afterEach, describe, expect, it, vi } from 'vitest'
import { setAccessToken, setWriteListener } from './client'
import { askSeasonQuestion, mapAnswer } from './questions'

const BODY = {
  status: 'generated', intent: 'explain', mode: 'ask', crop_season_id: 's1', answer: 'Trả lời',
  citations: [{ source_id: 's', chunk_id: 'c', document_id: 'd', title: 'T', source_type: 'guideline',
                url: 'javascript:alert(1)' }],
  trusted_facts: [], limitations: [], provenance: { answer_source: 'system_composed', llm_calls: 0, persisted: false },
}

describe('askSeasonQuestion', () => {
  afterEach(() => { vi.unstubAllGlobals(); setAccessToken(null); setWriteListener(null) })

  it('POSTs only question + intent with the user JWT, and does not mark cached reads stale', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(BODY), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock); setAccessToken('user-jwt')
    const onWrite = vi.fn(); setWriteListener(onWrite)
    await askSeasonQuestion('s1', { question: 'Q', intent: 'explain' })
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toMatch(/\/v1\/crop-seasons\/s1\/questions$/)
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({ question: 'Q', intent: 'explain' })
    expect(init.headers.get('Authorization')).toBe('Bearer user-jwt')
    expect(onWrite).not.toHaveBeenCalled()
  })

  it('a what-if question carries its scenario', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(BODY), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    await askSeasonQuestion('s1', { question: 'Q', intent: 'what_if', whatIfScenario: 'awd' })
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ question: 'Q', intent: 'what_if', what_if_scenario: 'awd' })
  })

  it('never offers a non-https citation link', () => {
    expect(mapAnswer(BODY).citations[0].url).toBeNull()
    expect(mapAnswer({ ...BODY, citations: [{ ...BODY.citations[0], url: 'https://example.invalid/x' }] }).citations[0].url)
      .toBe('https://example.invalid/x')
  })

  it('maps the server integrity warning of a citation, and nothing else as one (M7 E3)', () => {
    const sentence = 'Tài liệu đang có nội dung khoa học cần xác minh lại; không sử dụng làm căn cứ hướng dẫn canh tác.'
    expect(mapAnswer(BODY).citations[0].integrityWarning).toBeNull()
    const warned = { ...BODY, citations: [{ ...BODY.citations[0], integrity_warning: sentence }] }
    expect(mapAnswer(warned).citations[0].integrityWarning).toBe(sentence)
    for (const bad of ['', 42, { text: 'x' }])
      expect(mapAnswer({ ...BODY, citations: [{ ...BODY.citations[0], integrity_warning: bad }] }).citations[0].integrityWarning).toBeNull()
  })

  it('maps the additive finding detail only alongside a warning (older servers omit it)', () => {
    const c = BODY.citations[0]
    const detail = 'Phát hiện kiểm tra: mâu thuẫn với tài liệu tham chiếu.'
    expect(mapAnswer(BODY).citations[0].integrityDetail).toBeNull()                         // field absent: compatible
    expect(mapAnswer({ ...BODY, citations: [{ ...c, integrity_warning: 'w', integrity_detail: detail }] }).citations[0].integrityDetail).toBe(detail)
    expect(mapAnswer({ ...BODY, citations: [{ ...c, integrity_warning: null, integrity_detail: detail }] }).citations[0].integrityDetail).toBeNull()
    for (const bad of ['', 42, { text: 'x' }, null])
      expect(mapAnswer({ ...BODY, citations: [{ ...c, integrity_warning: 'w', integrity_detail: bad }] }).citations[0].integrityDetail).toBeNull()
  })

  it('maps the stored M05 rule outcomes apart from the generated suggestions', () => {
    const mapped = mapAnswer({ ...BODY, signals: [{ rule_code: 'data.completeness.water', type: 'data_task',
                                                    title: 'Bổ sung lượng nước tưới', status: 'generated', reason: 'x' }] })
    expect(mapped.storedRecommendations).toEqual([{ ruleCode: 'data.completeness.water', type: 'data_task',
                                                    title: 'Bổ sung lượng nước tưới', status: 'generated' }])
    expect(mapAnswer(BODY).storedRecommendations).toEqual([])
  })

  it('maps the error envelope', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(
      { detail: { error: { code: 'generation_unavailable', message: 'm' } } }), { status: 503 })))
    await expect(askSeasonQuestion('s1', { question: 'Q', intent: 'recommend' }))
      .rejects.toMatchObject({ status: 503, code: 'generation_unavailable' })
  })
})
