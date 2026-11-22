"""``python -m pipelines train --model transaction-classifier --dataset synthetic/v1``."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from pipelines.data_steps import PipelineError


def _alias_command(args: argparse.Namespace) -> int:
    from pipelines import promotion

    client = promotion.open_client(args.tracking_uri)
    try:
        if args.command == "promote":
            change = promotion.promote(
                client,
                args.model,
                args.version,
                actor=args.actor,
                reason=args.reason,
                force=args.force,
            )
        else:
            change = promotion.rollback(client, args.model, actor=args.actor, reason=args.reason)
    except PipelineError as exc:
        print(f"{args.command} refused: {exc}", file=sys.stderr)
        return 2
    print(
        f"{change.action}: {change.model} production "
        f"v{change.from_version or '-'} -> v{change.to_version}"
    )
    return 0


def _drift_command(args: argparse.Namespace) -> int:
    import datetime as dt
    import tempfile

    from pipelines.drift import job
    from pipelines.drift.config import load_config
    from pipelines.drift.sources import JsonlLogSource
    from pipelines.drift.store import LocalStore

    if not args.logs:
        print(
            "drift-report: BigQuery source needs GCP credentials and is not wired to the CLI yet; "
            "pass --logs <file> (docs/DECISIONS.md, T-35)",
            file=sys.stderr,
        )
        return 2
    day = dt.date.fromisoformat(args.date) if args.date else dt.datetime.now(dt.UTC).date()
    root = Path(__file__).resolve().parents[1]
    try:
        with tempfile.TemporaryDirectory() as tmp:
            if args.reference is not None:
                ref_dir, version = args.reference, "local-reference"
            else:
                from pipelines.promotion import open_client

                ref_dir, version = job.fetch_reference(
                    open_client(args.tracking_uri), args.model, Path(tmp)
                )
            summary = job.run_drift_report(
                report_date=day,
                reference_dir=ref_dir,
                model_version=version,
                source=JsonlLogSource(args.logs),
                store=LocalStore(args.reports_dir or root / "data" / "reports"),
                cfg=load_config(),
            )
    except PipelineError as exc:
        print(f"drift-report stopped: {exc}", file=sys.stderr)
        return 2
    print(
        f"drift-report {summary.report_date}: {summary.status} "
        f"(rows {summary.current_rows}, psi_max {summary.psi_max})"
    )
    return 1 if summary.status == "drift" else 0


def _shadow_command(args: argparse.Namespace) -> int:
    import datetime as dt

    from pipelines.promotion import open_client
    from pipelines.shadow import job

    if not args.logs:
        print(
            "shadow-evaluate: the BigQuery source is not wired to the CLI yet; "
            "pass --logs <file> (docs/DECISIONS.md, T-39)",
            file=sys.stderr,
        )
        return 2
    day = dt.date.fromisoformat(args.date) if args.date else dt.datetime.now(dt.UTC).date()
    root = Path(__file__).resolve().parents[1]
    try:
        report, outcome = job.run(
            client=open_client(args.tracking_uri),
            model=args.model,
            log_files=args.logs,
            corrections_file=args.corrections,
            reports_dir=args.reports_dir or root / "data" / "reports",
            today=day,
            promote=not args.dry_run,
        )
    except PipelineError as exc:
        print(f"shadow-evaluate stopped: {exc}", file=sys.stderr)
        return 2
    for c in report.criteria:
        print(f"  {c.status:12} {c.name} value={c.value} threshold={c.threshold} {c.detail}")
    note = (
        " (promoted)"
        if outcome["promoted"]
        else f" ({outcome['refused']})"
        if "refused" in outcome
        else ""
    )
    print(f"shadow-evaluate {day}: {report.outcome}{note}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pipelines")
    sub = parser.add_subparsers(dest="command", required=True)
    train = sub.add_parser("train", help="run the train_model flow (PRD 16.1)")
    train.add_argument("--model", default="transaction-classifier")
    train.add_argument("--dataset", default="synthetic/v1")
    train.add_argument("--models", nargs="+", default=None, help="candidate subset (smoke runs)")
    train.add_argument("--max-rows-per-class", type=int, default=None)
    train.add_argument("--no-register", action="store_true")
    train.add_argument(
        "--orchestrator",
        choices=["auto", "prefect", "none"],
        default="auto",
        help="auto = Prefect when PREFECT_API_URL is set, otherwise the same steps run inline",
    )
    promote = sub.add_parser("promote", help="move alias production to a version (PRD 16.3)")
    rollback = sub.add_parser("rollback", help="swap production and previous (PRD 16.5)")
    for p in (promote, rollback):
        p.add_argument("--model", default="transaction-classifier")
        p.add_argument("--reason", default="")
        p.add_argument("--actor", default=os.environ.get("PROMOTE_ACTOR", "operator"))
        p.add_argument("--tracking-uri", default=None)
    promote.add_argument("--version", required=True)
    promote.add_argument(
        "--force", action="store_true", help="allow gate != passed; needs --reason"
    )
    shadow = sub.add_parser("shadow-evaluate", help="judge the candidate on shadow logs (PRD 16.4)")
    shadow.add_argument("--model", default="transaction-classifier")
    shadow.add_argument(
        "--date", default=None, help="evaluation date YYYY-MM-DD (default: today UTC)"
    )
    shadow.add_argument("--tracking-uri", default=None)
    shadow.add_argument("--logs", nargs="+", type=Path, help="captured ml-service log files")
    shadow.add_argument(
        "--corrections", type=Path, default=None, help="JSONL: input_hash, category"
    )
    shadow.add_argument("--reports-dir", type=Path, default=None, help="local report root")
    shadow.add_argument("--dry-run", action="store_true", help="evaluate only; never move aliases")
    drift = sub.add_parser("drift-report", help="Evidently drift report for one day (PRD 18.3)")
    drift.add_argument("--model", default="transaction-classifier")
    drift.add_argument("--date", default=None, help="report date YYYY-MM-DD (default: today UTC)")
    drift.add_argument("--tracking-uri", default=None)
    drift.add_argument("--logs", nargs="+", type=Path, help="captured ml-service log files")
    drift.add_argument(
        "--reference", type=Path, default=None, help="reference/ folder (skips MLflow)"
    )
    drift.add_argument("--reports-dir", type=Path, default=None, help="local report root")
    drift.add_argument("--project", default=os.environ.get("GCP_PROJECT_ID"), help="GCP project")
    args = parser.parse_args(argv)

    if args.command in ("promote", "rollback"):
        return _alias_command(args)
    if args.command == "drift-report":
        return _drift_command(args)
    if args.command == "shadow-evaluate":
        return _shadow_command(args)

    os.environ.setdefault("PYTHONHASHSEED", "0")  # recorded in the run; set it before launching
    from pipelines import train_flow

    use_prefect = args.orchestrator == "prefect" or (
        args.orchestrator == "auto" and bool(os.environ.get("PREFECT_API_URL"))
    )
    print(f"orchestrator: {'prefect' if use_prefect else 'none (inline steps)'}", flush=True)
    run = train_flow.build_flow() if use_prefect else train_flow.run_training

    try:
        result = run(
            args.model,
            args.dataset,
            models=args.models,
            max_rows_per_class=args.max_rows_per_class,
            register=not args.no_register,
        )
    except PipelineError as exc:
        print(f"pipeline stopped: {exc}", file=sys.stderr)
        return 2
    print(
        f"run {result.mlflow_run_id}: gate {result.gate}, "
        f"registered version {result.registered_version}"
    )
    return 0 if result.gate == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
