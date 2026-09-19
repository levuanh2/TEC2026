import 'package:flutter/material.dart';

import '../design/design.dart';
import '../models/activity_field_spec.dart';
import '../models/carbon_readiness.dart';

/// Khối "Cần bổ sung / Đã đủ dữ liệu" của màn Carbon — cùng hành vi khối sửa
/// nhanh của Farmer Web. Widget CHỈ hiển thị: mọi mục thiếu, câu chữ và chỗ sửa
/// (`flow`) đều lấy từ máy chủ ([CarbonReadiness]); không có luật phương pháp
/// luận nào ở đây.
class CarbonReadinessSection extends StatelessWidget {
  const CarbonReadinessSection({
    super.key,
    required this.readiness,
    required this.canWrite,
    required this.online,
    required this.hasResult,
    required this.hasPendingChanges,
    required this.isRecordOnDevice,
    this.busy = false,
    this.onFixSeason,
    this.onFixActivity,
    this.onCalculate,
    this.onSyncNow,
  });

  final CarbonReadiness readiness;

  /// Người dùng được ghi vào farm của vụ (owner/editor). `false` → chỉ xem:
  /// không nút sửa, không nút tính.
  final bool canWrite;
  final bool online;

  /// Đã có một kết quả được lưu → nút là "Tính lại Carbon".
  final bool hasResult;

  /// Còn thay đổi trên máy chưa gửi: readiness phía dưới CHƯA tính tới chúng,
  /// và không được tính Carbon trên dữ liệu cũ.
  final bool hasPendingChanges;

  /// `activity_id` (server) có bản ghi tương ứng trên máy này không.
  final bool Function(String activityServerId) isRecordOnDevice;
  final bool busy;
  final void Function(MissingCarbonInput issue)? onFixSeason;
  final void Function(MissingCarbonInput issue, ReadinessRecord record)? onFixActivity;
  final VoidCallback? onCalculate;
  final VoidCallback? onSyncNow;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final blocking = readiness.blocking;
    final children = <Widget>[];

    if (hasPendingChanges) {
      children.add(_Note(
        key: const Key('carbon-pending-changes'),
        icon: Icons.sync_problem_outlined,
        tone: AppColors.warningText,
        text: 'Còn thay đổi trên máy chưa gửi lên. Danh sách dưới đây chưa tính '
            'các thay đổi đó; gửi dữ liệu rồi mới tính phát thải.',
        actionLabel: online && onSyncNow != null ? 'Gửi ngay' : null,
        onAction: onSyncNow,
      ));
      children.add(const SizedBox(height: AppSpacing.sm));
    }

    if (!canWrite) {
      children.add(const _Note(
        key: Key('carbon-read-only'),
        icon: Icons.visibility_outlined,
        tone: AppColors.textSecondary,
        text: 'Bạn chỉ có quyền xem vụ này — xem được dữ liệu còn thiếu và kết '
            'quả, nhưng không sửa hay tính phát thải.',
      ));
      children.add(const SizedBox(height: AppSpacing.sm));
    }

    if (blocking.isEmpty) {
      children.add(_ReadyCard(
        canWrite: canWrite,
        online: online,
        hasResult: hasResult,
        hasPendingChanges: hasPendingChanges,
        busy: busy,
        onCalculate: onCalculate,
      ));
    } else {
      children.add(Text(
        'Cần bổ sung ${blocking.length} thông tin để tính phát thải',
        key: const Key('carbon-missing-title'),
        style: text.titleSmall,
      ));
      children.add(const SizedBox(height: AppSpacing.xs));
      for (final issue in blocking) {
        children.add(_IssueCard(
          issue: issue,
          canWrite: canWrite,
          isRecordOnDevice: isRecordOnDevice,
          onFixSeason: onFixSeason,
          onFixActivity: onFixActivity,
        ));
        children.add(const SizedBox(height: AppSpacing.xs));
      }
    }

