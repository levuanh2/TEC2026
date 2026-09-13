import 'dart:convert';
import 'dart:io';

import 'package:agricarbon_app/db/local_database.dart';
import 'package:agricarbon_app/design/theme.dart';
import 'package:agricarbon_app/models/crop_season.dart';
import 'package:agricarbon_app/models/sync_state.dart';
import 'package:agricarbon_app/screens/camera_cv_screen.dart';
import 'package:agricarbon_app/services/cv_feedback_store.dart';
import 'package:agricarbon_app/services/cv_inference_service.dart';
import 'package:agricarbon_app/services/leaf_photo_source.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

// PNG 1x1 hợp lệ để Image.file giải mã sạch trong test.
const _png1x1 = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk'
    '+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==';

class _FakeCv implements CvInferenceService {
  _FakeCv({this.available = true});
  bool available;
  CvInferenceResult? next;
  Object? throwThis;
  int calls = 0;

  @override
  bool get isAvailable => available;

  @override
  Future<CvInferenceResult> classify(File image) async {
    calls++;
    if (throwThis != null) throw throwThis!;
    return next ??
        CvInferenceResult(label: LeafDiseaseLabel.brownSpot, confidence: 0.9);
  }
}

class _FakePhoto implements LeafPhotoSource {
  _FakePhoto(this.file);
  final File file;
  final List<LeafPhotoResult> captureQueue = [];
  final List<LeafPhotoResult> galleryQueue = [];
  int captureCalls = 0;
  int galleryCalls = 0;
  int settingsCalls = 0;

  @override
  Future<LeafPhotoResult> capture() async {
    captureCalls++;
    return captureQueue.isNotEmpty
        ? captureQueue.removeAt(0)
        : LeafPhotoResult.picked(file);
  }

  @override
  Future<LeafPhotoResult> pickFromGallery() async {
    galleryCalls++;
    return galleryQueue.isNotEmpty
        ? galleryQueue.removeAt(0)
        : LeafPhotoResult.picked(file);
  }

  @override
  Future<bool> openSettings() async {
    settingsCalls++;
    return true;
  }
}

late Directory _tmp;
late File _img;
late LocalDatabase _db;

CropSeason _season() => CropSeason(
      clientId: 'cs1',
      serverId: 'srv-cs1',
      plotClientId: 'p1',
      seasonCode: 'DX-01',
      syncState: SyncState.synced,
      createdAt: DateTime(2026),
      updatedAt: DateTime(2026),
    );

Future<void> _pump(
  WidgetTester tester, {
  required CvInferenceService cv,
  required LeafPhotoSource photos,
  bool withSeason = true,
  CvFeedbackStore? store,
}) async {
  tester.view.physicalSize = const Size(1200, 2600);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(MaterialApp(
    theme: AgriCarbonTheme.light(),
    home: CameraCvScreen(
      inference: cv,
      photoSource: photos,
      feedbackStore: store ?? CvFeedbackStore(_db),
      cropSeason: withSeason ? _season() : null,
      plotLabel: 'Thửa A',
    ),
  ));
  await tester.pumpAndSettle();
}

