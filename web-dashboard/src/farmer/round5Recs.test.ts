import { describe, expect, it } from 'vitest'
import type { Recommendation } from '../api/recommendations'
import type { SeasonMetrics } from '../api/metrics'
import { dataTaskKey, dataTaskResolved, recommendationsOutOfDate } from './scope'

const rec = (ruleCode: string, type: Recommendation['type'] = 'data_task'): Recommendation => ({
  id: ruleCode, cropSeasonId: 's-r5', ruleCode, ruleVersion: '1', engineVersion: null, type, status: 'generated',
  title: '', reason: '', comparedTo: null, co2eTotalKgBefore: null, co2eTotalKgAfter: null, co2eTotalKgDelta: null,
  co2ePercentDelta: null, impactStatus: 'unavailable', impactUnavailableReason: null,
  generatedAt: new Date().toISOString(), acceptedAt: null, dismissedAt: null,
})
const metrics = (over: Partial<SeasonMetrics['completeness']> = {}, yieldKg: number | null = 6000): SeasonMetrics => ({
  yieldKg, waterM3: null, fertilizerKg: null, totalCo2eKg: null, waterPerKg: null, fertilizerPerKg: null, co2ePerKg: null, costPerKg: null,
  completeness: { water: true, fertilizer: true, cost: false, carbon: false, ...over },
})

describe('a data task for data that has since been supplied is out of date', () => {
  it('reads the metric key from the rule code only for data tasks', () => {
    expect(dataTaskKey(rec('data.completeness.cost'))).toBe('cost')
    expect(dataTaskKey(rec('awd.optimization', 'optimization'))).toBeNull()
  })
  it('cost supplied → the "Bổ sung chi phí" task is resolved and triggers a refresh', () => {
    const items = [rec('data.completeness.cost')]
    expect(dataTaskResolved(items[0], metrics({ cost: true }))).toBe(true)
    expect(recommendationsOutOfDate('s-r5', items, metrics({ cost: true }))).toBe(true)
  })
  it('still missing → not resolved, and a fresh list stays as it is', () => {
    const items = [rec('data.completeness.cost')]
    expect(dataTaskResolved(items[0], metrics({ cost: false }))).toBe(false)
    expect(recommendationsOutOfDate('s-r5', items, metrics({ cost: false }))).toBe(false)
  })
  it('yield is resolved by a recorded yield', () => {
    expect(dataTaskResolved(rec('data.completeness.yield'), metrics({}, null))).toBe(false)
    expect(dataTaskResolved(rec('data.completeness.yield'), metrics({}, 5000))).toBe(true)
  })
})
