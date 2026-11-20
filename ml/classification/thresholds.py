"""Decision-threshold calibration for the classifier (PRD 7.3.4, pipeline step 6).

Rule (PRD): ``t_high`` is the smallest threshold whose auto-applied predictions reach the target
precision; ``t_low`` is the smallest threshold whose "suggest" band [t_low, t_high) reaches its
target. Read literally with cumulative precision, the rule is degenerate whenever the overall
accuracy already exceeds the target (here 95.3% > 95%): every row would be auto-applied.
We therefore walk fixed-width confidence bands from the top down and lower a threshold only while
the precision of each band passed over meets the target (see docs/DECISIONS.md, T-10).
Thresholds are chosen on the VALIDATION split only; other splits are diagnostics.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from ml.classification.config import load_train_config

FloatArray = NDArray[np.float64]


def _bands(
    conf: FloatArray, ok: NDArray[np.bool_], width: float, min_support: int
) -> list[dict[str, float]]:
    n_bands = round(1.0 / width)
    out = []
    for i in range(n_bands):
        lo, hi = i * width, (i + 1) * width
        mask = (conf >= lo) & ((conf < hi) if i < n_bands - 1 else (conf <= hi))
        n = int(mask.sum())
        out.append(
            {
                "lo": round(lo, 6),
                "hi": round(hi, 6),
                "n": n,
                "precision": float(ok[mask].mean()) if n else float("nan"),
                "supported": n >= min_support,
            }
        )
    return out


def choose_thresholds(
    conf: FloatArray, ok: NDArray[np.bool_], params: dict[str, Any]
) -> dict[str, Any]:
    """Pick ``t_high`` / ``t_low`` from calibrated top-1 confidences and correctness flags."""
    width = float(params["band_width"])
    hi_target = float(params["high_precision_target"])
    lo_target = float(params["low_precision_target"])
    bands = _bands(conf, ok, width, int(params["min_band_support"]))
    flags: list[str] = []

    # t_high: walk down while every supported band passed over meets the high target.
    t_high: float | None = None
    for band in reversed(bands):
        if not band["supported"]:
            continue
        if band["precision"] >= hi_target:
            t_high = band["lo"]
        else:
            break
    if t_high is None:
        t_high = float(params["defaults"]["t_high"])
        flags.append("t_high_not_found_used_default")

    # t_low: keep walking down from t_high while bands meet the low target.
    t_low = t_high
    for band in reversed([b for b in bands if b["hi"] <= t_high + 1e-9]):
        if not band["supported"]:
            continue
        if band["precision"] >= lo_target:
            t_low = band["lo"]
        else:
            break
    if t_low >= t_high:
        t_low = t_high
        flags.append("no_suggest_band: no confidence band below t_high reaches the low target")
    return {"t_high": round(t_high, 6), "t_low": round(t_low, 6), "flags": flags, "bands": bands}


def decision_stats(
    conf: FloatArray, ok: NDArray[np.bool_], t_high: float, t_low: float
) -> dict[str, Any]:
    """Share of rows per decision and the precision of each decision's predictions."""
    auto = conf >= t_high
    suggest = (conf >= t_low) & ~auto
    review = conf < t_low

    def part(mask: NDArray[np.bool_]) -> dict[str, float | None]:
        return {
            "share": float(mask.mean()),
            "precision": float(ok[mask].mean()) if mask.any() else None,
        }

    return {"auto_apply": part(auto), "suggest": part(suggest), "needs_review": part(review)}


def build_report(
    conf_by_split: dict[str, tuple[FloatArray, NDArray[np.bool_]]], params: dict[str, Any]
) -> dict[str, Any]:
    """Choose thresholds on validation; report decision statistics on every split."""
    conf, ok = conf_by_split["validation"]
    chosen = choose_thresholds(conf, ok, params)
    t_high, t_low = chosen["t_high"], chosen["t_low"]
    stats = {split: decision_stats(c, o, t_high, t_low) for split, (c, o) in conf_by_split.items()}
    return {
        "decision_thresholds": {
            "t_high": t_high,
            "t_low": t_low,
            "calibration": "isotonic",
            "chosen_on": "validation",
            "flags": chosen["flags"],
        },
        "validation_bands": chosen["bands"],
        "decision_stats": stats,
        "parameters": params,
    }


def confidences(
    artifacts: dict[str, Any], frame: Any, encode: Any
) -> tuple[FloatArray, NDArray[np.bool_]]:
    from ml.classification.pipeline import batched_scores

    raw = batched_scores(artifacts["model"], artifacts["transformer"], frame)
    proba = artifacts["calibrator"].predict_proba(raw)
    return proba.max(axis=1), proba.argmax(axis=1) == encode(frame)


def compute_report(
    artifacts: dict[str, Any], frames: dict[str, Any], params: dict[str, Any]
) -> dict[str, Any]:
    from ml.classification.train import _encode

    splits = ("validation", "test", "test_unseen_merchant")
    conf = {s: confidences(artifacts, frames[s], _encode) for s in splits}
    return build_report(conf, params)


def _log_to_mlflow(model_dir: Path) -> None:
    """Attach the thresholds and updated metadata to the MLflow run of this model, if any."""
    import mlflow

    from ml.classification.train import ROOT

    saved = json.loads((model_dir / "evaluation" / "report.json").read_text())
    run_id = (saved.get("mlflow") or {}).get("run_id")
    if not run_id:
        return
    mlflow.set_tracking_uri(f"sqlite:///{ROOT / 'data' / 'mlflow' / 'mlflow.db'}")
    with mlflow.start_run(run_id=run_id):
        mlflow.log_artifact(str(model_dir / "metadata.json"), "model")
        mlflow.log_artifact(str(model_dir / "evaluation" / "thresholds.json"), "evaluation")


def main(argv: list[str] | None = None) -> int:
    import joblib

    from ml.classification.data import load_split_frames
    from ml.classification.train import ROOT

    parser = argparse.ArgumentParser(prog="ml.classification.thresholds")
    parser.add_argument("--model-dir", type=Path, default=None, help="default: latest run")
    args = parser.parse_args(argv)
    runs = sorted((ROOT / "models" / "transaction-classifier").glob("2*"))
    model_dir = args.model_dir or runs[-1]
    cfg = load_train_config()
    ds = cfg["dataset"]
    frames = load_split_frames(ROOT / ds["data_dir"], ROOT / ds["assignments"])
    report = compute_report(joblib.load(model_dir / "model.joblib"), frames, cfg["thresholds"])
    (model_dir / "evaluation" / "thresholds.json").write_text(
        json.dumps(report, indent=2, default=float), encoding="utf-8"
    )
    meta_path = model_dir / "metadata.json"
    meta = json.loads(meta_path.read_text())
    meta["decision_thresholds"] = report["decision_thresholds"]
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    _log_to_mlflow(model_dir)
    t = report["decision_thresholds"]
    print(f"t_high={t['t_high']} t_low={t['t_low']} flags={t['flags']}")
    for split, s in report["decision_stats"].items():
        print(
            split,
            {
                k: (
                    round(v["share"], 4),
                    None if v["precision"] is None else round(v["precision"], 4),
                )
                for k, v in s.items()
            },
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
