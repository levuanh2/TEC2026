// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Activity } from '../types'

/* Farmer activity forms V2 — field-operation entry flows.
 *
 * These cover the contract the forms have to the backend (blank stays null, a
 * real zero survives, required fields block the write) and the behaviour a
 * farmer depends on (the write lands on the season they picked, editing does
 * not silently drop values they entered before, a slow save cannot be
 * double-submitted, a failed save keeps what they typed).
 */

const createActivity = vi.fn()
const updateActivity = vi.fn()
const deleteActivity = vi.fn()

vi.mock('../api/activities', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/activities')>()
  return {
    ...actual,
    createActivity: (...a: unknown[]) => createActivity(...a),
    updateActivity: (...a: unknown[]) => updateActivity(...a),
    deleteActivity: (...a: unknown[]) => deleteActivity(...a),
  }
})

const { ActivitySheetForm, QuickActions, useActivityMutations } = await import('./ActivityForms')

const SEASON = { id: 'season-1', label: 'Hè Thu 2026 · Thửa 1.1' }
const OTHER_SEASON = { id: 'season-2', label: 'Thu Đông 2026 · Thửa 1.2' }

const writeResult = (data: Record<string, unknown> = {}) => ({
  id: 'act-new', cropSeasonId: SEASON.id, activityType: 'fertilizer' as const,
  occurredAt: '2026-09-12T00:00:00Z', note: null, data, createdBy: 'u', createdAt: '', updatedAt: '',
  idempotentReplay: false,
})

beforeEach(() => {
  createActivity.mockReset().mockResolvedValue(writeResult())
  updateActivity.mockReset().mockResolvedValue(writeResult())
  deleteActivity.mockReset().mockResolvedValue(undefined)
})
afterEach(cleanup)

function renderForm(props: Partial<Parameters<typeof ActivitySheetForm>[0]> = {}) {
  const onSaved = vi.fn()
  const onClose = vi.fn()
  render(
    <ActivitySheetForm
      mode="create" activityType="fertilizer" season={SEASON}
      onClose={onClose} onSaved={onSaved} {...props}
    />,
  )
  return { onSaved, onClose }
}

/** Type into a labelled field. The label text carries the required marker, so
 *  match on a prefix rather than the exact string. */
function fill(label: string | RegExp, value: string) {
  const field = screen.getByLabelText(label)
  fireEvent.change(field, { target: { value } })
}

/** The submit button relabels itself to "Đang lưu…" mid-flight, so target the
 *  element rather than its text. */
const submitButton = () => document.querySelector('button[type="submit"]') as HTMLButtonElement
const save = () => fireEvent.click(submitButton())
const openMore = () => fireEvent.click(document.querySelector('details.fw-more > summary')!)
const payload = () => createActivity.mock.calls[0][1].data as Record<string, unknown>

/** `<details>` keeps its children in the DOM when closed — that is the point of
 *  the element and how it stays accessible. "Hidden" therefore means *inside a
 *  closed disclosure*, not *absent*. */
function isInsideClosedDisclosure(label: RegExp): boolean {
  const field = screen.queryByLabelText(label)
  if (!field) return false
  const details = field.closest('details')
  return Boolean(details) && !details!.open
}
const disclosureIsOpen = () => Boolean((document.querySelector('details.fw-more') as HTMLDetailsElement)?.open)

/* ------------------------------------------------------------ the six forms */

