"""FR-01 auth and account lifecycle against real PostgreSQL (PRD 7.1, 13.1.1, 17.1)."""

from __future__ import annotations

import datetime as dt
import io
import uuid
from collections.abc import Iterator

import jwt
import pytest
from app.core.config import Settings
from app.core.passwords import common_passwords
from app.main import create_app
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

pytestmark = pytest.mark.integration

SECRET = "s" * 40
PASSWORD = "correct horse battery"
API = "/api/v1"


def _settings(database_url: str, **kw: object) -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        app_env="ci",
        database_url=database_url,
        jwt_secret=SECRET,
        cookie_secure=False,
        **kw,
    )


@pytest.fixture
def log_stream() -> io.StringIO:
    return io.StringIO()


@pytest.fixture
def client(engine: Engine, database_url: str, log_stream: io.StringIO) -> Iterator[TestClient]:
    """Fresh app (and rate limiter) per test; DB schema is shared, emails are unique per test."""
    app = create_app(_settings(database_url), log_stream=log_stream)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.state.engine.dispose()


def email() -> str:
    return f"user-{uuid.uuid4().hex[:10]}@Example.com"


def register(client: TestClient, addr: str | None = None, password: str = PASSWORD) -> dict:  # type: ignore[type-arg]
    r = client.post(
        f"{API}/auth/register",
        json={"email": addr or email(), "password": password, "display_name": "Tester"},
    )
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_fr_01_01_register_normalizes_email_and_hides_secrets(client: TestClient) -> None:
    body = register(client, "  MiXed.Case@Example.COM ")
    assert body["user"]["email"] == "mixed.case@example.com"
    assert body["expires_in"] == 900
    assert "password" not in str(body).lower().replace("password_", "")
    assert body["user"]["currency"] == "IDR" and body["user"]["timezone"] == "Asia/Jakarta"
    assert body["user"]["opening_balance"] == "0.00"
    assert "password_hash" not in body["user"]


def test_fr_01_01_duplicate_email_is_case_insensitive(client: TestClient) -> None:
    register(client, "dupe@example.com")
    r = client.post(
        f"{API}/auth/register",
        json={"email": "DUPE@example.com", "password": PASSWORD, "display_name": "x"},
    )
    assert r.status_code == 409 and r.json()["code"] == "CONFLICT"


@pytest.mark.parametrize(
    ("password", "code"),
    [
        ("short", "PASSWORD_TOO_SHORT"),
        ("x" * 129, "PASSWORD_TOO_LONG"),
        (next(p for p in sorted(common_passwords()) if len(p) >= 10), "PASSWORD_TOO_COMMON"),
    ],
)
def test_fr_01_02_password_policy(client: TestClient, password: str, code: str) -> None:
    r = client.post(
        f"{API}/auth/register",
        json={"email": email(), "password": password, "display_name": "x"},
    )
    assert r.status_code == 422
    assert r.json()["errors"][0]["code"] == code
    assert password not in r.text


def test_fr_01_02_boundary_lengths_are_accepted(client: TestClient) -> None:
    register(client, password="a1b2c3d4e5")  # exactly 10
    register(client, password="q" * 64 + "Z9" * 32)  # exactly 128


def test_fr_01_03_register_sets_hardened_refresh_cookie(engine: Engine, database_url: str) -> None:
    app = create_app(
        Settings(_env_file=None, app_env="ci", database_url=database_url, jwt_secret=SECRET)  # type: ignore[call-arg]
    )
    with TestClient(app) as c:
        r = c.post(
            f"{API}/auth/register",
            json={"email": email(), "password": PASSWORD, "display_name": "x"},
        )
    cookie = r.headers["set-cookie"].lower()
    assert "refresh_token=" in cookie and "httponly" in cookie and "secure" in cookie
    assert "samesite=strict" in cookie and "path=/api/v1/auth" in cookie
    assert f"max-age={30 * 86400}" in cookie
    app.state.engine.dispose()


def test_fr_01_03_access_token_claims(client: TestClient) -> None:
    token = register(client)["access_token"]
    claims = jwt.decode(token, SECRET, algorithms=["HS256"])
    assert claims["typ"] == "access" and claims["exp"] - claims["iat"] == 900
    assert uuid.UUID(claims["sub"]) and claims["jti"]


