import { Ico } from '../icons'
import { useState } from 'react'
import {
  listOrganizations,
  getOrganization,
  getOrganizationSummary,
  getFarmPerformance,
} from '../api/organizations'
import { listFarms, getFarm, getPlotsForFarm, getPlot, getFarmMetrics, getFarmCropSeasons } from '../api/farms'
import { getCropSeasons } from '../api/crops'
import { ha, kg, place, perKg, date } from '../format'
import { seasonStatus } from '../vocab'
import {
  Async,
  Badge,
  Breadcrumb,
  DataTable,
  EmptyState,
  Hero,
  Kpi,
  MetricCard,
  PageHead,
  Section,
  useAsync,
  go,
} from '../ui'
import { FarmPerformanceTable } from '../components/FarmPerformanceTable'

const isActiveSeason = (status: string | null | undefined) =>
  ['active', 'in_progress', 'planted'].includes(String(status ?? '').toLowerCase())

/** The plot a season sits on, by id, for tables that list a whole farm. */
function plotName(plots: { id: string; name: string }[] | null | undefined, plotId: string | null | undefined) {
  if (!plotId) return '—'
  return plots?.find((p) => p.id === plotId)?.name ?? '—'
}

/* ============================================================ Organizations */

export function OrganizationsPage() {
  const state = useAsync(() => listOrganizations(), [])
  return (
    <>
      {/* The subtitle used to say "chọn một tổ chức" unconditionally, but the
        * selector only exists when the account administers more than one.
        * With a single organisation there was nothing on the page to choose. */}
      <PageHead
        eyebrow="Quản lý"
        title="Tổ chức / HTX"
        meta={[(state.data?.length ?? 0) > 1
          ? <>Phạm vi quản trị — chọn một tổ chức để xem các nông hộ trực thuộc</>
          : <>Phạm vi quản trị của bạn — các nông hộ trực thuộc tổ chức này</>]}
      />
      <Async state={state} isEmpty={(o) => o.length === 0} empty={<EmptyState icon="organization" title="Chưa có tổ chức nào trong phạm vi truy cập" body="Tài khoản của bạn chưa được gán vào tổ chức hoặc hợp tác xã nào. Liên hệ quản trị viên để được cấp phạm vi." />}>
        {(orgs) => <OrgDetail ids={orgs.map((o) => ({ id: o.id, name: o.name }))} />}
      </Async>
    </>
  )
}

function OrgDetail({ ids }: { ids: { id: string; name: string }[] }) {
  const [selected, setSelected] = useState(ids[0].id)
  // Detail card and the (slow) farm-performance table load independently.
  const detail = useAsync(
    () => Promise.all([getOrganization(selected), getOrganizationSummary(selected)]),
    [selected],
  )
  const performance = useAsync(() => getFarmPerformance(selected), [selected])

  return (
    <>
      {ids.length > 1 && (
        <label className="chip" style={{ padding: '6px 12px', marginBottom: 4, display: 'inline-flex', gap: 8 }}>
          Tổ chức
          <select className="select" value={selected} onChange={(e) => setSelected(e.target.value)}>
            {ids.map((o) => (
              <option key={o.id} value={o.id}>
                {o.name}
              </option>
            ))}
          </select>
        </label>
      )}
      <Async state={detail} skeleton="kpis">
        {([org, summary]) => (
          <Hero
            eyebrow={org.organizationType === 'cooperative' ? 'Hợp tác xã' : org.organizationType}
            title={org.name}
            meta={[
              <>Mã {org.code}</>,
              <><Ico name="pin" size={13} /> {place(org.commune, org.district, org.province)}</>,
              <Badge tone={org.isActive ? 'success' : 'neutral'} dot>{org.isActive ? 'Đang hoạt động' : 'Ngừng hoạt động'}</Badge>,
            ]}
            stats={[
              { label: 'Nông hộ', value: summary.farmCount },
              { label: 'Thửa ruộng', value: summary.plotCount },
              { label: 'Vụ canh tác', value: summary.cropSeasonCount },
              { label: 'Diện tích', value: ha(summary.totalAreaHa) },
            ]}
          />
        )}
      </Async>

      <Section title="Nông hộ trực thuộc" description="So sánh hiệu suất — nhấp một hàng để mở hồ sơ nông hộ">
        <Async state={performance} skeleton="table">
          {(rows) => <FarmPerformanceTable items={rows} />}
        </Async>
      </Section>
    </>
  )
}

/* ================================================================== Farms */

