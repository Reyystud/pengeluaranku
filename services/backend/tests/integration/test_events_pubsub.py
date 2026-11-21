"""Outbox -> relay -> push endpoint -> idempotent consumers (PRD 7.11, 14.3), against PostgreSQL.

The "bus" is an in-memory publisher whose messages are delivered to the worker app the way
Pub/Sub push would (base64 body, at-least-once, any order, possible duplicates).
"""

from __future__ import annotations

import base64
import json
import time
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from app.core.config import Settings
from app.events.outbox import enqueue
from app.events.publisher import InMemoryPublisher
from app.events.relay import Relay, publish_pending
from app.main import create_app
from app.services.anomalies import AnomalyService
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from .conftest import API, make_user, signup


def build(engine: Engine, database_url: str, **over: Any) -> Iterator[TestClient]:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        app_env="ci",
        database_url=database_url,
        jwt_secret="s" * 40,
        cookie_secure=False,
        event_bus="pubsub",
        pubsub_project_id="p",
        **over,
    )
    app = create_app(settings, publisher=over.pop("publisher", None))
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.state.engine.dispose()


@pytest.fixture
def api(engine: Engine, database_url: str) -> Iterator[TestClient]:
    """The public API with EVENT_BUS=pubsub: no in-process draining."""
    yield from build(engine, database_url)


@pytest.fixture
def worker(engine: Engine, database_url: str) -> Iterator[TestClient]:
    yield from build(engine, database_url, role="worker")


@pytest.fixture(autouse=True)
def quiet_outbox(engine: Engine) -> Iterator[None]:
    """Other tests assert on pending events: start and leave the outbox with nothing pending."""
    park = text("UPDATE outbox_events SET published_at = now() WHERE published_at IS NULL")
    with engine.begin() as conn:
        conn.execute(park)
    yield
    with engine.begin() as conn:
        conn.execute(park)


def create_tx(api: TestClient, headers: dict[str, str], amount: str = "25000.00") -> str:
    r = api.post(
        f"{API}/transactions",
        json={
            "transaction_type": "expense",
            "amount": amount,
            "description": "Kopi pagi",
            "transaction_date": "2026-11-20",
        },
        headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


def outbox_for(engine: Engine, tx_id: str) -> dict[str, Any]:
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT id, payload, published_at FROM outbox_events WHERE aggregate_id = :a"),
            {"a": tx_id},
        ).one()
    return {"id": row.id, "payload": row.payload, "published_at": row.published_at}


def claims(engine: Engine, event_id: Any) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT consumer FROM processed_events WHERE event_id = :e"), {"e": event_id}
        )
        return {r[0] for r in rows}


def push_body(envelope: dict[str, Any]) -> dict[str, Any]:
    data = base64.b64encode(json.dumps(envelope).encode()).decode()
    return {"message": {"data": data, "messageId": "1"}, "subscription": "projects/p/s/x"}


def deliver(worker: TestClient, envelope: dict[str, Any]) -> int:
    return worker.post("/internal/events/transaction", json=push_body(envelope)).status_code


def test_fr_11_06_pubsub_mode_does_not_drain_in_process(api: TestClient, engine: Engine) -> None:
    tx_id = create_tx(api, signup(api))
    event = outbox_for(engine, tx_id)
    assert event["published_at"] is None
    assert claims(engine, event["id"]) == set()


def test_fr_11_01_event_is_written_in_the_same_transaction_as_the_change(
    api: TestClient, engine: Engine
) -> None:
    headers = signup(api)
    tx_id = create_tx(api, headers)
    assert api.delete(f"{API}/transactions/{tx_id}", headers=headers).status_code == 204
    with engine.connect() as conn:
        types = [
            r[0]
            for r in conn.execute(
                text("SELECT event_type FROM outbox_events WHERE aggregate_id = :a ORDER BY id"),
                {"a": tx_id},
            )
        ]
    assert types == ["transaction.created", "transaction.deleted"]


def test_fr_11_02_relay_publishes_pending_events_and_marks_them(session: Session) -> None:
    user = make_user(session)
    row = enqueue(
        session,
        "transaction.created",
        user_id=user.id,
        aggregate_id=uuid.uuid4(),
        request_id="r",
        data={
            "transaction_id": str(uuid.uuid4()),
            "transaction_version": 1,
            "transaction_type": "expense",
            "source": "manual",
            "import_id": None,
        },
    )
    session.flush()
    bus = InMemoryPublisher()
    assert publish_pending(session, bus, 100) >= 1
    assert row.payload in bus.published
    assert row.published_at is not None
    published = len(bus.published)
    session.flush()  # the test session has autoflush off; a commit would do this
    assert publish_pending(session, bus, 100) == 0  # nothing left: no second publication
    assert len(bus.published) == published


