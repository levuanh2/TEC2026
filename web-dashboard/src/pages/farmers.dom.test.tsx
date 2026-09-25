// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/client'
import type { FarmerAccount } from '../api/farmers'
import { routeName } from '../routes'

/* Management "Tài khoản nông hộ": list, contextual actions, "Thêm nông hộ". */

const ORG = 'org-1'
const account = (over: Partial<FarmerAccount>): FarmerAccount => ({
  userId: 'u1', email: 'binh@example.vn', fullName: 'Nguyễn Văn Bình', phone: null, accountStatus: 'active',
  farms: [], plotCount: 0, seasonCount: 0, activeSeasonCount: 0, stage: 'no_farm', primaryFarmId: null, idlePlotId: null, ...over,
})
let accounts: FarmerAccount[] = []
const provisionFarmer = vi.fn()
const createPlot = vi.fn()

vi.mock('../api/farmers', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/farmers')>()),
  listFarmerAccounts: async () => accounts,
  provisionFarmer: (...a: unknown[]) => provisionFarmer(...a),
  createPlot: (...a: unknown[]) => createPlot(...a),
}))

const { FarmerAccountsPage, ProvisionFarmerPage, parseArea } = await import('./farmers')
const { passwordProblems } = await import('../farmer/ChangePassword')

beforeEach(() => { accounts = []; provisionFarmer.mockReset(); createPlot.mockReset(); history.replaceState({}, '', '/accounts/farmers') })
afterEach(cleanup)

describe('routing', () => {
  it('lives outside /farmer, which the role redirect reserves for the Farmer shell', () => {
    expect(routeName('/accounts/farmers')).toBe('farmer-accounts')
    expect(routeName('/accounts/farmers/new')).toBe('farmer-account-new')
  })
})

