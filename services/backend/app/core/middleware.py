"""Request context middleware: request IDs, access log line, metrics, last-resort 500s (PRD 13.1.3).

Pure ASGI (not ``BaseHTTPMiddleware``) so that streaming and exception handling behave.
The access log records route template, method, status and latency only: never the query string,
headers or body, which can carry descriptions, tokens or CSV content (PRD 17.3).
"""

from __future__ import annotations

import time
from typing import Any

import structlog
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import internal_error_response
from app.core.ids import REQUEST_ID_PATTERN, new_ulid
from app.core.metrics import HTTP_DURATION, HTTP_REQUESTS

log = structlog.get_logger("http")


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp, service: str) -> None:
        self.app = app
        self.service = service

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        supplied = Headers(scope=scope).get("x-request-id", "")
        request_id = supplied if REQUEST_ID_PATTERN.match(supplied) else new_ulid()
        scope.setdefault("state", {})["request_id"] = request_id
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        started = time.perf_counter()
        status = 500
        response_started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                status = int(message["status"])
                MutableHeaders(scope=message)["X-Request-ID"] = request_id
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:
            log.error("unhandled_exception", exc_info=exc)
            status = 500
            if not response_started:
                await internal_error_response(request_id)(scope, receive, send_wrapper)
        finally:
            elapsed = time.perf_counter() - started
            route = getattr(scope.get("route"), "path", None) or "unmatched"
            method = str(scope["method"])
            HTTP_REQUESTS.labels(self.service, route, method, str(status)).inc()
            HTTP_DURATION.labels(self.service, route, method).observe(elapsed)
            fields: dict[str, Any] = {
                "route": route,
                "method": method,
                "status": status,
                "latency_ms": round(elapsed * 1000, 2),
            }
            log.info("http_request", **fields)
            structlog.contextvars.clear_contextvars()
