"""Pagination cho list endpoint — quy ước page/page_size (SRS API §26).

`paginate()` cắt một list đã load đầy đủ (repo hiện tại đọc từng bảng riêng,
không query phân trang tận Postgres — chấp nhận được ở quy mô MVP; ghi rõ đây
KHÔNG phải phân trang tận DB, để không hiểu lầm là đã tối ưu N+1).
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from .api_errors import error_detail

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


def validate_page_params(page: int, page_size: int) -> None:
    if page < 1:
        raise HTTPException(
            status_code=400,
            detail=error_detail("invalid_page", "page phải >= 1."),
        )
    if page_size < 1 or page_size > MAX_PAGE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=error_detail(
                "invalid_page_size", f"page_size phải trong khoảng 1..{MAX_PAGE_SIZE}."
            ),
        )


def paginate(items: list[Any], page: int, page_size: int) -> dict[str, Any]:
    validate_page_params(page, page_size)
    total = len(items)
    start = (page - 1) * page_size
    page_items = items[start : start + page_size]
    return {
        "items": page_items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "has_more": start + page_size < total,
    }
