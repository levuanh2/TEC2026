import type { SeasonMetrics } from '../../api/metrics'
import type { Activity } from '../../types'
import { date, daysSince, ha } from '../../format'
import { ACTIVITY_TITLE, dayLabel, fmtNumber } from '../activityView'
import {
  ActivityCardActions, ActivityDetailActions, AddActivityCta, toSeasonContext, useActivityMutations,
  type ActivityMutations, type SeasonContext,
} from '../ActivityForms'
import { CvHistorySection, CvPreviewCard } from '../CvCheck'
import type { QueryState } from '../data'
import { Ico, type IconName } from '../icons'
import { JournalView, MiniTimeline } from '../journal'
import { Crumbs, ErrorPanel, Fact, Flash, IconTile, MoreLink, Section, Sk, SkBlock, Tabs } from '../kit'
import { RecommendationsSection } from '../Recommendations'
import { isActiveStatus, resolveSeason, seasonStatusLabel, useActivities, useMetrics, useScope, type SeasonCtx } from '../scope'
import { SeasonCarbon } from './Carbon'
import { MetricCards } from './Performance'
import { useCanEditSeason, useWritableSeason } from '../writeAccess'
import { NEW_SEASON_PARAM } from '../StartSeason'

export type SeasonTab = 'overview' | 'journal' | 'performance' | 'carbon'
const NOT_FOUND = 'Không tìm thấy dữ liệu hoặc dữ liệu không thuộc phạm vi truy cập.'

export function SeasonWorkspace({ id, tab }: { id: string; tab: SeasonTab }) {
  const scope = useScope()
  const ctx = resolveSeason(scope.data, id)
  const metrics = useMetrics(id)
  const activities = useActivities(id)
  const mutations = useActivityMutations()
  const seasonCtx = ctx ? toSeasonContext(ctx.season, ctx.plot) : null
  // Journal write affordances only where the farm role allows writing.
  const writeCtx = useWritableSeason(ctx)
  const canEditSeason = useCanEditSeason(ctx)
  // Opened straight after "Bắt đầu vụ mới": offer the first record once.
  const justStarted = new URLSearchParams(location.search).has(NEW_SEASON_PARAM)
  const base = `/farmer/crop-seasons/${id}`
  const tabs: { label: string; to: string; icon: IconName; current: boolean }[] = [
    { label: 'Tổng quan', to: base, icon: 'overview', current: tab === 'overview' },
    { label: 'Nhật ký', to: `${base}/journal`, icon: 'journal', current: tab === 'journal' },
    { label: 'Hiệu suất', to: `${base}/performance`, icon: 'performance', current: tab === 'performance' },
    { label: 'Carbon', to: `${base}/carbon`, icon: 'carbon', current: tab === 'carbon' },
  ]

  if (scope.error && !scope.data) return <ErrorPanel error={scope.error} onRetry={scope.reload} />
  if (scope.data && !ctx) {
    return <><Crumbs items={[{ label: 'Ruộng của tôi', to: '/farmer/farms' }, { label: 'Vụ canh tác' }]} /><ErrorPanel error={NOT_FOUND} /></>
  }

  return (
    <>
      {ctx ? <SeasonHeader ctx={ctx} /> : <SeasonHeaderSkeleton />}
      <Tabs items={tabs} />
      <Flash message={mutations.flash} />
      {writeCtx && justStarted && !activities.data?.length && mutations.version === 0 && (
        <div className="fw-started" role="status">
          <p>Đã bắt đầu vụ <b>{ctx?.season.name}</b>. Vụ đã sẵn sàng để ghi nhật ký.</p>
          <button type="button" className="fw-btn" onClick={() => mutations.openPicker(writeCtx)}><Ico name="plus" />Ghi hoạt động đầu tiên</button>
        </div>
      )}
      {tab === 'overview' && <SeasonOverview id={id} ctx={ctx} seasonCtx={seasonCtx} writeCtx={writeCtx} metrics={metrics} activities={activities} mutations={mutations} />}
      {tab === 'journal' && (
        <Section
          title="Nhật ký của vụ này"
          icon="journal"
          tone="leaf"
          description={ctx ? `Chỉ hoạt động thuộc "${ctx.season.name}" — nhấn một hoạt động để xem chi tiết.` : undefined}
          action={writeCtx ? <AddActivityCta season={writeCtx} mutations={mutations} /> : undefined}
        >
          <JournalView
            state={activities}
            resetSignal={mutations.version}
            renderCardActions={writeCtx ? (a) => <ActivityCardActions activity={a} season={writeCtx} mutations={mutations} /> : undefined}
            renderDetailActions={writeCtx ? (a) => <ActivityDetailActions activity={a} season={writeCtx} mutations={mutations} /> : undefined}
          />
        </Section>
      )}
      {tab === 'performance' && (
        <Section title="Hiệu suất vụ này" icon="performance" description="Mỗi chỉ số kèm ý nghĩa và dữ liệu dùng để tính; thiếu dữ liệu không bị thay bằng số 0.">
          <MetricCards state={metrics} activities={activities} ctx={ctx} season={writeCtx} mutations={mutations} carbonTo={`/farmer/crop-seasons/${id}/carbon`} />
        </Section>
      )}
      {tab === 'carbon' && (
        <SeasonCarbon
          seasonId={id} season={ctx?.season ?? null} plotId={ctx?.plot?.id ?? null} writeCtx={writeCtx} canEditSeason={canEditSeason}
          activities={activities.data} mutations={mutations} onSaved={scope.reload}
        />
      )}
      {mutations.node}
    </>
  )
}

