# Progress

Status of every task in PRD §20.3. Update this file at the end of each session.

Status values: `todo` · `in-progress` · `blocked` · `done` · `cut` (dropped at a cut line, with reason).

**Current focus:** next T-30 (see PRD 20.3); remember the `suggest` band is empty and unseen merchants are over-confident (T-09/T-10 notes)
**Current tier:** A (weeks 1–6) — target: Cut line A (`make demo` works locally)

---

## Session handoff

Newest entry on top. Keep each entry short: what was done, what is half-done, what to do next, gotchas.

### 2026-11-21 — T-29 Docker images, compose, `make demo`
- Done: `docker-compose.yml`, `infrastructure/docker/{python,mlflow,frontend}.Dockerfile`, `.dockerignore`, `make up|down|seed-demo|demo`, `services/backend/app/seed_demo.py` (+7 unit tests), http(s) `MLFLOW_TRACKING_URI` support in `train-local` and the pipeline, README setup section, `.env.example` entries.
- Verified: `make check` OK (551 non-integration tests, 510 backend, coverage 98.82%, 90 Vitest). On this machine all four images build. The stack was run with host networking (this kernel cannot create Docker bridge networks, so `docker compose up` itself could not be run here): migrations ran, `/readyz` 200 on the backend, ML service 503 without a model, `seed-demo` imported 1,148 rows (all valid), a second run did nothing, `make train-local` registered version 1 in the MLflow server, the ML service loaded it by polling without a restart, `categorize-preview` through the backend returned `source: model`, and the frontend proxied a demo login (200). Image sizes: backend 1.41 GB, ml-service 1.39 GB, frontend 2.47 GB.
- Not verified: `docker compose up` with the real bridge network and healthcheck ordering, `make demo` end to end, the UI in a browser (T-24 checks still pending too).
- Gotchas: the first `make demo` trains on the full v1 dataset (about 10 minutes for 3 candidates). The demo model is alias `candidate`, not promoted. No worker, pubsub emulator or observability profile yet.
- Next: T-30.

### 2026-11-21 — T-28 Reproducibility CI job
- Done: `pipelines/reproducibility.py` (two training runs in separate processes, compare dataset hash, split hash and macro F1), config section `reproducibility`, `make repro`, `.github/workflows/ml-reproducibility.yml` (weekly, PRs touching ML paths, manual; uploads the result JSON), `pipelines/tests/test_reproducibility.py` (decision logic with fake runs).
- Verified: `make check` OK (544 non-integration tests, 503 backend, coverage 98.87%, 90 Vitest). A real `make repro` run (about 2.5 min): macro F1 0.9655 in both runs, delta 0.0, same dataset and split hashes. The workflow itself has not run on GitHub yet.
- Gotchas: the check measures determinism of the baseline on a tiny dataset, not model quality. It is not in `make check` (time).
- Next: T-29.

### 2026-11-21 — T-27 Promote, rollback, ML service alias polling
- Done: `pipelines/promotion.py` (`promote`, `rollback`), CLI `python -m pipelines promote|rollback`, Makefile targets `promote` and `rollback`, `docs/ops/rollback-log.md` written on first use, `ModelSource.current_version()`, `ModelRegistry.refresh()`, background poller in the ML service lifespan (`MODEL_POLL_INTERVAL_S`).
- Verified: tests for first promotion, previous parking, refusal of `needs_review` / untagged versions, forced promotion with a reason, unknown and already-production versions, reversible rollback with log rows, CLI exit codes; polling tests (alias moves, unchanged alias, refused tampered artifact keeps the old model, unreachable registry, local_dir newer run, the real background poller swapping inside a running app). `make check`: OK (backend 503 tests, coverage 98.87%; the rest of the suite also green).
- Gotchas: version 1 in the local registry has no `gate` tag, so promoting it needs `make promote VERSION=1 FORCE=1 REASON="..."`. A rollback drill (Week 8 exit) has not been run on a real service yet; the poller was tested in-process only.
- Not done / for later: shadow loading of `@candidate` and `shadow-evaluate` (T-39), Docker/compose wiring of the poll interval (T-29), the weak golden-set result from T-26 still blocks new registrations.
- Next: T-28.

