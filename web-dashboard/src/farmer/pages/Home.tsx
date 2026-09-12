import type { CurrentUser } from '../../api/me'
import type { SeasonMetrics } from '../../api/metrics'
import type { Recommendation } from '../../api/recommendations'
import { date, daysSince, ha } from '../../format'
import { Link } from '../../ui'
import { ACTIVITY_TITLE, buildAttention, greeting, localDay, longDay } from '../activityView'
import { QuickActions, toSeasonContext, useActivityMutations, type ActivityMutations, type SeasonContext } from '../ActivityForms'
import { CvPreviewCard } from '../CvCheck'
import type { QueryState } from '../data'
import { Ico } from '../icons'
import { MiniTimeline } from '../journal'
import { Chip, Empty, ErrorPanel, Flash, IconTile, MoreLink, Section, Sk, SkBlock } from '../kit'
import { metricViews } from '../metricsView'
import { RecommendationsSection } from '../Recommendations'
import {
  activeSeasonsOf, prefetchSeason, primarySeason, seasonStatusLabel, useActivities, useMetrics, useRecommendations, useScope,
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
  const mutations = useActivityMutations()
  const writable: SeasonContext[] = activeSeasonsOf(scope.data).map((c) => toSeasonContext(c.season, c.plot))
  const primaryCtx = primary ? toSeasonContext(primary.season, primary.plot) : null
  const name = viewer.fullName?.trim()

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

      <HomeHero scope={scope} primary={primary} />

      <Section title="Ghi nhanh" icon="plus" description="Chọn việc bạn vừa làm để ghi vào nhật ký của vụ đang canh tác.">
        <QuickActions seasons={writable} mutations={mutations} loading={scope.loading} />
      </Section>

      <div className="fw-home-grid">
        <Section className="fw-area-attn" title="Cần chú ý" icon="warning" tone="amber" description="Chỉ từ dữ liệu thực tế của vụ.">
          <AttentionList metrics={pending(metrics, scope.loading)} recs={recs.data} season={primaryCtx} mutations={mutations} hasSeason={Boolean(sid)} />
        </Section>
        <Section className="fw-area-perf" title="Hiệu suất vụ này" icon="performance" action={sid ? <MoreLink to="/farmer/performance">Chi tiết</MoreLink> : undefined}>
          <PerformanceSnapshot state={pending(metrics, scope.loading)} hasSeason={Boolean(sid)} />
        </Section>
        <div className="fw-area-recs">
          <RecommendationsSection seasonId={scope.loading ? null : sid} limit={2} moreTo={sid ? `/farmer/crop-seasons/${sid}` : undefined} />
        </div>
        <Section className="fw-area-journal" title="Nhật ký gần đây" icon="journal" tone="leaf" action={sid ? <MoreLink to="/farmer/journal">Xem nhật ký</MoreLink> : undefined}>
          <MiniTimeline state={pending(activities, scope.loading)} limit={5} />
        </Section>
        <div className="fw-area-cv">
          <CvPreviewCard season={primaryCtx} seasonId={sid} />
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
  return <SeasonHero ctx={primary} />
}

export function HeroSkeleton() {
  return (
    <SkBlock label="Đang tải vụ đang canh tác" className="fw-hero fw-hero--sk">
      <div className="fw-hero__main"><Sk w={150} h={26} r={999} /><Sk w="55%" h={34} /><Sk w="42%" h={15} /><Sk w="50%" h={26} r={999} /></div>
      <div className="fw-hero__side"><Sk w={130} h={46} /><Sk w="100%" h={14} /><Sk w="100%" h={14} /></div>
    </SkBlock>
  )
}

