"""``python -m pipelines train --model transaction-classifier --dataset synthetic/v1``."""

from __future__ import annotations

import argparse
import os
import sys

from pipelines.data_steps import PipelineError


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
    args = parser.parse_args(argv)

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
