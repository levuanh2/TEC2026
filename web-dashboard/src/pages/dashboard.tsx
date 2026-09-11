import {
  getOrganization,
  getOrganizationSummary,
  getFarmPerformance,
  getOrganizationMetrics,
} from '../api/organizations'
import { listMrvCases, getMrvCase } from '../api/mrv'
import { ha, kg, num, perKg } from '../format'
import { mrvProgress } from '../utils/mrvPresentation'
import { Async, EmptyState, Hero, Kpi, Link, LoadingSkeleton, MetricCard, Notice, PageHead, Section, useAsync, type Tone } from '../ui'
import { FarmPerformanceTable } from '../components/FarmPerformanceTable'

const completenessTone = (ok: boolean): { tone: Tone; label: string } =>
  ok ? { tone: 'success', label: 'Đủ dữ liệu' } : { tone: 'warning', label: 'Thiếu dữ liệu' }

/**
 * Each section fetches independently so the fastest content paints first and a
 * slow rollup query only blocks its own card, not the whole page (brief §18).
 */
export function DashboardPage({ organizationId }: { organizationId: string | null }) {
  return (
    <>
      <PageHead
        eyebrow="AgriCarbon"
        title="Tổng quan"
        meta={[<>Hệ thống quản trị hiệu suất tài nguyên &amp; carbon cho lúa gạo</>]}
      />
      {!organizationId ? (
        <EmptyState
          icon="🏢"
          title="Tài khoản chưa gắn với tổ chức"
          body="Không có phạm vi HTX/tổ chức nào để tổng hợp. Liên hệ quản trị viên để được thêm vào một tổ chức."
        />
      ) : (
        <DashboardBody organizationId={organizationId} />
      )}
    </>
  )
}

