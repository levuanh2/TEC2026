// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

/* Forced first login, shell wiring: while the session carries the server-set
 * flag the app renders ONLY the change form -- no /v1/me, no business request
 * (the server would refuse them anyway). When the change completes with a new
 * session, the normal shell loads with that session. */

const FLAGGED = { access_token: 'temp', user: { id: 'u1', email: 'f@x.vn', app_metadata: { must_change_password: true } } }
const FRESH = { access_token: 'fresh', user: { id: 'u1', email: 'f@x.vn', app_metadata: {} } }

const getMe = vi.fn(async () => ({ role: 'farmer', organizationId: null, mustChangePassword: false }))
vi.mock('./api/auth', () => ({
  onAuthEnded: () => () => {},
  restoreSession: async () => FLAGGED,
  signIn: vi.fn(),
  signOut: vi.fn(),
  mustChangePassword: (s: { user?: { app_metadata?: { must_change_password?: unknown } } } | null) =>
    s?.user?.app_metadata?.must_change_password === true,
}))
vi.mock('./api/me', () => ({ getMe: () => getMe(), readViewerHint: () => null, writeViewerHint: () => {} }))
vi.mock('./components/ForcedPasswordChange', () => ({
  ForcedPasswordChange: ({ done }: { done: (s: unknown) => void }) => (
    <button type="button" onClick={() => done(FRESH)}>forced-change-form</button>
  ),
}))
vi.mock('./farmer/scope', async (orig) => ({ ...(await orig<object>()), prefetchFarmerScope: () => {} }))
vi.mock('./api/farms', async (orig) => ({ ...(await orig<object>()), usingMockData: false }))

const { default: App } = await import('./App')

afterEach(() => { cleanup(); getMe.mockClear() })

describe('a session still on the temporary password', () => {
  it('gets only the change form and sends no /v1/me; after the change the shell loads with the new session', async () => {
    history.replaceState({}, '', '/farmer')
    render(<App />)
    const form = await screen.findByText('forced-change-form')
    await act(async () => { await new Promise((r) => setTimeout(r, 30)) })
    expect(getMe).not.toHaveBeenCalled()

    fireEvent.click(form)
    await waitFor(() => expect(getMe).toHaveBeenCalled())
    expect(screen.queryByText('forced-change-form')).toBeNull()
  })
})
