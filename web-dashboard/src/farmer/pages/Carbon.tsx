import { useState } from 'react'
import { ApiError } from '../../api/client'
import { calculateCarbon, getCarbon, type CarbonResult, type Scenario } from '../../api/carbon'
import { isResultStale } from '../../carbon/readiness'
import { SCENARIO_LABEL, carbonSourceLabel, cleanWarning, notCounted, resultKindLabel, simulationOutdated } from '../../carbon/presentation'
import type { Activity, CropSeason } from '../../types'
import { SeasonMethodologyPanel } from '../../features/seasonMethodology'
import { co2eKg, dateTime, perKg } from '../../format'
import type { ActivityMutations, SeasonContext } from '../ActivityForms'
import { fmtNumber } from '../activityView'
import { CarbonRepairHub } from '../CarbonRepair'
import { Disclosure } from '../metricRows'
import { Ico } from '../icons'
import { Chip, ErrorPanel, IconTile, Section, Sk, SkBlock } from '../kit'
import { carbonInputsChangedAt, invalidateQueries, keys, useQuery } from '../data'
import { useCarbon, useCarbonReadiness } from '../scope'

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
  /* "Cần tính lại": a Carbon input changed since the ACTUAL result was stored —
   * the server's input fingerprint no longer matches the result's. A cost or
   * note edit is not in the fingerprint, and a scenario is never compared. */
  const stale = Boolean(state.data?.kind === 'result' && isResultStale({
    readiness: readiness.data, result: state.data.result, latestInputAt: carbonInputsChangedAt(seasonId),
  }))
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
  const compare = <ScenarioCompare seasonId={seasonId} actual={state.data.result} canCalculate={canEdit} />
  return outstanding
    ? <>{hub}<CarbonSuccess result={state.data.result} stale={stale} />{compare}{inputs}</>
    : <><CarbonSuccess result={state.data.result} stale={stale} />{compare}{inputs}</>
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
  const sources = [...result.breakdown].sort((a, b) => b.co2e_kg - a.co2e_kg)
  const top = sources[0] ?? null
  const missing = notCounted(result)
  const citations = [...new Set(result.breakdown.flatMap((b) =>
    Object.values((b.provenance ?? {}) as Record<string, unknown>).map((v) => String(v ?? '').trim()).filter(Boolean)))]
  return (
    <>
      {/* The farmer's question first ("how much did this season emit?"), then
        * the comparable figure, then where it came from. The scientific detail
        * stays available but never leads. */}
      {stale && (
        <p className="fw-restale fw-role fw-role--attention" data-testid="carbon-stale">
          <Ico name="warning" />
          <span><b>Cần tính lại.</b> Dữ liệu dùng để tính Carbon đã thay đổi sau lần tính gần nhất, nên số dưới đây là kết quả cũ.</span>
        </p>
      )}
      <div className="fw-carbon-hero">
        <div>
          <small>Tổng phát thải vụ này</small>
          <b className={total == null ? 'is-empty' : undefined} data-testid="carbon-actual-total">{total == null ? 'Chưa đủ dữ liệu' : fmtNumber(total)}</b>
          <span>kg CO₂e</span>
        </div>
        <div>
          <small>Phát thải trên mỗi kg lúa</small>
          <b className={result.co2e_per_kg == null ? 'is-empty' : undefined} data-testid="carbon-actual-per-kg">{result.co2e_per_kg == null ? 'Chưa đủ dữ liệu' : perKg(result.co2e_per_kg, '')}</b>
          <span>{result.co2e_per_kg == null ? 'Cần sản lượng hợp lệ để tính CO₂e/kg' : 'kg CO₂e / kg lúa'}</span>
        </div>
        <div>
          <small>Tính lúc</small>
          <b className="is-empty">{result.calculated_at ? dateTime(result.calculated_at) : 'Chưa có dữ liệu'}</b>
          <span data-testid="carbon-result-state">{stale ? 'Cần tính lại' : 'Đã tính'} · {resultKindLabel(result)}</span>
        </div>
      </div>
      {top && (
        <p className="fw-carbon-top" data-testid="carbon-top-source">
          <Ico name="carbon" />Nguồn đóng góp nhiều nhất: <b>{carbonSourceLabel(top)}</b>
          {total && total > 0 ? <> — {Math.round((Math.max(0, top.co2e_kg) / total) * 100)}% tổng phát thải</> : null}
        </p>
      )}
      <Section title="Nguồn phát thải trong bản tính" icon="carbon" tone="carbon">
        <div className="fw-sources" data-testid="carbon-sources">
          {sources.map((item, index) => {
            const share = total && total > 0 ? Math.max(0, item.co2e_kg) / total : null
            return (
              <div key={index} className="fw-source">
                <span>{carbonSourceLabel(item)}</span>
                <span className="fw-source__bar" aria-hidden="true"><i style={{ width: `${(share ?? 0) * 100}%` }} /></span>
                <b>{co2eKg(item.co2e_kg)}</b>
              </div>
            )
          })}
        </div>
        {missing.length > 0 && (
          <div className="fw-notcounted" data-testid="carbon-not-counted">
            <b>Không có dòng số riêng trong bản tính</b>
            <ul>{missing.map((m) => <li key={m.key}><span>{m.label}</span> — {m.reason}</li>)}</ul>
          </div>
        )}
      </Section>
      <p className="fw-disclaimer"><Ico name="info" />Kết quả là ước tính theo bộ phương pháp hiện tại; không phải chứng nhận hoặc tín chỉ carbon.</p>
      <Disclosure label="Phương pháp và hệ số sử dụng">
        <dl className="fw-detail" data-testid="carbon-methodology">
          <div><dt>Loại kết quả</dt><dd>{resultKindLabel(result)}</dd></div>
          <div><dt>Dữ liệu sử dụng</dt><dd>Các hoạt động đã ghi của vụ (bón phân, rơm rạ, nhiên liệu…), chế độ nước và sản lượng thóc. Chi phí không được dùng.</dd></div>
          <div><dt>Phiên bản bộ hệ số</dt><dd>{result.ef_config_version || 'Không xác định được từ bản tính đã lưu'}</dd></div>
          <div><dt>Phiên bản công cụ tính</dt><dd>{result.engine_version || 'Không xác định được từ bản tính đã lưu'}</dd></div>
          <div><dt>Thời điểm tính</dt><dd>{result.calculated_at ? dateTime(result.calculated_at) : 'Không xác định được'}</dd></div>
          {citations.length > 0 && <div><dt>Nguồn hệ số</dt><dd><ul className="fw-citations">{citations.map((c) => <li key={c}>{c}</li>)}</ul></dd></div>}
          <div><dt>So sánh</dt><dd>Chưa có mốc so sánh được xác minh cho phát thải của vụ này.</dd></div>
          {result.warnings.length > 0 && <div><dt>Cảnh báo phương pháp</dt><dd><ul className="fw-citations">{result.warnings.map((w) => <li key={w}>{cleanWarning(w)}</li>)}</ul></dd></div>}
        </dl>
      </Disclosure>
    </>
  )
}

