import 'package:flutter/material.dart';
import 'package:flutter/semantics.dart';
import 'package:flutter/services.dart';

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
    // Keep the sheet below the status bar: in landscape it otherwise reached
    // the top edge, and the pinned Cancel/Save sat under the status bar,
    // where the phone swallowed taps (seen on the Xiaomi).
    useSafeArea: true,
    // The form draws the same handle itself, so it can drop it when the
    // keyboard leaves almost no room (landscape phone, large text).
    showDragHandle: false,
    // Read the keyboard inset from the SHEET's own context so the sheet
    // rebuilds when the keyboard height changes. The caller's context did not
    // rebuild: after a rotation the phone kept a stale inset and the sheet
    // (and its actions) ended up under the keyboard.
    builder: (sheetContext) => Padding(
      padding:
          EdgeInsets.only(bottom: MediaQuery.viewInsetsOf(sheetContext).bottom),
      child: SeasonMethodologyForm(season: season, focusCode: focusCode),
    ),
  );
}

class SeasonMethodologyForm extends StatefulWidget {
  const SeasonMethodologyForm(
      {super.key, required this.season, this.focusCode});
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

  /// Counts rejected saves. The pinned error summary is keyed by it, so a
  /// repeated invalid Save creates a fresh live region that is announced
  /// again instead of staying silent.
  int _rejectedSaves = 0;

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
      error = days == null
          ? 'Số ngày phải là số nguyên.'
          : cultivationDaysError(days);
    }
    setState(() {
      _daysError = error;
      if (error != null) _rejectedSaves++;
    });
    if (error != null) {
      // Where the platform supports announcements, say the error out loud;
      // elsewhere (Android) the live region below announces it, as Flutter's
      // own field error does.
      if (MediaQuery.supportsAnnounceOf(context)) {
        SemanticsService.sendAnnouncement(
            View.of(context), error, Directionality.of(context));
      }
      return;
    }
    Navigator.of(context).pop(SeasonMethodologyValues(
      ipccWaterRegime: IpccWaterRegime.fromWire(_ipcc),
      preSeasonWaterRegime: PreSeasonWaterRegime.fromWire(_pre),
      cultivationDays: days,
    ));
  }

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    // Found on a physical phone: landscape + keyboard + font 1.8 left only the
    // days field visible, with Save below the keyboard and no visible Cancel.
    // While cramped, Cancel/Save are pinned on top, the intro is hidden and
    // the focused field is scrolled into view. The fields keep their keys,
    // so input and focus survive the switch and rotation.
    final cramped = isCramped(MediaQuery.of(context));
    return SafeArea(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          cramped
              ? _CrampedActions(
                  onSave: _save,
                  error: _daysError,
                  rejectedSaves: _rejectedSaves,
                )
              : const _SheetHandle(),
          Flexible(
            child: SingleChildScrollView(
              padding: EdgeInsets.fromLTRB(AppSpacing.screenH, 0,
                  AppSpacing.screenH, cramped ? AppSpacing.sm : AppSpacing.lg),
              child: FocusReveal(
                enabled: cramped,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    if (!cramped) ...[
                      Text('Thông tin phương pháp tính',
                          style: text.titleMedium),
                      const SizedBox(height: AppSpacing.xxs),
                      Text(
                        'Vụ ${widget.season.seasonCode}. Lưu trên máy trước, tự gửi lên khi có mạng.',
                        style: text.bodySmall
                            ?.copyWith(color: AppColors.textSecondary),
                      ),
                      const SizedBox(height: AppSpacing.md),
                    ],
                    AdaptiveFormField(
                      key: const Key('methodology-ipcc'),
                      label: 'Chế độ nước trong vụ',
                      kind: AdaptiveFieldKind.select,
                      value: _ipcc,
                      options: [
                        for (final r in IpccWaterRegime.values)
                          AdaptiveFieldOption(r.wire, r.labelVi),
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
                      // While cramped, the message is in the pinned row
                      // (the line under the field is scrolled out of the
                      // ~50 dp viewport). The field keeps its error border.
                      showErrorText: !cramped,
                      // Keep '.', ',' and '-' so "1.5" or "-5" reach _save
                      // and are rejected out loud. The digits-only default
                      // turned them into 15 / 5 and saved them silently.
                      inputFormatters: _daysInput,
                    ),
                    if (!cramped) ...[
                      const SizedBox(height: AppSpacing.lg),
                      PrimaryButton(
                        key: const Key('methodology-save'),
                        label: 'Lưu',
                        onPressed: _save,
                      ),
                    ],
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

final _daysInput = [FilteringTextInputFormatter.allow(RegExp(r'[0-9.,\-]'))];

/// Same look as Material's bottom-sheet drag handle (32x4 in a 48 dp area);
/// dragging the sheet still works because the whole sheet is draggable.
class _SheetHandle extends StatelessWidget {
  const _SheetHandle();
  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final size = theme.bottomSheetTheme.dragHandleSize ?? const Size(32, 4);
    return Semantics(
      label: 'Đóng',
      button: true,
      onTap: () => Navigator.of(context).maybePop(),
      child: SizedBox(
        height: kMinInteractiveDimension,
        child: Center(
          child: Container(
            width: size.width,
            height: size.height,
            decoration: BoxDecoration(
              color: theme.bottomSheetTheme.dragHandleColor ??
                  theme.colorScheme.onSurfaceVariant,
              borderRadius: BorderRadius.circular(size.height / 2),
            ),
          ),
        ),
      ),
    );
  }
}

/// Cancel / title / Save in one 48 dp row, used only while cramped.
///
/// After a rejected Save the title is replaced by the validation message, so
/// the error sits next to the Save button that produced it. On the phone
/// (landscape, keyboard, font 1.8) the message under the field was scrolled
/// out of view and the rejected Save looked like it did nothing.
class _CrampedActions extends StatelessWidget {
  const _CrampedActions(
      {required this.onSave, required this.error, required this.rejectedSaves});
  final VoidCallback onSave;
  final String? error;
  final int rejectedSaves;
  @override
  Widget build(BuildContext context) => MediaQuery.withClampedTextScaling(
        maxScaleFactor: 1.2,
        child: SizedBox(
          height: kMinInteractiveDimension,
          child: Row(children: [
            TextButton(
              key: const Key('methodology-cancel'),
              onPressed: () => Navigator.of(context).maybePop(),
              child: const Text('Huỷ'),
            ),
            Expanded(
              child: error == null
                  ? Text('Phương pháp tính',
                      textAlign: TextAlign.center,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.titleSmall)
                  : _ErrorSummary(
                      key: ValueKey('methodology-error-$rejectedSaves'),
                      message: error!),
            ),
            Padding(
              padding: const EdgeInsets.only(right: AppSpacing.xs),
              child: FilledButton(
                key: const Key('methodology-save'),
                onPressed: onSave,
                child: const Text('Lưu'),
              ),
            ),
          ]),
        ),
      );
}

/// The validation message pinned in the cramped action row.
class _ErrorSummary extends StatelessWidget {
  const _ErrorSummary({super.key, required this.message});
  final String message;
  @override
  Widget build(BuildContext context) => Semantics(
        container: true,
        liveRegion: !MediaQuery.supportsAnnounceOf(context),
        child: Row(
          key: const Key('methodology-error-summary'),
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const ExcludeSemantics(
              child:
                  Icon(Icons.error_outline, size: 18, color: AppColors.error),
            ),
            const SizedBox(width: AppSpacing.xxs),
            Flexible(
              child: Text(
                message,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: Theme.of(context)
                    .textTheme
                    .labelMedium
                    ?.copyWith(color: AppColors.error),
              ),
            ),
          ],
        ),
      );
}
