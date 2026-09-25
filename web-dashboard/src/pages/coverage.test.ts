import { describe, expect, it } from 'vitest'
import type { FarmPerformance } from '../api/organizations'
import { COVERAGE_BASIS, HARVEST_COPY, coverageOf, coverageSentence, harvestState, missingReason } from './coverage'

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
    expect(coverageSentence(c, false)).toBe('Chưa công bố chỉ số toàn HTX — mới có 1/4 nông hộ đủ dữ liệu.')
  })

  it('lists exactly the missing farms, each with its own reason', () => {
    expect(coverageOf(farms, 'water').missing.map((x) => [x.farm.farmId, x.reason])).toEqual([
      ['b', 'Có vụ chưa ghi sản lượng thu hoạch'],
      ['c', 'Có vụ thiếu lượng nước tưới'],
      ['d', 'Chưa có vụ mùa nào'],
    ])
  })

  it('names the metric-specific gap once yield is present', () => {
    expect(missingReason(farm('x', { costPerKg: null }), 'cost')).toBe('Có vụ còn hoạt động chưa ghi chi phí')
    expect(missingReason(farm('x'), 'carbon')).toBe('Có vụ chưa có kết quả Carbon')
    expect(coverageOf([farm('x', { co2ePerKg: 0.9 })], 'carbon').valid).toBe(1)
  })

  it('an empty scope is said, not a silent full coverage', () => {
    expect(coverageSentence(coverageOf([], 'cost'), false)).toBe('Chưa công bố chỉ số toàn HTX — HTX chưa có nông hộ nào.')
  })

  it('the per-season count is never invented, and never phrased as developer copy', () => {
    expect(COVERAGE_BASIS).toBe('Tính theo nông hộ; chưa có tổng hợp chi tiết theo từng vụ.')
    expect(COVERAGE_BASIS).not.toMatch(/endpoint|API|batch/i)
  })
})

describe('Round 4.4: harvest state from a per-farm yield that is null when ANY season lacks one', () => {
  it('a figure means every season is harvested', () => {
    expect(harvestState(farm('x', { yieldKg: 5200 }))).toBe('recorded')
  })
  it('null with seasons is "some season missing" — never "no harvest"', () => {
    // 1 farm, season A 5 200 kg + season B no harvest → the server sends null.
    expect(harvestState(farm('x', { yieldKg: null, dataStatus: 'partial' }))).toBe('incomplete')
    expect(HARVEST_COPY.incomplete).toBe('Có vụ chưa ghi sản lượng thu hoạch')
  })
  it('only a farm with no season at all is "no harvest"', () => {
    expect(harvestState(farm('x', { yieldKg: null, dataStatus: 'missing' }))).toBe('none')
    expect(HARVEST_COPY.none).toBe('Chưa có sản lượng thu hoạch')
  })
  it('no state reads the old, false "Chưa ghi thu hoạch"', () => {
    expect(Object.values(HARVEST_COPY)).not.toContain('Chưa ghi thu hoạch')
  })
  it('a withheld figure names its cause once; coverage is a count, not a grade', () => {
    expect(coverageSentence({ total: 3, valid: 0, missing: [] }, false)).toBe('Chưa công bố chỉ số toàn HTX — 3/3 nông hộ còn thiếu dữ liệu.')
    expect(coverageSentence({ total: 3, valid: 1, missing: [] }, false)).toBe('Chưa công bố chỉ số toàn HTX — mới có 1/3 nông hộ đủ dữ liệu.')
    expect(coverageSentence({ total: 3, valid: 3, missing: [] }, true)).toBe('Tính trên 3/3 nông hộ đủ dữ liệu.')
  })
})
