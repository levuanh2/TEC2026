import 'package:agricarbon_app/services/sync_errors.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:supabase_flutter/supabase_flutter.dart' show PostgrestException;

void main() {
  // Nhánh phân loại mà `FarmScreen._showCooperativeLookupFailed` (bug #9) dựa
  // vào để phân biệt "mất mạng" với "bị từ chối quyền".
  test('lỗi mạng -> SyncErrorKind.network', () {
    expect(
      classifySyncError(Exception('SocketException: Failed host lookup')),
      SyncErrorKind.network,
    );
    expect(
      classifySyncError(Exception('Connection closed before full header')),
      SyncErrorKind.network,
    );
  });

  test('RLS 42501 -> SyncErrorKind.rlsDenied', () {
    expect(
      classifySyncError(
        const PostgrestException(message: 'permission denied', code: '42501'),
      ),
      SyncErrorKind.rlsDenied,
    );
  });

  test('trùng khoá 23505 -> SyncErrorKind.duplicate', () {
    expect(
      classifySyncError(
        const PostgrestException(message: 'duplicate key value', code: '23505'),
      ),
      SyncErrorKind.duplicate,
    );
  });

  test('lỗi lạ -> unknown (không ném)', () {
    expect(classifySyncError(Exception('???')), SyncErrorKind.unknown);
  });

  test('syncErrorMessage KHÔNG kèm exception thô', () {
    for (final kind in SyncErrorKind.values) {
      final msg = syncErrorMessage(kind);
      expect(msg, isNotEmpty);
      expect(msg.toLowerCase(), isNot(contains('exception')));
    }
  });
}
