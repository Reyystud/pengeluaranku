"""Account lifecycle: register, login, refresh rotation, logout, password, delete (FR-01)."""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ProblemError
from app.core.logging import pseudonymize
from app.core.passwords import password_problem
from app.core.periods import next_period_start
from app.core.ratelimit import RateLimiter
from app.core.security import (
    create_access_token,
    hash_password,
    hash_refresh_token,
    needs_rehash,
    new_refresh_token,
    unauthenticated,
    verify_password,
)
from app.models import DeletionRequest, RefreshToken, User
from app.models.base import utcnow
from app.repositories import RefreshTokenStore, UserRepository
from app.schemas.auth import UpdateProfileRequest

log = structlog.get_logger("auth")

LOGIN_WINDOW = 15 * 60
LOGIN_EMAIL_LIMIT = 5
LOGIN_IP_LIMIT = 20
REGISTER_WINDOW = 60 * 60
REGISTER_IP_LIMIT = 5


@dataclass(frozen=True)
class Session_:
    """Result of login/register/refresh: the access token and the raw refresh token (cookie)."""

    user: User
    access_token: str
    expires_in: int
    refresh_token: str


def _rate_limited(retry_after: int) -> ProblemError:
    return ProblemError(
        429,
        "RATE_LIMITED",
        "Too many requests",
        "Too many attempts. Try again later.",
        headers={"Retry-After": str(retry_after)},
    )


def _invalid_credentials() -> ProblemError:
    return unauthenticated("INVALID_CREDENTIALS", "Email or password is incorrect.")


def _password_error(field: str, code: str) -> ProblemError:
    messages = {
        "PASSWORD_TOO_SHORT": "Password must be at least 10 characters.",
        "PASSWORD_TOO_LONG": "Password must be at most 128 characters.",
        "PASSWORD_TOO_COMMON": "This password is too common. Choose another one.",
    }
    return ProblemError(
        422,
        "VALIDATION_ERROR",
        "Validation failed",
        "One or more fields are invalid.",
        errors=[{"field": field, "code": code, "message": messages[code]}],
    )


