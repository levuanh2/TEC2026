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

/**
 * Number input -> number | null respecting the blank-vs-zero rule (brief §12):
 * an empty string must stay `null` (unknown), never become 0.
 */
export function blankToNumber(raw: string): number | null {
  const trimmed = raw.trim()
  if (trimmed === '') return null
  const n = Number(trimmed)
  return Number.isNaN(n) ? null : n
}
