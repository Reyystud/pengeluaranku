# Progress

Status of every task in PRD §20.3. Update this file at the end of each session.

Status values: `todo` · `in-progress` · `blocked` · `done` · `cut` (dropped at a cut line, with reason).

**Current focus:** next T-20 (see task list); remember the `suggest` band is empty and unseen merchants are over-confident (T-09/T-10 notes)
**Current tier:** A (weeks 1–6) — target: Cut line A (`make demo` works locally)

---

## Session handoff

Newest entry on top. Keep each entry short: what was done, what is half-done, what to do next, gotchas.

### 2026-11-20 — T-19 Frontend scaffold
- Done: `frontend/` Next.js 16 (App Router, TS strict, Tailwind v4). Pages: landing, `/login`, `/register`, `/transactions` (filters, table that becomes cards on phones, add/edit drawer with live categorization chip and quick picks, bulk delete, review-queue tab with badge, confirm suggestion, dismiss duplicate), `/transactions/import` (upload, preview with per-row status/errors and editable categories, commit options, result), `/dashboard` and `/settings` as empty states. In-memory access token, one shared refresh then retry, redirect to `/login`. Loading, empty and error states (error shows `request_id` with Copy). `t()` strings in `src/messages/en.json`. `services/backend/openapi.json` + generated `src/api/schema.d.ts`, `make openapi`, `make openapi-check`, `make web`, CI job `frontend`.
- Verified: 41 Vitest tests (money/time helpers, API client refresh/error mapping, chip states, drawer preview/validation/idempotency, auth forms, hook headers) + 1 live contract test run against the real backend through the Next proxy (register, categories, preview, create with replay, list, bulk delete); `next build` ok; lint, tsc and prettier clean. The smoke run found the missing `Idempotency-Key` and the `deleted` response field, both fixed. Not verified: real browser rendering, mobile layout by eye, Lighthouse/axe (no browser tooling here), Playwright flows.
- Hooks for later: T-20 dashboard (add Recharts there), T-42 settings (merchant rules API exists), `frontend/AGENTS.md` is ignored (Next writes it unless `agentRules: false`, now set).
- Not done: demo login button (T-29), notifications and budgets pages, E2E.
- Next: T-20.

### 2026-11-20 — T-18 Backend ML client and categorization flow
- Done: `app/clients/ml.py` (`MlClient`, `CircuitBreaker`), `app/services/categorization.py` (rule -> ML -> fallback, FR-03.10), `app/repositories/categorization.py`, `app/api/merchant_rules.py`. New endpoints: `POST /transactions/categorize-preview` (60/min), `/{id}/confirm-category`, `/{id}/recategorize`, `GET/PATCH/DELETE /merchant-rules`; `PATCH /transactions/{id}` gained `apply_to_past_merchant_transactions`. Create and CSV preview/commit write `category_predictions`; category changes write `category_feedback` and upsert merchant rules. CSV preview classifies in one batch call. Saving never fails because of the ML service (tested for timeout, 5xx, connect error, garbage body, open circuit).
- Verified: unit tests for client/breaker/interpretation (22), integration tests for the flow (25, fake ML over `MockTransport`), BOLA suite extended to `merchant-rules`; contract test against the real ML service schemas. Backend coverage ~98.7%. Decisions in `docs/DECISIONS.md`, PRD addendum at the end of `docs/PRD.md`.
- Not done: `/internal/jobs/recategorize-needs-review` (T-37), Google ID-token auth to the ML service, anomaly/forecast calls (T-23+).
- Next: T-19 (frontend scaffold: auth, layout, API client, transactions page, review queue, CSV import UI).

