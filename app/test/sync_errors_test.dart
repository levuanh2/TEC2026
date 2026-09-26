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

  test('vòng đời vụ 55000 -> seasonClosed, vĩnh viễn (không phải lỗi quyền)', () {
    for (final e in const [
      PostgrestException(message: 'crop_season_not_open: x', code: '55000'),
      PostgrestException(message: 'illegal_crop_season_transition: closed -> active', code: 'P0001'),
    ]) {
      final k = classifySyncError(e);
      expect(k, SyncErrorKind.seasonClosed);
      expect(k.isPermanent, isTrue);
      expect(kTransientErrorCodes, isNot(contains(k.name)));
    }
    expect(syncErrorMessage(SyncErrorKind.seasonClosed), contains('đã kết thúc'));
  });
}
