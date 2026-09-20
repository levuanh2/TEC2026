import { useId, useState, type ReactNode } from 'react'
import { calculateCarbon, type CarbonMissingInput, type CarbonMissingRecord, type CarbonReadiness } from '../api/carbon'
import { updateSeasonMethodology } from '../api/crops'
import { PRE_SEASON_REGIMES, WATER_REGIMES } from '../features/seasonMethodology'
import type { Activity, IpccPreSeasonRegime, IpccWaterRegime } from '../types'
import { Link } from '../ui'
import { isSupportedActivityType, type ActivityMutations, type SeasonContext } from './ActivityForms'
import { ACTIVITY_TITLE, dayLabel } from './activityView'
import { invalidateQueries, keys } from './data'
import { Ico } from './icons'

/**
 * The Carbon tab as a repair hub: every input the server says is missing, each
 * with the one action that supplies it, on this page.
 *
 * No methodology lives here. Which inputs are missing, their wording, which
 * screen fixes each (`flow`) and which stored records they concern (`records`)
 * all come from `/carbon/readiness`. This component only maps a `flow` to a
 * control:
 *   carbon_methodology → inline editor for that one season field
 *   activity           → "Sửa ngay" opening the existing edit sheet for the record
 *   plot               → link to the plot
 *   factor_unavailable → an honest limitation, never a form
 * Validation stays where it already is: the shared activity form and the API.
 */

export function CarbonRepairHub({ seasonId, readiness, hasResult, stale, plotId, writeCtx, activities, mutations, onSeasonSaved }: {
  seasonId: string
  readiness: CarbonReadiness
  /** A stored Carbon result exists, so the ready-state action is "Tính lại". */
  hasResult: boolean
  /** The stored result predates the farmer's latest edit. */
  stale?: boolean
  plotId?: string | null
  /** The season as a write target; null for a viewer, who gets no edit controls. */
  writeCtx: SeasonContext | null
  activities?: Activity[]
  mutations?: ActivityMutations
  onSeasonSaved?: () => void
}) {
  const blocking = readiness.missing_inputs.filter((m) => m.blocking)
  const optional = readiness.missing_inputs.filter((m) => !m.blocking)
  const titleId = useId()

  if (!blocking.length) {
    return (
      <section
        className={`fw-repair fw-repair--ready fw-role fw-role--${stale ? 'attention' : hasResult ? 'positive' : 'info'}`}
        aria-labelledby={titleId} data-testid="carbon-ready"
      >
        {/* Three of the five states live here — ready to calculate, already
          * calculated, and calculated-but-out-of-date — each named in words. */}
        <p className="fw-repair__status">
          <Ico name={stale ? 'warning' : 'check'} />
          {stale ? 'Cần tính lại' : hasResult ? 'Đã tính' : 'Sẵn sàng tính'}
        </p>
        <h2 id={titleId}>
          {stale
            ? 'Dữ liệu đã thay đổi sau lần tính gần nhất.'
            : hasResult ? 'Vụ này đã có kết quả phát thải.' : 'Đã đủ dữ liệu để tính phát thải.'}
        </h2>
        {optional.map((m) => <p key={m.code} className="fw-note">{m.label} — {m.detail}</p>)}
        {writeCtx
          ? <CalculateAction seasonId={seasonId} again={hasResult} />
          : <p className="fw-note">Chủ hộ hoặc cán bộ hợp tác xã có quyền ghi sẽ tính kết quả cho vụ này.</p>}
      </section>
    )
  }

  const byId = new Map((activities ?? []).map((a) => [a.id, a]))
  return (
    <section className="fw-repair" aria-labelledby={titleId}>
      <h2 id={titleId}>Cần bổ sung {blocking.length} thông tin để tính phát thải</h2>
      <p className="fw-note">
        {writeCtx ? 'Sửa trực tiếp tại đây — mục đã xong sẽ tự biến mất.' : 'Bạn chỉ có quyền xem. Hãy liên hệ chủ hộ hoặc cán bộ hợp tác xã để bổ sung.'}
      </p>
      <ol className="fw-repair__list" data-testid="carbon-missing">
        {blocking.map((m) => (
          <RepairItem key={m.code} issue={m} seasonId={seasonId} plotId={plotId} writeCtx={writeCtx} byId={byId} mutations={mutations} onSeasonSaved={onSeasonSaved} />
        ))}
      </ol>
      {optional.map((m) => <p key={m.code} className="fw-note">{m.label} — {m.detail}</p>)}
    </section>
  )
}

