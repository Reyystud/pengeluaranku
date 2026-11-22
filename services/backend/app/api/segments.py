"""Behavior segment (PRD 7.13, 13.2: GET /intelligence/segment)."""

from __future__ import annotations

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.analytics import get_now
from app.api.deps import CurrentUser, SessionDep
from app.schemas.segments import SegmentOut
from app.services.segments import SegmentService

router = APIRouter(prefix="/intelligence/segment", tags=["intelligence"])


@router.get("", response_model=SegmentOut)
def get_segment(
    session: SessionDep, user: CurrentUser, now: Annotated[dt.datetime, Depends(get_now)]
) -> SegmentOut:
    """The user's segment with its defining traits, or the reason there is none yet."""
    return SegmentService(session, user, now).current()
