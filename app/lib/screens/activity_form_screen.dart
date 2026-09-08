import 'package:flutter/material.dart';
import 'package:uuid/uuid.dart';

import '../app_services.dart';
import '../models/activity.dart';
import '../models/activity_field_spec.dart';

final _uuid = Uuid();

/// Form động theo `kActivityFieldSpecs` — 1 file thay vì 7 file gần giống
/// nhau cho từng loại hoạt động (§11–15).
///
/// Lưu THẲNG vào SQLite khi bấm "Lưu" — KHÔNG gọi mạng ở đây (NFR-01: nhập
/// liệu không bao giờ phụ thuộc kết nối). Đồng bộ là hành động riêng, người
/// dùng tự bấm ở màn hình trước (hoặc để dành lúc có mạng).
class ActivityFormScreen extends StatefulWidget {
  const ActivityFormScreen({
    super.key,
    required this.services,
    required this.cropSeasonId,
    required this.activityType,
  });

  final AppServices services;
  final String cropSeasonId;
  final String activityType;

  @override
  State<ActivityFormScreen> createState() => _ActivityFormScreenState();
}

class _ActivityFormScreenState extends State<ActivityFormScreen> {
  final _controllers = <String, TextEditingController>{};
  final _selectValues = <String, String?>{};
  final _boolValues = <String, bool>{}; // FieldKind.boolean — mặc định false, không nhạy methodology
  final _nullableBoolValues = <String, bool?>{}; // FieldKind.nullableBoolean — null = CHƯA CHỌN, không gửi lên
  final _noteController = TextEditingController();
  DateTime _occurredAt = DateTime.now();

  List<ActivityFieldSpec> get _specs => kActivityFieldSpecs[widget.activityType] ?? [];

  @override
  void initState() {
    super.initState();
    for (final spec in _specs) {
      if (spec.kind == FieldKind.boolean) {
        _boolValues[spec.key] = false;
      } else if (spec.kind == FieldKind.nullableBoolean) {
        _nullableBoolValues[spec.key] = null; // CHƯA CHỌN — không tự default
      } else {
        _controllers[spec.key] = TextEditingController();
      }
    }
  }

