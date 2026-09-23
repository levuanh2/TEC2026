// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { CarbonMissingInput, CarbonReadiness } from '../../api/carbon'
import type { Activity, CropSeason } from '../../types'

/* The Carbon tab is a repair hub: each input the SERVER says is missing is
 * listed with the one action that supplies it, on this page — an inline editor
 * for a season field, "Sửa ngay" on the exact record, a link to the plot, or an
 * honest limitation for fuel. No methodology lives in the client: these tests
 * feed readiness payloads and check routing on `flow`/`records` only. */

const carbonState = { loading: false, error: null as string | null, data: { kind: 'none', reason: 'no_calculation' } as unknown, reload: vi.fn() }
const readinessState = { loading: false, error: null, data: null as CarbonReadiness | null, reload: vi.fn() }
const updateSeasonMethodology = vi.fn()
const calculateCarbon = vi.fn()
const invalidateQueries = vi.fn()

vi.mock('../scope', () => ({
  useCarbon: () => carbonState,
  useCarbonReadiness: () => readinessState,
}))
vi.mock('../../api/crops', () => ({ updateSeasonMethodology: (...a: unknown[]) => updateSeasonMethodology(...a) }))
vi.mock('../../api/carbon', () => ({ calculateCarbon: (...a: unknown[]) => calculateCarbon(...a) }))
vi.mock('../data', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../data')>()),
  invalidateQueries: (...a: unknown[]) => invalidateQueries(...a),
}))

const { SeasonCarbon } = await import('./Carbon')

const season: CropSeason = {
  id: 's1', plotId: 'p1', name: 'HT-2026', status: 'active',
  ipccWaterRegime: null, preSeasonWaterRegime: null, cultivationDays: null,
}
const writeCtx = { id: 's1', label: 'HT-2026 · Thửa 1' }

const issue = (over: Partial<CarbonMissingInput> = {}): CarbonMissingInput => ({
  code: 'pre_season_water_regime', label: 'Thiếu chế độ nước trước vụ',
  detail: 'Tình trạng ngập nước trước khi vào vụ ảnh hưởng trực tiếp tới CH₄.',
  flow: 'carbon_methodology', activity_type: null, blocking: true, records: [], ...over,
})
const readiness = (...items: CarbonMissingInput[]): CarbonReadiness => ({
  can_calculate: !items.some((m) => m.blocking),
  blocking_count: items.filter((m) => m.blocking).length,
  missing_inputs: items,
})

const npk: Activity = { id: 'act-npk', cropSeasonId: 's1', occurredAt: '2026-03-05T00:00:00Z', type: 'fertilizer', detail: '{}', recorder: 'u', source: 'web' }
const straw: Activity = { id: 'act-straw', cropSeasonId: 's1', occurredAt: '2026-03-01T00:00:00Z', type: 'straw_management', detail: '{}', recorder: 'u', source: 'web' }
const nitrogen = issue({
  code: 'fertilizer_nitrogen', label: 'Thiếu hàm lượng Nitơ của lần bón phân', flow: 'activity', activity_type: 'fertilizer',
  records: [{ activity_id: 'act-npk', occurred_on: '2026-03-05', label: 'NPK' }],
})
const dryMatter = issue({
  code: 'straw_dry_matter', label: 'Thiếu tỷ lệ chất khô của rơm', flow: 'activity', activity_type: 'straw_management',
  records: [{ activity_id: 'act-straw', occurred_on: '2026-03-01', label: 'burned' }],
})

function renderTab(props: Partial<Parameters<typeof SeasonCarbon>[0]> = {}) {
  const mutations = { openEdit: vi.fn(), openPicker: vi.fn(), openCreate: vi.fn(), openDelete: vi.fn(), flash: null, node: null, version: 0 }
  const onSaved = vi.fn()
  const utils = render(
    <SeasonCarbon seasonId="s1" season={season} plotId="p1" writeCtx={writeCtx}
      activities={[npk, straw]} mutations={mutations} onSaved={onSaved} {...props} />,
  )
  return { ...utils, mutations, onSaved }
}

beforeEach(() => {
  readinessState.data = null
  carbonState.data = { kind: 'none', reason: 'no_calculation' }
  updateSeasonMethodology.mockReset().mockResolvedValue(season)
  calculateCarbon.mockReset().mockResolvedValue({})
  invalidateQueries.mockReset()
})
afterEach(cleanup)

