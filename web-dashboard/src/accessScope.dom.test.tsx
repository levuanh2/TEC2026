// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useEffect } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { keys, queryClient } from './query/client'

/* R3 security review. /v1/me is mapped by the REAL toCurrentUser here (only
 * the network answer is faked), so the tests see exactly what the shell
 * compares between answers.
 *  F1: losing a farm the account could only READ (farm_role viewer), or a
 *      second organisation membership, changed nothing the shell compared, so
 *      a re-check kept the rows cached under it on screen.
 *  F3: the first /v1/me of a session applied an answer for ANOTHER account
 *      (token replaced in flight) as this session's role, and wrote it into
 *      this user's hint.
 *  F6: a crafted ?next= that the browser resolves to another origin made the
 *      sign-in itself fail (replaceState throws). */

type Raw = { user_id: string; full_name: string | null; roles: string[]; organization_memberships: { organization_id: string; role: string }[]; farm_memberships: { farm_id: string; farm_role: string }[] }
let raw: () => Promise<Raw>
const writeViewerHint = vi.fn()
const signIn = vi.fn()
const mounts = { farmer: 0 }
let ended: ((reason: 'expired' | 'signed_out') => void) | null = null
let session: { access_token: string; user: { id: string; email: string; app_metadata: object } } | null

vi.mock('./api/auth', () => ({
  onSignOutConfirmed: () => () => {},
  confirmSignOut: async () => false,
  onAuthEnded: (fn: typeof ended) => { ended = fn; return () => { ended = null } },
  onSessionRefreshed: () => () => {},
  onSessionReplaced: () => () => {},
  restoreSession: async () => session,
  signIn: (...a: unknown[]) => signIn(...a),
  signOut: vi.fn(),
  mustChangePassword: () => false,
}))
vi.mock('./api/me', async (orig) => {
  const real = await orig<typeof import('./api/me')>()
  return { ...real, getMe: async () => real.toCurrentUser(await raw()), readViewerHint: () => null, writeViewerHint: (...a: unknown[]) => writeViewerHint(...a), clearViewerHint: () => {} }
})
vi.mock('./api/organizations', async (orig) => ({ ...(await orig<object>()), getOrganization: async (id: string) => ({ id, name: 'HTX QA' }), clearOrganizationCache: () => {} }))
vi.mock('./farmer/scope', async (orig) => ({ ...(await orig<object>()), prefetchFarmerScope: () => {} }))
vi.mock('./query/prefetch', () => ({ prefetchRouteData: () => {} }))
vi.mock('./api/farms', async (orig) => ({ ...(await orig<object>()), usingMockData: false }))
vi.mock('./farmer/FarmerExperience', () => ({
  FarmerExperience: () => { useEffect(() => { mounts.farmer++ }, []); return <p>farmer-experience</p> },
}))
vi.mock('./pages/operations', () => ({
  OperationsOverview: ({ organizationId }: { organizationId: string | null }) => <p>ops-overview {organizationId}</p>,
  SeasonsWorkspace: () => <p>seasons-workspace</p>,
}))

const { default: App, REVALIDATE_MIN_INTERVAL_MS } = await import('./App')

const SESSION_A = { access_token: 't-a', user: { id: 'user-A', email: 'a@example.test', app_metadata: {} } }
const farmer = (farms: Raw['farm_memberships'], orgs: Raw['organization_memberships'] = [{ organization_id: 'org-1', role: 'farmer' }]): Raw =>
  ({ user_id: 'user-A', full_name: 'QA', roles: [...new Set([...orgs.map((o) => o.role), ...farms.map((f) => f.farm_role)])], organization_memberships: orgs, farm_memberships: farms })
const ROWS = [{ season: 'cached-under-the-old-access' }]
let now = 1_000_000
const later = () => { now += REVALIDATE_MIN_INTERVAL_MS + 1 }
const focus = () => act(() => { window.dispatchEvent(new Event('focus')) })
const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 20)) })

beforeEach(() => {
  now = 1_000_000
  vi.spyOn(Date, 'now').mockImplementation(() => now)
  queryClient.clear(); mounts.farmer = 0; session = SESSION_A
  writeViewerHint.mockClear(); signIn.mockReset()
})
afterEach(() => { cleanup(); vi.restoreAllMocks() })

async function startAsFarmer(first: Raw) {
  raw = async () => first
  history.replaceState({}, '', '/farmer')
  render(<App />)
  await screen.findByText('farmer-experience')
  await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
  queryClient.setQueryData(keys.org('org-1', 'carbon-status'), ROWS)
  expect(mounts.farmer).toBe(1)
}

