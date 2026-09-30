import type { CarbonMissingInput, CarbonResult } from '../api/carbon'
import type { SeasonMetrics } from '../api/metrics'
import { perKg as perKgText } from '../format'
import type { ActivitySummary } from '../api/crops'
import type { Activity } from '../types'
import { fmtNumber, toNumber, type QuickType } from './activityView'
import type { IconName } from './icons'
import { carbonSourceLabel } from '../carbon/presentation'

/* View model for the season's metrics (Round 4.3).
 *
 * Every figure the server computed reaches the screen unchanged. What this
 * module adds is presentation only: a unit a farmer reads more easily (litres
 * rather than cubic metres, grams rather than a fraction of a kilogram), the
 * per-hectare reading when the plot has a recorded area, and the sentences
 * that say what a number means, what it was computed from and whether the
 * season has the data to trust it.
 *
 * What it never adds: a grade. There is no verified benchmark for water,
 * fertiliser, cost or CO₂e per kg in this system, so no metric is ever called
 * high, low, good, bad, saving or wasteful. It says so in words instead. */

/** Said wherever a reader would otherwise infer "is this good?". */
export const NO_BENCHMARK = 'Chưa có mốc để đánh giá cao hay thấp.'

/** Words a metric may only use once a verified benchmark exists. None does. */
export const JUDGEMENT_WORDS = ['tốt', 'xấu', 'cao hơn', 'thấp hơn', 'tiết kiệm', 'lãng phí', 'đạt chuẩn', 'vượt chuẩn', 'hiệu quả cao', 'hiệu quả thấp']

/* Four groups, in this order, so money never sits beside CO₂e.
 *
 * A farmer reading "chi phí/kg" directly above "CO₂e/kg" concludes that
 * spending less lowers their emissions. Cost is not an input to any emission
 * factor, and the layout has to say so before the words do. */
export type MetricGroupKey = 'resource' | 'cost' | 'carbon'
export type MetricKey = 'water' | 'fertilizer' | 'cost' | 'carbon'

export interface Reading { value: string; unit: string }

export interface MetricAction {
  label: string
  /** A route to open, or… */
  to?: string
  /** …a record form to open in place. */
  create?: QuickType
}

export interface MetricDetail {
  key: MetricKey
  group: MetricGroupKey
  name: string
  icon: IconName
  /** The reading a farmer acts on. null = not enough data, never 0. */
  primary: Reading | null
  /** Methodology units and the totals the primary was computed from. */
  secondary: Reading[]
  meaning: string
  /** "Tính từ …" — only when the figures behind it are all recorded. */
  basis: string | null
  /** The data state in words; `ok` is never implied by colour alone. */
  status: { ok: boolean; text: string }
  /** What is missing, specifically, when there is no primary reading. */
  missing: string | null
  comparison: string
  action: MetricAction | null
  /** Lines of the collapsed "Cách tính và dữ liệu sử dụng" disclosure. */
  method: string[]
}

/* ------------------------------------------------------------ formatting */

const nf = (max: number) => new Intl.NumberFormat('vi-VN', { maximumFractionDigits: max })
const money = nf(0)

/** A readable precision for a converted unit: 63 not 63,46; 5,4 not 5,40.
 *  Display only — the server value is shown beside it at full precision. */
export function readable(n: number): string {
  const a = Math.abs(n)
  return nf(a >= 10 ? 0 : a >= 1 ? 1 : 3).format(n)
}

/** m³ per kg → litres per kg. Presentation only; the server figure is untouched. */
export const litresPerKg = (m3PerKg: number) => m3PerKg * 1000
/** kg per kg → grams per kg. Presentation only. */
export const gramsPerKg = (kgPerKg: number) => kgPerKg * 1000

export const vnd = (n: number) => `${money.format(n)} ₫`

/* ------------------------------------------------------------ season facts */

export interface CostCategory {
  type: string
  label: string
  /** Records of this kind in the season. */
  records: number
  /** How many of them carry a cost. */
  withCost: number
  /** Sum of the costs that were recorded. */
  recordedVnd: number
}

/** Facts read straight off the season's own records and plot. */
export interface SeasonFacts {
  /** Area used for per-hectare readings, and where it came from. */
  areaHa: number | null
  areaSource: 'harvested' | 'plot' | null
  plotAreaHa: number | null
  harvestedAreaHa: number | null
  irrigationRecords: number
  fertilizerRecords: number
  /** Any fertiliser record carries an N/P/K share — the per-kg figure still
   *  uses product mass, which is what the server divides. */
  fertilizerHasNutrient: boolean
  costCategories: CostCategory[]
  /** Total of every cost recorded, and how many records carry one. */
  recordedCostVnd: number
  recordsWithCost: number
  costableRecords: number
}

