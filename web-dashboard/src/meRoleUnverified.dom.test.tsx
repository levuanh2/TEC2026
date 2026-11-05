// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from './api/client'
import type { CurrentUser } from './api/me'

/* Regression (real-browser QA 2026-11-04): when /v1/me failed, App set the
 * viewer to role "farmer" and redirected, so a Manager landed in the Farmer
 * UI. The role is whatever the backend says; until it has said, no business
 * screen renders — a neutral error with "Thử lại", the URL left alone.
 *
 * Decision 2026-11-05: the cached role hint no longer paints anything either.
 * While the session is restored and /v1/me is pending the screen is a neutral
 * skeleton, and only the role/organisation /v1/me just confirmed open a shell.
 * The business screens below count their renders, so "never rendered" is
 * asserted, not just "not on screen at the end". */

let ended: ((reason: 'expired' | 'signed_out') => void) | null = null
const signOut = vi.fn(async () => {})
type FakeSession = { access_token: string; user: { id: string; email: string; app_metadata: object } }
const SESSION_A: FakeSession = { access_token: 't', user: { id: 'u1', email: 'manager@example.test', app_metadata: {} } }
const SESSION_B: FakeSession = { access_token: 't2', user: { id: 'u2', email: 'farmer@example.test', app_metadata: {} } }
const signIn = vi.fn(async (): Promise<FakeSession> => SESSION_B)
let meAnswer: () => Promise<CurrentUser>
let hint: CurrentUser | null = null
const getMe = vi.fn(() => meAnswer())
const clearViewerHint = vi.fn()
const prefetchFarmerScope = vi.fn()
const clearFarmerCache = vi.fn()
const clearOrganizationCache = vi.fn()
const renders = { farmer: 0, ops: 0, seasons: 0, mrv: 0 }

vi.mock('./api/auth', () => ({
  onAuthEnded: (fn: typeof ended) => { ended = fn; return () => { ended = null } },
  onSessionRefreshed: () => () => {},
  restoreSession: async () => SESSION_A,
  signIn: () => signIn(),
  signOut: () => signOut(),
  mustChangePassword: () => false,
}))
vi.mock('./api/me', () => ({
  getMe: () => getMe(),
  readViewerHint: () => hint,
  writeViewerHint: () => {},
  clearViewerHint: () => clearViewerHint(),
}))
vi.mock('./api/organizations', () => ({
  getOrganization: async (id: string) => ({ id, name: id === 'org-2' ? 'HTX Hai' : 'HTX Một' }),
  clearOrganizationCache: () => clearOrganizationCache(),
}))
vi.mock('./farmer/data', async (orig) => ({ ...(await orig<object>()), clearFarmerCache: () => clearFarmerCache() }))
vi.mock('./farmer/scope', async (orig) => ({ ...(await orig<object>()), prefetchFarmerScope: () => prefetchFarmerScope() }))
vi.mock('./api/farms', async (orig) => ({ ...(await orig<object>()), usingMockData: false }))
vi.mock('./farmer/FarmerExperience', () => ({
  FarmerExperience: ({ viewer }: { viewer: CurrentUser }) => { renders.farmer++; return <p>farmer-experience {viewer.organizationId}</p> },
}))
vi.mock('./pages/operations', () => ({
  OperationsOverview: ({ organizationId }: { organizationId: string | null }) => { renders.ops++; return <p>ops-overview {organizationId}</p> },
  SeasonsWorkspace: () => { renders.seasons++; return <p>seasons-workspace</p> },
}))
vi.mock('./pages/mrv', () => ({ MrvPage: () => { renders.mrv++; return <p>mrv-page</p> } }))

const { default: App } = await import('./App')