describe('farmer account list', () => {
  it('shows name, account status, farm, plots and season stage with ONE contextual action', async () => {
    accounts = [
      account({ userId: 'a', fullName: 'Chưa có hộ', stage: 'no_farm' }),
      account({ userId: 'b', fullName: 'Chưa có thửa', stage: 'no_plot', farms: [{ id: 'f', code: 'F', name: 'Hộ B', farmRole: 'owner' }], primaryFarmId: 'f' }),
      account({ userId: 'c', fullName: 'Chưa có vụ', stage: 'no_season', plotCount: 1, farms: [{ id: 'g', code: 'G', name: 'Hộ C', farmRole: 'owner' }], primaryFarmId: 'g', idlePlotId: 'p' }),
      account({ userId: 'd', fullName: 'Đang làm', stage: 'active_season', plotCount: 2, activeSeasonCount: 1, farms: [{ id: 'h', code: 'H', name: 'Hộ D', farmRole: 'owner' }], primaryFarmId: 'h' }),
    ]
    render(<FarmerAccountsPage organizationId={ORG} role="cooperative_manager" />)
    await waitFor(() => screen.getByText('Chưa có hộ'))
    expect(screen.getAllByText('Đang hoạt động').length).toBe(4)
    expect(screen.getByRole('button', { name: 'Tạo nông hộ' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Gán thửa' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Tạo vụ' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Xem' })).toBeTruthy()
    expect(screen.getAllByRole('button', { name: /Thêm nông hộ/ }).length).toBe(1)
  })

  it('a non-manager gets no provisioning or structure actions', async () => {
    accounts = [account({ stage: 'no_plot', farms: [{ id: 'f', code: 'F', name: 'Hộ', farmRole: 'owner' }], primaryFarmId: 'f' })]
    render(<FarmerAccountsPage organizationId={ORG} role="enterprise_viewer" />)
    await waitFor(() => screen.getByText('Nguyễn Văn Bình'))
    expect(screen.queryByRole('button', { name: /Thêm nông hộ/ })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Gán thửa' })).toBeNull()
  })

  it('an ended account offers no action but viewing', async () => {
    accounts = [account({ accountStatus: 'ended', stage: 'no_plot', farms: [{ id: 'f', code: 'F', name: 'Hộ', farmRole: 'owner' }], primaryFarmId: 'f' })]
    render(<FarmerAccountsPage organizationId={ORG} role="cooperative_manager" />)
    await waitFor(() => screen.getByText('Đã rời HTX'))
    expect(screen.queryByRole('button', { name: 'Gán thửa' })).toBeNull()
  })

  it('"Gán thửa" records a plot on the farmer\'s farm and refreshes', async () => {
    accounts = [account({ stage: 'no_plot', farms: [{ id: 'f', code: 'F', name: 'Hộ', farmRole: 'owner' }], primaryFarmId: 'f' })]
    createPlot.mockResolvedValue({ id: 'p1' })
    render(<FarmerAccountsPage organizationId={ORG} role="cooperative_manager" />)
    await waitFor(() => screen.getByRole('button', { name: 'Gán thửa' }))
    fireEvent.click(screen.getByRole('button', { name: 'Gán thửa' }))
    fireEvent.change(screen.getByLabelText(/Tên thửa/), { target: { value: 'Thửa 1' } })
    fireEvent.change(screen.getByLabelText(/Mã thửa/), { target: { value: 'T-1' } })
    fireEvent.change(screen.getByLabelText(/Diện tích/), { target: { value: '1,25' } })
    fireEvent.click(screen.getAllByRole('button', { name: 'Gán thửa' }).at(-1)!)
    await waitFor(() => expect(createPlot).toHaveBeenCalledWith('f', { name: 'Thửa 1', plotCode: 'T-1', areaHa: 1.25 }))
  })
})

function fillAccount() {
  fireEvent.change(screen.getByLabelText(/Họ và tên/), { target: { value: 'Nguyễn Văn Bình' } })
  fireEvent.change(screen.getByLabelText(/Email đăng nhập/), { target: { value: 'binh@example.vn' } })
  fireEvent.change(screen.getByLabelText(/Tên nông hộ/), { target: { value: 'Hộ Bình' } })
  fireEvent.change(screen.getByLabelText(/Mã hộ/), { target: { value: 'HH-9' } })
  fireEvent.change(screen.getByLabelText(/Tên thửa/), { target: { value: 'Thửa 1' } })
  fireEvent.change(screen.getByLabelText(/Mã thửa/), { target: { value: 'T-1' } })
  fireEvent.change(screen.getByLabelText(/Diện tích/), { target: { value: '1.2' } })
}

describe('"Thêm nông hộ"', () => {
  it('provisions account + farm + plot in one request and shows the temporary password once', async () => {
    let resolve!: (v: unknown) => void
    provisionFarmer.mockReturnValue(new Promise((r) => { resolve = r }))
    render(<ProvisionFarmerPage organizationId={ORG} role="cooperative_manager" />)
    fillAccount()
    const submit = screen.getByRole('button', { name: 'Tạo tài khoản nông hộ' })
    fireEvent.click(submit)
    fireEvent.click(submit)
    expect(provisionFarmer).toHaveBeenCalledTimes(1)
    expect(provisionFarmer.mock.calls[0][0]).toBe(ORG)
    expect(provisionFarmer.mock.calls[0][1]).toMatchObject({
      fullName: 'Nguyễn Văn Bình', email: 'binh@example.vn',
      farm: expect.objectContaining({ farmName: 'Hộ Bình', farmCode: 'HH-9' }),
      plot: { name: 'Thửa 1', plotCode: 'T-1', areaHa: 1.2 },
    })
    await act(async () => { resolve({ userId: 'u', email: 'binh@example.vn', fullName: 'Nguyễn Văn Bình', farmId: 'f', plotId: 'p', temporaryPassword: 'Ab3d-Ef4h-Jk5m' }) })
    expect(screen.getByTestId('temporary-password').textContent).toBe('Ab3d-Ef4h-Jk5m')
    expect(screen.getByText(/chỉ hiển thị một lần/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /Bắt đầu vụ cho thửa này/ }))
    expect(location.pathname).toBe('/plots/p')
  })

  it('an account can be created before its land: no farm, no plot', async () => {
    provisionFarmer.mockResolvedValue({ userId: 'u', email: 'x@y.vn', fullName: 'X', farmId: null, plotId: null, temporaryPassword: 'Ab3d-Ef4h-Jk5m' })
    render(<ProvisionFarmerPage organizationId={ORG} role="cooperative_manager" />)
    fireEvent.change(screen.getByLabelText(/Họ và tên/), { target: { value: 'X' } })
    fireEvent.change(screen.getByLabelText(/Email đăng nhập/), { target: { value: 'x@y.vn' } })
    fireEvent.click(screen.getByLabelText(/Tạo nông hộ cho tài khoản này/))
    fireEvent.click(screen.getByRole('button', { name: 'Tạo tài khoản nông hộ' }))
    await waitFor(() => expect(provisionFarmer).toHaveBeenCalled())
    expect(provisionFarmer.mock.calls[0][1]).toMatchObject({ farm: null, plot: null })
  })

  it('a duplicate account is explained and nothing is shown as created', async () => {
    provisionFarmer.mockRejectedValue(new ApiError(409, 'farmer_already_member', 'x'))
    render(<ProvisionFarmerPage organizationId={ORG} role="cooperative_manager" />)
    fillAccount()
    fireEvent.click(screen.getByRole('button', { name: 'Tạo tài khoản nông hộ' }))
    await waitFor(() => expect(screen.getByText(/đã là tài khoản thành viên của HTX/)).toBeTruthy())
    expect(screen.queryByTestId('temporary-password')).toBeNull()
    expect((screen.getByRole('button', { name: 'Tạo tài khoản nông hộ' }) as HTMLButtonElement).disabled).toBe(false)
  })

  it('validates before sending: email and area', () => {
    render(<ProvisionFarmerPage organizationId={ORG} role="cooperative_manager" />)
    fillAccount()
    fireEvent.change(screen.getByLabelText(/Email đăng nhập/), { target: { value: 'not-an-email' } })
    fireEvent.change(screen.getByLabelText(/Diện tích/), { target: { value: '0' } })
    fireEvent.click(screen.getByRole('button', { name: 'Tạo tài khoản nông hộ' }))
    expect(screen.getByText(/Nhập email hợp lệ/)).toBeTruthy()
    expect(screen.getByText(/diện tích lớn hơn 0/)).toBeTruthy()
    expect(provisionFarmer).not.toHaveBeenCalled()
  })

  it.each(['enterprise_viewer', 'regulator', 'farmer'] as const)('%s cannot open the form', (role) => {
    render(<ProvisionFarmerPage organizationId={ORG} role={role} />)
    expect(screen.getByText(/Chỉ cán bộ quản lý HTX được thêm nông hộ/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Tạo tài khoản nông hộ' })).toBeNull()
  })
})

describe('helpers', () => {
  it('reads a Vietnamese decimal comma', () => {
    expect(parseArea('1,25')).toBe(1.25)
    expect(parseArea('')).toBeNull()
    expect(parseArea('abc')).toBeNull()
  })

  it('password rules for "Đổi mật khẩu"', () => {
    expect(passwordProblems('short1A', 'short1A')).toMatch(/8 ký tự/)
    expect(passwordProblems('alllowercase1', 'alllowercase1')).toMatch(/chữ hoa/)
    expect(passwordProblems('Good1Password', 'Other1Password')).toMatch(/không khớp/)
    expect(passwordProblems('Good1Password', 'Good1Password')).toBeNull()
  })
})
