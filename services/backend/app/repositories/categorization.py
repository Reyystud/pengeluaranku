"""Merchant rules, predictions and feedback (PRD 7.3, 7.10, 7.15). All methods are user-scoped."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select, update

from app.models import CategoryFeedback, CategoryPrediction, MerchantRule
from app.models.base import utcnow
from app.repositories.base import ScopedRepository

MAX_RULES_PER_USER = 1000  # FR-15.03


class MerchantRuleRepository(ScopedRepository[MerchantRule]):
    model = MerchantRule

    def get_by_key(self, user_id: uuid.UUID, merchant_key: str) -> MerchantRule | None:
        stmt = select(MerchantRule).where(
            MerchantRule.user_id == user_id, MerchantRule.merchant_key == merchant_key
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def list_all(self, user_id: uuid.UUID) -> list[MerchantRule]:
        stmt = (
            select(MerchantRule)
            .where(MerchantRule.user_id == user_id)
            .order_by(MerchantRule.updated_at.desc(), MerchantRule.id)
            .limit(MAX_RULES_PER_USER)
        )
        return list(self.session.execute(stmt).scalars())

    def get_many_by_keys(
        self, user_id: uuid.UUID, merchant_keys: Sequence[str]
    ) -> dict[str, MerchantRule]:
        if not merchant_keys:
            return {}
        stmt = select(MerchantRule).where(
            MerchantRule.user_id == user_id, MerchantRule.merchant_key.in_(list(merchant_keys))
        )
        return {r.merchant_key: r for r in self.session.execute(stmt).scalars()}

    def mark_applied(
        self, user_id: uuid.UUID, rule_ids: Sequence[uuid.UUID], times: int = 1
    ) -> None:
        if not rule_ids:
            return
        now = utcnow()
        self.session.execute(
            update(MerchantRule)
            .where(MerchantRule.user_id == user_id, MerchantRule.id.in_(list(rule_ids)))
            .values(times_applied=MerchantRule.times_applied + times, last_applied_at=now)
        )


class CategoryPredictionRepository(ScopedRepository[CategoryPrediction]):
    model = CategoryPrediction

    def latest_for(
        self, user_id: uuid.UUID, transaction_id: uuid.UUID
    ) -> CategoryPrediction | None:
        stmt = (
            select(CategoryPrediction)
            .where(
                CategoryPrediction.user_id == user_id,
                CategoryPrediction.transaction_id == transaction_id,
            )
            .order_by(CategoryPrediction.created_at.desc(), CategoryPrediction.id.desc())
            .limit(1)
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def add_many(self, user_id: uuid.UUID, rows: Sequence[CategoryPrediction]) -> None:
        for row in rows:
            if row.user_id is not None and row.user_id != user_id:
                raise ValueError("entity already belongs to another user")
            row.user_id = user_id
        self.session.add_all(list(rows))
        self.session.flush()


class CategoryFeedbackRepository(ScopedRepository[CategoryFeedback]):
    model = CategoryFeedback

    def recent_for(self, user_id: uuid.UUID, transaction_id: uuid.UUID) -> list[CategoryFeedback]:
        stmt = (
            select(CategoryFeedback)
            .where(
                CategoryFeedback.user_id == user_id,
                CategoryFeedback.transaction_id == transaction_id,
            )
            .order_by(CategoryFeedback.created_at.desc())
        )
        return list(self.session.execute(stmt).scalars())


__all__ = [
    "MAX_RULES_PER_USER",
    "CategoryFeedbackRepository",
    "CategoryPredictionRepository",
    "MerchantRuleRepository",
]
