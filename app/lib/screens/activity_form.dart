import 'package:flutter/material.dart';
import 'package:uuid/uuid.dart';

import '../db/local_database.dart';
import '../design/design.dart';
import '../models/activity.dart';
import '../models/activity_field_spec.dart';
import '../models/activity_validation.dart';
import '../models/crop_season.dart';
import '../models/methodology_enums.dart';

final _uuid = Uuid();

/// Form động ghi/sửa 1 Activity. Field `key` khớp cột bảng chi tiết thật.
///
/// - Lưu THẲNG SQLite trong transaction, KHÔNG gọi mạng ([LocalDatabase.saveActivity]).
/// - Sửa giữ nguyên `clientEventId` và `type` (đổi type = mồ côi bảng chi tiết
///   trên server → form KHÔNG có ô chọn type).
/// - Input sai định dạng → báo lỗi tại ô, KHÔNG biến thành null rồi lưu.
class ActivityForm extends StatefulWidget {
  const ActivityForm({
    super.key,
    required this.db,
    required this.cropSeasonClientId,
    required this.activityType,
    required this.onSaved,
    this.existing,
    this.online = true,
  });

  final LocalDatabase db;
  final String cropSeasonClientId;
  final String activityType;
  final Activity? existing;
  final bool online;

  /// Gọi sau khi lưu xong (parent lo điều hướng / refresh).
  final Future<void> Function() onSaved;

  @override
  State<ActivityForm> createState() => _ActivityFormState();
}

class _ActivityFormState extends State<ActivityForm> {
  final _text = <String, TextEditingController>{};
  final _select = <String, String?>{};
  final _tristate = <String, bool?>{};
  final _noteCtl = TextEditingController();

  late DateTime _occurredAt;
  final _fieldErrors = <String, String>{};
  String? _occurredAtError;
  bool _saving = false;
  CropSeason? _activeSeason;

  List<ActivityFieldSpec> get _specs =>
      kActivityFieldSpecs[widget.activityType] ?? const [];

  bool get _isEdit => widget.existing != null;

  @override
  void initState() {
    super.initState();
    final existing = widget.existing;
    _occurredAt = existing?.occurredAt ?? DateTime.now();
    _noteCtl.text = existing?.note ?? '';

    for (final spec in _specs) {
      final raw = existing?.payload[spec.key];
      switch (spec.kind) {
        case ActivityFieldKind.select:
          _select[spec.key] = raw as String?;
        case ActivityFieldKind.tristate:
          _tristate[spec.key] = raw is bool ? raw : null;
        case ActivityFieldKind.text:
        case ActivityFieldKind.decimal:
        case ActivityFieldKind.integer:
          _text[spec.key] = TextEditingController(
            text: raw == null ? '' : _stringify(raw),
          );
      }
    }
    _loadSeason();
  }

  Future<void> _loadSeason() async {
    final s =
        await widget.db.getCropSeasonByClientId(widget.cropSeasonClientId);
    if (mounted) setState(() => _activeSeason = s);
  }

  @override
  void dispose() {
    for (final c in _text.values) {
      c.dispose();
    }
    _noteCtl.dispose();
    super.dispose();
  }

  static String _stringify(Object v) {
    if (v is double && v == v.roundToDouble()) return v.toInt().toString();
    return v.toString();
  }

  Map<String, ParsedField> _collect() {
    final out = <String, ParsedField>{};
    for (final spec in _specs) {
      switch (spec.kind) {
        case ActivityFieldKind.select:
          final v = _select[spec.key];
          out[spec.key] =
              v == null ? const ParsedField.empty() : ParsedField(v, null);
        case ActivityFieldKind.tristate:
          final v = _tristate[spec.key];
          out[spec.key] = v == null
              ? const ParsedField.empty()
              : ParsedField(v ? 'true' : 'false', null);
        case ActivityFieldKind.text:
        case ActivityFieldKind.decimal:
        case ActivityFieldKind.integer:
          out[spec.key] = parseActivityField(spec, _text[spec.key]!.text);
      }
    }
    return out;
  }

