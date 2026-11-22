"""Internal endpoints of the worker (PRD 13.2): called by Pub/Sub push and Cloud Scheduler only.

Not part of the public OpenAPI document. Every route verifies a Google OIDC token
(``app.core.internal_auth``). ``POST /internal/jobs/{name}`` runs a batch job (T-37).
"""

from __future__ import annotations

import base64
import binascii
import datetime as dt
import json
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict

from app.api.deps import SessionDep
from app.core.errors import ProblemError
from app.core.internal_auth import require_internal_caller
from app.events.dispatcher import dispatch
from app.events.schema import InvalidEvent, validate_envelope
from app.jobs.catalogue import JOBS
from app.jobs.framework import JobContext, run_job
from app.models import User

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/internal",
    tags=["internal"],
    dependencies=[Depends(require_internal_caller)],
    include_in_schema=False,
)


class PushMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    data: str


class PushBody(BaseModel):
    """Pub/Sub push envelope: ``{"message": {"data": <base64 json>, ...}, "subscription": ...}``."""

    model_config = ConfigDict(extra="ignore")
    message: PushMessage


def _invalid(reason: str) -> ProblemError:
    # 4xx is not an ack: Pub/Sub retries and finally dead-letters it, where it can be inspected.
    return ProblemError(400, "INVALID_EVENT", "Invalid event", reason)


@router.post("/events/transaction", status_code=204)
def receive_transaction_event(body: PushBody, session: SessionDep) -> Response:
    """Consume one ``transaction.*`` / ``import.committed`` event (FR-11).

    2xx acknowledges (handled, duplicate, stale, or the user no longer exists). A failing
    consumer raises, the transaction (and its idempotency claims) rolls back, the response is a
    5xx and Pub/Sub retries with backoff (10-600 s, 5 attempts) before dead-lettering.
    """
    try:
        envelope = json.loads(base64.b64decode(body.message.data, validate=True))
    except (binascii.Error, ValueError) as exc:
        raise _invalid("The message data is not base64 encoded JSON.") from exc
    try:
        validate_envelope(envelope)
    except InvalidEvent as exc:
        raise _invalid(str(exc)) from exc
    user = session.get(User, uuid.UUID(envelope["user_id"]))
    if user is None:  # the account was deleted after the event was written
        log.info("event for a deleted user acknowledged: %s", envelope["event_type"])
        return Response(status_code=204)
    dispatch(session, user, [(uuid.UUID(envelope["event_id"]), envelope)])
    log.info("event consumed: %s", envelope["event_type"])
    return Response(status_code=204)


class JobRunOut(BaseModel):
    job: str
    status: str
    run_id: uuid.UUID | None
    users: int
    errors: int
    stats: dict[str, int]
    error: str | None


@router.post("/jobs/{name}", response_model=JobRunOut)
def run_batch_job(
    name: str,
    request: Request,
    date: Annotated[dt.date | None, Query()] = None,
) -> JobRunOut:
    """Run one batch job now (Cloud Scheduler, PRD 15.1). The run is synchronous.

    ``?date=YYYY-MM-DD`` runs as if it were that UTC date at 12:00 (replays and tests). A job that
    is already running answers ``skipped``; a run with failed users answers 200 with
    ``status=failed`` and is recorded in ``job_runs``. The caller decides whether to retry.
    """
    spec = JOBS.get(name)
    if spec is None:
        raise ProblemError(404, "JOB_NOT_FOUND", "Unknown job", f"The backend has no job {name!r}.")
    factory = request.app.state.session_factory
    if factory is None:
        raise ProblemError(503, "SERVICE_UNAVAILABLE", "Service unavailable", "No database.")
    now = (
        dt.datetime.combine(date, dt.time(12), tzinfo=dt.UTC)
        if date is not None
        else dt.datetime.now(dt.UTC)
    )
    ctx = JobContext(request.app.state.settings, now, ml=request.app.state.ml_client)
    result = run_job(factory, spec, ctx)
    return JobRunOut(
        job=result.job,
        status=result.status,
        run_id=result.run_id,
        users=result.users,
        errors=result.errors,
        stats=result.stats,
        error=result.error,
    )
