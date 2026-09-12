import { getOrganization, getOrganizationMetrics, getFarmPerformance } from '../api/organizations'
import { perKg } from '../format'
import { Async, EmptyState, MetricCard, PageHead, Section, useAsync, type Tone } from '../ui'
import { FarmPerformanceTable } from '../components/FarmPerformanceTable'

const tone = (ok: boolean): { tone: Tone; label: string } =>
  ok ? { tone: 'success', label: 'Đủ dữ liệu' } : { tone: 'warning', label: 'Thiếu dữ liệu' }

export function PerformancePage({ organizationId }: { organizationId: string | null }) {
  return (
    <>
      <PageHead
        eyebrow="Hiệu suất"
        title="Hiệu suất vùng"
        meta={[<>Bốn chỉ số trên mỗi kg thóc, tổng hợp toàn HTX và so sánh giữa các nông hộ</>]}
      />
      {!organizationId ? (
        <EmptyState icon="analytics" title="Tài khoản chưa gắn với tổ chức" body="Cần một phạm vi HTX để tổng hợp hiệu suất vùng." />
      ) : (
        <PerformanceBody organizationId={organizationId} />
      )}
    </>
  )
}

function PerformanceBody({ organizationId }: { organizationId: string }) {
  const org = useAsync(() => getOrganization(organizationId), [organizationId])
  const metrics = useAsync(() => getOrganizationMetrics(organizationId), [organizationId])
  const performance = useAsync(() => getFarmPerformance(organizationId), [organizationId])

  return (
    <>
      <Async state={metrics} skeleton="kpis">
        {(m) => (
          <div className="grid grid-4">
            <MetricCard name="Nước / kg" value={m.waterPerKg == null ? 'Chưa đủ dữ liệu' : perKg(m.waterPerKg, '')} unit="m³/kg" context="Tổng m³ nước / tổng kg thóc" status={tone(m.completeness.water)} />
            <MetricCard name="Phân bón / kg" value={m.fertilizerPerKg == null ? 'Chưa đủ dữ liệu' : perKg(m.fertilizerPerKg, '')} unit="kg/kg" context="Tổng kg phân / tổng kg thóc" status={tone(m.completeness.fertilizer)} />
            <MetricCard name="Carbon / kg" value={m.co2ePerKg == null ? 'Chưa đủ dữ liệu' : perKg(m.co2ePerKg, '')} unit="kg CO₂e/kg" context="Chờ GWP theo QĐ 4801 / IPCC Tier 2" status={{ tone: 'warning', label: 'Đang chờ hệ số' }} />
            <MetricCard name="Chi phí / kg" value={m.costPerKg == null ? 'Chưa đủ dữ liệu' : perKg(m.costPerKg, '')} unit="₫/kg" context="Tổng chi phí đầu vào / tổng kg thóc" status={tone(m.completeness.cost)} />
          </div>
        )}
      </Async>

      <Section title="So sánh nông hộ" description={org.data ? `${org.data.name} — nhấp một hàng để mở hồ sơ nông hộ` : 'Nhấp một hàng để mở hồ sơ nông hộ'}>
        <Async state={performance} skeleton="table">
          {(rows) => <FarmPerformanceTable items={rows} />}
        </Async>
      </Section>
    </>
  )
}
