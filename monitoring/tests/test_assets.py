"""Monitoring assets (PRD 18): dashboards and alert rules only use metrics that exist."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
FUNCTIONS = {
    "sum", "rate", "increase", "histogram_quantile", "max", "by", "le", "and", "or", "without",
    "avg", "min", "count", "irate", "unless", "on", "ignoring", "group_left", "group_right",
}  # fmt: skip


def registered_names() -> set[str]:
    import app.main  # noqa: F401  (registers every backend metric)
    from ml_service.metrics import REGISTRY as ML
    from prometheus_client import REGISTRY as BACKEND

    names: set[str] = set()
    for registry in (BACKEND, ML):
        for family in registry.collect():
            names.add(family.name)
            for suffix in ("_total", "_bucket", "_count", "_sum", "_created", "_info"):
                names.add(family.name + suffix)
    return names


def used_metrics(expr: str) -> set[str]:
    expr = re.sub(r'"[^"]*"', '""', expr)  # string literals
    expr = re.sub(r"\{[^}]*\}", "", expr)  # label matchers
    expr = re.sub(r"\[[^\]]*\]", "", expr)  # ranges
    expr = re.sub(r"\b(by|without|on|ignoring)\s*\([^)]*\)", "", expr)
    tokens = set(re.findall(r"[a-zA-Z_:][a-zA-Z0-9_:]*", expr))
    return {t for t in tokens if t not in FUNCTIONS and not t.isdigit()}


def dashboards() -> list[Path]:
    return sorted((ROOT / "dashboards").glob("*.json"))


def alert_rules() -> list[dict[str, object]]:
    data = yaml.safe_load((ROOT / "prometheus" / "alerts.yml").read_text())
    return [rule for group in data["groups"] for rule in group["rules"]]


def test_18_6_the_four_dashboards_of_the_prd_exist_with_unique_uids() -> None:
    boards = [json.loads(p.read_text()) for p in dashboards()]
    assert {p.stem for p in dashboards()} == {
        "service-health", "model-health", "data-health", "pipelines-jobs"
    }  # fmt: skip
    assert len({b["uid"] for b in boards}) == 4
    for board in boards:
        ids = [p["id"] for p in board["panels"]]
        assert len(ids) == len(set(ids)), board["title"]


@pytest.mark.parametrize("path", dashboards(), ids=lambda p: p.stem)
def test_18_6_every_dashboard_query_uses_a_registered_metric(path: Path) -> None:
    known = registered_names()
    board = json.loads(path.read_text())
    queries = [t["expr"] for p in board["panels"] for t in p.get("targets", [])]
    assert queries, "a dashboard without queries is empty"
    for expr in queries:
        unknown = used_metrics(expr) - known
        assert not unknown, f"{path.stem}: {unknown} in {expr}"


@pytest.mark.parametrize("path", dashboards(), ids=lambda p: p.stem)
def test_18_6_dashboards_never_group_by_user_or_transaction_ids(path: Path) -> None:
    board = json.loads(path.read_text())
    queries = " ".join(t["expr"] for p in board["panels"] for t in p.get("targets", []))
    assert not re.search(r"user_id|transaction_id|merchant", queries)


def test_18_7_every_alert_has_a_severity_summary_and_runbook_link() -> None:
    rules = alert_rules()
    assert {r["alert"] for r in rules} >= {
        "BackendLatencyP95High", "High5xxRate", "MlCircuitOpen", "OutboxBacklogGrowing"
    }  # fmt: skip
    for rule in rules:
        assert rule["labels"]["severity"] in {"warning", "critical"}  # type: ignore[index]
        ann = rule["annotations"]
        assert ann["summary"] and ann["runbook"].startswith("docs/RUNBOOK.md#")  # type: ignore[index]


def test_18_7_every_alert_expression_uses_a_registered_metric() -> None:
    known = registered_names()
    for rule in alert_rules():
        unknown = used_metrics(str(rule["expr"])) - known
        assert not unknown, f"{rule['alert']}: {unknown}"


def test_18_1_alert_thresholds_match_the_prd() -> None:
    by_name = {r["alert"]: r for r in alert_rules()}
    assert "> 0.02" in str(by_name["High5xxRate"]["expr"]) and by_name["High5xxRate"]["for"] == "5m"
    assert by_name["BackendLatencyP95High"]["for"] == "10m"
    assert by_name["MlCircuitOpen"]["for"] == "5m" and "== 2" in str(
        by_name["MlCircuitOpen"]["expr"]
    )


def test_18_1_prometheus_scrapes_every_service_and_loads_the_rules() -> None:
    cfg = yaml.safe_load((ROOT / "prometheus" / "prometheus.yml").read_text())
    jobs = {j["job_name"]: j["static_configs"][0]["targets"][0] for j in cfg["scrape_configs"]}
    assert jobs == {
        "backend": "backend:8000", "worker": "worker:8000", "ml-service": "ml-service:8080"
    }  # fmt: skip
    assert cfg["rule_files"] == ["/etc/prometheus/alerts.yml"]
