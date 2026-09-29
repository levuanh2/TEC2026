import type { ReactNode } from 'react'
import type { CarbonReadiness } from '../api/carbon'
import { carbonView } from '../carbon/readiness'
import type { SeasonMetrics } from '../api/metrics'
import { date, daysSince, ha } from '../format'
import type { Activity } from '../types'
import { Link } from '../ui'
import { localDay } from './activityView'
import type { QueryState } from './data'
import { Ico, type IconName } from './icons'
import { Sk } from './kit'
import { homeSummary, journalLine, metricDetails, readable, type Reading, type SeasonFacts } from './metricsView'
import { seasonStatusLabel, type SeasonCtx } from './scope'
import { harvestDate, sowingDate, type SeasonDate } from './seasonDates'

/* The hybrid Farmer surface: identity, ONE next action, and a compact read of
 * how the season is doing.
 *
 * Every figure here already exists in the API responses this page loads
 * (`/metrics`, `/activities`, `/carbon/readiness`). Nothing is estimated,
 * scored or benchmarked — a farmer's own numbers, arranged so the first screen
 * answers: which season, what to do next, what is missing, how it is running.
 */

/** Row 1 — the single statement of which season this is.
 *
 * Home used to say it three times: this bar, then a hero with a 62px day
 * count and the season name again, and the shell's topbar chip above both.
 * The hero is gone; this bar carries everything it held — farm, plot, season,
 * status, day count and the two dates — and its only action is a quiet link,
 * so the page has exactly one primary button (the next action below it).
 */
export function SeasonContextBar({ ctx, loading, activities }: { ctx: SeasonCtx | null; loading?: boolean; activities?: Activity[] | null }) {
  if (loading) {
    return (
      <div className="fw-ctxbar" aria-busy="true">
        <Sk w={220} h={16} /><Sk w={160} h={16} /><Sk w={120} h={16} />
      </div>
    )
  }
  if (!ctx) return null
  const { season, plot, farm } = ctx
  const sown = sowingDate(season, activities)
  const harvested = harvestDate(season, activities)
  const days = season.harvestDate || harvested.source === 'journal' ? null : daysSince(sown.iso ?? undefined)
  return (
    <section className="fw-ctxbar" aria-labelledby="fw-ctxbar-season">
      <p className="fw-ctxbar__place">
        {farm && <span><Ico name="farm" />{farm.name}</span>}
        {plot && <span><Ico name="plot" />{plot.name}{plot.areaHa != null && <small> · {ha(plot.areaHa)}</small>}</span>}
        {season.variety && <span><Ico name="seeding" />Giống {season.variety}</span>}
      </p>
      <p className="fw-ctxbar__season">
        <b id="fw-ctxbar-season">{season.name}</b>
        <span className="fw-role fw-role--positive">{seasonStatusLabel(season.status)}</span>
        {/* The day count is a fact, not the headline: it reads at body size
          * beside the season, instead of as the largest thing on the page. */}
        {days != null && <span className="fw-ctxbar__days"><Ico name="calendar" />{days} ngày kể từ gieo sạ</span>}
      </p>
      <p className="fw-ctxbar__dates">
        <SeasonDateItem icon="calendar" label="Gieo sạ" d={sown} testId="season-sowing-date" />
        <SeasonDateItem icon="harvest" label="Thu hoạch" d={harvested} testId="season-harvest-date" />
      </p>
      <p className="fw-ctxbar__go">
        <Link className="fw-link" to={`/farmer/crop-seasons/${season.id}`}>Xem chi tiết vụ<Ico name="arrow" /></Link>
      </p>
    </section>
  )
}

function SeasonDateItem({ icon, label, d, testId }: { icon: IconName; label: string; d: SeasonDate; testId: string }) {
  return (
    <span data-testid={testId}>
      <Ico name={icon} />{label}: <b className={d.value ? undefined : 'is-empty'}>{d.value ?? 'Chưa ghi nhận'}</b>
      {d.note && <small className="fw-ctxbar__src"> ({d.note})</small>}
    </span>
  )
}

export type NextActionKind = 'record' | 'fix-data' | 'calculate' | 'view-result' | 'none'

export interface NextAction {
  kind: NextActionKind
  title: string
  body: string
  cta: string
}

/** The single next action, decided from the season's own state.
 *
 * Order matters and is the farmer's, not the system's: data the Carbon Engine
 * is waiting for → today's field work → the calculation that is now possible.
 * Everything else on the page is a link, never a second competing button.
 */
