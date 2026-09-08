import 'package:flutter/material.dart';

import '../app_services.dart';
import '../models/farm.dart';
import 'plot_screen.dart';

/// Farm hiếm khi tạo mới (một hộ thường chỉ có 1 farm, do quản lý HTX cấp
/// trước). Vì vậy tạo Farm là hành động ONLINE-only, không cần đưa vào hàng
/// đợi offline — khác với Plot/CropSeason/Activity ở các màn sau.
class FarmScreen extends StatefulWidget {
  const FarmScreen({super.key, required this.services});
  final AppServices services;

  @override
  State<FarmScreen> createState() => _FarmScreenState();
}

class _FarmScreenState extends State<FarmScreen> {
  List<Farm> _farms = [];
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      await widget.services.sync.pullFarmsPlotsSeasons();
    } catch (e) {
      // Offline/lỗi mạng: KHÔNG chặn màn hình — vẫn hiện cache local (offline-first).
      // Nhưng nếu cache cũng trống, phải nói rõ "chưa kiểm tra được" khác với
      // "chắc chắn chưa có hộ nào" — hai trạng thái khác nhau (Phase 17).
      _error = 'Không kết nối được máy chủ. Đang hiện dữ liệu đã lưu trên máy (nếu có).';
    }
    final farms = await widget.services.db.listFarms();
    if (!mounted) return;
    setState(() {
      _farms = farms;
      _loading = false;
    });
  }

  Future<void> _createFarm() async {
    final cooperativeId = await widget.services.sync.currentCooperativeId();
    if (cooperativeId == null) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Bạn chưa được thêm vào HTX nào. Liên hệ quản lý HTX để được cấp quyền.'),
        ),
      );
      return;
    }
    final codeController = TextEditingController();
    final nameController = TextEditingController();
    final result = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Tạo hộ / trang trại mới'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: codeController,
              decoration: const InputDecoration(labelText: 'Mã hộ'),
            ),
            TextField(
              controller: nameController,
              decoration: const InputDecoration(labelText: 'Tên hộ'),
            ),
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Huỷ')),
          ElevatedButton(onPressed: () => Navigator.pop(context, true), child: const Text('Tạo')),
        ],
      ),
    );
    if (result != true) return;
    if (codeController.text.trim().isEmpty || nameController.text.trim().isEmpty) return;

    try {
      await widget.services.auth.client.from('farms').insert({
        'cooperative_id': cooperativeId,
        'farm_code': codeController.text.trim(),
        'farm_name': nameController.text.trim(),
      });
      await _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Không tạo được hộ mới: $e')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Hộ / Trang trại của tôi'),
        actions: [
          IconButton(icon: const Icon(Icons.logout), onPressed: widget.services.auth.signOut),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _farms.isEmpty
              ? Center(
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      if (_error != null) ...[
                        Padding(
                          padding: const EdgeInsets.symmetric(horizontal: 24),
                          child: Text(_error!,
                              textAlign: TextAlign.center,
                              style: const TextStyle(color: Colors.orange)),
                        ),
                        const SizedBox(height: 12),
                      ],
                      const Text('Chưa có hộ/trang trại nào (trên máy này).'),
                      const SizedBox(height: 12),
                      ElevatedButton(onPressed: _createFarm, child: const Text('Tạo mới')),
                      TextButton(onPressed: _load, child: const Text('Thử tải lại')),
                    ],
                  ),
                )
              : ListView.builder(
                  itemCount: _farms.length,
                  itemBuilder: (context, i) {
                    final farm = _farms[i];
                    return ListTile(
                      leading: const Icon(Icons.agriculture),
                      title: Text(farm.farmName),
                      subtitle: Text(farm.farmCode),
                      trailing: const Icon(Icons.chevron_right),
                      onTap: () => Navigator.of(context).push(
                        MaterialPageRoute(
                          builder: (_) => PlotScreen(services: widget.services, farm: farm),
                        ),
                      ),
                    );
                  },
                ),
      floatingActionButton:
          _farms.isEmpty ? null : FloatingActionButton(onPressed: _createFarm, child: const Icon(Icons.add)),
    );
  }
}
