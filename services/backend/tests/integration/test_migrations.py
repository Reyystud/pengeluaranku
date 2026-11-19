"""Alembic migrations against real PostgreSQL (PRD 12.1: reversible, no drift, seed)."""

from __future__ import annotations

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from app.core.db import alembic_config, database_check, head_revision, migrations_check
from app.models import Base
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import IntegrityError

from ml.taxonomy import CATEGORIES, MODEL_LABELS
from tests.integration.conftest import reset_schema

pytestmark = pytest.mark.integration


def test_fr_12_schema_has_no_drift_from_models(engine: Engine) -> None:
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_fr_12_every_user_owned_table_has_user_id_index_and_cascade(engine: Engine) -> None:
    insp = inspect(engine)
    for table in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns(table)}
        if "user_id" not in cols or table in {"users", "outbox_events"}:
            continue
        fks = [f for f in insp.get_foreign_keys(table) if f["constrained_columns"] == ["user_id"]]
        assert fks and fks[0]["options"].get("ondelete") == "CASCADE", table
        pk = insp.get_pk_constraint(table)["constrained_columns"]
        indexed = [i["column_names"][0] for i in insp.get_indexes(table) if i["column_names"]]
        assert pk[0] == "user_id" or "user_id" in indexed, table


def test_fr_12_categories_seed_matches_taxonomy(engine: Engine) -> None:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT slug, name, transaction_type, is_model_label "
                "FROM categories ORDER BY sort_order"
            )
        ).all()
    assert [r[0] for r in rows] == [c.slug for c in CATEGORIES]
    assert [(r[1], r[2]) for r in rows] == [
        (c.display_name, c.transaction_type) for c in CATEGORIES
    ]
    assert {r[0] for r in rows if r[3]} == set(MODEL_LABELS)
    uncategorized = next(r for r in rows if r[0] == "uncategorized")
    assert uncategorized[2] == "any" and uncategorized[3] is False


def test_fr_12_readiness_checks_pass_at_head(engine: Engine) -> None:
    database_check(engine)()
    migrations_check(engine)()


def test_fr_12_migration_check_fails_when_not_at_head(engine: Engine, database_url: str) -> None:
    with engine.begin() as conn:
        conn.execute(text("UPDATE alembic_version SET version_num = 'stale'"))
    try:
        with pytest.raises(RuntimeError):
            migrations_check(engine)()
    finally:
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE alembic_version SET version_num = :v"), {"v": head_revision()}
            )


def test_fr_12_money_is_numeric_and_dates_are_timestamptz(engine: Engine) -> None:
    cols = {c["name"]: c for c in inspect(engine).get_columns("transactions")}
    assert str(cols["amount"]["type"]) == "NUMERIC(15, 2)"
    assert cols["transaction_date"]["type"].timezone is True


def test_fr_12_check_constraint_rejects_unknown_enum(session) -> None:  # type: ignore[no-untyped-def]
    from tests.integration.conftest import make_user

    user = make_user(session)
    with pytest.raises(IntegrityError):
        session.execute(text("UPDATE users SET locale = 'xx' WHERE id = :i"), {"i": user.id})


def test_fr_12_migration_is_reversible(database_url: str, engine: Engine) -> None:
    cfg = alembic_config(database_url)
    command.downgrade(cfg, "base")
    assert inspect(engine).get_table_names() == ["alembic_version"]
    command.upgrade(cfg, "head")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM categories")).scalar_one() == len(CATEGORIES)


def test_fr_12_fresh_database_upgrade(database_url: str, engine: Engine) -> None:
    reset_schema(engine)
    command.upgrade(alembic_config(database_url), "head")
    assert "transactions" in inspect(engine).get_table_names()