function RepairItem({ issue, seasonId, plotId, writeCtx, byId, mutations, onSeasonSaved }: {
  issue: CarbonMissingInput
  seasonId: string
  plotId?: string | null
  writeCtx: SeasonContext | null
  byId: Map<string, Activity>
  mutations?: ActivityMutations
  onSeasonSaved?: () => void
}) {
  const titleId = useId()
  const limitation = issue.flow === 'factor_unavailable'
  const journal = `/farmer/crop-seasons/${seasonId}/journal`
  let action: ReactNode = null

  if (issue.flow === 'carbon_methodology') {
    action = writeCtx
      ? <SeasonFieldFix code={issue.code} seasonId={seasonId} labelledBy={titleId} onSaved={onSeasonSaved} />
      : null
  } else if (issue.flow === 'activity') {
    const records = issue.records ?? []
    action = records.length && writeCtx && mutations ? (
      <ul className="fw-repair__records">
        {records.map((r) => (
          <RecordRow key={r.activity_id} record={r} activity={byId.get(r.activity_id)} activityType={issue.activity_type}
            onEdit={(a) => mutations.openEdit(a, writeCtx, { revealMore: true })} journal={journal} />
        ))}
      </ul>
    ) : writeCtx ? <Link to={journal} className="fw-btn fw-btn--soft fw-btn--sm">Mở nhật ký vụ</Link> : null
  } else if (issue.flow === 'plot') {
    action = (
      <>
        <p className="fw-note">Diện tích thửa do cán bộ hợp tác xã quản lý trong hồ sơ thửa.</p>
        {plotId && <Link to={`/farmer/plots/${plotId}`} className="fw-btn fw-btn--soft fw-btn--sm">Cập nhật diện tích</Link>}
      </>
    )
  } else if (limitation) {
    action = <Link to={journal} className="fw-btn fw-btn--ghost fw-btn--sm">Xem bản ghi nhiên liệu</Link>
  }

  return (
    <li className={`fw-repair__item fw-role fw-role--${limitation ? 'info' : 'attention'}${limitation ? ' is-limit' : ''}`} aria-labelledby={titleId}>
      {/* State in words, not only colour. */}
      <p className="fw-repair__status">
        <Ico name={limitation ? 'info' : 'warning'} />
        {limitation ? 'Giới hạn của bộ hệ số — nhập thêm không giúp tính được' : 'Cần bổ sung'}
      </p>
      <h3 id={titleId}>{limitation ? 'Vụ có ghi nhiên liệu nhưng hệ số phát thải nhiên liệu chưa được xác minh.' : issue.label}</h3>
      <p>{issue.detail}</p>
      {action}
    </li>
  )
}

function RecordRow({ record, activity, activityType, onEdit, journal }: {
  record: CarbonMissingRecord
  activity?: Activity
  activityType: string | null
  onEdit: (a: Activity) => void
  journal: string
}) {
  const kind = ACTIVITY_TITLE[activityType ?? ''] ?? 'Bản ghi'
  const when = record.occurred_on ? dayLabel(record.occurred_on) : null
  const name = [kind, record.label, when].filter(Boolean).join(' · ')
  return (
    <li>
      <span>{name}</span>
      {activity && isSupportedActivityType(activity.type)
        ? <button type="button" className="fw-btn fw-btn--primary fw-btn--sm" aria-label={`Sửa ngay: ${name}`} onClick={() => onEdit(activity)}><Ico name="edit" />Sửa ngay</button>
        : <Link to={journal} className="fw-btn fw-btn--soft fw-btn--sm">Mở trong nhật ký</Link>}
    </li>
  )
}

/* ------------------------------------------------ season-field quick fix */