/** Which payload field holds each activity's cost — mirrors the server's
 *  `_COST_FIELD_BY_ACTIVITY` (read_repo.py). Seeding names it differently. */
const COST_FIELD: Record<string, string> = {
  seeding: 'cost_vnd', fertilizer: 'total_cost_vnd', irrigation: 'total_cost_vnd', pesticide: 'total_cost_vnd',
  fuel: 'total_cost_vnd', straw_management: 'total_cost_vnd', harvest: 'total_cost_vnd',
}

export const COST_LABEL: Record<string, string> = {
  seeding: 'Giống', fertilizer: 'Phân bón', pesticide: 'Thuốc BVTV', fuel: 'Nhiên liệu',
  irrigation: 'Tưới nước', straw_management: 'Xử lý rơm rạ', harvest: 'Thu hoạch',
}

const COST_ORDER = ['seeding', 'fertilizer', 'pesticide', 'fuel', 'irrigation', 'straw_management', 'harvest']

function payload(a: Pick<Activity, 'detail'>): Record<string, unknown> {
  try {
    const v: unknown = JSON.parse(a.detail)
    return v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {}
  } catch { return {} }
}

export function seasonFacts(activities: Pick<Activity, 'type' | 'detail'>[] | null | undefined, plotAreaHa?: number | null): SeasonFacts {
  const list = activities ?? []
  const byType = new Map<string, CostCategory>()
  let harvested = 0; let harvests = 0; let harvestsWithArea = 0
  let fertilizerHasNutrient = false
  for (const a of list) {
    const p = payload(a)
    if (a.type === 'harvest') {
      harvests += 1
      const area = toNumber(p.harvested_area_ha)
      if (area != null && area > 0) { harvested += area; harvestsWithArea += 1 }
    }
    if (a.type === 'fertilizer' && ['nitrogen_percent', 'phosphorus_percent', 'potassium_percent', 'n_percent'].some((k) => toNumber(p[k]) != null)) {
      fertilizerHasNutrient = true
    }
    const field = COST_FIELD[a.type]
    if (!field) continue
    const c = byType.get(a.type) ?? { type: a.type, label: COST_LABEL[a.type] ?? a.type, records: 0, withCost: 0, recordedVnd: 0 }
    c.records += 1
    const cost = toNumber(p[field])
    if (cost != null) { c.withCost += 1; c.recordedVnd += cost }
    byType.set(a.type, c)
  }
  const costCategories = COST_ORDER.map((t) => byType.get(t)).filter((c): c is CostCategory => Boolean(c))
  // Harvested area only when every harvest record carries one; otherwise a
  // partial sum would understate the area and overstate the yield per ha.
  const harvestedAreaHa = harvests > 0 && harvestsWithArea === harvests ? harvested : null
  const plot = plotAreaHa != null && plotAreaHa > 0 ? plotAreaHa : null
  return {
    areaHa: harvestedAreaHa ?? plot,
    areaSource: harvestedAreaHa != null ? 'harvested' : plot != null ? 'plot' : null,
    plotAreaHa: plot,
    harvestedAreaHa,
    irrigationRecords: list.filter((a) => a.type === 'irrigation').length,
    fertilizerRecords: list.filter((a) => a.type === 'fertilizer').length,
    fertilizerHasNutrient,
    costCategories,
    recordedCostVnd: costCategories.reduce((s, c) => s + c.recordedVnd, 0),
    recordsWithCost: costCategories.reduce((s, c) => s + c.withCost, 0),
    costableRecords: costCategories.reduce((s, c) => s + c.records, 0),
  }
}

/** `seasonFacts` from the server's whole-season summary instead of the full
 * list (Round 5.1): the same rules — cost per type, harvested area only when
 * every harvest carries one — applied by the server to every record. */
