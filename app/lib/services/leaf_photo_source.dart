import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart' show PlatformException;
import 'package:image_picker/image_picker.dart';
import 'package:permission_handler/permission_handler.dart';

/// Nguồn ảnh lá lúa cho màn 24 — chụp bằng máy ảnh hoặc chọn từ thư viện.
///
/// Đây là lớp trừu tượng để màn hình test được mà không đụng platform. Bản
/// thật ([ImagePickerLeafPhotoSource]) bọc `image_picker` + `permission_handler`
/// — KHÔNG gọi MethodChannel/`camera` API trực tiếp vì hai package này đã có
/// abstraction đủ dùng cho một ảnh tĩnh.

/// Kết cục một lần chụp/chọn ảnh.
enum LeafPhotoOutcome {
  /// Có ảnh hợp lệ trong [LeafPhotoResult.file].
  picked,

  /// Nông dân bấm huỷ hộp thoại — không phải lỗi.
  cancelled,

  /// Thiết bị không có máy ảnh (máy ảo, máy bị gỡ camera). KHÔNG crash.
  cameraUnavailable,

  /// Quyền bị từ chối lần này — có thể hỏi lại.
  permissionDenied,

  /// Quyền bị từ chối vĩnh viễn ("Không hỏi lại") — phải vào Cài đặt.
  permissionPermanentlyDenied,

  /// Quyền bị chặn ở mức hệ thống (quản lý thiết bị / kiểm soát của phụ huynh).
  /// Vào Cài đặt cũng không mở được.
  permissionRestricted,

  /// Đã chọn được file nhưng không phải JPEG/PNG, rỗng, hoặc hỏng.
  invalidImage,

  /// File vượt quá [kMaxLeafPhotoBytes].
  tooLarge,

  /// Lỗi không lường trước ở tầng platform.
  failed,
}

/// Kết quả một lần chụp/chọn.
class LeafPhotoResult {
  const LeafPhotoResult(this.outcome, {this.file, this.message});

  const LeafPhotoResult.picked(this.file)
      : outcome = LeafPhotoOutcome.picked,
        message = null;

  const LeafPhotoResult.cancelled()
      : outcome = LeafPhotoOutcome.cancelled,
        file = null,
        message = null;

  final LeafPhotoOutcome outcome;

  /// Ảnh hợp lệ (đã resize/nén, đã bỏ EXIF GPS). `null` trừ khi
  /// [outcome] == [LeafPhotoOutcome.picked].
  final File? file;

  /// Thông điệp thân thiện (đã tiếng Việt) để hiển thị khi có lỗi.
  final String? message;

  bool get isPicked => outcome == LeafPhotoOutcome.picked && file != null;
}

/// Cạnh dài tối đa khi resize — đủ để model phân loại, đủ nhỏ để gửi/lưu offline.
const int kMaxLeafPhotoDimension = 1600;

/// Chất lượng nén JPEG (0..100). Chỉ áp dụng cho ảnh JPEG.
const int kLeafPhotoJpegQuality = 85;

/// Giới hạn kích thước file sau resize/nén. PNG từ thư viện không được nén theo
/// chất lượng nên vẫn có thể lớn — chặn ở đây để không lưu file khổng lồ.
const int kMaxLeafPhotoBytes = 12 * 1024 * 1024;

/// Nguồn ảnh trừu tượng.
abstract class LeafPhotoSource {
  /// Chụp ảnh mới bằng máy ảnh.
  Future<LeafPhotoResult> capture();

  /// Chọn một ảnh có sẵn từ thư viện.
  Future<LeafPhotoResult> pickFromGallery();

  /// Mở trang Cài đặt ứng dụng (khi quyền bị từ chối vĩnh viễn).
  Future<bool> openSettings();
}

/// Bản thật: `image_picker` lo hộp thoại + resize/nén + tái mã hoá (rụng EXIF
/// GPS khi truyền `maxWidth/maxHeight` và `requestFullMetadata: false`).
/// `permission_handler` lo trạng thái quyền chi tiết mà `image_picker` không
/// phân biệt được (permanentlyDenied vs denied) và `openAppSettings`.
///
/// KHÔNG xoá ảnh gốc: `image_picker` trả về một BẢN SAO trong thư mục cache của
/// app; ảnh trong cuộn camera / thư viện không bị đụng tới.
class ImagePickerLeafPhotoSource implements LeafPhotoSource {
  ImagePickerLeafPhotoSource({ImagePicker? picker})
      : _picker = picker ?? ImagePicker();

  final ImagePicker _picker;

  @override
  Future<LeafPhotoResult> capture() async {
    // Máy ảnh: luôn cần quyền CAMERA (đã khai trong Manifest / Info.plist).
    final gate = await _ensure(Permission.camera);
    if (gate != null) return gate;
    return _pick(ImageSource.camera);
  }

  @override
  Future<LeafPhotoResult> pickFromGallery() async {
    // Thư viện: iOS 14+ dùng PHPicker (không cần quyền) nhưng vẫn kiểm
    // `Permission.photos` để bắt trạng thái `restricted`. Android dùng Photo
    // Picker của hệ thống — KHÔNG cần READ_MEDIA_IMAGES/READ_EXTERNAL_STORAGE,
    // nên bỏ qua cổng quyền để không xin nhầm quyền chưa khai.
    if (defaultTargetPlatform == TargetPlatform.iOS) {
      final gate = await _ensure(Permission.photos);
      if (gate != null) return gate;
    }
    return _pick(ImageSource.gallery);
  }

  @override
  Future<bool> openSettings() => openAppSettings();

