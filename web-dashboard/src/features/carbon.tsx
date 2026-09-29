import { Ico } from '../icons'
import { useState } from 'react'
import { ApiError } from '../api/client'
import { calculateCarbon, getCarbon, type CarbonResult, type Scenario } from '../api/carbon'
import { num, perKg, dateTime, co2eKg } from '../format'
import { Async, Badge, Link, Notice, Section, Segmented, useAsync, EmptyState } from '../ui'
import { useCarbonView } from '../carbon/useCarbonView'
import { carbonSourceLabel, cleanWarning, gasLabel, isSimulation, notCounted, resultKindLabel } from '../carbon/presentation'

/* The actual result is the season's; the other two are simulations of the same
 * data under an assumed water regime, and are labelled as such everywhere. */
const SCENARIOS: { value: Scenario; label: string }[] = [
  { value: 'as_recorded', label: 'Kết quả vận hành' },
  { value: 'awd', label: 'Mô phỏng: AWD' },
  { value: 'continuous_flooding', label: 'Mô phỏng: Ngập liên tục' },
]

const FACTOR_GAP_CODES = new Set(['missing_emission_factor', 'factor_set_not_imported'])

/** Semantic tone → the pastel role class in styles.css. */
const toneClass = (tone: string) =>
  tone === 'methodology' ? 'methodology' : tone === 'attention' ? 'attention' : tone === 'positive' ? 'positive' : tone === 'info' ? 'water' : 'neutral'

const gasClass = (gas?: string) => {
  const g = (gas ?? '').toUpperCase()
  return g.includes('CH4') ? 'gas-ch4' : g.includes('N2O') ? 'gas-n2o' : 'gas-co2'
}
const dict = (v: unknown): Record<string, unknown> =>
  v != null && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {}
const statusClass = (v: unknown) =>
  v === 'VERIFIED' ? 'verified' : v === 'PENDING_VERIFICATION' ? 'pending' : 'test'
const statusLabel = (v: unknown) =>
  v === 'VERIFIED' ? 'Đã xác minh' : v === 'PENDING_VERIFICATION' ? 'Chờ xác minh' : 'Chưa xác minh'

/**
 * Premium Carbon screen (brief §12): hero result emphasising CO₂e/kg, scenario
 * control, source breakdown, and a provenance chain so a reviewer can audit
 * every number down to its IPCC citation. Never renders a fabricated figure —
 * a missing emission factor shows a calm "chưa thể tính" state, not a red wall.
 */
