import { describe, expect, it } from 'vitest'
import type { SeasonMetrics } from '../api/metrics'
import type { Recommendation } from '../api/recommendations'
import { buildAttention, dayLabel, groupByDay, initials, isDemoPlaceholder, viewActivity } from './activityView'
import { metricViews } from './metricsView'

const act = (type: string, payload: Record<string, unknown>) => ({ type, detail: JSON.stringify(payload) })

const metrics = (over: Partial<SeasonMetrics> = {}): SeasonMetrics => ({
  yieldKg: 5200, waterM3: 320, fertilizerKg: 150, totalCo2eKg: null,
  waterPerKg: 0.0615, fertilizerPerKg: 0.0288, co2ePerKg: null, costPerKg: null,
  completeness: { water: true, fertilizer: true, cost: false, carbon: false },
  ...over,
})

describe('viewActivity (Farmer journal presentation)', () => {
  it('localizes enum values and formats the recorded quantity', () => {
    const v = viewActivity(act('irrigation', { method: 'awd', water_volume_m3: 320, note: 'sáng' }))
    expect(v.title).toBe('Tưới nước')
    expect(v.value).toBe('320 m³')
    expect(v.meta).toContain('Tưới ngập–khô xen kẽ (AWD)')
    // A raw enum must never survive into the meta line.
    expect(v.meta.join(' ')).not.toContain('awd')
    expect(v.note).toBe('sáng')
  })

  it('accepts numeric strings from write responses', () => {
    expect(viewActivity(act('harvest', { yield_kg: '5200' })).value).toBe('5.200 kg thóc')
  })

  it('never invents a value that was not recorded', () => {
    const v = viewActivity(act('irrigation', { method: 'continuous_flooding', water_volume_m3: null }))
    expect(v.value).toBeNull()
    expect(v.meta).toEqual(['Ngập liên tục'])
  })

  it('keeps a recorded zero as zero', () => {
    expect(viewActivity(act('irrigation', { water_volume_m3: 0 })).value).toBe('0 m³')
  })
})

describe('journal dates', () => {
  const now = new Date(2026, 8, 12, 9, 0)
  it('labels today, yesterday and older days', () => {
    expect(dayLabel('2026-09-12', now)).toBe('Hôm nay')
    expect(dayLabel('2026-09-11', now)).toBe('Hôm qua')
    expect(dayLabel('2026-09-06', now)).toBe('Chủ nhật, 06/09/2026')
  })
  it('groups by day, newest first', () => {
    const groups = groupByDay([{ id: 'a', occurredAt: '2026-06-10T00:00:00Z' }, { id: 'b', occurredAt: '2026-09-06T00:00:00Z' }, { id: 'c', occurredAt: '2026-09-06T00:00:00Z' }])
    expect(groups.map((g) => g.day)).toEqual(['2026-09-06', '2026-06-10'])
    expect(groups[0].items).toHaveLength(2)
  })
})

describe('buildAttention', () => {
  it('only reports real missing-data signals', () => {
    const items = buildAttention(metrics(), [])
    expect(items.map((i) => i.id)).toEqual(['cost', 'carbon'])
  })

  it('is empty when every signal is present', () => {
    const complete = metrics({ costPerKg: 900, co2ePerKg: 1.2, completeness: { water: true, fertilizer: true, cost: true, carbon: true } })
    expect(buildAttention(complete, [])).toEqual([])
  })

  it('uses a generated data-task recommendation instead of duplicating the same signal', () => {
    const rec = { id: 'r1', type: 'data_task', status: 'generated', ruleCode: 'data.completeness.cost', title: 'Bổ sung chi phí vật tư', reason: 'thiếu chi phí' } as Recommendation
    const items = buildAttention(metrics(), [rec])
    expect(items.map((i) => i.id)).toEqual(['rec-r1', 'carbon'])
  })

  it('ignores recommendations the farmer already handled', () => {
    const rec = { id: 'r1', type: 'data_task', status: 'accepted', ruleCode: 'data.completeness.cost', title: 't', reason: 'r' } as Recommendation
    expect(buildAttention(metrics(), [rec]).map((i) => i.id)).toEqual(['cost', 'carbon'])
  })
})

describe('metricViews', () => {
  it('shows backend ratios as-is and keeps missing ratios null (never 0)', () => {
    const views = metricViews(metrics())
    expect(views.find((v) => v.key === 'water')?.value).toBe('0,062')
    expect(views.find((v) => v.key === 'cost')?.value).toBeNull()
    expect(views.find((v) => v.key === 'carbon')?.value).toBeNull()
  })

  it('points to the harvest form when yield is what is missing', () => {
    const views = metricViews(metrics({ yieldKg: null, waterPerKg: null, fertilizerPerKg: null }))
    expect(views.find((v) => v.key === 'water')?.cta).toBe('harvest')
  })

  it('offers no form shortcut where no dedicated form exists', () => {
    const views = metricViews(metrics())
    expect(views.find((v) => v.key === 'cost')?.cta).toBeUndefined()
    expect(views.find((v) => v.key === 'carbon')?.cta).toBeUndefined()
  })
})

describe('initials', () => {
  it('uses first and last name, else the email initial', () => {
    expect(initials('Nguyễn Văn An', 'x@y.z')).toBe('NA')
    expect(initials(null, 'qa-farmer@x.local')).toBe('Q')
  })
})

describe('demo seed scaffolding', () => {
  it('shows a short badge instead of the seeder English text', () => {
    const v = viewActivity({ type: 'pesticide', detail: JSON.stringify({ product_name: 'Demo pesticide', amount: 2, unit: 'lít' }) })
    expect(v.meta).toContain('Dữ liệu minh họa')
    expect(v.meta.join(' ')).not.toContain('Demo pesticide')
  })

  it('never swallows a real product name or a farmer note', () => {
    const v = viewActivity({ type: 'pesticide', detail: JSON.stringify({ product_name: 'Regent 800WG', amount: 2, unit: 'lít', note: 'Phun lúc chiều mát' }) })
    expect(v.meta).toContain('Regent 800WG')
    expect(v.note).toBe('Phun lúc chiều mát')
  })

  it('only matches the seeder shape, not any word starting with Demo', () => {
    expect(isDemoPlaceholder('Demo pesticide')).toBe(true)
    expect(isDemoPlaceholder('Demo straw_management')).toBe(true)
    expect(isDemoPlaceholder('Demo Farm Co.')).toBe(false)
    expect(isDemoPlaceholder('Thuốc Demo')).toBe(false)
  })
})
