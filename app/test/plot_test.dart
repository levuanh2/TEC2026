import 'package:agricarbon_app/models/plot.dart';
import 'package:agricarbon_app/models/plot_validation.dart';
import 'package:agricarbon_app/models/sync_state.dart';
import 'package:flutter_test/flutter_test.dart';

Plot _plot() {
  final now = DateTime(2026, 2, 1, 8);
  return Plot(
    clientId: 'p1',
    serverId: null,
    farmId: 'farm-1',
    plotCode: 'A-01',
    name: 'Ruộng nhà',
    areaHa: 0.5,
    latitude: 10.1,
    longitude: 105.2,
    createdAt: now,
    updatedAt: now,
  );
}

void main() {
  group('round-trip', () {
    test('toRow -> fromRow giữ nguyên field + sync metadata', () {
      final r = Plot.fromRow(_plot().toRow());
      expect(r.clientId, 'p1');
      expect(r.serverId, isNull);
      expect(r.farmId, 'farm-1');
      expect(r.plotCode, 'A-01');
      expect(r.name, 'Ruộng nhà');
      expect(r.areaHa, 0.5);
      expect(r.latitude, 10.1);
      expect(r.longitude, 105.2);
      expect(r.syncState, SyncState.pending);
      expect(r.retryCount, 0);
    });

    test('toServerInsert KHÔNG gửi id/metadata; GPS chỉ gửi khi có', () {
      final body = _plot().toServerInsert();
      expect(body.containsKey('id'), isFalse);
      expect(body.containsKey('server_id'), isFalse);
      expect(body.containsKey('sync_state'), isFalse);
      expect(body['farm_id'], 'farm-1');
      expect(body['area_ha'], 0.5);
      expect(body['latitude'], 10.1);

      final noGps = _plot().copyWith(latitude: null, longitude: null);
      // copyWith giữ giá trị cũ khi truyền null; dựng plot mới không GPS:
      final bare = Plot(
        clientId: 'x',
        farmId: 'f',
        plotCode: 'c',
        name: 'n',
        areaHa: 1,
        createdAt: DateTime(2026),
        updatedAt: DateTime(2026),
      );
      expect(bare.toServerInsert().containsKey('latitude'), isFalse);
      expect(noGps, isNotNull);
    });
  });

  group('validation area_ha', () {
    test('phải là số > 0', () {
      expect(plotAreaError('0'), isNotNull);
      expect(plotAreaError('-0.5'), isNotNull);
      expect(plotAreaError('abc'), isNotNull);
      expect(plotAreaError(''), isNotNull);
      expect(plotAreaError('0.5'), isNull);
      expect(plotAreaError('0,5'), isNull, reason: 'chấp nhận dấu phẩy VN');
    });
    test('quá lớn -> báo kiểm tra đơn vị', () {
      expect(plotAreaError('50000'), isNotNull);
    });
    test('parseArea', () {
      expect(parseArea('1,42'), 1.42);
      expect(parseArea(' 2.0 '), 2.0);
      expect(parseArea('x'), isNull);
    });
    test('mã thửa bắt buộc', () {
      expect(plotCodeError(''), isNotNull);
      expect(plotCodeError('A-01'), isNull);
    });
  });
}
