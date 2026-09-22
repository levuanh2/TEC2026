import type { CurrentUser } from '../../api/me'
import type { SeasonMetrics } from '../../api/metrics'
import type { Recommendation } from '../../api/recommendations'
import { date, daysSince, ha } from '../../format'
import { Link } from '../../ui'
import { ACTIVITY_TITLE, buildAttention, greeting, localDay, longDay, type MetricGroup } from '../activityView'
import type { CarbonMissingInput } from '../../api/carbon'
import { QuickActions, toSeasonContext, useActivityMutations, type ActivityMutations, type SeasonContext } from '../ActivityForms'
import { CvPreviewCard } from '../CvCheck'
import type { QueryState } from '../data'
import { Ico } from '../icons'
import { MiniTimeline } from '../journal'
import { Chip, Empty, ErrorPanel, Flash, IconTile, MoreLink, Section, Sk, SkBlock } from '../kit'
import { CostPanel, PrimaryNextAction, SeasonContextBar, SummaryStrip, nextAction } from '../hybrid'
import { metricGroups } from '../metricsView'
import { RecommendationsSection } from '../Recommendations'
import { useCanWriteFarm, useWritableSeason } from '../writeAccess'
import {
  activeSeasonsOf, prefetchSeason, primarySeason, seasonStatusLabel, useActivities, useCarbonReadiness, useMetrics, useRecommendations, useScope,
  type SeasonCtx,
} from '../scope'

/** While the scope itself is loading, dependent sections are still "loading" too. */
function pending<T>(state: QueryState<T>, scopeLoading: boolean): QueryState<T> {
  return scopeLoading ? { ...state, loading: true } : state
}

export function FarmerHome({ viewer }: { viewer: CurrentUser }) {
  const scope = useScope()
  const primary = primarySeason(scope.data)
  const sid = primary?.season.id ?? null
  const metrics = useMetrics(sid)
  const activities = useActivities(sid)
  const recs = useRecommendations(sid)
  const carbonReadiness = useCarbonReadiness(sid)
  const mutations = useActivityMutations()
  const canWrite = useCanWriteFarm()
  const active = activeSeasonsOf(scope.data)
  const writable: SeasonContext[] = active.filter((c) => canWrite(c.plot?.farmId)).map((c) => toSeasonContext(c.season, c.plot))
  const readOnly = !scope.loading && active.length > 0 && writable.length === 0
  const primaryCtx = primary ? toSeasonContext(primary.season, primary.plot) : null
  const primaryWriteCtx = useWritableSeason(primary)
  const name = viewer.fullName?.trim()
  /* One next action, derived from this season's own state (missing Carbon
   * inputs → today's field work → a calculation that is now possible). */
  const action = nextAction({
    hasSeason: Boolean(sid),
    canWrite: Boolean(primaryWriteCtx),
    readiness: carbonReadiness.data,
    activities: activities.data,
    hasCarbonResult: metrics.data?.co2ePerKg != null,
  })

  return (
    <>
      <header className="fw-greet">
        <div>
          <p className="fw-greet__hello">{greeting()}{name ? `, ${name}` : ''}</p>
          <h1>Hôm nay trên ruộng của bạn</h1>
        </div>
        <div className="fw-greet__ctx">
          {primary?.farm && <Chip icon="farm" tone="forest">{primary.farm.name}</Chip>}
          <Chip icon="calendar">{longDay(localDay(new Date()))}</Chip>
        </div>
      </header>
      <Flash message={mutations.flash} />

      {/* The farmer's four questions, in order: which season · what to do next ·
        * how is it running · what did I record. One primary action only —
        * everything else on this page is a link. */}
      <div className="fw-home-top">
        <HomeHero scope={scope} primary={primary} />

        <PrimaryNextAction
          loading={scope.loading || (Boolean(sid) && (activities.loading || carbonReadiness.loading))}
          action={action}
          to={action?.kind === 'fix-data' || action?.kind === 'calculate' ? '/farmer/carbon' : undefined}
          onAct={action?.kind === 'record' && primaryWriteCtx ? () => mutations.openCreate('irrigation', primaryWriteCtx) : undefined}
        />
      </div>

      {sid && (
        <Section className="fw-area-summary" title="Tổng quan vụ này" action={<MoreLink to="/farmer/performance">Xem chi tiết</MoreLink>}>
          <SummaryStrip activities={pending(activities, scope.loading)} metrics={pending(metrics, scope.loading)} readiness={pending(carbonReadiness, scope.loading)} />
          {/* Cost is deliberately below the season figures and carries its own
            * sentence: it is not an input to any emission factor. */}
          <CostPanel metrics={pending(metrics, scope.loading)} />
        </Section>
      )}

      {!readOnly && (
        <Section title="Ghi nhanh" description="Chọn việc bạn vừa làm để ghi vào nhật ký của vụ đang canh tác." action={<MoreLink to="/farmer/journal">Mở nhật ký</MoreLink>}>
          <QuickActions seasons={writable} mutations={mutations} loading={scope.loading} />
        </Section>
      )}

      {/* Reading order is the farmer's, not the database's: what is running
        * (ledger, above) → what to record (quick, above) → is the data sound
        * → anything to notice → what I did lately. The DOM order below is that
        * order, so phones get it verbatim and the grid only rearranges it on
        * desktop. */}
      {/* Two real columns, so each one flows continuously instead of leaving
        * holes where a grid row was sized by the other column's content. On
        * phones the wrappers become `display: contents` and `order` restores the
        * farmer's reading order: data soundness → attention → what I did. */}
      <div className="fw-home-grid">
        <div className="fw-home-col">
          <Section className="fw-area-perf" title="Hiệu suất vụ này" action={sid ? <MoreLink to="/farmer/performance">Chi tiết</MoreLink> : undefined}>
            <PerformanceSnapshot state={pending(metrics, scope.loading)} hasSeason={Boolean(sid)} />
          </Section>
          <Section className="fw-area-journal" title="Nhật ký gần đây" action={sid ? <MoreLink to="/farmer/journal">Xem nhật ký</MoreLink> : undefined}>
            <MiniTimeline state={pending(activities, scope.loading)} limit={5} />
          </Section>
        </div>
        <div className="fw-home-col">
          <Section className="fw-area-attn" title="Cần chú ý" description="Chỉ từ dữ liệu thực tế của vụ.">
            <AttentionList metrics={pending(metrics, scope.loading)} recs={recs.data} carbonMissing={carbonReadiness.data?.missing_inputs} season={primaryWriteCtx} mutations={mutations} hasSeason={Boolean(sid)} />
          </Section>
          <div className="fw-area-recs">
            <RecommendationsSection seasonId={scope.loading ? null : sid} limit={2} moreTo={sid ? `/farmer/crop-seasons/${sid}` : undefined} />
          </div>
          <div className="fw-area-cv">
            <CvPreviewCard season={primaryCtx} seasonId={sid} />
          </div>
        </div>
      </div>
      {mutations.node}
    </>
  )
}

