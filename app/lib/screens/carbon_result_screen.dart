import 'package:flutter/material.dart';

import '../db/local_database.dart';
import '../design/design.dart';
import '../models/activity.dart';
import '../models/carbon_readiness.dart';
import '../models/carbon_result.dart';
import '../models/crop_season.dart';
import '../services/carbon_api_service.dart';
import '../services/carbon_cache.dart';
import '../services/connectivity_service.dart';
import 'carbon_readiness_section.dart';
import 'season_methodology_sheet.dart';

/// Màn 25 — "Kết quả phát thải" của một vụ.
///
/// KHÔNG tính carbon trong app. KHÔNG gọi API bằng local UUID (dùng
/// `crop_seasons.server_id`). Tiền điều kiện: có phiên đăng nhập, vụ đã đồng bộ,
/// KHÔNG còn Activity `pending`/`failed` của vụ — nếu không, hiện CTA sang "Gửi
/// dữ liệu". Số liệu THẬT từ backend; `co2e_per_kg == null` → dòng chữ, KHÔNG
/// hiện "0". Cache theo user + cropSeason + scenario; offline đọc cache; refresh
/// lỗi KHÔNG xoá cache.
class CarbonResultScreen extends StatefulWidget {
  const CarbonResultScreen({
    super.key,
    required this.carbonApi,
    required this.cache,
    required this.db,
    required this.cropSeasonClientId,
    this.onOpenSync,
    this.connectivity,
    this.syncNow,
    this.loadWritableFarmIds,
    this.editActivity,
  });

  final CarbonApiService carbonApi;
  final CarbonCache cache;
  final LocalDatabase db;
  final String cropSeasonClientId;
  final VoidCallback? onOpenSync;

  /// `null` → coi như có mạng (test / môi trường không có plugin).
  final ConnectivityService? connectivity;

  /// Chạy một lượt đồng bộ sẵn có (SyncCoordinator.runSync). Không có hệ thống
  /// đồng bộ riêng cho màn này.
  final Future<void> Function()? syncNow;

  /// Farm (server id) được ghi — `null` khi chưa biết (offline): khi đó KHÔNG
  /// ẩn nút sửa (sửa trên máy luôn an toàn, RLS chặn lúc gửi nếu không có quyền).
  final Future<Set<String>?> Function()? loadWritableFarmIds;

  /// Mở form sửa đúng hoạt động (mục readiness "Sửa ngay").
  final Future<void> Function(Activity activity)? editActivity;

  @override
  State<CarbonResultScreen> createState() => _CarbonResultScreenState();
}

enum _Phase {
  loading,
  noSeason, // không tìm thấy vụ trong DB
  notSynced, // vụ chưa có server_id
  content, // đã đủ điều kiện — hiện kết quả / empty / lỗi
}

const _kScenarioLabels = <String, String>{
  kScenarioAsRecorded: 'Theo ghi nhận thực tế',
  kScenarioAwd: 'Ngập – khô xen kẽ (AWD)',
  kScenarioContinuousFlooding: 'Tưới ngập liên tục',
};

class _CarbonResultScreenState extends State<CarbonResultScreen> {
  _Phase _phase = _Phase.loading;

  String? _plotLabel;
  String? _seasonLabel;
  String? _seasonServerId;
  int _unsyncedCount = 0;

  List<String> _scenarios = kOfficialScenarios;
  String _scenario = kScenarioAsRecorded;
  CarbonHealth? _health;

  CarbonResult? _result;
  String? _softError; // lỗi khi đang hiện cache (không chặn)
  bool _sessionExpired = false;
  bool _fatal = false; // lỗi không có cache để hiện
  String? _fatalMessage;
  bool _busy = false; // đang gọi calculate / tải lại
  bool _showDetails = false;

  // So sánh kịch bản.
  CarbonResult? _awdResult;
  CarbonResult? _continuousResult;

  // Readiness — nguồn sự thật là máy chủ.
  CropSeason? _season;
  String? _plotFarmId;
  bool _seasonPending = false;
  Map<String, Activity> _localByServerId = const {};
  CarbonReadiness? _readiness;
  String? _readinessError;
  bool _readinessLoading = false;
  Set<String>? _writableFarmIds;
  DateTime? _inputsChangedAt;

