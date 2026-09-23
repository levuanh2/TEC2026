// Farmer-friendly validation mirroring backend/schemas.py constraints exactly
// (Field(gt=0), Field(ge=0, le=100), Field(ge=0)) so the form never leans on
// raw Pydantic error JSON (brief FW-2 §10).
export type FieldErrors = Record<string, string>

export interface FertilizerDraft {
  fertilizerName: string
  amountKg: number | null
  nitrogenPercent: number | null
  phosphorusPercent: number | null
  potassiumPercent: number | null
  totalCostVnd: number | null
}

export function validateFertilizer(draft: FertilizerDraft): FieldErrors {
  const errors: FieldErrors = {}
  if (!draft.fertilizerName.trim()) errors.fertilizerName = 'Vui lòng nhập loại phân.'
  if (draft.amountKg == null || draft.amountKg <= 0) errors.amountKg = 'Lượng phân phải lớn hơn 0.'
  for (const [key, label] of [
    ['nitrogenPercent', 'Hàm lượng đạm'],
    ['phosphorusPercent', 'Hàm lượng lân'],
    ['potassiumPercent', 'Hàm lượng kali'],
  ] as const) {
    const v = draft[key]
    if (v != null && (v < 0 || v > 100)) errors[key] = `${label} phải từ 0 đến 100%.`
  }
  if (draft.totalCostVnd != null && draft.totalCostVnd < 0) errors.totalCostVnd = 'Chi phí không thể là số âm.'
  return errors
}

export interface IrrigationDraft {
  method: string
  waterVolumeM3: number | null
  durationMinutes: number | null
  waterLevelCm: number | null
  pumpEnergyKwh: number | null
  totalCostVnd: number | null
}

const IRRIGATION_METHODS = new Set(['awd', 'continuous_flooding', 'alternate', 'other'])

export function validateIrrigation(draft: IrrigationDraft): FieldErrors {
  const errors: FieldErrors = {}
  if (!IRRIGATION_METHODS.has(draft.method)) errors.method = 'Vui lòng chọn hình thức tưới.'
  if (draft.waterVolumeM3 != null && draft.waterVolumeM3 < 0) errors.waterVolumeM3 = 'Lượng nước không thể là số âm.'
  if (draft.durationMinutes != null && draft.durationMinutes < 0) errors.durationMinutes = 'Thời gian tưới không thể là số âm.'
  if (draft.pumpEnergyKwh != null && draft.pumpEnergyKwh < 0) errors.pumpEnergyKwh = 'Năng lượng bơm không thể là số âm.'
  if (draft.totalCostVnd != null && draft.totalCostVnd < 0) errors.totalCostVnd = 'Chi phí không thể là số âm.'
  return errors
}

export interface HarvestDraft {
  yieldKg: number | null
  harvestedAreaHa: number | null
  moisturePercent: number | null
  totalCostVnd: number | null
}

export function validateHarvest(draft: HarvestDraft): FieldErrors {
  const errors: FieldErrors = {}
  if (draft.yieldKg == null || draft.yieldKg <= 0) errors.yieldKg = 'Sản lượng thu hoạch phải lớn hơn 0.'
  if (draft.harvestedAreaHa != null && draft.harvestedAreaHa <= 0) errors.harvestedAreaHa = 'Diện tích thu hoạch phải lớn hơn 0.'
  if (draft.moisturePercent != null && (draft.moisturePercent < 0 || draft.moisturePercent > 100)) errors.moisturePercent = 'Độ ẩm phải từ 0 đến 100%.'
  if (draft.totalCostVnd != null && draft.totalCostVnd < 0) errors.totalCostVnd = 'Chi phí không thể là số âm.'
  return errors
}

export interface SeedingDraft {
  seedKg: number | null
  costVnd: number | null
}

export function validateSeeding(draft: SeedingDraft): FieldErrors {
  const errors: FieldErrors = {}
  if (draft.seedKg == null || draft.seedKg <= 0) errors.seedKg = 'Lượng giống phải lớn hơn 0.'
  if (draft.costVnd != null && draft.costVnd < 0) errors.costVnd = 'Chi phí không thể là số âm.'
  return errors
}

export interface PesticideDraft {
  productName: string
  amount: number | null
  unit: string
  totalCostVnd: number | null
}

export function validatePesticide(draft: PesticideDraft): FieldErrors {
  const errors: FieldErrors = {}
  if (!draft.productName.trim()) errors.productName = 'Vui lòng nhập tên thuốc.'
  if (draft.amount == null || draft.amount <= 0) errors.amount = 'Lượng sử dụng phải lớn hơn 0.'
  if (!draft.unit.trim()) errors.unit = 'Vui lòng nhập đơn vị.'
  if (draft.totalCostVnd != null && draft.totalCostVnd < 0) errors.totalCostVnd = 'Chi phí không thể là số âm.'
  return errors
}

