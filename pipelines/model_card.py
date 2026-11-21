"""Model card generation from a real run (PRD 16.1 step 9). Nothing is hand-typed or invented."""

from __future__ import annotations

from typing import Any

from pipelines.gates import GateResult


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _behavioural_lines(report: dict[str, Any]) -> list[str]:
    beh, lat = report.get("behavioural"), report.get("latency_benchmark")
    lines: list[str] = []
    if beh:
        lines.append(
            f"- Golden set ({beh['golden_version']}, {beh['n_cases']} cases): accuracy "
            f"{beh['golden_accuracy']:.3f}; categories under the minimum-functionality rule: "
            f"{', '.join(beh['mft_failures']) or 'none'}."
        )
        lines.append(
            "- Invariance (top-1 unchanged): "
            + ", ".join(f"{n} {v:.2f}" for n, v in beh["invariance_pass_rate"].items())
            + "."
        )
    if lat:
        lines.append(
            f"- Latency, {lat['requests']} replayed requests on {lat['threads']} CPU threads: "
            f"P50 {lat['p50_ms']:.1f} ms, P95 {lat['p95_ms']:.1f} ms, P99 {lat['p99_ms']:.1f} ms "
            "(this machine; not an SLO measurement)."
        )
    return lines


def render_model_card(
    report: dict[str, Any],
    metadata: dict[str, Any],
    gates: list[GateResult],
    mlflow_run_id: str | None,
    mlflow_version: str | None,
) -> str:
    winner = report["selection"]["winner"]
    res = report["models"][winner]
    test, unseen = res["test"], res["test_unseen_merchant"]
    dataset = report["dataset"]
    thresholds = metadata.get("decision_thresholds") or {}
    lines = [
        f"# Model card: {metadata['model_name']}",
        "",
        f"Generated from run `{report['run_id']}` (MLflow run `{mlflow_run_id or 'not logged'}`, "
        f"registry version `{mlflow_version or 'not registered'}`). Do not edit by hand.",
        "",
        "## Model",
        f"- Algorithm: {winner} + isotonic one-vs-rest calibration, chosen on validation macro F1 "
        f"(baseline {report['selection']['baseline']}, required gain "
        f"{report['selection']['required_gain_points']} points).",
        f"- Feature version `{report['feature_version']}`, "
        f"taxonomy `{report['taxonomy_version']}`.",
        f"- Labels: {len(metadata['labels'])} categories (`uncategorized` is never a label).",
        f"- Code: git `{report['git_commit']}`; trained at {metadata['trained_at']}.",
        "",
        "## Data",
        f"- Dataset `{dataset['version']}`, split hash `{dataset['split_hash']}`, "
        f"transactions SHA-256 `{dataset['transactions_sha256']}`.",
        "- Synthetic data only; results say nothing about real-world accuracy.",
        "",
        "## Decision thresholds",
        f"- `t_high` {thresholds.get('t_high')}, `t_low` {thresholds.get('t_low')} "
        f"(calibration: {thresholds.get('calibration')}).",
        "",
        "## Results (measured in this run)",
        "| split | macro F1 | accuracy | ECE |",
        "|---|---|---|---|",
        f"| test (temporal) | {test['macro_f1']:.4f} | {_pct(test['accuracy'])} | "
        f"{test['ece']:.4f} |",
        f"| test, unseen merchants | {unseen['macro_f1']:.4f} | {_pct(unseen['accuracy'])} | "
        f"{unseen['ece']:.4f} |",
        "",
        "## Gates",
        "| gate | status | detail |",
        "|---|---|---|",
        *(f"| {g.name} | {g.status} | {g.detail} |" for g in gates),
        "",
        "## Behavioural tests and latency",
        *_behavioural_lines(report),
        "",
        "## Limits",
        "- Unseen merchants are much weaker than seen ones; see the unseen row above.",
        "- Gates marked `skipped` had nothing to compare with (see their detail).",
        "- The golden set was written by the project team; many merchants also exist in the "
        "synthetic catalogue, so real-world accuracy is not shown by these numbers.",
        "",
    ]
    return "\n".join(lines)


def render_summary(
    report: dict[str, Any],
    gates: list[GateResult],
    registered: str | None,
    dirty: bool,
) -> str:
    """Short markdown for the run and for ``$GITHUB_STEP_SUMMARY`` (step 10)."""
    winner = report["selection"]["winner"]
    test = report["models"][winner]["test"]
    outcome = (
        f"registered as version {registered} (alias candidate)" if registered else "NOT registered"
    )
    lines = [
        f"### train_model: {outcome}",
        f"- dataset `{report['dataset']['version']}`, winner `{winner}`, "
        f"test macro F1 {test['macro_f1']:.4f}, ECE {test['ece']:.4f}",
        f"- git `{report['git_commit']}`{' (dirty tree)' if dirty else ''}",
        "",
        "| gate | status |",
        "|---|---|",
        *(f"| {g.name} | {g.status} |" for g in gates),
        "",
    ]
    return "\n".join(lines)
