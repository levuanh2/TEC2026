import { describe, expect, it } from 'vitest'
import {
  blankToNumber, numberFormatErrors, validateFertilizer, validateHarvest, validateIrrigation,
  validatePesticide, validateSeeding, validateStrawManagement,
} from './activityValidation'

const fertilizerBase = { fertilizerName: 'Urê', amountKg: 120, nitrogenPercent: 46, phosphorusPercent: null, potassiumPercent: null, totalCostVnd: null }
const irrigationBase = { method: 'awd', waterVolumeM3: 32, durationMinutes: null, waterLevelCm: null, pumpEnergyKwh: null, totalCostVnd: null }
const harvestBase = { yieldKg: 3100, harvestedAreaHa: null, moisturePercent: null, totalCostVnd: null }
const seedingBase = { seedKg: 120, costVnd: null }
const pesticideBase = { productName: 'Regent', amount: 0.5, unit: 'kg', totalCostVnd: null }
const strawBase = { method: 'incorporated', strawMassKg: 4000, totalCostVnd: null }

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

describe('seeding validation', () => {
  it('accepts a valid draft', () => {
    expect(validateSeeding(seedingBase)).toEqual({})
  })
  it('rejects seedKg <= 0', () => {
    expect(validateSeeding({ ...seedingBase, seedKg: 0 }).seedKg).toBeDefined()
    expect(validateSeeding({ ...seedingBase, seedKg: null }).seedKg).toBeDefined()
  })
  it('rejects negative cost', () => {
    expect(validateSeeding({ ...seedingBase, costVnd: -1 }).costVnd).toBeDefined()
  })
  it('accepts cost omitted (blank stays null, not an error)', () => {
    expect(validateSeeding({ ...seedingBase, costVnd: null })).toEqual({})
  })
})

describe('pesticide validation', () => {
  it('accepts a valid draft', () => {
    expect(validatePesticide(pesticideBase)).toEqual({})
  })
  it('requires a product name', () => {
    expect(validatePesticide({ ...pesticideBase, productName: '  ' }).productName).toBeDefined()
  })
  it('rejects amount <= 0', () => {
    expect(validatePesticide({ ...pesticideBase, amount: 0 }).amount).toBeDefined()
  })
  it('requires a unit', () => {
    expect(validatePesticide({ ...pesticideBase, unit: '' }).unit).toBeDefined()
  })
  it('rejects negative cost', () => {
    expect(validatePesticide({ ...pesticideBase, totalCostVnd: -1 }).totalCostVnd).toBeDefined()
  })
})

describe('straw management validation', () => {
  it('accepts a valid draft', () => {
    expect(validateStrawManagement(strawBase)).toEqual({})
  })
  it('rejects an unsupported method', () => {
    expect(validateStrawManagement({ ...strawBase, method: 'composted_extra' }).method).toBeDefined()
  })
  it('accepts mass omitted (blank stays null, not an error)', () => {
    expect(validateStrawManagement({ ...strawBase, strawMassKg: null })).toEqual({})
  })
  it('rejects negative mass/cost', () => {
    expect(validateStrawManagement({ ...strawBase, strawMassKg: -1 }).strawMassKg).toBeDefined()
    expect(validateStrawManagement({ ...strawBase, totalCostVnd: -1 }).totalCostVnd).toBeDefined()
  })
  it('accepts every backend-supported enum value', () => {
    for (const method of ['incorporated', 'removed', 'burned', 'composted', 'other']) {
      expect(validateStrawManagement({ ...strawBase, method })).toEqual({})
    }
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

describe('number text parsing', () => {
  it('accepts a decimal comma and a decimal point alike', () => {
    expect(blankToNumber('0,85')).toBe(0.85)
    expect(blankToNumber('0.85')).toBe(0.85)
  })
  it('turns unparseable text into NaN, never into null (unknown)', () => {
    for (const bad of ['abc', '1,2,3', '1.000,5', '1e3', '0x10', 'Infinity']) {
      expect(Number.isNaN(blankToNumber(bad))).toBe(true)
    }
  })
  it('never rescales a percentage into a fraction', () => {
    expect(blankToNumber('85')).toBe(85)
  })
  it('numberFormatErrors flags bad text and non-integers where the backend wants an int', () => {
    expect(numberFormatErrors({ a: '', b: '12', c: '0,5' })).toEqual({})
    expect(Object.keys(numberFormatErrors({ a: 'abc' }))).toEqual(['a'])
    expect(Object.keys(numberFormatErrors({ d: '1.5' }, ['d']))).toEqual(['d'])
    expect(numberFormatErrors({ d: '15' }, ['d'])).toEqual({})
  })
})
