"""FastAPI dependencies shared by routers."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.db import session_scope
from app.core.errors import ProblemError
from app.core.ratelimit import RateLimiter
from app.core.security import AccessClaims, decode_access_token, unauthenticated
from app.models import User
from app.repositories import UserRepository


def get_session(request: Request) -> Iterator[Session]:
    """One session per request: commit on success, roll back on error."""
    factory = getattr(request.app.state, "session_factory", None)
    if factory is None:
        raise ProblemError(
            503, "SERVICE_UNAVAILABLE", "Service unavailable", "The database is not configured."
        )
    yield from session_scope(factory)


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_limiter(request: Request) -> RateLimiter:
    limiter: RateLimiter = request.app.state.rate_limiter
    return limiter


def client_ip(request: Request) -> str:
    # Direct peer address only: X-Forwarded-For is client-controlled unless a trusted proxy sets it.
    return request.client.host if request.client else "unknown"


SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]


def get_claims(request: Request, settings: SettingsDep) -> AccessClaims:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token or settings.jwt_secret is None:
        raise unauthenticated()
    return decode_access_token(token.strip(), settings.jwt_secret.get_secret_value())


ClaimsDep = Annotated[AccessClaims, Depends(get_claims)]


def get_current_user(claims: ClaimsDep, session: SessionDep) -> User:
    """Bearer-token auth. The user id comes from the token ``sub``, never from the request body."""
    user = UserRepository(session).get(claims.user_id)
    if user is None:
        raise unauthenticated()
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
