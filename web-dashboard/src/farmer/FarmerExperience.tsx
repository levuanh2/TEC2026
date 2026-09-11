import { useMemo, useState } from 'react'
import type { Session } from '@supabase/supabase-js'
import type { Activity, CropSeason, Farm, Plot } from '../types'
import { getActivities, getCropSeason, getCropSeasons } from '../api/crops'
import { getFarm, getPlotsForFarm, getPlot, listFarms } from '../api/farms'
import { getResourceMetrics, type SeasonMetrics } from '../api/metrics'
import { getCarbon, type CarbonResult } from '../api/carbon'
import { signOut } from '../api/auth'
import { usingMockData } from '../api/farms'
import { activityIcon, presentActivity } from '../utils/activityPresentation'
import { date, dateTime, daysSince, ha, perKg } from '../format'
import { FarmerJournalTimeline } from './journal'
import { Async, Badge, Breadcrumb, EmptyState, ErrorState, Hero, Link, MetricCard, Notice, PageHead, Section, Tabs, useAsync, go } from '../ui'
import {
  ActivityRowActions, AddActivityCta, QuickEntryPanel, toSeasonContext, useActivityMutations,
  type SeasonContext,
} from './ActivityForms'
import { RecommendationsSection } from './Recommendations'
import { CvCheckButton, CvHistorySection, CvHomeSummaryCard } from './CvCheck'

type Scope = { farms: Farm[]; plots: Plot[]; seasons: CropSeason[] }
type SeasonWithContext = CropSeason & { plot?: Plot; farm?: Farm }

async function loadScope(): Promise<Scope> {
  const farms = await listFarms()
  const plotGroups = await Promise.all(farms.map(async (farm) => ({ farm, plots: await getPlotsForFarm(farm.id) })))
  const plots = plotGroups.flatMap((group) => group.plots)
  const seasonGroups = await Promise.all(plots.map(async (plot) => ({ plot, seasons: await getCropSeasons(plot.id) })))
  return { farms, plots, seasons: seasonGroups.flatMap((group) => group.seasons) }
}

function activeSeason(scope: Scope | undefined): SeasonWithContext | null {
  if (!scope) return null
  const active = scope.seasons
    .filter((season) => /(^active$|đang|canh tác)/i.test(season.status ?? ''))
    .sort((a, b) => String(b.plantingDate ?? '').localeCompare(String(a.plantingDate ?? '')))[0]
  if (!active) return null
  const plot = scope.plots.find((item) => item.id === active.plotId)
  return { ...active, plot, farm: scope.farms.find((item) => item.id === plot?.farmId) }
}

const farmerRoutes = [
  { to: '/farmer', label: 'Tổng quan', icon: '⌂' },
  { to: '/farmer/journal', label: 'Nhật ký', icon: '◷' },
  { to: '/farmer/farms', label: 'Ruộng', icon: '⌑' },
  { to: '/farmer/performance', label: 'Hiệu suất', icon: '◌' },
  { to: '/farmer/account', label: 'Tôi', icon: '◉' },
]

function FarmerShell({ session, path, children }: { session: Session | null; path: string; children: React.ReactNode }) {
  const email = session?.user.email ?? 'Tài khoản nông hộ'
  return (
    <div className="farmer-shell">
      <aside className="farmer-rail">
        <Link to="/farmer" className="farmer-brand">AgriCarbon<small>Nhật ký canh tác</small></Link>
        <nav className="farmer-nav" aria-label="Điều hướng nông hộ">
          {farmerRoutes.map((item) => <FarmerNavItem key={item.to} item={item} path={path} />)}
        </nav>
        <div className="farmer-user"><span className="avatar" aria-hidden="true">{email[0]?.toUpperCase()}</span><span><b>{email}</b><small>Nông hộ</small><button className="link" onClick={() => void signOut().then(() => go('/login'))}>Đăng xuất</button></span></div>
      </aside>
      <main className="farmer-main"><div className="farmer-content">{children}</div></main>
      <nav className="farmer-bottom-nav" aria-label="Điều hướng nông hộ trên điện thoại">
        {farmerRoutes.map((item) => <FarmerNavItem key={item.to} item={item} path={path} compact />)}
      </nav>
    </div>
  )
}

