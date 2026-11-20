"""Forecast API (PRD 7.7, 13.2): ``GET /intelligence/forecast``."""

from __future__ import annotations

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.analytics import get_now
from app.api.deps import CurrentUser, SessionDep
from app.schemas.forecasts import ForecastResponse
from app.services.forecasts import ForecastService

router = APIRouter(prefix="/intelligence/forecast", tags=["intelligence"])


@router.get("", response_model=ForecastResponse)
def get_forecast(
    session: SessionDep,
    user: CurrentUser,
    now: Annotated[dt.datetime, Depends(get_now)],
    category: Annotated[str | None, Query(max_length=64)] = None,
) -> ForecastResponse:
    return ForecastService(session, user, now).get(category)
