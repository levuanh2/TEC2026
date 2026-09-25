import type { CarbonResult } from '../../api/carbon'
import type { Activity, CropSeason } from '../../types'
import { SeasonMethodologyPanel } from '../../features/seasonMethodology'
import { dateTime, perKg } from '../../format'
import type { ActivityMutations, SeasonContext } from '../ActivityForms'
import { fmtNumber } from '../activityView'
import { CarbonRepairHub } from '../CarbonRepair'
import { Disclosure } from '../metricRows'
import { SOURCE_LABEL } from '../metricsView'
import { Ico } from '../icons'
import { Chip, ErrorPanel, IconTile, Section, Sk, SkBlock } from '../kit'
import { carbonInputsChangedAt, invalidateQueries, keys } from '../data'
import { useCarbon, useCarbonReadiness } from '../scope'

const SCENARIO: Record<string, string> = {
  as_recorded: 'Theo dữ liệu đã ghi', awd: 'Ướt khô xen kẽ (AWD)', continuous_flooding: 'Ngập liên tục',
}

export function SeasonCarbon({ seasonId, season, plotId, writeCtx = null, canEditSeason, activities, mutations, onSaved }: {
  seasonId: string
  /** The season row, so the methodology panel can show what is already recorded. */
  season?: CropSeason | null
  plotId?: string | null
  /** The season as a write target; null for a viewer — no edit controls at all. */
  writeCtx?: SeasonContext | null
  /** May change the season record and calculate, whatever its status. Defaults
   * to `writeCtx != null`; a finished season passes true with a null writeCtx. */
  canEditSeason?: boolean
  /** The season's records, so "Sửa ngay" can open the exact one readiness names. */
  activities?: Activity[]
  /** The page's single edit-sheet owner — the same form the journal uses. */
  mutations?: ActivityMutations
  onSaved?: () => void
}) {
  const canEdit = canEditSeason ?? Boolean(writeCtx)
  const state = useCarbon(seasonId)
  const readiness = useCarbonReadiness(seasonId)
  const hasResult = state.data?.kind === 'result'
  /* "Cần tính lại": the farmer changed an input after this result was
   * calculated. Timestamps only — nothing here re-derives an emission. */
  const changedAt = carbonInputsChangedAt(seasonId)
  const calculatedAt = state.data?.kind === 'result' ? state.data.result.calculated_at : null
  const stale = Boolean(hasResult && changedAt && calculatedAt && changedAt > calculatedAt)
  // A saved season field can resolve a readiness item, from either editor.
  const seasonSaved = () => { invalidateQueries(keys.carbonReadiness(seasonId)); onSaved?.() }
  /* Repair hub first: what is missing and the one action that supplies each.
   * Absent when readiness is unavailable — the page still renders calmly. */
  const hub = readiness.data ? (
    <CarbonRepairHub
      seasonId={seasonId} readiness={readiness.data} hasResult={hasResult} stale={stale} plotId={plotId}
      writeCtx={writeCtx} canEditSeason={canEdit} activities={activities} mutations={mutations} onSeasonSaved={seasonSaved}
    />
  ) : null
  /* The full methodology panel stays for reviewing or changing values that are
   * already set. It is the same panel Management uses — one implementation. */
  const inputs = season ? (
    <SeasonMethodologyPanel season={season} canEdit={canEdit} onSaved={seasonSaved} />
  ) : null
  if (state.loading) {
    return (
      <SkBlock label="Đang tải Carbon" className="fw-carbon-empty">
        <Sk w={200} h={200} r={100} />
        <span className="fw-sk-lines"><Sk w="30%" h={24} r={999} /><Sk w="80%" h={26} /><Sk w="60%" h={14} /><Sk w="90%" h={44} /></span>
      </SkBlock>
    )
  }
  if (state.error) return <>{hub}<ErrorPanel error={state.error} onRetry={state.reload} />{inputs}</>
  if (!state.data || state.data.kind === 'none') {
    return <>{hub}<CarbonEmpty reason={state.data?.kind === 'none' ? state.data.reason : null} />{inputs}</>
  }
  /* A fresh result with nothing outstanding: the result leads and the hub,
   * whose only content would be "Tính lại", is not shown — recalculating is not
   * the next thing to do. Stale or still-incomplete: the hub first, since it
   * carries the action the result is waiting on. */
  const outstanding = stale || (readiness.data?.missing_inputs ?? []).some((m) => m.blocking)
  return outstanding
    ? <>{hub}<CarbonSuccess result={state.data.result} stale={stale} />{inputs}</>
    : <><CarbonSuccess result={state.data.result} stale={stale} />{inputs}</>
}

/** No stored result yet. What is missing, and how to supply it, is the repair
 * hub's job; this only says what the empty state means. */
