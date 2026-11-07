// AI Q&A panel for one crop season, shared by the Farmer and Management entry points.
//
// Nothing is persisted, here or on the server: the panel keeps the last answer in
// component state only. It lives inside the scope-keyed app tree (App.tsx
// `scopeEpoch`), so a sign-out, a takeover by another account or a role/scope change
// remounts it empty. A late answer is applied only if it belongs to the latest question
// for the same season (generation counter), so an answer can never land on another
// season's or another person's screen.
import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { ApiError } from '../api/client'
import { askSeasonQuestion, type QuestionAnswer, type QuestionIntent } from '../api/questions'
import { suggestIntent } from './questionIntent'
import './aiQuestions.css'

export type QuestionAudience = 'farmer' | 'manager'

/** Build-time switch for the entry points (default OFF). The backend route has its own
 * switch (RAG_QA_ENABLED); both must be on for the panel to be shown and answer. */
export const aiQuestionsEnabled = import.meta.env.VITE_AI_QA_ENABLED === 'true'

/** Client-side bound on one question; the server has its own provider timeout. */
export const QUESTION_TIMEOUT_MS = 45_000

interface IntentOption { intent: QuestionIntent; label: string; hint: string }

const READ_INTENTS: IntentOption[] = [
  { intent: 'explain', label: 'Giải thích vụ', hint: 'Mô tả số liệu đã ghi nhận của vụ' },
  { intent: 'data_gap', label: 'Dữ liệu còn thiếu', hint: 'Những dữ liệu cần bổ sung để tính phát thải' },
  { intent: 'evidence', label: 'Tài liệu tham khảo', hint: 'Đoạn tài liệu đã duyệt liên quan câu hỏi' },
  { intent: 'compare', label: 'So sánh', hint: 'Đặt số liệu vụ này cạnh vụ khác bạn được xem' },
]
const FARMER_ACTION: IntentOption = {
  intent: 'recommend', label: 'Gợi ý hành động', hint: 'Chỉ dành cho nông hộ có quyền ghi của vụ',
}
const INTENT_LABEL: Record<string, string> = Object.fromEntries(
  [...READ_INTENTS, FARMER_ACTION].map((o) => [o.intent, o.label]).concat([['what_if', 'Mô phỏng']]),
)

const SUGGESTIONS: Record<QuestionAudience, { text: string; intent: QuestionIntent }[]> = {
  farmer: [
    { text: 'Vụ này đang thế nào?', intent: 'explain' },
    { text: 'Vụ này còn thiếu dữ liệu gì?', intent: 'data_gap' },
    { text: 'Tài liệu nào nói về tưới ngập khô xen kẽ?', intent: 'evidence' },
    { text: 'So với vụ trước của ruộng này thì sao?', intent: 'compare' },
  ],
  manager: [
    { text: 'Tóm tắt số liệu của vụ này', intent: 'explain' },
    { text: 'Vụ này còn thiếu dữ liệu nào để tính phát thải?', intent: 'data_gap' },
    { text: 'Có tài liệu đã duyệt nào về giảm phát thải mê-tan?', intent: 'evidence' },
    { text: 'So sánh với các vụ khác của cùng thửa', intent: 'compare' },
  ],
}

const SOURCE_TYPE: Record<string, string> = {
  guideline: 'Hướng dẫn', policy: 'Chính sách', methodology: 'Phương pháp luận',
  research: 'Nghiên cứu', tenant_document: 'Tài liệu nội bộ HTX',
}

type View =
  | { state: 'idle' }
  | { state: 'loading'; question: string }
  | { state: 'answered'; question: string; answer: QuestionAnswer }
  | { state: 'failed'; question: string; intent: QuestionIntent; message: string; retryable: boolean }