export function seasonFactsFromSummary(
  summary: Pick<ActivitySummary, 'countByType' | 'costByType' | 'harvests' | 'harvestsWithArea' | 'harvestedAreaHa' | 'fertilizerHasNutrient'> | null | undefined,
  plotAreaHa?: number | null,
): SeasonFacts {
  if (!summary) return seasonFacts(null, plotAreaHa)
  const costCategories = COST_ORDER.filter((t) => summary.costByType[t]).map((t) => ({
    type: t, label: COST_LABEL[t] ?? t, records: summary.costByType[t].records,
    withCost: summary.costByType[t].withCost, recordedVnd: summary.costByType[t].recordedVnd,
  }))
  const harvestedAreaHa = summary.harvests > 0 && summary.harvestsWithArea === summary.harvests ? summary.harvestedAreaHa : null
  const plot = plotAreaHa != null && plotAreaHa > 0 ? plotAreaHa : null
  return {
    areaHa: harvestedAreaHa ?? plot,
    areaSource: harvestedAreaHa != null ? 'harvested' : plot != null ? 'plot' : null,
    plotAreaHa: plot,
    harvestedAreaHa,
    irrigationRecords: summary.countByType.irrigation ?? 0,
    fertilizerRecords: summary.countByType.fertilizer ?? 0,
    fertilizerHasNutrient: summary.fertilizerHasNutrient,
    costCategories,
    recordedCostVnd: costCategories.reduce((s, c) => s + c.recordedVnd, 0),
    recordsWithCost: costCategories.reduce((s, c) => s + c.withCost, 0),
    costableRecords: costCategories.reduce((s, c) => s + c.records, 0),
  }
}

const areaWords = (f: SeasonFacts) => f.areaSource === 'harvested' ? 'diện tích thu hoạch đã ghi' : 'diện tích thửa'

/* ------------------------------------------------------------ yield context */

export interface YieldContext {
  yieldKg: number | null
  areaHa: number | null
  areaLabel: string | null
  /** t/ha — context for the season, not a Carbon input. */
  tonnesPerHa: string | null
  /** What is missing, named, when yield per ha cannot be shown. */
  missing: string | null
}

export function yieldContext(m: Pick<SeasonMetrics, 'yieldKg'> | null | undefined, f: SeasonFacts): YieldContext {
  const y = m?.yieldKg ?? null
  const gaps = [y == null && 'sản lượng thóc (hoạt động Thu hoạch)', f.areaHa == null && 'diện tích thửa hoặc diện tích thu hoạch'].filter(Boolean) as string[]
  return {
    yieldKg: y,
    areaHa: f.areaHa,
    areaLabel: f.areaSource === 'harvested' ? 'Diện tích thu hoạch' : f.areaSource === 'plot' ? 'Diện tích thửa' : null,
    tonnesPerHa: y != null && f.areaHa != null ? readable(y / 1000 / f.areaHa) : null,
    missing: gaps.length ? `Chưa tính được năng suất: thiếu ${gaps.join(' và ')}.` : null,
  }
}

/* ------------------------------------------------------------ the four metrics */

export interface CarbonInputs {
  /** Server readiness, grouped (carbonView). null while unread. */
  fixable: CarbonMissingInput[]
  limitations: CarbonMissingInput[]
  /** The stored result, when the season has one. */
  result: Pick<CarbonResult, 'breakdown' | 'calculated_at' | 'total_co2e_kg' | 'co2e_per_kg'> | null
  stale: boolean
  /** Where the quick-fix hub lives for this season. */
  fixTo: string
}


const needYield = 'Thiếu sản lượng thóc: hãy ghi hoạt động Thu hoạch có số kg.'

