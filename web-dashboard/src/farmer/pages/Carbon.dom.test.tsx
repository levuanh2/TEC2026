// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { CarbonMissingInput } from '../../api/carbon'
import type { CropSeason } from '../../types'

/* The Carbon tab used to be a dead end: "Hệ thống chưa thể tạo kết quả Carbon"
 * with nothing to do about it. It now renders the inputs the SERVER says are
 * missing, and a CTA that lands where each one is actually supplied. */

const carbonState = { loading: false, error: null as string | null, data: { kind: 'none', reason: 'no_calculation' }, reload: vi.fn() }
const readinessState = { loading: false, error: null, data: null as unknown, reload: vi.fn() }

vi.mock('../scope', () => ({
  useCarbon: () => carbonState,
  useCarbonReadiness: () => readinessState,
}))
vi.mock('../../api/crops', () => ({ updateSeasonMethodology: vi.fn() }))

const { SeasonCarbon } = await import('./Carbon')

const season: CropSeason = {
  id: 's1', plotId: 'p1', name: 'HT-2026', status: 'active',
  ipccWaterRegime: null, preSeasonWaterRegime: null, cultivationDays: null,
}

const input = (over: Partial<CarbonMissingInput> = {}): CarbonMissingInput => ({
  code: 'pre_season_water_regime', label: 'Thiếu chế độ nước trước vụ',
  detail: 'Tình trạng ngập nước trước khi vào vụ ảnh hưởng trực tiếp tới CH₄.',
  flow: 'carbon_methodology', activity_type: null, blocking: true, ...over,
})

beforeEach(() => { readinessState.data = null })
afterEach(cleanup)

describe('Farmer Carbon tab empty state', () => {
  it('lists the server-named missing inputs instead of a generic failure', () => {
    readinessState.data = { can_calculate: false, blocking_count: 2, missing_inputs: [
      input(), input({ code: 'cultivation_days', label: 'Thiếu số ngày canh tác', detail: 'Cần số ngày canh tác.' }),
    ] }
    render(<SeasonCarbon seasonId="s1" season={season} canEdit />)
    expect(screen.getByText('Cần bổ sung dữ liệu để tính phát thải')).toBeTruthy()
    expect(screen.getByText('Thiếu chế độ nước trước vụ')).toBeTruthy()
    expect(screen.getByText('Thiếu số ngày canh tác')).toBeTruthy()
  })

  it('points the Carbon CTA at the methodology panel on this page', () => {
    readinessState.data = { can_calculate: false, blocking_count: 1, missing_inputs: [input()] }
    render(<SeasonCarbon seasonId="s1" season={season} canEdit />)
    const cta = screen.getByRole('link', { name: 'Bổ sung dữ liệu Carbon' })
    expect(cta.getAttribute('href')).toBe('#fw-carbon-methodology')
    // and that anchor exists on the rendered page, so the button is not a dead link
    expect(document.getElementById('fw-carbon-methodology')).toBeTruthy()
  })

  it('points an activity-level input at the journal instead', () => {
    readinessState.data = { can_calculate: false, blocking_count: 1, missing_inputs: [
      input({ code: 'fertilizer_nitrogen', label: 'Thiếu hàm lượng Nitơ', flow: 'activity', activity_type: 'fertilizer' }),
    ] }
    render(<SeasonCarbon seasonId="s1" season={season} canEdit />)
    const cta = screen.getByRole('link', { name: 'Sửa bản ghi trong nhật ký' })
    expect(cta.getAttribute('href')).toBe('/farmer/crop-seasons/s1/journal')
    expect(screen.queryByRole('link', { name: 'Bổ sung dữ liệu Carbon' })).toBeNull()
  })

  it('states that cost is not a Carbon input', () => {
    readinessState.data = { can_calculate: false, blocking_count: 1, missing_inputs: [input()] }
    render(<SeasonCarbon seasonId="s1" season={season} canEdit />)
    expect(screen.getByText(/Chi phí không phải đầu vào của Carbon/)).toBeTruthy()
  })

  it('treats a missing yield as non-blocking, not as the reason Carbon failed', () => {
    readinessState.data = { can_calculate: true, blocking_count: 0, missing_inputs: [
      input({ code: 'harvest_yield', label: 'Chưa ghi sản lượng thu hoạch', flow: 'activity', activity_type: 'harvest', blocking: false }),
    ] }
    render(<SeasonCarbon seasonId="s1" season={season} canEdit />)
    expect(screen.queryByText('Cần bổ sung dữ liệu để tính phát thải')).toBeNull()
    expect(screen.getByText(/chỉ chưa có cường độ trên mỗi kg lúa/)).toBeTruthy()
  })

  it('still renders calmly when readiness is unavailable', () => {
    readinessState.data = null
    render(<SeasonCarbon seasonId="s1" season={season} canEdit />)
    expect(screen.getByText('Chưa có kết quả phát thải cho vụ này')).toBeTruthy()
    expect(screen.queryByTestId('carbon-missing')).toBeNull()
  })

  it('renders the methodology input panel on the tab so the CTA has a target', () => {
    readinessState.data = { can_calculate: false, blocking_count: 1, missing_inputs: [input()] }
    render(<SeasonCarbon seasonId="s1" season={season} canEdit />)
    expect(screen.getByText('Thông tin phương pháp tính')).toBeTruthy()
  })
})