function failureMessage(error: unknown, timedOut: boolean): { message: string; retryable: boolean } {
  if (timedOut) return { message: 'Quá thời gian chờ câu trả lời. Bạn có thể thử lại.', retryable: true }
  if (!(error instanceof ApiError)) return { message: 'Không gửi được câu hỏi. Vui lòng thử lại.', retryable: true }
  if (error.code === 'backend_not_configured') return { message: 'Trợ lý hỏi đáp chưa được bật cho hệ thống này.', retryable: false }
  if (error.code === 'generation_unavailable') return { message: 'Loại câu hỏi này cần trợ lý AI, hiện chưa sẵn sàng. Hãy chọn loại câu hỏi khác.', retryable: false }
  if (error.status === 404) return { message: 'Không tìm thấy vụ, hoặc bạn không có quyền với loại câu hỏi này.', retryable: false }
  if (error.status === 422) return { message: 'Câu hỏi chưa hợp lệ. Hãy viết ngắn gọn hơn và chọn loại câu hỏi.', retryable: false }
  if (error.status === 502) return { message: 'Câu trả lời bị chặn vì không qua được bước kiểm tra nguồn dẫn. Bạn có thể thử lại.', retryable: true }
  if (error.code === 'offline') return { message: 'Không có kết nối mạng.', retryable: true }
  if (error.status === 401) return { message: 'Phiên đăng nhập đã hết. Hãy đăng nhập lại.', retryable: false }
  return { message: 'Hệ thống chưa trả lời được. Vui lòng thử lại.', retryable: true }
}

function factValue(value: QuestionAnswer['facts'][number]['value'], unit: string | null): string {
  if (value === null) return 'chưa có dữ liệu'
  if (typeof value === 'boolean') return value ? 'có' : 'không'
  return unit ? `${value} ${unit}` : String(value)
}

