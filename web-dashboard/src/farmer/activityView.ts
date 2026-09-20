import type { Activity } from '../types'
import type { SeasonMetrics } from '../api/metrics'
import type { Recommendation } from '../api/recommendations'
import type { CarbonMissingInput } from '../api/carbon'

/* Farmer-facing presentation of recorded activities. Management keeps its
 * own `presentActivity`; this one localizes enum values and never invents a
 * value that isn't in the payload (missing -> null, shown as "chưa ghi"). */

type Payload = Record<string, unknown>

const nf = new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 2 })

export function toNumber(v: unknown): number | null {
  if (typeof v === 'number') return Number.isFinite(v) ? v : null
  if (typeof v === 'string' && v.trim() !== '') { const n = Number(v); return Number.isFinite(n) ? n : null }
  return null
}
export const fmtNumber = (n: number) => nf.format(n)
const text = (v: unknown): string | null => (typeof v === 'string' && v.trim() !== '' ? v.trim() : null)
const qty = (v: unknown, unit: string): string | null => { const n = toNumber(v); return n == null ? null : `${nf.format(n)} ${unit}` }
const money = (v: unknown): string | null => { const n = toNumber(v); return n == null ? null : `Chi phí ${nf.format(n)} ₫` }

export const IRRIGATION_METHOD_LABEL: Record<string, string> = {
  awd: 'Ướt khô xen kẽ (AWD)', continuous_flooding: 'Ngập liên tục', alternate: 'Luân phiên', other: 'Khác',
}
export const STRAW_METHOD_LABEL: Record<string, string> = {
  incorporated: 'Vùi vào đất', burned: 'Đốt', removed: 'Mang ra khỏi ruộng', composted: 'Ủ compost', other: 'Khác',
}

export const ACTIVITY_TITLE: Record<string, string> = {
  seeding: 'Gieo sạ', fertilizer: 'Bón phân', irrigation: 'Tưới nước', pesticide: 'Thuốc BVTV',
  straw_management: 'Rơm rạ', harvest: 'Thu hoạch', fuel: 'Nhiên liệu',
}

export interface ActivityView { title: string; value: string | null; meta: string[]; note: string | null }

function parse(detail: string): Payload | null {
  try { const v: unknown = JSON.parse(detail); return v && typeof v === 'object' && !Array.isArray(v) ? (v as Payload) : null } catch { return null }
}

export function viewActivity(activity: Pick<Activity, 'type' | 'detail'>): ActivityView {
  const title = ACTIVITY_TITLE[activity.type] ?? activity.type
  const p = parse(activity.detail)
  if (!p) return { title, value: null, meta: activity.detail ? [activity.detail] : [], note: null }
  const meta = (...items: (string | null)[]) => items.filter((x): x is string => Boolean(x))
  const note = text(p.note)
  switch (activity.type) {
    case 'seeding':
      return { title, value: qty(p.seed_kg, 'kg giống'), meta: meta(text(p.variety_name) && `Giống ${text(p.variety_name)}`, text(p.seeding_method), money(p.cost_vnd)), note }
    case 'fertilizer':
      return { title, value: qty(p.amount_kg, 'kg'), meta: meta(text(p.fertilizer_name) ?? text(p.fertilizer_type), toNumber(p.nitrogen_percent) != null ? `Đạm ${nf.format(toNumber(p.nitrogen_percent)!)}%` : null, money(p.total_cost_vnd)), note }
    case 'irrigation': {
      const method = text(p.water_regime) ?? text(p.irrigation_method) ?? text(p.method)
      return { title, value: qty(p.water_volume_m3, 'm³'), meta: meta(method && (IRRIGATION_METHOD_LABEL[method] ?? method), qty(p.duration_minutes, 'phút'), toNumber(p.water_level_cm) != null ? `Mực nước ${nf.format(toNumber(p.water_level_cm)!)} cm` : null, qty(p.pump_energy_kwh, 'kWh bơm'), money(p.total_cost_vnd)), note }
    }
    case 'pesticide': {
      const amount = toNumber(p.amount)
      return { title, value: amount == null ? null : `${nf.format(amount)} ${text(p.unit) ?? ''}`.trim(), meta: meta(text(p.product_name), text(p.active_ingredient), money(p.total_cost_vnd)), note }
    }
    case 'straw_management': {
      const method = text(p.management_method) ?? text(p.method)
      return { title, value: qty(p.straw_mass_kg ?? p.straw_amount_kg, 'kg'), meta: meta(method && (STRAW_METHOD_LABEL[method] ?? method), money(p.total_cost_vnd)), note }
    }
    case 'harvest':
      return { title, value: qty(p.yield_kg, 'kg thóc'), meta: meta(qty(p.harvested_area_ha, 'ha'), toNumber(p.moisture_percent) != null ? `Độ ẩm ${nf.format(toNumber(p.moisture_percent)!)}%` : null, money(p.total_cost_vnd)), note }
    case 'fuel':
      return { title, value: qty(p.amount_liter ?? p.amount_litre, 'L'), meta: meta(text(p.fuel_type), text(p.equipment_name)), note }
    default:
      return { title, value: null, meta: [], note }
  }
}