export function FarmsPage() {
  const state = useAsync(() => listFarms(), [])
  // A cooperative has hundreds of households; the register had no way to find
  // one but the browser's own page search. Name, code and place are the three
  // things an officer has in hand when they go looking.
  const [q, setQ] = useState('')
  const match = (f: { name: string; code: string; commune?: string; district?: string; province?: string }) => {
    const needle = q.trim().toLowerCase()
    if (!needle) return true
    return [f.name, f.code, f.commune, f.district, f.province].some((v) => (v ?? '').toLowerCase().includes(needle))
  }
  return (
    <>
      <PageHead eyebrow="Quản lý" title="Nông hộ" meta={[<>Tất cả nông hộ trong phạm vi truy cập của bạn</>]} />
      <Async state={state} isEmpty={(f) => f.length === 0} empty={<EmptyState icon="farms" title="Chưa có nông hộ nào" body="Chưa có nông hộ nào thuộc phạm vi truy cập của tài khoản này." />}>
        {(all) => {
          const farms = all.filter(match)
          return (
        <>
          <div className="ops-filters">
            <label className="ops-search">
              <Ico name="search" size={14} />
              <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Tìm theo tên hộ, mã hộ hoặc địa bàn…" aria-label="Tìm nông hộ" />
            </label>
            <p className="ops-count" aria-live="polite">{farms.length}/{all.length} nông hộ</p>
          </div>
          {farms.length === 0 ? (
            <EmptyState icon="search" title="Không có nông hộ nào khớp từ khóa" body={`Không tìm thấy nông hộ nào cho “${q.trim()}”. Thử tên hộ, mã hộ hoặc tên xã.`} />
          ) : (
          <DataTable
            rows={farms}
            rowKey={(f) => f.id}
            rowHref={(f) => `/farms/${f.id}`}
            rowLabel={(f) => `Mở hồ sơ nông hộ ${f.name}`}
            columns={[
              { label: 'Mã hộ', render: (f) => <span className="col-key">{f.code}</span> },
              { label: 'Chủ hộ', render: (f) => f.name },
              { label: 'Địa bàn', render: (f) => place(f.commune, f.district, f.province) },
              { label: 'Thửa', align: 'num', render: (f) => f.plotCount },
              { label: 'Diện tích', align: 'num', render: (f) => (f.areaHa == null ? <span className="cell-empty">—</span> : ha(f.areaHa)) },
            ]}
          />
          )}
        </>
          )
        }}
      </Async>
    </>
  )
}

/* =============================================================== Farm page */

export function FarmPage({ id }: { id: string }) {
  const head = useAsync(() => getFarm(id), [id])
  const plots = useAsync(() => getPlotsForFarm(id), [id])
  const metrics = useAsync(() => getFarmMetrics(id), [id])
  const seasons = useAsync(() => getFarmCropSeasons(id), [id])

  return (
    <Async state={head} isEmpty={(f) => !f} empty={<EmptyState icon="search" title="Không tìm thấy nông hộ" />}>
      {(farm) => {
        if (!farm) return <EmptyState icon="search" title="Không tìm thấy nông hộ" />
        return (
          <>
            <Breadcrumb items={[{ label: 'Nông hộ', to: '/farms' }, { label: farm.name }]} />
            <Hero
              eyebrow="Nông hộ"
              title={farm.name}
              titleAs="h1"
              meta={[<>Mã hộ {farm.code}</>, <><Ico name="pin" size={13} /> {place(farm.commune, farm.district, farm.province)}</>]}
              stats={[{ label: 'Thửa ruộng', value: farm.plotCount }]}
            />

            <div className="grid grid-3" style={{ marginTop: 'var(--gap-lg)' }}>
              <Async state={plots} skeleton="kpis">
                {(rows) => (
                  <MetricCard
                    name="Diện tích"
                    value={rows.reduce((s, p) => s + (p.areaHa ?? 0), 0) > 0 ? ha(rows.reduce((s, p) => s + (p.areaHa ?? 0), 0)) : 'Chưa đủ dữ liệu'}
                    context="Tổng diện tích các thửa"
                  />
                )}
              </Async>
              <Async state={metrics} skeleton="kpis">
                {(m) => <MetricCard name="Sản lượng" value={m?.yieldKg == null ? 'Chưa đủ dữ liệu' : kg(m.yieldKg)} context="Thóc đã ghi nhận thu hoạch" />}
              </Async>
              <Async state={metrics} skeleton="kpis">
                {(m) => (
                  <MetricCard
                    name="CO₂e / kg"
                    value={m?.co2ePerKg == null ? 'Chưa đủ dữ liệu' : perKg(m.co2ePerKg, '')}
                    unit="kg/kg"
                    context="Chờ hệ số phát thải"
                    status={{ tone: 'warning', label: 'Đang chờ hệ số' }}
                  />
                )}
              </Async>
            </div>

            <Section title="Thửa ruộng">
              <Async state={plots} skeleton="table" isEmpty={(r) => r.length === 0} empty={<EmptyState icon="plot" title="Nông hộ chưa khai báo thửa ruộng" />}>
                {(rows) => (
                  <DataTable
                    rows={rows}
                    rowKey={(p) => p.id}
                    rowHref={(p) => `/plots/${p.id}`}
                    rowLabel={(p) => `Mở thửa ${p.name}`}
                    columns={[
                      { label: 'Mã thửa', render: (p) => <span className="col-key">{p.code}</span> },
                      { label: 'Tên', render: (p) => p.name },
                      { label: 'Diện tích', align: 'num', render: (p) => (p.areaHa == null ? <span className="cell-empty">—</span> : ha(p.areaHa)) },
                      { label: 'Vị trí', render: (p) => p.location ?? '—' },
                    ]}
                  />
                )}
              </Async>
            </Section>

            <Section title="Vụ canh tác" description="Toàn bộ vụ trên các thửa của nông hộ này">
              <Async state={seasons} skeleton="table" isEmpty={(r) => r.length === 0} empty={<EmptyState icon="seeding" title="Nông hộ chưa có vụ canh tác nào" />}>
                {(rows) => (
                  <DataTable
                    rows={rows}
                    rowKey={(s) => s.id}
                    rowHref={(s) => `/crop-seasons/${s.id}`}
                    rowLabel={(s) => `Mở vụ ${s.name}`}
                    columns={[
                      { label: 'Vụ', render: (s) => <span className="col-key">{s.name}</span> },
                      /* A farm has several plots, so "which season" is not an
                       * answer until the plot is named next to it. */
                      { label: 'Thửa', render: (s) => plotName(plots.data, s.plotId) },
                      { label: 'Giống', render: (s) => s.variety ?? '—' },
                      { label: 'Trạng thái', render: (s) => <Badge tone={isActiveSeason(s.status) ? 'success' : 'neutral'} dot>{seasonStatus(s.status)}</Badge> },
                      { label: 'Gieo sạ', render: (s) => date(s.plantingDate) },
                    ]}
                  />
                )}
              </Async>
            </Section>
          </>
        )
      }}
    </Async>
  )
}

