import 'package:flutter/material.dart';

import '../db/local_database.dart';
import '../design/design.dart';
import '../models/crop_season_metrics.dart';
import '../models/resource_comparison.dart';
import '../models/sync_state.dart';
import '../services/metrics_cache.dart';
import '../services/metrics_service.dart';
import '../services/read_api.dart';
import '../services/recommendation_repository.dart';

/// Màn "Hiệu quả sử dụng tài nguyên" — 4 chỉ số trên mỗi kg lúa (nước / phân bón
/// / khí thải / chi phí) + so sánh + khuyến nghị.
///
/// KHÔNG tự tính chỉ số nào backend đã trả (`GET /v1/crop-seasons/{id}/metrics`).
/// KHÔNG gọi API bằng local UUID — dùng `crop_seasons.server_id`. `null` → chữ,
/// KHÔNG "0". Thiếu sản lượng → per-kg báo "Chưa có sản lượng". Offline đọc
/// cache kèm nhãn; refresh lỗi KHÔNG xoá cache. So sánh chỉ hiện khi có đủ nhóm
/// + thời kỳ + nguồn + dữ liệu — nếu không: "Chưa đủ dữ liệu để so sánh".
/// Khuyến nghị: chưa có endpoint → "chưa được cấu hình", KHÔNG bịa.
class ResourceDashboardScreen extends StatefulWidget {
  const ResourceDashboardScreen({
    super.key,
    required this.metricsApi,
    required this.cache,
    required this.recommendations,
    required this.db,
    required this.cropSeasonClientId,
    this.onOpenSync,
  });

  final MetricsService metricsApi;
  final MetricsCache cache;
  final RecommendationRepository recommendations;
  final LocalDatabase db;
  final String cropSeasonClientId;
  final VoidCallback? onOpenSync;

  @override
  State<ResourceDashboardScreen> createState() =>
      _ResourceDashboardScreenState();
}

enum _Phase { loading, noSeason, notSynced, content }

const _kKindLabel = <ResourceMetricKind, String>{
  ResourceMetricKind.water: 'Nước / kg',
  ResourceMetricKind.fertilizer: 'Phân bón / kg',
  ResourceMetricKind.co2e: 'Khí thải / kg',
  ResourceMetricKind.cost: 'Chi phí / kg',
};

const _kKindUnit = <ResourceMetricKind, String>{
  ResourceMetricKind.water: 'm³/kg',
  ResourceMetricKind.fertilizer: 'kg/kg',
  ResourceMetricKind.co2e: 'kg CO₂e/kg',
  ResourceMetricKind.cost: 'đồng/kg',
};

/// Nhóm Activity nguồn của mỗi chỉ số — lấy từ `read_repo.metrics()`, KHÔNG phải
/// số minh hoạ. Dùng cho sheet "chi tiết".
const _kKindSources = <ResourceMetricKind, List<String>>{
  ResourceMetricKind.water: [
    'Hoạt động "Tưới nước" — lượng nước (m³)',
    'Hoạt động "Thu hoạch" — sản lượng (kg)',
  ],
  ResourceMetricKind.fertilizer: [
    'Hoạt động "Bón phân" — khối lượng phân (kg)',
    'Hoạt động "Thu hoạch" — sản lượng (kg)',
  ],
  ResourceMetricKind.co2e: [
    'Kết quả tính phát thải của vụ (kịch bản thực tế)',
    'Hoạt động "Thu hoạch" — sản lượng (kg)',
  ],
  ResourceMetricKind.cost: [
    'Chi phí vật tư ghi trong mọi hoạt động (VND)',
    'Hoạt động "Thu hoạch" — sản lượng (kg)',
  ],
};

class _ResourceDashboardScreenState extends State<ResourceDashboardScreen> {
  _Phase _phase = _Phase.loading;

  String? _plotLabel;
  String? _seasonLabel;
  String? _seasonServerId;
  int _unsyncedCount = 0;