function FarmerNavItem({ item, path, compact = false }: { item: typeof farmerRoutes[number]; path: string; compact?: boolean }) {
  const active = item.to === '/farmer' ? path === '/farmer' : path.startsWith(item.to)
  return <Link to={item.to} className={active ? 'is-active' : undefined} aria-current={active ? 'page' : undefined}><span aria-hidden="true">{item.icon}</span>{compact ? <small>{item.label}</small> : item.label}</Link>
}

export function FarmerExperience({ session, path }: { session: Session | null; path: string }) {
  const page = farmerRoute(path)
  const id = farmerParam(path)
  let content: React.ReactNode
  switch (page) {
    case 'home': content = <FarmerHome />; break
    case 'journal': content = <FarmerJournal seasonId={id} />; break
    case 'farms': content = <FarmerFarms />; break
    case 'farm': content = <FarmerFarm id={id!} />; break
    case 'plot': content = <FarmerPlot id={id!} />; break
    case 'season': content = <FarmerSeason id={id!} tab="overview" />; break
    case 'season-journal': content = <FarmerSeason id={id!} tab="journal" />; break
    case 'season-performance': content = <FarmerSeason id={id!} tab="performance" />; break
    case 'season-carbon': content = <FarmerSeason id={id!} tab="carbon" />; break
    case 'performance': content = <FarmerPerformance />; break
    case 'account': content = <FarmerAccount session={session} />; break
    default: content = <EmptyState icon="🔍" title="Không tìm thấy trang" body="Đường dẫn này không thuộc khu vực nông hộ." action={<Link to="/farmer" className="btn btn--ghost">Về Tổng quan</Link>} />
  }
  return <FarmerShell session={session} path={path}>{content}</FarmerShell>
}

function FarmerHome() {
  const scope = useAsync(loadScope, [])
  const current = activeSeason(scope.data)
  const metrics = useAsync(() => current ? getResourceMetrics(current.id) : Promise.resolve(null), [current?.id])
  const activities = useAsync(() => current ? getActivities(current.id) : Promise.resolve([]), [current?.id])
  const mutations = useActivityMutations(() => { activities.reload(); metrics.reload() })
  const [cvVersion, setCvVersion] = useState(0)
  const writableSeasons: SeasonContext[] = (scope.data?.seasons ?? [])
    .filter((season) => season.status === 'active')
    .map((season) => toSeasonContext(season, scope.data?.plots.find((plot) => plot.id === season.plotId)))
  return <>
    <PageHead eyebrow="AgriCarbon cho nông hộ" title="Hôm nay trên ruộng của bạn" meta={[<>Theo dõi vụ đang canh tác và những việc cần bổ sung.</>]} />
    {mutations.flash && <Notice kind="success">{mutations.flash}</Notice>}
    <Async state={scope} skeleton="page" isEmpty={(data) => data.farms.length === 0} empty={<EmptyState icon="🌾" title="Chưa có ruộng trong phạm vi của bạn" body="Liên hệ quản lý HTX để được gán nông hộ hoặc thửa ruộng." />}>
      {(data) => {
        const season = activeSeason(data)
        if (!season) return <EmptyState icon="🌱" title="Chưa có vụ đang canh tác" body="Bạn vẫn có thể xem các ruộng và vụ đã ghi nhận." action={<Link to="/farmer/farms" className="btn btn--ghost">Xem ruộng của tôi</Link>} />
        return <div className="farmer-stack">
          {/* Hierarchy per FW design pass: hero -> quick actions -> attention
              -> performance -> recommendations -> recent activity -> CV
              preview (brief Part 4.1) — CV moved from the top to a bottom
              preview since it's a secondary tool, not the day's main task. */}
          <CurrentSeasonCard season={season} />
          <QuickEntryPanel activeSeasons={writableSeasons} mutations={mutations} />
          <DataAttention metrics={metrics.data} loading={metrics.loading} />
          <Section title="Hiệu suất vụ này" description="Chỉ số dùng dữ liệu đã ghi nhận; thiếu dữ liệu sẽ không được thay bằng số 0.">
            <Async state={metrics} skeleton="kpis">{(m) => m ? <FarmerMetricGrid metrics={m} /> : <EmptyState title="Chưa đủ dữ liệu hiệu suất" />}</Async>
          </Section>
          <RecommendationsSection seasonId={season.id} />
          <Section title="Nhật ký gần đây" cta={{ label: 'Xem toàn bộ nhật ký', to: `/farmer/crop-seasons/${season.id}/journal` }}>
            <Async state={activities} skeleton="table">{(items) => <RecentActivities activities={items} />}</Async>
          </Section>
          <section className="farmer-quick">
            <div><h2>Kiểm tra lá lúa</h2><p>Chụp hoặc chọn ảnh để nhận diện nhanh bằng AI (baseline, chưa xác nhận thực địa).</p></div>
            <div><CvCheckButton season={toSeasonContext(season, season.plot)} onChecked={() => setCvVersion((v) => v + 1)} /></div>
          </section>
          <CvHomeSummaryCard seasonId={season.id} reloadKey={cvVersion} />
        </div>
      }}
    </Async>
  </>
}

