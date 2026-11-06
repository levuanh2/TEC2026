// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

/* R3 F4: the login screen after a sign-out says only what is true.
 *  - "Bạn đã đăng xuất." only when the server confirmed the revocation;
 *  - otherwise a warning that the session may still be valid elsewhere, with
 *    "Thử xác nhận lại"; a late confirmation (or a successful retry) turns it
 *    into the plain confirmation;
 *  - a sign-out from another tab is reported as such, not as a confirmation. */

let ended: ((reason: string) => void) | null = null
let confirmedListener: (() => void) | null = null
const confirmSignOut = vi.fn(async () => false)

vi.mock('./api/auth', () => ({
  onSignOutConfirmed: (fn: () => void) => { confirmedListener = fn; return () => { confirmedListener = null } },
  confirmSignOut: () => confirmSignOut(),
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

afterEach(() => { cleanup(); ended = null; confirmedListener = null; confirmSignOut.mockReset() })

async function signedInThenEnded(reason: string) {
  history.replaceState({}, '', '/farmer')
  render(<App />)
  await screen.findByText('farmer-experience')
  act(() => ended!(reason))
  return screen.findByTestId('auth-ended')
}

describe('login screen after a sign-out', () => {
  it('confirmed: the plain "Bạn đã đăng xuất." and no retry', async () => {
    const notice = await signedInThenEnded('signed_out')
    expect(notice.textContent).toBe('Bạn đã đăng xuất.')
    expect(screen.queryByRole('button', { name: 'Thử xác nhận lại' })).toBeNull()
  })

  it('unconfirmed: a warning (role=alert), never the plain confirmation; a failed retry explains what to do', async () => {
    const notice = await signedInThenEnded('signed_out_unconfirmed')
    expect(notice.getAttribute('role')).toBe('alert')
    expect(notice.textContent).toMatch(/chưa xác nhận được với máy chủ/)
    expect(notice.textContent).not.toBe('Bạn đã đăng xuất.')
    confirmSignOut.mockResolvedValueOnce(false)
    fireEvent.click(screen.getByRole('button', { name: 'Thử xác nhận lại' }))
    expect(await screen.findByTestId('sign-out-unconfirmed-help')).toBeTruthy()
    expect(screen.getByTestId('auth-ended').textContent).toMatch(/chưa xác nhận/)
  })

  it('unconfirmed, then a successful retry: "Bạn đã đăng xuất."', async () => {
    await signedInThenEnded('signed_out_unconfirmed')
    confirmSignOut.mockResolvedValueOnce(true)
    fireEvent.click(screen.getByRole('button', { name: 'Thử xác nhận lại' }))
    await vi.waitFor(() => expect(screen.getByTestId('auth-ended').textContent).toBe('Bạn đã đăng xuất.'))
    expect(screen.queryByRole('button', { name: 'Thử xác nhận lại' })).toBeNull()
  })

  it('unconfirmed, then the late server answer confirms it on its own', async () => {
    await signedInThenEnded('signed_out_unconfirmed')
    act(() => confirmedListener!())
    expect(screen.getByTestId('auth-ended').textContent).toBe('Bạn đã đăng xuất.')
  })

  it('ended in another tab: said as such', async () => {
    const notice = await signedInThenEnded('ended_elsewhere')
    expect(notice.textContent).toMatch(/ở một tab khác/)
  })
})