def test_fr_11_02_failed_publish_leaves_the_event_pending(session: Session) -> None:
    user = make_user(session)
    row = enqueue(
        session,
        "import.committed",
        user_id=user.id,
        aggregate_id=uuid.uuid4(),
        request_id=None,
        data={"import_id": str(uuid.uuid4()), "committed_count": 1},
    )
    session.flush()

    class Down:
        def publish(self, envelopes: Any) -> None:
            raise ConnectionError("bus down")

    with pytest.raises(ConnectionError):
        publish_pending(session, Down(), 100)
    assert row.published_at is None


def test_fr_11_02_batch_limit_is_respected(session: Session) -> None:
    user = make_user(session)
    for _ in range(3):
        enqueue(
            session,
            "import.committed",
            user_id=user.id,
            aggregate_id=uuid.uuid4(),
            request_id=None,
            data={"import_id": str(uuid.uuid4()), "committed_count": 1},
        )
    session.flush()
    bus = InMemoryPublisher()
    assert publish_pending(session, bus, 2) == 2


def test_fr_11_02_two_relays_never_publish_the_same_row(engine: Engine, database_url: str) -> None:
    api_user = uuid.uuid4()
    ids = [uuid.uuid4() for _ in range(4)]
    with engine.begin() as conn:
        # Only pending rows of this test matter: park everything else as published.
        conn.execute(
            text("UPDATE outbox_events SET published_at = now() WHERE published_at IS NULL")
        )
        for i, event_id in enumerate(ids):
            conn.execute(
                text(
                    "INSERT INTO outbox_events (id, event_type, aggregate_id, user_id, payload, created_at) "
                    "VALUES (:i, 'import.committed', :a, :u, CAST(:p AS jsonb), now())"
                ),
                {
                    "i": event_id,
                    "a": uuid.uuid4(),
                    "u": api_user,
                    "p": json.dumps({"event_id": str(event_id), "n": i}),
                },
            )
    first, second = sessionmaker(engine)(), sessionmaker(engine)()
    try:
        a, b = InMemoryPublisher(), InMemoryPublisher()
        assert publish_pending(first, a, 2) == 2  # holds its two rows, not committed yet
        assert publish_pending(second, b, 10) == 2  # skips the locked ones
        seen = {e["event_id"] for e in a.published} | {e["event_id"] for e in b.published}
        assert seen == {str(i) for i in ids}
        assert not ({e["event_id"] for e in a.published} & {e["event_id"] for e in b.published})
    finally:
        first.rollback()
        second.rollback()
        first.close()
        second.close()
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM outbox_events WHERE id = ANY(:ids)"), {"ids": ids})


