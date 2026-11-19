"""Data-access layer (PRD 12.4). One repository per user-owned table, plus users and categories."""

from __future__ import annotations

from typing import Any

from app.models import (
    Anomaly,
    Budget,
    CategoryFeedback,
    CategoryPrediction,
    Forecast,
    ForecastOutcome,
    Insight,
    MerchantRule,
    Notification,
    RecurringSeries,
    TransactionImport,
)
from app.repositories.auth import RefreshTokenStore
from app.repositories.base import ScopedRepository
from app.repositories.idempotency import IdempotencyRepository
from app.repositories.transactions import TransactionFilters, TransactionRepository
from app.repositories.users import CategoryRepository, UserRepository


class TransactionImportRepository(ScopedRepository[TransactionImport]):
    model = TransactionImport


class CategoryPredictionRepository(ScopedRepository[CategoryPrediction]):
    model = CategoryPrediction


class MerchantRuleRepository(ScopedRepository[MerchantRule]):
    model = MerchantRule


class CategoryFeedbackRepository(ScopedRepository[CategoryFeedback]):
    model = CategoryFeedback


class BudgetRepository(ScopedRepository[Budget]):
    model = Budget


class AnomalyRepository(ScopedRepository[Anomaly]):
    model = Anomaly


class ForecastRepository(ScopedRepository[Forecast]):
    model = Forecast


class ForecastOutcomeRepository(ScopedRepository[ForecastOutcome]):
    model = ForecastOutcome


class RecurringSeriesRepository(ScopedRepository[RecurringSeries]):
    model = RecurringSeries


class InsightRepository(ScopedRepository[Insight]):
    model = Insight


class NotificationRepository(ScopedRepository[Notification]):
    model = Notification


SCOPED_REPOSITORIES: tuple[type[ScopedRepository[Any]], ...] = (
    TransactionRepository,
    TransactionImportRepository,
    CategoryPredictionRepository,
    MerchantRuleRepository,
    CategoryFeedbackRepository,
    BudgetRepository,
    AnomalyRepository,
    ForecastRepository,
    ForecastOutcomeRepository,
    RecurringSeriesRepository,
    InsightRepository,
    NotificationRepository,
)

# Keyed (non-`id`) repositories; the scoping tests introspect them too.
KEYED_REPOSITORIES: dict[str, type] = {"idempotency_keys": IdempotencyRepository}

# Tables with a ``user_id`` column but no single ``id`` key, so the generic repository does not
# fit. The owning task adds a keyed repository with the same user_id-first rule (PRD 12.4).
KEYED_PENDING: dict[str, str] = {
    "budget_period_snapshots": "T-21 (budgets): keyed by (budget_id, period_id)",
    "anomaly_suppressions": "T-23 (anomaly feedback): keyed by (user_id, merchant_key)",
    "user_segments": "T-27 (clustering): one row per user",
}

# Tables that carry a user_id but are not owned through the scoped repositories, with the reason.
UNSCOPED_BY_DESIGN: dict[str, str] = {
    "refresh_tokens": "looked up by token hash before the user is known; see repositories/auth.py",
    "outbox_events": "no FK on purpose; written by the event publisher inside the same transaction",
}

__all__ = [
    "KEYED_REPOSITORIES",
    "IdempotencyRepository",
    "TransactionFilters",
    "TransactionRepository",
    "KEYED_PENDING",
    "SCOPED_REPOSITORIES",
    "UNSCOPED_BY_DESIGN",
    "CategoryRepository",
    "RefreshTokenStore",
    "ScopedRepository",
    "UserRepository",
]
