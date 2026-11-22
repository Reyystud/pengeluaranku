"""Batch jobs (PRD 15, 12.3): runner behaviour and each job in the catalogue."""

from __future__ import annotations

import dataclasses
import datetime as dt
import uuid
from collections.abc import Iterator
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from app.core.config import Settings
from app.core.metrics import JOB_RUNS
from app.jobs.catalogue import JOBS
from app.jobs.framework import JobContext, JobSpec, run_job
from app.main import create_app
from app.models import User
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from tests.integration.conftest import API, signup
from tests.integration.ledger_support import seed_transactions
from tests.integration.test_categorization_api import FakeMl, install

pytestmark = pytest.mark.integration

JKT = ZoneInfo("Asia/Jakarta")
NOW = dt.datetime(2026, 11, 20, 5, 0, tzinfo=dt.UTC)  # Friday 12:00 Jakarta, period Nov 1-30


def at(month: int, day: int, hour: int = 10) -> dt.datetime:
    return dt.datetime(2026, month, day, hour, tzinfo=JKT)


@pytest.fixture
def factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
def me(client: TestClient) -> tuple[uuid.UUID, dict[str, str]]:
    headers = signup(client)
    return uuid.UUID(client.get(f"{API}/users/me", headers=headers).json()["id"]), headers


def settings_of(client: TestClient) -> Settings:
    return client.app.state.settings  # type: ignore[attr-defined,no-any-return]


def only(spec: JobSpec, user_id: uuid.UUID) -> JobSpec:
    """The same job restricted to one user, so rows other tests left behind do not interfere."""
    return dataclasses.replace(spec, eligible=lambda _ctx: User.id == user_id)


def ctx_for(client: TestClient, now: dt.datetime = NOW, ml: Any = None) -> JobContext:
    return JobContext(settings_of(client), now, ml=ml)


def scalar(engine: Engine, sql: str, **params: Any) -> Any:
    with engine.connect() as conn:
        return conn.execute(text(sql), params).scalar_one()


# -- runner --------------------------------------------------------------------------------------
def test_fr_15_failing_user_is_isolated_counted_and_recorded_without_data(
    client: TestClient, engine: Engine, factory: sessionmaker[Session]
) -> None:
    a, b = (
        uuid.UUID(client.get(f"{API}/users/me", headers=signup(client)).json()["id"])
        for _ in range(2)
    )
    seen: list[uuid.UUID] = []

    def boom(session: Session, user: User, ctx: JobContext) -> dict[str, int]:
        seen.append(user.id)
        if user.id == a:
            raise ValueError(f"secret detail about {user.email}")
        return {"done": 1}

    spec = JobSpec("test-boom", "x", user_fn=boom, eligible=lambda _c: User.id.in_([a, b]))
    before = JOB_RUNS.labels("test-boom", "error")._value.get()
    result = run_job(factory, spec, ctx_for(client))
    assert sorted(seen) == sorted([a, b])  # the second user still ran
    assert (result.status, result.users, result.errors, result.stats) == (
        "failed",
        2,
        1,
        {"done": 1},
    )
    assert result.error == "ValueError x1"  # exception class only: the message could hold user data
    row = scalar(
        engine, "SELECT status || '|' || error FROM job_runs WHERE id = :i", i=result.run_id
    )
    assert row == "failed|ValueError x1"
    stats = scalar(engine, "SELECT stats::text FROM job_runs WHERE id = :i", i=result.run_id)
    assert '"errors": 1' in stats and "secret" not in stats
    assert JOB_RUNS.labels("test-boom", "error")._value.get() == before + 1


def test_fr_15_a_successful_run_is_recorded_and_counted_ok(
    client: TestClient, engine: Engine, factory: sessionmaker[Session], me: tuple[uuid.UUID, Any]
) -> None:
    before = JOB_RUNS.labels("test-ok", "ok")._value.get()
    spec = JobSpec(
        "test-ok", "x", user_fn=lambda *_: {"n": 2}, eligible=lambda _c: User.id == me[0]
    )
    result = run_job(factory, spec, ctx_for(client))
    assert (result.status, result.users, result.errors, result.stats) == (
        "succeeded",
        1,
        0,
        {"n": 2},
    )
    assert (
        scalar(engine, "SELECT status FROM job_runs WHERE id = :i", i=result.run_id) == "succeeded"
    )
    assert scalar(
        engine, "SELECT finished_at IS NOT NULL FROM job_runs WHERE id = :i", i=result.run_id
    )
    assert JOB_RUNS.labels("test-ok", "ok")._value.get() == before + 1