  bool get _online => widget.connectivity?.isOnline ?? true;
  bool get _canWrite {
    final ids = _writableFarmIds;
    final farm = _plotFarmId;
    if (ids == null || farm == null) return true;
    return ids.contains(farm);
  }

  bool get _hasPendingChanges => _seasonPending || _unsyncedCount > 0;

  /// Kết quả đang xem được tính TRƯỚC lần người dùng sửa đầu vào gần nhất.
  bool get _resultIsStale {
    final r = _result;
    final changed = _inputsChangedAt;
    if (r == null || changed == null) return false;
    final calculated = DateTime.tryParse(r.calculatedAt);
    return calculated != null && changed.isAfter(calculated);
  }

  @override
  void initState() {
    super.initState();
    _init();
  }

  Future<void> _init() async {
    final season =
        await widget.db.getCropSeasonByClientId(widget.cropSeasonClientId);
    if (!mounted) return;
    if (season == null) {
      setState(() => _phase = _Phase.noSeason);
      return;
    }
    await _readLocal();
    if (!mounted) return;

    if (_seasonServerId == null) {
      setState(() => _phase = _Phase.notSynced);
      return;
    }

    setState(() => _phase = _Phase.content);
    await Future.wait([_loadContent(), _loadReadiness(), _loadWriteAccess()]);
  }

  /// Trạng thái trên máy: vụ, thửa, hoạt động (theo server id), thay đổi chưa gửi.
  Future<void> _readLocal() async {
    final season =
        await widget.db.getCropSeasonByClientId(widget.cropSeasonClientId);
    if (season == null) return;
    final plot = await widget.db.getPlotByClientId(season.plotClientId);
    final activities = await widget.db
        .listActivitiesByCropSeasonClientId(widget.cropSeasonClientId);
    final changedAt =
        await widget.db.carbonInputsChangedAt(widget.cropSeasonClientId);
    final pendingDeletes = (await widget.db.listActivitiesByCropSeasonClientId(
            widget.cropSeasonClientId,
            includeDeleted: true))
        .where((a) => a.deletedLocally && a.syncState != SyncState.synced)
        .length;
    if (!mounted) return;
    setState(() {
      _season = season;
      _plotLabel = plot?.plotCode ?? plot?.name;
      _plotFarmId = plot?.farmId;
      _seasonLabel = season.seasonCode;
      _seasonServerId = season.serverId;
      _seasonPending = season.syncState != SyncState.synced;
      _inputsChangedAt = changedAt;
      _unsyncedCount = activities
              .where((a) =>
                  a.syncState == SyncState.pending ||
                  a.syncState == SyncState.failed)
              .length +
          pendingDeletes;
      _localByServerId = {
        for (final a in activities)
          if (a.serverActivityId != null) a.serverActivityId!: a,
      };
    });
  }

  Future<void> _loadWriteAccess() async {
    final load = widget.loadWritableFarmIds;
    if (load == null) return;
    try {
      final ids = await load();
      if (mounted) setState(() => _writableFarmIds = ids);
    } catch (_) {
      // Không biết quyền (offline): giữ null — không ẩn nút sửa trên máy.
    }
  }

