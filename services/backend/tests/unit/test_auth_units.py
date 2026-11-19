"""Pure auth building blocks: hashing, tokens, policy, rate limiter, periods (PRD 7.1, 17.1)."""

from __future__ import annotations

import datetime as dt
import uuid

import jwt
import pytest
from app.core.errors import ProblemError
from app.core.passwords import common_passwords, password_problem
from app.core.periods import next_period_start, period_start
from app.core.ratelimit import RateLimiter
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    hash_refresh_token,
    needs_rehash,
    new_refresh_token,
    verify_password,
)
from app.schemas.auth import RegisterRequest, UpdateProfileRequest
from pydantic import ValidationError

SECRET = "k" * 40


def test_fr_01_argon2id_hash_verifies_and_never_stores_plaintext() -> None:
    h = hash_password("a long enough password")
    assert h.startswith("$argon2id$") and "a long enough password" not in h
    assert "m=65536,t=3,p=1" in h
    assert verify_password(h, "a long enough password") is True
    assert verify_password(h, "different password!") is False
    assert needs_rehash(h) is False


def test_fr_01_10_unknown_user_never_verifies() -> None:
    assert verify_password(None, "anything at all") is False
    assert verify_password("not-a-hash", "anything at all") is False


def test_13_1_1_access_token_roundtrip_and_session_claim() -> None:
    uid, sid = uuid.uuid4(), uuid.uuid4()
    token, expires_in = create_access_token(uid, SECRET, 900, session_id=sid)
    claims = decode_access_token(token, SECRET)
    assert (claims.user_id, claims.session_id, expires_in) == (uid, sid, 900)


def test_13_1_1_decode_rejects_expired_with_skew_and_wrong_type() -> None:
    uid = uuid.uuid4()
    old = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=16)
    expired, _ = create_access_token(uid, SECRET, 900, now=old)
    with pytest.raises(ProblemError) as exc:
        decode_access_token(expired, SECRET)
    assert exc.value.code == "TOKEN_EXPIRED" and exc.value.status == 401
    barely = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=15, seconds=-10)
    ok, _ = create_access_token(uid, SECRET, 900, now=barely)
    assert decode_access_token(ok, SECRET).user_id == uid
    refresh_like = jwt.encode(
        {
            "sub": str(uid),
            "iat": dt.datetime.now(dt.UTC),
            "exp": dt.datetime.now(dt.UTC) + dt.timedelta(minutes=1),
            "jti": "j",
            "typ": "refresh",
        },
        SECRET,
        algorithm="HS256",
    )
    with pytest.raises(ProblemError):
        decode_access_token(refresh_like, SECRET)


def test_fr_01_04_refresh_tokens_are_random_and_hashed() -> None:
    a, a_hash = new_refresh_token()
    b, _ = new_refresh_token()
    assert a != b and len(a) >= 64
    assert a_hash == hash_refresh_token(a) and len(a_hash) == 64 and a not in a_hash


def test_fr_01_02_password_policy_boundaries() -> None:
    assert password_problem("a" * 9) == "PASSWORD_TOO_SHORT"
    assert password_problem("a1b2c3d4e5") is None
    assert password_problem("z" * 128) is None
    assert password_problem("z" * 129) == "PASSWORD_TOO_LONG"
    common = next(p for p in sorted(common_passwords()) if len(p) >= 10)
    assert password_problem(common) == "PASSWORD_TOO_COMMON"
    assert password_problem(common.upper()) == "PASSWORD_TOO_COMMON"
    assert len(common_passwords()) > 9000


def test_fr_01_01_email_is_trimmed_lowercased_and_validated() -> None:
    ok = RegisterRequest(email="  A.B@Example.COM ", password="x", display_name=" Bu ")
    assert ok.email == "a.b@example.com" and ok.display_name == "Bu"
    for bad in ("nope", "a@b", "a b@example.com", "@example.com", "a@@example.com"):
        with pytest.raises(ValidationError):
            RegisterRequest(email=bad, password="x", display_name="n")


def test_fr_01_06_profile_schema_rejects_unknown_and_bad_values() -> None:
    assert UpdateProfileRequest(opening_balance="10.50").opening_balance is not None  # type: ignore[arg-type]
    for bad in (
        {"budget_period_start_day": 29},
        {"timezone": "Nope/Zone"},
        {"currency": "USD"},
        {"opening_balance": "1.001"},
        {"opening_balance": True},
        {"unknown": 1},
    ):
        with pytest.raises(ValidationError):
            UpdateProfileRequest(**bad)  # type: ignore[arg-type]


def test_fr_01_10_rate_limiter_window_slides_and_resets() -> None:
    now = [0.0]
    limiter = RateLimiter(clock=lambda: now[0])
    key = RateLimiter.key("login-email", "a@example.com")
    assert "a@example.com" not in key
    for _ in range(5):
        assert limiter.retry_after(key, 5, 900) == 0
        limiter.record(key, 900)
    assert 1 <= limiter.retry_after(key, 5, 900) <= 901
    now[0] = 901
    assert limiter.retry_after(key, 5, 900) == 0
    limiter.record(key, 900)
    limiter.reset(key)
    assert limiter.retry_after(key, 1, 900) == 0


@pytest.mark.parametrize(
    ("day", "start", "current", "following"),
    [
        (dt.date(2026, 11, 20), 1, dt.date(2026, 11, 1), dt.date(2026, 12, 1)),
        (dt.date(2026, 11, 20), 25, dt.date(2026, 10, 25), dt.date(2026, 11, 25)),
        (dt.date(2026, 11, 25), 25, dt.date(2026, 11, 25), dt.date(2026, 12, 25)),
        (dt.date(2026, 1, 10), 25, dt.date(2025, 12, 25), dt.date(2026, 1, 25)),
        (dt.date(2026, 12, 30), 28, dt.date(2026, 12, 28), dt.date(2027, 1, 28)),
    ],
)
def test_fr_01_07_period_boundaries(
    day: dt.date, start: int, current: dt.date, following: dt.date
) -> None:
    assert period_start(day, start) == current
    assert next_period_start(day, start) == following
