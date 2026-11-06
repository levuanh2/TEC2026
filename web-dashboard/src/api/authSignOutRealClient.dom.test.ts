// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

/* R3 security review, findings F4/F5, against the REAL auth-js client (only
 * the network is fake; the session lives in jsdom's localStorage exactly as in
 * a browser). Pins the library behaviour the fix relies on, so an auth-js
 * upgrade that changes it fails here.
 *
 * F4: the shell leaves after SIGN_OUT_WAIT_MS while /logout may still be
 *     running; auth-js removes the stored session only when that call
 *     returns, so a reload in between restored the session the person had
 *     just been told was ended (shared computer).
 * F5: when that late /logout returned after the next person had signed in,
 *     auth-js removed THEIR stored session (and its SIGNED_OUT was ignored
 *     while the sign-out flag was still set). */

const PROJECT = 'https://r3probe.supabase.co'
const STORAGE_KEY = 'sb-r3probe-auth-token'
let logout: () => Promise<Response>
let nextUser = 'user-A'
const calls: string[] = []

const b64 = (o: object) => btoa(JSON.stringify(o)).replace(/=+$/, '').replace(/\+/g, '-').replace(/\//g, '_')
const jwt = (sub: string) => `${b64({ alg: 'HS256', typ: 'JWT' })}.${b64({ sub, exp: Math.floor(Date.now() / 1000) + 3600, role: 'authenticated' })}.c2ln`
function sessionFor(sub: string) {
  return { access_token: jwt(sub), refresh_token: `r-${sub}`, token_type: 'bearer', expires_in: 3600, expires_at: Math.floor(Date.now() / 1000) + 3600, user: { id: sub, aud: 'authenticated', email: `${sub}@example.test`, app_metadata: {}, user_metadata: {} } }
}
async function network(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
  calls.push(url.replace(PROJECT, ''))
  if (url.includes('/token?grant_type=password')) return new Response(JSON.stringify(sessionFor(nextUser)), { status: 200, headers: { 'content-type': 'application/json' } })
  if (url.includes('/logout')) {
    return new Promise<Response>((resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(init.signal!.reason ?? new DOMException('aborted', 'AbortError')), { once: true })
      logout().then(resolve, reject)
    })
  }
  return new Response('{}', { status: 404 })
}

vi.mock('../utils/supabase', async (orig) => {
  const real = await orig<typeof import('../utils/supabase')>()
  const { createClient } = await import('@supabase/supabase-js')
  return { ...real, supabase: createClient(PROJECT, 'publishable-test-key', { auth: { autoRefreshToken: false, detectSessionInUrl: false }, global: { fetch: real.boundedAuthFetch(network) } }) }
})
vi.mock('../farmer/data', () => ({ clearFarmerCache: () => {} }))

const auth = await import('./auth')
const { supabase } = await import('../utils/supabase')
const stored = () => { const raw = localStorage.getItem(STORAGE_KEY); return raw ? (JSON.parse(raw).user?.id ?? null) : null }

beforeEach(() => { calls.length = 0; nextUser = 'user-A'; logout = async () => new Response(null, { status: 204 }) })
afterEach(async () => { logout = async () => new Response(null, { status: 204 }); localStorage.clear() })