def test_fr_15_second_run_of_the_same_job_is_refused_while_one_is_running(
    client: TestClient, engine: Engine, factory: sessionmaker[Session]
) -> None:
    from app.jobs.framework import _lock_key

    holder = engine.connect()
    try:
        holder.execute(text("SELECT pg_advisory_lock(:k)"), {"k": _lock_key("test-lock")})
        result = run_job(
            factory, JobSpec("test-lock", "x", global_fn=lambda *_: {}), ctx_for(client)
        )
        assert (result.status, result.run_id, result.error) == ("skipped", None, "already running")
    finally:
        holder.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _lock_key("test-lock")})
        holder.close()
    ran = run_job(factory, JobSpec("test-lock", "x", global_fn=lambda *_: {}), ctx_for(client))
    assert ran.status == "succeeded"


def test_fr_15_chunks_walk_every_user(client: TestClient, factory: sessionmaker[Session]) -> None:
    ids = [
        uuid.UUID(client.get(f"{API}/users/me", headers=signup(client)).json()["id"])
        for _ in range(5)
    ]
    seen: set[uuid.UUID] = set()
    cfg = dataclasses.replace(ctx_for(client).cfg, chunk_size=2)
    spec = JobSpec(
        "test-chunks",
        "x",
        user_fn=lambda s, u, c: seen.add(u.id) or {"n": 1},
        eligible=lambda _c: User.id.in_(ids),
    )
    result = run_job(factory, spec, JobContext(settings_of(client), NOW, cfg))
    assert seen == set(ids) and result.users == 5


# -- cleanup -------------------------------------------------------------------------------------
def test_fr_12_3_cleanup_prunes_by_retention_and_is_idempotent(
    client: TestClient, engine: Engine, factory: sessionmaker[Session], me: tuple[uuid.UUID, Any]
) -> None:
    uid = me[0]
    old, fresh = NOW - dt.timedelta(days=500), NOW - dt.timedelta(hours=1)
    eid_old, eid_new = uuid.uuid4(), uuid.uuid4()
    with engine.begin() as c:

        def put(sql: str, **p: Any) -> None:
            c.execute(text(sql), {"u": uid, **p})

        for when, key in ((old, "old"), (fresh, "fresh")):
            put(
                "INSERT INTO idempotency_keys (user_id, key, method, path, request_hash, created_at) "
                "VALUES (:u, :k, 'POST', '/x', 'h', :t)",
                k=f"{key}-{uid}",
                t=when,
            )
            put(
                "INSERT INTO notifications (id, user_id, type, title, body, payload, dedupe_key, created_at) "
                "VALUES (gen_random_uuid(), :u, 'review_queue', 't', 'b', '{}', :k, :t)",
                k=f"n-{key}",
                t=when,
            )
        put(
            "INSERT INTO processed_events (event_id, consumer, processed_at) VALUES (:e, 'c', :t)",
            e=eid_old,
            t=old,
        )
        put(
            "INSERT INTO processed_events (event_id, consumer, processed_at) VALUES (:e, 'c', :t)",
            e=eid_new,
            t=fresh,
        )
        for eid, when in ((eid_old, old), (eid_new, fresh)):
            put(
                "INSERT INTO outbox_events (id, event_type, aggregate_id, user_id, payload, created_at, "
                "published_at) VALUES (:e, 'transaction.created', :e, :u, '{}', :t, :t)",
                e=eid,
                t=when,
            )
        put(
            "INSERT INTO anomaly_suppressions (user_id, merchant_key, expires_at) VALUES (:u, 'gone', :t)",
            t=NOW - dt.timedelta(days=1),
        )
        put(
            "INSERT INTO anomaly_suppressions (user_id, merchant_key, expires_at) VALUES (:u, 'live', :t)",
            t=NOW + dt.timedelta(days=5),
        )
        put(
            "INSERT INTO transaction_imports (id, user_id, status, file_sha256, original_filename, "
            "row_count, valid_count, invalid_count, duplicate_count, staged_rows, expires_at, created_at) "
            "VALUES (:i, :u, 'previewed', 'h', 'f.csv', 1, 1, 0, 0, '[{\"a\": 1}]', :t, :t)",
            i=uuid.UUID(int=uid.int ^ 1),
            t=NOW - dt.timedelta(hours=2),
        )

    first = run_job(factory, JOBS["cleanup"], ctx_for(client))
    assert first.status == "succeeded"
    s = first.stats
    assert s["imports_expired"] >= 1 and s["anomaly_suppressions"] >= 1
    assert s["idempotency_keys"] >= 1 and s["notifications"] >= 1
    assert s["processed_events"] >= 1 and s["outbox_events"] >= 1

    assert scalar(engine, "SELECT count(*) FROM idempotency_keys WHERE user_id = :u", u=uid) == 1
    assert scalar(engine, "SELECT count(*) FROM notifications WHERE user_id = :u", u=uid) == 1
    assert (
        scalar(engine, "SELECT count(*) FROM processed_events WHERE event_id = :e", e=eid_old) == 0
    )
    assert (
        scalar(engine, "SELECT count(*) FROM processed_events WHERE event_id = :e", e=eid_new) == 1
    )
    assert scalar(engine, "SELECT count(*) FROM outbox_events WHERE id = :e", e=eid_old) == 0
    assert scalar(engine, "SELECT count(*) FROM outbox_events WHERE id = :e", e=eid_new) == 1
    assert (
        scalar(engine, "SELECT merchant_key FROM anomaly_suppressions WHERE user_id = :u", u=uid)
        == "live"
    )
    imp = (
        engine.connect()
        .execute(
            text("SELECT status, staged_rows::text FROM transaction_imports WHERE user_id = :u"),
            {"u": uid},
        )
        .one()
    )
    assert tuple(imp) == ("expired", "[]")

    second = run_job(factory, JOBS["cleanup"], ctx_for(client))
    assert all(
        second.stats[k] == 0 for k in ("imports_expired", "idempotency_keys", "notifications")
    )


