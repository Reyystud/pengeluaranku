"""Fine-tune an Indonesian BERT-family model and compare it with the baseline (PRD 9.2, 9.1).

    # in the DL environment (.venv-dl: torch CPU + transformers; see docs/MODEL_EVALUATION.md)
    PYTHONPATH=. .venv-dl/bin/python -m ml.classification.indobert train --out-dir models/indobert
    PYTHONPATH=. .venv-dl/bin/python -m ml.classification.indobert profile --model-dir <dir>
    # in the normal environment
    uv run python -m ml.classification.indobert decide report.json
    uv run python -m ml.classification.indobert log report.json

``train`` fine-tunes on a class-capped train sample, fits a temperature on a validation sample,
scores the model and the baseline on the SAME deterministic test and unseen-merchant samples and
writes a report. ``profile`` loads the saved model in a fresh process and measures cold start, RAM
and single-request CPU latency with 2 threads, in full precision and with dynamic int8
quantization. torch and transformers are imported inside functions: the normal environment does not
have them (PRD 6.5: DL experiment extra only).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from ml.classification.data import cap_per_class
from ml.classification.metrics import expected_calibration_error, summarize
from ml.config import _load_yaml
from ml.features.classifier import INPUT_COLUMNS, build_feature_frame
from ml.taxonomy import MODEL_LABELS

ROOT = Path(__file__).resolve().parents[2]
LABELS = list(MODEL_LABELS)


# -- pure helpers (tested without torch) ---------------------------------------------------------
def fit_temperature(logits: np.ndarray, y: np.ndarray) -> float:
    """Temperature T > 0 minimizing the NLL of ``softmax(logits / T)`` (PRD 9.2)."""
    from scipy.optimize import minimize_scalar

    def nll(log_t: float) -> float:
        z = logits / np.exp(log_t)
        z = z - z.max(axis=1, keepdims=True)
        logp = z - np.log(np.exp(z).sum(axis=1, keepdims=True))
        return float(-logp[np.arange(len(y)), y].mean())

    return float(np.exp(minimize_scalar(nll, bounds=(-3.0, 3.0), method="bounded").x))


def softmax(logits: np.ndarray, temperature: float = 1.0) -> np.ndarray:
    z = logits / temperature
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return np.asarray(e / e.sum(axis=1, keepdims=True), dtype=np.float64)


def build_text(description: str, merchant: str | None, payment_method: str) -> str:
    """The model input: no amount or hour (a text model); the baseline also gets those."""
    parts = [description.strip(), (merchant or "").strip(), payment_method.replace("_", " ")]
    return " | ".join(p for p in parts if p)


def decide(report: dict[str, Any], rule: dict[str, Any]) -> dict[str, Any]:
    """The ship rule of PRD 9.1, fixed in ``config/train/indobert.yaml`` before training."""
    gain = (report["bert"]["test"]["macro_f1"] - report["baseline"]["test"]["macro_f1"]) * 100
    out: dict[str, Any] = {
        "macro_f1_gain_points": gain,
        "needs_points": float(rule["min_macro_f1_gain_points"]),
        "f1_ok": bool(gain >= float(rule["min_macro_f1_gain_points"])),
    }
    prof = report.get("profile")
    if prof:
        p95 = prof["fp32"]["p95_ms"]
        ram = prof["fp32"]["rss_after_inference_gib"]
        out |= {
            "p95_ms": p95,
            "p95_slo_ms": float(rule["p95_slo_ms"]),
            "latency_ok": bool(p95 <= float(rule["p95_slo_ms"])),
            "rss_gib": ram,
            "ram_limit_gib": float(rule["ram_limit_gib"]),
            "ram_ok": bool(ram <= float(rule["ram_limit_gib"])),
        }
        out["ship"] = bool(out["f1_ok"] and out["latency_ok"] and out["ram_ok"])
    else:
        out["ship"] = None  # latency and RAM not measured yet
    return out


# -- data ---------------------------------------------------------------------------------------
def load_samples(cfg: dict[str, Any]) -> dict[str, pd.DataFrame]:
    data_dir = ROOT / cfg["dataset"]["data_dir"]
    cols = list(dict.fromkeys([*INPUT_COLUMNS, "transaction_id", "true_category"]))
    tx = pd.read_parquet(data_dir / "transactions.parquet", columns=cols)
    assign = pd.read_parquet(
        ROOT / cfg["dataset"]["assignments"], columns=["transaction_id", "classifier_split"]
    )
    tx = tx.merge(assign, on="transaction_id")
    tx["label"] = tx["true_category"]
    seed, ev = int(cfg["seed"]), cfg["eval"]
    out: dict[str, pd.DataFrame] = {}
    train = tx[tx["classifier_split"] == "train"]
    out["train"] = cap_per_class(train, int(cfg["train"]["max_rows_per_class"]), seed)
    for name, split, rows in (
        ("validation", "validation", ev["validation_rows"]),
        ("test", "test", ev["test_rows"]),
        ("unseen", "test_unseen_merchant", ev["unseen_rows"]),
    ):
        part = tx[tx["classifier_split"] == split]
        out[name] = part.sample(n=min(int(rows), len(part)), random_state=seed).reset_index(
            drop=True
        )
    return out


def texts_of(frame: pd.DataFrame) -> list[str]:
    return [
        build_text(str(d), None if pd.isna(m) else str(m), str(p))
        for d, m, p in zip(
            frame["description"], frame["merchant"], frame["payment_method"], strict=True
        )
    ]


def baseline_proba(model_dir: Path, frame: pd.DataFrame) -> np.ndarray:
    import joblib

    art = joblib.load(model_dir / "model.joblib")
    feats = build_feature_frame(frame)
    X = art["transformer"].transform(feats).tocsr()
    raw = np.asarray(art["model"].predict_proba(X), dtype=np.float64)
    return np.asarray(art["calibrator"].predict_proba(raw), dtype=np.float64)


# -- torch parts ---------------------------------------------------------------------------------
def encode(tok: Any, texts: list[str], max_length: int) -> list[dict[str, list[int]]]:
    enc = tok(texts, truncation=True, max_length=max_length, return_token_type_ids=False)
    return [{k: enc[k][i] for k in enc} for i in range(len(texts))]


def logits_for(model: Any, tok: Any, texts: list[str], max_length: int, batch: int) -> np.ndarray:
    import torch

    enc = encode(tok, texts, max_length)
    order = np.argsort([len(e["input_ids"]) for e in enc])  # similar lengths per batch
    out = np.zeros((len(texts), model.config.num_labels), dtype=np.float64)
    model.eval()
    with torch.inference_mode():
        for start in range(0, len(order), batch):
            idx = order[start : start + batch]
            padded = tok.pad([enc[i] for i in idx], return_tensors="pt")
            out[idx] = model(**padded).logits.float().numpy()
    return out


def fine_tune(
    cfg: dict[str, Any], frame: pd.DataFrame, out_dir: Path
) -> tuple[Any, Any, dict[str, Any]]:
    import torch
    from transformers import (
        AutoModelForSequenceClassification,
        AutoTokenizer,
        get_linear_schedule_with_warmup,
    )

    seed = int(cfg["seed"])
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    name, length = cfg["model"]["name"], int(cfg["model"]["max_length"])
    tok = AutoTokenizer.from_pretrained(name)
    model = AutoModelForSequenceClassification.from_pretrained(
        name,
        num_labels=len(LABELS),
        id2label=dict(enumerate(LABELS)),
        label2id={n: i for i, n in enumerate(LABELS)},
    )
    t = cfg["train"]
    y_all = frame["label"].map({n: i for i, n in enumerate(LABELS)}).to_numpy()
    enc = encode(tok, texts_of(frame), length)
    steps_per_epoch = int(np.ceil(len(enc) / int(t["batch_size"])))
    total = steps_per_epoch * int(t["epochs"])
    opt = torch.optim.AdamW(
        model.parameters(), lr=float(t["learning_rate"]), weight_decay=float(t["weight_decay"])
    )
    sched = get_linear_schedule_with_warmup(opt, int(total * float(t["warmup_ratio"])), total)
    started, step, losses = time.time(), 0, []
    model.train()
    for epoch in range(int(t["epochs"])):
        order = rng.permutation(len(enc))
        for start in range(0, len(order), int(t["batch_size"])):
            idx = order[start : start + int(t["batch_size"])]
            batch = tok.pad([enc[i] for i in idx], return_tensors="pt")
            loss = torch.nn.functional.cross_entropy(
                model(**batch).logits, torch.tensor(y_all[idx])
            )
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sched.step()
            opt.zero_grad()
            losses.append(float(loss))
            step += 1
            if step % 50 == 0:
                print(
                    f"epoch {epoch} step {step}/{total} loss {np.mean(losses[-50:]):.4f} "
                    f"elapsed {time.time() - started:.0f}s",
                    flush=True,
                )
    out_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(out_dir)
    tok.save_pretrained(out_dir)
    return (
        model,
        tok,
        {
            "train_rows": len(enc),
            "steps": total,
            "fit_seconds": round(time.time() - started, 1),
            "final_loss": float(np.mean(losses[-50:])),
        },
    )


def cmd_train(args: argparse.Namespace) -> None:
    import torch
    import transformers

    cfg = _load_yaml("train/indobert.yaml")
    t0 = time.time()
    samples = load_samples(cfg)
    run = time.strftime("%Y%m%d-%H%M%S")
    out_dir = Path(args.out_dir) / run
    model, tok, fit = fine_tune(cfg, samples["train"], out_dir)
    length, batch = int(cfg["model"]["max_length"]), int(cfg["eval"]["batch_size"])
    idx = {n: i for i, n in enumerate(LABELS)}
    y: dict[str, NDArray[np.int64]] = {
        k: np.asarray(samples[k]["label"].map(idx), dtype=np.int64)
        for k in ("validation", "test", "unseen")
    }
    logits = {k: logits_for(model, tok, texts_of(samples[k]), length, batch) for k in y}
    temperature = fit_temperature(logits["validation"], y["validation"])
    bins = int(cfg["eval"]["ece_bins"])
    base_dir = ROOT / cfg["baseline_model_dir"]
    report: dict[str, Any] = {
        "config_version": cfg["version"],
        "model": cfg["model"]["name"],
        "dataset_version": cfg["dataset"]["dataset_version"],
        "temperature": temperature,
        "fit": fit,
        "run": run,
        "model_dir": str(out_dir),
        "torch": torch.__version__,
        "transformers": transformers.__version__,
        "git_commit": subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=ROOT,
            check=False,
        ).stdout.strip(),
        "baseline_model_dir": cfg["baseline_model_dir"],
        "samples": {k: len(v) for k, v in samples.items()},
        "bert": {},
        "bert_uncalibrated_ece": {},
        "baseline": {},
    }
    for k, name in (("test", "test"), ("unseen", "unseen")):
        proba = softmax(logits[k], temperature)
        report["bert"][name] = {
            m: v for m, v in summarize(proba, y[k], LABELS, bins).items() if m != "confusion_matrix"
        }
        report["bert_uncalibrated_ece"][name] = expected_calibration_error(
            softmax(logits[k]), y[k], bins
        )
        base = baseline_proba(base_dir, samples[k])
        report["baseline"][name] = {
            m: v for m, v in summarize(base, y[k], LABELS, bins).items() if m != "confusion_matrix"
        }
    (out_dir / "metadata.json").write_text(
        json.dumps({"temperature": temperature, "labels": LABELS, "max_length": length}),
        encoding="utf-8",
    )
    report["total_seconds"] = round(time.time() - t0, 1)
    Path(args.report).write_text(json.dumps(report, indent=2, default=float), encoding="utf-8")
    print(
        json.dumps(
            {k: report[k] for k in ("fit", "temperature")}
            | {
                "test": {
                    "bert": report["bert"]["test"]["macro_f1"],
                    "baseline": report["baseline"]["test"]["macro_f1"],
                }
            },
            indent=2,
        )
    )


def dir_size_mib(path: Path) -> float:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) / 2**20


def cmd_profile(args: argparse.Namespace) -> None:
    import os
    import sys

    import psutil
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    cfg = _load_yaml("train/indobert.yaml")
    knobs = cfg["latency"]
    model_dir = Path(args.model_dir)
    meta = json.loads((model_dir / "metadata.json").read_text(encoding="utf-8"))
    torch.set_num_threads(int(knobs["threads"]))
    proc = psutil.Process(os.getpid())
    rss_start = proc.memory_info().rss / 2**30
    t0 = time.perf_counter()
    tok = AutoTokenizer.from_pretrained(model_dir)
    model = AutoModelForSequenceClassification.from_pretrained(model_dir).eval()
    cold = time.perf_counter() - t0
    samples = load_samples(cfg)  # only for realistic requests
    texts = texts_of(samples["test"].head(int(knobs["requests"]) + int(knobs["warmup_requests"])))
    length = int(meta["max_length"])

    def measure(m: Any) -> dict[str, Any]:
        times: list[float] = []
        with torch.inference_mode():
            for i, text in enumerate(texts):
                start = time.perf_counter()
                enc = tok(
                    text,
                    truncation=True,
                    max_length=length,
                    return_tensors="pt",
                    return_token_type_ids=False,
                )
                _ = m(**enc).logits
                if i >= int(knobs["warmup_requests"]):
                    times.append((time.perf_counter() - start) * 1000.0)
        return {
            "requests": len(times),
            "p50_ms": float(np.percentile(times, 50)),
            "p95_ms": float(np.percentile(times, 95)),
            "p99_ms": float(np.percentile(times, 99)),
            "rss_after_inference_gib": proc.memory_info().rss / 2**30,
        }

    fp32 = measure(model)
    quant = torch.quantization.quantize_dynamic(model, {torch.nn.Linear}, dtype=torch.qint8)
    int8 = measure(quant)
    site = (
        Path(sys.prefix)
        / "lib"
        / f"python{sys.version_info.major}.{sys.version_info.minor}"
        / "site-packages"
    )
    packages = {
        p: dir_size_mib(site / p)
        for p in ("torch", "transformers", "tokenizers", "safetensors", "numpy", "scipy")
        if (site / p).exists()
    }
    result = {
        "threads": int(knobs["threads"]),
        "host_cpus": os.cpu_count(),
        "model_dir_mib": dir_size_mib(model_dir),
        "cold_start_load_seconds": round(cold, 2),
        "rss_start_gib": rss_start,
        "fp32": fp32,
        "int8_dynamic": int8,
        "site_packages_mib": packages,
        "site_packages_total_mib": sum(packages.values()),
    }
    Path(args.report).write_text(json.dumps(result, indent=2, default=float), encoding="utf-8")
    print(json.dumps(result, indent=2, default=float))


def cmd_decide(args: argparse.Namespace) -> None:
    cfg = _load_yaml("train/indobert.yaml")
    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    print(json.dumps(decide(report, cfg["ship_rule"]), indent=2))


def cmd_log(args: argparse.Namespace) -> None:
    from ml.tracking import log_run

    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    cfg = _load_yaml("train/indobert.yaml")
    decision = decide(report, cfg["ship_rule"])
    flat = {
        "bert_test_macro_f1": report["bert"]["test"]["macro_f1"],
        "baseline_test_macro_f1": report["baseline"]["test"]["macro_f1"],
        "bert_unseen_macro_f1": report["bert"]["unseen"]["macro_f1"],
        "baseline_unseen_macro_f1": report["baseline"]["unseen"]["macro_f1"],
        "bert_test_ece": report["bert"]["test"]["ece"],
        "macro_f1_gain_points": decision["macro_f1_gain_points"],
        "fit_seconds": report["fit"]["fit_seconds"],
    }
    if report.get("profile"):
        flat |= {
            "p95_ms_fp32": report["profile"]["fp32"]["p95_ms"],
            "p95_ms_int8": report["profile"]["int8_dynamic"]["p95_ms"],
            "rss_gib": report["profile"]["fp32"]["rss_after_inference_gib"],
        }
    run_id = log_run(
        "classifier-indobert",
        f"{cfg['version']}-{report['git_commit']}",
        {
            "model": report["model"],
            "config_version": cfg["version"],
            "seed": cfg["seed"],
            "dataset_version": report["dataset_version"],
            "git_commit": report["git_commit"],
            "ship": decision["ship"],
        },
        flat,
        {"evaluation/report.json": report | {"decision": decision}},
    )
    print(run_id)


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    train = sub.add_parser("train")
    train.add_argument("--out-dir", default="models/indobert")
    train.add_argument("--report", default="data/indobert_report.json")
    profile = sub.add_parser("profile")
    profile.add_argument("--model-dir", required=True)
    profile.add_argument("--report", default="data/indobert_profile.json")
    for name in ("decide", "log"):
        sub.add_parser(name).add_argument("report")
    args = parser.parse_args()
    {"train": cmd_train, "profile": cmd_profile, "decide": cmd_decide, "log": cmd_log}[args.cmd](
        args
    )


if __name__ == "__main__":
    main()
