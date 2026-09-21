import { describe, expect, it } from 'vitest'
import type { SeasonMetrics } from '../api/metrics'
import { metricGroups, metricViews } from './metricsView'

const metrics = (over: Partial<SeasonMetrics> = {}): SeasonMetrics => ({
  yieldKg: 5200, waterM3: 320, fertilizerKg: 150, totalCo2eKg: null,
  waterPerKg: 0.062, fertilizerPerKg: 0.029, co2ePerKg: null, costPerKg: null,
  completeness: { water: true, fertilizer: true, cost: false, carbon: false },
  ...over,
})

describe('metric grouping', () => {
  it('keeps cost in its own group, never beside Carbon', () => {
    const groups = metricGroups(metrics())
    expect(groups.map((g) => g.key)).toEqual(['resource', 'cost', 'carbon'])
    expect(groups[0].items.map((i) => i.key)).toEqual(['water', 'fertilizer'])
    expect(groups[1].items.map((i) => i.key)).toEqual(['cost'])
    expect(groups[2].items.map((i) => i.key)).toEqual(['carbon'])
  })

  it('says in words that cost is not a CO₂e input', () => {
    const cost = metricGroups(metrics()).find((g) => g.key === 'cost')!
    expect(cost.description).toContain('Không dùng để tính CO₂e')
  })

  it('every metric declares the group it belongs to', () => {
    for (const v of metricViews(metrics())) {
      expect(['resource', 'cost', 'carbon']).toContain(v.group)
    }
  })

  it('groups hold the same four metrics the flat list does', () => {
    const flat = metricViews(metrics()).map((v) => v.key).sort()
    const grouped = metricGroups(metrics()).flatMap((g) => g.items.map((i) => i.key)).sort()
    expect(grouped).toEqual(flat)
  })
})
