// @vitest-environment jsdom
import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import { useEffect } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from './api/client'
import type { CurrentUser } from './api/me'
import { keys, queryClient } from './query/client'
import { clearFarmerCache, fetchQuery, peekQuery } from './farmer/data'

/* PR #17 review findings, each a regression test:
 *  1. Another tab of the same browser signs a DIFFERENT person in (Supabase
 *     shares the stored session and token across tabs): this tab must switch to
 *     that session and verify it from the neutral skeleton, never show the new
 *     person's data under the old person's role or cache.
 *  2. A re-check whose /v1/me answers for another user id than this tab's
 *     session is treated the same way.
 *  3. A hung re-check must not switch re-checking off for good.
 *  4. A farmer-cache request started before a clear must not write its (old
 *     scope) answer into the cleared cache when it settles.
 *  5. A re-check still in flight when the session ends, is replaced by another
 *     person's, or has its token refreshed: its late answer is either ignored
 *     (old session) or applied once (same session), never twice and never to
 *     another person; a Management read in flight when the scope changes never
 *     lands in the new cache. */

let ended: ((reason: 'expired' | 'signed_out') => void) | null = null
let replace: ((s: unknown) => void) | null = null
let refreshed: (() => void) | null = null
const A = { access_token: 'tA', user: { id: 'user-a', email: 'a@example.test', app_metadata: {} } }
const B = { access_token: 'tB', user: { id: 'user-b', email: 'b@example.test', app_metadata: {} } }
let stored: typeof A = A
const restoreSession = vi.fn(async () => stored)
let meAnswer: () => Promise<CurrentUser>
const getMe = vi.fn(() => meAnswer())
const renders: { page: string; email: string | null }[] = []

vi.mock('./api/auth', () => ({
  onAuthEnded: (fn: typeof ended) => { ended = fn; return () => { ended = null } },
  onSessionRefreshed: (fn: () => void) => { refreshed = fn; return () => { refreshed = null } },
  onSessionReplaced: (fn: typeof replace) => { replace = fn; return () => { replace = null } },
  restoreSession: () => restoreSession(),
  signIn: vi.fn(),
  signOut: vi.fn(),
  mustChangePassword: () => false,
}))
vi.mock('./api/me', () => ({ getMe: () => getMe(), readViewerHint: () => null, writeViewerHint: () => {}, clearViewerHint: () => {} }))
vi.mock('./api/organizations', async (orig) => ({ ...(await orig<object>()), getOrganization: async (id: string) => ({ id, name: 'HTX QA' }), clearOrganizationCache: () => {} }))
vi.mock('./farmer/scope', async (orig) => ({ ...(await orig<object>()), prefetchFarmerScope: () => {} }))
vi.mock('./query/prefetch', () => ({ prefetchRouteData: () => {} }))
vi.mock('./api/farms', async (orig) => ({ ...(await orig<object>()), usingMockData: false }))
vi.mock('./farmer/FarmerExperience', () => ({
  FarmerExperience: ({ session }: { session: { user: { email: string } } | null }) => {
    useEffect(() => { renders.push({ page: 'farmer', email: session?.user.email ?? null }) })
    return <p>farmer-experience {session?.user.email}</p>
  },
}))
vi.mock('./pages/operations', () => ({
  OperationsOverview: () => { renders.push({ page: 'ops', email: null }); return <p>ops-overview</p> },
  SeasonsWorkspace: () => <p>seasons</p>,
}))

const { default: App, REVALIDATE_MIN_INTERVAL_MS, REVALIDATE_STALE_MS } = await import('./App')
const MANAGER_A: CurrentUser = { role: 'cooperative_manager', organizationId: 'org-1', fullName: 'A', userId: 'user-a' }
const FARMER_B: CurrentUser = { role: 'farmer', organizationId: 'org-1', fullName: 'B', userId: 'user-b', writableFarmIds: ['farm-1'] }
let now = 5_000_000
const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 20)) })
const focus = () => act(() => { window.dispatchEvent(new Event('focus')) })

async function startAsManagerA() {
  meAnswer = async () => MANAGER_A
  history.replaceState({}, '', '/dashboard')
  render(<App />)
  await screen.findByText('ops-overview')
  queryClient.setQueryData(keys.org('org-1', 'carbon-status'), [{ only: 'manager A may see this' }])
  // findByText resolves on the DOM commit, possibly before React has run the
  // passive effects that register the focus/visibility listeners: flush them.
  await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
}