def test_fr_12_3_cleanup_never_deletes_unpublished_outbox_rows(
    client: TestClient, engine: Engine, factory: sessionmaker[Session], me: tuple[uuid.UUID, Any]
) -> None:
    eid = uuid.uuid4()
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO outbox_events (id, event_type, aggregate_id, user_id, payload, created_at) "
                "VALUES (:e, 'transaction.created', :e, :u, '{}', :t)"
            ),
            {"e": eid, "u": me[0], "t": NOW - dt.timedelta(days=100)},
        )
    run_job(factory, JOBS["cleanup"], ctx_for(client))
    assert scalar(engine, "SELECT count(*) FROM outbox_events WHERE id = :e", e=eid) == 1
    with engine.begin() as c:
        c.execute(text("UPDATE outbox_events SET published_at = now() WHERE id = :e"), {"e": eid})


# -- notifications -------------------------------------------------------------------------------
def test_fr_14_review_queue_reminder_notifies_once_per_week_and_only_from_five(
    client: TestClient, engine: Engine, factory: sessionmaker[Session], me: tuple[uuid.UUID, Any]
) -> None:
    uid = me[0]
    spec = only(JOBS["review-queue-reminder"], uid)

    def queue(n: int, start: int) -> None:
        seed_transactions(
            engine,
            uid,
            [
                {
                    "at": at(11, start + i),
                    "type": "expense",
                    "amount": "10000",
                    "category": "uncategorized",
                    "status": "needs_review",
                }
                for i in range(n)
            ],
        )

    queue(4, 1)
    assert run_job(factory, spec, ctx_for(client)).stats == {"notifications": 0}
    queue(1, 10)  # now five
    first = run_job(factory, spec, ctx_for(client))
    again = run_job(factory, spec, ctx_for(client))
    assert first.stats == {"notifications": 1} and again.stats == {"notifications": 0}
    n = scalar(
        engine,
        "SELECT count(*) FROM notifications WHERE user_id = :u AND type = 'review_queue'",
        u=uid,
    )
    assert n == 1
    next_week = run_job(factory, spec, ctx_for(client, NOW + dt.timedelta(days=7)))
    assert next_week.stats == {"notifications": 1}


