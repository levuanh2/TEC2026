// Cổng chặn thử-lại của hàng đợi offline. Chạy trên desktop bằng
// sqflite_common_ffi, không cần emulator.
//
// Bộ phân loại lỗi (`classifySyncError`) đã đúng từ trước, nhưng hàng đợi vẫn
// chọn lại MỌI bản ghi `failed` ở mỗi vòng đồng bộ, nên một lỗi vĩnh viễn (RLS
// từ chối, dữ liệu sai) bị gửi lại mãi mãi. Các test dưới đây khoá hành vi mới:
// lỗi tạm thời được thử lại NHƯNG có trần, lỗi vĩnh viễn thì không tự chọn lại.
//
// Lưu ý cột: `activities` lưu mã lỗi ở `sync_error`, còn `plots` /
// `crop_seasons` ở `sync_error_code` — mệnh đề chọn phải dùng đúng cột cho từng
// bảng, và đây là thứ `flutter analyze` KHÔNG bắt được.
import 'dart:io';

import 'package:agricarbon_app/db/local_database.dart';
import 'package:agricarbon_app/models/activity.dart';
import 'package:agricarbon_app/services/sync_errors.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

const _user = 'aaaaaaaa-1111-2222-3333-444444444444';

late Directory _tmp;

Activity _activity(String id) => Activity(
      clientEventId: id,
      cropSeasonId: 'season-1',
      type: 'irrigation',
      occurredAt: DateTime.parse('2026-09-13T10:00:00+07:00'),
      payload: const {'method': 'awd'},
      createdAt: DateTime(2026, 9, 13),
    );

void main() {
  setUpAll(() {
    sqfliteFfiInit();
    _tmp = Directory.systemTemp.createTempSync('retry_gate_test');
  });
  tearDownAll(() {
    if (_tmp.existsSync()) _tmp.deleteSync(recursive: true);
  });

  late LocalDatabase db;
  var dbSeq = 0;
  setUp(() async {
    // Một file DB riêng cho mỗi test — hàng đợi của test trước không lẫn sang.
    db = LocalDatabase(
        factory: databaseFactoryFfi, directoryOverride: _tmp.path);
    await db.openForUser('$_user-${dbSeq++}');
  });
  tearDown(() async => db.close());

  /// Đưa một activity vào hàng đợi ở trạng thái mong muốn.
  /// `failCount` lần gọi `failed` → `retry_count` tăng bấy nhiêu.
  Future<String> queued(String id,
      {SyncState state = SyncState.pending,
      String? code,
      int failCount = 0}) async {
    await db.insertActivity(_activity(id));
    for (var i = 0; i < failCount; i++) {
      await db.updateActivitySyncState(id,
          state: SyncState.failed, error: code);
    }
    if (state != SyncState.failed && failCount == 0) {
      await db.updateActivitySyncState(id, state: state);
    }
    return id;
  }

  Future<List<String>> picked() async =>
      (await db.listPendingActivities()).map((a) => a.clientEventId).toList();

  group('phân loại lỗi là dứt khoát', () {
    test('mạng / chưa xác nhận / chưa rõ là TẠM THỜI', () {
      expect(SyncErrorKind.network.isTransient, isTrue);
      expect(SyncErrorKind.notConfirmed.isTransient, isTrue);
      expect(SyncErrorKind.unknown.isTransient, isTrue);
    });

    test('RLS / auth / validation / duplicate là VĨNH VIỄN', () {
      expect(SyncErrorKind.rlsDenied.isPermanent, isTrue);
      expect(SyncErrorKind.auth.isPermanent, isTrue);
      expect(SyncErrorKind.validation.isPermanent, isTrue);
      expect(SyncErrorKind.duplicate.isPermanent, isTrue);
    });

    test('mỗi kind thuộc đúng một nhóm', () {
      for (final k in SyncErrorKind.values) {
        expect(k.isTransient == !k.isPermanent, isTrue, reason: '$k');
      }
    });
  });

  group('hàng đợi chỉ chọn thứ còn đáng gửi', () {
    test('pending luôn được chọn', () async {
      await queued('a-pending');
      expect(await picked(), contains('a-pending'));
    });

    test('lỗi mạng dưới trần: vẫn được chọn lại', () async {
      await queued('a-net', code: 'network', failCount: kMaxSyncAttempts - 1);
      expect(await picked(), contains('a-net'));
    });

    test('lỗi mạng ĐẠT trần: thôi tự chọn lại', () async {
      await queued('a-net-max', code: 'network', failCount: kMaxSyncAttempts);
      expect(await picked(), isNot(contains('a-net-max')));
    });

    test('RLS từ chối: không tự chọn lại ngay từ lần đầu', () async {
      await queued('a-rls', code: 'rlsDenied', failCount: 1);
      expect(await picked(), isNot(contains('a-rls')));
    });

    test('phiên hết hạn: không nã request bằng token hỏng', () async {
      await queued('a-auth', code: 'auth', failCount: 1);
      expect(await picked(), isNot(contains('a-auth')));
    });

    test('dữ liệu sai: giữ failed, không tự gửi lại', () async {
      await queued('a-val', code: 'validation', failCount: 1);
      expect(await picked(), isNot(contains('a-val')));
    });

    test('đã gửi thành công thì không bị chọn lại', () async {
      await queued('a-ok', state: SyncState.synced);
      expect(await picked(), isNot(contains('a-ok')));
    });

    test('lỗi vĩnh viễn vẫn nằm trong DB để màn hình Đồng bộ hiển thị',
        () async {
      await queued('a-rls2', code: 'rlsDenied', failCount: 1);
      expect(await db.getActivity('a-rls2'), isNotNull);
      expect(await db.countPendingActivities(), greaterThan(0));
    });
  });

  group('idempotency giữ nguyên qua các lần thử lại', () {
    test('client_event_id KHÔNG đổi sau nhiều lần fail rồi chọn lại', () async {
      await queued('a-stable');
      for (var i = 1; i < kMaxSyncAttempts; i++) {
        await db.updateActivitySyncState('a-stable',
            state: SyncState.failed, error: 'network');
        expect(await picked(), contains('a-stable'),
            reason: 'lần $i vẫn phải còn trong hàng đợi');
        final row = await db.getActivity('a-stable');
        expect(row!.clientEventId, 'a-stable',
            reason: 'thử lại KHÔNG được sinh khoá idempotency mới');
      }
    });
  });
}
