// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Activity } from '../types'

/* Round 4.1 — an invalid quick-fix must look unsaveable at the button, and the
 * seed's demo marker must never become (or silently replace) a farmer's note. */

const updateActivity = vi.fn()
vi.mock('../api/activities', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/activities')>()
  return { ...actual, updateActivity: (...a: unknown[]) => updateActivity(...a) }
})

const { ActivitySheetForm } = await import('./ActivityForms')

const MARKER = 'DEMO / SYNTHETIC DATA — NOT FIELD DATA, NOT OFFICIAL MRV DATA'
const SEASON = { id: 'season-1', label: 'DEMO-HT-2026 · Thửa demo 1.1' }
const straw = (note: string | null): Activity => ({
  id: 'act-straw', cropSeasonId: SEASON.id, occurredAt: '2026-09-06T00:00:00Z', type: 'straw_management',
  detail: JSON.stringify({ method: 'incorporated', straw_mass_kg: 800, days_before_cultivation: null, dry_matter_fraction: null, returned_to_field: null, note }),
  recorder: '', source: 'web',
})
const irrigation = (note: string | null): Activity => ({
  id: 'act-irr', cropSeasonId: SEASON.id, occurredAt: '2026-09-13T00:00:00Z', type: 'irrigation',
  detail: JSON.stringify({ method: 'awd', water_volume_m3: 10, note }), recorder: '', source: 'web',
})

beforeEach(() => updateActivity.mockReset().mockResolvedValue({
  id: 'x', cropSeasonId: SEASON.id, activityType: 'irrigation', occurredAt: '', note: null, data: {},
  createdBy: null, createdAt: '', updatedAt: '', idempotentReplay: false,
}))
afterEach(cleanup)

const field = (label: RegExp) => screen.getByLabelText(label) as HTMLInputElement
const saveButton = () => screen.getByRole('button', { name: 'Lưu thay đổi' })

describe('quick-fix: an invalid value blocks the save visibly', () => {
  function openQuickFix() {
    render(<ActivitySheetForm mode="edit" activityType="straw_management" season={SEASON} activity={straw(null)}
      fix={['straw_days_before_cultivation', 'straw_dry_matter']} onClose={vi.fn()} onSaved={vi.fn()} />)
  }

  it('-1 is flagged beside the field, linked by aria-describedby, and the button says it cannot save', () => {
    openQuickFix()
    fireEvent.change(field(/Số ngày trước khi làm đất/), { target: { value: '-1' } })
    const input = field(/Số ngày trước khi làm đất/)
    expect(input.getAttribute('aria-invalid')).toBe('true')
    const errId = input.getAttribute('aria-describedby')!.split(' ')[0]
    const err = document.getElementById(errId)!
    expect(err.textContent).toMatch(/âm/)
    // The error sits with its field, not in a banner elsewhere.
    expect(input.closest('[data-field]')!.contains(err)).toBe(true)

    const btn = saveButton()
    expect(btn.getAttribute('aria-disabled')).toBe('true')
    const why = document.getElementById(btn.getAttribute('aria-describedby')!)!
    expect(why.textContent).toMatch(/Chưa lưu được/)

    fireEvent.click(btn)
    expect(updateActivity).not.toHaveBeenCalled()
  })

  it('a fresh quick-fix does not open looking broken', () => {
    openQuickFix()
    expect(saveButton().getAttribute('aria-disabled')).toBeNull()
  })

  it.each([['0,85'], ['0.85']])('accepts %s for the dry-matter fraction and saves 0.85', async (typed) => {
    openQuickFix()
    fireEvent.change(field(/Số ngày trước khi làm đất/), { target: { value: '14' } })
    fireEvent.change(field(/Tỷ lệ chất khô của rơm/), { target: { value: typed } })
    expect(field(/Tỷ lệ chất khô của rơm/).getAttribute('aria-invalid')).not.toBe('true')
    expect(saveButton().getAttribute('aria-disabled')).toBeNull()
    fireEvent.click(saveButton())
    await waitFor(() => expect(updateActivity).toHaveBeenCalledTimes(1))
    expect(updateActivity.mock.calls[0][1].data).toMatchObject({ dryMatterFraction: 0.85, daysBeforeCultivation: 14 })
  })
})

describe('demo marker is metadata, never a note', () => {
  const openEdit = (note: string | null) =>
    render(<ActivitySheetForm mode="edit" activityType="irrigation" season={SEASON} activity={irrigation(note)} onClose={vi.fn()} onSaved={vi.fn()} />)
  const noteBox = () => screen.getByLabelText(/^Ghi chú/) as HTMLTextAreaElement

  it('is shown as a Vietnamese badge, not typed into the note box', () => {
    openEdit(MARKER)
    expect(noteBox().value).toBe('')
    expect(screen.getByTestId('demo-marker').textContent).toMatch(/Dữ liệu minh họa/)
    expect(document.body.textContent).not.toMatch(/SYNTHETIC/)
  })

  it('an untouched note is not sent — the stored marker is left exactly as it was', async () => {
    openEdit(MARKER)
    fireEvent.change(field(/Lượng nước/), { target: { value: '12' } })
    fireEvent.click(saveButton())
    await waitFor(() => expect(updateActivity).toHaveBeenCalledTimes(1))
    expect(updateActivity.mock.calls[0][2]).not.toHaveProperty('note')
  })

  it('a note the farmer writes is saved with the marker kept after it', async () => {
    openEdit(MARKER)
    fireEvent.change(noteBox(), { target: { value: 'Bơm lúc sáng' } })
    fireEvent.click(saveButton())
    await waitFor(() => expect(updateActivity).toHaveBeenCalledTimes(1))
    expect(updateActivity.mock.calls[0][2].note).toBe(`Bơm lúc sáng\n\n${MARKER}`)
  })

  it('a real note beside the marker stays visible and editable', () => {
    openEdit(`Ruộng khô nứt\n\n${MARKER}`)
    expect(noteBox().value).toBe('Ruộng khô nứt')
  })

  it('a record with no marker behaves as before: clearing the note sends null', async () => {
    openEdit('Ghi chú cũ')
    expect(screen.queryByTestId('demo-marker')).toBeNull()
    fireEvent.change(noteBox(), { target: { value: '' } })
    fireEvent.click(saveButton())
    await waitFor(() => expect(updateActivity).toHaveBeenCalledTimes(1))
    expect(updateActivity.mock.calls[0][2].note).toBeNull()
  })
})