export interface StrawManagementDraft {
  method: string
  strawMassKg: number | null
  totalCostVnd: number | null
  daysBeforeCultivation?: number | null
  dryMatterFraction?: number | null
}

const STRAW_METHODS = new Set(['incorporated', 'removed', 'burned', 'composted', 'other'])

export function validateStrawManagement(draft: StrawManagementDraft): FieldErrors {
  const errors: FieldErrors = {}
  if (!STRAW_METHODS.has(draft.method)) errors.method = 'Vui lòng chọn cách xử lý rơm rạ.'
  if (draft.strawMassKg != null && draft.strawMassKg < 0) errors.strawMassKg = 'Lượng rơm rạ không thể là số âm.'
  if (draft.totalCostVnd != null && draft.totalCostVnd < 0) errors.totalCostVnd = 'Chi phí không thể là số âm.'
  // Mirrors StrawManagementActivityData: ge=0 and gt=0/le=1 respectively.
  if (draft.daysBeforeCultivation != null && draft.daysBeforeCultivation < 0) {
    errors.daysBeforeCultivation = 'Số ngày không thể là số âm.'
  }
  if (draft.dryMatterFraction != null && (draft.dryMatterFraction <= 0 || draft.dryMatterFraction > 1)) {
    errors.dryMatterFraction = 'Tỷ lệ chất khô phải lớn hơn 0 và không quá 1.'
  }
  return errors
}

/**
 * Number input -> number | null respecting the blank-vs-zero rule (brief §12):
 * an empty string must stay `null` (unknown), never become 0.
 *
 * A decimal comma is accepted ("0,85" — the hint the form itself shows a
 * farmer). Anything else that is not a plain decimal is `NaN`, never `null`: a
 * typo must surface as an error through `numberFormatErrors`, not be saved as
 * "unknown" without the farmer noticing.
 */
export function blankToNumber(raw: string): number | null {
  const trimmed = raw.trim()
  if (trimmed === '') return null
  if (!/^[+-]?(\d+([.,]\d+)?|[.,]\d+)$/.test(trimmed)) return Number.NaN
  return Number(trimmed.replace(',', '.'))
}

/**
 * Format errors for the raw text of number fields, keyed like the validators'
 * errors. `integers` lists the keys the backend types as `int`.
 */
export function numberFormatErrors(raw: Record<string, string>, integers: readonly string[] = []): FieldErrors {
  const errors: FieldErrors = {}
  for (const [key, text] of Object.entries(raw)) {
    const n = blankToNumber(text)
    if (n == null) continue
    if (Number.isNaN(n)) errors[key] = 'Vui lòng nhập một số hợp lệ, ví dụ 12 hoặc 0,85.'
    else if (integers.includes(key) && !Number.isInteger(n)) errors[key] = 'Vui lòng nhập số nguyên.'
  }
  return errors
}

/**
 * Carbon readiness gap code (server) → the form field that supplies it.
 *
 * The server decides which inputs are missing; this only says where on the
 * form each one is typed. A code not listed here has no field on this form.
 */
export const GAP_FIELD: Readonly<Record<string, string>> = {
  straw_days_before_cultivation: 'daysBeforeCultivation',
  straw_dry_matter: 'dryMatterFraction',
  straw_mass: 'strawMassKg',
  straw_returned_to_field: 'returnedToField',
  fertilizer_nitrogen: 'nitrogenPercent',
}

const REQUIRED_MESSAGE: Readonly<Record<string, string>> = {
  daysBeforeCultivation: 'Nhập số ngày (số nguyên, từ 0) — cần để tính phát thải.',
  dryMatterFraction: 'Nhập tỷ lệ chất khô từ 0 đến 1, ví dụ 0,85 — cần để tính phát thải.',
  strawMassKg: 'Nhập lượng rơm (kg) — cần để tính phát thải.',
  returnedToField: 'Chọn rơm có được trả lại ruộng không — cần để tính phát thải.',
  nitrogenPercent: 'Nhập hàm lượng đạm (%) — cần để tính phát thải.',
}

/** The fields a set of open readiness gaps makes required, in form order. */
export function requiredFieldsFor(gapCodes: readonly string[]): string[] {
  const wanted = new Set(gapCodes.map((c) => GAP_FIELD[c]).filter(Boolean))
  return Object.keys(REQUIRED_MESSAGE).filter((f) => wanted.has(f))
}

/** A blank value in a field an open Carbon gap depends on. */
export function requiredErrors(required: readonly string[], values: Readonly<Record<string, string>>): FieldErrors {
  const errors: FieldErrors = {}
  for (const key of required) {
    if (key in values && values[key].trim() === '') errors[key] = REQUIRED_MESSAGE[key] ?? 'Trường này cần để tính phát thải.'
  }
  return errors
}
