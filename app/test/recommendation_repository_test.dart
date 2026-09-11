import 'package:agricarbon_app/models/resource_comparison.dart';
import 'package:agricarbon_app/services/recommendation_repository.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('Recommendation.fromJson + isValid', () {
    test('đủ nội dung + impact (nested) + compared_to + source -> hợp lệ', () {
      final r = Recommendation.fromJson({
        'trigger': 'fertilizer_n_above_benchmark',
        'message_vi': 'Giảm phân đạm ở lần bón tới.',
        'compared_to': 'trung bình 12 hộ trong HTX, vụ Hè Thu 2026',
        'source': 'benchmark HTX',
        'impact': {'co2e_reduction_kg': 112.0, 'cost_saving_vnd': 340000},
      });
      expect(r.isValid, isTrue);
      expect(r.co2eReductionKg, 112.0);
      expect(r.costSavingVnd, 340000);
    });

    test('impact phẳng (không nested) cũng parse được', () {
      final r = Recommendation.fromJson({
        'message_vi': 'x',
        'compared_to': 'y',
        'benchmark': 'z',
        'co2e_reduction_kg': 5,
        'cost_saving_vnd': 10,
      });
      expect(r.hasImpact, isTrue);
      expect(r.source, 'z');
      expect(r.isValid, isTrue);
    });

    test('thiếu impact -> KHÔNG hợp lệ (không render như khuyến nghị)', () {
      final r = Recommendation.fromJson({
        'message_vi': 'Giảm phân.',
        'compared_to': 'trung bình HTX',
        'source': 'HTX',
      });
      expect(r.hasImpact, isFalse);
      expect(r.isValid, isFalse);
    });

    test('thiếu compared_to/source -> KHÔNG được tuyên bố benchmark', () {
      final r = Recommendation.fromJson({
        'message_vi': 'Giảm phân.',
        'impact': {'co2e_reduction_kg': 1, 'cost_saving_vnd': 1},
      });
      expect(r.hasBenchmark, isFalse);
      expect(r.isValid, isFalse);
    });

    test('thiếu nội dung tiếng Việt -> KHÔNG hợp lệ', () {
      final r = Recommendation.fromJson({
        'message_vi': '   ',
        'compared_to': 'a',
        'source': 'b',
        'impact': {'co2e_reduction_kg': 1, 'cost_saving_vnd': 1},
      });
      expect(r.isValid, isFalse);
    });
  });

  group('UnavailableRecommendationRepository', () {
    test('isAvailable=false, forCropSeason ném (không fixture/mock)', () async {
      const repo = UnavailableRecommendationRepository();
      expect(repo.isAvailable, isFalse);
      await expectLater(
        repo.forCropSeason('srv-cs1'),
        throwsA(isA<RecommendationUnavailable>()),
      );
    });
  });

  group('ResourceComparison', () {
    test('unavailable -> không render', () {
      expect(const ResourceComparison.unavailable().isRenderable, isFalse);
    });

    test('chỉ render khi đủ nhóm + thời kỳ + nguồn + dữ liệu đủ', () {
      expect(
        const ResourceComparison(
          group: '12 hộ HTX',
          period: 'Hè Thu 2026',
          source: 'trung bình HTX',
          dataSufficient: true,
        ).isRenderable,
        isTrue,
      );
      expect(
        const ResourceComparison(
          group: '12 hộ HTX',
          period: 'Hè Thu 2026',
          source: 'trung bình HTX',
          dataSufficient: false,
        ).isRenderable,
        isFalse,
      );
    });
  });
}