export function CarbonPanel({ id, seasonLabel, canRecalculate = true }: { id: string; seasonLabel?: string; canRecalculate?: boolean }) {
  const [scenario, setScenario] = useState<Scenario>('as_recorded')
  const state = useAsync(() => getCarbon(id, scenario), [id, scenario])
  const [recalc, setRecalc] = useState<{ busy: boolean; error?: string }>({ busy: false })
  /* The same readiness answer the Farmer sees and the Carbon list shows. This
   * panel used to consult nothing at all: it offered "Tính lại theo kịch bản"
   * for every season, including ones whose factor set cannot produce a number,
   * so the button's only possible outcome was an error. */
  const readiness = useCarbonView(id, { resultTarget: `/crop-seasons/${id}/carbon` })
  const view = readiness.view
  const blocked = Boolean(view && !view.isReady && view.calculationStatus !== 'calculated' && view.calculationStatus !== 'stale')
  /* The one action this state allows, and nothing else. A button that could
   * only fail is not drawn at all (it used to be drawn disabled, while the copy
   * below still told the officer to press it). */
  const hasStored = Boolean(state.data) && !state.error
  const action: string | null = !canRecalculate || readiness.loading || state.loading || blocked
    ? null
    : view?.calculationStatus === 'stale' && scenario === 'as_recorded' ? 'Tính lại'
      : !hasStored ? (scenario === 'as_recorded' ? 'Tính Carbon' : 'Tính kịch bản mô phỏng')
        : null
  const activityGaps = view?.userFixableGaps.filter((g) => g.flow === 'activity') ?? []
  const methodologyGaps = view?.userFixableGaps.filter((g) => g.flow === 'carbon_methodology') ?? []

  async function recalculate() {
    setRecalc({ busy: true })
    try {
      await calculateCarbon(id, scenario)
      setRecalc({ busy: false })
      state.reload()
      // The stale/current decision reads the actual result: re-read it too, or
      // "Tính lại" stays on screen after a successful recalculation.
      if (scenario === 'as_recorded') readiness.reload()
    } catch (e) {
      const api = e as ApiError
      setRecalc({
        busy: false,
        error: FACTOR_GAP_CODES.has(api?.code)
          ? 'Chưa thể tính: bộ hệ số phát thải chưa hoàn chỉnh.'
          : e instanceof Error
            ? e.message
            : 'Không thể tính lại.',
      })
    }
  }

  return (
    <div className="stack">
      <Section
        title="Phát thải carbon"
        description={seasonLabel ? `Kết quả tính cho vụ ${seasonLabel}` : 'Kết quả tính CO₂e theo vụ canh tác'}
      >
        <div className="stack">
          <div className="section__head" style={{ marginBottom: 0 }}>
            <Segmented options={SCENARIOS} value={scenario} onChange={setScenario} label="Kịch bản chế độ nước" />
            {/* Persisting a calculation needs write authority on the crop (B4);
              * read-only management roles only view results. */}
            {action && (
              <button className="btn" onClick={recalculate} disabled={recalc.busy} data-testid="carbon-action">
                <Ico name="calculator" size={14} />{recalc.busy ? 'Đang tính…' : action}
              </button>
            )}
          </div>

          {/* One readiness statement, identical in wording to every other
            * Carbon surface, above the result it explains. */}
          {view && !readiness.loading && (
            <div className={`carbon-readiness role--${toneClass(view.tone)}`}>
              <Badge tone={view.tone === 'positive' ? 'success' : view.tone === 'attention' ? 'warning' : 'neutral'}>
                <Ico name={view.icon === 'check' ? 'check' : view.icon === 'warning' ? 'warning' : 'info'} size={13} />{view.label}
              </Badge>
              <p>{view.detail}</p>
              {view.userFixableGaps.length > 0 && (
                <>
                  <ul>{view.userFixableGaps.map((g) => <li key={g.code}><b>{g.label}</b> — {g.detail}</li>)}</ul>
                  {/* Where each gap is supplied — the next step, not a button that cannot run. */}
                  {canRecalculate && (
                    <p className="carbon-readiness__fix">
                      {methodologyGaps.length > 0 && <a className="btn btn--sm" href="#fw-carbon-methodology">Bổ sung thông tin phương pháp</a>}
                      {activityGaps.length > 0 && <Link to={`/crop-seasons/${id}/activities`} className={`btn btn--sm${methodologyGaps.length ? ' btn--ghost' : ''}`}>Xem hoạt động cần bổ sung</Link>}
                    </p>
                  )}
                </>
              )}
              {view.methodologyLimitations.length > 0 && (
                <ul>{view.methodologyLimitations.map((g) => <li key={g.code}><b>{g.label}</b> — {g.detail}</li>)}</ul>
              )}
            </div>
          )}

          {scenario !== 'as_recorded' && (
            <Notice kind="info">
              <Ico name="info" size={14} /> Kịch bản mô phỏng: tính lại cùng dữ liệu của vụ với chế độ nước giả định. Đây là ước tính
              theo kịch bản, không phải kết quả đã ghi nhận và không thay kết quả vận hành của vụ.
            </Notice>
          )}

          {recalc.error && <Notice kind="warning">{recalc.error}</Notice>}

          <CarbonBody state={state} canRecalculate={canRecalculate} action={action} blocked={blocked} />
        </div>
      </Section>
    </div>
  )
}

/** The empty result says what will produce one — naming only a control that
 *  is on screen and enabled right now. */
const noCalcState = (canRecalculate: boolean, action: string | null, blocked: boolean) => (
  <EmptyState
    icon="calculator"
    title="Chưa có bản tính CO₂e cho vụ này"
    body={!canRecalculate
      ? 'Kết quả sẽ hiển thị khi quản lý HTX hoặc nông hộ phụ trách lưu bản tính cho vụ này.'
      : blocked
        ? 'Cần bổ sung các thông tin nêu ở trên trước khi tính phát thải.'
        : action
          ? `Chọn “${action}” để tính phát thải từ dữ liệu hoạt động hiện có.`
          : 'Đang kiểm tra dữ liệu của vụ.'}
  />
)