describe('sign-out with the real auth-js client', () => {
  it('the storage key the fix removes is the one auth-js uses', async () => {
    expect((supabase!.auth as unknown as { storageKey: string }).storageKey).toBe(STORAGE_KEY)
    await auth.signIn('a@example.test', 'pw')
    expect(stored()).toBe('user-A')
    await auth.signOut()
    expect(stored()).toBeNull()
  })

  it('F4: /logout hangs — once the shell has left, a reload restores nothing', async () => {
    await auth.signIn('a@example.test', 'pw')
    expect(stored()).toBe('user-A')
    logout = () => new Promise<Response>(() => {})
    const ended = vi.fn()
    const off = auth.onAuthEnded(ended)
    await auth.signOut()
    expect(ended).toHaveBeenCalledWith('signed_out_unconfirmed')
    // What a reload reads: the stored session.
    expect(stored()).toBeNull()
    expect(await auth.restoreSession()).toBeNull()
    off()
  }, 10_000)

  it('F5: /logout is slow and the next person signs in meanwhile — their session survives the late sign-out', async () => {
    await auth.signIn('a@example.test', 'pw')
    let release!: () => void
    logout = () => new Promise<Response>((r) => { release = () => r(new Response(null, { status: 204 })) })
    const ended = vi.fn()
    const off = auth.onAuthEnded(ended)
    await auth.signOut()                         // left after SIGN_OUT_WAIT_MS, /logout still pending
    expect(ended).toHaveBeenCalledTimes(1)
    nextUser = 'user-B'
    const signingIn = auth.signIn('b@example.test', 'pw')
    await new Promise((r) => setTimeout(r, 50))
    release()                                    // A's sign-out finally returns
    const b = await signingIn
    expect(b?.user.id).toBe('user-B')
    await new Promise((r) => setTimeout(r, 50))
    expect(stored()).toBe('user-B')
    expect((await supabase!.auth.getSession()).data.session?.user.id).toBe('user-B')
    expect(ended).toHaveBeenCalledTimes(1)
    // B's password grant went out only after A's /logout had returned.
    expect(calls.filter((u) => /logout|grant_type=password/.test(u)).map((u) => (u.includes('logout') ? 'logout' : 'token'))).toEqual(['token', 'logout', 'token'])
    off()
  }, 10_000)
})

describe('boundedAuthFetch', () => {
  it('aborts a /logout that does not answer within LOGOUT_TIMEOUT_MS and leaves other requests alone', async () => {
    const { boundedAuthFetch, LOGOUT_TIMEOUT_MS } = await import('../utils/supabase')
    vi.useFakeTimers()
    try {
      const seen: (AbortSignal | undefined | null)[] = []
      const base = vi.fn((_i: RequestInfo | URL, init?: RequestInit) => {
        seen.push(init?.signal)
        return new Promise<Response>((_r, reject) => init?.signal?.addEventListener('abort', () => reject(init.signal!.reason), { once: true }))
      }) as unknown as typeof fetch
      const f = boundedAuthFetch(base)
      const hung = f(`${PROJECT}/auth/v1/logout?scope=global`, { method: 'POST' })
      const outcome = hung.then(() => 'resolved', (e: unknown) => (e instanceof DOMException ? e.name : String(e)))
      await vi.advanceTimersByTimeAsync(LOGOUT_TIMEOUT_MS - 1)
      let settled = false
      void outcome.then(() => { settled = true })
      await Promise.resolve()
      expect(settled).toBe(false)
      await vi.advanceTimersByTimeAsync(1)
      expect(await outcome).toBe('TimeoutError')

      const own = new AbortController()
      void f(`${PROJECT}/auth/v1/token?grant_type=password`, { method: 'POST', signal: own.signal }).catch(() => undefined)
      expect(seen[1]).toBe(own.signal)
      own.abort()
    } finally {
      vi.useRealTimers()
    }
  })
})

