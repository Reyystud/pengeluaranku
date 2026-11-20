"""GET/PATCH/DELETE /users/me and POST /users/me/password (PRD 13.2)."""

from __future__ import annotations

from fastapi import APIRouter, Response

from app.api.auth import ServiceDep, clear_refresh_cookie
from app.api.deps import ClaimsDep, CurrentUser, SettingsDep
from app.schemas.auth import (
    ChangePasswordRequest,
    DeleteAccountRequest,
    UpdateProfileRequest,
    UserOut,
)

router = APIRouter(prefix="/users/me", tags=["users"])


@router.get("", response_model=UserOut)
def get_me(user: CurrentUser) -> UserOut:
    return UserOut.from_model(user)


@router.patch("", response_model=UserOut)
def update_me(body: UpdateProfileRequest, user: CurrentUser, service: ServiceDep) -> UserOut:
    return UserOut.from_model(service.update_profile(user, body))


@router.post("/password", status_code=204)
def change_password(
    body: ChangePasswordRequest, user: CurrentUser, claims: ClaimsDep, service: ServiceDep
) -> Response:
    service.change_password(user, body.current_password, body.new_password, claims.session_id)
    return Response(status_code=204)


@router.delete("", status_code=204)
def delete_me(
    body: DeleteAccountRequest, user: CurrentUser, service: ServiceDep, settings: SettingsDep
) -> Response:
    service.delete_account(user, body.password)
    response = Response(status_code=204)
    clear_refresh_cookie(response, settings)
    return response