def test_fr_01_03_refresh_token_is_stored_only_as_sha256(
    client: TestClient, engine: Engine
) -> None:
    register(client)
    raw = client.cookies.get("refresh_token")
    assert raw
    with engine.connect() as conn:
        hashes = [r[0] for r in conn.execute(text("SELECT token_hash FROM refresh_tokens"))]
    assert raw not in hashes and all(len(h) == 64 for h in hashes)


def test_fr_01_10_wrong_password_and_unknown_email_look_identical(client: TestClient) -> None:
    addr = email()
    register(client, addr)
    wrong = client.post(f"{API}/auth/login", json={"email": addr, "password": "nope-nope-nope"})
    unknown = client.post(
        f"{API}/auth/login", json={"email": email(), "password": "nope-nope-nope"}
    )
    assert wrong.status_code == unknown.status_code == 401
    for key in ("code", "title", "detail", "status", "type"):
        assert wrong.json()[key] == unknown.json()[key]
    assert wrong.json()["code"] == "INVALID_CREDENTIALS"


def test_fr_01_10_login_blocks_after_5_failures_per_email(client: TestClient) -> None:
    addr = email()
    register(client, addr)
    for _ in range(5):
        assert (
            client.post(f"{API}/auth/login", json={"email": addr, "password": "bad-bad-bad"})
        ).status_code == 401
    blocked = client.post(f"{API}/auth/login", json={"email": addr, "password": PASSWORD})
    assert blocked.status_code == 429 and blocked.json()["code"] == "RATE_LIMITED"
    assert int(blocked.headers["Retry-After"]) > 0


def test_fr_01_10_unknown_emails_are_rate_limited_too(client: TestClient) -> None:
    addr = email()  # never registered: counting must not reveal that
    for _ in range(5):
        client.post(f"{API}/auth/login", json={"email": addr, "password": "bad-bad-bad"})
    assert (
        client.post(f"{API}/auth/login", json={"email": addr, "password": "x"}).status_code == 429
    )


def test_fr_01_10_login_blocks_after_20_failures_per_ip(client: TestClient) -> None:
    for _ in range(20):
        assert (
            client.post(f"{API}/auth/login", json={"email": email(), "password": "bad-bad-bad"})
        ).status_code == 401
    r = client.post(f"{API}/auth/login", json={"email": email(), "password": "bad-bad-bad"})
    assert r.status_code == 429 and "Retry-After" in r.headers


def test_fr_01_10_successful_login_resets_email_counter(client: TestClient) -> None:
    addr = email()
    register(client, addr)
    for _ in range(4):
        client.post(f"{API}/auth/login", json={"email": addr, "password": "bad-bad-bad"})
    assert (
        client.post(f"{API}/auth/login", json={"email": addr, "password": PASSWORD}).status_code
        == 200
    )
    for _ in range(4):
        client.post(f"{API}/auth/login", json={"email": addr, "password": "bad-bad-bad"})
    assert (
        client.post(f"{API}/auth/login", json={"email": addr, "password": PASSWORD}).status_code
        == 200
    )


def test_register_is_limited_to_5_per_hour_per_ip(client: TestClient) -> None:
    for _ in range(5):
        register(client)
    r = client.post(
        f"{API}/auth/register",
        json={"email": email(), "password": PASSWORD, "display_name": "x"},
    )
    assert r.status_code == 429 and "Retry-After" in r.headers


def test_fr_01_04_refresh_rotates_and_reuse_revokes_family(client: TestClient) -> None:
    addr = email()
    register(client, addr)
    first = client.cookies.get("refresh_token")
    r = client.post(f"{API}/auth/refresh")
    assert r.status_code == 200 and r.json()["access_token"]
    second = client.cookies.get("refresh_token")
    assert second and second != first

    # Replay the rotated-out token: 401 and the whole family dies, including the newest token.
    client.cookies.clear()
    client.cookies.set("refresh_token", first, path=f"{API}/auth")
    assert client.post(f"{API}/auth/refresh").status_code == 401
    client.cookies.clear()
    client.cookies.set("refresh_token", second, path=f"{API}/auth")
    assert client.post(f"{API}/auth/refresh").status_code == 401