function water(m: SeasonMetrics, f: SeasonFacts): MetricDetail {
  const v = m.waterPerKg
  const secondary: Reading[] = []
  if (v != null) secondary.push({ value: perKgText(v, ''), unit: 'm³ / kg lúa' })
  if (m.waterM3 != null) secondary.push({ value: fmtNumber(m.waterM3), unit: 'm³ đã ghi' })
  if (m.waterM3 != null && f.areaHa != null) secondary.push({ value: readable(m.waterM3 / f.areaHa), unit: 'm³ / ha' })
  const missing = v != null ? null
    : m.yieldKg == null ? needYield
      : f.irrigationRecords === 0 ? 'Chưa có hoạt động tưới nào trong vụ.'
        : 'Có lần tưới chưa ghi lượng nước (m³), nên chưa cộng được tổng.'
  return {
    key: 'water', group: 'resource', name: 'Nước tưới', icon: 'irrigation',
    primary: v == null ? null : { value: readable(litresPerKg(v)), unit: 'lít nước / kg lúa' },
    secondary,
    meaning: 'Lượng nước tưới đã ghi để làm ra mỗi kg thóc.',
    basis: v != null && m.waterM3 != null && m.yieldKg != null
      ? `Tính từ ${fmtNumber(m.waterM3)} m³ nước và ${fmtNumber(m.yieldKg)} kg thóc đã ghi.`
      : null,
    status: v != null ? { ok: true, text: 'Đủ dữ liệu để tính' } : { ok: false, text: 'Chưa đủ dữ liệu' },
    missing,
    comparison: NO_BENCHMARK,
    action: v == null && m.yieldKg == null
      ? { label: 'Ghi thu hoạch', create: 'harvest' }
      : { label: 'Xem hoạt động tưới', to: '/farmer/journal?loai=irrigation' },
    method: [
      'Tổng lượng nước (m³) của mọi lần tưới trong vụ ÷ tổng sản lượng thóc (kg). Máy chủ tính; màn hình chỉ đổi 1 m³ = 1.000 lít.',
      'Chỉ tính khi mọi lần tưới đều có lượng nước — thiếu một lần là chưa tính, không thay bằng 0.',
      f.areaHa != null ? `m³/ha dùng ${areaWords(f)}: ${fmtNumber(f.areaHa)} ha.` : 'Chưa có diện tích nên chưa tính m³/ha.',
    ],
  }
}

function fertilizer(m: SeasonMetrics, f: SeasonFacts): MetricDetail {
  const perHa = m.fertilizerKg != null && f.areaHa != null ? m.fertilizerKg / f.areaHa : null
  const v = m.fertilizerPerKg
  const secondary: Reading[] = []
  if (m.fertilizerKg != null) secondary.push({ value: fmtNumber(m.fertilizerKg), unit: 'kg phân đã ghi' })
  if (v != null) secondary.push({ value: readable(gramsPerKg(v)), unit: 'g phân / kg lúa' })
  if (v != null) secondary.push({ value: perKgText(v, ''), unit: 'kg / kg lúa' })
  // kg/ha is what a farmer plans a dose with; it leads whenever the area is known.
  const primary: Reading | null = perHa != null
    ? { value: readable(perHa), unit: 'kg phân / ha' }
    : v != null ? { value: readable(gramsPerKg(v)), unit: 'g phân / kg lúa' } : null
  if (primary && perHa == null) secondary.splice(1, 1)
  const missing = primary ? null
    : f.fertilizerRecords === 0 ? 'Chưa có lần bón phân nào trong vụ.'
      : m.fertilizerKg == null ? 'Có lần bón phân chưa ghi khối lượng (kg), nên chưa cộng được tổng.'
        : m.yieldKg == null ? needYield
          : 'Chưa có diện tích thửa để tính kg/ha.'
  return {
    key: 'fertilizer', group: 'resource', name: 'Phân bón', icon: 'fertilizer',
    primary, secondary,
    meaning: perHa != null
      ? `Khối lượng sản phẩm phân bón (không phải lượng N/P/K) đã ghi trên mỗi ha ${areaWords(f)} — dùng để so với liều bón bạn dự định.`
      : 'Khối lượng sản phẩm phân bón (không phải lượng N/P/K) đã ghi để làm ra mỗi kg thóc.',
    basis: m.fertilizerKg != null && (f.areaHa != null || m.yieldKg != null)
      ? `Tính từ ${fmtNumber(m.fertilizerKg)} kg phân đã ghi${f.areaHa != null ? `, ${fmtNumber(f.areaHa)} ha ${areaWords(f)}` : ''}${m.yieldKg != null ? ` và ${fmtNumber(m.yieldKg)} kg thóc` : ''}.`
      : null,
    status: primary ? { ok: true, text: 'Đủ dữ liệu để tính' } : { ok: false, text: 'Chưa đủ dữ liệu' },
    missing,
    comparison: NO_BENCHMARK,
    action: !primary && m.yieldKg == null && m.fertilizerKg != null
      ? { label: 'Ghi thu hoạch', create: 'harvest' }
      : { label: 'Xem hoạt động bón phân', to: '/farmer/journal?loai=fertilizer' },
    method: [
      'Tính theo khối lượng sản phẩm phân bón đã ghi (kg bao phân), không phải lượng dưỡng chất N/P/K.',
      f.fertilizerHasNutrient
        ? 'Tỷ lệ đạm bạn ghi được dùng cho phần tính Carbon, không dùng cho chỉ số này.'
        : 'Chưa có tỷ lệ N/P/K trong các lần bón đã ghi.',
      'kg/kg lúa = tổng kg phân ÷ tổng kg thóc (máy chủ tính); g/kg chỉ là cách viết khác (× 1.000).',
      f.areaHa != null ? `kg/ha dùng ${areaWords(f)}: ${fmtNumber(f.areaHa)} ha.` : 'Chưa có diện tích nên chưa tính kg/ha.',
    ],
  }
}

