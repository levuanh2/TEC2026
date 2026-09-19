import 'package:flutter/material.dart';

import '../design/design.dart';
import '../models/crop_season.dart';
import '../models/crop_season_validation.dart';
import '../models/methodology_enums.dart';

/// Ba thông tin phương pháp tính của vụ mà máy chủ báo thiếu qua readiness
/// (`flow = carbon_methodology`). Cùng ba ô Farmer Web sửa; ở đây giá trị được
/// LƯU TRÊN MÁY rồi đi theo hàng đợi đồng bộ sẵn có (upsert `crop_seasons`) —
/// không qua FastAPI, không có hệ thống đồng bộ thứ hai.
class SeasonMethodologyValues {
  const SeasonMethodologyValues({
    required this.ipccWaterRegime,
    required this.preSeasonWaterRegime,
    required this.cultivationDays,
  });
  final IpccWaterRegime? ipccWaterRegime;
  final PreSeasonWaterRegime? preSeasonWaterRegime;
  final int? cultivationDays;
}

/// Mở sheet; trả về giá trị mới, hoặc `null` khi người dùng huỷ. [focusCode] là
/// `code` của mục readiness đã bấm (để nhấn mạnh đúng ô) — không quyết định gì.
Future<SeasonMethodologyValues?> showSeasonMethodologySheet(
  BuildContext context, {
  required CropSeason season,
  String? focusCode,
}) {
  return showModalBottomSheet<SeasonMethodologyValues>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    builder: (_) => Padding(
      padding: EdgeInsets.only(bottom: MediaQuery.of(context).viewInsets.bottom),
      child: SeasonMethodologyForm(season: season, focusCode: focusCode),
    ),
  );
}

class SeasonMethodologyForm extends StatefulWidget {
  const SeasonMethodologyForm({super.key, required this.season, this.focusCode});
  final CropSeason season;
  final String? focusCode;

  @override
  State<SeasonMethodologyForm> createState() => _SeasonMethodologyFormState();
}

class _SeasonMethodologyFormState extends State<SeasonMethodologyForm> {
  late String? _ipcc = widget.season.ipccWaterRegime?.wire;
  late String? _pre = widget.season.preSeasonWaterRegime?.wire;
  late final _days = TextEditingController(
    text: widget.season.cultivationDays?.toString() ?? '',
  );
  String? _daysError;

  @override
  void dispose() {
    _days.dispose();
    super.dispose();
  }

  void _save() {
    final raw = _days.text.trim();
    int? days;
    String? error;
    if (raw.isNotEmpty) {
      days = int.tryParse(raw);
      error = days == null ? 'Số ngày phải là số nguyên.' : cultivationDaysError(days);
    }
    setState(() => _daysError = error);
    if (error != null) return;
    Navigator.of(context).pop(SeasonMethodologyValues(
      ipccWaterRegime: IpccWaterRegime.fromWire(_ipcc),
      preSeasonWaterRegime: PreSeasonWaterRegime.fromWire(_pre),
      cultivationDays: days,
    ));
  }

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return SafeArea(
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(
            AppSpacing.screenH, 0, AppSpacing.screenH, AppSpacing.lg),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          mainAxisSize: MainAxisSize.min,
          children: [
            Text('Thông tin phương pháp tính', style: text.titleMedium),
            const SizedBox(height: AppSpacing.xxs),
            Text(
              'Vụ ${widget.season.seasonCode}. Lưu trên máy trước, tự gửi lên khi có mạng.',
              style: text.bodySmall?.copyWith(color: AppColors.textSecondary),
            ),
            const SizedBox(height: AppSpacing.md),
            AdaptiveFormField(
              key: const Key('methodology-ipcc'),
              label: 'Chế độ nước trong vụ',
              kind: AdaptiveFieldKind.select,
              value: _ipcc,
              options: [
                for (final r in IpccWaterRegime.values) AdaptiveFieldOption(r.wire, r.labelVi),
              ],
              onValueChanged: (v) => setState(() => _ipcc = v),
            ),
            const SizedBox(height: AppSpacing.sm),
            AdaptiveFormField(
              key: const Key('methodology-pre'),
              label: 'Chế độ nước trước vụ',
              kind: AdaptiveFieldKind.select,
              value: _pre,
              options: [
                for (final r in PreSeasonWaterRegime.values)
                  AdaptiveFieldOption(r.wire, r.labelVi),
              ],
              onValueChanged: (v) => setState(() => _pre = v),
            ),
            const SizedBox(height: AppSpacing.sm),
            AdaptiveFormField(
              key: const Key('methodology-days'),
              label: 'Số ngày canh tác',
              kind: AdaptiveFieldKind.integer,
              controller: _days,
              hint: 'Từ gieo sạ tới thu hoạch, ví dụ 100',
              errorText: _daysError,
            ),
            const SizedBox(height: AppSpacing.lg),
            PrimaryButton(
              key: const Key('methodology-save'),
              label: 'Lưu',
              onPressed: _save,
            ),
          ],
        ),
      ),
    );
  }
}