### 2026-11-20 — T-17 ML inference service
- Done: `services/ml_service/ml_service/` (`config`, `errors`, `schemas`, `inference`, `main`, `__main__`, `api/{classify,models,health}`, `loading/{artifact,sources,registry}`, `metrics`). `POST /v1/classify`, `POST /v1/classify/batch` (≤ 500), `GET /v1/models`, `/healthz`, `/readyz`, `/metrics`. Model sources: `local_dir` and MLflow alias. Hash verification before unpickling, thresholds only from `metadata.json`. `make ml-api` runs it on :8080.
- Verified: 66 service tests (toy model trained inside the tests, MLflow registry in a temp sqlite store, tamper/threshold/label cases, parity with the offline pipeline, privacy sentinel) plus one smoke test with the real T-09 model that skips when `models/` is absent; `make check` green with PostgreSQL: 390 non-integration tests and 285 backend tests, backend coverage 98.9%. Real model: `STARBUCKS GRAND INDONESIA` gives `food_beverage`, `auto_apply`.
- Hooks for later: T-18 builds the backend client against `ClassifyRequest`/`ClassifyResponse` (send `merchant_key` from `resolve_merchant`, `weekday` Monday = 0, explicit `local_hour: null`; handle all three decisions, `suggest` is absent with the current thresholds). T-27 adds alias polling/hot-swap on `ModelRegistry.load()`. Dockerfile and compose come with T-29.
- Not done: anomaly, forecast, cluster endpoints and shadow mode (their tasks), Google ID-token auth, `services/ml_service/openapi.json`, load benchmark.
- Next: T-18 (backend ML client, circuit breaker, categorization flow, merchant rules, feedback, categorize-preview).

### 2026-11-20 — T-16 BOLA/IDOR suite
- Done: `tests/security/test_bola.py` (8 tests). Routes are auto-discovered from OpenAPI; all 7 operations with an id return 404 for another user, with the same response as a nonexistent id, and leave the victim's data unchanged. Also bulk ids in bodies (atomic), list/count/search/filter leakage, cursors of another user, 401 without or with a garbage token on every non-public route, and tokens of a deleted account.
- Gotcha: a new endpoint with a path id fails the coverage test until it gets a factory in `RESOURCES` (and a body in `BODIES` if it needs one). Public routes are listed in `PUBLIC_PREFIXES`.
- Next: T-17 (ML inference service).

### 2026-11-20 — T-15 CSV import
- Done: `GET /transactions/imports/template.csv`, `POST /transactions/imports` (preview), `GET /transactions/imports/{id}` (paginated rows), `POST .../commit` (strict / skip_invalid, skip_duplicates, category_overrides, idempotent), `DELETE .../{id}`. All 10 row error codes plus file-level errors (413/422), delimiter detection, BOM, Indonesian amounts (`Rp 1.500.000`), five date formats in the user's timezone, duplicates against existing rows and within the file, `FILE_ALREADY_IMPORTED`, atomic commit, outbox events.
- Verified: see the T-15 test files `tests/unit/test_csv_parse.py` and `tests/integration/test_imports_api.py` (31 integration tests, including a 5,000-row commit, a forced DB failure that persists nothing, and concurrent commits); `make check` green with PostgreSQL: 277 backend tests, coverage 98.9%.
- Hooks for later: T-18 should replace the per-row `Categorizer` call in preview with a batch call and write `category_predictions`; T-37 cleanup job marks expired imports; T-16 BOLA suite can add the import endpoints (`test_fr_02_01_other_users_imports_are_404_everywhere`).
- Not done: per-user cap on open previews, upload rate limit, `csv_imports_total` metric, duplicate re-check at commit.
- Next: T-16 (BOLA/IDOR suite).

### 2026-11-20 — T-14 transactions
- Done: `GET/POST /transactions`, `GET /transactions/count`, `GET/PATCH/DELETE /transactions/{id}`, `POST /transactions/{id}/dismiss-duplicate`, `POST /transactions/bulk-delete`, `bulk-categorize`, `GET /categories` (ETag). Filters, signed cursor pagination (date or amount sort), `Idempotency-Key`, `If-Match` versions, duplicate flags, outbox events.
- Verified: `make check` green with PostgreSQL, backend coverage 98.7%; 200 backend tests (116 before).
- CI: new `backend-integration` job. `make check` now needs PostgreSQL (TEST_DATABASE_URL or Docker); without it the integration tests skip and the coverage gate fails.
- Hooks for later: `Categorizer` seam in `app/services/transactions.py` (T-18); CSV import (T-15) should reuse `TransactionService` validation helpers and `find_duplicate`; the BOLA suite (T-16) can build on `test_fr_02_01_other_users_transactions_are_404_everywhere`.
- Not done: prediction/anomaly summary on `GET /transactions/{id}`, feedback and merchant rules (T-18), idempotency cleanup job, event publisher and JSON Schemas for events.
- Next: T-15 (CSV preview/commit).

