import { beforeEach, describe, expect, it } from 'vitest'
import type { FarmerScope } from '../api/farms'
import type { Recommendation } from '../api/recommendations'
import { clearFarmerCache, markSeasonDataChanged } from './data'
import {
  activeSeasonsOf, isActiveStatus, primarySeason, recommendationsOutOfDate, resolveSeason,
  RECS_STALE_AFTER_MS, seasonStatusLabel, seasonsOf, sumArea,
} from './scope'

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

// ---------------------------------------------------------------------------
// Deferred M05 generation. `POST .../recommendations/generate` measured
// 7.3-9.5s / 33 Supabase round trips, so a page never runs it as part of
// loading: this predicate is the only thing that may schedule one, after the
// section has already rendered whatever is stored.
// ---------------------------------------------------------------------------

const rec = (generatedAt: string): Recommendation => ({
  id: 'r1', cropSeasonId: 's1', ruleCode: 'water.awd', ruleVersion: '1', engineVersion: '1',
  type: 'data_task', status: 'generated', title: 't', reason: 'r', comparedTo: null,
  co2eTotalKgBefore: null, co2eTotalKgAfter: null, co2eTotalKgDelta: null, co2ePercentDelta: null,
  impactStatus: 'unavailable', impactUnavailableReason: null,
  generatedAt, acceptedAt: null, dismissedAt: null,
})

describe('deferred recommendation generation', () => {
  beforeEach(() => clearFarmerCache())

  it('does not regenerate a freshly generated set', () => {
    expect(recommendationsOutOfDate('s1', [rec(new Date().toISOString())])).toBe(false)
  })

  it('regenerates when nothing has been stored yet', () => {
    expect(recommendationsOutOfDate('s1', [])).toBe(true)
  })

  it('regenerates once the stored set has aged out', () => {
    const old = new Date(Date.now() - RECS_STALE_AFTER_MS - 60_000).toISOString()
    expect(recommendationsOutOfDate('s1', [rec(old)])).toBe(true)
  })

  it('uses the newest item, not the oldest, to judge age', () => {
    const old = new Date(Date.now() - RECS_STALE_AFTER_MS - 60_000).toISOString()
    expect(recommendationsOutOfDate('s1', [rec(old), rec(new Date().toISOString())])).toBe(false)
  })

  it('regenerates immediately after that season’s records change, however fresh the set is', () => {
    markSeasonDataChanged('s1')
    expect(recommendationsOutOfDate('s1', [rec(new Date().toISOString())])).toBe(true)
    // ...and only for that season.
    expect(recommendationsOutOfDate('s2', [rec(new Date().toISOString())])).toBe(false)
  })

  it('treats an unparseable timestamp as out of date rather than trusting it', () => {
    expect(recommendationsOutOfDate('untouched-season', [rec('not-a-date')])).toBe(true)
  })

  it('sign-out forgets which seasons were touched', () => {
    markSeasonDataChanged('s1')
    clearFarmerCache()
    expect(recommendationsOutOfDate('s1', [rec(new Date().toISOString())])).toBe(false)
  })
})
