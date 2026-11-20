"""Budgets API (PRD 7.5, 13.2)."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.api.analytics import get_now
from app.api.deps import CurrentUser, SessionDep
from app.schemas.budgets import (
    BudgetCreate,
    BudgetHistory,
    BudgetList,
    BudgetOut,
    BudgetUpdate,
)
from app.services.budgets import BudgetService

router = APIRouter(prefix="/budgets", tags=["budgets"])


def _service(
    session: SessionDep, user: CurrentUser, now: Annotated[dt.datetime, Depends(get_now)]
) -> BudgetService:
    return BudgetService(session, user, now)


ServiceDep = Annotated[BudgetService, Depends(_service)]


@router.get("", response_model=BudgetList)
def list_budgets(service: ServiceDep) -> BudgetList:
    return service.list()


@router.post("", status_code=201, response_model=BudgetOut)
def create_budget(body: BudgetCreate, service: ServiceDep) -> BudgetOut:
    return service.create(body)


@router.get("/{budget_id}", response_model=BudgetOut)
def get_budget(budget_id: uuid.UUID, service: ServiceDep) -> BudgetOut:
    return service.get(budget_id)


@router.patch("/{budget_id}", response_model=BudgetOut)
def update_budget(budget_id: uuid.UUID, body: BudgetUpdate, service: ServiceDep) -> BudgetOut:
    return service.update(budget_id, body)


@router.delete("/{budget_id}", status_code=204)
def delete_budget(budget_id: uuid.UUID, service: ServiceDep) -> Response:
    service.delete(budget_id)
    return Response(status_code=204)


@router.get("/{budget_id}/history", response_model=BudgetHistory)
def budget_history(
    budget_id: uuid.UUID, service: ServiceDep, limit: Annotated[int, Query(ge=1, le=60)] = 12
) -> BudgetHistory:
    return service.history(budget_id, limit)
