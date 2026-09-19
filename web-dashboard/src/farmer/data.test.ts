import { beforeEach, describe, expect, it, vi } from 'vitest'
import { clearFarmerCache, fetchQuery, invalidateQueries, keys, markSeasonDataChanged, peekQuery, querySeq, setQueryData, subscribeQuery } from './data'

describe('Farmer read cache (stale-while-revalidate)', () => {
  beforeEach(() => clearFarmerCache())

  it('shares one request between concurrent readers of the same key', async () => {
    const fetcher = vi.fn().mockResolvedValue(['a'])
    const [x, y] = await Promise.all([fetchQuery('k', fetcher), fetchQuery('k', fetcher)])
    expect(fetcher).toHaveBeenCalledTimes(1)
    expect(x).toEqual(['a'])
    expect(y).toEqual(['a'])
  })

  it('serves fresh cached data without a new request, and refetches once stale', async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(1).mockResolvedValueOnce(2)
    await fetchQuery('k', fetcher, { staleMs: 60_000 })
    expect(await fetchQuery('k', fetcher, { staleMs: 60_000 })).toBe(1)
    expect(fetcher).toHaveBeenCalledTimes(1)
    expect(await fetchQuery('k', fetcher, { staleMs: 0 })).toBe(2)
    expect(fetcher).toHaveBeenCalledTimes(2)
  })

  it('refetches after invalidation, and a request started before it cannot overwrite newer data', async () => {
    let resolveOld!: (v: string) => void
    const old = fetchQuery('k', () => new Promise<string>((r) => { resolveOld = r }))
    invalidateQueries('k')
    await fetchQuery('k', () => Promise.resolve('new'))
    resolveOld('old')
    await old
    expect(peekQuery('k')).toBe('new')
  })

  it('setQueryData wins over an in-flight read of the same key', async () => {
    let resolveRead!: (v: string[]) => void
    const read = fetchQuery('recs', () => new Promise<string[]>((r) => { resolveRead = r }))
    setQueryData('recs', ['generated'])
    resolveRead(['stale list'])
    await read
    expect(peekQuery('recs')).toEqual(['generated'])
  })

  /* Every Farmer write — seeding, fertilizer, irrigation, pesticide, straw
   * management, harvest, and the edit/delete of any of them — goes through one
   * `done()` in ActivityForms and therefore through `markSeasonDataChanged`.
   * This pins exactly which reads that is allowed to touch: the ones an
   * activity write can actually change, and nothing else. Over-invalidating
   * here is what turns one save into a refetch storm. */
  it('a season write refetches only that season’s derived reads', async () => {
    const fetchers = {
      scope: vi.fn().mockResolvedValue('scope'),
      activities: vi.fn().mockResolvedValue('a'),
      metrics: vi.fn().mockResolvedValue('m'),
      recs: vi.fn().mockResolvedValue('r'),
      recsGen: vi.fn().mockResolvedValue(1),
      cv: vi.fn().mockResolvedValue('cv'),
      carbon: vi.fn().mockResolvedValue('c'),
      carbonReadiness: vi.fn().mockResolvedValue('cr'),
      org: vi.fn().mockResolvedValue('o'),
      otherSeasonMetrics: vi.fn().mockResolvedValue('m2'),
    }
    const read = async () => {
      await fetchQuery(keys.scope, fetchers.scope, { staleMs: 60_000 })
      await fetchQuery(keys.activities('s1'), fetchers.activities, { staleMs: 60_000 })
      await fetchQuery(keys.metrics('s1'), fetchers.metrics, { staleMs: 60_000 })
      await fetchQuery(keys.recs('s1'), fetchers.recs, { staleMs: 60_000 })
      await fetchQuery(keys.recsGen('s1'), fetchers.recsGen, { staleMs: 60_000 })
      await fetchQuery(keys.cv('s1'), fetchers.cv, { staleMs: 60_000 })
      await fetchQuery(keys.carbon('s1'), fetchers.carbon, { staleMs: 60_000 })
      await fetchQuery(keys.carbonReadiness('s1'), fetchers.carbonReadiness, { staleMs: 60_000 })
      await fetchQuery(keys.org('org-1'), fetchers.org, { staleMs: 60_000 })
      await fetchQuery(keys.metrics('s2'), fetchers.otherSeasonMetrics, { staleMs: 60_000 })
    }

    await read()
    markSeasonDataChanged('s1')
    await read()

    // Refetched: everything an activity write can change.
    expect(fetchers.activities).toHaveBeenCalledTimes(2)
    expect(fetchers.metrics).toHaveBeenCalledTimes(2)
    expect(fetchers.recs).toHaveBeenCalledTimes(2)
    expect(fetchers.recsGen).toHaveBeenCalledTimes(2)
    // Which Carbon inputs are missing can change with a record edit (Nitơ, rơm).
    expect(fetchers.carbonReadiness).toHaveBeenCalledTimes(2)
    // Untouched: writing an activity changes none of these, and re-reading the
    // viewer's hierarchy or organization identity on every save is pure waste.
    expect(fetchers.scope).toHaveBeenCalledTimes(1)
    expect(fetchers.org).toHaveBeenCalledTimes(1)
    // A Carbon calculation is never triggered by an activity write (the harvest
    // confirmation says so explicitly), and a leaf photo is unrelated.
    expect(fetchers.carbon).toHaveBeenCalledTimes(1)
    expect(fetchers.cv).toHaveBeenCalledTimes(1)
    // And another season's reads are not collateral damage.
    expect(fetchers.otherSeasonMetrics).toHaveBeenCalledTimes(1)
  })

  it('sign-out clears everything', async () => {
    await fetchQuery(keys.scope, () => Promise.resolve('scope'))
    clearFarmerCache()
    expect(peekQuery(keys.scope)).toBeUndefined()
  })

  /* A read can start before the component that displays it mounts (a prefetch,
   * or another page reading the same key) and resolve in the gap between that
   * component's render and its subscription. `useQuery` subscribes through
   * `useSyncExternalStore`, which re-reads this sequence right after
   * subscribing — so the change must still be visible then, not only through
   * the notification that was already missed. */
  it('a change that lands before a subscriber attaches is still visible to it', async () => {
    const seen = querySeq('k')
    await fetchQuery('k', () => Promise.resolve('value'))
    let notified = false
    subscribeQuery('k', () => { notified = true })
    expect(notified).toBe(false)
    expect(querySeq('k')).not.toBe(seen)
    expect(peekQuery('k')).toBe('value')
  })

  it('counts every change to a key, including one back to the same value', async () => {
    const start = querySeq('k')
    setQueryData('k', 'x')
    setQueryData('k', 'x')
    expect(querySeq('k')).toBe(start + 2)
  })

  it('keeps no data for a failed first load', async () => {
    await expect(fetchQuery('k', () => Promise.reject(new Error('boom')))).rejects.toThrow('boom')
    expect(peekQuery('k')).toBeUndefined()
  })
})
