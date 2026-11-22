"""T-35: drift job (PRD 18.1, 18.3). Real Evidently runs on synthetic frames, no network."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import httpx
import numpy as np
import pandas as pd
import pytest

from ml.monitoring import load_reference, merchant_hash, write_reference
from pipelines.drift import job
from pipelines.drift.config import DriftConfig, load_config
from pipelines.drift.report import summarize, unseen_alert, unseen_share
from pipelines.drift.sources import BigQueryLogSource, JsonlLogSource, parse_lines
from pipelines.drift.store import GcsStore, LocalStore

CFG = load_config()
DAY = dt.date(2026, 3, 10)
END = dt.datetime(2026, 3, 10, tzinfo=dt.UTC)
WINDOW = (END - dt.timedelta(days=7), END)


def frame(
    n: int, *, mu: float = 10.0, cash: float = 0.5, unseen: float = 0.05, seed: int = 0
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    known = [merchant_hash(f"m{i}") for i in range(20)]
    hashes = [
        "ffffffffffff" if rng.random() < unseen else known[int(rng.integers(20))] for _ in range(n)
    ]
    return pd.DataFrame(
        {
            "logged_at": pd.Timestamp("2026-03-08", tz="UTC"),
            "log_amount": rng.normal(mu, 1.0, n),
            "payment_method": rng.choice(["cash", "e_wallet"], n, p=[cash, 1 - cash]),
            "hour_bucket": rng.choice(["morning", "midday", "evening"], n),
            "predicted_category": rng.choice(["food_beverage", "transport", "shopping"], n),
            "confidence": rng.beta(8, 2, n),
            "merchant_hash": hashes,
        }
    )


KNOWN = {merchant_hash(f"m{i}") for i in range(20)}


def test_fr_18_03_merchant_hash_is_stable_and_blank_is_none() -> None:
    assert merchant_hash(" Gojek ") == merchant_hash("gojek")
    assert len(str(merchant_hash("gojek"))) == 12
    assert merchant_hash("   ") is None


def test_fr_18_03_config_matches_prd_thresholds() -> None:
    assert CFG.window_days == 7
    assert CFG.psi_threshold == 0.25
    assert CFG.unseen_ratio_threshold == 2.0
    assert CFG.unseen_history_days == 28
    assert set(CFG.key_features) == {
        "log_amount",
        "payment_method",
        "hour_bucket",
        "predicted_category",
    }


def test_fr_18_03_config_rejects_key_feature_outside_monitored_columns(tmp_path: Path) -> None:
    bad = tmp_path / "drift.yaml"
    bad.write_text(
        "version: x\nwindow_days: 7\nmin_rows: 1\npsi_threshold: 0.25\nkey_features: [nope]\n"
        "numeric_features: [a]\ncategorical_features: [b]\nunseen_ratio_threshold: 2\n"
        "unseen_history_days: 28\nunseen_min_history: 7\n"
    )
    with pytest.raises(ValueError, match="key_features"):
        load_config(bad)


def test_fr_18_03_no_drift_when_current_matches_reference() -> None:
    summary, snapshot = summarize(
        report_date=DAY,
        model_version="m@1",
        reference=frame(2000, seed=1),
        current=frame(600, seed=2),
        known_merchants=KNOWN,
        unseen_history=[],
        cfg=CFG,
        window=WINDOW,
    )
    assert summary.status == "ok" and snapshot is not None
    assert summary.drifted_features == []
    assert summary.psi_max is not None and summary.psi_max < CFG.psi_threshold


def test_fr_18_03_shifted_amount_and_payment_mix_are_flagged() -> None:
    summary, _ = summarize(
        report_date=DAY,
        model_version="m@1",
        reference=frame(2000, seed=1),
        current=frame(600, mu=11.5, cash=0.9, seed=3),
        known_merchants=KNOWN,
        unseen_history=[],
        cfg=CFG,
        window=WINDOW,
    )
    assert summary.status == "drift"
    assert {"log_amount", "payment_method"} <= set(summary.drifted_features)
    assert "hour_bucket" not in summary.drifted_features
    assert summary.psi_max is not None and summary.psi_max > CFG.psi_threshold


def test_fr_18_03_too_few_rows_skips_instead_of_computing() -> None:
    summary, snapshot = summarize(
        report_date=DAY,
        model_version="m@1",
        reference=frame(500),
        current=frame(CFG.min_rows - 1),
        known_merchants=KNOWN,
        unseen_history=[],
        cfg=CFG,
        window=WINDOW,
    )
    assert summary.status == "skipped" and snapshot is None and summary.psi == {}
    assert "minimum" in summary.reason


def test_fr_18_01_unseen_share_ignores_rows_without_merchant() -> None:
    current = frame(10)
    current["merchant_hash"] = [None] * 5 + ["ffffffffffff"] * 2 + [merchant_hash("m1")] * 3
    assert unseen_share(current, KNOWN) == pytest.approx(0.4)
    current["merchant_hash"] = None
    assert unseen_share(current, KNOWN) is None


def test_fr_18_01_unseen_alert_needs_history_and_two_times_the_median() -> None:
    history = [0.05] * 10
    median, ratio, alert = unseen_alert(0.11, history, CFG)
    assert median == pytest.approx(0.05) and ratio == pytest.approx(2.2) and alert
    assert unseen_alert(0.10, history, CFG)[2] is False  # exactly 2x is not above 2x
    assert unseen_alert(0.50, [0.05] * (CFG.unseen_min_history - 1), CFG) == (None, None, False)
    assert unseen_alert(0.5, [0.0] * 10, CFG) == (0.0, None, False)
    assert unseen_alert(None, history, CFG) == (None, None, False)


def test_fr_18_01_history_uses_only_the_configured_window() -> None:
    old = [9.0] * 5
    recent = [0.05] * CFG.unseen_history_days
    median, _, _ = unseen_alert(0.05, old + recent, CFG)
    assert median == pytest.approx(0.05)


def _log_line(**over: object) -> str:
    doc: dict[str, object] = {
        "event": "prediction",
        "shadow": False,
        "logged_at": "2026-03-08T10:00:00Z",
        "merchant_hash": "abc",
        "features_summary": {"log_amount": 10.7, "payment_method": "cash", "hour_bucket": "midday"},
        "output": {"predicted_category": "transport", "confidence": 0.9},
    }
    doc.update(over)
    return json.dumps(doc)


def test_fr_18_04_parse_lines_keeps_only_live_predictions() -> None:
    lines = [
        "ml-service-1  | " + _log_line(),  # docker compose prefix
        _log_line(shadow=True),
        _log_line(event="other"),
        "not json {oops",
        "plain text",
        _log_line(output={"predicted_category": "x"}),  # incomplete
        _log_line(merchant_hash=None),
    ]
    out = parse_lines(lines)
    assert len(out) == 2
    assert out["merchant_hash"].tolist()[0] == "abc"
    assert pd.isna(out["merchant_hash"].tolist()[1])
    assert str(out["logged_at"].dt.tz) == "UTC"


def test_fr_18_04_jsonl_source_filters_the_window(tmp_path: Path) -> None:
    path = tmp_path / "logs.txt"
    path.write_text(
        "\n".join(
            [
                _log_line(logged_at="2026-03-02T23:59:59Z"),
                _log_line(logged_at="2026-03-03T00:00:00Z"),
                _log_line(logged_at="2026-03-09T23:59:59Z"),
                _log_line(logged_at="2026-03-10T00:00:00Z"),
            ]
        )
    )
    out = JsonlLogSource([path]).fetch(*WINDOW)
    assert len(out) == 2


def test_fr_18_03_reference_roundtrip(tmp_path: Path) -> None:
    sample = frame(50)[["log_amount", "payment_method", "hour_bucket", "predicted_category"]]
    sample["confidence"] = 0.9
    folder = write_reference(tmp_path, sample, sorted(KNOWN))
    loaded, merchants = load_reference(folder)
    assert len(loaded) == 50 and merchants == KNOWN


def test_fr_18_03_local_store_is_idempotent_and_reads_history(tmp_path: Path) -> None:
    store = LocalStore(tmp_path)
    for offset, share in [(3, 0.04), (2, 0.06), (1, None)]:
        store.save(DAY - dt.timedelta(days=offset), None, {"unseen_merchant_share": share})
    assert store.history(DAY, 28) == [0.04, 0.06]  # oldest first, null skipped, missing skipped
    where = store.save(DAY, "<html/>", {"a": 1})
    store.save(DAY, "<html>2</html>", {"a": 2})
    assert json.loads((Path(where) / "summary.json").read_text()) == {"a": 2}
    assert (Path(where) / "report.html").read_text() == "<html>2</html>"
    assert store.history(DAY, 28) == [0.04, 0.06]  # today is never part of its own history


def test_fr_18_03_gcs_store_uploads_to_the_dated_path_and_skips_404() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "POST":
            return httpx.Response(200, json={})
        if "2026-03-09" in str(request.url) or "2026-03-09" in request.url.path:
            return httpx.Response(200, json={"unseen_merchant_share": 0.05})
        return httpx.Response(404)

    store = GcsStore("proj-reports", lambda: "tok", httpx.MockTransport(handler))
    where = store.save(DAY, "<html/>", {"x": 1})
    assert where == "gs://proj-reports/drift/2026-03-10/"
    uploads = [r for r in seen if r.method == "POST"]
    assert {r.url.params["name"] for r in uploads} == {
        "drift/2026-03-10/summary.json",
        "drift/2026-03-10/report.html",
    }
    assert all(r.headers["authorization"] == "Bearer tok" for r in seen)
    assert store.history(DAY, 3) == [0.05]


def test_fr_18_04_bigquery_source_parses_rows_and_creates_the_view() -> None:
    bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        if "CREATE OR REPLACE VIEW" in str(body["query"]):
            return httpx.Response(200, json={"jobComplete": True})
        fields = [
            {"name": n}
            for n in (
                "logged_at",
                "log_amount",
                "payment_method",
                "hour_bucket",
                "predicted_category",
                "confidence",
                "merchant_hash",
            )
        ]
        row = ["1772931600.0", "10.7", "cash", "midday", "transport", "0.9", None]
        return httpx.Response(
            200,
            json={
                "jobComplete": True,
                "schema": {"fields": fields},
                "rows": [{"f": [{"v": v} for v in row]}],
            },
        )

    source = BigQueryLogSource("proj", lambda: "tok", httpx.MockTransport(handler))
    source.ensure_view()
    out = source.fetch(*WINDOW)
    assert "predictions.prediction_logs" in str(bodies[0]["query"])
    assert "run_googleapis_com_stdout" in str(bodies[0]["query"])
    assert bodies[1]["parameterMode"] == "NAMED"
    assert len(out) == 1 and out["log_amount"].iloc[0] == pytest.approx(10.7)
    assert pd.isna(out["merchant_hash"].iloc[0])


def test_fr_18_03_job_writes_html_and_summary_and_is_idempotent(tmp_path: Path) -> None:
    ref = frame(1500, seed=1)[["log_amount", "payment_method", "hour_bucket", "predicted_category"]]
    ref["confidence"] = 0.9
    (tmp_path / "model").mkdir()
    folder = write_reference(tmp_path / "model", ref, sorted(KNOWN))
    logs = tmp_path / "logs.txt"
    cur = frame(300, mu=11.5, seed=4)
    lines = [
        _log_line(
            logged_at="2026-03-08T10:00:00Z",
            merchant_hash=r.merchant_hash,
            features_summary={
                "log_amount": float(r.log_amount),
                "payment_method": r.payment_method,
                "hour_bucket": r.hour_bucket,
            },
            output={"predicted_category": r.predicted_category, "confidence": float(r.confidence)},
        )
        for r in cur.itertuples()
    ]
    logs.write_text("\n".join(lines))
    store = LocalStore(tmp_path / "reports")
    results = [
        job.run_drift_report(
            report_date=DAY,
            reference_dir=folder,
            model_version="m@1",
            source=JsonlLogSource([logs]),
            store=store,
            cfg=CFG,
        )
        for _ in range(2)
    ]
    assert results[0].to_dict() == results[1].to_dict()
    out = tmp_path / "reports" / "drift" / "2026-03-10"
    assert (out / "report.html").stat().st_size > 10_000
    saved = json.loads((out / "summary.json").read_text())
    assert saved["status"] == "drift" and "log_amount" in saved["drifted_features"]
    text = (out / "summary.json").read_text()
    assert "description" not in text and "user" not in text  # numbers and feature names only


def test_fr_18_03_job_without_reference_stops_with_a_clear_error() -> None:
    class Missing:
        def get_model_version_by_alias(self, *_: object) -> object:
            import mlflow

            raise mlflow.exceptions.MlflowException("no alias")

    from pipelines.data_steps import PipelineError

    with pytest.raises(PipelineError, match="NO_PRODUCTION"):
        job.fetch_reference(Missing(), "transaction-classifier", Path("."))  # type: ignore[arg-type]


def test_fr_18_03_default_config_type() -> None:
    assert isinstance(CFG, DriftConfig)
