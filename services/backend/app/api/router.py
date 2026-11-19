"""Versioned API router. Feature routers (auth, transactions, ...) are added here."""

from fastapi import APIRouter

api_router = APIRouter(prefix="/api/v1")
