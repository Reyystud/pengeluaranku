"""Password hashing, access tokens and refresh-token helpers (PRD 13.1.1, 17.1)."""

from __future__ import annotations

import datetime as dt
import hashlib
import secrets
import uuid
from dataclasses import dataclass

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.errors import ProblemError

# Argon2id parameters from PRD 17.1. Tune on the real host so hashing takes 200-500 ms.
_HASHER = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=1)
# Verified against when the email is unknown, so timing does not reveal account existence.
_DUMMY_HASH = _HASHER.hash("timing-equalizer-not-a-real-password")

JWT_ALGORITHM = "HS256"
CLOCK_SKEW_SECONDS = 30


def hash_password(password: str) -> str:
    return _HASHER.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    """Constant-work verify; ``None`` (unknown user) still burns one hash verification."""
    try:
        return _HASHER.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _HASHER.check_needs_rehash(password_hash)


@dataclass(frozen=True)
class AccessClaims:
    user_id: uuid.UUID
    jti: str
    expires_at: dt.datetime
    session_id: uuid.UUID | None = None  # refresh-token family of the login (``sid`` claim)


def create_access_token(
    user_id: uuid.UUID,
    secret: str,
    ttl_seconds: int,
    session_id: uuid.UUID | None = None,
    now: dt.datetime | None = None,
) -> tuple[str, int]:
    """Return ``(token, expires_in_seconds)``."""
    issued = now or dt.datetime.now(dt.UTC)
    payload = {
        "sub": str(user_id),
        "iat": issued,
        "exp": issued + dt.timedelta(seconds=ttl_seconds),
        "jti": uuid.uuid4().hex,
        "typ": "access",
    }
    if session_id is not None:
        payload["sid"] = str(session_id)
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM), ttl_seconds


def decode_access_token(token: str, secret: str) -> AccessClaims:
    """Verify signature, expiry (30 s skew), required claims and ``typ``; else ``ProblemError``."""
    try:
        data = jwt.decode(
            token,
            secret,
            algorithms=[JWT_ALGORITHM],
            leeway=CLOCK_SKEW_SECONDS,
            options={"require": ["sub", "iat", "exp", "jti", "typ"]},
        )
        if data["typ"] != "access":
            raise jwt.InvalidTokenError("wrong token type")
        return AccessClaims(
            user_id=uuid.UUID(data["sub"]),
            jti=str(data["jti"]),
            expires_at=dt.datetime.fromtimestamp(data["exp"], dt.UTC),
            session_id=uuid.UUID(data["sid"]) if "sid" in data else None,
        )
    except jwt.ExpiredSignatureError as exc:
        raise unauthenticated("TOKEN_EXPIRED", "The access token has expired.") from exc
    except (jwt.InvalidTokenError, ValueError, KeyError) as exc:
        raise unauthenticated("UNAUTHENTICATED", "Authentication required.") from exc


def unauthenticated(
    code: str = "UNAUTHENTICATED", detail: str = "Authentication required."
) -> ProblemError:
    return ProblemError(
        401, code, "Authentication required", detail, headers={"WWW-Authenticate": "Bearer"}
    )


def new_refresh_token() -> tuple[str, str]:
    """Return ``(opaque_token, sha256_hex)``. Only the hash is stored."""
    token = secrets.token_urlsafe(48)
    return token, hash_refresh_token(token)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
