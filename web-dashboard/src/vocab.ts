/* Every raw database value the UI is allowed to show, in Vietnamese.
 *
 * The audit found `active`, `draft`, `awd`, `incorporated`, `diesel` and `web`
 * rendered straight from the column onto a farmer's screen. Two different
 * presenters each mapped a subset, so the same value read one way on the home
 * screen and another in the journal. This is the single dictionary both use.
 *
 * It maps for display only. Stored values never change — `label()` takes the
 * raw string and returns words; nothing here is ever written back.
 */

/** `public.crop_status` */
const CROP_STATUS: Record<string, string> = {
  planned: 'Dự kiến',
  active: 'Đang canh tác',
  harvested: 'Đã thu hoạch',
  closed: 'Đã kết thúc',
  cancelled: 'Đã huỷ',
}

/** `public.irrigation_method` — the water regime a farmer chose. */
const IRRIGATION_METHOD: Record<string, string> = {
  awd: 'Tưới ngập–khô xen kẽ (AWD)',
  continuous_flooding: 'Ngập liên tục',
  alternate: 'Tưới luân phiên',
  other: 'Cách khác',
}

/** `public.straw_management_method` */
const STRAW_METHOD: Record<string, string> = {
  incorporated: 'Vùi vào đất',
  removed: 'Mang khỏi ruộng',
  burned: 'Đốt tại ruộng',
  composted: 'Ủ compost',
  other: 'Cách khác',
}

/** `public.fuel_type` */
const FUEL_TYPE: Record<string, string> = {
  diesel: 'Dầu diesel',
  gasoline: 'Xăng',
  lpg: 'Khí hoá lỏng (LPG)',
  other: 'Loại khác',
}

/** `public.activity_type` */
const ACTIVITY_TYPE: Record<string, string> = {
  seeding: 'Gieo sạ',
  fertilizer: 'Bón phân',
  irrigation: 'Tưới nước',
  pesticide: 'Thuốc bảo vệ thực vật',
  fuel: 'Nhiên liệu',
  straw_management: 'Quản lý rơm rạ',
  harvest: 'Thu hoạch',
  other: 'Hoạt động khác',
}

/** `public.data_source` — how the record reached the system. */
const DATA_SOURCE: Record<string, string> = {
  mobile_offline: 'Ứng dụng di động (ngoại tuyến)',
  mobile_online: 'Ứng dụng di động',
  web: 'Ứng dụng web',
  api: 'Kết nối API',
  import: 'Nhập từ tệp',
  system: 'Hệ thống tạo',
}

/** `public.mrv_case_status` — the case itself, NOT its six steps. Mixing the
 *  two is what made a case in progress report "Chưa bắt đầu". */
const MRV_CASE_STATUS: Record<string, string> = {
  draft: 'Bản nháp',
  in_progress: 'Đang thực hiện',
  ready_for_verification: 'Chờ thẩm định',
  verified: 'Đã thẩm định',
  closed: 'Đã đóng hồ sơ',
}

/** `public.mrv_step_status` */
const MRV_STEP_STATUS: Record<string, string> = {
  not_started: 'Chưa bắt đầu',
  in_progress: 'Đang thực hiện',
  completed: 'Hoàn thành',
  blocked: 'Bị chặn',
}

/** IPCC water regime during the season (`public.ipcc_water_regime`). */
const IPCC_WATER_REGIME: Record<string, string> = {
  irrigated_continuous_flooding: 'Tưới — ngập liên tục',
  irrigated_single_drainage: 'Tưới — rút nước một lần',
  irrigated_multiple_drainage: 'Tưới — rút nước nhiều lần',
  rainfed_regular: 'Nước trời — thường xuyên',
  rainfed_drought_prone: 'Nước trời — dễ hạn',
  deep_water: 'Ruộng nước sâu',
  upland: 'Ruộng cạn',
}

/** IPCC pre-season regime (`public.ipcc_pre_season_regime`). */
const IPCC_PRE_SEASON: Record<string, string> = {
  non_flooded_pre_season_lt_180d: 'Không ngập trước vụ, dưới 180 ngày',
  non_flooded_pre_season_gt_180d: 'Không ngập trước vụ, trên 180 ngày',
  flooded_pre_season_gt_30d: 'Ngập trước vụ, trên 30 ngày',
  non_flooded_pre_season_gt_365d: 'Không ngập trước vụ, trên 365 ngày',
}

/** Carbon water-regime scenario (`public.carbon_scenario`). */
const CARBON_SCENARIO: Record<string, string> = {
  as_recorded: 'Theo ghi nhận',
  awd: 'AWD (rút nước)',
  continuous_flooding: 'Ngập liên tục',
}

const DICTS = {
  cropStatus: CROP_STATUS,
  irrigationMethod: IRRIGATION_METHOD,
  strawMethod: STRAW_METHOD,
  fuelType: FUEL_TYPE,
  activityType: ACTIVITY_TYPE,
  dataSource: DATA_SOURCE,
  mrvCaseStatus: MRV_CASE_STATUS,
  mrvStepStatus: MRV_STEP_STATUS,
  ipccWaterRegime: IPCC_WATER_REGIME,
  ipccPreSeason: IPCC_PRE_SEASON,
  carbonScenario: CARBON_SCENARIO,
} as const

export type VocabKind = keyof typeof DICTS

/**
 * Vietnamese wording for one stored value.
 *
 * An unknown value falls back to `fallback` rather than to itself: a raw enum
 * that slipped through must read as "Chưa rõ", never as `in_review`.
 */
export function label(kind: VocabKind, value: string | null | undefined, fallback = 'Chưa rõ'): string {
  if (value == null || value === '') return fallback
  return DICTS[kind][String(value).toLowerCase()] ?? fallback
}

/** True when a value is one this dictionary knows — for tests and guards. */
export const known = (kind: VocabKind, value: string | null | undefined): boolean =>
  value != null && String(value).toLowerCase() in DICTS[kind]

/** Season status, the wording used on every screen. */
export const seasonStatus = (value: string | null | undefined) =>
  label('cropStatus', value, 'Chưa rõ trạng thái')

/** Any raw value that must never reach a user, for the guard in tests. */
export const RAW_ENUM_VALUES: string[] = [
  ...new Set(Object.values(DICTS).flatMap((d) => Object.keys(d))),
]
