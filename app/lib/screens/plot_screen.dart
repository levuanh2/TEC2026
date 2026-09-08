import 'package:flutter/material.dart';
import 'package:uuid/uuid.dart';

import '../app_services.dart';
import '../models/farm.dart';
import '../models/plot.dart';
import 'crop_season_screen.dart';

const _uuid = Uuid();

class PlotScreen extends StatefulWidget {
  const PlotScreen({super.key, required this.services, required this.farm});
  final AppServices services;
  final Farm farm;

  @override
  State<PlotScreen> createState() => _PlotScreenState();
}

class _PlotScreenState extends State<PlotScreen> {
  List<Plot> _plots = [];

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final plots = await widget.services.db.listPlotsByFarm(widget.farm.id);
    if (mounted) setState(() => _plots = plots);
  }

  Future<void> _createPlot() async {
    final codeController = TextEditingController();
    final nameController = TextEditingController();
    final areaController = TextEditingController();

    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Thêm thửa ruộng'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(controller: codeController, decoration: const InputDecoration(labelText: 'Mã thửa')),
            TextField(controller: nameController, decoration: const InputDecoration(labelText: 'Tên thửa')),
            TextField(
              controller: areaController,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              decoration: const InputDecoration(labelText: 'Diện tích (ha)'),
            ),
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Huỷ')),
          ElevatedButton(onPressed: () => Navigator.pop(context, true), child: const Text('Lưu')),
        ],
      ),
    );
    if (ok != true) return;

    final area = double.tryParse(areaController.text.trim().replaceAll(',', '.'));
    if (codeController.text.trim().isEmpty || area == null || area <= 0) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Diện tích phải lớn hơn 0.')),
      );
      return;
    }

    final plot = Plot(
      id: _uuid.v4(), // id tạm - sync_service sẽ thay bằng id thật khi đồng bộ
      farmId: widget.farm.id,
      plotCode: codeController.text.trim(),
      name: nameController.text.trim().isEmpty ? codeController.text.trim() : nameController.text.trim(),
      areaHa: area,
    );
    // Lưu local ngay — hoạt động được cả khi mất mạng (NFR-01).
    await widget.services.db.upsertPlot(plot, pendingCreate: true);
    await _load();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text('Thửa ruộng — ${widget.farm.farmName}')),
      body: _plots.isEmpty
          ? const Center(child: Text('Chưa có thửa ruộng nào. Bấm + để thêm.'))
          : ListView.builder(
              itemCount: _plots.length,
              itemBuilder: (context, i) {
                final plot = _plots[i];
                return ListTile(
                  leading: const Icon(Icons.crop_square),
                  title: Text(plot.name),
                  subtitle: Text('${plot.plotCode} · ${plot.areaHa} ha'),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () => Navigator.of(context).push(
                    MaterialPageRoute(
                      builder: (_) => CropSeasonScreen(services: widget.services, plot: plot),
                    ),
                  ),
                );
              },
            ),
      floatingActionButton: FloatingActionButton(onPressed: _createPlot, child: const Icon(Icons.add)),
    );
  }
}
