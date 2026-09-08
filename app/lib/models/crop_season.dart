class CropSeason {
  final String id;
  final String plotId;
  final String seasonCode;
  final String? varietyName;
  final DateTime? plantingDate;
  final DateTime? expectedHarvestDate;
  final String status; // planned | active | harvested | closed | cancelled

  const CropSeason({
    required this.id,
    required this.plotId,
    required this.seasonCode,
    this.varietyName,
    this.plantingDate,
    this.expectedHarvestDate,
    this.status = 'planned',
  });

  factory CropSeason.fromMap(Map<String, dynamic> map) => CropSeason(
        id: map['id'] as String,
        plotId: map['plot_id'] as String,
        seasonCode: map['season_code'] as String,
        varietyName: map['variety_name'] as String?,
        plantingDate: map['planting_date'] == null
            ? null
            : DateTime.parse(map['planting_date'] as String),
        expectedHarvestDate: map['expected_harvest_date'] == null
            ? null
            : DateTime.parse(map['expected_harvest_date'] as String),
        status: map['status'] as String? ?? 'planned',
      );

  Map<String, dynamic> toLocalMap() => {
        'id': id,
        'plot_id': plotId,
        'season_code': seasonCode,
        'variety_name': varietyName,
        'planting_date': plantingDate?.toIso8601String(),
        'expected_harvest_date': expectedHarvestDate?.toIso8601String(),
        'status': status,
      };

  Map<String, dynamic> toInsertMap() => {
        'plot_id': plotId,
        'season_code': seasonCode,
        'crop_type': 'rice',
        if (varietyName != null) 'variety_name': varietyName,
        if (plantingDate != null)
          'planting_date': _dateOnly(plantingDate!),
        if (expectedHarvestDate != null)
          'expected_harvest_date': _dateOnly(expectedHarvestDate!),
      };

  static String _dateOnly(DateTime d) =>
      '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';
}
