import { describe, expect, it } from 'vitest'
import { blankToNumber, validateFertilizer, validateHarvest, validateIrrigation } from './activityValidation'

const fertilizerBase = { fertilizerName: 'Urê', amountKg: 120, nitrogenPercent: 46, phosphorusPercent: null, potassiumPercent: null, totalCostVnd: null }
const irrigationBase = { method: 'awd', waterVolumeM3: 32, durationMinutes: null, waterLevelCm: null, pumpEnergyKwh: null, totalCostVnd: null }
const harvestBase = { yieldKg: 3100, harvestedAreaHa: null, moisturePercent: null, totalCostVnd: null }

describe('fertilizer validation', () => {
  it('accepts a valid draft', () => {
    expect(validateFertilizer(fertilizerBase)).toEqual({})
  })
  it('rejects amount <= 0', () => {
    expect(validateFertilizer({ ...fertilizerBase, amountKg: 0 }).amountKg).toBe('Lượng phân phải lớn hơn 0.')
    expect(validateFertilizer({ ...fertilizerBase, amountKg: -5 }).amountKg).toBe('Lượng phân phải lớn hơn 0.')
  })
  it('rejects nitrogen outside 0-100', () => {
    expect(validateFertilizer({ ...fertilizerBase, nitrogenPercent: 101 }).nitrogenPercent).toBe('Hàm lượng đạm phải từ 0 đến 100%.')
    expect(validateFertilizer({ ...fertilizerBase, nitrogenPercent: -1 }).nitrogenPercent).toBe('Hàm lượng đạm phải từ 0 đến 100%.')
  })
  it('rejects negative cost', () => {
    expect(validateFertilizer({ ...fertilizerBase, totalCostVnd: -1 }).totalCostVnd).toBe('Chi phí không thể là số âm.')
  })
  it('requires a fertilizer name', () => {
    expect(validateFertilizer({ ...fertilizerBase, fertilizerName: '  ' }).fertilizerName).toBeDefined()
  })
})

describe('irrigation validation', () => {
  it('accepts a valid draft with water omitted (blank stays null, not an error)', () => {
    expect(validateIrrigation({ ...irrigationBase, waterVolumeM3: null })).toEqual({})
  })
  it('accepts an explicit zero for water', () => {
    expect(validateIrrigation({ ...irrigationBase, waterVolumeM3: 0 })).toEqual({})
  })
  it('rejects negative water/duration/energy/cost', () => {
    expect(validateIrrigation({ ...irrigationBase, waterVolumeM3: -1 }).waterVolumeM3).toBeDefined()
    expect(validateIrrigation({ ...irrigationBase, durationMinutes: -1 }).durationMinutes).toBeDefined()
    expect(validateIrrigation({ ...irrigationBase, pumpEnergyKwh: -1 }).pumpEnergyKwh).toBeDefined()
    expect(validateIrrigation({ ...irrigationBase, totalCostVnd: -1 }).totalCostVnd).toBeDefined()
  })
  it('rejects an unsupported method', () => {
    expect(validateIrrigation({ ...irrigationBase, method: 'flood-it' }).method).toBeDefined()
  })
})

describe('harvest validation', () => {
  it('accepts a valid draft', () => {
    expect(validateHarvest(harvestBase)).toEqual({})
  })
  it('rejects yield <= 0', () => {
    expect(validateHarvest({ ...harvestBase, yieldKg: 0 }).yieldKg).toBeDefined()
  })
  it('rejects harvested area <= 0 when provided', () => {
    expect(validateHarvest({ ...harvestBase, harvestedAreaHa: 0 }).harvestedAreaHa).toBeDefined()
  })
  it('rejects moisture outside 0-100', () => {
    expect(validateHarvest({ ...harvestBase, moisturePercent: 101 }).moisturePercent).toBeDefined()
  })
})

describe('blankToNumber (blank vs zero semantics, brief §12)', () => {
  it('maps an empty string to null, not 0', () => {
    expect(blankToNumber('')).toBeNull()
    expect(blankToNumber('   ')).toBeNull()
  })
  it('maps an explicit 0 to 0', () => {
    expect(blankToNumber('0')).toBe(0)
  })
  it('parses a normal number', () => {
    expect(blankToNumber('32.5')).toBe(32.5)
  })
})