type SeasonField = 'ipccWaterRegime' | 'preSeasonWaterRegime' | 'cultivationDays'
const SEASON_FIELD: Record<string, { field: SeasonField; label: string; options?: { value: string; label: string; help: string }[] }> = {
  water_regime: { field: 'ipccWaterRegime', label: 'Chế độ nước trong vụ', options: WATER_REGIMES },
  pre_season_water_regime: { field: 'preSeasonWaterRegime', label: 'Chế độ nước trước vụ', options: PRE_SEASON_REGIMES },
  cultivation_days: { field: 'cultivationDays', label: 'Số ngày canh tác' },
}

function SeasonFieldFix({ code, seasonId, labelledBy, onSaved }: {
  code: string; seasonId: string; labelledBy: string; onSaved?: () => void
}) {
  const spec = SEASON_FIELD[code]
  const inputId = useId()
  const [value, setValue] = useState('')
  const [state, setState] = useState<{ busy: boolean; error?: string; saved?: boolean }>({ busy: false })
  if (!spec) return <a className="fw-btn fw-btn--soft fw-btn--sm" href="#fw-carbon-methodology">Bổ sung dữ liệu Carbon</a>

  async function save() {
    setState({ busy: true })
    try {
      const patch = spec.field === 'cultivationDays'
        ? { cultivationDays: Number(value) }
        : spec.field === 'ipccWaterRegime'
          ? { ipccWaterRegime: value as IpccWaterRegime }
          : { preSeasonWaterRegime: value as IpccPreSeasonRegime }
      await updateSeasonMethodology(seasonId, patch)
      setState({ busy: false, saved: true })
      // The parent refetches the season and readiness; the item disappears once
      // readiness comes back without it.
      onSaved?.()
    } catch (e) {
      const status = (e as { status?: number })?.status
      setState({ busy: false, error: status === 404 ? 'Bạn không có quyền sửa vụ này.' : e instanceof Error ? e.message : 'Không lưu được.' })
    }
  }

  const help = spec.options?.find((o) => o.value === value)?.help
  return (
    <form className="fw-repair__fix" aria-labelledby={labelledBy} onSubmit={(e) => { e.preventDefault(); if (value.trim()) void save() }}>
      <label htmlFor={inputId}>{spec.label}</label>
      <div className="fw-repair__row">
        {spec.options ? (
          <select id={inputId} value={value} onChange={(e) => setValue(e.target.value)} aria-describedby={help ? `${inputId}-help` : undefined}>
            <option value="" disabled>— Chọn —</option>
            {spec.options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        ) : (
          <span className="fw-repair__unit">
            <input id={inputId} type="number" inputMode="numeric" step="1" min="1" value={value} onChange={(e) => setValue(e.target.value)} />
            <span>ngày</span>
          </span>
        )}
        <button type="submit" className="fw-btn fw-btn--primary fw-btn--sm" disabled={state.busy || !value.trim()}>
          {state.busy ? 'Đang lưu…' : state.saved ? 'Đã lưu' : 'Lưu'}
        </button>
      </div>
      {help && <small id={`${inputId}-help`}>{help}</small>}
      {state.error && <p className="fw-form__error" role="alert">{state.error}</p>}
      {state.saved && <p className="fw-note" role="status">Đã lưu. Đang cập nhật danh sách…</p>}
    </form>
  )
}

/* ------------------------------------------------------- ready → calculate */

function CalculateAction({ seasonId, again }: { seasonId: string; again: boolean }) {
  const [state, setState] = useState<{ busy: boolean; error?: string }>({ busy: false })
  async function run() {
    setState({ busy: true })
    try {
      await calculateCarbon(seasonId, 'as_recorded')
      setState({ busy: false })
      // The stored result, readiness and the dashboard's Carbon completeness.
      invalidateQueries(keys.carbon(seasonId), keys.metrics(seasonId))
    } catch (e) {
      setState({ busy: false, error: e instanceof Error ? e.message : 'Không tính được.' })
    }
  }
  return (
    <>
      <p className="fw-cta-row">
        <button type="button" className="fw-btn fw-btn--primary" onClick={() => void run()} disabled={state.busy}>
          <Ico name="calculator" />{state.busy ? 'Đang tính…' : again ? 'Tính lại Carbon' : 'Tính Carbon'}
        </button>
      </p>
      {state.error && <p className="fw-form__error" role="alert">{state.error}</p>}
    </>
  )
}
