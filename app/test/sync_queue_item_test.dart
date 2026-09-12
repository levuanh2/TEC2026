import 'package:agricarbon_app/models/sync_queue_item.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('activityPayloadSummary — đơn vị THẬT theo schema, null bỏ qua', () {
    test('irrigation dùng m³, KHÔNG "mm"', () {
      final s = activityPayloadSummary('irrigation', {'water_volume_m3': 32});
      expect(s, '32 m³');
      expect(s, isNot(contains('mm')));
    });

    test('irrigation không có nước -> rơi về số phút / cách tưới', () {
      expect(activityPayloadSummary('irrigation', {'duration_minutes': 45}),
          '45 phút');
      expect(activityPayloadSummary('irrigation', {'method': 'awd'}),
          'Ngập-khô xen kẽ');
    });

    test('fertilizer/fuel/harvest/seeding dùng cột chính', () {
      expect(
          activityPayloadSummary('fertilizer', {'amount_kg': 18.0}), '18 kg');
      expect(activityPayloadSummary('fuel', {'amount_liter': 5.5}), '5.5 lít');
      expect(activityPayloadSummary('harvest', {'yield_kg': 4200}), '4200 kg');
      expect(activityPayloadSummary('seeding', {'seed_kg': 40}), '40 kg');
    });

    test('pesticide ghép lượng + đơn vị người dùng nhập', () {
      expect(
        activityPayloadSummary('pesticide', {'amount': 2, 'unit': 'lít'}),
        '2 lít',
      );
    });

    test('thiếu số -> null (KHÔNG "0")', () {
      expect(activityPayloadSummary('fertilizer', const {}), isNull);
      expect(
          activityPayloadSummary('harvest', const {'yield_kg': null}), isNull);
    });
  });

  group('SyncQueueItem.fromActivityRow', () {
    Map<String, dynamic> row({
      String type = 'fertilizer',
      int deleted = 0,
      String state = 'pending',
      String? err,
      int retry = 0,
    }) =>
        {
          'id': 'a1',
          'crop_season_id': 'cs1',
          'type': type,
          'occurred_at': '2026-02-02T07:10:00.000',
          'created_at': '2026-02-02T07:12:00.000',
          'payload_json': '{"fertilizer_name":"Ure","amount_kg":18}',
          'sync_state': state,
          'sync_error': err,
          'retry_count': retry,
          'last_attempt_at': null,
          'deleted_locally': deleted,
          '_plot_code': 'A-01',
          '_season_code': 'S1',
        };

    test('bản thường: tiêu đề "loại · thửa", phụ đề mốc + tóm tắt thật', () {
      final it = SyncQueueItem.fromActivityRow(row());
      expect(it.kind, SyncQueueKind.activity);
      expect(it.title, 'Bón phân · A-01');
      expect(it.subtitle, contains('02/02 07:10'));
      expect(it.subtitle, contains('18 kg'));
      expect(it.isTombstone, isFalse);
    });

    test('tombstone: "Xoá <loại>" + "đã đánh dấu xoá"', () {
      final it = SyncQueueItem.fromActivityRow(row(deleted: 1));
      expect(it.title, startsWith('Xoá '));
      expect(it.subtitle, contains('đã đánh dấu xoá'));
      expect(it.isTombstone, isTrue);
    });

    test('failed giữ mã lỗi + số lần thử', () {
      final it = SyncQueueItem.fromActivityRow(
          row(state: 'failed', err: 'network', retry: 3));
      expect(it.isFailed, isTrue);
      expect(it.errorCode, 'network');
      expect(it.retryCount, 3);
    });
  });
}
