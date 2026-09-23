import { describe, expect, it } from 'vitest'
import { farmArea } from './area'

describe('farmArea', () => {
  it('sums the recorded plot areas', () => {
    expect(farmArea([{ areaHa: 1.3 }, { areaHa: 0.7 }])).toEqual({ ha: 2, complete: true, plots: 2 })
  })
  it('never counts a plot without an area as zero', () => {
    expect(farmArea([{ areaHa: 1.3 }, { areaHa: null }])).toEqual({ ha: 1.3, complete: false, plots: 2 })
  })
  it('has no area at all when no plot records one', () => {
    expect(farmArea([{}, { areaHa: undefined }])).toEqual({ ha: null, complete: false, plots: 2 })
    expect(farmArea([])).toEqual({ ha: null, complete: true, plots: 0 })
  })
})