function CurrentSeasonCard({ season }: { season: SeasonWithContext }) {
  const growingDays = daysSince(season.plantingDate)
  return (
    <Hero
      eyebrow="Vụ đang canh tác"
      title={season.name}
      meta={[
        <>{season.plot?.name ?? 'Thửa ruộng'} · {season.plot?.areaHa == null ? 'Chưa có diện tích' : ha(season.plot.areaHa)}</>,
        <Badge tone="success" dot>{season.status ?? 'Đang canh tác'}</Badge>,
      ]}
      stats={growingDays == null ? undefined : [{ label: 'Ngày đang canh tác', value: growingDays }]}
      actions={<Link className="btn btn--ghost" to={`/farmer/crop-seasons/${season.id}`}>Xem vụ →</Link>}
    />
  )
}

function FarmerMetricGrid({ metrics }: { metrics: SeasonMetrics }) {
  const status = (present: boolean) => present ? { tone: 'success' as const, label: 'Đã ghi nhận' } : { tone: 'warning' as const, label: 'Chưa đủ dữ liệu' }
  return <div className="farmer-metrics">
    <MetricCard name="Nước / kg lúa" value={metrics.waterPerKg == null ? 'Chưa đủ dữ liệu' : perKg(metrics.waterPerKg, '')} unit="m³/kg" context="Nước đã ghi nhận" status={status(metrics.completeness.water)} />
    <MetricCard name="Phân bón / kg lúa" value={metrics.fertilizerPerKg == null ? 'Chưa đủ dữ liệu' : perKg(metrics.fertilizerPerKg, '')} unit="kg/kg" context="Khối lượng phân vật lý" status={status(metrics.completeness.fertilizer)} />
    <MetricCard name="Carbon / kg lúa" value={metrics.co2ePerKg == null ? 'Chưa đủ dữ liệu' : perKg(metrics.co2ePerKg, '')} unit="kg CO₂e/kg" context="Kết quả tính khi hệ số sẵn sàng" status={status(metrics.completeness.carbon)} />
    <MetricCard name="Chi phí / kg lúa" value={metrics.costPerKg == null ? 'Chưa đủ dữ liệu' : perKg(metrics.costPerKg, '')} unit="₫/kg" context="Chi phí vật tư đã ghi nhận" status={status(metrics.completeness.cost)} />
  </div>
}

function DataAttention({ metrics, loading }: { metrics?: SeasonMetrics | null; loading: boolean }) {
  if (loading) return <div className="skeleton sk-row" aria-label="Đang kiểm tra dữ liệu" />
  if (!metrics) return null
  const items = [!metrics.completeness.water && 'Thiếu dữ liệu nước', !metrics.completeness.fertilizer && 'Thiếu dữ liệu phân bón', !metrics.completeness.carbon && 'Chưa có kết quả Carbon'].filter(Boolean)
  if (!items.length) return null
  return <Notice kind="warning"><b>Việc cần chú ý:</b> {items.join(' · ')}. Dữ liệu canh tác của bạn vẫn được lưu bình thường.</Notice>
}

function RecentActivities({ activities }: { activities: Activity[] }) {
  if (!activities.length) return <EmptyState icon="🗒️" title="Chưa có hoạt động nào được ghi nhận cho vụ này." />
  return <div className="farmer-recent">{[...activities].sort((a, b) => b.occurredAt.localeCompare(a.occurredAt)).slice(0, 5).map((activity) => {
    const p = presentActivity(activity.type, activity.detail)
    return <div className="farmer-recent__item" key={activity.id}><span aria-hidden="true">{activityIcon(activity.type)}</span><div><b>{p.label}</b><small>{p.summary}</small></div><time>{date(activity.occurredAt)}</time></div>
  })}</div>
}

const isActiveStatus = (status: string | undefined | null) => /(^active$|đang|canh tác)/i.test(status ?? '')

