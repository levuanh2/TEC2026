import { describe, expect, it } from 'vitest'
import { co2eKg, perKg, vndPerKg } from './format'

/* Precision policy (Round 5, docs/WEB_LOGIC_UAT_ROUND5.md §precision): the
 * display rounds, it never changes a value, and a missing value is never 0. */
const nbsp = (s: string) => s.replace(/ /g, ' ')

describe('display precision', () => {
  it('kg CO₂e totals keep 2 decimals', () => {
    expect(nbsp(co2eKg(3473.4671))).toBe('3.473,47 kg CO₂e')
    expect(nbsp(co2eKg(0.004))).toBe('0 kg CO₂e')
  })
  it('₫/kg is whole đồng', () => {
    expect(nbsp(vndPerKg(1090.385))).toBe('1.090')
  })
  it('per-kg intensities keep 3 decimals (0,997 never becomes "1")', () => {
    expect(nbsp(perKg(0.997, 'kg CO₂e/kg'))).toBe('0,997 kg CO₂e/kg')
  })
  it('missing is "not enough data" (or the caller\'s text), never 0', () => {
    expect(co2eKg(null)).toBe('Chưa đủ dữ liệu')
    expect(vndPerKg(undefined)).toBe('Chưa đủ dữ liệu')
    expect(co2eKg(null, '—')).toBe('—')
    expect(vndPerKg(null, '—')).toBe('—')
    expect(co2eKg(0)).not.toBe('Chưa đủ dữ liệu')
  })
})
