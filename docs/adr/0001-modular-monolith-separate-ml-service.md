# ADR-0001: Backend is a modular monolith; ML inference is a separate service

- Status: accepted
- Date: 2026-11-19
- PRD sections affected: 6.1, 6.3, 6.4, 14.1, 22

## Context
The product has business logic (auth, transactions, budgets, analytics, insights, notifications) and ML inference (classification, anomaly scoring, forecasting, clustering). The two parts have different dependencies (scikit-learn, LightGBM, possibly PyTorch vs. a lean web stack), different image sizes, and different release cycles: models change through the registry, business logic through code deploys. The project is built by one person in ~10 weeks, so operational overhead must stay small.

## Options considered
1. **Single service containing everything** — simplest deploy; but ML dependencies bloat the API image, a model load failure can take the whole API down, and model releases are coupled to code releases.
2. **Microservices per domain** (auth, transactions, budgets, ML…) — clean boundaries on paper; far too much operational and contract overhead for one developer, and the business domains share one database anyway.
3. **Modular monolith backend + separate stateless ML service** — business logic stays in one codebase with clear internal modules; ML is isolated where the boundary is real.

## Decision
Option 3. `services/backend` is a modular monolith (routers → services → repositories) and also runs as the `worker` role from the same image. `services/ml_service` is a stateless FastAPI inference service that never reads the user database, loads models by MLflow alias, and is called by the backend with a 300 ms timeout and a circuit breaker.

## Consequences
- Positive: ML can fail, scale, and be rolled back independently; saving a transaction never depends on ML (fallback to `needs_review`, PRD 6.3).
- Positive: one clear, written contract between backend and ML (PRD §14) — good evidence of cross-team API design.
- Negative: a network hop on the categorization path; requires timeout, retry policy, circuit breaker, and IAM between services.
- Negative: online features must be computed somewhere outside the ML service → ADR-0002.
- Revisit if: a business domain develops a truly independent scaling or release need.