function SeasonHeader({ ctx }: { ctx: SeasonCtx }) {
  const { season, plot, farm } = ctx
  const active = isActiveStatus(season.status)
  const days = !season.harvestDate ? daysSince(season.plantingDate) : null
  return (
    <section className="fw-ws-head">
      <Crumbs items={[
        { label: 'Ruộng của tôi', to: '/farmer/farms' },
        ...(farm ? [{ label: farm.name, to: `/farmer/farms/${farm.id}` }] : []),
        ...(plot ? [{ label: plot.name, to: `/farmer/plots/${plot.id}` }] : []),
        { label: season.name },
      ]} />
      <div className="fw-ws-head__title">
        <IconTile name="seeding" tone="leaf" size="lg" />
        <div>
          <p className="fw-head__eyebrow">Vụ canh tác</p>
          <h1>{season.name}</h1>
        </div>
        <span className={`fw-chip fw-chip--dot tone-${active ? 'leaf' : 'sage'}`}>{seasonStatusLabel(season.status)}</span>
      </div>
      <div className="fw-ws-head__facts">
        <Fact icon="plot" label="Thửa" value={plot ? `${plot.name}${plot.areaHa != null ? ` · ${ha(plot.areaHa)}` : ''}` : null} />
        <Fact icon="farm" label="Nông hộ" value={farm?.name} />
        <Fact icon="seeding" label="Giống" value={season.variety} />
        <Fact icon="calendar" label="Gieo sạ" value={season.plantingDate ? date(season.plantingDate) : null} />
        <Fact icon="harvest" label="Thu hoạch" value={season.harvestDate ? date(season.harvestDate) : null} />
        {days != null && <Fact icon="clock" label="Đã canh tác" value={`${days} ngày`} />}
      </div>
    </section>
  )
}

function SeasonHeaderSkeleton() {
  return (
    <SkBlock label="Đang tải vụ canh tác" className="fw-ws-head">
      <Sk w={260} h={14} />
      <div className="fw-ws-head__title"><Sk w={58} h={58} r={17} /><span className="fw-sk-lines"><Sk w={90} h={12} /><Sk w={220} h={28} /></span></div>
      <div className="fw-ws-head__facts">{[0, 1, 2, 3, 4].map((i) => <Sk key={i} h={54} r={14} />)}</div>
    </SkBlock>
  )
}

function SeasonOverview({ id, ctx, seasonCtx, writeCtx, metrics, activities, mutations }: {
  id: string; ctx: SeasonCtx | null; seasonCtx: SeasonContext | null; writeCtx: SeasonContext | null
  metrics: QueryState<SeasonMetrics>; activities: QueryState<Activity[]>; mutations: ActivityMutations
}) {
  return (
    <>
      {/* One way to start a record, the same one the journal has: the
        * picker is step 1 inside the sheet, not a second grid on the page. */}
      {writeCtx && (
        <p className="fw-cta-row fw-cta-row--start"><AddActivityCta season={writeCtx} mutations={mutations} /></p>
      )}
      <div className="fw-grid-2">
        <Section title="Tình trạng vụ" icon="checklist" tone="leaf">
          <SeasonStatus ctx={ctx} metrics={metrics} activities={activities} />
        </Section>
        <Section title="Mức đầy đủ dữ liệu" icon="check" description="Mỗi mục chỉ tính từ bản ghi thực tế.">
          <Completeness metrics={metrics} />
        </Section>
      </div>
      <div className="fw-grid-2">
        <Section title="Hoạt động gần đây" icon="journal" tone="leaf" action={<MoreLink to={`/farmer/crop-seasons/${id}/journal`}>Xem nhật ký</MoreLink>}>
          <MiniTimeline state={activities} limit={5} />
        </Section>
        <RecommendationsSection seasonId={id} />
      </div>
      <CvPreviewCard season={seasonCtx} seasonId={id} />
      <CvHistorySection seasonId={id} />
    </>
  )
}

