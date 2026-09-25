// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

/* Round 4.3 gate — Management Performance must not fan out per season. It
 * reads exactly three organisation endpoints; coverage comes from the
 * farm-performance rows it already has. */

const calls: string[] = []
vi.mock('../api/organizations', () => ({
  getOrganization: async () => { calls.push('organization'); return { id: 'o', code: 'O', name: 'HTX Demo', organizationType: 'cooperative', isActive: true } },
  getOrganizationMetrics: async () => {
    calls.push('metrics')
    return { waterPerKg: null, fertilizerPerKg: 0.03, co2ePerKg: null, costPerKg: null, yieldKg: null, waterM3: null, fertilizerKg: null, totalCo2eKg: null, completeness: { water: false, fertilizer: true, cost: false, carbon: false } }
  },
  getFarmPerformance: async () => {
    calls.push('farm-performance')
    return [
      { farmId: 'f1', farmName: 'Hộ 1', areaHa: 2, yieldKg: 5000, waterPerKg: 0.06, fertilizerPerKg: 0.03, co2ePerKg: null, costPerKg: null, dataStatus: 'partial' },
      { farmId: 'f2', farmName: 'Hộ 2', areaHa: 3, yieldKg: 4000, waterPerKg: null, fertilizerPerKg: 0.03, co2ePerKg: null, costPerKg: null, dataStatus: 'partial' },
    ]
  },
}))
const perSeason = vi.fn()
vi.mock('../api/metrics', () => ({ getResourceMetrics: (...a: unknown[]) => { perSeason(...a); return Promise.resolve(null) } }))
const farmsApi = vi.fn()
vi.mock('../api/farms', () => ({
  usingMockData: false,
  listFarms: (...a: unknown[]) => { farmsApi('listFarms', ...a); return Promise.resolve([]) },
  getFarmCropSeasons: (...a: unknown[]) => { farmsApi('seasons', ...a); return Promise.resolve([]) },
  getPlotsForFarm: (...a: unknown[]) => { farmsApi('plots', ...a); return Promise.resolve([]) },
}))

const { PerformancePage } = await import('./performance')

afterEach(cleanup)

describe('Management Performance request budget', () => {
  it('reads three org endpoints once each and no per-season /metrics', async () => {
    render(<PerformancePage organizationId="o" />)
    await waitFor(() => expect(screen.getAllByTestId('aggregate-coverage')[0].textContent).toMatch(/1\/2 nông hộ/))
    expect([...calls].sort()).toEqual(['farm-performance', 'metrics', 'organization'])
    expect(perSeason).not.toHaveBeenCalled()
    expect(farmsApi).not.toHaveBeenCalled()
    // Water: one farm of two. Fertiliser: both. Cost and Carbon: none.
    // Round 4.4: one sentence per aggregate; a count of farms, never a grade.
    expect(screen.getAllByTestId('aggregate-coverage').map((n) => n.textContent)).toEqual([
      'Chưa công bố chỉ số toàn HTX — mới có 1/2 nông hộ đủ dữ liệu.',
      'Tính trên 2/2 nông hộ đủ dữ liệu.',
      'Chưa công bố chỉ số toàn HTX — 2/2 nông hộ còn thiếu dữ liệu.',
      'Chưa công bố chỉ số toàn HTX — 2/2 nông hộ còn thiếu dữ liệu.',
    ])
    for (const n of screen.getAllByTestId('aggregate-season-coverage')) {
      expect(n.textContent).toBe('Tính theo nông hộ; chưa có tổng hợp chi tiết theo từng vụ.')
    }
  })
})