def test_fr_01_04_other_login_sessions_survive_reuse_of_one_family(client: TestClient) -> None:
    addr = email()
    register(client, addr)
    a_old = client.cookies.get("refresh_token")
    client.post(f"{API}/auth/refresh")  # rotates family A
    client.cookies.clear()
    client.post(f"{API}/auth/login", json={"email": addr, "password": PASSWORD})  # family B
    b = client.cookies.get("refresh_token")
    client.cookies.clear()
    client.cookies.set("refresh_token", a_old, path=f"{API}/auth")
    assert client.post(f"{API}/auth/refresh").status_code == 401  # reuse of A
    client.cookies.clear()
    client.cookies.set("refresh_token", b, path=f"{API}/auth")
    assert client.post(f"{API}/auth/refresh").status_code == 200  # B untouched


def test_fr_01_04_missing_unknown_and_expired_refresh_tokens(
    client: TestClient, engine: Engine
) -> None:
    assert client.post(f"{API}/auth/refresh").status_code == 401
    client.cookies.set("refresh_token", "not-a-real-token", path=f"{API}/auth")
    assert client.post(f"{API}/auth/refresh").status_code == 401
    register(client)
    with engine.begin() as conn:
        conn.execute(text("UPDATE refresh_tokens SET expires_at = now() - interval '1 minute'"))
    r = client.post(f"{API}/auth/refresh")
    assert r.status_code == 401 and r.json()["code"] == "TOKEN_EXPIRED"


def test_fr_01_05_logout_revokes_family_and_clears_cookie(client: TestClient) -> None:
    register(client)
    token = client.cookies.get("refresh_token")
    r = client.post(f"{API}/auth/logout")
    assert r.status_code == 204
    assert (
        "refresh_token=" in r.headers["set-cookie"]
        and "max-age=0" in r.headers["set-cookie"].lower()
    )
    client.cookies.set("refresh_token", token, path=f"{API}/auth")
    assert client.post(f"{API}/auth/refresh").status_code == 401


def test_fr_01_05_logout_without_cookie_is_idempotent(client: TestClient) -> None:
    assert client.post(f"{API}/auth/logout").status_code == 204


def test_13_1_1_protected_endpoints_reject_bad_tokens(client: TestClient) -> None:
    good = register(client)["access_token"]
    assert client.get(f"{API}/users/me").status_code == 401
    assert client.get(f"{API}/users/me", headers={"Authorization": "Basic abc"}).status_code == 401
    assert client.get(f"{API}/users/me", headers=bearer("garbage")).status_code == 401
    assert client.get(f"{API}/users/me", headers=bearer(good + "x")).status_code == 401
    assert client.get(f"{API}/users/me", headers=bearer(good)).status_code == 200
    r = client.get(f"{API}/users/me")
    assert r.headers["www-authenticate"] == "Bearer" and r.json()["code"] == "UNAUTHENTICATED"


def _token(sub: str, **override: object) -> str:
    now = dt.datetime.now(dt.UTC)
    claims: dict[str, object] = {
        "sub": sub,
        "iat": now,
        "exp": now + dt.timedelta(minutes=5),
        "jti": "j",
        "typ": "access",
    }
    claims.update(override)
    return jwt.encode({k: v for k, v in claims.items() if v is not None}, SECRET, algorithm="HS256")


def test_13_1_1_expired_wrong_type_and_missing_claims_are_rejected(client: TestClient) -> None:
    sub = register(client)["user"]["id"]
    now = dt.datetime.now(dt.UTC)
    expired = _token(sub, exp=now - dt.timedelta(minutes=2))
    r = client.get(f"{API}/users/me", headers=bearer(expired))
    assert r.status_code == 401 and r.json()["code"] == "TOKEN_EXPIRED"
    # Inside the 30 s clock-skew tolerance the token still works.
    assert (
        client.get(
            f"{API}/users/me", headers=bearer(_token(sub, exp=now - dt.timedelta(seconds=10)))
        ).status_code
        == 200
    )
    assert (
        client.get(f"{API}/users/me", headers=bearer(_token(sub, typ="refresh"))).status_code == 401
    )
    assert client.get(f"{API}/users/me", headers=bearer(_token(sub, jti=None))).status_code == 401
    assert client.get(f"{API}/users/me", headers=bearer(_token("not-a-uuid"))).status_code == 401
    assert (
        client.get(f"{API}/users/me", headers=bearer(_token(str(uuid.uuid4())))).status_code == 401
    )
    forged = jwt.encode(
        {"sub": sub, "exp": now + dt.timedelta(minutes=5)}, "other" * 10, algorithm="HS256"
    )
    assert client.get(f"{API}/users/me", headers=bearer(forged)).status_code == 401
    none_alg = jwt.encode(
        {"sub": sub, "iat": now, "exp": now + dt.timedelta(minutes=5), "jti": "j", "typ": "access"},
        None,
        algorithm="none",
    )
    assert client.get(f"{API}/users/me", headers=bearer(none_alg)).status_code == 401


