"""Repositories that are not user-scoped: users (the principals) and categories (global seed)."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Category, User


class UserRepository:
    """Lookups by id or email. Used by auth, never by user-facing data endpoints."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, id: uuid.UUID) -> User | None:
        return self.session.get(User, id)

    def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(func.lower(User.email) == email.lower())
        return self.session.execute(stmt).scalar_one_or_none()

    def add(self, user: User) -> User:
        self.session.add(user)
        self.session.flush()
        return user

    def delete(self, id: uuid.UUID) -> bool:
        user = self.get(id)
        if user is None:
            return False
        self.session.delete(user)
        self.session.flush()
        return True


class CategoryRepository:
    """Categories are global reference data (seeded by the first migration)."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def list(self) -> list[Category]:
        return list(self.session.execute(select(Category).order_by(Category.sort_order)).scalars())

    def get_by_slug(self, slug: str) -> Category | None:
        stmt = select(Category).where(Category.slug == slug)
        return self.session.execute(stmt).scalar_one_or_none()

    def get(self, id: uuid.UUID) -> Category | None:
        return self.session.get(Category, id)
