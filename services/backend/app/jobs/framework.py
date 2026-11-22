"""Job runner (PRD 15.1): idempotent runs, a ``job_runs`` row, chunks of users, per-user isolation.

A job is either per-user (``fn(session, user, ctx) -> stats``) or global (``fn(session, ctx)``).
Each user runs in its own transaction: an error rolls that user back, is counted and logged with
the pseudonymous id, and the run goes on. A run with at least one failed user ends as ``failed``
(the ``JobFailed`` alert) and can simply be re-run: every job is safe to repeat for the same date.
A second run of the same job while one is in progress is refused (PostgreSQL advisory lock), which
also covers Cloud Scheduler retries.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import uuid
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

import structlog
from sqlalchemy import ColumnElement, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.ids import new_uuid7
from app.core.logging import pseudonymize
from app.core.metrics import observe_job
from app.jobs.config import JobsConfig, load_jobs_config
from app.models import JobRun, User
from app.models.base import utcnow

log = structlog.get_logger("app.jobs")

Status = Literal["succeeded", "failed", "skipped"]


@dataclass
class JobContext:
    settings: Settings
    now: dt.datetime
    cfg: JobsConfig = field(default_factory=load_jobs_config)
    ml: Any = None  # MlClient when a job needs the ML service (recategorize-needs-review)


@dataclass(frozen=True)
class JobSpec:
    name: str
    description: str
    user_fn: Callable[[Session, User, JobContext], dict[str, int]] | None = None
    global_fn: Callable[[Session, JobContext], dict[str, int]] | None = None
    eligible: Callable[[JobContext], ColumnElement[bool] | None] | None = None


@dataclass
class JobResult:
    job: str
    status: Status
    run_id: uuid.UUID | None = None
    users: int = 0
    errors: int = 0
    stats: dict[str, int] = field(default_factory=dict)
    error: str | None = None


class JobFailed(Exception):
    pass


def _lock_key(name: str) -> int:
    return int.from_bytes(hashlib.sha256(name.encode()).digest()[:7], "big")  # fits a bigint


def _start(factory: sessionmaker[Session], name: str) -> uuid.UUID:
    with factory() as session:
        run_id = new_uuid7()
        session.add(
            JobRun(id=run_id, job_name=name, started_at=utcnow(), status="running", stats={})
        )
        session.commit()
    return run_id


def _finish(factory: sessionmaker[Session], run_id: uuid.UUID, result: JobResult) -> None:
    with factory() as session:
        run = session.get(JobRun, run_id)
        if run is not None:
            run.finished_at = utcnow()
            run.status = "failed" if result.status == "failed" else "succeeded"
            run.stats = {"users": result.users, "errors": result.errors, **result.stats}
            run.error = result.error
            session.commit()


def _user_ids(
    factory: sessionmaker[Session], spec: JobSpec, ctx: JobContext, after: uuid.UUID | None
) -> list[uuid.UUID]:
    stmt = select(User.id).order_by(User.id).limit(ctx.cfg.chunk_size)
    if after is not None:
        stmt = stmt.where(User.id > after)
    if spec.eligible is not None:
        condition = spec.eligible(ctx)
        if condition is not None:
            stmt = stmt.where(condition)
    with factory() as session:
        return list(session.execute(stmt).scalars())


def _run_user(
    factory: sessionmaker[Session],
    spec: JobSpec,
    ctx: JobContext,
    user_id: uuid.UUID,
    totals: Counter[str],
    failures: Counter[str],
) -> bool:
    assert spec.user_fn is not None
    with factory() as session:
        try:
            user = session.get(User, user_id)
            if user is None:
                return True  # deleted between listing and processing
            for key, value in spec.user_fn(session, user, ctx).items():
                totals[key] += value
            session.commit()
            return True
        except Exception as exc:  # per-user isolation: count it, log it, carry on
            session.rollback()
            failures[type(exc).__name__] += 1
            log.warning(
                "job.user_failed",
                job=spec.name,
                user_pseudo_id=pseudonymize(
                    str(user_id), ctx.settings.export_pseudonym_key.get_secret_value()
                ),
                error_type=type(exc).__name__,
            )
            return False


def _execute(factory: sessionmaker[Session], spec: JobSpec, ctx: JobContext) -> JobResult:
    result = JobResult(job=spec.name, status="succeeded")
    totals: Counter[str] = Counter()
    failures: Counter[str] = Counter()
    if spec.global_fn is not None:
        with factory() as session:
            try:
                totals.update(spec.global_fn(session, ctx))
                session.commit()
            except Exception as exc:
                session.rollback()
                failures[type(exc).__name__] += 1
    else:
        after: uuid.UUID | None = None
        while True:
            ids = _user_ids(factory, spec, ctx, after)
            if not ids:
                break
            for user_id in ids:
                result.users += 1
                _run_user(factory, spec, ctx, user_id, totals, failures)
            after = ids[-1]
    result.stats = dict(totals)
    result.errors = sum(failures.values())
    if failures:
        result.status = "failed"
        result.error = "; ".join(f"{name} x{n}" for name, n in sorted(failures.items()))
    return result


def run_job(factory: sessionmaker[Session], spec: JobSpec, ctx: JobContext) -> JobResult:
    """Run one job end to end. Never raises for per-user errors; returns the result."""
    with factory() as probe:
        lock = probe.connection()
        got = lock.execute(
            text("SELECT pg_try_advisory_lock(:k)"), {"k": _lock_key(spec.name)}
        ).scalar_one()
        if not got:
            log.info("job.skipped_already_running", job=spec.name)
            return JobResult(job=spec.name, status="skipped", error="already running")
        run_id = _start(factory, spec.name)
        try:
            try:
                with observe_job(spec.name):
                    result = _execute(factory, spec, ctx)
                    if result.status == "failed":
                        raise JobFailed(result.error)
            except JobFailed:
                pass  # observe_job counted the run as an error; ``result`` carries the details
            result.run_id = run_id
            _finish(factory, run_id, result)
            log.info(
                "job.finished",
                job=spec.name,
                status=result.status,
                users=result.users,
                errors=result.errors,
                **{f"stat_{k}": v for k, v in result.stats.items()},
            )
            return result
        finally:
            lock.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _lock_key(spec.name)})
            probe.commit()
