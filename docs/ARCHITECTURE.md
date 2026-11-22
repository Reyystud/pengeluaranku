# Architecture

The full design is [PRD section 6](PRD.md); this page is the short version, with what exists in the repository today. Decision records: [`docs/adr/`](adr/) and [`DECISIONS.md`](DECISIONS.md).

## Components

| Component | Where | Role |
|---|---|---|
| frontend | `frontend/` | Next.js. Calls only the backend, same origin `/api/v1/*` (Next rewrites to the backend, so the SameSite refresh cookie works without CORS). |
| backend | `services/backend/` | FastAPI modular monolith: auth, transactions, CSV import, budgets, analytics, anomalies, forecasts, recurring, insights, segments, notifications, merchant rules. Owns PostgreSQL. Also runs as `worker` (`ROLE=worker`) for Pub/Sub push endpoints and batch jobs under `/internal/*`. |
| ml-service | `services/ml_service/` | Stateless inference. Never reads the user database. Loads models by MLflow alias, logs predictions, runs the candidate in shadow mode. |
| `ml/` | shared library | Preprocessing, features, classifier, anomaly detection, forecasting, clustering, recurring detection, evaluation. Imported by training and by the backend so batch and online features cannot differ. |
| pipelines | `pipelines/` | Prefect flows: train, gate, register, promote, drift report, shadow evaluation. |
| infrastructure | `infrastructure/` | Docker, Terraform for GCP (Cloud Run, Cloud SQL, Pub/Sub, BigQuery, Cloud Scheduler, Monitoring). Offline `terraform test` only; nothing has been applied. |

## Request flow: creating a transaction

1. The frontend sends `POST /api/v1/transactions` with an `Idempotency-Key`.
2. The backend validates, normalizes the merchant, and checks the user's merchant rules. A rule wins and no model is called.
3. Otherwise it calls `ml-service /v1/classify` (300 ms timeout, circuit breaker). If the call fails the transaction is saved as `needs_review`: saving never fails because the ML service is down.
4. The transaction, its prediction and an outbox event are written in one database transaction.
5. The outbox relay publishes `transaction.created`; the worker consumes it idempotently and scores anomalies.

## Batch work

Daily and weekly jobs (`services/backend/app/jobs/catalogue.py`) run per user in the worker: budget close, forecasts, category surge, recurring refresh, insights, due-soon notices, review reminders, and `clustering-weekly` (behavior segment). Heavy jobs (drift report, training) run as pipelines.

## ML lifecycle

Train, evaluate against a baseline, gate, register in MLflow with `metadata.json`, set alias `candidate`, run shadow, promote to `production` with `promotion.promote`, roll back with `make rollback`. Thresholds live in model metadata or versioned `config/` files, never in business code.

## Boundaries that matter

- Every user-scoped query filters by the authenticated `user_id` through repository helpers; cross-user access returns 404.
- Money is `Decimal` / `NUMERIC(15,2)` / a string in JSON.
- Logs carry `user_pseudo_id`, never raw ids, descriptions or amounts tied to a user.
- All data is synthetic.

## What is not built or not deployed

- No GCP deployment has been made; the Terraform has only been validated and tested offline. See "Known gaps" in `infrastructure/terraform/README.md`.
- The data export endpoint (FR-16, a "Could") is not built; the Settings page says so.
- The scheduler is paused and BigQuery sources are not wired.
