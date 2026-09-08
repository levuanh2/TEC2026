class Plot {
  final String id;
  final String farmId;
  final String plotCode;
  final String name;
  final double areaHa;

  const Plot({
    required this.id,
    required this.farmId,
    required this.plotCode,
    required this.name,
    required this.areaHa,
  });

  factory Plot.fromMap(Map<String, dynamic> map) => Plot(
        id: map['id'] as String,
        farmId: map['farm_id'] as String,
        plotCode: map['plot_code'] as String,
        name: map['name'] as String,
        areaHa: (map['area_ha'] as num).toDouble(),
      );

  Map<String, dynamic> toLocalMap() => {
        'id': id,
        'farm_id': farmId,
        'plot_code': plotCode,
        'name': name,
        'area_ha': areaHa,
      };

  /// Hàng để insert lên Supabase — KHÔNG gửi id, để DB tự sinh (gen_random_uuid()).
  /// id cục bộ (uuid tạm) sẽ được thay bằng id thật sau khi Supabase trả về.
  Map<String, dynamic> toInsertMap() => {
        'farm_id': farmId,
        'plot_code': plotCode,
        'name': name,
        'area_ha': areaHa,
      };
}