beforeEach(() => {
  now = 5_000_000; vi.spyOn(Date, 'now').mockImplementation(() => now)
  stored = A; renders.length = 0; queryClient.clear()
})
afterEach(() => { cleanup(); ended = null; replace = null; refreshed = null; vi.restoreAllMocks(); getMe.mockClear(); restoreSession.mockClear() })

describe('another person signed in from another tab', () => {
  it('the tab switches to that session through the skeleton; nothing of A is shown with B', async () => {
    await startAsManagerA()
    let resolve: (v: CurrentUser) => void = () => {}
    meAnswer = () => new Promise((r) => { resolve = r })
    renders.length = 0
    act(() => replace!(B))
    await settle()
    expect(screen.getByTestId('viewer-verifying')).toBeTruthy()
    expect(document.querySelector('.shell, .role-chip')).toBeNull()
    expect(renders).toEqual([])
    expect(queryClient.getQueryData(keys.org('org-1', 'carbon-status'))).toBeUndefined()
    resolve(FARMER_B)
    expect(await screen.findByText('farmer-experience b@example.test')).toBeTruthy()
    expect(renders.every((r) => r.email === 'b@example.test')).toBe(true)
    expect(location.pathname).toBe('/farmer')
  })
})

describe('a re-check that answers for another user id', () => {
  it('drops the caches and re-verifies with the stored session instead of re-labelling A with B\'s data', async () => {
    await startAsManagerA()
    stored = B
    meAnswer = async () => FARMER_B
    now += REVALIDATE_MIN_INTERVAL_MS + 1
    await focus(); await settle()
    expect(restoreSession).toHaveBeenCalledTimes(2)
    expect(queryClient.getQueryData(keys.org('org-1', 'carbon-status'))).toBeUndefined()
    expect(await screen.findByText('farmer-experience b@example.test')).toBeTruthy()
    expect(screen.queryByText(/a@example.test/)).toBeNull()
  })
})

describe('a hung re-check', () => {
  it('stops blocking after REVALIDATE_STALE_MS, so the next focus checks again', async () => {
    await startAsManagerA()
    meAnswer = () => new Promise(() => {})   // never answers
    now += REVALIDATE_MIN_INTERVAL_MS + 1
    await focus()
    expect(getMe).toHaveBeenCalledTimes(2)
    now += REVALIDATE_MIN_INTERVAL_MS + 1    // past the interval but the first is still "in flight" (< stale)
    expect(REVALIDATE_MIN_INTERVAL_MS).toBeGreaterThan(REVALIDATE_STALE_MS)
    meAnswer = async () => MANAGER_A
    await focus(); await settle()
    expect(getMe).toHaveBeenCalledTimes(3)
  })
})

describe('farmer cache and requests in flight', () => {
  it('a request started before a clear does not write its answer into the cleared cache', async () => {
    let resolveOld: (v: unknown) => void = () => {}
    const pending = fetchQuery('farmer:scope', () => new Promise((r) => { resolveOld = r }))
    clearFarmerCache()
    resolveOld({ farms: ['farm-of-the-previous-scope'] })
    await pending
    expect(peekQuery('farmer:scope')).toBeUndefined()
    // A request started after the clear is cached normally.
    await fetchQuery('farmer:scope', async () => ({ farms: ['current'] }))
    expect(peekQuery('farmer:scope')).toEqual({ farms: ['current'] })
    await waitFor(() => expect(true).toBe(true))
  })
})

