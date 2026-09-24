import { useId, useState } from 'react'
import { Ico } from '../icons'
import { Badge, Link } from '../ui'
import { coverageLine, type Coverage } from '../pages/coverage'

/* One cooperative aggregate, always with its coverage (Round 4.3).
 *
 * A per-kg figure for the whole cooperative is only as good as the seasons
 * behind it, so every aggregate says: the scope, how many seasons carry the
 * data, how many do not — as a control that opens exactly those seasons —
 * and the comparison it is (not) measured against. */
export function AggregateMetric({ name, value, unit, formula, coverage, scope, loadingCoverage, readCount }: {
  name: string
  /** Server figure, formatted; null when the server returned none. */
  value: string | null
  unit: string
  formula: string
  coverage: Coverage | null
  scope: string
  loadingCoverage?: boolean
  readCount?: number
}) {
  const [open, setOpen] = useState(false)
  const listId = useId()
  const c = coverage
  const missing = c?.missing.length ?? 0
  return (
    <article className="agg" data-testid="aggregate-metric">
      <div className="agg__top">
        <h3 className="agg__name">{name}</h3>
        {value != null
          ? <Badge tone="success">Tính trên mọi vụ</Badge>
          : <Badge tone="warning">Chưa tính được cho toàn HTX</Badge>}
      </div>
      <p className={`agg__value${value == null ? ' is-empty' : ''}`}>
        {value != null
          ? <span className="agg__reading"><b>{value}</b>{' '}<small>{unit}</small></span>
          : 'Chưa tính được'}
      </p>
      <p className="agg__coverage" data-testid="aggregate-coverage">
        {c && !loadingCoverage
          ? <>{coverageLine(c)}{value == null && c.total > 0 && <span className="agg__why"> — chỉ số toàn HTX chỉ tính khi mọi vụ đủ dữ liệu.</span>}</>
          : <span className="muted">Đang đọc độ phủ dữ liệu{readCount != null && c ? ` (${readCount}/${c.total} vụ)` : '…'}</span>}
      </p>
      <dl className="agg__facts">
        <div><dt>Phạm vi</dt><dd>{scope}</dd></div>
        <div><dt>Cách tính</dt><dd>{formula}</dd></div>
        <div><dt>Mốc so sánh</dt><dd>Chưa có mốc so sánh</dd></div>
      </dl>
      {c && !loadingCoverage && missing > 0 && (
        <div className="agg__missing">
          <button type="button" className="agg__toggle" aria-expanded={open} aria-controls={listId} onClick={() => setOpen((o) => !o)}>
            <Ico name="warning" size={14} />{missing} vụ thiếu dữ liệu<Ico name="chevron" size={14} />
          </button>
          <ul id={listId} className="agg__list" hidden={!open}>
            {c.missing.map(({ row, reason }) => (
              <li key={row.seasonId}>
                <Link to={`/crop-seasons/${row.seasonId}`}>{row.farmName} · {row.plotName ?? 'Chưa rõ thửa'} · {row.seasonName}</Link>
                <small>{reason}</small>
              </li>
            ))}
          </ul>
        </div>
      )}
    </article>
  )
}
