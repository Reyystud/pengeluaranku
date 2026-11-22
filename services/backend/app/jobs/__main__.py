"""``python -m app.jobs <name> [--date YYYY-MM-DD]``: run one job now (``make jobs-run``)."""

from __future__ import annotations

import argparse
import datetime as dt
import sys

from app.clients.ml import MlClient
from app.core.config import Settings
from app.core.db import create_session_factory, register_readiness
from app.jobs.catalogue import JOBS
from app.jobs.framework import JobContext, run_job


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.jobs")
    parser.add_argument("job", nargs="?", choices=sorted(JOBS))
    parser.add_argument("--date", default=None, help="run as if it were this UTC date at 12:00")
    parser.add_argument("--list", action="store_true", help="list the jobs and exit")
    args = parser.parse_args(argv)
    if args.list or args.job is None:
        for name, spec in sorted(JOBS.items()):
            print(f"{name:28} {spec.description}")
        return 0
    settings = Settings()
    engine = register_readiness({}, settings)
    if engine is None:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2
    now = (
        dt.datetime.combine(dt.date.fromisoformat(args.date), dt.time(12), tzinfo=dt.UTC)
        if args.date
        else dt.datetime.now(dt.UTC)
    )
    result = run_job(
        create_session_factory(engine),
        JOBS[args.job],
        JobContext(settings, now, ml=MlClient(settings)),
    )
    print(
        f"{result.job}: {result.status} users={result.users} errors={result.errors} "
        f"stats={result.stats}" + (f" error={result.error}" if result.error else "")
    )
    return 0 if result.status == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
