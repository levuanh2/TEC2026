import type { IconName } from '../icons'
import { label as vocab } from '../vocab'
type Payload = Record<string, unknown>

export interface ActivityPresentation { label: string; summary: string; detail?: string }

const missing = 'Chưa có dữ liệu'

/** The demo seed writes English scaffolding into free-text fields — a product
 *  called "Demo pesticide", a note reading "Demo harvest". It names the raw
 *  activity type in English, which is what neither a farmer nor a cooperative
 *  manager should read. The Farmer timeline already refused it; Management
 *  printed it verbatim, so `/crop-seasons/:id/activities` showed
 *  "Demo pesticide" against a real tenant.
 *
 *  Matched narrowly, on the seeder's own shape, so a real product name or a
 *  farmer's own note is never swallowed: only "Demo <known activity type>".
 */
const DEMO_PLACEHOLDER = /^demo[\s_-]+(seeding|fertilizer|irrigation|pesticide|fuel|straw[\s_-]?management|harvest|other)$/i
export const isDemoPlaceholder = (v: string | null | undefined): boolean =>
  typeof v === 'string' && DEMO_PLACEHOLDER.test(v.trim())

/** The seed script writes one English disclaimer into every demo row's note
 *  (`backend/scripts/seed_demo_data.py::DEMO_NOTE`). It is a property of the
 *  tenant, not of each activity: a surface says it once, in Vietnamese, as
 *  "Dữ liệu minh họa" — never the English sentence on every row. */
const DEMO_DISCLAIMER = /demo\s*\/\s*synthetic data/i
export const isDemoDisclaimer = (v: string | null | undefined): boolean =>
  typeof v === 'string' && DEMO_DISCLAIMER.test(v)
/** True when any of these activities is seeded demo data. */
export const hasDemoData = (activities: readonly { detail: string }[] | null | undefined): boolean =>
  (activities ?? []).some((a) => DEMO_DISCLAIMER.test(a.detail ?? ''))

const value = (payload: Payload, key: string, unit = ''): string => {
  if (!(key in payload)) return missing
  if (payload[key] == null) return '—'
  const text = String(payload[key])
  if (isDemoPlaceholder(text)) return 'Dữ liệu minh họa'
  return `${text}${unit ? ` ${unit}` : ''}`
}
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
  water_regime: 'Chế độ nước', irrigation_method: 'Hình thức tưới', method: 'Phương pháp', water_volume_m3: 'Nước tưới (m³)',
  // Real payloads carry these; without a label the drawer printed the column.
  duration_minutes: 'Thời gian tưới (phút)', water_level_cm: 'Mực nước (cm)', pump_energy_kwh: 'Điện bơm (kWh)',
  phosphorus_percent: 'Hàm lượng P (%)', potassium_percent: 'Hàm lượng K (%)', moisture_percent: 'Độ ẩm (%)',
  product_name: 'Tên sản phẩm', amount: 'Lượng dùng', unit: 'Đơn vị',
  fuel_type: 'Loại nhiên liệu', amount_liter: 'Lượng (L)', amount_litre: 'Lượng (L)', equipment_name: 'Thiết bị',
  management_method: 'Phương pháp xử lý rơm', straw_amount_kg: 'Khối lượng rơm (kg)', straw_mass_kg: 'Khối lượng rơm (kg)',
  yield_kg: 'Sản lượng (kg)', harvested_area_ha: 'Diện tích thu hoạch (ha)', note: 'Ghi chú',
  cost_vnd: 'Chi phí (đ)', total_cost_vnd: 'Chi phí (đ)', active_ingredient: 'Mục đích / đối tượng',
  days_before_cultivation: 'Số ngày trước khi làm đất', dry_matter_fraction: 'Tỷ lệ chất khô của rơm', returned_to_field: 'Rơm trả lại ruộng',
}
/** Bookkeeping columns. They identify a row to the database, not an activity
 *  to a farmer, and the drawer was printing them: `activity_id` with its raw
 *  uuid, `created_at` and `updated_at` with raw ISO timestamps. */
const INTERNAL_KEY = /^(.*_id|created_at|updated_at|deleted_at|recorded_by|source)$/

/** Stored enums that must be read through the shared dictionary, never
 *  printed: the drawer showed `awd` where it meant "Tưới ngập–khô xen kẽ". */
const ENUM_KEY: Record<string, Parameters<typeof vocab>[0]> = {
  method: 'irrigationMethod', water_regime: 'irrigationMethod', irrigation_method: 'irrigationMethod',
  management_method: 'strawMethod', straw_method: 'strawMethod',
  fuel_type: 'fuelType',
}

/** Label/value rows for the detail drawer.
 *
 * Three rules, each one a defect this found on real data that the mock tenant
 * never produced, because its payloads happened to carry only mapped keys:
 *   - a bookkeeping column is dropped, not shown;
 *   - a key with no Vietnamese label is dropped rather than printed as the
 *     database column name — a farmer never reads `pump_energy_kwh`;
 *   - a stored enum goes through the dictionary.
 */
/** `method` is one column name with a different meaning per activity: the
 *  irrigation regime on a watering, the straw treatment on a straw record.
 *  Read through the irrigation dictionary regardless, a straw record's
 *  `incorporated` became "Chưa rõ" in the drawer while the list beside it said
 *  "Vùi vào đất" — two stories about one record. */
const METHOD_BY_TYPE: Record<string, { kind: Parameters<typeof vocab>[0]; label: string }> = {
  straw_management: { kind: 'strawMethod', label: 'Phương pháp xử lý rơm' },
  irrigation: { kind: 'irrigationMethod', label: 'Hình thức tưới' },
}

export function activityFields(detail: string, type?: string): { label: string; value: string }[] {
  const payload = parse(detail)
  if (!payload) return detail ? [{ label: 'Chi tiết', value: detail }] : []
  const rows: { label: string; value: string }[] = []
  for (const [k, v] of Object.entries(payload)) {
    if (INTERNAL_KEY.test(k)) continue
    const byType = k === 'method' && type ? METHOD_BY_TYPE[type] : undefined
    const label = byType?.label ?? KEY_LABELS[k]
    if (!label) continue
    if (v == null || v === '') { rows.push({ label, value: '—' }); continue }
    if (typeof v === 'boolean') { rows.push({ label, value: v ? 'Có' : 'Không' }); continue }
    const kind = byType?.kind ?? ENUM_KEY[k]
    const text = String(v)
    rows.push({ label, value: kind ? vocab(kind, text) : isDemoPlaceholder(text) || isDemoDisclaimer(text) ? 'Dữ liệu minh họa' : text })
  }
  return rows
}