  List<String> get _liveWarnings {
    // Chỉ cảnh báo AWD thiếu drainage count — tính từ state hiện tại.
    return validateActivity(
      type: widget.activityType,
      parsed: {
        'method': _select['method'] == null
            ? const ParsedField.empty()
            : ParsedField(_select['method']!, null),
      },
      occurredAt: _occurredAt,
      activeSeason: _activeSeason,
    ).warnings;
  }

  Future<void> _pickDateTime() async {
    final now = DateTime.now();
    final date = await showDatePicker(
      context: context,
      initialDate: _occurredAt.isAfter(now) ? now : _occurredAt,
      firstDate: DateTime(2020),
      lastDate: now,
    );
    if (date == null || !mounted) return;
    final time = await showTimePicker(
      context: context,
      initialTime: TimeOfDay.fromDateTime(_occurredAt),
    );
    if (!mounted) return;
    final t = time ?? TimeOfDay.fromDateTime(_occurredAt);
    setState(() {
      _occurredAt = DateTime(date.year, date.month, date.day, t.hour, t.minute);
      _occurredAtError = null;
    });
  }

  Future<void> _save() async {
    if (_saving) return;
    FocusScope.of(context).unfocus();

    final parsed = _collect();
    final result = validateActivity(
      type: widget.activityType,
      parsed: parsed,
      occurredAt: _occurredAt,
      activeSeason: _activeSeason,
    );
    if (result.hasError) {
      setState(() {
        _fieldErrors
          ..clear()
          ..addAll(result.fieldErrors);
        _occurredAtError = result.occurredAtError;
      });
      return;
    }

    setState(() {
      _saving = true;
      _fieldErrors.clear();
      _occurredAtError = null;
    });

    final payload = <String, dynamic>{};
    for (final entry in parsed.entries) {
      final v = entry.value.value;
      if (v == null) continue;
      if (v == 'true') {
        payload[entry.key] = true;
      } else if (v == 'false') {
        payload[entry.key] = false;
      } else {
        payload[entry.key] = v;
      }
    }
    final note = _noteCtl.text.trim().isEmpty ? null : _noteCtl.text.trim();

    final existing = widget.existing;
    final activity = existing == null
        ? Activity(
            clientEventId: _uuid.v4(),
            cropSeasonId: widget.cropSeasonClientId,
            type: widget.activityType,
            occurredAt: _occurredAt,
            payload: payload,
            note: note,
            createdAt: DateTime.now(),
          )
        : existing.editedWith(
            occurredAt: _occurredAt,
            payload: payload,
            note: note,
            clearNote: note == null,
          );

    await widget.db.saveActivity(activity); // transaction, không gọi mạng
    // Kết quả Carbon đã lưu (nếu có) giờ có thể đã cũ — màn Carbon so mốc này
    // với `calculated_at` để nhắc "cần tính lại"; không so công thức.
    await widget.db.markCarbonInputsChanged(widget.cropSeasonClientId);
    if (!mounted) return;
    setState(() => _saving = false);
    await widget.onSaved();
  }

