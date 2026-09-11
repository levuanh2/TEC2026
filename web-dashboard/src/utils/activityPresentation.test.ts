import { describe, expect, it } from 'vitest'
import { presentActivity } from './activityPresentation'

describe('activity presentation', () => {
  it('turns an irrigation payload into a human-readable summary', () => {
    expect(presentActivity('irrigation', JSON.stringify({ method: 'awd', water_volume_m3: 32 }))).toMatchObject({ label: 'Nước tưới', summary: 'awd · 32 m³' })
  })
  it('keeps missing values distinct from a real zero', () => {
    expect(presentActivity('harvest', JSON.stringify({ yield_kg: 0 })).summary).toBe('0 kg')
    expect(presentActivity('harvest', JSON.stringify({})).summary).toBe('Chưa có dữ liệu')
  })
})
