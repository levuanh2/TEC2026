// @vitest-environment jsdom
import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import { useEffect } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from './api/client'
import type { CurrentUser } from './api/me'
import { keys, queryClient } from './query/client'

/* An open tab re-reads /v1/me when it is focused or shown again and after a
 * token refresh, throttled, so a role revoked or changed while the tab stayed
 * open does not keep its old screen and cached rows until a reload.
 * Real query client; Date.now is moved by the test; the business pages count
 * mounts and record what the cache held when they rendered. */

let ended: ((reason: 'expired' | 'signed_out') => void) | null = null
const refreshListeners = new Set<() => void>()
let meAnswer: () => Promise<CurrentUser>
const getMe = vi.fn(() => meAnswer())
const clearViewerHint = vi.fn()
const mounts = { ops: 0, farmer: 0 }
const opsRenders: { org: string | null; cached: unknown }[] = []

vi.mock('./api/auth', () => ({
  onSignOutConfirmed: () => () => {},
  confirmSignOut: async () => false,
  onAuthEnded: (fn: typeof ended) => { ended = fn; return () => { ended = null } },
  onSessionRefreshed: (fn: () => void) => { refreshListeners.add(fn); return () => { refreshListeners.delete(fn) } },
  onSessionReplaced: () => () => {},
  restoreSession: async () => ({ access_token: 't', user: { id: 'u1', email: 'qa@example.test', app_metadata: {} } }),
  signIn: vi.fn(),
  signOut: vi.fn(),
  mustChangePassword: () => false,
}))
vi.mock('./api/me', () => ({ getMe: () => getMe(), readViewerHint: () => null, writeViewerHint: () => {}, clearViewerHint: () => clearViewerHint() }))
vi.mock('./api/organizations', async (orig) => ({
  ...(await orig<object>()),
  getOrganization: async (id: string) => ({ id, name: 'HTX QA' }),
  clearOrganizationCache: () => {},
}))
vi.mock('./farmer/scope', async (orig) => ({ ...(await orig<object>()), prefetchFarmerScope: () => {} }))
vi.mock('./query/prefetch', () => ({ prefetchRouteData: () => {} }))
vi.mock('./api/farms', async (orig) => ({ ...(await orig<object>()), usingMockData: false }))
vi.mock('./farmer/FarmerExperience', () => ({
  FarmerExperience: () => {
    useEffect(() => { mounts.farmer++ }, [])
    return <p>farmer-experience</p>
  },
}))
vi.mock('./pages/operations', () => ({
  OperationsOverview: ({ organizationId }: { organizationId: string | null }) => {
    useEffect(() => { mounts.ops++ }, [])
    opsRenders.push({ org: organizationId, cached: queryClient.getQueryData(keys.org(organizationId ?? '-', 'carbon-status')) })
    return <p>ops-overview {organizationId}</p>
  },
  SeasonsWorkspace: () => <p>seasons-workspace</p>,
}))

const { default: App, REVALIDATE_MIN_INTERVAL_MS } = await import('./App')

const MANAGER: CurrentUser = { role: 'cooperative_manager', organizationId: 'org-1', fullName: 'QA' }
const FARMER: CurrentUser = { role: 'farmer', organizationId: 'org-1', fullName: 'QA', writableFarmIds: ['farm-1'] }
const ROWS = [{ season: 'cached-under-the-manager-role' }]
let now = 1_000_000
const later = () => { now += REVALIDATE_MIN_INTERVAL_MS + 1 }
const focus = () => act(() => { window.dispatchEvent(new Event('focus')) })
const show = () => act(() => {
  Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true })
  document.dispatchEvent(new Event('visibilitychange'))
})
const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 20)) })

async function startAsManager() {
  meAnswer = async () => MANAGER
  history.replaceState({}, '', '/dashboard')
  render(<App />)
  await screen.findByText('ops-overview org-1')
  queryClient.setQueryData(keys.org('org-1', 'carbon-status'), ROWS)
  expect(getMe).toHaveBeenCalledTimes(1)
  // findByText resolves on the DOM commit, possibly before React has run the
  // passive effects that register the focus/visibility listeners: flush them.
  await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
}

beforeEach(() => {
  now = 1_000_000
  vi.spyOn(Date, 'now').mockImplementation(() => now)
  queryClient.clear(); mounts.ops = 0; mounts.farmer = 0; opsRenders.length = 0; refreshListeners.clear()
})
afterEach(() => { cleanup(); ended = null; vi.restoreAllMocks(); getMe.mockClear(); clearViewerHint.mockClear() })

describe('throttling', () => {
  it('a focus within the interval sends nothing; after it, exactly one /v1/me', async () => {
    await startAsManager()
    await focus(); await show(); await settle()
    expect(getMe).toHaveBeenCalledTimes(1)
    later()
    await focus(); await settle()
    expect(getMe).toHaveBeenCalledTimes(2)
  })

  it('a burst of focus + visibility events while a check is in flight sends one request', async () => {
    await startAsManager()
    let resolve: (v: CurrentUser) => void = () => {}
    meAnswer = () => new Promise((r) => { resolve = r })
    later()
    await focus(); await show(); await focus(); await show()
    expect(getMe).toHaveBeenCalledTimes(2)
    resolve(MANAGER); await settle()
  })

  it('nothing is re-checked while the role is still unverified', async () => {
    let resolve: (v: CurrentUser) => void = () => {}
    meAnswer = () => new Promise((r) => { resolve = r })
    history.replaceState({}, '', '/dashboard')
    render(<App />)
    await waitFor(() => expect(getMe).toHaveBeenCalledTimes(1))
    later()
    await focus(); await show(); await settle()
    expect(getMe).toHaveBeenCalledTimes(1)
    resolve(MANAGER)
    await screen.findByText('ops-overview org-1')
  })
})