export function nextAction(input: {
  hasSeason: boolean
  canWrite: boolean
  readiness?: CarbonReadiness | null
  activities?: Activity[] | null
  hasCarbonResult: boolean
  today?: string
}): NextAction | null {
  if (!input.hasSeason || !input.canWrite) return null
  // Same grouping as Management and the Carbon screen: an unverified factor is
  // never counted as something the farmer forgot to type in.
  const view = carbonView({ readiness: input.readiness })
  if (view.userFixableGaps.length) {
    return {
      kind: 'fix-data',
      title: 'Bổ sung dữ liệu còn thiếu',
      body: `Còn ${view.userFixableGaps.length} thông tin để tính phát thải cho vụ này.`,
      cta: 'Bổ sung ngay',
    }
  }
  const today = input.today ?? localDay(new Date())
  const recordedToday = (input.activities ?? []).some((a) => a.occurredAt.slice(0, 10) === today)
  if (!recordedToday) {
    return {
      kind: 'record',
      title: 'Ghi hoạt động hôm nay',
      body: 'Hôm nay chưa có hoạt động nào trong nhật ký của vụ này.',
      cta: 'Ghi hoạt động',
    }
  }
  if (view.isReady && !input.hasCarbonResult) {
    return {
      kind: 'calculate',
      title: 'Tính Carbon cho vụ này',
      body: 'Dữ liệu đã đủ — hệ thống có thể tính phát thải ngay.',
      cta: 'Tính Carbon',
    }
  }
  if (input.hasCarbonResult) {
    return {
      kind: 'view-result',
      title: 'Xem kết quả Carbon',
      body: 'Vụ này đã có kết quả phát thải và đã ghi hoạt động hôm nay.',
      cta: 'Xem kết quả',
    }
  }
  return null
}

export function PrimaryNextAction({ action, onAct, to, loading }: {
  action: NextAction | null
  /** Handler for the in-place action (opening the record sheet). */
  onAct?: () => void
  /** Destination when the action is a navigation (Carbon repair / calculate). */
  to?: string
  loading?: boolean
}) {
  if (loading) {
    return <div className="fw-next fw-next--sk" aria-busy="true"><Sk w={44} h={44} r={10} /><span className="fw-sk-lines"><Sk w="40%" h={18} /><Sk w="70%" h={13} /></span></div>
  }
  if (!action) return null
  const tone = action.kind === 'fix-data' ? 'attention' : action.kind === 'calculate' || action.kind === 'view-result' ? 'info' : 'positive'
  const icon: IconName = action.kind === 'fix-data' ? 'warning' : action.kind === 'calculate' || action.kind === 'view-result' ? 'carbon' : 'journal'
  return (
    <section className={`fw-next fw-next--${tone}`} aria-labelledby="fw-next-title">
      <span className="fw-next__ico" aria-hidden="true"><Ico name={icon} /></span>
      <div className="fw-next__text">
        <h2 id="fw-next-title">{action.title}</h2>
        <p>{action.body}</p>
      </div>
      {to
        ? <Link className="fw-btn fw-next__cta" to={to}>{action.cta}<Ico name="arrow" /></Link>
        : <button type="button" className="fw-btn fw-next__cta" onClick={onAct}>{action.cta}<Ico name="arrow" /></button>}
    </section>
  )
}

/** Row 3 — the season at a glance: two resource readings in the unit a
 *  farmer reads, the Carbon state, and the journal count as a plain line.
 *
 * The activity count used to be a green KPI tile beside water, fertiliser and
 * Carbon, which read as "more records = better season". It is a fact about
 * the journal, so it is said as one, in neutral text, with its link. Each
 * reading carries one short sentence and "Xem chi tiết"; the arithmetic, the
 * basis and the methodology live on Performance. */
