"""Anomalies API (PRD 7.6, 13.2): list, detail, feedback; mounted under ``/intelligence``."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.analytics import get_now
from app.api.deps import CurrentUser, SessionDep, SettingsDep
from app.schemas.anomalies import (
    AnomalyFeedback,
    AnomalyOut,
    AnomalyPage,
    AnomalyStatus,
    AnomalyType,
    Severity,
)
from app.services.anomalies import AnomalyService

router = APIRouter(prefix="/intelligence/anomalies", tags=["intelligence"])


def _service(
    session: SessionDep, user: CurrentUser, now: Annotated[dt.datetime, Depends(get_now)]
) -> AnomalyService:
    return AnomalyService(session, user, now)


ServiceDep = Annotated[AnomalyService, Depends(_service)]


@router.get("", response_model=AnomalyPage)
def list_anomalies(
    service: ServiceDep,
    settings: SettingsDep,
    status: Annotated[list[AnomalyStatus] | None, Query()] = None,
    severity: Severity | None = None,
    type: AnomalyType | None = None,
    period_id: dt.date | None = None,
    alerts_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(max_length=1000)] = None,
) -> AnomalyPage:
    return service.page(
        statuses=list(status) if status else None,
        severity=severity,
        anomaly_type=type,
        period_id=period_id,
        alerts_only=alerts_only,
        limit=limit,
        cursor=cursor,
        secret=settings.cursor_signing_key.get_secret_value(),
    )


@router.get("/{anomaly_id}", response_model=AnomalyOut)
def get_anomaly(anomaly_id: uuid.UUID, service: ServiceDep) -> AnomalyOut:
    return service.get(anomaly_id)


@router.post("/{anomaly_id}/feedback", response_model=AnomalyOut)
def anomaly_feedback(
    anomaly_id: uuid.UUID, body: AnomalyFeedback, service: ServiceDep
) -> AnomalyOut:
    return service.feedback(anomaly_id, body)
