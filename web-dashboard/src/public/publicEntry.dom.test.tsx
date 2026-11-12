// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import { isPublicPath } from './routes'
import { routeName } from '../routes'

const auth = vi.hoisted(() => ({ restore: vi.fn(), me: vi.fn() }))
vi.mock('../api/auth', async (original) => ({ ...await original<typeof import('../api/auth')>(), restoreSession: auth.restore }))
vi.mock('../api/me', async (original) => ({ ...await original<typeof import('../api/me')>(), getMe: auth.me }))

beforeEach(() => {
  auth.restore.mockReset().mockResolvedValue(null)
  auth.me.mockReset()
  vi.spyOn(window, 'scrollTo').mockImplementation(() => {})
})
afterEach(() => { cleanup(); vi.restoreAllMocks() })

describe('public/application boundary', () => {
  it.each(['/', '/nen-tang', '/dich-vu', '/bao-cao', '/bang-gia', '/tin-tuc', '/tin-tuc/du-lieu-canh-tac-va-ho-so-mrv'])('%s opens without restoring a session or querying account scope', (path) => {
    history.replaceState({}, '', path)
    render(<App />)
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
    expect(auth.restore).not.toHaveBeenCalled()
    expect(auth.me).not.toHaveBeenCalled()
    expect(document.querySelector('.shell, .fw-shell')).toBeNull()
  })

  it('enters the existing sign-in flow on request, then returns to public home', async () => {
    history.replaceState({}, '', '/')
    render(<App />)
    fireEvent.click(screen.getAllByRole('link', { name: /^Đăng nhập/ })[0])
    expect(await screen.findByRole('heading', { name: 'Đăng nhập' })).toBeTruthy()
    expect(auth.restore).toHaveBeenCalledTimes(1)
    fireEvent.click(screen.getByRole('link', { name: /Về trang chủ AgriCarbon/ }))
    expect(screen.getByRole('heading', { level: 1 }).textContent).toContain('Số hóa canh tác')
    expect(location.pathname).toBe('/')
  })

  it('keeps protected paths outside the public route set', () => {
    for (const path of ['/login', '/dashboard', '/farmer', '/farmer/journal', '/mrv', '/crop-seasons/s1', '/accounts/farmers', '/unknown']) expect(isPublicPath(path)).toBe(false)
    expect(routeName('/')).toBe('public')
    expect(routeName('/dashboard')).toBe('dashboard')
    expect(routeName('/farmer/journal')).toBe('farmer')
  })
})