### 2026-11-21 — T-26 Offline gates, behavioural tests, latency benchmark
- Done: `ml/tests/golden/classifier.yaml` (114 hand-labelled cases, 6 per label), `ml/classification/behavioural.py` (golden accuracy, minimum functionality, three invariance perturbations; `python -m ml.classification.behavioural <run dir>`), `ml/classification/benchmark.py` (1,000-request replay, 2 threads), `pipelines/gates.py` rewritten (all PRD 16.3 gates: data quality, reproducibility, beats baseline, beats production, slices, calibration, behavioural, latency; statuses `pass|fail|review|skipped`), `registry.fetch_production()`, model card sections for behavioural tests and latency, config sections `behavioural`, `benchmark`, extra `gates` knobs.
- Verified: gate unit tests for every boundary (ECE, 0.5-point margin, 5.0-point slice drop, golden regression, latency), behavioural logic with a stub model, golden file integrity (>= 100 cases, >= 3 per category, types match labels), flow tests on the tiny dataset (metrics/gates in metadata, default thresholds block a weak model, a `production` alias becomes the reference and a model that does not gain 0.5 points is blocked and the alias is untouched); `make check` green (528 non-integration tests, 503 backend tests, backend coverage 98.87%, 90 Vitest).
- **Real finding:** the T-09 baseline (run 20261120-024213) scores 0.781 golden accuracy (89/114) and fails minimum functionality in 8 categories; invariance passes (0.93 / 0.97 / 1.00) and latency is P95 25.8 ms. With the PRD thresholds a new `make train` on v1 will therefore NOT register a classifier. Details and examples in `docs/MODEL_EVALUATION.md`. Options for a later task: improve the model/generator realism, or amend the golden-set threshold through an ADR; I did not touch the thresholds or the golden cases.
- Gotchas: version 1 in the local MLflow registry (alias `candidate`, from T-09) predates the gates. A `needs_review` version must be refused by T-27's promote unless forced. Directional anomaly/forecast tests live with those models.
- Not done / for later: shadow evaluation (T-27+), reproducibility CI (T-28), gates for anomaly/forecast/clustering models (T-38, T-41), novelty handling for unseen merchants.
- Next: T-27.

### 2026-11-21 — T-25 Prefect training flow, MLflow registry, model card
- Done: `pipelines/{data_steps,gates,registry,model_card,train_flow,__main__}.py`; `make train MODEL=transaction-classifier DATASET=synthetic/v1` (`PYTHONHASHSEED=0`); `make prefect-server`. Steps: manifest hash check, Pandera on every row (quarantine file with ids only, stop above 1%), locked split hash check, batch-vs-online feature parity sample, candidates + calibration + thresholds + evaluation (`ml.classification.train.fit_candidates` / `write_run_dir`, shared with `make train-local`), gates, MLflow parent run with a child per candidate, `candidate` alias, generated `model_card.md`, `summary.md` (also appended to `$GITHUB_STEP_SUMMARY`). Config: `pipeline` and `gates` sections in `config/train/classifier.yaml`.
- Verified: 27 tests in `pipelines/tests` (tiny generated dataset with locked splits: clean run registers v1 with complete metadata and alias, parent/child runs, dirty tree never registers, ECE gate blocks, second run moves `candidate`, every data-step failure, gate rules, model card text); `make check` green (511 non-integration tests, 503 backend tests, backend coverage 98.87%, 90 Vitest). The Prefect wrapper was run once against a real Prefect server (tiny dataset, registered v1). Smoke run on the real synthetic v1 (`--models logreg --max-rows-per-class 2000`, dirty tree, scratch MLflow store): 2,171,358 rows validated with 0 quarantined, splits and parity passed, test macro F1 0.9702, ECE 0.0010 (capped training sample, not the T-09 result), gate failed only on `reproducibility` as designed.
- Gotchas: (1) Prefect 3.8.8's server cannot start inside this workspace (FastAPI 0.165 removed `min_items`); the flow runs inline by default and as Prefect tasks when `PREFECT_API_URL` points to `make prefect-server` (isolated `uvx` environment). (2) A dirty working tree (even untracked files) makes the run `gate=failed`/`dirty=true` and it is not registered: commit first, then `make train`. (3) Full run on v1 validates 2.1M rows and trains three candidates: allow ~25 minutes and 3+ GB RAM. (4) `semantic_version` is `0.<registry version>.0`.
- Not done / for later: slices, behavioural tests, latency benchmark and beats-production gates (T-26; listed as `skipped` in metadata), promote/rollback and `production`/`previous` aliases (T-27), reproducibility CI job (T-28), curated-label merge (needs feedback data), other models (T-38, T-41), a full `make train` registration of v1 (needs a clean tree).
- Next: T-26.

