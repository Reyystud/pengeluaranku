"""FastAPI application factory (PRD 13, 19.4). ``uvicorn app.main:app`` or ``python -m app``."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TextIO

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health, internal
from app.api.router import api_router
from app.clients.ml import MlClient
from app.core.config import Settings, get_settings
from app.core.db import create_session_factory, register_readiness
from app.core.errors import install_error_handlers
from app.core.internal_auth import google_token_verifier
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.core.ratelimit import RateLimiter
from app.events.publisher import EventPublisher, build_publisher
from app.events.relay import Relay

API_VERSION = "0.1.0"


def create_app(
    settings: Settings | None = None,
    log_stream: TextIO | None = None,
    publisher: EventPublisher | None = None,
) -> FastAPI:
    """``ROLE=api`` serves the public API; ``ROLE=worker`` serves only ``/internal/*`` and, with
    ``EVENT_BUS=pubsub``, runs the outbox relay in the background (PRD 6.3, 7.11)."""
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.service_name, log_stream)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        factory = app.state.session_factory
        relay: Relay | None = None
        if settings.role == "worker" and settings.event_bus == "pubsub" and factory is not None:
            relay = Relay(
                factory,
                publisher or build_publisher(settings),
                interval_s=settings.relay_interval_s,
                batch_size=settings.relay_batch_size,
            )
            relay.start()
        app.state.relay = relay
        try:
            yield
        finally:
            if relay is not None:
                relay.stop()

    app = FastAPI(
        lifespan=lifespan,
        title="Smart Expense Intelligence API",
        version=API_VERSION,
        description="Expense tracking with categorization, anomaly detection and forecasting.",
    )
    app.state.settings = settings
    app.state.readiness_checks = {}
    app.state.rate_limiter = RateLimiter()
    app.state.ml_client = MlClient(settings)
    app.state.token_verifier = google_token_verifier
    engine = register_readiness(app.state.readiness_checks, settings)
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine) if engine is not None else None
    install_error_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "Retry-After"],
    )
    app.add_middleware(RequestContextMiddleware, service=settings.service_name)
    app.include_router(health.router)
    if settings.role == "worker":
        app.include_router(internal.router)
    else:
        app.include_router(api_router)
    return app


app = create_app()