function FarmerFarms() {
  const scope = useAsync(loadScope, [])
  return <>
    <PageHead eyebrow="Ruộng của tôi" title="Các ruộng trong phạm vi của bạn" />
    <Async state={scope} skeleton="page" isEmpty={(data) => data.farms.length === 0} empty={<EmptyState icon="🌾" title="Chưa có ruộng nào" body="Chưa có farm được cấp quyền cho tài khoản này." />}>
      {({ farms, plots, seasons }) => (
        <div className="farmer-farm-grid">
          {farms.map((farm) => {
            const farmPlots = plots.filter((plot) => plot.farmId === farm.id)
            const farmSeasons = seasons.filter((s) => farmPlots.some((p) => p.id === s.plotId))
            const activeCount = farmSeasons.filter((s) => isActiveStatus(s.status)).length
            return (
              <article className="farmer-farm-card" key={farm.id}>
                <p>{farm.code}</p>
                <h2>{farm.name}</h2>
                <div className="farmer-farm-card__stats">
                  <span>{farm.plotCount} thửa</span>
                  <span>{farm.areaHa == null ? 'Chưa có diện tích' : ha(farm.areaHa)}</span>
                  <span className={activeCount ? 'is-active' : undefined}>{activeCount} vụ đang canh tác</span>
                </div>
                <div className="farmer-farm-card__plots">
                  {farmPlots.map((plot) => {
                    const latest = seasons.filter((season) => season.plotId === plot.id).sort((a, b) => String(b.plantingDate ?? '').localeCompare(String(a.plantingDate ?? '')))[0]
                    return <Link key={plot.id} to={`/farmer/plots/${plot.id}`}><b>{plot.name}</b><small>{plot.areaHa == null ? 'Chưa có diện tích' : ha(plot.areaHa)}{latest ? ` · ${latest.name}` : ''}</small></Link>
                  })}
                </div>
                <Link className="btn btn--ghost" to={`/farmer/farms/${farm.id}`}>Xem ruộng</Link>
              </article>
            )
          })}
        </div>
      )}
    </Async>
  </>
}

function FarmerFarm({ id }: { id: string }) {
  const state = useAsync(async () => {
    const [farm, plots, seasons] = await Promise.all([getFarm(id), getPlotsForFarm(id), getFarmCropSeasonsFor(id)])
    return { farm, plots, seasons }
  }, [id])
  return <Async state={state} isEmpty={(data) => !data.farm} empty={<EmptyState icon="🔍" title="Không tìm thấy nông hộ" />}>
    {({ farm, plots, seasons }) => {
      if (!farm) return null
      const activeCount = seasons.filter((s) => isActiveStatus(s.status)).length
      return <>
        <Breadcrumb items={[{ label: 'Ruộng của tôi', to: '/farmer/farms' }, { label: farm.name }]} />
        <Hero
          eyebrow="Nông hộ"
          title={farm.name}
          titleAs="h1"
          meta={[<>Mã hộ {farm.code}</>]}
          stats={[
            { label: 'Thửa ruộng', value: farm.plotCount },
            { label: 'Diện tích', value: farm.areaHa == null ? '—' : ha(farm.areaHa) },
            { label: 'Vụ đang canh tác', value: activeCount },
          ]}
        />
        <PlotCards plots={plots} seasons={seasons} />
      </>
    }}
  </Async>
}

async function getFarmCropSeasonsFor(farmId: string): Promise<CropSeason[]> {
  const plots = await getPlotsForFarm(farmId)
  const groups = await Promise.all(plots.map((p) => getCropSeasons(p.id)))
  return groups.flat()
}

function PlotCards({ plots, seasons }: { plots: Plot[]; seasons: CropSeason[] }) {
  if (!plots.length) return <EmptyState icon="🗺️" title="Chưa có thửa ruộng nào" />
  return <div className="farmer-plot-grid">
    {plots.map((plot) => {
      const plotSeasons = seasons.filter((s) => s.plotId === plot.id)
      const active = plotSeasons.find((s) => isActiveStatus(s.status))
      return (
        <Link key={plot.id} to={`/farmer/plots/${plot.id}`} className="farmer-plot-card">
          <span>Thửa {plot.code}</span>
          <b>{plot.name}</b>
          <small>{plot.areaHa == null ? 'Chưa có diện tích' : ha(plot.areaHa)}</small>
          {active ? <small style={{ color: 'var(--brand-strong)', fontWeight: 650 }}>Đang canh tác: {active.name}</small> : <small>Chưa có vụ đang canh tác</small>}
          <em>Xem mùa vụ →</em>
        </Link>
      )
    })}
  </div>
}