### 2026-11-21 — T-24 Forecast run-rate + decomposition + API/UI
- Done: `ml/forecasting` (run-rate, seasonal naive, interval heuristic, exceed band, daily P10/P50/P90 curve), `config/forecast.yaml`; backend `ForecastRepository`/`ForecastService` (compute, store in `forecasts`, lazy 6 h cache rule, prune to 30, `refresh_all()` for the daily batch), `GET /intelligence/forecast` (overall or `category`), `BudgetOut.projected` (FR-05.07), estimated period-end balance; frontend Forecast tab on `/intelligence` (estimate label, range, band in words, chart + table, "How is this calculated?") and a dashboard estimate card.
- Verified: `make check` (see below), 90 Vitest tests, new unit/property tests for the formulas and 19 integration tests (minimum history, run-rate vs seasonal, category minimums, bands at the P50/P90 boundaries, cache rules, pruning, isolation).
- No accuracy numbers yet: a forecast evaluation on the locked forecast periods is not part of this task; do not quote any MAPE until it comes from a real run.
- Decisions: `docs/DECISIONS.md` (T-24), PRD addendum T-24.
- Not done / for later: recurring decomposition (T-30), ETS/LightGBM quantile models and the promotion gate (T-38), the daily job that calls `refresh_all()` (T-37), forecast outcomes (`forecast_outcomes`) at period close, browser check of the Forecast tab at 360 px and dark mode.
- Next: T-25.

### 2026-11-21 — T-23 Anomaly baseline, rules, event path, API/UI, feedback
- Done: `ml/anomaly_detection` (robust z-score spike + low amount, Poisson burst, new merchant, category surge, computed reasons, cold-start prior, batch history helper, evaluation script, priors script); `config/anomaly.yaml` + `config/anomaly_priors.yaml` (from the anomaly train split of synthetic v1); backend repository/service, in-process outbox drain with `processed_events` dedupe, alert cap, suppressions, historical rows, re-score on edit, cascade on delete, `anomaly_alert` notification, `GET /intelligence/anomalies`, `GET .../{id}`, `POST .../{id}/feedback`; frontend `/intelligence` (filters, reasons, confirm/dismiss with reason) and a dashboard "Unusual spending" card.
- Verified: `make check` green (484 tests incl. integration, coverage 98.9%); 82 Vitest tests; BOLA suite covers `anomaly_id`; SQL history is pinned to the batch helper by a parity test; point-in-time harness passes.
- Real run (no MLflow run ID, plain script): `python -m ml.anomaly_detection.evaluate --users 60` on synthetic v1, 60 users (SHA-256 sample), validation + test anomaly splits, 18,635 scored expenses, labels used only for scoring. Any-flag row level: precision 0.214, recall 0.658 (52 of 79 labelled). Per type (flagged / labelled / precision / recall): amount_spike 118 / 19 / 0.110 / 0.684; frequency_burst 119 / 46 / 0.210 / 0.543; new_merchant_high_value 10 / 14 / 0.700 / 0.500. Small sample: indicative only; the full-dataset report with an MLflow run belongs to T-38 (`docs/MODEL_EVALUATION.md`). Precision is low because the PRD thresholds are loose on this data; they were not tuned on it.
- Decisions: see `docs/DECISIONS.md` (T-23), PRD addendum T-23.
- Not done / for later: ML service `/v1/anomaly/score` and IsolationForest/LOF (T-38), the daily job that calls `detect_category_surges()` (T-37), re-score on category change, anomaly insights on the dashboard (T-31), `docs/model_cards` entry, browser check of `/intelligence` at 360 px and dark mode (no browser here).
- Next: T-24.

