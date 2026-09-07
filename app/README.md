# app/ — Mobile App ghi nhật ký canh tác

- **Lớp MVP:** 1a (Walking Skeleton) — đường găng, làm trước tiên.
- **Phụ trách:** Người A.
- **Đặc tả:** [`../docs/modules/01-mobile-app.md`](../docs/modules/01-mobile-app.md)

## Vai trò

Thu thập Activity Data theo khung "1 phải 5 giảm" (giống, phân bón, nước tưới/AWD,
thuốc BVTV, xử lý rơm rạ), lưu offline-first, đồng bộ lên `backend/` khi có mạng,
hiển thị CO2e/kg trả về từ Carbon Engine.

## Stack (đề xuất, chưa khóa)

Flutter + SQLite cục bộ (`drift`/`sqflite`) cho offline-first. Đổi stack được, miễn
giữ nguyên hợp đồng API ở [`../docs/SRS.md`](../docs/SRS.md) mục "API contract 1a".

## Chạy

```bash
flutter pub get
flutter run
```

Chưa có logic nghiệp vụ — `lib/main.dart` mới chỉ là entrypoint rỗng có TODO.
