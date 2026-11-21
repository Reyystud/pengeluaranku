"""Events without a database (PRD 7.11, 14.3, 17.1): schemas, publisher, settings, internal auth."""

from __future__ import annotations

import base64
import json
import threading
import uuid
from typing import Any

import httpx
import pytest
from app.core.config import Settings
from app.core.internal_auth import google_token_verifier
from app.events.publisher import InMemoryPublisher, PubSubPublisher
from app.events.relay import Relay
from app.events.schema import InvalidEvent, validate_envelope
from app.main import create_app
from fastapi.testclient import TestClient

WORKER_SA = "scheduler@p.iam.gserviceaccount.com"
AUDIENCE = "https://worker.example.run.app"


def envelope(event_type: str = "transaction.created", **data: Any) -> dict[str, Any]:
    body: dict[str, Any] = (
        {"import_id": str(uuid.uuid4()), "committed_count": 3}
        if event_type == "import.committed"
        else {
            "transaction_id": str(uuid.uuid4()),
            "transaction_version": 1,
            "transaction_type": "expense",
            "source": "manual",
            "import_id": None,
        }
    )
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "schema_version": 1,
        "occurred_at": "2026-11-22T05:30:02Z",
        "request_id": None,
        "user_id": str(uuid.uuid4()),
        "data": {**body, **data},
    }


def settings(**over: Any) -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None, app_env="ci", jwt_secret="s" * 40, cookie_secure=False, **over
    )


# -- schemas (FR-11, PRD 14.3) --------------------------------------------------------------------
@pytest.mark.parametrize(
    "event_type",
    ["transaction.created", "transaction.updated", "transaction.deleted", "import.committed"],
)
def test_fr_11_01_every_event_type_has_a_schema_that_accepts_its_payload(event_type: str) -> None:
    validate_envelope(envelope(event_type))


def test_fr_11_01_updated_may_list_changed_fields() -> None:
    validate_envelope(envelope("transaction.updated", changed_fields=["amount"]))


@pytest.mark.parametrize(
    ("bad", "reason"),
    [
        (lambda e: e["data"].update(amount="25000.00"), "amount in a payload"),
        (lambda e: e["data"].update(description="KOPI"), "description in a payload"),
        (lambda e: e.update(user_id="not-a-uuid"), "bad user id"),
        (lambda e: e["data"].update(transaction_version=0), "version below 1"),
        (lambda e: e["data"].update(transaction_type="refund"), "unknown type"),
        (lambda e: e.update(schema_version=2), "unsupported version"),
        (lambda e: e.update(event_type="transaction.exploded"), "unknown event"),
        (lambda e: e.pop("event_id"), "missing event id"),
    ],
)
def test_fr_11_01_payloads_with_pii_or_wrong_shape_are_rejected(bad: Any, reason: str) -> None:
    e = envelope()
    bad(e)
    with pytest.raises(InvalidEvent):
        validate_envelope(e)


def test_fr_11_01_non_objects_are_rejected_without_echoing_values() -> None:
    for value in ("text", 3, None, []):
        with pytest.raises(InvalidEvent):
            validate_envelope(value)
    leaky = envelope()
    leaky["data"]["description"] = "SECRET-MERCHANT"
    with pytest.raises(InvalidEvent) as info:
        validate_envelope(leaky)
    assert "SECRET-MERCHANT" not in str(info.value)


# -- publisher ------------------------------------------------------------------------------------
def pubsub_transport(seen: list[httpx.Request], ids: int | None = None) -> httpx.MockTransport:
    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        count = len(json.loads(request.content)["messages"]) if ids is None else ids
        return httpx.Response(200, json={"messageIds": [str(i) for i in range(count)]})

    return httpx.MockTransport(respond)


def test_fr_11_02_publisher_posts_base64_json_with_attributes_and_a_token() -> None:
    seen: list[httpx.Request] = []
    pub = PubSubPublisher(
        "proj", "transaction-events", token_provider=lambda: "tok", transport=pubsub_transport(seen)
    )
    e = envelope("transaction.deleted")
    pub.publish([e])
    request = seen[0]
    assert str(request.url) == (
        "https://pubsub.googleapis.com/v1/projects/proj/topics/transaction-events:publish"
    )
    assert request.headers["Authorization"] == "Bearer tok"
    message = json.loads(request.content)["messages"][0]
    assert json.loads(base64.b64decode(message["data"])) == e
    assert message["attributes"] == {"event_type": "transaction.deleted", "schema_version": "1"}


def test_fr_11_06_emulator_is_used_without_credentials() -> None:
    seen: list[httpx.Request] = []

    def no_token() -> str:
        raise AssertionError("the emulator needs no credentials")

    pub = PubSubPublisher(
        "proj",
        "t",
        emulator_host="pubsub-emulator:8085",
        token_provider=no_token,
        transport=pubsub_transport(seen),
    )
    pub.publish([envelope()])
    assert str(seen[0].url).startswith("http://pubsub-emulator:8085/v1/projects/proj/topics/t:")
    assert "Authorization" not in seen[0].headers