function HomeHero({ scope, primary }: { scope: QueryState<{ farms: unknown[] }>; primary: SeasonCtx | null }) {
  if (scope.loading) return <HeroSkeleton />
  if (scope.error) return <ErrorPanel error={scope.error} onRetry={scope.reload} />
  if (!scope.data?.farms.length) return <Empty icon="farm" title="Chưa có ruộng trong phạm vi của bạn" body="Liên hệ quản lý HTX để được gán nông hộ hoặc thửa ruộng." />
  if (!primary) {
    return <Empty icon="seeding" tone="leaf" title="Chưa có vụ đang canh tác" body="Bạn vẫn có thể xem các ruộng và vụ đã ghi nhận." action={<Link to="/farmer/farms" className="fw-btn fw-btn--soft">Xem ruộng của tôi</Link>} />
  }
  // One statement of which season this is — see SeasonContextBar.
  return <SeasonContextBar ctx={primary} />
}

export function HeroSkeleton() {
  return (
    <SkBlock label="Đang tải vụ đang canh tác" className="fw-ctxbar">
      <Sk w={220} h={16} /><Sk w="55%" h={22} /><Sk w="42%" h={14} />
    </SkBlock>
  )
}

function AttentionList({ metrics, recs, carbonMissing, season, mutations, hasSeason }: {
  metrics: QueryState<SeasonMetrics>; recs?: Recommendation[]; carbonMissing?: CarbonMissingInput[] | null; season: SeasonContext | null; mutations: ActivityMutations; hasSeason: boolean
}) {
  if (metrics.loading) {
    return (
      <SkBlock label="Đang kiểm tra dữ liệu" className="fw-attn">
        {[0, 1].map((i) => <div key={i} className="fw-attn__item tone-sage"><Sk w={34} h={34} r={10} /><span className="fw-sk-lines"><Sk w="45%" h={14} /><Sk w="75%" h={12} /></span></div>)}
      </SkBlock>
    )
  }
  const clear = <p className="fw-attn__clear"><Ico name="check" />Không có việc cần chú ý lúc này.</p>
  if (!hasSeason) return clear
  if (metrics.error) return <ErrorPanel error={metrics.error} onRetry={metrics.reload} />
  const items = buildAttention(metrics.data, recs, carbonMissing)
  if (!items.length) return clear

  /* Cost and Carbon are independent metrics fed by different inputs. Grouping
   * them under separate headings stops a farmer reading "thiếu chi phí" as a
   * reason Carbon did not compute — money is never a Carbon input. */
  const groups: { key: MetricGroup; label: string; hint: string }[] = [
    { key: 'resource', label: 'Hiệu suất tài nguyên', hint: 'Nước, phân bón, chi phí trên mỗi kg lúa' },
    { key: 'carbon', label: 'Phát thải carbon', hint: 'Dữ liệu canh tác theo phương pháp IPCC — không dùng chi phí' },
  ]
  const row = (item: (typeof items)[number]) => {
    const tone = item.tone === 'warning' ? 'amber' : 'info'
    return (
      <li key={item.id} className={`fw-attn__item tone-${tone}`}>
        <IconTile name={item.tone === 'warning' ? 'warning' : 'info'} tone={tone} size="sm" />
        <div><b>{item.title}</b><p>{item.body}</p></div>
        {item.action && season && (
          <button type="button" className="fw-btn fw-btn--soft fw-btn--sm" aria-label={`Ghi ${ACTIVITY_TITLE[item.action].toLowerCase()} ngay`} onClick={() => mutations.openCreate(item.action!, season)}>Ghi ngay</button>
        )}
        {!item.action && item.link && season && (
          <a className="fw-btn fw-btn--soft fw-btn--sm" href={item.link.to(season.id)}>{item.link.label}</a>
        )}
      </li>
    )
  }
  return (
    <>
      {groups.map((g) => {
        const rows = items.filter((i) => i.group === g.key)
        if (!rows.length) return null
        return (
          <section key={g.key} className="fw-attn-group">
            <h3 className="fw-attn-group__title">{g.label}<small>{g.hint}</small></h3>
            <ul className="fw-attn">{rows.map(row)}</ul>
          </section>
        )
      })}
    </>
  )
}

