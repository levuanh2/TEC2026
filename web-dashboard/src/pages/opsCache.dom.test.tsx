// @vitest-environment jsdom
import { cleanup, renderHook, waitFor, act } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { CarbonSeasonStatus } from '../api/carbon'
import { queryWrapper, testQueryClient } from '../test/withQuery'

/* P1/P3: the four operations routes share one cache, every source reports on
 * its own, and a number is never shown as final when its source failed. */

const calls = { status: 0, farms: 0, listing: 0, mrv: 0 }
let statusAnswer: () => Promise<{ organization_id: string; items: CarbonSeasonStatus[] }>
let mrvAnswer: () => Promise<unknown[]>
let listingAnswer: () => Promise<Map<string, unknown>>

vi.mock('../api/carbon', () => ({ getOrganizationCarbonStatus: () => { calls.status++; return statusAnswer() } }))
vi.mock('../api/engine', () => ({ getEngineInfo: () => Promise.resolve({ efConfigVersion: 'v1', engineVersion: 'e', carbonProductionReady: false }) }))
vi.mock('../api/mrv', () => ({ getOrganizationMrvBatches: () => { calls.mrv++; return mrvAnswer() } }))
vi.mock('../api/farms', () => ({
  listFarms: () => { calls.farms++; return Promise.resolve([{ id: 'farm-1', code: 'F1', name: 'Nông hộ 1', plotCount: 1 }]) },
  getOrganizationPlotsSeasons: () => { calls.listing++; return listingAnswer() },
}))

const { useOperations } = await import('./ops')
const { summaryTiles } = await import('./operations')
const { makeQueryClient } = await import('../query/client')

const seasonIds = ['s-1', 's-2', 's-3']
const listing = () => Promise.resolve(new Map([['farm-1', {
  plots: [{ id: 'plot-1', farmId: 'farm-1', code: 'P1', name: 'Thửa 1' }],
  seasons: seasonIds.map((id) => ({ id, plotId: 'plot-1', name: id, status: 'active' })),
}]]))
const readiness = { can_calculate: false, blocking_count: 1, input_hash: 'h', ef_config_version: 'v1',
  missing_inputs: [{ code: 'yield', label: 'Sản lượng', detail: '', flow: 'activity' as const, activity_type: 'harvest', blocking: true }] }
const okItem = (id: string): CarbonSeasonStatus => ({ crop_season_id: id, readiness, readiness_error: null, actual: null, actual_error: null })
const status = (items = seasonIds.map(okItem)) => Promise.resolve({ organization_id: 'org-1', items })
const never = <T,>() => new Promise<T>(() => undefined)
const counts = (rows: { missing: unknown[] }[]) => ({ missing: rows.filter((r) => r.missing.length).length, ready: 0, stale: 0, mrv: 0, limited: 0 })

beforeEach(() => {
  Object.assign(calls, { status: 0, farms: 0, listing: 0, mrv: 0 })
  statusAnswer = () => status(); mrvAnswer = () => Promise.resolve([]); listingAnswer = listing
})
afterEach(() => cleanup())

describe('useOperations on the shared cache', () => {
  it('a slow Carbon status never holds the season list', async () => {
    statusAnswer = never
    const { result } = renderHook(() => useOperations('org-1'), { wrapper: queryWrapper() })
    await waitFor(() => expect(result.current.seasons.loading).toBe(false))
    expect(result.current.data?.rows).toHaveLength(3)
    expect(result.current.carbon.loading).toBe(true)
    expect(result.current.data?.pending).toBe(3)
    // The Carbon tiles wait (skeleton); nothing is shown as a final zero.
    const tiles = summaryTiles(counts(result.current.data!.rows), result.current)
    expect(tiles.filter((t) => t.label !== 'Hồ sơ MRV chờ xử lý').every((t) => t.loading)).toBe(true)
  })

  it('a failed Carbon status: rows say so, Carbon tiles have no number (not 0)', async () => {
    statusAnswer = () => Promise.reject(new Error('Máy chủ phản hồi quá lâu.'))
    const { result } = renderHook(() => useOperations('org-1'), { wrapper: queryWrapper() })
    await waitFor(() => expect(result.current.carbon.error).toBe('Máy chủ phản hồi quá lâu.'))
    expect(result.current.error).toBeNull()
    expect(result.current.data!.rows.every((r) => r.error === 'Máy chủ phản hồi quá lâu.')).toBe(true)
    const tiles = summaryTiles(counts(result.current.data!.rows), result.current)
    const carbonTiles = tiles.filter((t) => t.label !== 'Hồ sơ MRV chờ xử lý')
    expect(carbonTiles).toHaveLength(4)
    expect(carbonTiles.every((t) => t.value === null && !t.loading)).toBe(true)
  })

  it('some seasons failing: the count is marked incomplete, never presented as final', async () => {
    statusAnswer = () => status([okItem('s-1'), { ...okItem('s-2'), readiness: null, readiness_error: { code: 'internal_error', message: 'x' } }, okItem('s-3')])
    const { result } = renderHook(() => useOperations('org-1'), { wrapper: queryWrapper() })
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.carbon.failedSeasons).toBe(1)
    const missing = summaryTiles(counts(result.current.data!.rows), result.current).find((t) => t.label === 'Vụ thiếu dữ liệu')!
    expect(missing).toMatchObject({ value: 2, incomplete: 1 })
  })

  it('a failed MRV read is reported, and its tile is not a silent 0', async () => {
    mrvAnswer = () => Promise.reject(new Error('MRV down'))
    const { result } = renderHook(() => useOperations('org-1'), { wrapper: queryWrapper() })
    await waitFor(() => expect(result.current.mrv.error).toBe('MRV down'))
    const tile = summaryTiles(counts(result.current.data!.rows), result.current).find((t) => t.label === 'Hồ sơ MRV chờ xử lý')!
    expect(tile.value).toBeNull()
  })

  it('Dashboard → Vụ mùa → Carbon → Dữ liệu thiếu reuse one read of each source', async () => {
    // The production cache configuration (45 s fresh), not the test default.
    const client = makeQueryClient()
    for (let i = 0; i < 4; i++) {
      const { result, unmount } = renderHook(() => useOperations('org-1'), { wrapper: queryWrapper(client) })
      await waitFor(() => expect(result.current.loading).toBe(false))
      expect(result.current.data!.rows).toHaveLength(3)
      unmount()
    }
    expect(calls).toEqual({ status: 1, farms: 1, listing: 1, mrv: 1 })
  })

  it('a failed refresh keeps the cached rows on screen and says they may be old', async () => {
    const client = testQueryClient()
    const { result } = renderHook(() => useOperations('org-1'), { wrapper: queryWrapper(client) })
    await waitFor(() => expect(result.current.loading).toBe(false))
    statusAnswer = () => Promise.reject(new Error('503'))
    act(() => result.current.reload())
    await waitFor(() => expect(result.current.stale?.error).toBe('503'))
    expect(result.current.carbon.error).toBeNull()
    expect(result.current.data!.rows.every((r) => !r.error)).toBe(true)
    expect(result.current.stale!.updatedAt).toBeGreaterThan(0)
  })

  it('no organisation: nothing is requested', async () => {
    const { result } = renderHook(() => useOperations(null), { wrapper: queryWrapper() })
    await act(async () => { await new Promise((r) => setTimeout(r, 10)) })
    expect(result.current.loading).toBe(false)
    expect(calls).toEqual({ status: 0, farms: 0, listing: 0, mrv: 0 })
  })
})
