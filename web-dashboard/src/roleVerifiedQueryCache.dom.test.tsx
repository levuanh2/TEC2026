// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { CurrentUser } from './api/me'
import { keys, queryClient } from './query/client'

/* PR #12 (shared TanStack query cache) + PR #15 (no business screen before
 * /v1/me confirms the role), integrated. The query keys carry the user and the
 * organisation but not the role, so the shell must drop cached rows whenever
 * /v1/me confirms a different scope -- including the same user and the same
 * organisation with another role -- before the new shell's first render. And
 * nothing of PR #12's prefetching may start before the role is confirmed.
 * Uses the REAL query client; the business pages record what the cache held
 * at their first render. */

let ended: ((reason: 'expired' | 'signed_out') => void) | null = null
type FakeSession = { access_token: string; user: { id: string; email: string; app_metadata: object } }
const SESSION: FakeSession = { access_token: 't1', user: { id: 'u1', email: 'qa@example.test', app_metadata: {} } }
const signIn = vi.fn(async (): Promise<FakeSession> => ({ ...SESSION, access_token: 't2' }))
let meAnswer: () => Promise<CurrentUser>
const getMe = vi.fn(() => meAnswer())
const prefetchRouteData = vi.fn()
const prefetchRoute = vi.fn()
const clearFarmerCache = vi.fn()
const seenAtFirstRender: { page: string; cached: unknown }[] = []

vi.mock('./api/auth', () => ({
  onAuthEnded: (fn: typeof ended) => { ended = fn; return () => { ended = null } },
  onSessionRefreshed: () => () => {},
  restoreSession: async () => SESSION,
  signIn: () => signIn(),
  signOut: vi.fn(),
  mustChangePassword: () => false,
}))
vi.mock('./api/me', () => ({ getMe: () => getMe(), readViewerHint: () => null, writeViewerHint: () => {}, clearViewerHint: () => {} }))
vi.mock('./api/organizations', async (orig) => ({
  ...(await orig<object>()),
  getOrganization: async (id: string) => ({ id, name: 'HTX QA' }),
  clearOrganizationCache: () => {},
}))
vi.mock('./farmer/data', async (orig) => ({ ...(await orig<object>()), clearFarmerCache: () => clearFarmerCache() }))
vi.mock('./farmer/scope', async (orig) => ({ ...(await orig<object>()), prefetchFarmerScope: () => {} }))
vi.mock('./query/prefetch', () => ({ prefetchRouteData: (...a: unknown[]) => prefetchRouteData(...a) }))
vi.mock('./routeChunks', async (orig) => ({ ...(await orig<object>()), prefetchRoute: (...a: unknown[]) => prefetchRoute(...a) }))
vi.mock('./api/farms', async (orig) => ({ ...(await orig<object>()), usingMockData: false }))
vi.mock('./farmer/FarmerExperience', () => ({
  FarmerExperience: () => {
    seenAtFirstRender.push({ page: 'farmer', cached: queryClient.getQueryData(keys.farms()) })
    return <p>farmer-experience</p>
  },
}))
vi.mock('./pages/operations', () => ({
  OperationsOverview: ({ organizationId }: { organizationId: string }) => {
    seenAtFirstRender.push({ page: 'ops', cached: queryClient.getQueryData(keys.org(organizationId, 'carbon-status')) })
    return <p>ops-overview</p>
  },
  SeasonsWorkspace: () => <p>seasons-workspace</p>,
}))

const { default: App } = await import('./App')

const MANAGER: CurrentUser = { role: 'cooperative_manager', organizationId: 'org-1', fullName: 'QA' }
const VIEWER: CurrentUser = { role: 'enterprise_viewer', organizationId: 'org-1', fullName: 'QA' }
const FARMER: CurrentUser = { role: 'farmer', organizationId: 'org-1', fullName: 'QA', writableFarmIds: ['farm-1'] }
const MANAGER_ROWS = [{ season: 's-only-a-manager-may-see' }]

async function signInAgain() {
  act(() => ended!('expired'))
  await waitFor(() => expect(location.pathname).toBe('/login'))
  fireEvent.change(screen.getByLabelText('Email'), { target: { value: SESSION.user.email } })
  fireEvent.change(screen.getByLabelText('Mật khẩu'), { target: { value: 'x' } })
  fireEvent.submit(screen.getByLabelText('Email').closest('form')!)
}
/** What the first shell of the given session found in the cache. */
const firstRender = (page: string) => seenAtFirstRender.filter((r) => r.page === page)

beforeEach(() => { queryClient.clear(); seenAtFirstRender.length = 0 })
afterEach(() => {
  cleanup(); ended = null
  for (const fn of [getMe, signIn, prefetchRouteData, prefetchRoute, clearFarmerCache]) fn.mockClear()
})

