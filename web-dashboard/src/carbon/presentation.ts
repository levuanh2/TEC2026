/* How a Carbon result is *named* on every screen — never how it is computed.
 *
 * Before this module the Farmer screen looked source names up in a table whose
 * keys the engine never emits ("Nguồn khác" for everything but CH₄), Management
 * guessed from substrings and fell back to the raw value (`undefined · ch4` for
 * a stored result, which carried `category` instead of `source`), the scenario
 * showed as the DB enum `actual`, and warnings carried the season's UUID.
 *
 * Nothing here is methodology: labels, the kind of result, which categories the
 * stored payload shows were NOT counted and the reason the engine itself gives.
 * No emission figure is produced, altered or rounded here.
 */
import type { CarbonBreakdown, CarbonResult, Scenario } from '../api/carbon'

const FUEL: Record<string, string> = { diesel: 'dầu diesel', gasoline: 'xăng', lpg: 'khí LPG', other: 'loại khác' }
const GAS: Record<string, string> = { ch4: 'CH₄', n2o: 'N₂O', co2: 'CO₂' }

export const gasLabel = (gas: unknown): string => GAS[String(gas ?? '').toLowerCase()] ?? 'khí nhà kính'

/** A breakdown line's name in plain Vietnamese. Never the raw engine value. */
export function carbonSourceLabel(line: Pick<CarbonBreakdown, 'source' | 'gas'> | { source?: unknown; gas?: unknown }): string {
  const source = String(line.source ?? '')
  if (source === 'ch4_rice_cultivation') return 'Phát thải methane (CH₄) từ ruộng lúa và quản lý nước'
  if (source === 'n2o_fertilizer_direct') return 'Phát thải N₂O từ phân đạm'
  if (source === 'straw_burning') return `Đốt rơm rạ (${gasLabel(line.gas)})`
  if (source.startsWith('fuel_')) return `Nhiên liệu máy móc (${FUEL[source.slice(5)] ?? 'loại khác'})`
  if (source === 'fuel') return 'Nhiên liệu máy móc'
  return 'Nguồn phát thải chưa đặt tên'
}

/* ---------------------------------------------------------------- kind */

export const SCENARIO_LABEL: Record<Scenario, string> = {
  as_recorded: 'Theo dữ liệu đã ghi',
  awd: 'Ướt khô xen kẽ (AWD)',
  continuous_flooding: 'Ngập liên tục',
}

/** The scenario of a result in API vocabulary; older servers sent the DB enum `actual`. */
export function resultScenario(r: Pick<CarbonResult, 'scenario' | 'water_regime_scenario'>): Scenario | null {
  const raw = String(r.water_regime_scenario ?? r.scenario ?? '')
  if (raw === 'actual' || raw === 'as_recorded') return 'as_recorded'
  if (raw === 'awd' || raw === 'continuous_flooding') return raw
  return null
}

export const isSimulation = (r: Pick<CarbonResult, 'scenario' | 'water_regime_scenario' | 'calculation_kind'>) =>
  r.calculation_kind ? r.calculation_kind === 'scenario' : resultScenario(r) !== 'as_recorded'

/** "Kết quả vận hành" for the recorded season, "Kịch bản mô phỏng · …" otherwise. */
export function resultKindLabel(r: Pick<CarbonResult, 'scenario' | 'water_regime_scenario' | 'calculation_kind'>): string {
  const s = resultScenario(r)
  if (!isSimulation(r)) return 'Kết quả vận hành · theo dữ liệu đã ghi'
  return `Kịch bản mô phỏng · ${s ? SCENARIO_LABEL[s] : 'không rõ chế độ nước'}`
}

/* ------------------------------------------------------ coverage & text */

/** A category the result does NOT carry as a number, and the engine's reason. */
export interface NotCounted { key: string; label: string; reason: string }

const dict = (v: unknown): Record<string, unknown> =>
  v != null && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {}

/**
 * The four categories a farmer expects to see, and whether this result counts
 * each one. Only categories without a numeric line are listed, each with a
 * reason from the payload or the documented method (docs/CARBON_METHOD.md) —
 * never as a 0 kg line, which would claim a measured zero.
 */
export function notCounted(r: Pick<CarbonResult, 'breakdown' | 'warnings'>): NotCounted[] {
  const lines = r.breakdown ?? []
  const has = (p: (s: string) => boolean) => lines.some((b) => p(String(b.source ?? '')))
  const warnings = (r.warnings ?? []).join(' ')
  const out: NotCounted[] = []

  if (!has((s) => s === 'n2o_fertilizer_direct')) {
    out.push({ key: 'fertilizer', label: 'Phát thải N₂O từ phân bón', reason: 'Chưa đưa vào bản tính: vụ chưa có lượng đạm từ phân bón được ghi nhận.' })
  }
  if (!has((s) => s === 'fuel' || s.startsWith('fuel_'))) {
    out.push({
      key: 'fuel', label: 'Nhiên liệu hoặc điện bơm',
      reason: /kWh bơm điện/.test(warnings)
        ? 'Chưa đưa vào bản tính: có điện bơm được ghi nhưng hệ số lưới điện Việt Nam chưa được cấu hình; vụ không có bản ghi nhiên liệu máy móc.'
        : 'Chưa đưa vào bản tính: vụ không có bản ghi nhiên liệu máy móc; điện bơm chưa có hệ số lưới điện được cấu hình.',
    })
  }
  if (!has((s) => s === 'straw_burning')) {
    const ch4 = lines.find((b) => b.source === 'ch4_rice_cultivation')
    const factors = Object.keys(dict(ch4?.factors_used))
    // `cfoa.<key>` is recorded only when an organic amendment entered SFo.
    const inCh4 = factors.some((k) => k.includes('.cfoa.'))
    out.push({
      key: 'straw', label: 'Quản lý rơm rạ',
      reason: inCh4
        ? 'Không có dòng riêng: rơm vùi/ủ trả lại ruộng đã được tính trong dòng methane (hệ số điều chỉnh chất hữu cơ). Không có bản ghi đốt rơm.'
        : 'Không có dòng riêng: vụ không có bản ghi đốt rơm; rơm không trả lại ruộng không làm tăng methane trong bản tính.',
    })
  }
  return out
}

const UUID = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi

/** An engine warning without the season id, file paths or config keys. */
export function cleanWarning(w: string): string {
  return w
    .replace(/Vụ '[^']*':\s*/g, '')
    .replace(/\s*\((?:docs|backend)\/[^)]*\)/g, '')
    .replace(UUID, 'vụ này')
    .trim()
}

/** The per-kg figure at one precision on every screen (docs: 3 significant decimals). */
export const PER_KG_DECIMALS = 3