def test_fr_11_02_publisher_raises_on_http_errors_and_partial_acks() -> None:
    failing = PubSubPublisher(
        "p",
        "t",
        token_provider=lambda: "x",
        transport=httpx.MockTransport(lambda r: httpx.Response(503)),
    )
    with pytest.raises(httpx.HTTPStatusError):
        failing.publish([envelope()])
    short = PubSubPublisher(
        "p", "t", token_provider=lambda: "x", transport=pubsub_transport([], ids=0)
    )
    with pytest.raises(RuntimeError, match="fewer messages"):
        short.publish([envelope()])


def test_fr_11_02_publishing_nothing_makes_no_request() -> None:
    seen: list[httpx.Request] = []
    PubSubPublisher("p", "t", token_provider=lambda: "x", transport=pubsub_transport(seen)).publish(
        []
    )
    assert seen == []


# -- settings -------------------------------------------------------------------------------------
def test_fr_11_06_pubsub_needs_a_project() -> None:
    with pytest.raises(ValueError, match="PUBSUB_PROJECT_ID"):
        settings(event_bus="pubsub")
    assert settings(event_bus="pubsub", pubsub_project_id="p").event_bus == "pubsub"


def test_17_1_demo_worker_refuses_to_start_without_oidc_settings() -> None:
    with pytest.raises(ValueError, match="INTERNAL_OIDC_AUDIENCE"):
        Settings(  # type: ignore[call-arg]
            _env_file=None, app_env="demo", role="worker", jwt_secret="s" * 40
        )
    ok = Settings(  # type: ignore[call-arg]
        _env_file=None,
        app_env="demo",
        role="worker",
        jwt_secret="s" * 40,
        internal_oidc_audience=AUDIENCE,
        internal_allowed_sa=f" {WORKER_SA} , b@p.iam.gserviceaccount.com,",
    )
    assert ok.allowed_service_accounts == {WORKER_SA, "b@p.iam.gserviceaccount.com"}


# -- internal auth and roles (PRD 17.1) -----------------------------------------------------------
def worker_app(verifier: Any = None, **over: Any) -> TestClient:
    app = create_app(
        settings(
            role="worker", internal_oidc_audience=AUDIENCE, internal_allowed_sa=WORKER_SA, **over
        )
    )
    if verifier is not None:
        app.state.token_verifier = verifier
    return TestClient(app, raise_server_exceptions=False)


def push(client: TestClient, headers: dict[str, str] | None = None) -> httpx.Response:
    data = base64.b64encode(json.dumps(envelope()).encode()).decode()
    return client.post(
        "/internal/events/transaction", json={"message": {"data": data}}, headers=headers or {}
    )


def test_17_1_internal_endpoint_requires_a_bearer_token() -> None:
    assert push(worker_app()).status_code == 401
    assert push(worker_app(), {"Authorization": "Basic abc"}).status_code == 401


def test_17_1_invalid_token_is_unauthenticated_without_details() -> None:
    def verifier(token: str, audience: str) -> dict[str, Any]:
        raise ValueError("Token expired: secret-detail")

    response = push(worker_app(verifier), {"Authorization": "Bearer t"})
    assert response.status_code == 401
    assert "secret-detail" not in response.text


def test_17_1_token_of_another_service_account_is_forbidden() -> None:
    def verifier(token: str, audience: str) -> dict[str, Any]:
        assert audience == AUDIENCE
        return {"email": "intruder@p.iam.gserviceaccount.com", "email_verified": True}

    assert push(worker_app(verifier), {"Authorization": "Bearer t"}).status_code == 403


def test_17_1_unverified_email_is_forbidden() -> None:
    def verifier(token: str, audience: str) -> dict[str, Any]:
        return {"email": WORKER_SA, "email_verified": False}

    assert push(worker_app(verifier), {"Authorization": "Bearer t"}).status_code == 403


def test_17_1_allowed_service_account_passes_auth() -> None:
    def verifier(token: str, audience: str) -> dict[str, Any]:
        return {"email": WORKER_SA, "email_verified": True}

    # No database is configured here, so a request that passed auth stops at the 503.
    assert push(worker_app(verifier), {"Authorization": "Bearer t"}).status_code == 503


def test_17_1_default_verifier_rejects_a_garbage_token() -> None:
    with pytest.raises(ValueError):
        google_token_verifier("not.a.jwt", AUDIENCE)


def test_6_3_roles_expose_different_routes() -> None:
    worker = worker_app()
    assert worker.get("/healthz").status_code == 200
    assert worker.post("/api/v1/auth/login", json={}).status_code == 404
    api = TestClient(create_app(settings()), raise_server_exceptions=False)
    assert api.post("/internal/events/transaction", json={}).status_code == 404
    assert "/internal/events/transaction" not in json.dumps(api.get("/openapi.json").json())


def test_6_3_internal_routes_are_not_in_the_worker_openapi_document() -> None:
    assert "/internal" not in json.dumps(worker_app().get("/openapi.json").json())


# -- relay thread ---------------------------------------------------------------------------------
def test_fr_11_02_relay_loop_backs_off_after_failures_and_stops_cleanly() -> None:
    calls: list[int] = []
    done = threading.Event()

    class Probe(Relay):
        def run_once(self) -> int:
            calls.append(len(calls))
            if len(calls) == 1:
                raise RuntimeError("bus down")
            done.set()
            return 0

    relay = Probe(None, InMemoryPublisher(), interval_s=0.01)  # type: ignore[arg-type]
    relay.start()
    assert done.wait(5), "the loop must retry after a failure"
    relay.stop()
    assert len(calls) >= 2
