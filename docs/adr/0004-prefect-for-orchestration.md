# ADR-0004: Prefect 3 for pipeline orchestration

- Status: accepted
- Date: 2026-11-19
- PRD sections affected: 3.3 (C10), 15, 16.1, 16.7

## Context
Training, evaluation, gating, registration, batch scoring, drift reports, and exports must run as reproducible pipelines, both on a laptop and as scheduled jobs on GCP. PRD v2.0 left the orchestrator open between Prefect and Airflow. One developer maintains everything.

## Options considered
1. **Apache Airflow** — industry standard; but needs a scheduler, webserver, and metadata DB, DAG-file conventions, and is heavy to run locally for one project.
2. **Prefect 3** — flows are plain Python functions, run locally with no server, and deploy as Cloud Run Jobs.
3. **Plain scripts + cron / Cloud Scheduler** — minimal, but no task-level retries, observability, or structured flow runs.

## Decision
Option 2. Pipelines in `pipelines/` are Prefect 3 flows (e.g. `train_model(model_name, dataset_version)`), run locally via `make train` and in GCP as Cloud Run Jobs triggered by Cloud Scheduler. Airflow is documented as the alternative.

## Consequences
- Positive: low setup cost; flows are testable Python; same code locally and in the cloud.
- Negative: less familiar than Airflow to some reviewers — the ADR explains the trade-off.
- Revisit if: the number of pipelines and cross-team dependencies grows to the point where Airflow's ecosystem pays off.
