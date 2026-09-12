import 'dart:convert';

import 'sync_state.dart';

/// Loại bản ghi trong hàng đợi gửi dữ liệu.
enum SyncQueueKind { plot, cropSeason, activity }

/// Một dòng trong màn "Gửi dữ liệu" (SVG 23). Gộp từ 3 bảng local
/// (plots / crop_seasons / activities) đang `pending` hoặc `failed`.
///
/// KHÔNG bịa số: `subtitle` chỉ dùng dữ liệu THẬT người dùng đã nhập. Không có
/// dòng "ảnh" ở đây vì app chưa có bản ghi ảnh thật (CV chưa triển khai).
class SyncQueueItem {
  const SyncQueueItem({
    required this.kind,
    required this.clientId,
    required this.title,
    required this.subtitle,
    required this.syncState,
    required this.retryCount,
    this.errorCode,
    this.occurredAt,
    this.recordedAt,
    this.lastAttemptAt,
    this.isTombstone = false,
  });

  final SyncQueueKind kind;
  final String clientId;

  /// Dạng "loại công việc · mã thửa" — dựng từ dữ liệu thật của bản ghi.
  final String title;

  /// Dạng "ngày giờ · tóm tắt payload" — mốc `occurred_at` + số liệu thật.
  final String subtitle;

  final SyncState syncState;
  final int retryCount;
  final String? errorCode;

  /// Thời gian LÀM (activity `occurred_at`). Plot/CropSeason không có.
  final DateTime? occurredAt;

  /// Thời gian GHI trên máy (`created_at`).
  final DateTime? recordedAt;
  final DateTime? lastAttemptAt;
  final bool isTombstone;

  bool get isFailed => syncState == SyncState.failed;

  // --- Dựng từ hàng SQLite ------------------------------------------------

  factory SyncQueueItem.fromPlotRow(Map<String, dynamic> r) => SyncQueueItem(
        kind: SyncQueueKind.plot,
        clientId: r['id'] as String,
        title: 'Thửa ${r['plot_code']}',
        subtitle: _plotSubtitle(r),
        syncState: SyncStateCodec.fromValue(r['sync_state'] as String?),
        retryCount: (r['retry_count'] as int?) ?? 0,
        errorCode: r['sync_error_code'] as String?,
        recordedAt: _dt(r['created_at']),
        lastAttemptAt: _dt(r['last_attempt_at']),
      );

  factory SyncQueueItem.fromCropSeasonRow(Map<String, dynamic> r) =>
      SyncQueueItem(
        kind: SyncQueueKind.cropSeason,
        clientId: r['id'] as String,
        title: _joinDot([
          'Vụ ${r['season_code']}',
          r['_plot_code'] as String?,
        ]),
        subtitle: _joinDot([
          (r['variety_name'] as String?)?.trim().isNotEmpty == true
              ? 'Giống ${(r['variety_name'] as String).trim()}'
              : null,
          _dtShort(_dt(r['planting_date'])) != null
              ? 'gieo ${_dtShort(_dt(r['planting_date']))}'
              : null,
        ], fallback: 'Vụ canh tác mới'),
        syncState: SyncStateCodec.fromValue(r['sync_state'] as String?),
        retryCount: (r['retry_count'] as int?) ?? 0,
        errorCode: r['sync_error_code'] as String?,
        recordedAt: _dt(r['created_at']),
        lastAttemptAt: _dt(r['last_attempt_at']),
      );

  factory SyncQueueItem.fromActivityRow(Map<String, dynamic> r) {
    final type = r['type'] as String;
    final deleted = ((r['deleted_locally'] as int?) ?? 0) == 1;
    final occurred = _dt(r['occurred_at']);
    final payload = _decodePayload(r['payload_json']);
    final typeLabel = kSyncActivityLabels[type] ?? type;
    final plotCode = r['_plot_code'] as String?;
    return SyncQueueItem(
      kind: SyncQueueKind.activity,
      clientId: r['id'] as String,
      title: _joinDot([
        deleted ? 'Xoá $typeLabel' : typeLabel,
        plotCode,
      ]),
      subtitle: _joinDot([
        _dtShort(occurred),
        deleted ? 'đã đánh dấu xoá' : activityPayloadSummary(type, payload),
      ], fallback: deleted ? 'đã đánh dấu xoá' : 'chưa có chi tiết'),
      syncState: SyncStateCodec.fromValue(r['sync_state'] as String?),
      retryCount: (r['retry_count'] as int?) ?? 0,
      errorCode: r['sync_error'] as String?,
      occurredAt: occurred,
      recordedAt: _dt(r['created_at']),
      lastAttemptAt: _dt(r['last_attempt_at']),
      isTombstone: deleted,
    );
  }

