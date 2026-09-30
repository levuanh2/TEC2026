import { Ico } from '../icons'
import { useCarbonView } from '../carbon/useCarbonView'
import { label, seasonStatus } from '../vocab'
import { getCropSeason, getActivities, getProductionBatches, endCropSeason, endSeasonErrorMessage } from '../api/crops'
import { useState } from 'react'
import { getPlot, usingMockData } from '../api/farms'
import { getOrganizationMrvBatches } from '../api/mrv'
import { getResourceMetrics } from '../api/metrics'
import { ha, kg, date, perKg, vndPerKg } from '../format'
import {
  Async,
  Badge,
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
  ConfirmDialog,
} from '../ui'
import { ActivityTimeline, ActivityCoverage } from '../features/activities'
import { CarbonPanel } from '../features/carbon'
import { SeasonMethodologyPanel } from '../features/seasonMethodology'
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
export function SeasonHub({ id, tab, role, organizationId }: { id: string; tab: SeasonTab; role?: Role; organizationId?: string | null }) {
  const frame = useAsync(async () => {
    const season = await getCropSeason(id)
    const plot = season?.plotId ? await getPlot(season.plotId).catch(() => undefined) : undefined
    return { season, plot }
  }, [id])
  const metrics = useAsync(() => getResourceMetrics(id), [id])
  const activities = useAsync(() => getActivities(id), [id])
  const batches = useAsync(() => getProductionBatches(id), [id])
  const [ending, setEnding] = useState(false)
  const [endBusy, setEndBusy] = useState(false)
  const [endError, setEndError] = useState<string | null>(null)

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
                <>Trạng thái: {seasonStatus(season.status)}</>,
              ]}
              actions={<>
                {tab !== 'carbon' && (
                  <button className="btn btn--ghost" onClick={() => go(`${base}/carbon`)}>
                    Xem Carbon
                  </button>
                )}
                {/* Only an active cooperative manager may end a season from
                  * Management; the server decides (user_can_write_crop). */}
                {role === 'cooperative_manager' && season.status === 'active' && (
                  <button className="btn btn--ghost" onClick={() => setEnding(true)}>Kết thúc vụ</button>
                )}
              </>}
            />

            <Tabs items={tabs} />
            {ending && (
              <ConfirmDialog
                title={`Kết thúc vụ ${season.name}?`}
                body={<>
                  <p>Sau khi kết thúc, nhật ký vụ chỉ còn để xem: nông hộ không ghi, sửa hay xóa hoạt động nữa, kể cả từ ứng dụng điện thoại. Hiệu suất và Carbon giữ nguyên. Vụ đã kết thúc không mở lại được.</p>
                  {endError && <p className="form-field__error" role="alert">{endError}</p>}
                </>}
                confirmLabel="Kết thúc vụ"
                tone="danger"
                busy={endBusy}
                onCancel={() => { setEnding(false); setEndError(null) }}
                onConfirm={async () => {
                  setEndBusy(true); setEndError(null)
                  try { await endCropSeason(season.id); setEnding(false); frame.reload() }
                  catch (err) { setEndError(endSeasonErrorMessage(err)) }
                  finally { setEndBusy(false) }
                }}
              />
            )}

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
            {tab === 'carbon' && (
              <div className="stack">
                {/* Inputs first, result second: the panel says which methodology
                  * input is still missing, which is the usual reason the result
                  * below cannot be produced. */}
                {/* A farm-level `viewer` still shows up as app role `farmer`, so the
                  * client cannot rule them out here — the backend answers 404 and the
                  * panel surfaces that as a permission message. */}
                {/* Result and readiness first; the methodology form is the
                  * detail behind it, open only while something there is missing. */}
                <CarbonPanel id={id} seasonLabel={season.name} canRecalculate={role !== 'regulator' && role !== 'enterprise_viewer'} />
                <SeasonMethodologyPanel
                  season={season}
                  canEdit={role !== 'regulator' && role !== 'enterprise_viewer'}
                  onSaved={() => frame.reload()}
                />
              </div>
            )}
            {tab === 'mrv' && (
              <Async state={batches} skeleton="table">
                {(rows) => <SeasonMrv seasonId={id} organizationId={organizationId ?? null} batches={rows} />}
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
            <MiniMetric label="Chi phí/kg" value={m?.costPerKg == null ? '—' : `${vndPerKg(m.costPerKg)} ₫`} />
          </div>
          <button className="btn btn--link" onClick={() => go(`${base}/performance`)}>
            Xem chi tiết hiệu suất <Ico name="arrow" size={14} />
          </button>
        </div>

        {/* "Bước tiếp theo" used to be decided by whether a harvest record
          * existed, which is how this card came to say "Đã đủ dữ liệu vụ"
          * about a season whose Carbon screen was naming a missing straw
          * input and an unverified fuel factor. It now reads from the same
          * view model as every other Carbon surface. */}
        <CarbonNextStep seasonId={season.id} base={base} />
      </div>

      {(batches.data?.length ?? 0) > 0 && (
        <Section title="Lô sản xuất (truy xuất nguồn gốc)">
          <DataTable
            rows={batches.data!}
            rowKey={(b) => b.id}
            columns={[
              { label: 'Mã lô', render: (b) => <span className="col-key">{b.batchCode}</span> },
              { label: 'Tên', render: (b) => b.name ?? '—' },
              { label: 'Trạng thái', render: (b) => label('cropStatus', b.status) },
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
        <MetricCard name="Carbon / kg" value={metrics.co2ePerKg == null ? 'Chưa đủ dữ liệu' : perKg(metrics.co2ePerKg, '')} unit="kg CO₂e/kg" context={metrics.co2ePerKg == null ? 'Chưa có kết quả Carbon đã tính' : 'Theo kết quả Carbon đã lưu của vụ'} />
        <MetricCard name="Chi phí / kg" value={metrics.costPerKg == null ? 'Chưa đủ dữ liệu' : vndPerKg(metrics.costPerKg)} unit="₫/kg" context="Tổng chi phí đầu vào chia sản lượng" status={tone(metrics.completeness.cost)} />
      </div>
      {!metrics.completeness.cost && (
        <Notice kind="info">Chi phí đầu vào chưa nhập đủ — chỉ số chi phí/kg tạm thời chưa hiển thị.</Notice>
      )}
    </Section>
  )
}

/** A season belongs to an MRV case only through a real case↔batch relation.
 *
 * Every season has a production batch (the `default` one is created with the
 * season), so "has a batch" says nothing about MRV. This reads the cases in
 * scope and their linked batches, and claims membership only for a case that
 * actually lists this season. */
function SeasonMrv({ seasonId, organizationId, batches }: { seasonId: string; organizationId: string | null; batches: Batches }) {
  const memberships = useAsync(async () => {
    if (usingMockData || !organizationId) return []
    // One request for every case of the organization (Round 5.1: it was one
    // batches request per case, unbounded).
    const cases = await getOrganizationMrvBatches(organizationId)
    return cases
      .map(({ batches: all, ...c }) => ({ c, batches: all.filter((b) => b.cropSeasonId === seasonId) }))
      .filter((x) => x.batches.length > 0)
  }, [seasonId, organizationId])
  const linked = memberships.data ?? []
  const first = linked[0]
  return (
    <Section
      title="MRV"
      description={memberships.loading ? 'Đang kiểm tra liên kết hồ sơ MRV…'
        : memberships.error ? 'Chưa kiểm tra được liên kết hồ sơ MRV.'
          : first ? `Vụ này thuộc hồ sơ MRV ${linked.map((x) => x.c.caseCode).join(', ')} qua các lô sản xuất được liên kết.`
            : 'Vụ này chưa thuộc hồ sơ MRV nào.'}
      cta={first ? { label: 'Mở hồ sơ MRV của vụ', to: `/mrv?case=${encodeURIComponent(first.c.caseId)}` } : undefined}
    >
      <div data-testid="season-mrv-membership" data-linked={memberships.loading ? 'loading' : memberships.error ? 'unknown' : first ? 'true' : 'false'} hidden />
      {!memberships.loading && !memberships.error && !first && (
        <Notice kind="info">
          Lô sản xuất bên dưới là đơn vị truy xuất của vụ; lô chưa được gắn vào hồ sơ MRV nên vụ chưa tham gia MRV.
        </Notice>
      )}
      {batches.length === 0 ? (
        <EmptyState icon="task" title="Vụ chưa có lô sản xuất" />
      ) : (
        <DataTable
          rows={batches}
          rowKey={(b) => b.id}
          columns={[
            { label: 'Lô sản xuất', render: (b) => <span className="col-key">{b.batchCode === 'default' ? 'Lô mặc định của vụ' : b.batchCode}</span> },
            { label: 'Hồ sơ MRV', render: (b) => {
              const hit = linked.find((x) => x.batches.some((mb) => mb.productionBatchId === b.id))
              return hit ? hit.c.caseCode : 'Chưa gắn'
            } },
            { label: 'Trạng thái', render: (b) => label('cropStatus', b.status) },
            { label: 'Bắt đầu', render: (b) => b.startedOn ? date(b.startedOn) : 'Chưa ghi nhận' },
            { label: 'Kết thúc', render: (b) => b.closedOn ? date(b.closedOn) : 'Chưa kết thúc' },
          ]}
        />
      )}
    </Section>
  )
}


/** What this season actually needs next, from the one shared Carbon view.
 *
 * Shows the same wording as the Carbon tab, the Carbon list and the Farmer's
 * own screen, and offers an action only when that action can succeed. */
function CarbonNextStep({ seasonId, base }: { seasonId: string; base: string }) {
  const { view, loading } = useCarbonView(seasonId, {
    fixTarget: base,
    resultTarget: `${base}/carbon`,
  })
  return (
    <div className="card card--pad stack">
      <span className="kpi__label">Bước tiếp theo</span>
      {loading || !view ? (
        <p className="skeleton sk-line" style={{ height: 16, width: '80%' }} aria-label="Đang đọc trạng thái Carbon" />
      ) : (
        <>
          <p>
            <Badge tone={view.tone === 'positive' ? 'success' : view.tone === 'attention' ? 'warning' : 'neutral'}>
              <Ico name={view.icon === 'check' ? 'check' : view.icon === 'warning' ? 'warning' : 'info'} size={13} />{view.label}
            </Badge>
          </p>
          <p style={{ fontSize: 'var(--fs-sm)' }}>{view.detail}</p>
          {view.userFixableGaps.length > 0 && (
            <ul className="stack" style={{ fontSize: 'var(--fs-caption)', margin: 0, paddingLeft: 18 }}>
              {view.userFixableGaps.map((g) => <li key={g.code}>{g.label}</li>)}
            </ul>
          )}
        </>
      )}
      {/* One link out of this card, and only to a screen that can help. */}
      <button className="btn btn--ghost" onClick={() => go(`${base}/carbon`)}>
        Mở màn hình Carbon <Ico name="arrow" size={14} />
      </button>
    </div>
  )
}