  CropSeasonMetrics? _metrics;
  final ResourceComparison _comparison = const ResourceComparison.unavailable();

  bool _busy = false;
  bool _sessionExpired = false;
  String? _softError; // lỗi khi vẫn có cache để hiện
  bool _fatal = false; // lỗi và KHÔNG có gì để hiện
  String? _fatalMessage;

  bool _recsAvailable = true;
  bool _recsError = false;
  List<Recommendation> _recs = const [];

  @override
  void initState() {
    super.initState();
    _recsAvailable = widget.recommendations.isAvailable;
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
    final plot = await widget.db.getPlotByClientId(season.plotClientId);
    final activities = await widget.db
        .listActivitiesByCropSeasonClientId(widget.cropSeasonClientId);
    if (!mounted) return;

    _plotLabel = plot?.plotCode ?? plot?.name;
    _seasonLabel = season.seasonCode;
    _seasonServerId = season.serverId;
    _unsyncedCount = activities
        .where((a) =>
            a.syncState == SyncState.pending || a.syncState == SyncState.failed)
        .length;

    if (_seasonServerId == null) {
      setState(() => _phase = _Phase.notSynced);
      return;
    }
    setState(() => _phase = _Phase.content);
    await _load();
  }

  Future<void> _load() async {
    final sid = _seasonServerId!;
    if (_busy) return;
    setState(() => _busy = true);

    // 1) Cache trước — không để trắng màn khi đang gọi mạng.
    final cached = await widget.cache.read(sid);
    if (!mounted) return;
    if (cached != null && _metrics == null) {
      setState(() => _metrics = cached);
    }

    // 2) Mạng.
    try {
      final live = await widget.metricsApi.fetchForCropSeason(sid);
      if (!mounted) return;
      final stamped = live.copyWith(fetchedAt: DateTime.now());
      await widget.cache.write(sid, stamped);
      setState(() {
        _metrics = stamped.copyWith(fromCache: false);
        _softError = null;
        _sessionExpired = false;
        _fatal = false;
      });
    } on ReadApiException catch (e) {
      if (!mounted) return;
      setState(() {
        if (e.isUnauthorized) _sessionExpired = true;
        if (_metrics != null) {
          _softError = e.isUnauthorized ? null : _friendly(e);
        } else {
          _fatal = true;
          _fatalMessage = _friendly(e);
        }
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        if (_metrics != null) {
          _softError = _friendly(e);
        } else {
          _fatal = true;
          _fatalMessage = _friendly(e);
        }
      });
    } finally {
      if (mounted) setState(() => _busy = false);
    }

    await _loadRecommendations(sid);
  }

  Future<void> _loadRecommendations(String sid) async {
    if (!widget.recommendations.isAvailable) {
      if (mounted) setState(() => _recsAvailable = false);
      return;
    }
    try {
      final list = await widget.recommendations.forCropSeason(sid);
      if (!mounted) return;
      setState(() {
        _recsAvailable = true;
        _recsError = false;
        _recs = list;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _recsError = true;
        _recs = const [];
      });
    }
  }

  static String _friendly(Object e) {
    if (e is ReadApiException) {
      if (e.isUnauthorized) {
        return 'Phiên đăng nhập đã hết hạn. Đăng nhập lại để cập nhật số mới.';
      }
      return 'Máy chủ chưa trả được chỉ số (mã ${e.statusCode}). Thử lại sau.';
    }
    final s = e.toString();
    if (s.contains('SocketException') ||
        s.contains('Failed host lookup') ||
        s.contains('TimeoutException')) {
      return 'Mất kết nối tới hệ thống. Kiểm tra mạng rồi thử lại.';
    }
    return 'Chưa lấy được chỉ số. Thử lại sau.';
  }

