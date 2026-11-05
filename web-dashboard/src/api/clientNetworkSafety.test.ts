import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  ApiError, apiRequest, isTransientError, MAX_CONCURRENT_READS, READ_TIMEOUT_MS, readLimiterState, setAccessToken,
} from './client'

/* P4 network safety: bounded concurrency for reads, a timeout for reads only,
 * aborts that pass through untouched, and which failures count as transient. */

const ok = () => new Response(JSON.stringify({ ok: true }), { status: 200 })

/** A fetch that answers only when the test says so, honouring the signal. */
function controlledFetch() {
  const pending: { resolve: () => void; url: string; signal?: AbortSignal | null }[] = []
  const fn = vi.fn((url: string, init: RequestInit) => new Promise<Response>((resolve, reject) => {
    init.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
    pending.push({ resolve: () => resolve(ok()), url, signal: init.signal })
  }))
  return { fn, pending }
}

const flush = () => new Promise((r) => setTimeout(r, 0))

describe('read limiter', () => {
  afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); setAccessToken(null) })

  it(`never has more than ${MAX_CONCURRENT_READS} reads on the wire; the rest wait their turn`, async () => {
    const f = controlledFetch(); vi.stubGlobal('fetch', f.fn)
    const all = Array.from({ length: 7 }, (_, i) => apiRequest(`/v1/r/${i}`))
    await flush()
    expect(f.fn).toHaveBeenCalledTimes(MAX_CONCURRENT_READS)
    expect(readLimiterState()).toEqual({ inFlight: MAX_CONCURRENT_READS, queued: 3 })
    f.pending[0].resolve(); await flush(); await flush()
    expect(f.fn).toHaveBeenCalledTimes(MAX_CONCURRENT_READS + 1)
    for (let i = 0; i < 7; i++) { f.pending[i]?.resolve(); await flush(); await flush() }
    await Promise.all(all)
    expect(readLimiterState()).toEqual({ inFlight: 0, queued: 0 })
  })

  it('never queues a write behind reads', async () => {
    const f = controlledFetch(); vi.stubGlobal('fetch', f.fn)
    const reads = Array.from({ length: MAX_CONCURRENT_READS }, (_, i) => apiRequest(`/v1/r/${i}`))
    const write = apiRequest('/v1/w', { method: 'POST', body: '{}' })
    await flush()
    const sentWrite = f.fn.mock.calls.some((c) => String(c[0]).endsWith('/v1/w'))
    f.pending.forEach((p) => p.resolve())
    await Promise.all([...reads, write])
    expect(sentWrite).toBe(true)
  })

  it('a queued read the page abandons leaves the queue and never reaches the network', async () => {
    const f = controlledFetch(); vi.stubGlobal('fetch', f.fn)
    const busy = Array.from({ length: MAX_CONCURRENT_READS }, (_, i) => apiRequest(`/v1/r/${i}`))
    const ctl = new AbortController()
    const queued = apiRequest('/v1/late', { signal: ctl.signal })
    await flush()
    expect(readLimiterState().queued).toBe(1)
    ctl.abort()
    await expect(queued).rejects.toMatchObject({ name: 'AbortError' })
    expect(readLimiterState().queued).toBe(0)
    f.pending.forEach((p) => p.resolve())
    await Promise.all(busy)
    expect(f.fn.mock.calls.some((c) => String(c[0]).includes('/v1/late'))).toBe(false)
  })

  it('an in-flight read aborted by the page rejects as an abort, not as "offline"', async () => {
    const f = controlledFetch(); vi.stubGlobal('fetch', f.fn)
    const ctl = new AbortController()
    const p = apiRequest('/v1/x', { signal: ctl.signal })
    await flush()
    ctl.abort()
    await expect(p).rejects.toMatchObject({ name: 'AbortError' })
    expect(readLimiterState().inFlight).toBe(0)
  })
})

describe('read timeout', () => {
  afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers() })

  it(`a read with no answer after ${READ_TIMEOUT_MS / 1000} s fails with a clear timeout error`, async () => {
    vi.useFakeTimers()
    const f = controlledFetch(); vi.stubGlobal('fetch', f.fn)
    const p = apiRequest('/v1/slow')
    const assertion = expect(p).rejects.toMatchObject({ status: 0, code: 'timeout' })
    await vi.advanceTimersByTimeAsync(READ_TIMEOUT_MS + 1)
    await assertion
    expect(readLimiterState().inFlight).toBe(0)
  })

  it('a write is never timed out by the client', async () => {
    vi.useFakeTimers()
    const f = controlledFetch(); vi.stubGlobal('fetch', f.fn)
    let settled = false
    const p = apiRequest('/v1/w', { method: 'POST', body: '{}' }).finally(() => { settled = true })
    await vi.advanceTimersByTimeAsync(READ_TIMEOUT_MS * 3)
    expect(settled).toBe(false)
    f.pending[0].resolve()
    await p
  })

  it('a network failure stays "offline", distinct from a timeout', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    await expect(apiRequest('/v1/x')).rejects.toMatchObject({ status: 0, code: 'offline' })
  })
})

describe('isTransientError', () => {
  it.each([
    [new ApiError(0, 'offline', ''), true],
    [new ApiError(502, 'x', ''), true],
    [new ApiError(503, 'database_unavailable', ''), true],
    [new ApiError(504, 'x', ''), true],
    [new ApiError(0, 'timeout', ''), false],
    [new ApiError(500, 'internal_error', ''), false],
    [new ApiError(401, 'session_expired', ''), false],
    [new ApiError(403, 'forbidden', ''), false],
    [new ApiError(404, 'not_found', ''), false],
    [new ApiError(422, 'validation_error', ''), false],
    [new Error('plain'), false],
  ])('%o → %s', (error, expected) => {
    expect(isTransientError(error)).toBe(expected)
  })
})
