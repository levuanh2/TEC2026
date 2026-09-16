// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { CropSeason } from '../types'

/* The season-level IPCC inputs (SFw / SFp) had no Farmer Web control at all, so a
 * web-only user could never produce a Carbon result. These cover the two things
 * that matter: the panel tells the user exactly which input is missing, and it
 * never invents one. */

const updateSeasonMethodology = vi.fn()
vi.mock('../api/crops', () => ({
  updateSeasonMethodology: (...args: unknown[]) => updateSeasonMethodology(...args),
}))

const { SeasonMethodologyPanel } = await import('./seasonMethodology')

const season = (over: Partial<CropSeason> = {}): CropSeason => ({
  id: 's1', plotId: 'p1', name: 'HT-2026', status: 'active',
  ipccWaterRegime: null, preSeasonWaterRegime: null, cultivationDays: null, ...over,
})

beforeEach(() => {
  updateSeasonMethodology.mockReset()
  updateSeasonMethodology.mockResolvedValue(season())
})
afterEach(cleanup)

describe('SeasonMethodologyPanel', () => {
  it('names each missing Carbon input instead of a generic warning', () => {
    render(<SeasonMethodologyPanel season={season()} canEdit />)
    expect(screen.getByText(/Chế độ nước trong vụ · Chế độ nước trước vụ/)).toBeTruthy()
  })

  it('names only the input still missing when one is already recorded', () => {
    render(<SeasonMethodologyPanel season={season({ ipccWaterRegime: 'upland' })} canEdit />)
    const notice = screen.getByText(/Chưa tính được carbon/)
    expect(notice.textContent).toContain('Chế độ nước trước vụ')
    expect(notice.textContent).not.toContain('Chế độ nước trong vụ')
  })

  it('confirms readiness once both regimes are recorded', () => {
    render(<SeasonMethodologyPanel season={season({
      ipccWaterRegime: 'irrigated_multiple_drainage',
      preSeasonWaterRegime: 'non_flooded_pre_season_lt_180d',
    })} canEdit />)
    expect(screen.getByText('Đã đủ thông tin chế độ nước để tính phát thải.')).toBeTruthy()
  })

  it('offers every IPCC water regime the engine accepts, with AWD discoverable', () => {
    render(<SeasonMethodologyPanel season={season()} canEdit />)
    fireEvent.click(screen.getByRole('button', { name: /Khai báo/ }))
    expect(screen.getAllByRole('radio', { name: /Tưới|Nhờ nước trời|Lúa/ }).length).toBe(7)
    expect(screen.getByText(/rút nước nhiều lần \(gồm AWD\)/)).toBeTruthy()
    expect(screen.getAllByRole('radio', { name: /ngập|Không ngập|Có ngập/ }).length).toBeGreaterThanOrEqual(4)
  })

  it('sends the chosen regimes and leaves an untouched day count null, not 0', async () => {
    render(<SeasonMethodologyPanel season={season()} canEdit />)
    fireEvent.click(screen.getByRole('button', { name: /Khai báo/ }))
    fireEvent.click(screen.getByRole('radio', { name: /rút nước nhiều lần/ }))
    fireEvent.click(screen.getByRole('radio', { name: /dưới 180 ngày/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Lưu' }))
    await waitFor(() => expect(updateSeasonMethodology).toHaveBeenCalled())
    expect(updateSeasonMethodology.mock.calls[0][1]).toEqual({
      ipccWaterRegime: 'irrigated_multiple_drainage',
      preSeasonWaterRegime: 'non_flooded_pre_season_lt_180d',
      cultivationDays: null,
    })
  })

  it('explains a refused write in Vietnamese rather than a raw error', async () => {
    updateSeasonMethodology.mockRejectedValue(Object.assign(new Error('not found'), { status: 404 }))
    render(<SeasonMethodologyPanel season={season()} canEdit />)
    fireEvent.click(screen.getByRole('button', { name: /Khai báo/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Lưu' }))
    await waitFor(() =>
      expect(screen.getByText(/không có quyền sửa thông tin phương pháp tính/)).toBeTruthy())
  })

  it('gives a read-only viewer the diagnosis but no form', () => {
    render(<SeasonMethodologyPanel season={season()} canEdit={false} />)
    expect(screen.getByText(/liên hệ chủ hộ hoặc cán bộ hợp tác xã/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Khai báo/ })).toBeNull()
  })
})
