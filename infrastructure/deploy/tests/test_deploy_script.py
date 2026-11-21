"""deploy.sh against a fake ``gcloud`` (PRD 19.5): digests, ordering, rollback, failure handling."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "deploy.sh"

FAKE_GCLOUD = """#!/usr/bin/env bash
echo "$*" >> "$CALLS"
case "$*" in
  *"artifacts docker images describe"*)
    ref="$5"; name="${ref##*/}"; name="${name%%:*}"
    [[ "$MISSING" == "$name" ]] && exit 1
    echo "sha256:digest-of-$name" ;;
  *"run services describe"*)
    svc="$4"; echo "$svc-00001" ;;
  *"run jobs execute"*) [[ "$MIGRATE_FAILS" == "1" ]] && exit 1 ;;
  *"update-traffic"*"--to-revisions"*) [[ "$ROLLBACK_FAILS" == "$4" ]] && exit 1 ;;
esac
exit 0
"""


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "gcloud"
    fake.write_text(FAKE_GCLOUD)
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    return {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "CALLS": str(tmp_path / "calls.txt"),
        "STATE_DIR": str(tmp_path / "state"),
        "PROJECT_ID": "p",
        "REGION": "r",
        "REGISTRY": "r-docker.pkg.dev/p/sei",
        "TAG": "abc123",
        "MISSING": "",
        "MIGRATE_FAILS": "0",
        "ROLLBACK_FAILS": "",
    }


def run(arg: str, env: dict[str, str]) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    done = subprocess.run(
        ["bash", str(SCRIPT), arg], env=env, capture_output=True, text=True, check=False
    )
    calls = Path(env["CALLS"])
    return done, calls.read_text().splitlines() if calls.exists() else []


def test_fr_19_05_migrate_updates_the_job_to_the_backend_digest_then_waits_for_it(
    env: dict[str, str],
) -> None:
    done, calls = run("migrate", env)
    assert done.returncode == 0, done.stderr
    update = next(c for c in calls if "run jobs update migrate" in c)
    assert "--image r-docker.pkg.dev/p/sei/backend@sha256:digest-of-backend" in update
    assert calls.index(update) < next(i for i, c in enumerate(calls) if "run jobs execute" in c)
    assert any("--wait" in c for c in calls if "run jobs execute" in c)


def test_fr_19_05_failed_migration_fails_the_step(env: dict[str, str]) -> None:
    done, _ = run("migrate", {**env, "MIGRATE_FAILS": "1"})
    assert done.returncode != 0


def test_fr_19_05_deploy_pins_every_service_to_a_digest_never_a_tag(env: dict[str, str]) -> None:
    done, calls = run("deploy", env)
    assert done.returncode == 0, done.stderr
    updates = [c for c in calls if c.startswith("run services update ")]
    assert len(updates) == 5
    assert all("@sha256:" in c and ":abc123" not in c for c in updates)
    worker = next(c for c in updates if " worker " in c)
    assert "/backend@sha256:digest-of-backend" in worker  # the worker runs the backend image


def test_fr_19_05_deploy_records_live_revisions_before_changing_anything(
    env: dict[str, str],
) -> None:
    done, calls = run("deploy", env)
    assert done.returncode == 0
    first_update = next(i for i, c in enumerate(calls) if c.startswith("run services update "))
    describes = [i for i, c in enumerate(calls) if "run services describe" in c]
    assert describes and max(describes) < first_update
    recorded = Path(env["STATE_DIR"], "previous-revisions.txt").read_text().splitlines()
    assert "backend backend-00001" in recorded and len(recorded) == 5


def test_fr_19_05_deploy_returns_traffic_to_latest_after_each_update(env: dict[str, str]) -> None:
    _, calls = run("deploy", env)
    assert sum("update-traffic" in c and "--to-latest" in c for c in calls) == 5


def test_fr_19_05_missing_image_stops_the_deploy_before_any_change(env: dict[str, str]) -> None:
    done, calls = run("deploy", {**env, "MISSING": "frontend"})
    assert done.returncode != 0
    assert not any(c.startswith("run services update") for c in calls)


def test_fr_19_05_rollback_restores_the_recorded_revisions(env: dict[str, str]) -> None:
    run("deploy", env)
    done, calls = run("rollback", env)
    assert done.returncode == 0, done.stderr
    traffic = [c for c in calls if "--to-revisions" in c]
    assert len(traffic) == 5
    assert any(" backend " in c and "--to-revisions backend-00001=100" in c for c in traffic)


def test_fr_19_05_rollback_tries_every_service_and_reports_a_failure(env: dict[str, str]) -> None:
    run("deploy", env)
    done, calls = run("rollback", {**env, "ROLLBACK_FAILS": "mlflow"})
    assert done.returncode != 0
    assert sum("--to-revisions" in c for c in calls) == 5


def test_fr_19_05_rollback_without_a_record_refuses(env: dict[str, str]) -> None:
    done, _ = run("rollback", env)
    assert done.returncode != 0
    assert "nothing recorded" in done.stderr


def test_fr_19_05_unknown_command_is_a_usage_error(env: dict[str, str]) -> None:
    done, _ = run("explode", env)
    assert done.returncode == 2
