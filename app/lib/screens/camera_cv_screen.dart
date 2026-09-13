import 'dart:io';

import 'package:flutter/material.dart';

import '../design/design.dart';
import '../models/crop_season.dart';
import '../services/cv_feedback_store.dart';
import '../services/cv_inference_service.dart';
import '../services/leaf_photo_source.dart';

/// Màn 24 — "Kiểm tra ảnh lá lúa".
///
/// Chỉ phân loại **bệnh lá** (4 nhãn: Đạo ôn / Bạc lá / Đốm nâu / Lá khỏe).
/// KHÔNG nhận diện "giai đoạn sinh trưởng" hay "mực nước" dù SVG 24 có vẽ —
/// tài liệu TEC chỉ cho phép bài toán bệnh lá (docs/modules/03-computer-vision.md).
///
/// Model nằm ở `ml/` và chưa có → [inference] thường là
/// [UnavailableCvInferenceService]: hiện "chưa cấu hình", KHÔNG bịa độ tin cậy
/// hay nhãn nào. Khi có service thật, chỉ cần đổi implementation ở
/// `AppRoutes.openCameraCv` — màn này không đổi.
class CameraCvScreen extends StatefulWidget {
  const CameraCvScreen({
    super.key,
    required this.inference,
    required this.photoSource,
    required this.feedbackStore,
    required this.cropSeason,
    this.plotLabel,
  });

  final CvInferenceService inference;
  final LeafPhotoSource photoSource;
  final CvFeedbackStore feedbackStore;

  /// Vụ đang canh tác — ảnh kiểm tra được gắn với vụ này. `null` ⇒ chưa chọn vụ.
  final CropSeason? cropSeason;

  /// Nhãn hiển thị của thửa ruộng (tên hoặc mã).
  final String? plotLabel;

  @override
  State<CameraCvScreen> createState() => _CameraCvScreenState();
}

class _CameraCvScreenState extends State<CameraCvScreen> {
  File? _photo;
  bool _picking = false;
  bool _analyzing = false;

  CvInferenceResult? _result;
  bool _inferenceError = false;

  /// Sự cố lần chụp/chọn gần nhất (quyền, không có máy ảnh, ảnh sai định dạng…).
  LeafPhotoResult? _photoIssue;

  /// Đã lưu phản hồi "Xác nhận đúng" / "Chỉnh lại" cho ảnh hiện tại.
  bool _feedbackSaved = false;
  String? _feedbackSavedMsg;

  bool get _hasSeason => widget.cropSeason != null;

  @override
  Widget build(BuildContext context) {
    return AppScaffold(
      header: const AppHeader(
        title: 'AgriCarbon',
        subtitle: 'Kiểm tra ảnh lá lúa',
        showBackButton: true,
      ),
      body: _hasSeason ? _content() : _noSeason(),
    );
  }

  Widget _noSeason() => const EmptyState(
        icon: Icons.eco_outlined,
        title: 'Chưa chọn vụ canh tác',
        message:
            'Ảnh kiểm tra lá lúa được gắn với vụ đang canh tác. Hãy chọn vụ ở '
            'màn Trang chủ rồi quay lại đây.',
      );

