import { describe, expect, it } from 'vitest'
import { activityDataPayload, type ActivityInput } from './activities'

describe('activityDataPayload (exact runtime field names, backend/schemas.py)', () => {
  it('builds the fertilizer payload with snake_case keys and null for omitted optionals', () => {
    const input: ActivityInput = {
      activityType: 'fertilizer',
      data: { fertilizerName: 'Urê', fertilizerType: null, amountKg: 120, nitrogenPercent: 46, phosphorusPercent: null, potassiumPercent: null, totalCostVnd: 850000 },
    }
    expect(activityDataPayload(input)).toEqual({
      fertilizer_name: 'Urê', fertilizer_type: null, amount_kg: 120,
      nitrogen_percent: 46, phosphorus_percent: null, potassium_percent: null,
      total_cost_vnd: 850000,
    })
  })

  it('builds the irrigation payload preserving null (blank) water volume, not 0', () => {
    const input: ActivityInput = {
      activityType: 'irrigation',
      data: { method: 'awd', waterVolumeM3: null, durationMinutes: null, waterLevelCm: null, pumpEnergyKwh: null, totalCostVnd: null },
    }
    expect(activityDataPayload(input)).toEqual({
      method: 'awd', water_volume_m3: null, duration_minutes: null,
      water_level_cm: null, pump_energy_kwh: null, total_cost_vnd: null,
    })
  })

  it('builds the irrigation payload preserving an explicit 0 water volume', () => {
    const input: ActivityInput = {
      activityType: 'irrigation',
      data: { method: 'awd', waterVolumeM3: 0, durationMinutes: null, waterLevelCm: null, pumpEnergyKwh: null, totalCostVnd: null },
    }
    expect(activityDataPayload(input).water_volume_m3).toBe(0)
  })

  it('builds the harvest payload with yield_kg required', () => {
    const input: ActivityInput = {
      activityType: 'harvest',
      data: { yieldKg: 3100, harvestedAreaHa: 1.2, moisturePercent: 14, totalCostVnd: null },
    }
    expect(activityDataPayload(input)).toEqual({
      yield_kg: 3100, harvested_area_ha: 1.2, moisture_percent: 14, total_cost_vnd: null,
    })
  })
})