def test_fr_14_recurring_due_soon_notifies_once_for_a_payment_within_two_days(
    client: TestClient, engine: Engine, factory: sessionmaker[Session], me: tuple[uuid.UUID, Any]
) -> None:
    uid = me[0]
    cat = scalar(engine, "SELECT id FROM categories WHERE slug = 'entertainment'")
    with engine.begin() as c:
        for key, due in (
            ("netflix", "2026-11-22"),
            ("spotify", "2026-11-25"),
            ("pln", "2026-11-19"),
        ):
            c.execute(
                text(
                    "INSERT INTO recurring_series (id, user_id, merchant_key, merchant_display, "
                    "transaction_type, category_id, frequency, median_interval_days, expected_amount, "
                    "amount_cv, last_date, next_expected_date, occurrences, confidence, status, "
                    "created_at, updated_at) VALUES (gen_random_uuid(), :u, :k, :d, 'expense', :c, "
                    "'monthly', 30, 54000, 0, '2026-10-22', :due, 4, 0.9, 'user_confirmed', now(), now())"
                ),
                {"u": uid, "k": key, "d": key.title(), "c": cat, "due": dt.date.fromisoformat(due)},
            )
    spec = only(JOBS["recurring-due-soon"], uid)
    seed_transactions(
        engine,
        uid,
        [
            {
                "at": at(10, 22),
                "type": "expense",
                "amount": "54000",
                "category": "entertainment",
                "merchant": "Netflix",
                "key": "netflix",
            }
        ],
    )
    first = run_job(factory, spec, ctx_for(client))
    assert first.stats == {"notifications": 1}  # today is the 20th: only the 22nd is within 2 days
    assert run_job(factory, spec, ctx_for(client)).stats == {"notifications": 0}
    title = scalar(
        engine,
        "SELECT title FROM notifications WHERE user_id = :u AND type = 'recurring_due_soon'",
        u=uid,
    )
    assert title == "Netflix is due 2026-11-22"


# -- budgets, forecasts --------------------------------------------------------------------------
def test_fr_05_08_daily_budget_close_writes_snapshot_and_outcomes_once(
    client: TestClient, engine: Engine, factory: sessionmaker[Session], me: tuple[uuid.UUID, Any]
) -> None:
    uid = me[0]
    seed_transactions(
        engine,
        uid,
        [
            {"at": at(10, 3), "type": "expense", "amount": "400000", "category": "food_beverage"},
            {"at": at(10, 20), "type": "expense", "amount": "200000", "category": "food_beverage"},
        ],
    )
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO budgets (id, user_id, category_id, limit_amount, created_at, updated_at) "
                "VALUES (gen_random_uuid(), :u, NULL, 1000000, :t, :t)"
            ),
            {"u": uid, "t": dt.datetime(2026, 9, 1, tzinfo=dt.UTC)},
        )
        for day, predicted in ((10, "700000.00"), (20, "650000.00")):
            c.execute(
                text(
                    "INSERT INTO forecasts (id, user_id, period_id, category_id, as_of, spent_to_date, "
                    "predicted_total, interval_low, interval_high, baseline_prediction, method, "
                    "history_level, daily_curve, created_at) VALUES (gen_random_uuid(), :u, '2026-10-01', "
                    "NULL, :as_of, 0, :p, 0, 0, 600000, 'run_rate', 'personal', '[]', now())"
                ),
                {"u": uid, "as_of": at(10, day), "p": predicted},
            )
    spec = only(JOBS["daily-budget-close"], uid)
    first = run_job(factory, spec, ctx_for(client))
    assert first.status == "succeeded" and first.stats == {"snapshots": 1, "outcomes": 2}
    snap = (
        engine.connect()
        .execute(
            text(
                "SELECT spent, limit_amount, utilization FROM budget_period_snapshots WHERE user_id = :u"
            ),
            {"u": uid},
        )
        .one()
    )
    assert (str(snap[0]), str(snap[1]), str(snap[2])) == ("600000.00", "1000000.00", "0.6000")
    rows = (
        engine.connect()
        .execute(
            text(
                "SELECT forecast_day, predicted_total, actual_total FROM forecast_outcomes "
                "WHERE user_id = :u ORDER BY forecast_day"
            ),
            {"u": uid},
        )
        .all()
    )
    assert [(r[0], str(r[1]), str(r[2])) for r in rows] == [
        (10, "700000.00", "600000.00"),
        (20, "650000.00", "600000.00"),
    ]
    assert run_job(factory, spec, ctx_for(client)).stats == {"snapshots": 0, "outcomes": 0}


