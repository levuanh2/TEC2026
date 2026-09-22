import { describe, expect, it } from 'vitest'
import { activityFields, presentActivity } from './activityPresentation'

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

/* The real tenant's payloads carry columns the mock's never did, and the
 * detail drawer printed all of them: a uuid, two ISO timestamps, four database
 * column names and a raw `awd`. */
describe('activityFields — the detail drawer', () => {
  const irrigation = JSON.stringify({
    activity_id: '5167f018-7856-46c1-a334-08882e761fbd',
    method: 'awd',
    water_volume_m3: 320,
    duration_minutes: null,
    pump_energy_kwh: 12,
    secret_internal_column: 'x',
    created_at: '2026-09-08T19:19:19.845233+00:00',
    updated_at: '2026-09-08T19:19:19.845233+00:00',
  })

  it('drops bookkeeping columns rather than showing a uuid or an ISO timestamp', () => {
    const rows = activityFields(irrigation)
    const blob = JSON.stringify(rows)
    expect(blob).not.toMatch(/5167f018-7856-46c1-a334-08882e761fbd/)
    expect(blob).not.toMatch(/2026-09-08T19:19:19/)
    expect(rows.map((r) => r.label)).not.toContain('activity_id')
    expect(rows.map((r) => r.label)).not.toContain('created_at')
  })

  it('drops a key it has no Vietnamese label for, instead of printing the column name', () => {
    expect(activityFields(irrigation).map((r) => r.label)).not.toContain('secret_internal_column')
  })

  it('reads a stored enum through the dictionary', () => {
    expect(activityFields(irrigation)).toContainEqual({ label: 'Phương pháp', value: 'Tưới ngập–khô xen kẽ (AWD)' })
  })

  it('still shows a labelled field, and an empty one as a dash', () => {
    const rows = activityFields(irrigation)
    expect(rows).toContainEqual({ label: 'Lượng nước (m³)', value: '320' })
    expect(rows).toContainEqual({ label: 'Điện bơm (kWh)', value: '12' })
    expect(rows).toContainEqual({ label: 'Thời gian tưới (phút)', value: '—' })
  })

  it('replaces the demo seed scaffolding wherever it appears', () => {
    expect(activityFields(JSON.stringify({ product_name: 'Demo pesticide', amount: 2 })))
      .toContainEqual({ label: 'Tên sản phẩm', value: 'Dữ liệu minh họa' })
    expect(presentActivity('pesticide', JSON.stringify({ product_name: 'Demo pesticide', amount: 2 })).summary)
      .toBe('Dữ liệu minh họa · 2')
  })
})
