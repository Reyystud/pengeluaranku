# Smart Expense Intelligence - Makefile (PRD section 19.1)
# Targets marked "stub" fail loudly until their task lands (see docs/PROGRESS.md).

SHELL := /bin/bash
.DEFAULT_GOAL := help

define NOT_YET
	@echo "make $@ is not implemented yet (planned in task $(1); see docs/PROGRESS.md)"; exit 1
endef

.PHONY: openapi-check web thresholds coverage-backend api ml-api eda splits verify-splits help setup lint format typecheck test test-integration check \
        data train-local prefect-server up down seed-demo demo openapi train promote rollback loadtest jobs-run

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

up: ## docker compose up (stub: T-29)
	$(call NOT_YET,T-29)

down: ## docker compose down (stub: T-29)
	$(call NOT_YET,T-29)

seed-demo: ## Create demo user with synthetic data (stub: T-29)
	$(call NOT_YET,T-29)

demo: ## data + train-local + up + seed-demo (stub: T-29)
	$(call NOT_YET,T-29)

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
