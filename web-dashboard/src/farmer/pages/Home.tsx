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
import { useCanWriteFarm, useWritableSeason } from '../writeAccess'
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
  const canWrite = useCanWriteFarm()
  const active = activeSeasonsOf(scope.data)
  const writable: SeasonContext[] = active.filter((c) => canWrite(c.plot?.farmId)).map((c) => toSeasonContext(c.season, c.plot))
  const readOnly = !scope.loading && active.length > 0 && writable.length === 0
  const primaryCtx = primary ? toSeasonContext(primary.season, primary.plot) : null
  const primaryWriteCtx = useWritableSeason(primary)
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

      {!readOnly && (
        <Section title="Ghi nhanh" description="Chọn việc bạn vừa làm để ghi vào nhật ký của vụ đang canh tác.">
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
            <AttentionList metrics={pending(metrics, scope.loading)} recs={recs.data} season={primaryWriteCtx} mutations={mutations} hasSeason={Boolean(sid)} />
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
  return <SeasonHero ctx={primary} />
}

export function HeroSkeleton() {
  return (
    <SkBlock label="Đang tải vụ đang canh tác" className="fw-ledger">
      <div className="fw-ledger__top">
        <div className="fw-ledger__title"><Sk w={180} h={62} /><Sk w="55%" h={26} /><Sk w="42%" h={15} /></div>
        <div className="fw-ledger__dates"><Sk w={200} h={16} /><Sk w={200} h={16} /></div>
      </div>
    </SkBlock>
  )
}

/** The season ledger — the Stat-Led head of the Farmer app.
 *
 * The figure is the one number a farmer already keeps in their head: how many
 * days this season has been in the ground. It is real (derived from the planting
 * date we hold) and it is never shown alone — the words beside it say what it
 * counts, and the season identity sits directly under it. When there is no
 * planting date there is no figure: the slot states that plainly rather than
 * inventing a number to fill the shape. */
export function SeasonHero({ ctx }: { ctx: SeasonCtx }) {
  const { season, plot, farm } = ctx
  const days = season.harvestDate ? null : daysSince(season.plantingDate)
  return (
    <section className="fw-ledger" aria-labelledby="fw-hero-title">
      <div className="fw-ledger__top">
        <div className="fw-ledger__title">
          <p className="fw-ledger__figure">
            {days != null
              ? <><b>{days}</b><span>ngày kể từ gieo sạ</span></>
              : <span className="is-empty">{season.harvestDate ? 'Vụ đã thu hoạch' : 'Chưa ghi nhận ngày gieo sạ'}</span>}
          </p>
          <h2 id="fw-hero-title">{season.name}</h2>
          <p className="fw-ledger__place">
            <span><Ico name="plot" />{plot?.name ?? 'Thửa ruộng'}</span>
            {farm && <span><Ico name="farm" />{farm.name} · {farm.code}</span>}
          </p>
          <p className="fw-ledger__meta">
            <span className="fw-chip fw-chip--dot">{seasonStatusLabel(season.status)}</span>
            {plot?.areaHa != null && <span className="fw-chip"><Ico name="area" />{ha(plot.areaHa)}</span>}
            {season.variety && <span className="fw-chip"><Ico name="seeding" />Giống {season.variety}</span>}
          </p>
          <p className="fw-ledger__actions">
            <Link className="fw-btn" to={`/farmer/crop-seasons/${season.id}`} onMouseEnter={() => prefetchSeason(season.id)} onFocus={() => prefetchSeason(season.id)}>Xem vụ<Ico name="arrow" /></Link>
          </p>
        </div>
        <div className="fw-ledger__dates">
          <p className="fw-ledger__date"><span><Ico name="calendar" />Gieo sạ</span><b className={season.plantingDate ? undefined : 'is-empty'}>{season.plantingDate ? date(season.plantingDate) : 'Chưa ghi nhận'}</b></p>
          <p className="fw-ledger__date"><span><Ico name="harvest" />Thu hoạch</span><b className={season.harvestDate ? undefined : 'is-empty'}>{season.harvestDate ? date(season.harvestDate) : 'Chưa ghi nhận'}</b></p>
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
