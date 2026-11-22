"""Data-access layer (PRD 12.4). One repository per user-owned table, plus users and categories."""

from __future__ import annotations

from typing import Any

from app.models import ForecastOutcome
from app.repositories.anomalies import AnomalyRepository, AnomalySuppressionRepository
from app.repositories.auth import RefreshTokenStore
from app.repositories.base import ScopedRepository
from app.repositories.budgets import BudgetRepository
from app.repositories.categorization import (
    CategoryFeedbackRepository,
    CategoryPredictionRepository,
    MerchantRuleRepository,
)
from app.repositories.forecasts import ForecastRepository
from app.repositories.idempotency import IdempotencyRepository
from app.repositories.imports import TransactionImportRepository
from app.repositories.insights import InsightRepository
from app.repositories.notifications import NotificationRepository
from app.repositories.recurring import RecurringSeriesRepository
from app.repositories.transactions import TransactionFilters, TransactionRepository
from app.repositories.users import CategoryRepository, UserRepository


class ForecastOutcomeRepository(ScopedRepository[ForecastOutcome]):
    model = ForecastOutcome


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
KEYED_REPOSITORIES: dict[str, type] = {
    "idempotency_keys": IdempotencyRepository,
    "budget_period_snapshots": BudgetRepository,  # keyed by (budget_id, period_id)
    "anomaly_suppressions": AnomalySuppressionRepository,  # keyed by (user_id, merchant_key)
}

# Tables with a ``user_id`` column but no single ``id`` key, so the generic repository does not
# fit. The owning task adds a keyed repository with the same user_id-first rule (PRD 12.4).
KEYED_PENDING: dict[str, str] = {
    "user_segments": "T-27 (clustering): one row per user",
}

# Tables that carry a user_id but are not owned through the scoped repositories, with the reason.
UNSCOPED_BY_DESIGN: dict[str, str] = {
    "refresh_tokens": "looked up by token hash before the user is known; see repositories/auth.py",
    "outbox_events": "no FK on purpose; written by the event publisher inside the same transaction",
}

__all__ = [
    "AnomalyRepository",
    "ForecastRepository",
    "AnomalySuppressionRepository",
    "BudgetRepository",
    "NotificationRepository",
    "KEYED_REPOSITORIES",
    "IdempotencyRepository",
    "CategoryFeedbackRepository",
    "CategoryPredictionRepository",
    "MerchantRuleRepository",
    "TransactionFilters",
    "TransactionImportRepository",
    "TransactionRepository",
    "KEYED_PENDING",
    "SCOPED_REPOSITORIES",
    "UNSCOPED_BY_DESIGN",
    "CategoryRepository",
    "RefreshTokenStore",
    "ScopedRepository",
    "UserRepository",
]
