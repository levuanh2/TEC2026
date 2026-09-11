/// Điểm chạm phân loại bệnh lá lúa cho màn 24.
///
/// Tài liệu TEC (module 03) chỉ cho phép **4 nhãn bệnh lá**, KHÔNG có "giai
/// đoạn sinh trưởng" hay "mực nước" (dù SVG 24 có vẽ) — xem
/// `docs/modules/03-computer-vision.md` §1–2.
///
/// Model nằm ở `ml/` (ngoài phạm vi `app/`) và HIỆN CHƯA CÓ. Vì vậy bản chạy
/// thật dùng [UnavailableCvInferenceService] — hiện thông báo "chưa cấu hình",
/// KHÔNG bịa nhãn/độ tin cậy. Khi có model/endpoint thật, thay implementation
/// qua constructor của màn (dependency injection) — không sửa UI.
library;

import 'dart:io';

/// 4 nhãn bệnh lá lúa được phép (FR-1b-01). `wire` khớp chuỗi model/endpoint
/// trả về; `vi` là nhãn hiển thị cho nông dân.
enum LeafDiseaseLabel {
  blast('blast', 'Đạo ôn'),
  bacterialBlight('bacterial_blight', 'Bạc lá'),
  brownSpot('brown_spot', 'Đốm nâu'),
  healthy('healthy', 'Lá khỏe');

  const LeafDiseaseLabel(this.wire, this.vi);

  /// Giá trị khớp output model: `blast` | `bacterial_blight` | `brown_spot` |
  /// `healthy`.
  final String wire;

  /// Nhãn tiếng Việt hiển thị.
  final String vi;

  /// Đọc nhãn từ chuỗi `wire`. Ném [FormatException] nếu không thuộc 4 lớp —
  /// KHÔNG ép về một nhãn mặc định (tránh gán nhầm nhãn bệnh).
  static LeafDiseaseLabel fromWire(String value) {
    for (final l in LeafDiseaseLabel.values) {
      if (l.wire == value) return l;
    }
    throw FormatException('Nhãn bệnh lá không hợp lệ: "$value"');
  }
}

/// Ngưỡng độ tin cậy để hiển thị (FR-1b-04). Đây CHỈ là cổng hiển thị phía app:
/// dưới ngưỡng → hiện "cần kiểm tra", KHÔNG khẳng định độ chính xác thực địa.
/// Nguồn quyết định `isUncertain` thật là ở model; hằng số này chỉ dùng khi
/// model không tự đánh dấu.
const double kCvConfidenceThreshold = 0.70;

/// Kết quả nhận biết một ảnh lá.
class CvInferenceResult {
  CvInferenceResult({
    required this.label,
    required this.confidence,
    bool? isUncertain,
  })  : assert(
            confidence >= 0 && confidence <= 1, 'confidence phải trong [0,1]'),
        isUncertain = isUncertain ?? (confidence < kCvConfidenceThreshold);

  final LeafDiseaseLabel label;

  /// Nhãn tiếng Việt tương ứng [label].
  String get labelVi => label.vi;

  /// Độ tin cậy 0..1 do model trả về.
  final double confidence;

  /// `true` khi model tự đánh dấu chưa chắc, HOẶC khi [confidence] dưới
  /// [kCvConfidenceThreshold]. UI phải hiện "Không chắc chắn — cần kiểm tra"
  /// và KHÔNG ép nông dân chấp nhận nhãn.
  final bool isUncertain;
}

/// Ném khi gọi [CvInferenceService.classify] trên một service chưa được cấu
/// hình (chưa có model/endpoint). UI bắt lỗi này để hiện thông báo trung thực,
/// KHÔNG hiện kết quả giả.
class CvInferenceUnavailable implements Exception {
  const CvInferenceUnavailable();

  @override
  String toString() =>
      'CvInferenceUnavailable: nhận dạng bệnh chưa được cấu hình';
}

/// Ném khi ảnh hợp lệ nhưng model/endpoint không xử lý được (ảnh hỏng ở phía
/// suy luận, endpoint 5xx...). Tách khỏi [CvInferenceUnavailable] để UI phân
/// biệt "chưa cấu hình" với "thử lại được".
class CvInferenceFailure implements Exception {
  const CvInferenceFailure([this.message]);
  final String? message;

  @override
  String toString() => 'CvInferenceFailure(${message ?? 'không rõ'})';
}

/// Hợp đồng phân loại bệnh lá. Một ảnh vào → một [CvInferenceResult] ra.
abstract class CvInferenceService {
  /// `false` khi chưa có model/endpoint thật — UI hiện "chưa cấu hình" và
  /// KHÔNG gọi [classify].
  bool get isAvailable;

  /// Phân loại [image] (đã được kiểm hợp lệ JPEG/PNG ở tầng chọn ảnh).
  /// Ném [CvInferenceUnavailable] nếu [isAvailable] == false.
  Future<CvInferenceResult> classify(File image);
}

/// Bản chạy thật khi CHƯA có model/endpoint. Luôn báo chưa sẵn sàng — không
/// bao giờ trả một độ tin cậy hay nhãn dựng sẵn nào.
class UnavailableCvInferenceService implements CvInferenceService {
  const UnavailableCvInferenceService();

  @override
  bool get isAvailable => false;

  @override
  Future<CvInferenceResult> classify(File image) async {
    throw const CvInferenceUnavailable();
  }
}
