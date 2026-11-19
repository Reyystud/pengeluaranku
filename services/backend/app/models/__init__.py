"""SQLAlchemy models. Importing this package registers every table on ``Base.metadata``."""

from app.models.base import Base
from app.models.insights import (
    Anomaly,
    AnomalySuppression,
    Budget,
    BudgetPeriodSnapshot,
    Forecast,
    ForecastOutcome,
    Insight,
    Notification,
    RecurringSeries,
    RecurringSeriesTransaction,
    UserSegment,
)
from app.models.platform import (
    DeletionRequest,
    IdempotencyKey,
    JobRun,
    OutboxEvent,
    ProcessedEvent,
)
from app.models.transactions import (
    CategoryFeedback,
    CategoryPrediction,
    MerchantRule,
    Transaction,
    TransactionImport,
)
from app.models.users import Category, RefreshToken, User

__all__ = [
    "Anomaly",
    "AnomalySuppression",
    "Base",
    "Budget",
    "BudgetPeriodSnapshot",
    "Category",
    "CategoryFeedback",
    "CategoryPrediction",
    "DeletionRequest",
    "Forecast",
    "ForecastOutcome",
    "IdempotencyKey",
    "Insight",
    "JobRun",
    "MerchantRule",
    "Notification",
    "OutboxEvent",
    "ProcessedEvent",
    "RecurringSeries",
    "RecurringSeriesTransaction",
    "RefreshToken",
    "Transaction",
    "TransactionImport",
    "User",
    "UserSegment",
]
