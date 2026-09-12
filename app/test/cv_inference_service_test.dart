import 'dart:io';

import 'package:agricarbon_app/db/local_database.dart';
import 'package:agricarbon_app/services/cv_feedback_store.dart';
import 'package:agricarbon_app/services/cv_inference_service.dart';
import 'package:agricarbon_app/services/leaf_photo_source.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

// 1x1 PNG hợp lệ (magic 89 50 4E 47…).
const _pngBytes = <int>[
  0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, //
  0x00, 0x00, 0x00, 0x0D, 0x49, 0x48, 0x44, 0x52,
  0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,
  0x08, 0x06, 0x00, 0x00, 0x00, 0x1F, 0x15, 0xC4,
  0x89, 0x00, 0x00, 0x00, 0x0D, 0x49, 0x44, 0x41,
  0x54, 0x78, 0x9C, 0x63, 0x00, 0x01, 0x00, 0x00,
  0x05, 0x00, 0x01, 0x0D, 0x0A, 0x2D, 0xB4, 0x00,
  0x00, 0x00, 0x00, 0x49, 0x45, 0x4E, 0x44, 0xAE,
  0x42, 0x60, 0x82,
];
const _jpegBytes = <int>[
  0xFF,
  0xD8,
  0xFF,
  0xE0,
  0x00,
  0x10,
  0x4A,
  0x46,
  0x49,
  0x46
];

