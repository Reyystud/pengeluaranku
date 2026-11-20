"""Transactions API (PRD 13.2, FR-02)."""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Callable
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.deps import (
    CurrentUser,
    SessionDep,
    SettingsDep,
    enforce_rate_limit,
    get_limiter,
    get_ml_client,
)
from app.clients.ml import MlClient
from app.core.ratelimit import RateLimiter
from app.schemas.transactions import (
    BulkCategorize,
    BulkDelete,
    CategorizePreview,
    CategorizePreviewOut,
    CountOut,
    RecategorizeRequest,
    TransactionCreate,
    TransactionCreated,
    TransactionOut,
    TransactionPage,
    TransactionUpdate,
    TransactionUpdated,
)
from app.services.categorization import MlCategorizer
from app.services.idempotency import IdempotencyService, validate_key
from app.services.transactions import DEFAULT_LIMIT, MAX_LIMIT, ListQuery, TransactionService

router = APIRouter(prefix="/transactions", tags=["transactions"])

IdempotencyHeader = Annotated[str | None, Header(alias="Idempotency-Key")]


def _service(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    user: CurrentUser,
    ml: Annotated[MlClient, Depends(get_ml_client)],
) -> TransactionService:
    request_id = getattr(request.state, "request_id", None)
    service = TransactionService(session, settings, user, request_id=request_id)
    service.categorizer = MlCategorizer(session, ml, service.by_slug, service.by_id)
    return service


ServiceDep = Annotated[TransactionService, Depends(_service)]


def list_query(
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    transaction_type: Literal["income", "expense", "transfer"] | None = None,
    category: Annotated[list[str] | None, Query()] = None,
    payment_method: Annotated[list[str] | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    min_amount: Decimal | None = None,
    max_amount: Decimal | None = None,
    category_status: Literal[
        "auto", "suggested", "needs_review", "rule", "user_set", "user_confirmed"
    ]
    | None = None,
    possible_duplicate: bool | None = None,
    sort: Literal["date", "amount"] = "date",
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    cursor: Annotated[str | None, Query(max_length=1000)] = None,
) -> ListQuery:
    return ListQuery(
        date_from=date_from,
        date_to=date_to,
        transaction_type=transaction_type,
        category=category or [],
        payment_method=payment_method or [],
        q=q,
        min_amount=min_amount,
        max_amount=max_amount,
        category_status=category_status,
        possible_duplicate=possible_duplicate,
        sort=sort,
        limit=limit,
        cursor=cursor,
    )


QueryDep = Annotated[ListQuery, Depends(list_query)]


def run_idempotent(
    *,
    session: SessionDep,
    user: CurrentUser,
    request: Request,
    key: str | None,
    body: BaseModel | None,
    status_code: int,
    work: Callable[[], BaseModel],
) -> JSONResponse:
    """Run ``work`` once per ``(user, key)``; replay the stored response for repeats (13.1.5)."""
    service = IdempotencyService(session) if key else None
    payload: Any = body.model_dump(mode="json") if body is not None else None
    if service and key:
        replay = service.begin(user.id, key, request.method, request.url.path, payload)
        if replay is not None:
            return JSONResponse(
                replay.body, status_code=replay.status, headers={"Idempotent-Replayed": "true"}
            )
    result = work().model_dump(mode="json")
    if service and key:
        service.complete(user.id, key, status_code, result)
    return JSONResponse(result, status_code=status_code)


@router.get("", response_model=TransactionPage)
def list_transactions(query: QueryDep, service: ServiceDep) -> TransactionPage:
    return service.search(query)


@router.get("/count", response_model=CountOut)
def count_transactions(query: QueryDep, service: ServiceDep) -> CountOut:
    return CountOut(count=service.count(query))


@router.post("", status_code=201, response_model=TransactionCreated)
def create_transaction(
    body: TransactionCreate,
    request: Request,
    session: SessionDep,
    user: CurrentUser,
    service: ServiceDep,
    idempotency_key: IdempotencyHeader = None,
) -> JSONResponse:
    key = validate_key(idempotency_key, required=True)
    return run_idempotent(
        session=session,
        user=user,
        request=request,
        key=key,
        body=body,
        status_code=201,
        work=lambda: service.create(body),
    )


@router.post("/categorize-preview", response_model=CategorizePreviewOut)
def categorize_preview(
    body: CategorizePreview,
    user: CurrentUser,
    service: ServiceDep,
    limiter: Annotated[RateLimiter, Depends(get_limiter)],
) -> CategorizePreviewOut:
    enforce_rate_limit(limiter, "categorize-preview", user.id, 60, 60.0)  # 60 / min (13.1.6)
    return service.preview_category(body)


@router.post("/bulk-delete")
def bulk_delete(
    body: BulkDelete,
    request: Request,
    session: SessionDep,
    user: CurrentUser,
    service: ServiceDep,
    idempotency_key: IdempotencyHeader = None,
) -> JSONResponse:
    key = validate_key(idempotency_key, required=True)

    class Deleted(BaseModel):
        deleted: int

    return run_idempotent(
        session=session,
        user=user,
        request=request,
        key=key,
        body=body,
        status_code=200,
        work=lambda: Deleted(deleted=service.bulk_delete(body.ids)),
    )


@router.post("/bulk-categorize")
def bulk_categorize(
    body: BulkCategorize,
    request: Request,
    session: SessionDep,
    user: CurrentUser,
    service: ServiceDep,
    idempotency_key: IdempotencyHeader = None,
) -> JSONResponse:
    key = validate_key(idempotency_key, required=True)

    class Updated(BaseModel):
        updated: int

    return run_idempotent(
        session=session,
        user=user,
        request=request,
        key=key,
        body=body,
        status_code=200,
        work=lambda: Updated(updated=service.bulk_categorize(body.ids, body.category)),
    )


@router.get("/{transaction_id}", response_model=TransactionOut)
def get_transaction(transaction_id: uuid.UUID, service: ServiceDep) -> TransactionOut:
    return service.get(transaction_id)


@router.patch("/{transaction_id}", response_model=TransactionUpdated)
def update_transaction(
    transaction_id: uuid.UUID,
    body: TransactionUpdate,
    service: ServiceDep,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> TransactionUpdated:
    return service.update(transaction_id, body, if_match)


@router.post("/{transaction_id}/confirm-category", response_model=TransactionOut)
def confirm_category(transaction_id: uuid.UUID, service: ServiceDep) -> TransactionOut:
    return service.confirm_category(transaction_id)


@router.post("/{transaction_id}/recategorize", response_model=TransactionCreated)
def recategorize(
    transaction_id: uuid.UUID, service: ServiceDep, body: RecategorizeRequest | None = None
) -> TransactionCreated:
    return service.recategorize(transaction_id, force=body.force if body else False)


@router.post("/{transaction_id}/dismiss-duplicate", response_model=TransactionOut)
def dismiss_duplicate(transaction_id: uuid.UUID, service: ServiceDep) -> TransactionOut:
    return service.dismiss_duplicate(transaction_id)


@router.delete("/{transaction_id}", status_code=204)
def delete_transaction(transaction_id: uuid.UUID, service: ServiceDep) -> Response:
    service.delete(transaction_id)
    return Response(status_code=204)