  Future<void> _loadReadiness() async {
    final sid = _seasonServerId;
    if (sid == null) return;
    if (!_online) {
      setState(() {
        _readiness = null;
        _readinessError =
            'Cần kết nối mạng để kiểm tra dữ liệu còn thiếu và tính phát thải.';
      });
      return;
    }
    setState(() => _readinessLoading = true);
    try {
      final r = await widget.carbonApi.readiness(cropSeasonId: sid);
      if (!mounted) return;
      setState(() {
        _readiness = r;
        _readinessError = null;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _readinessError = CarbonApiService.friendlyMessage(e));
    } finally {
      if (mounted) setState(() => _readinessLoading = false);
    }
  }

  /// Sau một lần sửa trên máy: đọc lại trạng thái, gửi bằng lượt đồng bộ sẵn có
  /// nếu có mạng, rồi hỏi lại máy chủ. Offline → giá trị nằm trên máy, chờ gửi.
  Future<void> _afterLocalChange() async {
    await widget.db.markCarbonInputsChanged(widget.cropSeasonClientId);
    await _readLocal();
    if (_online && widget.syncNow != null) {
      try {
        await widget.syncNow!();
      } catch (_) {
        // Lỗi đồng bộ đã hiện ở màn Gửi dữ liệu; ở đây chỉ đọc lại trạng thái.
      }
      await _readLocal();
    }
    await _loadReadiness();
  }

  Future<void> _syncNow() async {
    if (widget.syncNow == null) return;
    try {
      await widget.syncNow!();
    } catch (_) {}
    await _readLocal();
    await _loadReadiness();
  }

  Future<void> _fixSeason(MissingCarbonInput issue) async {
    final season = _season;
    if (season == null) return;
    final values = await showSeasonMethodologySheet(context,
        season: season, focusCode: issue.code);
    if (values == null) return;
    await widget.db.upsertCropSeason(season.copyWith(
      ipccWaterRegime: values.ipccWaterRegime,
      preSeasonWaterRegime: values.preSeasonWaterRegime,
      cultivationDays: values.cultivationDays,
      syncState: SyncState.pending,
      updatedAt: DateTime.now(),
      clearSyncError: true,
    ));
    await _afterLocalChange();
  }

  Future<void> _fixActivity(MissingCarbonInput issue, ReadinessRecord record) async {
    final activity = _localByServerId[record.activityId];
    final edit = widget.editActivity;
    if (activity == null || edit == null) return;
    await edit(activity);
    // Form tự đánh dấu thay đổi khi lưu; huỷ thì không có gì để gửi.
    await _readLocal();
    if (_online && widget.syncNow != null && _unsyncedCount > 0) {
      try {
        await widget.syncNow!();
      } catch (_) {}
      await _readLocal();
    }
    await _loadReadiness();
  }

  Future<void> _loadContent() async {
    final sid = _seasonServerId!;
    // Danh sách kịch bản + health (song song, không chặn nhau, lỗi tự fallback).
    final results = await Future.wait([
      widget.carbonApi.scenarios(),
      widget.carbonApi.health(),
    ]);
    if (!mounted) return;
    setState(() {
      _scenarios = (results[0] as List<String>);
      if (!_scenarios.contains(_scenario)) _scenario = _scenarios.first;
      _health = results[1] as CarbonHealth?;
    });

    await _fetchScenario(sid, _scenario, primary: true);
    await _refreshComparison(sid);
  }

  /// Lấy kết quả cho 1 scenario. `primary` = scenario đang xem (cập nhật
  /// `_result` + trạng thái lỗi). Ngược lại chỉ nạp cho phần so sánh.
  Future<void> _fetchScenario(
    String sid,
    String scenario, {
    required bool primary,
  }) async {
    final cached = await widget.cache.read(sid, scenario);
    if (primary && cached != null && _result == null) {
      // Hiện cache ngay để không trắng màn trong lúc gọi mạng.
      setState(() => _result = cached);
    }
    try {
      final live = await widget.carbonApi.latest(
        cropSeasonId: sid,
        scenario: scenario,
      );
      if (!mounted) return;
      if (live != null) {
        await widget.cache.write(sid, scenario, live);
      }
      if (primary) {
        setState(() {
          _result = live ?? _result; // null = no_calculation (empty state)
          if (live == null && cached == null) _result = null;
          _softError = null;
          _sessionExpired = false;
          _fatal = false;
        });
      }
      _assignComparison(scenario, live ?? cached);
    } on CarbonApiException catch (e) {
      if (!mounted) return;
      _assignComparison(scenario, cached);
      if (!primary) return;
      if (e.isUnauthorized) {
        setState(() {
          _sessionExpired = true;
          if (cached != null) {
            _result = cached;
            _softError = null;
          } else {
            _fatal = true;
            _fatalMessage = CarbonApiService.friendlyMessage(e);
          }
        });
        return;
      }
      setState(() {
        if (cached != null) {
          _result = cached;
          _softError = CarbonApiService.friendlyMessage(e);
        } else {
          _fatal = true;
          _fatalMessage = CarbonApiService.friendlyMessage(e);
        }
      });
    } catch (e) {
      if (!mounted) return;
      _assignComparison(scenario, cached);
      if (!primary) return;
      setState(() {
        if (cached != null || _result != null) {
          _result ??= cached;
          _softError = CarbonApiService.friendlyMessage(e);
        } else {
          _fatal = true;
          _fatalMessage = CarbonApiService.friendlyMessage(e);
        }
      });
    }
  }

  void _assignComparison(String scenario, CarbonResult? r) {
    if (scenario == kScenarioAwd) _awdResult = r;
    if (scenario == kScenarioContinuousFlooding) _continuousResult = r;
  }

  Future<void> _refreshComparison(String sid) async {
    // Chỉ nạp cho scenario chưa có (scenario đang xem đã nạp ở _fetchScenario).
    for (final s in [kScenarioAwd, kScenarioContinuousFlooding]) {
      if (s == _scenario) continue;
      await _fetchScenario(sid, s, primary: false);
    }
    if (mounted) setState(() {});
  }

  Future<void> _onScenarioChanged(String? value) async {
    if (value == null || value == _scenario || _busy) return;
    setState(() {
      _scenario = value;
      _result = null;
      _softError = null;
    });
    await _fetchScenario(_seasonServerId!, value, primary: true);
    if (mounted) setState(() {});
  }

  Future<void> _calculate() async {
    if (_busy) return;
    if (!_online) {
      setState(() => _softError = 'Cần kết nối mạng để tính phát thải.');
      return;
    }
    setState(() => _busy = true);
    try {
      final live = await widget.carbonApi.calculate(
        cropSeasonId: _seasonServerId!,
        scenario: _scenario,
      );
      if (!mounted) return;
      await widget.cache.write(_seasonServerId!, _scenario, live);
      setState(() {
        _result = live;
        _softError = null;
        _sessionExpired = false;
        _fatal = false;
      });
      _assignComparison(_scenario, live);
      await _refreshComparison(_seasonServerId!);
    } on CarbonApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _sessionExpired = e.isUnauthorized;
        // KHÔNG xoá _result / cache cũ khi tính lại lỗi.
        if (_result == null) {
          _fatal = true;
          _fatalMessage = CarbonApiService.friendlyMessage(e);
        } else {
          _softError = CarbonApiService.friendlyMessage(e);
        }
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        if (_result == null) {
          _fatal = true;
          _fatalMessage = CarbonApiService.friendlyMessage(e);
        } else {
          _softError = CarbonApiService.friendlyMessage(e);
        }
      });
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return AppScaffold(
      header: const AppHeader(
        title: 'AgriCarbon',
        subtitle: 'Kết quả phát thải',
        showBackButton: true,
      ),
      // Nội dung dạng `ListView` tự cuộn (states loading/error/blocked là
      // `Center` — không cần cuộn) → tắt cuộn của AppScaffold để tránh lồng
      // viewport không giới hạn chiều cao.
      scrollable: false,
      padded: false,
      body: _body(),
    );
  }

  Widget _body() {
    switch (_phase) {
      case _Phase.loading:
        return const LoadingState(message: 'Đang kiểm tra dữ liệu vụ...');
      case _Phase.noSeason:
        return const ErrorState(
          title: 'Không tìm thấy vụ canh tác',
          message: 'Chọn lại vụ ở màn trước rồi thử lại.',
        );
      case _Phase.notSynced:
        return _BlockedCta(
          icon: Icons.cloud_off_outlined,
          title: 'Vụ chưa đồng bộ lên hệ thống',
          message: 'Chưa tính được phát thải khi vụ chỉ mới lưu trên máy. '
              'Gửi dữ liệu lên rồi quay lại đây.',
          onOpenSync: widget.onOpenSync,
        );
      case _Phase.content:
        return _content();
    }
  }

  Widget _content() {
    final text = Theme.of(context).textTheme;
    if (_fatal) {
      return ErrorState(
        title: _sessionExpired
            ? 'Phiên đăng nhập có vấn đề'
            : 'Chưa lấy được kết quả',
        message: _fatalMessage ?? 'Vui lòng thử lại.',
        onRetry: () {
          setState(() {
            _fatal = false;
            _result = null;
          });
          _loadContent();
        },
      );
    }

    final r = _result;
    return ListView(
      padding: const EdgeInsets.fromLTRB(
        AppSpacing.screenH,
        AppSpacing.md,
        AppSpacing.screenH,
        AppSpacing.xl,
      ),
      children: [
        if (_plotLabel != null || _seasonLabel != null)
          Text(
            'Ruộng ${_plotLabel ?? '—'} · Vụ ${_seasonLabel ?? '—'}',
            style: text.titleSmall,
          ),
        const SizedBox(height: AppSpacing.sm),
        _ScenarioPicker(
          value: _scenario,
          options: _scenarios,
          onChanged: _busy ? null : _onScenarioChanged,
        ),
        if (_health != null && !_health!.carbonProductionReady) ...[
          const SizedBox(height: AppSpacing.sm),
          const _NotReadyBanner(),
        ],
        if (_sessionExpired) ...[
          const SizedBox(height: AppSpacing.sm),
          _SoftBanner(
            icon: Icons.lock_outline,
            text:
                'Phiên đăng nhập đã hết hạn — số dưới đây là bản đã lưu. Đăng '
                'nhập lại để cập nhật.',
            tone: AppColors.error,
          ),
        ],
        if (_softError != null) ...[
          const SizedBox(height: AppSpacing.sm),
          _SoftBanner(
            icon: Icons.sync_problem_outlined,
            text: '$_softError\nĐang xem số đã lưu trên máy.',
            tone: AppColors.warningText,
          ),
        ],
        const SizedBox(height: AppSpacing.md),
        _readinessBlock(),
        const SizedBox(height: AppSpacing.md),
        if (_resultIsStale) ...[
          const _SoftBanner(
            key: Key('carbon-stale'),
            icon: Icons.update,
            text: 'Dữ liệu đã thay đổi sau lần tính gần nhất — cần tính lại. '
                'Số dưới đây là kết quả cũ.',
            tone: AppColors.warningText,
          ),
          const SizedBox(height: AppSpacing.sm),
        ],
        if (r == null)
          const _EmptyResult()
        else ...[
          if (r.fromCache && _softError == null && !_sessionExpired) ...[
            _CacheStamp(result: r),
            const SizedBox(height: AppSpacing.sm),
          ],
          _HeroCard(result: r),
          const SizedBox(height: AppSpacing.sm),
          _TotalsCard(result: r),
          const SizedBox(height: AppSpacing.sm),
          _BreakdownCard(result: r),
          _ComparisonCard(awd: _awdResult, continuous: _continuousResult),
          if (r.warnings.isNotEmpty) ...[
            const SizedBox(height: AppSpacing.sm),
            _WarningsCard(warnings: r.warnings),
          ],
          const SizedBox(height: AppSpacing.sm),
          _MethodologyCard(result: r, health: _health),
          const SizedBox(height: AppSpacing.sm),
          SecondaryButton(
            label: _showDetails ? 'Ẩn chi tiết' : 'Xem chi tiết',
            expanded: true,
            icon: _showDetails ? Icons.expand_less : Icons.expand_more,
            onPressed: () => setState(() => _showDetails = !_showDetails),
          ),
          if (_showDetails) ...[
            const SizedBox(height: AppSpacing.sm),
            _DetailsCard(result: r),
          ],
        ],
        const SizedBox(height: AppSpacing.xs),
        Text(
          'Kết quả do hệ thống tính, ứng dụng không tự tính.',
          textAlign: TextAlign.center,
          style: text.labelSmall?.copyWith(color: AppColors.textSecondary),
        ),
      ],
    );
  }
}

