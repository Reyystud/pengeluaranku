# Smart Expense Intelligence - Makefile (PRD section 19.1)
# Targets marked "stub" fail loudly until their task lands (see docs/PROGRESS.md).

SHELL := /bin/bash
.DEFAULT_GOAL := help

define NOT_YET
	@echo "make $@ is not implemented yet (planned in task $(1); see docs/PROGRESS.md)"; exit 1
endef

.PHONY: api eda splits verify-splits help setup lint format typecheck test test-integration check \
        data train-local up down seed-demo demo openapi train promote rollback loadtest jobs-run

help: ## List targets
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-18s %s\n", $$1, $$2}'

setup: ## Install toolchains, pre-commit hooks, create .env
	uv sync --all-packages
	@if [ -f frontend/package.json ]; then pnpm install; fi
	uv run pre-commit install
	@if [ ! -f .env ]; then cp .env.example .env && echo "created .env from .env.example"; fi

lint: ## ruff lint + format check
	uv run ruff check .
	uv run ruff format --check .

format: ## Auto-format and fix
	uv run ruff check --fix .
	uv run ruff format .

typecheck: ## mypy --strict on ml/ and backend app/
	uv run mypy

test: ## Unit tests (no external services); backend coverage gate 80%
	uv run pytest -m "not integration"
	uv run pytest services/backend -m "not integration" -q --cov=app --cov-fail-under=80

test-integration: ## Integration tests (testcontainers)
	uv run pytest -m integration || [ $$? -eq 5 ]

check: lint typecheck test ## Lint + types + tests (must pass before finishing a task)
	@echo "make check: OK (frontend checks are added in T-19)"

WORKERS ?= 4
data: ## Generate synthetic dataset v1 into data/synthetic/v1 (make data WORKERS=8)
	uv run python -m data_generator generate --config config/generator/default.yaml --seed 42 --out data/synthetic/v1 --workers $(WORKERS)

api: ## Run the backend dev server on http://127.0.0.1:8000 (docs at /docs)
	RELOAD=true uv run python -m app

eda: ## Regenerate docs/figures + data/eda_stats.json from the train split
	uv run python -m ml.eda.run_eda

splits: ## Compute + lock splits for data/synthetic/v1 into data_splits/ (refuses to change locked splits)
	uv run python -m ml.evaluation make-splits --data data/synthetic/v1 --dataset-version synthetic/v1

verify-splits: ## Check committed splits still match data/synthetic/v1
	uv run python -m ml.evaluation verify-splits --data data/synthetic/v1 --dataset-version synthetic/v1

train-local: ## Train baselines + register to local MLflow (stub: T-09/T-25)
	$(call NOT_YET,T-09/T-25)

up: ## docker compose up (stub: T-29)
	$(call NOT_YET,T-29)

down: ## docker compose down (stub: T-29)
	$(call NOT_YET,T-29)

seed-demo: ## Create demo user with synthetic data (stub: T-29)
	$(call NOT_YET,T-29)

demo: ## data + train-local + up + seed-demo (stub: T-29)
	$(call NOT_YET,T-29)

openapi: ## Regenerate OpenAPI specs + frontend client (stub: T-11/T-19)
	$(call NOT_YET,T-11/T-19)

train: ## make train MODEL=... DATASET=... (stub: T-25)
	$(call NOT_YET,T-25)

promote: ## Promote a model version (stub: T-27)
	$(call NOT_YET,T-27)

rollback: ## Roll back @production to @previous (stub: T-27)
	$(call NOT_YET,T-27)

loadtest: ## k6 load test (stub: T-43)
	$(call NOT_YET,T-43)

jobs-run: ## make jobs-run JOB=... (stub: T-37)
	$(call NOT_YET,T-37)