describe('season-field quick fix', () => {
  it('edits the one missing season field inline and sends only that field', async () => {
    readinessState.data = readiness(issue({ code: 'water_regime', label: 'Thiếu chế độ nước trong vụ' }))
    const { onSaved } = renderTab()
    fireEvent.change(screen.getByLabelText('Chế độ nước trong vụ'), { target: { value: 'irrigated_multiple_drainage' } })
    fireEvent.click(screen.getByRole('button', { name: 'Lưu' }))
    await waitFor(() => expect(updateSeasonMethodology).toHaveBeenCalledWith('s1', { ipccWaterRegime: 'irrigated_multiple_drainage' }))
    expect(onSaved).toHaveBeenCalled()
  })

  it('takes cultivation days as a number of days', async () => {
    readinessState.data = readiness(issue({ code: 'cultivation_days', label: 'Thiếu số ngày canh tác' }))
    renderTab()
    fireEvent.change(screen.getByLabelText('Số ngày canh tác'), { target: { value: '100' } })
    fireEvent.click(screen.getByRole('button', { name: 'Lưu' }))
    await waitFor(() => expect(updateSeasonMethodology).toHaveBeenCalledWith('s1', { cultivationDays: 100 }))
  })

  it('refetches readiness after a save, so the item can disappear without a page reload', async () => {
    readinessState.data = readiness(issue())
    renderTab()
    fireEvent.change(screen.getByLabelText('Chế độ nước trước vụ'), { target: { value: 'non_flooded_pre_season_lt_180d' } })
    fireEvent.click(screen.getByRole('button', { name: 'Lưu' }))
    await waitFor(() => expect(invalidateQueries).toHaveBeenCalledWith('carbon:s1:readiness'))
  })

  it('keeps Lưu disabled until a value is chosen', () => {
    readinessState.data = readiness(issue())
    renderTab()
    expect((screen.getByRole('button', { name: 'Lưu' }) as HTMLButtonElement).disabled).toBe(true)
  })
})

describe('activity direct edit', () => {
  it('"Sửa ngay" opens the existing edit sheet on the exact fertilizer record, disclosure open', () => {
    readinessState.data = readiness(nitrogen)
    const { mutations } = renderTab()
    fireEvent.click(screen.getByRole('button', { name: /Sửa ngay: Bón phân · NPK/ }))
    // The gap code travels with the record, so the form can make N required.
    expect(mutations.openEdit).toHaveBeenCalledWith(npk, writeCtx, { fix: ['fertilizer_nitrogen'] })
  })

  it('"Sửa ngay" opens the exact straw record', () => {
    readinessState.data = readiness(dryMatter)
    const { mutations } = renderTab()
    fireEvent.click(screen.getByRole('button', { name: /Sửa ngay/ }))
    expect(mutations.openEdit).toHaveBeenCalledWith(straw, writeCtx, { fix: [dryMatter.code] })
  })

  it('both straw cards open the same record by id, even beside another straw record on the same date', () => {
    const sameDay: Activity = { ...straw, id: 'act-straw-other' }
    const days = issue({
      code: 'straw_days_before_cultivation', label: 'Thiếu số ngày vùi rơm trước khi làm đất', flow: 'activity',
      activity_type: 'straw_management', records: [{ activity_id: 'act-straw', occurred_on: '2026-03-01', label: 'incorporated' }],
    })
    readinessState.data = readiness(days, dryMatter)
    const { mutations } = renderTab({ activities: [sameDay, npk, straw] })
    const buttons = screen.getAllByRole('button', { name: /Sửa ngay/ })
    expect(buttons).toHaveLength(2)
    for (const button of buttons) fireEvent.click(button)
    expect(mutations.openEdit.mock.calls.map((c) => c[0].id)).toEqual(['act-straw', 'act-straw'])
  })

  it('never sends the user to search the journal when the record is known', () => {
    readinessState.data = readiness(nitrogen, dryMatter)
    renderTab()
    expect(screen.queryByRole('link', { name: /nhật ký/i })).toBeNull()
  })
})

describe('plot and fuel', () => {
  it('routes a missing plot area to the plot, not to methodology settings', () => {
    readinessState.data = readiness(issue({ code: 'area', label: 'Thiếu diện tích thửa', flow: 'plot' }))
    renderTab()
    expect(screen.getByRole('link', { name: 'Cập nhật diện tích' }).getAttribute('href')).toBe('/farmer/plots/p1')
    expect(screen.queryByRole('link', { name: 'Bổ sung dữ liệu Carbon' })).toBeNull()
    expect(screen.queryByRole('combobox')).toBeNull()
  })

  it('shows fuel as an honest, non-editable limitation', () => {
    readinessState.data = readiness(issue({
      code: 'fuel_factor_unverified', label: 'Vụ có ghi nhiên liệu nhưng chưa có hệ số đã xác minh',
      detail: 'Đây là giới hạn của bộ hệ số, không phải do bạn nhập thiếu.', flow: 'factor_unavailable', activity_type: 'fuel',
    }))
    renderTab()
    expect(screen.getByText('Vụ có ghi nhiên liệu nhưng hệ số phát thải nhiên liệu chưa được xác minh.')).toBeTruthy()
    expect(screen.getByText(/nhập thêm không giúp tính được/)).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Xem bản ghi nhiên liệu' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Sửa ngay|Lưu/ })).toBeNull()
  })

  it('does not count the factor limitation as something to fill in', () => {
    // Two blocking inputs, one of which no form can resolve: the heading has to
    // agree with the number of editable rows below it, or the farmer goes
    // looking for a field that is not there.
    readinessState.data = readiness(issue(), issue({
      code: 'fuel_factor_unverified', label: 'Vụ có ghi nhiên liệu nhưng chưa có hệ số đã xác minh',
      detail: 'Đây là giới hạn của bộ hệ số.', flow: 'factor_unavailable', activity_type: 'fuel',
    }))
    renderTab()
    expect(screen.getByText('Cần bổ sung 1 thông tin để tính phát thải')).toBeTruthy()
    expect(screen.getByText(/nhập thêm không giúp tính được/)).toBeTruthy()
  })
})

