"""shadow-evaluate (PRD 16.4): criteria, promotion through the registry, CLI."""

from __future__ import annotations

import datetime as dt
import json
import os
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest
from mlflow.tracking import MlflowClient

from pipelines.__main__ import main
from pipelines.shadow import job, logs
from pipelines.shadow.config import ShadowConfig, load_config
from pipelines.shadow.evaluate import INSUFFICIENT, PASSED, REJECTED, evaluate, psi

MODEL = "transaction-classifier"
PROD, CAND = f"{MODEL}@1", f"{MODEL}@2"
CATS = ["groceries", "food_beverage", "transportation", "health"]
START = dt.datetime(2026, 11, 1, tzinfo=dt.UTC)
CFG = load_config()


def make_lines(
    n: int = 1200,
    days: float = 8.0,
    disagree_every: int = 0,
    latency: float = 20.0,
    errors: int = 0,
    cand_shift: bool = False,
) -> list[str]:
    """``n`` mirrored items: production line + shadow line (+ ``errors`` shadow_error lines)."""
    out = []
    for i in range(n):
        when = (
            (START + dt.timedelta(days=days * i / max(n - 1, 1))).isoformat().replace("+00:00", "Z")
        )
        cat = CATS[i % len(CATS)]
        other = CATS[(i + 1) % len(CATS)]
        if cand_shift:
            other = CATS[0]
        cand_cat = other if disagree_every and i % disagree_every == 0 else cat
        for version, predicted, shadow in ((PROD, cat, False), (CAND, cand_cat, True)):
            out.append(
                json.dumps(
                    {
                        "event": "prediction",
                        "model_version": version,
                        "request_id": f"r{i}",
                        "input_hash": f"h{i:05d}",
                        "logged_at": when,
                        "shadow": shadow,
                        "output": {"predicted_category": predicted, "confidence": 0.9},
                        "latency_ms": latency,
                    }
                )
            )
    for j in range(errors):
        out.append(
            json.dumps(
                {
                    "event": "shadow_error",
                    "model_version": CAND,
                    "request_id": f"e{j}",
                    "logged_at": START.isoformat().replace("+00:00", "Z"),
                    "error_type": "RuntimeError",
                }
            )
        )
    return out


def run_eval(lines: list[str], corrections: dict[str, str] | None = None, cfg: ShadowConfig = CFG):  # type: ignore[no-untyped-def]
    preds, errs = logs.parse_lines(lines)
    return evaluate(
        preds, errs, corrections or {}, production_version=PROD, candidate_version=CAND, cfg=cfg
    )


def status(report, name: str) -> str:  # type: ignore[no-untyped-def]
    return next(c.status for c in report.criteria if c.name == name)


def lenient(**over: object) -> ShadowConfig:
    return replace(CFG, require_corrections=False, **over)  # type: ignore[arg-type]


def test_fr_16_4_all_criteria_met_passes() -> None:
    report = run_eval(make_lines(), cfg=lenient())
    assert report.outcome == PASSED
    assert report.matched_items == 1200 and report.period_days >= 7


def test_fr_16_4_short_period_or_few_predictions_is_insufficient_not_rejected() -> None:
    assert run_eval(make_lines(days=3), cfg=lenient()).outcome == INSUFFICIENT
    assert run_eval(make_lines(n=500), cfg=lenient()).outcome == INSUFFICIENT
    assert (
        status(run_eval(make_lines(days=3), cfg=lenient()), "shadow_period_days") == "insufficient"
    )


def test_fr_16_4_agreement_below_85_percent_rejects() -> None:
    ok = run_eval(make_lines(disagree_every=10), cfg=lenient())  # 90% agreement
    assert status(ok, "agreement_non_corrected") == "pass"
    bad = run_eval(make_lines(disagree_every=5), cfg=lenient())  # 80% agreement
    assert status(bad, "agreement_non_corrected") == "fail" and bad.outcome == REJECTED


def test_fr_16_4_corrected_items_are_judged_on_accuracy_not_agreement() -> None:
    lines = make_lines(disagree_every=2)  # candidate differs from production on every even item
    corrections = {
        f"h{i:05d}": CATS[i % len(CATS)] for i in range(0, 200, 2)
    }  # production was right
    report = run_eval(
        lines, corrections, cfg=lenient(min_corrected_items=30, agreement_min=0.0, psi_max=10.0)
    )
    assert status(report, "corrected_accuracy") == "fail" and report.outcome == REJECTED
    right_cand = {
        f"h{i:05d}": CATS[(i + 1) % len(CATS)] for i in range(0, 200, 2)
    }  # candidate right
    good = run_eval(
        lines, right_cand, cfg=lenient(min_corrected_items=30, agreement_min=0.0, psi_max=10.0)
    )
    assert status(good, "corrected_accuracy") == "pass" and good.outcome == PASSED


def test_fr_16_4_too_few_corrections_block_promotion_unless_configured() -> None:
    strict = run_eval(make_lines(), {"h00001": "health"})
    assert status(strict, "corrected_accuracy") == "insufficient" and strict.outcome == INSUFFICIENT
    assert run_eval(make_lines(), {"h00001": "health"}, cfg=lenient()).outcome == PASSED


def test_fr_16_4_latency_psi_and_errors_each_block() -> None:
    slow = run_eval(make_lines(latency=450.0), cfg=lenient())
    assert status(slow, "candidate_p95_latency_ms") == "fail" and slow.outcome == REJECTED
    shifted = run_eval(
        make_lines(cand_shift=True, disagree_every=1000000), cfg=lenient(agreement_min=0.0)
    )
    assert status(shifted, "category_psi") == "pass"  # no disagreement -> same distribution
    skew = run_eval(make_lines(cand_shift=True, disagree_every=1), cfg=lenient(agreement_min=0.0))
    assert status(skew, "category_psi") == "fail"
    noisy = run_eval(make_lines(errors=5), cfg=lenient())  # 5 / 1205 = 0.41% > 0.1%
    assert status(noisy, "error_rate") == "fail"
    assert status(run_eval(make_lines(errors=1), cfg=lenient()), "error_rate") == "pass"  # 0.083%