function DashboardBody({ organizationId }: { organizationId: string }) {
  const core = useAsync(
    () => Promise.all([getOrganization(organizationId), getOrganizationSummary(organizationId)]),
    [organizationId],
  )
  const metrics = useAsync(() => getOrganizationMetrics(organizationId), [organizationId])
  const performance = useAsync(() => getFarmPerformance(organizationId), [organizationId])
  const mrv = useAsync(
    () => listMrvCases().then((c) => (c[0] ? getMrvCase(c[0].caseId) : null)),
    [organizationId],
  )

  return (
    <>
      <Async state={core} skeleton="kpis">
        {([org, summary]) => (
          <>
            <Hero
              eyebrow={org.organizationType === 'cooperative' ? 'Hợp tác xã' : org.organizationType}
              title={org.name}
              meta={[<>{summary.farmCount} nông hộ</>, <>{summary.plotCount} thửa</>, <>{summary.cropSeasonCount} vụ canh tác</>]}
              stats={[
                { label: 'Tổng diện tích', value: ha(summary.totalAreaHa) },
                { label: 'Tổng sản lượng', value: kg(summary.totalYieldKg) },
              ]}
            />

            <div className="kpi-strip" style={{ marginTop: 'var(--gap-lg)' }}>
              <Kpi accent label="Tổng CO₂e" value={summary.totalCo2eKg == null ? 'Chưa đủ dữ liệu' : num(summary.totalCo2eKg)} sub="kg CO₂e toàn vùng" />
              <Kpi accent label="CO₂e / kg thóc" value={summary.co2ePerKg == null ? 'Chưa đủ dữ liệu' : num(summary.co2ePerKg, { max: 3 })} sub="chỉ số phát thải cường độ" />
              <Kpi variant="sub" label="Nông hộ" value={summary.farmCount} />
              <Kpi variant="sub" label="Thửa ruộng" value={summary.plotCount} />
            </div>
          </>
        )}
      </Async>

      <Section title="Hiệu suất vùng / HTX" description="Bốn chỉ số trên mỗi kg thóc — lõi khác biệt của AgriCarbon" cta={{ label: 'Xem hiệu suất', to: '/performance' }}>
        <Async state={metrics} skeleton="kpis">
          {(m) => (
            <>
              <div className="grid grid-4">
                <MetricCard name="Nước / kg" value={m.waterPerKg == null ? 'Chưa đủ dữ liệu' : perKg(m.waterPerKg, '')} unit="m³/kg" context="Tổng m³ nước / tổng kg thóc" status={completenessTone(m.completeness.water)} />
                <MetricCard name="Phân bón / kg" value={m.fertilizerPerKg == null ? 'Chưa đủ dữ liệu' : perKg(m.fertilizerPerKg, '')} unit="kg/kg" context="Tổng kg phân / tổng kg thóc" status={completenessTone(m.completeness.fertilizer)} />
                <MetricCard name="CO₂e / kg" value={m.co2ePerKg == null ? 'Chưa đủ dữ liệu' : perKg(m.co2ePerKg, '')} unit="kg/kg" context="Chờ GWP theo QĐ 4801 / IPCC" status={{ tone: 'warning', label: 'Đang chờ hệ số' }} />
                <MetricCard name="Chi phí / kg" value={m.costPerKg == null ? 'Chưa đủ dữ liệu' : perKg(m.costPerKg, '')} unit="₫/kg" context="Tổng chi phí đầu vào / kg thóc" status={completenessTone(m.completeness.cost)} />
              </div>
              {(!m.completeness.water || !m.completeness.fertilizer || !m.completeness.cost) && (
                <Notice kind="warning">
                  <b>Dữ liệu chưa đầy đủ:</b>{' '}
                  {[!m.completeness.water && 'nước tưới', !m.completeness.fertilizer && 'phân bón', !m.completeness.cost && 'chi phí'].filter(Boolean).join(', ')}{' '}
                  — một hoặc nhiều vụ trong vùng còn thiếu dữ liệu, chỉ số trên mỗi kg tương ứng chưa tính được.
                </Notice>
              )}
            </>
          )}
        </Async>
      </Section>

      <Section title="Hiệu suất theo nông hộ" description="So sánh các hộ trong HTX — nhấp một hàng để xem chi tiết hộ">
        <Async state={performance} skeleton="table">
          {(rows) => <FarmPerformanceTable items={rows} />}
        </Async>
      </Section>

      <div className="split" style={{ marginTop: 30 }}>
        <Async state={core} skeleton="table">
          {([, summary]) => (
            <div className="card card--pad stack">
              <div className="section__head" style={{ marginBottom: 0 }}>
                <h2 style={{ fontSize: 'var(--fs-h2)' }}>Carbon</h2>
              </div>
              <div className="grid grid-2">
                <div>
                  <div className="kpi__label">CO₂e tổng</div>
                  <div className={`kpi__value${summary.totalCo2eKg == null ? ' is-empty' : ''}`}>{summary.totalCo2eKg == null ? 'Chưa đủ dữ liệu' : num(summary.totalCo2eKg)}</div>
                </div>
                <div>
                  <div className="kpi__label">CO₂e / kg</div>
                  <div className={`kpi__value${summary.co2ePerKg == null ? ' is-empty' : ''}`}>{summary.co2ePerKg == null ? 'Chưa đủ dữ liệu' : num(summary.co2ePerKg, { max: 3 })}</div>
                </div>
              </div>
              <p className="muted" style={{ fontSize: 'var(--fs-sm)' }}>
                Số CO₂e cấp vùng chỉ hiện khi bộ hệ số phát thải (GWP, hệ số nhiên liệu) được xác minh. Kết quả chi tiết
                xem trong từng vụ canh tác.
              </p>
            </div>
          )}
        </Async>

        <div className="card card--pad stack">
          <div className="section__head" style={{ marginBottom: 0 }}>
            <h2 style={{ fontSize: 'var(--fs-h2)' }}>MRV</h2>
          </div>
          {mrv.loading ? (
            <LoadingSkeleton variant="table" />
          ) : mrv.data ? (
            <MrvPanel mrv={mrv.data} />
          ) : (
            <p className="muted" style={{ fontSize: 'var(--fs-sm)' }}>Chưa có hồ sơ MRV nào trong phạm vi.</p>
          )}
        </div>
      </div>
    </>
  )
}

function MrvPanel({ mrv }: { mrv: NonNullable<Awaited<ReturnType<typeof getMrvCase>>> }) {
  const p = mrvProgress(mrv.steps)
  return (
    <>
      <div className="progress-head">
        <b>
          {p.done}/{p.total}
        </b>
        <span>bước hoàn thành</span>
      </div>
      <div className="progress">
        <div className="progress__fill" style={{ width: `${p.total ? (p.done / p.total) * 100 : 0}%` }} />
      </div>
      <p className="muted" style={{ fontSize: 'var(--fs-sm)' }}>
        {mrv.name} · {p.inProgress} bước đang thực hiện · {mrv.evidenceCount} minh chứng
      </p>
      <Link to="/mrv" className="section__cta">
        Xem hồ sơ MRV →
      </Link>
    </>
  )
}