    // Không chặn tính, chỉ làm mất chỉ số trên mỗi kg (vd. chưa có sản lượng).
    for (final issue in readiness.nonBlocking) {
      children.add(const SizedBox(height: AppSpacing.xs));
      children.add(_IssueCard(
        issue: issue,
        canWrite: canWrite,
        isRecordOnDevice: isRecordOnDevice,
        onFixSeason: onFixSeason,
        onFixActivity: onFixActivity,
      ));
    }

    children.add(const SizedBox(height: AppSpacing.xs));
    children.add(Text(
      'Chi phí không phải đầu vào của phát thải — chi phí chỉ dùng cho chỉ số '
      'Chi phí/kg.',
      style: text.labelSmall?.copyWith(color: AppColors.textSecondary),
    ));

    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: children);
  }
}

class _ReadyCard extends StatelessWidget {
  const _ReadyCard({
    required this.canWrite,
    required this.online,
    required this.hasResult,
    required this.hasPendingChanges,
    required this.busy,
    required this.onCalculate,
  });
  final bool canWrite;
  final bool online;
  final bool hasResult;
  final bool hasPendingChanges;
  final bool busy;
  final VoidCallback? onCalculate;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final String? blockedReason = !canWrite
        ? null
        : !online
            ? 'Cần kết nối mạng để tính phát thải.'
            : hasPendingChanges
                ? 'Gửi các thay đổi còn trên máy trước khi tính.'
                : null;
    return AppCard(
      key: const Key('carbon-ready'),
      variant: AppCardVariant.highlight,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(children: [
            const Icon(Icons.check_circle_outline, color: AppColors.primary),
            const SizedBox(width: AppSpacing.xs),
            Expanded(
              child: Text('Đã đủ dữ liệu để tính phát thải.', style: text.titleSmall),
            ),
          ]),
          if (canWrite) ...[
            const SizedBox(height: AppSpacing.sm),
            if (blockedReason != null)
              Text(blockedReason,
                  key: const Key('carbon-calc-blocked'),
                  style: text.bodySmall?.copyWith(color: AppColors.warningText))
            else
              PrimaryButton(
                key: const Key('carbon-calculate'),
                label: hasResult ? 'Tính lại Carbon' : 'Tính Carbon',
                loading: busy,
                onPressed: onCalculate,
              ),
          ],
        ],
      ),
    );
  }
}

class _IssueCard extends StatelessWidget {
  const _IssueCard({
    required this.issue,
    required this.canWrite,
    required this.isRecordOnDevice,
    required this.onFixSeason,
    required this.onFixActivity,
  });
  final MissingCarbonInput issue;
  final bool canWrite;
  final bool Function(String) isRecordOnDevice;
  final void Function(MissingCarbonInput)? onFixSeason;
  final void Function(MissingCarbonInput, ReadinessRecord)? onFixActivity;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final limitation = issue.flow == ReadinessFlow.factorUnavailable;
    final body = <Widget>[
      Text(
        limitation ? 'Giới hạn của hệ thống' : issue.blocking ? 'Cần bổ sung' : 'Nên bổ sung',
        style: text.labelSmall?.copyWith(
            color: limitation ? AppColors.warningText : AppColors.textSecondary),
      ),
      const SizedBox(height: AppSpacing.xxs),
      Text(issue.label, style: text.titleSmall),
      if (issue.detail.isNotEmpty) ...[
        const SizedBox(height: AppSpacing.xxs),
        Text(issue.detail, style: text.bodySmall),
      ],
    ];

