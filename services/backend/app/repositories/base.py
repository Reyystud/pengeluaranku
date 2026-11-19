"""Repository base classes (PRD 12.4).

Every public method of a user-scoped repository takes ``user_id`` as its FIRST required argument
and filters on it, so cross-user access is impossible by construction. A missing row and a row
owned by someone else are indistinguishable: both yield ``None`` / HTTP 404 (PRD 0.3 rule 6).
``tests/unit/test_repository_scoping.py`` enforces this by introspection, and
``tests/integration/test_repository_scoping_db.py`` by recording the SQL of a real database.
"""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.errors import not_found
from app.models.base import Base


class ScopedRepository[M: Base]:
    """CRUD helpers for a table with ``id`` and ``user_id`` columns."""

    model: ClassVar[type[Any]]

    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, user_id: uuid.UUID, id: uuid.UUID) -> M | None:
        stmt = select(self.model).where(self.model.user_id == user_id, self.model.id == id)
        return self.session.execute(stmt).scalar_one_or_none()  # type: ignore[no-any-return,unused-ignore]

    def require(self, user_id: uuid.UUID, id: uuid.UUID) -> M:
        """Like ``get`` but raises the 404 problem for missing or foreign rows."""
        entity = self.get(user_id, id)
        if entity is None:
            raise not_found()
        return entity

    def list(self, user_id: uuid.UUID, limit: int = 100) -> list[M]:
        stmt = (
            select(self.model)
            .where(self.model.user_id == user_id)
            .order_by(self.model.id)
            .limit(limit)
        )
        return list(self.session.execute(stmt).scalars())

    def count(self, user_id: uuid.UUID) -> int:
        stmt = select(func.count()).select_from(self.model).where(self.model.user_id == user_id)
        return int(self.session.execute(stmt).scalar_one())

    def add(self, user_id: uuid.UUID, entity: Any) -> M:
        """Attach ``entity`` to ``user_id``. A different pre-set owner is rejected."""
        current = getattr(entity, "user_id", None)
        if current is not None and current != user_id:
            raise ValueError("entity already belongs to another user")
        entity.user_id = user_id
        self.session.add(entity)
        self.session.flush()
        result: M = entity
        return result

    def delete(self, user_id: uuid.UUID, id: uuid.UUID) -> bool:
        stmt = delete(self.model).where(self.model.user_id == user_id, self.model.id == id)
        result: Any = self.session.execute(stmt)
        return bool(result.rowcount)
