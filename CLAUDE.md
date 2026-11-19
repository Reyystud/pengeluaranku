# CLAUDE.md — Smart Expense Intelligence

Read this file at the start of every session. It is the short map; `docs/PRD.md` (v3.0, ~2,800 lines) is the single source of truth. Do not read the whole PRD each time — use the section map below.

## Session start checklist

1. Read `docs/PROGRESS.md` → find the current task (T-NN), its status, and the last handoff note.
2. Read the PRD sections listed for that task's area (map below) and the task line in PRD §20.3.
3. Check `docs/DECISIONS.md` and `docs/adr/` for decisions that amend the PRD.
4. Work on **one task ID** per session/PR. Leave the system runnable.
5. Before ending: update `docs/PROGRESS.md` (status + handoff note), log small decisions in `docs/DECISIONS.md`.

## Non-negotiable rules (PRD §0.3)

1. **Vertical slices.** Every task leaves `make check` green and `docker compose up` working.
2. **Never invent numbers.** Metrics in README/docs/UI/CV come from a real run (MLflow run ID or test report). Until then write `[TBD after run]`.
3. **No hardcoded ML thresholds** in business code. They live in model `metadata.json` (§11.6) or versioned `config/` files.
4. **Never log** raw descriptions, merchant names, notes, user-tied amounts, emails, passwords, tokens, cookies, Authorization headers, raw CSV (§17.3). Logs use `user_pseudo_id`, never raw `user_id`.
5. **Never commit** secrets, real personal financial data, or large datasets. Synthetic data from a seed only (§10.1).
6. **Every user-scoped query filters by the authenticated `user_id`** via repository helpers (§12.4). Cross-user access returns 404.
7. **Money is never a float.** `Decimal` in Python, `NUMERIC(15,2)` in PostgreSQL, string in JSON (`"25000.00"`). Floats only inside ML feature code (`log1p(amount)`) (§4.3).
8. **Ambiguity:** pick the simplest option consistent with the PRD, implement it, record it (ADR for design-level, one line in `docs/DECISIONS.md` for small ones). Don't block.
9. **Contract change** (DB, API, event, ML request/response) → update the PRD section in the same PR + Alembic migration + version bump.
10. **Tests come with code.** Reference requirement IDs in test names: `test_fr_02_07_commit_is_atomic_on_db_error`.
11. **Out of scope:** Kafka, Kubernetes, managed feature store, LLM features, bank sync, OCR, multi-currency, email/push notifications (§3.2). Propose via ADR instead.
12. **Runs locally without GCP** (§19.1). Cloud code sits behind an interface with a local implementation.

Precedence when sources disagree (§0.2): PRD v3.0 → accepted ADRs that amend it → generated OpenAPI → (PRD v1/v2 are historical only).

## Key domain conventions

- IDs: UUIDv7, generated in the app. Timestamps: `TIMESTAMPTZ` UTC; all day/week/period logic in the **user's timezone** (default `Asia/Jakarta`). Week starts Monday (§4.2).
- `amount` always > 0; direction from `transaction_type` ∈ `income | expense | transfer`. Transfers are excluded from income/expense totals (§4.4).
- "Month" = the user's **budget period** (start day 1–28), never the calendar month (§4.5).
- Categories are fixed, seeded slugs (`taxonomy-1`); `uncategorized` is never a model label (§4.6).
- Enums stored as `TEXT` + `CHECK`; tables plural snake_case; JSON snake_case (§4.8).
- Saving a transaction **must never fail because the ML service is down** → `needs_review` (§6.3).
- MLflow model names: `transaction-classifier`, `anomaly-detector`, `expense-forecaster`, `behavior-clusterer`; use aliases `production`/`candidate`/`previous`, not stages.
- Commits: Conventional Commits (`feat:`, `fix:`, `ml:`, `infra:`, `docs:`), trunk-based, squash merge.

## Commands (PRD §19.1 — created in T-01/T-29; may not exist yet)

| Command | Purpose |
|---|---|
| `make setup` | Install toolchains (uv, pnpm), pre-commit, copy `.env.example` → `.env` |
| `make check` | Lint + types + tests + coverage gates — **must pass before finishing a task** |
| `make test` / `make test-integration` | Unit / integration (testcontainers) tests |
| `make data` | Generate synthetic dataset (default seed) |
| `make train-local` | Train baselines, register to local MLflow |
| `make demo` | `data` + `train-local` + `up` + `seed-demo` |
| `make up` / `make down` | Docker compose up/down |
| `make openapi` | Regenerate OpenAPI specs + frontend client |
| `make train MODEL=… DATASET=…` | Full Prefect training pipeline |
| `make promote` / `make rollback` | MLflow alias management |

