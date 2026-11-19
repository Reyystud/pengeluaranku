"""Backend scaffold tests (T-11): health, request IDs, problem+json, logging rules, metrics."""

import re
from collections.abc import Callable

import pytest
import structlog
from app.core.config import Settings
from app.core.errors import ProblemError, not_found
from app.core.ids import new_ulid
from app.core.logging import (
    REDACTED,
    configure_logging,
    description_fingerprint,
    pseudonymize,
    redact_sensitive,
)
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from tests.unit.conftest import Harness

SENTINEL = "SENTINEL-DO-NOT-LOG-7f3a"
ULID = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


class Item(BaseModel):
    description: str = Field(min_length=1, max_length=40)
    amount: int = Field(gt=0)


def build_router() -> APIRouter:
    router = APIRouter()
    log = structlog.get_logger("test")

    @router.post("/echo")
    def echo(item: Item) -> dict[str, int]:
        # a careless handler: logs everything it was given
        log.info(
            "saw item",
            description=item.description,
            amount=item.amount,
            **description_fingerprint(item.description),
        )
        return {"ok": 1}

    @router.get("/items/{item_id}")
    def get_item(item_id: str) -> dict[str, str]:
        if item_id == "missing":
            raise not_found()
        return {"id": item_id}

    @router.get("/boom")
    def boom() -> None:
        raise RuntimeError(f"database exploded for {SENTINEL}")

    @router.get("/limited")
    def limited() -> None:
        raise ProblemError(429, "RATE_LIMITED", "Too many requests", headers={"Retry-After": "7"})

    @router.get("/teapot")
    def teapot() -> None:
        raise HTTPException(status_code=403)

    return router


@pytest.fixture
def h(make_harness: Callable[..., Harness]) -> Harness:
    return make_harness(build_router())


# ---- health -------------------------------------------------------------------------------


def test_healthz_has_no_dependencies(h: Harness) -> None:
    h.app.state.readiness_checks["db"] = lambda: (_ for _ in ()).throw(RuntimeError("down"))
    response = h.client.get("/healthz")
    assert response.status_code == 200 and response.json() == {"status": "ok"}


def test_readyz_ok_without_checks(h: Harness) -> None:
    response = h.client.get("/readyz")
    assert response.status_code == 200 and response.json()["status"] == "ok"


def test_readyz_reports_failed_check_as_503_without_leaking_message(h: Harness) -> None:
    def failing() -> None:
        raise ConnectionError("postgres://user:hunter2@db/sei refused")

    h.app.state.readiness_checks["db"] = failing
    response = h.client.get("/readyz")
    body = response.json()
    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")
    assert body["code"] == "SERVICE_UNAVAILABLE"
    assert body["errors"] == [{"field": "db", "code": "CHECK_FAILED", "message": "ConnectionError"}]
    assert "hunter2" not in response.text


# ---- request ids --------------------------------------------------------------------------


def test_request_id_generated_as_ulid_and_returned(h: Harness) -> None:
    response = h.client.get("/healthz")
    assert ULID.match(response.headers["X-Request-ID"])


def test_valid_request_id_is_kept(h: Harness) -> None:
    response = h.client.get("/healthz", headers={"X-Request-ID": "abc-12345678"})
    assert response.headers["X-Request-ID"] == "abc-12345678"


@pytest.mark.parametrize("bad", ["short", "has space in it 1234", "x" * 65, "bad!chars-1234"])
def test_invalid_request_id_is_replaced(h: Harness, bad: str) -> None:
    response = h.client.get("/healthz", headers={"X-Request-ID": bad})
    assert response.headers["X-Request-ID"] != bad
    assert ULID.match(response.headers["X-Request-ID"])


def test_request_id_in_error_body_matches_header(h: Harness) -> None:
    response = h.client.get("/items/missing", headers={"X-Request-ID": "req-00000001"})
    assert response.json()["request_id"] == "req-00000001" == response.headers["X-Request-ID"]


def test_ulid_is_sortable_and_well_formed() -> None:
    a, b = new_ulid(1_000), new_ulid(2_000)
    assert ULID.match(a) and a < b


