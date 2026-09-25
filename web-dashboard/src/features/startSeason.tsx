import { useId, useState, type FormEvent } from 'react'
import { ApiError } from '../api/client'
import { startCropSeason, type StartedSeason } from '../api/crops'
import type { Plot } from '../types'

/* "Bắt đầu vụ mới" — one form for Farmer Web and Management Web.
 *
 * Both call the same endpoint (`POST /v1/plots/{id}/crop-seasons`) through
 * `startCropSeason`; there is no second mutation path. The form asks only
 * what a person knows when starting a season. Crop type, status and the
 * default production batch are the server's: the season comes back already
 * able to take activities, so nothing here creates a batch. Carbon methodology
 * inputs are not asked for — they are supplied later on the Carbon page and
 * are never defaulted. */

export interface StartSeasonFormProps {
  /** Plots the viewer may start a season on. More than one shows a picker. */
  plots: Plot[]
  initialPlotId?: string | null
  onStarted: (started: StartedSeason, plot: Plot) => void
  onCancel: () => void
  /** Only the button classes differ between the two experiences. */
  variant: 'farmer' | 'management'
}

const MESSAGES: Record<string, string> = {
  active_season_exists: 'Thửa này đang có một vụ đang canh tác. Kết thúc vụ đó trước khi bắt đầu vụ mới.',
  season_code_exists: 'Thửa này đã có một vụ với tên này. Hãy đặt tên khác, ví dụ thêm năm.',
  not_found: 'Bạn không có quyền bắt đầu vụ trên thửa này, hoặc thửa không còn tồn tại.',
  offline: 'Không kết nối được máy chủ. Kiểm tra mạng rồi thử lại.',
}

/** The message shown for a failed start. Exported for tests. */
export function startSeasonErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (MESSAGES[err.code]) return MESSAGES[err.code]
    if (err.status === 422) return 'Thông tin vụ chưa hợp lệ. Kiểm tra lại tên vụ và các ngày.'
  }
  return 'Chưa bắt đầu được vụ. Vui lòng thử lại.'
}

/** Field problems the server would also refuse, said before sending. */
export function startSeasonFieldErrors(v: { seasonCode: string; plantingDate: string; expectedHarvestDate: string }): Record<string, string> {
  const out: Record<string, string> = {}
  const code = v.seasonCode.trim()
  if (!code) out.seasonCode = 'Nhập tên vụ, ví dụ "Hè Thu 2026".'
  else if (code.length > 64) out.seasonCode = 'Tên vụ tối đa 64 ký tự.'
  if (v.plantingDate && v.expectedHarvestDate && v.expectedHarvestDate < v.plantingDate) {
    out.expectedHarvestDate = 'Ngày dự kiến thu hoạch không được trước ngày gieo sạ.'
  }
  return out
}

