// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'

/* Sign-out is local first: the shell must leave even when the server call
 * fails, and every session-scoped cache is dropped. */

const remoteSignOut = vi.fn()
vi.mock('../utils/supabase', () => ({
  supabase: {
    auth: {
      signOut: (...a: unknown[]) => remoteSignOut(...a),
      onAuthStateChange: vi.fn(),
      getSession: vi.fn().mockResolvedValue({ data: { session: { access_token: 'live-token', user: { id: 'u1' } } }, error: null }),
      refreshSession: vi.fn().mockResolvedValue({ data: { session: null }, error: { message: 'Refresh Token Not Found' } }),
      signInWithPassword: vi.fn().mockResolvedValue({ data: { session: null }, error: new Error('Invalid login credentials') }),
    },
  },
}))
const clearFarmerCache = vi.fn()
vi.mock('../farmer/data', () => ({ clearFarmerCache: () => clearFarmerCache() }))

const { onAuthEnded, restoreSession, signIn, signOut, signInErrorMessage } = await import('./auth')
const { apiRequest } = await import('./client')

afterEach(() => { vi.unstubAllGlobals(); remoteSignOut.mockReset(); clearFarmerCache.mockReset() })

describe('auth boundary', () => {
  it('sign-out tells the shell and clears caches even when the server call throws', async () => {
    remoteSignOut.mockRejectedValue(new Error('network down'))
    await restoreSession()
    const ended = vi.fn()
    const off = onAuthEnded(ended)
    await signOut()
    expect(ended).toHaveBeenCalledWith('signed_out')
    expect(clearFarmerCache).toHaveBeenCalled()
    off()
  })

  it('an unrecoverable 401 ends the session as expired', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 401 })))
    await restoreSession()
    const ended = vi.fn()
    const off = onAuthEnded(ended)
    await expect(apiRequest('/v1/farmer/scope')).rejects.toMatchObject({ code: 'session_expired' })
    expect(ended).toHaveBeenCalledWith('expired')
    // A late second signal (Supabase SIGNED_OUT after the failed refresh) is not
    // a second ending: the shell hears it exactly once.
    await expect(apiRequest('/v1/farmer/scope')).rejects.toMatchObject({ code: 'session_expired' })
    expect(ended).toHaveBeenCalledTimes(1)
    off()
  })

  it('never shows Supabase English on the login screen', async () => {
    await expect(signIn('a@b.c', 'x')).rejects.toThrow('Email hoặc mật khẩu không đúng.')
    expect(signInErrorMessage(new Error('Failed to fetch'))).toMatch(/Không kết nối được máy chủ/)
    expect(signInErrorMessage(new Error('something odd'))).toBe('Không thể đăng nhập. Vui lòng thử lại.')
  })
})