const SIMULATIONS: Scenario[] = ['awd', 'continuous_flooding']


/** Simulated water regimes beside the actual result — never in its place.
 *
 * Each scenario is read by name. A missing one is "Chưa tính", not an error,
 * and calculating it touches only its own query: the actual result above is
 * not re-read, so a simulation cannot change the season's numbers. */
function ScenarioCompare({ seasonId, actual, canCalculate }: { seasonId: string; actual: CarbonResult; canCalculate: boolean }) {
  const [busy, setBusy] = useState<Scenario | null>(null)
  const [error, setError] = useState<string | null>(null)
  const key = `${keys.carbon(seasonId)}:simulations`
  const sims = useQuery<Partial<Record<Scenario, CarbonResult | null>>>(key, async () => {
    const read = async (s: Scenario) => {
      try { return await getCarbon(seasonId, s) } catch (e) {
        if (e instanceof ApiError && e.code === 'no_calculation') return null
        throw e
      }
    }
    const [awd, flooding] = await Promise.all(SIMULATIONS.map(read))
    return { awd, continuous_flooding: flooding }
  })
  async function run(s: Scenario) {
    setBusy(s); setError(null)
    try {
      await calculateCarbon(seasonId, s)
      invalidateQueries(key)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Không tính được kịch bản này.')
    } finally { setBusy(null) }
  }
  const actualTotal = actual.total_co2e_kg ?? actual.co2e_total_kg ?? null
  return (
    <Section title="So sánh với kịch bản mô phỏng" icon="irrigation" tone="water">
      <p className="fw-scenario-note">
        Kịch bản mô phỏng tính lại <b>cùng dữ liệu của vụ</b> với một chế độ nước giả định. Đây là ước tính theo kịch bản —
        không phải kết quả đã ghi nhận, không phải tác động được chứng nhận. Kết quả vận hành ở trên không thay đổi.
      </p>
      {sims.loading && !sims.data ? <SkBlock label="Đang tải kịch bản"><Sk w="100%" h={60} /></SkBlock> : null}
      {sims.error ? <ErrorPanel error={sims.error} onRetry={sims.reload} /> : null}
      {sims.data && (
        <div className="fw-scenarios" data-testid="carbon-scenarios">
          <div className="fw-scenario fw-scenario--actual">
            <small>Kết quả vận hành · {SCENARIO_LABEL.as_recorded}</small>
            <b>{actual.co2e_per_kg == null ? 'Chưa đủ dữ liệu' : perKg(actual.co2e_per_kg, 'kg CO₂e/kg')}</b>
            <span>{actualTotal == null ? 'Chưa đủ dữ liệu' : `${fmtNumber(actualTotal)} kg CO₂e`}</span>
          </div>
          {SIMULATIONS.map((s) => {
            const r = sims.data?.[s] ?? null
            return (
              <div key={s} className="fw-scenario" data-testid={`carbon-scenario-${s}`}>
                <small>Kịch bản mô phỏng · {SCENARIO_LABEL[s]}</small>
                {r ? (
                  <>
                    <b>{r.co2e_per_kg == null ? 'Chưa đủ dữ liệu' : perKg(r.co2e_per_kg, 'kg CO₂e/kg')}</b>
                    <span>{fmtNumber(r.total_co2e_kg)} kg CO₂e · tính lúc {r.calculated_at ? dateTime(r.calculated_at) : '—'}</span>
                    {simulationOutdated(r, actual) && (
                      <>
                        <span className="fw-scenario__old" data-testid={`carbon-scenario-${s}-outdated`}>
                          Tính trên dữ liệu cũ hơn kết quả vận hành — chưa so sánh được.
                        </span>
                        {canCalculate && <button type="button" className="fw-btn fw-btn--soft fw-btn--sm" disabled={busy != null} onClick={() => void run(s)}>{busy === s ? 'Đang tính…' : 'Tính lại kịch bản'}</button>}
                      </>
                    )}
                  </>
                ) : (
                  <>
                    <b className="is-empty">Chưa tính</b>
                    {canCalculate
                      ? <button type="button" className="fw-btn fw-btn--soft fw-btn--sm" disabled={busy != null} onClick={() => void run(s)}>{busy === s ? 'Đang tính…' : 'Tính kịch bản'}</button>
                      : <span>Chưa có bản tính cho kịch bản này.</span>}
                  </>
                )}
              </div>
            )
          })}
        </div>
      )}
      {error && <p className="fw-form__error" role="alert">{error}</p>}
    </Section>
  )
}
