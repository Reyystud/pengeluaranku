"""Refresh-token store.

Deliberately NOT user-scoped: a refresh request arrives with only the opaque token, so the row
is found by its SHA-256 hash before any user is known. Everything else here takes ``user_id``.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import RefreshToken


class RefreshTokenStore:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, token: RefreshToken) -> RefreshToken:
        self.session.add(token)
        self.session.flush()
        return token

    def get_by_hash_for_update(self, token_hash: str) -> RefreshToken | None:
        """Row lock serializes concurrent refreshes of one token (no double rotation)."""
        stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash).with_for_update()
        return self.session.execute(stmt).scalar_one_or_none()

    def revoke_family(self, family_id: uuid.UUID, now: dt.datetime) -> None:
        stmt = (
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        self.session.execute(stmt)

    def revoke_all_for_user(
        self, user_id: uuid.UUID, now: dt.datetime, except_family: uuid.UUID | None = None
    ) -> None:
        stmt = (
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        if except_family is not None:
            stmt = stmt.where(RefreshToken.family_id != except_family)
        self.session.execute(stmt)