extension on _CarbonResultScreenState {
  Widget _readinessBlock() {
    final readiness = _readiness;
    if (readiness == null) {
      if (_readinessLoading) {
        return const LoadingState(message: 'Đang kiểm tra dữ liệu còn thiếu...');
      }
      return _SoftBanner(
        key: const Key('carbon-readiness-unavailable'),
        icon: _online ? Icons.error_outline : Icons.cloud_off_outlined,
        text: _readinessError ??
            'Chưa kiểm tra được dữ liệu còn thiếu. Kéo xuống hoặc mở lại để thử.',
        tone: AppColors.warningText,
      );
    }
    return CarbonReadinessSection(
      readiness: readiness,
      canWrite: _canWrite,
      online: _online,
      hasResult: _result != null,
      hasPendingChanges: _hasPendingChanges,
      isRecordOnDevice: _localByServerId.containsKey,
      busy: _busy,
      onFixSeason: _fixSeason,
      onFixActivity: widget.editActivity == null ? null : _fixActivity,
      onCalculate: _calculate,
      onSyncNow: widget.syncNow == null ? null : _syncNow,
    );
  }
}

// ---------------------------------------------------------------------------

class _BlockedCta extends StatelessWidget {
  const _BlockedCta({
    required this.icon,
    required this.title,
    required this.message,
    required this.onOpenSync,
  });
  final IconData icon;
  final String title;
  final String message;
  final VoidCallback? onOpenSync;

