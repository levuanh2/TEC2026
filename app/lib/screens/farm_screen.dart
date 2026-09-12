import 'package:flutter/material.dart';

import '../app_services.dart';
import '../design/design.dart';
import '../models/farm.dart';
import '../services/sync_errors.dart';
import 'plot_screen.dart';

/// Danh sách Hộ / Trang trại. Farm lấy từ dữ liệu THẬT (kéo từ Supabase, RLS
/// lọc). Tạo Farm là **online-only** theo kiến trúc hiện tại — không giả vờ
/// offline khi chưa có cơ chế server hợp lệ.
class FarmScreen extends StatefulWidget {
  const FarmScreen({super.key, required this.services});
  final AppServices services;

  @override
  State<FarmScreen> createState() => _FarmScreenState();
}

class _FarmScreenState extends State<FarmScreen> {
  List<Farm> _farms = [];
  bool _loading = true;
  bool _offlineCache = false; // đang hiện cache vì không gọi được server

  AppServices get _s => widget.services;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _offlineCache = false;
    });
    try {
      await _s.sync.pullFarmsPlotsSeasons();
      await _s.activeContext.revalidate();
    } catch (_) {
      _offlineCache = true; // vẫn hiện cache local (offline-first)
    }
    final farms = await _s.db.listFarms();
    if (!mounted) return;
    setState(() {
      _farms = farms;
      _loading = false;
    });
  }

  Future<void> _openFarm(Farm farm) async {
    await _s.activeContext.setFarm(farm);
    if (!mounted) return;
    await Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => PlotScreen(services: _s, farm: farm),
      ),
    );
    await _load();
  }

  Future<void> _createFarm() async {
    // Tra HTX của người dùng — có thể ném (mất mạng / RLS). KHÔNG để lỗi thoát
    // ra khỏi callback của nút.
    final String? cooperativeId;
    try {
      cooperativeId = await _s.sync.currentCooperativeId();
    } catch (error) {
      if (!mounted) return;
      await _showCooperativeLookupFailed(classifySyncError(error));
      return;
    }
    if (!mounted) return;
    if (cooperativeId == null) {
      await _showNoCooperativeInfo();
      return;
    }

    final codeCtl = TextEditingController();
    final nameCtl = TextEditingController();
    String? codeErr;
    String? nameErr;

    final created = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (dialogContext, setLocal) {
          Future<void> submit() async {
            final code = codeCtl.text.trim();
            final name = nameCtl.text.trim();
            setLocal(() {
              codeErr = code.isEmpty ? 'Nhập mã hộ.' : null;
              nameErr = name.isEmpty ? 'Nhập tên hộ.' : null;
            });
            if (codeErr != null || nameErr != null) return;
            try {
              await _s.auth.client.from('farms').insert({
                'cooperative_id': cooperativeId,
                'farm_code': code,
                'farm_name': name,
              });
              if (dialogContext.mounted) Navigator.pop(dialogContext, true);
            } catch (error) {
              final kind = classifySyncError(error);
              setLocal(() {
                // Phân biệt "không có quyền" (RLS) với "mất mạng".
                if (kind == SyncErrorKind.rlsDenied) {
                  nameErr = 'Bạn không có quyền tạo hộ trong HTX này. '
                      'Liên hệ quản lý HTX.';
                } else if (kind == SyncErrorKind.network) {
                  nameErr = 'Không có mạng. Tạo hộ cần kết nối — thử lại khi '
                      'có mạng.';
                } else if (kind == SyncErrorKind.duplicate) {
                  codeErr = 'Mã hộ này đã tồn tại trong HTX.';
                } else {
                  nameErr = 'Chưa tạo được hộ. Thử lại sau.';
                }
              });
            }
          }

          return AlertDialog(
            title: const Text('Tạo hộ / trang trại mới'),
            content: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                TextField(
                  controller: codeCtl,
                  decoration: InputDecoration(
                    labelText: 'Mã hộ *',
                    errorText: codeErr,
                  ),
                ),
                const SizedBox(height: AppSpacing.xs),
                TextField(
                  controller: nameCtl,
                  decoration: InputDecoration(
                    labelText: 'Tên hộ *',
                    errorText: nameErr,
                  ),
                ),
              ],
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(dialogContext, false),
                child: const Text('Huỷ'),
              ),
              PrimaryButton(
                label: 'Tạo',
                expanded: false,
                onPressed: submit,
              ),
            ],
          );
        },
      ),
    );

    if (created == true) await _load();
  }

  Future<void> _showCooperativeLookupFailed(SyncErrorKind kind) {
    final message = kind == SyncErrorKind.network
        ? 'Không có mạng nên chưa kiểm tra được hợp tác xã của bạn. Kết nối '
            'mạng rồi thử lại.'
        : 'Chưa kiểm tra được thông tin hợp tác xã của bạn. Thử lại sau ít '
            'phút, hoặc liên hệ quản lý HTX nếu vẫn không được.';
    return showDialog<void>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Chưa tạo được hộ'),
        content: Text(message),
        actions: [
          PrimaryButton(
            label: 'Đã hiểu',
            expanded: false,
            onPressed: () => Navigator.pop(context),
          ),
        ],
      ),
    );
  }

  Future<void> _showNoCooperativeInfo() {
    return showDialog<void>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Chưa thuộc HTX nào'),
        content: const Text(
          'Tài khoản của bạn chưa được thêm vào hợp tác xã nào nên chưa tạo '
          'được hộ/trang trại. Vui lòng liên hệ quản lý HTX để được thêm vào, '
          'sau đó mở lại màn hình này.',
        ),
        actions: [
          PrimaryButton(
            label: 'Đã hiểu',
            expanded: false,
            onPressed: () => Navigator.pop(context),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return AppScaffold(
      header: const AppHeader(
        title: 'Hộ / Trang trại của tôi',
        showBackButton: true,
      ),
      scrollable: false,
      padded: false,
      floatingActionButton: (_loading || _farms.isEmpty)
          ? null
          : FloatingActionButton(
              onPressed: _createFarm,
              tooltip: 'Tạo hộ mới',
              child: const Icon(Icons.add),
            ),
      body: _loading
          ? const LoadingState(message: 'Đang tải danh sách hộ...')
          : _farms.isEmpty
              ? EmptyState(
                  icon: Icons.agriculture_outlined,
                  title: _offlineCache
                      ? 'Chưa tải được danh sách hộ'
                      : 'Chưa có hộ / trang trại nào',
                  message: _offlineCache
                      ? 'Không kết nối được máy chủ và trên máy chưa có dữ liệu '
                          'đã lưu. Kiểm tra mạng rồi thử lại.'
                      : 'Tạo hộ mới (cần có mạng), hoặc nhờ quản lý HTX thêm hộ '
                          'cho bạn.',
                  actionLabel: _offlineCache ? 'Thử lại' : 'Tạo hộ mới',
                  onAction: _offlineCache ? _load : _createFarm,
                )
              : RefreshIndicator(
                  onRefresh: _load,
                  child: ListView.separated(
                    padding: const EdgeInsets.all(AppSpacing.screenH),
                    itemCount: _farms.length + (_offlineCache ? 1 : 0),
                    separatorBuilder: (_, __) =>
                        const SizedBox(height: AppSpacing.sm),
                    itemBuilder: (context, i) {
                      if (_offlineCache && i == 0) {
                        return const OfflineBanner(
                          message:
                              'Đang hiện dữ liệu đã lưu trên máy — chưa kết nối '
                              'được máy chủ.',
                        );
                      }
                      final farm = _farms[i - (_offlineCache ? 1 : 0)];
                      return AppCard(
                        onTap: () => _openFarm(farm),
                        child: Row(
                          children: [
                            const Icon(Icons.agriculture_outlined,
                                color: AppColors.primary),
                            const SizedBox(width: AppSpacing.sm),
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(farm.farmName,
                                      style: Theme.of(context)
                                          .textTheme
                                          .titleSmall),
                                  const SizedBox(height: 2),
                                  Text(
                                    [farm.farmCode, farm.locationLabel]
                                        .where((s) => s.isNotEmpty)
                                        .join(' · '),
                                    style: Theme.of(context)
                                        .textTheme
                                        .labelSmall
                                        ?.copyWith(
                                            color: AppColors.textSecondary),
                                  ),
                                ],
                              ),
                            ),
                            const Icon(Icons.chevron_right,
                                color: AppColors.textSecondary),
                          ],
                        ),
                      );
                    },
                  ),
                ),
    );
  }
}