const MANAGER: CurrentUser = { role: 'cooperative_manager', organizationId: 'org-1', fullName: 'Quản lý' }
const FARMER: CurrentUser = { role: 'farmer', organizationId: 'org-1', fullName: 'Nông hộ', writableFarmIds: ['farm-1'] }
const offline = () => Promise.reject(new ApiError(0, 'offline', 'Không thể kết nối FastAPI.'))
const http = (status: number) => () => Promise.reject(new ApiError(status, 'x', `HTTP ${status}`))
const at = (path: string) => history.replaceState({}, '', path)
const businessScreens = () => ['farmer-experience', 'ops-overview', 'seasons-workspace', 'mrv-page']
  .filter((t) => document.body.textContent?.includes(t))
const businessRenders = () => renders.farmer + renders.ops + renders.seasons + renders.mrv
const resetRenders = () => { renders.farmer = 0; renders.ops = 0; renders.seasons = 0; renders.mrv = 0 }
/** /v1/me that answers only when the test says so. */
function pendingMe() {
  let resolve: (v: CurrentUser) => void = () => {}
  let reject: (e: unknown) => void = () => {}
  meAnswer = () => new Promise<CurrentUser>((res, rej) => { resolve = res; reject = rej })
  return { resolve: (v: CurrentUser) => resolve(v), reject: (e: unknown) => reject(e) }
}
/** Let React flush effects and settled promises without /v1/me answering. */
const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 30)) })
/** The neutral skeleton: no role label, no navigation, no business screen. */
function expectNeutralSkeleton() {
  const box = screen.getByTestId('viewer-verifying')
  expect(box.textContent).not.toMatch(/Nông hộ|Quản lý HTX|Doanh nghiệp|Cơ quan quản lý/)
  expect(document.querySelector('nav, aside, .sidebar, .role-chip')).toBeNull()
  expect(businessScreens()).toEqual([])
}
/** End the current session and sign in again through the login form. */
async function signInAgain(next: FakeSession) {
  act(() => ended!('expired'))
  await waitFor(() => expect(location.pathname).toBe('/login'))
  signIn.mockResolvedValueOnce(next)
  fireEvent.change(screen.getByLabelText('Email'), { target: { value: next.user.email } })
  fireEvent.change(screen.getByLabelText('Mật khẩu'), { target: { value: 'x' } })
  fireEvent.submit(screen.getByLabelText('Email').closest('form')!)
}

beforeEach(() => { hint = null; meAnswer = async () => MANAGER; resetRenders() })
afterEach(() => {
  cleanup(); ended = null
  for (const fn of [getMe, clearViewerHint, signOut, signIn, prefetchFarmerScope, clearFarmerCache, clearOrganizationCache]) fn.mockClear()
})

