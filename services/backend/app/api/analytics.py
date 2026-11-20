"""GET /analytics/* (PRD 7.4, 13.2). Read-only; every figure is computed in SQL."""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import CurrentUser, SessionDep
from app.schemas.analytics import (
    CategoriesOut,
    MerchantsOut,
    MethodsOut,
    RangeName,
    SummaryOut,
    TrendsOut,
)
from app.services.analytics import AnalyticsService, Window

router = APIRouter(prefix="/analytics", tags=["analytics"])


def get_now(request: Request) -> dt.datetime:
    """The clock, as a dependency so tests can pin "today"."""
    return dt.datetime.now(dt.UTC)


def _service(
    session: SessionDep, user: CurrentUser, now: Annotated[dt.datetime, Depends(get_now)]
) -> AnalyticsService:
    return AnalyticsService(session, user, now)


ServiceDep = Annotated[AnalyticsService, Depends(_service)]
GranularityParam = Literal["auto", "day", "week", "month"]


def _window(
    service: ServiceDep,
    range: Annotated[RangeName, Query()] = "current_period",
    date_from: Annotated[dt.date | None, Query()] = None,
    date_to: Annotated[dt.date | None, Query()] = None,
) -> Window:
    return service.window(range, date_from, date_to)


WindowDep = Annotated[Window, Depends(_window)]


@router.get("/summary", response_model=SummaryOut)
def summary(service: ServiceDep, window: WindowDep) -> SummaryOut:
    return service.summary(window)


@router.get("/categories", response_model=CategoriesOut)
def categories(service: ServiceDep, window: WindowDep) -> CategoriesOut:
    return service.categories(window)


@router.get("/trends", response_model=TrendsOut)
def trends(
    service: ServiceDep,
    window: WindowDep,
    granularity: Annotated[GranularityParam, Query()] = "auto",
) -> TrendsOut:
    return service.trends(window, None if granularity == "auto" else granularity)


@router.get("/merchants", response_model=MerchantsOut)
def merchants(
    service: ServiceDep,
    window: WindowDep,
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
) -> MerchantsOut:
    return service.merchants(window, limit)


@router.get("/payment-methods", response_model=MethodsOut)
def payment_methods(service: ServiceDep, window: WindowDep) -> MethodsOut:
    return service.payment_methods(window)
