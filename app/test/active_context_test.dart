import 'dart:io';

import 'package:agricarbon_app/db/local_database.dart';
import 'package:agricarbon_app/models/crop_season.dart';
import 'package:agricarbon_app/models/farm.dart';
import 'package:agricarbon_app/models/plot.dart';
import 'package:agricarbon_app/services/active_context.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

const _user = 'cccccccc-0000-0000-0000-000000000000';

late Directory _tmp;

LocalDatabase _db() =>
    LocalDatabase(factory: databaseFactoryFfi, directoryOverride: _tmp.path);

Farm _farm(String id) => Farm(
      id: id,
      cooperativeId: 'org-1',
      farmCode: 'HH-$id',
      farmName: 'Hộ $id',
    );

Plot _plot(String clientId, String farmId) {
  final now = DateTime(2026);
  return Plot(
    clientId: clientId,
    farmId: farmId,
    plotCode: 'A-01',
    name: 'A-01',
    areaHa: 1,
    createdAt: now,
    updatedAt: now,
  );
}

CropSeason _season(String clientId, String plotClientId, {String? serverId}) {
  final now = DateTime(2026);
  return CropSeason(
    clientId: clientId,
    serverId: serverId,
    plotClientId: plotClientId,
    seasonCode: 'S1',
    createdAt: now,
    updatedAt: now,
  );
}

void main() {
  setUpAll(sqfliteFfiInit);
  setUp(() async {
    _tmp = await Directory.systemTemp.createTemp('agri_ctx_test');
  });
  tearDown(() async {
    if (_tmp.existsSync()) await _tmp.delete(recursive: true);
  });

  test('chọn Farm -> Plot -> Crop Season và khôi phục sau khi mở lại',
      () async {
    final db = _db();
    await db.openForUser(_user);
    await db.replaceFarms([_farm('f1')]);
    await db.upsertPlot(_plot('p1', 'f1'));
    await db.upsertCropSeason(_season('cs1', 'p1', serverId: 'srv-cs1'));

    final ctx = ActiveContext();
    await ctx.attach(db);
    await ctx.setFarm(await db.getFarm('f1'));
    await ctx.setPlot(await db.getPlotByClientId('p1'));
    await ctx.setCropSeason(await db.getCropSeasonByClientId('cs1'));

    expect(ctx.farmId, 'f1');
    expect(ctx.plotClientId, 'p1');
    expect(ctx.cropSeasonClientId, 'cs1');
    // Carbon dùng SERVER id của vụ.
    expect(ctx.cropSeasonServerId, 'srv-cs1');

    // Mở lại (giả lập restart) -> khôi phục đúng.
    final ctx2 = ActiveContext();
    await ctx2.attach(db);
    expect(ctx2.farmId, 'f1');
    expect(ctx2.plotClientId, 'p1');
    expect(ctx2.cropSeasonClientId, 'cs1');
    await db.close();
  });

  test('đổi Farm -> tự xoá Plot và Crop Season đang chọn', () async {
    final db = _db();
    await db.openForUser(_user);
    await db.replaceFarms([_farm('f1'), _farm('f2')]);
    await db.upsertPlot(_plot('p1', 'f1'));
    await db.upsertCropSeason(_season('cs1', 'p1'));

    final ctx = ActiveContext();
    await ctx.attach(db);
    await ctx.setFarm(await db.getFarm('f1'));
    await ctx.setPlot(await db.getPlotByClientId('p1'));
    await ctx.setCropSeason(await db.getCropSeasonByClientId('cs1'));

    await ctx.setFarm(await db.getFarm('f2'));
    expect(ctx.farmId, 'f2');
    expect(ctx.plotClientId, isNull);
    expect(ctx.cropSeasonClientId, isNull);
    await db.close();
  });

  test('entity bị xoá khỏi cache -> revalidate() dọn an toàn từ cấp mất xuống',
      () async {
    final db = _db();
    await db.openForUser(_user);
    await db.replaceFarms([_farm('f1')]);
    await db.upsertPlot(_plot('p1', 'f1'));
    await db.upsertCropSeason(_season('cs1', 'p1'));

    final ctx = ActiveContext();
    await ctx.attach(db);
    await ctx.setFarm(await db.getFarm('f1'));
    await ctx.setPlot(await db.getPlotByClientId('p1'));
    await ctx.setCropSeason(await db.getCropSeasonByClientId('cs1'));

    // Server không còn Farm f1 nữa (mất quyền / bị xoá) -> replaceFarms rỗng.
    await db.replaceFarms([]);
    await ctx.revalidate();

    expect(ctx.farm, isNull);
    expect(ctx.plot, isNull);
    expect(ctx.cropSeason, isNull);
    // active_context trong DB cũng đã được dọn.
    expect(await db.readActiveContext(), isNull);
    await db.close();
  });

  test('không cho gán Plot lệch Farm / Crop Season lệch Plot', () async {
    final db = _db();
    await db.openForUser(_user);
    await db.replaceFarms([_farm('f1'), _farm('f2')]);
    await db.upsertPlot(_plot('p2', 'f2'));

    final ctx = ActiveContext();
    await ctx.attach(db);
    await ctx.setFarm(await db.getFarm('f1'));

    expect(
      () => ctx.setPlot(_plot('p2', 'f2')),
      throwsArgumentError,
    );
    await db.close();
  });

  test('detach() xoá state RAM, KHÔNG đụng DB', () async {
    final db = _db();
    await db.openForUser(_user);
    await db.replaceFarms([_farm('f1')]);

    final ctx = ActiveContext();
    await ctx.attach(db);
    await ctx.setFarm(await db.getFarm('f1'));
    ctx.detach();

    expect(ctx.farm, isNull);
    // Bản ghi vẫn còn trong DB (không bị xoá).
    expect((await db.readActiveContext())?['farm_id'], 'f1');
    await db.close();
  });
}