/* =============================================================== Plot page */

export function PlotPage({ id }: { id: string }) {
  const state = useAsync(async () => {
    const [plot, seasons] = await Promise.all([getPlot(id), getCropSeasons(id)])
    return { plot, seasons }
  }, [id])

  return (
    <Async state={state} isEmpty={(d) => !d.plot}>
      {({ plot, seasons }) => {
        if (!plot) return <EmptyState icon="search" title="Không tìm thấy thửa ruộng" />
        const active = seasons.find((s) => (s.status ?? '').toLowerCase().includes('active') || (s.status ?? '').includes('canh tác'))
        return (
          <>
            <Breadcrumb
              items={[
                { label: 'Nông hộ', to: '/farms' },
                ...(plot.farmId ? [{ label: 'Hồ sơ nông hộ', to: `/farms/${plot.farmId}` }] : []),
                { label: plot.name },
              ]}
            />
            <Hero
              eyebrow="Thửa ruộng"
              title={plot.name}
              titleAs="h1"
              meta={[<>Mã thửa {plot.code}</>, <><Ico name="pin" size={13} /> {plot.location ?? '—'}</>]}
              stats={[{ label: 'Diện tích', value: plot.areaHa == null ? '—' : ha(plot.areaHa) }]}
              actions={active ? (
                <button className="btn btn--ghost" onClick={() => go(`/crop-seasons/${active.id}`)}>
                  Vụ đang canh tác: {active.name} <Ico name="arrow" size={14} />
                </button>
              ) : undefined}
            />

            <Section title="Vụ canh tác" description={active ? undefined : 'Chưa có vụ nào đang hoạt động trên thửa này'}>
              {seasons.length === 0 ? (
                <EmptyState icon="seeding" title="Thửa này chưa có vụ canh tác nào" />
              ) : (
                <DataTable
                  rows={seasons}
                  rowKey={(s) => s.id}
                  rowHref={(s) => `/crop-seasons/${s.id}`}
                  rowLabel={(s) => `Mở vụ ${s.name}`}
                  columns={[
                    { label: 'Vụ', render: (s) => <span className="col-key">{s.name}</span> },
                    { label: 'Giống', render: (s) => s.variety ?? '—' },
                    { label: 'Trạng thái', render: (s) => <Badge tone={s.id === active?.id ? 'success' : 'neutral'} dot>{seasonStatus(s.status)}</Badge> },
                    { label: 'Gieo sạ', render: (s) => date(s.plantingDate) },
                    { label: 'Thu hoạch', render: (s) => date(s.harvestDate) },
                  ]}
                />
              )}
            </Section>
          </>
        )
      }}
    </Async>
  )
}