describe('primary screen holds only what a farmer records in the field', () => {
  it('fertilizer shows the two required facts and hides methodology behind the disclosure', () => {
    renderForm({ activityType: 'fertilizer' })
    expect(screen.getByLabelText(/Loại phân/)).toBeTruthy()
    expect(screen.getByLabelText(/Lượng bón/)).toBeTruthy()
    // N/P/K are Carbon-methodology inputs, not the farmer's action.
    expect(isInsideClosedDisclosure(/Hàm lượng đạm/)).toBe(true)
    openMore()
    expect(disclosureIsOpen()).toBe(true)
  })

  it('harvest leads with yield, the denominator of every per-kg metric', () => {
    renderForm({ activityType: 'harvest' })
    expect(screen.getByLabelText(/Sản lượng thu hoạch/)).toBeTruthy()
    expect(screen.getByLabelText(/Sản lượng thu hoạch/).closest('details')).toBeNull()
    expect(isInsideClosedDisclosure(/Độ ẩm/)).toBe(true)
  })

  it('straw offers the Carbon-methodology fields in plain language, never as jargon', () => {
    renderForm({ activityType: 'straw_management' })
    openMore()
    expect(screen.getByLabelText(/Số ngày trước khi làm đất/)).toBeTruthy()
    expect(screen.getByLabelText(/Tỷ lệ chất khô/)).toBeTruthy()
    // The UI must never surface the emission-factor vocabulary.
    expect(document.body.textContent).not.toMatch(/SFo|CFOA|emission factor/i)
  })

  // Regression: the note was briefly moved inside the disclosure. The real
  // write E2E tags its QA rows through this field and hung for ten minutes on
  // an invisible textarea — but the reason to keep it out is not the test. The
  // note is the farmer's own remark, in a product called Nhật ký; cost and
  // methodology are what the system wants, and those are what get folded away.
  it('keeps the note reachable without opening the disclosure, on every form', () => {
    for (const t of ['seeding', 'fertilizer', 'irrigation', 'pesticide', 'straw_management', 'harvest'] as const) {
      cleanup()
      renderForm({ activityType: t })
      const note = screen.getByLabelText(/^Ghi chú/)
      expect(note.closest('details')).toBeNull()
    }
  })

  it('every form names its disclosure by what it holds, and the disclosure closes the form', () => {
    for (const t of ['seeding', 'fertilizer', 'irrigation', 'pesticide', 'straw_management', 'harvest'] as const) {
      cleanup()
      renderForm({ activityType: t })
      const details = document.querySelector('details.fw-more')!
      const summary = details.querySelector('summary')!.textContent ?? ''
      expect(summary).toMatch(t === 'seeding' ? /^Chi phí/ : /^Thông tin kỹ thuật và chi phí/)
      expect(summary).toMatch(/chi phí/i)
      // Nothing that is always visible sits under the closed summary.
      const note = screen.getByLabelText(/^Ghi chú/)
      expect(note.compareDocumentPosition(details) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    }
  })

  it('irrigation: essentials visible, technical fields and cost behind the disclosure', () => {
    renderForm({ activityType: 'irrigation' })
    const details = document.querySelector('details.fw-more') as HTMLDetailsElement
    expect(details.open).toBe(false)
    expect(details.querySelector('summary')!.textContent).toContain('Thời gian tưới, mực nước, máy bơm · chi phí')
    for (const label of [/^Hình thức tưới/, /^Lượng nước/, /^Ghi chú/]) expect(screen.getByLabelText(label).closest('details')).toBeNull()
    for (const label of [/^Thời gian tưới/, /^Mực nước ruộng/, /^Chi phí/]) expect(screen.getByLabelText(label).closest('details')).toBe(details)
  })
})

describe('required validation blocks the write', () => {
  it('fertilizer refuses a blank name and a non-positive amount', async () => {
    renderForm({ activityType: 'fertilizer' })
    save()
    await waitFor(() => expect(screen.getByText('Vui lòng nhập loại phân.')).toBeTruthy())
    expect(screen.getByText('Lượng phân phải lớn hơn 0.')).toBeTruthy()
    expect(createActivity).not.toHaveBeenCalled()
  })

  it('harvest keeps yield_kg > 0', async () => {
    renderForm({ activityType: 'harvest' })
    fill(/Sản lượng thu hoạch/, '0')
    save()
    await waitFor(() => expect(screen.getByText('Sản lượng thu hoạch phải lớn hơn 0.')).toBeTruthy())
    expect(createActivity).not.toHaveBeenCalled()
  })
})

describe('null vs zero', () => {
  it('a blank optional number is sent as null, never as an invented 0', async () => {
    renderForm({ activityType: 'fertilizer' })
    fill(/Loại phân/, 'Urê')
    fill(/Lượng bón/, '150')
    save()
    await waitFor(() => expect(createActivity).toHaveBeenCalled())
    const d = payload()
    expect(d.amountKg).toBe(150)
    expect(d.nitrogenPercent).toBeNull()
    expect(d.phosphorusPercent).toBeNull()
    expect(d.totalCostVnd).toBeNull()
  })

  it('a real zero survives where zero is a valid reading', async () => {
    renderForm({ activityType: 'irrigation' })
    fireEvent.change(screen.getByLabelText(/Hình thức tưới/), { target: { value: 'awd' } })
    fill(/Lượng nước/, '0')
    save()
    await waitFor(() => expect(createActivity).toHaveBeenCalled())
    expect(payload().waterVolumeM3).toBe(0)
  })

  it('irrigation water left blank stays unknown rather than becoming zero', async () => {
    renderForm({ activityType: 'irrigation' })
    fireEvent.change(screen.getByLabelText(/Hình thức tưới/), { target: { value: 'awd' } })
    save()
    await waitFor(() => expect(createActivity).toHaveBeenCalled())
    expect(payload().waterVolumeM3).toBeNull()
  })

  it('straw methodology fields stay null when untouched', async () => {
    renderForm({ activityType: 'straw_management' })
    fireEvent.change(screen.getByLabelText(/Cách xử lý rơm rạ/), { target: { value: 'incorporated' } })
    save()
    await waitFor(() => expect(createActivity).toHaveBeenCalled())
    const d = payload()
    expect(d.daysBeforeCultivation).toBeNull()
    expect(d.dryMatterFraction).toBeNull()
    expect(d.returnedToField).toBeNull()
  })
})

describe('submit behaviour', () => {
  it('a successful save reports the write to the caller', async () => {
    const { onSaved } = renderForm({ activityType: 'harvest' })
    fill(/Sản lượng thu hoạch/, '5200')
    save()
    await waitFor(() => expect(onSaved).toHaveBeenCalled())
  })

  it('a failed save keeps the entered values and leaves the sheet open', async () => {
    createActivity.mockRejectedValue(new Error('mạng lỗi'))
    const { onClose, onSaved } = renderForm({ activityType: 'harvest' })
    fill(/Sản lượng thu hoạch/, '5200')
    save()
    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy())
    expect((screen.getByLabelText(/Sản lượng thu hoạch/) as HTMLInputElement).value).toBe('5200')
    expect(onClose).not.toHaveBeenCalled()
    expect(onSaved).not.toHaveBeenCalled()
  })

  it('cannot be double-submitted while the write is in flight', async () => {
    let release!: (v: unknown) => void
    createActivity.mockImplementation(() => new Promise((r) => { release = r }))
    renderForm({ activityType: 'harvest' })
    fill(/Sản lượng thu hoạch/, '5200')
    save()
    await waitFor(() => expect(submitButton().disabled).toBe(true))
    save(); save()
    expect(createActivity).toHaveBeenCalledTimes(1)
    await act(async () => { release(writeResult()); })
  })
})