def test_fr_01_06_profile_update_and_validation(client: TestClient) -> None:
    token = register(client)["access_token"]
    h = bearer(token)
    r = client.patch(
        f"{API}/users/me",
        headers=h,
        json={
            "display_name": "  Budi  ",
            "timezone": "Asia/Makassar",
            "opening_balance": "1500000.50",
            "training_consent": True,
            "locale": "id",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["display_name"] == "Budi" and body["timezone"] == "Asia/Makassar"
    assert body["opening_balance"] == "1500000.50" and body["training_consent"] is True
    assert client.get(f"{API}/users/me", headers=h).json()["locale"] == "id"
    for bad in (
        {"timezone": "Mars/Phobos"},
        {"budget_period_start_day": 29},
        {"budget_period_start_day": 0},
        {"currency": "USD"},
        {"locale": "fr"},
        {"opening_balance": "1.234"},
        {"opening_balance": "abc"},
        {"display_name": ""},
        {"email": "new@example.com"},  # not an updatable field
        {"is_demo": True},
    ):
        assert client.patch(f"{API}/users/me", headers=h, json=bad).status_code == 422, bad


def test_fr_01_07_period_start_day_change_applies_from_next_period(client: TestClient) -> None:
    h = bearer(register(client)["access_token"])
    r = client.patch(f"{API}/users/me", headers=h, json={"budget_period_start_day": 25})
    body = r.json()
    assert body["budget_period_start_day"] == 1  # current period keeps its boundaries
    assert body["pending_period_start_day"] == 25
    effective = dt.date.fromisoformat(body["pending_period_start_effective"])
    assert effective.day == 1 and effective > dt.date.today() - dt.timedelta(days=1)
    back = client.patch(f"{API}/users/me", headers=h, json={"budget_period_start_day": 1}).json()
    assert back["pending_period_start_day"] is None


def test_fr_01_08_change_password_revokes_other_sessions_only(client: TestClient) -> None:
    addr = email()
    a = register(client, addr)
    a_cookie = client.cookies.get("refresh_token")
    client.cookies.clear()
    client.post(f"{API}/auth/login", json={"email": addr, "password": PASSWORD})
    b_cookie = client.cookies.get("refresh_token")

    new_pw = "another long passphrase"
    r = client.post(
        f"{API}/users/me/password",
        headers=bearer(a["access_token"]),
        json={"current_password": PASSWORD, "new_password": new_pw},
    )
    assert r.status_code == 204
    client.cookies.clear()
    client.cookies.set("refresh_token", b_cookie, path=f"{API}/auth")
    assert client.post(f"{API}/auth/refresh").status_code == 401  # other session revoked
    client.cookies.clear()
    client.cookies.set("refresh_token", a_cookie, path=f"{API}/auth")
    assert client.post(f"{API}/auth/refresh").status_code == 200  # current session kept
    assert (
        client.post(f"{API}/auth/login", json={"email": addr, "password": PASSWORD}).status_code
        == 401
    )
    assert (
        client.post(f"{API}/auth/login", json={"email": addr, "password": new_pw}).status_code
        == 200
    )


def test_fr_01_08_change_password_validates_current_and_new(client: TestClient) -> None:
    h = bearer(register(client)["access_token"])
    wrong = client.post(
        f"{API}/users/me/password",
        headers=h,
        json={"current_password": "wrong-wrong", "new_password": "another long passphrase"},
    )
    assert wrong.status_code == 422 and wrong.json()["errors"][0]["field"] == "current_password"
    weak = client.post(
        f"{API}/users/me/password",
        headers=h,
        json={"current_password": PASSWORD, "new_password": "short"},
    )
    assert weak.status_code == 422 and weak.json()["errors"][0]["code"] == "PASSWORD_TOO_SHORT"


def test_fr_01_09_delete_account_cascades_and_leaves_only_a_tombstone(
    client: TestClient, engine: Engine
) -> None:
    body = register(client)
    uid = body["user"]["id"]
    h = bearer(body["access_token"])
    with engine.begin() as conn:
        cat = conn.execute(text("SELECT id FROM categories WHERE slug = 'groceries'")).scalar_one()
        conn.execute(
            text(
                "INSERT INTO transactions (id, user_id, transaction_type, amount, description,"
                " transaction_date, category_id, category_status, source, created_at, updated_at)"
                " VALUES (:id, :u, 'expense', 10.00, 'x', now(), :c, 'auto', 'manual',"
                " now(), now())"
            ),
            {"id": uuid.uuid4(), "u": uid, "c": cat},
        )
        conn.execute(
            text(
                "INSERT INTO budgets (id, user_id, limit_amount, created_at, updated_at)"
                " VALUES (:id, :u, 5.00, now(), now())"
            ),
            {"id": uuid.uuid4(), "u": uid},
        )

    assert (
        client.request(
            "DELETE",
            f"{API}/users/me",
            headers=h,
            json={"password": "bad-bad-bad", "confirm": "DELETE"},
        ).status_code
        == 401
    )
    assert (
        client.request(
            "DELETE", f"{API}/users/me", headers=h, json={"password": PASSWORD, "confirm": "delete"}
        ).status_code
        == 422
    )
    assert (
        client.request(
            "DELETE", f"{API}/users/me", headers=h, json={"password": PASSWORD}
        ).status_code
        == 422
    )
    r = client.request(
        "DELETE", f"{API}/users/me", headers=h, json={"password": PASSWORD, "confirm": "DELETE"}
    )
    assert r.status_code == 204
    assert "max-age=0" in r.headers["set-cookie"].lower()

    with engine.connect() as conn:
        for table in ("users", "transactions", "budgets", "refresh_tokens"):
            col = "id" if table == "users" else "user_id"
            n = conn.execute(
                text(f"SELECT count(*) FROM {table} WHERE {col} = :u"), {"u": uid}
            ).scalar_one()
            assert n == 0, table
        tomb = conn.execute(
            text("SELECT user_pseudo_id, requested_at, purged_at FROM deletion_requests")
        ).all()
    assert len(tomb) >= 1 and all(uid not in t[0] and len(t[0]) == 16 for t in tomb)
    assert (
        client.get(f"{API}/users/me", headers=h).status_code == 401
    )  # token no longer maps to a user


def test_17_3_logs_never_contain_email_password_or_tokens(
    client: TestClient, log_stream: io.StringIO
) -> None:
    addr = f"sentinel-{uuid.uuid4().hex[:8]}@example.com"
    secret_pw = "SENTINEL-password-value-123"
    body = register(client, addr, password=secret_pw)
    refresh_cookie = client.cookies.get("refresh_token") or "missing"
    client.post(f"{API}/auth/login", json={"email": addr, "password": "wrong-wrong-wrong"})
    client.post(f"{API}/auth/login", json={"email": addr, "password": secret_pw})
    client.post(f"{API}/auth/refresh")
    logs = log_stream.getvalue()
    assert logs, "expected log output"
    for forbidden in (
        addr,
        addr.split("@")[0],
        secret_pw,
        "wrong-wrong-wrong",
        body["access_token"],
        refresh_cookie,
        body["user"]["id"],
    ):
        assert forbidden not in logs, forbidden


def test_auth_unavailable_without_jwt_secret(engine: Engine, database_url: str) -> None:
    app = create_app(
        Settings(_env_file=None, app_env="ci", database_url=database_url)  # type: ignore[call-arg]
    )
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.post(
            f"{API}/auth/register",
            json={"email": email(), "password": PASSWORD, "display_name": "x"},
        )
    assert r.status_code == 503
    app.state.engine.dispose()
