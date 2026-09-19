import 'package:flutter/material.dart';
import 'package:uuid/uuid.dart';

import '../app_services.dart';
import '../design/design.dart';
import '../models/crop_season.dart';
import '../models/crop_season_validation.dart';
import '../models/methodology_enums.dart';
import '../models/plot.dart';
import '../models/sync_state.dart';

final _uuid = Uuid();

/// Tạo / sửa Vụ canh tác, gồm các biến phương pháp luận Carbon Engine cần.
/// KHÔNG tự đặt mặc định cho biến phương pháp luận khi nông dân chưa biết —
/// để trống, backend sẽ báo khi tính.
class CropSeasonFormScreen extends StatefulWidget {
  const CropSeasonFormScreen({
    super.key,
    required this.services,
    required this.plot,
    this.existing,
  });

  final AppServices services;
  final Plot plot;
  final CropSeason? existing;

  @override
  State<CropSeasonFormScreen> createState() => _CropSeasonFormScreenState();
}

class _CropSeasonFormScreenState extends State<CropSeasonFormScreen> {
  late final _codeCtl =
      TextEditingController(text: widget.existing?.seasonCode ?? '');
  late final _varietyCtl =
      TextEditingController(text: widget.existing?.varietyName ?? '');
  late final _cultivationDaysCtl = TextEditingController(
      text: widget.existing?.cultivationDays?.toString() ?? '');
  late final _drainageCtl = TextEditingController(
      text: widget.existing?.drainageEventCount?.toString() ?? '');

  DateTime? _planting;
  DateTime? _expectedHarvest;
  DateTime? _actualHarvest;
  DefaultIrrigationMethod? _irrigation;
  IpccWaterRegime? _ipccRegime;
  PreSeasonWaterRegime? _preSeason;