  @override
  Widget build(BuildContext context) {
    return AppScaffold(
      header: const AppHeader(
        title: 'AgriCarbon',
        subtitle: 'Hiệu quả tài nguyên',
        showBackButton: true,
      ),
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
        return EmptyState(
          icon: Icons.cloud_off_outlined,
          title: 'Vụ chưa đồng bộ lên hệ thống',
          message: 'Chỉ số hiệu quả được hệ thống tính từ nhật ký đã gửi lên. '
              'Gửi dữ liệu của vụ rồi quay lại đây.',
          actionLabel: widget.onOpenSync == null ? null : 'Đi tới Gửi dữ liệu',
          onAction: widget.onOpenSync,
        );
      case _Phase.content:
        return _content();
    }
  }

  Widget _content() {
    final text = Theme.of(context).textTheme;
    final m = _metrics;

    if (m == null) {
      if (_fatal) {
        return ErrorState(
          title: _sessionExpired
              ? 'Phiên đăng nhập có vấn đề'
              : 'Chưa lấy được chỉ số',
          message: _fatalMessage ?? 'Vui lòng thử lại.',
          onRetry: _busy ? null : _load,
        );
      }
      return const LoadingState(message: 'Đang tải chỉ số...');
    }

    return ListView(
      padding: const EdgeInsets.fromLTRB(
        AppSpacing.screenH,
        AppSpacing.md,
        AppSpacing.screenH,
        AppSpacing.xl,
      ),
      children: [
        if (_plotLabel != null || _seasonLabel != null)
          Text('Ruộng ${_plotLabel ?? '—'} · Vụ ${_seasonLabel ?? '—'}',
              style: text.titleSmall),
        const SizedBox(height: AppSpacing.sm),
        if (m.fromCache && _softError == null && !_sessionExpired) ...[
          _CacheStamp(fetchedAt: m.fetchedAt),
          const SizedBox(height: AppSpacing.sm),
        ],
        if (_sessionExpired) ...[
          _SoftBanner(
            icon: Icons.lock_outline,
            text: 'Phiên đăng nhập đã hết hạn — số dưới đây là bản đã lưu. '
                'Đăng nhập lại để cập nhật.',
            tone: AppColors.error,
          ),
          const SizedBox(height: AppSpacing.sm),
        ],
        if (_softError != null) ...[
          _SoftBanner(
            icon: Icons.sync_problem_outlined,
            text: '$_softError\nĐang xem số đã lưu trên máy.',
            tone: AppColors.warningText,
          ),
          const SizedBox(height: AppSpacing.sm),
        ],
        if (_unsyncedCount > 0) ...[
          _SoftBanner(
            icon: Icons.upload_file_outlined,
            text: 'Còn $_unsyncedCount hoạt động của vụ chưa gửi lên — chỉ số '
                'có thể chưa phản ánh đủ. Gửi nốt rồi mở lại.',
            tone: AppColors.warningText,
          ),
          const SizedBox(height: AppSpacing.sm),
        ],
        _MetricsGrid(metrics: m, onOpenDetail: _openDetail),
        const SizedBox(height: AppSpacing.md),
        _ComparisonCard(comparison: _comparison),
        const SizedBox(height: AppSpacing.sm),
        _RecommendationSection(
          available: _recsAvailable,
          error: _recsError,
          recommendations: _recs,
        ),
        const SizedBox(height: AppSpacing.lg),
        PrimaryButton(
          label: 'Tính lại',
          loading: _busy,
          onPressed: _busy ? null : _load,
        ),
        const SizedBox(height: AppSpacing.xs),
        Text(
          'Số do hệ thống tính từ nhật ký đã ghi — ứng dụng không tự tính lại.',
          textAlign: TextAlign.center,
          style: text.labelSmall?.copyWith(color: AppColors.textSecondary),
        ),
      ],
    );
  }

  Future<void> _openDetail(ResourceMetricKind kind) async {
    final m = _metrics;
    if (m == null) return;
    await showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      isScrollControlled: true,
      builder: (_) => _MetricDetailSheet(kind: kind, metrics: m),
    );
  }
}

// ---------------------------------------------------------------------------

