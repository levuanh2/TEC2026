"""Request-ID middleware + structured access log.

Chấp nhận `X-Request-ID` của client nếu có (để trace xuyên hệ thống), sinh
uuid4 nếu không. Log method/path/status/duration — KHÔNG BAO GIỜ log
Authorization header, JWT, password, service-role key.
"""
from __future__ import annotations

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("agricarbon.access")


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = request_id
        started = time.monotonic()
        response = await call_next(request)
        duration_ms = (time.monotonic() - started) * 1000
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "access request_id=%s method=%s path=%s status=%d duration_ms=%.1f",
            request_id, request.method, request.url.path, response.status_code, duration_ms,
        )
        return response
