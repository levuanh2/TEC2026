import 'package:agricarbon_app/models/crop_season.dart';
import 'package:agricarbon_app/models/crop_season_validation.dart';
import 'package:agricarbon_app/models/methodology_enums.dart';
import 'package:flutter_test/flutter_test.dart';

CropSeason _full() {
  final now = DateTime(2025, 11, 1);
  return CropSeason(
    clientId: 'cs1',
    serverId: 'srv-1',
    plotClientId: 'p1',
    seasonCode: 'ĐX 2025-2026',
    varietyName: 'OM5451',
    plantingDate: DateTime(2025, 11, 20),
    expectedHarvestDate: DateTime(2026, 2, 28),
    actualHarvestDate: DateTime(2026, 3, 1),
    defaultIrrigationMethod: DefaultIrrigationMethod.awd,
    ipccWaterRegime: IpccWaterRegime.irrigatedMultipleDrainage,
    preSeasonWaterRegime: PreSeasonWaterRegime.floodedGt30d,
    cultivationDays: 101,
    drainageEventCount: 3,
    status: CropSeasonStatus.active,
    createdAt: now,
    updatedAt: now,
  );
}

void main() {
  group('round-trip', () {
    test('toRow -> fromRow giữ nguyên MỌI field phương pháp luận', () {
      final restored = CropSeason.fromRow(_full().toRow());
      final o = _full();
      expect(restored.clientId, o.clientId);
      expect(restored.serverId, o.serverId);
      expect(restored.plotClientId, o.plotClientId);
      expect(restored.seasonCode, o.seasonCode);
      expect(restored.varietyName, o.varietyName);
      expect(restored.plantingDate, o.plantingDate);
      expect(restored.expectedHarvestDate, o.expectedHarvestDate);
      expect(restored.actualHarvestDate, o.actualHarvestDate);
      expect(restored.defaultIrrigationMethod, DefaultIrrigationMethod.awd);
      expect(
          restored.ipccWaterRegime, IpccWaterRegime.irrigatedMultipleDrainage);
      expect(restored.preSeasonWaterRegime, PreSeasonWaterRegime.floodedGt30d);
      expect(restored.cultivationDays, 101);
      expect(restored.drainageEventCount, 3);
      expect(restored.status, CropSeasonStatus.active);
    });

    test('field chưa biết = null, KHÔNG bị default khi round-trip', () {
      final bare = CropSeason(
        clientId: 'c',
        plotClientId: 'p',
        seasonCode: 'S',
        createdAt: DateTime(2026),
        updatedAt: DateTime(2026),
      );
      final restored = CropSeason.fromRow(bare.toRow());
      expect(restored.ipccWaterRegime, isNull);
      expect(restored.preSeasonWaterRegime, isNull);
      expect(restored.defaultIrrigationMethod, isNull);
      expect(restored.cultivationDays, isNull);
      expect(restored.drainageEventCount, isNull);
    });
  });

  group('toServerInsert', () {
    test('gửi đúng wire enum, chỉ gửi field CÓ giá trị', () {
      final body = _full().toServerInsert(plotServerId: 'srv-plot');
      expect(body['plot_id'], 'srv-plot');
      expect(body['default_irrigation_method'], 'awd');
      expect(body['ipcc_water_regime'], 'irrigated_multiple_drainage');
      expect(body['pre_season_water_regime'], 'flooded_pre_season_gt_30d');
      expect(body['cultivation_days'], 101);
      expect(body['drainage_event_count'], 3);
      expect(body['planting_date'], '2025-11-20');
      expect(body['status'], 'active');
    });

    test('field null -> KHÔNG có trong payload (server không ép mặc định)', () {
      final bare = CropSeason(
        clientId: 'c',
        plotClientId: 'p',
        seasonCode: 'S',
        createdAt: DateTime(2026),
        updatedAt: DateTime(2026),
      );
      final body = bare.toServerInsert(plotServerId: 'x');
      expect(body.containsKey('ipcc_water_regime'), isFalse);
      expect(body.containsKey('pre_season_water_regime'), isFalse);
      expect(body.containsKey('cultivation_days'), isFalse);
      expect(body.containsKey('variety_name'), isFalse);
    });
  });

  group('validation', () {
    test('mã vụ bắt buộc', () {
      expect(seasonCodeError(''), isNotNull);
      expect(seasonCodeError('  '), isNotNull);
      expect(seasonCodeError('ĐX'), isNull);
    });

    test('cultivation_days phải > 0 nếu có nhập', () {
      expect(cultivationDaysError(null), isNull);
      expect(cultivationDaysError(0), isNotNull);
      expect(cultivationDaysError(-5), isNotNull);
      expect(cultivationDaysError(100), isNull);
    });

    test('drainage_event_count phải >= 0', () {
      expect(drainageCountError(null), isNull);
      expect(drainageCountError(-1), isNotNull);
      expect(drainageCountError(0), isNull);
      expect(drainageCountError(4), isNull);
    });

    test('ngày thu hoạch không trước ngày gieo', () {
      expect(
        harvestNotBeforePlantingError(
          planting: DateTime(2025, 11, 20),
          expectedHarvest: DateTime(2025, 11, 1),
        ),
        isNotNull,
      );
      expect(
        harvestNotBeforePlantingError(
          planting: DateTime(2025, 11, 20),
          actualHarvest: DateTime(2026, 3, 1),
        ),
        isNull,
      );
    });

    test('gợi ý cultivation_days từ ngày gieo/thu hoạch — chỉ là gợi ý', () {
      expect(
        suggestCultivationDays(
          planting: DateTime(2025, 11, 20),
          expectedHarvest: DateTime(2026, 2, 28),
        ),
        100,
      );
      expect(suggestCultivationDays(planting: DateTime(2025, 11, 20)), isNull);
      // Ưu tiên ngày thu hoạch THỰC TẾ.
      expect(
        suggestCultivationDays(
          planting: DateTime(2025, 11, 20),
          expectedHarvest: DateTime(2026, 2, 28),
          actualHarvest: DateTime(2026, 3, 1),
        ),
        101,
      );
    });

    test('AWD thiếu số lần rút nước -> cảnh báo (không chặn lưu)', () {
      expect(
        awdDrainageWarning(
            isMultipleDrainageRegime: true, drainageEventCount: null),
        isNotNull,
      );
      expect(
        awdDrainageWarning(
            isMultipleDrainageRegime: true, drainageEventCount: 3),
        isNull,
      );
      expect(
        awdDrainageWarning(
            isMultipleDrainageRegime: false, drainageEventCount: null),
        isNull,
      );
    });
  });

  group('enum wire khớp Supabase', () {
    test('ipcc_water_regime', () {
      expect(IpccWaterRegime.values.map((e) => e.wire).toSet(), {
        'irrigated_continuous_flooding',
        'irrigated_single_drainage',
        'irrigated_multiple_drainage',
        'rainfed_regular',
        'rainfed_drought_prone',
        'deep_water',
        'upland',
      });
    });
    test('pre_season_water_regime', () {
      expect(PreSeasonWaterRegime.values.map((e) => e.wire).toSet(), {
        'non_flooded_pre_season_lt_180d',
        'non_flooded_pre_season_gt_180d',
        'flooded_pre_season_gt_30d',
        'non_flooded_pre_season_gt_365d',
      });
    });
    test('default_irrigation_method', () {
      expect(DefaultIrrigationMethod.values.map((e) => e.wire).toSet(), {
        'awd',
        'continuous_flooding',
        'alternate',
        'other',
      });
    });
    test('mỗi enum có nhãn tiếng Việt không rỗng', () {
      for (final e in [
        ...IpccWaterRegime.values,
        ...PreSeasonWaterRegime.values,
        ...DefaultIrrigationMethod.values,
      ]) {
        expect((e as dynamic).labelVi, isNotEmpty);
      }
    });
  });
}
