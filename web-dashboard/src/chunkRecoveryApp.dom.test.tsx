// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { CurrentUser } from './api/me'

/* Chunk failures inside the real App: the confirmed role, the session handling
 * and the shell are unaffected. A Manager page that cannot load shows a retry
 * inside the Management shell; a Farmer UI that cannot load shows a neutral
 * full-page retry, never another role's shell. */

let ended: ((reason: 'expired' | 'signed_out') => void) | null = null
let meAnswer: () => Promise<CurrentUser>
const getMe = vi.fn(() => meAnswer())
const loads = { mrv: 0, farmer: 0 }
const fail = { mrv: false, farmer: false }
const chunk404 = (name: string) => new TypeError(`Failed to fetch dynamically imported module: https://agricarbon.info.vn/assets/${name}-OLD.js`)

vi.mock('./api/auth', () => ({
  onAuthEnded: (fn: typeof ended) => { ended = fn; return () => { ended = null } },
  restoreSession: async () => ({ access_token: 't', user: { id: 'u1', email: 'qa@example.test', app_metadata: {} } }),
  signIn: vi.fn(),
  signOut: vi.fn(),
  mustChangePassword: () => false,
}))
vi.mock('./api/me', () => ({ getMe: () => getMe(), readViewerHint: () => null, writeViewerHint: () => {}, clearViewerHint: () => {} }))
vi.mock('./api/organizations', async (orig) => ({ ...(await orig<object>()), getOrganization: async (id: string) => ({ id, name: 'HTX QA' }) }))
vi.mock('./farmer/scope', async (orig) => ({ ...(await orig<object>()), prefetchFarmerScope: () => {} }))
vi.mock('./query/prefetch', () => ({ prefetchRouteData: () => {} }))
vi.mock('./api/farms', async (orig) => ({ ...(await orig<object>()), usingMockData: false }))
vi.mock('./pages/operations', () => ({ OperationsOverview: () => <p>ops-overview</p>, SeasonsWorkspace: () => <p>seasons</p> }))
vi.mock('./routeChunks', async (orig) => {
  const real = await orig<typeof import('./routeChunks')>()
  const { createElement } = await import('react')
  // Fresh lazy routes per test (React.lazy keeps a resolved load for good).
  const holder = {
    mrv: null as unknown as React.ComponentType,
    farmer: null as unknown as React.ComponentType,
    reset() {
      holder.mrv = real.lazyRoute(async () => {
        loads.mrv++
        if (fail.mrv) throw chunk404('mrv')
        return { MrvPage: () => <p>mrv-page</p> }
      }, 'MrvPage')
      holder.farmer = real.lazyRoute(async () => {
        loads.farmer++
        if (fail.farmer) throw chunk404('FarmerExperience')
        return { FarmerExperience: () => <p>farmer-experience</p> }
      }, 'FarmerExperience')
    },
  }
  ;(globalThis as unknown as { __routes: typeof holder }).__routes = holder
  return {
    ...real,
    prefetchRoute: () => {},
    MrvPage: (p: object) => createElement(holder.mrv, p),
    FarmerExperience: (p: object) => createElement(holder.farmer, p),
  }
})

const { default: App } = await import('./App')
const MANAGER: CurrentUser = { role: 'cooperative_manager', organizationId: 'org-1', fullName: 'QA' }
const FARMER: CurrentUser = { role: 'farmer', organizationId: 'org-1', fullName: 'QA', writableFarmIds: ['farm-1'] }

beforeEach(() => { (globalThis as unknown as { __routes: { reset(): void } }).__routes.reset(); loads.mrv = 0; loads.farmer = 0; fail.mrv = false; fail.farmer = false; vi.spyOn(console, 'error').mockImplementation(() => {}) })
afterEach(() => { cleanup(); ended = null; getMe.mockClear(); vi.restoreAllMocks() })

describe('chunk failures in the App', () => {
  it('Manager page chunk 404: retry inside the shell (sidebar and role kept); Thử lại loads it once fixed', async () => {
    meAnswer = async () => MANAGER
    fail.mrv = true
    history.replaceState({}, '', '/mrv')
    render(<App />)
    const box = await screen.findByTestId('chunk-error')
    expect(box.textContent).toContain('Không tải được nội dung. Vui lòng thử lại.')
    expect(document.querySelector('.shell')).not.toBeNull()
    expect(document.querySelector('.role-chip')?.textContent).toBe('Quản lý HTX')
    fail.mrv = false
    fireEvent.click(screen.getByRole('button', { name: 'Thử lại' }))
    expect(await screen.findByText('mrv-page')).toBeTruthy()
    expect(loads.mrv).toBe(2)
    expect(getMe).toHaveBeenCalledTimes(1)
  })

  it('leaving the failed page for another one works without a reload', async () => {
    meAnswer = async () => MANAGER
    fail.mrv = true
    history.replaceState({}, '', '/mrv')
    render(<App />)
    await screen.findByTestId('chunk-error')
    act(() => { history.pushState({}, '', '/dashboard'); dispatchEvent(new PopStateEvent('popstate')) })
    expect(await screen.findByText('ops-overview')).toBeTruthy()
    expect(screen.queryByTestId('chunk-error')).toBeNull()
  })

  it('Farmer UI chunk fails: neutral full-page retry, never the Management shell; retry opens the Farmer UI', async () => {
    meAnswer = async () => FARMER
    fail.farmer = true
    history.replaceState({}, '', '/farmer')
    render(<App />)
    await screen.findByTestId('chunk-error')
    expect(document.querySelector('.shell, .role-chip, nav')).toBeNull()
    expect(location.pathname).toBe('/farmer')
    fail.farmer = false
    fireEvent.click(screen.getByRole('button', { name: 'Thử lại' }))
    expect(await screen.findByText('farmer-experience')).toBeTruthy()
  })

  it('session expiry while the chunk error is shown: login with next=, the error is gone', async () => {
    meAnswer = async () => MANAGER
    fail.mrv = true
    history.replaceState({}, '', '/mrv')
    render(<App />)
    await screen.findByTestId('chunk-error')
    act(() => ended!('expired'))
    await waitFor(() => expect(location.pathname + location.search).toBe('/login?next=%2Fmrv'))
    expect(screen.queryByTestId('chunk-error')).toBeNull()
    expect(document.querySelector('.shell')).toBeNull()
  })

  it('no chunk is requested before /v1/me confirms the role', async () => {
    let resolve: (v: CurrentUser) => void = () => {}
    meAnswer = () => new Promise((r) => { resolve = r })
    history.replaceState({}, '', '/farmer')
    render(<App />)
    await waitFor(() => expect(getMe).toHaveBeenCalled())
    await act(async () => { await new Promise((r) => setTimeout(r, 30)) })
    expect(loads.farmer).toBe(0)
    expect(screen.getByTestId('viewer-verifying')).toBeTruthy()
    resolve(FARMER)
    expect(await screen.findByText('farmer-experience')).toBeTruthy()
  })
})
