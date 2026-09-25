// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { ReactElement } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Activity, CropSeason, Farm, Plot } from '../types'
import { ApiError } from '../api/client'
import { FarmWriteAccess } from './writeAccess'

/* Season lifecycle on Farmer Web: no-season onboarding, starting a season, and
 * the rule that only an OPEN season is ever a journal write target. */

const farm = { id: 'farm-1', code: 'F1', name: 'Hộ 1' } as Farm
const plot = { id: 'plot-1', farmId: 'farm-1', code: 'P1', name: 'Thửa 1', areaHa: 1.25 } as Plot
const season = (id: string, status: string): CropSeason => ({ id, plotId: 'plot-1', name: `Vụ ${id}`, status } as CropSeason)
const activity: Activity = {
  id: 'act-1', cropSeasonId: 'old', occurredAt: '2026-03-02', type: 'fertilizer',
  detail: JSON.stringify({ fertilizer_name: 'Urê', amount_kg: 12 }), recorder: 'QA', source: 'web',
}
const ready = <T,>(data: T) => ({ data, loading: false, error: null, reload: () => undefined })

let scope: { farms: Farm[]; plots: Plot[]; seasons: CropSeason[] } = { farms: [farm], plots: [plot], seasons: [] }

vi.mock('./scope', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./scope')>()
  return {
    ...actual,
    useScope: () => ready(scope),
    useActivities: (id: string | null) => ready(id ? [activity] : []),
  }
})

const startCropSeason = vi.fn()
vi.mock('../api/crops', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/crops')>()
  return { ...actual, startCropSeason: (...args: unknown[]) => startCropSeason(...args) }
})

const { FarmerJournalPage } = await import('./pages/Journal')
const { FarmerPlotPage } = await import('./pages/Farms')
const { startSeasonErrorMessage, startSeasonFieldErrors } = await import('../features/startSeason')

const as = (writable: string[], node: ReactElement) => render(<FarmWriteAccess.Provider value={writable}>{node}</FarmWriteAccess.Provider>)

beforeEach(() => {
  scope = { farms: [farm], plots: [plot], seasons: [] }
  startCropSeason.mockReset()
  history.replaceState({}, '', '/farmer/journal')
})
afterEach(cleanup)

describe('plot with no crop season', () => {
  it('offers "Bắt đầu vụ mới" to a farm owner/editor', () => {
    as(['farm-1'], <FarmerPlotPage id="plot-1" />)
    expect(screen.getByText('Chưa có vụ canh tác')).toBeTruthy()
    expect(screen.getByText(/Bạn đã có thửa ruộng. Bắt đầu vụ mới để ghi nhật ký/)).toBeTruthy()
    expect(screen.getByRole('button', { name: /Bắt đầu vụ mới/ })).toBeTruthy()
  })

  it('a read-only member is told so and gets no create button', () => {
    as([], <FarmerPlotPage id="plot-1" />)
    expect(screen.getByText(/Bạn chưa có quyền tạo vụ canh tác/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Bắt đầu vụ mới/ })).toBeNull()
  })

  it('a plot whose only season is harvested can start the next one', () => {
    scope.seasons = [season('old', 'harvested')]
    as(['farm-1'], <FarmerPlotPage id="plot-1" />)
    expect(screen.getByRole('button', { name: /Bắt đầu vụ mới/ })).toBeTruthy()
  })

  it('a plot with an active season offers no second start', () => {
    scope.seasons = [season('now', 'active')]
    as(['farm-1'], <FarmerPlotPage id="plot-1" />)
    expect(screen.queryByRole('button', { name: /Bắt đầu vụ mới/ })).toBeNull()
  })
})

describe('journal with no ACTIVE season', () => {
  it('shows the onboarding state, never a writable empty journal', () => {
    as(['farm-1'], <FarmerJournalPage />)
    expect(screen.getByText('Bạn chưa có vụ đang canh tác')).toBeTruthy()
    expect(screen.getByText(/Bạn cần bắt đầu một vụ trên thửa ruộng trước khi ghi nhật ký hoạt động/)).toBeTruthy()
    expect(screen.getByRole('button', { name: /Bắt đầu vụ mới/ })).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Ghi hoạt động/ })).toBeNull()
  })

  it('an account with no plot is told the cooperative has not assigned one', () => {
    scope = { farms: [], plots: [], seasons: [] }
    as([], <FarmerJournalPage />)
    expect(screen.getByText('HTX chưa gán thửa ruộng cho tài khoản của bạn.')).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Bắt đầu vụ mới/ })).toBeNull()
  })

  it('a read-only member gets "Xem ruộng của tôi" and an explanation, no create', () => {
    as([], <FarmerJournalPage />)
    expect(screen.getByText(/Bạn chưa có quyền tạo vụ canh tác/)).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Xem ruộng của tôi' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Bắt đầu vụ mới/ })).toBeNull()
  })
})