function CarbonEmpty({ reason }: { reason: 'no_calculation' | null }) {
  return (
    <section className="fw-carbon-empty" aria-labelledby="fw-carbon-empty-title">
      <div className="fw-carbon-art" aria-hidden="true"><IconTile name="carbon" tone="carbon" /></div>
      <div className="fw-carbon-empty__text">
        <Chip tone="carbon" icon="leaf">Carbon của vụ</Chip>
        <h2 id="fw-carbon-empty-title">Chưa có kết quả phát thải cho vụ này</h2>
        {reason === 'no_calculation' && (
          <p className="fw-reason"><b>Lý do từ hệ thống</b>Chưa có bản tính phát thải thành công nào được lưu cho vụ này.</p>
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

function CarbonSuccess({ result, stale }: { result: CarbonResult; stale?: boolean }) {
  const total = result.total_co2e_kg ?? result.co2e_total_kg ?? null
  const scenario = result.water_regime_scenario ?? result.scenario
  const sources = [...result.breakdown].sort((a, b) => b.co2e_kg - a.co2e_kg)
  const top = sources[0] ?? null
  return (
    <>
      {/* The farmer's question first ("how much did this season emit?"), then
        * the comparable figure, then where it came from. The scientific detail
        * stays available but never leads. */}
      {stale && (
        <p className="fw-restale fw-role fw-role--attention" data-testid="carbon-stale">
          <Ico name="warning" />
          <span><b>Cần tính lại.</b> Bạn đã thay đổi dữ liệu sau lần tính gần nhất, nên số dưới đây là kết quả cũ.</span>
        </p>
      )}
      <div className="fw-carbon-hero">
        <div>
          <small>Tổng phát thải vụ này</small>
          <b className={total == null ? 'is-empty' : undefined}>{total == null ? 'Chưa đủ dữ liệu' : fmtNumber(total)}</b>
          <span>kg CO₂e</span>
        </div>
        <div>
          <small>Phát thải trên mỗi kg lúa</small>
          <b className={result.co2e_per_kg == null ? 'is-empty' : undefined}>{result.co2e_per_kg == null ? 'Chưa đủ dữ liệu' : perKg(result.co2e_per_kg, '')}</b>
          <span>{result.co2e_per_kg == null ? 'Cần sản lượng hợp lệ để tính CO₂e/kg' : 'kg CO₂e / kg lúa'}</span>
        </div>
        <div>
          <small>Tính lúc</small>
          <b className="is-empty">{result.calculated_at ? dateTime(result.calculated_at) : 'Chưa có dữ liệu'}</b>
          <span data-testid="carbon-result-state">{stale ? 'Cần tính lại' : 'Kết quả mới nhất'} · {scenario ? (SCENARIO[scenario] ?? scenario) : 'Chưa rõ kịch bản'}</span>
        </div>
      </div>
      {top && (
        <p className="fw-carbon-top" data-testid="carbon-top-source">
          <Ico name="carbon" />Nguồn đóng góp nhiều nhất: <b>{SOURCE_LABEL[top.source] ?? 'Nguồn khác'}</b>
          {total && total > 0 ? <> — {Math.round((Math.max(0, top.co2e_kg) / total) * 100)}% tổng phát thải</> : null}
        </p>
      )}
      <Section title="Nguồn phát thải chính" icon="carbon" tone="carbon">
        <div className="fw-sources">
          {sources.map((item, index) => {
            const share = total && total > 0 ? Math.max(0, item.co2e_kg) / total : null
            return (
              <div key={index} className="fw-source">
                <span>{SOURCE_LABEL[item.source] ?? 'Nguồn khác'}</span>
                <span className="fw-source__bar" aria-hidden="true"><i style={{ width: `${(share ?? 0) * 100}%` }} /></span>
                <b>{perKg(item.co2e_kg, 'kg CO₂e')}</b>
              </div>
            )
          })}
        </div>
      </Section>
      <p className="fw-disclaimer"><Ico name="info" />Kết quả là ước tính theo bộ phương pháp hiện tại; không phải chứng nhận hoặc tín chỉ carbon.</p>
      <Disclosure label="Cách tính và dữ liệu sử dụng">
        <dl className="fw-detail">
          <div><dt>Dữ liệu sử dụng</dt><dd>Các hoạt động đã ghi của vụ (bón phân, rơm rạ, nhiên liệu…), chế độ nước và sản lượng thóc. Chi phí không được dùng.</dd></div>
          <div><dt>Phiên bản bộ hệ số</dt><dd>{result.ef_config_version ?? 'Chưa có dữ liệu'}</dd></div>
          <div><dt>Phiên bản công cụ tính</dt><dd>{result.engine_version ?? 'Chưa có dữ liệu'}</dd></div>
          <div><dt>Kịch bản nước</dt><dd>{scenario ? (SCENARIO[scenario] ?? scenario) : 'Chưa có dữ liệu'}</dd></div>
          <div><dt>So sánh</dt><dd>Chưa có mốc so sánh cho phát thải của vụ này.</dd></div>
          {result.warnings.length > 0 && <div><dt>Cảnh báo</dt><dd>{result.warnings.join('; ')}</dd></div>}
        </dl>
      </Disclosure>
    </>
  )
}