describe('edit mode', () => {
  const existing: Activity = {
    id: 'act-1', cropSeasonId: SEASON.id, occurredAt: '2026-09-01T00:00:00Z', type: 'fertilizer',
    detail: JSON.stringify({ fertilizer_name: 'Urê', amount_kg: 150, nitrogen_percent: 46, total_cost_vnd: 900000 }),
    recorder: 'QA', source: 'web',
  }

  it('opens populated, titled as an edit, and saves through update', async () => {
    renderForm({ mode: 'edit', activityType: 'fertilizer', activity: existing })
    expect((screen.getByLabelText(/Loại phân/) as HTMLInputElement).value).toBe('Urê')
    expect(screen.getByRole('button', { name: 'Lưu thay đổi' })).toBeTruthy()
    save()
    await waitFor(() => expect(updateActivity).toHaveBeenCalled())
    expect(createActivity).not.toHaveBeenCalled()
  })

  it('opens the disclosure when the record already carries optional values', () => {
    renderForm({ mode: 'edit', activityType: 'fertilizer', activity: existing })
    // No click: the farmer's earlier entry must not be hidden behind a summary.
    expect((screen.getByLabelText(/Hàm lượng đạm/) as HTMLInputElement).value).toBe('46')
  })

  it('leaves the disclosure closed when there is nothing optional to show', () => {
    const bare: Activity = { ...existing, detail: JSON.stringify({ fertilizer_name: 'Urê', amount_kg: 150 }) }
    renderForm({ mode: 'edit', activityType: 'fertilizer', activity: bare })
    expect(disclosureIsOpen()).toBe(false)
  })

  it('re-saving an untouched record preserves its optional values', async () => {
    renderForm({ mode: 'edit', activityType: 'fertilizer', activity: existing })
    save()
    await waitFor(() => expect(updateActivity).toHaveBeenCalled())
    const d = updateActivity.mock.calls[0][1].data as Record<string, unknown>
    expect(d.nitrogenPercent).toBe(46)
    expect(d.totalCostVnd).toBe(900000)
  })
})

