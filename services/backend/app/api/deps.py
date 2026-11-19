"""FastAPI dependencies shared by routers."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.db import session_scope
from app.core.errors import ProblemError


def get_session(request: Request) -> Iterator[Session]:
    """One session per request: commit on success, roll back on error."""
    factory = getattr(request.app.state, "session_factory", None)
    if factory is None:
        raise ProblemError(
            503, "SERVICE_UNAVAILABLE", "Service unavailable", "The database is not configured."
        )
    yield from session_scope(factory)
