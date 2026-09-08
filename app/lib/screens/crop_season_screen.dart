import 'package:flutter/material.dart';
import 'package:uuid/uuid.dart';

import '../app_services.dart';
import '../models/crop_season.dart';
import '../models/plot.dart';
import 'crop_season_detail_screen.dart';

const _uuid = Uuid();

class CropSeasonScreen extends StatefulWidget {
  const CropSeasonScreen({super.key, required this.services, required this.plot});
  final AppServices services;
  final Plot plot;

  @override
  State<CropSeasonScreen> createState() => _CropSeasonScreenState();
}

class _CropSeasonScreenState extends State<CropSeasonScreen> {
  List<CropSeason> _seasons = [];

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final seasons = await widget.services.db.listCropSeasonsByPlot(widget.plot.id);
    if (mounted) setState(() => _seasons = seasons);
  }

  Future<void> _createSeason() async {
    final codeController = TextEditingController();
    final varietyController = TextEditingController();
    DateTime? plantingDate;

    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          title: const Text('Thêm vụ canh tác'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: codeController,
                decoration: const InputDecoration(labelText: 'Mã vụ (vd: DX-2026)'),
              ),
              TextField(
                controller: varietyController,
                decoration: const InputDecoration(labelText: 'Giống lúa'),
              ),
              const SizedBox(height: 8),
              OutlinedButton(
                onPressed: () async {
                  final picked = await showDatePicker(
                    context: context,
                    initialDate: DateTime.now(),
                    firstDate: DateTime(2020),
                    lastDate: DateTime(2100),
                  );
                  if (picked != null) setDialogState(() => plantingDate = picked);
                },
                child: Text(
                  plantingDate == null
                      ? 'Chọn ngày gieo sạ'
                      : 'Gieo sạ: ${plantingDate!.day}/${plantingDate!.month}/${plantingDate!.year}',
                ),
              ),
            ],
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Huỷ')),
            ElevatedButton(onPressed: () => Navigator.pop(context, true), child: const Text('Lưu')),
          ],
        ),
      ),
    );
    if (ok != true || codeController.text.trim().isEmpty) return;

    final season = CropSeason(
      id: _uuid.v4(),
      plotId: widget.plot.id,
      seasonCode: codeController.text.trim(),
      varietyName: varietyController.text.trim().isEmpty ? null : varietyController.text.trim(),
      plantingDate: plantingDate,
    );
    await widget.services.db.upsertCropSeason(season, pendingCreate: true);
    await _load();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text('Vụ canh tác — ${widget.plot.name}')),
      body: _seasons.isEmpty
          ? const Center(child: Text('Chưa có vụ canh tác nào. Bấm + để thêm.'))
          : ListView.builder(
              itemCount: _seasons.length,
              itemBuilder: (context, i) {
                final season = _seasons[i];
                return ListTile(
                  leading: const Icon(Icons.grass),
                  title: Text(season.seasonCode),
                  subtitle: Text(season.varietyName ?? 'Chưa ghi giống'),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () => Navigator.of(context).push(
                    MaterialPageRoute(
                      builder: (_) =>
                          CropSeasonDetailScreen(services: widget.services, season: season),
                    ),
                  ),
                );
              },
            ),
      floatingActionButton: FloatingActionButton(onPressed: _createSeason, child: const Icon(Icons.add)),
    );
  }
}
