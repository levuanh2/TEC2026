/// Enum phương pháp luận của Crop Season — giá trị `wire` phải KHỚP TUYỆT ĐỐI
/// enum tương ứng trên Supabase (`supabase/migrations/`), không tự đổi tên.
/// `labelVi` là câu giải thích cho nông dân (NFR-06: không thuật ngữ hàn lâm).
library;

/// `crop_seasons.default_irrigation_method` — `public.irrigation_method`.
/// Cách nông dân mô tả việc tưới; KHÁC `ipccWaterRegime` (phân loại IPCC chi tiết).
enum DefaultIrrigationMethod {
  awd('awd', 'Ngập - khô xen kẽ (AWD)'),
  continuousFlooding('continuous_flooding', 'Ngập nước liên tục'),
  alternate('alternate', 'Xen kẽ kiểu khác'),
  other('other', 'Cách khác');

  const DefaultIrrigationMethod(this.wire, this.labelVi);
  final String wire;
  final String labelVi;

  static DefaultIrrigationMethod? fromWire(String? wire) =>
      _fromWire(DefaultIrrigationMethod.values, wire);
}

/// `crop_seasons.ipcc_water_regime` — `public.ipcc_water_regime` (IPCC Table 5.12).
enum IpccWaterRegime {
  irrigatedContinuousFlooding(
    'irrigated_continuous_flooding',
    'Chủ động tưới, ngập nước gần như suốt vụ',
  ),
  irrigatedSingleDrainage(
    'irrigated_single_drainage',
    'Chủ động tưới, rút nước 1 lần giữa vụ',
  ),
  irrigatedMultipleDrainage(
    'irrigated_multiple_drainage',
    'Chủ động tưới, rút nước nhiều lần (gồm AWD)',
  ),
  rainfedRegular(
    'rainfed_regular',
    'Nhờ nước trời, thường đủ nước',
  ),
  rainfedDroughtProne(
    'rainfed_drought_prone',
    'Nhờ nước trời, hay bị thiếu nước',
  ),
  deepWater(
    'deep_water',
    'Ruộng nước sâu (trên 50 cm)',
  ),
  upland(
    'upland',
    'Lúa cạn / lúa nương (không ngập)',
  );

  const IpccWaterRegime(this.wire, this.labelVi);
  final String wire;
  final String labelVi;

  static IpccWaterRegime? fromWire(String? wire) =>
      _fromWire(IpccWaterRegime.values, wire);
}

/// `crop_seasons.pre_season_water_regime` — `public.ipcc_pre_season_regime`
/// (IPCC Table 5.13). Chế độ nước của ruộng TRƯỚC khi gieo sạ vụ này — ảnh
/// hưởng mạnh tới phát thải CH4 (ngập trước vụ >30 ngày làm hệ số hơn gấp đôi).
enum PreSeasonWaterRegime {
  nonFloodedLt180d(
    'non_flooded_pre_season_lt_180d',
    'Ruộng để khô (không ngập) dưới 6 tháng trước khi gieo',
  ),
  nonFloodedGt180d(
    'non_flooded_pre_season_gt_180d',
    'Ruộng để khô trên 6 tháng trước khi gieo',
  ),
  floodedGt30d(
    'flooded_pre_season_gt_30d',
    'Ruộng ngập nước từ 1 tháng trở lên trước khi gieo',
  ),
  nonFloodedGt365d(
    'non_flooded_pre_season_gt_365d',
    'Ruộng bỏ khô trên 1 năm trước khi gieo',
  );

  const PreSeasonWaterRegime(this.wire, this.labelVi);
  final String wire;
  final String labelVi;

  static PreSeasonWaterRegime? fromWire(String? wire) =>
      _fromWire(PreSeasonWaterRegime.values, wire);
}

/// `crop_seasons.status` — `public.crop_status`.
enum CropSeasonStatus {
  planned('planned', 'Đã lên kế hoạch'),
  active('active', 'Đang canh tác'),
  harvested('harvested', 'Đã thu hoạch'),
  closed('closed', 'Đã chốt'),
  cancelled('cancelled', 'Đã huỷ');

  const CropSeasonStatus(this.wire, this.labelVi);
  final String wire;
  final String labelVi;

  static CropSeasonStatus fromWire(String? wire) =>
      _fromWire(CropSeasonStatus.values, wire) ?? CropSeasonStatus.planned;
}

/// Vụ còn nhận ghi / sửa công việc trên máy không. `active` là trạng thái hệ
/// thống nhận hoạt động; `planned` (bản app cũ) vẫn cho ghi trên máy vì lượt
/// đồng bộ sẽ chuyển vụ sang `active` trước khi gửi công việc. Vụ đã thu
/// hoạch / chốt / huỷ thì không — cơ sở dữ liệu cũng từ chối.
bool seasonAcceptsActivities(CropSeasonStatus status) =>
    status == CropSeasonStatus.active || status == CropSeasonStatus.planned;

T? _fromWire<T extends Enum>(List<T> values, String? wire) {
  if (wire == null) return null;
  for (final v in values) {
    if ((v as dynamic).wire == wire) return v;
  }
  return null;
}