describe('sign-out outcome: local cleanup and server revocation are reported separately', () => {
  it('server confirms in time: "signed_out"', async () => {
    await auth.signIn('a@example.test', 'pw')
    const ended = vi.fn(); const off = auth.onAuthEnded(ended)
    await auth.signOut()
    expect(ended).toHaveBeenCalledWith('signed_out')
    expect(stored()).toBeNull()
    off()
  })

  it('offline: stored session removed, reason "signed_out_unconfirmed"; a retry once the network is back confirms it', async () => {
    await auth.signIn('a@example.test', 'pw')
    logout = () => Promise.reject(new TypeError('Failed to fetch'))
    const ended = vi.fn(); const off = auth.onAuthEnded(ended)
    const confirmed = vi.fn(); const offC = auth.onSignOutConfirmed(confirmed)
    await auth.signOut()
    expect(ended).toHaveBeenCalledWith('signed_out_unconfirmed')
    expect(stored()).toBeNull()
    // Still offline: the retry cannot confirm.
    expect(await auth.confirmSignOut()).toBe(false)
    expect(confirmed).not.toHaveBeenCalled()
    // Network back: the retry asks the server with the captured token (scope global).
    logout = async () => new Response(null, { status: 204 })
    calls.length = 0
    expect(await auth.confirmSignOut()).toBe(true)
    expect(calls.some((u) => /\/auth\/v1\/logout\?scope=global/.test(u))).toBe(true)
    expect(confirmed).toHaveBeenCalledTimes(1)
    // Nothing left to confirm.
    expect(await auth.confirmSignOut()).toBe(false)
    off(); offC()
  })

  it('slow /logout that succeeds after the shell left: first "unconfirmed", then confirmed', async () => {
    await auth.signIn('a@example.test', 'pw')
    let release!: () => void
    logout = () => new Promise<Response>((r) => { release = () => r(new Response(null, { status: 204 })) })
    const ended = vi.fn(); const off = auth.onAuthEnded(ended)
    const confirmed = vi.fn(); const offC = auth.onSignOutConfirmed(confirmed)
    await auth.signOut()
    expect(ended).toHaveBeenCalledWith('signed_out_unconfirmed')
    expect(confirmed).not.toHaveBeenCalled()
    release()
    await vi.waitFor(() => expect(confirmed).toHaveBeenCalledTimes(1))
    off(); offC()
  }, 10_000)

  it('a server refusal of the retry (expired token) does not confirm', async () => {
    await auth.signIn('a@example.test', 'pw')
    logout = () => Promise.reject(new TypeError('Failed to fetch'))
    await auth.signOut()
    logout = async () => new Response('{"code":401,"msg":"invalid JWT"}', { status: 401, headers: { 'content-type': 'application/json' } })
    expect(await auth.confirmSignOut()).toBe(false)
  })
})

describe('another tab of this browser removes the stored session', () => {
  it('this tab ends as "ended_elsewhere"; a refresh written by another tab is not an ending', async () => {
    await auth.signIn('a@example.test', 'pw')
    const ended = vi.fn(); const off = auth.onAuthEnded(ended)
    window.dispatchEvent(new StorageEvent('storage', { key: STORAGE_KEY, oldValue: '{}', newValue: '{"refreshed":true}' }))
    window.dispatchEvent(new StorageEvent('storage', { key: 'some-other-key', oldValue: 'x', newValue: null }))
    expect(ended).not.toHaveBeenCalled()
    window.dispatchEvent(new StorageEvent('storage', { key: STORAGE_KEY, oldValue: '{}', newValue: null }))
    expect(ended).toHaveBeenCalledWith('ended_elsewhere')
    expect(ended).toHaveBeenCalledTimes(1)
    // Requests stop at once in this tab.
    await expect((await import('./client')).apiRequest('/v1/me')).rejects.toMatchObject({ code: 'session_expired' })
    off()
  })
})

describe('the unconfirmed token does not outlive the next sign-in', () => {
  it('after a new sign-in there is nothing left to confirm', async () => {
    await auth.signIn('a@example.test', 'pw')
    logout = () => Promise.reject(new TypeError('Failed to fetch'))
    await auth.signOut()
    logout = async () => new Response(null, { status: 204 })
    nextUser = 'user-B'
    await auth.signIn('b@example.test', 'pw')
    calls.length = 0
    expect(await auth.confirmSignOut()).toBe(false)
    expect(calls.filter((u) => u.includes('/logout'))).toEqual([])
  })
})

describe('the server confirmed, but this browser still stores the session', () => {
  it('is not reported as a confirmed sign-out (storage silently kept it)', async () => {
    await auth.signIn('a@example.test', 'pw')
    const removeItem = vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => undefined) // silently keeps everything
    try {
      const ended = vi.fn(); const off = auth.onAuthEnded(ended)
      await auth.signOut()
      expect(stored()).toBe('user-A')
      expect(ended).toHaveBeenCalledWith('signed_out_unconfirmed')
      off()
    } finally {
      removeItem.mockRestore()
      localStorage.clear()
    }
  })
})
