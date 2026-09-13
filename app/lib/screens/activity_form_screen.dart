import 'package:flutter/material.dart';

import '../app_services.dart';
import '../design/design.dart';
import '../models/activity.dart';
import '../models/activity_field_spec.dart';
import 'activity_form.dart';

/// Màn ghi/sửa 1 hoạt động — bọc [ActivityForm] trong [AppScaffold]. Dùng khi
/// push chồng (sửa từ chi tiết, hoặc ghi nhanh sâu từ Trang chủ). Ghi nhanh
/// trong tab dùng trực tiếp [ActivityForm].
class ActivityFormScreen extends StatelessWidget {
  const ActivityFormScreen({
    super.key,
    required this.services,
    required this.cropSeasonId,
    required this.activityType,
    this.existing,
  });

  final AppServices services;

  /// `crop_seasons.client_id` (ổn định).
  final String cropSeasonId;
  final String activityType;
  final Activity? existing;

  @override
  Widget build(BuildContext context) {
    final label = kActivityTypeLabels[activityType] ?? activityType;
    return AppScaffold(
      header: AppHeader(
        title: existing == null ? 'Ghi: $label' : 'Sửa: $label',
        showBackButton: true,
      ),
      body: ActivityForm(
        db: services.db,
        cropSeasonClientId: cropSeasonId,
        activityType: activityType,
        existing: existing,
        online: services.connectivity.isOnline,
        onSaved: () async {
          if (context.mounted) Navigator.of(context).pop(true);
        },
      ),
    );
  }
}