  // --- Helpers ----------------------------------------------------------

  static Map<String, dynamic> _decodePayload(Object? raw) {
    if (raw is! String || raw.isEmpty) return const {};
    try {
      final d = jsonDecode(raw);
      return d is Map<String, dynamic> ? d : const {};
    } catch (_) {
      return const {};
    }
  }

  static String _plotSubtitle(Map<String, dynamic> r) {
    final area = (r['area_ha'] as num?)?.toDouble();
    final parts = <String?>[
      (r['name'] as String?)?.trim().isNotEmpty == true
          ? (r['name'] as String).trim()
          : null,
      area != null ? '${_trimNum(area)} ha' : null,
    ];
    return _joinDot(parts, fallback: 'Thửa ruộng mới');
  }

  static DateTime? _dt(Object? v) =>
      v is String && v.isNotEmpty ? DateTime.tryParse(v) : null;

  static String? _dtShort(DateTime? d) {
    if (d == null) return null;
    final l = d.toLocal();
    String p(int n) => n.toString().padLeft(2, '0');
    return '${p(l.day)}/${p(l.month)} ${p(l.hour)}:${p(l.minute)}';
  }

  static String _joinDot(List<String?> parts, {String fallback = ''}) {
    final kept = parts.where((s) => s != null && s.trim().isNotEmpty).toList();
    return kept.isEmpty ? fallback : kept.join(' · ');
  }

  static String _trimNum(num v) =>
      v == v.roundToDouble() ? v.toInt().toString() : v.toString();
}

/// Nhãn loại — tách bản riêng để `models/` không kéo `package:flutter` (IconData)
/// từ `activity_field_spec.dart`.
const kSyncActivityLabels = <String, String>{
  'seeding': 'Giống',
  'fertilizer': 'Bón phân',
  'irrigation': 'Tưới nước',
  'pesticide': 'Thuốc BVTV',
  'straw_management': 'Rơm rạ',
  'fuel': 'Xăng dầu',
  'harvest': 'Thu hoạch',
};

/// Tóm tắt 1 dòng cho payload — dùng cột "chính" của từng loại, đơn vị THẬT theo
/// schema (m³ / cm / kWh / kg / lít), KHÔNG "mm", KHÔNG quy đổi. `null` field →
/// bỏ, không hiện "0".
String? activityPayloadSummary(String type, Map<String, dynamic> payload) {
  num? n(String k) => payload[k] is num ? payload[k] as num : null;
  String num2(num v) => v == v.roundToDouble() ? v.toInt().toString() : '$v';
  String? withUnit(String k, String unit) {
    final v = n(k);
    return v == null ? null : '${num2(v)} $unit';
  }

  switch (type) {
    case 'seeding':
      return withUnit('seed_kg', 'kg');
    case 'fertilizer':
      return withUnit('amount_kg', 'kg');
    case 'irrigation':
      return withUnit('water_volume_m3', 'm³') ??
          withUnit('duration_minutes', 'phút') ??
          _selLabel(payload['method'], _kIrrigationMethod);
    case 'pesticide':
      final amount = n('amount');
      final unit = (payload['unit'] as String?)?.trim();
      if (amount != null && unit != null && unit.isNotEmpty) {
        return '${num2(amount)} $unit';
      }
      return amount != null ? num2(amount) : null;
    case 'fuel':
      return withUnit('amount_liter', 'lít');
    case 'straw_management':
      return withUnit('straw_mass_kg', 'kg') ??
          _selLabel(payload['method'], _kStrawMethod);
    case 'harvest':
      return withUnit('yield_kg', 'kg');
    default:
      return null;
  }
}

String? _selLabel(Object? raw, Map<String, String> labels) {
  final v = raw is String ? raw : null;
  if (v == null) return null;
  return labels[v] ?? v;
}

const _kIrrigationMethod = {
  'awd': 'Ngập-khô xen kẽ',
  'continuous_flooding': 'Ngập liên tục',
  'alternate': 'Xen kẽ',
  'other': 'Cách khác',
};
const _kStrawMethod = {
  'incorporated': 'Vùi vào đất',
  'removed': 'Mang khỏi ruộng',
  'burned': 'Đốt tại ruộng',
  'composted': 'Ủ compost',
  'other': 'Cách khác',
};