export function StartSeasonForm({ plots, initialPlotId, onStarted, onCancel, variant }: StartSeasonFormProps) {
  const [plotId, setPlotId] = useState<string>(initialPlotId ?? (plots.length === 1 ? plots[0].id : ''))
  const [seasonCode, setSeasonCode] = useState('')
  const [variety, setVariety] = useState('')
  const [plantingDate, setPlantingDate] = useState('')
  const [expectedHarvestDate, setExpectedHarvestDate] = useState('')
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [failure, setFailure] = useState<string | null>(null)
  // Disables the submit button while a request is in flight: a double click
  // cannot send a second request. The server also refuses a second active
  // season on the plot and answers an identical repeat with the same season.
  const [pending, setPending] = useState(false)
  const ids = { plot: useId(), code: useId(), variety: useId(), planting: useId(), harvest: useId() }
  const btn = variant === 'farmer'
    ? { primary: 'fw-btn', ghost: 'fw-btn fw-btn--ghost' }
    : { primary: 'btn btn--primary', ghost: 'btn btn--ghost' }

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (pending) return
    const found = startSeasonFieldErrors({ seasonCode, plantingDate, expectedHarvestDate })
    if (!plotId) found.plot = 'Chọn thửa ruộng.'
    setErrors(found)
    setFailure(null)
    if (Object.keys(found).length) return
    const plot = plots.find((p) => p.id === plotId)!
    setPending(true)
    try {
      const started = await startCropSeason(plot.id, { seasonCode, variety, plantingDate, expectedHarvestDate })
      onStarted(started, plot)
    } catch (err) {
      setFailure(startSeasonErrorMessage(err))
      setPending(false)
    }
  }

  const err = (key: string, id: string) => errors[key]
    ? <span id={`${id}-err`} className="form-field__error" role="alert">{errors[key]}</span>
    : null

  return (
    <form className="start-season" onSubmit={submit} noValidate aria-busy={pending || undefined}>
      {plots.length > 1 ? (
        <div className="form-field" aria-invalid={errors.plot ? 'true' : undefined}>
          <label htmlFor={ids.plot}>Thửa ruộng <span className="form-field__required" aria-hidden="true">*</span></label>
          <select id={ids.plot} value={plotId} onChange={(e) => setPlotId(e.target.value)} aria-required aria-describedby={errors.plot ? `${ids.plot}-err` : undefined}>
            <option value="" disabled>— Chọn thửa —</option>
            {plots.map((p) => <option key={p.id} value={p.id}>{p.name} · Mã {p.code}</option>)}
          </select>
          {err('plot', ids.plot)}
        </div>
      ) : plots[0] ? (
        <p className="start-season__target">Thửa <b>{plots[0].name}</b> · Mã {plots[0].code}</p>
      ) : null}

      <div className="form-field" aria-invalid={errors.seasonCode ? 'true' : undefined}>
        <label htmlFor={ids.code}>Tên vụ <span className="form-field__required" aria-hidden="true">*</span></label>
        <input id={ids.code} value={seasonCode} onChange={(e) => setSeasonCode(e.target.value)} placeholder="Ví dụ: Hè Thu 2026"
          maxLength={64} autoComplete="off" aria-required aria-describedby={errors.seasonCode ? `${ids.code}-err` : undefined} autoFocus />
        {err('seasonCode', ids.code)}
      </div>

      <div className="form-field">
        <label htmlFor={ids.variety}>Giống lúa <span className="form-field__opt">Không bắt buộc</span></label>
        <input id={ids.variety} value={variety} onChange={(e) => setVariety(e.target.value)} placeholder="Ví dụ: OM5451" maxLength={120} autoComplete="off" />
      </div>

      <div className="start-season__dates">
        <div className="form-field">
          <label htmlFor={ids.planting}>Ngày gieo sạ <span className="form-field__opt">Không bắt buộc</span></label>
          <input id={ids.planting} type="date" value={plantingDate} onChange={(e) => setPlantingDate(e.target.value)} />
        </div>
        <div className="form-field" aria-invalid={errors.expectedHarvestDate ? 'true' : undefined}>
          <label htmlFor={ids.harvest}>Dự kiến thu hoạch <span className="form-field__opt">Không bắt buộc</span></label>
          <input id={ids.harvest} type="date" value={expectedHarvestDate} onChange={(e) => setExpectedHarvestDate(e.target.value)}
            aria-describedby={errors.expectedHarvestDate ? `${ids.harvest}-err` : undefined} />
          {err('expectedHarvestDate', ids.harvest)}
        </div>
      </div>

      <p className="start-season__note">Vụ bắt đầu ở trạng thái <b>đang canh tác</b>. Thông tin phương pháp tính Carbon được bổ sung sau, trên trang Carbon của vụ.</p>

      {failure && <div className="form-error" role="alert">{failure}</div>}

      <div className="start-season__actions">
        <button type="button" className={btn.ghost} onClick={onCancel} disabled={pending}>Hủy</button>
        <button type="submit" className={btn.primary} disabled={pending}>{pending ? 'Đang bắt đầu vụ…' : 'Bắt đầu vụ'}</button>
      </div>
    </form>
  )
}
