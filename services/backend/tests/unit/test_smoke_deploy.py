"""Post-deploy smoke test (PRD 19.5): step order, cleanup, failure reporting, no secret output."""

from __future__ import annotations

import datetime as dt

import httpx
import pytest
from app import smoke

PASSWORD = "s3cret-demo-password"


def server(overrides: dict[str, httpx.Response] | None = None) -> httpx.MockTransport:
    responses = {
        "GET /healthz": httpx.Response(200, json={"status": "ok"}),
        "POST /api/v1/auth/login": httpx.Response(200, json={"access_token": "tok-123"}),
        "POST /api/v1/transactions": httpx.Response(201, json={"id": "t-1"}),
        "GET /api/v1/transactions/t-1": httpx.Response(200, json={"id": "t-1"}),
        "DELETE /api/v1/transactions/t-1": httpx.Response(204),
        **(overrides or {}),
    }
    calls: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        key = f"{request.method} {request.url.path}"
        calls.append(key)
        if key == "POST /api/v1/transactions":
            assert request.headers["Idempotency-Key"]
        if key.startswith(("GET /api/v1/tr", "DELETE")):
            assert request.headers["Authorization"] == "Bearer tok-123"
        return responses[key]

    transport = httpx.MockTransport(respond)
    transport.calls = calls  # type: ignore[attr-defined]
    return transport


def calls(transport: httpx.MockTransport) -> list[str]:
    return transport.calls  # type: ignore[attr-defined,no-any-return]


def test_fr_19_05_smoke_runs_health_login_create_read_delete_in_order() -> None:
    transport = server()
    smoke.run("http://x", "d@example.com", PASSWORD, transport, dt.date(2026, 11, 22))
    assert calls(transport) == [
        "GET /healthz",
        "POST /api/v1/auth/login",
        "POST /api/v1/transactions",
        "GET /api/v1/transactions/t-1",
        "DELETE /api/v1/transactions/t-1",
    ]


def test_fr_19_05_unhealthy_service_stops_before_login() -> None:
    transport = server({"GET /healthz": httpx.Response(503)})
    with pytest.raises(smoke.SmokeFailure, match="healthz: expected 200, got 503"):
        smoke.run("http://x", "d@example.com", PASSWORD, transport)
    assert calls(transport) == ["GET /healthz"]


def test_fr_19_05_missing_demo_user_is_registered_then_login_is_retried() -> None:
    logins = iter([httpx.Response(401), httpx.Response(200, json={"access_token": "tok-123"})])
    transport = server(
        {"POST /api/v1/auth/register": httpx.Response(201, json={"access_token": "x"})}
    )
    inner = transport.handler  # type: ignore[attr-defined]

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/auth/login":
            calls(transport).append("POST /api/v1/auth/login")
            return next(logins)
        return inner(request)  # type: ignore[no-any-return]

    wrapped = httpx.MockTransport(respond)
    wrapped.calls = calls(transport)  # type: ignore[attr-defined]
    smoke.run("http://x", "d@example.com", PASSWORD, wrapped)
    assert calls(wrapped)[:4] == [
        "GET /healthz",
        "POST /api/v1/auth/login",
        "POST /api/v1/auth/register",
        "POST /api/v1/auth/login",
    ]


def test_fr_19_05_failed_login_is_reported_with_status_only() -> None:
    transport = server({"POST /api/v1/auth/login": httpx.Response(500, json={"detail": PASSWORD})})
    with pytest.raises(smoke.SmokeFailure) as info:
        smoke.run("http://x", "d@example.com", PASSWORD, transport)
    assert str(info.value) == "login: expected 200, got 500"
    assert PASSWORD not in str(info.value)


def test_fr_19_05_wrong_password_for_an_existing_user_fails_at_register() -> None:
    transport = server(
        {
            "POST /api/v1/auth/login": httpx.Response(401),
            "POST /api/v1/auth/register": httpx.Response(409),
        }
    )
    with pytest.raises(smoke.SmokeFailure, match="register demo user: expected 201, got 409"):
        smoke.run("http://x", "d@example.com", PASSWORD, transport)


def test_fr_19_05_transaction_is_deleted_even_when_the_read_fails() -> None:
    transport = server({"GET /api/v1/transactions/t-1": httpx.Response(500)})
    with pytest.raises(smoke.SmokeFailure, match="read transaction"):
        smoke.run("http://x", "d@example.com", PASSWORD, transport)
    assert calls(transport)[-1] == "DELETE /api/v1/transactions/t-1"


def test_fr_19_05_connection_errors_become_smoke_failures() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(smoke.SmokeFailure, match="request failed: ConnectError"):
        smoke.run("http://x", "d@example.com", PASSWORD, httpx.MockTransport(boom))


def test_fr_19_05_unexpected_body_is_a_failure_not_a_crash() -> None:
    transport = server({"POST /api/v1/auth/login": httpx.Response(200, json={})})
    with pytest.raises(smoke.SmokeFailure, match="unexpected response body"):
        smoke.run("http://x", "d@example.com", PASSWORD, transport)


def test_fr_19_05_main_requires_url_and_password(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("SMOKE_BASE_URL", raising=False)
    monkeypatch.delenv("DEMO_USER_PASSWORD", raising=False)
    assert smoke.main([]) == 2
    assert "required" in capsys.readouterr().err


def test_fr_19_05_main_exit_codes_and_no_secret_in_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("DEMO_USER_PASSWORD", PASSWORD)
    monkeypatch.setattr(smoke, "run", lambda *a, **k: None)
    assert smoke.main(["--base-url", "http://x"]) == 0

    def fail(*a: object, **k: object) -> None:
        raise smoke.SmokeFailure("login: expected 200, got 401")

    monkeypatch.setattr(smoke, "run", fail)
    assert smoke.main(["--base-url", "http://x"]) == 1
    captured = capsys.readouterr()
    assert PASSWORD not in captured.out + captured.err
    assert "FAIL login" in captured.err
