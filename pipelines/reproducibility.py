"""Re-run test (PRD 16.2, 21.1): train the baseline twice on a small dataset and compare.

Each run is a separate process with ``PYTHONHASHSEED=0``, so nothing is shared between them
except the files on disk. The check fails when the dataset or split hash differs, or when
``|macro F1(run 1) - macro F1(run 2)|`` exceeds ``reproducibility.max_macro_f1_delta``.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ml.classification.config import load_train_config

DATASET = "synthetic/repro"
ROOT = Path(__file__).resolve().parents[1]
MARKER = "REPRO_RESULT "


@dataclass(frozen=True)
class RunSummary:
    macro_f1: float
    winner: str
    split_hash: str
    dataset_sha256: str


def build_dataset(root: Path, cfg: dict[str, Any]) -> None:
    from data_generator.config import load_config
    from data_generator.generate import write_dataset
    from ml.evaluation.__main__ import main as splits_main

    spec = cfg["reproducibility"]
    gen = load_config(
        ROOT / "config" / "generator" / "default.yaml",
        seed=spec["data_seed"],
        n_users=spec["users"],
        months=spec["months"],
    )
    write_dataset(gen, root / "data" / DATASET)
    code = splits_main(
        [
            "make-splits",
            "--data", str(root / "data" / DATASET),
            "--dataset-version", DATASET,
            "--splits-dir", str(root / "data_splits"),
            "--assignments-dir", str(root / "data" / "splits"),
        ]
    )  # fmt: skip
    if code != 0:
        raise RuntimeError("make-splits failed")


def run_once(root: Path, work: Path) -> RunSummary:
    """One training run in this process (called in a child process by ``check``)."""
    from pipelines import train_flow

    spec = load_train_config()["reproducibility"]
    result = train_flow.run_training(
        "transaction-classifier",
        DATASET,
        models=list(spec["models"]),
        max_rows_per_class=int(spec["max_rows_per_class"]),
        root=str(root),
        mlflow_dir=str(work / "mlflow"),
        register=False,
        log=lambda _: None,
    )
    report = json.loads((result.run_dir / "evaluation" / "report.json").read_text("utf-8"))
    manifest = json.loads((root / "data" / DATASET / "manifest.json").read_text("utf-8"))
    return RunSummary(
        macro_f1=result.test_macro_f1,
        winner=result.winner,
        split_hash=str(report["dataset"]["split_hash"]),
        dataset_sha256=json.dumps(manifest["files_sha256"], sort_keys=True),
    )


def _child(root: Path, work: Path) -> RunSummary:
    env = {**os.environ, "PYTHONHASHSEED": "0", "MLFLOW_DISABLE_AGENT_HINT": "1"}
    env.pop("MLFLOW_TRACKING_URI", None)  # the child uses its own throw-away store
    out = subprocess.run(
        [sys.executable, "-m", "pipelines.reproducibility", "--child", str(root), str(work)],
        capture_output=True,
        text=True,
        env=env,
        cwd=ROOT,
        check=False,
    )
    for line in out.stdout.splitlines():
        if line.startswith(MARKER):
            return RunSummary(**json.loads(line[len(MARKER) :]))
    raise RuntimeError(f"training run failed (exit {out.returncode}):\n{out.stderr[-2000:]}")


def check(max_delta: float | None = None) -> dict[str, Any]:
    cfg = load_train_config()
    limit = float(
        max_delta if max_delta is not None else cfg["reproducibility"]["max_macro_f1_delta"]
    )
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        build_dataset(root, cfg)
        first = _child(root, root / "run1")
        second = _child(root, root / "run2")
    delta = abs(first.macro_f1 - second.macro_f1)
    problems = []
    if first.dataset_sha256 != second.dataset_sha256 or first.split_hash != second.split_hash:
        problems.append("dataset or split hash differs between runs")
    if delta > limit:
        problems.append(f"macro F1 differs by {delta:.6f} (limit {limit})")
    return {
        "passed": not problems,
        "problems": problems,
        "max_macro_f1_delta": limit,
        "macro_f1_delta": delta,
        "runs": [asdict(first), asdict(second)],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pipelines.reproducibility")
    parser.add_argument("--child", nargs=2, metavar=("ROOT", "WORK"), help=argparse.SUPPRESS)
    parser.add_argument("--out", type=Path, default=None, help="also write the result as JSON")
    args = parser.parse_args(argv)
    if args.child:
        summary = run_once(Path(args.child[0]), Path(args.child[1]))
        print(MARKER + json.dumps(asdict(summary)))
        return 0
    result = check()
    text = json.dumps(result, indent=2)
    print(text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