def test_fr_11_03_push_delivers_to_both_consumers_once_even_when_duplicated(
    api: TestClient, worker: TestClient, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    tx_id = create_tx(api, signup(api))
    event = outbox_for(engine, tx_id)
    scored: list[uuid.UUID] = []
    real = AnomalyService.score_transaction

    def spy(self: AnomalyService, transaction_id: uuid.UUID) -> int:
        scored.append(transaction_id)
        return real(self, transaction_id)

    monkeypatch.setattr(AnomalyService, "score_transaction", spy)
    assert deliver(worker, event["payload"]) == 204
    assert claims(engine, event["id"]) == {"anomaly-scorer", "recurring-updater"}
    assert deliver(worker, event["payload"]) == 204  # at-least-once: the same message again
    assert deliver(worker, event["payload"]) == 204
    assert len(scored) == 1


def test_fr_11_04_event_older_than_the_stored_version_is_ignored(
    api: TestClient, worker: TestClient, engine: Engine
) -> None:
    tx_id = create_tx(api, signup(api))
    event = outbox_for(engine, tx_id)
    with engine.begin() as conn:
        conn.execute(text("UPDATE transactions SET version = 2 WHERE id = :i"), {"i": tx_id})
    assert deliver(worker, event["payload"]) == 204
    assert claims(engine, event["id"]) == set()  # acknowledged without any consumer running


def test_fr_11_04_out_of_order_delivery_ends_in_the_same_state(
    api: TestClient, worker: TestClient, engine: Engine
) -> None:
    headers = signup(api)
    tx_id = create_tx(api, headers)
    assert api.delete(f"{API}/transactions/{tx_id}", headers=headers).status_code == 204
    with engine.connect() as conn:
        payloads = [
            r[0]
            for r in conn.execute(
                text("SELECT payload FROM outbox_events WHERE aggregate_id = :a ORDER BY id DESC"),
                {"a": tx_id},
            )
        ]
    assert [p["event_type"] for p in payloads] == ["transaction.deleted", "transaction.created"]
    assert [deliver(worker, p) for p in payloads] == [204, 204]  # deleted first, then created


def test_fr_11_05_failing_consumer_returns_5xx_and_leaves_no_claims_so_the_retry_works(
    api: TestClient, worker: TestClient, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    tx_id = create_tx(api, signup(api))
    event = outbox_for(engine, tx_id)
    real = AnomalyService.score_transaction

    def boom(self: AnomalyService, transaction_id: uuid.UUID) -> int:
        raise RuntimeError("scorer exploded")

    monkeypatch.setattr(AnomalyService, "score_transaction", boom)
    assert (
        deliver(worker, event["payload"]) == 500
    )  # not an ack: Pub/Sub retries, then dead-letters
    assert claims(engine, event["id"]) == set()
    monkeypatch.setattr(AnomalyService, "score_transaction", real)
    assert deliver(worker, event["payload"]) == 204  # the retry succeeds
    assert claims(engine, event["id"]) == {"anomaly-scorer", "recurring-updater"}


def test_fr_11_05_malformed_messages_are_not_acknowledged(worker: TestClient) -> None:
    for body in (
        {"message": {"data": "%%%not-base64%%%"}},
        {"message": {"data": base64.b64encode(b"not json").decode()}},
        {"message": {"data": base64.b64encode(b'{"event_type": "x"}').decode()}},
    ):
        response = worker.post("/internal/events/transaction", json=body)
        assert response.status_code == 400, body
        assert response.json()["code"] == "INVALID_EVENT"
    assert worker.post("/internal/events/transaction", json={}).status_code == 422


def test_fr_11_05_event_of_a_deleted_user_is_acknowledged(worker: TestClient) -> None:
    ghost = {
        "event_id": str(uuid.uuid4()),
        "event_type": "transaction.created",
        "schema_version": 1,
        "occurred_at": "2026-11-22T05:30:02Z",
        "request_id": None,
        "user_id": str(uuid.uuid4()),
        "data": {
            "transaction_id": str(uuid.uuid4()),
            "transaction_version": 1,
            "transaction_type": "expense",
            "source": "manual",
            "import_id": None,
        },
    }
    assert deliver(worker, ghost) == 204


def test_fr_11_02_relay_thread_in_the_worker_publishes_pending_events(
    api: TestClient, engine: Engine, database_url: str
) -> None:
    tx_id = create_tx(api, signup(api))
    assert outbox_for(engine, tx_id)["published_at"] is None
    bus = InMemoryPublisher()
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        app_env="ci",
        database_url=database_url,
        jwt_secret="s" * 40,
        event_bus="pubsub",
        pubsub_project_id="p",
        role="worker",
        relay_interval_s=0.05,
    )
    app = create_app(settings, publisher=bus)
    with TestClient(app):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and outbox_for(engine, tx_id)["published_at"] is None:
            time.sleep(0.05)
        assert isinstance(app.state.relay, Relay)
    assert outbox_for(engine, tx_id)["published_at"] is not None
    assert any(e["data"].get("transaction_id") == tx_id for e in bus.published)
    app.state.engine.dispose()


def test_fr_11_01_end_to_end_relay_then_push_scores_the_transaction(
    api: TestClient, worker: TestClient, engine: Engine, database_url: str
) -> None:
    tx_id = create_tx(api, signup(api))
    event = outbox_for(engine, tx_id)
    assert claims(engine, event["id"]) == set()
    bus = InMemoryPublisher()
    Relay(
        sessionmaker(engine),
        bus,
        batch_size=1000,
    ).run_once()
    mine = [e for e in bus.published if e["data"].get("transaction_id") == tx_id]
    assert len(mine) == 1
    assert all(deliver(worker, e) == 204 for e in bus.published)  # everything pending, in order
    assert claims(engine, event["id"]) == {"anomaly-scorer", "recurring-updater"}
