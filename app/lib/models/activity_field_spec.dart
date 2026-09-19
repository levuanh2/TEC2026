import 'package:flutter/material.dart';

/// Đặc tả field cho từng loại Activity — 1 form render động. `key` khớp TUYỆT ĐỐI
/// tên cột bảng chi tiết trên Supabase (đọc `supabase/migrations/`), không có
/// tầng đổi tên nào ở giữa.
///
/// `required` ở đây là bắt buộc KHÔNG điều kiện. Ràng buộc có điều kiện
/// (incorporated cần dry_matter + days...) nằm ở `activity_validation.dart`.
enum ActivityFieldKind {
  text,
  decimal,
  integer,
  select,

  /// 3 trạng thái Có / Không / Chưa chọn. Payload: `true` / `false` / (bỏ key khi
  /// "chưa rõ" — KHÔNG default `false`, xem CARBON_METHOD.md `returned_to_field`).
  tristate,
}

class ActivityOption {
  const ActivityOption(this.value, this.label);
  final String value;
  final String label;
}

class ActivityFieldSpec {
  const ActivityFieldSpec({
    required this.key,
    required this.label,
    required this.kind,
    this.required = false,
    this.options = const [],
    this.hint,
    this.unit,
    this.positive = false, // > 0
    this.nonNegative = false, // >= 0
    this.min,
    this.max,
  });

  final String key;
  final String label;
  final ActivityFieldKind kind;
  final bool required;
  final List<ActivityOption> options;
  final String? hint;
  final String? unit;
  final bool positive;
  final bool nonNegative;
  final num? min;
  final num? max;
}

/// Nhãn tiếng Việt cho từng loại — KHÔNG dùng emoji làm icon (dùng
/// [kActivityTypeIcons]).
const kActivityTypeLabels = <String, String>{
  'seeding': 'Giống',
  'fertilizer': 'Bón phân',
  'irrigation': 'Tưới nước',
  'pesticide': 'Thuốc BVTV',
  'straw_management': 'Rơm rạ',
  'fuel': 'Xăng dầu',
  'harvest': 'Thu hoạch',
};

const kActivityTypeIcons = <String, IconData>{
  'seeding': Icons.spa_outlined,
  'fertilizer': Icons.science_outlined,
  'irrigation': Icons.water_drop_outlined,
  'pesticide': Icons.pest_control_outlined,
  'straw_management': Icons.recycling_outlined,
  'fuel': Icons.local_gas_station_outlined,
  'harvest': Icons.agriculture_outlined,
};

/// 4 shortcut bám SVG 22 (Tưới / Bón phân / Xăng dầu / Rơm rạ).
const kQuickLogShortcuts = <String>[
  'irrigation',
  'fertilizer',
  'fuel',
  'straw_management',
];

const _costField = ActivityFieldSpec(
  key: 'total_cost_vnd',
  label: 'Chi phí',
  kind: ActivityFieldKind.decimal,
  unit: 'đồng',
  nonNegative: true,
);