export function SummaryStrip({ activities, metrics, readiness, facts, loading }: {
  activities: QueryState<Activity[]>
  metrics: QueryState<SeasonMetrics>
  readiness: QueryState<CarbonReadiness | null>
  facts: SeasonFacts
  loading?: boolean
}) {
  if (loading || activities.loading || metrics.loading) {
    return (
      <div className="fw-summary" aria-busy="true">
        {[0, 1, 2].map((i) => <div key={i} className="fw-summary__item"><Sk w="55%" h={12} /><Sk w="45%" h={22} /><Sk w="70%" h={11} /></div>)}
      </div>
    )
  }
  const m = metrics.data
  const count = activities.data?.length ?? 0
  // The one view model, so this tile cannot say "Sẵn sàng tính" while the
  // Carbon screen next door says a factor is missing.
  const view = carbonView({
    readiness: readiness.data,
    hasResult: m?.co2ePerKg != null || m?.totalCo2eKg != null,
  })
  const fixable = view.userFixableGaps.length
  const limits = view.methodologyLimitations.length
  const TONE: Record<string, Role> = {
    attention: 'attention', methodology: 'info', info: 'water', positive: 'positive', neutral: 'neutral',
  }
  const carbon: { label: string; role: Role } = readiness.loading
    ? { label: 'Đang kiểm tra', role: 'neutral' }
    : { label: view.label, role: TONE[view.tone] ?? 'neutral' }
  const total = m?.totalCo2eKg
  return (
    <>
      <div className="fw-summary">
        {homeSummary(m, facts).map((it) => (
          <Tile key={it.key} icon={it.icon} label={it.label} value={it.value} hint={it.hint} more="/farmer/performance" />
        ))}
        <Tile
          role={carbon.role} icon="carbon" label="Carbon"
          value={total != null ? (total >= 1000 ? { value: readable(total / 1000), unit: 't CO₂e cả vụ' } : { value: readable(total), unit: 'kg CO₂e cả vụ' }) : null}
          empty={carbon.label}
          hint={fixable ? `Còn thiếu ${fixable} thông tin để tính Carbon` : limits ? `${limits} giới hạn hệ số — không cần bạn nhập` : total != null ? 'Phát thải ước tính của cả vụ' : view.detail}
          more={fixable ? '/farmer/carbon' : '/farmer/performance'}
          moreLabel={fixable ? 'Bổ sung ngay' : 'Xem chi tiết'}
        />
      </div>
      <p className="fw-journal-line">
        <Ico name="journal" /><span>{journalLine(count)}</span>
        <Link className="fw-link" to="/farmer/journal">Xem nhật ký<Ico name="arrow" /></Link>
      </p>
    </>
  )
}

type Role = 'positive' | 'water' | 'attention' | 'error' | 'info' | 'neutral'

function Tile({ role = 'neutral', icon, label, value, empty, hint, more, moreLabel = 'Xem chi tiết' }: {
  role?: Role; icon: IconName; label: string; value?: Reading | null; empty?: string; hint?: string; more?: string; moreLabel?: string
}) {
  // A reading is neutral: there is no benchmark that would make a water
  // figure healthy or poor, so it is never painted as one. Only a state the
  // caller deliberately flags — Carbon readiness — carries a tone.
  const flagged = role === 'attention' || role === 'error' || role === 'info'
  const shown: Role = flagged ? role : 'neutral'
  return (
    <div className={`fw-summary__item fw-role fw-role--${shown}`}>
      <span className="fw-summary__label"><Ico name={icon} />{label}</span>
      {value != null
        ? <span className="fw-summary__value">{value.value}{'\u00a0'}<small>{value.unit}</small></span>
        : <span className="fw-summary__value is-empty">{empty ?? 'Chưa đủ dữ liệu'}</span>}
      {hint && <span className="fw-summary__note">{hint}</span>}
      {more && <Link className="fw-link fw-summary__more" to={more}>{moreLabel}<Ico name="arrow" /></Link>}
    </div>
  )
}

/** Cost sits on its own, away from Carbon, and says so in plain words.
 *
 * Money is not an input to any emission factor. Putting the two side by side
 * is what makes a farmer believe spending less would lower their CO₂e. */
export function CostPanel({ metrics, facts, moreTo }: { metrics: QueryState<SeasonMetrics>; facts: SeasonFacts; moreTo?: string }) {
  if (metrics.loading) return <div className="fw-cost" aria-busy="true"><Sk w="40%" h={14} /><Sk w="55%" h={24} /></div>
  const d = metrics.data ? metricDetails(metrics.data, facts).find((x) => x.key === 'cost')! : null
  const perKg = d?.secondary.find((r) => r.unit.startsWith('₫ / kg'))
  return (
    <div className="fw-cost">
      <span className="fw-cost__label"><Ico name="money" />Chi phí trực tiếp đã ghi</span>
      {d?.primary
        ? <span className="fw-cost__value">{d.primary.value}{' '}<small>{d.primary.unit}</small></span>
        : <span className="fw-cost__value is-empty">Chưa đủ dữ liệu chi phí</span>}
      <p className="fw-cost__note">
        {perKg ? `${perKg.value} ₫ cho mỗi kg lúa. ` : d && !d.primary && d.missing ? `${d.missing} ` : ''}
        Không phải tổng chi phí sản xuất. <b>Không dùng để tính CO₂e.</b>
      </p>
      <p className="fw-cost__links">
        {!d?.primary && <Link className="fw-link" to="/farmer/journal">Bổ sung chi phí trong Nhật ký<Ico name="arrow" /></Link>}
        {moreTo && <Link className="fw-link" to={moreTo}>Xem chi tiết<Ico name="arrow" /></Link>}
      </p>
    </div>
  )
}

/** A small, reusable status pill: colour + text, never colour alone. */
export function RoleBadge({ role, icon, children }: { role: Role; icon?: IconName; children: ReactNode }) {
  return (
    <span className={`fw-role fw-role--${role} fw-role-badge`}>
      {icon && <Ico name={icon} />}{children}
    </span>
  )
}