### 2026-11-21 — T-22 Dashboard, budgets and notifications pages
- Done: `/dashboard` (balance, income, expenses, net with change vs. the comparison window, savings rate, review-queue banner, budget progress, category donut, daily trend with cumulative line and budget pace, period comparison table, top merchants, period selector for this/last/last 3 periods, onboarding card for an empty ledger), `/budgets` (cards with status badge, utilization bar, remaining/over, thresholds, history of closed periods, add/edit drawer, two-step delete, warning when category limits exceed the overall limit), `/notifications` (list, unread filter, mark one/all as read, load more) and a bell with the unread count in the app shell that polls every 60 s only while the tab is visible (FR-14.04). Files: `frontend/src/features/{dashboard,budgets,notifications}/*`, `components/ui/{budget-status,chart-frame}.tsx`, `messages/en.json`, `AppShell.tsx`. Transaction writes now also refresh analytics, budgets and notifications queries.
- Accessibility (PRD 8.2): status is icon + words, every chart has a visible text summary and a data-table toggle, the donut has a legend with amounts and shares, progress bars expose `aria-valuetext`, the bell's accessible name carries the unread count.
- Verified: `pnpm lint`, `typecheck`, `build`; 70 Vitest tests (28 new: status and thresholds parsing, create/edit/delete/409, history, ranges, empty/error states with `request_id`, polling at 60 s with fake timers, mark read/all). A live contract test (`LIVE_API_URL=http://127.0.0.1:8000 pnpm test src/api/live.test.ts`) ran against the real backend: budget -> transaction -> `warning` status -> 80% notification -> read-all. Not checked in a real browser (no browser available in this session): look at the layout at 360 px and in dark mode before merging.
- Decisions: see `docs/DECISIONS.md` (T-22).
- Not done / for later: insights and active alerts on the dashboard (T-23, T-31 produce them), custom date range picker and the payment-method split (the API has both), sample-data card (T-29), settings page (T-42), Playwright E2E.
- Next: T-23.

### 2026-11-20 — T-21 Budgets and notifications
- Done: `GET/POST /budgets`, `GET/PATCH/DELETE /budgets/{id}`, `GET /budgets/{id}/history`; `GET /notifications` (cursor, `unread_only`), `GET /notifications/unread-count`, `POST /notifications/{id}/read`, `POST /notifications/read-all`. Code: `app/api/{budgets,notifications}.py`, `app/services/budgets.py`, `app/repositories/{budgets,notifications}.py`, `app/schemas/budgets.py`; `TransactionService.check_budgets()` runs after create, update, delete, bulk delete/categorize, recategorize and CSV commit (FR-05.06). OpenAPI file and frontend types regenerated.
- Verified: 56 integration tests (CRUD, 409 `BUDGET_EXISTS`, 422 `CATEGORY_TYPE_MISMATCH`, status boundaries, every write path notifying, no duplicate notifications, deletes keep past ones, pagination, per-user isolation, snapshots incl. limit change not rewriting history), 5 unit tests, BOLA suite extended with `budget_id` and `notification_id`. A mutation check (random dedupe key, `<=` instead of `<`) made 4 tests fail as expected.
- Decisions: see `docs/DECISIONS.md` (T-21).
- Not done / for later: `projected` (FR-05.07) is `null` until the forecast exists (T-24); the daily job that calls `BudgetService.snapshot_closed_period()` and `evaluate()` and the 90-day notification cleanup are T-37; other notification types (anomaly, import, recurring, review queue) come with their features; bell icon, notifications page and budgets page are T-22.
- Next: T-22.

