"""Recurring API (PRD 7.8, 13.2): ``GET /intelligence/recurring``, ``PATCH .../{id}``."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.analytics import get_now
from app.api.deps import CurrentUser, SessionDep
from app.schemas.recurring import RecurringList, RecurringOut, RecurringPatch
from app.services.recurring import RecurringService

router = APIRouter(prefix="/intelligence/recurring", tags=["intelligence"])


def _service(
    session: SessionDep, user: CurrentUser, now: Annotated[dt.datetime, Depends(get_now)]
) -> RecurringService:
    return RecurringService(session, user, now)


ServiceDep = Annotated[RecurringService, Depends(_service)]


@router.get("", response_model=RecurringList)
def list_recurring(service: ServiceDep) -> RecurringList:
    return service.overview()


@router.patch("/{series_id}", response_model=RecurringOut)
def patch_recurring(
    series_id: uuid.UUID, body: RecurringPatch, service: ServiceDep
) -> RecurringOut:
    return service.patch(series_id, body)
