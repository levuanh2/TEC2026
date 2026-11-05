// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from './api/client'
import type { CurrentUser } from './api/me'

/* Regression (real-browser QA 2026-11-04): when /v1/me failed, App set the
 * viewer to role "farmer" and redirected, so a Manager landed in the Farmer
 * UI. The role is whatever the backend says; until it has said, no business
 * screen renders — a neutral error with "Thử lại", the URL left alone. */

let ended: ((reason: 'expired' | 'signed_out') => void) | null = null
const signOut = vi.fn(async () => {})
let meAnswer: () => Promise<CurrentUser>
let hint: CurrentUser | null = null
const getMe = vi.fn(() => meAnswer())
const clearViewerHint = vi.fn()

vi.mock('./api/auth', () => ({
  onAuthEnded: (fn: typeof ended) => { ended = fn; return () => { ended = null } },
  restoreSession: async () => ({ access_token: 't', user: { id: 'u1', email: 'manager@example.test', app_metadata: {} } }),
  signIn: vi.fn(),
  signOut: () => signOut(),
  mustChangePassword: () => false,
}))
vi.mock('./api/me', () => ({
  getMe: () => getMe(),
  readViewerHint: () => hint,
  writeViewerHint: () => {},
  clearViewerHint: () => clearViewerHint(),
}))
vi.mock('./api/organizations', () => ({ getOrganization: async () => ({ id: 'org-1', name: 'HTX Một' }) }))
vi.mock('./farmer/scope', async (orig) => ({ ...(await orig<object>()), prefetchFarmerScope: () => {} }))
vi.mock('./api/farms', async (orig) => ({ ...(await orig<object>()), usingMockData: false }))
vi.mock('./farmer/FarmerExperience', () => ({ FarmerExperience: () => <p>farmer-experience</p> }))
vi.mock('./pages/operations', () => ({
  OperationsOverview: () => <p>ops-overview</p>,
  SeasonsWorkspace: () => <p>seasons-workspace</p>,
}))
vi.mock('./pages/mrv', () => ({ MrvPage: () => <p>mrv-page</p> }))

const { default: App } = await import('./App')

const MANAGER: CurrentUser = { role: 'cooperative_manager', organizationId: 'org-1', fullName: 'Quản lý' }
const FARMER: CurrentUser = { role: 'farmer', organizationId: 'org-1', fullName: 'Nông hộ', writableFarmIds: ['farm-1'] }
const offline = () => Promise.reject(new ApiError(0, 'offline', 'Không thể kết nối FastAPI.'))
const http = (status: number) => () => Promise.reject(new ApiError(status, 'x', `HTTP ${status}`))
const at = (path: string) => history.replaceState({}, '', path)
const businessScreens = () => ['farmer-experience', 'ops-overview', 'seasons-workspace', 'mrv-page']
  .filter((t) => document.body.textContent?.includes(t))

beforeEach(() => { hint = null; meAnswer = async () => MANAGER })
afterEach(() => { cleanup(); ended = null; getMe.mockClear(); clearViewerHint.mockClear(); signOut.mockClear() })

describe('/v1/me decides the role; a failed read never picks one', () => {
  it('Manager: /v1/me answers -> Management shell', async () => {
    at('/dashboard')
    render(<App />)
    expect(await screen.findByText('ops-overview')).toBeTruthy()
    expect(location.pathname).toBe('/dashboard')
  })

  it('Farmer: /v1/me answers -> Farmer UI', async () => {
    meAnswer = async () => FARMER
    at('/farmer')
    render(<App />)
    expect(await screen.findByText('farmer-experience')).toBeTruthy()
  })

  it('network error: neutral error, no business screen, no redirect to /farmer; retry recovers', async () => {
    meAnswer = offline
    at('/mrv')
    render(<App />)
    const box = await screen.findByTestId('viewer-unverified')
    expect(box.textContent).toContain('Không kết nối được máy chủ')
    expect(box.textContent).not.toMatch(/Nông hộ|Quản lý HTX/)
    expect(businessScreens()).toEqual([])
    expect(location.pathname).toBe('/mrv')
    expect(clearViewerHint).not.toHaveBeenCalled()

    meAnswer = async () => MANAGER
    fireEvent.click(screen.getByRole('button', { name: 'Thử lại' }))
    expect(await screen.findByText('mrv-page')).toBeTruthy()
    expect(location.pathname).toBe('/mrv')
    expect(getMe).toHaveBeenCalledTimes(2)
  })

  it('Manager with a cached hint: a failed revalidation replaces the shell with the error', async () => {
    hint = MANAGER
    meAnswer = http(500)
    at('/dashboard')
    render(<App />)
    const box = await screen.findByTestId('viewer-unverified')
    expect(box.textContent).toContain('mã 500')
    expect(businessScreens()).toEqual([])
    expect(location.pathname).toBe('/dashboard')
  })

  it('Farmer with a cached hint: same — the Farmer UI is not kept on an unverified role', async () => {
    hint = FARMER
    meAnswer = offline
    at('/farmer/journal')
    render(<App />)
    await screen.findByTestId('viewer-unverified')
    expect(businessScreens()).toEqual([])
    expect(location.pathname).toBe('/farmer/journal')
  })

  it('retry does not repaint the cached shell before the server answers', async () => {
    hint = MANAGER
    meAnswer = offline
    at('/dashboard')
    render(<App />)
    await screen.findByTestId('viewer-unverified')
    let resolveMe: (v: CurrentUser) => void = () => {}
    meAnswer = () => new Promise((r) => { resolveMe = r })
    fireEvent.click(screen.getByRole('button', { name: 'Thử lại' }))
    await waitFor(() => expect(getMe).toHaveBeenCalledTimes(2))
    expect(screen.getByText('Đang tải phạm vi tài khoản…')).toBeTruthy()
    expect(businessScreens()).toEqual([])
    resolveMe(MANAGER)
    expect(await screen.findByText('ops-overview')).toBeTruthy()
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
  })

  it('401 that did not end the session: error with "Đăng nhập lại", hint dropped', async () => {
    meAnswer = http(401)
    at('/dashboard')
    render(<App />)
    const box = await screen.findByTestId('viewer-unverified')
    expect(clearViewerHint).toHaveBeenCalled()
    expect(businessScreens()).toEqual([])
    fireEvent.click(screen.getByRole('button', { name: 'Đăng nhập lại' }))
    expect(signOut).toHaveBeenCalled()
    expect(box).toBeTruthy()
  })

  it('session expiry while /v1/me is in flight: login with next=, not the error screen', async () => {
    let rejectMe: (e: unknown) => void = () => {}
    meAnswer = () => new Promise((_, reject) => { rejectMe = reject })
    at('/dashboard')
    render(<App />)
    await waitFor(() => expect(getMe).toHaveBeenCalled())
    ended!('expired')
    rejectMe(new ApiError(401, 'session_expired', 'expired'))
    await waitFor(() => expect(document.body.textContent).toContain('Đăng nhập lại'))
    expect(screen.queryByTestId('viewer-unverified')).toBeNull()
    expect(location.pathname + location.search).toBe('/login?next=%2Fdashboard')
  })
})