function SeasonStatus({ ctx, metrics, activities }: { ctx: SeasonCtx | null; metrics: QueryState<SeasonMetrics>; activities: QueryState<Activity[]> }) {
  if (!ctx || activities.loading) {
    return <SkBlock label="Đang tải tình trạng vụ" className="fw-card fw-card--pad">{[0, 1, 2, 3, 4].map((i) => <Sk key={i} w="100%" h={18} />)}</SkBlock>
  }
  const rows = activities.data ?? []
  const latest = rows.reduce<string | null>((max, a) => (!max || a.occurredAt > max ? a.occurredAt : max), null)
  const types = [...new Set(rows.map((a) => a.type))]
  const days = !ctx.season.harvestDate ? daysSince(ctx.season.plantingDate) : null
  return (
    <div className="fw-card fw-card--pad">
      <dl className="fw-detail">
        <div><dt>Trạng thái</dt><dd>{seasonStatusLabel(ctx.season.status)}</dd></div>
        <div><dt>Thời gian canh tác</dt><dd>{days != null ? `${days} ngày kể từ gieo sạ` : ctx.season.harvestDate ? `Thu hoạch ${date(ctx.season.harvestDate)}` : 'Chưa ghi nhận ngày gieo sạ'}</dd></div>
        <div><dt>Hoạt động đã ghi</dt><dd>{activities.error ? '—' : rows.length}</dd></div>
        <div><dt>Loại hoạt động</dt><dd>{types.length ? types.map((t) => ACTIVITY_TITLE[t] ?? t).join(', ') : 'Chưa có'}</dd></div>
        <div><dt>Lần ghi gần nhất</dt><dd>{latest ? dayLabel(latest.slice(0, 10)) : 'Chưa có'}</dd></div>
        <div><dt>Sản lượng đã ghi</dt><dd>{metrics.loading ? '…' : metrics.data?.yieldKg != null ? `${fmtNumber(metrics.data.yieldKg)} kg thóc` : 'Chưa ghi nhận'}</dd></div>
      </dl>
    </div>
  )
}

function Completeness({ metrics }: { metrics: QueryState<SeasonMetrics> }) {
  if (metrics.loading) return <SkBlock label="Đang tải mức đầy đủ dữ liệu" className="fw-checklist">{[0, 1, 2, 3, 4].map((i) => <div key={i} className="fw-check"><Sk w={26} h={26} r={13} /><Sk w="60%" h={14} /></div>)}</SkBlock>
  if (metrics.error || !metrics.data) return <ErrorPanel error={metrics.error ?? 'Không có dữ liệu.'} onRetry={metrics.reload} />
  const m = metrics.data
  const items: { key: string; label: string; ok: boolean; icon: IconName }[] = [
    { key: 'water', label: 'Nước tưới', ok: m.completeness.water, icon: 'irrigation' },
    { key: 'fertilizer', label: 'Phân bón', ok: m.completeness.fertilizer, icon: 'fertilizer' },
    { key: 'yield', label: 'Sản lượng thu hoạch', ok: m.yieldKg != null, icon: 'harvest' },
    { key: 'cost', label: 'Chi phí vật tư', ok: m.completeness.cost, icon: 'money' },
    { key: 'carbon', label: 'Kết quả Carbon', ok: m.completeness.carbon, icon: 'carbon' },
  ]
  const done = items.filter((i) => i.ok).length
  return (
    <div className="fw-stack-sm">
      <div className="fw-progress">
        <div className="fw-progress__row"><span className="fw-note">Mục đã có dữ liệu</span><b>{done}/{items.length}</b></div>
        <div className="fw-progress__bar" role="progressbar" aria-label="Mục dữ liệu đã có" aria-valuemin={0} aria-valuemax={items.length} aria-valuenow={done}><i style={{ width: `${(done / items.length) * 100}%` }} /></div>
      </div>
      <ul className="fw-checklist">
        {items.map((i) => (
          <li key={i.key} className={`fw-check${i.ok ? ' is-ok' : ''}`}>
            <span className="fw-check__mark"><Ico name={i.ok ? 'check' : 'pending'} /></span>
            <span><b>{i.label}</b><small>{i.ok ? 'Đã có dữ liệu' : 'Chưa có dữ liệu'}</small></span>
            <Ico name={i.icon} className="fw-check__ico" />
          </li>
        ))}
      </ul>
    </div>
  )
}
