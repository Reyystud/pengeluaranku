"""POST /auth/register, /auth/login, /auth/refresh, /auth/logout (PRD 13.2)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Request, Response

from app.api.deps import SessionDep, SettingsDep, client_ip, get_limiter
from app.core.config import Settings
from app.core.ratelimit import RateLimiter
from app.schemas.auth import (
    AuthResponse,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserOut,
)
from app.services.auth import AuthService, Session_

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "refresh_token"
REFRESH_PATH = "/api/v1/auth"


def set_refresh_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=settings.refresh_token_ttl_s,
        path=REFRESH_PATH,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
    )


def clear_refresh_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        REFRESH_COOKIE,
        path=REFRESH_PATH,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
    )


def _service(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    limiter: Annotated[RateLimiter, Depends(get_limiter)],
) -> AuthService:
    return AuthService(session, settings, limiter, client_ip=client_ip(request))


ServiceDep = Annotated[AuthService, Depends(_service)]


def _auth_body(result: Session_) -> AuthResponse:
    return AuthResponse(
        user=UserOut.from_model(result.user),
        access_token=result.access_token,
        expires_in=result.expires_in,
    )


@router.post("/register", status_code=201, response_model=AuthResponse)
def register(
    body: RegisterRequest, response: Response, service: ServiceDep, settings: SettingsDep
) -> AuthResponse:
    result = service.register(body.email, body.password, body.display_name)
    set_refresh_cookie(response, result.refresh_token, settings)
    return _auth_body(result)


@router.post("/login", response_model=AuthResponse)
def login(
    body: LoginRequest, response: Response, service: ServiceDep, settings: SettingsDep
) -> AuthResponse:
    result = service.login(body.email, body.password)
    set_refresh_cookie(response, result.refresh_token, settings)
    return _auth_body(result)


@router.post("/refresh", response_model=TokenResponse)
def refresh(
    response: Response,
    service: ServiceDep,
    settings: SettingsDep,
    refresh_token: Annotated[str | None, Cookie()] = None,
) -> TokenResponse:
    result = service.refresh(refresh_token)
    set_refresh_cookie(response, result.refresh_token, settings)
    return TokenResponse(access_token=result.access_token, expires_in=result.expires_in)


@router.post("/logout", status_code=204)
def logout(
    service: ServiceDep,
    settings: SettingsDep,
    refresh_token: Annotated[str | None, Cookie()] = None,
) -> Response:
    service.logout(refresh_token)
    response = Response(status_code=204)
    clear_refresh_cookie(response, settings)
    return response
