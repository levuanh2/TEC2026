import { describe, expect, it } from 'vitest'
import { isSupportedActivityType, numOrUndef, QUICK_ENTRY_ACTIVE } from './ActivityForms'

// Numeric activity-detail fields are Postgres `numeric` columns: the read
// endpoint (PostgREST) serializes them as JSON numbers, but the write
// response (psycopg Decimal through FastAPI's Any-typed dict) serializes the
// same field as a JSON string — found via the real Farmer write E2E, where
// the harvest confirmation toast rendered "Đã ghi nhận thu hoạch  kg." (empty)
// because `typeof y === 'number'` rejected the string form.
describe('numOrUndef', () => {
  it('accepts a plain JSON number (read endpoint shape)', () => {
    expect(numOrUndef(5)).toBe(5)
    expect(numOrUndef(5.0)).toBe(5)
  })
  it('accepts a numeric string (write response shape)', () => {
    expect(numOrUndef('5')).toBe(5)
    expect(numOrUndef('120.5')).toBe(120.5)
  })
  it('returns undefined for null/undefined/blank/non-numeric', () => {
    expect(numOrUndef(null)).toBeUndefined()
    expect(numOrUndef(undefined)).toBeUndefined()
    expect(numOrUndef('')).toBeUndefined()
    expect(numOrUndef('  ')).toBeUndefined()
    expect(numOrUndef('abc')).toBeUndefined()
    expect(numOrUndef(Number.NaN)).toBeUndefined()
  })
})

describe('isSupportedActivityType (FW-2 Part 3)', () => {
  it('accepts all six writable types', () => {
    for (const type of ['fertilizer', 'irrigation', 'harvest', 'seeding', 'pesticide', 'straw_management']) {
      expect(isSupportedActivityType(type)).toBe(true)
    }
  })
  it('rejects an unwritable/unknown type', () => {
    expect(isSupportedActivityType('fuel')).toBe(false)
    expect(isSupportedActivityType('other')).toBe(false)
  })
})

describe('QUICK_ENTRY_ACTIVE (FW-2 Part 3 — nothing left "Sắp có")', () => {
  it('lists all six activity types with no disabled placeholders remaining', () => {
    expect(QUICK_ENTRY_ACTIVE.map((e) => e.type).sort()).toEqual(
      ['fertilizer', 'harvest', 'irrigation', 'pesticide', 'seeding', 'straw_management'].sort(),
    )
  })
})