class AuthService:
    def __init__(
        self, session: Session, settings: Settings, limiter: RateLimiter, *, client_ip: str
    ) -> None:
        self.session = session
        self.settings = settings
        self.limiter = limiter
        self.client_ip = client_ip
        self.users = UserRepository(session)
        self.tokens = RefreshTokenStore(session)

    # -- helpers -----------------------------------------------------------------------------
    def _secret(self) -> str:
        if self.settings.jwt_secret is None:
            raise ProblemError(
                503, "SERVICE_UNAVAILABLE", "Service unavailable", "Auth is not configured."
            )
        return self.settings.jwt_secret.get_secret_value()

    def _pseudo(self, user_id: uuid.UUID) -> str:
        return pseudonymize(str(user_id), self.settings.export_pseudonym_key.get_secret_value())

    def _issue(self, user: User, family_id: uuid.UUID | None = None) -> Session_:
        family_id = family_id or uuid.uuid4()
        token, token_hash = new_refresh_token()
        now = utcnow()
        self.tokens.add(
            RefreshToken(
                user_id=user.id,
                family_id=family_id,
                token_hash=token_hash,
                expires_at=now + dt.timedelta(seconds=self.settings.refresh_token_ttl_s),
            )
        )
        access, expires_in = create_access_token(
            user.id, self._secret(), self.settings.access_token_ttl_s, session_id=family_id
        )
        return Session_(user, access, expires_in, token)

    # -- FR-01.01 / 01.02 ---------------------------------------------------------------------
    def register(self, email: str, password: str, display_name: str) -> Session_:
        key = RateLimiter.key("register-ip", self.client_ip)
        wait = self.limiter.retry_after(key, REGISTER_IP_LIMIT, REGISTER_WINDOW)
        if wait:
            raise _rate_limited(wait)
        self.limiter.record(key, REGISTER_WINDOW)

        if (code := password_problem(password)) is not None:
            raise _password_error("password", code)
        user = User(email=email, password_hash=hash_password(password), display_name=display_name)
        try:
            with self.session.begin_nested():
                self.users.add(user)
        except IntegrityError as exc:
            raise ProblemError(
                409, "CONFLICT", "Conflict", "An account with this email already exists."
            ) from exc
        result = self._issue(user)
        log.info("auth.register", user_pseudo_id=self._pseudo(user.id))
        return result

    # -- FR-01.03 / 01.10 ---------------------------------------------------------------------
    def login(self, email: str, password: str) -> Session_:
        normalized = email.strip().lower()
        email_key = RateLimiter.key("login-email", normalized)
        ip_key = RateLimiter.key("login-ip", self.client_ip)
        wait = max(
            self.limiter.retry_after(email_key, LOGIN_EMAIL_LIMIT, LOGIN_WINDOW),
            self.limiter.retry_after(ip_key, LOGIN_IP_LIMIT, LOGIN_WINDOW),
        )
        if wait:
            raise _rate_limited(wait)

        user = self.users.get_by_email(normalized)
        if not verify_password(user.password_hash if user else None, password) or user is None:
            self.limiter.record(email_key, LOGIN_WINDOW)
            self.limiter.record(ip_key, LOGIN_WINDOW)
            log.info("auth.login_failed")
            raise _invalid_credentials()

        self.limiter.reset(email_key)
        if needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)
        result = self._issue(user)
        log.info("auth.login", user_pseudo_id=self._pseudo(user.id))
        return result

    # -- FR-01.04 -----------------------------------------------------------------------------
    def refresh(self, raw_token: str | None) -> Session_:
        if not raw_token:
            raise unauthenticated()
        row = self.tokens.get_by_hash_for_update(hash_refresh_token(raw_token))
        if row is None:
            raise unauthenticated()
        now = utcnow()
        if row.revoked_at is not None:
            # An already-rotated (or logged-out) token is being replayed: kill the whole family.
            self.tokens.revoke_family(row.family_id, now)
            self.session.commit()  # persist the revocation even though this request fails
            log.warning("auth.refresh_reuse", user_pseudo_id=self._pseudo(row.user_id))
            raise unauthenticated()
        if row.expires_at <= now:
            raise unauthenticated("TOKEN_EXPIRED", "The session has expired.")
        user = self.users.get(row.user_id)
        if user is None:
            raise unauthenticated()
        result = self._issue(user, family_id=row.family_id)
        new_row = self.tokens.get_by_hash_for_update(hash_refresh_token(result.refresh_token))
        row.revoked_at = now
        row.replaced_by = new_row.id if new_row else None
        return result

    # -- FR-01.05 -----------------------------------------------------------------------------
    def logout(self, raw_token: str | None) -> None:
        if not raw_token:
            return
        row = self.tokens.get_by_hash_for_update(hash_refresh_token(raw_token))
        if row is not None:
            self.tokens.revoke_family(row.family_id, utcnow())

    # -- FR-01.07 -----------------------------------------------------------------------------
    def update_profile(self, user: User, data: UpdateProfileRequest) -> User:
        fields = data.model_dump(exclude_unset=True)
        for name in ("display_name", "timezone", "locale", "training_consent", "opening_balance"):
            if fields.get(name) is not None:
                setattr(user, name, fields[name])
        new_day = fields.get("budget_period_start_day")
        if new_day is not None:
            if new_day == user.budget_period_start_day:
                user.pending_period_start_day = None
                user.pending_period_start_effective = None
            else:
                # Applies from the next period; the current period keeps its boundaries (4.5).
                today = dt.datetime.now(ZoneInfo(user.timezone)).date()
                user.pending_period_start_day = new_day
                user.pending_period_start_effective = next_period_start(
                    today, user.budget_period_start_day
                )
        self.session.flush()
        return user

    # -- FR-01.08 -----------------------------------------------------------------------------
    def change_password(
        self,
        user: User,
        current_password: str,
        new_password: str,
        current_session: uuid.UUID | None,
    ) -> None:
        if not verify_password(user.password_hash, current_password):
            raise ProblemError(
                422,
                "VALIDATION_ERROR",
                "Validation failed",
                "One or more fields are invalid.",
                errors=[
                    {
                        "field": "current_password",
                        "code": "INVALID_CREDENTIALS",
                        "message": "Current password is incorrect.",
                    }
                ],
            )
        if (code := password_problem(new_password)) is not None:
            raise _password_error("new_password", code)
        user.password_hash = hash_password(new_password)
        # The access token's ``sid`` identifies the caller's own session; all others are revoked.
        self.tokens.revoke_all_for_user(user.id, utcnow(), except_family=current_session)
        self.session.flush()
        log.info("auth.password_changed", user_pseudo_id=self._pseudo(user.id))

    # -- FR-01.09 -----------------------------------------------------------------------------
    def delete_account(self, user: User, password: str) -> None:
        if not verify_password(user.password_hash, password):
            raise _invalid_credentials()
        pseudo = self._pseudo(user.id)
        self.session.add(DeletionRequest(user_pseudo_id=pseudo, requested_at=utcnow()))
        self.users.delete(user.id)  # ON DELETE CASCADE removes every owned row (one transaction)
        log.info("auth.account_deleted", user_pseudo_id=pseudo)