  Widget _content() {
    final text = Theme.of(context).textTheme;
    final season = widget.cropSeason!;
    final plot = widget.plotLabel;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const SizedBox(height: AppSpacing.md),
        Text(
          plot == null
              ? 'Vụ ${season.seasonCode}'
              : 'Ruộng $plot · Vụ ${season.seasonCode}',
          style: text.bodyMedium?.copyWith(color: AppColors.textSecondary),
        ),
        const SizedBox(height: AppSpacing.md),
        _pictureArea(),
        const SizedBox(height: AppSpacing.md),
        ..._belowPicture(),
        const SizedBox(height: AppSpacing.lg),
      ],
    );
  }

  // -- Khung ảnh ------------------------------------------------------------

  Widget _pictureArea() {
    if (_photo == null) {
      return AspectRatio(
        aspectRatio: 4 / 3,
        child: DecoratedBox(
          decoration: BoxDecoration(
            color: AppColors.track,
            borderRadius: AppRadii.allCard,
            border: Border.all(color: AppColors.border),
          ),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              const Icon(Icons.center_focus_weak_outlined,
                  size: 44, color: AppColors.textSecondary),
              const SizedBox(height: AppSpacing.xs),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
                child: Text(
                  'Đưa một lá lúa vào giữa khung, nền đơn giản, đủ sáng.',
                  textAlign: TextAlign.center,
                  style: Theme.of(context)
                      .textTheme
                      .bodySmall
                      ?.copyWith(color: AppColors.textSecondary),
                ),
              ),
            ],
          ),
        ),
      );
    }
    return ClipRRect(
      borderRadius: AppRadii.allCard,
      child: AspectRatio(
        aspectRatio: 4 / 3,
        child: Image.file(
          _photo!,
          fit: BoxFit.cover,
          gaplessPlayback: true,
          errorBuilder: (_, __, ___) => const ColoredBox(
            color: AppColors.track,
            child: Center(
              child: Icon(Icons.broken_image_outlined,
                  color: AppColors.textSecondary),
            ),
          ),
        ),
      ),
    );
  }

  // -- Nội dung dưới khung ảnh --------------------------------------------

  List<Widget> _belowPicture() {
    if (_photo == null) {
      return [
        PrimaryButton(
          label: 'Chụp ảnh',
          icon: Icons.photo_camera_outlined,
          onPressed: _picking ? null : () => _pickFrom(_PickWhere.camera),
          loading: _picking,
        ),
        const SizedBox(height: AppSpacing.sm),
        SecondaryButton(
          label: 'Chọn từ thư viện',
          icon: Icons.photo_library_outlined,
          expanded: true,
          onPressed: _picking ? null : () => _pickFrom(_PickWhere.gallery),
        ),
        if (_photoIssue != null) ...[
          const SizedBox(height: AppSpacing.md),
          _PhotoIssueCard(
            issue: _photoIssue!,
            onOpenSettings: _openSettings,
          ),
        ],
      ];
    }

    return [
      SecondaryButton(
        label: 'Chụp/chọn lại',
        icon: Icons.refresh,
        expanded: true,
        onPressed: (_picking || _analyzing) ? null : _startOver,
      ),
      const SizedBox(height: AppSpacing.md),
      ..._resultArea(),
    ];
  }

  List<Widget> _resultArea() {
    if (_feedbackSaved) {
      return [
        AppCard(
          variant: AppCardVariant.highlight,
          child: Row(
            children: [
              const Icon(Icons.check_circle_outline, color: AppColors.primary),
              const SizedBox(width: AppSpacing.xs),
              Expanded(
                child: Text(
                  _feedbackSavedMsg ?? 'Đã lưu phản hồi (chỉ trên máy này).',
                  style: Theme.of(context).textTheme.bodyMedium,
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: AppSpacing.sm),
        SecondaryButton(
          label: 'Kiểm tra ảnh khác',
          icon: Icons.add_a_photo_outlined,
          expanded: true,
          onPressed: _startOver,
        ),
      ];
    }

    if (!widget.inference.isAvailable) {
      return const [_UnavailableCard()];
    }

    if (_analyzing) {
      return [
        const Padding(
          padding: EdgeInsets.symmetric(vertical: AppSpacing.md),
          child: LoadingState(message: 'Đang nhận biết bệnh lá…'),
        ),
      ];
    }

    if (_inferenceError) {
      return [
        Padding(
          padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
          child: ErrorState(
            title: 'Chưa nhận biết được ảnh này',
            message:
                'Thử chụp lại rõ hơn (một lá, đủ sáng) hoặc thử lại sau ít phút.',
            retryLabel: 'Thử lại',
            onRetry: _analyze,
          ),
        ),
      ];
    }

    final r = _result;
    if (r == null) return const [];

    return [
      _ResultCard(result: r),
      const SizedBox(height: AppSpacing.md),
      PrimaryButton(
        label: 'Xác nhận đúng',
        icon: Icons.check,
        onPressed: () => _saveFeedback(CvFeedbackVerdict.confirmed),
      ),
      const SizedBox(height: AppSpacing.sm),
      SecondaryButton(
        label: 'Chỉnh lại',
        icon: Icons.edit_outlined,
        expanded: true,
        onPressed: _openCorrectionSheet,
      ),
    ];
  }

  // -- Hành động ---------------------------------------------------------

  Future<void> _pickFrom(_PickWhere where) async {
    setState(() {
      _picking = true;
      _photoIssue = null;
    });
    final res = where == _PickWhere.camera
        ? await widget.photoSource.capture()
        : await widget.photoSource.pickFromGallery();
    if (!mounted) return;
    setState(() => _picking = false);

    switch (res.outcome) {
      case LeafPhotoOutcome.picked:
        setState(() {
          _photo = res.file;
          _result = null;
          _inferenceError = false;
          _feedbackSaved = false;
          _feedbackSavedMsg = null;
          _photoIssue = null;
        });
        await _analyze();
      case LeafPhotoOutcome.cancelled:
        break;
      default:
        setState(() => _photoIssue = res);
    }
  }

  Future<void> _analyze() async {
    final photo = _photo;
    if (photo == null || !widget.inference.isAvailable) return;
    setState(() {
      _analyzing = true;
      _inferenceError = false;
      _result = null;
    });
    try {
      final r = await widget.inference.classify(photo);
      if (!mounted) return;
      setState(() {
        _analyzing = false;
        _result = r;
      });
    } on CvInferenceUnavailable {
      // Service lật sang "chưa cấu hình" giữa chừng — để card unavailable hiện.
      if (!mounted) return;
      setState(() => _analyzing = false);
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _analyzing = false;
        _inferenceError = true;
      });
    }
  }

  Future<void> _openSettings() async {
    await widget.photoSource.openSettings();
  }

  void _startOver() {
    setState(() {
      _photo = null;
      _result = null;
      _inferenceError = false;
      _analyzing = false;
      _feedbackSaved = false;
      _feedbackSavedMsg = null;
      _photoIssue = null;
    });
  }

  Future<void> _openCorrectionSheet() async {
    final r = _result;
    if (r == null) return;
    final picked = await showModalBottomSheet<LeafDiseaseLabel>(
      context: context,
      showDragHandle: true,
      builder: (sheetContext) => _CorrectionSheet(current: r.label),
    );
    if (picked == null || !mounted) return;
    await _saveFeedback(
      CvFeedbackVerdict.corrected,
      corrected: picked,
    );
  }

  Future<void> _saveFeedback(
    CvFeedbackVerdict verdict, {
    LeafDiseaseLabel? corrected,
  }) async {
    final season = widget.cropSeason;
    final r = _result;
    if (season == null || r == null) return;

    await widget.feedbackStore.add(
      season.clientId,
      CvFeedbackEntry.fromResult(
        result: r,
        verdict: verdict,
        imagePath: _photo?.path,
        correctedLabel: corrected,
      ),
    );
    if (!mounted) return;

    final msg = verdict == CvFeedbackVerdict.confirmed
        ? 'Đã lưu xác nhận của bạn (chỉ trên máy này).'
        : 'Đã lưu chỉnh sửa: “${corrected?.vi ?? ''}” (chỉ trên máy này).';
    setState(() {
      _feedbackSaved = true;
      _feedbackSavedMsg = msg;
    });
    final messenger = ScaffoldMessenger.maybeOf(context);
    messenger?.showSnackBar(SnackBar(content: Text(msg)));
  }
}

enum _PickWhere { camera, gallery }

// -- Card: model chưa cấu hình ------------------------------------------

class _UnavailableCard extends StatelessWidget {
  const _UnavailableCard();

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return AppCard(
      variant: AppCardVariant.warning,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.info_outline, color: AppColors.warningText),
              const SizedBox(width: AppSpacing.xs),
              Expanded(
                child: Text('Nhận dạng bệnh chưa được cấu hình',
                    style: text.titleSmall),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.xs),
          Text(
            'Mô hình phân loại bệnh lá lúa đang được xây dựng. Khi sẵn sàng, '
            'ảnh bạn chụp sẽ được nhận biết ngay tại đây. Hiện app chưa đưa ra '
            'kết quả để tránh phán đoán thiếu cơ sở.',
            style: text.bodyMedium?.copyWith(color: AppColors.textSecondary),
          ),
        ],
      ),
    );
  }
}

