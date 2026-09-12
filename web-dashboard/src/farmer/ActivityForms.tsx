import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from 'react'
import type { Activity, CropSeason, Plot } from '../types'
import {
  createActivity, deleteActivity, updateActivity,
  type ActivityInput, type ActivityWriteResult, type IrrigationMethod, type StrawManagementMethod, type SupportedActivityType,
} from '../api/activities'
import {
  blankToNumber, validateFertilizer, validateHarvest, validateIrrigation,
  validatePesticide, validateSeeding, validateStrawManagement, type FieldErrors,
} from './activityValidation'
import { mapActivityError, type ActivityErrorPresentation } from './activityErrors'
import { nextIdempotencyKey } from './idempotency'
import { ACTIVITY_TITLE, longDay } from './activityView'
import { markSeasonDataChanged } from './data'
import { Ico, type IconName } from './icons'
import { ACTIVITY_ICON, FarmerConfirm, FarmerSheet, IconTile } from './kit'

/* ---------------------------------------------------------------- shared */

export interface SeasonContext { id: string; label: string }

export function toSeasonContext(season: CropSeason, plot?: Plot | null): SeasonContext {
  return { id: season.id, label: plot?.name ? `${season.name} · ${plot.name}` : season.name }
}

export function isSupportedActivityType(type: string): type is SupportedActivityType {
  return type === 'fertilizer' || type === 'irrigation' || type === 'harvest'
    || type === 'seeding' || type === 'pesticide' || type === 'straw_management'
}

export const QUICK_ENTRY_ACTIVE: { type: SupportedActivityType; label: string; hint: string }[] = [
  { type: 'seeding', label: 'Gieo sạ', hint: 'Giống, lượng giống' },
  { type: 'fertilizer', label: 'Bón phân', hint: 'Loại và lượng phân' },
  { type: 'irrigation', label: 'Tưới nước', hint: 'Hình thức, lượng nước' },
  { type: 'pesticide', label: 'Thuốc BVTV', hint: 'Tên thuốc, liều dùng' },
  { type: 'straw_management', label: 'Rơm rạ', hint: 'Cách xử lý rơm' },
  { type: 'harvest', label: 'Thu hoạch', hint: 'Sản lượng thóc' },
]

function parseDetail(activity?: Activity): Record<string, unknown> {
  if (!activity) return {}
  try {
    const v: unknown = JSON.parse(activity.detail)
    return v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {}
  } catch {
    return {}
  }
}

// Numeric detail fields are Postgres `numeric` columns. The read endpoint
// (PostgREST) serializes them as JSON numbers, but the write response
// (psycopg Decimal through FastAPI's Any-typed dict) serializes them as JSON
// strings to avoid float precision loss — same field, two representations
// depending on which endpoint returned it. Accept either.
export const numOrUndef = (v: unknown): number | undefined => {
  if (typeof v === 'number') return Number.isFinite(v) ? v : undefined
  if (typeof v === 'string' && v.trim() !== '') {
    const n = Number(v)
    return Number.isFinite(n) ? n : undefined
  }
  return undefined
}

/* --------------------------------------------------------------- fields */

const OPTIONAL = 'Không bắt buộc'

function LabelText({ label, unit, required, hint }: { label: string; unit?: string; required?: boolean; hint?: string }) {
  return (
    <>
      {label}{unit && ` (${unit})`}
      {required && <span className="form-field__required" aria-hidden="true"> *</span>}
      {hint === OPTIONAL ? <span className="form-field__opt">{OPTIONAL}</span> : hint ? <span className="form-field__hint"> · {hint}</span> : null}
    </>
  )
}

function TextField({ label, value, onChange, type = 'text', required, error, hint, autoFocus }: {
  label: string; value: string; onChange: (v: string) => void; type?: string; required?: boolean
  error?: string; hint?: string; autoFocus?: boolean
}) {
  const id = useId()
  const errId = `${id}-err`
  return (
    <div className="form-field" aria-invalid={error ? 'true' : undefined}>
      <label htmlFor={id}><LabelText label={label} required={required} hint={hint} /></label>
      <input id={id} type={type} value={value} required={required} autoFocus={autoFocus}
        aria-describedby={error ? errId : undefined} onChange={(e) => onChange(e.target.value)} />
      {error && <span id={errId} className="form-field__error" role="alert">{error}</span>}
    </div>
  )
}

