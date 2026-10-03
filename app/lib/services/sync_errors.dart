import 'package:supabase_flutter/supabase_flutter.dart' show PostgrestException;

/// Phân loại lỗi khi đẩy dữ liệu lên Supabase thành mã ngắn để lưu vào
/// `sync_error_code` và để UI phân biệt "lỗi mạng" (thử lại được) với "bị từ
/// chối quyền" (RLS — phải liên hệ quản lý HTX, thử lại vô ích).
enum SyncErrorKind {
  network,
  rlsDenied,
  auth,
  duplicate,
  validation,

  /// Máy chủ không xác nhận đã ghi (update trả 0 dòng / dòng lạ) — không phải
  /// exception, nhưng cũng KHÔNG được coi là thành công.
  notConfirmed,

  /// Vụ đã kết thúc (hoặc chưa bắt đầu) trên hệ thống: cơ sở dữ liệu từ chối
  /// ghi/sửa/xoá hoạt động của vụ đó (SQLSTATE 55000 `crop_season_not_open`),
  /// hoặc từ chối mở lại vụ (`illegal_crop_season_transition`). Vĩnh viễn:
  /// thử lại y nguyên sẽ luôn hỏng, và app KHÔNG tự mở lại vụ.
  seasonClosed,

  /// Diện tích thu hoạch lớn hơn diện tích thửa: máy từ chối gửi (kiểm tra
  /// trước khi đẩy) hoặc cơ sở dữ liệu từ chối (SQLSTATE 23514,
  /// `harvested_area_exceeds_plot`). Vĩnh viễn: phải SỬA bản ghi, gửi lại y
  /// nguyên luôn hỏng.
  harvestAreaExceedsPlot,
  unknown,
}

SyncErrorKind classifySyncError(Object error) {
  if (error is PostgrestException) {
    final code = error.code ?? '';
    final msg = error.message.toLowerCase();
    // Trước RLS: một lỗi vòng đời vụ có mã và thông điệp riêng (migration
    // 20260926090000), không phải "không có quyền".
    if (code == '55000' ||
        msg.contains('crop_season_not_open') ||
        msg.contains('illegal_crop_season_transition')) {
      return SyncErrorKind.seasonClosed;
    }
    // Trước lớp chung `23xxx` (validation): lỗi này có cách sửa riêng.
    if (msg.contains('harvested_area_exceeds_plot')) {
      return SyncErrorKind.harvestAreaExceedsPlot;
    }
    if (code == '42501' ||
        msg.contains('row-level security') ||
        msg.contains('permission denied')) {
      return SyncErrorKind.rlsDenied;
    }
    if (code.startsWith('PGRST3') ||
        msg.contains('jwt') ||
        msg.contains('not authorized')) {
      return SyncErrorKind.auth;
    }
    if (code == '23505') return SyncErrorKind.duplicate;
    if (code.startsWith('23') || code == '22P02') {
      return SyncErrorKind.validation;
    }
    return SyncErrorKind.unknown;
  }

  final text = error.toString().toLowerCase();
  if (text.contains('socketexception') ||
      text.contains('failed host lookup') ||
      text.contains('clientexception') ||
      text.contains('connection refused') ||
      text.contains('connection closed') ||
      text.contains('network is unreachable') ||
      text.contains('timed out')) {
    return SyncErrorKind.network;
  }
  return SyncErrorKind.unknown;
}

String syncErrorCode(Object error) => classifySyncError(error).name;

/// Số lần thử lại tối đa cho một lỗi TẠM THỜI trước khi hàng đợi thôi tự chọn
/// lại bản ghi đó. Nông dân vẫn gửi tay được từ màn hình Đồng bộ.
const int kMaxSyncAttempts = 5;

extension SyncErrorKindRetry on SyncErrorKind {
  /// Thử lại có cơ hội thành công mà KHÔNG cần ai sửa gì.
  ///
  /// `notConfirmed` nằm ở đây vì idempotency `(device_id, client_event_id)` bảo
  /// vệ: lần thử lại tìm thấy bản ghi cũ thay vì tạo bản trùng.
  /// `unknown` cũng thử lại — nhưng có trần, nên một lỗi lạ không thành bão
  /// request.
  bool get isTransient => switch (this) {
        SyncErrorKind.network => true,
        SyncErrorKind.notConfirmed => true,
        SyncErrorKind.unknown => true,
        SyncErrorKind.rlsDenied => false,
        SyncErrorKind.auth => false,
        SyncErrorKind.duplicate => false,
        SyncErrorKind.validation => false,
        SyncErrorKind.seasonClosed => false,
        SyncErrorKind.harvestAreaExceedsPlot => false,
      };

  /// Thử lại y nguyên payload/phiên hiện tại sẽ luôn hỏng như cũ — phải có ai
  /// đó can thiệp (cấp quyền, đăng nhập lại, sửa dữ liệu).
  bool get isPermanent => !isTransient;
}

/// Tên các lỗi TẠM THỜI, dạng chuỗi để ghép thẳng vào mệnh đề SQL của hàng đợi.
final List<String> kTransientErrorCodes = [
  for (final k in SyncErrorKind.values)
    if (k.isTransient) k.name,
];

/// Thông báo tiếng Việt cho nông dân — KHÔNG kèm exception thô.
String syncErrorMessage(SyncErrorKind kind) {
  switch (kind) {
    case SyncErrorKind.network:
      return 'Không có mạng hoặc mất kết nối — dữ liệu vẫn được lưu trên máy, '
          'sẽ tự gửi lại khi có mạng.';
    case SyncErrorKind.rlsDenied:
      return 'Bạn không có quyền lưu mục này lên hệ thống. Liên hệ quản lý HTX '
          'để được cấp quyền.';
    case SyncErrorKind.auth:
      return 'Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại rồi thử gửi lại.';
    case SyncErrorKind.duplicate:
      return 'Mục này đã có trên hệ thống.';
    case SyncErrorKind.validation:
      return 'Dữ liệu chưa hợp lệ để gửi lên hệ thống. Kiểm tra lại các ô đã nhập.';
    case SyncErrorKind.notConfirmed:
      return 'Máy chủ chưa xác nhận thao tác. Dữ liệu vẫn giữ trên máy, sẽ thử lại.';
    case SyncErrorKind.unknown:
      return 'Chưa gửi được lên hệ thống. Sẽ thử lại sau.';
    case SyncErrorKind.seasonClosed:
      return 'Vụ này đã kết thúc trên hệ thống nên không nhận thêm thay đổi. '
          'Bản ghi vẫn giữ trên máy; liên hệ cán bộ HTX nếu cần ghi bổ sung.';
    case SyncErrorKind.harvestAreaExceedsPlot:
      return 'Diện tích thu hoạch lớn hơn diện tích thửa. Mở bản ghi, sửa diện '
          'tích rồi gửi lại — bản ghi vẫn giữ trên máy.';
  }
}