/* ------------------------------------------------------------ dates */

const pad = (n: number) => String(n).padStart(2, '0')
export const localDay = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
const WEEKDAY = ['Chủ nhật', 'Thứ Hai', 'Thứ Ba', 'Thứ Tư', 'Thứ Năm', 'Thứ Sáu', 'Thứ Bảy']

/** "Thứ Bảy, 06/09/2026" for a YYYY-MM-DD day key. */
export function longDay(day: string): string {
  const [yy, mm, dd] = day.split('-').map(Number)
  if (!yy || !mm || !dd) return day
  return `${WEEKDAY[new Date(yy, mm - 1, dd).getDay()]}, ${pad(dd)}/${pad(mm)}/${yy}`
}

/** "Hôm nay" / "Hôm qua" / "Thứ Bảy, 06/09/2026" for a YYYY-MM-DD day key. */
export function dayLabel(day: string, now = new Date()): string {
  const y = new Date(now); y.setDate(now.getDate() - 1)
  if (day === localDay(now)) return 'Hôm nay'
  if (day === localDay(y)) return 'Hôm qua'
  return longDay(day)
}

export function groupByDay<T extends { occurredAt: string }>(items: T[]): { day: string; items: T[] }[] {
  const map = new Map<string, T[]>()
  for (const item of [...items].sort((a, b) => b.occurredAt.localeCompare(a.occurredAt))) {
    const day = item.occurredAt.slice(0, 10)
    map.set(day, [...(map.get(day) ?? []), item])
  }
  return [...map.entries()].map(([day, rows]) => ({ day, items: rows }))
}

export function initials(name: string | null | undefined, email: string | null | undefined): string {
  const n = name?.trim()
  if (n) {
    const parts = n.split(/\s+/)
    return `${parts[0][0] ?? ''}${parts.length > 1 ? parts[parts.length - 1][0] : ''}`.toUpperCase()
  }
  return (email?.[0] ?? 'N').toUpperCase()
}

export function greeting(now = new Date()): string {
  const h = now.getHours()
  return h < 11 ? 'Chào buổi sáng' : h < 14 ? 'Chào buổi trưa' : h < 18 ? 'Chào buổi chiều' : 'Chào buổi tối'
}

/* ------------------------------------------------------ attention */

export type QuickType = 'seeding' | 'fertilizer' | 'irrigation' | 'pesticide' | 'straw_management' | 'harvest'

/** Which metric an attention item belongs to. Cost and Carbon are independent
 * metrics fed by different inputs, and the dashboard must not let a farmer read
 * one as a cause of the other: money is never a Carbon input. */
export type MetricGroup = 'resource' | 'carbon'

export interface AttentionItem {
  id: string
  tone: 'warning' | 'info'
  group: MetricGroup
  title: string
  body: string
  /** Opens the create form for this activity type. */
  action?: QuickType
  /** A link the user follows instead — used when the fix is editing existing
   * records or filling the season's methodology panel, not creating anything. */
  link?: { label: string; to: (seasonId: string) => string }
}

const COST_CTA = { label: 'Bổ sung chi phí', to: (id: string) => `/farmer/crop-seasons/${id}/journal` }
const CARBON_CTA = { label: 'Bổ sung dữ liệu Carbon', to: (id: string) => `/farmer/crop-seasons/${id}/carbon` }