    switch (issue.flow) {
      case ReadinessFlow.factorUnavailable:
        // Không có ô nào để nhập: không hiện "Sửa ngay" giả.
        body.add(const SizedBox(height: AppSpacing.xs));
        body.add(Text(
          'Tính phát thải của vụ đang bị chặn vì mục này. Nhập thêm chi tiết '
          'cũng không giải quyết được — hệ thống không bỏ qua nó để ra số.',
          key: const Key('carbon-limitation-note'),
          style: text.bodySmall?.copyWith(color: AppColors.warningText),
        ));
      case ReadinessFlow.seasonMethodology:
        if (canWrite && onFixSeason != null) {
          body.add(const SizedBox(height: AppSpacing.xs));
          body.add(Align(
            alignment: Alignment.centerLeft,
            child: SecondaryButton(
              key: Key('fix-season-${issue.code}'),
              label: 'Sửa ngay',
              icon: Icons.edit_outlined,
              onPressed: () => onFixSeason!(issue),
            ),
          ));
        }
      case ReadinessFlow.activity:
        for (final record in issue.records) {
          body.add(const SizedBox(height: AppSpacing.xs));
          body.add(_RecordRow(
            issue: issue,
            record: record,
            canWrite: canWrite,
            onDevice: isRecordOnDevice(record.activityId),
            onFix: onFixActivity,
          ));
        }
      case ReadinessFlow.plot:
        body.add(const SizedBox(height: AppSpacing.xs));
        body.add(Text(
          canWrite
              ? 'Nhập diện tích ở mục Ruộng → chọn thửa của vụ này.'
              : 'Người có quyền quản lý thửa cần nhập diện tích.',
          style: text.bodySmall?.copyWith(color: AppColors.textSecondary),
        ));
      case ReadinessFlow.unknown:
        break;
    }

    return AppCard(
      key: Key('carbon-issue-${issue.code}'),
      variant: limitation ? AppCardVariant.warning : AppCardVariant.plain,
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: body),
    );
  }
}

class _RecordRow extends StatelessWidget {
  const _RecordRow({
    required this.issue,
    required this.record,
    required this.canWrite,
    required this.onDevice,
    required this.onFix,
  });
  final MissingCarbonInput issue;
  final ReadinessRecord record;
  final bool canWrite;
  final bool onDevice;
  final void Function(MissingCarbonInput, ReadinessRecord)? onFix;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final type = kActivityTypeLabels[issue.activityType] ?? issue.activityType ?? '';
    final what = [
      type,
      if (record.label != null && record.label!.isNotEmpty) record.label!,
      if (record.occurredOn != null) AppFormat.date(DateTime.tryParse(record.occurredOn!)),
    ].where((s) => s.isNotEmpty).join(' · ');
    return Row(
      children: [
        Expanded(child: Text(what, style: text.bodySmall)),
        if (canWrite && onDevice && onFix != null)
          TextButton(
            key: Key('fix-activity-${record.activityId}-${issue.code}'),
            onPressed: () => onFix!(issue, record),
            child: const Text('Sửa ngay'),
          )
        else if (canWrite && !onDevice)
          Flexible(
            child: Text(
              'Bản ghi không có trên máy này — sửa trên Farmer Web.',
              key: Key('record-not-on-device-${record.activityId}'),
              textAlign: TextAlign.end,
              style: text.labelSmall?.copyWith(color: AppColors.textSecondary),
            ),
          ),
      ],
    );
  }
}

class _Note extends StatelessWidget {
  const _Note({
    super.key,
    required this.icon,
    required this.tone,
    required this.text,
    this.actionLabel,
    this.onAction,
  });
  final IconData icon;
  final Color tone;
  final String text;
  final String? actionLabel;
  final VoidCallback? onAction;

  @override
  Widget build(BuildContext context) {
    return AppCard(
      variant: AppCardVariant.warning,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 20, color: tone),
          const SizedBox(width: AppSpacing.xs),
          Expanded(
            child: Text(text,
                style: Theme.of(context).textTheme.bodySmall?.copyWith(color: tone)),
          ),
          if (actionLabel != null)
            TextButton(onPressed: onAction, child: Text(actionLabel!)),
        ],
      ),
    );
  }
}
