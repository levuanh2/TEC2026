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
import { askSeasonQuestion, type QuestionAnswer, type QuestionCitation, type QuestionIntent } from '../api/questions'
import { suggestIntent } from './questionIntent'
import './aiQuestions.css'

export type QuestionAudience = 'farmer' | 'manager'

// Entry points decide visibility with `useAiQuestionsVisible()` (aiQuestionsVisibility.ts): the
// build flag VITE_AI_QA_ENABLED AND the server's `ai_qa_available` for this session (V-1b).
// There is deliberately no build-flag-only export here any more.
/** Offer the farmer action intent only when the server's action tier is on too
 *  (`RAG_QA_ACTION_TIER_ENABLED=true`); the server refuses it either way when it is off. */
export const aiActionTierEnabled = import.meta.env.VITE_AI_QA_ACTION_ENABLED === 'true'

/** Client-side bound on one question; the server has its own provider timeout. */
export const QUESTION_TIMEOUT_MS = 45_000

interface IntentOption { intent: QuestionIntent; label: string; hint: string }

const READ_INTENTS: IntentOption[] = [
  { intent: 'explain', label: 'Giải thích vụ', hint: 'Mô tả số liệu đã ghi nhận của vụ' },
  { intent: 'data_gap', label: 'Dữ liệu còn thiếu', hint: 'Những dữ liệu cần bổ sung để tính phát thải' },
  { intent: 'evidence', label: 'Tài liệu tham khảo', hint: 'Đoạn tài liệu trong kho tri thức liên quan câu hỏi' },
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
    { text: 'Có tài liệu nào trong kho tri thức về giảm phát thải mê-tan?', intent: 'evidence' },
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
  if (error.code === 'action_tier_disabled') return { message: 'Giai đoạn thử nghiệm chỉ hỗ trợ câu hỏi giải thích số liệu; chưa có gợi ý hành động.', retryable: false }
  if (error.code === 'question_rate_limited') return { message: 'Bạn đã hỏi quá nhiều câu trong thời gian ngắn. Vui lòng thử lại sau ít phút.', retryable: false }
  if (error.code === 'question_rate_limit_unavailable') return { message: 'Trợ lý tạm thời chưa nhận câu hỏi. Vui lòng thử lại sau.', retryable: false }
  if (error.code === 'question_not_enabled') return { message: 'Tính năng hỏi đáp đang thử nghiệm và chưa mở cho tài khoản này.', retryable: false }
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

/** A11 privacy notice, owner-approved text (2026-11-25). Shown above the panel for every pilot user. */
export const QA_PRIVACY_NOTICE =
  'Tính năng hỏi đáp đang trong giai đoạn thử nghiệm, hỗ trợ giải thích dữ liệu vụ mùa thuộc phạm vi được phép truy cập. ' +
  'Hệ thống không gửi nội dung câu hỏi đến mô hình AI bên ngoài trong chế độ hiện tại và chưa cung cấp khuyến nghị canh tác tự động. ' +
  'Hệ thống có giới hạn tần suất sử dụng và lưu thông tin vận hành cần thiết để bảo đảm an toàn, ổn định dịch vụ. ' +
  'Nội dung câu hỏi không được lưu; hệ thống chỉ ghi tài khoản và thời điểm hỏi để giới hạn tần suất. ' +
  'Số liệu Carbon là ước tính nội bộ, chưa đạt yêu cầu MRV. ' +
  'Nếu câu trả lời sai hoặc hiển thị dữ liệu không thuộc về bạn, hãy ngừng sử dụng và báo cho quản trị viên HTX.'

export function SeasonQuestionPanel({ seasonId, audience, actionTier = aiActionTierEnabled }: {
  seasonId: string; audience: QuestionAudience; actionTier?: boolean
}) {
  const canAct = audience === 'farmer' && actionTier
  const readOnlyTrial = audience === 'farmer' && !actionTier
  const intents = canAct ? [...READ_INTENTS, FARMER_ACTION] : READ_INTENTS
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
    const hint = suggestIntent(text, canAct)
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
          Câu trả lời chỉ dùng số liệu đã ghi nhận của vụ và tài liệu trong kho tri thức. Hệ thống không lưu câu hỏi.
        </p>
        <p className="aiq__notice" role="note" aria-label="Thông báo quyền riêng tư">{QA_PRIVACY_NOTICE}</p>
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
          {actionNotAvailable && (readOnlyTrial
            ? <>Giai đoạn thử nghiệm chưa có gợi ý hành động. Bạn vẫn có thể hỏi về số liệu, dữ liệu còn thiếu và tài liệu.</>
            : <>Gợi ý hành động chỉ dành cho nông hộ có quyền ghi của vụ. Bạn vẫn có thể hỏi về số liệu, dữ liệu còn thiếu và tài liệu.</>)}
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
          ? 'Do trợ lý AI viết từ tài liệu trong kho tri thức; hệ thống đã đối chiếu số liệu và nguồn dẫn với dữ liệu được truy xuất, không xác minh nội dung khoa học.'
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
          <p className="aiq__muted">Chưa có đoạn tài liệu nào trong kho tri thức khớp với câu hỏi này.</p>
        ) : (
          <>
            <p className="aiq__muted">{CITATION_SCOPE_NOTE}</p>
            <ol className="aiq__citations">
              {answer.citations.map((c) => <Citation key={`${c.sourceId}/${c.chunkId}`} citation={c} />)}
            </ol>
          </>
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

/** Workflow approval is not scientific verification (M7 READ-tier citation UX, 2026-11-16). */
export const CITATION_SCOPE_NOTE =
  'Tài liệu được dẫn là tài liệu trong kho tri thức đã qua quy trình duyệt tài liệu; điều đó không có nghĩa nội dung khoa học đã được xác minh độc lập.'
/** Shown instead of the link when a citation carries an integrity warning. */
export const LINK_WITHHELD_NOTE = 'Không hiển thị liên kết nguồn cho tài liệu có cảnh báo kiểm tra.'

/** Only an https URL is ever offered as a link. Re-checked here, not only in the API mapper. */
export function navigableUrl(url: string | null): string | null {
  if (typeof url !== 'string' || !/^https:\/\/[^\s]+$/.test(url)) return null
  try { return new URL(url).protocol === 'https:' ? url : null } catch { return null }
}

/** One citation. The warning sits directly after the title, always visible (no tooltip), and is the
 *  accessible description of the citation group. A warned citation is never offered as a link: that
 *  decision uses the server's structured state (integrityWarning present), never the warning's wording.
 *  All text is rendered as React text nodes (no HTML interpolation). */
function Citation({ citation: c }: { citation: QuestionCitation }) {
  const id = useId()
  const warned = c.integrityWarning !== null
  const url = warned ? null : navigableUrl(c.url)
  const titleId = `${id}-title`
  const warningId = `${id}-warning`
  const detailId = `${id}-detail`
  const described = warned ? [warningId, ...(c.integrityDetail ? [detailId] : [])].join(' ') : undefined
  return (
    <li className={`aiq__cite${warned ? ' is-warned' : ''}`}>
      <div role="group" aria-labelledby={titleId} aria-describedby={described}>
        <span id={titleId} className="aiq__cite-title">{c.title}</span>
        {warned && <p id={warningId} className="aiq__cite-warning" role="note">{c.integrityWarning}</p>}
        {warned && c.integrityDetail && <p id={detailId} className="aiq__cite-detail">{c.integrityDetail}</p>}
        <p className="aiq__cite-meta">
          {[c.section, SOURCE_TYPE[c.sourceType] ?? c.sourceType, c.publishedAt].filter(Boolean).join(' · ')}
          {url && (
            <> · <a href={url} target="_blank" rel="noopener noreferrer">Mở nguồn<span className="sr-only"> (tab mới)</span></a></>
          )}
          {warned && <> · <span className="aiq__cite-nolink">{LINK_WITHHELD_NOTE}</span></>}
        </p>
      </div>
    </li>
  )
}
