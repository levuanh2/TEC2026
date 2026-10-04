import { beforeEach, describe, expect, it, vi } from 'vitest'

/* Round 5.1 Home: it reads only the newest HOME_RECENT records and the
 * server's whole-season summary. Hovering the Home link warms exactly those
 * (plus metrics), and a write that invalidates the season's activities also
 * invalidates both -- their keys live under the `activities:<season>` prefix. */
const getRecentActivities = vi.fn(async () => [])
const getActivitySummary = vi.fn(async () => ({ total: 0 }))
const getActivities = vi.fn(async () => [])
const getResourceMetrics = vi.fn(async () => null)
vi.mock('../api/crops', () => ({
  getRecentActivities: (...a: unknown[]) => getRecentActivities(...(a as [])),
  getActivitySummary: (...a: unknown[]) => getActivitySummary(...(a as [])),
  getActivities: (...a: unknown[]) => getActivities(...(a as [])),
}))
vi.mock('../api/metrics', () => ({ getResourceMetrics: (...a: unknown[]) => getResourceMetrics(...(a as [])) }))
vi.mock('../api/farms', () => ({ usingMockData: false, getFarmerScope: vi.fn(async () => SCOPE) }))

const SCOPE = {
  farms: [{ id: 'f-1', code: 'F1', name: 'Hộ 1' }],
  plots: [{ id: 'p-1', farmId: 'f-1', code: 'P1', name: 'Ruộng 1', areaHa: 1 }],
  seasons: [{ id: 's-1', plotId: 'p-1', name: 'HT-2026', status: 'active', plantingDate: '2026-06-01' }],
}

const { HOME_RECENT, dataTaskResolved, prefetchNav } = await import('./scope')
const { invalidateQueries, keys, peekQuery, setQueryData } = await import('./data')

const flush = () => new Promise((r) => setTimeout(r, 0))

beforeEach(() => {
  for (const m of [getRecentActivities, getActivitySummary, getActivities, getResourceMetrics]) m.mockClear()
  setQueryData(keys.scope, SCOPE)
})

describe('Home prefetch', () => {
  it('hovering Home warms the recent records, the season summary and the metrics -- not the full journal', async () => {
    prefetchNav('/farmer')
    await flush()
    expect(getRecentActivities).toHaveBeenCalledWith('s-1', HOME_RECENT)
    expect(getActivitySummary).toHaveBeenCalledWith('s-1')
    expect(getResourceMetrics).toHaveBeenCalledWith('s-1')
    expect(getActivities).not.toHaveBeenCalled()
  })

  it('the journal link warms the full list instead', async () => {
    prefetchNav('/farmer/journal')
    await flush()
    expect(getActivities).toHaveBeenCalledWith('s-1')
    expect(getRecentActivities).not.toHaveBeenCalled()
  })

  it('a season activity write invalidates the recent list and the summary too', async () => {
    prefetchNav('/farmer')
    await flush()
    expect(keys.recentActivities('s-1', HOME_RECENT).startsWith(keys.activities('s-1'))).toBe(true)
    expect(keys.activitySummary('s-1').startsWith(keys.activities('s-1'))).toBe(true)
    // Fresh: hovering again fetches nothing.
    const [recent, summary] = [getRecentActivities.mock.calls.length, getActivitySummary.mock.calls.length]
    prefetchNav('/farmer')
    await flush()
    expect(getRecentActivities.mock.calls.length).toBe(recent)
    invalidateQueries(keys.activities('s-1'))
    // Stale now: the next read refetches both.
    prefetchNav('/farmer')
    await flush()
    expect(getRecentActivities.mock.calls.length).toBe(recent + 1)
    expect(getActivitySummary.mock.calls.length).toBe(summary + 1)
    expect(peekQuery(keys.activitySummary('s-1'))).toEqual({ total: 0 })
  })

  it('without a season in scope nothing is fetched', async () => {
    setQueryData(keys.scope, { farms: [], plots: [], seasons: [] })
    prefetchNav('/farmer')
    await flush()
    expect(getRecentActivities).not.toHaveBeenCalled()
  })
})

describe('dataTaskResolved', () => {
  it('a task for an unknown metric, or a non-task, is never resolved', () => {
    const m = { yieldKg: 1, completeness: { water: true, fertilizer: true, cost: true, carbon: true } } as never
    expect(dataTaskResolved({ ruleCode: 'data.completeness.carbon_custom', type: 'data_task' } as never, m)).toBe(false)
    expect(dataTaskResolved({ ruleCode: 'awd.optimization', type: 'optimization' } as never, m)).toBe(false)
    expect(dataTaskResolved({ ruleCode: 'data.completeness.water', type: 'data_task' } as never, m)).toBe(true)
  })
})