  @override
  Widget build(BuildContext context) {
    return EmptyState(
      icon: icon,
      title: title,
      message: message,
      actionLabel: onOpenSync == null ? null : 'Đi tới Gửi dữ liệu',
      onAction: onOpenSync,
    );
  }
}

class _NotReadyBanner extends StatelessWidget {
  const _NotReadyBanner();
  @override
  Widget build(BuildContext context) {
    return const OfflineBanner(
      icon: Icons.science_outlined,
      message:
          'Hệ thống chưa sẵn sàng tính phát thải CHÍNH THỨC (bộ hệ số / GWP '
          'chưa được xác minh). Số dưới đây chỉ để tham khảo, CHƯA phải kết quả '
          'MRV.',
    );
  }
}

class _SoftBanner extends StatelessWidget {
  const _SoftBanner({
    super.key,
    required this.icon,
    required this.text,
    required this.tone,
  });
  final IconData icon;
  final String text;
  final Color tone;

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
                style: Theme.of(context)
                    .textTheme
                    .bodySmall
                    ?.copyWith(color: tone)),
          ),
        ],
      ),
    );
  }
}

class _CacheStamp extends StatelessWidget {
  const _CacheStamp({required this.result});
  final CarbonResult result;
  @override
  Widget build(BuildContext context) {
    final calc = DateTime.tryParse(result.calculatedAt);
    return Text(
      'Số đã lưu trên máy'
      '${calc != null ? ' · hệ thống tính lúc ${AppFormat.dateTime(calc)}' : ''}'
      '${result.fetchedAt != null ? ' · lấy về ${AppFormat.dateTime(result.fetchedAt)}' : ''}',
      style: Theme.of(context)
          .textTheme
          .labelSmall
          ?.copyWith(color: AppColors.textSecondary),
    );
  }
}