// -- Card: kết quả nhận biết ------------------------------------------

class _ResultCard extends StatelessWidget {
  const _ResultCard({required this.result});
  final CvInferenceResult result;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final uncertain = result.isUncertain;
    return AppCard(
      variant: uncertain ? AppCardVariant.warning : AppCardVariant.highlight,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Kết quả nhận biết',
              style:
                  text.labelMedium?.copyWith(color: AppColors.textSecondary)),
          const SizedBox(height: AppSpacing.xxs),
          Text(result.labelVi, style: text.headlineSmall),
          const SizedBox(height: AppSpacing.sm),
          Row(
            children: [
              Text('Độ tin cậy',
                  style: text.bodyMedium
                      ?.copyWith(color: AppColors.textSecondary)),
              const Spacer(),
              Text(AppFormat.percent(result.confidence),
                  style: text.titleMedium),
            ],
          ),
          if (uncertain) ...[
            const SizedBox(height: AppSpacing.sm),
            const StatusBadge(
              label: 'Cần kiểm tra',
              tone: StatusTone.warning,
              icon: Icons.help_outline,
            ),
            const SizedBox(height: AppSpacing.xs),
            Text(
              'Không chắc chắn — cần kiểm tra. Hãy đối chiếu thực tế trước khi '
              'dựa vào kết quả này; đừng chọn nhãn nếu chưa chắc.',
              style: text.bodySmall?.copyWith(color: AppColors.warningText),
            ),
          ],
          const SizedBox(height: AppSpacing.sm),
          Text(
            'Đây là kết quả sơ bộ từ ảnh, không thay thế việc thăm đồng. Chưa '
            'có số liệu độ chính xác trên đồng ruộng.',
            style: text.labelSmall?.copyWith(color: AppColors.textSecondary),
          ),
        ],
      ),
    );
  }
}