describe('resolution and ready state', () => {
  it('a resolved item disappears once readiness comes back without it', () => {
    readinessState.data = readiness(issue(), nitrogen)
    const view = renderTab()
    expect(screen.getByText('Thiếu hàm lượng Nitơ của lần bón phân')).toBeTruthy()
    readinessState.data = readiness(issue())
    view.rerender(<SeasonCarbon seasonId="s1" season={season} plotId="p1" writeCtx={writeCtx} activities={[npk, straw]} mutations={view.mutations} />)
    expect(screen.queryByText('Thiếu hàm lượng Nitơ của lần bón phân')).toBeNull()
    expect(screen.getByText('Cần bổ sung 1 thông tin để tính phát thải')).toBeTruthy()
  })

  it('with everything resolved, replaces the list with the ready state and "Tính Carbon"', async () => {
    readinessState.data = readiness()
    renderTab()
    expect(screen.getByText('Đã đủ dữ liệu để tính phát thải.')).toBeTruthy()
    expect(screen.queryByTestId('carbon-missing')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: /Tính Carbon/ }))
    await waitFor(() => expect(calculateCarbon).toHaveBeenCalledWith('s1', 'as_recorded'))
    expect(invalidateQueries).toHaveBeenCalledWith('carbon:s1', 'metrics:s1')
  })

  it('leads with a fresh result and does not push a recalculation', () => {
    readinessState.data = readiness()
    carbonState.data = { kind: 'result', result: { crop_season_id: 's1', total_co2e_kg: 1200, co2e_per_kg: 0.3, breakdown: [], warnings: [] } }
    renderTab()
    expect(screen.getByText('Tổng phát thải vụ này')).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Tính lại Carbon/ })).toBeNull()
  })

  it('a non-blocking missing yield does not hold back the ready state', () => {
    readinessState.data = readiness(issue({ code: 'harvest_yield', label: 'Chưa ghi sản lượng thu hoạch', detail: 'Vẫn tính được tổng CO₂e.', flow: 'activity', activity_type: 'harvest', blocking: false }))
    renderTab()
    expect(screen.getByText('Đã đủ dữ liệu để tính phát thải.')).toBeTruthy()
    expect(screen.getByText(/Chưa ghi sản lượng thu hoạch/)).toBeTruthy()
  })
})

describe('authorization and fallbacks', () => {
  it('a viewer sees every issue but gets no edit or calculate controls', () => {
    readinessState.data = readiness(issue(), nitrogen)
    renderTab({ writeCtx: null })
    expect(screen.getByText('Thiếu chế độ nước trước vụ')).toBeTruthy()
    expect(screen.getByText(/chỉ có quyền xem/)).toBeTruthy()
    expect(screen.queryByRole('combobox')).toBeNull()
    expect(screen.queryByRole('button', { name: /Sửa ngay|Lưu/ })).toBeNull()
  })

  it('a viewer on a ready season cannot calculate', () => {
    readinessState.data = readiness()
    renderTab({ writeCtx: null })
    expect(screen.queryByRole('button', { name: /Tính/ })).toBeNull()
  })

  it('still renders calmly when readiness is unavailable', () => {
    readinessState.data = null
    renderTab()
    expect(screen.getByText('Chưa có kết quả phát thải cho vụ này')).toBeTruthy()
    expect(screen.queryByTestId('carbon-missing')).toBeNull()
  })

  it('states that cost is not a Carbon input', () => {
    readinessState.data = readiness(issue())
    renderTab()
    expect(screen.getByText(/Chi phí không phải đầu vào của Carbon/)).toBeTruthy()
  })

  it('keeps the full methodology panel for changing values already set', () => {
    readinessState.data = readiness(issue())
    renderTab()
    expect(screen.getByText('Thông tin phương pháp tính')).toBeTruthy()
  })
})