  String? _codeErr;
  String? _dateErr;
  String? _cultivationErr;
  String? _drainageErr;
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    final e = widget.existing;
    _planting = e?.plantingDate;
    _expectedHarvest = e?.expectedHarvestDate;
    _actualHarvest = e?.actualHarvestDate;
    _irrigation = e?.defaultIrrigationMethod;
    _ipccRegime = e?.ipccWaterRegime;
    _preSeason = e?.preSeasonWaterRegime;
  }

  @override
  void dispose() {
    _codeCtl.dispose();
    _varietyCtl.dispose();
    _cultivationDaysCtl.dispose();
    _drainageCtl.dispose();
    super.dispose();
  }

  int? get _cultivationDays => int.tryParse(_cultivationDaysCtl.text.trim());
  int? get _drainageCount => int.tryParse(_drainageCtl.text.trim());

  int? get _suggestedDays => suggestCultivationDays(
        planting: _planting,
        expectedHarvest: _expectedHarvest,
        actualHarvest: _actualHarvest,
      );

  String? get _awdWarning => awdDrainageWarning(
        isMultipleDrainageRegime:
            _ipccRegime == IpccWaterRegime.irrigatedMultipleDrainage,
        drainageEventCount: _drainageCount,
      );

  Future<void> _pickDate(
    DateTime? current,
    ValueChanged<DateTime?> onPicked,
  ) async {
    final picked = await showDatePicker(
      context: context,
      initialDate: current ?? DateTime.now(),
      firstDate: DateTime(2018),
      lastDate: DateTime(2100),
    );
    if (picked != null) {
      setState(() {
        onPicked(picked);
        _dateErr = null;
      });
    }
  }

  Future<void> _save() async {
    if (_saving) return;
    FocusScope.of(context).unfocus();

    final code = _codeCtl.text.trim();
    final days = _cultivationDays;
    final drainage = _drainageCount;
    final codeErr = seasonCodeError(code);
    final dateErr = harvestNotBeforePlantingError(
      planting: _planting,
      expectedHarvest: _expectedHarvest,
      actualHarvest: _actualHarvest,
    );
    final cultivationErr = cultivationDaysError(days);
    final drainageErr = drainageCountError(drainage);

    setState(() {
      _codeErr = codeErr;
      _dateErr = dateErr;
      _cultivationErr = cultivationErr;
      _drainageErr = drainageErr;
    });
    if ([codeErr, dateErr, cultivationErr, drainageErr].any((e) => e != null)) {
      return;
    }

    setState(() => _saving = true);
    final now = DateTime.now();
    final e = widget.existing;
    final season = CropSeason(
      clientId: e?.clientId ?? _uuid.v4(),
      serverId: e?.serverId,
      plotClientId: widget.plot.clientId,
      seasonCode: code,
      varietyName:
          _varietyCtl.text.trim().isEmpty ? null : _varietyCtl.text.trim(),
      plantingDate: _planting,
      expectedHarvestDate: _expectedHarvest,
      actualHarvestDate: _actualHarvest,
      defaultIrrigationMethod: _irrigation,
      ipccWaterRegime: _ipccRegime,
      preSeasonWaterRegime: _preSeason,
      cultivationDays: days,
      drainageEventCount: drainage,
      status: e?.status ?? CropSeasonStatus.planned,
      // Bản mới hoặc bản đã đồng bộ mà bị sửa → phải gửi lại.
      syncState: (e == null || e.isSynced) ? SyncState.pending : e.syncState,
      retryCount: e?.retryCount ?? 0,
      createdAt: e?.createdAt ?? now,
      updatedAt: now,
    );
    await widget.services.db.upsertCropSeason(season);
    if (e != null) await widget.services.db.markCarbonInputsChanged(season.clientId);
    if (!mounted) return;
    Navigator.of(context).pop(season);
  }

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final suggestion = _suggestedDays;

    return AppScaffold(
      header: AppHeader(
        title: widget.existing == null ? 'Thêm vụ canh tác' : 'Sửa vụ canh tác',
        subtitle: widget.plot.name,
        showBackButton: true,
      ),
      bottomBar: PrimaryButton(
        label: 'Lưu vụ canh tác',
        loading: _saving,
        onPressed: _save,
      ),
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          AdaptiveFormField(
            label: 'Mã vụ',
            kind: AdaptiveFieldKind.text,
            controller: _codeCtl,
            required: true,
            hint: 'ví dụ: ĐX 2025-2026',
            errorText: _codeErr,
          ),
          const SizedBox(height: AppSpacing.md),
          AdaptiveFormField(
            label: 'Giống lúa',
            kind: AdaptiveFieldKind.text,
            controller: _varietyCtl,
          ),
          const SizedBox(height: AppSpacing.lg),
          Text('Thời gian', style: text.titleMedium),
          const SizedBox(height: AppSpacing.xs),
          _DateRow(
            label: 'Ngày gieo sạ',
            value: _planting,
            onPick: () => _pickDate(_planting, (d) => _planting = d),
            onClear: _planting == null
                ? null
                : () => setState(() => _planting = null),
          ),
          _DateRow(
            label: 'Ngày thu hoạch dự kiến',
            value: _expectedHarvest,
            onPick: () =>
                _pickDate(_expectedHarvest, (d) => _expectedHarvest = d),
            onClear: _expectedHarvest == null
                ? null
                : () => setState(() => _expectedHarvest = null),
          ),
          _DateRow(
            label: 'Ngày thu hoạch thực tế',
            value: _actualHarvest,
            onPick: () => _pickDate(_actualHarvest, (d) => _actualHarvest = d),
            onClear: _actualHarvest == null
                ? null
                : () => setState(() => _actualHarvest = null),
          ),
          if (_dateErr != null) _fieldError(_dateErr!),
          const SizedBox(height: AppSpacing.lg),
          Text('Chế độ nước & phương pháp', style: text.titleMedium),
          const SizedBox(height: AppSpacing.xs),
          AdaptiveFormField(
            label: 'Cách tưới chính trong vụ',
            kind: AdaptiveFieldKind.select,
            value: _irrigation?.wire,
            options: [
              for (final m in DefaultIrrigationMethod.values)
                AdaptiveFieldOption(m.wire, m.labelVi),
            ],
            onValueChanged: (v) => setState(
                () => _irrigation = DefaultIrrigationMethod.fromWire(v)),
          ),
          const SizedBox(height: AppSpacing.md),
          AdaptiveFormField(
            label: 'Phân loại chế độ nước (IPCC)',
            kind: AdaptiveFieldKind.select,
            value: _ipccRegime?.wire,
            helperText:
                'Chọn đúng phân loại giúp tính phát thải sát thực tế hơn. '
                'Chưa chắc thì để trống.',
            options: [
              for (final r in IpccWaterRegime.values)
                AdaptiveFieldOption(r.wire, r.labelVi),
            ],
            onValueChanged: (v) =>
                setState(() => _ipccRegime = IpccWaterRegime.fromWire(v)),
          ),
          const SizedBox(height: AppSpacing.md),
          AdaptiveFormField(
            label: 'Số lần rút nước trong vụ',
            kind: AdaptiveFieldKind.integer,
            controller: _drainageCtl,
            errorText: _drainageErr,
            helperText: 'Chỉ áp dụng khi tưới rút nước nhiều lần / AWD.',
          ),
          if (_awdWarning != null) ...[
            const SizedBox(height: AppSpacing.xs),
            OfflineBanner(
              icon: Icons.info_outline,
              message: _awdWarning!,
            ),
          ],
          const SizedBox(height: AppSpacing.md),
          AdaptiveFormField(
            label: 'Chế độ nước của ruộng TRƯỚC khi gieo',
            kind: AdaptiveFieldKind.select,
            value: _preSeason?.wire,
            helperText:
                'Nước đọng trên ruộng thời gian dài trước vụ làm phát thải '
                'khí mê-tan tăng mạnh. Chọn tình huống gần đúng nhất.',
            options: [
              for (final r in PreSeasonWaterRegime.values)
                AdaptiveFieldOption(r.wire, r.labelVi),
            ],
            onValueChanged: (v) =>
                setState(() => _preSeason = PreSeasonWaterRegime.fromWire(v)),
          ),
          const SizedBox(height: AppSpacing.md),
          AdaptiveFormField(
            label: 'Số ngày canh tác (từ gieo tới thu hoạch)',
            kind: AdaptiveFieldKind.integer,
            controller: _cultivationDaysCtl,
            errorText: _cultivationErr,
          ),
          if (suggestion != null && _cultivationDays != suggestion) ...[
            const SizedBox(height: AppSpacing.xs),
            AppCard(
              variant: AppCardVariant.highlight,
              child: Row(
                children: [
                  Expanded(
                    child: Text(
                      'Từ ngày gieo và ngày thu hoạch, gợi ý khoảng '
                      '$suggestion ngày. Bạn xác nhận thì bấm "Dùng gợi ý".',
                      style: text.bodyMedium,
                    ),
                  ),
                  const SizedBox(width: AppSpacing.xs),
                  SecondaryButton(
                    label: 'Dùng gợi ý',
                    onPressed: () => setState(() {
                      _cultivationDaysCtl.text = suggestion.toString();
                      _cultivationErr = null;
                    }),
                  ),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _fieldError(String message) => Padding(
        padding: const EdgeInsets.only(top: AppSpacing.xxs),
        child: Text(
          message,
          style: Theme.of(context)
              .textTheme
              .labelSmall
              ?.copyWith(color: AppColors.error),
        ),
      );
}

class _DateRow extends StatelessWidget {
  const _DateRow({
    required this.label,
    required this.value,
    required this.onPick,
    this.onClear,
  });

  final String label;
  final DateTime? value;
  final VoidCallback onPick;
  final VoidCallback? onClear;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.xs),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(label, style: text.labelMedium),
                Text(
                  value == null ? 'Chưa chọn' : AppFormat.date(value),
                  style: text.bodyLarge,
                ),
              ],
            ),
          ),
          if (onClear != null)
            IconButton(
              icon: const Icon(Icons.close, size: 18),
              tooltip: 'Xoá ngày',
              onPressed: onClear,
            ),
          SecondaryButton(label: 'Chọn ngày', onPressed: onPick),
        ],
      ),
    );
  }
}
