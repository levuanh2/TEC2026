import { afterEach, describe, expect, it } from 'vitest'
import { ApiError } from '../api/client'
import { clearQueryCache, keys, MAX_RETRIES, queryClient, retryDelay, scope, setQueryUser, shouldRetry } from './client'

describe('retry policy', () => {
  it('retries a transient read failure at most twice', () => {
    const e = new ApiError(503, 'database_unavailable', '')
    expect([0, 1, 2].map((n) => shouldRetry(n, e))).toEqual([true, true, false])
    expect(MAX_RETRIES).toBe(2)
  })
  it.each([401, 403, 404, 422, 500])('never retries a %i', (status) => {
    expect(shouldRetry(0, new ApiError(status, 'x', ''))).toBe(false)
  })
  it('never retries a timeout', () => {
    expect(shouldRetry(0, new ApiError(0, 'timeout', ''))).toBe(false)
  })
  it('backs off 1 s then 3 s, with bounded jitter', () => {
    for (let i = 0; i < 20; i++) {
      expect(retryDelay(0)).toBeGreaterThanOrEqual(1000); expect(retryDelay(0)).toBeLessThan(1400)
      expect(retryDelay(1)).toBeGreaterThanOrEqual(3000); expect(retryDelay(1)).toBeLessThan(3400)
    }
  })
})

describe('cache scope', () => {
  afterEach(() => clearQueryCache())

  it('every key carries the signed-in user and organisation', () => {
    setQueryUser('user-a')
    expect(keys.org('org-1', 'carbon-status')).toEqual(['u', 'user-a', 'org', 'org-1', 'carbon-status'])
    expect(keys.farms()).toEqual(['u', 'user-a', 'farms'])
  })

  it('a different user signing in drops everything the previous one loaded', () => {
    setQueryUser('manager')
    queryClient.setQueryData(keys.org('org-1', 'carbon-status'), { items: ['secret'] })
    setQueryUser('farmer')
    expect(queryClient.getQueryCache().getAll()).toHaveLength(0)
    expect(scope()).toEqual(['u', 'farmer'])
  })

  it('the same user again (token refresh, re-sign-in) keeps the cache', () => {
    setQueryUser('manager')
    queryClient.setQueryData(keys.farms(), [1])
    setQueryUser('manager')
    expect(queryClient.getQueryData(keys.farms())).toEqual([1])
  })

  it('session end forgets every entry', () => {
    setQueryUser('manager')
    queryClient.setQueryData(keys.farms(), [1])
    clearQueryCache()
    expect(queryClient.getQueryCache().getAll()).toHaveLength(0)
    expect(scope()).toEqual(['u', 'anonymous'])
  })
})