function NumberField({ label, value, onChange, unit, required, error, hint }: {
  label: string; value: string; onChange: (v: string) => void; unit?: string; required?: boolean; error?: string; hint?: string
}) {
  const id = useId()
  const errId = `${id}-err`
  return (
    <div className="form-field" aria-invalid={error ? 'true' : undefined}>
      <label htmlFor={id}><LabelText label={label} unit={unit} required={required} hint={hint} /></label>
      <input id={id} type="number" inputMode="decimal" step="any" value={value}
        aria-describedby={error ? errId : undefined} onChange={(e) => onChange(e.target.value)} />
      {error && <span id={errId} className="form-field__error" role="alert">{error}</span>}
    </div>
  )
}

function TextAreaField({ label, value, onChange, hint }: { label: string; value: string; onChange: (v: string) => void; hint?: string }) {
  const id = useId()
  return (
    <div className="form-field form-field--full">
      <label htmlFor={id}><LabelText label={label} hint={hint} /></label>
      <textarea id={id} value={value} onChange={(e) => onChange(e.target.value)} rows={2} />
    </div>
  )
}

function SelectField({ label, value, onChange, options, error }: {
  label: string; value: string; onChange: (v: string) => void; options: { value: string; label: string }[]; error?: string
}) {
  const id = useId()
  const errId = `${id}-err`
  return (
    <div className="form-field" aria-invalid={error ? 'true' : undefined}>
      <label htmlFor={id}>{label}</label>
      <select id={id} value={value} aria-describedby={error ? errId : undefined} onChange={(e) => onChange(e.target.value)}>
        <option value="" disabled>— Chọn —</option>
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
      {error && <span id={errId} className="form-field__error" role="alert">{error}</span>}
    </div>
  )
}

