# Progress

Status of every task in PRD §20.3. Update this file at the end of each session.

Status values: `todo` · `in-progress` · `blocked` · `done` · `cut` (dropped at a cut line, with reason).

**Current focus:** T-03 (synthetic generator v1)
**Current tier:** A (weeks 1–6) — target: Cut line A (`make demo` works locally)

---

## Session handoff

Newest entry on top. Keep each entry short: what was done, what is half-done, what to do next, gotchas.

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
| T-03 | Synthetic generator v1 with manifest + Pandera self-validation | T-02 | todo | |
| T-04 | EDA notebook → `docs/EDA.md` | T-03 | todo | |
| T-05 | Split module + locked splits + hash | T-03 | todo | |
| T-06 | Public dataset search → `docs/DATA_SOURCES.md`; decide Q1 | — | todo | |

### Week 2 — Classifier
| ID | Task | Deps | Status | Notes |
|---|---|---|---|---|
| T-07 | `ml/preprocessing` (merchant normalization ≥ 30 tests, description preprocessing) | T-02 | todo | |
| T-08 | Classifier feature module + point-in-time and parity harness | T-07 | todo | |
| T-09 | Baseline LR + calibrated Linear SVM + LightGBM; MLflow; eval report | T-05, T-08 | todo | |
| T-10 | Threshold calibration procedure (7.3.4) | T-09 | todo | |

### Week 3 — Backend core
| ID | Task | Deps | Status | Notes |
|---|---|---|---|---|
| T-11 | Backend scaffold: settings, logging, problem+json, request IDs, health | T-01 | todo | |
| T-12 | DB schema + Alembic + category seed + repository layer with scoping test | T-11 | todo | |
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
| Q1 | Public dataset for classifier generalization testing | End of week 1 (T-06) | open |
| Q2 | UI language: English only, or Indonesian too | Week 4 | open (default: English, i18n-ready) |
| Q3 | IndoBERT base vs smaller distilled model | Week 9 | open |
| Q4 | GCP free tier/credits at deploy time | Week 7 | open (default: assume none) |
| Q5 | Internship application deadline | Week 1 | open (default: ≥ 10 weeks) |

## Blockers

None.
