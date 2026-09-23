// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Activity } from '../types'

/* Round 4 P0.2 — the Carbon quick-fix form must agree with Carbon readiness.
 * When the server says a straw record lacks "số ngày" and "tỷ lệ chất khô",
 * the form opened from "Sửa ngay" calls those fields required, never
 * "Không bắt buộc", validates them in place, and focuses the first one. */

const updateActivity = vi.fn()
vi.mock('../api/activities', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/activities')>()
  return { ...actual, updateActivity: (...a: unknown[]) => updateActivity(...a) }
})

const { ActivitySheetForm } = await import('./ActivityForms')

const SEASON = { id: 'season-1', label: 'DEMO-HT-2026 · Thửa demo 1.1' }
const straw: Activity = {
  id: 'act-straw', cropSeasonId: SEASON.id, occurredAt: '2026-09-06T00:00:00Z', type: 'straw_management',
  detail: JSON.stringify({ method: 'incorporated', straw_mass_kg: 800, days_before_cultivation: null, dry_matter_fraction: null, returned_to_field: null }),
  recorder: '', source: 'web',
}
const GAPS = ['straw_days_before_cultivation', 'straw_dry_matter']

beforeEach(() => updateActivity.mockReset().mockResolvedValue({
  id: 'act-straw', cropSeasonId: SEASON.id, activityType: 'straw_management', occurredAt: '', note: null, data: {},
  createdBy: null, createdAt: '', updatedAt: '', idempotentReplay: false,
}))
afterEach(cleanup)

function open(fix: string[] = GAPS) {
  const onSaved = vi.fn()
  const onClose = vi.fn()
  render(<ActivitySheetForm mode="edit" activityType="straw_management" season={SEASON} activity={straw} fix={fix} onClose={onClose} onSaved={onSaved} />)
  return { onSaved, onClose }
}
const field = (label: RegExp) => screen.getByLabelText(label) as HTMLInputElement
const save = () => fireEvent.click(screen.getByRole('button', { name: 'Lưu thay đổi' }))

describe('Carbon quick-fix contract', () => {
  it('never labels a gap field "Không bắt buộc", and marks it required', () => {
    open()
    for (const re of [/Số ngày trước khi làm đất/, /Tỷ lệ chất khô của rơm/]) {
      const input = field(re)
      const label = document.querySelector(`label[for="${input.id}"]`)!.textContent!
      expect(label).not.toMatch(/Không bắt buộc/)
      expect(label).toMatch(/\*/)
      expect(input.getAttribute('aria-required')).toBe('true')
    }
  })

  it('also avoids "Không bắt buộc" outside a quick-fix for incorporated straw', () => {
    open([])
    const label = document.querySelector(`label[for="${field(/Tỷ lệ chất khô của rơm/).id}"]`)!.textContent!
    expect(label).not.toMatch(/Không bắt buộc/)
    expect(label).toMatch(/Cần để tính phát thải/)
  })

  it('puts the caret on the first field the gap names', async () => {
    open()
    await waitFor(() => expect(document.activeElement).toBe(field(/Số ngày trước khi làm đất/)))
  })

  it('focuses dry matter when that is the only gap', async () => {
    open(['straw_dry_matter'])
    await waitFor(() => expect(document.activeElement).toBe(field(/Tỷ lệ chất khô của rơm/)))
  })

  it('refuses to save while a required gap field is blank, with the error under that field', async () => {
    const { onClose } = open()
    save()
    const input = field(/Số ngày trước khi làm đất/)
    const errId = input.getAttribute('aria-describedby')!.split(' ')[0]
    expect(document.getElementById(errId)!.textContent).toMatch(/cần để tính phát thải/)
    expect(input.getAttribute('aria-invalid')).toBe('true')
    expect(updateActivity).not.toHaveBeenCalled()
    expect(onClose).not.toHaveBeenCalled()
  })

  it.each([['1,5', /không quá 1/], ['-0.2', /lớn hơn 0/], ['0,8,5', /số hợp lệ/]])(
    'shows "%s" as invalid as soon as it is typed', (value, message) => {
      open()
      fireEvent.change(field(/Tỷ lệ chất khô của rơm/), { target: { value } })
      expect(screen.getByText(message)).toBeTruthy()
    })

  it('refuses a fractional day count', () => {
    open()
    fireEvent.change(field(/Số ngày trước khi làm đất/), { target: { value: '2,5' } })
    expect(screen.getByText(/số nguyên/)).toBeTruthy()
  })

  it('normalises "0,85" and sends numbers to the existing contract', async () => {
    const { onSaved } = open()
    fireEvent.change(field(/Số ngày trước khi làm đất/), { target: { value: '14' } })
    fireEvent.change(field(/Tỷ lệ chất khô của rơm/), { target: { value: '0,85' } })
    save()
    await waitFor(() => expect(updateActivity).toHaveBeenCalled())
    const { activityDataPayload } = await import('../api/activities')
    const body = activityDataPayload(updateActivity.mock.calls[0][1])
    expect(body.days_before_cultivation).toBe(14)
    expect(body.dry_matter_fraction).toBe(0.85)
    await waitFor(() => expect(onSaved).toHaveBeenCalled())
  })

  it('keeps the sheet open and the entries when the save fails', async () => {
    updateActivity.mockRejectedValueOnce(Object.assign(new Error('offline'), { status: 0, code: 'offline' }))
    const { onClose, onSaved } = open()
    fireEvent.change(field(/Số ngày trước khi làm đất/), { target: { value: '14' } })
    fireEvent.change(field(/Tỷ lệ chất khô của rơm/), { target: { value: '0.85' } })
    save()
    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy())
    expect(onClose).not.toHaveBeenCalled()
    expect(onSaved).not.toHaveBeenCalled()
    expect(field(/Tỷ lệ chất khô của rơm/).value).toBe('0.85')
  })
})
