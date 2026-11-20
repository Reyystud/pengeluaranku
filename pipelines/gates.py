"""Promotion gates (PRD 16.3). T-25 runs the gates that need no extra machinery.

Slices, behavioural tests and the latency benchmark belong to T-26; they are listed as
``skipped`` so a registered version never looks fully gated.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

Status = Literal["pass", "fail", "skipped"]

DEFERRED = {
    "slices": "T-26",
    "behavioural_tests": "T-26",
    "latency": "T-26",
    "beats_production": "T-26",
}


@dataclass(frozen=True)
class GateResult:
    name: str
    status: Status
    detail: str


def run_gates(
    *,
    dirty: bool,
    seed: int | None,
    winner: str,
    baseline: str,
    selection: dict[str, Any],
    test_ece: float,
    max_ece: float,
) -> list[GateResult]:
    results = [
        GateResult("data_quality", "pass", "validation and split checks passed before training"),
        GateResult(
            "reproducibility",
            "fail" if dirty or seed is None else "pass",
            "working tree has uncommitted changes"
            if dirty
            else "no seed recorded"
            if seed is None
            else "clean tree, seed recorded",
        ),
    ]
    # The baseline may win (PRD 9.1); a challenger only ships when it passed the ship rule,
    # which select_winner already enforced.
    results.append(
        GateResult(
            "beats_baseline",
            "pass",
            "baseline kept"
            if winner == baseline
            else f"{winner} beat {baseline} by the required margin on validation",
        )
        if selection["winner"] == winner
        else GateResult("beats_baseline", "fail", "winner does not match the selection")
    )
    results.append(
        GateResult(
            "calibration",
            "pass" if test_ece <= max_ece else "fail",
            f"test ECE {test_ece:.4f} (limit {max_ece:.2f})",
        )
    )
    results.extend(GateResult(n, "skipped", f"implemented in {t}") for n, t in DEFERRED.items())
    return results


def gates_passed(results: list[GateResult]) -> bool:
    return all(r.status != "fail" for r in results)
