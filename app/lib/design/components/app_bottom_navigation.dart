import 'package:flutter/material.dart';

import '../tokens.dart';

/// Một mục trên thanh điều hướng đáy.
class AppNavItem {
  const AppNavItem({
    required this.label,
    required this.icon,
    required this.selectedIcon,
  });

  final String label;
  final IconData icon;
  final IconData selectedIcon;
}

/// 4 mục cố định theo SVG "trang chủ": Trang chủ · Ghi nhanh · Gửi dữ liệu ·
/// Tài khoản. Icon dùng Material Icons (không cần font ngoài).
const List<AppNavItem> kAppNavItems = [
  AppNavItem(
    label: 'Trang chủ',
    icon: Icons.home_outlined,
    selectedIcon: Icons.home_rounded,
  ),
  AppNavItem(
    label: 'Ghi nhanh',
    icon: Icons.add_circle_outline,
    selectedIcon: Icons.add_circle_rounded,
  ),
  AppNavItem(
    label: 'Gửi dữ liệu',
    icon: Icons.sync_outlined,
    selectedIcon: Icons.sync_rounded,
  ),
  AppNavItem(
    label: 'Tài khoản',
    icon: Icons.person_outline,
    selectedIcon: Icons.person_rounded,
  ),
];

/// Thanh điều hướng đáy dùng cho shell 4 tab. Bọc SafeArea đáy để không đè lên
/// thanh cử chỉ Android / home indicator iOS. Chiều cao nội dung ~64 + inset.
class AppBottomNavigation extends StatelessWidget {
  const AppBottomNavigation({
    super.key,
    required this.currentIndex,
    required this.onSelect,
    this.items = kAppNavItems,
  });

  final int currentIndex;
  final ValueChanged<int> onSelect;
  final List<AppNavItem> items;

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: const BoxDecoration(
        color: AppColors.surface,
        border: Border(top: BorderSide(color: AppColors.border)),
      ),
      child: SafeArea(
        top: false,
        child: NavigationBar(
          selectedIndex: currentIndex.clamp(0, items.length - 1),
          onDestinationSelected: onSelect,
          destinations: [
            for (final item in items)
              NavigationDestination(
                icon: Icon(item.icon),
                selectedIcon: Icon(item.selectedIcon),
                label: item.label,
                tooltip: item.label,
              ),
          ],
        ),
      ),
    );
  }
}
