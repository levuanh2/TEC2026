// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { Session } from '@supabase/supabase-js'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/client'

/* Forced first login (Core V1 closure 3B): the flag comes from the server
 * (Supabase app_metadata / `/v1/me`), the form posts to the server, and only a
 * server success lets the shell continue. */

const replaceTemporaryPassword = vi.fn()
const signOut = vi.fn()
vi.mock('../api/auth', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/auth')>()),
  replaceTemporaryPassword: (...a: unknown[]) => replaceTemporaryPassword(...a),
  signOut: () => signOut(),
}))

const { ForcedPasswordChange } = await import('./ForcedPasswordChange')
const { mustChangePassword } = await import('../api/auth')
const { toCurrentUser } = await import('../api/me')

const session = (flag?: unknown) => ({ user: { id: 'u1', email: 'farmer@example.invalid', app_metadata: flag === undefined ? {} : { must_change_password: flag } } }) as unknown as Session

beforeEach(() => { replaceTemporaryPassword.mockReset(); signOut.mockReset() })
afterEach(cleanup)

function fill(current: string, next: string, confirm = next) {
  fireEvent.change(screen.getByLabelText('Mật khẩu tạm'), { target: { value: current } })
  fireEvent.change(screen.getByLabelText('Mật khẩu mới'), { target: { value: next } })
  fireEvent.change(screen.getByLabelText('Nhập lại mật khẩu mới'), { target: { value: confirm } })
  fireEvent.click(screen.getByRole('button', { name: 'Lưu mật khẩu và tiếp tục' }))
}

describe('the flag', () => {
  it('is only a literal true from app_metadata, never a client choice', () => {
    expect(mustChangePassword(session(true))).toBe(true)
    for (const v of [false, 'true', 1, null, undefined]) expect(mustChangePassword(session(v))).toBe(false)
    expect(mustChangePassword(null)).toBe(false)
  })

  it('is read from /v1/me as the live server state', () => {
    const base = { roles: ['farmer'], organization_memberships: [] }
    expect(toCurrentUser({ ...base, must_change_password: true }).mustChangePassword).toBe(true)
    expect(toCurrentUser(base).mustChangePassword).toBe(false)
  })
})

describe('ForcedPasswordChange', () => {
  it('sends the temporary and the new password to the server, then hands over the refreshed session', async () => {
    const fresh = session(false)
    replaceTemporaryPassword.mockResolvedValue(fresh)
    const done = vi.fn()
    render(<ForcedPasswordChange session={session(true)} done={done} />)
    expect(screen.getByText('farmer@example.invalid')).toBeTruthy()
    fill('Temp-Pass-1', 'Own-Pass-22')
    await waitFor(() => expect(done).toHaveBeenCalledWith(fresh))
    expect(replaceTemporaryPassword).toHaveBeenCalledWith('Temp-Pass-1', 'Own-Pass-22')
  })

  it('checks the new password locally before any request', () => {
    const done = vi.fn()
    render(<ForcedPasswordChange session={session(true)} done={done} />)
    fill('Temp-Pass-1', 'short')
    expect(screen.getByText('Mật khẩu mới cần ít nhất 8 ký tự.')).toBeTruthy()
    fill('Temp-Pass-1', 'Own-Pass-22', 'Own-Pass-23')
    expect(screen.getByText('Hai lần nhập mật khẩu mới không khớp.')).toBeTruthy()
    fill('', 'Own-Pass-22')
    expect(screen.getByText('Nhập mật khẩu tạm HTX đã cấp.')).toBeTruthy()
    expect(replaceTemporaryPassword).not.toHaveBeenCalled()
    expect(done).not.toHaveBeenCalled()
  })

  it('shows the server refusal and stays on the form', async () => {
    replaceTemporaryPassword.mockRejectedValue(new ApiError(422, 'current_password_incorrect', 'Mật khẩu hiện tại không đúng.'))
    const done = vi.fn()
    render(<ForcedPasswordChange session={session(true)} done={done} />)
    fill('Wrong-Pass-1', 'Own-Pass-22')
    expect(await screen.findByText('Mật khẩu hiện tại không đúng.')).toBeTruthy()
    expect(done).not.toHaveBeenCalled()
    expect(screen.getByTestId('forced-password-change')).toBeTruthy()
  })

  it('offers sign-out as the only other way out', () => {
    render(<ForcedPasswordChange session={session(true)} done={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Đăng xuất' }))
    expect(signOut).toHaveBeenCalledOnce()
  })
})