function cost(m: SeasonMetrics, f: SeasonFacts): MetricDetail {
  // The server reports cost only when every record that can carry one does.
  const complete = m.costPerKg != null || (m.completeness.cost && f.costableRecords > 0)
  const total = complete && f.recordsWithCost > 0 ? f.recordedCostVnd : null
  const secondary: Reading[] = []
  if (m.costPerKg != null) secondary.push({ value: money.format(m.costPerKg), unit: '₫ / kg lúa' })
  if (!complete && f.recordsWithCost > 0) {
    secondary.push({ value: money.format(f.recordedCostVnd), unit: `₫ đã ghi ở ${f.recordsWithCost}/${f.costableRecords} hoạt động — chưa phải tổng` })
  }
  const without = f.costableRecords - f.recordsWithCost
  const missing = total != null
    ? (m.costPerKg == null && m.yieldKg == null ? needYield : null)
    : f.costableRecords === 0 ? 'Chưa có hoạt động nào để ghi chi phí.'
      : `${without} hoạt động chưa ghi chi phí.`
  return {
    key: 'cost', group: 'cost', name: 'Tổng chi phí đã ghi', icon: 'money',
    primary: total == null ? null : { value: money.format(total), unit: '₫ đã ghi' },
    secondary,
    meaning: 'Tiền vật tư, nhiên liệu và dịch vụ bạn đã nhập cùng các hoạt động. Đây không phải tổng chi phí sản xuất.',
    basis: total != null ? `Cộng chi phí của ${f.recordsWithCost} hoạt động đã ghi${m.costPerKg != null && m.yieldKg != null ? `, chia cho ${fmtNumber(m.yieldKg)} kg thóc` : ''}.` : null,
    status: total != null ? { ok: true, text: 'Mọi hoạt động đã có chi phí' } : { ok: false, text: 'Chưa đủ dữ liệu chi phí' },
    missing,
    comparison: NO_BENCHMARK,
    action: { label: 'Bổ sung chi phí trong Nhật ký', to: '/farmer/journal' },
    method: [
      'Chỉ cộng chi phí bạn nhập trong từng hoạt động. Nhân công và thuê máy chưa có ô nhập riêng nên chưa được tính.',
      'Khi còn hoạt động chưa ghi chi phí, hệ thống không tính ₫/kg — để con số không bỏ sót phần chưa ghi.',
      'Chi phí không phải đầu vào của Carbon.',
    ],
  }
}

function carbon(m: SeasonMetrics, c: CarbonInputs | null): MetricDetail {
  const total = m.totalCo2eKg
  const perKg = m.co2ePerKg
  const r = c?.result ?? null
  const top = r && r.breakdown.length ? [...r.breakdown].sort((a, b) => b.co2e_kg - a.co2e_kg)[0] : null
  const fixable = c?.fixable.length ?? 0
  const limits = c?.limitations.length ?? 0
  // Total first, in tonnes once it passes a tonne; the per-kg intensity second.
  const primary: Reading | null = total == null ? null
    : total >= 1000 ? { value: readable(total / 1000), unit: 't CO₂e cả vụ' } : { value: readable(total), unit: 'kg CO₂e cả vụ' }
  const secondary: Reading[] = []
  if (primary && perKg != null) secondary.push({ value: perKgText(perKg, ''), unit: 'kg CO₂e / kg lúa' })
  if (primary && total != null && total >= 1000) secondary.push({ value: fmtNumber(Math.round(total)), unit: 'kg CO₂e cả vụ' })
  const missing = primary ? null
    : fixable ? `Còn thiếu ${fixable} thông tin để tính Carbon.`
      : limits ? `${limits} hạng mục chưa có hệ số phát thải đã xác minh — không cần bạn nhập thêm.`
        : 'Vụ chưa có kết quả tính Carbon.'
  return {
    key: 'carbon', group: 'carbon', name: 'Tổng phát thải của vụ', icon: 'carbon',
    primary, secondary,
    meaning: 'Lượng khí nhà kính ước tính cho cả vụ, quy về CO₂ tương đương.',
    basis: primary
      ? [top ? `Nguồn đóng góp nhiều nhất: ${carbonSourceLabel(top)}.` : null,
        r?.calculated_at ? `Tính lúc ${new Date(r.calculated_at).toLocaleString('vi-VN', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })}.` : null]
        .filter(Boolean).join(' ') || null
      : null,
    status: primary
      ? c?.stale ? { ok: false, text: 'Cần tính lại — dữ liệu đã đổi sau lần tính' } : { ok: true, text: 'Kết quả mới nhất' }
      : { ok: false, text: fixable ? `Thiếu ${fixable} thông tin` : limits ? 'Vướng giới hạn hệ số' : 'Chưa tính' },
    missing,
    comparison: 'Chưa có mốc so sánh cho phát thải của vụ này.',
    action: primary
      ? { label: c?.stale ? 'Tính lại Carbon' : 'Xem kết quả Carbon', to: c?.fixTo ?? '/farmer/carbon' }
      : fixable ? { label: `Bổ sung ${fixable} thông tin`, to: c?.fixTo ?? '/farmer/carbon' }
        : { label: 'Xem Carbon của vụ', to: c?.fixTo ?? '/farmer/carbon' },
    method: [
      'Máy chủ tính theo phương pháp IPCC 2019 với bộ hệ số đã xác minh; màn hình không ước đoán khi thiếu dữ liệu.',
      'kg CO₂e/kg lúa = tổng phát thải ÷ sản lượng thóc đã ghi.',
      ...(limits ? [`Giới hạn phương pháp (không phải do bạn nhập thiếu): ${c!.limitations.map((x) => x.label).join('; ')}.`] : []),
      'Chi phí không được dùng để tính Carbon.',
    ],
  }
}