class _ScenarioPicker extends StatelessWidget {
  const _ScenarioPicker({
    required this.value,
    required this.options,
    required this.onChanged,
  });
  final String value;
  final List<String> options;
  final ValueChanged<String?>? onChanged;

  @override
  Widget build(BuildContext context) {
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Kịch bản nước', style: Theme.of(context).textTheme.labelSmall),
          RadioGroup<String>(
            groupValue: value,
            onChanged: onChanged ?? (_) {},
            child: Column(
              children: [
                for (final o in options)
                  RadioListTile<String>(
                    contentPadding: EdgeInsets.zero,
                    title: Text(_kScenarioLabels[o] ?? o),
                    value: o,
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _EmptyResult extends StatelessWidget {
  const _EmptyResult();
  @override
  Widget build(BuildContext context) {
    return const EmptyState(
      icon: Icons.calculate_outlined,
      title: 'Vụ này chưa được tính phát thải',
      message: 'Khi đã đủ dữ liệu, bấm "Tính Carbon" ở trên — hệ thống tính '
          'theo nhật ký canh tác đã gửi lên.',
    );
  }
}

class _HeroCard extends StatelessWidget {
  const _HeroCard({required this.result});
  final CarbonResult result;
  @override
  Widget build(BuildContext context) {
    final perKg = result.co2ePerKg;
    return MetricCard(
      hero: true,
      label: 'Khí thải trên mỗi kg lúa',
      value: perKg == null ? null : AppFormat.number(perKg, fractionDigits: 3),
      unit: perKg == null ? null : 'kg CO₂e / kg lúa',
      // MISSING YIELD: null → dòng chữ, TUYỆT ĐỐI không "0".
      missingLabel: 'Chưa có sản lượng nên chưa tính được CO₂e/kg',
    );
  }
}

class _TotalsCard extends StatelessWidget {
  const _TotalsCard({required this.result});
  final CarbonResult result;
  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    Widget row(String label, String value) => Padding(
          padding: const EdgeInsets.symmetric(vertical: 3),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Flexible(
                child: Text(label,
                    style: text.bodyMedium
                        ?.copyWith(color: AppColors.textSecondary)),
              ),
              const SizedBox(width: AppSpacing.sm),
              Text(value, style: text.titleSmall),
            ],
          ),
        );
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          row(
              'Tổng khí thải của vụ',
              AppFormat.withUnit(result.totalCo2eKg, 'kg CO₂e',
                  fractionDigits: 1)),
          row('Sản lượng thu hoạch',
              AppFormat.withUnit(result.yieldKg, 'kg', fractionDigits: 0)),
        ],
      ),
    );
  }
}

