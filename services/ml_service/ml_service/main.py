"""ML inference service (PRD 14). Stateless: no database, no user data persisted or logged."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ml_service.api import classify, health, models
from ml_service.config import Settings
from ml_service.errors import install_handlers
from ml_service.loading.registry import ModelRegistry
from ml_service.metrics import HTTP_DURATION, HTTP_REQUESTS

log = logging.getLogger("ml_service")


class RequestMiddleware:
    """Request id, metrics by route template, and a log line without paths' query or bodies."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope["headers"])
        request_id = headers.get(b"x-request-id", b"").decode()[:64] or uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        started, status = time.perf_counter(), 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message["headers"] = [*message["headers"], (b"x-request-id", request_id.encode())]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            route = getattr(scope.get("route"), "path", "unmatched")
            elapsed = time.perf_counter() - started
            HTTP_REQUESTS.labels(scope["method"], route, str(status)).inc()
            HTTP_DURATION.labels(scope["method"], route).observe(elapsed)
            log.info(
                "request",
                extra={
                    "route": route,
                    "method": scope["method"],
                    "status": status,
                    "ms": round(elapsed * 1000, 2),
                    "request_id": request_id,
                },
            )


async def poll_models(registry: ModelRegistry, interval_s: float) -> None:
    """Check the alias every ``interval_s``; loading runs in a thread, off the event loop."""
    while True:
        await asyncio.sleep(interval_s)
        try:
            if await asyncio.to_thread(registry.refresh):
                log.info("model swapped")
        except Exception:  # the loop must survive anything; the old model keeps serving
            log.exception("model poll failed")


def create_app(settings: Settings | None = None, registry: ModelRegistry | None = None) -> FastAPI:
    settings = settings or Settings()
    if settings.ml_auth != "none":
        # Google ID token verification belongs with the Cloud Run deployment task (PRD 14.1).
        raise RuntimeError("ML_AUTH=google_id_token is not implemented yet; use ML_AUTH=none")
    registry = registry or ModelRegistry(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        registry.load()  # a failed load leaves /readyz at 503; the process stays up
        poller = (
            asyncio.create_task(poll_models(registry, settings.model_poll_interval_s))
            if settings.model_poll_interval_s > 0
            else None
        )
        try:
            yield
        finally:
            if poller is not None:
                poller.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await poller

    app = FastAPI(title="Smart Expense ML service", version="0.0.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.registry = registry
    install_handlers(app)
    app.add_middleware(RequestMiddleware)
    app.include_router(health.router)
    app.include_router(classify.router)
    app.include_router(models.router)

    return app
