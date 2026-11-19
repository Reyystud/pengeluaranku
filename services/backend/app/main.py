"""FastAPI application factory (PRD 13, 19.4). ``uvicorn app.main:app`` or ``python -m app``."""

from __future__ import annotations

from typing import TextIO

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health
from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware

API_VERSION = "0.1.0"


def create_app(settings: Settings | None = None, log_stream: TextIO | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.service_name, log_stream)

    app = FastAPI(
        title="Smart Expense Intelligence API",
        version=API_VERSION,
        description="Expense tracking with categorization, anomaly detection and forecasting.",
    )
    app.state.settings = settings
    app.state.readiness_checks = {}
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
    app.include_router(api_router)
    return app


app = create_app()
