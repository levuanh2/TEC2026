// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import { isPublicPath } from './routes'
import { readPlanSelection, selectedPlanReturn } from './pricing'

const auth = vi.hoisted(() => ({ restore: vi.fn(), signIn: vi.fn(), me: vi.fn() }))
vi.mock('../api/auth', async (original) => ({
  ...await original<typeof import('../api/auth')>(),
  restoreSession: auth.restore, signIn: auth.signIn, mustChangePassword: () => false,
  onAuthEnded: () => () => {}, onSessionReplaced: () => () => {},
  onSessionRefreshed: () => () => {}, onSignOutOutcome: () => () => {},
}))
vi.mock('../api/me', async (original) => ({ ...await original<typeof import('../api/me')>(), getMe: auth.me }))
vi.mock('../api/farms', async (original) => ({ ...await original<typeof import('../api/farms')>(), usingMockData: false }))
vi.mock('../farmer/scope', async (original) => ({ ...await original<typeof import('../farmer/scope')>(), prefetchFarmerScope: () => {} }))

const SESSION = { access_token: 'mock-selection-session', user: { id: 'selection-user', email: 'selection@example.test', app_metadata: {} } }
beforeEach(() => {
  auth.restore.mockReset().mockResolvedValue(null)
  auth.signIn.mockReset().mockResolvedValue(SESSION)
  auth.me.mockReset().mockResolvedValue({ userId: SESSION.user.id, role: 'farmer', organizationId: null })
  vi.spyOn(window, 'scrollTo').mockImplementation(() => {})
})
afterEach(() => { cleanup(); vi.restoreAllMocks(); localStorage.clear() })

describe('pricing choice and existing authentication boundary', () => {
  for (const audience of ['Nông hộ', 'Hợp tác xã']) {
    for (const plan of ['FREE', 'PLUS', 'PRO']) {
      it(`keeps ${audience} ${plan} when a signed-out visitor enters login`, async () => {
        history.replaceState({}, '', '/bang-gia')
        render(<App />)
        expect(auth.restore).not.toHaveBeenCalled()
        fireEvent.click(screen.getByRole('link', { name: `${plan === 'FREE' ? 'Chọn gói' : 'Mua ngay'} ${plan} — ${audience}` }))
        await screen.findByRole('heading', { name: 'Đăng nhập' })
        await waitFor(() => expect(location.pathname).toBe('/login'))
        expect(new URLSearchParams(location.search).get('next')).toBe(`/chon-goi?audience=${audience === 'Nông hộ' ? 'nong-ho' : 'hop-tac-xa'}&plan=${plan}`)
        expect(screen.getByText(`Bạn đã chọn gói ${plan} — ${audience}. Đăng nhập để tiếp tục với gói đã chọn.`)).toBeTruthy()
        expect(auth.me).not.toHaveBeenCalled()
      })
    }
  }

  it('returns to the exact chosen plan after sign-in and role verification', async () => {
    history.replaceState({}, '', '/login?next=%2Fchon-goi%3Faudience%3Dhop-tac-xa%26plan%3DPLUS')
    render(<App />)
    await screen.findByRole('heading', { name: 'Đăng nhập' })
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'selection@example.test' } })
    fireEvent.change(screen.getByLabelText('Mật khẩu'), { target: { value: 'mock-password-only' } })
    fireEvent.submit(screen.getByRole('button', { name: 'Đăng nhập' }).closest('form')!)
    await screen.findByRole('heading', { name: 'Gói dịch vụ bạn đã chọn' })
    const summary = screen.getByRole('region', { name: 'Thông tin gói đã chọn' })
    expect(within(summary).getByText('14.990.000 VNĐ')).toBeTruthy()
    expect(within(summary).getByRole('heading', { name: 'Gói PLUS' })).toBeTruthy()
    expect(screen.getByRole('status').textContent).toContain('Chưa phát sinh thanh toán hoặc kích hoạt')
    expect(auth.signIn).toHaveBeenCalledTimes(1)
    expect(auth.me).toHaveBeenCalled()
  })

  it.each(['farmer', 'cooperative_manager'])('a signed-in %s reviews the choice without signing in again', async (role) => {
    auth.restore.mockResolvedValue(SESSION)
    auth.me.mockResolvedValue({ userId: SESSION.user.id, role, organizationId: null })
    history.replaceState({}, '', '/chon-goi?audience=nong-ho&plan=PRO')
    render(<App />)
    await screen.findByRole('heading', { name: 'Gói dịch vụ bạn đã chọn' })
    expect(location.pathname).toBe('/chon-goi')
    expect(screen.getByText('1.999.990 VNĐ')).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Vào không gian của tôi' }).getAttribute('href')).toBe(role === 'farmer' ? '/farmer' : '/dashboard')
    expect(auth.signIn).not.toHaveBeenCalled()
  })

  it('does not bypass verification when the account read fails', async () => {
    auth.restore.mockResolvedValue(SESSION)
    auth.me.mockRejectedValue(new Error('mock verification unavailable'))
    history.replaceState({}, '', '/chon-goi?audience=nong-ho&plan=PLUS')
    render(<App />)
    await screen.findByTestId('viewer-unverified')
    expect(screen.queryByRole('heading', { name: 'Gói dịch vụ bạn đã chọn' })).toBeNull()
  })

  it('resolves only known catalogue choices and local return URLs', () => {
    expect(isPublicPath('/chon-goi')).toBe(false)
    for (const raw of ['https://example.test/chon-goi?audience=nong-ho&plan=PLUS', '//example.test/chon-goi?audience=nong-ho&plan=PLUS', '/chon-goi?audience=other&plan=PRO', '/chon-goi?audience=nong-ho&plan=ADMIN']) expect(selectedPlanReturn(raw)).toBeNull()
    expect(readPlanSelection('?audience=hop-tac-xa&plan=PLUS&price=0')?.plan.price).toBe(14990000)
  })
})
