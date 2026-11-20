"""Auth and profile request/response models (PRD 13.2). Money is a string in JSON."""

from __future__ import annotations

import datetime as dt
import re
import uuid
import zoneinfo
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.models import User

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s.]{2,}$")
MAX_OPENING_BALANCE = Decimal("1000000000000")

Password = Annotated[str, StringConstraints(max_length=1024)]  # policy checked in the service


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegisterRequest(StrictModel):
    email: str
    password: Password
    display_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)
    ]

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        email = value.strip().lower()
        if len(email) > 254 or not EMAIL_RE.match(email):
            raise ValueError("invalid email")
        return email


class LoginRequest(StrictModel):
    email: Annotated[str, StringConstraints(max_length=254)]
    password: Password


class ChangePasswordRequest(StrictModel):
    current_password: Password
    new_password: Password


class DeleteAccountRequest(StrictModel):
    password: Password
    confirm: Literal["DELETE"]


class UpdateProfileRequest(StrictModel):
    display_name: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)] | None
    ) = None
    currency: Literal["IDR"] | None = None
    timezone: str | None = None
    budget_period_start_day: Annotated[int, Field(ge=1, le=28)] | None = None
    opening_balance: Decimal | None = None
    training_consent: bool | None = None
    locale: Literal["en", "id"] | None = None

    @field_validator("timezone")
    @classmethod
    def _timezone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            zoneinfo.ZoneInfo(value)
        except (zoneinfo.ZoneInfoNotFoundError, ValueError, OSError) as exc:
            raise ValueError("unknown IANA timezone") from exc
        return value

    @field_validator("opening_balance", mode="before")
    @classmethod
    def _balance(cls, value: object) -> Decimal | None:
        if value is None:
            return None
        if isinstance(value, bool):
            raise ValueError("invalid amount")
        try:
            amount = Decimal(str(value))
        except InvalidOperation as exc:
            raise ValueError("invalid amount") from exc
        if not amount.is_finite() or abs(amount) > MAX_OPENING_BALANCE:
            raise ValueError("invalid amount")
        if amount != amount.quantize(Decimal("0.01")):
            raise ValueError("at most 2 decimal places")
        return amount


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    currency: str
    timezone: str
    locale: str
    budget_period_start_day: int
    pending_period_start_day: int | None
    pending_period_start_effective: dt.date | None
    opening_balance: str
    training_consent: bool
    is_demo: bool
    created_at: dt.datetime

    @classmethod
    def from_model(cls, user: User) -> UserOut:
        return cls(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            currency=user.currency,
            timezone=user.timezone,
            locale=user.locale,
            budget_period_start_day=user.budget_period_start_day,
            pending_period_start_day=user.pending_period_start_day,
            pending_period_start_effective=user.pending_period_start_effective,
            opening_balance=f"{user.opening_balance:.2f}",
            training_consent=user.training_consent,
            is_demo=user.is_demo,
            created_at=user.created_at,
        )


class AuthResponse(BaseModel):
    user: UserOut
    access_token: str
    expires_in: int


class TokenResponse(BaseModel):
    access_token: str
    expires_in: int