export function SeasonQuestionPanel({ seasonId, audience }: { seasonId: string; audience: QuestionAudience }) {
  const intents = audience === 'farmer' ? [...READ_INTENTS, FARMER_ACTION] : READ_INTENTS
  const [question, setQuestion] = useState('')
  const [intent, setIntent] = useState<QuestionIntent>('explain')
  // The user's own radio choice always wins over the typed-question hint.
  const [intentChosen, setIntentChosen] = useState(false)
  const [autoPicked, setAutoPicked] = useState<QuestionIntent | null>(null)
  const [actionNotAvailable, setActionNotAvailable] = useState(false)
  const [view, setView] = useState<View>({ state: 'idle' })
  const generation = useRef(0)
  const inFlight = useRef<AbortController | null>(null)
  const ids = useId()

  // Another season (or unmount): drop the answer and abandon anything in flight.
  useEffect(() => {
    setView({ state: 'idle' })
    return () => { generation.current += 1; inFlight.current?.abort() }
  }, [seasonId])

  async function ask(text: string, chosen: QuestionIntent) {
    const trimmed = text.trim()
    if (!trimmed) return
    inFlight.current?.abort()
    const mine = ++generation.current
    const controller = new AbortController()
    inFlight.current = controller
    let timedOut = false
    const timer = setTimeout(() => { timedOut = true; controller.abort() }, QUESTION_TIMEOUT_MS)
    setView({ state: 'loading', question: trimmed })
    try {
      const answer = await askSeasonQuestion(seasonId, { question: trimmed, intent: chosen }, controller.signal)
      if (mine !== generation.current || answer.cropSeasonId !== seasonId) return
      setView({ state: 'answered', question: trimmed, answer })
    } catch (error) {
      if (mine !== generation.current) return
      if (controller.signal.aborted && !timedOut) return
      setView({ state: 'failed', question: trimmed, intent: chosen, ...failureMessage(error, timedOut) })
    } finally {
      clearTimeout(timer)
      if (inFlight.current === controller) inFlight.current = null
    }
  }

  function onQuestionChange(text: string) {
    setQuestion(text)
    const hint = suggestIntent(text, audience === 'farmer')
    setActionNotAvailable(hint.actionNotAvailable)
    if (intentChosen) return
    if (hint.intent && intents.some((o) => o.intent === hint.intent)) {
      setIntent(hint.intent)
      setAutoPicked(hint.intent)
    } else {
      setAutoPicked(null)
    }
  }
  function chooseIntent(chosen: QuestionIntent) { setIntent(chosen); setIntentChosen(true); setAutoPicked(null) }

  function onSubmit(event: FormEvent) { event.preventDefault(); void ask(question, intent) }
  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void ask(question, intent) }
  }

  const busy = view.state === 'loading'
  return (
    <section className="aiq" aria-labelledby={`${ids}-title`}>
      <div className="aiq__head">
        <h2 id={`${ids}-title`} className="aiq__title">Hỏi đáp về vụ này</h2>
        <p className="aiq__lead">
          Câu trả lời chỉ dùng số liệu đã ghi nhận của vụ và tài liệu đã được duyệt. Hệ thống không lưu câu hỏi.
        </p>
      </div>

      <div className="aiq__suggest" role="group" aria-label="Câu hỏi gợi ý">
        {SUGGESTIONS[audience].map((s) => (
          <button key={s.text} type="button" className="aiq__chip" disabled={busy}
                  onClick={() => { setQuestion(s.text); setIntent(s.intent); setAutoPicked(null); void ask(s.text, s.intent) }}>
            {s.text}
          </button>
        ))}
      </div>

      <form className="aiq__form" onSubmit={onSubmit}>
        <fieldset className="aiq__intents">
          <legend className="aiq__legend">Loại câu hỏi</legend>
          {intents.map((o) => (
            <label key={o.intent} className={`aiq__intent${intent === o.intent ? ' is-on' : ''}`} title={o.hint}>
              <input type="radio" name={`${ids}-intent`} value={o.intent} checked={intent === o.intent}
                     onChange={() => chooseIntent(o.intent)} />
              {o.label}
            </label>
          ))}
        </fieldset>
        <label htmlFor={`${ids}-q`} className="aiq__legend">Câu hỏi của bạn</label>
        <textarea id={`${ids}-q`} className="aiq__input" rows={2} maxLength={2000} value={question}
                  placeholder="Ví dụ: Vụ này còn thiếu dữ liệu gì?" onChange={(e) => onQuestionChange(e.target.value)}
                  onKeyDown={onKeyDown} aria-describedby={`${ids}-hint`} />
        <p id={`${ids}-hint`} className="aiq__hint" aria-live="polite">
          {autoPicked && <>Đã chọn loại câu hỏi “{INTENT_LABEL[autoPicked]}” theo nội dung câu hỏi. Bạn có thể đổi.</>}
          {actionNotAvailable && <>Gợi ý hành động chỉ dành cho nông hộ có quyền ghi của vụ. Bạn vẫn có thể hỏi về số liệu, dữ liệu còn thiếu và tài liệu.</>}
        </p>
        <div className="aiq__actions">
          <button type="submit" className="aiq__send" disabled={busy || !question.trim()}>
            {busy ? 'Đang trả lời…' : 'Gửi câu hỏi'}
          </button>
        </div>
      </form>

      <div className="aiq__result" aria-live="polite" aria-busy={busy}>
        {view.state === 'loading' && (
          <div className="aiq__skeleton" role="status" aria-label="Đang soạn câu trả lời">
            <span /><span /><span />
          </div>
        )}
        {view.state === 'failed' && (
          <div className="aiq__error" role="alert">
            <p>{view.message}</p>
            {view.retryable && (
              <button type="button" className="aiq__retry" onClick={() => void ask(view.question, view.intent)}>Thử lại</button>
            )}
          </div>
        )}
        {view.state === 'answered' && <Answer answer={view.answer} question={view.question} />}
      </div>
    </section>
  )
}

