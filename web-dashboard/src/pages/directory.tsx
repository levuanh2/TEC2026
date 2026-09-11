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
import {
  Async,
  Badge,
  Breadcrumb,
  EmptyState,
  Kpi,
  MetricCard,
  PageHead,
  Section,
  useAsync,
  go,
} from '../ui'
import { FarmPerformanceTable } from '../components/FarmPerformanceTable'

/* ============================================================ Organizations */

export function OrganizationsPage() {
  const state = useAsync(() => listOrganizations(), [])
  return (
    <>
      <PageHead eyebrow="Quản lý" title="Tổ chức / HTX" meta={[<>Phạm vi quản trị — chọn một tổ chức để xem các nông hộ trực thuộc</>]} />
      <Async state={state} isEmpty={(o) => o.length === 0} empty={<EmptyState icon="⬡" title="Chưa có tổ chức nào trong phạm vi truy cập" />}>
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
          <div className="card card--pad" style={{ marginTop: 12 }}>
            <div className="section__head" style={{ marginBottom: 12 }}>
              <div>
                <h2 style={{ fontSize: 'var(--fs-h2)' }}>{org.name}</h2>
                <p className="muted" style={{ fontSize: 'var(--fs-sm)' }}>
                  {org.code} · {org.organizationType === 'cooperative' ? 'Hợp tác xã' : org.organizationType}
                </p>
              </div>
              <Badge tone={org.isActive ? 'success' : 'neutral'} dot>
                {org.isActive ? 'Đang hoạt động' : 'Ngừng hoạt động'}
              </Badge>
            </div>
            <div className="page-head__meta" style={{ marginTop: 0 }}>
              <span>📍 {place(org.commune, org.district, org.province)}</span>
              <span>
                <b>{summary.farmCount}</b> nông hộ
              </span>
              <span>
                <b>{summary.plotCount}</b> thửa
              </span>
              <span>
                <b>{summary.cropSeasonCount}</b> vụ · <b>{ha(summary.totalAreaHa)}</b>
              </span>
            </div>
          </div>
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
  return (
    <>
      <PageHead eyebrow="Quản lý" title="Nông hộ" meta={[<>Tất cả nông hộ trong phạm vi truy cập của bạn</>]} />
      <Async state={state} isEmpty={(f) => f.length === 0} empty={<EmptyState icon="⌂" title="Chưa có nông hộ nào" />}>
        {(farms) => (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Mã hộ</th>
                  <th>Chủ hộ</th>
                  <th>Địa bàn</th>
                  <th className="num">Thửa</th>
                  <th className="num">Diện tích</th>
                </tr>
              </thead>
              <tbody>
                {farms.map((f) => (
                  <tr key={f.id} className="is-clickable" onClick={() => go(`/farms/${f.id}`)}>
                    <td className="col-key">{f.code}</td>
                    <td>{f.name}</td>
                    <td>{place(f.commune, f.district, f.province)}</td>
                    <td className="num">{f.plotCount}</td>
                    <td className="num">{f.areaHa == null ? <span className="cell-empty">—</span> : ha(f.areaHa)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
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
    <Async state={head} isEmpty={(f) => !f} empty={<EmptyState icon="🔍" title="Không tìm thấy nông hộ" />}>
      {(farm) => {
        if (!farm) return <EmptyState icon="🔍" title="Không tìm thấy nông hộ" />
        return (
          <>
            <Breadcrumb items={[{ label: 'Nông hộ', to: '/farms' }, { label: farm.name }]} />
            <PageHead
              eyebrow="Nông hộ"
              title={farm.name}
              meta={[
                <>
                  Mã hộ <b>{farm.code}</b>
                </>,
                <>📍 {place(farm.commune, farm.district, farm.province)}</>,
                <>
                  <b>{farm.plotCount}</b> thửa ruộng
                </>,
              ]}
            />

            <div className="grid grid-3">
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
              <Async state={plots} skeleton="table" isEmpty={(r) => r.length === 0} empty={<EmptyState icon="🗺️" title="Nông hộ chưa khai báo thửa ruộng" />}>
                {(rows) => (
                  <div className="table-wrap">
                    <table className="data">
                      <thead>
                        <tr>
                          <th>Mã thửa</th>
                          <th>Tên</th>
                          <th className="num">Diện tích</th>
                          <th>Vị trí</th>
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map((p) => (
                          <tr key={p.id} className="is-clickable" onClick={() => go(`/plots/${p.id}`)}>
                            <td className="col-key">{p.code}</td>
                            <td>{p.name}</td>
                            <td className="num">{p.areaHa == null ? <span className="cell-empty">—</span> : ha(p.areaHa)}</td>
                            <td>{p.location ?? '—'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </Async>
            </Section>

            <Section title="Vụ canh tác" description="Toàn bộ vụ trên các thửa của nông hộ này">
              <Async state={seasons} skeleton="table" isEmpty={(r) => r.length === 0} empty={<EmptyState icon="🌱" title="Nông hộ chưa có vụ canh tác nào" />}>
                {(rows) => (
                  <div className="table-wrap">
                    <table className="data">
                      <thead>
                        <tr>
                          <th>Vụ</th>
                          <th>Giống</th>
                          <th>Trạng thái</th>
                          <th>Gieo sạ</th>
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map((s) => (
                          <tr key={s.id} className="is-clickable" onClick={() => go(`/crop-seasons/${s.id}`)}>
                            <td className="col-key">{s.name}</td>
                            <td>{s.variety ?? '—'}</td>
                            <td>{s.status ?? '—'}</td>
                            <td>{date(s.plantingDate)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
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
        if (!plot) return <EmptyState icon="🔍" title="Không tìm thấy thửa ruộng" />
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
            <PageHead
              eyebrow="Thửa ruộng"
              title={plot.name}
              meta={[
                <>
                  Mã thửa <b>{plot.code}</b>
                </>,
                <>
                  Diện tích <b>{plot.areaHa == null ? '—' : ha(plot.areaHa)}</b>
                </>,
                <>📍 {plot.location ?? '—'}</>,
              ]}
            />

            {active && (
              <div className="card card--pad" style={{ borderLeft: '3px solid var(--brand)' }}>
                <span className="kpi__label">Vụ đang canh tác</span>
                <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginTop: 6 }}>
                  <strong style={{ fontSize: 'var(--fs-h3)' }}>{active.name}</strong>
                  <Badge tone="success" dot>
                    {active.status}
                  </Badge>
                  <button className="btn btn--link" onClick={() => go(`/crop-seasons/${active.id}`)}>
                    Mở vụ canh tác →
                  </button>
                </div>
              </div>
            )}

            <Section title="Vụ canh tác">
              {seasons.length === 0 ? (
                <EmptyState icon="🌱" title="Thửa này chưa có vụ canh tác nào" />
              ) : (
                <div className="table-wrap">
                  <table className="data">
                    <thead>
                      <tr>
                        <th>Vụ</th>
                        <th>Giống</th>
                        <th>Trạng thái</th>
                        <th>Gieo sạ</th>
                        <th>Thu hoạch</th>
                      </tr>
                    </thead>
                    <tbody>
                      {seasons.map((s) => (
                        <tr key={s.id} className="is-clickable" onClick={() => go(`/crop-seasons/${s.id}`)}>
                          <td className="col-key">{s.name}</td>
                          <td>{s.variety ?? '—'}</td>
                          <td>{s.status ?? '—'}</td>
                          <td>{date(s.plantingDate)}</td>
                          <td>{date(s.harvestDate)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Section>
          </>
        )
      }}
    </Async>
  )
}
