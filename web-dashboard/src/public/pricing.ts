/** User-supplied service information. Display only; never an entitlement source. */
export interface ServicePlan {
  name: 'FREE' | 'PLUS' | 'PRO'
  price: number
  description: string
  groups: { label?: string; features: string[] }[]
  suitableFor: string[]
}

export const FARMER_PLANS: ServicePlan[] = [
  {
    name: 'FREE', price: 0,
    description: 'Bắt đầu ghi nhật ký canh tác trên điện thoại.',
    groups: [{ features: [
      'Ghi nhật ký canh tác: gieo sạ, phân bón, tưới nước, rơm rạ, thuốc BVTV, thu hoạch',
      'Tính carbon mùa vụ hiện tại: 1 lần/năm',
      'Trợ lý AI 1 triệu token/ngày',
    ] }],
    suitableFor: ['Nông hộ mới làm quen ứng dụng'],
  },
  {
    name: 'PLUS', price: 999990,
    description: 'Theo dõi chi phí và tài nguyên mỗi vụ.',
    groups: [{ features: [
      'Ghi nhật ký canh tác đầy đủ 6 hoạt động',
      'Tính hiệu suất: hiệu quả tài nguyên, chi phí',
      'Tính carbon mùa vụ hiện tại: 5 lần/năm',
      'Trợ lý AI 3 triệu token/ngày',
    ] }],
    suitableFor: ['Nông hộ muốn giảm chi phí đầu vào', 'Dùng nước, phân bón hiệu quả hơn'],
  },
  {
    name: 'PRO', price: 1999990,
    description: 'Đầy đủ công cụ cho canh tác phát thải thấp.',
    groups: [{ features: [
      'Ghi nhật ký canh tác đầy đủ 6 hoạt động',
      'Tính hiệu suất đầy đủ: phát thải carbon giữa các mùa vụ, tài nguyên, chi phí',
      'Tính carbon mùa vụ hiện tại: 15 lần/năm',
      'Trợ lý AI 5 triệu token/ngày',
    ] }],
    suitableFor: ['Nông hộ canh tác lúa phát thải thấp', 'Cần so sánh hiệu quả giữa các vụ'],
  },
]

export const COOPERATIVE_PLANS: ServicePlan[] = [
  {
    name: 'FREE', price: 0,
    description: 'Bắt đầu số hóa quản lý vùng trồng cho HTX.',
    groups: [
      { label: 'Cho HTX', features: [
        'Quản lý chung', 'Cấp 05 mã tài khoản nông hộ',
        'Tính carbon mùa vụ: 15 lần/năm', 'Dữ liệu thiếu: xem nội dung còn thiếu',
        'Quản lý nông hộ', 'Tổng quan vụ mùa & carbon theo vụ',
      ] },
      { label: 'Cho nông dân', features: ['Ghi nhật ký canh tác', 'Trợ lý AI 200.000 token/ngày'] },
    ],
    suitableFor: ['HTX muốn làm quen nền tảng', 'Nhóm nông hộ quy mô nhỏ'],
  },
  {
    name: 'PLUS', price: 14990000,
    description: 'Quản lý vùng trồng và sẵn sàng hồ sơ MRV.',
    groups: [
      { label: 'Cho HTX', features: [
        'Quản lý chung', 'Cấp 80 mã tài khoản nông hộ',
        'Tính carbon mùa vụ: 300 lần/năm', 'Dữ liệu thiếu: xem & gửi thông báo nhắc',
        'Quản lý nông hộ, xuất MRV 300 lượt', 'Tổng quan vụ mùa & carbon theo vụ',
        'Hiệu suất vùng trong phạm vi HTX',
      ] },
      { label: 'Cho nông dân', features: [
        'Ghi nhật ký canh tác', 'Tính hiệu suất: tài nguyên, chi phí', 'Trợ lý AI 1 triệu token/ngày',
      ] },
    ],
    suitableFor: ['HTX quy mô vừa (đến 80 nông hộ)', 'Cần báo cáo MRV cho xuất khẩu'],
  },
  {
    name: 'PRO', price: 49990000,
    description: 'Toàn bộ tính năng, không giới hạn quy mô.',
    groups: [
      { label: 'Cho HTX', features: [
        'Cấp mã nông hộ không giới hạn', 'Tính carbon mùa vụ không giới hạn',
        'Đầy đủ tính năng quản lý: nông hộ, vụ mùa, dữ liệu thiếu, carbon theo vụ, hiệu suất vùng, MRV',
      ] },
      { label: 'Cho nông dân', features: [
        'Ghi nhật ký canh tác', 'Tính hiệu suất đầy đủ', 'Trợ lý AI 1 triệu token/ngày',
      ] },
    ],
    suitableFor: ['HTX quy mô lớn, nhiều nông hộ', 'Quản lý tập trung cả vùng trồng'],
  },
]

export const JOURNAL_ACTIVITIES = ['Gieo sạ', 'Phân bón', 'Tưới nước', 'Rơm rạ', 'Thuốc BVTV', 'Thu hoạch']

export type PlanAudience = 'nong-ho' | 'hop-tac-xa'
export interface PlanSelection { audience: PlanAudience; audienceLabel: string; plan: ServicePlan }

/** URL intent is untrusted; resolve names against the displayed catalogue. */
export function readPlanSelection(search: string): PlanSelection | null {
  const params = new URLSearchParams(search)
  const audience = params.get('audience')
  if (audience !== 'nong-ho' && audience !== 'hop-tac-xa') return null
  const plan = (audience === 'nong-ho' ? FARMER_PLANS : COOPERATIVE_PLANS).find((item) => item.name === params.get('plan'))
  return plan ? { audience, audienceLabel: audience === 'nong-ho' ? 'Nông hộ' : 'Hợp tác xã', plan } : null
}

export function planSelectionPath(audience: string, plan: string): string {
  return `/chon-goi?${new URLSearchParams({ audience, plan })}`
}

/** Only the canonical local selection route can override the login landing. */
export function selectedPlanReturn(raw: string | null): string | null {
  if (!raw) return null
  const [path, search = ''] = raw.split('?')
  if (path !== '/chon-goi') return null
  const selection = readPlanSelection(search)
  return selection ? planSelectionPath(selection.audience, selection.plan.name) : null
}
