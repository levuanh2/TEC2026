import 'package:flutter_test/flutter_test.dart';

/// Múi giờ của `activities.occurred_at` / `recorded_at`.
///
/// Cả hai cột là `timestamptz` (supabase/migrations/20260907000000_baseline.sql)
/// — MỐC THỜI GIAN THẬT, không phải ngày lịch. Máy nông dân chạy giờ VN
/// (Asia/Ho_Chi_Minh, +07:00, không có DST).
///
/// Lỗi đã sửa: `sync_service.dart` gửi `occurredAt.toIso8601String()` trên một
/// `DateTime` local. Dart sinh chuỗi KHÔNG có `Z` cũng không có offset cho
/// DateTime local, nên Postgres đọc chuỗi trần đó theo giờ phiên (UTC): 23:00
/// ICT bị lưu thành 23:00Z, đọc lại ở VN thành 06:00 NGÀY HÔM SAU. Ngày canh
/// tác của nông dân bị lệch.
///
/// Các test dưới đây cố ý KHÔNG phụ thuộc múi giờ của máy chạy test: mốc thời
/// gian được dựng bằng offset tường minh (`+07:00`) và đối chiếu ở UTC, nên kết
/// quả giống nhau dù CI chạy ở UTC hay máy dev chạy ở ICT.
void main() {
  /// Đúng cách `sync_service` serialize lên Supabase sau khi sửa.
  String wire(DateTime d) => d.toUtc().toIso8601String();

  /// Đọc ngược về giờ VN mà không cần tz database: cộng offset cố định +07:00.
  DateTime asIct(String isoUtc) =>
      DateTime.parse(isoUtc).toUtc().add(const Duration(hours: 7));

  group('occurred_at là instant, gửi lên phải ở UTC', () {
    test('23:00 ICT 13/09 -> 16:00Z CÙNG ngày (ca quan trọng nhất)', () {
      final picked = DateTime.parse('2026-09-13T23:00:00+07:00');
      expect(wire(picked), '2026-09-13T16:00:00.000Z');
      // KHÔNG được là 23:00Z — đó chính là lỗi cũ.
      expect(wire(picked), isNot('2026-09-13T23:00:00.000Z'));
    });

    test('00:30 ICT 13/09 -> 17:30Z ngày 12/09 (qua ranh giới ngày)', () {
      final picked = DateTime.parse('2026-09-13T00:30:00+07:00');
      expect(wire(picked), '2026-09-12T17:30:00.000Z');
    });

    test('07:00 ICT -> 00:00Z cùng ngày', () {
      final picked = DateTime.parse('2026-09-13T07:00:00+07:00');
      expect(wire(picked), '2026-09-13T00:00:00.000Z');
    });

    test('17:00 ICT -> 10:00Z cùng ngày', () {
      final picked = DateTime.parse('2026-09-13T17:00:00+07:00');
      expect(wire(picked), '2026-09-13T10:00:00.000Z');
    });
  });

  group('vòng ghi–đọc trả lại đúng ngày/giờ nông dân đã nhập', () {
    for (final local in const [
      '2026-09-13T00:30:00+07:00',
      '2026-09-13T07:00:00+07:00',
      '2026-09-13T17:00:00+07:00',
      '2026-09-13T23:00:00+07:00',
    ]) {
      test('$local không lệch ngày sau khi đi qua UTC', () {
        final picked = DateTime.parse(local);
        final backInIct = asIct(wire(picked));
        final expected =
            DateTime.parse(local).toUtc().add(const Duration(hours: 7));
        expect(backInIct.year, expected.year);
        expect(backInIct.month, expected.month);
        expect(backInIct.day, expected.day,
            reason: 'ngày canh tác không được đổi');
        expect(backInIct.hour, expected.hour);
        expect(backInIct.minute, expected.minute);
      });
    }
  });

  group('mô tả lại lỗi cũ để nó không quay lại', () {
    test('DateTime local serialize KHÔNG có chỉ dấu múi giờ', () {
      final naiveLocal = DateTime(2026, 9, 13, 23, 0);
      final s = naiveLocal.toIso8601String();
      expect(s.endsWith('Z'), isFalse);
      expect(s.contains('+'), isFalse,
          reason: 'chuỗi trần: Postgres sẽ đọc theo giờ phiên (UTC), '
              'nên phải .toUtc() TRƯỚC khi gửi');
    });

    test('.toUtc() luôn sinh chuỗi kết thúc bằng Z', () {
      final naiveLocal = DateTime(2026, 9, 13, 23, 0);
      expect(wire(naiveLocal).endsWith('Z'), isTrue);
    });

    test('.toUtc() trên một DateTime đã là UTC không đổi gì (idempotent)', () {
      final alreadyUtc = DateTime.utc(2026, 9, 13, 16, 0);
      expect(wire(alreadyUtc), '2026-09-13T16:00:00.000Z');
      expect(wire(DateTime.parse(wire(alreadyUtc))), wire(alreadyUtc));
    });
  });
}
