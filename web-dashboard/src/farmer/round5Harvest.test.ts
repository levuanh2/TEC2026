import { describe, expect, it } from 'vitest'
import { validateHarvest } from './activityValidation'
import { mapActivityError } from './activityErrors'
import { ApiError } from '../api/client'

const draft = (harvestedAreaHa: number | null, plotAreaHa: number | null = 1.25) =>
  ({ yieldKg: 6000, harvestedAreaHa, moisturePercent: null, totalCostVnd: null, plotAreaHa })

describe('harvested area is bounded by the plot area', () => {
  it('refuses more than the plot, next to the field, in Vietnamese', () => {
    expect(validateHarvest(draft(1.3)).harvestedAreaHa).toBe('Diện tích thu hoạch không được lớn hơn diện tích thửa (1,25 ha).')
  })
  it('accepts exactly the plot area and less', () => {
    expect(validateHarvest(draft(1.25)).harvestedAreaHa).toBeUndefined()
    expect(validateHarvest(draft(0.5)).harvestedAreaHa).toBeUndefined()
  })
  it('applies no bound when the plot area is unknown', () => {
    expect(validateHarvest(draft(3, null)).harvestedAreaHa).toBeUndefined()
  })
  it('the error clears as soon as the value is valid again', () => {
    expect(validateHarvest(draft(2)).harvestedAreaHa).toBeTruthy()
    expect(validateHarvest(draft(1)).harvestedAreaHa).toBeUndefined()
  })
  it('shows the server refusal in Vietnamese, not raw JSON', () => {
    const err = new ApiError(422, 'harvested_area_exceeds_plot', 'Diện tích thu hoạch (1.3 ha) không được lớn hơn diện tích thửa (1.25 ha).')
    expect(mapActivityError(err)).toEqual({ message: err.message, retryable: false })
  })
})