def test_fr_15_forecast_surge_recurring_and_insights_jobs_run_and_insights_are_idempotent(
    client: TestClient, engine: Engine, factory: sessionmaker[Session], me: tuple[uuid.UUID, Any]
) -> None:
    uid = me[0]
    seed_transactions(
        engine,
        uid,
        [
            {
                "at": at(11, d),
                "type": "expense",
                "amount": "30000",
                "category": "food_beverage",
                "merchant": "Warung",
                "key": "warung",
            }
            for d in range(1, 18)
        ]
        + [{"at": at(10, 2), "type": "expense", "amount": "30000", "category": "food_beverage"}],
    )
    for name in ("daily-forecast", "category-surge", "recurring-refresh"):
        result = run_job(factory, only(JOBS[name], uid), ctx_for(client))
        assert (result.status, result.users, result.errors) == ("succeeded", 1, 0), name
    spec = only(JOBS["daily-insights"], uid)
    first = run_job(factory, spec, ctx_for(client))
    second = run_job(factory, spec, ctx_for(client))
    assert first.status == second.status == "succeeded"
    assert second.stats["created"] == 0 and second.stats["total"] == first.stats["total"]


# -- recategorize --------------------------------------------------------------------------------
def test_fr_15_recategorize_needs_review_uses_the_ml_service_and_leaves_failures_alone(
    client: TestClient, engine: Engine, factory: sessionmaker[Session], me: tuple[uuid.UUID, Any]
) -> None:
    uid = me[0]
    seed_transactions(
        engine,
        uid,
        [
            {
                "at": at(11, 1 + i),
                "type": "expense",
                "amount": "25000",
                "category": "uncategorized",
                "description": "kopi",
                "merchant": "Kopi",
                "key": "kopi",
                "status": "needs_review",
            }
            for i in range(3)
        ],
    )
    ml = FakeMl()
    ml_client = install(client, ml)
    spec = only(JOBS["recategorize-needs-review"], uid)

    ml.mode = "connect"
    down = run_job(factory, spec, ctx_for(client, ml=ml_client))
    assert down.status == "succeeded" and down.stats == {
        "recategorized": 0,
        "still_needs_review": 3,
    }

    ml.mode = "ok"
    up = run_job(factory, spec, ctx_for(client, ml=ml_client))
    assert up.stats["recategorized"] + up.stats["still_needs_review"] == 3
    left = scalar(
        engine,
        "SELECT count(*) FROM transactions WHERE user_id = :u AND category_status = 'needs_review'",
        u=uid,
    )
    assert left == up.stats["still_needs_review"]
    assert up.stats["recategorized"] >= 1
    # user-set categories are never touched
    assert run_job(factory, spec, ctx_for(client, ml=ml_client)).users == 1


# -- internal endpoint ---------------------------------------------------------------------------
@pytest.fixture
def worker(engine: Engine, database_url: str) -> Iterator[TestClient]:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        app_env="ci",
        database_url=database_url,
        jwt_secret="s" * 40,
        cookie_secure=False,
        role="worker",
    )
    app = create_app(settings)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.state.engine.dispose()


def test_fr_15_internal_endpoint_runs_a_job_and_rejects_unknown_names(worker: TestClient) -> None:
    ok = worker.post("/internal/jobs/cleanup")
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["job"] == "cleanup" and body["status"] == "succeeded" and body["run_id"]
    assert "idempotency_keys" in body["stats"]
    missing = worker.post("/internal/jobs/export-bigquery")
    assert missing.status_code == 404 and missing.json()["code"] == "JOB_NOT_FOUND"
    assert worker.post("/internal/jobs/cleanup?date=not-a-date").status_code == 422
    assert worker.post("/internal/jobs/cleanup?date=2026-11-20").status_code == 200


def test_fr_15_the_public_api_does_not_expose_jobs(client: TestClient) -> None:
    assert client.post("/internal/jobs/cleanup").status_code == 404
