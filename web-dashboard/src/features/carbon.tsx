import { Ico } from '../icons'
import { useState } from 'react'
import { ApiError } from '../api/client'
import { calculateCarbon, getCarbon, type CarbonResult, type Scenario } from '../api/carbon'
import { num, kg, perKg, dateTime } from '../format'
import { Async, Notice, Section, Segmented, useAsync, EmptyState } from '../ui'

const SCENARIOS: { value: Scenario; label: string }[] = [
  { value: 'as_recorded', label: 'Theo ghi nhận' },
  { value: 'awd', label: 'AWD (rút nước)' },
  { value: 'continuous_flooding', label: 'Ngập liên tục' },
]

const FACTOR_GAP_CODES = new Set(['missing_emission_factor', 'factor_set_not_imported'])

function sourceLabel(source: string): string {
  const s = source.toLowerCase()
  if (s.includes('ch4') || s.includes('methane') || s.includes('rice')) return 'CH₄ — ruộng lúa'
  if (s.includes('n2o') || s.includes('fertil')) return 'N₂O — phân bón'
  if (s.includes('straw') || s.includes('burn')) return 'Đốt rơm rạ'
  if (s.includes('fuel') || s.includes('diesel') || s.includes('gasolin') || s.includes('lpg')) return 'Nhiên liệu'
  return source
}
const gasClass = (gas?: string) => {
  const g = (gas ?? '').toUpperCase()
  return g.includes('CH4') ? 'gas-ch4' : g.includes('N2O') ? 'gas-n2o' : 'gas-co2'
}
const dict = (v: unknown): Record<string, unknown> =>
  v != null && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {}
const statusClass = (v: unknown) =>
  v === 'VERIFIED' ? 'verified' : v === 'PENDING_VERIFICATION' ? 'pending' : 'test'

/**
 * Premium Carbon screen (brief §12): hero result emphasising CO₂e/kg, scenario
 * control, source breakdown, and a provenance chain so a reviewer can audit
 * every number down to its IPCC citation. Never renders a fabricated figure —
 * a missing emission factor shows a calm "chưa thể tính" state, not a red wall.
 */
export function CarbonPanel({ id, seasonLabel }: { id: string; seasonLabel?: string }) {
  const [scenario, setScenario] = useState<Scenario>('as_recorded')
  const state = useAsync(() => getCarbon(id, scenario), [id, scenario])
  const [recalc, setRecalc] = useState<{ busy: boolean; error?: string }>({ busy: false })

  async function recalculate() {
    setRecalc({ busy: true })
    try {
      await calculateCarbon(id, scenario)
      setRecalc({ busy: false })
      state.reload()
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
            <button className="btn btn--ghost" onClick={recalculate} disabled={recalc.busy || state.loading}>
              {recalc.busy ? 'Đang tính…' : 'Tính lại theo kịch bản'}
            </button>
          </div>
          {recalc.error && <Notice kind="warning">{recalc.error}</Notice>}

          <CarbonBody state={state} />
        </div>
      </Section>
    </div>
  )
}

const NoCalcState = (
  <EmptyState
    icon="calculator"
    title="Chưa có bản tính CO₂e cho vụ này"
    body="Nhấn “Tính lại theo kịch bản” để chạy Carbon Engine với dữ liệu hoạt động hiện có."
  />
)

function CarbonBody({ state }: { state: ReturnType<typeof useAsync<CarbonResult>> }) {
  const err = state.error ?? ''
  // Chưa từng tính thành công — đây là trạng thái bình thường, không phải lỗi.
  if (err && /(chưa có bản tính|no[_ ]?calculation|calculate trước|not[_ ]?found|\b404\b)/i.test(err)) {
    return NoCalcState
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
      empty={NoCalcState}
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
  const scenarioName = (r.water_regime_scenario ?? r.scenario ?? '—') as string

  return (
    <div className="stack">
      {/* Primary result */}
      <div className="carbon-hero">
        <div className="carbon-hero__cell">
          <div className="carbon-hero__label">CO₂e tổng</div>
          <div className={`carbon-hero__value${total == null ? ' is-empty' : ''}`}>{total == null ? 'Chưa đủ dữ liệu' : num(total, { max: 1 })}</div>
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

      <div className="page-head__meta" style={{ marginTop: 0 }}>
        <span>
          Kịch bản: <b>{scenarioName}</b>
        </span>
        <span>
          Bộ hệ số: <b>{(r.ef_config_version as string) ?? '—'}</b>
        </span>
        <span>
          Engine: <b>{(r.engine_version as string) ?? '—'}</b>
        </span>
        <span>Tính lúc: {dateTime((r.calculated_at as string) ?? null)}</span>
      </div>

      {(r.warnings ?? []).map((w) => (
        <Notice key={w} kind="warning">
          <Ico name="warning" size={14} /> {w}
        </Notice>
      ))}

      {/* Breakdown */}
      {breakdown.length > 0 && (
        <div className="card card--pad">
          <h3 style={{ fontSize: 'var(--fs-h3)', marginBottom: 12 }}>Phân rã theo nguồn</h3>
          <div className="share-row">
            {breakdown.map((b, i) => {
              const v = b.co2e_kg ?? 0
              return (
                <div className="share" key={`${b.source}-${i}`}>
                  <span>
                    {sourceLabel(String(b.source))} <span className="muted">· {b.gas ?? '—'}</span>
                  </span>
                  <span className="share__track">
                    <span className={`share__fill ${gasClass(b.gas)}`} style={{ width: `${max > 0 ? (Math.abs(v) / max) * 100 : 0}%` }} />
                  </span>
                  <span className="share__val">{kg(v)}</span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Provenance / trust */}
      {breakdown.length > 0 && (
        <div className="card card--pad">
          <h3 style={{ fontSize: 'var(--fs-h3)', marginBottom: 6 }}>Số liệu này được tính thế nào?</h3>
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
        </div>
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
          {sourceLabel(String(entry.source))} <span className="muted">· {kg(entry.co2e_kg)}</span>
        </span>
        <span aria-hidden="true">{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <div className="prov-item__body">
          <h4>Công thức</h4>
          <code className="prov-item__formula">{entry.formula || '—'}</code>
          <p className="muted" style={{ marginTop: 6 }}>
            Giá trị hoạt động: {num(entry.activity_value, { max: 3 })} {entry.activity_unit} → {num(entry.gas_kg, { max: 4 })} kg {entry.gas}
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
                    <span className={`pstatus ${statusClass(v)}`}>{String(v)}</span>
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
