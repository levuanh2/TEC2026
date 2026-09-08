import 'package:flutter/material.dart';

import '../app_services.dart';
import '../models/activity.dart';
import '../models/activity_field_spec.dart';
import '../models/crop_season.dart';
import 'activity_form_screen.dart';
import 'carbon_result_screen.dart';

class CropSeasonDetailScreen extends StatefulWidget {
  const CropSeasonDetailScreen({super.key, required this.services, required this.season});
  final AppServices services;
  final CropSeason season;

  @override
  State<CropSeasonDetailScreen> createState() => _CropSeasonDetailScreenState();
}

class _CropSeasonDetailScreenState extends State<CropSeasonDetailScreen> {
  List<Activity> _activities = [];
  int _pendingCount = 0;
  bool _syncing = false;
  String? _syncMessage;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final activities = await widget.services.db.listActivitiesByCropSeason(widget.season.id);
    final pending = await widget.services.db.countPendingActivities();
    if (!mounted) return;
    setState(() {
      _activities = activities;
      _pendingCount = pending;
    });
  }

  Future<void> _sync() async {
    setState(() {
      _syncing = true;
      _syncMessage = null;
    });
    // Đồng bộ có thể mất vài giây — người dùng hoàn toàn có thể bấm Back trước
    // khi xong. Mọi setState SAU await đều phải kiểm `mounted` trước, không chỉ
    // ở finally — gọi setState trên State đã dispose là crash thật (không phải
    // lỗi lý thuyết), xem app/README.md phần audit.
    String? message;
    try {
      final summary = await widget.services.sync.syncAll();
      message = summary.hasErrors
          ? 'Đồng bộ xong nhưng còn ${summary.errors.length} lỗi — sẽ thử lại lần sau.'
          : 'Đồng bộ xong: ${summary.activitiesSynced} hoạt động, '
              '${summary.plotsSynced} thửa, ${summary.cropSeasonsSynced} vụ.';
    } catch (e) {
      message = 'Không có mạng hoặc lỗi kết nối — thử lại sau.';
    }
    if (!mounted) return;
    setState(() {
      _syncMessage = message;
      _syncing = false;
    });
    await _load();
  }

  Future<void> _openActivityForm(String type) async {
    await Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => ActivityFormScreen(
          services: widget.services,
          cropSeasonId: widget.season.id,
          activityType: type,
        ),
      ),
    );
    await _load();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(widget.season.seasonCode)),
      body: ListView(
        padding: const EdgeInsets.all(12),
        children: [
          Card(
            color: Colors.green.shade50,
            child: ListTile(
              leading: const Icon(Icons.cloud_sync),
              title: Text(_pendingCount == 0
                  ? 'Đã đồng bộ hết'
                  : 'Còn $_pendingCount hoạt động chưa đồng bộ'),
              subtitle: _syncMessage == null ? null : Text(_syncMessage!),
              trailing: _syncing
                  ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator())
                  : IconButton(icon: const Icon(Icons.sync), onPressed: _sync),
            ),
          ),
          const SizedBox(height: 12),
          const Text('Ghi nhật ký hoạt động', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
          const SizedBox(height: 8),
          GridView.count(
            crossAxisCount: 2,
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            mainAxisSpacing: 8,
            crossAxisSpacing: 8,
            childAspectRatio: 2.2,
            children: kActivityTypes
                .map((type) => ElevatedButton(
                      onPressed: () => _openActivityForm(type),
                      child: Text(
                        kActivityTypeLabels[type] ?? type,
                        style: const TextStyle(fontSize: 15),
                      ),
                    ))
                .toList(),
          ),
          const SizedBox(height: 16),
          SizedBox(
            width: double.infinity,
            height: 52,
            child: ElevatedButton.icon(
              icon: const Icon(Icons.eco),
              label: const Text('Xem CO2e', style: TextStyle(fontSize: 16)),
              onPressed: () => Navigator.of(context).push(
                MaterialPageRoute(
                  builder: (_) => CarbonResultScreen(
                    services: widget.services,
                    cropSeasonId: widget.season.id,
                  ),
                ),
              ),
            ),
          ),
          const SizedBox(height: 16),
          const Text('Đã ghi nhận', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
          if (_activities.isEmpty) const Padding(padding: EdgeInsets.all(8), child: Text('Chưa có hoạt động nào.')),
          ..._activities.map((a) => ListTile(
                leading: _syncIcon(a.syncState),
                title: Text(kActivityTypeLabels[a.type] ?? a.type),
                subtitle: Text('${a.occurredAt.day}/${a.occurredAt.month}/${a.occurredAt.year}'
                    '${a.syncError != null ? " — lỗi: ${a.syncError}" : ""}'),
              )),
        ],
      ),
    );
  }

  Widget _syncIcon(SyncState state) {
    switch (state) {
      case SyncState.synced:
        return const Icon(Icons.check_circle, color: Colors.green);
      case SyncState.syncing:
        return const Icon(Icons.sync, color: Colors.blue);
      case SyncState.failed:
        return const Icon(Icons.error, color: Colors.red);
      case SyncState.pending:
        return const Icon(Icons.schedule, color: Colors.grey);
    }
  }
}
