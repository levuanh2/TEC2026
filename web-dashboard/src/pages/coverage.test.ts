import { describe, expect, it } from 'vitest'
import type { FarmPerformance } from '../api/organizations'
import { SEASON_COVERAGE_PENDING, coverageLine, coverageOf, missingReason } from './coverage'

const farm = (id: string, over: Partial<FarmPerformance> = {}): FarmPerformance => ({
  farmId: id, farmName: `Hộ ${id}`, areaHa: 2, yieldKg: 5000, waterPerKg: 0.06, fertilizerPerKg: 0.03,
  co2ePerKg: null, costPerKg: null, dataStatus: 'partial', ...over,
})

describe('aggregate coverage from the farm-performance payload', () => {
  const farms = [
    farm('a'),
    farm('b', { yieldKg: null, waterPerKg: null, fertilizerPerKg: null }),
    farm('c', { waterPerKg: null }),
    farm('d', { yieldKg: 0, waterPerKg: null, fertilizerPerKg: null, dataStatus: 'missing' }),
  ]

  it('counts the farms that carry the server figure, never a recomputed one', () => {
    const c = coverageOf(farms, 'water')
    expect(c.total).toBe(4)
    expect(c.valid).toBe(1)
    expect(coverageLine(c)).toBe('Dựa trên 1/4 nông hộ đủ dữ liệu')
  })

  it('lists exactly the missing farms, each with its own reason', () => {
    expect(coverageOf(farms, 'water').missing.map((x) => [x.farm.farmId, x.reason])).toEqual([
      ['b', 'Có vụ thiếu sản lượng thu hoạch'],
      ['c', 'Có vụ thiếu lượng nước tưới'],
      ['d', 'Chưa có vụ nào có dữ liệu'],
    ])
  })

  it('names the metric-specific gap once yield is present', () => {
    expect(missingReason(farm('x', { costPerKg: null }), 'cost')).toBe('Có vụ còn hoạt động chưa ghi chi phí')
    expect(missingReason(farm('x'), 'carbon')).toBe('Có vụ chưa có kết quả Carbon')
    expect(coverageOf([farm('x', { co2ePerKg: 0.9 })], 'carbon').valid).toBe(1)
  })

  it('an empty scope is 0/0, not a silent full coverage', () => {
    expect(coverageLine(coverageOf([], 'cost'))).toBe('Dựa trên 0/0 nông hộ đủ dữ liệu')
  })

  it('the per-season count is stated as pending, never invented', () => {
    expect(SEASON_COVERAGE_PENDING).toBe('Chưa có dữ liệu tổng hợp — cần endpoint chỉ số theo lô.')
  })
})