describe('multi-season targeting', () => {
  function Harness({ seasons }: { seasons: { id: string; label: string }[] }) {
    const mutations = useActivityMutations()
    return <><QuickActions seasons={seasons} mutations={mutations} />{mutations.node}</>
  }

  it('writes straight to the only season when there is one', async () => {
    render(<Harness seasons={[SEASON]} />)
    fireEvent.click(screen.getByRole('button', { name: 'Bón phân' }))
    await waitFor(() => expect(screen.getByRole('dialog')).toBeTruthy())
    expect(document.querySelector('.fw-fn__target')!.textContent).toContain(SEASON.label)
  })

  it('asks which season when there are several, and writes to the one picked', async () => {
    render(<Harness seasons={[SEASON, OTHER_SEASON]} />)
    fireEvent.click(screen.getByRole('button', { name: 'Bón phân' }))
    await waitFor(() => expect(screen.getByRole('dialog', { name: 'Chọn vụ cần ghi' })).toBeTruthy())

    fireEvent.click(screen.getByRole('button', { name: new RegExp(OTHER_SEASON.label) }))
    await waitFor(() => expect(screen.getByRole('dialog', { name: 'Bón phân' })).toBeTruthy())

    const form = screen.getByRole('dialog', { name: 'Bón phân' })
    expect(form.querySelector('.fw-fn__target')!.textContent).toContain(OTHER_SEASON.label)

    fireEvent.change(within(form).getByLabelText(/Loại phân/), { target: { value: 'Urê' } })
    fireEvent.change(within(form).getByLabelText(/Lượng bón/), { target: { value: '10' } })
    fireEvent.click(form.querySelector('button[type="submit"]') as HTMLButtonElement)
    await waitFor(() => expect(createActivity).toHaveBeenCalled())
    // The write must land on the picked season, not the first one offered.
    expect(createActivity.mock.calls[0][0]).toBe(OTHER_SEASON.id)
  })
})

/* ------------------------------------------ Carbon quick-fix entry points */

describe('opened from the Carbon repair hub', () => {
  const fertilizer: Activity = {
    id: 'act-npk', cropSeasonId: SEASON.id, occurredAt: '2026-03-05T00:00:00Z', type: 'fertilizer',
    detail: JSON.stringify({ fertilizer_name: 'NPK', amount_kg: 80 }), recorder: 'u', source: 'web',
  }

  it('revealMore opens the disclosure so the blank Nitơ field is in view', () => {
    renderForm({ mode: 'edit', activity: fertilizer, revealMore: true })
    expect(disclosureIsOpen()).toBe(true)
    expect(screen.getByLabelText(/Hàm lượng đạm/)).toBeTruthy()
  })

  it('without revealMore a record with no methodology values keeps it closed', () => {
    renderForm({ mode: 'edit', activity: fertilizer })
    expect(disclosureIsOpen()).toBe(false)
  })

  it('editing Nitơ from the hub writes to that exact record', async () => {
    renderForm({ mode: 'edit', activity: fertilizer, revealMore: true })
    fill(/Hàm lượng đạm/, '16')
    save()
    await waitFor(() => expect(updateActivity).toHaveBeenCalled())
    expect(updateActivity.mock.calls[0][0]).toBe('act-npk')
    expect(updateActivity.mock.calls[0][1].data.nitrogenPercent).toBe(16)
  })

  it('straw can say "not returned to the field" — false, distinct from unrecorded null', async () => {
    renderForm({ activityType: 'straw_management' })
    fireEvent.change(screen.getByLabelText(/Cách xử lý rơm rạ/), { target: { value: 'composted' } })
    openMore()
    fireEvent.change(screen.getByLabelText(/Rơm có được trả lại ruộng không/), { target: { value: 'no' } })
    save()
    await waitFor(() => expect(createActivity).toHaveBeenCalled())
    expect(payload().returnedToField).toBe(false)
  })
})