String _formatPerKg(ResourceMetricKind kind, double value) => switch (kind) {
      ResourceMetricKind.water => AppFormat.number(value, fractionDigits: 1),
      ResourceMetricKind.fertilizer =>
        AppFormat.number(value, fractionDigits: 3),
      ResourceMetricKind.co2e => AppFormat.number(value, fractionDigits: 3),
      ResourceMetricKind.cost => AppFormat.number(value, fractionDigits: 0),
    };

class _MetricsGrid extends StatelessWidget {
  const _MetricsGrid({required this.metrics, required this.onOpenDetail});
  final CropSeasonMetrics metrics;
  final ValueChanged<ResourceMetricKind> onOpenDetail;

  @override
  Widget build(BuildContext context) {
    const kinds = ResourceMetricKind.values;
    return LayoutBuilder(
      builder: (context, constraints) {
        final twoCol = constraints.maxWidth >= 480;
        if (!twoCol) {
          return Column(
            children: [
              for (final k in kinds) ...[
                _MetricPerKgCard(
                    kind: k, metrics: metrics, onTap: () => onOpenDetail(k)),
                if (k != kinds.last) const SizedBox(height: AppSpacing.sm),
              ],
            ],
          );
        }
        // Hàng hai cột: KHÔNG dùng `stretch` (ListView cha không giới hạn chiều
        // cao → sẽ truyền `h=Infinity` xuống). Ô canh mép trên, cao theo nội
        // dung của chính nó.
        Widget cell(ResourceMetricKind k) => Expanded(
              child: _MetricPerKgCard(
                  kind: k, metrics: metrics, onTap: () => onOpenDetail(k)),
            );
        Widget row(ResourceMetricKind a, ResourceMetricKind b) => Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                cell(a),
                const SizedBox(width: AppSpacing.sm),
                cell(b),
              ],
            );
        return Column(
          children: [
            row(kinds[0], kinds[1]),
            const SizedBox(height: AppSpacing.sm),
            row(kinds[2], kinds[3]),
          ],
        );
      },
    );
  }
}

class _MetricPerKgCard extends StatelessWidget {
  const _MetricPerKgCard({
    required this.kind,
    required this.metrics,
    required this.onTap,
  });
  final ResourceMetricKind kind;
  final CropSeasonMetrics metrics;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final state = metrics.cellState(kind);
    final value = metrics.perKgValue(kind);
    final missingLabel = switch (state) {
      MetricCellState.missingYield => 'Chưa có sản lượng',
      _ => 'Chưa đủ dữ liệu',
    };
    return MetricCard(
      label: _kKindLabel[kind]!,
      value: state == MetricCellState.value && value != null
          ? _formatPerKg(kind, value)
          : null,
      unit: state == MetricCellState.value ? _kKindUnit[kind] : null,
      missingLabel: missingLabel,
      footnote: kind == ResourceMetricKind.water &&
              state == MetricCellState.value
          ? 'Với tưới ngập – khô xen kẽ, lượng nước là ước tính — độ chính xác '
              'thấp hơn các chỉ số khác.'
          : null,
      onTap: onTap,
    );
  }
}

class _CacheStamp extends StatelessWidget {
  const _CacheStamp({required this.fetchedAt});
  final DateTime? fetchedAt;
  @override
  Widget build(BuildContext context) {
    return Text(
      'Số đã lưu trên máy'
      '${fetchedAt != null ? ' · lấy về ${AppFormat.dateTime(fetchedAt)}' : ''}'
      ' — có thể chưa phải mới nhất.',
      style: Theme.of(context)
          .textTheme
          .labelSmall
          ?.copyWith(color: AppColors.textSecondary),
    );
  }
}

