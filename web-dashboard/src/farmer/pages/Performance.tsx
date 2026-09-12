import type { SeasonMetrics } from '../../api/metrics'
import { Link } from '../../ui'
import { ACTIVITY_TITLE, fmtNumber } from '../activityView'
import { toSeasonContext, useActivityMutations, type ActivityMutations, type SeasonContext } from '../ActivityForms'
import type { QueryState } from '../data'
import { Ico } from '../icons'
import { ACTIVITY_ICON, Chip, Empty, ErrorPanel, Flash, IconTile, PageHeader, Sk, SkBlock } from '../kit'
import { metricViews } from '../metricsView'
import { prefetchSeason, primarySeason, seasonStatusLabel, useMetrics, useScope } from '../scope'

export function MetricCards({ state, season, mutations, loading }: { state: QueryState<SeasonMetrics>; season: SeasonContext | null; mutations: ActivityMutations; loading?: boolean }) {
  if (loading || state.loading) {
    return (
      <SkBlock label="Đang tải chỉ số" className="fw-metrics">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="fw-metric">
            <div className="fw-metric__head"><Sk w={58} h={58} r={17} /><span className="fw-sk-lines"><Sk w="50%" h={16} /><Sk w="30%" h={12} /></span></div>
            <Sk w="45%" h={40} /><Sk w="80%" h={13} />
          </div>
        ))}
      </SkBlock>
    )
  }
  if (state.error || !state.data) return <ErrorPanel error={state.error ?? 'Không có dữ liệu.'} onRetry={state.reload} />
  const m = state.data
  return (
    <>
      <div className="fw-metrics">
        {metricViews(m).map((v) => (
          <article key={v.key} className="fw-metric" aria-labelledby={`fw-metric-${v.key}`}>
            <div className="fw-metric__head">
              <IconTile name={v.icon} tone={v.tone} size="lg" />
              <div><h3 id={`fw-metric-${v.key}`}>{v.label}</h3><small>{v.unit}</small></div>
              <span className={`fw-status ${v.value ? 'is-ok' : 'is-missing'}`}>{v.value ? 'Đã đủ dữ liệu' : 'Chưa đủ dữ liệu'}</span>
            </div>
            {v.value ? (
              <>
                <div className="fw-metric__value"><b>{v.value}</b><span>{v.unit}</span></div>
                <p className="fw-metric__explain">{v.explain}</p>
                {v.basis && <p className="fw-note">{v.basis}</p>}
              </>
            ) : (
              <div className="fw-metric__empty">
                <b>Chưa đủ dữ liệu</b>
                <p>{v.emptyHint}</p>
                {v.cta && season && (
                  <button type="button" className="fw-btn fw-btn--soft fw-btn--sm" onClick={() => mutations.openCreate(v.cta!, season)}>
                    <Ico name={ACTIVITY_ICON[v.cta].icon} />Ghi {ACTIVITY_TITLE[v.cta].toLowerCase()}
                  </button>
                )}
              </div>
            )}
          </article>
        ))}
      </div>
      <div className="fw-basis">
        <Chip icon="harvest" tone="amber">{m.yieldKg != null ? `Sản lượng đã ghi: ${fmtNumber(m.yieldKg)} kg thóc` : 'Chưa ghi nhận sản lượng'}</Chip>
        {m.waterM3 != null && <Chip icon="irrigation" tone="water">Nước đã ghi: {fmtNumber(m.waterM3)} m³</Chip>}
        {m.fertilizerKg != null && <Chip icon="fertilizer" tone="earth">Phân bón đã ghi: {fmtNumber(m.fertilizerKg)} kg</Chip>}
      </div>
      <p className="fw-note">Chi phí là chi phí vật tư đã ghi nhận, không phải tổng chi phí sản xuất. Carbon chỉ hiển thị khi có kết quả tính hợp lệ. Không so sánh hay chấm điểm khi chưa có mốc tham chiếu đã xác minh.</p>
    </>
  )
}

export function FarmerPerformancePage() {
  const scope = useScope()
  const primary = primarySeason(scope.data)
  const sid = primary?.season.id ?? null
  const metrics = useMetrics(sid)
  const mutations = useActivityMutations()
  const seasonCtx = primary ? toSeasonContext(primary.season, primary.plot) : null
  return (
    <>
      <PageHeader eyebrow="Hiệu suất" icon="performance" title="Hiệu suất vụ của tôi" subtitle="Bốn chỉ số tài nguyên và phát thải của vụ đang canh tác, tính từ dữ liệu bạn đã ghi." />
      {scope.loading ? (
        <SkBlock label="Đang tải vụ" className="fw-ctxbar"><Sk w={44} h={44} r={13} /><span className="fw-sk-lines"><Sk w="30%" h={16} /><Sk w="50%" h={12} /></span></SkBlock>
      ) : scope.error ? (
        <ErrorPanel error={scope.error} onRetry={scope.reload} />
      ) : primary ? (
        <div className="fw-ctxbar">
          <IconTile name="seeding" tone="leaf" />
          <div>
            <small>Đang xem vụ</small>
            <b>{primary.season.name}</b>
            <small>{[primary.plot?.name, primary.farm?.name].filter(Boolean).join(' · ')}</small>
          </div>
          <Chip tone="leaf" className="fw-chip--dot">{seasonStatusLabel(primary.season.status)}</Chip>
          <Link to={`/farmer/crop-seasons/${primary.season.id}/performance`} className="fw-link" onMouseEnter={() => prefetchSeason(primary.season.id)}>Mở trong vụ<Ico name="arrow" /></Link>
        </div>
      ) : (
        <Empty icon="performance" title="Chưa có vụ đang canh tác" body="Chỉ số sẽ xuất hiện khi một vụ đang hoạt động có dữ liệu ghi nhận." action={<Link to="/farmer/farms" className="fw-btn fw-btn--soft">Xem ruộng của tôi</Link>} />
      )}
      <Flash message={mutations.flash} />
      {(scope.loading || primary) && <MetricCards state={metrics} season={seasonCtx} mutations={mutations} loading={scope.loading} />}
      {mutations.node}
    </>
  )
}
