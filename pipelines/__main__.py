"""``python -m pipelines train --model transaction-classifier --dataset synthetic/v1``."""

from __future__ import annotations

import argparse
import os
import sys

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
    args = parser.parse_args(argv)

    if args.command in ("promote", "rollback"):
        return _alias_command(args)

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
