import { describe, expect, it } from 'vitest'
import { presentActivity } from './activityPresentation'

describe('activity presentation', () => {
  it('turns an irrigation payload into a human-readable summary', () => {
    // `awd` used to be printed straight from the payload onto the screen.
    expect(presentActivity('irrigation', JSON.stringify({ method: 'awd', water_volume_m3: 32 })))
      .toMatchObject({ label: 'Nước tưới', summary: 'Tưới ngập–khô xen kẽ (AWD) · 32 m³' })
  })
  it('never prints a raw enum for a fuel or straw payload either', () => {
    expect(presentActivity('fuel', JSON.stringify({ fuel_type: 'diesel', amount_liter: 15 })).summary)
      .toBe('Dầu diesel · 15 L')
    expect(presentActivity('straw_management', JSON.stringify({ management_method: 'incorporated', straw_mass_kg: 800 })).summary)
      .toBe('Vùi vào đất · 800 kg')
  })
  it('keeps missing values distinct from a real zero', () => {
    expect(presentActivity('harvest', JSON.stringify({ yield_kg: 0 })).summary).toBe('0 kg')
    expect(presentActivity('harvest', JSON.stringify({})).summary).toBe('Chưa có dữ liệu')
  })
})
