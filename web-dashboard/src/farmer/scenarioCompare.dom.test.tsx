// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

/* Simulated water regimes sit BESIDE the actual result, never in its place.
 * A scenario not calculated yet is "Chưa tính", not an error; calculating one
 * re-reads only the simulations -- the season's actual result is not read
 * again here, so a simulation cannot change the season's numbers. */
const getCarbon = vi.fn()
const calculateCarbon = vi.fn()
vi.mock('../api/carbon', async (orig) => ({
  ...(await orig<object>()),
  getCarbon: (...a: unknown[]) => getCarbon(...a),
  calculateCarbon: (...a: unknown[]) => calculateCarbon(...a),
}))

const { ApiError } = await import('../api/client')
const { ScenarioCompare } = await import('./pages/Carbon')

let n = 0
const season = () => `s-sim-${++n}` // a fresh cache key per test
const ACTUAL = { crop_season_id: 's', total_co2e_kg: 3473.4671, co2e_per_kg: 0.5789, calculated_at: '2026-09-20T00:00:00Z', breakdown: [], warnings: [] }
const AWD = { crop_season_id: 's', total_co2e_kg: 2100, co2e_per_kg: 0.35, calculated_at: '2026-09-21T00:00:00Z', breakdown: [], warnings: [] }
const notYet = () => new ApiError(404, 'no_calculation', 'none')

afterEach(() => { cleanup(); getCarbon.mockReset(); calculateCarbon.mockReset() })

describe('ScenarioCompare', () => {
  it('shows a stored simulation, "Chưa tính" for a missing one, and a writer can calculate it', async () => {
    const id = season()
    let flooding: unknown = null
    getCarbon.mockImplementation(async (_id: string, s: string) => {
      if (s === 'awd') return AWD
      if (flooding) return flooding
      throw notYet()
    })
    calculateCarbon.mockImplementation(async () => { flooding = { ...AWD, total_co2e_kg: 5200, co2e_per_kg: 0.87 } })
    render(<ScenarioCompare seasonId={id} actual={ACTUAL as never} canCalculate />)
    await screen.findByTestId('carbon-scenarios')
    expect(screen.getByTestId('carbon-scenario-awd').textContent).toContain('2.100 kg CO₂e')
    const missing = screen.getByTestId('carbon-scenario-continuous_flooding')
    expect(missing.textContent).toContain('Chưa tính')
    expect(getCarbon.mock.calls.every(([, s]) => s !== 'as_recorded')).toBe(true)

    fireEvent.click(screen.getByRole('button', { name: 'Tính kịch bản' }))
    await waitFor(() => expect(screen.getByTestId('carbon-scenario-continuous_flooding').textContent).toContain('5.200 kg CO₂e'))
    expect(calculateCarbon).toHaveBeenCalledWith(id, 'continuous_flooding')
    expect(getCarbon.mock.calls.every(([, s]) => s !== 'as_recorded')).toBe(true)
    // The actual result is untouched.
    expect(document.body.textContent).toMatch(/Kết quả vận hành[^]*3\.473(,\d+)? kg CO₂e/)
  })

  it('a reader without write authority sees "no calculation yet" and no button', async () => {
    getCarbon.mockRejectedValue(notYet())
    render(<ScenarioCompare seasonId={season()} actual={ACTUAL as never} canCalculate={false} />)
    await screen.findByTestId('carbon-scenarios')
    expect(screen.queryByRole('button')).toBeNull()
    expect(screen.getAllByText('Chưa có bản tính cho kịch bản này.')).toHaveLength(2)
  })

  it('a failed calculation is reported and the stored scenarios stay as they were', async () => {
    getCarbon.mockImplementation(async (_id: string, s: string) => { if (s === 'awd') return AWD; throw notYet() })
    calculateCarbon.mockRejectedValue(new Error('Vụ chưa đủ dữ liệu để tính kịch bản.'))
    render(<ScenarioCompare seasonId={season()} actual={ACTUAL as never} canCalculate />)
    await screen.findByTestId('carbon-scenarios')
    fireEvent.click(screen.getByRole('button', { name: 'Tính kịch bản' }))
    expect((await screen.findByRole('alert')).textContent).toBe('Vụ chưa đủ dữ liệu để tính kịch bản.')
    expect(screen.getByTestId('carbon-scenario-awd').textContent).toContain('2.100 kg CO₂e')
  })

  it('a real read failure (not "no calculation") is an error, not "Chưa tính"', async () => {
    getCarbon.mockRejectedValue(new ApiError(500, 'internal_error', 'Máy chủ lỗi'))
    render(<ScenarioCompare seasonId={season()} actual={ACTUAL as never} canCalculate />)
    await waitFor(() => expect(document.body.textContent).toContain('Máy chủ lỗi'))
    expect(screen.queryByTestId('carbon-scenarios')).toBeNull()
  })
})