function CarbonBody({ state, canRecalculate, action, blocked }: { state: ReturnType<typeof useAsync<CarbonResult>>; canRecalculate: boolean; action: string | null; blocked: boolean }) {
  const err = state.error ?? ''
  // Chưa từng tính thành công — đây là trạng thái bình thường, không phải lỗi.
  if (err && /(chưa có bản tính|no[_ ]?calculation|calculate trước|not[_ ]?found|\b404\b)/i.test(err)) {
    return noCalcState(canRecalculate, action, blocked)
  }
  // Bộ hệ số chưa hoàn chỉnh (GWP / hệ số nhiên liệu) — trạng thái "chờ khoa học", bình tĩnh.
  if (err && /(hệ số phát thải|\bgwp\b|emission factor|factor[_ ]?set)/i.test(err)) {
    return <FactorGapState detail={err} />
  }
  return (
    <Async
      state={state}
      skeleton="table"
      isEmpty={(r) => !r || (r.total_co2e_kg == null && (r.breakdown ?? []).length === 0)}
      empty={noCalcState(canRecalculate, action, blocked)}
    >
      {(r) => <CarbonResultView r={r} />}
    </Async>
  )
}

function FactorGapState({ detail }: { detail: string }) {
  return (
    <div className="state state--warning">
      <div className="state__icon" aria-hidden="true">
        ⏳
      </div>
      <p className="state__title">Chưa thể tính kết quả cuối cùng</p>
      <p className="state__body">
        Bộ hệ số phát thải chưa hoàn chỉnh (GWP / hệ số nhiên liệu đang chờ xác minh theo QĐ 4801 & IPCC Tier 2).
        Hệ thống cố ý không hiển thị số ước lượng thay thế.
      </p>
      <p className="state__body muted">{detail}</p>
    </div>
  )
}

function CarbonResultView({ r }: { r: CarbonResult }) {
  const total = r.total_co2e_kg ?? (r.co2e_total_kg as number | undefined) ?? null
  const perKgVal = r.co2e_per_kg
  const breakdown = (r.breakdown ?? []) as any[]
  const max = breakdown.reduce((m, b) => Math.max(m, Math.abs(b.co2e_kg ?? 0)), 0)
  const missing = notCounted(r)

  return (
    <div className="stack">
      {/* Primary result */}
      <div className="carbon-hero">
        <div className="carbon-hero__cell">
          <div className="carbon-hero__label">CO₂e tổng</div>
          <div className={`carbon-hero__value${total == null ? ' is-empty' : ''}`}>{total == null ? 'Chưa đủ dữ liệu' : num(total, { max: 2 })}</div>
          <div className="carbon-hero__unit">kg CO₂e · toàn vụ</div>
        </div>
        <div className="carbon-hero__cell is-primary">
          <div className="carbon-hero__label">CO₂e trên mỗi kg thóc</div>
          <div className={`carbon-hero__value${perKgVal == null ? ' is-empty' : ''}`}>
            {perKgVal == null ? 'Chưa đủ dữ liệu sản lượng' : num(perKgVal, { max: 3 })}
          </div>
          <div className="carbon-hero__unit">{perKgVal == null ? 'cần bản ghi thu hoạch' : 'kg CO₂e / kg'}</div>
        </div>
      </div>

      <div className="page-head__meta" style={{ marginTop: 0 }} data-testid="carbon-result-meta">
        <span>
          <b className={isSimulation(r) ? 'carbon-kind carbon-kind--sim' : 'carbon-kind'}>{resultKindLabel(r)}</b>
        </span>
        <span>
          Bộ hệ số: <b>{r.ef_config_version || 'Không xác định được'}</b>
        </span>
        <span>
          Công cụ tính: <b>{r.engine_version || 'Không xác định được'}</b>
        </span>
        <span>Tính lúc: {dateTime((r.calculated_at as string) ?? null)}</span>
      </div>
      <p className="muted">Ước tính theo phương pháp hiện tại — không phải chứng nhận hay tín chỉ carbon.</p>

      {/* Breakdown */}
      {breakdown.length > 0 && (
        <div className="card card--pad">
          <h3 style={{ fontSize: 'var(--fs-h3)', marginBottom: 12 }}>Phân rã theo nguồn</h3>
          <div className="share-row">
            {breakdown.map((b, i) => {
              const v = b.co2e_kg ?? 0
              return (
                <div className="share" key={`${b.source}-${i}`}>
                  <span>{carbonSourceLabel(b)}</span>
                  <span className="share__track">
                    <span className={`share__fill ${gasClass(b.gas)}`} style={{ width: `${max > 0 ? (Math.abs(v) / max) * 100 : 0}%` }} />
                  </span>
                  <span className="share__val">{co2eKg(v)}</span>
                </div>
              )
            })}
          </div>
          {missing.length > 0 && (
            <div className="carbon-notcounted" data-testid="carbon-not-counted">
              <b>Không có dòng số riêng trong bản tính</b>
              <ul>{missing.map((m) => <li key={m.key}><b>{m.label}</b> — {m.reason}</li>)}</ul>
            </div>
          )}
        </div>
      )}

      {/* Provenance: the scientific detail, one click away rather than first. */}
      {breakdown.length > 0 && (
        <details className="card card--pad tech-detail" data-testid="carbon-methodology">
          <summary>Phương pháp và hệ số sử dụng</summary>
          {(r.warnings ?? []).length > 0 && (
            <>
              <h4>Cảnh báo phương pháp</h4>
              <ul className="carbon-warnings">{(r.warnings ?? []).map((w) => <li key={w}>{cleanWarning(w)}</li>)}</ul>
            </>
          )}
          <div className="prov-chain">
            {['CO₂e/kg', 'Công thức', 'Hệ số', 'Nguồn trích dẫn', 'Phiên bản'].map((n, i) => (
              <span key={n} style={{ display: 'contents' }}>
                {i > 0 && <span className="prov-chain__arr"><Ico name="chevron" size={12} /></span>}
                <span className="prov-chain__node">{n}</span>
              </span>
            ))}
          </div>
          {breakdown.map((b, i) => (
            <ProvenanceItem key={`${b.source}-prov-${i}`} entry={b} />
          ))}
        </details>
      )}
    </div>
  )
}

