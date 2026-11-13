// User-supplied service information. Presentation only, not access/usage rules.
// Keep aligned with web-dashboard/src/public/pricing.ts.
class ServicePlan {
  const ServicePlan(
      {required this.name,
      required this.price,
      required this.description,
      required this.groups,
      required this.suitableFor});
  final String name;
  final int price;
  final String description;
  final List<PlanFeatureGroup> groups;
  final List<String> suitableFor;
  bool get featured => name == 'PLUS';
}

class PlanFeatureGroup {
  const PlanFeatureGroup({this.label, required this.features});
  final String? label;
  final List<String> features;
}

/// A UI choice, not a purchased subscription or an account permission.
class ServicePlanSelection {
  const ServicePlanSelection({required this.plan, required this.cooperative});
  final ServicePlan plan;
  final bool cooperative;
  String get audienceLabel => cooperative ? 'Hợp tác xã' : 'Nông hộ';
}

const farmerServicePlans = [
  ServicePlan(
      name: 'FREE',
      price: 0,
      description: 'Bắt đầu ghi nhật ký canh tác trên điện thoại.',
      groups: [
        PlanFeatureGroup(features: [
          'Ghi nhật ký canh tác: gieo sạ, phân bón, tưới nước, rơm rạ, thuốc BVTV, thu hoạch',
          'Tính carbon mùa vụ hiện tại: 1 lần/năm',
          'Trợ lý AI 1 triệu token/ngày'
        ])
      ],
      suitableFor: [
        'Nông hộ mới làm quen ứng dụng'
      ]),
  ServicePlan(
      name: 'PLUS',
      price: 999990,
      description: 'Theo dõi chi phí và tài nguyên mỗi vụ.',
      groups: [
        PlanFeatureGroup(features: [
          'Ghi nhật ký canh tác đầy đủ 6 hoạt động',
          'Tính hiệu suất: hiệu quả tài nguyên, chi phí',
          'Tính carbon mùa vụ hiện tại: 5 lần/năm',
          'Trợ lý AI 3 triệu token/ngày'
        ])
      ],
      suitableFor: [
        'Nông hộ muốn giảm chi phí đầu vào',
        'Dùng nước, phân bón hiệu quả hơn'
      ]),
  ServicePlan(
      name: 'PRO',
      price: 1999990,
      description: 'Đầy đủ công cụ cho canh tác phát thải thấp.',
      groups: [
        PlanFeatureGroup(features: [
          'Ghi nhật ký canh tác đầy đủ 6 hoạt động',
          'Tính hiệu suất đầy đủ: phát thải carbon giữa các mùa vụ, tài nguyên, chi phí',
          'Tính carbon mùa vụ hiện tại: 15 lần/năm',
          'Trợ lý AI 5 triệu token/ngày'
        ])
      ],
      suitableFor: [
        'Nông hộ canh tác lúa phát thải thấp',
        'Cần so sánh hiệu quả giữa các vụ'
      ])
];

const cooperativeServicePlans = [
  ServicePlan(
      name: 'FREE',
      price: 0,
      description: 'Bắt đầu số hóa quản lý vùng trồng cho HTX.',
      groups: [
        PlanFeatureGroup(label: 'Cho HTX', features: [
          'Quản lý chung',
          'Cấp 05 mã tài khoản nông hộ',
          'Tính carbon mùa vụ: 15 lần/năm',
          'Dữ liệu thiếu: xem nội dung còn thiếu',
          'Quản lý nông hộ',
          'Tổng quan vụ mùa & carbon theo vụ'
        ]),
        PlanFeatureGroup(
            label: 'Cho nông dân',
            features: ['Ghi nhật ký canh tác', 'Trợ lý AI 200.000 token/ngày'])
      ],
      suitableFor: [
        'HTX muốn làm quen nền tảng',
        'Nhóm nông hộ quy mô nhỏ'
      ]),
  ServicePlan(
      name: 'PLUS',
      price: 14990000,
      description: 'Quản lý vùng trồng và sẵn sàng hồ sơ MRV.',
      groups: [
        PlanFeatureGroup(label: 'Cho HTX', features: [
          'Quản lý chung',
          'Cấp 80 mã tài khoản nông hộ',
          'Tính carbon mùa vụ: 300 lần/năm',
          'Dữ liệu thiếu: xem & gửi thông báo nhắc',
          'Quản lý nông hộ, xuất MRV 300 lượt',
          'Tổng quan vụ mùa & carbon theo vụ',
          'Hiệu suất vùng trong phạm vi HTX'
        ]),
        PlanFeatureGroup(label: 'Cho nông dân', features: [
          'Ghi nhật ký canh tác',
          'Tính hiệu suất: tài nguyên, chi phí',
          'Trợ lý AI 1 triệu token/ngày'
        ])
      ],
      suitableFor: [
        'HTX quy mô vừa (đến 80 nông hộ)',
        'Cần báo cáo MRV cho xuất khẩu'
      ]),
  ServicePlan(
      name: 'PRO',
      price: 49990000,
      description: 'Toàn bộ tính năng, không giới hạn quy mô.',
      groups: [
        PlanFeatureGroup(label: 'Cho HTX', features: [
          'Cấp mã nông hộ không giới hạn',
          'Tính carbon mùa vụ không giới hạn',
          'Đầy đủ tính năng quản lý: nông hộ, vụ mùa, dữ liệu thiếu, carbon theo vụ, hiệu suất vùng, MRV'
        ]),
        PlanFeatureGroup(label: 'Cho nông dân', features: [
          'Ghi nhật ký canh tác',
          'Tính hiệu suất đầy đủ',
          'Trợ lý AI 1 triệu token/ngày'
        ])
      ],
      suitableFor: [
        'HTX quy mô lớn, nhiều nông hộ',
        'Quản lý tập trung cả vùng trồng'
      ])
];

const journalActivities = [
  'Gieo sạ',
  'Phân bón',
  'Tưới nước',
  'Rơm rạ',
  'Thuốc BVTV',
  'Thu hoạch'
];