describe('/v1/me decides the role; a failed read never picks one', () => {
  it('Manager: /v1/me answers -> Management shell', async () => {
    at('/dashboard')
    render(<App />)
    expect(await screen.findByText('ops-overview org-1')).toBeTruthy()
    expect(location.pathname).toBe('/dashboard')
    expect(renders.farmer).toBe(0)
  })

  it('Farmer: /v1/me answers -> Farmer UI', async () => {
    meAnswer = async () => FARMER
    at('/farmer')
    render(<App />)
    expect(await screen.findByText('farmer-experience org-1')).toBeTruthy()
    expect(renders.ops + renders.mrv + renders.seasons).toBe(0)
  })

  it('network error: neutral error, no business screen, no redirect to /farmer; retry recovers', async () => {
    meAnswer = offline
    at('/mrv')
    render(<App />)
    const box = await screen.findByTestId('viewer-unverified')
    expect(box.textContent).toContain('Không kết nối được máy chủ')
    expect(box.textContent).not.toMatch(/Nông hộ|Quản lý HTX/)
    expect(businessScreens()).toEqual([])
    expect(businessRenders()).toBe(0)
    expect(location.pathname).toBe('/mrv')
    expect(clearViewerHint).not.toHaveBeenCalled()

    meAnswer = async () => MANAGER
    fireEvent.click(screen.getByRole('button', { name: 'Thử lại' }))
    expect(await screen.findByText('mrv-page')).toBeTruthy()
    expect(location.pathname).toBe('/mrv')
    expect(getMe).toHaveBeenCalledTimes(2)
  })

  it('500 then the server recovers: retry shows the role the server now confirms', async () => {
    meAnswer = http(500)
    at('/farmer/journal')
    render(<App />)
    expect((await screen.findByTestId('viewer-unverified')).textContent).toContain('mã 500')
    expect(businessRenders()).toBe(0)
    meAnswer = async () => FARMER
    fireEvent.click(screen.getByRole('button', { name: 'Thử lại' }))
    expect(await screen.findByText('farmer-experience org-1')).toBeTruthy()
    expect(renders.ops).toBe(0)
  })

  it('Manager with a cached hint: a failed revalidation shows the error, never the shell', async () => {
    hint = MANAGER
    meAnswer = http(500)
    at('/dashboard')
    render(<App />)
    const box = await screen.findByTestId('viewer-unverified')
    expect(box.textContent).toContain('mã 500')
    expect(businessScreens()).toEqual([])
    expect(businessRenders()).toBe(0)
    expect(location.pathname).toBe('/dashboard')
  })

  it('Farmer with a cached hint: same — the Farmer UI is not opened on an unverified role', async () => {
    hint = FARMER
    meAnswer = offline
    at('/farmer/journal')
    render(<App />)
    await screen.findByTestId('viewer-unverified')
    expect(businessScreens()).toEqual([])
    expect(businessRenders()).toBe(0)
    expect(location.pathname).toBe('/farmer/journal')
  })

  it('retry shows the neutral skeleton, not a cached shell, until the server answers', async () => {
    hint = MANAGER
    meAnswer = offline
    at('/dashboard')
    render(<App />)
    await screen.findByTestId('viewer-unverified')
    const me = pendingMe()
    fireEvent.click(screen.getByRole('button', { name: 'Thử lại' }))
    await waitFor(() => expect(getMe).toHaveBeenCalledTimes(2))
    await settle()
    expectNeutralSkeleton()
    expect(businessRenders()).toBe(0)
    me.resolve(MANAGER)
    expect(await screen.findByText('ops-overview org-1')).toBeTruthy()
  })

  it('403: error, the cached hint is dropped, no business screen', async () => {
    hint = MANAGER
    meAnswer = http(403)
    at('/dashboard')
    render(<App />)
    const box = await screen.findByTestId('viewer-unverified')
    expect(box.textContent).toContain('từ chối')
    expect(clearViewerHint).toHaveBeenCalled()
    expect(businessScreens()).toEqual([])
    expect(businessRenders()).toBe(0)
  })

  it('401 that did not end the session: error with "Đăng nhập lại", hint dropped', async () => {
    hint = FARMER
    meAnswer = http(401)
    at('/dashboard')
    render(<App />)
    const box = await screen.findByTestId('viewer-unverified')
    expect(clearViewerHint).toHaveBeenCalled()
    expect(businessScreens()).toEqual([])
    expect(businessRenders()).toBe(0)
    fireEvent.click(screen.getByRole('button', { name: 'Đăng nhập lại' }))
    expect(signOut).toHaveBeenCalled()
    expect(box).toBeTruthy()
  })

  it('session expiry while /v1/me is in flight: login with next=, not the error screen', async () => {
    const me = pendingMe()
    at('/dashboard')
    render(<App />)
    await waitFor(() => expect(getMe).toHaveBeenCalled())
    ended!('expired')
    me.reject(new ApiError(401, 'session_expired', 'expired'))
    await waitFor(() => expect(document.body.textContent).toContain('Đăng nhập lại'))
    expect(screen.queryByTestId('viewer-unverified')).toBeNull()
    expect(location.pathname + location.search).toBe('/login?next=%2Fdashboard')
    expect(businessRenders()).toBe(0)
  })
})

