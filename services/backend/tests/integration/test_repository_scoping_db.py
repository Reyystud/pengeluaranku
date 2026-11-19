"""Two-user scoping test with SQL echo (PRD 12.4, 21.2 ``test_repository_scoping``)."""

from __future__ import annotations

import datetime as dt
import inspect
import uuid
from decimal import Decimal

import pytest
from app.core.errors import ProblemError
from app.models import Budget, MerchantRule, Transaction
from app.repositories import (
    SCOPED_REPOSITORIES,
    CategoryRepository,
    ScopedRepository,
    TransactionFilters,
    TransactionRepository,
)
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from tests.integration.conftest import make_user

pytestmark = pytest.mark.integration


def _tx(category_id: uuid.UUID) -> Transaction:
    return Transaction(
        transaction_type="expense",
        amount=Decimal("25000.00"),
        description="kopi",
        transaction_date=dt.datetime.now(dt.UTC),
        category_id=category_id,
        category_status="auto",
        source="manual",
    )


def test_fr_12_other_users_row_is_invisible_everywhere(session: Session) -> None:
    alice, bob = make_user(session), make_user(session)
    cat = CategoryRepository(session).get_by_slug("food_beverage")
    assert cat is not None
    repo = TransactionRepository(session)
    tx = repo.add(alice.id, _tx(cat.id))

    assert repo.get(alice.id, tx.id) is not None
    assert repo.get(bob.id, tx.id) is None
    assert repo.list(bob.id) == []
    assert repo.count(bob.id) == 0
    assert repo.delete(bob.id, tx.id) is False
    with pytest.raises(ProblemError) as exc:
        repo.require(bob.id, tx.id)
    assert exc.value.status == 404
    assert repo.count(alice.id) == 1


def test_fr_12_add_rejects_entity_owned_by_someone_else(session: Session) -> None:
    alice, bob = make_user(session), make_user(session)
    cat = CategoryRepository(session).get_by_slug("food_beverage")
    assert cat is not None
    entity = _tx(cat.id)
    entity.user_id = alice.id
    with pytest.raises(ValueError):
        TransactionRepository(session).add(bob.id, entity)


def test_fr_12_every_scoped_query_sends_user_id_in_sql(session: Session) -> None:
    """Record SQL for every public repo method; each statement must bind the caller's user_id."""
    alice, bob = make_user(session), make_user(session)
    cat = CategoryRepository(session).get_by_slug("food_beverage")
    assert cat is not None
    seeded = TransactionRepository(session).add(alice.id, _tx(cat.id))
    session.flush()

    seen: list[tuple[str, object]] = []

    @event.listens_for(session.get_bind(), "before_cursor_execute")
    def record(conn, cursor, statement, parameters, context, executemany):  # type: ignore[no-untyped-def]
        seen.append((statement, parameters))

    try:
        for repo_cls in SCOPED_REPOSITORIES:
            repo = repo_cls(session)
            for method, args in (
                ("get", (bob.id, seeded.id)),
                ("list", (bob.id,)),
                ("count", (bob.id,)),
                ("delete", (bob.id, seeded.id)),
            ):
                seen.clear()
                getattr(repo, method)(*args)
                assert seen, f"{repo_cls.__name__}.{method} ran no SQL"
                for statement, params in seen:
                    assert "user_id" in statement, (repo_cls.__name__, method, statement)
                    assert bob.id in (
                        params if isinstance(params, (tuple, list)) else tuple(params.values())
                    ), (
                        repo_cls.__name__,
                        method,
                    )
    finally:
        event.remove(session.get_bind(), "before_cursor_execute", record)
    assert TransactionRepository(session).count(alice.id) == 1


def test_fr_12_cascade_delete_removes_user_data(session: Session) -> None:
    alice = make_user(session)
    cat = CategoryRepository(session).get_by_slug("food_beverage")
    assert cat is not None
    TransactionRepository(session).add(alice.id, _tx(cat.id))
    session.add(
        MerchantRule(
            user_id=alice.id, merchant_key="kopi", merchant_display="Kopi", category_id=cat.id
        )
    )
    session.add(Budget(user_id=alice.id, category_id=None, limit_amount=Decimal("100.00")))
    session.flush()
    from app.repositories import UserRepository

    assert UserRepository(session).delete(alice.id) is True
    session.expire_all()
    assert TransactionRepository(session).count(alice.id) == 0


def test_fr_12_global_budget_is_unique_per_user(session: Session) -> None:
    from sqlalchemy.exc import IntegrityError

    alice = make_user(session)
    session.add(Budget(user_id=alice.id, category_id=None, limit_amount=Decimal("1.00")))
    session.flush()
    session.add(Budget(user_id=alice.id, category_id=None, limit_amount=Decimal("2.00")))
    with pytest.raises(IntegrityError):
        session.flush()


def test_repositories_signature_is_user_first() -> None:
    for repo_cls in SCOPED_REPOSITORIES:
        assert issubclass(repo_cls, ScopedRepository)
        for name, fn in inspect.getmembers(repo_cls, inspect.isfunction):
            if name.startswith("_"):
                continue
            first = next(iter(inspect.signature(fn).parameters.values()))
            assert first.name == "self"
            second = list(inspect.signature(fn).parameters)[1]
            assert second == "user_id", (repo_cls.__name__, name)


_ = Engine


def test_fr_12_transaction_query_methods_filter_by_user_id_in_sql(session: Session) -> None:
    alice, bob = make_user(session), make_user(session)
    cat = CategoryRepository(session).get_by_slug("food_beverage")
    assert cat is not None
    tx = TransactionRepository(session).add(alice.id, _tx(cat.id))
    repo = TransactionRepository(session)
    seen: list[tuple[str, object]] = []

    @event.listens_for(session.get_bind(), "before_cursor_execute")
    def record(conn, cursor, statement, parameters, context, executemany):  # type: ignore[no-untyped-def]
        seen.append((statement, parameters))

    try:
        calls = {
            "search": lambda: repo.search(bob.id, TransactionFilters(), sort="date", limit=10),
            "count_matching": lambda: repo.count_matching(bob.id, TransactionFilters()),
            "get_for_update": lambda: repo.get_for_update(bob.id, tx.id),
            "get_many": lambda: repo.get_many(bob.id, [tx.id]),
            "delete_many": lambda: repo.delete_many(bob.id, [tx.id]),
            "set_category_many": lambda: repo.set_category_many(
                bob.id, [tx.id], cat.id, "user_set"
            ),
            "find_duplicate": lambda: repo.find_duplicate(
                bob.id,
                transaction_type="expense",
                amount=Decimal("1.00"),
                merchant_key="k",
                occurred_at=dt.datetime.now(dt.UTC),
                has_time=True,
                timezone="Asia/Jakarta",
            ),
        }
        for name, call in calls.items():
            seen.clear()
            call()
            assert seen, name
            assert all("user_id" in stmt for stmt, _ in seen), name
    finally:
        event.remove(session.get_bind(), "before_cursor_execute", record)
    assert repo.count(alice.id) == 1  # bob's calls touched nothing of alice's