function FarmerPlot({ id }: { id: string }) {
  const state = useAsync(async () => {
    const plot = await getPlot(id)
    const [seasons, farm] = await Promise.all([
      getCropSeasons(id),
      plot?.farmId ? getFarm(plot.farmId).catch(() => undefined) : Promise.resolve(undefined),
    ])
    return { plot, seasons, farm }
  }, [id])
  return <Async state={state} isEmpty={(data) => !data.plot} empty={<EmptyState icon="🔍" title="Không tìm thấy thửa ruộng" />}>
    {({ plot, seasons, farm }) => {
      if (!plot) return null
      const active = seasons.find((s) => isActiveStatus(s.status))
      return <>
        <Breadcrumb items={[
          { label: 'Ruộng của tôi', to: '/farmer/farms' },
          ...(farm ? [{ label: farm.name, to: `/farmer/farms/${farm.id}` }] : []),
          { label: plot.name },
        ]} />
        <Hero
          eyebrow="Thửa ruộng"
          title={plot.name}
          titleAs="h1"
          meta={[<>Mã thửa {plot.code}</>, ...(farm ? [<>Thuộc {farm.name}</>] : [])]}
          stats={[{ label: 'Diện tích', value: plot.areaHa == null ? '—' : ha(plot.areaHa) }]}
          actions={active ? <Link className="btn btn--ghost" to={`/farmer/crop-seasons/${active.id}`}>Vụ đang canh tác: {active.name} →</Link> : undefined}
        />
        <Section title="Mùa vụ" description={active ? undefined : 'Thửa này hiện chưa có vụ nào đang canh tác'}>
          {!seasons.length ? <EmptyState icon="🌱" title="Thửa này chưa có vụ canh tác nào." /> : <div className="farmer-season-list">{seasons.map((season) => <Link key={season.id} to={`/farmer/crop-seasons/${season.id}`}><span>{season.status ?? 'Chưa rõ trạng thái'}</span><b>{season.name}</b><small>{season.variety ?? 'Chưa có giống'} · Gieo {date(season.plantingDate)}</small><em>Xem vụ →</em></Link>)}</div>}
        </Section>
      </>
    }}
  </Async>
}