function PerformanceSnapshot({ state, hasSeason }: { state: QueryState<SeasonMetrics>; hasSeason: boolean }) {
  if (state.loading) {
    return (
      <SkBlock label="Đang tải hiệu suất" className="fw-snap">
        {[0, 1, 2, 3].map((i) => <div key={i} className="fw-snap__item"><Sk w="60%" h={14} /><Sk w="50%" h={24} /><Sk w="40%" h={11} /></div>)}
      </SkBlock>
    )
  }
  if (!hasSeason) return <Empty icon="performance" title="Chưa có vụ đang canh tác" body="Chỉ số xuất hiện khi một vụ đang hoạt động có dữ liệu ghi nhận." />
  if (state.error || !state.data) return <ErrorPanel error={state.error ?? 'Không có dữ liệu.'} onRetry={state.reload} />
  return (
    <>
      {/* Grouped here too, so the home summary and the performance page tell
        * the same story about what cost has to do with CO₂e: nothing. */}
      {metricGroups(state.data).map((g) => (
        <div key={g.key} className="fw-snap-group">
          <p className="fw-snap-group__title">{g.title}</p>
          <div className="fw-snap">
            {g.items.map((v) => (
              <div key={v.key} className="fw-snap__item">
                <span className="fw-snap__label"><IconTile name={v.icon} tone={v.tone} size="sm" />{v.label}</span>
                <span className={`fw-snap__value${v.value ? '' : ' is-empty'}`}>{v.value ?? 'Chưa đủ dữ liệu'}{v.value && <small>{v.unit}</small>}</span>
                <span className={`fw-status ${v.value ? 'is-ok' : 'is-missing'}`}>{v.value ? 'Đã đủ dữ liệu' : v.shortHint}</span>
              </div>
            ))}
          </div>
        </div>
      ))}
    </>
  )
}