const _kSourceLabels = <String, String>{
  'ch4_rice_cultivation': 'Ruộng ngập (CH₄)',
  'n2o_fertilizer_direct': 'Phân bón — trực tiếp (N₂O)',
  'n2o_fertilizer_indirect': 'Phân bón — gián tiếp (N₂O)',
  'ch4_straw_incorporation': 'Vùi rơm rạ (CH₄)',
  'straw_burning': 'Đốt rơm rạ',
  'fuel_diesel': 'Dầu diesel bơm tưới',
  'fuel_combustion': 'Nhiên liệu',
};

class _BreakdownCard extends StatelessWidget {
  const _BreakdownCard({required this.result});
  final CarbonResult result;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final r = result;
    if (r.breakdown.isEmpty) {
      return AppCard(
        child: Text('Chưa có phân rã theo nguồn.',
            style: text.bodyMedium?.copyWith(color: AppColors.textSecondary)),
      );
    }
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Khí thải đến từ đâu?', style: text.titleSmall),
          const SizedBox(height: AppSpacing.xs),
          for (final e in r.breakdown) _row(context, e),
          if (r.breakdownMismatch) ...[
            const SizedBox(height: AppSpacing.xs),
            Text(
              'Tổng các nguồn (${AppFormat.number(r.breakdownSum, fractionDigits: 1)} kg) '
              'lệch tổng chung — hiển thị đúng số máy chủ trả về, không tự chỉnh.',
              style: text.labelSmall?.copyWith(color: AppColors.warningText),
            ),
          ],
        ],
      ),
    );
  }

  Widget _row(BuildContext context, CarbonBreakdownEntry e) {
    final text = Theme.of(context).textTheme;
    final share = result.shareOf(e); // null khi total<=0
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(_kSourceLabels[e.source] ?? e.source,
                    style: text.bodyMedium),
                Text(
                  // giữ mã nguồn THẬT để đối chiếu.
                  '${e.source} · ${e.gas.toUpperCase()}',
                  style:
                      text.labelSmall?.copyWith(color: AppColors.textSecondary),
                ),
              ],
            ),
          ),
          const SizedBox(width: AppSpacing.sm),
          Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Text(
                AppFormat.withUnit(e.co2eKg, 'kg', fractionDigits: 1),
                style: text.titleSmall,
              ),
              if (share != null)
                Text(AppFormat.percent(share),
                    style: text.labelSmall
                        ?.copyWith(color: AppColors.textSecondary)),
            ],
          ),
        ],
      ),
    );
  }
}

class _ComparisonCard extends StatelessWidget {
  const _ComparisonCard({required this.awd, required this.continuous});
  final CarbonResult? awd;
  final CarbonResult? continuous;

