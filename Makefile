# Smart Expense Intelligence - Makefile (PRD section 19.1)
# Targets marked "stub" fail loudly until their task lands (see docs/PROGRESS.md).

SHELL := /bin/bash
.DEFAULT_GOAL := help

define NOT_YET
	@echo "make $@ is not implemented yet (planned in task $(1); see docs/PROGRESS.md)"; exit 1
endef

.PHONY: openapi-check web thresholds coverage-backend api ml-api eda splits verify-splits help setup lint format typecheck test test-integration check \
        data train-local prefect-server up up-events up-observability down seed-demo demo openapi train repro recurring-eval dashboards terraform-check drift-report promote rollback loadtest jobs-run

help: ## List targets
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-18s %s\n", $$1, $$2}'

setup: ## Install toolchains, pre-commit hooks, create .env
	uv sync --all-packages
	@if [ -f frontend/package.json ]; then pnpm install; fi
	uv run pre-commit install
	@if [ ! -f .env ]; then cp .env.example .env && echo "created .env from .env.example"; fi

lint: ## ruff lint + format check (+ eslint/prettier when the frontend is installed)
	uv run ruff check .
	uv run ruff format --check .
	@if [ -d frontend/node_modules ]; then pnpm --dir frontend lint; fi

format: ## Auto-format and fix
	uv run ruff check --fix .
	uv run ruff format .

typecheck: ## mypy --strict on ml/, pipelines/ and backend app/, tsc --noEmit on the frontend
	uv run mypy
	@if [ -d frontend/node_modules ]; then pnpm --dir frontend typecheck; fi

test: ## Unit tests (no external services), including frontend Vitest
	uv run pytest -m "not integration"
	@if [ -d frontend/node_modules ]; then pnpm --dir frontend test; fi

test-integration: ## Integration tests (testcontainers, or TEST_DATABASE_URL=postgresql+psycopg://...)
	uv run pytest -m integration || [ $$? -eq 5 ]

coverage-backend: ## Backend unit + integration tests with the 80% line-coverage gate (needs PostgreSQL)
	uv run pytest services/backend -q --cov=app --cov-fail-under=80

check: lint typecheck test coverage-backend ## Lint + types + tests + coverage gate (must pass before finishing a task)
	@echo "make check: OK"

WORKERS ?= 4
data: ## Generate synthetic dataset v1 into data/synthetic/v1 (make data WORKERS=8)
	uv run python -m data_generator generate --config config/generator/default.yaml --seed 42 --out data/synthetic/v1 --workers $(WORKERS)

api: ## Run the backend dev server on http://127.0.0.1:8000 (docs at /docs)
	RELOAD=true uv run python -m app

thresholds: ## Recompute decision thresholds for the latest classifier run (PRD 7.3.4)
	MLFLOW_DISABLE_AGENT_HINT=1 uv run python -m ml.classification.thresholds

ml-api: ## Run the ML service on http://127.0.0.1:8080 (set MODEL_SOURCE=local_dir to load models/ from make train-local)
	uv run python -m ml_service

eda: ## Regenerate docs/figures + data/eda_stats.json from the train split
	uv run python -m ml.eda.run_eda

splits: ## Compute + lock splits for data/synthetic/v1 into data_splits/ (refuses to change locked splits)
	uv run python -m ml.evaluation make-splits --data data/synthetic/v1 --dataset-version synthetic/v1

verify-splits: ## Check committed splits still match data/synthetic/v1
	uv run python -m ml.evaluation verify-splits --data data/synthetic/v1 --dataset-version synthetic/v1

train-local: ## Train + evaluate classifier candidates, register best as `candidate` in local MLflow
	MLFLOW_DISABLE_AGENT_HINT=1 uv run python -m ml.classification.train

up: ## docker compose up -d --build (needs .env: make setup). Stack: postgres redis mlflow ml-service backend frontend
	docker compose up -d --build --wait

up-events: ## Same as up, plus the Pub/Sub emulator, the worker (outbox relay) and EVENT_BUS=pubsub
	EVENT_BUS=pubsub docker compose --profile events up -d --build --wait backend worker pubsub-emulator frontend
	EVENT_BUS=pubsub docker compose --profile events run --rm pubsub-init

up-observability: ## Same as up, plus Prometheus (:9090) and Grafana (:3001, dashboards from monitoring/)
	docker compose --profile observability up -d --build --wait
	docker compose --profile observability up -d prometheus grafana

dashboards: ## Regenerate monitoring/dashboards/*.json from monitoring/build_dashboards.py
	uv run python monitoring/build_dashboards.py

down: ## docker compose down (VOLUMES=1 also drops the database and MLflow volumes)
	docker compose --profile events --profile observability down $(if $(VOLUMES),--volumes)