def test_fr_16_4_logs_of_other_versions_are_ignored() -> None:
    lines = [x.replace(CAND, f"{MODEL}@9") for x in make_lines()]
    assert run_eval(lines, cfg=lenient()).outcome == INSUFFICIENT  # no shadow rows of v2


def test_fr_16_4_psi_is_zero_for_equal_distributions_and_finite_with_an_empty_category() -> None:
    a = pd.Series(["x"] * 50 + ["y"] * 50)
    assert psi(a, a, 1e-4) == 0.0
    b = pd.Series(["x"] * 100)
    value = psi(a, b, 1e-4)
    assert 0 < value < 50


def test_fr_16_4_parser_skips_noise_and_reads_both_event_kinds() -> None:
    lines = ["plain text", "{not json", '{"event":"request"}', *make_lines(2, errors=1)]
    preds, errs = logs.parse_lines(lines)
    assert len(preds) == 4 and preds["shadow"].sum() == 2 and len(errs) == 1


# -- job and CLI ---------------------------------------------------------------------------------
@pytest.fixture
def registry(tmp_path: Path) -> tuple[MlflowClient, str]:
    os.environ["MLFLOW_DISABLE_AGENT_HINT"] = "1"
    uri = f"sqlite:///{tmp_path / 'mlflow.db'}"
    client = MlflowClient(uri, uri)
    client.create_registered_model(MODEL)
    client.create_model_version(MODEL, source="runs:/x/model", tags={"gate": "passed"})
    client.create_model_version(MODEL, source="runs:/x/model", tags={"gate": "passed"})
    client.set_registered_model_alias(MODEL, "production", "1")
    client.set_registered_model_alias(MODEL, "candidate", "2")
    return client, uri


def alias(client: MlflowClient, name: str) -> str | None:
    try:
        return str(client.get_model_version_by_alias(MODEL, name).version)
    except Exception:
        return None


def write_logs(tmp_path: Path, **kw: object) -> Path:
    path = tmp_path / "ml.log"
    path.write_text("\n".join(make_lines(**kw)), encoding="utf-8")  # type: ignore[arg-type]
    return path


def run_job(client: MlflowClient, tmp_path: Path, log: Path, **kw: object):  # type: ignore[no-untyped-def]
    return job.run(
        client=client,
        model=MODEL,
        log_files=[log],
        corrections_file=None,
        reports_dir=tmp_path / "reports",
        today=dt.date(2026, 11, 10),
        cfg=lenient(),
        log_path=tmp_path / "rollback-log.md",
        **kw,  # type: ignore[arg-type]
    )


def test_fr_16_4_passing_candidate_is_promoted_and_the_old_production_becomes_previous(
    registry: tuple[MlflowClient, str], tmp_path: Path
) -> None:
    client, _ = registry
    report, outcome = run_job(client, tmp_path, write_logs(tmp_path))
    assert report.outcome == PASSED and outcome == {"promoted": True}
    assert (alias(client, "production"), alias(client, "previous")) == ("2", "1")
    saved = json.loads((tmp_path / "reports" / "shadow" / "2026-11-10.json").read_text())
    assert saved["outcome"] == "passed" and saved["promoted"] is True
    assert "shadow-evaluate" in (tmp_path / "rollback-log.md").read_text()


def test_fr_16_4_dry_run_and_failed_criteria_never_move_aliases(
    registry: tuple[MlflowClient, str], tmp_path: Path
) -> None:
    client, _ = registry
    _, outcome = run_job(client, tmp_path, write_logs(tmp_path), promote=False)
    assert outcome == {"promoted": False} and alias(client, "production") == "1"
    report, outcome = run_job(client, tmp_path, write_logs(tmp_path, disagree_every=3))
    assert report.outcome == REJECTED and outcome == {"promoted": False}
    assert alias(client, "production") == "1"


def test_fr_16_4_a_candidate_whose_gate_is_not_passed_is_refused_by_the_registry(
    registry: tuple[MlflowClient, str], tmp_path: Path
) -> None:
    client, _ = registry
    client.set_model_version_tag(MODEL, "2", "gate", "needs_review")
    report, outcome = run_job(client, tmp_path, write_logs(tmp_path))
    assert report.outcome == PASSED and outcome["promoted"] is False
    assert "GATE_NOT_PASSED" in outcome["refused"] and alias(client, "production") == "1"


def test_fr_16_4_cli_needs_logs_and_reports_the_outcome(
    registry: tuple[MlflowClient, str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, uri = registry
    base = ["shadow-evaluate", "--tracking-uri", uri, "--reports-dir", str(tmp_path / "r")]
    assert main(base) == 2  # no --logs
    log = write_logs(tmp_path, n=300)
    assert main([*base, "--logs", str(log), "--date", "2026-11-10", "--dry-run"]) == 0
    assert "insufficient_data" in capsys.readouterr().out
    assert (tmp_path / "r" / "shadow" / "2026-11-10.json").exists()


def test_fr_16_4_same_candidate_and_production_stops(
    registry: tuple[MlflowClient, str], tmp_path: Path
) -> None:
    client, _ = registry
    client.set_registered_model_alias(MODEL, "candidate", "1")
    with pytest.raises(job.PipelineError):
        run_job(client, tmp_path, write_logs(tmp_path))