  @override
  Widget build(BuildContext context) {
    final a = awd?.totalCo2eKg;
    final c = continuous?.totalCo2eKg;
    // CHỈ khi CÓ kết quả thật cho CẢ HAI, và continuous > 0.
    if (a == null || c == null || c <= 0) return const SizedBox.shrink();
    final reduction = (c - a) / c * 100;
    final text = Theme.of(context).textTheme;
    final better = reduction > 0;
    return Padding(
      padding: const EdgeInsets.only(top: AppSpacing.sm),
      child: AppCard(
        variant: AppCardVariant.highlight,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('So sánh kịch bản', style: text.titleSmall),
            const SizedBox(height: AppSpacing.xxs),
            Text(
              better
                  ? 'So với tưới ngập liên tục, kịch bản ngập – khô xen kẽ (AWD) '
                      'có tổng khí thải thấp hơn khoảng '
                      '${AppFormat.number(reduction, fractionDigits: 0)}%.'
                  : 'So với tưới ngập liên tục, kịch bản ngập – khô xen kẽ (AWD) '
                      'KHÔNG cho thấy giảm (chênh '
                      '${AppFormat.number(reduction.abs(), fractionDigits: 0)}%).',
              style: text.bodySmall,
            ),
            const SizedBox(height: AppSpacing.xxs),
            Text(
              'Đây là so sánh giữa hai kịch bản tính toán, KHÔNG phải mức giảm '
              'thực tế đã đo được của ruộng.',
              style: text.labelSmall?.copyWith(color: AppColors.textSecondary),
            ),
          ],
        ),
      ),
    );
  }
}

class _WarningsCard extends StatelessWidget {
  const _WarningsCard({required this.warnings});
  final List<String> warnings;
  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return AppCard(
      variant: AppCardVariant.warning,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Lưu ý từ hệ thống',
              style: text.titleSmall?.copyWith(color: AppColors.warningText)),
          const SizedBox(height: AppSpacing.xxs),
          for (final w in warnings)
            Padding(
              padding: const EdgeInsets.only(top: 2),
              child: Text('• $w',
                  style:
                      text.bodySmall?.copyWith(color: AppColors.warningText)),
            ),
        ],
      ),
    );
  }
}

class _MethodologyCard extends StatelessWidget {
  const _MethodologyCard({required this.result, required this.health});
  final CarbonResult result;
  final CarbonHealth? health;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final r = result;
    final calc = DateTime.tryParse(r.calculatedAt);
    Widget row(String k, String v) => Padding(
          padding: const EdgeInsets.symmetric(vertical: 2),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              SizedBox(
                width: 116,
                child: Text(k,
                    style: text.labelSmall
                        ?.copyWith(color: AppColors.textSecondary)),
              ),
              Expanded(child: Text(v, style: text.labelSmall)),
            ],
          ),
        );
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Phương pháp & bộ hệ số', style: text.titleSmall),
          const SizedBox(height: AppSpacing.xxs),
          row(
              'Phương pháp',
              r.methodologyName.isEmpty
                  ? AppFormat.missing
                  : r.methodologyName),
          if (r.methodologyVersion.isNotEmpty)
            row('Phiên bản', r.methodologyVersion),
          row(
              'Bộ hệ số',
              r.efConfigVersion.isEmpty
                  ? AppFormat.missing
                  : r.efConfigVersion),
          row(
              'Tính lúc',
              calc != null
                  ? AppFormat.dateTime(calc)
                  : (r.calculatedAt.isEmpty
                      ? AppFormat.missing
                      : r.calculatedAt)),
          if (health != null)
            row(
              'Trạng thái',
              health!.mrvCompliant
                  ? 'Đã đạt MRV'
                  : 'Chưa phải kết quả MRV (tham khảo)',
            ),
        ],
      ),
    );
  }
}

class _DetailsCard extends StatelessWidget {
  const _DetailsCard({required this.result});
  final CarbonResult result;
  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final r = result;
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Chi tiết kỹ thuật', style: text.titleSmall),
          const SizedBox(height: AppSpacing.xxs),
          if ((r.waterRegimeApplied ?? '').isNotEmpty)
            Text('Chế độ nước áp dụng: ${r.waterRegimeApplied}',
                style: text.labelSmall),
          if (r.engineVersion.isNotEmpty)
            Text('Phiên bản engine: ${r.engineVersion}',
                style: text.labelSmall),
          const SizedBox(height: AppSpacing.xs),
          for (final e in r.breakdown)
            Padding(
              padding: const EdgeInsets.only(bottom: AppSpacing.xs),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('${e.source} (${e.gas})', style: text.labelMedium),
                  if (e.formula.isNotEmpty)
                    Text(e.formula,
                        style: text.labelSmall
                            ?.copyWith(color: AppColors.textSecondary)),
                ],
              ),
            ),
        ],
      ),
    );
  }
}
