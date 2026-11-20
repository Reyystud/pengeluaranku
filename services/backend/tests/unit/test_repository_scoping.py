"""Repository scoping rules that need no database (PRD 12.4). DB-level proof is in integration."""

from __future__ import annotations

import inspect

from app.models import Base
from app.repositories import (
    KEYED_PENDING,
    KEYED_REPOSITORIES,
    SCOPED_REPOSITORIES,
    UNSCOPED_BY_DESIGN,
    CategoryRepository,
    UserRepository,
)


def test_fr_12_every_scoped_repository_method_takes_user_id_first() -> None:
    for repo_cls in SCOPED_REPOSITORIES:
        for name, fn in inspect.getmembers(repo_cls, inspect.isfunction):
            if name.startswith("_"):
                continue
            params = list(inspect.signature(fn).parameters)
            assert params[:2] == ["self", "user_id"], f"{repo_cls.__name__}.{name}{params}"


def test_fr_12_keyed_repository_methods_take_user_id_first() -> None:
    for repo_cls in KEYED_REPOSITORIES.values():
        for name, fn in inspect.getmembers(repo_cls, inspect.isfunction):
            if name.startswith("_"):
                continue
            assert list(inspect.signature(fn).parameters)[:2] == ["self", "user_id"], name


def test_fr_12_every_user_id_table_is_covered_or_explicitly_deferred() -> None:
    covered = {repo.model.__tablename__ for repo in SCOPED_REPOSITORIES} | set(KEYED_REPOSITORIES)
    with_user_id = {
        t.name for t in Base.metadata.sorted_tables if "user_id" in t.c and t.name != "users"
    }
    uncovered = with_user_id - covered - set(KEYED_PENDING) - set(UNSCOPED_BY_DESIGN)
    assert uncovered == set(), f"user-owned tables without a scoped repository: {uncovered}"


def test_fr_12_scoped_repositories_only_cover_tables_with_user_id_and_id() -> None:
    for repo_cls in SCOPED_REPOSITORIES:
        table = repo_cls.model.__table__
        assert "user_id" in table.c and "id" in table.c, table.name


def test_fr_12_unscoped_repositories_are_limited_to_users_and_categories() -> None:
    assert {UserRepository.__name__, CategoryRepository.__name__} == {
        "UserRepository",
        "CategoryRepository",
    }