class _SoftBanner extends StatelessWidget {
  const _SoftBanner({
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

class _ComparisonCard extends StatelessWidget {
  const _ComparisonCard({required this.comparison});
  final ResourceComparison comparison;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    if (!comparison.isRenderable) {
      return AppCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('So với hộ khác', style: text.titleSmall),
            const SizedBox(height: AppSpacing.xxs),
            Text('Chưa đủ dữ liệu để so sánh.', style: text.bodyMedium),
            const SizedBox(height: AppSpacing.xxs),
            Text(
              'Cần nhóm hộ so sánh, cùng thời kỳ và nguồn dữ liệu rõ ràng — hệ '
              'thống chưa cung cấp cho vụ này. App không tự tạo mức tham chiếu.',
              style: text.labelSmall?.copyWith(color: AppColors.textSecondary),
            ),
          ],
        ),
      );
    }
    return AppCard(
      variant: AppCardVariant.highlight,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('So với ${comparison.group}', style: text.titleSmall),
          const SizedBox(height: AppSpacing.xxs),
          Text('Thời kỳ: ${comparison.period}', style: text.bodySmall),
          Text('Nguồn: ${comparison.source}',
              style: text.labelSmall?.copyWith(color: AppColors.textSecondary)),
        ],
      ),
    );
  }
}

class _RecommendationSection extends StatelessWidget {
  const _RecommendationSection({
    required this.available,
    required this.error,
    required this.recommendations,
  });
  final bool available;
  final bool error;
  final List<Recommendation> recommendations;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    if (!available) {
      return AppCard(
        variant: AppCardVariant.warning,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(Icons.info_outline, color: AppColors.warningText),
                const SizedBox(width: AppSpacing.xs),
                Expanded(
                  child: Text('Gợi ý điều chỉnh chưa được cấu hình',
                      style: text.titleSmall),
                ),
              ],
            ),
            const SizedBox(height: AppSpacing.xs),
            Text(
              'Khi có, các gợi ý giảm phát thải/chi phí kèm mức tác động ước '
              'tính và nguồn so sánh sẽ hiện ở đây. Ứng dụng không tự đưa ra '
              'lời khuyên về liều phân/thuốc.',
              style: text.bodyMedium?.copyWith(color: AppColors.textSecondary),
            ),
          ],
        ),
      );
    }
    if (error) {
      return AppCard(
        child: Text('Chưa tải được gợi ý — thử lại sau.',
            style: text.bodyMedium?.copyWith(color: AppColors.textSecondary)),
      );
    }
    final valid = recommendations.where((r) => r.isValid).toList();
    if (valid.isEmpty) {
      return AppCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Gợi ý điều chỉnh', style: text.titleSmall),
            const SizedBox(height: AppSpacing.xxs),
            Text('Chưa có gợi ý nào cho vụ này.', style: text.bodyMedium),
          ],
        ),
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text('Gợi ý điều chỉnh', style: text.titleSmall),
        const SizedBox(height: AppSpacing.xs),
        for (final r in valid) ...[
          _RecommendationCard(rec: r),
          const SizedBox(height: AppSpacing.sm),
        ],
      ],
    );
  }
}

class _RecommendationCard extends StatelessWidget {
  const _RecommendationCard({required this.rec});
  final Recommendation rec;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(rec.messageVi, style: text.bodyMedium),
          const SizedBox(height: AppSpacing.xs),
          Wrap(
            spacing: AppSpacing.xs,
            runSpacing: AppSpacing.xxs,
            children: [
              StatusBadge(
                label: 'Giảm ~${AppFormat.number(rec.co2eReductionKg)} kg CO₂e',
                tone: StatusTone.positive,
              ),
              StatusBadge(
                label:
                    'Tiết kiệm ~${AppFormat.number(rec.costSavingVnd, fractionDigits: 0)} đồng',
                tone: StatusTone.positive,
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.xs),
          Text('So với: ${rec.comparedTo}',
              style: text.labelSmall?.copyWith(color: AppColors.textSecondary)),
          Text('Nguồn: ${rec.source}',
              style: text.labelSmall?.copyWith(color: AppColors.textSecondary)),
          const SizedBox(height: AppSpacing.xxs),
          Text(
            'Khuyến nghị tham khảo — cân nhắc điều kiện thực tế ruộng của bạn. '
            'Ứng dụng không kê liều phân/thuốc cụ thể.',
            style: text.labelSmall?.copyWith(color: AppColors.textSecondary),
          ),
        ],
      ),
    );
  }
}