describe('query cache follows the scope /v1/me confirms', () => {
  it('same user and organisation, role changed (Manager -> enterprise viewer): the Manager rows are gone before the new shell renders', async () => {
    meAnswer = async () => MANAGER
    history.replaceState({}, '', '/dashboard')
    render(<App />)
    await screen.findByText('ops-overview')
    queryClient.setQueryData(keys.org('org-1', 'carbon-status'), MANAGER_ROWS)
    queryClient.setQueryData(keys.farms(), MANAGER_ROWS)

    meAnswer = async () => VIEWER
    seenAtFirstRender.length = 0
    await signInAgain()
    await waitFor(() => expect(firstRender('ops').length).toBeGreaterThan(0))
    expect(firstRender('ops')[0].cached).toBeUndefined()
    expect(queryClient.getQueryData(keys.farms())).toBeUndefined()
    expect(clearFarmerCache).toHaveBeenCalled()
  })

  it('same user, Farmer promoted to Manager: the Farmer-scope rows are dropped too', async () => {
    meAnswer = async () => FARMER
    history.replaceState({}, '', '/farmer')
    render(<App />)
    await screen.findByText('farmer-experience')
    queryClient.setQueryData(keys.farms(), [{ id: 'farm-1' }])

    meAnswer = async () => MANAGER
    seenAtFirstRender.length = 0
    await signInAgain()
    await screen.findByText('ops-overview')
    expect(firstRender('farmer')).toEqual([])
    expect(queryClient.getQueryData(keys.farms())).toBeUndefined()
  })

  it('same user and the same confirmed scope: the cache is kept (no needless refetch)', async () => {
    meAnswer = async () => MANAGER
    history.replaceState({}, '', '/dashboard')
    render(<App />)
    await screen.findByText('ops-overview')
    queryClient.setQueryData(keys.org('org-1', 'carbon-status'), MANAGER_ROWS)

    seenAtFirstRender.length = 0
    await signInAgain()
    await waitFor(() => expect(firstRender('ops').length).toBeGreaterThan(0))
    expect(firstRender('ops')[0].cached).toEqual(MANAGER_ROWS)
    expect(clearFarmerCache).not.toHaveBeenCalled()
  })

  it('a change of farm access alone (same role and organisation) also drops the cache', async () => {
    meAnswer = async () => FARMER
    history.replaceState({}, '', '/farmer')
    render(<App />)
    await screen.findByText('farmer-experience')
    queryClient.setQueryData(keys.farms(), [{ id: 'farm-1' }])

    meAnswer = async () => ({ ...FARMER, writableFarmIds: [] })
    seenAtFirstRender.length = 0
    await signInAgain()
    await waitFor(() => expect(firstRender('farmer').length).toBeGreaterThan(0))
    expect(firstRender('farmer')[0].cached).toBeUndefined()
  })
})

describe('nothing from PR #12 starts before the role is confirmed', () => {
  it('while /v1/me is pending: neutral skeleton, no route-data or route-code prefetch, no business page', async () => {
    let resolve: (v: CurrentUser) => void = () => {}
    meAnswer = () => new Promise((r) => { resolve = r })
    history.replaceState({}, '', '/dashboard')
    render(<App />)
    await waitFor(() => expect(getMe).toHaveBeenCalled())
    await act(async () => { await new Promise((r) => setTimeout(r, 30)) })
    expect(screen.getByTestId('viewer-verifying')).toBeTruthy()
    expect(document.querySelector('.shell, .role-chip, nav')).toBeNull()
    // Hovering is impossible without the shell, and nothing prefetches on its own.
    expect(prefetchRouteData).not.toHaveBeenCalled()
    expect(prefetchRoute).not.toHaveBeenCalled()
    expect(seenAtFirstRender).toEqual([])
    resolve(MANAGER)
    await screen.findByText('ops-overview')
  })

  it('the lazy Farmer UI is reached only after /v1/me says Farmer (skeleton, not its Suspense fallback, while pending)', async () => {
    let resolve: (v: CurrentUser) => void = () => {}
    meAnswer = () => new Promise((r) => { resolve = r })
    history.replaceState({}, '', '/farmer')
    render(<App />)
    await waitFor(() => expect(getMe).toHaveBeenCalled())
    await act(async () => { await new Promise((r) => setTimeout(r, 30)) })
    expect(screen.getByTestId('viewer-verifying')).toBeTruthy()
    expect(document.body.textContent).not.toContain('Đang tải…')
    resolve(FARMER)
    await screen.findByText('farmer-experience')
  })
})
