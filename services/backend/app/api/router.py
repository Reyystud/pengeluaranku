"""Versioned API router. Feature routers (auth, transactions, ...) are added here."""

from fastapi import APIRouter

from app.api import (
    analytics,
    anomalies,
    auth,
    budgets,
    categories,
    forecasts,
    imports,
    insights,
    merchant_rules,
    notifications,
    recurring,
    transactions,
    users,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(categories.router)
api_router.include_router(imports.router)  # before /transactions/{id}
api_router.include_router(transactions.router)
api_router.include_router(merchant_rules.router)
api_router.include_router(analytics.router)
api_router.include_router(budgets.router)
api_router.include_router(notifications.router)
api_router.include_router(anomalies.router)
api_router.include_router(forecasts.router)
api_router.include_router(recurring.router)
api_router.include_router(insights.router)
