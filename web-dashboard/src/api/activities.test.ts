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

  it('builds the seeding payload using cost_vnd, not total_cost_vnd (FW-2 Part 3 §6)', () => {
    const input: ActivityInput = {
      activityType: 'seeding',
      data: { varietyName: 'OM5451', seedKg: 120, seedingMethod: 'sạ lan', costVnd: 500000 },
    }
    const payload = activityDataPayload(input)
    expect(payload).toEqual({
      variety_name: 'OM5451', seed_kg: 120, seeding_method: 'sạ lan', cost_vnd: 500000,
    })
    expect(payload.total_cost_vnd).toBeUndefined()
  })

  it('builds the seeding payload preserving null (blank) cost, not 0', () => {
    const input: ActivityInput = {
      activityType: 'seeding',
      data: { varietyName: null, seedKg: 120, seedingMethod: null, costVnd: null },
    }
    expect(activityDataPayload(input).cost_vnd).toBeNull()
  })

  it('builds the pesticide payload with snake_case keys', () => {
    const input: ActivityInput = {
      activityType: 'pesticide',
      data: { productName: 'Regent', activeIngredient: 'Fipronil', amount: 0.5, unit: 'kg', totalCostVnd: 120000 },
    }
    expect(activityDataPayload(input)).toEqual({
      product_name: 'Regent', active_ingredient: 'Fipronil', amount: 0.5, unit: 'kg', total_cost_vnd: 120000,
    })
  })

  it('builds the straw_management payload and never sends the methodology-only fields from the form', () => {
    const input: ActivityInput = {
      activityType: 'straw_management',
      data: { method: 'burned', strawMassKg: 4000, totalCostVnd: null },
    }
    const payload = activityDataPayload(input)
    expect(payload).toEqual({ method: 'burned', straw_mass_kg: 4000, total_cost_vnd: null })
    expect(payload.days_before_cultivation).toBeUndefined()
    expect(payload.dry_matter_fraction).toBeUndefined()
    expect(payload.returned_to_field).toBeUndefined()
  })

  it('builds the straw_management payload preserving null (blank) mass, not 0', () => {
    const input: ActivityInput = {
      activityType: 'straw_management',
      data: { method: 'incorporated', strawMassKg: null, totalCostVnd: null },
    }
    expect(activityDataPayload(input).straw_mass_kg).toBeNull()
  })
})
