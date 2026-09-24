import { describe, expect, it } from 'vitest'
import type { SeasonMetrics } from '../api/metrics'
import { coverageLine, coverageOf, missingReason, type SeasonMetricRow } from './coverage'

const m = (over: Partial<SeasonMetrics> = {}): SeasonMetrics => ({
  yieldKg: 5000, waterM3: 300, fertilizerKg: 150, totalCo2eKg: null,
  waterPerKg: 0.06, fertilizerPerKg: 0.03, co2ePerKg: null, costPerKg: null,
  completeness: { water: true, fertilizer: true, cost: false, carbon: false }, ...over,
})
const row = (id: string, metrics: SeasonMetrics | null, error?: string): SeasonMetricRow =>
  ({ seasonId: id, seasonName: `Vụ ${id}`, farmName: 'Hộ', plotName: 'Thửa', metrics, error })

describe('aggregate coverage', () => {
  const rows = [
    row('a', m()),
    row('b', m({ yieldKg: null, waterPerKg: null, fertilizerPerKg: null })),
    row('c', m({ waterM3: null, waterPerKg: null })),
    row('d', null, 'HTTP 500'),
  ]

  it('counts the seasons that carry the server figure, never a recomputed one', () => {
    const c = coverageOf(rows, 'water')
    expect(c.total).toBe(4)
    expect(c.valid).toBe(1)
    expect(coverageLine(c)).toBe('Dựa trên 1/4 vụ đủ dữ liệu')
  })

  it('lists exactly the missing seasons, each with its own reason', () => {
    const c = coverageOf(rows, 'water')
    expect(c.missing.map((x) => [x.row.seasonId, x.reason])).toEqual([
      ['b', 'Thiếu sản lượng thu hoạch'],
      ['c', 'Thiếu lượng nước tưới'],
      ['d', 'Không đọc được dữ liệu vụ (HTTP 500)'],
    ])
  })

  it('Carbon without a stored result says so before blaming yield', () => {
    expect(missingReason(m({ yieldKg: null }), 'carbon')).toBe('Chưa có kết quả Carbon')
    expect(missingReason(m({ totalCo2eKg: 900, yieldKg: null }), 'carbon')).toBe('Thiếu sản lượng thu hoạch')
    expect(coverageOf([row('x', m({ totalCo2eKg: 900, co2ePerKg: 0.18 }))], 'carbon').valid).toBe(1)
  })

  it('an empty scope is 0/0, not a silent full coverage', () => {
    expect(coverageLine(coverageOf([], 'cost'))).toBe('Dựa trên 0/0 vụ đủ dữ liệu')
  })
})