  @override
  Widget build(BuildContext context) {
    // Phòng vệ cuối: loại không thuộc 7 enum → KHÔNG dựng form, KHÔNG cho lưu
    // (chặn mọi sentinel như `__cv__` lỡ lọt tới đây).
    if (!kActivityTypes.contains(widget.activityType)) {
      return const ErrorState(
        title: 'Loại công việc không hợp lệ',
        message:
            'Không ghi được công việc này. Vui lòng chọn lại từ danh sách.',
      );
    }

    // Vụ đã kết thúc (thu hoạch / chốt / huỷ): nhật ký chỉ còn để xem. Chặn ở
    // form dùng chung nên mọi lối vào (Trang chủ, Ghi nhanh, chi tiết vụ, sửa)
    // đều như nhau; hệ thống cũng từ chối nếu một bản ghi cũ vẫn được gửi.
    final season = _activeSeason;
    if (season != null && !seasonAcceptsActivities(season.status)) {
      return const ErrorState(
        title: 'Vụ đã kết thúc',
        message: 'Vụ này đã kết thúc nên không ghi hay sửa công việc được nữa. '
            'Nhật ký của vụ vẫn xem được.',
      );
    }

    final text = Theme.of(context).textTheme;
    final warnings = _liveWarnings;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (!widget.online) ...[
          const OfflineBanner(
            message: 'Không có mạng — công việc vẫn được lưu trên điện thoại.',
          ),
          const SizedBox(height: AppSpacing.md),
        ],
        _DateTimeRow(
          value: _occurredAt,
          error: _occurredAtError,
          onPick: _pickDateTime,
        ),
        const SizedBox(height: AppSpacing.md),
        for (final spec in _specs) ...[
          _buildField(spec),
          const SizedBox(height: AppSpacing.md),
        ],
        AdaptiveFormField(
          label: 'Ghi chú thêm (không bắt buộc)',
          kind: AdaptiveFieldKind.multilineText,
          controller: _noteCtl,
        ),
        if (warnings.isNotEmpty) ...[
          const SizedBox(height: AppSpacing.md),
          for (final w in warnings)
            Padding(
              padding: const EdgeInsets.only(bottom: AppSpacing.xs),
              child: OfflineBanner(icon: Icons.info_outline, message: w),
            ),
        ],
        const SizedBox(height: AppSpacing.lg),
        PrimaryButton(
          label: _isEdit ? 'Lưu thay đổi' : 'Lưu công việc',
          loading: _saving,
          onPressed: _save,
        ),
        const SizedBox(height: AppSpacing.xs),
        Text(
          'Lưu ngay vào máy — gửi lên hệ thống là bước riêng.',
          style: text.labelSmall?.copyWith(color: AppColors.textSecondary),
          textAlign: TextAlign.center,
        ),
      ],
    );
  }

  Widget _buildField(ActivityFieldSpec spec) {
    final label =
        spec.unit == null ? spec.label : '${spec.label} (${spec.unit})';
    final error = _fieldErrors[spec.key];
    switch (spec.kind) {
      case ActivityFieldKind.select:
        return AdaptiveFormField(
          label: label,
          kind: AdaptiveFieldKind.select,
          required: spec.required,
          value: _select[spec.key],
          errorText: error,
          helperText: spec.hint,
          options: [
            for (final o in spec.options) AdaptiveFieldOption(o.value, o.label),
          ],
          onValueChanged: (v) => setState(() {
            _select[spec.key] = v;
            _fieldErrors.remove(spec.key);
          }),
        );
      case ActivityFieldKind.tristate:
        return AdaptiveFormField(
          label: label,
          kind: AdaptiveFieldKind.tristate,
          required: spec.required,
          value: _tristate[spec.key] == null
              ? null
              : (_tristate[spec.key]! ? 'true' : 'false'),
          errorText: error,
          hint: spec.hint,
          onValueChanged: (v) => setState(() {
            _tristate[spec.key] = v == null ? null : v == 'true';
            _fieldErrors.remove(spec.key);
          }),
        );
      case ActivityFieldKind.text:
        return AdaptiveFormField(
          label: label,
          kind: AdaptiveFieldKind.text,
          required: spec.required,
          controller: _text[spec.key],
          errorText: error,
          helperText: spec.hint,
        );
      case ActivityFieldKind.decimal:
        return AdaptiveFormField(
          label: label,
          kind: AdaptiveFieldKind.decimal,
          required: spec.required,
          controller: _text[spec.key],
          errorText: error,
          helperText: spec.hint,
        );
      case ActivityFieldKind.integer:
        return AdaptiveFormField(
          label: label,
          kind: AdaptiveFieldKind.integer,
          required: spec.required,
          controller: _text[spec.key],
          errorText: error,
          helperText: spec.hint,
        );
    }
  }
}

class _DateTimeRow extends StatelessWidget {
  const _DateTimeRow({
    required this.value,
    required this.onPick,
    this.error,
  });

  final DateTime value;
  final VoidCallback onPick;
  final String? error;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('Thời điểm làm việc', style: text.labelMedium),
        const SizedBox(height: AppSpacing.xxs),
        SecondaryButton(
          label: '${AppFormat.date(value)}  ·  ${AppFormat.time(value)}',
          icon: Icons.event_outlined,
          expanded: true,
          onPressed: onPick,
        ),
        if (error != null)
          Padding(
            padding: const EdgeInsets.only(top: AppSpacing.xxs),
            child: Text(error!,
                style: text.labelSmall?.copyWith(color: AppColors.error)),
          ),
      ],
    );
  }
}
