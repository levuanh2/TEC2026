import { useId, useState } from 'react'
import { Ico } from '../icons'
import { Link } from '../ui'
import { COVERAGE_BASIS, PUBLISH_RULE, coverageSentence, type Coverage } from '../pages/coverage'

/* One cooperative aggregate, always with its coverage (Round 4.3, 4.4).
 *
 * A per-kg figure for the whole cooperative is only as good as what stands
 * behind it, so every aggregate says: the scope, how many farms carry the data
 * (exact, from the farm-performance payload the page already loads), how many
 * do not — as a control that opens exactly those farms — and the comparison it
 * is (not) measured against.
 *
 * Round 4.4: the state is said once. It used to be a warning badge ("Chưa tính
 * được cho toàn HTX"), a placeholder value ("Chưa tính được") and a coverage
 * line ("Dựa trên 0/3 …") — three sentences for one fact, the badge colouring
 * a coverage count as if it were a grade. Now a withheld figure is one sentence
 * that names the cause, and a published one is the number plus its coverage.
 * The facts that are the same for every aggregate — scope, what the coverage
 * counts, when a figure is published, the missing benchmark — are said once
 * for the page by `AggregateBasis`, not four times (at 390px they were a
 * screen and a half of identical lines). */
export function AggregateBasis({ scope }: { scope: string }) {
  return (
    <dl className="agg-basis" data-testid="aggregate-basis" aria-label="Cách đọc các chỉ số">
      <div><dt>Phạm vi</dt><dd>{scope}</dd></div>
      <div><dt>Độ phủ</dt><dd data-testid="aggregate-season-coverage">{COVERAGE_BASIS}</dd></div>
      <div><dt>Điều kiện công bố</dt><dd>{PUBLISH_RULE}</dd></div>
      <div><dt>Mốc so sánh</dt><dd>Chưa có mốc so sánh — không đánh giá cao hay thấp.</dd></div>
    </dl>
  )
}

export function AggregateMetric({ name, value, unit, formula, coverage, loadingCoverage }: {
  name: string
  /** Server figure, formatted; null when the server returned none. */
  value: string | null
  unit: string
  formula: string
  /** null when the farm rows could not be read. */
  coverage: Coverage | null
  loadingCoverage?: boolean
}) {
  const [open, setOpen] = useState(false)
  const listId = useId()
  const c = coverage
  const missing = c?.missing.length ?? 0
  const published = value != null
  return (
    <article className={`agg${published ? '' : ' agg--withheld'}`} data-testid="aggregate-metric">
      <h3 className="agg__name">{name}</h3>
      {published && <p className="agg__value"><span className="agg__reading"><b>{value}</b>{' '}<small>{unit}</small></span></p>}
      <p className="agg__coverage" data-testid="aggregate-coverage">
        {loadingCoverage
          ? <span className="muted">Đang đọc độ phủ dữ liệu…</span>
          : c
            ? coverageSentence(c, published)
            : <>{published ? '' : 'Chưa công bố chỉ số toàn HTX. '}<span className="muted">Không đọc được danh sách nông hộ để tính độ phủ.</span></>}
      </p>
      <dl className="agg__facts">
        <div><dt>Cách tính</dt><dd>{formula}</dd></div>
      </dl>
      {c && !loadingCoverage && missing > 0 && (
        <div className="agg__missing">
          <button type="button" className="agg__toggle" aria-expanded={open} aria-controls={listId} onClick={() => setOpen((o) => !o)}>
            <Ico name="warning" size={14} />{missing} nông hộ thiếu dữ liệu<Ico name="chevron" size={14} />
          </button>
          <ul id={listId} className="agg__list" hidden={!open}>
            {c.missing.map(({ farm, reason }) => (
              <li key={farm.farmId}>
                <Link to={`/farms/${farm.farmId}`}>{farm.farmName}</Link>
                <small>{reason}</small>
              </li>
            ))}
          </ul>
        </div>
      )}
    </article>
  )
}
