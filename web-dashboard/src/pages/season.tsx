import { Ico } from '../icons'
import { getCropSeason, getActivities, getProductionBatches } from '../api/crops'
import { getPlot } from '../api/farms'
import { getResourceMetrics } from '../api/metrics'
import { ha, kg, date, perKg } from '../format'
import {
  Async,
  Breadcrumb,
  DataTable,
  DL,
  EmptyState,
  MetricCard,
  Notice,
  PageHead,
  Section,
  Tabs,
  useAsync,
  go,
  type Tone,
} from '../ui'
import { ActivityTimeline, ActivityCoverage } from '../features/activities'
import { CarbonPanel } from '../features/carbon'
import type { Role } from '../types'

export type SeasonTab = 'overview' | 'activities' | 'performance' | 'carbon' | 'mrv'

const tone = (ok: boolean): { tone: Tone; label: string } =>
  ok ? { tone: 'success', label: 'Đầy đủ dữ liệu' } : { tone: 'warning', label: 'Thiếu dữ liệu' }

type Metrics = Awaited<ReturnType<typeof getResourceMetrics>>
type Activities = Awaited<ReturnType<typeof getActivities>>
type Batches = Awaited<ReturnType<typeof getProductionBatches>>

/**
 * Season "hub": the frame (hero + tabs) loads from one fast query, every tab's
 * data streams into its own section so a slow query never blanks the page.
 */
export function SeasonHub({ id, tab, role }: { id: string; tab: SeasonTab; role?: Role }) {
  const frame = useAsync(async () => {
    const season = await getCropSeason(id)
    const plot = season?.plotId ? await getPlot(season.plotId).catch(() => undefined) : undefined
    return { season, plot }
  }, [id])
  const metrics = useAsync(() => getResourceMetrics(id), [id])
  const activities = useAsync(() => getActivities(id), [id])
  const batches = useAsync(() => getProductionBatches(id), [id])

  const base = `/crop-seasons/${id}`
  const tabs = [
    { label: 'Tổng quan', to: base, current: tab === 'overview' },
    { label: 'Hoạt động', to: `${base}/activities`, current: tab === 'activities' },
    { label: 'Hiệu suất', to: `${base}/performance`, current: tab === 'performance' },
    { label: 'Carbon', to: `${base}/carbon`, current: tab === 'carbon' },
    { label: 'MRV', to: `${base}/mrv`, current: tab === 'mrv' },
  ]

  return (
    <Async state={frame} isEmpty={(d) => !d.season} empty={<EmptyState icon="search" title="Không tìm thấy vụ canh tác" />}>
      {({ season, plot }) => {
        if (!season) return <EmptyState icon="search" title="Không tìm thấy vụ canh tác" />
        return (
          <>
            <Breadcrumb
              items={[
                { label: 'Nông hộ', to: '/farms' },
                ...(plot ? [{ label: plot.name, to: `/plots/${plot.id}` }] : []),
                { label: season.name },
              ]}
            />
            <PageHead
              eyebrow="Vụ canh tác"
              title={season.name}
              meta={[
                <>
                  Giống <b>{season.variety ?? '—'}</b>
                </>,
                <>
                  {plot ? plot.name : 'Thửa —'} · <b>{plot?.areaHa == null ? '—' : ha(plot.areaHa)}</b>
                </>,
                <>Trạng thái: {season.status ?? '—'}</>,
              ]}
              actions={
                <button className="btn" onClick={() => go(`${base}/carbon`)}>
                  Xem Carbon
                </button>
              }
            />

            <Tabs items={tabs} />

            {tab === 'overview' && (
              <Overview season={season} plot={plot} metrics={metrics} activities={activities} batches={batches} base={base} />
            )}
            {tab === 'activities' && (
              <Section title="Nhật ký hoạt động" description="Ghi nhận canh tác theo nhóm — nhấp để xem chi tiết">
                <Async state={activities} skeleton="table">
                  {(rows) => <ActivityTimeline activities={rows} />}
                </Async>
              </Section>
            )}
            {tab === 'performance' && (
              <Async state={metrics} skeleton="kpis">
                {(m) => <Performance metrics={m} />}
              </Async>
            )}
            {tab === 'carbon' && <CarbonPanel id={id} seasonLabel={season.name} canRecalculate={role !== 'regulator' && role !== 'enterprise_viewer'} />}
            {tab === 'mrv' && (
              <Async state={batches} skeleton="table">
                {(rows) => <SeasonMrv batches={rows} />}
              </Async>
            )}
          </>
        )
      }}
    </Async>
  )
}

type St<T> = ReturnType<typeof useAsync<T>>

