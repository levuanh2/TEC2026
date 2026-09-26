// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/client'
import type { CropSeason } from '../types'

/* "Kết thúc vụ": confirmation, one API call, cache updated so the journal
 * immediately stops offering writes; Management shows it to managers only. */

const endCropSeason = vi.fn()
vi.mock('../api/crops', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/crops')>()),
  endCropSeason: (...a: unknown[]) => endCropSeason(...a),
  getCropSeason: async () => ({ id: 's1', plotId: 'p1', name: 'HT', status: currentStatus } as CropSeason),
  getActivities: async () => [],
  getProductionBatches: async () => [],
}))
vi.mock('../api/farms', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/farms')>()),
  getPlot: async () => ({ id: 'p1', farmId: 'f1', code: 'P1', name: 'Thửa 1' }),
}))
vi.mock('../api/metrics', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/metrics')>()),
  getResourceMetrics: async () => null,
}))

let currentStatus = 'active'
const { EndSeasonButton } = await import('./EndSeason')
const { SeasonHub } = await import('../pages/season')
const { endSeasonErrorMessage } = await import('../api/crops')
const { setQueryData, peekQuery, keys } = await import('./data')

const season = { id: 's1', plotId: 'p1', name: 'HT', status: 'active' } as CropSeason
beforeEach(() => { endCropSeason.mockReset(); currentStatus = 'active' })
afterEach(cleanup)

describe('Farmer "Kết thúc vụ"', () => {
  it('asks for confirmation, sends one request and marks the season ended in the cache', async () => {
    setQueryData(keys.scope, { farms: [], plots: [], seasons: [season] })
    endCropSeason.mockResolvedValue({ ...season, status: 'harvested', harvestDate: '2026-09-01' })
    render(<EndSeasonButton season={season} />)
    fireEvent.click(screen.getByRole('button', { name: /Kết thúc vụ/ }))
    expect(screen.getByRole('alertdialog').textContent).toMatch(/không mở lại được/)
    fireEvent.change(screen.getByLabelText(/Ngày thu hoạch/), { target: { value: '2026-09-01' } })
    fireEvent.click(screen.getAllByRole('button', { name: 'Kết thúc vụ' }).at(-1)!)
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull())
    expect(endCropSeason).toHaveBeenCalledTimes(1)
    expect(endCropSeason).toHaveBeenCalledWith('s1', '2026-09-01')
    const scope = peekQuery<{ seasons: CropSeason[] }>(keys.scope)!
    expect(scope.seasons[0].status).toBe('harvested')
  })

  it('keeps the dialog open with the reason when the server refuses', async () => {
    endCropSeason.mockRejectedValue(new ApiError(409, 'illegal_crop_season_transition', 'x'))
    render(<EndSeasonButton season={season} />)
    fireEvent.click(screen.getByRole('button', { name: /Kết thúc vụ/ }))
    fireEvent.click(screen.getAllByRole('button', { name: 'Kết thúc vụ' }).at(-1)!)
    await waitFor(() => expect(screen.getByRole('alert').textContent).toMatch(/không mở lại được/))
  })

  it('maps refusals', () => {
    expect(endSeasonErrorMessage(new ApiError(404, 'not_found', ''))).toMatch(/không có quyền/)
    expect(endSeasonErrorMessage(new ApiError(422, 'validation_error', ''))).toMatch(/Ngày thu hoạch/)
  })
})

describe('Management "Kết thúc vụ"', () => {
  it('a cooperative manager can end an active season', async () => {
    endCropSeason.mockResolvedValue({ ...season, status: 'harvested' })
    render(<SeasonHub id="s1" tab="overview" role="cooperative_manager" />)
    const button = await screen.findByRole('button', { name: 'Kết thúc vụ' })
    fireEvent.click(button)
    fireEvent.click(screen.getAllByRole('button', { name: 'Kết thúc vụ' }).at(-1)!)
    await waitFor(() => expect(endCropSeason).toHaveBeenCalledWith('s1'))
  })

  it.each(['enterprise_viewer', 'regulator'] as const)('%s gets no end action', async (role) => {
    render(<SeasonHub id="s1" tab="overview" role={role} />)
    await screen.findByText(/Trạng thái/)
    expect(screen.queryByRole('button', { name: 'Kết thúc vụ' })).toBeNull()
  })

  it('an ended season offers no end action', async () => {
    currentStatus = 'harvested'
    render(<SeasonHub id="s1" tab="overview" role="cooperative_manager" />)
    await screen.findByText(/Trạng thái/)
    expect(screen.queryByRole('button', { name: 'Kết thúc vụ' })).toBeNull()
  })
})
