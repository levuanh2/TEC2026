import { useId, useState, type ReactNode } from 'react'
import { Link } from '../ui'
import type { SeasonContext, ActivityMutations } from './ActivityForms'
import { Ico } from './icons'
import type { MetricDetail, Reading, YieldContext } from './metricsView'

/* One pattern for every metric row on Performance (Round 4.3): name, the
 * reading a farmer acts on, the methodology units, a sentence of meaning, what
 * it was computed from, the data state in words, the comparison state, one
 * contextual action, and the method behind a closed disclosure.
 *
 * Rows, not cards: four metrics in four boxed tiles was a wall of equal
 * weights. Grouped panels with ruled rows let the value lead and the words
 * follow, and the page reads top to bottom. */

/** A value and its unit never part at a line break. */
export function ReadingText({ r, className = '' }: { r: Reading; className?: string }) {
  return <span className={`fw-reading ${className}`}><b>{r.value}</b>{' '}<span>{r.unit}</span></span>
}

/** A disclosure whose state a screen reader can hear (`aria-expanded`). */
export function Disclosure({ label, children }: { label: string; children: ReactNode }) {
  const [open, setOpen] = useState(false)
  const id = useId()
  return (
    <div className="fw-mdisc">
      <button type="button" className="fw-mdisc__btn" aria-expanded={open} aria-controls={id} onClick={() => setOpen((o) => !o)}>
        <Ico name="method" />{label}<Ico name="chevron" className="fw-mdisc__chev" />
      </button>
      <div id={id} className="fw-mdisc__body" hidden={!open}>{children}</div>
    </div>
  )
}

export function MetricRow({ d, season, mutations }: { d: MetricDetail; season: SeasonContext | null; mutations?: ActivityMutations }) {
  const headId = `fw-mrow-${d.key}`
  const act = d.action
  return (
    <article className={`fw-mrow fw-mrow--${d.group}`} aria-labelledby={headId} data-metric={d.key}>
      <div className="fw-mrow__main">
        <h4 id={headId} className="fw-mrow__name"><Ico name={d.icon} />{d.name}</h4>
        {d.primary ? (
          <p className="fw-mrow__value"><ReadingText r={d.primary} /></p>
        ) : (
          // The class the no-fabricated-zero checks look for: a missing value
          // is a sentence, never 0.
          <div className="fw-metric__empty fw-mrow__empty">
            <b>Chưa đủ dữ liệu</b>
            {d.missing && <p>{d.missing}</p>}
          </div>
        )}
        {d.secondary.length > 0 && (
          <ul className="fw-mrow__secondary" aria-label="Đơn vị khác và số liệu gốc">
            {d.secondary.map((r) => <li key={r.unit}><ReadingText r={r} /></li>)}
          </ul>
        )}
      </div>
      <div className="fw-mrow__words">
        <p className={`fw-mrow__status ${d.status.ok ? 'is-ok' : 'is-missing'}`}>
          <Ico name={d.status.ok ? 'check' : 'warning'} />{d.status.text}
        </p>
        <p className="fw-mrow__meaning">{d.meaning}</p>
        {d.basis && <p className="fw-mrow__basis">{d.basis}</p>}
        <p className="fw-mrow__compare">{d.comparison}</p>
        {act && (
          <p className="fw-mrow__act">
            {act.to ? (
              <Link to={act.to} className="fw-link">{act.label}<Ico name="arrow" /></Link>
            ) : act.create && season && mutations ? (
              <button type="button" className="fw-btn fw-btn--soft fw-btn--sm" onClick={() => mutations.openCreate(act.create!, season)}>{act.label}</button>
            ) : null}
          </p>
        )}
        <Disclosure label="Cách tính và dữ liệu sử dụng">
          <ul className="fw-mrow__method">{d.method.map((line) => <li key={line}>{line}</li>)}</ul>
        </Disclosure>
      </div>
    </article>
  )
}

/** "Bối cảnh vụ mùa": what the season produced, on how much land. Context
 *  only — yield per hectare is not an input to anything else on the page. */
export function YieldContextPanel({ y, seasonName, place, harvestAction }: {
  y: YieldContext
  seasonName: string
  place: string
  harvestAction?: ReactNode
}) {
  return (
    <section className="fw-yield" aria-labelledby="fw-yield-title">
      <h3 id="fw-yield-title" className="fw-mgroup__title">Bối cảnh vụ mùa</h3>
      <dl className="fw-yield__facts">
        <div><dt>Vụ đang xem</dt><dd><b>{seasonName}</b>{place && <small>{place}</small>}</dd></div>
        <div><dt>Sản lượng thóc đã ghi</dt><dd>{y.yieldKg != null ? <ReadingText r={{ value: new Intl.NumberFormat('vi-VN').format(y.yieldKg), unit: 'kg' }} /> : <span className="is-empty">Chưa ghi thu hoạch</span>}</dd></div>
        <div><dt>{y.areaLabel ?? 'Diện tích'}</dt><dd>{y.areaHa != null ? <ReadingText r={{ value: new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 2 }).format(y.areaHa), unit: 'ha' }} /> : <span className="is-empty">Chưa có diện tích</span>}</dd></div>
        <div><dt>Năng suất</dt><dd>{y.tonnesPerHa != null ? <ReadingText r={{ value: y.tonnesPerHa, unit: 'tấn / ha' }} /> : <span className="is-empty">Chưa tính được</span>}</dd></div>
      </dl>
      {y.missing && <p className="fw-yield__missing"><Ico name="info" />{y.missing}{harvestAction}</p>}
      <p className="fw-yield__note">Năng suất chỉ để bạn nắm bối cảnh của vụ; không phải đầu vào tính Carbon.</p>
    </section>
  )
}
