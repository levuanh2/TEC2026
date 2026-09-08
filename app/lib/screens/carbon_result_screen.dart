import 'package:flutter/material.dart';

import '../app_services.dart';
import '../models/carbon_result.dart';
import '../services/carbon_api_service.dart';

/// Không tính CO2e trong app — chỉ gửi request tới backend và hiển thị đúng
/// những gì backend trả (docs/BACKEND_1A.md §8, §20 của task này).
class CarbonResultScreen extends StatefulWidget {
  const CarbonResultScreen({super.key, required this.services, required this.cropSeasonId});
  final AppServices services;
  final String cropSeasonId;

  @override
  State<CarbonResultScreen> createState() => _CarbonResultScreenState();
}

class _CarbonResultScreenState extends State<CarbonResultScreen> {
  String _scenario = kScenarioAsRecorded;
  CarbonResult? _result;
  bool _loading = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _loadLatest();
  }

  Future<void> _loadLatest() async {
    setState(() => _loading = true);
    try {
      final result = await widget.services.carbonApi.latest(
        cropSeasonId: widget.cropSeasonId,
        scenario: _scenario,
      );
      setState(() => _result = result);
    } catch (e) {
      // Chưa từng tính -> không phải lỗi hiển thị, chỉ để trống, mời bấm Tính.
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _calculate() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final result = await widget.services.carbonApi.calculate(
        cropSeasonId: widget.cropSeasonId,
        scenario: _scenario,
      );
      setState(() => _result = result);
    } catch (e) {
      setState(() => _error = CarbonApiService.friendlyMessage(e));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Carbon (CO2e)')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          const Text('Kịch bản:', style: TextStyle(fontWeight: FontWeight.bold)),
          RadioListTile<String>(
            title: const Text('Theo ghi nhận thực tế'),
            value: kScenarioAsRecorded,
            groupValue: _scenario,
            onChanged: (v) => setState(() => _scenario = v!),
          ),
          RadioListTile<String>(
            title: const Text('AWD (ngập-khô xen kẽ)'),
            value: kScenarioAwd,
            groupValue: _scenario,
            onChanged: (v) => setState(() => _scenario = v!),
          ),
          RadioListTile<String>(
            title: const Text('Tưới ngập liên tục'),
            value: kScenarioContinuousFlooding,
            groupValue: _scenario,
            onChanged: (v) => setState(() => _scenario = v!),
          ),
          const SizedBox(height: 12),
          SizedBox(
            width: double.infinity,
            height: 52,
            child: ElevatedButton(
              onPressed: _loading ? null : _calculate,
              child: _loading
                  ? const CircularProgressIndicator()
                  : const Text('Tính CO2e', style: TextStyle(fontSize: 16)),
            ),
          ),
          if (_error != null)
            Padding(
              padding: const EdgeInsets.only(top: 12),
              child: Text(_error!, style: const TextStyle(color: Colors.red)),
            ),
          const SizedBox(height: 20),
          if (_result != null) _buildResult(_result!),
        ],
      ),
    );
  }

  Widget _buildResult(CarbonResult r) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('CO2e tổng: ${r.totalCo2eKg?.toStringAsFixed(1) ?? "—"} kg',
                style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
            const SizedBox(height: 4),
            // KHÔNG BAO GIỜ hiện "0" khi chưa có sản lượng — §20.
            r.co2ePerKg == null
                ? const Text(
                    'Chưa tính được CO2e/kg. Vui lòng bổ sung sản lượng thu hoạch.',
                    style: TextStyle(color: Colors.orange, fontWeight: FontWeight.bold),
                  )
                : Text('CO2e/kg: ${r.co2ePerKg!.toStringAsFixed(3)} kg CO2e/kg lúa',
                    style: const TextStyle(fontSize: 16)),
            const Divider(height: 24),
            const Text('Phân rã theo nguồn:', style: TextStyle(fontWeight: FontWeight.bold)),
            ...r.breakdown.map((b) => Padding(
                  padding: const EdgeInsets.only(top: 4),
                  child: Text('• ${_sourceLabel(b.source)} (${b.gas.toUpperCase()}): '
                      '${b.coeKg.toStringAsFixed(1)} kg CO2e'),
                )),
            if (r.warnings.isNotEmpty) ...[
              const Divider(height: 24),
              const Text('Lưu ý:', style: TextStyle(fontWeight: FontWeight.bold, color: Colors.orange)),
              ...r.warnings.map((w) => Padding(
                    padding: const EdgeInsets.only(top: 4),
                    child: Text('• $w', style: const TextStyle(fontSize: 13)),
                  )),
            ],
            const Divider(height: 24),
            Text('Phương pháp luận: ${r.methodologyName}', style: const TextStyle(fontSize: 12, color: Colors.grey)),
            Text('Bộ hệ số: ${r.efConfigVersion}', style: const TextStyle(fontSize: 12, color: Colors.grey)),
            Text('Tính lúc: ${r.calculatedAt}', style: const TextStyle(fontSize: 12, color: Colors.grey)),
          ],
        ),
      ),
    );
  }

  String _sourceLabel(String source) {
    const labels = {
      'ch4_rice_cultivation': 'Ruộng ngập (CH4)',
      'n2o_fertilizer_direct': 'Phân bón (N2O)',
      'straw_burning': 'Đốt rơm rạ',
      'fuel_diesel': 'Nhiên liệu diesel',
    };
    return labels[source] ?? source;
  }
}
