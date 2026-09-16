import type { CarbonMissingInput, CarbonResult } from '../../api/carbon'
import type { CropSeason } from '../../types'
import { SeasonMethodologyPanel } from '../../features/seasonMethodology'
import { dateTime, perKg } from '../../format'
import { fmtNumber } from '../activityView'
import { Ico } from '../icons'
import { Chip, ErrorPanel, IconTile, Section, Sk, SkBlock } from '../kit'
import { useCarbon, useCarbonReadiness } from '../scope'

const SCENARIO: Record<string, string> = {
  as_recorded: 'Theo dữ liệu đã ghi', awd: 'Ướt khô xen kẽ (AWD)', continuous_flooding: 'Ngập liên tục',
}

export function SeasonCarbon({ seasonId, season, canEdit = false, onSaved }: {
  seasonId: string
  /** The season row, so the methodology panel can show what is already recorded. */
  season?: CropSeason | null
  canEdit?: boolean
  onSaved?: () => void
}) {
  const state = useCarbon(seasonId)
  const readiness = useCarbonReadiness(seasonId)
  /* The inputs panel sits on this tab so "Bổ sung dữ liệu Carbon" has somewhere
   * to land. It is the same panel Management uses — one implementation, so the
   * two shells cannot drift on what the methodology requires. */
  const inputs = season ? (
    <SeasonMethodologyPanel season={season} canEdit={canEdit} onSaved={onSaved} />
  ) : null
  if (state.loading) {
    return (
      <SkBlock label="Đang tải Carbon" className="fw-carbon-empty">
        <Sk w={200} h={200} r={100} />
        <span className="fw-sk-lines"><Sk w="30%" h={24} r={999} /><Sk w="80%" h={26} /><Sk w="60%" h={14} /><Sk w="90%" h={44} /></span>
      </SkBlock>
    )
  }
  if (state.error) return <>{inputs}<ErrorPanel error={state.error} onRetry={state.reload} /></>
  if (!state.data || state.data.kind === 'none') {
    return (
      <>{inputs}<CarbonEmpty
        reason={state.data?.kind === 'none' ? state.data.reason : null}
        seasonId={seasonId}
        missing={readiness.data?.missing_inputs ?? null}
      /></>
    )
  }
  return <>{inputs}<CarbonSuccess result={state.data.result} /></>
}

/**
 * The empty state has to answer "what do I do now?", so it lists the inputs the
 * SERVER says are missing rather than a generic "chưa có kết quả hợp lệ".
 *
 * The list, its wording and which screen fixes each item all come from
 * `/carbon/readiness`. This component holds no methodology: it renders what it
 * is given and routes on `flow`.
 */
function CarbonEmpty({ reason, seasonId, missing }: {
  reason: 'no_calculation' | null
  seasonId: string
  missing: CarbonMissingInput[] | null
}) {
  const blocking = (missing ?? []).filter((m) => m.blocking)
  const optional = (missing ?? []).filter((m) => !m.blocking)
  return (
    <section className="fw-carbon-empty" aria-labelledby="fw-carbon-empty-title">
      <div className="fw-carbon-art" aria-hidden="true"><IconTile name="carbon" tone="carbon" /></div>
      <div className="fw-carbon-empty__text">
        <Chip tone="carbon" icon="leaf">Carbon của vụ</Chip>
        <h2 id="fw-carbon-empty-title">
          {blocking.length ? 'Cần bổ sung dữ liệu để tính phát thải' : 'Chưa có kết quả phát thải cho vụ này'}
        </h2>
        {blocking.length ? (
          <>
            <p>Còn thiếu {blocking.length} thông tin bắt buộc theo phương pháp IPCC:</p>
            <ul className="fw-missing" data-testid="carbon-missing">
              {blocking.map((m) => (
                <li key={m.code}><b>{m.label}</b><span>{m.detail}</span></li>
              ))}
            </ul>
            {/* Route on the server's `flow`, so the button never sends the user
              * to a screen that cannot supply the input it names. Season-level
              * regimes are fixed in the panel above; the rest live in the journal. */}
            <p className="fw-cta-row">
              {blocking.some((m) => m.flow === 'carbon_methodology') && (
                <a className="fw-btn fw-btn--primary" href="#fw-carbon-methodology">Bổ sung dữ liệu Carbon</a>
              )}
              {blocking.some((m) => m.flow === 'activity') && (
                <a className="fw-btn fw-btn--soft" href={`/farmer/crop-seasons/${seasonId}/journal`}>Sửa bản ghi trong nhật ký</a>
              )}
            </p>
          </>
        ) : (
          <>
            <p>Dữ liệu đầu vào đã đủ. Kết quả sẽ có sau khi vụ được tính phát thải.</p>
            {reason === 'no_calculation' && (
              <p className="fw-reason"><b>Lý do từ hệ thống</b>Chưa có bản tính phát thải thành công nào được lưu cho vụ này.</p>
            )}
          </>
        )}
        {optional.length > 0 && (
          <p className="fw-note">
            {optional.map((m) => m.label).join(' · ')} — vẫn tính được tổng CO₂e, chỉ chưa có cường độ trên mỗi kg lúa.
          </p>
        )}
        <ul className="fw-bullets">
          <li><Ico name="check" />Dữ liệu canh tác của bạn vẫn được lưu bình thường.</li>
          <li><Ico name="check" />Không có số liệu CO₂e nào được ước đoán thay thế.</li>
          <li><Ico name="check" />Chi phí không phải đầu vào của Carbon — chi phí chỉ dùng cho chỉ số Chi phí/kg.</li>
        </ul>
      </div>
    </section>
  )
}