function Answer({ answer, question }: { answer: QuestionAnswer; question: string }) {
  const insufficient = answer.status !== 'generated'
  const aiWritten = answer.answerSource === 'model_generated'
  const storedTitle = (ruleCode: string | null) =>
    answer.storedRecommendations.find((s) => s.ruleCode === ruleCode)?.title ?? null
  return (
    <article className={`aiq__answer${insufficient ? ' is-insufficient' : ''}`}>
      <p className="aiq__asked">Câu hỏi: {question}</p>
      <p className="aiq__kind">
        <span className={`aiq__badge${aiWritten ? ' is-ai' : ''}`}>
          {aiWritten ? 'Trợ lý AI viết' : 'Hệ thống soạn — không dùng AI'}
        </span>
        <span className="aiq__muted"> · Loại câu hỏi: {INTENT_LABEL[answer.intent] ?? answer.intent}</span>
      </p>
      {answer.answer && <p className="aiq__text">{answer.answer}</p>}
      <p className="aiq__provenance">
        {aiWritten
          ? 'Do trợ lý AI viết từ tài liệu đã duyệt; mọi số liệu và nguồn đã được hệ thống kiểm tra.'
          : 'Hệ thống tự soạn từ số liệu đã ghi nhận, không dùng mô hình AI. Đây là câu trả lời theo mẫu cố định của loại câu hỏi đã chọn, không diễn giải riêng câu chữ của bạn.'}
      </p>

      {answer.recommendations.length > 0 && (
        <div className="aiq__block">
          <h3>Trợ lý AI giải thích khuyến nghị đã có (không thay thế khuyến nghị đã lưu)</h3>
          <ul>
            {answer.recommendations.map((r) => (
              <li key={r.title}>
                <strong>{r.title}</strong>{r.actions.length > 0 && <> — {r.actions.join('; ')}</>}
                {storedTitle(r.ruleCode) && <span className="aiq__muted"> · Dựa trên khuyến nghị đã lưu: {storedTitle(r.ruleCode)}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}

      {answer.storedRecommendations.length > 0 && (
        <div className="aiq__block">
          <h3>Khuyến nghị đã lưu của hệ thống quy tắc</h3>
          <ul>
            {answer.storedRecommendations.map((s) => (
              <li key={s.ruleCode}>
                {s.title ?? s.ruleCode}
                <span className="aiq__muted"> · {s.type === 'data_task' ? 'Bổ sung dữ liệu' : 'Tối ưu hoá'}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {answer.limitations.length > 0 && (
        <div className="aiq__block">
          <h3>Giới hạn</h3>
          <ul>{answer.limitations.map((l) => <li key={l}>{l}</li>)}</ul>
        </div>
      )}

      <div className="aiq__block">
        <h3>Nguồn tài liệu</h3>
        {answer.citations.length === 0 ? (
          <p className="aiq__muted">Chưa có tài liệu đã duyệt nào khớp với câu hỏi này.</p>
        ) : (
          <ol className="aiq__citations">
            {answer.citations.map((c) => (
              <li key={`${c.sourceId}/${c.chunkId}`}>
                <span className="aiq__cite-title">{c.title}</span>
                {c.section && <span className="aiq__muted"> · {c.section}</span>}
                <span className="aiq__muted"> · {SOURCE_TYPE[c.sourceType] ?? c.sourceType}</span>
                {c.publishedAt && <span className="aiq__muted"> · {c.publishedAt}</span>}
                {c.url && (
                  <> · <a href={c.url} target="_blank" rel="noopener noreferrer">Mở nguồn<span className="sr-only"> (tab mới)</span></a></>
                )}
              </li>
            ))}
          </ol>
        )}
      </div>

      {answer.facts.length > 0 && (
        <details className="aiq__block">
          <summary>Số liệu hệ thống dùng trong câu trả lời ({answer.facts.length})</summary>
          <ul className="aiq__facts">
            {answer.facts.map((f) => <li key={f.factId}><code>{f.factId}</code>: {factValue(f.value, f.unit)}</li>)}
          </ul>
        </details>
      )}
    </article>
  )
}
