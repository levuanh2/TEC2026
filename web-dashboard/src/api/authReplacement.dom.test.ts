// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

/* R3 security review, finding F2 (auth side). Another tab of the same browser
 * signs a different person in; the storage and the token are shared. This
 * tab must treat that as a replacement however it learns of it: a SIGNED_IN,
 * a TOKEN_REFRESHED that picked up the other person's stored session, or a
 * 401 recovery whose refresh returns the other person's session. In each case
 * a request asked for the previous person is not answered with the new
 * person's token. */

type Listener = (event: string, session: unknown) => void
let listener: Listener | null = null
let refreshed: unknown = null
vi.mock('../utils/supabase', () => ({
  revokeSessionsWithToken: async () => true,
  supabase: {
    auth: {
      onAuthStateChange: (fn: Listener) => { listener = fn; return { data: { subscription: { unsubscribe: () => {} } } } },
      getSession: vi.fn(async () => ({ data: { session: sessionOf('user-A', 'token-A') }, error: null })),
      refreshSession: vi.fn(async () => ({ data: { session: refreshed }, error: null })),
      signOut: vi.fn(async () => ({ error: null })),
    },
  },
}))
vi.mock('../farmer/data', () => ({ clearFarmerCache: () => {} }))

function sessionOf(id: string, token: string) { return { access_token: token, user: { id, app_metadata: {} } } }

const auth = await import('./auth')
const { queryClient } = await import('../query/client')
const client = await import('./client')
const sent: (string | null)[] = []
let answer: (authz: string | null) => Promise<Response>

beforeEach(async () => {
  sent.length = 0
  answer = async () => new Response('{"ok":true}', { status: 200 })
  vi.stubGlobal('fetch', vi.fn(async (_u: string, init: RequestInit) => {
    const a = new Headers(init.headers).get('Authorization'); sent.push(a); return answer(a)
  }))
  await auth.restoreSession()
})
afterEach(() => { vi.unstubAllGlobals() })

const deferred = () => { let resolve!: (r: Response) => void; const p = new Promise<Response>((r) => { resolve = r }); return { p, resolve } }

describe('another person takes over the shared session', () => {
  it.each(['SIGNED_IN', 'TOKEN_REFRESHED'])('%s for another user: the tab is told, and an in-flight request is not retried with their token', async (event) => {
    const replaced = vi.fn()
    const off = auth.onSessionReplaced(replaced)
    const first = deferred()
    answer = () => first.p
    const req = client.apiRequest('/v1/farmer/scope')
    await vi.waitFor(() => expect(sent).toEqual(['Bearer token-A']))
    listener!(event, sessionOf('user-B', 'token-B'))
    expect(replaced).toHaveBeenCalledTimes(1)
    expect((replaced.mock.calls[0][0] as { user: { id: string } }).user.id).toBe('user-B')
    first.resolve(new Response('{}', { status: 401 }))
    await expect(req).rejects.toMatchObject({ code: 'session_replaced' })
    expect(sent).toEqual(['Bearer token-A'])
    // New requests go out as B.
    answer = async () => new Response('{"ok":true}', { status: 200 })
    await client.apiRequest('/v1/me')
    expect(sent.at(-1)).toBe('Bearer token-B')
    off()
  })

  it('a 401 recovery whose refresh returns another person\'s session: replacement, no retry with that token', async () => {
    const replaced = vi.fn()
    const off = auth.onSessionReplaced(replaced)
    const ended = vi.fn()
    const offEnded = auth.onAuthEnded(ended)
    refreshed = sessionOf('user-B', 'token-B')
    answer = async () => new Response('{}', { status: 401 })
    await expect(client.apiRequest('/v1/me')).rejects.toMatchObject({ code: 'session_replaced' })
    expect(sent).toEqual(['Bearer token-A'])
    expect(replaced).toHaveBeenCalledTimes(1)
    expect(ended).not.toHaveBeenCalled()
    off(); offEnded()
  })

  it('the same person refreshed: no replacement, the request is retried with the new token', async () => {
    const replaced = vi.fn()
    const off = auth.onSessionReplaced(replaced)
    refreshed = sessionOf('user-A', 'token-A2')
    let n = 0
    answer = async () => (n++ === 0 ? new Response('{}', { status: 401 }) : new Response('{"ok":2}', { status: 200 }))
    await expect(client.apiRequest('/v1/me')).resolves.toEqual({ ok: 2 })
    expect(sent).toEqual(['Bearer token-A', 'Bearer token-A2'])
    listener!('TOKEN_REFRESHED', sessionOf('user-A', 'token-A3'))
    expect(replaced).not.toHaveBeenCalled()
    off()
  })
})

describe('sign-out', () => {
  it('drops every cached query answer, even when the next person is the same account', async () => {
    queryClient.setQueryData(['u', 'user-A', 'org', 'org-1', 'carbon-status'], [{ row: 1 }])
    await auth.signOut()
    expect(queryClient.getQueryCache().getAll()).toEqual([])
  })
})