type FarmerTab = 'overview' | 'journal' | 'performance' | 'carbon'
function FarmerSeason({ id, tab }: { id: string; tab: FarmerTab }) {
  const frame = useAsync(async () => {
    const season = await getCropSeason(id)
    const plot = season ? await getPlot(season.plotId) : undefined
    const farm = plot?.farmId ? await getFarm(plot.farmId).catch(() => undefined) : undefined
    return { season, plot, farm }
  }, [id])
  const metrics = useAsync(() => getResourceMetrics(id), [id])
  const activities = useAsync(() => getActivities(id), [id])
  // Harvest edits change the yield denominator, so a mutation refetches both
  // the journal and the four resource metrics (brief FW-2 §21).
  const mutations = useActivityMutations(() => { activities.reload(); metrics.reload() })
  const [cvVersion, setCvVersion] = useState(0)
  const base = `/farmer/crop-seasons/${id}`
  const tabs = [{ label: 'Tổng quan', to: base, current: tab === 'overview' }, { label: 'Nhật ký', to: `${base}/journal`, current: tab === 'journal' }, { label: 'Hiệu suất', to: `${base}/performance`, current: tab === 'performance' }, { label: 'Carbon', to: `${base}/carbon`, current: tab === 'carbon' }]
  return <Async state={frame} isEmpty={(data) => !data.season} empty={<EmptyState icon="🔍" title="Không tìm thấy vụ canh tác" />}>{({ season, plot, farm }) => {
    if (!season) return null
    const seasonCtx = toSeasonContext(season, plot)
    return <>
      <Breadcrumb items={[
        { label: 'Ruộng của tôi', to: '/farmer/farms' },
        ...(farm ? [{ label: farm.name, to: `/farmer/farms/${farm.id}` }] : []),
        ...(plot ? [{ label: plot.name, to: `/farmer/plots/${plot.id}` }] : []),
        { label: season.name },
      ]} />
      <Hero
        eyebrow="Vụ canh tác"
        title={season.name}
        titleAs="h1"
        meta={[
          <>{plot?.name ?? 'Thửa ruộng'} · {plot?.areaHa == null ? 'Chưa có diện tích' : ha(plot.areaHa)}</>,
          <>Giống {season.variety ?? 'Chưa có dữ liệu'}</>,
          <Badge tone={isActiveStatus(season.status) ? 'success' : 'neutral'} dot>{season.status ?? 'Chưa rõ'}</Badge>,
        ]}
        stats={[
          { label: 'Gieo sạ', value: date(season.plantingDate) },
          { label: 'Thu hoạch', value: date(season.harvestDate) },
        ]}
      />
      <Tabs items={tabs} />
      {mutations.flash && <Notice kind="success">{mutations.flash}</Notice>}
      {tab === 'overview' && (
        <FarmerSeasonOverview
          season={season} metrics={metrics} activities={activities} seasonCtx={seasonCtx} cvVersion={cvVersion}
          mutations={mutations} onCvChecked={() => setCvVersion((v) => v + 1)}
        />
      )}
      {tab === 'journal' && <Section title="Nhật ký của vụ này" description={`Chỉ hoạt động thuộc "${season.name}" — nhấn một hoạt động để xem chi tiết.`}>
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 12 }}><AddActivityCta season={seasonCtx} mutations={mutations} /></div>
        <Async state={activities} skeleton="table">{(rows) => <FarmerJournalTimeline activities={rows} resetSignal={mutations.version} renderActions={(a) => <ActivityRowActions activity={a} season={seasonCtx} mutations={mutations} />} />}</Async>
      </Section>}
      {tab === 'performance' && <Section title="Hiệu suất vụ này"><Async state={metrics} skeleton="kpis">{(m) => <FarmerMetricGrid metrics={m} />}</Async></Section>}
      {tab === 'carbon' && <FarmerCarbon id={id} />}
      {/* Overview's QuickEntryPanel already self-renders mutations.node (see
          ActivityForms.tsx) — rendering it again here would mount the same
          open Sheet/ConfirmDialog twice. Only the journal tab's
          AddActivityCta/ActivityRowActions need this outer render. */}
      {tab === 'journal' && mutations.node}
    </>
  }}</Async>
}

function FarmerSeasonOverview({ season, metrics, activities, seasonCtx, cvVersion, mutations, onCvChecked }: { season: CropSeason; metrics: ReturnType<typeof useAsync<SeasonMetrics>>; activities: ReturnType<typeof useAsync<Activity[]>>; seasonCtx: SeasonContext; cvVersion: number; mutations: ReturnType<typeof useActivityMutations>; onCvChecked: () => void }) {
  return <div className="farmer-stack">
    <section className="farmer-season-summary"><dl><div><dt>Trạng thái</dt><dd>{season.status ?? 'Chưa rõ'}</dd></div><div><dt>Ngày gieo sạ</dt><dd>{date(season.plantingDate)}</dd></div><div><dt>Ngày thu hoạch</dt><dd>{date(season.harvestDate)}</dd></div></dl></section>
    <DataAttention metrics={metrics.data} loading={metrics.loading} />
    <Section title="Ghi nhanh cho vụ này" description="Chọn việc bạn vừa làm — không cần chọn lại vụ.">
      <QuickEntryPanel activeSeasons={[seasonCtx]} mutations={mutations} />
    </Section>
    <Section title="Hiệu suất"><Async state={metrics} skeleton="kpis">{(m) => <FarmerMetricGrid metrics={m} />}</Async></Section>
    <RecommendationsSection seasonId={season.id} />
    <Section title="Hoạt động gần đây" cta={{ label: 'Xem nhật ký', to: `/farmer/crop-seasons/${season.id}/journal` }}><Async state={activities} skeleton="table">{(rows) => <RecentActivities activities={rows} />}</Async></Section>
    <section className="farmer-quick">
      <div><h2>Kiểm tra lá lúa</h2><p>Chụp hoặc chọn ảnh để nhận diện nhanh bằng AI (baseline, chưa xác nhận thực địa).</p></div>
      <div><CvCheckButton season={seasonCtx} onChecked={onCvChecked} /></div>
    </section>
    <CvHistorySection seasonId={season.id} reloadKey={cvVersion} />
  </div>
}

function seasonContextFromScope(scope: Scope | undefined, seasonId: string | null): SeasonContext | null {
  if (!scope || !seasonId) return null
  const season = scope.seasons.find((s) => s.id === seasonId)
  if (!season) return null
  return toSeasonContext(season, scope.plots.find((plot) => plot.id === season.plotId))
}