function CheckboxField({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  const id = useId()
  return (
    <div className="form-check">
      <input id={id} type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <label htmlFor={id}>{label}</label>
    </div>
  )
}

function FormSection({ title, icon, children }: { title: string; icon: IconName; children: ReactNode }) {
  return <div className="fw-form__section"><h4><Ico name={icon} />{title}</h4>{children}</div>
}

const IRRIGATION_METHOD_OPTIONS: { value: IrrigationMethod; label: string }[] = [
  { value: 'awd', label: 'Ướt khô xen kẽ (AWD)' },
  { value: 'continuous_flooding', label: 'Ngập liên tục' },
  { value: 'alternate', label: 'Luân phiên' },
  { value: 'other', label: 'Khác' },
]

const STRAW_METHOD_OPTIONS: { value: StrawManagementMethod; label: string }[] = [
  { value: 'incorporated', label: 'Vùi vào đất' },
  { value: 'burned', label: 'Đốt' },
  { value: 'removed', label: 'Mang ra khỏi ruộng' },
  { value: 'composted', label: 'Ủ compost' },
  { value: 'other', label: 'Khác' },
]

const TITLES: Record<SupportedActivityType, { create: string; edit: string }> = {
  fertilizer: { create: 'Bón phân', edit: 'Chỉnh sửa bón phân' },
  irrigation: { create: 'Ghi tưới nước', edit: 'Chỉnh sửa tưới nước' },
  harvest: { create: 'Ghi thu hoạch', edit: 'Chỉnh sửa thu hoạch' },
  seeding: { create: 'Gieo sạ', edit: 'Chỉnh sửa gieo sạ' },
  pesticide: { create: 'Thuốc BVTV', edit: 'Chỉnh sửa thuốc BVTV' },
  straw_management: { create: 'Rơm rạ', edit: 'Chỉnh sửa rơm rạ' },
}

const DATE_LABEL: Record<SupportedActivityType, string> = {
  harvest: 'Ngày thu hoạch', irrigation: 'Ngày thực hiện', seeding: 'Ngày gieo sạ',
  pesticide: 'Ngày phun', straw_management: 'Ngày xử lý', fertilizer: 'Ngày bón',
}

/* --------------------------------------------------------- the form sheet */

export function ActivitySheetForm({ mode, activityType, season, activity, onClose, onSaved }: {
  mode: 'create' | 'edit'
  activityType: SupportedActivityType
  season: SeasonContext
  activity?: Activity
  onClose: () => void
  onSaved: (result: ActivityWriteResult) => void
}) {
  const detail = parseDetail(activity)
  const [date, setDate] = useState(() => (activity?.occurredAt ?? new Date().toISOString()).slice(0, 10))
  const [note, setNote] = useState(() => (typeof detail.note === 'string' ? detail.note : ''))
  const [touched, setTouched] = useState(false)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<ActivityErrorPresentation | null>(null)
  const formRef = useRef<HTMLFormElement>(null)
  const idKeyRef = useRef<string | null>(null)
  useEffect(() => { idKeyRef.current = nextIdempotencyKey(null, 'open') }, [])

  // fertilizer
  const [fName, setFName] = useState(String(detail.fertilizer_name ?? detail.fertilizer_type ?? ''))
  const [fAmount, setFAmount] = useState(numOrUndef(detail.amount_kg)?.toString() ?? '')
  const [fN, setFN] = useState(numOrUndef(detail.nitrogen_percent)?.toString() ?? '')
  const [fP, setFP] = useState(numOrUndef(detail.phosphorus_percent)?.toString() ?? '')
  const [fK, setFK] = useState(numOrUndef(detail.potassium_percent)?.toString() ?? '')
  const [fCost, setFCost] = useState(numOrUndef(detail.total_cost_vnd)?.toString() ?? '')
  const [fMore, setFMore] = useState(detail.phosphorus_percent != null || detail.potassium_percent != null)

  // irrigation
  const [iMethod, setIMethod] = useState(typeof detail.method === 'string' ? detail.method : '')
  const [iWater, setIWater] = useState(numOrUndef(detail.water_volume_m3)?.toString() ?? '')
  const [iPump, setIPump] = useState(detail.pump_energy_kwh != null)
  const [iPumpEnergy, setIPumpEnergy] = useState(numOrUndef(detail.pump_energy_kwh)?.toString() ?? '')
  const [iMore, setIMore] = useState(detail.duration_minutes != null || detail.water_level_cm != null)
  const [iDuration, setIDuration] = useState(numOrUndef(detail.duration_minutes)?.toString() ?? '')
  const [iLevel, setILevel] = useState(numOrUndef(detail.water_level_cm)?.toString() ?? '')
  const [iCost, setICost] = useState(numOrUndef(detail.total_cost_vnd)?.toString() ?? '')

  // harvest
  const [hYield, setHYield] = useState(numOrUndef(detail.yield_kg)?.toString() ?? '')
  const [hArea, setHArea] = useState(numOrUndef(detail.harvested_area_ha)?.toString() ?? '')
  const [hMoisture, setHMoisture] = useState(numOrUndef(detail.moisture_percent)?.toString() ?? '')
  const [hCost, setHCost] = useState(numOrUndef(detail.total_cost_vnd)?.toString() ?? '')

  // seeding
  const [sVariety, setSVariety] = useState(typeof detail.variety_name === 'string' ? detail.variety_name : '')
  const [sSeedKg, setSSeedKg] = useState(numOrUndef(detail.seed_kg)?.toString() ?? '')
  const [sMethod, setSMethod] = useState(typeof detail.seeding_method === 'string' ? detail.seeding_method : '')
  const [sCost, setSCost] = useState(numOrUndef(detail.cost_vnd)?.toString() ?? '')

  // pesticide
  const [pName, setPName] = useState(typeof detail.product_name === 'string' ? detail.product_name : '')
  const [pAmount, setPAmount] = useState(numOrUndef(detail.amount)?.toString() ?? '')
  const [pUnit, setPUnit] = useState(typeof detail.unit === 'string' ? detail.unit : '')
  const [pTarget, setPTarget] = useState(typeof detail.active_ingredient === 'string' ? detail.active_ingredient : '')
  const [pCost, setPCost] = useState(numOrUndef(detail.total_cost_vnd)?.toString() ?? '')

  // straw management
  const [wMethod, setWMethod] = useState(typeof detail.method === 'string' ? detail.method : '')
  const [wMass, setWMass] = useState(numOrUndef(detail.straw_mass_kg)?.toString() ?? '')
  const [wCost, setWCost] = useState(numOrUndef(detail.total_cost_vnd)?.toString() ?? '')

  let input: ActivityInput
  let errors: FieldErrors
  if (activityType === 'fertilizer') {
    const draft = { fertilizerName: fName, amountKg: blankToNumber(fAmount), nitrogenPercent: blankToNumber(fN), phosphorusPercent: blankToNumber(fP), potassiumPercent: blankToNumber(fK), totalCostVnd: blankToNumber(fCost) }
    errors = validateFertilizer(draft)
    input = { activityType: 'fertilizer', data: { fertilizerName: draft.fertilizerName, amountKg: draft.amountKg ?? 0, nitrogenPercent: draft.nitrogenPercent, phosphorusPercent: draft.phosphorusPercent, potassiumPercent: draft.potassiumPercent, totalCostVnd: draft.totalCostVnd } }
  } else if (activityType === 'irrigation') {
    const draft = { method: iMethod, waterVolumeM3: blankToNumber(iWater), durationMinutes: blankToNumber(iDuration), waterLevelCm: blankToNumber(iLevel), pumpEnergyKwh: iPump ? blankToNumber(iPumpEnergy) : null, totalCostVnd: blankToNumber(iCost) }
    errors = validateIrrigation(draft)
    input = { activityType: 'irrigation', data: { method: (draft.method || 'other') as IrrigationMethod, waterVolumeM3: draft.waterVolumeM3, durationMinutes: draft.durationMinutes, waterLevelCm: draft.waterLevelCm, pumpEnergyKwh: draft.pumpEnergyKwh, totalCostVnd: draft.totalCostVnd } }
  } else if (activityType === 'harvest') {
    const draft = { yieldKg: blankToNumber(hYield), harvestedAreaHa: blankToNumber(hArea), moisturePercent: blankToNumber(hMoisture), totalCostVnd: blankToNumber(hCost) }
    errors = validateHarvest(draft)
    input = { activityType: 'harvest', data: { yieldKg: draft.yieldKg ?? 0, harvestedAreaHa: draft.harvestedAreaHa, moisturePercent: draft.moisturePercent, totalCostVnd: draft.totalCostVnd } }
  } else if (activityType === 'seeding') {
    const draft = { seedKg: blankToNumber(sSeedKg), costVnd: blankToNumber(sCost) }
    errors = validateSeeding(draft)
    input = { activityType: 'seeding', data: { varietyName: sVariety.trim() || null, seedKg: draft.seedKg ?? 0, seedingMethod: sMethod.trim() || null, costVnd: draft.costVnd } }
  } else if (activityType === 'pesticide') {
    const draft = { productName: pName, amount: blankToNumber(pAmount), unit: pUnit, totalCostVnd: blankToNumber(pCost) }
    errors = validatePesticide(draft)
    input = { activityType: 'pesticide', data: { productName: draft.productName, activeIngredient: pTarget.trim() || null, amount: draft.amount ?? 0, unit: draft.unit, totalCostVnd: draft.totalCostVnd } }
  } else {
    const draft = { method: wMethod, strawMassKg: blankToNumber(wMass), totalCostVnd: blankToNumber(wCost) }
    errors = validateStrawManagement(draft)
    input = { activityType: 'straw_management', data: { method: (draft.method || 'other') as StrawManagementMethod, strawMassKg: draft.strawMassKg, totalCostVnd: draft.totalCostVnd } }
  }
  const hasErrors = Object.keys(errors).length > 0
  const err = (key: string) => (touched ? errors[key] : undefined)

  async function submit() {
    setPending(true)
    setError(null)
    try {
      const occurredAt = `${date}T00:00:00Z`
      const trimmedNote = note.trim() || null
      let result: ActivityWriteResult
      if (mode === 'create') {
        idKeyRef.current = nextIdempotencyKey(idKeyRef.current, 'retry')
        result = await createActivity(season.id, input, { occurredAt, note: trimmedNote, idempotencyKey: idKeyRef.current! })
      } else {
        result = await updateActivity(activity!.id, input, { occurredAt, note: trimmedNote })
      }
      idKeyRef.current = nextIdempotencyKey(idKeyRef.current, 'success')
      onSaved(result)
    } catch (caught) {
      setError(mapActivityError(caught))
    } finally {
      setPending(false)
    }
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setTouched(true)
    if (hasErrors) {
      requestAnimationFrame(() => formRef.current?.querySelector<HTMLElement>('[aria-invalid="true"] input, [aria-invalid="true"] select')?.focus())
      return
    }
    void submit()
  }

  const saveLabel = pending ? 'Đang lưu…' : mode === 'edit' ? 'Lưu thay đổi' : activityType === 'harvest' ? 'Lưu thu hoạch' : 'Lưu hoạt động'
  const look = ACTIVITY_ICON[activityType]

  let main: ReactNode
  let cost: ReactNode
  if (activityType === 'fertilizer') {
    main = <>
      <TextField label="Loại phân" value={fName} onChange={setFName} error={err('fertilizerName')} required />
      <div className="form-grid">
        <NumberField label="Lượng bón" unit="kg" value={fAmount} onChange={setFAmount} error={err('amountKg')} required />
        <NumberField label="Hàm lượng đạm" unit="%" value={fN} onChange={setFN} error={err('nitrogenPercent')} hint={OPTIONAL} />
      </div>
      <details className="activity-form__disclosure" open={fMore} onToggle={(e) => setFMore((e.target as HTMLDetailsElement).open)}>
        <summary>Thông tin dinh dưỡng khác</summary>
        <div className="form-grid">
          <NumberField label="Hàm lượng lân" unit="%" value={fP} onChange={setFP} error={err('phosphorusPercent')} />
          <NumberField label="Hàm lượng kali" unit="%" value={fK} onChange={setFK} error={err('potassiumPercent')} />
        </div>
      </details>
    </>
    cost = <NumberField label="Chi phí vật tư" unit="đ" value={fCost} onChange={setFCost} hint={OPTIONAL} error={err('totalCostVnd')} />
  } else if (activityType === 'irrigation') {
    main = <>
      <SelectField label="Hình thức tưới" value={iMethod} onChange={setIMethod} options={IRRIGATION_METHOD_OPTIONS} error={err('method')} />
      <NumberField label="Lượng nước" unit="m³" value={iWater} onChange={setIWater} hint={OPTIONAL} error={err('waterVolumeM3')} />
      <CheckboxField label="Sử dụng máy bơm" checked={iPump} onChange={setIPump} />
      {iPump && <NumberField label="Năng lượng bơm" unit="kWh" value={iPumpEnergy} onChange={setIPumpEnergy} error={err('pumpEnergyKwh')} />}
      <details className="activity-form__disclosure" open={iMore} onToggle={(e) => setIMore((e.target as HTMLDetailsElement).open)}>
        <summary>Thông tin khác</summary>
        <div className="form-grid">
          <NumberField label="Thời gian tưới" unit="phút" value={iDuration} onChange={setIDuration} error={err('durationMinutes')} />
          <NumberField label="Mực nước ruộng" unit="cm" value={iLevel} onChange={setILevel} />
        </div>
      </details>
    </>
    cost = <NumberField label="Chi phí vật tư" unit="đ" value={iCost} onChange={setICost} hint={OPTIONAL} error={err('totalCostVnd')} />
  } else if (activityType === 'harvest') {
    main = <>
      <NumberField label="Sản lượng thu hoạch" unit="kg" value={hYield} onChange={setHYield} error={err('yieldKg')} required />
      <div className="form-grid">
        <NumberField label="Diện tích thu hoạch" unit="ha" value={hArea} onChange={setHArea} hint={OPTIONAL} error={err('harvestedAreaHa')} />
        <NumberField label="Độ ẩm" unit="%" value={hMoisture} onChange={setHMoisture} hint={OPTIONAL} error={err('moisturePercent')} />
      </div>
    </>
    cost = <NumberField label="Chi phí" unit="đ" value={hCost} onChange={setHCost} hint={OPTIONAL} error={err('totalCostVnd')} />
  } else if (activityType === 'seeding') {
    main = <>
      <TextField label="Giống" value={sVariety} onChange={setSVariety} hint={OPTIONAL} />
      <div className="form-grid">
        <NumberField label="Lượng giống" unit="kg" value={sSeedKg} onChange={setSSeedKg} error={err('seedKg')} required />
        <TextField label="Phương pháp gieo" value={sMethod} onChange={setSMethod} hint={OPTIONAL} />
      </div>
    </>
    cost = <NumberField label="Chi phí vật tư" unit="đ" value={sCost} onChange={setSCost} hint={OPTIONAL} error={err('costVnd')} />
  } else if (activityType === 'pesticide') {
    main = <>
      <TextField label="Tên thuốc" value={pName} onChange={setPName} error={err('productName')} required />
      <div className="form-grid">
        <NumberField label="Lượng sử dụng" value={pAmount} onChange={setPAmount} error={err('amount')} required />
        <TextField label="Đơn vị" value={pUnit} onChange={setPUnit} hint="ví dụ: kg, lít, gói" error={err('unit')} required />
      </div>
      <TextField label="Mục đích / đối tượng" value={pTarget} onChange={setPTarget} hint={OPTIONAL} />
    </>
    cost = <NumberField label="Chi phí vật tư" unit="đ" value={pCost} onChange={setPCost} hint={OPTIONAL} error={err('totalCostVnd')} />
  } else {
    main = <>
      <SelectField label="Cách xử lý rơm rạ" value={wMethod} onChange={setWMethod} options={STRAW_METHOD_OPTIONS} error={err('method')} />
      {wMethod === 'burned' && (
        <p className="fw-disclaimer"><Ico name="info" />Hình thức xử lý này sẽ được ghi nhận cho tính toán phát thải khi phương pháp tính khả dụng.</p>
      )}
      <NumberField label="Lượng rơm rạ" unit="kg" value={wMass} onChange={setWMass} hint={OPTIONAL} error={err('strawMassKg')} />
    </>
    cost = <NumberField label="Chi phí" unit="đ" value={wCost} onChange={setWCost} hint={OPTIONAL} error={err('totalCostVnd')} />
  }

  return (
    <FarmerSheet title={TITLES[activityType][mode]} subtitle={season.label} icon={look.icon} tone={look.tone} onClose={onClose} busy={pending}>
      <form className="activity-form" ref={formRef} onSubmit={handleSubmit} noValidate>
        <p className="fw-form__ctx"><Ico name="plot" /><span>Vụ <b>{season.label}</b></span></p>
        <p className="fw-form__legend">Trường có dấu <span className="form-field__required" aria-hidden="true">*</span> là bắt buộc.</p>
        <FormSection title="Thời gian" icon="calendar">
          <TextField label={DATE_LABEL[activityType]} type="date" value={date} onChange={setDate} required autoFocus />
        </FormSection>
        <FormSection title="Thông tin chính" icon={look.icon}>{main}</FormSection>
        <FormSection title="Chi phí" icon="money">{cost}</FormSection>
        <FormSection title="Ghi chú" icon="journal">
          <TextAreaField label="Ghi chú" value={note} onChange={setNote} hint={OPTIONAL} />
        </FormSection>

        {error && (
          <div className="fw-form__error" role="alert">
            {error.message}
            {error.retryable && <button type="button" className="fw-btn fw-btn--ghost fw-btn--sm" onClick={() => void submit()}>Thử lại</button>}
          </div>
        )}

        <div className="fw-form__footer">
          <button type="button" className="fw-btn fw-btn--ghost" onClick={onClose} disabled={pending}>Hủy</button>
          <button type="submit" className="fw-btn" disabled={pending}>{saveLabel}</button>
        </div>
      </form>
    </FarmerSheet>
  )
}

/* -------------------------------------------------------------- delete */

const DELETE_COPY: Record<SupportedActivityType, { title: string; body: string }> = {
  fertilizer: { title: 'Xóa hoạt động', body: 'Xóa bản ghi bón phân này?\n\nBản ghi sẽ không còn được dùng trong nhật ký và tính toán hiệu suất.' },
  irrigation: { title: 'Xóa hoạt động', body: 'Xóa bản ghi tưới nước này?\n\nBản ghi sẽ không còn được dùng trong nhật ký và tính toán hiệu suất.' },
  harvest: { title: 'Xóa bản ghi thu hoạch', body: 'Xóa bản ghi thu hoạch?\n\nSản lượng này sẽ không còn được dùng để tính các chỉ số trên mỗi kg sản phẩm.' },
  seeding: { title: 'Xóa hoạt động', body: 'Xóa bản ghi gieo sạ này?\n\nBản ghi sẽ không còn được dùng trong nhật ký và tính toán hiệu suất.' },
  pesticide: { title: 'Xóa hoạt động', body: 'Xóa bản ghi thuốc BVTV này?\n\nBản ghi sẽ không còn được dùng trong nhật ký và tính toán hiệu suất.' },
  straw_management: { title: 'Xóa hoạt động', body: 'Xóa bản ghi xử lý rơm rạ này?\n\nBản ghi sẽ không còn được dùng trong nhật ký, tính toán hiệu suất và không còn đóng góp vào tính toán phát thải.' },
}

function DeleteActivityDialog({ activity, onCancel, onDeleted }: { activity: Activity; onCancel: () => void; onDeleted: () => void }) {
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<ActivityErrorPresentation | null>(null)
  const type = isSupportedActivityType(activity.type) ? activity.type : 'fertilizer'
  const copy = DELETE_COPY[type]

  async function confirm() {
    setPending(true)
    setError(null)
    try {
      await deleteActivity(activity.id)
      onDeleted()
    } catch (caught) {
      setError(mapActivityError(caught))
      setPending(false)
    }
  }

  return (
    <FarmerConfirm
      title={copy.title}
      body={<>{copy.body}{error && <><br /><br /><b style={{ color: 'var(--fw-danger)' }}>{error.message}</b></>}</>}
      confirmLabel="Xóa"
      busy={pending}
      onConfirm={() => void confirm()}
      onCancel={onCancel}
    />
  )
}

/* ---------------------------------------------------------- mutation hub */

function successMessage(mode: 'create' | 'edit', type: SupportedActivityType, result: ActivityWriteResult): string {
  if (mode === 'create' && type === 'harvest') {
    const y = numOrUndef(result.data.yield_kg)
    const kg = y !== undefined ? new Intl.NumberFormat('vi-VN').format(y) : ''
    return `Đã ghi nhận thu hoạch ${kg} kg. Các chỉ số hiệu suất đã được cập nhật.`
  }
  return mode === 'edit' ? 'Đã lưu thay đổi.' : 'Đã lưu hoạt động.'
}

const deletedMessage = (type: SupportedActivityType) => (type === 'harvest' ? 'Đã xóa bản ghi thu hoạch.' : 'Đã xóa hoạt động.')

type FlowState =
  | { kind: 'create'; type: SupportedActivityType; season: SeasonContext }
  | { kind: 'edit'; activity: Activity; season: SeasonContext }
  | { kind: 'delete'; activity: Activity; season: SeasonContext }
  | null

/**
 * Owns the currently-open create/edit/delete surface plus the post-mutation
 * message. A page renders `.node` exactly once; after a write, every cached
 * read derived from that season is invalidated.
 */
export function useActivityMutations() {
  const [state, setState] = useState<FlowState>(null)
  const [flash, setFlash] = useState<string | null>(null)
  const [version, setVersion] = useState(0)

  useEffect(() => {
    if (!flash) return
    const t = setTimeout(() => setFlash(null), 6000)
    return () => clearTimeout(t)
  }, [flash])

  const openCreate = (type: SupportedActivityType, season: SeasonContext) => setState({ kind: 'create', type, season })
  const openEdit = (activity: Activity, season: SeasonContext) => setState({ kind: 'edit', activity, season })
  const openDelete = (activity: Activity, season: SeasonContext) => setState({ kind: 'delete', activity, season })
  const close = () => setState(null)
  const done = (seasonId: string, message: string) => {
    setState(null)
    setFlash(message)
    setVersion((v) => v + 1)
    markSeasonDataChanged(seasonId)
  }

  let node: ReactNode = null
  if (state?.kind === 'delete') {
    const type = isSupportedActivityType(state.activity.type) ? state.activity.type : 'fertilizer'
    node = <DeleteActivityDialog activity={state.activity} onCancel={close} onDeleted={() => done(state.season.id, deletedMessage(type))} />
  } else if (state) {
    const type = state.kind === 'create' ? state.type : (isSupportedActivityType(state.activity.type) ? state.activity.type : 'fertilizer')
    node = (
      <ActivitySheetForm
        mode={state.kind}
        activityType={type}
        season={state.season}
        activity={state.kind === 'edit' ? state.activity : undefined}
        onClose={close}
        onSaved={(result) => done(state.season.id, successMessage(state.kind, type, result))}
      />
    )
  }

  return { openCreate, openEdit, openDelete, flash, node, version }
}

export type ActivityMutations = ReturnType<typeof useActivityMutations>

/* --------------------------------------------------------- quick actions */

export function QuickActions({ seasons, mutations, compact, loading }: { seasons: SeasonContext[]; mutations: ActivityMutations; compact?: boolean; loading?: boolean }) {
  const [picking, setPicking] = useState<SupportedActivityType | null>(null)
  const none = !loading && seasons.length === 0

  function click(type: SupportedActivityType) {
    if (!seasons.length) return
    if (seasons.length === 1) { mutations.openCreate(type, seasons[0]); return }
    setPicking(type)
  }

  return (
    <>
      <div className={`fw-quick${compact ? ' fw-quick--compact' : ''}`}>
        {QUICK_ENTRY_ACTIVE.map(({ type, label, hint }) => {
          const look = ACTIVITY_ICON[type]
          return (
            <button key={type} type="button" className={`fw-qa tone-${look.tone}`} aria-label={label} disabled={loading || none} onClick={() => click(type)}>
              <IconTile name={look.icon} tone={look.tone} size={compact ? 'sm' : 'md'} />
              <span className="fw-qa__label"><b>{label}</b><small>{hint}</small></span>
            </button>
          )
        })}
      </div>
      {none && <p className="fw-note">Chưa có vụ đang canh tác để ghi hoạt động.</p>}
      {picking && (
        <FarmerSheet title="Chọn vụ cần ghi" subtitle={ACTIVITY_TITLE[picking]} icon={ACTIVITY_ICON[picking].icon} tone={ACTIVITY_ICON[picking].tone} onClose={() => setPicking(null)}>
          <div className="fw-pick fw-pick--list">
            {seasons.map((s) => (
              <button key={s.id} type="button" onClick={() => { const t = picking; setPicking(null); mutations.openCreate(t, s) }}>
                <IconTile name="seeding" tone="leaf" size="sm" />{s.label}
              </button>
            ))}
          </div>
        </FarmerSheet>
      )}
    </>
  )
}

/* --------------------------------------------------- Journal "Ghi hoạt động" */

export function AddActivityCta({ season, mutations }: { season: SeasonContext; mutations: ActivityMutations }) {
  const [pickerOpen, setPickerOpen] = useState(false)
  return (
    <>
      <button type="button" className="fw-btn" onClick={() => setPickerOpen(true)}><Ico name="plus" />Ghi hoạt động</button>
      {pickerOpen && (
        <FarmerSheet title="Ghi hoạt động" subtitle={season.label} icon="journal" tone="leaf" onClose={() => setPickerOpen(false)}>
          <div className="fw-pick">
            {QUICK_ENTRY_ACTIVE.map(({ type, label }) => (
              <button key={type} type="button" onClick={() => { setPickerOpen(false); mutations.openCreate(type, season) }}>
                <IconTile name={ACTIVITY_ICON[type].icon} tone={ACTIVITY_ICON[type].tone} size="sm" />{label}
              </button>
            ))}
          </div>
        </FarmerSheet>
      )}
    </>
  )
}

/* ------------------------------------------------------ journal row actions */

export function ActivityDetailActions({ activity, season, mutations }: { activity: Activity; season: SeasonContext; mutations: ActivityMutations }) {
  if (!isSupportedActivityType(activity.type)) return null
  return (
    <>
      <button type="button" className="fw-btn fw-btn--soft" onClick={() => mutations.openEdit(activity, season)}><Ico name="edit" />Chỉnh sửa</button>
      <button type="button" className="fw-btn fw-btn--danger" onClick={() => mutations.openDelete(activity, season)}><Ico name="delete" />Xóa hoạt động</button>
    </>
  )
}

export function ActivityCardActions({ activity, season, mutations }: { activity: Activity; season: SeasonContext; mutations: ActivityMutations }) {
  if (!isSupportedActivityType(activity.type)) return null
  const what = `${ACTIVITY_TITLE[activity.type] ?? activity.type} ${longDay(activity.occurredAt.slice(0, 10))}`
  return (
    <>
      <button type="button" className="fw-iconbtn" aria-label={`Sửa bản ghi ${what}`} title="Sửa" onClick={() => mutations.openEdit(activity, season)}><Ico name="edit" /></button>
      <button type="button" className="fw-iconbtn fw-iconbtn--danger" aria-label={`Xóa bản ghi ${what}`} title="Xóa" onClick={() => mutations.openDelete(activity, season)}><Ico name="delete" /></button>
    </>
  )
}
