// Presentation formatting only — NO business math (brief §22). Backend already
// computed every ratio/aggregate; this file only turns a value into a string.

const EMPTY = 'Chưa đủ dữ liệu'

const nf = (max = 1) => new Intl.NumberFormat('vi-VN', { maximumFractionDigits: max })

/** null / undefined -> "Chưa đủ dữ liệu"; a real 0 stays "0". */
export function num(value: number | null | undefined, opts: { suffix?: string; max?: number; empty?: string } = {}): string {
  if (value == null || Number.isNaN(value)) return opts.empty ?? EMPTY
  return `${nf(opts.max ?? 1).format(value)}${opts.suffix ?? ''}`
}

export const kg = (v: number | null | undefined, empty?: string) => num(v, { suffix: ' kg', empty })
export const ha = (v: number | null | undefined, empty?: string) => num(v, { suffix: ' ha', max: 2, empty })
export const m3 = (v: number | null | undefined, empty?: string) => num(v, { suffix: ' m³', max: 2, empty })
export const vnd = (v: number | null | undefined, empty?: string) =>
  v == null ? (empty ?? EMPTY) : `${nf(0).format(v)} ₫`
/* Precision policy (Round 5, docs/WEB_LOGIC_UAT_ROUND5.md §precision):
 *   CO₂e/kg, nước/kg, phân/kg → 3 decimals (0,997 never becomes "1")
 *   ₫/kg and every ₫ amount → whole đồng (1.090 ₫, never 1.090,385 ₫)
 *   totals (kg, kg CO₂e)    → up to 1 decimal where the screen shows one */
export const vndPerKg = (v: number | null | undefined, empty?: string) =>
  v == null ? (empty ?? EMPTY) : nf(0).format(v)
export const perKg = (v: number | null | undefined, unit: string, empty?: string) =>
  v == null ? (empty ?? EMPTY) : `${nf(3).format(v)}${unit ? ` ${unit}` : ''}`

/** ISO date/datetime -> dd/MM/yyyy (locale-stable, no time). */
export function date(value: string | null | undefined): string {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value
  return d.toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit', year: 'numeric' })
}

export function dateTime(value: string | null | undefined): string {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value
  return d.toLocaleString('vi-VN', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

export const place = (...parts: (string | null | undefined)[]) =>
  parts.filter(Boolean).join(', ') || '—'

export const shortHash = (h: string | null | undefined) => (h ? `${h.slice(0, 10)}…` : '—')

/** Days elapsed since an ISO date, today inclusive of the start day — pure
 * presentation math on a real recorded date (planting date), never a
 * fabricated/estimated duration. */
export function daysSince(value: string | null | undefined): number | null {
  if (!value) return null
  const start = new Date(value)
  if (Number.isNaN(start.getTime())) return null
  const days = Math.floor((Date.now() - start.getTime()) / 86_400_000)
  return days >= 0 ? days : null
}

/** "Thửa <tên>" without doubling when the name already starts with "Thửa". */
export const plotTitle = (name: string | null | undefined) =>
  !name ? 'Thửa ruộng' : /^thửa\b/i.test(name.trim()) ? name.trim() : `Thửa ${name.trim()}`
