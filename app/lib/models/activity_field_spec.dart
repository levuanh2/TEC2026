/// Đặc tả field cho từng loại Activity — 1 form render động thay vì 7 file gần
/// giống nhau. Field `key` khớp thẳng tên cột bảng chi tiết trên Supabase
/// (xem sync_service.dart) để không cần một tầng đổi tên nào ở giữa.
/// `nullableBoolean` khác `boolean` ở chỗ có 3 trạng thái: Có / Không / CHƯA CHỌN.
/// Dùng cho field mà backend coi "chưa biết" khác hẳn "false" (methodology input
/// như `returned_to_field` — không được tự default, xem CARBON_METHOD.md).
/// `boolean` (2 trạng thái, mặc định false) chỉ dùng cho field KHÔNG ảnh hưởng
/// methodology (hiện chưa field nào dùng, giữ lại cho tương lai).
enum FieldKind { text, number, integer, select, boolean, nullableBoolean }

class FieldOption {
  const FieldOption(this.value, this.label);
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
  });

  final String key;
  final String label;
  final FieldKind kind;
  final bool required;
  final List<FieldOption> options;
  final String? hint;
}

/// Nhãn tiếng Việt cho từng loại hoạt động — dùng ở màn chọn loại + tiêu đề form.
const kActivityTypeLabels = <String, String>{
  'seeding': '🌱 Giống',
  'fertilizer': '🌾 Phân bón',
  'irrigation': '💧 Nước tưới',
  'pesticide': '🧪 Thuốc bảo vệ thực vật',
  'straw_management': '🌾 Rơm rạ',
  'fuel': '🚜 Nhiên liệu',
  'harvest': '🌾 Thu hoạch',
};