// -- Card: sự cố chụp/chọn ảnh --------------------------------------

class _PhotoIssueCard extends StatelessWidget {
  const _PhotoIssueCard({required this.issue, required this.onOpenSettings});

  final LeafPhotoResult issue;
  final Future<void> Function() onOpenSettings;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final showSettings =
        issue.outcome == LeafPhotoOutcome.permissionPermanentlyDenied;
    final tone = switch (issue.outcome) {
      LeafPhotoOutcome.cameraUnavailable => AppCardVariant.plain,
      _ => AppCardVariant.warning,
    };
    return AppCard(
      variant: tone,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            issue.message ?? 'Không mở được máy ảnh/thư viện.',
            style: text.bodyMedium,
          ),
          if (showSettings) ...[
            const SizedBox(height: AppSpacing.sm),
            PrimaryButton(
              label: 'Mở Cài đặt',
              icon: Icons.settings_outlined,
              onPressed: onOpenSettings,
            ),
          ],
        ],
      ),
    );
  }
}

// -- Bottom sheet: chỉnh lại nhãn ----------------------------------

class _CorrectionSheet extends StatefulWidget {
  const _CorrectionSheet({required this.current});
  final LeafDiseaseLabel current;

  @override
  State<_CorrectionSheet> createState() => _CorrectionSheetState();
}

class _CorrectionSheetState extends State<_CorrectionSheet> {
  late LeafDiseaseLabel _choice = widget.current;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return SafeArea(
      top: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(
          AppSpacing.screenH,
          0,
          AppSpacing.screenH,
          AppSpacing.md,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text('Chọn nhãn đúng', style: text.titleMedium),
            const SizedBox(height: AppSpacing.xs),
            Text(
              'Chọn tình trạng bạn quan sát thấy trên lá. Lựa chọn được lưu '
              'trên máy để cải thiện về sau.',
              style: text.bodySmall?.copyWith(color: AppColors.textSecondary),
            ),
            const SizedBox(height: AppSpacing.sm),
            RadioGroup<LeafDiseaseLabel>(
              groupValue: _choice,
              onChanged: (v) {
                if (v != null) setState(() => _choice = v);
              },
              child: Column(
                children: [
                  for (final label in LeafDiseaseLabel.values)
                    RadioListTile<LeafDiseaseLabel>(
                      value: label,
                      title: Text(label.vi),
                      contentPadding: EdgeInsets.zero,
                    ),
                ],
              ),
            ),
            const SizedBox(height: AppSpacing.sm),
            PrimaryButton(
              label: 'Lưu chỉnh sửa',
              onPressed: () => Navigator.of(context).pop(_choice),
            ),
          ],
        ),
      ),
    );
  }
}
