import { getOrganization, getOrganizationMetrics, getFarmPerformance } from '../api/organizations'
import { perKg } from '../format'
import { Async, EmptyState, PageHead, Section, useAsync } from '../ui'
import { AggregateMetric } from '../components/AggregateMetric'
import { FarmPerformanceTable } from '../components/FarmPerformanceTable'
import { coverageOf, useSeasonCoverage } from './coverage'

export function PerformancePage({ organizationId }: { organizationId: string | null }) {
  return (
    <>
      <PageHead
        eyebrow="Hiệu suất"
        title="Hiệu suất vùng"
        meta={[<>Chỉ số trên mỗi kg thóc của toàn HTX, kèm số vụ đứng sau từng con số</>]}
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
  const seasons = useSeasonCoverage(organizationId)
  const cov = (key: 'water' | 'fertilizer' | 'cost' | 'carbon') =>
    seasons.error ? null : coverageOf(seasons.rows, key)
  const scope = `${org.data?.name ?? 'HTX hiện tại'} · ${seasons.loading && !seasons.rows.length ? 'đang đếm vụ' : `${seasons.rows.length} vụ`}`
  const shared = { scope, loadingCoverage: seasons.loading, readCount: seasons.read }

  return (
    <>
      {seasons.error && <p className="ops-error" role="alert">Không đọc được danh sách vụ để tính độ phủ: {seasons.error}</p>}
      {/* Three groups, not one row of four look-alike cards. Cost per kg is an
        * accounting figure the cooperative records directly; CO₂e per kg is a
        * methodology result that depends on emission factors. Sitting next to
        * each other in identical tiles they read as two outputs of one
        * calculation. Every figure now carries the seasons behind it. */}
      <Async state={metrics} skeleton="kpis">
        {(m) => (
          <>
            <Section title="Hiệu quả tài nguyên" description="Lượng đầu vào thực tế trên mỗi kg thóc đã thu hoạch">
              <div className="grid grid-2">
                <AggregateMetric name="Nước / kg thóc" value={m.waterPerKg == null ? null : perKg(m.waterPerKg, '')} unit="m³/kg" formula="Tổng m³ nước ÷ tổng kg thóc của mọi vụ" coverage={cov('water')} {...shared} />
                <AggregateMetric name="Phân bón / kg thóc" value={m.fertilizerPerKg == null ? null : perKg(m.fertilizerPerKg, '')} unit="kg/kg" formula="Tổng kg phân (khối lượng sản phẩm) ÷ tổng kg thóc" coverage={cov('fertilizer')} {...shared} />
              </div>
            </Section>
            <Section title="Chi phí trực tiếp đã ghi" description="Chi phí do nông hộ nhập cùng hoạt động — không phải tổng chi phí sản xuất, không suy ra từ hệ số nào">
              <div className="grid grid-2">
                <AggregateMetric name="Chi phí / kg thóc" value={m.costPerKg == null ? null : perKg(m.costPerKg, '')} unit="₫/kg" formula="Tổng chi phí đã ghi ÷ tổng kg thóc" coverage={cov('cost')} {...shared} />
              </div>
            </Section>
            <Section title="Carbon" description="Kết quả tính theo phương pháp MRV — phụ thuộc hệ số phát thải, không phải một khoản chi">
              <div className="grid grid-2">
                <AggregateMetric name="CO₂e / kg thóc" value={m.co2ePerKg == null ? null : perKg(m.co2ePerKg, '')} unit="kg CO₂e/kg" formula="Tổng CO₂e các kết quả đã lưu ÷ tổng kg thóc" coverage={cov('carbon')} {...shared} />
              </div>
            </Section>
          </>
        )}
      </Async>

      <Section title="So sánh nông hộ" description={org.data ? `${org.data.name} — mở một hàng để xem hồ sơ nông hộ` : 'Mở một hàng để xem hồ sơ nông hộ'}>
        <Async state={performance} skeleton="table">
          {(rows) => <FarmPerformanceTable items={rows} />}
        </Async>
      </Section>
    </>
  )
}