describe('F1: a re-check compares every membership, read-only ones included', () => {
  it('a READ-ONLY farm removed: caches dropped and the Farmer tree remounts', async () => {
    await startAsFarmer(farmer([{ farm_id: 'farm-1', farm_role: 'editor' }, { farm_id: 'farm-2', farm_role: 'viewer' }]))
    raw = async () => farmer([{ farm_id: 'farm-1', farm_role: 'editor' }])
    later(); await focus(); await settle()
    await waitFor(() => expect(mounts.farmer).toBe(2))
    expect(queryClient.getQueryData(keys.org('org-1', 'carbon-status'))).toBeUndefined()
  })

  it('a second organisation membership ended: caches dropped', async () => {
    await startAsFarmer(farmer([{ farm_id: 'farm-1', farm_role: 'editor' }], [{ organization_id: 'org-1', role: 'farmer' }, { organization_id: 'org-2', role: 'farmer' }]))
    raw = async () => farmer([{ farm_id: 'farm-1', farm_role: 'editor' }])
    later(); await focus(); await settle()
    await waitFor(() => expect(mounts.farmer).toBe(2))
    expect(queryClient.getQueryData(keys.org('org-1', 'carbon-status'))).toBeUndefined()
  })

  it('the same memberships in another order change nothing (no remount, cache kept)', async () => {
    const farms = [{ farm_id: 'farm-1', farm_role: 'editor' }, { farm_id: 'farm-2', farm_role: 'viewer' }]
    await startAsFarmer(farmer(farms))
    raw = async () => farmer([...farms].reverse())
    later(); await focus(); await settle()
    expect(mounts.farmer).toBe(1)
    expect(queryClient.getQueryData(keys.org('org-1', 'carbon-status'))).toEqual(ROWS)
  })
})

describe('F3: the first /v1/me answer of a session must be for that session', () => {
  it("an answer for another account: no business screen, no hint for this user, a neutral retry screen", async () => {
    raw = async () => ({ user_id: 'user-B', full_name: 'B', roles: ['cooperative_manager'], organization_memberships: [{ organization_id: 'org-B', role: 'cooperative_manager' }], farm_memberships: [] })
    history.replaceState({}, '', '/dashboard')
    render(<App />)
    expect(await screen.findByTestId('viewer-unverified')).toBeTruthy()
    expect(screen.queryByText(/ops-overview/)).toBeNull()
    expect(document.querySelector('.shell, .role-chip')).toBeNull()
    expect(writeViewerHint).not.toHaveBeenCalled()
    expect(location.pathname).toBe('/dashboard')
  })
})

describe('F6: ?next= after sign-in', () => {
  it.each([
    ['/\\evil.example/phish'],
    ['//evil.example/phish'],
    ['https://evil.example/phish'],
  ])('%s: sign-in still completes and the URL stays on this site', async (next) => {
    session = null
    signIn.mockResolvedValue(SESSION_A)
    raw = async () => farmer([{ farm_id: 'farm-1', farm_role: 'editor' }])
    history.replaceState({}, '', `/login?next=${encodeURIComponent(next)}`)
    render(<App />)
    const form = (await screen.findByRole('button', { name: 'Đăng nhập' })).closest('form')!
    fireEvent.change(form.querySelector('input[name=email]')!, { target: { value: 'a@example.test' } })
    fireEvent.change(form.querySelector('input[name=password]')!, { target: { value: 'pw' } })
    fireEvent.submit(form)
    expect(await screen.findByText('farmer-experience')).toBeTruthy()
    expect(location.origin).toBe(window.location.origin)
    expect(location.pathname).toBe('/farmer')
  })

  it('a page of this site is still returned to', async () => {
    session = null
    signIn.mockResolvedValue(SESSION_A)
    raw = async () => farmer([{ farm_id: 'farm-1', farm_role: 'editor' }])
    history.replaceState({}, '', `/login?next=${encodeURIComponent('/farmer/journal?season=s1')}`)
    render(<App />)
    const form = (await screen.findByRole('button', { name: 'Đăng nhập' })).closest('form')!
    fireEvent.change(form.querySelector('input[name=email]')!, { target: { value: 'a@example.test' } })
    fireEvent.change(form.querySelector('input[name=password]')!, { target: { value: 'pw' } })
    fireEvent.submit(form)
    expect(await screen.findByText('farmer-experience')).toBeTruthy()
    expect(location.pathname + location.search).toBe('/farmer/journal?season=s1')
  })
})

describe('the first /v1/me of a session still pending when the session ends', () => {
  it('sign-out: its late answer writes no hint, renders nothing and does not leave /login', async () => {
    let resolveLate: (r: Raw) => void = () => {}
    let asked = false
    raw = () => { asked = true; return new Promise<Raw>((r) => { resolveLate = r }) }
    history.replaceState({}, '', '/dashboard')
    render(<App />)
    await waitFor(() => expect(asked).toBe(true))
    act(() => ended!('signed_out'))
    expect(location.pathname).toBe('/login')
    resolveLate({ user_id: 'user-A', full_name: 'A', roles: ['cooperative_manager'], organization_memberships: [{ organization_id: 'org-1', role: 'cooperative_manager' }], farm_memberships: [] })
    await settle()
    expect(location.pathname).toBe('/login')
    expect(writeViewerHint).not.toHaveBeenCalled()
    expect(document.querySelector('.shell, .role-chip')).toBeNull()
  })
})