export function SeasonHero({ ctx }: { ctx: SeasonCtx }) {
  const { season, plot, farm } = ctx
  const days = season.harvestDate ? null : daysSince(season.plantingDate)
  return (
    <section className="fw-hero" aria-labelledby="fw-hero-title">
      <div className="fw-hero__main">
        <span className="fw-hero__eyebrow"><Ico name="seeding" />Vụ đang canh tác</span>
        <h2 id="fw-hero-title" className="fw-hero__title">{season.name}</h2>
        <p className="fw-hero__place">
          <span><Ico name="plot" />{plot?.name ?? 'Thửa ruộng'}</span>
          {farm && <span><Ico name="farm" />{farm.name} · {farm.code}</span>}
        </p>
        <div className="fw-hero__chips">
          <span className="fw-chip fw-chip--live fw-chip--dot">{seasonStatusLabel(season.status)}</span>
          {plot?.areaHa != null && <span className="fw-chip"><Ico name="area" />{ha(plot.areaHa)}</span>}
          {season.variety && <span className="fw-chip"><Ico name="seeding" />Giống {season.variety}</span>}
        </div>
        <div className="fw-hero__actions">
          <Link className="fw-btn" to={`/farmer/crop-seasons/${season.id}`} onMouseEnter={() => prefetchSeason(season.id)} onFocus={() => prefetchSeason(season.id)}>Xem vụ<Ico name="arrow" /></Link>
        </div>
      </div>
      <div className="fw-hero__side">
        {days != null
          ? <div className="fw-hero__days"><b>{days}</b><span>ngày<br />kể từ gieo sạ</span></div>
          : <div className="fw-hero__days"><span>{season.harvestDate ? 'Vụ đã có ngày thu hoạch' : 'Chưa ghi nhận ngày gieo sạ'}</span></div>}
        <div className="fw-hero__dates">
          <div className="fw-hero__date"><span><Ico name="calendar" />Gieo sạ</span><b className={season.plantingDate ? undefined : 'is-empty'}>{season.plantingDate ? date(season.plantingDate) : 'Chưa ghi nhận'}</b></div>
          <div className="fw-hero__date"><span><Ico name="harvest" />Thu hoạch</span><b className={season.harvestDate ? undefined : 'is-empty'}>{season.harvestDate ? date(season.harvestDate) : 'Chưa ghi nhận'}</b></div>
        </div>
      </div>
    </section>
  )
}

function AttentionList({ metrics, recs, season, mutations, hasSeason }: {
  metrics: QueryState<SeasonMetrics>; recs?: Recommendation[]; season: SeasonContext | null; mutations: ActivityMutations; hasSeason: boolean
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
  const items = buildAttention(metrics.data, recs)
  if (!items.length) return clear
  return (
    <ul className="fw-attn">
      {items.map((item) => {
        const tone = item.tone === 'warning' ? 'amber' : 'info'
        return (
          <li key={item.id} className={`fw-attn__item tone-${tone}`}>
            <IconTile name={item.tone === 'warning' ? 'warning' : 'info'} tone={tone} size="sm" />
            <div><b>{item.title}</b><p>{item.body}</p></div>
            {item.action && season && (
              <button type="button" className="fw-btn fw-btn--soft fw-btn--sm" aria-label={`Ghi ${ACTIVITY_TITLE[item.action].toLowerCase()} ngay`} onClick={() => mutations.openCreate(item.action!, season)}>Ghi ngay</button>
            )}
          </li>
        )
      })}
    </ul>
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
    <div className="fw-snap">
      {metricViews(state.data).map((v) => (
        <div key={v.key} className="fw-snap__item">
          <span className="fw-snap__label"><IconTile name={v.icon} tone={v.tone} size="sm" />{v.label}</span>
          <span className={`fw-snap__value${v.value ? '' : ' is-empty'}`}>{v.value ?? 'Chưa đủ dữ liệu'}{v.value && <small>{v.unit}</small>}</span>
          <span className={`fw-status ${v.value ? 'is-ok' : 'is-missing'}`}>{v.value ? 'Đã đủ dữ liệu' : v.shortHint}</span>
        </div>
      ))}
    </div>
  )
}
