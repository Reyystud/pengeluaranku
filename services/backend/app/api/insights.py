"""Insights API (PRD 7.9, 13.2): list, dismiss, refresh."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.analytics import get_now
from app.api.deps import CurrentUser, SessionDep, enforce_rate_limit, get_limiter
from app.core.ratelimit import RateLimiter
from app.schemas.insights import InsightList, InsightOut, RefreshOut
from app.services.insights import InsightService

router = APIRouter(prefix="/intelligence/insights", tags=["intelligence"])


@router.get("", response_model=InsightList)
def list_insights(
    session: SessionDep,
    user: CurrentUser,
    now: Annotated[dt.datetime, Depends(get_now)],
    period_id: Annotated[dt.date | None, Query()] = None,
    include_dismissed: Annotated[bool, Query()] = False,
    limit: Annotated[int | None, Query(ge=1, le=200)] = None,
) -> InsightList:
    """Highest priority first (warning, positive, info, then magnitude); ``limit=3`` is the
    dashboard card (FR-09.05)."""
    result = InsightService(session, user, now).listing(period_id, include_dismissed)
    if limit is not None:
        result.items = result.items[:limit]
    return result


@router.post("/refresh", response_model=RefreshOut)
def refresh_insights(
    session: SessionDep,
    user: CurrentUser,
    now: Annotated[dt.datetime, Depends(get_now)],
    limiter: Annotated[RateLimiter, Depends(get_limiter)],
) -> RefreshOut:
    enforce_rate_limit(limiter, "insights-refresh", user.id, 1, 60.0)  # 1 / min (FR-09.01)
    return InsightService(session, user, now).refresh()


@router.post("/{insight_id}/dismiss", response_model=InsightOut)
def dismiss_insight(
    insight_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
    now: Annotated[dt.datetime, Depends(get_now)],
) -> InsightOut:
    return InsightService(session, user, now).dismiss(insight_id)