function ProvenanceItem({ entry }: { entry: any }) {
  const [open, setOpen] = useState(false)
  const factors = dict(entry.factors_used)
  const provenance = dict(entry.provenance)
  const status = dict(entry.parameter_status)
  return (
    <div className="prov-item">
      <button className="prov-item__head" aria-expanded={open} onClick={() => setOpen(!open)}>
        <span>
          {carbonSourceLabel(entry)} <span className="muted">· {co2eKg(entry.co2e_kg)}</span>
        </span>
        <span aria-hidden="true">{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <div className="prov-item__body">
          <h4>Công thức</h4>
          <code className="prov-item__formula">{entry.formula || '—'}</code>
          <p className="muted" style={{ marginTop: 6 }}>
            Giá trị hoạt động: {num(entry.activity_value, { max: 3 })} {entry.activity_unit} → {num(entry.gas_kg, { max: 4 })} kg {gasLabel(entry.gas)}
          </p>

          <h4>Hệ số sử dụng</h4>
          {Object.keys(factors).length ? (
            <dl>
              {Object.entries(factors).map(([k, v]) => (
                <span key={k} style={{ display: 'contents' }}>
                  <dt>{k}</dt>
                  <dd>{String(v)}</dd>
                </span>
              ))}
            </dl>
          ) : (
            <p className="muted">—</p>
          )}

          <h4>Nguồn trích dẫn</h4>
          {Object.keys(provenance).length ? (
            <dl>
              {Object.entries(provenance).map(([k, v]) => (
                <span key={k} style={{ display: 'contents' }}>
                  <dt>{k}</dt>
                  <dd>{String(v) || '— (thiếu nguồn)'}</dd>
                </span>
              ))}
            </dl>
          ) : (
            <p className="muted">—</p>
          )}

          <h4>Trạng thái xác minh tham số</h4>
          {Object.keys(status).length ? (
            <dl>
              {Object.entries(status).map(([k, v]) => (
                <span key={k} style={{ display: 'contents' }}>
                  <dt>{k}</dt>
                  <dd>
                    <span className={`pstatus ${statusClass(v)}`}>{statusLabel(v)}</span>
                  </dd>
                </span>
              ))}
            </dl>
          ) : (
            <p className="muted">—</p>
          )}
        </div>
      )}
    </div>
  )
}

// re-export for pages that only need the ratio formatter
export { perKg }
