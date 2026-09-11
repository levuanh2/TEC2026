import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

/// Chốt: KHÔNG có dữ liệu minh hoạ từ Figma lọt vào source production (`lib/`).
/// SVG chỉ định bố cục/phong cách — số liệu và tên phải lấy từ dữ liệu thật.
void main() {
  test('lib/ không chứa placeholder từ SVG', () {
    // Chuỗi minh hoạ trong 7 file SVG (tên người, mã hộ, số ruộng, số liệu,
    // hotline...) — không được xuất hiện nguyên văn trong mã production.
    const forbidden = <String>[
      'Nguyễn Văn An',
      'chú Nguyễn',
      'HH-001',
      '1900 1234',
      '0,68',
      '↓ 14%',
      '↓14%',
      '4,2 ha',
      'A-01 · 1,42',
      'trung bình 12 hộ',
      'Hè Thu 2026',
      // SVG 23 (Gửi dữ liệu) — số/mã minh hoạ, KHÔNG hardcode.
      '32 mm',
      '1 ảnh',
      '18 kg',
      'B-03',
      'A-02',
      '10:12 hôm nay',
      // SVG 25 (Kết quả phát thải) — số/nhãn minh hoạ.
      'bộ số liệu lúa Việt Nam 2026',
      'Hè Thu 2026',
      'giảm khoảng 24%',
      'giảm khoảng 24',
      // SVG 24 (Kiểm tra ảnh lá lúa) — số/nhãn minh hoạ + tính năng KHÔNG làm
      // (giai đoạn sinh trưởng, mực nước) và độ tin cậy dựng sẵn.
      'Đẻ nhánh',
      '2–4 cm',
      '78%',
      '0.78',
      '0,78',
      'Kết quả nhận biết gần nhất',
      // Module 04/05 (Resource dashboard + Recommendation) — số/benchmark/khuyến
      // nghị minh hoạ trong tài liệu, KHÔNG hardcode vào app.
      'rec-001',
      'giảm 18 kg N',
      'phân đạm cao hơn mức trung bình HTX',
      '1420.0',
      '4150.0',
      '1.720',
      // SVG 26 (Tài khoản) + nghiệm thu cuối — mã thửa/mốc giờ/tỷ lệ minh hoạ.
      'A-01',
      '10:12',
      '62%',
    ];

    final offenders = <String>[];
    for (final entity in Directory('lib').listSync(recursive: true)) {
      if (entity is! File || !entity.path.endsWith('.dart')) continue;
      final content = entity.readAsStringSync();
      for (final needle in forbidden) {
        if (content.contains(needle)) {
          offenders.add('${entity.path}: "$needle"');
        }
      }
    }

    expect(
      offenders,
      isEmpty,
      reason: 'Placeholder Figma lọt vào production:\n${offenders.join('\n')}',
    );
  });
}
