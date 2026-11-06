// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

/* R3 security review, F4/F5, against the REAL auth-js client: only the network
 * is fake, and the session lives in jsdom's localStorage exactly as in a
 * browser. This pins the auth-js behaviour the sign-out relies on, so an
 * upgrade that changes it fails here.
 *
 * Sign-out contract:
 *  - local first, at once: nothing stored, requests stopped, the shell leaves
 *    ("signing_out") before the server answers;
 *  - server revocation (/logout?scope=global, the person's own token): only a
 *    2xx confirms it. Offline, hung, 401/403/500/503, or a session still
 *    stored -> "unconfirmed";
 *  - "Thử xác nhận lại" uses that sign-out's own token and is bounded;
 *  - a late sign-out never removes the next person's session (F5);
 *  - a token refresh racing the sign-out cannot bring the session back. */

const PROJECT = 'https://r3probe.supabase.co'
const STORAGE_KEY = 'sb-r3probe-auth-token'
let logout: () => Promise<Response>
let nextUser = 'user-A'
const calls: string[] = []
const logoutAuth: string[] = []

const b64 = (o: object) => btoa(JSON.stringify(o)).replace(/=+$/, '').replace(/\+/g, '-').replace(/\//g, '_')
const jwt = (sub: string, n = 0) => `${b64({ alg: 'HS256', typ: 'JWT' })}.${b64({ sub, n, exp: Math.floor(Date.now() / 1000) + 3600, role: 'authenticated' })}.c2ln`
let tokenSerial = 0
function sessionFor(sub: string) {
  tokenSerial++
  return { access_token: jwt(sub, tokenSerial), refresh_token: `r-${sub}-${tokenSerial}`, token_type: 'bearer', expires_in: 3600, expires_at: Math.floor(Date.now() / 1000) + 3600, user: { id: sub, aud: 'authenticated', email: `${sub}@example.test`, app_metadata: {}, user_metadata: {} } }
}
let refresh: () => Promise<Response> = async () => new Response('{}', { status: 400 })
async function network(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
  calls.push(url.replace(PROJECT, ''))
  if (url.includes('/token?grant_type=password')) return new Response(JSON.stringify(sessionFor(nextUser)), { status: 200, headers: { 'content-type': 'application/json' } })
  if (url.includes('/token?grant_type=refresh_token')) return refresh()
  if (url.includes('/logout')) {
    logoutAuth.push(new Headers(init?.headers).get('Authorization') ?? '')
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
  return {
    ...real,
    supabase: createClient(PROJECT, 'publishable-test-key', { auth: { autoRefreshToken: false, detectSessionInUrl: false }, global: { fetch: real.boundedAuthFetch(network) } }),
    // The real revoker, pointed at the same fake project and network.
    revokeSessionsWithToken: real.revokerFor(PROJECT, 'publishable-test-key', real.boundedAuthFetch(network)),
  }
})
vi.mock('../farmer/data', () => ({ clearFarmerCache: () => {} }))

const auth = await import('./auth')
const client = await import('./client')
const { supabase } = await import('../utils/supabase')
const stored = () => { const raw = localStorage.getItem(STORAGE_KEY); return raw ? (JSON.parse(raw).user?.id ?? null) : null }
const ok204 = async () => new Response(null, { status: 204 })
const settle = (ms = 50) => new Promise((r) => setTimeout(r, ms))

function record() {
  const ended = vi.fn(); const offE = auth.onAuthEnded(ended)
  const outcome = vi.fn(); const offO = auth.onSignOutOutcome(outcome)
  return { ended, outcome, off: () => { offE(); offO() } }
}

beforeEach(() => { calls.length = 0; logoutAuth.length = 0; nextUser = 'user-A'; logout = ok204; refresh = async () => new Response('{}', { status: 400 }) })
afterEach(() => { logout = ok204; localStorage.clear() })

describe('sign-out: local first, then the server', () => {
  it('the storage key removed is the one auth-js uses; 204 -> "signing_out" then "confirmed"', async () => {
    expect((supabase!.auth as unknown as { storageKey: string }).storageKey).toBe(STORAGE_KEY)
    await auth.signIn('a@example.test', 'pw')
    expect(stored()).toBe('user-A')
    const r = record()
    await auth.signOut()
    expect(r.ended).toHaveBeenCalledWith('signing_out')
    expect(r.outcome).toHaveBeenCalledWith('confirmed')
    expect(r.outcome).not.toHaveBeenCalledWith('unconfirmed')
    expect(stored()).toBeNull()
    expect(calls.filter((u) => u.includes('/logout'))).toEqual(['/auth/v1/logout?scope=global'])
    r.off()
  })

  it('the shell leaves at once: "signing_out", nothing stored and requests refused, before the server answers', async () => {
    await auth.signIn('a@example.test', 'pw')
    let unhang!: () => void
    logout = () => new Promise<Response>((res) => { unhang = () => res(new Response(null, { status: 204 })) })
    const r = record()
    const out = auth.signOut()
    await settle(20)
    expect(r.ended).toHaveBeenCalledWith('signing_out')
    expect(r.outcome).not.toHaveBeenCalled()
    expect(stored()).toBeNull()
    await expect(client.apiRequest('/v1/me')).rejects.toMatchObject({ code: 'session_expired' })
    await out
    unhang(); await settle()   // let the pending sign-out end: the next sign-in would wait for it
    r.off()
  }, 10_000)

  it('F4: /logout hangs -> "unconfirmed"; a reload restores nothing', async () => {
    await auth.signIn('a@example.test', 'pw')
    let unhang!: () => void
    logout = () => new Promise<Response>((res) => { unhang = () => res(new Response(null, { status: 204 })) })
    const r = record()
    await auth.signOut()
    expect(r.outcome).toHaveBeenCalledWith('unconfirmed')
    expect(stored()).toBeNull()
    expect(await auth.restoreSession()).toBeNull()
    unhang(); await settle()
    r.off()
  }, 10_000)

  it.each([401, 403, 500, 503])('/logout answers %i -> "unconfirmed" (auth-js would call 401/403 a success)', async (status) => {
    await auth.signIn('a@example.test', 'pw')
    logout = async () => new Response(JSON.stringify({ code: status, msg: 'x' }), { status, headers: { 'content-type': 'application/json' } })
    const r = record()
    await auth.signOut()
    expect(r.outcome).toHaveBeenCalledWith('unconfirmed')
    expect(r.outcome).not.toHaveBeenCalledWith('confirmed')
    expect(stored()).toBeNull()
    r.off()
  })

  it('offline -> "unconfirmed"; the retry while still offline fails; once the network is back it confirms with the ORIGINAL token', async () => {
    await auth.signIn('a@example.test', 'pw')
    const tokenA = JSON.parse(localStorage.getItem(STORAGE_KEY)!).access_token
    logout = () => Promise.reject(new TypeError('Failed to fetch'))
    const r = record()
    await auth.signOut()
    expect(r.outcome).toHaveBeenCalledWith('unconfirmed')
    expect(stored()).toBeNull()
    expect(await auth.confirmSignOut()).toBe(false)
    logout = ok204
    logoutAuth.length = 0; calls.length = 0
    expect(await auth.confirmSignOut()).toBe(true)
    expect(calls.filter((u) => u.includes('/logout'))).toEqual(['/auth/v1/logout?scope=global'])
    expect(logoutAuth).toEqual([`Bearer ${tokenA}`])
    expect(r.outcome).toHaveBeenLastCalledWith('confirmed')
    expect(await auth.confirmSignOut()).toBe(false)   // nothing left to confirm
    r.off()
  })

  it(`the retry is bounded: after ${3} failures it stops and sends nothing more`, async () => {
    await auth.signIn('a@example.test', 'pw')
    logout = () => Promise.reject(new TypeError('Failed to fetch'))
    await auth.signOut()
    for (let i = 0; i < auth.MAX_CONFIRM_ATTEMPTS; i++) expect(await auth.confirmSignOut()).toBe(false)
    expect(auth.canConfirmSignOut()).toBe(false)
    calls.length = 0
    logout = ok204
    expect(await auth.confirmSignOut()).toBe(false)
    expect(calls).toEqual([])
  })

  it('slow /logout that succeeds after the shell left: "unconfirmed", then "confirmed"', async () => {
    await auth.signIn('a@example.test', 'pw')
    let release!: () => void
    logout = () => new Promise<Response>((res) => { release = () => res(new Response(null, { status: 204 })) })
    const r = record()
    await auth.signOut()
    expect(r.outcome).toHaveBeenCalledWith('unconfirmed')
    release()
    await vi.waitFor(() => expect(r.outcome).toHaveBeenLastCalledWith('confirmed'))
    r.off()
  }, 10_000)

  it('the server confirmed, but the browser still stores the session -> "unconfirmed"', async () => {
    await auth.signIn('a@example.test', 'pw')
    const removeItem = vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => undefined) // silently keeps everything
    try {
      const r = record()
      await auth.signOut()
      expect(stored()).toBe('user-A')
      expect(r.outcome).toHaveBeenCalledWith('unconfirmed')
      expect(r.outcome).not.toHaveBeenCalledWith('confirmed')
      r.off()
    } finally {
      removeItem.mockRestore()
      localStorage.clear()
    }
  })

  it('a token refresh racing the sign-out cannot bring the session back', async () => {
    await auth.signIn('a@example.test', 'pw')
    let releaseRefresh!: () => void
    refresh = () => new Promise<Response>((res) => { releaseRefresh = () => res(new Response(JSON.stringify(sessionFor('user-A')), { status: 200, headers: { 'content-type': 'application/json' } })) })
    const refreshing = supabase!.auth.refreshSession().catch(() => undefined)
    await settle(10)
    const out = auth.signOut()
    await settle(10)
    releaseRefresh()                       // the refresh stores a NEW session after the local removal
    await refreshing
    await out
    await settle(100)
    expect(stored()).toBeNull()
    expect((await supabase!.auth.getSession()).data.session).toBeNull()
  }, 10_000)
})

