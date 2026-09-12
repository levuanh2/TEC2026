import { describe, expect, it } from 'vitest'
import type { FarmerScope } from '../api/farms'
import { activeSeasonsOf, isActiveStatus, primarySeason, resolveSeason, seasonStatusLabel, seasonsOf, sumArea } from './scope'

const scope: FarmerScope = {
  farms: [{ id: 'f1', code: 'F-01', name: 'Hộ 1', plotCount: 2 }],
  plots: [
    { id: 'p1', farmId: 'f1', code: 'P-01', name: 'Thửa 1', areaHa: 1.3 },
    { id: 'p2', farmId: 'f1', code: 'P-02', name: 'Thửa 2', areaHa: 1.6 },
  ],
  seasons: [
    { id: 'old', plotId: 'p1', name: 'ĐX-2025', plantingDate: '2025-12-01', status: 'completed' },
    { id: 's1', plotId: 'p1', name: 'HT-2026 A', plantingDate: '2026-05-18', status: 'active' },
    { id: 's2', plotId: 'p2', name: 'HT-2026 B', plantingDate: '2026-05-20', status: 'active' },
  ],
}

describe('farmer scope helpers', () => {
  it('orders active seasons first, most recently planted first', () => {
    expect(seasonsOf(scope).map((c) => c.season.id)).toEqual(['s2', 's1', 'old'])
    expect(activeSeasonsOf(scope).map((c) => c.season.id)).toEqual(['s2', 's1'])
    expect(primarySeason(scope)?.season.id).toBe('s2')
  })

  it('resolves a season with its plot and farm, and nothing for an id outside the scope', () => {
    const ctx = resolveSeason(scope, 's1')
    expect(ctx?.plot?.id).toBe('p1')
    expect(ctx?.farm?.id).toBe('f1')
    expect(resolveSeason(scope, 'someone-elses-season')).toBeNull()
  })

  it('never returns a partial area total', () => {
    expect(sumArea(scope.plots)).toBeCloseTo(2.9)
    expect(sumArea([...scope.plots, { id: 'p3', farmId: 'f1', code: 'P-03', name: 'Thửa 3' }])).toBeNull()
    expect(sumArea([])).toBeNull()
  })

  it('labels statuses without inventing states', () => {
    expect(isActiveStatus('active')).toBe(true)
    expect(seasonStatusLabel('active')).toBe('Đang canh tác')
    expect(seasonStatusLabel('completed')).toBe('Đã kết thúc')
    expect(seasonStatusLabel(undefined)).toBe('Chưa rõ trạng thái')
  })

  it('has no primary season when nothing is active', () => {
    expect(primarySeason({ ...scope, seasons: [scope.seasons[0]] })).toBeNull()
  })
})