# ---- problem+json -------------------------------------------------------------------------


def test_fr_not_found_for_unknown_route_is_problem_json(h: Harness) -> None:
    response = h.client.get("/nothing-here")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "NOT_FOUND"


def test_cross_user_style_not_found_has_no_hint(h: Harness) -> None:
    body = h.client.get("/items/missing").json()
    assert body["status"] == 404 and body["code"] == "NOT_FOUND"
    assert set(body) <= {"type", "title", "status", "code", "detail", "request_id"}


def test_method_not_allowed_is_problem_json(h: Harness) -> None:
    response = h.client.delete("/healthz")
    assert response.status_code == 405 and response.json()["code"] == "METHOD_NOT_ALLOWED"


def test_http_exception_maps_status_code(h: Harness) -> None:
    response = h.client.get("/teapot")
    assert response.status_code == 403 and response.json()["code"] == "FORBIDDEN"


def test_problem_error_headers_are_sent(h: Harness) -> None:
    response = h.client.get("/limited")
    assert response.status_code == 429 and response.headers["Retry-After"] == "7"
    assert response.json()["code"] == "RATE_LIMITED"


def test_validation_error_lists_fields_and_never_echoes_input(h: Harness) -> None:
    response = h.client.post("/echo", json={"description": SENTINEL + "x" * 30, "amount": -5})
    body = response.json()
    assert response.status_code == 422 and body["code"] == "VALIDATION_ERROR"
    fields = {e["field"]: e for e in body["errors"]}
    assert set(fields) == {"description", "amount"}
    assert all(e["code"] == "INVALID_VALUE" for e in fields.values())
    assert SENTINEL not in response.text


def test_missing_field_code(h: Harness) -> None:
    body = h.client.post("/echo", json={"amount": 5}).json()
    assert body["errors"] == [
        {"field": "description", "code": "FIELD_REQUIRED", "message": "Field required"}
    ]


def test_unhandled_exception_is_500_without_leaking_details(h: Harness) -> None:
    response = h.client.get("/boom")
    body = response.json()
    assert response.status_code == 500 and body["code"] == "INTERNAL_ERROR"
    assert body["request_id"] == response.headers["X-Request-ID"]
    assert "exploded" not in response.text and "Traceback" not in response.text


# ---- logging rules (PRD 17.3) --------------------------------------------------------------


def test_sentinel_never_appears_in_logs_for_a_normal_request(h: Harness) -> None:
    h.client.post(
        f"/echo?q={SENTINEL}",
        json={"description": SENTINEL, "amount": 10},
        headers={"Authorization": f"Bearer {SENTINEL}", "Cookie": f"s={SENTINEL}"},
    )
    assert SENTINEL not in h.log_text
    saw = next(e for e in h.log_events() if e.get("event") == "saw item")
    assert saw["description"] == REDACTED and saw["amount"] == REDACTED
    assert saw["description_length"] == len(SENTINEL)
    assert len(saw["description_hash"]) == 12


def test_sentinel_never_appears_in_logs_for_validation_errors(h: Harness) -> None:
    h.client.post("/echo", json={"description": SENTINEL * 2, "amount": -1})
    assert SENTINEL not in h.log_text


def test_access_log_has_route_template_not_raw_path_or_query(h: Harness) -> None:
    h.client.get(f"/items/abc123?secret={SENTINEL}")
    event = next(e for e in h.log_events() if e.get("event") == "http_request")
    assert event["route"] == "/items/{item_id}"
    assert event["method"] == "GET" and event["status"] == 200
    assert "request_id" in event and event["service"] == "backend"
    assert "abc123" not in h.log_text and SENTINEL not in h.log_text


def test_unhandled_exception_logs_stack_server_side_only(h: Harness) -> None:
    response = h.client.get("/boom")
    assert "RuntimeError" in h.log_text  # stack is logged for operators
    assert "RuntimeError" not in response.text