describe('F5: a late sign-out and the next person', () => {
  it('/logout is slow and the next person signs in meanwhile: their session survives; the sign-in waited', async () => {
    await auth.signIn('a@example.test', 'pw')
    let release!: () => void
    logout = () => new Promise<Response>((res) => { release = () => res(new Response(null, { status: 204 })) })
    const r = record()
    await auth.signOut()
    nextUser = 'user-B'
    const signingIn = auth.signIn('b@example.test', 'pw')
    await settle()
    // While A's revocation is pending, the next sign-in has NOT gone out yet: a
    // global revocation landing after it would also end a new session of the
    // same account.
    expect(calls.filter((u) => u.includes('grant_type=password'))).toHaveLength(1)
    release()
    const b = await signingIn
    expect(b?.user.id).toBe('user-B')
    await settle()
    expect(stored()).toBe('user-B')
    expect((await supabase!.auth.getSession()).data.session?.user.id).toBe('user-B')
    expect(r.ended).toHaveBeenCalledTimes(1)
    // B's password grant went out only after A's /logout had returned.
    expect(calls.filter((u) => /logout|grant_type=password/.test(u)).map((u) => (u.includes('logout') ? 'logout' : 'token'))).toEqual(['token', 'logout', 'token'])
    r.off()
  }, 10_000)

  it('the next sign-in drops the unconfirmed token: nothing left to confirm, nothing sent', async () => {
    await auth.signIn('a@example.test', 'pw')
    logout = () => Promise.reject(new TypeError('Failed to fetch'))
    await auth.signOut()
    logout = ok204
    nextUser = 'user-B'
    await auth.signIn('b@example.test', 'pw')
    calls.length = 0
    expect(await auth.confirmSignOut()).toBe(false)
    expect(calls.filter((u) => u.includes('/logout'))).toEqual([])
  })
})

describe('another tab of this browser removes the stored session', () => {
  it('this tab ends as "ended_elsewhere"; a refresh written by another tab is not an ending', async () => {
    await auth.signIn('a@example.test', 'pw')
    const r = record()
    window.dispatchEvent(new StorageEvent('storage', { key: STORAGE_KEY, oldValue: '{}', newValue: '{"refreshed":true}' }))
    window.dispatchEvent(new StorageEvent('storage', { key: 'some-other-key', oldValue: 'x', newValue: null }))
    expect(r.ended).not.toHaveBeenCalled()
    window.dispatchEvent(new StorageEvent('storage', { key: STORAGE_KEY, oldValue: '{}', newValue: null }))
    expect(r.ended).toHaveBeenCalledWith('ended_elsewhere')
    expect(r.ended).toHaveBeenCalledTimes(1)
    await expect(client.apiRequest('/v1/me')).rejects.toMatchObject({ code: 'session_expired' })
    r.off()
  })
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
