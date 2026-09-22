import type { IconName } from '../icons'
import { label as vocab } from '../vocab'
type Payload = Record<string, unknown>

export interface ActivityPresentation { label: string; summary: string; detail?: string }

const missing = 'Chưa có dữ liệu'
const value = (payload: Payload, key: string, unit = ''): string => !(key in payload) ? missing : payload[key] == null ? '—' : `${String(payload[key])}${unit ? ` ${unit}` : ''}`
const first = (payload: Payload, ...keys: string[]): string => {
  const key = keys.find(candidate => candidate in payload)
  return key ? value(payload, key) : missing
}
const quantity = (payload: Payload, keys: string[], unit: string): string => {
  const key = keys.find(candidate => candidate in payload)
  return key ? value(payload, key, unit) : missing
}
/** A stored enum, always read through the shared dictionary — `awd` and
 *  `incorporated` used to be printed straight onto the screen from here. */
const enumOf = (payload: Payload, kind: Parameters<typeof vocab>[0], ...keys: string[]): string => {
  const key = keys.find((candidate) => candidate in payload)
  if (!key || payload[key] == null) return missing
  return vocab(kind, String(payload[key]))
}
const parse = (detail: string): Payload | null => {
  try { const value: unknown = JSON.parse(detail); return value != null && typeof value === 'object' && !Array.isArray(value) ? value as Payload : null } catch { return null }
}

/** The Vietnamese name of an activity type. Never the stored value.
 *
 * `presentActivity` used to fall back to `type` whenever the detail column was
 * not JSON — which is exactly what the demo seed and every offline row written
 * before the JSON contract look like — so the Management timeline printed
 * `irrigation` where it meant "Nước tưới". */
const TYPE_LABEL: Record<string, string> = {
  seeding: 'Gieo sạ',
  fertilizer: 'Phân bón',
  irrigation: 'Nước tưới',
  pesticide: 'Thuốc bảo vệ thực vật',
  fuel: 'Nhiên liệu',
  straw_management: 'Quản lý rơm rạ',
  harvest: 'Thu hoạch',
}
export const activityTypeLabel = (type: string): string => TYPE_LABEL[type] ?? 'Hoạt động khác'

export function presentActivity(type: string, detail: string): ActivityPresentation {
  const payload = parse(detail)
  if (!payload) return { label: activityTypeLabel(type), summary: detail || missing }
  switch (type) {
    case 'seeding': return { label: 'Gieo sạ', summary: `${value(payload, 'variety_name')} · ${value(payload, 'seed_kg', 'kg')}`, detail: `Phương pháp: ${value(payload, 'seeding_method')}` }
    case 'fertilizer': return { label: 'Phân bón', summary: `${first(payload, 'fertilizer_name', 'fertilizer_type')} · ${value(payload, 'amount_kg', 'kg')}`, detail: `N: ${value(payload, 'nitrogen_percent', '%')}` }
    case 'irrigation': return { label: 'Nước tưới', summary: `${enumOf(payload, 'irrigationMethod', 'water_regime', 'irrigation_method', 'method')} · ${value(payload, 'water_volume_m3', 'm³')}` }
    case 'pesticide': return { label: 'Thuốc bảo vệ thực vật', summary: `${value(payload, 'product_name')} · ${value(payload, 'amount')}`, detail: `Đơn vị: ${value(payload, 'unit')}` }
    case 'fuel': return { label: 'Nhiên liệu', summary: `${enumOf(payload, 'fuelType', 'fuel_type')} · ${quantity(payload, ['amount_liter', 'amount_litre'], 'L')}`, detail: `Thiết bị: ${value(payload, 'equipment_name')}` }
    case 'straw_management': return { label: 'Quản lý rơm rạ', summary: `${enumOf(payload, 'strawMethod', 'management_method', 'method')} · ${quantity(payload, ['straw_amount_kg', 'straw_mass_kg'], 'kg')}` }
    case 'harvest': return { label: 'Thu hoạch', summary: value(payload, 'yield_kg', 'kg'), detail: `Diện tích thu hoạch: ${value(payload, 'harvested_area_ha', 'ha')}` }
    default: return { label: activityTypeLabel(type), summary: missing }
  }
}

// --- Grouping + iconography for the redesigned activity timeline (brief §10) ---

/** Canonical group order farmers read a season in. */
export const ACTIVITY_GROUPS: { type: string; label: string; icon: IconName }[] = [
  { type: 'seeding', label: 'Giống', icon: 'seeding' },
  { type: 'fertilizer', label: 'Phân bón', icon: 'fertilizer' },
  { type: 'irrigation', label: 'Nước', icon: 'irrigation' },
  { type: 'pesticide', label: 'Thuốc BVTV', icon: 'pesticide' },
  { type: 'fuel', label: 'Nhiên liệu', icon: 'fuel' },
  { type: 'straw_management', label: 'Rơm rạ', icon: 'straw' },
  { type: 'harvest', label: 'Thu hoạch', icon: 'harvest' },
]

export const activityIcon = (type: string): string => ACTIVITY_GROUPS.find((g) => g.type === type)?.icon ?? 'journal'

export function groupActivities<T extends { type: string; occurredAt: string }>(items: T[]) {
  return ACTIVITY_GROUPS
    .map((g) => ({ ...g, items: items.filter((a) => a.type === g.type).sort((x, y) => x.occurredAt.localeCompare(y.occurredAt)) }))
    .filter((g) => g.items.length > 0)
}

/** Flat label/value rows for the detail drawer — every payload key, humanised key names. */
const KEY_LABELS: Record<string, string> = {
  variety_name: 'Giống', seed_kg: 'Lượng giống (kg)', seeding_method: 'Phương pháp gieo',
  fertilizer_name: 'Loại phân', fertilizer_type: 'Loại phân', amount_kg: 'Khối lượng (kg)', nitrogen_percent: 'Hàm lượng N (%)', application_no: 'Lần bón',
  water_regime: 'Chế độ nước', irrigation_method: 'Phương pháp tưới', method: 'Phương pháp', water_volume_m3: 'Lượng nước (m³)',
  product_name: 'Tên sản phẩm', amount: 'Lượng dùng', unit: 'Đơn vị',
  fuel_type: 'Loại nhiên liệu', amount_liter: 'Lượng (L)', amount_litre: 'Lượng (L)', equipment_name: 'Thiết bị',
  management_method: 'Phương pháp xử lý', straw_amount_kg: 'Khối lượng rơm (kg)', straw_mass_kg: 'Khối lượng rơm (kg)',
  yield_kg: 'Sản lượng (kg)', harvested_area_ha: 'Diện tích thu hoạch (ha)', note: 'Ghi chú',
  cost_vnd: 'Chi phí (đ)', total_cost_vnd: 'Chi phí (đ)', active_ingredient: 'Mục đích / đối tượng',
  days_before_cultivation: 'Số ngày trước canh tác', dry_matter_fraction: 'Tỷ lệ chất khô', returned_to_field: 'Trả lại ruộng',
}
export function activityFields(detail: string): { label: string; value: string }[] {
  const payload = parse(detail)
  if (!payload) return detail ? [{ label: 'Chi tiết', value: detail }] : []
  return Object.entries(payload).map(([k, v]) => ({
    label: KEY_LABELS[k] ?? k,
    value: v == null || v === '' ? '—' : String(v),
  }))
}