function Overview({
  season,
  plot,
  metrics,
  activities,
  batches,
  base,
}: {
  season: NonNullable<Awaited<ReturnType<typeof getCropSeason>>>
  plot: Awaited<ReturnType<typeof getPlot>>
  metrics: St<Metrics>
  activities: St<Activities>
  batches: St<Batches>
  base: string
}) {
  const m = metrics.data
  const acts = activities.data ?? []
  const hasHarvest = acts.some((a) => a.type === 'harvest') || m?.yieldKg != null

  return (
    <div className="stack">
      <div className="card card--pad">
        <DL
          items={[
            { term: 'Giống', value: season.variety ?? '—' },
            { term: 'Vụ', value: season.name },
            { term: 'Ngày gieo sạ', value: date(season.plantingDate) },
            { term: 'Ngày thu hoạch', value: date(season.harvestDate) },
            { term: 'Diện tích thửa', value: plot?.areaHa == null ? '—' : ha(plot.areaHa) },
            {
              term: 'Sản lượng',
              value: metrics.loading ? 'Đang tải…' : m?.yieldKg == null ? 'Chưa có dữ liệu thu hoạch' : kg(m.yieldKg),
            },
          ]}
        />
      </div>

      <Section title="Dữ liệu hoạt động đã ghi nhận">
        <Async state={activities} skeleton="table">
          {(rows) => <ActivityCoverage activities={rows} />}
        </Async>
      </Section>

      <div className="split">
        <div className="card card--pad stack">
          <span className="kpi__label">Hiệu suất trên mỗi kg (tóm tắt)</span>
          <div className="grid grid-2">
            <MiniMetric label="Nước/kg" value={m?.waterPerKg == null ? '—' : perKg(m.waterPerKg, 'm³')} />
            <MiniMetric label="Phân/kg" value={m?.fertilizerPerKg == null ? '—' : perKg(m.fertilizerPerKg, 'kg')} />
            <MiniMetric label="CO₂e/kg" value={m?.co2ePerKg == null ? '—' : perKg(m.co2ePerKg, 'kg')} />
            <MiniMetric label="Chi phí/kg" value={m?.costPerKg == null ? '—' : perKg(m.costPerKg, '₫')} />
          </div>
          <button className="btn btn--link" onClick={() => go(`${base}/performance`)}>
            Xem chi tiết hiệu suất <Ico name="arrow" size={14} />
          </button>
        </div>

        <div className="card card--pad stack">
          <span className="kpi__label">Bước tiếp theo</span>
          <p style={{ fontSize: 'var(--fs-sm)' }}>
            {!hasHarvest
              ? 'Chưa có bản ghi thu hoạch — CO₂e/kg và chi phí/kg sẽ tính được sau khi nhập sản lượng.'
              : 'Đã đủ dữ liệu vụ. Chạy Carbon Engine để xem phát thải và chuẩn bị hồ sơ MRV.'}
          </p>
          <button className="btn btn--ghost" onClick={() => go(`${base}/carbon`)}>
            Mở màn hình Carbon <Ico name="arrow" size={14} />
          </button>
        </div>
      </div>

      {(batches.data?.length ?? 0) > 0 && (
        <Section title="Lô sản xuất (truy xuất nguồn gốc)">
          <DataTable
            rows={batches.data!}
            rowKey={(b) => b.id}
            columns={[
              { label: 'Mã lô', render: (b) => <span className="col-key">{b.batchCode}</span> },
              { label: 'Tên', render: (b) => b.name ?? '—' },
              { label: 'Trạng thái', render: (b) => b.status },
              { label: 'Bắt đầu', render: (b) => date(b.startedOn) },
            ]}
          />
        </Section>
      )}
    </div>
  )
}

function MiniMetric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="kpi__label">{label}</div>
      <div className={`kpi__value${value === '—' ? ' is-empty' : ''}`} style={{ fontSize: 18 }}>
        {value}
      </div>
    </div>
  )
}

function Performance({ metrics }: { metrics: Metrics }) {
  return (
    <Section title="Hiệu suất trên mỗi kg thóc" description="Lõi khác biệt của AgriCarbon — mỗi chỉ số kèm ngữ cảnh và trạng thái dữ liệu">
      <div className="grid grid-4">
        <MetricCard name="Nước / kg" value={metrics.waterPerKg == null ? 'Chưa đủ dữ liệu' : perKg(metrics.waterPerKg, '')} unit="m³/kg" context="Tổng nước tưới chia sản lượng" status={tone(metrics.completeness.water)} />
        <MetricCard name="Phân bón / kg" value={metrics.fertilizerPerKg == null ? 'Chưa đủ dữ liệu' : perKg(metrics.fertilizerPerKg, '')} unit="kg/kg" context="Tổng phân bón chia sản lượng" status={tone(metrics.completeness.fertilizer)} />
        <MetricCard name="Carbon / kg" value={metrics.co2ePerKg == null ? 'Chưa đủ dữ liệu' : perKg(metrics.co2ePerKg, '')} unit="kg CO₂e/kg" context="Chờ GWP theo QĐ 4801 / IPCC Tier 2" status={{ tone: 'warning', label: 'Đang chờ hệ số' }} />
        <MetricCard name="Chi phí / kg" value={metrics.costPerKg == null ? 'Chưa đủ dữ liệu' : perKg(metrics.costPerKg, '')} unit="₫/kg" context="Tổng chi phí đầu vào chia sản lượng" status={tone(metrics.completeness.cost)} />
      </div>
      {!metrics.completeness.cost && (
        <Notice kind="info">Chi phí đầu vào chưa nhập đủ — chỉ số chi phí/kg tạm thời chưa hiển thị.</Notice>
      )}
    </Section>
  )
}

function SeasonMrv({ batches }: { batches: Batches }) {
  return (
    <Section title="MRV" description="Vụ này tham gia hồ sơ MRV của tổ chức thông qua các lô sản xuất bên dưới" cta={{ label: 'Mở hồ sơ MRV', to: '/mrv' }}>
      {batches.length === 0 ? (
        <EmptyState icon="task" title="Vụ chưa gắn lô sản xuất nào vào hồ sơ MRV" />
      ) : (
        <DataTable
          rows={batches}
          rowKey={(b) => b.id}
          columns={[
            { label: 'Mã lô', render: (b) => <span className="col-key">{b.batchCode}</span> },
            { label: 'Trạng thái', render: (b) => b.status },
            { label: 'Bắt đầu', render: (b) => date(b.startedOn) },
            { label: 'Kết thúc', render: (b) => date(b.closedOn) },
          ]}
        />
      )}
    </Section>
  )
}