describe('closed-season write protection', () => {
  it('closed/harvested-only seasons stay readable but never offer "Ghi hoạt động"', () => {
    scope.seasons = [season('old', 'harvested'), season('older', 'closed')]
    as(['farm-1'], <FarmerJournalPage />)
    expect(screen.getByText('Bạn chưa có vụ đang canh tác')).toBeTruthy()
    expect(screen.getByText('Nhật ký các vụ trước')).toBeTruthy()
    expect(screen.getByRole('button', { name: /Urê/ })).toBeTruthy() // the past record is still shown
    expect(screen.queryByRole('button', { name: /Ghi hoạt động/ })).toBeNull()
    expect(screen.queryByRole('button', { name: /Sửa bản ghi/ })).toBeNull()
    expect(screen.queryByRole('button', { name: /Xóa bản ghi/ })).toBeNull()
  })

  it('a planned season is not open for journal writes either', () => {
    scope.seasons = [season('next', 'planned')]
    as(['farm-1'], <FarmerJournalPage />)
    expect(screen.queryByRole('button', { name: /Ghi hoạt động/ })).toBeNull()
  })

  it('an active season keeps "Ghi hoạt động" for an owner/editor', () => {
    scope.seasons = [season('now', 'active'), season('old', 'harvested')]
    as(['farm-1'], <FarmerJournalPage />)
    expect(screen.getByRole('button', { name: /Ghi hoạt động/ })).toBeTruthy()
  })

  it('picking a past season while one is active removes the write controls', () => {
    scope.seasons = [season('now', 'active'), season('old', 'harvested')]
    as(['farm-1'], <FarmerJournalPage />)
    fireEvent.click(screen.getByRole('button', { name: /Vụ old/ }))
    expect(screen.queryByRole('button', { name: /Ghi hoạt động/ })).toBeNull()
  })
})

describe('starting a season', () => {
  it('sends one request and lands on the new season', async () => {
    let resolve!: (v: unknown) => void
    startCropSeason.mockReturnValue(new Promise((r) => { resolve = r }))
    as(['farm-1'], <FarmerJournalPage />)
    fireEvent.click(screen.getByRole('button', { name: /Bắt đầu vụ mới/ }))
    fireEvent.change(screen.getByLabelText(/Tên vụ/), { target: { value: 'Hè Thu 2026' } })
    fireEvent.change(screen.getByLabelText(/Giống lúa/), { target: { value: 'OM5451' } })
    const submit = screen.getByRole('button', { name: 'Bắt đầu vụ' })
    fireEvent.click(submit)
    fireEvent.click(submit) // double submit while pending
    expect(startCropSeason).toHaveBeenCalledTimes(1)
    expect(startCropSeason.mock.calls[0][0]).toBe('plot-1')
    expect(startCropSeason.mock.calls[0][1]).toMatchObject({ seasonCode: 'Hè Thu 2026', variety: 'OM5451' })
    expect((screen.getByRole('button', { name: /Đang bắt đầu vụ/ }) as HTMLButtonElement).disabled).toBe(true)
    await act(async () => { resolve({ season: season('new-1', 'active'), defaultBatchId: 'b-1', replay: false }) })
    await waitFor(() => expect(location.pathname).toBe('/farmer/crop-seasons/new-1'))
    expect(location.search).toBe('?vu-moi=1')
  })

  it('refuses a blank season name before sending anything', () => {
    as(['farm-1'], <FarmerPlotPage id="plot-1" />)
    fireEvent.click(screen.getByRole('button', { name: /Bắt đầu vụ mới/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Bắt đầu vụ' }))
    expect(screen.getByText(/Nhập tên vụ/)).toBeTruthy()
    expect(startCropSeason).not.toHaveBeenCalled()
  })

  it('shows the server conflict in plain Vietnamese and allows a retry', async () => {
    startCropSeason.mockRejectedValue(new ApiError(409, 'active_season_exists', 'x'))
    as(['farm-1'], <FarmerPlotPage id="plot-1" />)
    fireEvent.click(screen.getByRole('button', { name: /Bắt đầu vụ mới/ }))
    fireEvent.change(screen.getByLabelText(/Tên vụ/), { target: { value: 'HT' } })
    fireEvent.click(screen.getByRole('button', { name: 'Bắt đầu vụ' }))
    await waitFor(() => expect(screen.getByRole('alert').textContent).toMatch(/đang có một vụ đang canh tác/))
    expect((screen.getByRole('button', { name: 'Bắt đầu vụ' }) as HTMLButtonElement).disabled).toBe(false)
  })
})

describe('start-season messages', () => {
  it('maps every server refusal to its own sentence', () => {
    expect(startSeasonErrorMessage(new ApiError(409, 'season_code_exists', ''))).toMatch(/đã có một vụ với tên này/)
    expect(startSeasonErrorMessage(new ApiError(404, 'not_found', ''))).toMatch(/không có quyền/)
    expect(startSeasonErrorMessage(new ApiError(0, 'offline', ''))).toMatch(/Không kết nối/)
    expect(startSeasonErrorMessage(new Error('boom'))).toMatch(/thử lại/)
  })

  it('checks the same date rule as the database', () => {
    expect(startSeasonFieldErrors({ seasonCode: 'HT', plantingDate: '2026-05-18', expectedHarvestDate: '2026-05-01' }).expectedHarvestDate).toBeTruthy()
    expect(startSeasonFieldErrors({ seasonCode: 'HT', plantingDate: '2026-05-18', expectedHarvestDate: '2026-08-30' })).toEqual({})
  })
})