Stack (§6.5): Python 3.12 + `uv` workspace, FastAPI, SQLAlchemy 2 (sync, `lazy="raise"`), Alembic, Pydantic v2; scikit-learn/LightGBM/statsmodels; MLflow, Prefect 3, Evidently, Pandera; Next.js + TS strict + pnpm; Docker, Terraform, GitHub Actions. **Adding a library not in §6.5 requires a line in `docs/DECISIONS.md`.**

## Repository layout (PRD §22)

```text
frontend/            Next.js app
services/backend/    FastAPI (also runs as `worker` with ROLE=worker): app/{api,core,models,schemas,services,repositories,events,jobs,clients}, migrations/, tests/{unit,integration,security}
services/ml_service/ FastAPI inference only — stateless, never reads the user DB
ml/                  Shared library: preprocessing, features, classification, anomaly_detection, forecasting, clustering, recurring, evaluation, schemas
data_generator/      Synthetic generator
pipelines/           Prefect flows (train, gate, register, promote, drift, exports)
config/              generator/, train/, insights.yaml, merchant_aliases.yaml, holidays_id.yaml, label_maps/
schemas/events/      JSON Schemas for events
monitoring/          Grafana, Prometheus, alert rules, Evidently
infrastructure/      terraform/ (GCP), docker/
docs/                PRD, ADRs, PROGRESS, DECISIONS, and result docs
data/, models/       gitignored; data_splits/ is committed
```

## PRD section map — read before working on…

| Working on | Read in `docs/PRD.md` |
|---|---|
| Anything (first time) | §0, §3 (scope, non-goals, conflict resolutions C1–C12), §4 (conventions) |
| Repo scaffold, Makefile, CI | §6.5, §19.1, §19.5, §21.1, §22 |
| Synthetic data, EDA, splits | §10 (esp. 10.1, 10.4), §4.6 |
| Merchant normalization / preprocessing | §7.3.2, §7.3.3, §11.1 |
| Features | §11 (point-in-time + parity rules in 11.1) |
| Classifier training/eval | §7.3, §9.1, §9.2, §9.6, §21.4 |
| Backend scaffold, logging, errors | §13.1, §17.3 |
| DB schema / migrations / repositories | §12 |
| Auth, accounts | §7.1 (FR-01), §13.1.1, §17.1 |
| Transactions, CSV import, duplicates | §7.2 (FR-02), §13.2, §13.3 |
| Categorization flow, ML client, circuit breaker | §6.3, §6.4, §7.3 (FR-03), §7.10 (FR-10), §7.15 (FR-15) |
| ML service | §11.3–11.6, §14.1, §14.2 |
| Analytics / budgets / notifications | §7.4, §7.5, §7.14 (FR-04/05/14), §4.5 |
| Anomaly detection | §7.6 (FR-06), §9.3, §11.2.2 |
| Forecasting | §7.7 (FR-07), §9.4, §11.2.3 |
| Recurring / insights / clustering | §7.8, §7.9, §7.13, §9.5 |
| Events, outbox, worker | §6.3, §7.11 (FR-11), §14.3 |
| Batch jobs | §15 |
| MLOps pipeline, gates, shadow, rollback | §16 |
| Security & privacy | §17 |
| Monitoring, metrics, runbook | §18 |
| Config / env vars / GCP | §19.2–19.4 |
| Tests | §21 (required named tests in 21.2) |
| Frontend | §8 |
| Acceptance / Definition of Done | §26 |
| Task list & dependencies | §20.3 |

## Where things are recorded (§0.4)

| What | Where |
|---|---|
| Task status + session handoff | `docs/PROGRESS.md` |
| Architecture decisions | `docs/adr/NNNN-kebab-title.md` (template: `docs/adr/0000-template.md`) |
| Small decisions (one line) | `docs/DECISIONS.md` |
| Open questions Q1–Q5 | PRD §25 (status mirrored in `docs/PROGRESS.md`) |
| Model results | `docs/MODEL_EVALUATION.md` + MLflow (create only from real runs) |

Result docs (`EDA.md`, `DATA_SOURCES.md`, `MODEL_EVALUATION.md`, `model_cards/`, `RUNBOOK.md`, `API.md`, `ARCHITECTURE.md`) are written **when their task produces real content** — never pre-filled with made-up results.
