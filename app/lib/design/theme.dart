import 'package:flutter/material.dart';

import 'tokens.dart';

/// Shared Material 3 presentation. Font and artwork are bundled for offline use.
class AgriCarbonTheme {
  const AgriCarbonTheme._();

  static ThemeData light() {
    const scheme = ColorScheme(
      brightness: Brightness.light,
      primary: AppColors.primary,
      onPrimary: Colors.white,
      primaryContainer: AppColors.primarySurface,
      onPrimaryContainer: AppColors.textPrimary,
      secondary: AppColors.headerDark,
      onSecondary: Colors.white,
      secondaryContainer: AppColors.primarySurface,
      onSecondaryContainer: AppColors.textPrimary,
      tertiary: AppColors.warningText,
      onTertiary: Colors.white,
      tertiaryContainer: AppColors.warningSurface,
      onTertiaryContainer: AppColors.warningText,
      error: AppColors.error,
      onError: Colors.white,
      errorContainer: AppColors.errorSurface,
      onErrorContainer: AppColors.error,
      surface: AppColors.surface,
      onSurface: AppColors.textPrimary,
      onSurfaceVariant: AppColors.textSecondary,
      outline: AppColors.controlLine,
      outlineVariant: AppColors.track,
      shadow: Color(0x14000000),
      scrim: Color(0x66000000),
      inverseSurface: AppColors.headerDark,
      onInverseSurface: Colors.white,
      inversePrimary: AppColors.primarySurface,
      surfaceTint: AppColors.primary,
    );

    final textTheme =
        _textTheme(AppColors.textPrimary, AppColors.textSecondary);

    return ThemeData(
      useMaterial3: true,
      fontFamily: AppBrand.fontFamily,
      colorScheme: scheme,
      scaffoldBackgroundColor: AppColors.background,
      canvasColor: AppColors.background,
      textTheme: textTheme,
      splashFactory: InkSparkle.splashFactory,
      visualDensity: VisualDensity.standard,
      appBarTheme: const AppBarTheme(
        backgroundColor: AppColors.headerDark,
        foregroundColor: AppColors.onHeaderPrimary,
        elevation: 0,
        scrolledUnderElevation: 0,
        centerTitle: false,
      ),
      cardTheme: CardThemeData(
        color: AppColors.surface,
        elevation: 0,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
          borderRadius: AppRadii.allCard,
          side: const BorderSide(color: AppColors.border),
        ),
      ),
      dividerTheme: const DividerThemeData(
        color: AppColors.border,
        thickness: 1,
        space: AppSpacing.lg,
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: AppColors.surface,
        contentPadding: const EdgeInsets.symmetric(
          horizontal: AppSpacing.md,
          vertical: AppSpacing.sm + 2,
        ),
        border: _fieldBorder(AppColors.controlLine),
        enabledBorder: _fieldBorder(AppColors.controlLine),
        focusedBorder: _fieldBorder(AppColors.primary, width: 1.6),
        errorBorder: _fieldBorder(AppColors.error),
        focusedErrorBorder: _fieldBorder(AppColors.error, width: 1.6),
        labelStyle: textTheme.labelMedium,
        floatingLabelStyle: const TextStyle(color: AppColors.primary),
        hintStyle:
            textTheme.bodyMedium?.copyWith(color: AppColors.textSecondary),
        helperStyle:
            textTheme.labelSmall?.copyWith(color: AppColors.textSecondary),
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: AppColors.primary,
          foregroundColor: Colors.white,
          disabledBackgroundColor: AppColors.border,
          disabledForegroundColor: AppColors.textSecondary,
          elevation: 0,
          minimumSize: const Size(kMinTouchTarget, kMinTouchTarget),
          padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
          textStyle: textTheme.labelLarge,
          shape: const RoundedRectangleBorder(borderRadius: AppRadii.allField),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          foregroundColor: AppColors.textPrimary,
          side: const BorderSide(color: AppColors.controlLine),
          minimumSize: const Size(kMinTouchTarget, kMinTouchTarget),
          padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
          textStyle: textTheme.labelLarge,
          shape: const RoundedRectangleBorder(borderRadius: AppRadii.allField),
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(
          foregroundColor: AppColors.primary,
          minimumSize: const Size(kMinTouchTarget, kMinTouchTarget),
          textStyle: textTheme.labelLarge,
        ),
      ),
      snackBarTheme: SnackBarThemeData(
        behavior: SnackBarBehavior.floating,
        backgroundColor: AppColors.headerDark,
        contentTextStyle: textTheme.bodyMedium?.copyWith(color: Colors.white),
        shape: const RoundedRectangleBorder(borderRadius: AppRadii.allField),
      ),
      dialogTheme: DialogThemeData(
        backgroundColor: AppColors.surface,
        shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(AppRadii.lg)),
        titleTextStyle: textTheme.titleLarge,
        contentTextStyle: textTheme.bodyLarge,
      ),
      chipTheme: ChipThemeData(
        backgroundColor: AppColors.surface,
        selectedColor: AppColors.primarySurface,
        side: const BorderSide(color: AppColors.border),
        labelStyle: textTheme.labelMedium,
        shape: const StadiumBorder(),
        showCheckmark: false,
      ),
      listTileTheme: const ListTileThemeData(
        iconColor: AppColors.primary,
        textColor: AppColors.textPrimary,
      ),
      progressIndicatorTheme: const ProgressIndicatorThemeData(
        color: AppColors.primary,
      ),
      bottomSheetTheme: const BottomSheetThemeData(
        backgroundColor: AppColors.surface,
        surfaceTintColor: Colors.transparent,
        showDragHandle: true,
        shape: RoundedRectangleBorder(
          borderRadius:
              BorderRadius.vertical(top: Radius.circular(AppRadii.xxl)),
        ),
      ),
      pageTransitionsTheme: PageTransitionsTheme(builders: {
        ...const PageTransitionsTheme().builders,
        TargetPlatform.android: const _BrandPageTransition(),
        TargetPlatform.windows: const _BrandPageTransition(),
        TargetPlatform.linux: const _BrandPageTransition(),
      }),
      navigationBarTheme: NavigationBarThemeData(
        backgroundColor: Colors.transparent,
        surfaceTintColor: Colors.transparent,
        indicatorColor: AppColors.brandGold,
        elevation: 0,
        height: 72,
        labelBehavior: NavigationDestinationLabelBehavior.alwaysShow,
        iconTheme: WidgetStateProperty.resolveWith(
          (states) => IconThemeData(
            color: states.contains(WidgetState.selected)
                ? AppColors.headerDeep
                : AppColors.onHeaderSecondary,
          ),
        ),
        labelTextStyle: WidgetStateProperty.resolveWith(
          (states) => textTheme.labelSmall?.copyWith(
            color: states.contains(WidgetState.selected)
                ? AppColors.brandGold
                : AppColors.onHeaderSecondary,
            fontWeight: FontWeight.w600,
          ),
        ),
      ),
    );
  }

  static OutlineInputBorder _fieldBorder(Color color, {double width = 1}) =>
      OutlineInputBorder(
        borderRadius: AppRadii.allField,
        borderSide: BorderSide(color: color, width: width),
      );

  static TextTheme _textTheme(Color primary, Color secondary) {
    TextStyle s(double size, FontWeight weight,
            {Color? color, double height = 1.35}) =>
        TextStyle(
          fontFamily: AppBrand.fontFamily,
          fontSize: size,
          fontWeight: weight,
          height: height,
          color: color ?? primary,
        );

    return TextTheme(
      // Số liệu "anh hùng" ở màn kết quả carbon (SVG: 42/800).
      displayLarge: s(42, FontWeight.w800, height: 1.1),
      displayMedium: s(30, FontWeight.w700, height: 1.35),
      // Tiêu đề màn trên nền trắng (SVG: 26/750).
      headlineMedium: s(26, FontWeight.w700, height: 1.4),
      headlineSmall: s(22, FontWeight.w700, height: 1.4),
      titleLarge: s(18, FontWeight.w700),
      // Tiêu đề khối / section (SVG: 15/700).
      titleMedium: s(15, FontWeight.w700),
      titleSmall: s(13, FontWeight.w600),
      bodyLarge: s(14, FontWeight.w500),
      bodyMedium: s(13, FontWeight.w400),
      bodySmall: s(12, FontWeight.w400, color: secondary),
      labelLarge: s(14, FontWeight.w600, height: 1.2),
      // Nhãn ô nhập (SVG: 12/600).
      labelMedium: s(12, FontWeight.w600),
      labelSmall: s(11, FontWeight.w400, color: secondary),
    );
  }

  /// Style chữ trên nền header tối — không nằm trong [TextTheme] vì màu ngược.
  static const TextStyle headerTitle = TextStyle(
    fontFamily: AppBrand.fontFamily,
    fontSize: 18,
    fontWeight: FontWeight.w700,
    color: AppColors.onHeaderPrimary,
    height: 1.4,
  );

  static const TextStyle headerSubtitle = TextStyle(
    fontFamily: AppBrand.fontFamily,
    fontSize: 13,
    fontWeight: FontWeight.w500,
    color: AppColors.onHeaderSecondary,
    height: 1.4,
  );
}

class _BrandPageTransition extends PageTransitionsBuilder {
  const _BrandPageTransition();

  @override
  Widget buildTransitions<T>(
      PageRoute<T> route,
      BuildContext context,
      Animation<double> animation,
      Animation<double> secondaryAnimation,
      Widget child) {
    if (MediaQuery.disableAnimationsOf(context)) return child;
    return FadeTransition(opacity: animation, child: child);
  }
}