void main() {
  group('LeafDiseaseLabel', () {
    test('đúng 4 nhãn được phép, không có giai đoạn / mực nước', () {
      expect(LeafDiseaseLabel.values.map((e) => e.wire).toList(),
          ['blast', 'bacterial_blight', 'brown_spot', 'healthy']);
      expect(LeafDiseaseLabel.values.map((e) => e.vi).toList(),
          ['Đạo ôn', 'Bạc lá', 'Đốm nâu', 'Lá khỏe']);
    });

    test('fromWire ánh xạ đúng, chuỗi lạ ném (không ép nhãn)', () {
      expect(
          LeafDiseaseLabel.fromWire('brown_spot'), LeafDiseaseLabel.brownSpot);
      expect(() => LeafDiseaseLabel.fromWire('tungro'), throwsFormatException);
      expect(() => LeafDiseaseLabel.fromWire(''), throwsFormatException);
    });
  });

  group('CvInferenceResult', () {
    test('confidence dưới ngưỡng -> isUncertain tự bật', () {
      final r = CvInferenceResult(
          label: LeafDiseaseLabel.blast,
          confidence: kCvConfidenceThreshold - 0.01);
      expect(r.isUncertain, isTrue);
      expect(r.labelVi, 'Đạo ôn');
    });

    test('confidence trên ngưỡng -> không uncertain, nhưng model ép được', () {
      final ok =
          CvInferenceResult(label: LeafDiseaseLabel.healthy, confidence: 0.95);
      expect(ok.isUncertain, isFalse);
      final forced = CvInferenceResult(
          label: LeafDiseaseLabel.healthy, confidence: 0.95, isUncertain: true);
      expect(forced.isUncertain, isTrue);
    });

    test('confidence ngoài [0,1] -> assert', () {
      expect(
        () => CvInferenceResult(label: LeafDiseaseLabel.blast, confidence: 1.4),
        throwsA(isA<AssertionError>()),
      );
    });
  });

  group('UnavailableCvInferenceService', () {
    test(
        'isAvailable = false, classify ném CvInferenceUnavailable (không kết quả giả)',
        () async {
      const svc = UnavailableCvInferenceService();
      expect(svc.isAvailable, isFalse);
      await expectLater(
        svc.classify(File('bất-kỳ.jpg')),
        throwsA(isA<CvInferenceUnavailable>()),
      );
    });
  });

  group('ImagePickerLeafPhotoSource.validateFile', () {
    late Directory tmp;
    setUp(() async {
      tmp = await Directory.systemTemp.createTemp('cv_validate');
    });
    tearDown(() async {
      if (tmp.existsSync()) await tmp.delete(recursive: true);
    });

    test('PNG hợp lệ -> picked', () async {
      final f = File('${tmp.path}/a.png')..writeAsBytesSync(_pngBytes);
      final res = await ImagePickerLeafPhotoSource.validateFile(f);
      expect(res.outcome, LeafPhotoOutcome.picked);
      expect(res.file!.path, f.path);
    });

    test('JPEG hợp lệ -> picked', () async {
      final f = File('${tmp.path}/a.jpg')..writeAsBytesSync(_jpegBytes);
      final res = await ImagePickerLeafPhotoSource.validateFile(f);
      expect(res.outcome, LeafPhotoOutcome.picked);
    });

    test('không phải ảnh (đuôi .jpg nhưng nội dung text) -> invalidImage',
        () async {
      final f = File('${tmp.path}/fake.jpg')..writeAsStringSync('not an image');
      final res = await ImagePickerLeafPhotoSource.validateFile(f);
      expect(res.outcome, LeafPhotoOutcome.invalidImage);
      expect(res.message, contains('JPEG'));
    });

    test('file rỗng -> invalidImage', () async {
      final f = File('${tmp.path}/empty.png')..writeAsBytesSync(const []);
      final res = await ImagePickerLeafPhotoSource.validateFile(f);
      expect(res.outcome, LeafPhotoOutcome.invalidImage);
    });

    test('file không tồn tại -> invalidImage', () async {
      final res = await ImagePickerLeafPhotoSource.validateFile(
          File('${tmp.path}/missing.png'));
      expect(res.outcome, LeafPhotoOutcome.invalidImage);
    });

    test('vượt kMaxLeafPhotoBytes -> tooLarge', () async {
      final f = File('${tmp.path}/big.jpg');
      final bytes = <int>[..._jpegBytes, ...List.filled(kMaxLeafPhotoBytes, 0)];
      f.writeAsBytesSync(bytes);
      final res = await ImagePickerLeafPhotoSource.validateFile(f);
      expect(res.outcome, LeafPhotoOutcome.tooLarge);
    });
  });

  group('CvFeedbackStore (local-only)', () {
    late Directory tmp;
    late LocalDatabase db;
    setUpAll(sqfliteFfiInit);
    setUp(() async {
      tmp = await Directory.systemTemp.createTemp('cv_feedback');
      db = LocalDatabase(
          factory: databaseFactoryFfiNoIsolate, directoryOverride: tmp.path);
      await db.openForUser('11111111-0000-0000-0000-000000000000');
    });
    tearDown(() async {
      await db.close();
      if (tmp.existsSync()) await tmp.delete(recursive: true);
    });

    test('add + list round-trip theo vụ, giữ thứ tự', () async {
      final store = CvFeedbackStore(db);
      final base =
          CvInferenceResult(label: LeafDiseaseLabel.brownSpot, confidence: 0.9);
      await store.add(
          'cs1',
          CvFeedbackEntry.fromResult(
              result: base,
              verdict: CvFeedbackVerdict.confirmed,
              at: DateTime(2026, 1, 1)));
      await store.add(
          'cs1',
          CvFeedbackEntry.fromResult(
              result: base,
              verdict: CvFeedbackVerdict.corrected,
              correctedLabel: LeafDiseaseLabel.bacterialBlight,
              at: DateTime(2026, 1, 2)));

      final rows = await store.list('cs1');
      expect(rows, hasLength(2));
      expect(rows[0].verdict, CvFeedbackVerdict.confirmed);
      expect(rows[1].verdict, CvFeedbackVerdict.corrected);
      expect(rows[1].correctedLabel, 'bacterial_blight');
      expect(rows[1].modelLabel, 'brown_spot');

      // Vụ khác không lẫn.
      expect(await store.list('cs2'), isEmpty);
    });

    test('list khi chưa có gì -> rỗng', () async {
      expect(await CvFeedbackStore(db).list('nope'), isEmpty);
    });
  });
}
