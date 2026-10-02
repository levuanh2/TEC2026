// @vitest-environment jsdom
import { cleanup, render, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

/* Round 4.4 final gate — found by round4-real "an expired session lands on
 * login" failing intermittently with the URL on /farmer instead of
 * /login?next=%2Ffarmer%2Fjournal.
 *
 * When /v1/me is in flight and its 401 ends the session, the session-end
 * handler sends the app to /login?next=…, and then getMe() rejects in the same
 * microtask chain — before React commits the render whose effect cleanup
 * would mark that request stale. Its catch ran the role redirect, which sends
 * "/login" to the role's home: the person saw the login screen but lost the
 * page to come back to. Whether it happened depended on Supabase's lock timing,
 * so the real test was flaky; here the order is forced. */

let ended: ((reason: 'expired' | 'signed_out') => void) | null = null
let rejectMe: ((e: unknown) => void) | null = null

vi.mock('./api/auth', () => ({
  onAuthEnded: (fn: typeof ended) => { ended = fn; return () => { ended = null } },
  restoreSession: async () => ({ access_token: 't', user: { id: 'u1', email: 'farmer@example.test' } }),
  signIn: vi.fn(),
  signOut: vi.fn(),
  mustChangePassword: () => false,
}))
vi.mock('./api/me', () => ({
  getMe: () => new Promise((_, reject) => { rejectMe = reject }),
  readViewerHint: () => null,
  writeViewerHint: () => {},
}))
vi.mock('./farmer/scope', async (orig) => ({ ...(await orig<object>()), prefetchFarmerScope: () => {} }))
vi.mock('./api/farms', async (orig) => ({ ...(await orig<object>()), usingMockData: false }))

const { default: App } = await import('./App')

afterEach(() => { cleanup(); ended = null; rejectMe = null })

describe('session ends while /v1/me is in flight', () => {
  it('stays on /login?next=… — the failed /v1/me does not redirect to the role home', async () => {
    history.replaceState({}, '', '/farmer/journal')
    render(<App />)
    await waitFor(() => expect(rejectMe).not.toBeNull())
    // Same order as the real failure: the 401 ends the session, then the same
    // request rejects — with no React commit in between.
    ended!('expired')
    rejectMe!(new Error('session_expired'))
    await new Promise((r) => setTimeout(r, 50))
    await waitFor(() => expect(document.body.textContent).toContain('Đăng nhập lại'))
    expect(location.pathname + location.search).toBe('/login?next=%2Ffarmer%2Fjournal')
  })
})
