// Shared AgriCarbon palette, aligned with the web visual refresh (2026-11).
//
// Quy tắc: KHÔNG viết mã màu / khoảng cách / bo góc trực tiếp trong screen —
// mọi giá trị hình thức phải đi qua đây hoặc qua ThemeData ở `theme.dart`.
//
// Frame tham chiếu của SVG là 430×932 (một máy Android tầm trung). Các hằng
// `kRef*` chỉ để hiểu bố cục gốc — layout thật phải co giãn (xem
// `AppBreakpoints`, `AppScaffold`), KHÔNG hardcode kích thước toàn màn hình.

import 'package:flutter/material.dart';

/// Kích thước khung thiết kế gốc — chỉ dùng để đối chiếu tỷ lệ, không khoá layout.
const double kRefFrameWidth = 430;
const double kRefFrameHeight = 932;
const double kRefHeaderHeight = 86;
const double kRefBottomNavHeight = 82;

/// Vùng chạm tối thiểu (Material accessibility) — mọi nút/again phải ≥ 48×48.
const double kMinTouchTarget = 48;

class AppColors {
  const AppColors._();

  /// Nền chính của mọi màn hình.
  static const background = Color(0xFFF7FAF8);

  /// Header tối (thanh trên cùng) + nền các khối nhấn mạnh tối.
  static const headerDark = Color(0xFF164E3D);
  static const headerDeep = Color(0xFF103B30);

  /// Chữ chính trên nền sáng.
  static const textPrimary = Color(0xFF183E32);

  /// Chữ phụ / mô tả trên nền sáng.
  static const textSecondary = Color(0xFF586D62);

  /// Màu thương hiệu — nút chính, icon nhấn, trạng thái tốt.
  static const primary = Color(0xFF23664F);

  /// Nền xanh nhạt cho card thông tin / pill trạng thái tốt.
  static const primarySurface = Color(0xFFE0F2EC);

  /// Viền các ô nhập, card nền trắng.
  static const border = Color(0xFFD9E5DE);
  static const controlLine = Color(0xFF82958A);

  // Decorative/domain colour is kept separate from warning and error states.
  static const leafSurface = Color(0xFFEAF3DB);
  static const waterSurface = Color(0xFFE4F2F9);
  static const grainSurface = Color(0xFFFFF3D8);
  static const earthSurface = Color(0xFFF5ECE1);
  static const infoSurface = Color(0xFFEDF0FA);
  static const leafInk = Color(0xFF40623A);
  static const waterInk = Color(0xFF2D5A6C);
  static const grainInk = Color(0xFF735B30);
  static const earthInk = Color(0xFF715238);
  static const brandGold = Color(0xFFE7CD82);
  static const shadow = Color(0x0D1A452F);

  /// Bề mặt trắng (card, ô nhập).
  static const surface = Color(0xFFFFFFFF);

  /// Cảnh báo / "cần kiểm tra" — nền + chữ (đi theo cặp).
  static const warningSurface = Color(0xFFFFF4DF);
  static const warningText = Color(0xFF80511B);

  /// Lỗi thật (mất phiên, không có quyền, 500...). SVG không định nghĩa riêng —
  /// dùng đỏ Material chuẩn, tách hẳn khỏi "cảnh báo" màu hổ phách ở trên.
  static const error = Color(0xFFB3261E);
  static const errorSurface = Color(0xFFFCECEA);

  /// Chữ phụ trên nền header tối (tiêu đề phụ, dòng mô tả).
  static const onHeaderPrimary = Color(0xFFFFFFFF);
  static const onHeaderSecondary = Color(0xFFD5E5DF);

  /// Chấm trạng thái mạng nhỏ ở góc header.
  static const onHeaderDot = Color(0xFFB8D2C7);

  /// Rãnh nền của thanh tỷ lệ / progress khi chưa lấp đầy.
  static const track = Color(0xFFE9EEEB);
}

