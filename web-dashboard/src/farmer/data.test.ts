import { beforeEach, describe, expect, it, vi } from 'vitest'
import { clearFarmerCache, fetchQuery, invalidateQueries, keys, markSeasonDataChanged, peekQuery, setQueryData } from './data'

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

  it('a season write invalidates only that season’s derived reads, never the stable scope', async () => {
    const scope = vi.fn().mockResolvedValue('scope')
    const metrics = vi.fn().mockResolvedValue('m')
    const other = vi.fn().mockResolvedValue('other')
    await fetchQuery(keys.scope, scope, { staleMs: 60_000 })
    await fetchQuery(keys.metrics('s1'), metrics, { staleMs: 60_000 })
    await fetchQuery(keys.metrics('s2'), other, { staleMs: 60_000 })
    markSeasonDataChanged('s1')
    await fetchQuery(keys.scope, scope, { staleMs: 60_000 })
    await fetchQuery(keys.metrics('s1'), metrics, { staleMs: 60_000 })
    await fetchQuery(keys.metrics('s2'), other, { staleMs: 60_000 })
    expect(scope).toHaveBeenCalledTimes(1)
    expect(metrics).toHaveBeenCalledTimes(2)
    expect(other).toHaveBeenCalledTimes(1)
  })

  it('sign-out clears everything', async () => {
    await fetchQuery(keys.scope, () => Promise.resolve('scope'))
    clearFarmerCache()
    expect(peekQuery(keys.scope)).toBeUndefined()
  })

  it('keeps no data for a failed first load', async () => {
    await expect(fetchQuery('k', () => Promise.reject(new Error('boom')))).rejects.toThrow('boom')
    expect(peekQuery('k')).toBeUndefined()
  })
})
