"""FR-13 behavior segments (PRD 7.13): weekly assignment, GET /intelligence/segment, scoping."""

from __future__ import annotations

import dataclasses
import datetime as dt
import uuid
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from app.api.analytics import get_now
from app.core.config import Settings
from app.jobs.catalogue import JOBS
from app.jobs.framework import JobContext, JobSpec, run_job
from app.models import User
from app.services.segments import load_clusterer
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from ml.clustering.config import load_clustering_config
from ml.clustering.features import RAW_COLUMNS, raw_features
from tests.integration.conftest import API, signup
from tests.integration.ledger_support import seed_transactions

pytestmark = pytest.mark.integration

JKT = ZoneInfo("Asia/Jakarta")
NOW = dt.datetime(2026, 11, 20, 5, 0, tzinfo=dt.UTC)  # period Nov 1-30; complete: Sep, Oct


def at(month: int, day: int, hour: int = 10) -> dt.datetime:
    return dt.datetime(2026, month, day, hour, tzinfo=JKT)


@pytest.fixture
def auth(client: TestClient) -> dict[str, str]:
    client.app.dependency_overrides[get_now] = lambda: NOW  # type: ignore[attr-defined]
    return signup(client)


@pytest.fixture
def factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def uid_of(client: TestClient, headers: dict[str, str]) -> uuid.UUID:
    return uuid.UUID(client.get(f"{API}/users/me", headers=headers).json()["id"])


def settings_of(client: TestClient) -> Settings:
    return client.app.state.settings  # type: ignore[attr-defined,no-any-return]


def only(spec: JobSpec, user_id: uuid.UUID) -> JobSpec:
    return dataclasses.replace(spec, eligible=lambda _ctx: User.id == user_id)


def two_periods_of_spending() -> list[dict[str, Any]]:
    """Sep and Oct, irregular merchants and dates (so no recurring series), salary in both."""
    rows: list[dict[str, Any]] = []
    spend = [
        ("food_beverage", 45000),
        ("shopping", 320000),
        ("groceries", 150000),
        ("transportation", 22000),
        ("entertainment", 80000),
    ]
    for month in (9, 10):
        for i, (cat, amount) in enumerate(spend * 3):
            rows.append(
                {
                    "at": at(month, 2 + i * 2, 9 + i % 8),
                    "type": "expense",
                    "amount": str(amount + i * 1700),
                    "category": cat,
                    "merchant": f"Shop {month}-{i}",
                    "key": f"shop-{month}-{i}",
                }
            )
        rows.append(
            {"at": at(month, 25), "type": "income", "amount": "9000000", "category": "salary"}
        )
    rows.append(
        {
            "at": at(9, 1, 8),
            "type": "expense",
            "amount": "30000",
            "category": "food_beverage",
            "merchant": "First",
            "key": "first",
        }
    )
    return rows


def run(client: TestClient, factory: sessionmaker[Session], uid: uuid.UUID) -> Any:
    ctx = JobContext(settings_of(client), NOW)
    return run_job(factory, only(JOBS["clustering-weekly"], uid), ctx)


def test_fr_13_01_user_with_two_complete_periods_gets_a_segment_matching_the_ml_code(
    client: TestClient, auth: dict[str, str], engine: Engine, factory: sessionmaker[Session]
) -> None:
    uid = uid_of(client, auth)
    rows = two_periods_of_spending()
    seed_transactions(engine, uid, rows)
    before = client.get(f"{API}/intelligence/segment", headers=auth).json()
    assert (before["segment"], before["reason"], before["complete_periods"]) == (
        None,
        "NOT_COMPUTED",
        2,
    )

    result = run(client, factory, uid)
    assert (result.status, result.stats) == ("succeeded", {"assigned": 1, "skipped": 0})

    body = client.get(f"{API}/intelligence/segment", headers=auth).json()
    seg = body["segment"]
    assert body["reason"] is None and seg["model_version"] == load_clusterer().version  # type: ignore[union-attr]
    assert seg["name"] and seg["description"] and len(seg["traits"]) <= 3

    # parity: the same data through the ML code, outside the backend
    frame = pd.DataFrame(
        [
            {
                "occurred_at": pd.Timestamp(r["at"].astimezone(JKT).replace(tzinfo=None)),
                "type": r["type"],
                "amount_f": float(r["amount"]),
                "category": r["category"],
                "recurring": False,
            }
            for r in rows
        ]
    )
    cfg = load_clustering_config()
    days = (dt.date(2026, 10, 31) - dt.date(2026, 9, 1)).days + 1
    feats = raw_features(frame, days, 2, cfg)
    assert feats is not None
    model = load_clusterer()
    assert model is not None
    index, _ = model.assign(pd.DataFrame([feats], columns=list(RAW_COLUMNS)), cfg)
    assert seg["id"] == model.segments[int(index[0])].id
    for trait in seg["traits"]:
        assert trait["direction"] in ("higher", "lower") and 0 <= trait["percent"] <= 100
        assert "similar users" in trait["message"]


def test_fr_13_01_a_second_run_updates_the_same_row(
    client: TestClient, auth: dict[str, str], engine: Engine, factory: sessionmaker[Session]
) -> None:
    uid = uid_of(client, auth)
    seed_transactions(engine, uid, two_periods_of_spending())
    run(client, factory, uid)
    run(client, factory, uid)
    with engine.connect() as conn:
        assert (
            conn.execute(
                text("SELECT count(*) FROM user_segments WHERE user_id = :u"), {"u": uid}
            ).scalar_one()
            == 1
        )


def test_fr_13_01_too_little_history_gets_no_segment_and_says_why(
    client: TestClient, auth: dict[str, str], engine: Engine, factory: sessionmaker[Session]
) -> None:
    uid = uid_of(client, auth)
    seed_transactions(
        engine,
        uid,
        [  # only the current period and one complete one
            {"at": at(10, 1), "type": "expense", "amount": "50000", "category": "food_beverage"},
            {"at": at(11, 3), "type": "expense", "amount": "50000", "category": "food_beverage"},
        ],
    )
    result = run(client, factory, uid)
    assert result.stats == {"assigned": 0, "skipped": 1}
    body = client.get(f"{API}/intelligence/segment", headers=auth).json()
    assert (body["segment"], body["reason"]) == (None, "INSUFFICIENT_HISTORY")
    assert (body["complete_periods"], body["required_periods"]) == (1, 2)


def test_fr_13_04_segments_are_private_to_the_user(
    client: TestClient, auth: dict[str, str], engine: Engine, factory: sessionmaker[Session]
) -> None:
    uid = uid_of(client, auth)
    seed_transactions(engine, uid, two_periods_of_spending())
    run(client, factory, uid)
    other = signup(client)
    body = client.get(f"{API}/intelligence/segment", headers=other).json()
    assert body["segment"] is None and body["reason"] == "INSUFFICIENT_HISTORY"
    assert client.get(f"{API}/intelligence/segment").status_code == 401


def test_fr_13_03_without_a_model_artifact_the_api_says_so(
    client: TestClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.services.segments.load_clusterer", lambda: None)
    body = client.get(f"{API}/intelligence/segment", headers=auth).json()
    assert (body["segment"], body["reason"]) == (None, "MODEL_NOT_AVAILABLE")
