"""Request-ID middleware + structured access log.

Chấp nhận `X-Request-ID` của client nếu có (để trace xuyên hệ thống), sinh
uuid4 nếu không. Log method/path/status/duration — KHÔNG BAO GIỜ log
Authorization header, JWT, password, service-role key.

Cũng đếm số round trip backend→Supabase của chính request đó (`profiling`):
một endpoint chậm thường chậm vì fan-out, và con số đó phải đo được chứ không
phải đoán. Header `Server-Timing` chỉ bật khi `server_timing` = true (dev/QA);
access log luôn có `db_calls`/`db_ms`, đều là số — không chứa dữ liệu người dùng.
"""
from __future__ import annotations

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from . import profiling

logger = logging.getLogger("agricarbon.access")

_SAFE_LABEL = str.maketrans({";": "_", ",": "_", '"': "_", "\\": "_"})


def _server_timing(profile: profiling.RequestProfile, duration_ms: float) -> str:
    parts = [f'total;dur={duration_ms:.1f}', f'db;dur={profile.db_ms:.1f};desc="{profile.calls} calls"']
    for label, count, total_ms in profile.top(14):
        metric = label.translate(_SAFE_LABEL).replace(" ", "-")
        parts.append(f'{metric};dur={total_ms:.1f};desc="x{count}"')
    for label, total_ms in profile.phases.items():
        parts.append(f'phase-{label.translate(_SAFE_LABEL).replace(" ", "-")};dur={total_ms:.1f}')
    return ", ".join(parts)


class RequestIdMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, server_timing: bool = False) -> None:
        super().__init__(app)
        self._server_timing = server_timing

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = request_id
        profile = profiling.start()
        started = time.monotonic()
        response = await call_next(request)
        duration_ms = (time.monotonic() - started) * 1000
        response.headers["X-Request-ID"] = request_id
        if self._server_timing:
            response.headers["Server-Timing"] = _server_timing(profile, duration_ms)
        logger.info(
            "access request_id=%s method=%s path=%s status=%d duration_ms=%.1f db_calls=%d db_ms=%.1f",
            request_id, request.method, request.url.path, response.status_code, duration_ms,
            profile.calls, profile.db_ms,
        )
        return response
