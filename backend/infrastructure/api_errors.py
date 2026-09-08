"""Unified HTTP error envelope for every /v1 route.

Toàn bộ response lỗi phải có hình dạng:

    {"error": {"code": "<snake_case>", "message": "<human message>"}}

Trước đây route carbon (POST /carbon/calculate, GET .../carbon) dùng
`{"error": "<string>", "message": "..."}` (flat) còn route đọc mới dùng dạng
nested — hai hình dạng khác nhau trong cùng API là vi phạm hợp đồng lỗi thống
nhất. Dùng `error_detail()` ở MỌI nơi raise HTTPException thay vì tự dựng dict.
"""
from __future__ import annotations

from typing import Any


def error_detail(code: str, message: str, **extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"code": code, "message": message}
    body.update(extra)
    return {"error": body}
