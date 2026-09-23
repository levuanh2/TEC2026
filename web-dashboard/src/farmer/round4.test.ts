import { describe, expect, it } from 'vitest'
import { hasDemoData, isDemoDisclaimer } from '../utils/activityPresentation'
import { viewActivity } from './activityView'
import { requiredFieldsFor, requiredErrors } from './activityValidation'

const DISCLAIMER = 'DEMO / SYNTHETIC DATA — NOT FIELD DATA, NOT OFFICIAL MRV DATA'

describe('demo disclaimer', () => {
  it('is recognised and never shown as a per-row note', () => {
    expect(isDemoDisclaimer(DISCLAIMER)).toBe(true)
    const v = viewActivity({ type: 'harvest', detail: JSON.stringify({ yield_kg: 5200, note: DISCLAIMER }) })
    expect(v.note).toBeNull()
  })
  it("keeps the farmer's own note", () => {
    const v = viewActivity({ type: 'harvest', detail: JSON.stringify({ yield_kg: 5200, note: 'Gặt sớm vì mưa' }) })
    expect(v.note).toBe('Gặt sớm vì mưa')
  })
  it('marks a ledger that holds any seeded row', () => {
    expect(hasDemoData([{ detail: JSON.stringify({ note: DISCLAIMER }) }, { detail: '{}' }])).toBe(true)
    expect(hasDemoData([{ detail: '{}' }])).toBe(false)
  })
})

describe('readiness gap → required form field', () => {
  it('maps only codes that have a field on the form', () => {
    expect(requiredFieldsFor(['straw_dry_matter', 'straw_days_before_cultivation', 'fuel_factor_unverified']))
      .toEqual(['daysBeforeCultivation', 'dryMatterFraction'])
  })
  it('flags a blank required field and nothing else', () => {
    expect(requiredErrors(['dryMatterFraction'], { dryMatterFraction: ' ', daysBeforeCultivation: '' })).toEqual({
      dryMatterFraction: expect.stringMatching(/cần để tính phát thải/),
    })
  })
})