function CarbonSuccess({ result }: { result: CarbonResult }) {
  const total = result.total_co2e_kg ?? result.co2e_total_kg ?? null
  const scenario = result.water_regime_scenario ?? result.scenario
  const sources = [...result.breakdown].sort((a, b) => b.co2e_kg - a.co2e_kg)
  return (
    <>
      <div className="fw-carbon-hero">
        <div>
          <small>Carbon trên mỗi kg lúa</small>
          <b className={result.co2e_per_kg == null ? 'is-empty' : undefined}>{result.co2e_per_kg == null ? 'Chưa đủ dữ liệu' : perKg(result.co2e_per_kg, '')}</b>
          <span>{result.co2e_per_kg == null ? 'Cần sản lượng hợp lệ để tính CO₂e/kg' : 'kg CO₂e / kg lúa'}</span>
        </div>
        <div>
          <small>Tổng phát thải của vụ</small>
          <b className={total == null ? 'is-empty' : undefined}>{total == null ? 'Chưa đủ dữ liệu' : fmtNumber(total)}</b>
          <span>kg CO₂e</span>
        </div>
        <div>
          <small>Tính lúc</small>
          <b className="is-empty">{result.calculated_at ? dateTime(result.calculated_at) : 'Chưa có dữ liệu'}</b>
          <span>Kịch bản: {scenario ? (SCENARIO[scenario] ?? scenario) : 'Chưa có dữ liệu'}</span>
        </div>
      </div>
      <Section title="Nguồn phát thải chính" icon="carbon" tone="carbon">
        <div className="fw-sources">
          {sources.map((item, index) => {
            const share = total && total > 0 ? Math.max(0, item.co2e_kg) / total : null
            return (
              <div key={index} className="fw-source">
                <span>{item.source}</span>
                <span className="fw-source__bar" aria-hidden="true"><i style={{ width: `${(share ?? 0) * 100}%` }} /></span>
                <b>{perKg(item.co2e_kg, 'kg CO₂e')}</b>
              </div>
            )
          })}
        </div>
      </Section>
      <p className="fw-disclaimer"><Ico name="info" />Kết quả là ước tính theo bộ phương pháp hiện tại; không phải chứng nhận hoặc tín chỉ carbon.</p>
      <details className="fw-disclosure">
        <summary><Ico name="method" />Cách tính<Ico name="chevron" /></summary>
        <div className="fw-disclosure__body">
          <dl className="fw-detail">
            <div><dt>Phiên bản bộ hệ số</dt><dd>{result.ef_config_version ?? 'Chưa có dữ liệu'}</dd></div>
            <div><dt>Phiên bản công cụ tính</dt><dd>{result.engine_version ?? 'Chưa có dữ liệu'}</dd></div>
            <div><dt>Kịch bản nước</dt><dd>{scenario ? (SCENARIO[scenario] ?? scenario) : 'Chưa có dữ liệu'}</dd></div>
            {result.warnings.length > 0 && <div><dt>Cảnh báo</dt><dd>{result.warnings.join('; ')}</dd></div>}
          </dl>
        </div>
      </details>
    </>
  )
}
