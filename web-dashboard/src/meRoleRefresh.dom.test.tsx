// @vitest-environment jsdom
import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setAccessToken, setUnauthorizedHandler } from './api/client'

/* Session expiry and the refresh token, through the REAL /v1/me client
 * (api/me getMe -> api/client apiRequest; only fetch is faked). The access
 * token is expired, /v1/me answers 401, the client refreshes once and retries:
 *  - refresh succeeds  -> the role from the retried /v1/me opens the shell,
 *                         and nothing renders before that answer;
 *  - refresh fails     -> the session ends: login with next=, no shell, no
 *                         "unverified" error and no guessed role. */

let ended: ((reason: 'expired' | 'signed_out') => void) | null = null
const renders = { farmer: 0, ops: 0 }

vi.mock('./api/auth', () => ({
  onAuthEnded: (fn: typeof ended) => { ended = fn; return () => { ended = null } },
  onSessionRefreshed: () => () => {},
  onSessionReplaced: () => () => {},
  restoreSession: async () => ({ access_token: 'expired', user: { id: 'u1', email: 'manager@example.test', app_metadata: {} } }),
  signIn: vi.fn(),
  signOut: vi.fn(),
  mustChangePassword: () => false,
}))
vi.mock('./api/organizations', () => ({ getOrganization: async (id: string) => ({ id, name: 'HTX Một' }), clearOrganizationCache: () => {} }))
vi.mock('./farmer/scope', async (orig) => ({ ...(await orig<object>()), prefetchFarmerScope: () => {} }))
vi.mock('./api/farms', async (orig) => ({ ...(await orig<object>()), usingMockData: false }))
vi.mock('./farmer/FarmerExperience', () => ({ FarmerExperience: () => { renders.farmer++; return <p>farmer-experience</p> } }))
vi.mock('./pages/operations', () => ({
  OperationsOverview: () => { renders.ops++; return <p>ops-overview</p> },
  SeasonsWorkspace: () => <p>seasons-workspace</p>,
}))

const { default: App } = await import('./App')

const MANAGER_ME = { user_id: 'u1', full_name: 'Quản lý', roles: ['cooperative_manager'], organization_memberships: [{ organization_id: 'org-1' }], farm_memberships: [] }
const sentTokens: string[] = []
let releaseRetry: () => void = () => {}

beforeEach(() => {
  renders.farmer = 0; renders.ops = 0; sentTokens.length = 0
  localStorage.clear()
  setAccessToken('expired')
  vi.stubGlobal('fetch', vi.fn(async (_url: string, init: RequestInit) => {
    const token = new Headers(init.headers).get('Authorization')?.replace('Bearer ', '') ?? ''
    sentTokens.push(token)
    if (token !== 'fresh') return new Response(JSON.stringify({ detail: { error: { code: 'invalid_token', message: 'expired' } } }), { status: 401 })
    // The retried request waits so the test can look at the screen meanwhile.
    await new Promise<void>((r) => { releaseRetry = r })
    return new Response(JSON.stringify(MANAGER_ME), { status: 200 })
  }))
})
afterEach(() => { cleanup(); ended = null; setUnauthorizedHandler(null); vi.unstubAllGlobals() })

describe('/v1/me with an expired access token', () => {
  it('refresh succeeds: skeleton until the retried /v1/me answers, then the confirmed Manager shell', async () => {
    setUnauthorizedHandler(async () => { setAccessToken('fresh'); return 'fresh' })
    history.replaceState({}, '', '/dashboard')
    render(<App />)
    await waitFor(() => expect(sentTokens).toEqual(['expired', 'fresh']))
    await act(async () => { await new Promise((r) => setTimeout(r, 30)) })
    expect(screen.getByTestId('viewer-verifying')).toBeTruthy()
    expect(renders.farmer + renders.ops).toBe(0)

    act(() => releaseRetry())
    expect(await screen.findByText('ops-overview')).toBeTruthy()
    expect(renders.farmer).toBe(0)
    expect(location.pathname).toBe('/dashboard')
  })

  it('refresh fails: the session ends -> login with next=, never a shell or a guessed role', async () => {
    // What api/auth does when the refresh token is rejected: end the session, no token.
    setUnauthorizedHandler(async () => { ended?.('expired'); return null })
    history.replaceState({}, '', '/dashboard')
    render(<App />)
    await waitFor(() => expect(location.pathname + location.search).toBe('/login?next=%2Fdashboard'))
    await act(async () => { await new Promise((r) => setTimeout(r, 30)) })
    expect(screen.queryByTestId('viewer-unverified')).toBeNull()
    expect(document.body.textContent).toContain('Đăng nhập lại')
    expect(renders.farmer + renders.ops).toBe(0)
    expect(sentTokens).toEqual(['expired'])
  })
})
