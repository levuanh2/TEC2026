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
  unknown,
}

SyncErrorKind classifySyncError(Object error) {
  if (error is PostgrestException) {
    final code = error.code ?? '';
    final msg = error.message.toLowerCase();
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
  }
}