seed-demo: ## Create the demo user with 12 months of synthetic history via the running backend (needs make data + make up)
	@set -a; . ./.env; set +a; \
	DEMO_USER_PASSWORD="$$DEMO_USER_PASSWORD" uv run python -m app.seed_demo --base-url http://127.0.0.1:$${BACKEND_PORT:-8000}

demo: ## data + up + train-local (into the compose MLflow) + seed-demo, then print URLs
	@test -f .env || { echo ".env missing: run make setup"; exit 1; }
	$(MAKE) data
	CLASSIFIER_ALIAS=candidate $(MAKE) up
	MLFLOW_TRACKING_URI=http://127.0.0.1:$${MLFLOW_PORT:-5000} $(MAKE) train-local
	$(MAKE) seed-demo
	@echo ""
	@echo "Frontend   http://localhost:$${FRONTEND_PORT:-3000}"
	@echo "API docs   http://localhost:$${BACKEND_PORT:-8000}/docs"
	@echo "MLflow     http://localhost:$${MLFLOW_PORT:-5000}"
	@echo "ML service http://localhost:$${ML_PORT:-8080}/readyz  (loads the model within MODEL_POLL_INTERVAL_S)"
	@echo "Demo user  demo@example.com / DEMO_USER_PASSWORD from .env. The model is the unpromoted T-09 baseline (alias candidate)."

openapi: ## Regenerate services/backend/openapi.json and the frontend API types
	uv run python -m app.openapi_export services/backend/openapi.json
	pnpm --dir frontend gen:api

openapi-check: ## Fail when the committed OpenAPI file or the generated frontend types are stale
	uv run pytest services/backend/tests/unit/test_openapi_export.py -q
	pnpm --dir frontend gen:api
	git diff --exit-code -- frontend/src/api/schema.d.ts

web: ## Run the frontend dev server on http://localhost:3000 (proxies /api/v1 to the backend)
	pnpm --dir frontend dev

MODEL ?= transaction-classifier
DATASET ?= synthetic/v1
train: ## Prefect flow train_model: make train MODEL=transaction-classifier DATASET=synthetic/v1 (PRD 16.1)
	MLFLOW_DISABLE_AGENT_HINT=1 PYTHONHASHSEED=0 uv run python -m pipelines train --model $(MODEL) --dataset $(DATASET)

repro: ## Re-run test (PRD 16.2): train the baseline twice in separate processes, assert |delta macro F1| <= 0.01 (~2.5 min)
	MLFLOW_DISABLE_AGENT_HINT=1 uv run python -m pipelines.reproducibility --out data/reproducibility.json

recurring-eval: ## Score the recurring detector against the generator's labels on 1,000 sampled users (~40 s, PRD 7.8)
	uv run python -m ml.recurring.evaluate --users 1000 --out data/recurring_eval.json

drift-report: ## Evidently drift report from captured ml-service logs (LOGS=file [REFERENCE=models/.../reference] [DATE=YYYY-MM-DD])
	@test -n "$(LOGS)" || { echo "usage: make drift-report LOGS=ml-service.log  (docker compose logs --no-log-prefix ml-service > ml-service.log)"; exit 2; }
	uv run python -m pipelines drift-report --logs $(LOGS) $(if $(REFERENCE),--reference $(REFERENCE)) $(if $(DATE),--date $(DATE))

terraform-check: ## Terraform fmt, validate and the offline guardrail tests (needs terraform >= 1.7; no GCP credentials)
	cd infrastructure/terraform && terraform fmt -check -recursive && terraform init -backend=false -input=false && terraform validate && terraform test

prefect-server: ## Run a Prefect server on :4200 in its own environment (then export PREFECT_API_URL=http://127.0.0.1:4200/api)
	uvx --from "prefect>=3,<4" --with "fastapi<0.160" prefect server start

promote: ## make promote MODEL=transaction-classifier VERSION=2 [REASON=... FORCE=1] (PRD 16.3)
	MLFLOW_DISABLE_AGENT_HINT=1 uv run python -m pipelines promote --model $(MODEL) --version $(VERSION) --reason "$(REASON)" $(if $(FORCE),--force)

rollback: ## make rollback MODEL=transaction-classifier REASON="..." : swap @production and @previous (PRD 16.5)
	MLFLOW_DISABLE_AGENT_HINT=1 uv run python -m pipelines rollback --model $(MODEL) --reason "$(REASON)"

loadtest: ## k6 load test (stub: T-43)
	$(call NOT_YET,T-43)

jobs-run: ## make jobs-run JOB=... (stub: T-37)
	$(call NOT_YET,T-37)
