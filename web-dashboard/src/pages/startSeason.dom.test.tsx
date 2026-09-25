// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { CropSeason, Plot } from '../types'

/* Management starts a season through the SAME endpoint wrapper as Farmer Web
 * (`startCropSeason`), from the plot page, and only as a cooperative manager. */

const plot = { id: 'plot-1', farmId: 'farm-1', code: 'P1', name: 'Thửa 1', areaHa: 1.25 } as Plot
let seasons: CropSeason[] = []
const startCropSeason = vi.fn()

vi.mock('../api/farms', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/farms')>()),
  getPlot: async () => plot,
}))
vi.mock('../api/crops', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/crops')>()),
  getCropSeasons: async () => seasons,
  startCropSeason: (...args: unknown[]) => startCropSeason(...args),
}))

const { PlotPage } = await import('./directory')

beforeEach(() => { seasons = []; startCropSeason.mockReset(); history.replaceState({}, '', '/plots/plot-1') })
afterEach(cleanup)

describe('Management plot page — start a season', () => {
  it('a cooperative manager sees "Bắt đầu vụ mới" on a plot with no season', async () => {
    render(<PlotPage id="plot-1" role="cooperative_manager" />)
    await waitFor(() => expect(screen.getByText('Chưa có vụ canh tác')).toBeTruthy())
    expect(screen.getAllByRole('button', { name: /Bắt đầu vụ mới/ }).length).toBeGreaterThan(0)
  })

  it.each(['enterprise_viewer', 'regulator', 'farmer'] as const)('%s gets no create control', async (role) => {
    render(<PlotPage id="plot-1" role={role} />)
    await waitFor(() => expect(screen.getByText('Chưa có vụ canh tác')).toBeTruthy())
    expect(screen.queryByRole('button', { name: /Bắt đầu vụ mới/ })).toBeNull()
  })

  it('no second start while a season is active', async () => {
    seasons = [{ id: 's1', plotId: 'plot-1', name: 'HT', status: 'active' } as CropSeason]
    render(<PlotPage id="plot-1" role="cooperative_manager" />)
    await waitFor(() => expect(screen.getByText(/Vụ đang canh tác: HT/)).toBeTruthy())
    expect(screen.queryByRole('button', { name: /Bắt đầu vụ mới/ })).toBeNull()
  })

  it('creates through the shared endpoint and opens the season hub', async () => {
    startCropSeason.mockResolvedValue({ season: { id: 'new-1', plotId: 'plot-1', name: 'HT', status: 'active' }, defaultBatchId: 'b', replay: false })
    render(<PlotPage id="plot-1" role="cooperative_manager" />)
    await waitFor(() => screen.getByText('Chưa có vụ canh tác'))
    fireEvent.click(screen.getAllByRole('button', { name: /Bắt đầu vụ mới/ })[0])
    fireEvent.change(screen.getByLabelText(/Tên vụ/), { target: { value: 'HT' } })
    fireEvent.click(screen.getByRole('button', { name: 'Bắt đầu vụ' }))
    await waitFor(() => expect(location.pathname).toBe('/crop-seasons/new-1'))
    expect(startCropSeason).toHaveBeenCalledWith('plot-1', expect.objectContaining({ seasonCode: 'HT' }))
  })
})
