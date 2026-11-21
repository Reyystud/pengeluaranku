"""Promotion gates (PRD 16.3) for the classifier. Pure functions over measured evidence.

``fail`` blocks registration; ``review`` registers the version with ``gate=needs_review`` and
keeps it out of auto-promotion; ``skipped`` means the gate had nothing to compare with and says
why. Thresholds come from ``config/train/classifier.yaml``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Status = Literal["pass", "fail", "review", "skipped"]


@dataclass(frozen=True)
class GateResult:
    name: str
    status: Status
    detail: str


@dataclass(frozen=True)
class Reference:
    """What the current production version measured (read from its MLflow artifacts)."""

    version: str
    split_hash: str | None
    test_macro_f1: float | None
    slices: dict[str, float]
    golden_accuracy: float | None


@dataclass
class GateInputs:
    dirty: bool
    seed: int | None
    winner: str
    baseline: str
    test_ece: float
    test_macro_f1: float
    split_hash: str
    slices: dict[str, float]  # candidate: "archetype:x" / "category:y" -> F1
    baseline_slices: dict[str, float]
    behavioural: dict[str, Any]
    latency: dict[str, Any]
    reference: Reference | None = None
    knobs: dict[str, Any] = field(default_factory=dict)  # the `gates` config section


def slice_scores(test: dict[str, Any]) -> dict[str, float]:
    """Archetype macro F1 and per-category F1 from an evaluation ``test`` block."""
    out = {f"archetype:{k}": float(v["macro_f1"]) for k, v in test.get("by_archetype", {}).items()}
    for label, row in test.get("per_class", {}).items():
        if row.get("support", 0) > 0:
            out[f"category:{label}"] = float(row["f1"])
    return out


def slice_drops(
    candidate: dict[str, float], reference: dict[str, float], max_drop_points: float
) -> list[str]:
    limit = max_drop_points / 100.0
    return sorted(
        f"{name} (-{(reference[name] - value) * 100:.1f} points)"
        for name, value in candidate.items()
        if name in reference and reference[name] - value > limit
    )


def run_gates(inp: GateInputs) -> list[GateResult]:
    k = inp.knobs
    results = [
        GateResult("data_quality", "pass", "validation and split checks passed before training"),
        _reproducibility(inp),
        GateResult(
            "beats_baseline",
            "pass",
            "baseline kept"
            if inp.winner == inp.baseline
            else f"{inp.winner} beat {inp.baseline} by the required margin on validation",
        ),
        GateResult(
            "calibration",
            "pass" if inp.test_ece <= float(k["max_ece"]) else "fail",
            f"test ECE {inp.test_ece:.4f} (limit {float(k['max_ece']):.2f})",
        ),
        _beats_production(inp),
        _slices(inp),
        _behavioural(inp),
        _latency(inp),
    ]
    return results


def _reproducibility(inp: GateInputs) -> GateResult:
    if inp.dirty:
        return GateResult("reproducibility", "fail", "working tree has uncommitted changes")
    if inp.seed is None:
        return GateResult("reproducibility", "fail", "no seed recorded")
    return GateResult("reproducibility", "pass", "clean tree, seed recorded")


def _same_split(inp: GateInputs) -> bool:
    return inp.reference is not None and inp.reference.split_hash == inp.split_hash


def _beats_production(inp: GateInputs) -> GateResult:
    ref = inp.reference
    if ref is None:
        return GateResult("beats_production", "skipped", "no production model yet")
    if not _same_split(inp) or ref.test_macro_f1 is None:
        return GateResult("beats_production", "skipped", "production used a different split")
    margin = float(inp.knobs["beats_production_margin_points"]) / 100.0
    ok = inp.test_macro_f1 >= ref.test_macro_f1 + margin
    return GateResult(
        "beats_production",
        "pass" if ok else "fail",
        f"test macro F1 {inp.test_macro_f1:.4f} vs production v{ref.version} "
        f"{ref.test_macro_f1:.4f} (+{margin * 100:.1f} points required)",
    )


def _slices(inp: GateInputs) -> GateResult:
    limit = float(inp.knobs["slice_max_drop_points"])
    if inp.reference is not None and _same_split(inp):
        against, reference = f"production v{inp.reference.version}", inp.reference.slices
    elif inp.winner != inp.baseline:
        against, reference = f"baseline {inp.baseline}", inp.baseline_slices
    else:
        return GateResult("slices", "skipped", "no reference: the baseline is the winner")
    drops = slice_drops(inp.slices, reference, limit)
    if drops:
        return GateResult(
            "slices", "review", f"drops over {limit:g} points vs {against}: " + "; ".join(drops)
        )
    return GateResult("slices", "pass", f"no slice drops over {limit:g} points vs {against}")


def _behavioural(inp: GateInputs) -> GateResult:
    beh = inp.behavioural
    failed = [name for name, ok in beh["checks"].items() if not ok]
    ref = inp.reference
    if ref is not None and ref.golden_accuracy is not None:
        if beh["golden_accuracy"] < ref.golden_accuracy:
            failed.append(f"golden regression vs production v{ref.version}")
    summary = (
        f"golden accuracy {beh['golden_accuracy']:.3f} on {beh['n_cases']} cases; "
        f"invariance {', '.join(f'{n} {v:.2f}' for n, v in beh['invariance_pass_rate'].items())}"
    )
    if failed:
        extra = (
            f"; categories under minimum: {', '.join(beh['mft_failures'])}"
            if (beh["mft_failures"])
            else ""
        )
        return GateResult(
            "behavioural_tests", "fail", f"failed {', '.join(failed)}: {summary}{extra}"
        )
    return GateResult("behavioural_tests", "pass", summary)


def _latency(inp: GateInputs) -> GateResult:
    lat = inp.latency
    detail = (
        f"P95 {lat['p95_ms']:.1f} ms over {lat['requests']} requests on {lat['threads']} threads "
        f"(SLO {lat['slo_p95_ms']:g} ms)"
    )
    return GateResult("latency", "pass" if lat["within_slo"] else "fail", detail)


def gate_outcome(results: list[GateResult]) -> str:
    """``failed`` blocks registration, ``needs_review`` registers without auto-promotion."""
    if any(r.status == "fail" for r in results):
        return "failed"
    if any(r.status == "review" for r in results):
        return "needs_review"
    return "passed"


def gates_passed(results: list[GateResult]) -> bool:
    return gate_outcome(results) != "failed"
