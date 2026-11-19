"""Versioned API router. Feature routers (auth, transactions, ...) are added here."""

from fastapi import APIRouter

from app.api import auth, categories, transactions, users

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(categories.router)
api_router.include_router(transactions.router)
