# Progress

Status of every task in PRD §20.3. Update this file at the end of each session.

Status values: `todo` · `in-progress` · `blocked` · `done` · `cut` (dropped at a cut line, with reason).

**Current focus:** next T-08 (classifier feature module with point-in-time and parity harness)
**Current tier:** A (weeks 1–6) — target: Cut line A (`make demo` works locally)

---

## Session handoff

Newest entry on top. Keep each entry short: what was done, what is half-done, what to do next, gotchas.

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
- Branch note: this work is on `feat/backend-core`; T-08..T-10 live on `feat/classifier`. `docs/PROGRESS.md` and `docs/DECISIONS.md` were edited on both, so expect a merge conflict there: keep both sets of entries.

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
| T-08 | Classifier feature module + point-in-time and parity harness | T-07 | todo | |
| T-09 | Baseline LR + calibrated Linear SVM + LightGBM; MLflow; eval report | T-05, T-08 | todo | |
| T-10 | Threshold calibration procedure (7.3.4) | T-09 | todo | |

### Week 3 — Backend core
| ID | Task | Deps | Status | Notes |
|---|---|---|---|---|
| T-11 | Backend scaffold: settings, logging, problem+json, request IDs, health | T-01 | done | `services/backend/app/` scaffold, 46 tests, `make api` |
| T-12 | DB schema + Alembic + category seed + repository layer with scoping test | T-11 | done | `app/models/`, `migrations/versions/0001_initial_schema.py`, `app/repositories/`, 15 integration + 12 unit tests |
| T-13 | Auth (register/login/refresh rotation/logout/password/delete) + rate limits | T-12 | todo | |
| T-14 | Transactions CRUD + filters + cursor pagination + idempotency + duplicates | T-12 | todo | |
| T-15 | CSV preview/commit with all error codes | T-14 | todo | |
| T-16 | BOLA/IDOR test suite | T-13, T-14 | todo | |

### Week 4 — ML service + frontend core
| ID | Task | Deps | Status | Notes |
|---|---|---|---|---|
| T-17 | ML service: model loading, `/v1/classify`, batch, probes, metrics, hash verification | T-09 | todo | |
| T-18 | Backend ML client (timeout, circuit breaker, fallback), categorization flow, merchant rules, feedback, categorize-preview | T-14, T-17 | todo | |
| T-19 | Frontend scaffold: auth, layout, API client, transactions page, review queue, CSV import UI | T-13, T-18 | todo | |

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
