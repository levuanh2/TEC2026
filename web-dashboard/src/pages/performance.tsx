import { getOrganization, getOrganizationMetrics, getFarmPerformance } from '../api/organizations'
import { perKg } from '../format'
import { Async, EmptyState, MetricCard, PageHead, Section, useAsync, type Tone } from '../ui'
import { FarmPerformanceTable } from '../components/FarmPerformanceTable'

const tone = (ok: boolean): { tone: Tone; label: string } =>
  ok ? { tone: 'success', label: 'Đủ dữ liệu' } : { tone: 'warning', label: 'Thiếu dữ liệu' }

/** "Chưa đủ dữ liệu" on its own never said what to go and record. */
const blockerCopy = (complete: boolean, what: string) =>
  complete ? 'Thiếu sản lượng thu hoạch' : `Thiếu số liệu ${what}`

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
      {/* Three groups, not one row of four look-alike cards. Cost per kg is an
        * accounting figure the cooperative records directly; CO₂e per kg is a
        * methodology result that depends on emission factors. Sitting next to
        * each other in identical tiles they read as two outputs of one
        * calculation, which is how a manager ends up treating a pending factor
        * as a missing receipt. */}
      <Async state={metrics} skeleton="kpis">
        {(m) => (
          <>
            <Section title="Hiệu quả tài nguyên" description="Lượng đầu vào thực tế trên mỗi kg thóc đã thu hoạch">
              <div className="grid grid-2">
                <MetricCard name="Nước / kg thóc" value={m.waterPerKg == null ? blockerCopy(m.completeness.water, 'nước tưới') : perKg(m.waterPerKg, '')} unit="m³/kg" context="Tổng m³ nước / tổng kg thóc" status={tone(m.completeness.water)} />
                <MetricCard name="Phân bón / kg thóc" value={m.fertilizerPerKg == null ? blockerCopy(m.completeness.fertilizer, 'bón phân') : perKg(m.fertilizerPerKg, '')} unit="kg/kg" context="Tổng kg phân / tổng kg thóc" status={tone(m.completeness.fertilizer)} />
              </div>
            </Section>
            <Section title="Chi phí ghi nhận trực tiếp" description="Chi phí do nông hộ nhập cùng hoạt động — không suy ra từ hệ số nào">
              <div className="grid grid-2">
                <MetricCard name="Chi phí / kg thóc" value={m.costPerKg == null ? blockerCopy(m.completeness.cost, 'chi phí đầu vào') : perKg(m.costPerKg, '')} unit="₫/kg" context="Tổng chi phí đầu vào / tổng kg thóc" status={tone(m.completeness.cost)} />
              </div>
            </Section>
            <Section title="Carbon" description="Kết quả tính theo phương pháp MRV — phụ thuộc hệ số phát thải, không phải một khoản chi">
              <div className="grid grid-2">
                <MetricCard name="CO₂e / kg thóc" value={m.co2ePerKg == null ? 'Chưa đủ dữ liệu' : perKg(m.co2ePerKg, '')} unit="kg CO₂e/kg" context={m.co2ePerKg == null ? 'Chưa có kết quả Carbon đã tính' : 'Theo các kết quả Carbon đã lưu'} />
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
