"""Staged CSV imports (PRD 7.2.3). Every method takes ``user_id`` first and filters by it."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models import TransactionImport
from app.repositories.base import ScopedRepository


class TransactionImportRepository(ScopedRepository[TransactionImport]):
    model = TransactionImport

    def get_for_update(self, user_id: uuid.UUID, id: uuid.UUID) -> TransactionImport | None:
        stmt = (
            select(TransactionImport)
            .where(TransactionImport.user_id == user_id, TransactionImport.id == id)
            .with_for_update()
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def committed_with_sha(self, user_id: uuid.UUID, sha256: str) -> TransactionImport | None:
        """A previously committed import of the same file content (FR-02.09)."""
        stmt = (
            select(TransactionImport)
            .where(
                TransactionImport.user_id == user_id,
                TransactionImport.file_sha256 == sha256,
                TransactionImport.status == "committed",
            )
            .order_by(TransactionImport.created_at.desc())
            .limit(1)
        )
        return self.session.execute(stmt).scalar_one_or_none()