const kActivityFieldSpecs = <String, List<ActivityFieldSpec>>{
  // -- seeding_events -----------------------------------------------------
  'seeding': [
    ActivityFieldSpec(
      key: 'variety_name',
      label: 'Tên giống',
      kind: ActivityFieldKind.text,
    ),
    ActivityFieldSpec(
      key: 'seed_kg',
      label: 'Lượng giống gieo sạ',
      kind: ActivityFieldKind.decimal,
      unit: 'kg',
      required: true,
      positive: true,
    ),
    ActivityFieldSpec(
      key: 'seeding_method',
      label: 'Phương thức gieo sạ',
      kind: ActivityFieldKind.select,
      options: [
        ActivityOption('sa_lan', 'Sạ lan'),
        ActivityOption('sa_hang', 'Sạ hàng'),
        ActivityOption('cay', 'Cấy'),
      ],
    ),
    ActivityFieldSpec(
      key: 'cost_vnd',
      label: 'Chi phí',
      kind: ActivityFieldKind.decimal,
      unit: 'đồng',
      nonNegative: true,
    ),
  ],

  // -- fertilizer_applications -----------------------------------------
  'fertilizer': [
    ActivityFieldSpec(
      key: 'fertilizer_name',
      label: 'Tên phân',
      kind: ActivityFieldKind.text,
      required: true,
    ),
    ActivityFieldSpec(
      key: 'fertilizer_type',
      label: 'Loại phân',
      kind: ActivityFieldKind.text,
    ),
    ActivityFieldSpec(
      key: 'amount_kg',
      label: 'Khối lượng',
      kind: ActivityFieldKind.decimal,
      unit: 'kg',
      required: true,
      positive: true,
    ),
    ActivityFieldSpec(
      key: 'nitrogen_percent',
      label: '% đạm (N)',
      kind: ActivityFieldKind.decimal,
      unit: '%',
      min: 0,
      max: 100,
      hint: 'Ghi đúng số in trên bao phân — quan trọng cho tính phát thải',
    ),
    ActivityFieldSpec(
      key: 'phosphorus_percent',
      label: '% lân (P)',
      kind: ActivityFieldKind.decimal,
      unit: '%',
      min: 0,
      max: 100,
    ),
    ActivityFieldSpec(
      key: 'potassium_percent',
      label: '% kali (K)',
      kind: ActivityFieldKind.decimal,
      unit: '%',
      min: 0,
      max: 100,
    ),
    _costField,
  ],

  // -- irrigation_events ---------------------------------------------------
  'irrigation': [
    ActivityFieldSpec(
      key: 'method',
      label: 'Cách tưới',
      kind: ActivityFieldKind.select,
      required: true,
      options: [
        ActivityOption('awd', 'Ngập - khô xen kẽ (AWD)'),
        ActivityOption('continuous_flooding', 'Ngập liên tục'),
        ActivityOption('alternate', 'Xen kẽ kiểu khác'),
        ActivityOption('other', 'Cách khác'),
      ],
    ),
    ActivityFieldSpec(
      key: 'water_volume_m3',
      label: 'Lượng nước',
      kind: ActivityFieldKind.decimal,
      unit: 'm³',
      nonNegative: true,
      hint:
          'Nhập theo m³. Không quy đổi từ mm nếu chưa có công thức được duyệt.',
    ),
    ActivityFieldSpec(
      key: 'duration_minutes',
      label: 'Thời gian tưới',
      kind: ActivityFieldKind.integer,
      unit: 'phút',
      nonNegative: true,
    ),
    ActivityFieldSpec(
      key: 'water_level_cm',
      label: 'Mực nước trên ruộng',
      kind: ActivityFieldKind.decimal,
      unit: 'cm',
      nonNegative: true,
    ),
    ActivityFieldSpec(
      key: 'pump_energy_kwh',
      label: 'Điện bơm',
      kind: ActivityFieldKind.decimal,
      unit: 'kWh',
      nonNegative: true,
    ),
    _costField,
  ],

  // -- pesticide_applications --------------------------------------------
  'pesticide': [
    ActivityFieldSpec(
      key: 'product_name',
      label: 'Tên thuốc',
      kind: ActivityFieldKind.text,
      required: true,
    ),
    ActivityFieldSpec(
      key: 'active_ingredient',
      label: 'Hoạt chất',
      kind: ActivityFieldKind.text,
    ),
    ActivityFieldSpec(
      key: 'amount',
      label: 'Lượng dùng',
      kind: ActivityFieldKind.decimal,
      required: true,
      positive: true,
    ),
    ActivityFieldSpec(
      key: 'unit',
      label: 'Đơn vị (lít / kg / gói...)',
      kind: ActivityFieldKind.text,
      required: true,
    ),
    _costField,
  ],

  // -- fuel_usages ------------------------------------------------------
  'fuel': [
    ActivityFieldSpec(
      key: 'fuel_type',
      label: 'Loại nhiên liệu',
      kind: ActivityFieldKind.select,
      required: true,
      options: [
        ActivityOption('diesel', 'Dầu diesel'),
        ActivityOption('gasoline', 'Xăng'),
        ActivityOption('lpg', 'Gas (LPG)'),
        ActivityOption('other', 'Loại khác'),
      ],
    ),
    ActivityFieldSpec(
      key: 'amount_liter',
      label: 'Số lít',
      kind: ActivityFieldKind.decimal,
      unit: 'lít',
      required: true,
      positive: true,
    ),
    ActivityFieldSpec(
      key: 'equipment_name',
      label: 'Thiết bị / máy',
      kind: ActivityFieldKind.text,
    ),
    _costField,
  ],

  // -- straw_management_events -----------------------------------------
  'straw_management': [
    ActivityFieldSpec(
      key: 'method',
      label: 'Cách xử lý rơm',
      kind: ActivityFieldKind.select,
      required: true,
      options: [
        ActivityOption('incorporated', 'Vùi vào đất'),
        ActivityOption('removed', 'Mang khỏi ruộng'),
        ActivityOption('burned', 'Đốt tại ruộng'),
        ActivityOption('composted', 'Ủ compost'),
        ActivityOption('other', 'Cách khác'),
      ],
    ),
    ActivityFieldSpec(
      key: 'straw_mass_kg',
      label: 'Khối lượng rơm',
      kind: ActivityFieldKind.decimal,
      unit: 'kg',
      nonNegative: true,
    ),
    ActivityFieldSpec(
      key: 'dry_matter_fraction',
      label: 'Tỷ lệ chất khô',
      kind: ActivityFieldKind.decimal,
      positive: true, // schema: > 0 và <= 1
      max: 1,
      hint: 'Số lớn hơn 0, tối đa 1 (ví dụ 0,85) — không phải phần trăm.',
    ),
    ActivityFieldSpec(
      key: 'days_before_cultivation',
      label: 'Số ngày trước khi bắt đầu canh tác',
      kind: ActivityFieldKind.integer,
      unit: 'ngày',
      nonNegative: true,
      hint: 'Số nguyên, 0 trở lên.',
    ),
    ActivityFieldSpec(
      key: 'returned_to_field',
      label: 'Compost có trả lại chính ruộng này?',
      kind: ActivityFieldKind.tristate,
      hint: 'Cần khi ủ compost. Chưa chắc thì để "Chưa chọn" — hệ thống '
          'KHÔNG tự hiểu là "Không".',
    ),
    _costField,
  ],

  // -- harvest_events -------------------------------------------------
  'harvest': [
    ActivityFieldSpec(
      key: 'yield_kg',
      label: 'Sản lượng thu hoạch',
      kind: ActivityFieldKind.decimal,
      unit: 'kg',
      required: true,
      positive: true,
      hint: 'Đây là mẫu số của CO₂e/kg — chưa nhập thì chưa tính được.',
    ),
    ActivityFieldSpec(
      key: 'harvested_area_ha',
      label: 'Diện tích thu hoạch',
      kind: ActivityFieldKind.decimal,
      unit: 'ha',
      positive: true,
    ),
    ActivityFieldSpec(
      key: 'moisture_percent',
      label: 'Độ ẩm hạt',
      kind: ActivityFieldKind.decimal,
      unit: '%',
      min: 0,
      max: 100,
    ),
    _costField,
  ],
};