class _MetricDetailSheet extends StatelessWidget {
  const _MetricDetailSheet({required this.kind, required this.metrics});
  final ResourceMetricKind kind;
  final CropSeasonMetrics metrics;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final state = metrics.cellState(kind);
    final value = metrics.perKgValue(kind);
    final total = metrics.totalValue(kind);
    final stateLine = switch (state) {
      MetricCellState.value =>
        '${_formatPerKg(kind, value!)} ${_kKindUnit[kind]}',
      MetricCellState.missingYield =>
        'Chưa có sản lượng thu hoạch nên chưa tính được chỉ số trên mỗi kg.',
      MetricCellState.incompleteData =>
        'Chưa đủ dữ liệu loại này để tính chỉ số trên mỗi kg.',
    };
    return SafeArea(
      top: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(
          AppSpacing.screenH,
          0,
          AppSpacing.screenH,
          AppSpacing.lg,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('${_kKindLabel[kind]!} — chi tiết', style: text.titleMedium),
            const SizedBox(height: AppSpacing.xs),
            Text(stateLine, style: text.bodyMedium),
            const SizedBox(height: AppSpacing.md),
            Text('Tính từ', style: text.labelMedium),
            const SizedBox(height: AppSpacing.xxs),
            for (final s in _kKindSources[kind]!)
              Padding(
                padding: const EdgeInsets.only(bottom: 2),
                child: Text('• $s', style: text.bodySmall),
              ),
            const SizedBox(height: AppSpacing.md),
            if (kind != ResourceMetricKind.cost)
              _detailRow(
                context,
                'Tổng ${_totalLabel(kind)}',
                total == null
                    ? 'Chưa đủ dữ liệu'
                    : AppFormat.withUnit(total, _totalUnit(kind),
                        fractionDigits: 1),
              ),
            _detailRow(
              context,
              'Sản lượng thu hoạch',
              metrics.yieldKg == null
                  ? 'Chưa có sản lượng'
                  : AppFormat.withUnit(metrics.yieldKg, 'kg',
                      fractionDigits: 0),
            ),
            _detailRow(
              context,
              'Dữ liệu ${_totalLabel(kind)}',
              metrics.resourceComplete(kind) ? 'đủ' : 'chưa đủ',
            ),
            const SizedBox(height: AppSpacing.sm),
            Text(
              'Các số trên do hệ thống tính từ nhật ký — ứng dụng không tự '
              'cộng/chia lại.',
              style: text.labelSmall?.copyWith(color: AppColors.textSecondary),
            ),
          ],
        ),
      ),
    );
  }

  static String _totalLabel(ResourceMetricKind kind) => switch (kind) {
        ResourceMetricKind.water => 'nước tưới',
        ResourceMetricKind.fertilizer => 'phân bón',
        ResourceMetricKind.co2e => 'khí thải vụ',
        ResourceMetricKind.cost => 'chi phí',
      };

  static String _totalUnit(ResourceMetricKind kind) => switch (kind) {
        ResourceMetricKind.water => 'm³',
        ResourceMetricKind.fertilizer => 'kg',
        ResourceMetricKind.co2e => 'kg CO₂e',
        ResourceMetricKind.cost => 'đồng',
      };

  Widget _detailRow(BuildContext context, String k, String v) {
    final text = Theme.of(context).textTheme;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Flexible(
            child: Text(k,
                style:
                    text.bodySmall?.copyWith(color: AppColors.textSecondary)),
          ),
          const SizedBox(width: AppSpacing.sm),
          Text(v, style: text.bodySmall),
        ],
      ),
    );
  }
}
