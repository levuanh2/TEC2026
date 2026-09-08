class Farm {
  final String id;
  final String cooperativeId;
  final String farmCode;
  final String farmName;

  const Farm({
    required this.id,
    required this.cooperativeId,
    required this.farmCode,
    required this.farmName,
  });

  factory Farm.fromMap(Map<String, dynamic> map) => Farm(
        id: map['id'] as String,
        cooperativeId: map['cooperative_id'] as String,
        farmCode: map['farm_code'] as String,
        farmName: map['farm_name'] as String,
      );

  Map<String, dynamic> toLocalMap() => {
        'id': id,
        'cooperative_id': cooperativeId,
        'farm_code': farmCode,
        'farm_name': farmName,
      };
}
