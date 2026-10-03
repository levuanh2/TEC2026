import {
  getOrganization,
  getOrganizationSummary,
  getFarmPerformance,
  getOrganizationMetrics,
} from '../api/organizations'
import { listMrvCases, getMrvCase } from '../api/mrv'
import { ha, kg, num, perKg, vndPerKg } from '../format'
import { mrvProgress } from '../utils/mrvPresentation'
import { Async, EmptyState, Hero, Link, LoadingSkeleton, MetricCard, PageHead, Section, useAsync, type Tone } from '../ui'
import { Ico, type IconName } from '../icons'
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
          icon="organization"
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
      {/* A - Scope. Who this organisation is and how big it is: the one place
        * the counts are stated. */}
      <Async state={core} skeleton="kpis">
        {([org, summary]) => (
          <Hero
            eyebrow={org.organizationType === 'cooperative' ? 'Hợp tác xã' : org.organizationType}
            title={org.name}
            meta={[<>{summary.farmCount} nông hộ</>, <>{summary.plotCount} thửa</>, <>{summary.cropSeasonCount} vụ canh tác</>]}
            stats={[
              { label: 'Tổng diện tích', value: ha(summary.totalAreaHa) },
              { label: 'Tổng sản lượng', value: kg(summary.totalYieldKg) },
            ]}
          />
        )}
      </Async>

      {/* B - Attention. A manager opens this page to find out what is wrong, not
        * to read a KPI wall, so the exceptions come before the figures. Every
        * line is a condition the API already reports (a completeness flag, a
        * missing factor set, an unfinished MRV step). Nothing here is a score,
        * a threshold or a trend - those would have to be invented. */}
      <AttentionSection metrics={metrics.data} mrv={mrv.data ?? undefined} loading={metrics.loading} />

      {/* D - Who. Comparison before explanation: the manager picks the farm that
        * looks wrong, then asks which metric drove it. */}
      <Section title="Hiệu suất theo nông hộ" description="So sánh các hộ trong HTX — nhấp một hàng để xem chi tiết hộ">
        <Async state={performance} skeleton="table">
          {(rows) => <FarmPerformanceTable items={rows} />}
        </Async>
      </Section>

      {/* E - Which metric. The four per-kg readings that explain the comparison
        * above. The completeness caveat now lives in Attention, not here. */}
      <Section title="Hiệu suất vùng / HTX" description="Bốn chỉ số trên mỗi kg thóc — lõi khác biệt của AgriCarbon" cta={{ label: 'Xem hiệu suất', to: '/performance' }}>
        <Async state={metrics} skeleton="kpis">
          {(m) => (
            <div className="grid grid-4">
              <MetricCard name="Nước / kg" value={m.waterPerKg == null ? 'Chưa đủ dữ liệu' : perKg(m.waterPerKg, '')} unit="m³/kg" context="Tổng m³ nước / tổng kg thóc" status={completenessTone(m.completeness.water)} />
              <MetricCard name="Phân bón / kg" value={m.fertilizerPerKg == null ? 'Chưa đủ dữ liệu' : perKg(m.fertilizerPerKg, '')} unit="kg/kg" context="Tổng kg phân / tổng kg thóc" status={completenessTone(m.completeness.fertilizer)} />
              <MetricCard name="CO₂e / kg" value={m.co2ePerKg == null ? 'Chưa đủ dữ liệu' : perKg(m.co2ePerKg, '')} unit="kg/kg" context={m.co2ePerKg == null ? 'Chưa có kết quả Carbon đã tính' : 'Theo các kết quả Carbon đã lưu'} />
              <MetricCard name="Chi phí / kg" value={m.costPerKg == null ? 'Chưa đủ dữ liệu' : vndPerKg(m.costPerKg)} unit="₫/kg" context="Tổng chi phí đầu vào / kg thóc" status={completenessTone(m.completeness.cost)} />
            </div>
          )}
        </Async>
      </Section>

      {/* F - Readiness. The only place the organisation-level CO2e figures are
        * stated. They used to appear here AND in a KPI strip at the top: the
        * same number twice, answering the same question. Here they arrive with
        * the reason they are empty, which is what makes them worth showing. */}
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
            <MrvPanel mrv={mrv.data ?? undefined} />
          ) : (
            <p className="muted" style={{ fontSize: 'var(--fs-sm)' }}>Chưa có hồ sơ MRV nào trong phạm vi.</p>
          )}
        </div>
      </div>
    </>
  )
}

type OrgMetrics = Awaited<ReturnType<typeof getOrganizationMetrics>>
type MrvCase = NonNullable<Awaited<ReturnType<typeof getMrvCase>>>
type AttentionItem = { icon: IconName; title: string; detail: string; to?: string; label?: string }

/** One ruled row per real, already-known condition. Never a score, a threshold
 *  or a trend: this page has no dataset that would support one honestly. */
function AttentionSection({ metrics, mrv, loading }: { metrics?: OrgMetrics; mrv?: MrvCase; loading: boolean }) {
  const items: AttentionItem[] = []

  if (metrics) {
    const missing = [
      !metrics.completeness.water && 'nước tưới',
      !metrics.completeness.fertilizer && 'phân bón',
      !metrics.completeness.cost && 'chi phí',
    ].filter(Boolean) as string[]
    if (missing.length) {
      items.push({
        icon: 'warning',
        title: `Thiếu dữ liệu: ${missing.join(', ')}`,
        detail: 'Một hoặc nhiều vụ trong vùng chưa ghi đủ, nên chỉ số trên mỗi kg tương ứng chưa tính được.',
        to: '/performance',
        label: 'Xem hiệu suất',
      })
    }
    if (metrics.co2ePerKg == null) {
      items.push({
        icon: 'carbon',
        title: 'Chưa công bố CO₂e/kg cấp HTX',
        detail: 'Chỉ số toàn HTX chỉ công bố khi mọi vụ trong phạm vi có kết quả Carbon vận hành và sản lượng. Xem từng vụ ở mục Carbon.',
      })
    }
  }

  if (mrv) {
    const p = mrvProgress(mrv.steps)
    if (p.done < p.total) {
      items.push({
        icon: 'mrv',
        title: `Hồ sơ MRV còn ${p.total - p.done}/${p.total} bước chưa hoàn thành`,
        detail: `${mrv.name} · ${p.inProgress} bước đang thực hiện · ${mrv.evidenceCount} minh chứng đã nộp.`,
        to: '/mrv',
        label: 'Xem hồ sơ',
      })
    }
  }

  if (loading && items.length === 0) return null

  return (
    <Section title="Cần chú ý" description="Chỉ từ trạng thái dữ liệu thực tế — không có ngưỡng hay điểm số tự đặt">
      {items.length === 0 ? (
        <p className="muted" style={{ fontSize: 'var(--fs-sm)', paddingTop: 12 }}>
          Không có vấn đề dữ liệu nào trong phạm vi hiện tại.
        </p>
      ) : (
        <ul className="attn">
          {items.map((it) => (
            <li key={it.title} className="attn__item">
              <Ico name={it.icon} size={16} />
              <div>
                <b>{it.title}</b>
                <p>{it.detail}</p>
              </div>
              {it.to && (
                <Link to={it.to} className="section__cta">
                  {it.label}
                </Link>
              )}
            </li>
          ))}
        </ul>
      )}
    </Section>
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
        Xem hồ sơ MRV <Ico name="arrow" size={14} />
      </Link>
    </>
  )
}