  @override
  void dispose() {
    for (final c in _controllers.values) {
      c.dispose();
    }
    _noteController.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    // Validate required fields — thông báo tiếng Việt, không jargon.
    for (final spec in _specs) {
      if (!spec.required) continue;
      final ok = spec.kind == FieldKind.select
          ? _selectValues[spec.key] != null
          : (_controllers[spec.key]?.text.trim().isNotEmpty ?? false);
      if (!ok) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Vui lòng nhập "${spec.label}".')),
        );
        return;
      }
    }

    final payload = <String, dynamic>{};
    for (final spec in _specs) {
      switch (spec.kind) {
        case FieldKind.select:
          final v = _selectValues[spec.key];
          if (v != null) payload[spec.key] = v;
          break;
        case FieldKind.boolean:
          payload[spec.key] = _boolValues[spec.key] ?? false;
          break;
        case FieldKind.nullableBoolean:
          // Chưa chọn -> KHÔNG đưa key vào payload. Gửi "false" thay cho "chưa
          // biết" chính là default một methodology input — cấm (xem
          // activity_field_spec.dart). Backend tự báo MethodologyGapError khi
          // thiếu, đúng như thiết kế.
          final v = _nullableBoolValues[spec.key];
          if (v != null) payload[spec.key] = v;
          break;
        case FieldKind.number:
          final raw = _controllers[spec.key]?.text.trim() ?? '';
          if (raw.isNotEmpty) payload[spec.key] = double.tryParse(raw.replaceAll(',', '.'));
          break;
        case FieldKind.integer:
          final raw = _controllers[spec.key]?.text.trim() ?? '';
          if (raw.isNotEmpty) payload[spec.key] = int.tryParse(raw);
          break;
        case FieldKind.text:
          final raw = _controllers[spec.key]?.text.trim() ?? '';
          if (raw.isNotEmpty) payload[spec.key] = raw;
          break;
      }
    }

    final activity = Activity(
      clientEventId: _uuid.v4(),
      cropSeasonId: widget.cropSeasonId,
      type: widget.activityType,
      occurredAt: _occurredAt,
      payload: payload,
      note: _noteController.text.trim().isEmpty ? null : _noteController.text.trim(),
      createdAt: DateTime.now(),
    );

    await widget.services.db.insertActivity(activity);
    if (!mounted) return;
    Navigator.of(context).pop();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(kActivityTypeLabels[widget.activityType] ?? widget.activityType)),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          OutlinedButton(
            onPressed: () async {
              final picked = await showDatePicker(
                context: context,
                initialDate: _occurredAt,
                firstDate: DateTime(2020),
                lastDate: DateTime.now(),
              );
              if (picked != null) setState(() => _occurredAt = picked);
            },
            child: Text('Ngày: ${_occurredAt.day}/${_occurredAt.month}/${_occurredAt.year}'),
          ),
          const SizedBox(height: 12),
          ..._specs.map(_buildField),
          const SizedBox(height: 12),
          TextField(
            controller: _noteController,
            maxLines: 2,
            decoration: const InputDecoration(labelText: 'Ghi chú thêm (nếu có)', border: OutlineInputBorder()),
          ),
          const SizedBox(height: 24),
          SizedBox(
            width: double.infinity,
            height: 52,
            child: ElevatedButton(onPressed: _save, child: const Text('Lưu', style: TextStyle(fontSize: 18))),
          ),
        ],
      ),
    );
  }

  Widget _buildField(ActivityFieldSpec spec) {
    Widget field;
    switch (spec.kind) {
      case FieldKind.select:
        field = DropdownButtonFormField<String>(
          value: _selectValues[spec.key],
          decoration: InputDecoration(labelText: spec.label, border: const OutlineInputBorder()),
          items: spec.options
              .map((o) => DropdownMenuItem(value: o.value, child: Text(o.label)))
              .toList(),
          onChanged: (v) => setState(() => _selectValues[spec.key] = v),
        );
        break;
      case FieldKind.boolean:
        field = SwitchListTile(
          title: Text(spec.label),
          value: _boolValues[spec.key] ?? false,
          onChanged: (v) => setState(() => _boolValues[spec.key] = v),
        );
        break;
      case FieldKind.nullableBoolean:
        final current = _nullableBoolValues[spec.key];
        field = Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(spec.label),
            const SizedBox(height: 4),
            Wrap(
              spacing: 8,
              children: [
                ChoiceChip(
                  label: const Text('Chưa rõ'),
                  selected: current == null,
                  onSelected: (_) => setState(() => _nullableBoolValues[spec.key] = null),
                ),
                ChoiceChip(
                  label: const Text('Có'),
                  selected: current == true,
                  onSelected: (_) => setState(() => _nullableBoolValues[spec.key] = true),
                ),
                ChoiceChip(
                  label: const Text('Không'),
                  selected: current == false,
                  onSelected: (_) => setState(() => _nullableBoolValues[spec.key] = false),
                ),
              ],
            ),
          ],
        );
        break;
      case FieldKind.number:
      case FieldKind.integer:
        field = TextField(
          controller: _controllers[spec.key],
          keyboardType: TextInputType.numberWithOptions(decimal: spec.kind == FieldKind.number),
          decoration: InputDecoration(
            labelText: spec.required ? '${spec.label} *' : spec.label,
            border: const OutlineInputBorder(),
          ),
        );
        break;
      case FieldKind.text:
        field = TextField(
          controller: _controllers[spec.key],
          decoration: InputDecoration(
            labelText: spec.required ? '${spec.label} *' : spec.label,
            border: const OutlineInputBorder(),
          ),
        );
        break;
    }
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          field,
          if (spec.hint != null)
            Padding(
              padding: const EdgeInsets.only(top: 4, left: 4),
              child: Text(spec.hint!, style: TextStyle(fontSize: 12, color: Colors.grey.shade600)),
            ),
        ],
      ),
    );
  }
}