describe('a re-check still in flight', () => {
  const FARMER_A: CurrentUser = { role: 'farmer', organizationId: 'org-1', fullName: 'A', userId: 'user-a', writableFarmIds: [] }
  /** /v1/me answers in call order; a `pending` slot is resolved by the test. */
  function meQueue(...answers: (CurrentUser | 'pending')[]) {
    const late: { resolve: (v: CurrentUser) => void } = { resolve: () => {} }
    meAnswer = () => {
      const next = answers.shift() ?? MANAGER_A
      return next === 'pending' ? new Promise((r) => { late.resolve = r }) : Promise.resolve(next)
    }
    return late
  }

  it('sign-out while it is pending: the late answer (a new role) changes nothing, login stays', async () => {
    await startAsManagerA()
    const late = meQueue('pending')
    now += REVALIDATE_MIN_INTERVAL_MS + 1
    await focus()
    expect(getMe).toHaveBeenCalledTimes(2)
    act(() => ended!('signed_out'))
    await settle()
    expect(location.pathname).toBe('/login')
    renders.length = 0
    late.resolve(FARMER_A)
    await settle()
    expect(location.pathname).toBe('/login')
    expect(renders).toEqual([])
    expect(screen.queryByText(/farmer-experience|ops-overview/)).toBeNull()
    // The late answer ran no re-labelling: no viewer state, no new cache entry
    // (the seeded entry is the only one; auth.ts, mocked here, clears it on a
    // real sign-out).
    expect(queryClient.getQueryCache().getAll().map((q) => q.queryKey)).toEqual([keys.org('org-1', 'carbon-status')])
  })

  it("another person signs in from another tab while it is pending: A's late answer is ignored, B keeps B's role", async () => {
    await startAsManagerA()
    const late = meQueue('pending', FARMER_B)
    now += REVALIDATE_MIN_INTERVAL_MS + 1
    await focus()
    act(() => replace!(B))
    expect(await screen.findByText('farmer-experience b@example.test')).toBeTruthy()
    expect(getMe).toHaveBeenCalledTimes(3)
    renders.length = 0
    // A's re-check answers last, with a changed scope for A.
    late.resolve({ ...MANAGER_A, organizationId: 'org-2' })
    await settle()
    expect(screen.getByText('farmer-experience b@example.test')).toBeTruthy()
    expect(screen.queryByText('ops-overview')).toBeNull()
    expect(location.pathname).toBe('/farmer')
    expect(renders.every((r) => r.email === 'b@example.test')).toBe(true)
  })

  it("B took over while A's re-check was pending: A's late 403 does not send B back to the verifying screen", async () => {
    await startAsManagerA()
    let rejectLate: (e: unknown) => void = () => {}
    const answers: (() => Promise<CurrentUser>)[] = [() => new Promise<CurrentUser>((_r, reject) => { rejectLate = reject })]
    meAnswer = () => (answers.shift() ?? (async () => FARMER_B))()
    now += REVALIDATE_MIN_INTERVAL_MS + 1
    await focus()
    act(() => replace!(B))
    expect(await screen.findByText('farmer-experience b@example.test')).toBeTruthy()
    // A's re-check fails last, with a decision (403) that was about A.
    rejectLate(new ApiError(403, 'forbidden', 'HTTP 403'))
    await settle()
    expect(screen.getByText('farmer-experience b@example.test')).toBeTruthy()
    expect(screen.queryByTestId('viewer-verifying')).toBeNull()
    expect(screen.queryByTestId('viewer-unverified')).toBeNull()
  })

  it('a token refresh while it is pending sends no second /v1/me; the answer is applied once', async () => {
    await startAsManagerA()
    const late = meQueue('pending')
    now += REVALIDATE_MIN_INTERVAL_MS + 1
    await focus()
    act(() => refreshed!())
    act(() => refreshed!())
    expect(getMe).toHaveBeenCalledTimes(2)
    late.resolve(FARMER_A)
    expect(await screen.findByText('farmer-experience a@example.test')).toBeTruthy()
    expect(queryClient.getQueryData(keys.org('org-1', 'carbon-status'))).toBeUndefined()
    expect(location.pathname).toBe('/farmer')
    expect(getMe).toHaveBeenCalledTimes(2)
  })

  it('a Management read in flight when the scope changes never lands in the new cache', async () => {
    await startAsManagerA()
    let resolveRead: (v: unknown) => void = () => {}
    const key = keys.org('org-1', 'farms')
    const read = queryClient.fetchQuery({ queryKey: key, queryFn: () => new Promise((r) => { resolveRead = r }) }).catch(() => 'cancelled')
    meQueue(FARMER_A)
    now += REVALIDATE_MIN_INTERVAL_MS + 1
    await focus(); await settle()
    expect(await screen.findByText('farmer-experience a@example.test')).toBeTruthy()
    resolveRead([{ farm: 'read under the manager role' }])
    await read
    await settle()
    expect(queryClient.getQueryData(key)).toBeUndefined()
  })
})