describe('the cached role hint never opens a business screen', () => {
  it.each([
    ['Manager', MANAGER, '/dashboard'],
    ['Farmer', FARMER, '/farmer/journal'],
  ])('%s with a cached hint while /v1/me is pending: neutral skeleton only', async (_label, cached, path) => {
    hint = cached
    const me = pendingMe()
    at(path)
    render(<App />)
    await waitFor(() => expect(getMe).toHaveBeenCalled())
    await settle()
    expectNeutralSkeleton()
    expect(screen.getByTestId('viewer-verifying').textContent).toContain('Đang xác minh quyền tài khoản')
    expect(businessRenders()).toBe(0)
    expect(location.pathname).toBe(path)
    me.resolve(cached)
    await waitFor(() => expect(businessRenders()).toBeGreaterThan(0))
  })

  it('no hint while /v1/me is pending: the same neutral skeleton', async () => {
    const me = pendingMe()
    at('/dashboard')
    render(<App />)
    await waitFor(() => expect(getMe).toHaveBeenCalled())
    await settle()
    expectNeutralSkeleton()
    me.resolve(MANAGER)
    expect(await screen.findByText('ops-overview org-1')).toBeTruthy()
  })

  it('cached Manager whose access was revoked (server now says Farmer): the Management shell never renders', async () => {
    hint = MANAGER
    meAnswer = async () => FARMER
    at('/dashboard')
    render(<App />)
    expect(await screen.findByText('farmer-experience org-1')).toBeTruthy()
    expect(renders.ops + renders.seasons + renders.mrv).toBe(0)
    expect(location.pathname).toBe('/farmer')
  })

  it('cached Farmer promoted to Manager: the Farmer UI never renders, the Management shell does', async () => {
    hint = FARMER
    meAnswer = async () => MANAGER
    at('/farmer/journal')
    render(<App />)
    expect(await screen.findByText('ops-overview org-1')).toBeTruthy()
    expect(renders.farmer).toBe(0)
    expect(location.pathname).toBe('/dashboard')
  })

  it('the hint only steers the Farmer prefetch (a network read with no authority)', async () => {
    hint = MANAGER
    const me = pendingMe()
    at('/dashboard')
    render(<App />)
    await waitFor(() => expect(getMe).toHaveBeenCalled())
    expect(prefetchFarmerScope).not.toHaveBeenCalled()
    me.resolve(MANAGER)
    await screen.findByText('ops-overview org-1')
  })
})

describe('a changed scope never shows the previous scope', () => {
  it('session ends, a different account signs in: skeleton while verifying, caches dropped before the new shell', async () => {
    at('/dashboard')
    render(<App />)
    expect(await screen.findByText('ops-overview org-1')).toBeTruthy()

    const me = pendingMe()
    clearFarmerCache.mockClear(); clearOrganizationCache.mockClear()
    resetRenders()
    await signInAgain(SESSION_B)
    await waitFor(() => expect(getMe).toHaveBeenCalledTimes(2))
    await settle()
    // Session B is unverified: nothing of session A's Manager scope renders,
    // and no Farmer UI is guessed for B either (the login returned to
    // /dashboard via next=, where the old code painted a default shell).
    expectNeutralSkeleton()
    expect(businessRenders()).toBe(0)

    me.resolve({ ...FARMER, organizationId: 'org-2' })
    expect(await screen.findByText('farmer-experience org-2')).toBeTruthy()
    expect(renders.ops).toBe(0)
    expect(clearFarmerCache).toHaveBeenCalled()
    expect(clearOrganizationCache).toHaveBeenCalled()
  })

  it('same account and scope after signing in again: caches are not dropped by the shell', async () => {
    at('/dashboard')
    render(<App />)
    await screen.findByText('ops-overview org-1')
    await signInAgain({ ...SESSION_A, access_token: 't3' })
    await waitFor(() => expect(getMe).toHaveBeenCalledTimes(2))
    expect(await screen.findByText('ops-overview org-1')).toBeTruthy()
    expect(clearFarmerCache).not.toHaveBeenCalled()
    expect(clearOrganizationCache).not.toHaveBeenCalled()
  })
})
