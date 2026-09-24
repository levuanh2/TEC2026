import type { SeasonMetrics } from '../../api/metrics'
import { carbonView } from '../../carbon/readiness'
import type { Activity } from '../../types'
import { Link } from '../../ui'
import { useActivityMutations, type ActivityMutations, type SeasonContext } from '../ActivityForms'
import { carbonInputsChangedAt, type QueryState } from '../data'
import { Ico } from '../icons'
import { Empty, ErrorPanel, Flash, PageHeader, Sk, SkBlock } from '../kit'
import { MetricRow, YieldContextPanel } from '../metricRows'
import { metricGroups, seasonFacts, yieldContext, type CarbonInputs } from '../metricsView'
import { prefetchSeason, primarySeason, useActivities, useCarbon, useCarbonReadiness, useMetrics, useScope, type SeasonCtx } from '../scope'
import { useWritableSeason } from '../writeAccess'

/** Performance, in four groups (Round 4.3): the season's context, resource
 *  efficiency, recorded direct cost, and Carbon. Cost and Carbon never share a
 *  group, a colour or a row. */
export function MetricCards({ state, season, mutations, loading, ctx, activities, carbonTo }: {
  state: QueryState<SeasonMetrics>
  season: SeasonContext | null
  mutations: ActivityMutations
  loading?: boolean
  /** The season being read — plot area and names for the context panel. */
  ctx: SeasonCtx | null
  activities: QueryState<Activity[]>
  /** Where this surface's Carbon quick-fix lives. */
  carbonTo: string
}) {
  const sid = ctx?.season.id ?? null
  const readiness = useCarbonReadiness(sid)
  const carbon = useCarbon(sid)
  if (loading || state.loading || activities.loading) {
    return (
      <SkBlock label="Đang tải chỉ số" className="fw-metrics">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="fw-mrow">
            <span className="fw-sk-lines"><Sk w="40%" h={16} /><Sk w="30%" h={34} /></span>
            <span className="fw-sk-lines"><Sk w="80%" h={13} /><Sk w="60%" h={13} /></span>
          </div>
        ))}
      </SkBlock>
    )
  }
  if (state.error || !state.data) return <ErrorPanel error={state.error ?? 'Không có dữ liệu.'} onRetry={state.reload} />
  const m = state.data
  const facts = seasonFacts(activities.data, ctx?.plot?.areaHa)
  const view = carbonView({ readiness: readiness.data })
  const result = carbon.data?.kind === 'result' ? carbon.data.result : null
  const changedAt = sid ? carbonInputsChangedAt(sid) : null
  const carbonInputs: CarbonInputs = {
    fixable: view.userFixableGaps,
    limitations: view.methodologyLimitations,
    result,
    stale: Boolean(result?.calculated_at && changedAt && changedAt > result.calculated_at),
    fixTo: carbonTo,
  }
  const y = yieldContext(m, facts)
  return (
    <div className="fw-perf">
      {ctx && (
        <YieldContextPanel
          y={y}
          seasonName={ctx.season.name}
          place={[ctx.plot?.name, ctx.farm?.name].filter(Boolean).join(' · ')}
          harvestAction={m.yieldKg == null && season
            ? <button type="button" className="fw-btn fw-btn--soft fw-btn--sm" onClick={() => mutations.openCreate('harvest', season)}>Ghi thu hoạch</button>
            : undefined}
        />
      )}
      {/* Separate groups, not one flat row: cost used to sit directly above
        * CO₂e/kg, which reads as though spending less lowers emissions. */}
      {metricGroups(m, facts, carbonInputs).map((g) => (
        <section key={g.key} className={`fw-mgroup fw-mgroup--${g.key}`} aria-labelledby={`fw-mgroup-${g.key}`}>
          <h3 id={`fw-mgroup-${g.key}`} className="fw-mgroup__title">{g.title}</h3>
          <p className="fw-mgroup__desc">{g.description}</p>
          {g.key === 'cost' && <CostCoverage facts={facts} />}
          <div className="fw-mrows">
            {g.items.map((d) => <MetricRow key={d.key} d={d} season={season} mutations={mutations} />)}
          </div>
        </section>
      ))}
    </div>
  )
}

/** Which kinds of record carry a cost and which do not — so "chưa đủ dữ liệu"
 *  names the records to open rather than leaving the farmer to guess. */
function CostCoverage({ facts }: { facts: ReturnType<typeof seasonFacts> }) {
  if (!facts.costCategories.length) return null
  // Nothing recorded anywhere: one line, not a list of every kind saying "no".
  if (facts.recordsWithCost === 0) {
    return (
      <ul className="fw-costcov" aria-label="Chi phí theo nhóm hoạt động">
        <li className="is-missing"><Ico name="warning" /><span>Chưa hoạt động nào có chi phí</span><small>0/{facts.costableRecords} hoạt động</small></li>
        <li className="is-na"><Ico name="info" /><span>Nhân công, thuê máy</span><small>Chưa có ô nhập riêng</small></li>
      </ul>
    )
  }
  return (
    <ul className="fw-costcov" aria-label="Chi phí theo nhóm hoạt động">
      {facts.costCategories.map((c) => {
        const done = c.withCost === c.records
        return (
          <li key={c.type} className={done ? 'is-ok' : 'is-missing'}>
            <Ico name={done ? 'check' : 'warning'} />
            <span>{c.label}</span>
            <small>{done ? `Đã ghi (${c.records}/${c.records})` : `Chưa ghi chi phí ${c.records - c.withCost}/${c.records} lần`}</small>
          </li>
        )
      })}
      <li className="is-na"><Ico name="info" /><span>Nhân công, thuê máy</span><small>Chưa có ô nhập riêng</small></li>
    </ul>
  )
}

export function FarmerPerformancePage() {
  const scope = useScope()
  const primary = primarySeason(scope.data)
  const sid = primary?.season.id ?? null
  const metrics = useMetrics(sid)
  const activities = useActivities(sid)
  const mutations = useActivityMutations()
  const seasonCtx = useWritableSeason(primary)
  return (
    <>
      <PageHeader
        eyebrow="Hiệu suất" icon="performance" title="Hiệu suất vụ của tôi"
        subtitle="Mỗi con số kèm ý nghĩa, dữ liệu dùng để tính và việc bạn có thể làm tiếp."
        actions={primary ? <Link to={`/farmer/crop-seasons/${primary.season.id}/performance`} className="fw-link" onMouseEnter={() => prefetchSeason(primary.season.id)}>Mở trong vụ<Ico name="arrow" /></Link> : undefined}
      />
      {scope.error ? (
        <ErrorPanel error={scope.error} onRetry={scope.reload} />
      ) : !scope.loading && !primary ? (
        <Empty icon="performance" title="Chưa có vụ đang canh tác" body="Chỉ số sẽ xuất hiện khi một vụ đang hoạt động có dữ liệu ghi nhận." action={<Link to="/farmer/farms" className="fw-btn fw-btn--soft">Xem ruộng của tôi</Link>} />
      ) : null}
      <Flash message={mutations.flash} />
      {(scope.loading || primary) && (
        <MetricCards state={metrics} activities={activities} ctx={primary} season={seasonCtx} mutations={mutations} loading={scope.loading} carbonTo="/farmer/carbon" />
      )}
      {mutations.node}
    </>
  )
}