class AppBrand {
  const AppBrand._();
  static const fontFamily = 'BeVietnamPro';
  static const slogan = 'Số hóa canh tác - Xanh hóa tương lai';
  static const riceImage = 'assets/images/mekong-rice.webp';
}

class AppGradients {
  const AppGradients._();
  static const workspace = LinearGradient(
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
    colors: [Color(0xFFF2F7E9), AppColors.background, Color(0xFFE8F3F7)],
    stops: [0, .55, 1],
  );
  static const header = LinearGradient(
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
    colors: [AppColors.headerDark, AppColors.headerDeep],
  );
}

enum AppTone { neutral, leaf, water, grain, earth, carbon, info }

extension AppToneColors on AppTone {
  Color get surface => switch (this) {
        AppTone.neutral => AppColors.surface,
        AppTone.leaf => AppColors.leafSurface,
        AppTone.water => AppColors.waterSurface,
        AppTone.grain => AppColors.grainSurface,
        AppTone.earth => AppColors.earthSurface,
        AppTone.carbon => AppColors.primarySurface,
        AppTone.info => AppColors.infoSurface,
      };
  Color get ink => switch (this) {
        AppTone.leaf => AppColors.leafInk,
        AppTone.water => AppColors.waterInk,
        AppTone.grain => AppColors.grainInk,
        AppTone.earth => AppColors.earthInk,
        _ => AppColors.primary,
      };
}

AppTone activityTone(String? type) => switch (type) {
      'seeding' || 'pesticide' => AppTone.leaf,
      'irrigation' => AppTone.water,
      'straw_management' || 'harvest' => AppTone.grain,
      'fertilizer' || 'fuel' => AppTone.earth,
      _ => AppTone.carbon,
    };

/// Khoảng cách — thang 4pt. `screenH` là padding ngang chuẩn của mọi màn (SVG = 24).
class AppSpacing {
  const AppSpacing._();

  static const double xxs = 4;
  static const double xs = 8;
  static const double sm = 12;
  static const double md = 16;
  static const double lg = 24;
  static const double xl = 32;
  static const double xxl = 48;

  /// Padding ngang chuẩn của nội dung màn hình.
  static const double screenH = 24;

  /// Padding dọc mặc định giữa các nhóm nội dung.
  static const double sectionGap = 16;
}

/// Bo góc — đúng 6 mức trong SVG. Dùng [card]/[field]/[pill]/[sheet] theo ngữ
/// nghĩa thay vì nhớ số.
class AppRadii {
  const AppRadii._();

  static const double xs = 10; // ô nhập, nút
  static const double sm = 12; // card danh sách
  static const double md = 14; // card nhỏ
  static const double lg = 16; // card kết quả
  static const double xl = 18; // khối nhấn mạnh
  static const double xxl = 22; // panel lớn (màn đăng nhập)

  static const Radius field = Radius.circular(xs);
  static const Radius card = Radius.circular(lg);
  static const Radius pill = Radius.circular(999);

  static const BorderRadius allField = BorderRadius.all(field);
  static const BorderRadius allCard = BorderRadius.all(card);
  static const BorderRadius allPill = BorderRadius.all(pill);
}

/// Thời lượng animation dùng chung — giữ nhất quán, tránh mỗi chỗ một con số.
class AppDurations {
  const AppDurations._();

  static const fast = Duration(milliseconds: 150);
  static const normal = Duration(milliseconds: 250);
}

/// Ngưỡng chiều rộng để layout tự thích ứng (360 / 390 / 430 là các máy mục tiêu).
/// Không dùng để khoá kích thước — chỉ để quyết định số cột lưới, v.v.
class AppBreakpoints {
  const AppBreakpoints._();

  static const double compact = 360;
  static const double medium = 400;

  /// Số cột cho lưới nút "ghi nhanh": 1 cột khi máy rất hẹp, 2 cột còn lại.
  static int quickActionColumns(double width) => width < 320 ? 1 : 2;
}
