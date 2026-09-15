# Chỉ mục sơ đồ

Mọi sơ đồ trong site được viết bằng Mermaid ngay trong Markdown, render bởi Material
for MkDocs. Bảng dưới liệt kê từng sơ đồ và trang chứa nó.

## Kiến trúc

| Sơ đồ | Loại | Trang |
|---|---|---|
| Vòng lặp sản phẩm MEASURE → UNDERSTAND → OPTIMIZE → ACT | flowchart | [Trang chủ](../index.md) |
| Ba trải nghiệm + backend dùng chung | flowchart | [Trang chủ](../index.md) |
| **System Context** | flowchart | [System context](system-context.md) |
| Ranh giới tin cậy | flowchart | [System context](system-context.md) |
| **Container** | flowchart | [Container architecture](container-architecture.md) |
| Thành phần bên trong FastAPI | flowchart | [Container architecture](container-architecture.md) |
| Phụ thuộc giữa các module | flowchart | [Module map](module-map.md) |
| **Domain Model** — tổ chức, nông hộ, vụ | classDiagram | [Domain model](domain-model.md) |
| Domain Model — hoạt động canh tác | classDiagram | [Domain model](domain-model.md) |
| Domain Model — kết quả theo vụ | classDiagram | [Domain model](domain-model.md) |
| Domain Model — MRV | classDiagram | [Domain model](domain-model.md) |

## Database

| Sơ đồ | Loại | Trang |
|---|---|---|
| **Database ER** — Organization / Membership | erDiagram | [Database schema](../database/schema.md) |
| Database ER — Farm / Plot / Season / Batch | erDiagram | [Database schema](../database/schema.md) |
| Database ER — Activities | erDiagram | [Database schema](../database/schema.md) |
| Database ER — Carbon | erDiagram | [Database schema](../database/schema.md) |
| Database ER — Recommendation | erDiagram | [Database schema](../database/schema.md) |
| Database ER — Computer Vision | erDiagram | [Database schema](../database/schema.md) |
| Database ER — MRV và Exports | erDiagram | [Database schema](../database/schema.md) |

## Workflow và module

| Sơ đồ | Loại | Trang |
|---|---|---|
| **Farmer Workflow** — vòng chung | flowchart | [Luồng nông hộ](../workflows/farmer-workflow.md) |
| Flutter offline flow | flowchart | [Luồng nông hộ](../workflows/farmer-workflow.md) |
| Farmer Web online flow | flowchart | [Luồng nông hộ](../workflows/farmer-workflow.md) |
| **Flutter Sync** — kiến trúc | flowchart | [Flutter Mobile](../modules/flutter-mobile.md) |
| Flutter — luồng trạng thái đồng bộ | flowchart | [Flutter Mobile](../modules/flutter-mobile.md) |
| Flutter — xoá mềm | flowchart | [Flutter Mobile](../modules/flutter-mobile.md) |
| Web — điểm vào và định tuyến | flowchart | [Web](../modules/web-dashboard.md) |
| **Carbon Flow** — tính, lưu, tái sử dụng | flowchart | [Carbon Engine](../modules/carbon-engine.md) |
| Phân luồng rơm rạ | flowchart | [Phương pháp tính](../methodology/carbon-calculation.md) |
| **Carbon Sequence** — tính và lưu | sequenceDiagram | [Sequence tính Carbon](../workflows/carbon-calculation-sequence.md) |
| Carbon Sequence — đọc bản tính | sequenceDiagram | [Sequence tính Carbon](../workflows/carbon-calculation-sequence.md) |
| Resource Metrics — tổng hợp có trọng số | flowchart | [Resource Metrics](../modules/resource-metrics.md) |
| **Recommendation** — luồng sinh | flowchart | [Recommendation](../modules/recommendation.md) |
| Recommendation — quyết định rule AWD | flowchart | [Recommendation](../modules/recommendation.md) |
| Computer Vision — upload và suy luận | flowchart | [Computer Vision](../modules/computer-vision.md) |
| **MRV** — quy trình hồ sơ | flowchart | [MRV](../modules/mrv.md) |
| **Export** — snapshot JSON và renderer XLSX/PDF | flowchart | [MRV](../modules/mrv.md) |
| Export — tải về an toàn | flowchart | [MRV](../modules/mrv.md) |
| FastAPI xác thực người gọi | sequenceDiagram | [Authentication và RLS](../security/authentication-and-rls.md) |

## Sequence hệ thống

Tất cả nằm ở [Sequence diagram hệ thống](../workflows/system-sequences.md):

1. Login / auth
2. Farmer thêm activity qua Web
3. Flutter offline sync
4. Carbon calculation (tóm tắt)
5. Recommendation simulation
6. MRV JSON export
7. XLSX / PDF render
8. Secure artifact download

## Deployment

| Sơ đồ | Loại | Trang |
|---|---|---|
| **Deployment** — topology đang dùng | flowchart | [Kiến trúc triển khai](../deployment/architecture.md) |
| Deployment — topology tổng quát | flowchart | [Kiến trúc triển khai](../deployment/architecture.md) |