### 2026-11-20 — T-13 auth and account lifecycle
- Done: register, login, refresh (rotation + family revocation on reuse), logout, `GET/PATCH /users/me`, change password, delete account (hard delete + `deletion_requests` tombstone with pseudo id), `get_current_user` / `get_claims` dependencies, login 5 per email / 20 per IP per 15 min and register 5 per hour per IP, all with problem+json errors.
- Verified: `make check` green; 116 backend tests pass with PostgreSQL (29 auth integration tests). Sentinel test confirms emails, passwords and tokens never appear in logs.
- Other endpoints must use `CurrentUser` from `app/api/deps.py` and repositories from T-12; the user id always comes from the token.
- Not done: `GET /users/me/export` (FR-16, Could), Argon2 timing tuning on the real host, write/read rate limits (they come with their endpoints), security response headers (HSTS/CSP, belongs with infra/frontend tasks).
- Next: T-14 (transactions CRUD, idempotency, cursor pagination, duplicates).

### 2026-11-20 — T-12 DB schema, migrations, repositories
- Done: 25 tables from PRD 12.2 as SQLAlchemy 2 models, reversible migration `0001` with category seed (taxonomy-1, 20 rows), `ScopedRepository`, `UserRepository`, `CategoryRepository`, `get_session` dependency, `database` and `migrations` readiness checks (registered when `DATABASE_URL` is set), `new_uuid7()`.
- Verified: `make check` green (backend coverage 91%); 15 integration tests pass on PostgreSQL 16 (no model/DB drift, up/down/up, seed equals taxonomy, two-user SQL echo scoping, cascade delete).
- Run integration: `TEST_DATABASE_URL=postgresql+psycopg://... make test-integration`, or just Docker with testcontainers. Migrate locally: `cd services/backend && DATABASE_URL=... uv run alembic upgrade head`.
- Gotchas: ruff `extend-exclude` was `models`, which hid `app/models`; now anchored. Migration files ignore E501.
- Next: T-13 (auth). Keyed repositories listed in `KEYED_PENDING` are added by their tasks. Add Alembic upgrade to the compose/startup path in the infra task (T-29).

