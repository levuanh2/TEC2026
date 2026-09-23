import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from 'react'
import type { Activity, CropSeason, Plot } from '../types'
import {
  createActivity, deleteActivity, updateActivity,
  type ActivityInput, type ActivityWriteResult, type IrrigationMethod, type StrawManagementMethod, type SupportedActivityType,
} from '../api/activities'
import {
  blankToNumber, numberFormatErrors, requiredErrors, requiredFieldsFor, validateFertilizer, validateHarvest, validateIrrigation,
  validatePesticide, validateSeeding, validateStrawManagement, type FieldErrors,
} from './activityValidation'
import { mapActivityError, type ActivityErrorPresentation } from './activityErrors'
import { nextIdempotencyKey } from './idempotency'
import { ACTIVITY_TITLE, longDay } from './activityView'
import { markSeasonDataChanged } from './data'
import { Ico } from './icons'
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
/** Not required to save the record, but required for the Carbon result. */
const CARBON_NEEDS = 'Cần để tính phát thải'
const NO_GAPS: readonly string[] = []

function LabelText({ label, required, hint }: { label: string; required?: boolean; hint?: string }) {
  return (
    <>
      {label}
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

/** A measurement, not a database column.
 *
 * The unit sits beside the value the way it does on a feed sack or a meter —
 * not folded into the label as "Lượng bón (kg)". `integer` switches the mobile
 * keypad to the numeric pad and the step to 1 for the fields the backend types
 * as `int`; everything else keeps the decimal pad. Blank is preserved as blank
 * all the way to `blankToNumber`, so unknown never becomes zero. */
function NumberField({ label, value, onChange, unit, required, error, hint, help, integer, big, field }: {
  label: string; value: string; onChange: (v: string) => void; unit?: string; required?: boolean
  error?: string; hint?: string; integer?: boolean; big?: boolean
  /** A sentence under the label (range, example) — read out with the field. */
  help?: string
  /** The draft key this field feeds; lets a Carbon quick-fix find and focus it. */
  field?: string
}) {
  const id = useId()
  const errId = `${id}-err`
  const unitId = `${id}-unit`
  const helpId = `${id}-help`
  const described = [error ? errId : null, help ? helpId : null, unit ? unitId : null].filter(Boolean).join(' ') || undefined
  return (
    <div className={`form-field fw-num${big ? ' fw-num--big' : ''}`} aria-invalid={error ? 'true' : undefined} data-field={field}>
      <label htmlFor={id}><LabelText label={label} required={required} hint={hint} /></label>
      {help && <span className="form-field__help" id={helpId}>{help}</span>}
      <span className="fw-num__box">
        {/* Text, not type="number": a number input reports "" for "0,85" or a
          * typo, so the entry would silently become blank. The raw text goes
          * to `blankToNumber` / `numberFormatErrors` instead. */}
        <input id={id} type="text" inputMode={integer ? 'numeric' : 'decimal'} autoComplete="off"
          value={value} aria-describedby={described} aria-required={required || undefined}
          aria-invalid={error ? true : undefined} onChange={(e) => onChange(e.target.value)} />
        {unit && <span className="fw-num__unit" id={unitId}>{unit}</span>}
      </span>
      {error && <span id={errId} className="form-field__error" role="alert"><Ico name="warning" />{error}</span>}
    </div>
  )
}

/** Free text with suggestions. The backend types these as plain strings, so a
 * hard select would break the moment a farmer edits a record holding a value
 * outside the list. A datalist speeds up the common case and keeps the rest. */
function SuggestField({ label, value, onChange, options, required, error, hint }: {
  label: string; value: string; onChange: (v: string) => void; options: string[]
  required?: boolean; error?: string; hint?: string
}) {
  const id = useId()
  const listId = `${id}-list`
  const errId = `${id}-err`
  return (
    <div className="form-field" aria-invalid={error ? 'true' : undefined}>
      <label htmlFor={id}><LabelText label={label} required={required} hint={hint} /></label>
      <input id={id} list={listId} value={value} aria-describedby={error ? errId : undefined}
        onChange={(e) => onChange(e.target.value)} />
      <datalist id={listId}>{options.map((o) => <option key={o} value={o} />)}</datalist>
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

function SelectField({ label, value, onChange, options, error, required, field }: {
  label: string; value: string; onChange: (v: string) => void; options: { value: string; label: string }[]; error?: string
  required?: boolean; field?: string
}) {
  const id = useId()
  const errId = `${id}-err`
  return (
    <div className="form-field" aria-invalid={error ? 'true' : undefined} data-field={field}>
      <label htmlFor={id}><LabelText label={label} required={required} /></label>
      <select id={id} value={value} aria-describedby={error ? errId : undefined} aria-required={required || undefined}
        aria-invalid={error ? true : undefined} onChange={(e) => onChange(e.target.value)}>
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

const MORE_LABEL = 'Thông tin bổ sung'

/** The one disclosure every form uses. Collapsed on a new entry so the default
 * screen is only what a farmer typically records; opened automatically when
 * editing a record that already carries any of these values, so nothing the
 * farmer entered before is hidden from them on the way back in. */
function MoreDetails({ open, onToggle, children }: { open: boolean; onToggle: (v: boolean) => void; children: ReactNode }) {
  return (
    <details className="fw-more" open={open} onToggle={(e) => onToggle((e.target as HTMLDetailsElement).open)}>
      <summary>{MORE_LABEL}</summary>
      <div className="fw-more__body">{children}</div>
    </details>
  )
}

const SEEDING_METHODS = ['Sạ hàng', 'Sạ lan', 'Cấy tay', 'Cấy máy']
const PESTICIDE_UNITS = ['kg', 'lít', 'ml', 'gam', 'gói']

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

/** Where the farmer is in the three steps of recording one activity.
 *
 * The steps are the real ones — the type was picked to open this sheet (1),
 * the essential fields are being filled (2), and saving is the confirmation
 * (3). Nothing here adds a screen; it tells the farmer how much is left. */
export function ActivitySteps({ current }: { current: 1 | 2 | 3 }) {
  const steps = ['Chọn hoạt động', 'Nhập thông tin', 'Xác nhận'] as const
  return (
    <ol className="fw-steps" aria-label="Các bước ghi hoạt động">
      {steps.map((label, i) => {
        const n = (i + 1) as 1 | 2 | 3
        const state = n < current ? 'done' : n === current ? 'current' : 'todo'
        return (
          <li key={label} className={`fw-steps__item is-${state}`} aria-current={state === 'current' ? 'step' : undefined}>
            <span className="fw-steps__n" aria-hidden="true">{state === 'done' ? <Ico name="check" /> : n}</span>
            <span className="fw-steps__label">{label}</span>
          </li>
        )
      })}
    </ol>
  )
}

/* --------------------------------------------------------- the form sheet */

export function ActivitySheetForm({ mode, activityType, season, activity, revealMore = false, fix = NO_GAPS, onClose, onSaved }: {
  mode: 'create' | 'edit'
  activityType: SupportedActivityType
  season: SeasonContext
  activity?: Activity
  /** Open "Thông tin bổ sung" on the way in — used when the field being fixed
   * (Nitơ, rơm) lives there and is, by definition, still blank. */
  revealMore?: boolean
  /** Readiness gap codes the server reports open for THIS record. Each one
   * makes its field required here: Carbon cannot be computed without it, so
   * the form must not call it optional. */
  fix?: readonly string[]
  onClose: () => void
  onSaved: (result: ActivityWriteResult) => void
}) {
  const detail = parseDetail(activity)
  const required = requiredFieldsFor(fix)
  const needs = (field: string) => required.includes(field)
  const reveal = revealMore || fix.length > 0
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
  const [wDays, setWDays] = useState(numOrUndef(detail.days_before_cultivation)?.toString() ?? '')
  const [wDry, setWDry] = useState(numOrUndef(detail.dry_matter_fraction)?.toString() ?? '')
  const [wReturned, setWReturned] = useState<boolean | null>(
    typeof detail.returned_to_field === 'boolean' ? detail.returned_to_field : null,
  )

  // One disclosure for every form. Open it on the way in when the record being
  // edited already carries something that lives inside it — otherwise a farmer
  // would have to guess that their own earlier entry is behind a closed summary.
  const [moreOpen, setMoreOpen] = useState(() => reveal || mode === 'edit' && [
    detail.nitrogen_percent, detail.phosphorus_percent, detail.potassium_percent,
    detail.duration_minutes, detail.water_level_cm, detail.pump_energy_kwh,
    detail.harvested_area_ha, detail.moisture_percent,
    detail.active_ingredient, detail.variety_name,
    detail.days_before_cultivation, detail.dry_matter_fraction, detail.returned_to_field,
    detail.total_cost_vnd, detail.cost_vnd, detail.note,
  ].some((v) => v != null && v !== ''))

  // Arriving from a Carbon quick-fix, the field that needs filling is inside
  // the disclosure and — that being why Carbon flagged it — still blank. Open
  // the section and put the caret in the first blank control in it, so the
  // farmer lands on the field they were sent here to complete rather than on
  // a form that merely contains it somewhere.
  useEffect(() => {
    if (!reveal) return
    const id = requestAnimationFrame(() => {
      const form = formRef.current
      if (!form) return
      // The field a gap names comes first, in form order; otherwise the first
      // blank control of the disclosure, as before.
      const named = Array.from(form.querySelectorAll<HTMLElement>('[data-field]'))
        .filter((el) => required.includes(el.dataset.field ?? ''))
        .map((el) => el.querySelector<HTMLInputElement | HTMLSelectElement>('input, select'))
        .filter((c): c is HTMLInputElement | HTMLSelectElement => Boolean(c))
      const body = form.querySelector('.fw-more__body')
      const controls = body ? Array.from(body.querySelectorAll<HTMLInputElement | HTMLSelectElement>('input, select')) : []
      const target = named.find((c) => !c.value) ?? named[0] ?? controls.find((c) => !c.value) ?? controls[0]
      target?.focus()
    })
    return () => cancelAnimationFrame(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reveal])

  let input: ActivityInput
  let errors: FieldErrors
  if (activityType === 'fertilizer') {
    const draft = { fertilizerName: fName, amountKg: blankToNumber(fAmount), nitrogenPercent: blankToNumber(fN), phosphorusPercent: blankToNumber(fP), potassiumPercent: blankToNumber(fK), totalCostVnd: blankToNumber(fCost) }
    errors = { ...requiredErrors(required, { nitrogenPercent: fN }), ...validateFertilizer(draft), ...numberFormatErrors({ amountKg: fAmount, nitrogenPercent: fN, phosphorusPercent: fP, potassiumPercent: fK, totalCostVnd: fCost }) }
    input = { activityType: 'fertilizer', data: { fertilizerName: draft.fertilizerName, amountKg: draft.amountKg ?? 0, nitrogenPercent: draft.nitrogenPercent, phosphorusPercent: draft.phosphorusPercent, potassiumPercent: draft.potassiumPercent, totalCostVnd: draft.totalCostVnd } }
  } else if (activityType === 'irrigation') {
    const draft = { method: iMethod, waterVolumeM3: blankToNumber(iWater), durationMinutes: blankToNumber(iDuration), waterLevelCm: blankToNumber(iLevel), pumpEnergyKwh: iPump ? blankToNumber(iPumpEnergy) : null, totalCostVnd: blankToNumber(iCost) }
    errors = { ...validateIrrigation(draft), ...numberFormatErrors({ waterVolumeM3: iWater, durationMinutes: iDuration, waterLevelCm: iLevel, pumpEnergyKwh: iPump ? iPumpEnergy : '', totalCostVnd: iCost }, ['durationMinutes']) }
    input = { activityType: 'irrigation', data: { method: (draft.method || 'other') as IrrigationMethod, waterVolumeM3: draft.waterVolumeM3, durationMinutes: draft.durationMinutes, waterLevelCm: draft.waterLevelCm, pumpEnergyKwh: draft.pumpEnergyKwh, totalCostVnd: draft.totalCostVnd } }
  } else if (activityType === 'harvest') {
    const draft = { yieldKg: blankToNumber(hYield), harvestedAreaHa: blankToNumber(hArea), moisturePercent: blankToNumber(hMoisture), totalCostVnd: blankToNumber(hCost) }
    errors = { ...validateHarvest(draft), ...numberFormatErrors({ yieldKg: hYield, harvestedAreaHa: hArea, moisturePercent: hMoisture, totalCostVnd: hCost }) }
    input = { activityType: 'harvest', data: { yieldKg: draft.yieldKg ?? 0, harvestedAreaHa: draft.harvestedAreaHa, moisturePercent: draft.moisturePercent, totalCostVnd: draft.totalCostVnd } }
  } else if (activityType === 'seeding') {
    const draft = { seedKg: blankToNumber(sSeedKg), costVnd: blankToNumber(sCost) }
    errors = { ...validateSeeding(draft), ...numberFormatErrors({ seedKg: sSeedKg, costVnd: sCost }) }
    input = { activityType: 'seeding', data: { varietyName: sVariety.trim() || null, seedKg: draft.seedKg ?? 0, seedingMethod: sMethod.trim() || null, costVnd: draft.costVnd } }
  } else if (activityType === 'pesticide') {
    const draft = { productName: pName, amount: blankToNumber(pAmount), unit: pUnit, totalCostVnd: blankToNumber(pCost) }
    errors = { ...validatePesticide(draft), ...numberFormatErrors({ amount: pAmount, totalCostVnd: pCost }) }
    input = { activityType: 'pesticide', data: { productName: draft.productName, activeIngredient: pTarget.trim() || null, amount: draft.amount ?? 0, unit: draft.unit, totalCostVnd: draft.totalCostVnd } }
  } else {
    const draft = {
      method: wMethod, strawMassKg: blankToNumber(wMass), totalCostVnd: blankToNumber(wCost),
      daysBeforeCultivation: blankToNumber(wDays), dryMatterFraction: blankToNumber(wDry),
    }
    errors = {
      ...requiredErrors(required, { strawMassKg: wMass, daysBeforeCultivation: wDays, dryMatterFraction: wDry, returnedToField: wReturned == null ? '' : String(wReturned) }),
      ...validateStrawManagement(draft),
      ...numberFormatErrors({ strawMassKg: wMass, totalCostVnd: wCost, daysBeforeCultivation: wDays, dryMatterFraction: wDry }, ['daysBeforeCultivation']),
    }
    input = { activityType: 'straw_management', data: {
      method: (draft.method || 'other') as StrawManagementMethod,
      strawMassKg: draft.strawMassKg, totalCostVnd: draft.totalCostVnd,
      daysBeforeCultivation: draft.daysBeforeCultivation, dryMatterFraction: draft.dryMatterFraction,
      returnedToField: wReturned,
    } }
  }
  const hasErrors = Object.keys(errors).length > 0
  // A blank required field is flagged once the farmer tries to save; a value
  // that is typed but wrong ("0,8,5", "-3", "1,2" for a 0-1 ratio) is flagged
  // as soon as it is typed, beside the field, not only after a failed save.
  const RAW: Record<string, string> = {
    amountKg: fAmount, nitrogenPercent: fN, phosphorusPercent: fP, potassiumPercent: fK, waterVolumeM3: iWater,
    durationMinutes: iDuration, waterLevelCm: iLevel, pumpEnergyKwh: iPumpEnergy, yieldKg: hYield, harvestedAreaHa: hArea,
    moisturePercent: hMoisture, seedKg: sSeedKg, amount: pAmount, strawMassKg: wMass, daysBeforeCultivation: wDays,
    dryMatterFraction: wDry,
  }
  const err = (key: string) => (touched || (RAW[key] ?? '').trim() !== '' ? errors[key] : undefined)

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

  // Primary = what a farmer records standing in the field. Optional = everything
  // that belongs to methodology, accounting or afterthought. Nothing that is
  // merely *supported* by the backend gets to sit on the primary screen.
  let main: ReactNode
  let extra: ReactNode
  let costField: ReactNode
  if (activityType === 'fertilizer') {
    main = <>
      <TextField label="Loại phân" value={fName} onChange={setFName} error={err('fertilizerName')} required autoFocus />
      <NumberField label="Lượng bón" unit="kg" value={fAmount} onChange={setFAmount} error={err('amountKg')} required big />
    </>
    // N is a methodology input, not the farmer's action — the backend types it
    // optional, so it does not get equal billing with the amount actually spread.
    extra = <>
      <NumberField label="Hàm lượng đạm" unit="%" value={fN} onChange={setFN} error={err('nitrogenPercent')} field="nitrogenPercent"
        required={needs('nitrogenPercent')} hint={needs('nitrogenPercent') ? CARBON_NEEDS : OPTIONAL} />
      <div className="form-grid">
        <NumberField label="Hàm lượng lân" unit="%" value={fP} onChange={setFP} error={err('phosphorusPercent')} hint={OPTIONAL} />
        <NumberField label="Hàm lượng kali" unit="%" value={fK} onChange={setFK} error={err('potassiumPercent')} hint={OPTIONAL} />
      </div>
    </>
    costField = <NumberField label="Chi phí vật tư" unit="đ" value={fCost} onChange={setFCost} hint={OPTIONAL} error={err('totalCostVnd')} integer />
  } else if (activityType === 'irrigation') {
    main = <>
      <SelectField label="Hình thức tưới" value={iMethod} onChange={setIMethod} options={IRRIGATION_METHOD_OPTIONS} error={err('method')} />
      <NumberField label="Lượng nước" unit="m³" value={iWater} onChange={setIWater} hint="Để trống nếu không đo được" error={err('waterVolumeM3')} big />
    </>
    extra = <>
      <div className="form-grid">
        <NumberField label="Thời gian tưới" unit="phút" value={iDuration} onChange={setIDuration} error={err('durationMinutes')} hint={OPTIONAL} integer />
        <NumberField label="Mực nước ruộng" unit="cm" value={iLevel} onChange={setILevel} hint={OPTIONAL} error={err('waterLevelCm')} />
      </div>
      <CheckboxField label="Có dùng máy bơm" checked={iPump} onChange={setIPump} />
      {iPump && <NumberField label="Năng lượng bơm" unit="kWh" value={iPumpEnergy} onChange={setIPumpEnergy} error={err('pumpEnergyKwh')} hint={OPTIONAL} />}
    </>
    costField = <NumberField label="Chi phí" unit="đ" value={iCost} onChange={setICost} hint={OPTIONAL} error={err('totalCostVnd')} integer />
  } else if (activityType === 'harvest') {
    // Yield is the denominator of every per-kg metric on the Performance page,
    // so it is the one field on the screen and it is set large.
    main = <NumberField label="Sản lượng thu hoạch" unit="kg" value={hYield} onChange={setHYield} error={err('yieldKg')} required big />
    extra = <div className="form-grid">
      <NumberField label="Diện tích thu hoạch" unit="ha" value={hArea} onChange={setHArea} hint={OPTIONAL} error={err('harvestedAreaHa')} />
      <NumberField label="Độ ẩm" unit="%" value={hMoisture} onChange={setHMoisture} hint={OPTIONAL} error={err('moisturePercent')} />
    </div>
    costField = <NumberField label="Chi phí" unit="đ" value={hCost} onChange={setHCost} hint={OPTIONAL} error={err('totalCostVnd')} integer />
  } else if (activityType === 'seeding') {
    main = <>
      <TextField label="Giống" value={sVariety} onChange={setSVariety} hint={OPTIONAL} autoFocus />
      <NumberField label="Lượng giống" unit="kg" value={sSeedKg} onChange={setSSeedKg} error={err('seedKg')} required big />
      <SuggestField label="Phương pháp gieo" value={sMethod} onChange={setSMethod} options={SEEDING_METHODS} hint={OPTIONAL} />
    </>
    extra = null
    costField = <NumberField label="Chi phí vật tư" unit="đ" value={sCost} onChange={setSCost} hint={OPTIONAL} error={err('costVnd')} integer />
  } else if (activityType === 'pesticide') {
    main = <>
      <TextField label="Tên thuốc" value={pName} onChange={setPName} error={err('productName')} required autoFocus />
      <div className="form-grid">
        <NumberField label="Lượng sử dụng" value={pAmount} onChange={setPAmount} error={err('amount')} required />
        <SuggestField label="Đơn vị" value={pUnit} onChange={setPUnit} options={PESTICIDE_UNITS} error={err('unit')} required />
      </div>
    </>
    extra = <TextField label="Hoạt chất / đối tượng phòng trừ" value={pTarget} onChange={setPTarget} hint={OPTIONAL} />
    costField = <NumberField label="Chi phí vật tư" unit="đ" value={pCost} onChange={setPCost} hint={OPTIONAL} error={err('totalCostVnd')} integer />
  } else {
    main = <>
      <SelectField label="Cách xử lý rơm rạ" value={wMethod} onChange={setWMethod} options={STRAW_METHOD_OPTIONS} error={err('method')} />
      {/* Straw burning factors are verified (IPCC 2006 Vol.4 Ch.2 Tables 2.5/2.6),
        * so this IS counted now — the old "khi phương pháp tính khả dụng" wording
        * understated it. Needs the dry-matter fraction below to compute. */}
      {wMethod === 'burned' && (
        <p className="fw-disclaimer"><Ico name="info" />Đốt rơm phát thải CH₄ và N₂O, sẽ được tính vào kết quả carbon của vụ. Cần điền <strong>Tỷ lệ chất khô của rơm</strong> ở phần Thông tin bổ sung.</p>
      )}
      <NumberField label="Lượng rơm rạ" unit="kg" value={wMass} onChange={setWMass} error={err('strawMassKg')} big field="strawMassKg"
        required={needs('strawMassKg')} hint={needs('strawMassKg') ? CARBON_NEEDS : OPTIONAL} />
    </>
    // Carbon-methodology inputs, stated the way a farmer would say them. Blank
    // stays blank: the Carbon Engine still fails closed rather than guessing.
    extra = <>
      {/* Never "Không bắt buộc": the Carbon result cannot be computed for
        * incorporated or burned straw without these two. Required outright
        * when the server reports the gap open for this record. */}
      <NumberField label="Số ngày trước khi làm đất" unit="ngày" value={wDays} onChange={setWDays} error={err('daysBeforeCultivation')} integer
        field="daysBeforeCultivation" required={needs('daysBeforeCultivation')} hint={wMethod === 'incorporated' || needs('daysBeforeCultivation') ? CARBON_NEEDS : undefined}
        help="Số ngày từ lúc vùi rơm tới lúc làm đất cho vụ mới. Số nguyên, từ 0." />
      <NumberField label="Tỷ lệ chất khô của rơm" value={wDry} onChange={setWDry} error={err('dryMatterFraction')}
        field="dryMatterFraction" required={needs('dryMatterFraction')} hint={['incorporated', 'burned', 'composted'].includes(wMethod) || needs('dryMatterFraction') ? CARBON_NEEDS : undefined}
        help="Phần khối lượng còn lại khi rơm khô hẳn. Từ 0 đến 1, ví dụ 0,85 hoặc 0.85." />
      {/* Three states, not a checkbox: "không trả lại" is a real answer the
        * Carbon Engine needs for composted straw, distinct from "chưa ghi". */}
      <SelectField
        field="returnedToField" required={needs('returnedToField')} error={err('returnedToField')}
        label="Rơm có được trả lại ruộng không"
        value={wReturned == null ? '' : wReturned ? 'yes' : 'no'}
        onChange={(v) => setWReturned(v === 'yes' ? true : v === 'no' ? false : null)}
        options={[{ value: 'yes', label: 'Có, trả lại ruộng' }, { value: 'no', label: 'Không, mang đi nơi khác' }]}
      />
    </>
    costField = <NumberField label="Chi phí" unit="đ" value={wCost} onChange={setWCost} hint={OPTIONAL} error={err('totalCostVnd')} integer />
  }

  return (
    <FarmerSheet title={TITLES[activityType][mode]} subtitle={season.label} icon={look.icon} tone={look.tone} onClose={onClose} busy={pending}>
      <form className="activity-form" ref={formRef} onSubmit={handleSubmit} noValidate>
        {mode === 'create' && <ActivitySteps current={pending ? 3 : 2} />}
        {/* The field note's head: which season this is written to, and when it
          * happened. No farmer should have to wonder about the target, and the
          * date is a first-class row rather than a section of its own. */}
        <div className="fw-fn">
          <p className="fw-fn__target"><Ico name="plot" /><span>Ghi vào vụ <b>{season.label}</b></span></p>
          <TextField label={DATE_LABEL[activityType]} type="date" value={date} onChange={setDate} required />
          {/* The native picker writes the date in the browser's own locale
            * (09/23/2026 on an English Chrome). The day is also said the
            * Vietnamese way, so there is never a doubt about day vs month. */}
          {/^\d{4}-\d{2}-\d{2}$/.test(date) && <small className="fw-date-read" aria-live="polite">{longDay(date)}</small>}
        </div>

        {main}

        <MoreDetails open={moreOpen} onToggle={setMoreOpen}>
          {extra}
          {costField}
        </MoreDetails>

        {/* The note stays on the primary screen. Cost and methodology are things
          * the system wants; the note is the farmer's own remark about what
          * happened in the field — and this product is called Nhật ký. Burying
          * it behind a summary is the one optional field that would cost more
          * than it saves. */}
        <TextAreaField label="Ghi chú" value={note} onChange={setNote} hint={OPTIONAL} />

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
  | { kind: 'pick'; season: SeasonContext }
  | { kind: 'create'; type: SupportedActivityType; season: SeasonContext }
  | { kind: 'edit'; activity: Activity; season: SeasonContext; revealMore?: boolean; fix?: readonly string[] }
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

  /** Step 1 of recording: which activity. The one entry point every "Ghi
   * hoạt động" button opens, so Home and the journal start the same way. */
  const openPicker = (season: SeasonContext) => setState({ kind: 'pick', season })
  const openCreate = (type: SupportedActivityType, season: SeasonContext) => setState({ kind: 'create', type, season })
  const openEdit = (activity: Activity, season: SeasonContext, opts?: { revealMore?: boolean; fix?: readonly string[] }) =>
    setState({ kind: 'edit', activity, season, revealMore: opts?.revealMore, fix: opts?.fix })
  const openDelete = (activity: Activity, season: SeasonContext) => setState({ kind: 'delete', activity, season })
  const close = () => setState(null)
  const done = (seasonId: string, message: string) => {
    setState(null)
    setFlash(message)
    setVersion((v) => v + 1)
    markSeasonDataChanged(seasonId)
  }

  let node: ReactNode = null
  if (state?.kind === 'pick') {
    const season = state.season
    node = (
      <FarmerSheet title="Ghi hoạt động" subtitle={season.label} icon="journal" tone="leaf" onClose={close}>
        <ActivitySteps current={1} />
        <div className="fw-pick" role="group" aria-label="Chọn loại hoạt động">
          {QUICK_ENTRY_ACTIVE.map(({ type, label, hint }) => (
            <button key={type} type="button" className={`tone-${ACTIVITY_ICON[type].tone}`} onClick={() => openCreate(type, season)}>
              <IconTile name={ACTIVITY_ICON[type].icon} tone={ACTIVITY_ICON[type].tone} size="sm" />
              <span className="fw-pick__text"><b>{label}</b><small>{hint}</small></span>
            </button>
          ))}
        </div>
      </FarmerSheet>
    )
  } else if (state?.kind === 'delete') {
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
        revealMore={state.kind === 'edit' && state.revealMore}
        fix={state.kind === 'edit' ? state.fix : undefined}
        onClose={close}
        onSaved={(result) => done(state.season.id, successMessage(state.kind, type, result))}
      />
    )
  }

  return { openPicker, openCreate, openEdit, openDelete, flash, node, version }
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
  return <button type="button" className="fw-btn" onClick={() => mutations.openPicker(season)}><Ico name="plus" />Ghi hoạt động</button>
}

/* ------------------------------------------------------ journal row actions */

/** Edit is the action; delete is the exception.
 *
 * They used to sit side by side as two filled buttons of equal weight, which
 * makes destroying a record as easy to hit as correcting one. Delete now reads
 * as a written action set apart and below, and still routes through the same
 * confirmation dialog. */
export function ActivityDetailActions({ activity, season, mutations }: { activity: Activity; season: SeasonContext; mutations: ActivityMutations }) {
  if (!isSupportedActivityType(activity.type)) return null
  return (
    <>
      <button type="button" className="fw-btn fw-btn--soft" onClick={() => mutations.openEdit(activity, season)}><Ico name="edit" />Chỉnh sửa</button>
      <button type="button" className="fw-destroy" onClick={() => mutations.openDelete(activity, season)}>Xóa hoạt động này</button>
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