function FarmerJournal({ seasonId }: { seasonId: string | null }) {
  const scope = useAsync(loadScope, [])
  const selected = seasonId ?? activeSeason(scope.data)?.id ?? null
  const activities = useAsync(() => selected ? getActivities(selected) : Promise.resolve([]), [selected])
  const mutations = useActivityMutations(() => activities.reload())
  const seasonCtx = seasonContextFromScope(scope.data, selected)
  return <>
    <PageHead
      eyebrow="Nhật ký"
      title="Hoạt động canh tác"
      meta={[seasonCtx ? <>Vụ đang xem: <b>{seasonCtx.label}</b></> : <>Chỉ hiển thị các hoạt động đã ghi nhận.</>]}
    />
    {mutations.flash && <Notice kind="success">{mutations.flash}</Notice>}
    <Async state={scope} skeleton="page" isEmpty={(data) => data.seasons.length === 0} empty={<EmptyState icon="🗒️" title="Chưa có vụ canh tác để xem nhật ký." />}>
      {() => !selected ? <EmptyState icon="🗒️" title="Chưa có vụ đang canh tác" body="Chọn một vụ từ Ruộng của tôi để xem nhật ký." /> : (
        <Section title="Toàn bộ nhật ký của vụ" description="Nhóm theo ngày — nhấn một hoạt động để xem chi tiết.">
          {seasonCtx && <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 12 }}><AddActivityCta season={seasonCtx} mutations={mutations} /></div>}
          <Async state={activities} skeleton="table">{(rows) => <FarmerJournalTimeline activities={rows} resetSignal={mutations.version} renderActions={seasonCtx ? (a) => <ActivityRowActions activity={a} season={seasonCtx} mutations={mutations} /> : undefined} />}</Async>
        </Section>
      )}
    </Async>
    {mutations.node}
  </>
}

function FarmerPerformance() {
  const scope = useAsync(loadScope, [])
  const current = activeSeason(scope.data)
  const metrics = useAsync(() => current ? getResourceMetrics(current.id) : Promise.resolve(null), [current?.id])
  return <><PageHead eyebrow="Hiệu suất" title="Hiệu suất vụ của tôi" meta={[<>Không so sánh hoặc đánh giá khi chưa có benchmark đã xác minh.</>]} /><Async state={scope} skeleton="page">{() => !current ? <EmptyState icon="◌" title="Chưa có vụ đang canh tác" body="Chỉ số sẽ xuất hiện khi một vụ đang hoạt động có dữ liệu ghi nhận." /> : <><CurrentSeasonCard season={current} /><Section title="Bốn chỉ số chính"><Async state={metrics} skeleton="kpis">{(m) => m ? <FarmerMetricGrid metrics={m} /> : <EmptyState title="Chưa đủ dữ liệu hiệu suất" />}</Async></Section><p className="farmer-disclaimer">Chi phí là chi phí vật tư đã ghi nhận, không phải tổng chi phí sản xuất. Carbon chỉ hiển thị khi có kết quả tính hợp lệ.</p></>}</Async></>
}

function FarmerCarbon({ id }: { id: string }) {
  const state = useAsync(() => usingMockData ? Promise.resolve(null) : getCarbon(id), [id])
  if (state.loading) return <div className="skeleton sk-kpi" aria-label="Đang tải Carbon" />
  if (usingMockData) return <CarbonEmpty />
  if (state.error && /no[_ ]?calculation|404|chưa có bản tính/i.test(state.error)) return <CarbonEmpty />
  if (state.error) return <ErrorState error={state.error} onRetry={state.reload} />
  if (!state.data) return <CarbonEmpty />
  return <FarmerCarbonSuccess result={state.data} />
}

function CarbonEmpty() {
  return (
    <section className="farmer-carbon-empty">
      <span aria-hidden="true">◎</span>
      <h2>Chưa có kết quả phát thải hợp lệ cho vụ này</h2>
      <p>Hệ thống chưa thể tạo kết quả CO₂e chính thức cho vụ này vì bộ hệ số cần thiết chưa được xác minh đầy đủ.</p>
      <small>Dữ liệu canh tác của bạn vẫn được lưu bình thường.</small>
    </section>
  )
}

