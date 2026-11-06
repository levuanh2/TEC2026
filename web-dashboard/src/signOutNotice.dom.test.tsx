// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

/* R3 F4: the login screen after a sign-out says only what is true.
 *  - At once (local session gone, server not answered): "Đang xác nhận…",
 *    never the plain confirmation, and no business screen.
 *  - "Bạn đã đăng xuất." only after the server confirmed.
 *  - Otherwise a warning that the session may still be valid elsewhere, with a
 *    BOUNDED "Thử xác nhận lại"; a late confirmation or a successful retry
 *    turns it into the confirmation.
 *  - R16 (owner-approved): a session ended in another tab is reported as such. */

let ended: ((reason: string) => void) | null = null
let outcome: ((o: 'confirmed' | 'unconfirmed') => void) | null = null
const confirmSignOut = vi.fn(async () => false)
let canConfirm = true

vi.mock('./api/auth', () => ({
  onSignOutOutcome: (fn: typeof outcome) => { outcome = fn; return () => { outcome = null } },
  confirmSignOut: () => confirmSignOut(),
  canConfirmSignOut: () => canConfirm,
  onAuthEnded: (fn: typeof ended) => { ended = fn; return () => { ended = null } },
  onSessionRefreshed: () => () => {},
  onSessionReplaced: () => () => {},
  restoreSession: async () => ({ access_token: 't', user: { id: 'u1', email: 'a@example.test', app_metadata: {} } }),
  signIn: vi.fn(),
  signOut: vi.fn(),
  mustChangePassword: () => false,
}))
vi.mock('./api/me', () => ({ getMe: async () => ({ role: 'farmer', organizationId: 'org-1', userId: 'u1' }), readViewerHint: () => null, writeViewerHint: () => {}, clearViewerHint: () => {} }))
vi.mock('./farmer/scope', async (orig) => ({ ...(await orig<object>()), prefetchFarmerScope: () => {} }))
vi.mock('./api/farms', async (orig) => ({ ...(await orig<object>()), usingMockData: false }))
vi.mock('./farmer/FarmerExperience', () => ({ FarmerExperience: () => <p>farmer-experience</p> }))

const { default: App } = await import('./App')

afterEach(() => { cleanup(); ended = null; outcome = null; confirmSignOut.mockReset(); canConfirm = true })

async function signedInThenEnded(reason: string) {
  history.replaceState({}, '', '/farmer')
  render(<App />)
  await screen.findByText('farmer-experience')
  act(() => ended!(reason))
  return screen.findByTestId('auth-ended')
}
const notice = () => screen.getByTestId('auth-ended')

describe('login screen after a sign-out', () => {
  it('at once: the business screen is gone and the notice says the server is being asked, not "signed out"', async () => {
    await signedInThenEnded('signing_out')
    expect(screen.queryByText('farmer-experience')).toBeNull()
    expect(notice().textContent).toMatch(/Đang xác nhận với máy chủ/)
    expect(notice().textContent).not.toBe('Bạn đã đăng xuất.')
    expect(screen.queryByRole('button', { name: 'Thử xác nhận lại' })).toBeNull()
  })

  it('then confirmed by the server: "Bạn đã đăng xuất." and no retry', async () => {
    await signedInThenEnded('signing_out')
    act(() => outcome!('confirmed'))
    expect(notice().textContent).toBe('Bạn đã đăng xuất.')
    expect(screen.queryByRole('button', { name: 'Thử xác nhận lại' })).toBeNull()
  })

  it('then unconfirmed: a warning (role=alert), never the plain confirmation; a failed retry explains what to do', async () => {
    await signedInThenEnded('signing_out')
    act(() => outcome!('unconfirmed'))
    expect(notice().getAttribute('role')).toBe('alert')
    expect(notice().textContent).toMatch(/chưa xác nhận được với máy chủ/)
    confirmSignOut.mockResolvedValueOnce(false)
    fireEvent.click(screen.getByRole('button', { name: 'Thử xác nhận lại' }))
    expect(await screen.findByTestId('sign-out-unconfirmed-help')).toBeTruthy()
    expect(notice().textContent).toMatch(/chưa xác nhận/)
  })

  it('unconfirmed, then a successful retry: "Bạn đã đăng xuất."', async () => {
    await signedInThenEnded('signing_out')
    act(() => outcome!('unconfirmed'))
    confirmSignOut.mockResolvedValueOnce(true)
    fireEvent.click(screen.getByRole('button', { name: 'Thử xác nhận lại' }))
    await vi.waitFor(() => expect(notice().textContent).toBe('Bạn đã đăng xuất.'))
  })

  it('unconfirmed, then the late server answer confirms it on its own', async () => {
    await signedInThenEnded('signing_out')
    act(() => outcome!('unconfirmed'))
    act(() => outcome!('confirmed'))
    expect(notice().textContent).toBe('Bạn đã đăng xuất.')
  })

  it('retries used up: no button any more, only the advice', async () => {
    canConfirm = false
    await signedInThenEnded('signing_out')
    act(() => outcome!('unconfirmed'))
    expect(screen.queryByRole('button', { name: 'Thử xác nhận lại' })).toBeNull()
    expect(screen.getByTestId('sign-out-unconfirmed-help').textContent).toMatch(/Không xác nhận được với máy chủ/)
  })

  it('an outcome never turns another kind of ending into "signed out" (expired stays expired)', async () => {
    await signedInThenEnded('expired')
    act(() => outcome!('confirmed'))
    expect(notice().textContent).toMatch(/hết hạn/)
  })

  it('R16 (owner-approved): ended in another tab is said as such, on the neutral login screen', async () => {
    await signedInThenEnded('ended_elsewhere')
    expect(notice().textContent).toMatch(/ở một tab khác/)
    expect(screen.queryByText('farmer-experience')).toBeNull()
  })
})
