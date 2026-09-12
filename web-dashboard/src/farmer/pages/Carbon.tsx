import type { CarbonResult } from '../../api/carbon'
import { dateTime, perKg } from '../../format'
import { fmtNumber } from '../activityView'
import { Ico } from '../icons'
import { Chip, ErrorPanel, IconTile, Section, Sk, SkBlock } from '../kit'
import { useCarbon } from '../scope'

const SCENARIO: Record<string, string> = {
  as_recorded: 'Theo dữ liệu đã ghi', awd: 'Ướt khô xen kẽ (AWD)', continuous_flooding: 'Ngập liên tục',
}

export function SeasonCarbon({ seasonId }: { seasonId: string }) {
  const state = useCarbon(seasonId)
  if (state.loading) {
    return (
      <SkBlock label="Đang tải Carbon" className="fw-carbon-empty">
        <Sk w={200} h={200} r={100} />
        <span className="fw-sk-lines"><Sk w="30%" h={24} r={999} /><Sk w="80%" h={26} /><Sk w="60%" h={14} /><Sk w="90%" h={44} /></span>
      </SkBlock>
    )
  }
  if (state.error) return <ErrorPanel error={state.error} onRetry={state.reload} />
  if (!state.data || state.data.kind === 'none') return <CarbonEmpty reason={state.data?.kind === 'none' ? state.data.reason : null} />
  return <CarbonSuccess result={state.data.result} />
}

function CarbonEmpty({ reason }: { reason: 'no_calculation' | null }) {
  return (
    <section className="fw-carbon-empty" aria-labelledby="fw-carbon-empty-title">
      <div className="fw-carbon-art" aria-hidden="true"><IconTile name="carbon" tone="carbon" /></div>
      <div className="fw-carbon-empty__text">
        <Chip tone="carbon" icon="leaf">Carbon của vụ</Chip>
        <h2 id="fw-carbon-empty-title">Chưa có kết quả phát thải hợp lệ cho vụ này</h2>
        <p>Hệ thống chưa thể tạo kết quả Carbon cho vụ này.</p>
        {reason === 'no_calculation' && (
          <p className="fw-reason"><b>Lý do từ hệ thống</b>Chưa có bản tính phát thải thành công nào được lưu cho vụ này.</p>
        )}
        <ul className="fw-bullets">
          <li><Ico name="check" />Dữ liệu canh tác của bạn vẫn được lưu bình thường.</li>
          <li><Ico name="check" />Không có số liệu CO₂e nào được ước đoán thay thế.</li>
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