### 2026-11-20 — T-11 backend scaffold
- Done: `app/main.py` (factory), `app/core/{config,ids,logging,errors,middleware,metrics}.py`, `app/api/{health,router}.py`, `python -m app` / `make api` (http://127.0.0.1:8000, Swagger at `/docs`), 46 tests in `services/backend/tests/unit/test_scaffold.py` (health, request ids, problem+json, sentinel log test, redaction, metrics, settings). Backend coverage 96%, gate 80% enabled in `make test`.
- Try it: `make api`, then `curl localhost:8000/healthz`, open `/docs`, `curl localhost:8000/metrics`.
- Next: T-12 (DB schema, Alembic, category seed, repository layer with user scoping). It should register DB and migration-head readiness checks in `app.state.readiness_checks`, and add a UUIDv7 helper next to `new_ulid` in `app/core/ids.py`.

### 2026-11-20 — T-10 decision thresholds
- Done: `ml/classification/thresholds.py` (band-walk procedure), config section `thresholds`, `make thresholds`, hook in `train.py`, `ml/tests/test_thresholds.py` (9 tests), docs (MODEL_EVALUATION, model card). Run 20261120-024213 now has `decision_thresholds` `t_high 0.90`, `t_low 0.90` in `metadata.json` (also logged to its MLflow run).
- Behaviour: seen merchants 90.4% auto-applied at ~100% precision, 9.6% needs_review; the suggest band is empty. Unseen merchants: 45.4% auto-applied at 0.685 precision. The ML service (T-17) and backend (T-14) must treat the `suggest` decision as possibly absent and still handle all three decisions.
- Open: novelty rule for unseen merchants, generator holdout variant, latency benchmark.

### 2026-11-20 — T-09 classifier baselines
- Done: `ml/classification/{config,data,pipeline,calibration,metrics,train}.py`, `config/train/classifier.yaml`, `make train-local`, `docs/MODEL_EVALUATION.md`, `docs/model_cards/transaction-classifier.md`, tests (`ml/tests/test_classifier_metrics.py`, `data_generator/tests/test_classifier_smoke.py`). Run `20261120-024213`; MLflow model `transaction-classifier` v1 alias `candidate` (local sqlite in `data/mlflow/`).
- Results: LR baseline wins (SVM and LightGBM did not gain 2.0 points). Temporal test macro F1 0.969 is saturated at the ambiguity ceiling; unseen-merchant macro F1 is 0.52 and calibration there is poor (ECE 0.31).
- **For T-10:** thresholds fitted on the (seen-merchant) validation split will be over-optimistic for unseen merchants. Consider a novelty feature/rule and report precision on the unseen split next to the chosen thresholds. Metadata `decision_thresholds` is null until then.
- Open: generator holdout variant (9.6.6), latency benchmark (T-17/T-30), learning curve for the 25k-per-class cap.
- Gotchas: training needs about 3+ GB RAM and ~15 minutes (LightGBM ~6 min); run with output to a log file, not piped to `tail`. `uv run python -m ml.classification.train --max-rows-per-class 2000 --no-mlflow` is a quick smoke run.

### 2026-11-20 — T-08 classifier features
- Done: `ml/features/{__init__,classifier,point_in_time,testing}.py`, `ml/tests/test_feature_parity.py` (24 tests: batch vs online parity on hand-made rows and 5,000 synthetic rows, harness self-tests, hour-bucket boundaries).
- T-09 must: fit TF-IDF (`desc_char_tfidf`, `desc_word_tfidf`, `merchant_char_tfidf`) and the `log_amount` scaler on the TRAIN split only, one-hot `payment_method`/`transaction_type`/`hour_bucket` using the fixed `HOUR_BUCKETS`, and save `FEATURE_VERSION` into `metadata.json`. Backend/ML service call `online_features`, never reimplement.
- `merchant_key` comes from `resolve_merchant`; the unseen-merchant split is on `true_merchant`, so check in T-09 that held-out merchants are not trivially recognizable through alias targets.
- New libraries for T-09 (scikit-learn, lightgbm, mlflow, joblib) are in PRD 6.5; log a DECISIONS line when adding them.

### 2026-11-20 — T-07 merchant normalization
- Done: `ml/preprocessing/merchant.py` (`normalize_merchant`, `preprocess_description`, `derive_merchant`, `derive_merchant_key`, `resolve_merchant`), `ml/tests/test_merchant_normalization.py` (61 tests incl. hypothesis and a synthetic-data agreement test). 95.3% agreement with `true_merchant` on a 200k train sample; misses are injected typos.
- Backend (T-12+) and ML service must import these functions, never reimplement them (parity rule, PRD 11.1).
- Next: T-08 features (needs T-07). Note the unseen-merchant split uses `true_merchant`; once real `merchant_key` features exist, check that held-out merchants do not leak through `normalize_merchant` aliases.

### 2026-11-20 — T-05 locked splits
- Done: `ml/evaluation/splits.py` (classifier, anomaly, forecast, clustering splits), CLI (`python -m ml.evaluation make-splits|verify-splits`), `make splits`/`make verify-splits`, `data_splits/README.md`, committed `data_splits/synthetic/v1/` files. Generator bumped to 1.1.0 (new `true_merchant` column), dataset regenerated. `make check` green (83 tests incl. the lock test against the full dataset).
- Locked values (synthetic/v1, generator 1.1.0, seed 42): split_hash `cc7b019c3718c3b21f7756892314356fb0ae15eb603dc6b3c16046a19e8b1b3d`; classifier train 1,263,380 / validation 270,883 / test 271,888 / unseen-merchant test 365,207 (42 held-out merchants, 16.8% of rows); anomaly 1,519,032 / 325,655 / 326,671; 8,000 forecast periods (2,000 users x 4); clustering halves of 1,000 users.
- **From now on the splits are locked.** Changing the dataset, the generator output, or the split rules requires an ADR, then `python -m ml.evaluation make-splits ... --force` (`make splits` refuses to overwrite locked splits).
- Next: T-04 EDA (`docs/EDA.md`, needs matplotlib/jupyter; compute on the TRAIN split only for anything used to design features) and T-06 (public datasets + licenses, decide Q1). Then week 2: T-07 `normalize_merchant` (>= 30 tests).
- Gotchas: do not regenerate `data/synthetic/v1` with another generator version or numpy version without re-running `make verify-splits`. A numpy upgrade that changes RNG streams would change the dataset and trip the lock test; that is the intended alarm. The unseen-merchant split is larger than 15% of rows because popular merchants can be held out.

### 2026-11-20 — T-03 synthetic generator
- Done: `data_generator/` (config loader, noise, per-user simulation, writer, CLI), `ml/schemas/synthetic.py` (Pandera schemas, incl. category-share and type/category consistency), configs in `config/generator/` (default, subscriptions, 5 archetypes), `make data`. `make check` green (62 tests).
- Full dataset (seed 42, v1): 2,171,358 transactions, 2,000 users, 454 MB (gitignored, `data/synthetic/v1`). Takes ~2.3 min with 6 workers. Two full runs with different worker counts produced identical sha256 for all three data files (transactions.csv 20d6e816..., transactions.parquet 1d8296ea..., users.parquet 711e4a08...), recorded here as generator-1.0.0 evidence.
- Measured properties (descriptive, from this synthetic data only): anomaly rows 0.98% of expenses; ambiguous labels 5.06%; date-only rows 14.9%; recurring rows 3.1%; expense/income ratio 0.83-0.99 by archetype.
- Next: T-05 split module + locked splits + hash (PRD §10.4; needs `transaction_id`, `user_id`, `merchant` / merchant_key — T-07 `normalize_merchant` is needed for the unseen-merchant split, so decide whether to use the clean `merchant` column or wait for T-07). T-04 EDA notebook can start now (needs matplotlib/jupyter, not installed yet).
- Gotchas: `category` column is intentionally blank; the label is `true_category`. Duplicates have no label column. Holdout variant config for the circularity check is not written yet. Pandas is 3.x (new string dtype); use `pandera.pandas`.

### 2026-11-19 — T-02 taxonomy, merchants, aliases, holidays
- Done: `ml/taxonomy.py` (20 categories, 19 model labels, `is_valid_for_type`), `config/generator/merchants.yaml` (>= 15 merchants per expense/transfer category), `config/merchant_aliases.yaml` (42 aliases), `config/cities_id.yaml`, `config/holidays_id.yaml` (2025-2027, verified against SKB pages), loaders in `ml/config.py`, integrity tests. `make check` green (31 tests).
- Not done on purpose: `normalize_merchant` itself and its >= 30 tests (T-07). Alias map is only validated for shape and merchant targets until then.
- Next: T-03 synthetic generator. Needs PRD §10.1 (spec + example archetype YAML), §4.2-4.7, §7.2.3 CSV columns. Archetype configs go in `config/generator/`. Pandera is not installed yet.
- Gotchas: holiday source pages were read via a summarizing fetch tool; spot-check against the SKB PDF if exact dates matter. Ramadan windows not included.

### 2026-11-19 — T-01 repo scaffold
- Done: folder structure per PRD §22, uv workspace (5 members), pnpm workspace (frontend placeholder), `Makefile` (real: setup/lint/format/typecheck/test/test-integration/check; stubs for the rest, each naming its task), `.pre-commit-config.yaml` (hygiene, ruff, gitleaks), `.github/workflows/ci.yml` (python lint/types/tests + gitleaks), `.env.example` (all §19.4 vars), full `.gitignore`.
- Verified: `make check` passes; `pre-commit run --all-files` passes; stubs fail with a clear message.
- Not verified: CI on GitHub (push needed); `make setup` end to end (installs git hooks; run it once yourself).
- Next: T-02 (taxonomy, merchant lists, alias map, holidays config) in `config/` and `ml/`. Needs PRD §4.6, §7.3.2, §10.1.
- Gotchas: use `uv sync --all-packages` (plain `uv sync` skips members). ML service package is `ml_service`, not `app`. Node on this machine is v26; project targets Node 22 (`.nvmrc`).

### 2026-11-19 — pre-coding docs
- Done: `CLAUDE.md`, `docs/PROGRESS.md`, `docs/DECISIONS.md`, ADR template + ADR-0001…0009, skeleton `README.md`, `.github/pull_request_template.md`, `docs/PRIVACY.md`, `SECURITY.md`.
- Not started: no code yet.
- Next: T-01 repo scaffold (uv workspace, pnpm, pre-commit, Makefile skeleton, CI lint job, `.env.example`, `.gitignore`). The ADR template part of T-01 is already done.
- Note: `graphify-out/` (local knowledge-graph output) exists in the working tree; add it to `.gitignore` in T-01.

---

## Tasks

### Week 1 — Data foundation
| ID | Task | Deps | Status | Notes |
|---|---|---|---|---|
| T-01 | Repo scaffold: structure, uv workspace, pnpm, pre-commit, Makefile skeleton, CI lint job, ADR template, `.env.example` | — | done | `make check` green locally (ruff, mypy --strict, 5 smoke tests); pre-commit passes. CI workflow not yet run on GitHub. Deviations logged in DECISIONS.md |
| T-02 | Category taxonomy + merchant lists + alias map + holidays config | T-01 | done | `ml/taxonomy.py`, `ml/config.py`, `config/{merchant_aliases,holidays_id,cities_id}.yaml`, `config/generator/merchants.yaml`; 26 new tests |
| T-03 | Synthetic generator v1 with manifest + Pandera self-validation | T-02 | done | `python -m data_generator`, `make data`; full dataset regenerated byte-identically (6 vs 3 workers); 31 new tests |
| T-04 | EDA notebook → `docs/EDA.md` | T-03 | done | `docs/EDA.md`, `make eda`  |
| T-05 | Split module + locked splits + hash | T-03 | done | `ml/evaluation/splits.py`, `data_splits/synthetic/v1/` (split_hash cc7b019c...), generator 1.1.0 (`true_merchant`); `make splits`, `make verify-splits` |
| T-06 | Public dataset search → `docs/DATA_SOURCES.md`; decide Q1 | — | done | `docs/DATA_SOURCES.md`; Q1 decided: no public dataset |

### Week 2 — Classifier
| ID | Task | Deps | Status | Notes |
|---|---|---|---|---|
| T-07 | `ml/preprocessing` (merchant normalization ≥ 30 tests, description preprocessing) | T-02 | done | `ml/preprocessing/merchant.py`, 61 tests |
| T-08 | Classifier feature module + point-in-time and parity harness | T-07 | done | `ml/features/` (classifier, point_in_time, testing); parity test on 5,000 synthetic rows |
| T-09 | Baseline LR + calibrated Linear SVM + LightGBM; MLflow; eval report | T-05, T-08 | done | `ml/classification/`, `docs/MODEL_EVALUATION.md`, model card; MLflow run bbf88d53...; baseline wins |
| T-10 | Threshold calibration procedure (7.3.4) | T-09 | done | `ml/classification/thresholds.py`; t_high 0.90, t_low 0.90 (no suggest band) |

### Week 3 — Backend core
| ID | Task | Deps | Status | Notes |
|---|---|---|---|---|
| T-11 | Backend scaffold: settings, logging, problem+json, request IDs, health | T-01 | done | `services/backend/app/` scaffold, 46 tests, `make api` |
| T-12 | DB schema + Alembic + category seed + repository layer with scoping test | T-11 | done | `app/models/`, `migrations/versions/0001_initial_schema.py`, `app/repositories/`, 15 integration + 12 unit tests |
| T-13 | Auth (register/login/refresh rotation/logout/password/delete) + rate limits | T-12 | done | `app/api/{auth,users}.py`, `app/services/auth.py`, `app/core/{security,passwords,ratelimit,periods}.py`, 29 integration + 10 unit tests |
| T-14 | Transactions CRUD + filters + cursor pagination + idempotency + duplicates | T-12 | done | `app/api/transactions.py`, `app/services/{transactions,idempotency}.py`, `app/repositories/{transactions,idempotency}.py`, 67 integration + 12 unit tests |
| T-15 | CSV preview/commit with all error codes | T-14 | done | `app/api/imports.py`, `app/services/imports.py`, `app/core/csvparse.py`, `app/repositories/imports.py`, 31 integration + 46 unit tests |
| T-16 | BOLA/IDOR test suite | T-13, T-14 | done | `services/backend/tests/security/test_bola.py` (8 tests, auto-discovers routes) |

### Week 4 — ML service + frontend core
| ID | Task | Deps | Status | Notes |
|---|---|---|---|---|
| T-17 | ML service: model loading, `/v1/classify`, batch, probes, metrics, hash verification | T-09 | done | `services/ml_service/ml_service/`, 66 tests, `make ml-api` |
| T-18 | Backend ML client (timeout, circuit breaker, fallback), categorization flow, merchant rules, feedback, categorize-preview | T-14, T-17 | done | 2026-11-20 |
| T-19 | Frontend scaffold: auth, layout, API client, transactions page, review queue, CSV import UI | T-13, T-18 | done | 2026-11-20 |

### Week 5 — Budgets, analytics, intelligence baselines
| ID | Task | Deps | Status | Notes |
|---|---|---|---|---|
| T-20 | Analytics endpoints (SQL aggregations) + property tests vs raw SQL | T-14 | todo | |
| T-21 | Budgets + status + thresholds + notifications (FR-05, FR-14) | T-20 | todo | |
| T-22 | Dashboard + budgets pages | T-20, T-21 | todo | |
| T-23 | Anomaly baseline + rules + in-memory event path + anomalies API/UI + feedback | T-18 | todo | |
| T-24 | Forecast run-rate + decomposition + API/UI | T-20 | todo | |

### Week 6 — MLOps core (= Cut line A)
| ID | Task | Deps | Status | Notes |
|---|---|---|---|---|
| T-25 | Prefect training flow; MLflow registry, aliases, metadata.json, model card generation | T-09 | todo | |
| T-26 | Offline gates + behavioural tests + latency benchmark | T-25 | todo | |
| T-27 | `make promote` / `make rollback`; ML service alias polling hot-swap | T-25, T-17 | todo | |
| T-28 | Reproducibility CI job | T-25 | todo | |
| T-29 | Docker images + full compose + `make demo` | all above | todo | |

### Week 7 — Deployment
| ID | Task | Deps | Status | Notes |
|---|---|---|---|---|
| T-30 | Recurring detection (FR-08) + forecast decomposition with recurring | T-24 | todo | |
| T-31 | Terraform for all GCP resources + budget alerts | T-29 | todo | Decide Q4 first |
| T-32 | CI/CD build/deploy with WIF, migrations job, smoke tests, revision rollback | T-31 | todo | |

### Week 8 — Events and monitoring (= Cut line B)
| ID | Task | Deps | Status | Notes |
|---|---|---|---|---|
| T-33 | Outbox + relay + Pub/Sub + worker push endpoint + DLQ + idempotent consumers | T-23, T-31 | todo | |
| T-34 | Metrics, Grafana dashboards, Cloud Monitoring alerts, prediction log sink | T-32 | todo | |
| T-35 | Evidently drift job + reports | T-34 | todo | |
| T-36 | Runbook (≥ 3 entries, each tested once) + rollback drill | T-34 | todo | |
| T-37 | Insights engine (FR-09) + batch job scheduler | T-30 | todo | |
| T-38 | Anomaly model (IF/LOF) + forecast models (ETS, LightGBM quantile) vs baselines | T-23, T-24, T-25 | todo | |
| T-39 | Shadow mode + `shadow-evaluate` | T-27, T-34 | todo | |

### Week 9 — Depth
| ID | Task | Deps | Status | Notes |
|---|---|---|---|---|
| T-40 | IndoBERT experiment + latency/cost report; ship decision | T-26 | todo | Decide Q3 first |
| T-41 | Clustering (FR-13) + segment UI | T-25 | todo | |
| T-42 | Settings page (merchant rules, consent, export, delete account) | T-19 | todo | |

### Week 10 — Verification and release (= Cut line C)
| ID | Task | Deps | Status | Notes |
|---|---|---|---|---|
| T-43 | k6 load test vs SLO incl. cold starts | T-32 | todo | |
| T-44 | E2E Playwright flows | T-22, T-42 | todo | |
| T-45 | Docs set, model cards, ADRs complete; demo video | all | todo | |
| T-46 | Independent verification vs PRD §26 (fresh session, PRD + repo only) | all | todo | |

---

## Open questions (PRD §25)

| ID | Question | Decide by | Status |
|---|---|---|---|
| Q1 | Public dataset for classifier generalization testing | End of week 1 (T-06) | decided 2026-11-20: no public dataset (see DATA_SOURCES.md) |
| Q2 | UI language: English only, or Indonesian too | Week 4 | open (default: English, i18n-ready) |
| Q3 | IndoBERT base vs smaller distilled model | Week 9 | open |
| Q4 | GCP free tier/credits at deploy time | Week 7 | open (default: assume none) |
| Q5 | Internship application deadline | Week 1 | open (default: ≥ 10 weeks) |

## Blockers

None.
