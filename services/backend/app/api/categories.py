"""GET /categories: global seeded taxonomy, cacheable with an ETag (PRD 13.2)."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated

from fastapi import APIRouter, Header, Response
from fastapi.responses import JSONResponse

from app.api.deps import CurrentUser, SessionDep
from app.repositories import CategoryRepository
from app.schemas.transactions import CategoryOut

router = APIRouter(prefix="/categories", tags=["categories"])


@router.get("", response_model=list[CategoryOut])
def list_categories(
    session: SessionDep,
    _user: CurrentUser,
    if_none_match: Annotated[str | None, Header(alias="If-None-Match")] = None,
) -> Response:
    items = [
        CategoryOut(id=c.id, slug=c.slug, name=c.name, transaction_type=c.transaction_type)
        for c in CategoryRepository(session).list()
    ]
    body = [i.model_dump(mode="json") for i in items]
    etag = '"' + hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:32] + '"'
    headers = {"ETag": etag, "Cache-Control": "private, max-age=3600"}
    if if_none_match == etag:
        return Response(status_code=304, headers=headers)
    return JSONResponse(body, headers=headers)