const kActivityFieldSpecs = <String, List<ActivityFieldSpec>>{
  'seeding': [
    ActivityFieldSpec(key: 'variety_name', label: 'Tên giống', kind: FieldKind.text),
    ActivityFieldSpec(
      key: 'seed_kg',
      label: 'Lượng giống gieo sạ (kg)',
      kind: FieldKind.number,
      required: true,
    ),
    ActivityFieldSpec(
      key: 'seeding_method',
      label: 'Phương thức gieo sạ',
      kind: FieldKind.select,
      options: [
        FieldOption('sạ lan', 'Sạ lan'),
        FieldOption('sạ hàng', 'Sạ hàng'),
        FieldOption('cấy', 'Cấy'),
      ],
    ),
    ActivityFieldSpec(key: 'cost_vnd', label: 'Chi phí (đồng)', kind: FieldKind.number),
  ],
  'fertilizer': [
    ActivityFieldSpec(
      key: 'fertilizer_name',
      label: 'Tên phân',
      kind: FieldKind.text,
      required: true,
    ),
    ActivityFieldSpec(key: 'fertilizer_type', label: 'Loại phân', kind: FieldKind.text),
    ActivityFieldSpec(
      key: 'amount_kg',
      label: 'Khối lượng (kg)',
      kind: FieldKind.number,
      required: true,
    ),
    ActivityFieldSpec(
      key: 'nitrogen_percent',
      label: '% N (đạm)',
      kind: FieldKind.number,
      hint: 'Quan trọng cho tính toán carbon — ghi đúng % trên bao phân',
    ),
    ActivityFieldSpec(key: 'phosphorus_percent', label: '% P (lân)', kind: FieldKind.number),
    ActivityFieldSpec(key: 'potassium_percent', label: '% K (kali)', kind: FieldKind.number),
    ActivityFieldSpec(key: 'total_cost_vnd', label: 'Chi phí (đồng)', kind: FieldKind.number),
  ],
  'irrigation': [
    ActivityFieldSpec(
      key: 'method',
      label: 'Chế độ tưới',
      kind: FieldKind.select,
      required: true,
      options: [
        FieldOption('awd', 'Ngập-khô xen kẽ (AWD)'),
        FieldOption('continuous_flooding', 'Ngập liên tục'),
      ],
    ),
    ActivityFieldSpec(key: 'water_volume_m3', label: 'Lượng nước (m³)', kind: FieldKind.number),
    ActivityFieldSpec(key: 'water_level_cm', label: 'Mực nước (cm)', kind: FieldKind.number),
    ActivityFieldSpec(key: 'pump_energy_kwh', label: 'Điện bơm (kWh)', kind: FieldKind.number),
    ActivityFieldSpec(key: 'total_cost_vnd', label: 'Chi phí (đồng)', kind: FieldKind.number),
  ],
  'pesticide': [
    ActivityFieldSpec(key: 'product_name', label: 'Tên thuốc', kind: FieldKind.text, required: true),
    ActivityFieldSpec(key: 'active_ingredient', label: 'Hoạt chất', kind: FieldKind.text),
    ActivityFieldSpec(key: 'amount', label: 'Lượng dùng', kind: FieldKind.number, required: true),
    ActivityFieldSpec(
      key: 'unit',
      label: 'Đơn vị (lít/kg/gói...)',
      kind: FieldKind.text,
      required: true,
    ),
    ActivityFieldSpec(key: 'total_cost_vnd', label: 'Chi phí (đồng)', kind: FieldKind.number),
  ],
  'straw_management': [
    ActivityFieldSpec(
      key: 'method',
      label: 'Phương thức xử lý',
      kind: FieldKind.select,
      required: true,
      options: [
        FieldOption('incorporated', 'Vùi vào đất'),
        FieldOption('removed', 'Mang khỏi ruộng'),
        FieldOption('burned', 'Đốt'),
        FieldOption('composted', 'Ủ compost'),
      ],
    ),
    ActivityFieldSpec(key: 'straw_mass_kg', label: 'Khối lượng rơm (kg)', kind: FieldKind.number),
    ActivityFieldSpec(
      key: 'dry_matter_fraction',
      label: 'Tỷ lệ chất khô (0–1)',
      kind: FieldKind.number,
      hint: 'Để trống nếu chưa rõ — hệ thống sẽ báo khi cần bổ sung, không tự đoán',
    ),
    ActivityFieldSpec(
      key: 'days_before_cultivation',
      label: 'Số ngày trước khi gieo sạ',
      kind: FieldKind.integer,
      hint: 'Chỉ áp dụng khi vùi vào đất',
    ),
    ActivityFieldSpec(
      key: 'returned_to_field',
      label: 'Có trả lại ruộng không',
      kind: FieldKind.nullableBoolean,
      hint: 'Chỉ áp dụng khi ủ compost. Để "Chưa rõ" nếu không chắc — '
          'KHÔNG mặc định là "Không", hệ thống sẽ hỏi lại khi cần.',
    ),
    ActivityFieldSpec(key: 'total_cost_vnd', label: 'Chi phí (đồng)', kind: FieldKind.number),
  ],
  'fuel': [
    ActivityFieldSpec(
      key: 'fuel_type',
      label: 'Loại nhiên liệu',
      kind: FieldKind.select,
      required: true,
      options: [
        FieldOption('diesel', 'Dầu diesel'),
        FieldOption('gasoline', 'Xăng'),
        FieldOption('lpg', 'Gas (LPG)'),
      ],
    ),
    ActivityFieldSpec(key: 'amount_liter', label: 'Số lít', kind: FieldKind.number, required: true),
    ActivityFieldSpec(key: 'equipment_name', label: 'Thiết bị/máy', kind: FieldKind.text),
    ActivityFieldSpec(key: 'total_cost_vnd', label: 'Chi phí (đồng)', kind: FieldKind.number),
  ],
  'harvest': [
    ActivityFieldSpec(
      key: 'yield_kg',
      label: 'Sản lượng (kg)',
      kind: FieldKind.number,
      required: true,
      hint: 'Đây là mẫu số của CO2e/kg — chưa nhập thì chưa tính được',
    ),
    ActivityFieldSpec(
      key: 'harvested_area_ha',
      label: 'Diện tích thu hoạch (ha)',
      kind: FieldKind.number,
    ),
    ActivityFieldSpec(key: 'moisture_percent', label: 'Độ ẩm (%)', kind: FieldKind.number),
    ActivityFieldSpec(key: 'total_cost_vnd', label: 'Chi phí (đồng)', kind: FieldKind.number),
  ],
};