/* -------------------------------- straw quick-fix: save and read back */

describe('straw quick-fix persistence', () => {
  // The seeded record from the reproduced bug: incorporated, mass known,
  // methodology fields blank.
  const straw: Activity = {
    id: 'act-straw', cropSeasonId: SEASON.id, occurredAt: '2026-09-06T06:00:00Z', type: 'straw_management',
    detail: JSON.stringify({ method: 'incorporated', straw_mass_kg: 800, total_cost_vnd: null,
      days_before_cultivation: null, dry_matter_fraction: null, returned_to_field: null }),
    recorder: '', source: 'web',
  }
  const sentBody = async () => {
    const { activityDataPayload } = await import('../api/activities')
    return activityDataPayload(updateActivity.mock.calls[0][1])
  }

  it('sends the entered days and dry matter to that exact record, keeping the rest', async () => {
    renderForm({ mode: 'edit', activityType: 'straw_management', activity: straw, revealMore: true })
    fill(/Số ngày trước khi làm đất/, '20')
    fill(/Tỷ lệ chất khô của rơm/, '0.85')
    save()
    await waitFor(() => expect(updateActivity).toHaveBeenCalled())
    expect(updateActivity.mock.calls[0][0]).toBe('act-straw')
    expect(await sentBody()).toEqual({
      method: 'incorporated', straw_mass_kg: 800, total_cost_vnd: null,
      days_before_cultivation: 20, dry_matter_fraction: 0.85, returned_to_field: null,
    })
  })

  it('accepts the decimal comma its own hint shows ("0,85")', async () => {
    renderForm({ mode: 'edit', activityType: 'straw_management', activity: straw, revealMore: true })
    fill(/Tỷ lệ chất khô của rơm/, '0,85')
    save()
    await waitFor(() => expect(updateActivity).toHaveBeenCalled())
    expect((await sentBody()).dry_matter_fraction).toBe(0.85)
  })

  it.each([
    ['85', /không quá 1/],
    ['0', /lớn hơn 0/],
    ['abc', /số hợp lệ/],
  ])('refuses dry matter "%s" instead of saving or rescaling it', async (value, message) => {
    renderForm({ mode: 'edit', activityType: 'straw_management', activity: straw, revealMore: true })
    fill(/Tỷ lệ chất khô của rơm/, value)
    save()
    expect(await screen.findByText(message)).toBeTruthy()
    expect(updateActivity).not.toHaveBeenCalled()
  })

  it.each([
    ['-1', /không thể là số âm/],
    ['1.5', /số nguyên/],
  ])('refuses days "%s"', async (value, message) => {
    renderForm({ mode: 'edit', activityType: 'straw_management', activity: straw, revealMore: true })
    fill(/Số ngày trước khi làm đất/, value)
    save()
    expect(await screen.findByText(message)).toBeTruthy()
    expect(updateActivity).not.toHaveBeenCalled()
  })

  it('a real 0 days survives; blank stays null', async () => {
    renderForm({ mode: 'edit', activityType: 'straw_management', activity: straw, revealMore: true })
    fill(/Số ngày trước khi làm đất/, '0')
    save()
    await waitFor(() => expect(updateActivity).toHaveBeenCalled())
    const body = await sentBody()
    expect(body.days_before_cultivation).toBe(0)
    expect(body.dry_matter_fraction).toBeNull()
  })

  it('reopening from the server response shows the persisted values', () => {
    // The write response serializes numeric columns as strings ("0.850").
    const saved: Activity = { ...straw, detail: JSON.stringify({ method: 'incorporated', straw_mass_kg: '800.000',
      total_cost_vnd: null, days_before_cultivation: 20, dry_matter_fraction: '0.850', returned_to_field: true }) }
    renderForm({ mode: 'edit', activityType: 'straw_management', activity: saved })
    expect(disclosureIsOpen()).toBe(true)
    expect((screen.getByLabelText(/Số ngày trước khi làm đất/) as HTMLInputElement).value).toBe('20')
    expect((screen.getByLabelText(/Tỷ lệ chất khô của rơm/) as HTMLInputElement).value).toBe('0.85')
    expect((screen.getByLabelText(/Rơm có được trả lại ruộng không/) as HTMLSelectElement).value).toBe('yes')
  })
})