  /// Trả `null` nếu được phép đi tiếp, ngược lại trả [LeafPhotoResult] mô tả
  /// lý do từ chối.
  Future<LeafPhotoResult?> _ensure(Permission permission) async {
    var status = await permission.status;
    if (status.isGranted || status.isLimited || status.isProvisional) {
      return null;
    }
    if (status.isPermanentlyDenied) {
      return const LeafPhotoResult(
        LeafPhotoOutcome.permissionPermanentlyDenied,
        message: 'Quyền đã bị tắt. Vào Cài đặt để bật lại rồi thử lại.',
      );
    }
    if (status.isRestricted) {
      return const LeafPhotoResult(
        LeafPhotoOutcome.permissionRestricted,
        message:
            'Thiết bị đang giới hạn quyền này (quản lý thiết bị hoặc kiểm soát '
            'của phụ huynh).',
      );
    }
    // denied — hỏi một lần.
    status = await permission.request();
    if (status.isGranted || status.isLimited || status.isProvisional) {
      return null;
    }
    if (status.isPermanentlyDenied) {
      return const LeafPhotoResult(
        LeafPhotoOutcome.permissionPermanentlyDenied,
        message: 'Quyền đã bị tắt. Vào Cài đặt để bật lại rồi thử lại.',
      );
    }
    if (status.isRestricted) {
      return const LeafPhotoResult(
        LeafPhotoOutcome.permissionRestricted,
        message: 'Thiết bị đang giới hạn quyền này.',
      );
    }
    return const LeafPhotoResult(
      LeafPhotoOutcome.permissionDenied,
      message: 'Cần cấp quyền để tiếp tục.',
    );
  }

  Future<LeafPhotoResult> _pick(ImageSource source) async {
    XFile? x;
    try {
      x = await _picker.pickImage(
        source: source,
        maxWidth: kMaxLeafPhotoDimension.toDouble(),
        maxHeight: kMaxLeafPhotoDimension.toDouble(),
        imageQuality: kLeafPhotoJpegQuality,
        // Không lấy metadata đầy đủ ⇒ không kèm toạ độ GPS vào bản sao.
        requestFullMetadata: false,
      );
    } on PlatformException catch (e) {
      switch (e.code) {
        case 'no_available_camera':
        case 'no_cameras':
          return const LeafPhotoResult(
            LeafPhotoOutcome.cameraUnavailable,
            message: 'Thiết bị không có máy ảnh. Bạn vẫn có thể chọn ảnh từ '
                'thư viện.',
          );
        case 'camera_access_denied':
        case 'photo_access_denied':
          return const LeafPhotoResult(
            LeafPhotoOutcome.permissionDenied,
            message: 'Cần cấp quyền để tiếp tục.',
          );
        case 'multiple_request':
          return const LeafPhotoResult(
            LeafPhotoOutcome.failed,
            message: 'Đang mở hộp thoại chọn ảnh khác. Thử lại sau giây lát.',
          );
        default:
          return LeafPhotoResult(
            LeafPhotoOutcome.failed,
            message: 'Không mở được máy ảnh/thư viện. Thử lại sau.',
          );
      }
    } catch (_) {
      return const LeafPhotoResult(
        LeafPhotoOutcome.failed,
        message: 'Không mở được máy ảnh/thư viện. Thử lại sau.',
      );
    }

    if (x == null) return const LeafPhotoResult.cancelled();
    return validateFile(File(x.path));
  }

  /// Kiểm file: tồn tại, khác rỗng, đúng magic bytes JPEG/PNG, không quá lớn.
  /// Tách `static` để test được mà không cần platform.
  @visibleForTesting
  static Future<LeafPhotoResult> validateFile(File file) async {
    try {
      if (!await file.exists()) {
        return const LeafPhotoResult(
          LeafPhotoOutcome.invalidImage,
          message: 'Không đọc được ảnh vừa chọn.',
        );
      }
      final len = await file.length();
      if (len <= 0) {
        return const LeafPhotoResult(
          LeafPhotoOutcome.invalidImage,
          message: 'Ảnh rỗng hoặc hỏng.',
        );
      }
      if (len > kMaxLeafPhotoBytes) {
        return const LeafPhotoResult(
          LeafPhotoOutcome.tooLarge,
          message: 'Ảnh quá lớn. Hãy chụp lại hoặc chọn ảnh nhỏ hơn.',
        );
      }
      final raf = await file.open();
      List<int> head;
      try {
        head = await raf.read(12);
      } finally {
        await raf.close();
      }
      if (!_looksLikeJpeg(head) && !_looksLikePng(head)) {
        return const LeafPhotoResult(
          LeafPhotoOutcome.invalidImage,
          message: 'Chỉ nhận ảnh JPEG hoặc PNG.',
        );
      }
      return LeafPhotoResult.picked(file);
    } catch (_) {
      return const LeafPhotoResult(
        LeafPhotoOutcome.failed,
        message: 'Không đọc được ảnh vừa chọn.',
      );
    }
  }

  static bool _looksLikeJpeg(List<int> b) =>
      b.length >= 3 && b[0] == 0xFF && b[1] == 0xD8 && b[2] == 0xFF;

  static bool _looksLikePng(List<int> b) =>
      b.length >= 8 &&
      b[0] == 0x89 &&
      b[1] == 0x50 &&
      b[2] == 0x4E &&
      b[3] == 0x47 &&
      b[4] == 0x0D &&
      b[5] == 0x0A &&
      b[6] == 0x1A &&
      b[7] == 0x0A;
}
