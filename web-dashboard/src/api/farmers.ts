import { ApiError, apiRequest } from './client'
import { usingMockData } from './farms'

/* Management: the cooperative's farmer accounts and their onboarding.
 *
 * Every call goes to FastAPI. The Supabase Auth Admin API (the only place an
 * account can be created) is reached server-side; this module never holds a
 * service-role credential and never talks to Supabase Auth itself. */

export type FarmerStage = 'no_farm' | 'no_plot' | 'no_season' | 'active_season' | 'history_only'
export interface FarmerFarmRef { id: string; code: string; name: string; farmRole: string }
export interface FarmerAccount {
  userId: string; email: string | null; fullName: string | null; phone: string | null
  accountStatus: 'active' | 'locked' | 'ended'
  farms: FarmerFarmRef[]; plotCount: number; seasonCount: number; activeSeasonCount: number
  stage: FarmerStage; primaryFarmId: string | null; idlePlotId: string | null
}

const account = (x: any): FarmerAccount => ({
  userId: x.user_id, email: x.email ?? null, fullName: x.full_name ?? null, phone: x.phone ?? null,
  accountStatus: x.account_status,
  farms: (x.farms ?? []).map((f: any) => ({ id: f.id, code: f.farm_code, name: f.farm_name, farmRole: f.farm_role })),
  plotCount: x.plot_count, seasonCount: x.season_count, activeSeasonCount: x.active_season_count,
  stage: x.stage, primaryFarmId: x.primary_farm_id ?? null, idlePlotId: x.idle_plot_id ?? null,
})

const MOCK_UNAVAILABLE = () => new ApiError(503, 'mock_mode', 'Chức năng cấp tài khoản cần máy chủ thật, không có trong chế độ dữ liệu mẫu.')

export async function listFarmerAccounts(organizationId: string): Promise<FarmerAccount[]> {
  if (usingMockData) return []
  return (await apiRequest<{ items: any[] }>(`/v1/organizations/${organizationId}/farmers`)).items.map(account)
}

export interface FarmInput { farmCode: string; farmName: string; commune?: string; district?: string; province?: string }
export interface PlotInput { plotCode: string; name: string; areaHa: number }
export interface ProvisionInput { fullName: string; email: string; phone?: string; farm?: FarmInput | null; plot?: PlotInput | null }
export interface ProvisionedFarmer {
  userId: string; email: string; fullName: string; farmId: string | null; plotId: string | null
  /** Shown once, to hand to the farmer. The server keeps no copy. */
  temporaryPassword: string
}

const farmBody = (f: FarmInput) => ({
  farm_code: f.farmCode.trim(), farm_name: f.farmName.trim(),
  commune_name: f.commune?.trim() || null, district_name: f.district?.trim() || null, province_name: f.province?.trim() || null,
})
const plotBody = (p: PlotInput) => ({ plot_code: p.plotCode.trim(), name: p.name.trim(), area_ha: p.areaHa })

export async function provisionFarmer(organizationId: string, input: ProvisionInput): Promise<ProvisionedFarmer> {
  if (usingMockData) throw MOCK_UNAVAILABLE()
  const x = await apiRequest<any>(`/v1/organizations/${organizationId}/farmers`, {
    method: 'POST',
    body: JSON.stringify({
      full_name: input.fullName.trim(), email: input.email.trim(), phone: input.phone?.trim() || null,
      farm: input.farm ? farmBody(input.farm) : null,
      plot: input.farm && input.plot ? plotBody(input.plot) : null,
    }),
  })
  return { userId: x.user_id, email: x.email, fullName: x.full_name, farmId: x.farm_id ?? null, plotId: x.plot_id ?? null, temporaryPassword: x.temporary_password }
}

export async function createFarmForFarmer(organizationId: string, ownerUserId: string, farm: FarmInput): Promise<{ id: string }> {
  if (usingMockData) throw MOCK_UNAVAILABLE()
  return apiRequest(`/v1/organizations/${organizationId}/farms`, { method: 'POST', body: JSON.stringify({ owner_user_id: ownerUserId, ...farmBody(farm) }) })
}

export async function createPlot(farmId: string, plot: PlotInput): Promise<{ id: string }> {
  if (usingMockData) throw MOCK_UNAVAILABLE()
  return apiRequest(`/v1/farms/${farmId}/plots`, { method: 'POST', body: JSON.stringify(plotBody(plot)) })
}

const MESSAGES: Record<string, string> = {
  farmer_already_member: 'Email này đã là tài khoản thành viên của HTX. Tìm nông hộ trong danh sách thay vì tạo mới.',
  membership_inactive: 'Email này thuộc một thành viên đã ngừng tham gia HTX. Việc kích hoạt lại cần quản trị hệ thống thực hiện.',
  account_exists: 'Email này đã được dùng cho một tài khoản khác. Dùng email khác hoặc liên hệ quản trị hệ thống.',
  farm_code_exists: 'HTX đã có nông hộ với mã này. Hãy dùng mã hộ khác.',
  plot_code_exists: 'Nông hộ đã có thửa với mã này. Hãy dùng mã thửa khác.',
  not_found: 'Bạn không có quyền thực hiện thao tác này cho HTX.',
  provisioning_failed: 'Chưa tạo được tài khoản nông hộ. Không có dữ liệu nào được lưu; hãy thử lại.',
  provisioning_incomplete: 'Chưa tạo được tài khoản nông hộ. Tài khoản đăng nhập đã bị khoá và chưa thuộc HTX; báo quản trị hệ thống.',
  offline: 'Không kết nối được máy chủ. Kiểm tra mạng rồi thử lại.',
}

export function provisioningErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (MESSAGES[err.code]) return MESSAGES[err.code]
    if (err.status === 422) return 'Thông tin chưa hợp lệ. Kiểm tra email, mã và diện tích.'
    if (err.code === 'mock_mode') return err.message
  }
  return 'Chưa thực hiện được. Vui lòng thử lại.'
}