describe('what a re-check does', () => {
  it('same scope: nothing changes on screen and the cache is kept (no remount)', async () => {
    await startAsManager()
    later(); await focus(); await settle()
    expect(getMe).toHaveBeenCalledTimes(2)
    expect(mounts.ops).toBe(1)
    expect(queryClient.getQueryData(keys.org('org-1', 'carbon-status'))).toEqual(ROWS)
  })

  it('revoked (403): neutral unverified screen, business UI gone, cache and hint dropped', async () => {
    await startAsManager()
    meAnswer = () => Promise.reject(new ApiError(403, 'forbidden', 'HTTP 403'))
    later(); await focus(); await settle()
    expect(screen.getByTestId('viewer-unverified')).toBeTruthy()
    expect(screen.queryByText(/ops-overview/)).toBeNull()
    expect(document.querySelector('.shell, .role-chip')).toBeNull()
    expect(queryClient.getQueryData(keys.org('org-1', 'carbon-status'))).toBeUndefined()
    expect(clearViewerHint).toHaveBeenCalled()
  })

  it('role changed to Farmer (same user and organisation): caches dropped, Farmer UI, the Manager page is not rendered again', async () => {
    await startAsManager()
    const rendersBefore = opsRenders.length
    meAnswer = async () => FARMER
    later(); await focus(); await settle()
    expect(await screen.findByText('farmer-experience')).toBeTruthy()
    expect(location.pathname).toBe('/farmer')
    expect(opsRenders.length).toBe(rendersBefore)
    expect(queryClient.getQueryData(keys.org('org-1', 'carbon-status'))).toBeUndefined()
  })

  it('organisation changed: the business tree remounts and never renders the old rows', async () => {
    await startAsManager()
    meAnswer = async () => ({ ...MANAGER, organizationId: 'org-2' })
    later(); await focus(); await settle()
    expect(await screen.findByText('ops-overview org-2')).toBeTruthy()
    expect(mounts.ops).toBe(2)
    const afterSwitch = opsRenders.filter((r) => r.org === 'org-2')
    expect(afterSwitch.every((r) => r.cached === undefined)).toBe(true)
    expect(queryClient.getQueryData(keys.org('org-1', 'carbon-status'))).toBeUndefined()
  })

  it('farm scope changed (a writable farm added): caches dropped and the tree remounts; the same farms reordered change nothing', async () => {
    meAnswer = async () => FARMER
    history.replaceState({}, '', '/farmer')
    render(<App />)
    await screen.findByText('farmer-experience')
    await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
    queryClient.setQueryData(keys.org('org-1', 'carbon-status'), ROWS)
    expect(mounts.farmer).toBe(1)

    meAnswer = async () => ({ ...FARMER, writableFarmIds: ['farm-1', 'farm-2'] })
    later(); await focus(); await settle()
    await waitFor(() => expect(mounts.farmer).toBe(2))
    expect(queryClient.getQueryData(keys.org('org-1', 'carbon-status'))).toBeUndefined()

    queryClient.setQueryData(keys.org('org-1', 'carbon-status'), ROWS)
    meAnswer = async () => ({ ...FARMER, writableFarmIds: ['farm-2', 'farm-1'] })
    later(); await focus(); await settle()
    expect(getMe).toHaveBeenCalledTimes(3)
    expect(mounts.farmer).toBe(2)
    expect(queryClient.getQueryData(keys.org('org-1', 'carbon-status'))).toEqual(ROWS)
  })

  it.each([
    ['network error', () => Promise.reject(new ApiError(0, 'offline', 'offline'))],
    ['500', () => Promise.reject(new ApiError(500, 'internal_error', 'HTTP 500'))],
    ['503', () => Promise.reject(new ApiError(503, 'unavailable', 'HTTP 503'))],
  ])('%s: no role is inferred, the screen and cache stay, the next focus tries again', async (_label, fail) => {
    await startAsManager()
    meAnswer = fail as () => Promise<CurrentUser>
    later(); await focus(); await settle()
    expect(screen.getByText('ops-overview org-1')).toBeTruthy()
    expect(screen.queryByTestId('viewer-unverified')).toBeNull()
    expect(queryClient.getQueryData(keys.org('org-1', 'carbon-status'))).toEqual(ROWS)
    meAnswer = async () => FARMER
    later(); await focus(); await settle()
    expect(await screen.findByText('farmer-experience')).toBeTruthy()
  })

  it('a token refresh triggers the re-check too (same throttle)', async () => {
    await startAsManager()
    meAnswer = async () => FARMER
    act(() => { for (const fn of refreshListeners) fn() })
    await settle()
    expect(getMe).toHaveBeenCalledTimes(1)
    later()
    act(() => { for (const fn of refreshListeners) fn() })
    expect(await screen.findByText('farmer-experience')).toBeTruthy()
  })

  it('a 401 that ends the session goes to login, not to the unverified screen', async () => {
    await startAsManager()
    meAnswer = () => { ended!('expired'); return Promise.reject(new ApiError(401, 'session_expired', 'expired')) }
    later(); await focus(); await settle()
    expect(location.pathname + location.search).toBe('/login?next=%2Fdashboard')
    expect(screen.queryByTestId('viewer-unverified')).toBeNull()
    expect(screen.queryByText(/ops-overview/)).toBeNull()
  })
})