function FarmerCarbonSuccess({ result }: { result: CarbonResult }) {
  return (
    <div className="farmer-stack">
      <section className="farmer-carbon-result">
        <p>Carbon của vụ này</p>
        <strong>{result.co2e_per_kg == null ? 'Chưa đủ dữ liệu' : perKg(result.co2e_per_kg, '')}</strong>
        <span>{result.co2e_per_kg == null ? 'Cần sản lượng hợp lệ để tính CO₂e/kg' : 'kg CO₂e / kg lúa'}</span>
        <small>Tổng vụ: {result.total_co2e_kg == null ? 'Chưa đủ dữ liệu' : `${Math.round(result.total_co2e_kg)} kg CO₂e`} · Kịch bản: {result.water_regime_scenario ?? result.scenario ?? 'Chưa có dữ liệu'}</small>
        {result.calculated_at && <small>Tính lúc {dateTime(result.calculated_at)}</small>}
      </section>
      <Section title="Nguồn phát thải chính">
        <div className="farmer-source-list">
          {result.breakdown.map((item, index) => <div key={index}><b>{item.source}</b><span>{perKg(item.co2e_kg, 'kg CO₂e')}</span></div>)}
        </div>
      </Section>
      <Notice kind="info">Kết quả là ước tính theo bộ phương pháp hiện tại; không phải chứng nhận hoặc tín chỉ carbon.</Notice>
      <details className="activity-form__disclosure">
        <summary>Cách tính (chi tiết phương pháp luận)</summary>
        <dl className="dl" style={{ gridTemplateColumns: '1fr', marginTop: 10 }}>
          <div><dt>Phiên bản bộ hệ số</dt><dd>{result.ef_config_version ?? 'Chưa có dữ liệu'}</dd></div>
          <div><dt>Phiên bản công cụ tính</dt><dd>{result.engine_version ?? 'Chưa có dữ liệu'}</dd></div>
          {result.warnings.length > 0 && <div><dt>Cảnh báo</dt><dd>{result.warnings.join('; ')}</dd></div>}
        </dl>
      </details>
    </div>
  )
}

function FarmerAccount({ session }: { session: Session | null }) {
  const scope = useAsync(loadScope, [])
  return <>
    <PageHead eyebrow="Tài khoản" title="Thông tin của tôi" />
    <section className="farmer-account">
      <span className="avatar" aria-hidden="true">{session?.user.email?.[0]?.toUpperCase() ?? 'N'}</span>
      <div><b>{session?.user.email ?? 'Tài khoản nông hộ'}</b><small>Vai trò: Nông hộ</small></div>
      <button className="btn btn--ghost" onClick={() => void signOut().then(() => go('/login'))}>Đăng xuất</button>
    </section>
    <Section title="Phạm vi truy cập" description="Ruộng và vụ canh tác bạn đang được gán quyền xem/ghi">
      <Async state={scope} skeleton="kpis">
        {(data) => (
          <div className="farmer-metrics">
            <MetricCard name="Ruộng" value={data.farms.length} />
            <MetricCard name="Thửa ruộng" value={data.plots.length} />
            <MetricCard name="Vụ canh tác" value={data.seasons.length} />
          </div>
        )}
      </Async>
    </Section>
  </>
}

type FarmerRoute = 'home' | 'journal' | 'farms' | 'farm' | 'plot' | 'season' | 'season-journal' | 'season-performance' | 'season-carbon' | 'performance' | 'account' | 'not-found'
function farmerRoute(path: string): FarmerRoute {
  if (path === '/farmer') return 'home'; if (path === '/farmer/journal') return 'journal'; if (path === '/farmer/farms') return 'farms'; if (path === '/farmer/performance') return 'performance'; if (path === '/farmer/account') return 'account'; if (/^\/farmer\/farms\/[^/]+$/.test(path)) return 'farm'; if (/^\/farmer\/plots\/[^/]+$/.test(path)) return 'plot'; if (/^\/farmer\/crop-seasons\/[^/]+\/journal$/.test(path)) return 'season-journal'; if (/^\/farmer\/crop-seasons\/[^/]+\/performance$/.test(path)) return 'season-performance'; if (/^\/farmer\/crop-seasons\/[^/]+\/carbon$/.test(path)) return 'season-carbon'; if (/^\/farmer\/crop-seasons\/[^/]+$/.test(path)) return 'season'; return 'not-found'
}
function farmerParam(path: string): string | null { return path.match(/^\/farmer\/(?:farms|plots|crop-seasons)\/([^/]+)/)?.[1] ?? null }
