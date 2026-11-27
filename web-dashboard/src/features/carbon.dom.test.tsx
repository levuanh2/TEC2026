// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

/* B4 affordance: only crop writers may persist a Carbon calculation, so the
 * read-only Management roles do not get a recalculate button that the server
 * would refuse. Viewing stays available to everyone who can read the season. */

vi.mock('../api/carbon', () => ({
  getCarbon: () => Promise.reject(new Error('no_calculation')),
  calculateCarbon: vi.fn(),
}))

const { CarbonPanel, statusLabel } = await import('./carbon')

afterEach(cleanup)

describe('parameter status wording', () => {
  it('says a factor was matched to its source, never that it was verified', () => {
    expect(statusLabel('VERIFIED')).toBe('Đã đối chiếu nguồn')
    expect(statusLabel('PENDING_VERIFICATION')).toBe('Chờ đối chiếu nguồn')
    expect(statusLabel('TEST_ONLY')).toBe('Chưa đối chiếu nguồn')
    for (const v of ['VERIFIED', 'PENDING_VERIFICATION', null]) expect(statusLabel(v)).not.toMatch(/xác minh/)
  })
})

describe('Carbon recalculate affordance', () => {
  it('is shown when the viewer may persist, and the empty state names that same button', async () => {
    render(<CarbonPanel id="season-1" canRecalculate />)
    await waitFor(() => expect(screen.getByText('Chưa có bản tính CO₂e cho vụ này')).toBeTruthy())
    // No stored result yet: the action is to calculate, not to "recalculate".
    const button = screen.getByRole('button', { name: 'Tính Carbon' }) as HTMLButtonElement
    expect(button.disabled).toBe(false)
    expect(screen.getByText(/Chọn “Tính Carbon”/)).toBeTruthy()
    expect(screen.queryByText(/Tính lại theo kịch bản/)).toBeNull()
  })

  it('is hidden for a read-only viewer, who still sees the result state', async () => {
    render(<CarbonPanel id="season-1" canRecalculate={false} />)
    await waitFor(() => expect(screen.getByText('Chưa có bản tính CO₂e cho vụ này')).toBeTruthy())
    expect(screen.queryByRole('button', { name: /Tính/ })).toBeNull()
    expect(screen.queryByText(/Chọn “Tính/)).toBeNull()
  })
})