### 2026-11-20 — T-20 Analytics endpoints
- Done: `GET /analytics/summary|categories|trends|merchants|payment-methods` (FR-04.01-10): `app/api/analytics.py`, `app/services/analytics.py` (ranges, comparison, buckets), `app/repositories/analytics.py` (all sums in SQL: `SUM ... FILTER`, `GROUP BY`, window sum, `unnest ... WITH ORDINALITY` buckets), `app/schemas/analytics.py`, `PeriodBounds`/`period_bounds` in `app/core/periods.py` (start-day change applies from the next period). Committed `openapi.json` and `frontend/src/api/schema.d.ts` regenerated.
- Verified: 20 hypothesis-generated ledgers (5 time zones incl. DST, start days 1..28, transfers, blank merchants, rows around day boundaries) compared with plain SQL (local-date cast) for balance, flows, savings rate, comparison, categories, merchants, payment methods, and day/week/month trends; two hand-computed golden ledgers (`tests/fixtures/ledgers/*.yaml`, 14 cases); 15 unit tests (periods tile the calendar with no gap/overlap, buckets, percent rules); validation, auth, cross-user isolation and repository scoping tests. Two mutation checks (change one expected number; count transfers as expenses) made the suites fail as they should. Measured on this dev machine with 50,000 rows for one user (p50 over 15 calls, single process, not an SLO result): summary 58 ms, categories 21 ms, trends 38 ms (custom 366-day range 161 ms), merchants 19 ms, payment methods 18 ms.
- Decisions: see `docs/DECISIONS.md` (T-20). No Redis cache (FR-04.12 says compute directly without Redis; Redis is not in the stack yet).
- Hooks for later: T-21 budgets reuse `period_bounds` and `AnalyticsRepository` (the trend already reads the overall budget for the pace line); T-22 builds the dashboard on these endpoints; T-24 forecast reuses `expense_buckets`.
- Not done: Redis cache and invalidation (FR-04.12), onboarding/sample-data cards (FR-04.11, frontend), a promotion job for `pending_period_start_day` (the service already computes periods correctly from the pending fields).
- Next: T-21.

### 2026-11-20 — T-19 Frontend scaffold
- Done: `frontend/` Next.js 16 (App Router, TS strict, Tailwind v4). Pages: landing, `/login`, `/register`, `/transactions` (filters, table that becomes cards on phones, add/edit drawer with live categorization chip and quick picks, bulk delete, review-queue tab with badge, confirm suggestion, dismiss duplicate), `/transactions/import` (upload, preview with per-row status/errors and editable categories, commit options, result), `/dashboard` and `/settings` as empty states. In-memory access token, one shared refresh then retry, redirect to `/login`. Loading, empty and error states (error shows `request_id` with Copy). `t()` strings in `src/messages/en.json`. `services/backend/openapi.json` + generated `src/api/schema.d.ts`, `make openapi`, `make openapi-check`, `make web`, CI job `frontend`.
- Verified: 41 Vitest tests (money/time helpers, API client refresh/error mapping, chip states, drawer preview/validation/idempotency, auth forms, hook headers) + 1 live contract test run against the real backend through the Next proxy (register, categories, preview, create with replay, list, bulk delete); `next build` ok; lint, tsc and prettier clean. The smoke run found the missing `Idempotency-Key` and the `deleted` response field, both fixed. Not verified: real browser rendering, mobile layout by eye, Lighthouse/axe (no browser tooling here), Playwright flows.
- Hooks for later: the dashboard page is T-22 (add Recharts there; T-20 is backend analytics), T-42 settings (merchant rules API exists), `frontend/AGENTS.md` is ignored (Next writes it unless `agentRules: false`, now set).
- Not done: demo login button (T-29), notifications and budgets pages, E2E.
- Next: T-20 (backend analytics endpoints).

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
| T-20 | Analytics endpoints (SQL aggregations) + property tests vs raw SQL | T-14 | done | 2026-11-20 |
| T-21 | Budgets + status + thresholds + notifications (FR-05, FR-14) | T-20 | done | 2026-11-20 |
| T-22 | Dashboard + budgets pages | T-20, T-21 | done | 2026-11-21 |
| T-23 | Anomaly baseline + rules + in-memory event path + anomalies API/UI + feedback | T-18 | done | 2026-11-21 |
| T-24 | Forecast run-rate + decomposition + API/UI | T-20 | done | 2026-11-21 |

### Week 6 — MLOps core (= Cut line A)
| ID | Task | Deps | Status | Notes |
|---|---|---|---|---|
| T-25 | Prefect training flow; MLflow registry, aliases, metadata.json, model card generation | T-09 | done | 2026-11-21 |
| T-26 | Offline gates + behavioural tests + latency benchmark | T-25 | done | 2026-11-21; golden set + gates; T-09 baseline fails golden (0.781) |
| T-27 | `make promote` / `make rollback`; ML service alias polling hot-swap | T-25, T-17 | done 2026-11-21 | |
| T-28 | Reproducibility CI job | T-25 | done 2026-11-21 | |
| T-29 | Docker images + full compose + `make demo` | all above | done 2026-11-21 | |

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