void main() {
  setUpAll(sqfliteFfiInit);

  setUp(() async {
    _tmp = await Directory.systemTemp.createTemp('cv_screen');
    _img = File('${_tmp.path}/leaf.png')
      ..writeAsBytesSync(base64Decode(_png1x1));
    _db = LocalDatabase(
        factory: databaseFactoryFfiNoIsolate, directoryOverride: _tmp.path);
    await _db.openForUser('22222222-0000-0000-0000-000000000000');
  });

  tearDown(() async {
    await _db.close();
    if (_tmp.existsSync()) await _tmp.delete(recursive: true);
  });

  testWidgets('chưa chọn vụ -> yêu cầu chọn vụ, không có nút chụp',
      (tester) async {
    await _pump(tester,
        cv: _FakeCv(), photos: _FakePhoto(_img), withSeason: false);
    expect(find.text('Chưa chọn vụ canh tác'), findsOneWidget);
    expect(find.text('Chụp ảnh'), findsNothing);
  });

  testWidgets('service chưa cấu hình -> thông báo, KHÔNG %, KHÔNG nút xác nhận',
      (tester) async {
    final cv = _FakeCv(available: false);
    final photos = _FakePhoto(_img);
    await _pump(tester, cv: cv, photos: photos);

    await tester.tap(find.text('Chụp ảnh'));
    await tester.pumpAndSettle();

    expect(find.text('Nhận dạng bệnh chưa được cấu hình'), findsOneWidget);
    expect(cv.calls, 0);
    expect(find.textContaining('%'), findsNothing);
    expect(find.text('Xác nhận đúng'), findsNothing);
    expect(find.text('Chỉnh lại'), findsNothing);
  });

  testWidgets('chụp -> hiện nhãn tiếng Việt + độ tin cậy thật', (tester) async {
    final cv = _FakeCv()
      ..next =
          CvInferenceResult(label: LeafDiseaseLabel.brownSpot, confidence: 0.9);
    await _pump(tester, cv: cv, photos: _FakePhoto(_img));

    await tester.tap(find.text('Chụp ảnh'));
    await tester.pumpAndSettle();

    expect(find.text('Đốm nâu'), findsOneWidget);
    expect(find.text('90%'), findsOneWidget);
    expect(find.text('Xác nhận đúng'), findsOneWidget);
    expect(find.text('Cần kiểm tra'), findsNothing);
  });

  testWidgets('kết quả chưa chắc -> badge "Cần kiểm tra" + cảnh báo',
      (tester) async {
    final cv = _FakeCv()
      ..next =
          CvInferenceResult(label: LeafDiseaseLabel.blast, confidence: 0.4);
    await _pump(tester, cv: cv, photos: _FakePhoto(_img));

    await tester.tap(find.text('Chọn từ thư viện'));
    await tester.pumpAndSettle();

    expect(find.text('Cần kiểm tra'), findsOneWidget);
    expect(find.textContaining('Không chắc chắn'), findsOneWidget);
  });

  testWidgets('chụp/chọn lại -> quay về khung chụp', (tester) async {
    await _pump(tester, cv: _FakeCv(), photos: _FakePhoto(_img));
    await tester.tap(find.text('Chụp ảnh'));
    await tester.pumpAndSettle();
    expect(find.text('Đốm nâu'), findsOneWidget);

    await tester.tap(find.text('Chụp/chọn lại'));
    await tester.pumpAndSettle();

    expect(find.text('Chụp ảnh'), findsOneWidget);
    expect(find.text('Chọn từ thư viện'), findsOneWidget);
    expect(find.text('Đốm nâu'), findsNothing);
  });

  testWidgets('quyền bị từ chối vĩnh viễn -> nút "Mở Cài đặt" gọi openSettings',
      (tester) async {
    final photos = _FakePhoto(_img)
      ..captureQueue.add(const LeafPhotoResult(
        LeafPhotoOutcome.permissionPermanentlyDenied,
        message: 'Quyền đã bị tắt. Vào Cài đặt để bật lại rồi thử lại.',
      ));
    await _pump(tester, cv: _FakeCv(), photos: photos);

    await tester.tap(find.text('Chụp ảnh'));
    await tester.pumpAndSettle();

    expect(find.textContaining('Vào Cài đặt'), findsOneWidget);
    await tester.tap(find.text('Mở Cài đặt'));
    await tester.pumpAndSettle();
    expect(photos.settingsCalls, 1);
  });

  testWidgets('quyền bị từ chối (tạm) -> thông báo, KHÔNG có "Mở Cài đặt"',
      (tester) async {
    final photos = _FakePhoto(_img)
      ..captureQueue.add(const LeafPhotoResult(
        LeafPhotoOutcome.permissionDenied,
        message: 'Cần cấp quyền để tiếp tục.',
      ));
    await _pump(tester, cv: _FakeCv(), photos: photos);

    await tester.tap(find.text('Chụp ảnh'));
    await tester.pumpAndSettle();

    expect(find.text('Cần cấp quyền để tiếp tục.'), findsOneWidget);
    expect(find.text('Mở Cài đặt'), findsNothing);
  });

  testWidgets('quyền bị hạn chế (restricted) -> nêu rõ thiết bị giới hạn',
      (tester) async {
    final photos = _FakePhoto(_img)
      ..captureQueue.add(const LeafPhotoResult(
        LeafPhotoOutcome.permissionRestricted,
        message: 'Thiết bị đang giới hạn quyền này.',
      ));
    await _pump(tester, cv: _FakeCv(), photos: photos);

    await tester.tap(find.text('Chụp ảnh'));
    await tester.pumpAndSettle();

    expect(find.textContaining('giới hạn quyền'), findsOneWidget);
    expect(find.text('Mở Cài đặt'), findsNothing);
  });

  testWidgets('không có máy ảnh -> không crash, vẫn dùng được thư viện',
      (tester) async {
    final photos = _FakePhoto(_img)
      ..captureQueue.add(const LeafPhotoResult(
        LeafPhotoOutcome.cameraUnavailable,
        message:
            'Thiết bị không có máy ảnh. Bạn vẫn có thể chọn ảnh từ thư viện.',
      ));
    await _pump(tester, cv: _FakeCv(), photos: photos);

    await tester.tap(find.text('Chụp ảnh'));
    await tester.pumpAndSettle();
    expect(find.textContaining('không có máy ảnh'), findsOneWidget);

    // Thư viện vẫn hoạt động.
    await tester.tap(find.text('Chọn từ thư viện'));
    await tester.pumpAndSettle();
    expect(find.text('Đốm nâu'), findsOneWidget);
  });

  testWidgets('ảnh sai định dạng -> báo lỗi thân thiện', (tester) async {
    final photos = _FakePhoto(_img)
      ..captureQueue.add(const LeafPhotoResult(
        LeafPhotoOutcome.invalidImage,
        message: 'Chỉ nhận ảnh JPEG hoặc PNG.',
      ));
    await _pump(tester, cv: _FakeCv(), photos: photos);

    await tester.tap(find.text('Chụp ảnh'));
    await tester.pumpAndSettle();
    expect(find.text('Chỉ nhận ảnh JPEG hoặc PNG.'), findsOneWidget);
  });

  testWidgets('chỉnh lại -> sheet đủ 4 nhãn, lưu local đúng nhãn',
      (tester) async {
    final store = CvFeedbackStore(_db);
    final cv = _FakeCv()
      ..next =
          CvInferenceResult(label: LeafDiseaseLabel.brownSpot, confidence: 0.9);
    await _pump(tester, cv: cv, photos: _FakePhoto(_img), store: store);

    await tester.tap(find.text('Chụp ảnh'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Chỉnh lại'));
    await tester.pumpAndSettle();

    for (final vi in ['Đạo ôn', 'Bạc lá', 'Đốm nâu', 'Lá khỏe']) {
      expect(
        find.widgetWithText(RadioListTile<LeafDiseaseLabel>, vi),
        findsOneWidget,
      );
    }
    await tester
        .tap(find.widgetWithText(RadioListTile<LeafDiseaseLabel>, 'Bạc lá'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Lưu chỉnh sửa'));
    await tester.pumpAndSettle();

    final rows = await store.list('cs1');
    expect(rows, hasLength(1));
    expect(rows.single.verdict, CvFeedbackVerdict.corrected);
    expect(rows.single.correctedLabel, 'bacterial_blight');
    expect(find.textContaining('Đã lưu chỉnh sửa'), findsWidgets);
  });

  testWidgets('xác nhận đúng -> lưu local verdict confirmed', (tester) async {
    final store = CvFeedbackStore(_db);
    await _pump(tester, cv: _FakeCv(), photos: _FakePhoto(_img), store: store);

    await tester.tap(find.text('Chụp ảnh'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Xác nhận đúng'));
    await tester.pumpAndSettle();

    final rows = await store.list('cs1');
    expect(rows.single.verdict, CvFeedbackVerdict.confirmed);
    expect(rows.single.modelLabel, 'brown_spot');
    expect(find.textContaining('Đã lưu xác nhận'), findsWidgets);
  });

  testWidgets('suy luận lỗi -> ErrorState + "Thử lại" chạy lại được',
      (tester) async {
    final cv = _FakeCv()..throwThis = const CvInferenceFailure('boom');
    await _pump(tester, cv: cv, photos: _FakePhoto(_img));

    await tester.tap(find.text('Chụp ảnh'));
    await tester.pumpAndSettle();
    expect(find.text('Chưa nhận biết được ảnh này'), findsOneWidget);

    cv.throwThis = null;
    cv.next =
        CvInferenceResult(label: LeafDiseaseLabel.healthy, confidence: 0.88);
    await tester.tap(find.text('Thử lại'));
    await tester.pumpAndSettle();
    expect(find.text('Lá khỏe'), findsOneWidget);
    expect(find.text('88%'), findsOneWidget);
  });
}
