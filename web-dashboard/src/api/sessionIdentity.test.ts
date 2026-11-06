import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

/* R3 security review, finding F2: a request is asked on behalf of one person.
 * When the session ends or another person's session takes over the tab while
 * it is queued or in flight, it must never be sent, or retried after a 401,
 * with the next person's token (a refresh would refresh whoever is stored
 * now). A token rotation of the SAME person is still retried once. */

type Client = typeof import('./client')
let c: Client
const sent: (string | null)[] = []
let answer: (auth: string | null) => Promise<Response>

beforeEach(async () => {
  vi.resetModules()
  c = await import('./client')
  sent.length = 0
  answer = async () => new Response('{"ok":true}', { status: 200 })
  vi.stubGlobal('fetch', vi.fn(async (_url: string, init: RequestInit) => {
    const auth = new Headers(init.headers).get('Authorization')
    sent.push(auth)
    return answer(auth)
  }))
})
afterEach(() => { vi.unstubAllGlobals() })

const deferred = () => { let resolve!: (r: Response) => void; const p = new Promise<Response>((r) => { resolve = r }); return { p, resolve } }
const unauthorized = () => new Response('{}', { status: 401 })

describe('a request belongs to the identity it started under', () => {
  it('replaced while in flight: the 401 is not retried with the new person\'s token, and no refresh is tried', async () => {
    const refresh = vi.fn(async () => 'token-B-refreshed')
    c.setUnauthorizedHandler(refresh)
    c.setAccessToken('token-A')
    const first = deferred()
    answer = () => first.p
    const req = c.apiRequest('/v1/farmer/scope')
    await vi.waitFor(() => expect(sent).toEqual(['Bearer token-A']))
    // Another tab signed B in: the auth layer moves the identity, then installs B's token.
    c.beginIdentity()
    c.setAccessToken('token-B')
    first.resolve(unauthorized())
    await expect(req).rejects.toMatchObject({ status: 401, code: 'session_replaced' })
    expect(sent).toEqual(['Bearer token-A'])
    expect(refresh).not.toHaveBeenCalled()
  })

  it('same person, token rotated while in flight: retried once with the rotated token', async () => {
    c.setUnauthorizedHandler(async () => null)
    c.setAccessToken('token-A1')
    let n = 0
    answer = async () => (n++ === 0 ? (c.setAccessToken('token-A2'), unauthorized()) : new Response('{"ok":1}', { status: 200 }))
    await expect(c.apiRequest('/v1/me')).resolves.toEqual({ ok: 1 })
    expect(sent).toEqual(['Bearer token-A1', 'Bearer token-A2'])
  })

  it('a refresh that turns out to be someone else\'s session is not used for the retry', async () => {
    c.setAccessToken('token-A')
    // The auth layer's handler finds the stored session is B's: it replaces (moves the identity) and returns B's token.
    c.setUnauthorizedHandler(async () => { c.beginIdentity(); c.setAccessToken('token-B'); return 'token-B' })
    answer = async () => unauthorized()
    await expect(c.apiRequest('/v1/me')).rejects.toMatchObject({ code: 'session_replaced' })
    expect(sent).toEqual(['Bearer token-A'])
  })

  it('signed out while in flight: no refresh after the sign-out, the request ends as expired', async () => {
    const refresh = vi.fn(async () => 'token-zombie')
    c.setUnauthorizedHandler(refresh)
    c.setAccessToken('token-A')
    const first = deferred()
    answer = () => first.p
    const req = c.apiRequest('/v1/me')
    await vi.waitFor(() => expect(sent.length).toBe(1))
    c.endSession()
    first.resolve(unauthorized())
    await expect(req).rejects.toMatchObject({ code: 'session_expired' })
    expect(refresh).not.toHaveBeenCalled()
  })

  it('a read queued behind the concurrency limit when another person takes over is never sent', async () => {
    c.setAccessToken('token-A')
    const hold = Array.from({ length: c.MAX_CONCURRENT_READS }, deferred)
    let i = 0
    answer = (auth) => (auth === 'Bearer token-A' && i < hold.length ? hold[i++].p : Promise.resolve(new Response('{"ok":true}', { status: 200 })))
    const busy = hold.map((_, k) => c.apiRequest(`/v1/busy/${k}`))
    await vi.waitFor(() => expect(sent.length).toBe(c.MAX_CONCURRENT_READS))
    const queued = c.apiRequest('/v1/organizations/org-A/seasons')
    expect(c.readLimiterState().queued).toBe(1)
    c.beginIdentity()
    c.setAccessToken('token-B')
    hold.forEach((h) => h.resolve(new Response('{}', { status: 200 })))
    await Promise.all(busy)
    await expect(queued).rejects.toMatchObject({ code: 'session_replaced' })
    expect(sent.filter((s) => s === 'Bearer token-B')).toEqual([])
  })

  it('a request started after the takeover uses the new token normally', async () => {
    c.setAccessToken('token-A')
    c.beginIdentity()
    c.setAccessToken('token-B')
    await expect(c.apiRequest('/v1/me')).resolves.toEqual({ ok: true })
    expect(sent).toEqual(['Bearer token-B'])
  })

  it('a read queued behind the concurrency limit when the session ends is never sent and ends as expired', async () => {
    c.setAccessToken('token-A')
    const hold = Array.from({ length: c.MAX_CONCURRENT_READS }, deferred)
    let i = 0
    answer = () => (i < hold.length ? hold[i++].p : Promise.resolve(new Response('{}', { status: 200 })))
    const busy = hold.map((_, k) => c.apiRequest(`/v1/busy/${k}`))
    await vi.waitFor(() => expect(sent.length).toBe(c.MAX_CONCURRENT_READS))
    const queued = c.apiRequest('/v1/organizations/org-A/seasons')
    c.endSession()
    hold.forEach((h) => h.resolve(new Response('{}', { status: 200 })))
    await Promise.all(busy)
    await expect(queued).rejects.toMatchObject({ code: 'session_expired' })
    expect(sent.length).toBe(c.MAX_CONCURRENT_READS)
  })
})