/** Only real signals: metric completeness flags + generated data-task recommendations.
 *
 * `carbonMissing` comes from the server's readiness endpoint. When it is
 * available the Carbon item names the actual missing input instead of saying
 * "chưa có kết quả hợp lệ"; the client never derives that list itself. */
export function buildAttention(
  metrics: SeasonMetrics | null | undefined,
  recs: Recommendation[] | null | undefined,
  carbonMissing?: CarbonMissingInput[] | null,
): AttentionItem[] {
  const items: AttentionItem[] = []
  const tasks = (recs ?? []).filter((r) => r.type === 'data_task' && r.status === 'generated')
  const taskCovers = (suffix: string) => tasks.some((t) => t.ruleCode.endsWith(suffix))
  for (const t of tasks) {
    const cost = t.ruleCode.endsWith('.cost')
    items.push({
      id: `rec-${t.id}`, tone: 'warning', group: 'resource', title: t.title, body: t.reason,
      ...(cost ? { link: COST_CTA } : {}),
    })
  }
  if (metrics) {
    if (metrics.yieldKg == null && !taskCovers('.yield')) items.push({ id: 'yield', tone: 'warning', group: 'resource', title: 'Chưa ghi nhận sản lượng thu hoạch', body: 'Các chỉ số trên mỗi kg lúa chỉ tính được khi có sản lượng.', action: 'harvest' })
    if (!metrics.completeness.water && !taskCovers('.water')) items.push({ id: 'water', tone: 'warning', group: 'resource', title: 'Chưa có dữ liệu nước tưới', body: 'Ghi các lần tưới để tính lượng nước trên mỗi kg lúa.', action: 'irrigation' })
    if (!metrics.completeness.fertilizer && !taskCovers('.fertilizer')) items.push({ id: 'fertilizer', tone: 'warning', group: 'resource', title: 'Chưa có dữ liệu phân bón', body: 'Ghi các lần bón để tính lượng phân trên mỗi kg lúa.', action: 'fertilizer' })
    if (!metrics.completeness.cost && !taskCovers('.cost')) items.push({
      id: 'cost', tone: 'warning', group: 'resource', title: 'Thiếu chi phí vật tư',
      // Says which metric it blocks, and which it does NOT.
      body: 'Chi phí / kg lúa chưa tính được khi còn hoạt động thiếu chi phí. Chi phí không ảnh hưởng tới kết quả Carbon.',
      link: COST_CTA,
    })
  }

  // Carbon: prefer the server's named missing inputs over any generic wording.
  // A blocking input the farmer cannot supply (an unverified factor) is counted
  // apart from the ones they can: telling someone to fill in 3 things when only
  // 2 can be filled in is how a screen loses their trust.
  const blocking = (carbonMissing ?? []).filter((m) => m.blocking)
  const fixable = blocking.filter((m) => m.flow !== 'factor_unavailable')
  const limits = blocking.filter((m) => m.flow === 'factor_unavailable')
  if (fixable.length) {
    items.push({
      id: 'carbon', tone: 'warning', group: 'carbon',
      title: fixable.length === 1 ? fixable[0].label : `Thiếu ${fixable.length} dữ liệu để tính Carbon`,
      body: fixable.length === 1 ? fixable[0].detail : fixable.map((m) => m.label).join(' · '),
      link: CARBON_CTA,
    })
  }
  if (limits.length) {
    items.push({
      id: 'carbon-limit', tone: 'info', group: 'carbon',
      title: limits.length === 1 ? limits[0].label : `${limits.length} giới hạn của bộ hệ số`,
      // No CTA: no amount of data entry resolves a factor the set does not have.
      body: `${limits.map((m) => m.detail || m.label).join(' · ')} Không thể bổ sung bằng cách nhập dữ liệu.`,
    })
  }
  if (!blocking.length && metrics && !metrics.completeness.carbon) {
    // Readiness unavailable (or every input present but no calculation stored yet).
    items.push({
      id: 'carbon', tone: 'info', group: 'carbon', title: 'Chưa có kết quả Carbon cho vụ này',
      body: 'Dữ liệu canh tác vẫn được lưu. Mở mục Carbon của vụ để tính.',
      link: CARBON_CTA,
    })
  }
  return items
}
