# backend/ — API + Carbon Engine

- **Lớp MVP:** 1a (Carbon Engine — đường găng) + 1b (benchmark, recommendation) + 1c (export MRV).
- **Phụ trách:** Người B.
- **Đặc tả:** [`../docs/modules/02-carbon-engine.md`](../docs/modules/02-carbon-engine.md)

## Vai trò

Nhận Activity Data từ `app/`, tính CO2e và CO2e/kg theo công thức
`Activity Data × Emission Factor`, tách riêng kịch bản AWD và tưới ngập liên tục.
Là nguồn số liệu cho Resource Dashboard (1b), Web Dashboard (1c) và Export MRV (1c).

## Stack (đề xuất, chưa khóa)

Python 3.11 + FastAPI + SQLite (đổi sang Postgres khi có nhiều HTX). Cùng ngôn ngữ
với `ml/` để Người B chỉ phải nuôi 1 môi trường.

## Chạy

```bash
python -m venv .venv && .venv/Scripts/activate   # Windows
pip install -r requirements.txt
uvicorn main:app --reload
```

## Quy tắc bắt buộc

Hệ số phát thải (Emission Factor) và giá tín chỉ carbon **không được hardcode** trong
code tính toán — mọi giá trị nằm ở [`config/emission_factors.yaml`](config/emission_factors.yaml)
kèm nguồn trích dẫn và ngày cần review lại. Xem SRS mục "Ràng buộc".
