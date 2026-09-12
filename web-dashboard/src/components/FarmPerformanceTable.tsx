import type { FarmPerformance } from '../api/organizations'
import { ha, kg, num, vnd } from '../format'
import { DataStatusBadge, EmptyState, go } from '../ui'

const cell = (v: number | null | undefined, fmt: (n: number) => string) =>
  v == null ? <span className="cell-empty">Chưa đủ dữ liệu</span> : fmt(v)

/**
 * Ranked farm comparison for a HTX (brief §5 "FARM PERFORMANCE"). The farm name
 * leads, CO₂e/kg is the highlighted column, numerics are tabular and
 * right-aligned, and a row opens that farm. Not a database dump.
 */
export function FarmPerformanceTable({ items }: { items: FarmPerformance[] }) {
  if (items.length === 0) {
    return <EmptyState icon="straw" title="Chưa có dữ liệu hiệu suất nông hộ" body="Khi các hộ trong HTX ghi nhận hoạt động và thu hoạch, bảng so sánh sẽ xuất hiện ở đây." />
  }
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            <th>Nông hộ</th>
            <th className="num">Diện tích</th>
            <th className="num">Sản lượng</th>
            <th className="num">Nước/kg</th>
            <th className="num">Phân/kg</th>
            <th className="num col-hi">CO₂e/kg</th>
            <th className="num">Chi phí/kg</th>
            <th>Trạng thái</th>
          </tr>
        </thead>
        <tbody>
          {items.map((f) => (
            <tr key={f.farmId} className="is-clickable" onClick={() => go(`/farms/${f.farmId}`)}>
              <td className="col-key">{f.farmName}</td>
              <td className="num">{cell(f.areaHa, (n) => ha(n))}</td>
              <td className="num">{cell(f.yieldKg, (n) => kg(n))}</td>
              <td className="num">{cell(f.waterPerKg, (n) => num(n, { max: 3 }))}</td>
              <td className="num">{cell(f.fertilizerPerKg, (n) => num(n, { max: 3 }))}</td>
              <td className="num col-hi">{cell(f.co2ePerKg, (n) => num(n, { max: 3 }))}</td>
              <td className="num">{cell(f.costPerKg, (n) => vnd(n))}</td>
              <td>
                <DataStatusBadge status={f.dataStatus} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