/** The season's four metric rows, each in its semantic group. */
export function metricDetails(m: SeasonMetrics, facts: SeasonFacts, carbonInputs: CarbonInputs | null = null): MetricDetail[] {
  return [water(m, facts), fertilizer(m, facts), cost(m, facts), carbon(m, carbonInputs)]
}

export interface MetricGroupView {
  key: MetricGroupKey
  title: string
  description: string
  items: MetricDetail[]
}

const GROUPS: { key: MetricGroupKey; title: string; description: string }[] = [
  { key: 'resource', title: 'Hiệu quả tài nguyên', description: 'Nước và phân bón đã ghi, quy về mỗi kg lúa và mỗi ha.' },
  { key: 'cost', title: 'Chi phí trực tiếp đã ghi', description: 'Tiền bạn đã nhập cùng hoạt động. Không dùng để tính CO₂e.' },
  { key: 'carbon', title: 'Phát thải Carbon', description: 'Tính từ dữ liệu canh tác theo phương pháp IPCC — không liên quan tới chi phí.' },
]

/** The same four metrics, grouped so cost and Carbon are visibly separate. */
export function metricGroups(m: SeasonMetrics, facts: SeasonFacts, carbonInputs: CarbonInputs | null = null): MetricGroupView[] {
  const views = metricDetails(m, facts, carbonInputs)
  return GROUPS.map((g) => ({ ...g, items: views.filter((v) => v.group === g.key) }))
}

/* ------------------------------------------------------------ Home summary */

export interface SummaryItem {
  key: 'water' | 'fertilizer'
  label: string
  icon: IconName
  value: Reading | null
  hint: string
}

/** Home's two resource readings: the easy unit and one short sentence. The
 *  arithmetic, basis and methodology live on Performance. */
export function homeSummary(m: SeasonMetrics | null | undefined, f: SeasonFacts): SummaryItem[] {
  if (!m) return []
  const w = water(m, f); const fz = fertilizer(m, f)
  return [
    { key: 'water', label: 'Nước tưới', icon: 'irrigation', value: w.primary, hint: w.primary ? 'Nước đã ghi cho mỗi kg lúa' : (w.missing ?? 'Chưa đủ dữ liệu') },
    { key: 'fertilizer', label: 'Phân bón', icon: 'fertilizer', value: fz.primary, hint: fz.primary ? (fz.primary.unit.includes('/ ha') ? 'Phân đã bón trên mỗi ha' : 'Phân đã bón cho mỗi kg lúa') : (fz.missing ?? 'Chưa đủ dữ liệu') },
  ]
}

/** The journal line on Home: a count of records, not a performance figure. */
export const journalLine = (count: number) => count > 0 ? `Nhật ký: ${count} hoạt động đã ghi` : 'Nhật ký: chưa có hoạt động nào'
