import 'package:supabase_flutter/supabase_flutter.dart';

import '../db/local_database.dart';
import '../models/activity.dart';
import '../models/crop_season.dart';
import '../models/farm.dart';
import '../models/plot.dart';
import 'device_service.dart';

const _kDetailTableFor = <String, String>{
  'seeding': 'seeding_events',
  'fertilizer': 'fertilizer_applications',
  'irrigation': 'irrigation_events',
  'pesticide': 'pesticide_applications',
  'fuel': 'fuel_usages',
  'straw_management': 'straw_management_events',
  'harvest': 'harvest_events',
};

/// Đẩy dữ liệu offline lên Supabase khi có mạng. KHÔNG qua backend FastAPI —
/// activities là dữ liệu CRUD RLS đã tự chịu trách nhiệm phân quyền (baseline
/// đã có policy insert cho authenticated); backend chỉ lo tính CO2e.
///
/// Idempotent bằng đúng cơ chế schema đã có sẵn: unique (device_id,
/// client_event_id) trên `activities`, và activity_id làm PRIMARY KEY của mọi
/// bảng chi tiết — upsert lại không tạo bản ghi trùng, retry an toàn (FR-1a-07).
class SyncService {
  SyncService(this._client, this._db, this._devices);
  final SupabaseClient _client;
  final LocalDatabase _db;
  final DeviceService _devices;

  final _batchCache = <String, String>{}; // cropSeasonId(server) -> batchId(server)

  Future<SyncSummary> syncAll() async {
    final summary = SyncSummary();
    await _pushPlots(summary);
    await _pushCropSeasons(summary);
    await _pushActivities(summary);
    return summary;
  }

  Future<void> _pushPlots(SyncSummary summary) async {
    for (final row in await _db.listPendingPlots()) {
      final localId = row['id'] as String;
      try {
        final plot = Plot.fromMap(row);
        final inserted = await _client
            .from('plots')
            .insert(plot.toInsertMap())
            .select('id')
            .single();
        await _db.markPlotSynced(localId, inserted['id'] as String);
        summary.plotsSynced++;
      } catch (e) {
        summary.errors.add('Thửa ${row['plot_code']}: $e');
      }
    }
  }

  Future<void> _pushCropSeasons(SyncSummary summary) async {
    final localPlotIds = (await _db.listPendingPlots()).map((r) => r['id'] as String).toSet();
    for (final row in await _db.listPendingCropSeasons()) {
      final localId = row['id'] as String;
      final plotId = row['plot_id'] as String;
      if (localPlotIds.contains(plotId)) {
        continue; // thửa cha chưa đồng bộ xong — thử lại lượt sau
      }
      try {
        final season = CropSeason.fromMap(row);
        final inserted = await _client
            .from('crop_seasons')
            .insert(season.toInsertMap())
            .select('id')
            .single();
        await _db.markCropSeasonSynced(localId, inserted['id'] as String);
        summary.cropSeasonsSynced++;
      } catch (e) {
        summary.errors.add('Vụ ${row['season_code']}: $e');
      }
    }
  }

  Future<void> _pushActivities(SyncSummary summary) async {
    final localCropSeasonIds =
        (await _db.listPendingCropSeasons()).map((r) => r['id'] as String).toSet();
    final deviceId = await _devices.ensureServerDeviceId();

    for (final activity in await _db.listPendingActivities()) {
      if (localCropSeasonIds.contains(activity.cropSeasonId)) {
        continue; // vụ canh tác cha chưa có id thật trên server — thử lại lượt sau
      }
      try {
        await _db.updateActivitySyncState(activity.id, state: SyncState.syncing);
        final batchId = await _ensureDefaultBatch(activity.cropSeasonId);

        final activityRow = await _client
            .from('activities')
            .upsert(
              {
                'production_batch_id': batchId,
                'activity_type': activity.type,
                'occurred_at': activity.occurredAt.toIso8601String(),
                'recorded_at': activity.createdAt.toIso8601String(),
                'source': 'mobile_offline',
                'device_id': deviceId,
                'client_event_id': activity.id,
                if (activity.note != null) 'note': activity.note,
              },
              onConflict: 'device_id,client_event_id',
            )
            .select('id')
            .single();
        final serverActivityId = activityRow['id'] as String;

        final table = _kDetailTableFor[activity.type];
        if (table != null) {
          await _client.from(table).upsert(
            {'activity_id': serverActivityId, ...activity.payload},
            onConflict: 'activity_id',
          );
        }

        await _db.updateActivitySyncState(
          activity.id,
          state: SyncState.synced,
          serverActivityId: serverActivityId,
        );
        summary.activitiesSynced++;
      } catch (e) {
        await _db.updateActivitySyncState(
          activity.id,
          state: SyncState.failed,
          error: e.toString(),
        );
        summary.errors.add('Hoạt động ${activity.type} (${activity.occurredAt}): $e');
      }
    }
  }

  /// Nông dân không thao tác khái niệm "lô" — MVP tự tạo 1 batch mặc định mỗi vụ
  /// để thoả `activities.production_batch_id NOT NULL`. Carbon Engine vẫn tính
  /// theo Crop Season, batch này chỉ để thoả ràng buộc DB (xem
  /// docs/CARBON_CALCULATION_SCOPE_RESOLUTION.md — Batch là traceability).
  Future<String> _ensureDefaultBatch(String cropSeasonId) async {
    final cached = _batchCache[cropSeasonId];
    if (cached != null) return cached;
    final row = await _client
        .from('production_batches')
        .upsert(
          {'crop_season_id': cropSeasonId, 'batch_code': 'default'},
          onConflict: 'crop_season_id,batch_code',
        )
        .select('id')
        .single();
    final id = row['id'] as String;
    _batchCache[cropSeasonId] = id;
    return id;
  }

  /// HTX (organization) mà người dùng hiện tại là thành viên — cần để tạo Farm
  /// mới (farms.cooperative_id). Việc gia nhập HTX nằm ngoài phạm vi MVP 1a
  /// (do quản lý HTX thêm thủ công qua Supabase), app chỉ đọc lại.
  Future<String?> currentCooperativeId() async {
    final userId = _client.auth.currentUser?.id;
    if (userId == null) return null;
    final rows = await _client
        .from('organization_memberships')
        .select('organization_id')
        .eq('user_id', userId)
        .limit(1);
    final list = rows as List;
    if (list.isEmpty) return null;
    return list.first['organization_id'] as String;
  }

  /// Kéo Farm/Plot/CropSeason từ Supabase về cache local — chỉ hiển thị, không
  /// phải nguồn ghi (RLS đã lọc đúng theo người dùng hiện tại).
  Future<void> pullFarmsPlotsSeasons() async {
    final farms = await _client.from('farms').select();
    for (final row in farms as List) {
      await _db.upsertFarm(Farm.fromMap(row as Map<String, dynamic>));
    }
    final plots = await _client.from('plots').select();
    for (final row in plots as List) {
      await _db.upsertPlot(Plot.fromMap(row as Map<String, dynamic>));
    }
    final seasons = await _client.from('crop_seasons').select();
    for (final row in seasons as List) {
      await _db.upsertCropSeason(CropSeason.fromMap(row as Map<String, dynamic>));
    }
  }
}

class SyncSummary {
  int plotsSynced = 0;
  int cropSeasonsSynced = 0;
  int activitiesSynced = 0;
  final errors = <String>[];

  bool get hasErrors => errors.isNotEmpty;
}