def test_log_lines_are_json_with_required_fields(h: Harness) -> None:
    h.client.get("/healthz")
    event = next(e for e in h.log_events() if e.get("event") == "http_request")
    assert {
        "timestamp",
        "severity",
        "service",
        "request_id",
        "route",
        "status",
        "latency_ms",
    } <= set(event)
    assert event["severity"] == "INFO"


@pytest.mark.parametrize(
    "key",
    [
        "description",
        "merchant",
        "notes",
        "amount",
        "email",
        "password",
        "token",
        "authorization",
        "cookie",
        "csv",
        "user_id",
    ],
)
def test_redaction_blanks_forbidden_keys(key: str) -> None:
    out = redact_sensitive(None, "info", {"event": "x", key: "value"})
    assert out[key] == REDACTED


def test_redaction_scrubs_tokens_and_emails_in_values_and_nested_dicts() -> None:
    event = {
        "event": "x",
        "message": "login by ani@example.com with Bearer abc.def.ghi",
        "ctx": {"email": "a@b.co", "keep": "fine"},
        "jwt": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.c2lnbmF0dXJl",
    }
    out = redact_sensitive(None, "info", dict(event))
    assert "ani@example.com" not in out["message"] and "abc.def.ghi" not in out["message"]
    assert out["ctx"] == {"email": REDACTED, "keep": "fine"}
    assert "eyJ" not in out["jwt"]


def test_pseudonymize_is_stable_keyed_and_hides_the_id() -> None:
    a = pseudonymize("user-123", "key-1")
    assert a == pseudonymize("user-123", "key-1")
    assert a != pseudonymize("user-123", "key-2") and a != pseudonymize("user-124", "key-1")
    assert len(a) == 16 and "user-123" not in a


def test_description_fingerprint_does_not_contain_text() -> None:
    fp = description_fingerprint("Kopi Kenangan")
    assert fp["description_length"] == 13 and "Kopi" not in str(fp)


def test_configure_logging_filters_by_level() -> None:
    import io

    stream = io.StringIO()
    configure_logging("WARNING", "backend", stream)
    log = structlog.get_logger("x")
    log.info("quiet")
    log.warning("loud")
    assert "loud" in stream.getvalue() and "quiet" not in stream.getvalue()


# ---- metrics ------------------------------------------------------------------------------


def test_metrics_endpoint_counts_requests_by_route_template(h: Harness) -> None:
    h.client.get("/items/1")
    h.client.get("/items/2")
    text = h.client.get("/metrics").text
    assert (
        'http_requests_total{method="GET",route="/items/{item_id}",service="backend",status="200"}'
        in text
    )
    assert "/items/1" not in text and "http_request_duration_seconds_bucket" in text


# ---- settings -----------------------------------------------------------------------------


def settings(**kw: object) -> Settings:
    return Settings(_env_file=None, **kw)  # type: ignore[arg-type]


def test_settings_defaults() -> None:
    s = settings()
    assert s.app_env == "local" and s.role == "api" and s.log_level == "INFO"
    assert s.cors_origin_list == ["http://localhost:3000"] and s.service_name == "backend"
    assert s.jwt_secret is None and s.max_transaction_amount == 1_000_000_000


def test_settings_cors_list_and_worker_role() -> None:
    s = settings(cors_origins="https://a.example, https://b.example ,", role="worker")
    assert s.cors_origin_list == ["https://a.example", "https://b.example"]
    assert s.service_name == "worker"


def test_settings_reject_short_jwt_secret() -> None:
    with pytest.raises(ValueError, match="at least 32 bytes"):
        settings(jwt_secret="too-short")
    assert settings(jwt_secret="x" * 32).jwt_secret is not None


def test_settings_secrets_never_appear_in_repr() -> None:
    s = settings(jwt_secret="y" * 40)
    assert "y" * 40 not in repr(s) and "y" * 40 not in str(s.model_dump())


def test_settings_reject_unknown_env_and_log_level() -> None:
    with pytest.raises(ValueError):
        settings(app_env="prod")
    with pytest.raises(ValueError, match="LOG_LEVEL"):
        settings(log_level="loud")
    assert settings(log_level="debug").log_level == "DEBUG"
