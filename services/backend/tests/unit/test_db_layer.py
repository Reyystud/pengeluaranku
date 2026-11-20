"""IDs, models and readiness wiring that need no PostgreSQL."""

from __future__ import annotations

import uuid

from app.core.config import Settings
from app.core.db import database_check, head_revision, register_readiness
from app.core.ids import new_uuid7
from app.models import Base
from sqlalchemy import create_engine
from sqlalchemy.orm import configure_mappers

from ml.taxonomy import CATEGORIES


def test_fr_12_uuid7_has_version_variant_and_orders_by_time() -> None:
    a, b = new_uuid7(1_000), new_uuid7(2_000)
    assert a.version == 7 and a.variant == uuid.RFC_4122
    assert a < b
    assert new_uuid7() != new_uuid7()


def test_fr_12_uuid7_embeds_the_millisecond_timestamp() -> None:
    ms = 1_700_000_000_123
    assert new_uuid7(ms).int >> 80 == ms


def test_fr_12_mappers_configure_and_money_is_numeric() -> None:
    configure_mappers()
    for table in Base.metadata.sorted_tables:
        for col in table.c:
            assert "FLOAT" not in str(col.type).upper() and "REAL" not in str(col.type).upper(), (
                table.name,
                col.name,
            )


def test_fr_12_database_check_runs_select_1() -> None:
    database_check(create_engine("sqlite://"))()


def test_fr_12_no_readiness_checks_without_database_url() -> None:
    checks: dict[str, object] = {}
    assert register_readiness(checks, Settings(jwt_secret="x" * 40)) is None  # type: ignore[arg-type]
    assert checks == {}


def test_fr_12_database_url_registers_database_and_migration_checks() -> None:
    checks: dict[str, object] = {}
    settings = Settings(jwt_secret="x" * 40, database_url="postgresql+psycopg://u:p@127.0.0.1:1/x")  # type: ignore[arg-type]
    engine = register_readiness(checks, settings)  # type: ignore[arg-type]
    assert engine is not None and set(checks) == {"database", "migrations"}


def test_fr_12_migration_has_a_single_head() -> None:
    assert head_revision() == "0001"


def test_fr_12_migration_seed_matches_taxonomy_1() -> None:
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "migrations/versions/0001_initial_schema.py"
    spec = importlib.util.spec_from_file_location("m0001", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    seed = [(r[1], r[2], r[3], r[4]) for r in mod.CATEGORY_SEED]
    assert seed == [
        (c.slug, c.display_name, c.transaction_type, c.slug != "uncategorized") for c in CATEGORIES
    ]
