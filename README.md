# Smart Expense Intelligence

> **Status: work in progress.** Built over 10 weeks against the spec in [`docs/PRD.md`](docs/PRD.md). Progress is tracked in [`docs/PROGRESS.md`](docs/PROGRESS.md). Results, demo link, and screenshots will be added once they come from real runs.

## The problem

Many students and young professionals in Indonesia lose track of their daily spending. Existing expense trackers make them record and categorize every transaction by hand, small recurring payments go unnoticed, unusual spending is found only after the balance is low, and nobody can tell whether the money will last until the end of the month. Smart Expense Intelligence uses machine learning to categorize transactions automatically, flag unusual spending with reasons, forecast end-of-period spending with an uncertainty range, detect recurring payments, and produce insights that can be traced back to the user's own data.

## Planned features

- Transactions: manual entry and two-step CSV import (preview → atomic commit)
- Automatic categorization with calibrated confidence and per-user merchant memory
- Analytics dashboard and budgets with threshold notifications
- Anomaly detection with explainable reasons
- Period-end forecasting with P10/P50/P90 range
- Recurring expense detection and rule-based insights
- MLOps: Prefect pipeline, MLflow registry, promotion gates, shadow mode, one-command rollback, monitoring

All training and demo data is synthetic (see [ADR-0008](docs/adr/0008-synthetic-data-only.md)).

## Tech stack

Python 3.12 (uv), FastAPI, PostgreSQL, scikit-learn / LightGBM / statsmodels, MLflow, Prefect 3, Evidently, Next.js + TypeScript, Docker, Terraform, GitHub Actions, Google Cloud (Cloud Run, Cloud SQL, Pub/Sub, BigQuery, GCS).

## Setup

> The scaffold is not built yet (task T-01). These commands are the target interface from PRD §19.1.

Requirements: Docker, [uv](https://docs.astral.sh/uv/), Node 22 LTS + pnpm, make.

```bash
make setup   # install toolchains, pre-commit hooks, create .env from .env.example
make demo    # generate synthetic data, train baseline models, start the stack, seed a demo user
make check   # lint, type-check, tests, coverage gates
```

No GCP account is needed to run locally.

## Documentation

- [Product requirements (PRD v3.0)](docs/PRD.md)
- [Architecture decision records](docs/adr/)
- [Decisions log](docs/DECISIONS.md)
- [Privacy](docs/PRIVACY.md) · [Security policy](SECURITY.md)

## License

[TBD]
