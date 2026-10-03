import { beforeEach, describe, expect, it, vi } from 'vitest'

/* Forced first login (Web): the server verifies the temporary password, sets
 * the new one and clears the flag in one call; changing it revokes every
 * refresh token, so the new session comes from signing in with the NEW
 * password -- never from a refresh. */
const apiRequest = vi.fn()
const signInWithPassword = vi.fn()
vi.mock('./client', () => ({
  apiRequest: (...a: unknown[]) => apiRequest(...a),
  endSession: vi.fn(), setAccessToken: vi.fn(), setUnauthorizedHandler: vi.fn(),
}))
vi.mock('../utils/supabase', () => ({
  supabase: { auth: {
    signInWithPassword: (...a: unknown[]) => signInWithPassword(...a),
    onAuthStateChange: vi.fn(() => ({ data: { subscription: { unsubscribe: vi.fn() } } })),
  } },
}))
vi.mock('../farmer/data', () => ({ clearFarmerCache: vi.fn() }))

const { replaceTemporaryPassword, mustChangePassword } = await import('./auth')

const SESSION = { access_token: 'new-token', user: { id: 'u1', app_metadata: {} } }

beforeEach(() => { apiRequest.mockReset(); signInWithPassword.mockReset() })

describe('replaceTemporaryPassword', () => {
  it('posts both passwords once, then signs in with the NEW password', async () => {
    apiRequest.mockResolvedValue({ must_change_password: false })
    signInWithPassword.mockResolvedValue({ data: { session: SESSION }, error: null })
    const session = await replaceTemporaryPassword('a@x.vn', 'Temp-1', 'Mine-2026')
    expect(apiRequest).toHaveBeenCalledTimes(1)
    const [path, init] = apiRequest.mock.calls[0]
    expect(path).toBe('/v1/me/password')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({ current_password: 'Temp-1', new_password: 'Mine-2026' })
    expect(signInWithPassword).toHaveBeenCalledWith({ email: 'a@x.vn', password: 'Mine-2026' })
    expect(session).toBe(SESSION)
  })

  it('a refused change (wrong temporary password) is reported as is, and no sign-in is attempted', async () => {
    apiRequest.mockRejectedValue(new Error('Mật khẩu hiện tại không đúng.'))
    await expect(replaceTemporaryPassword('a@x.vn', 'Wrong', 'Mine-2026')).rejects.toThrow('Mật khẩu hiện tại không đúng.')
    expect(signInWithPassword).not.toHaveBeenCalled()
  })

  it.each([
    ['the sign-in fails', () => signInWithPassword.mockResolvedValue({ data: { session: null }, error: new Error('network') })],
    ['the sign-in returns no session', () => signInWithPassword.mockResolvedValue({ data: { session: null }, error: null })],
  ])('changed but %s: says the password WAS changed and to sign in with the new one', async (_label, arrange) => {
    apiRequest.mockResolvedValue({ must_change_password: false })
    arrange()
    await expect(replaceTemporaryPassword('a@x.vn', 'Temp-1', 'Mine-2026'))
      .rejects.toThrow('Đã đổi mật khẩu. Vui lòng đăng nhập lại bằng mật khẩu mới.')
  })
})

describe('mustChangePassword', () => {
  it('reads only the server-set app_metadata flag', () => {
    expect(mustChangePassword(null)).toBe(false)
    expect(mustChangePassword({ user: { app_metadata: { must_change_password: true } } } as never)).toBe(true)
    expect(mustChangePassword({ user: { app_metadata: {}, user_metadata: { must_change_password: true } } } as never)).toBe(false)
    expect(mustChangePassword({ user: { app_metadata: { must_change_password: 'true' } } } as never)).toBe(false)
  })
})
