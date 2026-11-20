"""CSV import endpoints (PRD 7.2.3, 13.2). Registered before ``/transactions/{id}``."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Header, Query, Request, Response, UploadFile
from fastapi.responses import JSONResponse

from app.api.deps import CurrentUser, SessionDep, SettingsDep
from app.api.transactions import IdempotencyHeader, run_idempotent
from app.schemas.imports import CommitRequest, ImportPreview
from app.services.idempotency import validate_key
from app.services.imports import (
    MAX_FILE_BYTES,
    PAGE_SIZE,
    ImportService,
    file_too_large,
    template_csv,
)

router = APIRouter(prefix="/transactions/imports", tags=["imports"])


def _service(
    request: Request, session: SessionDep, settings: SettingsDep, user: CurrentUser
) -> ImportService:
    return ImportService(
        session, settings, user, request_id=getattr(request.state, "request_id", None)
    )


ServiceDep = Annotated[ImportService, Depends(_service)]


@router.get("/template.csv")
def template(user: CurrentUser) -> Response:
    today = dt.datetime.now(ZoneInfo(user.timezone)).date()
    return Response(
        template_csv(today),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="transactions-template.csv"'},
    )


@router.post("", status_code=201, response_model=ImportPreview)
def create_import(
    service: ServiceDep,
    file: Annotated[UploadFile, File()],
    content_length: Annotated[int | None, Header()] = None,
) -> ImportPreview:
    # Reject oversized bodies by header first; the read below is capped as well (FR-02.10).
    if content_length is not None and content_length > MAX_FILE_BYTES + 64 * 1024:
        raise file_too_large()
    raw = file.file.read(MAX_FILE_BYTES + 1)
    return service.preview(raw, file.filename)


@router.get("/{import_id}", response_model=ImportPreview)
def get_import(
    import_id: uuid.UUID,
    service: ServiceDep,
    cursor: Annotated[str | None, Query(max_length=1000)] = None,
    limit: Annotated[int, Query(ge=1, le=PAGE_SIZE)] = PAGE_SIZE,
) -> ImportPreview:
    return service.get(import_id, cursor, limit)


@router.post("/{import_id}/commit")
def commit_import(
    import_id: uuid.UUID,
    body: CommitRequest,
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
        status_code=200,
        work=lambda: service.commit(import_id, body),
    )


@router.delete("/{import_id}", status_code=204)
def discard_import(import_id: uuid.UUID, service: ServiceDep) -> Response:
    service.discard(import_id)
    return Response(status_code=204)
