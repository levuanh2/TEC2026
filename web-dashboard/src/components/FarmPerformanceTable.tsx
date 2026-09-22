import type { FarmPerformance } from '../api/organizations'
import { ha, kg, num, vnd } from '../format'
import { DataStatusBadge, EmptyState, Link } from '../ui'

/** Why one cell is empty, in the words of the thing that has to be recorded.
 *
 * Every blank cell used to read "Chưa đủ dữ liệu", which is true and useless:
 * it never said whether the farm was missing its harvest, its irrigation, its
 * fertiliser, its costs, or an emission factor nobody at the cooperative can
 * supply. Yield is checked first because it is the denominator of all four
 * per-kg metrics — without it, no column can resolve, and pointing at water
 * would send the reader after the wrong record. */
function blocker(row: FarmPerformance, metric: 'water' | 'fertilizer' | 'carbon' | 'cost'): string {
  if (row.yieldKg == null) return 'Thiếu sản lượng thu hoạch'
  switch (metric) {
    case 'water': return 'Thiếu số liệu tưới nước'
    case 'fertilizer': return 'Thiếu số liệu bón phân'
    case 'cost': return 'Thiếu chi phí đầu vào'
    case 'carbon': return 'Chờ hệ số phát thải'
  }
}

const cell = (row: FarmPerformance, metric: 'water' | 'fertilizer' | 'carbon' | 'cost', v: number | null | undefined, fmt: (n: number) => string) =>
  v == null ? <span className="cell-empty" title={blocker(row, metric)}>{blocker(row, metric)}</span> : fmt(v)

/**
 * Ranked farm comparison for a HTX (brief §5 "FARM PERFORMANCE"). The farm name
 * leads and is a real link — the row used to be a `<tr onClick>`, which no
 * keyboard could reach. Resource efficiency, cost and Carbon are separated by
 * a group header row, because cost per kg is an accounting figure and CO₂e per
 * kg is a methodology result; side by side and identically styled they read as
 * two halves of one formula.
 */
export function FarmPerformanceTable({ items }: { items: FarmPerformance[] }) {
  if (items.length === 0) {
    return <EmptyState icon="straw" title="Chưa có dữ liệu hiệu suất nông hộ" body="Khi các hộ trong HTX ghi nhận hoạt động và thu hoạch, bảng so sánh sẽ xuất hiện ở đây." />
  }
  return (
    <div className="table-wrap">
      <table className="data perf-table">
        <thead>
          <tr className="colgroups">
            <th colSpan={3} aria-hidden="true" />
            <th colSpan={2} scope="colgroup" className="colgroup">Hiệu quả tài nguyên</th>
            <th scope="colgroup" className="colgroup">Chi phí ghi nhận</th>
            <th scope="colgroup" className="colgroup colgroup--carbon">Carbon</th>
            <th aria-hidden="true" />
          </tr>
          <tr>
            <th scope="col">Nông hộ</th>
            <th scope="col" className="num">Diện tích</th>
            <th scope="col" className="num">Sản lượng</th>
            <th scope="col" className="num">Nước / kg thóc</th>
            <th scope="col" className="num">Phân / kg thóc</th>
            <th scope="col" className="num">Chi phí / kg thóc</th>
            <th scope="col" className="num col-hi">CO₂e / kg thóc</th>
            <th scope="col">Trạng thái</th>
          </tr>
        </thead>
        <tbody>
          {items.map((f) => (
            <tr key={f.farmId} className="has-rowlink">
              <td data-label="Nông hộ" className="col-key">
                <Link to={`/farms/${f.farmId}`} className="rowlink" aria-label={`Mở hồ sơ nông hộ ${f.farmName}`}>{f.farmName}</Link>
              </td>
              <td data-label="Diện tích" className="num">{f.areaHa == null ? <span className="cell-empty">—</span> : ha(f.areaHa)}</td>
              <td data-label="Sản lượng" className="num">{f.yieldKg == null ? <span className="cell-empty">Chưa ghi thu hoạch</span> : kg(f.yieldKg)}</td>
              <td data-label="Nước / kg thóc" className="num">{cell(f, 'water', f.waterPerKg, (n) => num(n, { max: 3 }))}</td>
              <td data-label="Phân / kg thóc" className="num">{cell(f, 'fertilizer', f.fertilizerPerKg, (n) => num(n, { max: 3 }))}</td>
              <td data-label="Chi phí / kg thóc" className="num">{cell(f, 'cost', f.costPerKg, (n) => vnd(n))}</td>
              <td data-label="CO₂e / kg thóc" className="num col-hi">{cell(f, 'carbon', f.co2ePerKg, (n) => num(n, { max: 3 }))}</td>
              <td data-label="Trạng thái">
                <DataStatusBadge status={f.dataStatus} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
