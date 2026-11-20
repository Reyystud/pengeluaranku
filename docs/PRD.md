# Smart Expense Intelligence — Product Requirements Document

| Field | Value |
|---|---|
| Version | 3.0 (implementation spec) |
| Supersedes | PRD v1.0 (product spec) and PRD v2.0 (MLE portfolio revision) |
| Status | Approved for implementation |
| Owner | Muhammad Rafiandhi Suryadinata |
| Last updated | 2026-11-19 |
| Product type | AI/ML-powered personal finance web application |
| Primary market | Indonesia (IDR, Asia/Jakarta, Indonesian merchants) |
| Target users | University students and young professionals |
| Delivery | 10 weeks, three tiers with cut lines (Section 20) |

---

## Table of contents

- [0. How to use this document (read first — especially if you are an AI coding agent)](#0-how-to-use-this-document-read-first--especially-if-you-are-an-ai-coding-agent)
- [1. Product overview](#1-product-overview)
- [2. Users, personas, and problems](#2-users-personas-and-problems)
- [3. Scope, priorities, and non-goals](#3-scope-priorities-and-non-goals)
- [4. Conventions, glossary, and domain primitives](#4-conventions-glossary-and-domain-primitives)
- [5. Success metrics and service levels](#5-success-metrics-and-service-levels)
- [6. System architecture overview](#6-system-architecture-overview)
- [7. Functional requirements](#7-functional-requirements)
- [8. User experience and frontend specification](#8-user-experience-and-frontend-specification)
- [9. Machine learning design](#9-machine-learning-design)
- [10. Data](#10-data)
- [11. Features and model artifacts](#11-features-and-model-artifacts)
- [12. Database design (PostgreSQL)](#12-database-design-postgresql)
- [13. Backend public API (`/api/v1`)](#13-backend-public-api-apiv1)
- [14. ML service API and event contracts](#14-ml-service-api-and-event-contracts)
- [15. Batch jobs and scheduling](#15-batch-jobs-and-scheduling)
- [16. MLOps: pipeline, registry, promotion, rollback](#16-mlops-pipeline-registry-promotion-rollback)
- [17. Security and privacy](#17-security-and-privacy)
- [18. Monitoring, alerting, and runbooks](#18-monitoring-alerting-and-runbooks)
- [19. Infrastructure, environments, and configuration](#19-infrastructure-environments-and-configuration)
- [20. Delivery plan: 10 weeks, tiers, and cut lines](#20-delivery-plan-10-weeks-tiers-and-cut-lines)
- [21. Testing strategy](#21-testing-strategy)
- [22. Repository structure](#22-repository-structure)
- [23. Documentation set](#23-documentation-set)
- [24. Risks and mitigations](#24-risks-and-mitigations)
- [25. Open questions](#25-open-questions)
- [26. Acceptance criteria and Definition of Done](#26-acceptance-criteria-and-definition-of-done)
- [Appendix A — Mapping to the target role (ML Engineer intern)](#appendix-a--mapping-to-the-target-role-ml-engineer-intern)
- [Appendix B — Portfolio packaging and interview preparation](#appendix-b--portfolio-packaging-and-interview-preparation)
- [Appendix C — ADR template (`docs/adr/0000-template.md`)](#appendix-c--adr-template-docsadr0000-templatemd)
- [Appendix D — Model card template (`docs/model_cards/<model>.md`)](#appendix-d--model-card-template-docsmodel_cardsmodelmd)
- [Appendix E — Official technical references](#appendix-e--official-technical-references)

---

## 0. How to use this document (read first — especially if you are an AI coding agent)

This PRD is the single source of truth for building Smart Expense Intelligence. It is written so that an engineer or an AI coding agent can implement any part of the system without guessing.

### 0.1 Normative language

- **MUST** / **MUST NOT**: required. A pull request that violates it is incomplete.
- **SHOULD** / **SHOULD NOT**: expected unless there is a written reason (put the reason in an ADR, see 0.4).
- **MAY**: optional.

### 0.2 Precedence when sources disagree

1. This PRD (v3.0).
2. Accepted ADRs in `docs/adr/` that explicitly amend a PRD section.
3. Generated contracts (`services/backend/openapi.json`, `services/ml_service/openapi.json`) — these MUST be regenerated from code and MUST match Section 13–14 of this PRD.
4. PRD v1.0 / v2.0 are historical only. Do not implement anything from them that is not in this document. Section 3 lists every conflict between them and how it was resolved.

### 0.3 Rules for agents working on this repository

1. **Work in vertical slices.** Each task (Section 20.3) MUST leave the system runnable: `make check` passes (lint, type-check, tests) and `docker compose up` still starts.
2. **Never invent numbers.** Any metric that appears in README, docs, CV bullets, or UI MUST come from an actual run (MLflow run ID or test report). Use placeholders like `[TBD after run]` until then.
3. **Never hardcode ML thresholds in business code.** Thresholds live in model metadata (Section 11.6) or in `config/` files with a version.
4. **Never log raw transaction descriptions, merchant names, amounts tied to a user, tokens, or passwords** (Section 17.3).
5. **Never commit secrets, real personal financial data, or large datasets.** Only synthetic data generated from a seed (Section 10.1).
6. **Every user-scoped query MUST filter by the authenticated `user_id`.** Use the repository helpers in Section 12.4; do not write raw unscoped queries.
7. **Money is never a float.** Use `Decimal` in Python, `NUMERIC` in PostgreSQL, strings in JSON (Section 4.3).
8. **When something is ambiguous**, choose the simplest option consistent with this PRD, implement it, and record it in `docs/adr/NNNN-title.md` plus the "Decisions log" in `docs/DECISIONS.md`. Do not block.
9. **When you change a contract** (DB schema, API, event, ML request/response), update this PRD's relevant section in the same PR, add an Alembic migration if needed, and bump the version field where defined.
10. **Tests come with code.** Each requirement ID (e.g. `FR-02.07`) SHOULD be referenced in at least one test name or docstring so coverage can be traced: `def test_fr_02_07_duplicate_detected_same_day(): ...`.
11. **Do not add infrastructure that this PRD lists as out of scope** (Kafka, Kubernetes, managed feature store, LLM features). Write an ADR proposal instead.
12. **Everything MUST run locally without a GCP account** (Section 19.1). Cloud-specific code sits behind an interface with a local implementation.

### 0.4 Where decisions are recorded

| What | Where |
|---|---|
| Architecture/design decisions | `docs/adr/NNNN-kebab-title.md` (template in Appendix C) |
| Short decision log (one line each) | `docs/DECISIONS.md` |
| Open questions still unresolved | Section 25 of this PRD |
| Model results | `docs/MODEL_EVALUATION.md` + MLflow |

---

## 1. Product overview

### 1.1 Background

Many people struggle to understand and manage daily spending. Expense trackers exist, but users still record and categorize transactions by hand. Small recurring purchases go unnoticed, unusual spending is discovered only after the balance is low, and users cannot tell whether their money will last until the end of the month.

Conventional trackers record and visualize. Smart Expense Intelligence turns transaction history into actionable information with machine learning: automatic categorization, anomaly alerts, month-end forecasts, recurring-payment detection, and personalized insights — each one explainable and traceable to the user's own data.

### 1.2 Vision

A personal financial intelligence platform that helps users **understand, predict, and improve** their spending through automation, analytics, and machine learning.

### 1.3 Core user questions

- Student: **"Will my money last until the end of the month?"**
- Young professional: **"Where does my money actually go?"**

### 1.4 Product goals

| ID | Goal | Measured by |
|---|---|---|
| G1 | Reduce manual effort in recording and categorizing | % of transactions auto-categorized at target precision (coverage curve, Section 9.2) |
| G2 | Reveal spending patterns automatically | Dashboard + insights computed from user data only |
| G3 | Detect unusual transactions and behavior | Anomaly precision at recall ≥ 0.50; alerts per user per month |
| G4 | Forecast future spending | WAPE of period-end forecast vs. run-rate baseline |
| G5 | Generate personalized, traceable insights | Every insight has an evidence payload |
| G6 | Demonstrate an end-to-end ML product | Reproducible pipeline, registry, promotion gate, rollback, monitoring, deployed on GCP |

### 1.5 Portfolio objective

This project is also a portfolio piece for a Machine Learning Engineer internship. Every claim in the README MUST be verifiable in the repository within minutes (Appendix A maps role requirements to evidence).

---

## 2. Users, personas, and problems

### 2.1 Personas

**Persona A — University student**
- Fixed monthly allowance (~Rp1.500.000), arriving around the same day each month.
- Many small transactions (coffee, food delivery, ride-hailing, minimarket).
- Struggles to control food and entertainment spending.
- Core need: "Will my money be enough until the end of the month?"

**Persona B — Young professional**
- Salary (~Rp7.000.000) on a payday that is often not the 1st (e.g. the 25th).
- Multiple payment methods: e-wallets (GoPay, OVO, DANA, ShopeePay), bank transfer, debit/credit card, QRIS.
- Several subscriptions (streaming, music, cloud storage, gym).
- Core need: "Where does my money actually go?"

Secondary archetypes used by the synthetic generator (not marketed personas): freelancer with irregular income, impulsive spender, subscription-heavy user.

### 2.2 Problems → solutions

| User problem | Solution | Requirement |
|---|---|---|
| Manual categorization is tedious | Automatic categorization with confidence and per-user merchant memory | FR-03 |
| Spending patterns are unclear | Analytics dashboard | FR-04 |
| Budgets are exceeded unnoticed | Budgets with status and threshold notifications | FR-05, FR-14 |
| Unusual expenses go unnoticed | Explainable anomaly detection | FR-06 |
| Month-end spending is hard to estimate | Period-end forecast with uncertainty range | FR-07 |
| Recurring payments are forgotten | Recurring expense detection with next-due date | FR-08 |
| Raw numbers are hard to interpret | Rule-based, traceable insights | FR-09 |

---

## 3. Scope, priorities, and non-goals

### 3.1 Requirement index

| ID | Feature | Priority | Tier | Phase |
|---|---|---|---|---|
| FR-01 | Authentication, profile, account deletion | Must | A | 1 |
| FR-02 | Transactions: CRUD, CSV import, duplicates | Must | A | 1 |
| FR-03 | Automatic categorization with confidence | Must | A | 1 |
| FR-04 | Analytics dashboard | Must | A | 1 |
| FR-05 | Budgets and status | Must | A | 1 |
| FR-06 | Anomaly detection with reasons | Should | A (baseline) / B (model) | 2 |
| FR-07 | Expense forecasting | Should | A (baseline) / B (model) | 2 |
| FR-08 | Recurring expense detection | Should | B | 2 |
| FR-09 | Personalized insights (rule-based) | Should | B | 2 |
| FR-10 | Feedback loop (corrections, alert confirmations) | Must | A | 2 |
| FR-11 | Event-driven scoring via Pub/Sub | Should | B | 3 |
| FR-12 | Training pipeline, registry, promotion, monitoring | Must | A (pipeline+registry) / B (monitoring) | 3 |
| FR-13 | Spending behavior clustering | Could | C | 2 |
| FR-14 | In-app notifications | Should | A | 1 |
| FR-15 | Merchant rules management (settings) | Should | B | 2 |
| FR-16 | Personal data export | Could | C | 1 |

Tier definitions and cut lines: Section 20.

### 3.2 Non-goals (MUST NOT be built in this release)

- Direct bank integration or automatic bank synchronization (incl. open-banking APIs, SMS/email parsing).
- Payments, money transfers, top-ups.
- Investment portfolio management, credit scoring, loan recommendations.
- LLM-based financial advisor or LLM-generated insight text.
- Automated multi-currency conversion (only IDR is supported; see 4.3).
- Receipt OCR.
- Native mobile apps (the web app MUST be responsive down to 360 px width).
- Email / push / SMS notifications (in-app only).
- Shared/household accounts, multiple users per ledger.
- Multiple wallets/accounts per user with separate balances (one combined ledger per user; payment method is a tag).
- Kafka, Kubernetes, a managed feature store. These go in ADRs as future options only.

### 3.3 Conflicts between v1.0 and v2.0 and how they are resolved

| # | Conflict | Resolution in v3.0 |
|---|---|---|
| C1 | v1.0 used `FR-01` for features and `FR-001` for rows | Feature IDs `FR-NN`; sub-requirements `FR-NN.MM` |
| C2 | Two categorize endpoints: `/transactions/{id}/categorize` and `/transactions/categorize` | Split by purpose: `POST /transactions/categorize-preview` (no persistence) and `POST /transactions/{id}/recategorize` (re-run on stored transaction). ML inference only on the internal ML service |
| C3 | v1.0 acceptance: "valid rows are imported, invalid rows get errors"; v2.0: "one bad row fails the whole import" | Two-step import: `preview` validates everything and returns per-row results; `commit` imports atomically either all rows (`mode=strict`, default) or only the rows that were valid at preview (`mode=skip_invalid`). Either way the DB never holds a partial import (FR-02.07) |
| C4 | Latency: v1.0 P95 ≤ 500 ms for everything; v2.0 300/200/500 ms | v2.0 values (Section 5.3) |
| C5 | Classification target: "+3 points and ≥ 0.85" vs decision rule "+2 points" | A candidate ships only if macro F1 ≥ LR baseline + 2.0 points (ship rule, 9.1) **and** ≥ current production + 0.5 points (avoids churn, 16.3). 0.85 is the reported project target, not a gate (Sections 5.2, 16.3) |
| C6 | Anomaly cold start: "conservative global baselines" vs "< 30 transactions uses cohort prior" | < 30 transactions **in that category** for that user → category-level global prior (Section 7.6.4) |
| C7 | Netflix → Entertainment vs a "Subscription" concept | Category stays semantic (Entertainment); "subscription/recurring" is a separate flag from FR-08, never a category |
| C8 | Month = calendar month vs budgeting period | All "month" logic uses the user's **budget period** (start day 1–28, Section 4.5) |
| C9 | v1.0 CSV `type` had only income/expense | Adds `transfer` (e-wallet top-ups, moving money between own accounts), excluded from income/expense totals (Section 4.4) |
| C10 | Orchestrator "Prefect or Airflow" | Prefect 3 (ADR-0004) |
| C11 | Tracking "MLflow or Vertex AI" | MLflow (ADR-0003); Vertex AI documented as alternative |
| C12 | Repo layout `backend/` (v1) vs `services/backend/` (v2) | v2 layout (Section 22) |

---

## 4. Conventions, glossary, and domain primitives

### 4.1 Glossary

| Term | Definition |
|---|---|
| Transaction | One money movement recorded by a user: income, expense, or transfer |
| Merchant | Counterparty name. Provided by user/CSV or derived from description |
| `merchant_key` | Normalized merchant string used for grouping and rules (Section 7.3.2) |
| Budget period | The user's recurring monthly window starting on `budget_period_start_day` |
| Period-to-date (PTD) | From the current period start to "now" in the user's timezone |
| Decision | Categorization outcome: `auto_apply`, `suggest`, `needs_review` |
| Category status | How a transaction got its category (Section 7.3.5) |
| Alert | An anomaly that the system chose to surface to the user (subject to the alert budget) |
| Insight | A deterministic, data-backed statement with an evidence payload |
| Run-rate | Baseline forecast: PTD spending ÷ days elapsed × days in period |
| Production model | Model version tagged with MLflow alias `production` |
| Candidate | Model version that passed offline gates, alias `candidate` |
| Shadow | Candidate receiving mirrored traffic whose outputs are logged, not shown |
| Feature version | Version string of the shared feature code (e.g. `features-1`) |
| Archetype | Synthetic user profile used by the data generator |

### 4.2 Identifiers and time

- All primary keys are UUIDv7 (time-ordered) generated in the application. Column type `UUID`.
- All timestamps are stored as `TIMESTAMPTZ` in UTC. API returns ISO 8601 with offset (`2026-11-18T05:30:00Z`).
- Each user has `timezone` (IANA, default `Asia/Jakarta`). Every "day", "week", "period", "weekend", and "time of day" computation MUST use the user's timezone.
- Week starts Monday. Weekend = Saturday and Sunday.
- A transaction may have **no time of day** (CSV date-only, or user did not set a time). Store `transaction_date` at 12:00 local time and set `has_time = false`. Time-of-day features MUST treat `has_time = false` as missing (Section 11.2).

### 4.3 Money

- Currency: **IDR only** in this release. `users.currency` exists and is fixed to `IDR` (validated); this keeps the schema ready for later.
- Storage: `NUMERIC(15,2)`; Python `decimal.Decimal`; JSON as a **string** (`"25000.00"`). Frontend parses with a decimal-safe approach (no float arithmetic for totals; totals come from the API).
- `amount` is always **positive** (> 0). Direction comes from `transaction_type`.
- Maximum single amount: `999,999,999,999.99` (fits NUMERIC(15,2)); validation rejects ≤ 0 and above `MAX_TRANSACTION_AMOUNT` (config, default 1,000,000,000).
- Display format: `id-ID` locale, no decimals for IDR: `Rp25.000`, `Rp1.500.000`. Negative values (net cash flow) display as `-Rp200.000`.
- Rounding for display only; stored values are never rounded except to 2 dp on input (`ROUND_HALF_UP`).
- ML features use `log1p(amount)` as float — floats are allowed **only inside ML code**, never for stored money.

### 4.4 Transaction types

| `transaction_type` | Meaning | Counted in income | Counted in expenses | Affects balance |
|---|---|---|---|---|
| `income` | Money in (allowance, salary, refund) | Yes | No | + |
| `expense` | Money out for consumption | No | Yes | − |
| `transfer` | Moving money between the user's own places (e-wallet top-up, cash withdrawal, savings) | No | No | 0 (net-neutral) |

Transfers exist so that "Top Up GoPay Rp200.000" is not counted as spending twice (once at top-up, once at purchase). The categorizer MUST be able to predict the `transfer` category; type mismatches are handled in 7.3.4.

### 4.5 Budget period

- `users.budget_period_start_day` ∈ 1..28 (default 1). 29–31 are not allowed to avoid short months.
- Period containing date *d* (local): starts on the most recent date ≤ *d* whose day-of-month = start day; ends the day before the next start.
- Example: start day 25 → period 2026-11-25 to 2026-12-24 inclusive.
- `period_id` string format: `YYYY-MM-DD` of the period start (e.g. `2026-11-25`).
- Changing the start day takes effect from the **next** period; the current period keeps its boundaries (store `budget_period_start_day_effective_from`).
- `days_in_period` and `days_elapsed` (inclusive of today) are computed in local time.

### 4.6 Category taxonomy (seeded, system-defined)

Categories are global and fixed in v3.0 (users cannot create categories; this keeps the classifier label space stable). Slugs are the stable identifiers used in ML labels and APIs; display names are for UI.

| Slug | Display name | Type | Examples (merchant / description) |
|---|---|---|---|
| `food_beverage` | Food & Beverage | expense | Kopi Kenangan, Starbucks, GoFood, GrabFood, ShopeeFood, warteg, Mie Gacoan |
| `groceries` | Groceries | expense | Indomaret, Alfamart, Superindo, Hypermart, pasar |
| `transportation` | Transportation | expense | Grab, Gojek GoRide, KRL, MRT Jakarta, TransJakarta, bensin Pertamina, parkir, tol |
| `utilities` | Utilities & Bills | expense | PLN, PDAM, IndiHome, Biznet, pulsa Telkomsel, paket data |
| `housing` | Housing | expense | kos, sewa apartemen, IPL |
| `shopping` | Shopping | expense | Tokopedia, Shopee, Lazada, Uniqlo, Erafone |
| `entertainment` | Entertainment | expense | Netflix, Spotify, Disney+ Hotstar, XXI, CGV, Steam |
| `health` | Health | expense | Kimia Farma, Guardian, Halodoc, klinik, BPJS (when paid voluntarily) |
| `education` | Education | expense | UKT, Coursera, buku, fotokopi |
| `personal_care` | Personal Care | expense | barbershop, salon, laundry |
| `gifts_donations` | Gifts & Donations | expense | kado, zakat, donasi, Kitabisa |
| `fees_charges` | Fees & Charges | expense | biaya admin, biaya transfer, denda |
| `other_expense` | Other Expense | expense | anything not covered |
| `allowance` | Allowance | income | uang saku, kiriman orang tua |
| `salary` | Salary | income | gaji, payroll |
| `freelance` | Freelance & Side Income | income | proyek, honor |
| `refund` | Refund & Cashback | income | refund, cashback |
| `other_income` | Other Income | income | hadiah uang, bunga |
| `transfer` | Transfer & Top-up | transfer | Top Up GoPay, tarik tunai, pindah ke tabungan |
| `uncategorized` | Uncategorized | any | System placeholder for `needs_review`; never a model label |

Rules:
- `categories.transaction_type` constrains which categories are valid for a transaction type (validation error `CATEGORY_TYPE_MISMATCH` otherwise). `uncategorized` is valid for all types.
- Refunds are **income** and do not reduce category spending (known limitation; document in UI tooltip).
- Taxonomy changes require a new `taxonomy_version` (stored in model metadata) and retraining. Current: `taxonomy-1`.

### 4.7 Payment methods

`payment_method` enum: `cash`, `bank_transfer`, `debit_card`, `credit_card`, `e_wallet`, `qris`, `other`.

CSV/API input aliases (case-insensitive, trimmed, `-`/space → `_`): `bank` → `bank_transfer`, `card` → `debit_card`, `ewallet`/`e-wallet` → `e_wallet`, `qr` → `qris`. Unknown values → validation error `INVALID_PAYMENT_METHOD`.

### 4.8 Naming conventions

- Python: snake_case modules/functions, PascalCase classes. API JSON fields: snake_case.
- DB tables: plural snake_case. Enums stored as `TEXT` + `CHECK` constraint (easier migrations than PG enums).
- Model names in MLflow: `transaction-classifier`, `anomaly-detector`, `expense-forecaster`, `behavior-clusterer`.
- Model version strings in API responses: `<model-name>@<mlflow-version>` e.g. `transaction-classifier@7`. A semantic label (e.g. `1.0.0`) MAY be kept as an MLflow tag.
- Events: `<entity>.<past-tense-verb>` e.g. `transaction.created`.

---

## 5. Success metrics and service levels

### 5.1 Product metrics (tracked in the monitoring dashboard)

| Metric | Definition | Initial target |
|---|---|---|
| Auto-categorization coverage | % of new transactions with decision `auto_apply` | ≥ 60% at auto-apply precision ≥ 0.95 |
| Correction rate | % of model-categorized transactions later changed by the user within 30 days | ≤ 10% |
| Alert load | Anomaly alerts surfaced per user per period | ≤ 3 (hard cap, 7.6.6) |
| Alert confirmation rate | confirmed ÷ (confirmed + dismissed) | ≥ 0.50 |
| Import success | CSV commits that succeed ÷ commits attempted | ≥ 99% |

### 5.2 Model metrics and baselines

Every target is measured against a simple baseline on the locked splits (Section 10.4). A model that does not beat its baseline is not promoted, regardless of sophistication.

| Area | Primary metric | Baseline | Initial target |
|---|---|---|---|
| Classification | Macro F1 on temporal test split | TF-IDF (char n-gram) + Logistic Regression | ≥ 0.85 reported; shipping needs ≥ +2.0 points vs. baseline and ≥ +0.5 vs. production |
| Anomaly detection | Precision at recall ≥ 0.50 | Robust modified z-score (MAD) per user × category | ≥ 0.70 |
| Forecasting | WAPE of period-total forecast made on day 15 | Run-rate | ≤ 20% and MASE < 1 |
| Clustering | Silhouette; stability across seeds (ARI) | K-Means, k by silhouette | Silhouette ≥ 0.40, ARI ≥ 0.80 |
| Reproducibility | |metric(run₁) − metric(run₂)| with same seed and data | — | ≤ 0.01 |

These are experimental targets, not guarantees. Because the main data is synthetic, the evaluation report MUST separate synthetic results from public-dataset results and state limitations.

### 5.3 Service level objectives

| SLI | Target | Window |
|---|---|---|
| Backend CRUD latency P95 (server-side, excl. network) | ≤ 300 ms | 7 days |
| ML inference latency P95, linear models | ≤ 200 ms | 7 days |
| ML inference latency P95, transformer model (if shipped) | ≤ 500 ms | 7 days |
| `POST /transactions` end-to-end P95 (incl. sync categorization) | ≤ 500 ms | 7 days |
| Transaction processing success (2xx ÷ valid requests) | ≥ 99% | 7 days |
| Anomaly scoring freshness (event → stored result) P95 | ≤ 60 s | 7 days |
| Demo deployment availability | ≥ 99.5% | 30 days |
| Backend test coverage (lines) | ≥ 80% | every merge |
| `ml/` library test coverage (lines) | ≥ 70% | every merge |

Cold starts on Cloud Run with min instances = 0 are excluded from latency SLOs but MUST be reported separately in the load-test report.

---

## 6. System architecture overview

### 6.1 Components

```text
                         ┌──────────────────────────────┐
  Browser ──HTTPS──────▶ │ frontend (Next.js, Cloud Run)│
                         └──────────────┬───────────────┘
                                        │ REST /api/v1 (JWT)
                         ┌──────────────▼───────────────┐   sync, IAM-auth, timeout 300 ms
                         │ backend (FastAPI, Cloud Run) │ ─────────────────────────────┐
                         │ auth · transactions · budgets│                              │
                         │ analytics · insights · rules │                              ▼
                         └──┬──────────┬──────────┬─────┘              ┌──────────────────────────┐
                            │          │          │ publish            │ ml-service (FastAPI,     │
                    SQL     │   cache  │          ▼                    │ Cloud Run, private)      │
              ┌─────────────▼┐  ┌──────▼─┐  ┌─────────────┐  push     │ classify · anomaly ·     │
              │ Cloud SQL    │  │ Redis  │  │ Pub/Sub     │──────┐    │ forecast · cluster       │
              │ PostgreSQL   │  │(optional)│ │ transaction.*│     │    └───────────▲──────────────┘
              └──────┬───────┘  └────────┘  └─────────────┘      │                │ loads models
                     │ daily export                              ▼                │
              ┌──────▼───────┐                         ┌──────────────────┐  ┌────┴─────────────┐
              │ BigQuery     │◀── prediction log sink ─│ worker (backend  │  │ Cloud Storage    │
              │ raw/curated/ │                         │ image, /internal)│  │ models, datasets │
              │ features/    │                         └──────────────────┘  └────▲─────────────┘
              │ predictions  │                                                    │
              └──────┬───────┘          ┌───────────────────────────┐             │
                     └────────────────▶ │ pipelines (Prefect flows, │─────────────┘
                                        │ Cloud Run Jobs, scheduled)│──▶ MLflow (Cloud Run + Cloud SQL + GCS)
                                        └───────────────────────────┘
```

| Component | Responsibility | Owns data? |
|---|---|---|
| `frontend` | UI, client-side validation, calls backend only | No |
| `backend` | Auth, business rules, persistence, online feature computation, analytics, insights, budgets, notifications, publishing events | Yes (Cloud SQL) |
| `worker` | Same codebase/image as backend, deployed as a separate Cloud Run service exposing only `/internal/*` push endpoints for Pub/Sub | Uses backend DB |
| `ml-service` | Stateless inference only. Never reads the user DB. Loads model artifacts by alias. Logs predictions | No |
| `pipelines` | Data generation, validation, training, evaluation, gating, registration, batch scoring (forecast, clustering) | Writes artifacts, registry, batch results via backend internal API |
| `mlflow` | Experiment tracking + model registry | Yes (its own DB schema) |

### 6.2 Key architecture decisions (each has an ADR)

| ADR | Decision | Why |
|---|---|---|
| 0001 | Backend is a modular monolith; ML is a separate service | ML has different dependencies, image size, and release cycle; business logic does not |
| 0002 | Online features are computed in the backend using the shared `ml/preprocessing` package and sent in the inference request | ML service stays stateless and DB-free; one feature code path for training and serving |
| 0003 | MLflow over Vertex AI Experiments/Registry | Portable, runs locally, free; Vertex AI noted as managed alternative |
| 0004 | Prefect 3 for orchestration | Lighter than Airflow for a single project; flows are plain Python and run locally |
| 0005 | Pub/Sub + Cloud Run, no Kafka/Kubernetes | Sufficient for the scale; managed; scale-to-zero |
| 0006 | No managed feature store | BigQuery `features` tables + shared module are enough |
| 0007 | Baseline-first modeling | Every model must beat a simple baseline before shipping |
| 0008 | Synthetic data only for training and public demo | Privacy; reproducibility |
| 0009 | Two-step CSV import (preview/commit) | Resolves C3 without partial imports |

### 6.3 Request flows

**Create transaction (sync path)**
1. Frontend `POST /api/v1/transactions` with `Idempotency-Key`.
2. Backend validates (Pydantic), normalizes merchant (`merchant_key`).
3. If a user merchant rule matches → category from rule, `category_status = rule`, no ML call.
4. Else backend calls `ml-service POST /v1/classify` with timeout 300 ms, 1 retry on connection error only (not on timeout).
5. On success: apply decision (7.3.5). On timeout/5xx/circuit open: `category_id = uncategorized`, `category_status = needs_review`, `ml_error = 'unavailable'`. **Saving the transaction MUST NOT fail because of ML.**
6. Insert transaction + `category_predictions` row + outbox row (`transaction.created`) in **one DB transaction**.
7. Return 201 with the transaction including decision info.
8. Outbox relay publishes the event to Pub/Sub (at-least-once).

**Anomaly scoring (async path)**: Pub/Sub push → `worker POST /internal/events/transaction` → dedupe by `event_id` → compute anomaly features from history before the transaction → `ml-service POST /v1/anomaly/score` → upsert `anomalies` → maybe create alert notification (alert budget, 7.6.6) → ack. Failures return 5xx so Pub/Sub retries; after 5 attempts → dead-letter topic.

**Forecast**: daily batch job + on-demand recompute when cache is stale (FR-07.07).

**CSV import**: `preview` (validate + classify in batch, store a staged import) → user reviews → `commit` (atomic insert) → one `transaction.created` event per row (batched publish).

### 6.4 Circuit breaker for backend → ML service

- Open after 5 consecutive failures or > 50% failures over the last 20 calls; stay open 30 s; then half-open with 1 trial request.
- While open, skip the call and use the fallback in 6.3 step 5.
- Expose `ml_circuit_state` gauge (0 closed, 1 half-open, 2 open).

### 6.5 Technology stack

Pin exact versions in lockfiles (`uv.lock`, `pnpm-lock.yaml`) at project start; use the latest stable release of each at that time. Do not add libraries outside this table without a line in `docs/DECISIONS.md`.

| Layer | Choice |
|---|---|
| Python | 3.12; `uv` workspace (packages: `ml`, `data_generator`, `services/backend`, `services/ml_service`, `pipelines`) |
| API framework | FastAPI + Uvicorn; Pydantic v2; pydantic-settings |
| DB access | SQLAlchemy 2.x (sync sessions, `lazy="raise"`), psycopg 3, Alembic |
| Auth | PyJWT, argon2-cffi |
| HTTP client | httpx (with explicit timeouts) |
| Logging/metrics/tracing | structlog, prometheus-client, OpenTelemetry (optional) |
| Data/ML | pandas, numpy, scikit-learn, LightGBM, statsmodels, scipy, pandera, duckdb; PyTorch + transformers (+ optimum/onnxruntime) only in the DL experiment extra |
| MLOps | MLflow, Prefect 3, Evidently |
| GCP SDKs | google-cloud-pubsub, google-cloud-bigquery, google-cloud-storage, google-auth |
| Testing | pytest, hypothesis, testcontainers, time-machine, schemathesis, jsonschema |
| Quality | ruff (lint + format), mypy (strict for `ml/` and backend `app/`), pre-commit, gitleaks |
| Frontend | Node 22 LTS, pnpm, Next.js (App Router), TypeScript strict, Tailwind, shadcn/ui, TanStack Query, React Hook Form, Zod, Recharts, Vitest, Playwright |
| Infra | Docker, Terraform, GitHub Actions, k6 |

---

## 7. Functional requirements

Each sub-requirement has an ID `FR-NN.MM`. Acceptance criteria are in Section 26.

### 7.1 FR-01 — Authentication, profile, and account lifecycle

| ID | Requirement | Priority |
|---|---|---|
| FR-01.01 | Users register with email + password + display name. Email is unique (case-insensitive, stored lowercased and trimmed) | Must |
| FR-01.02 | Password policy: 10–128 characters; reject if in a bundled common-password list (top 10k); no composition rules | Must |
| FR-01.03 | Login returns an access token (JWT, 15 min) in the response body and sets a refresh token (opaque, 30 days) in an `HttpOnly; Secure; SameSite=Strict; Path=/api/v1/auth` cookie | Must |
| FR-01.04 | Refresh rotates the refresh token on every use. Reuse of an already-rotated token revokes the whole token family (all sessions from that login) | Must |
| FR-01.05 | Logout revokes the current refresh token family | Must |
| FR-01.06 | Profile fields: `display_name`, `currency` (fixed `IDR`), `timezone` (IANA, default `Asia/Jakarta`), `budget_period_start_day` (1–28, default 1), `opening_balance` (default 0), `training_consent` (default false), `locale` (`en` default; `id` reserved) | Must |
| FR-01.07 | Users can update profile fields (FR-01.06). Changing `budget_period_start_day` applies from the next period (4.5) | Should |
| FR-01.08 | Users can change password (requires current password); this revokes all other sessions | Should |
| FR-01.09 | Users can delete their account. Requires password re-entry and typing `DELETE`. Deletion is a **hard delete** of the user row and all owned rows (transactions, budgets, predictions, anomalies, feedback, insights, forecasts, recurring, rules, notifications, imports, sessions) via `ON DELETE CASCADE`, in one DB transaction. A `deletion_requests` tombstone (user_id hash + timestamp only) triggers purging that user's rows from BigQuery tables within 24 h (daily job) | Must |
| FR-01.10 | Login rate limit: 5 failed attempts per email per 15 min and 20 per IP per 15 min → 429 with `Retry-After`. Error messages MUST NOT reveal whether an email exists | Must |
| FR-01.11 | Email verification and password reset by email are **out of scope** (no email sending). Document as future work | — |
| FR-01.12 | A seeded demo account (`demo@example.com`, password from env) with 12 months of synthetic data exists in the demo deployment; it is reset nightly | Should |

### 7.2 FR-02 — Transaction management

#### 7.2.1 Transaction fields

| Field | Type | Required on create | Rules |
|---|---|---|---|
| `id` | UUID | server | UUIDv7 |
| `user_id` | UUID | server | from token, never from body |
| `transaction_type` | `income`/`expense`/`transfer` | yes | |
| `amount` | decimal string | yes | > 0, ≤ `MAX_TRANSACTION_AMOUNT`, max 2 dp |
| `description` | string | yes | trimmed, 1–200 chars, control chars stripped |
| `merchant` | string | no | trimmed, ≤ 100 chars; if absent, derived (7.3.2) |
| `merchant_key` | string | server | normalized merchant (7.3.2) |
| `transaction_date` | datetime or date | yes | not more than 1 day in the future (user tz); not before 2000-01-01 |
| `has_time` | bool | server | false if a date without time was given |
| `payment_method` | enum | no | default `other` |
| `category_id` | UUID/slug | no | if provided, `category_status = user_set` and no ML call |
| `category_status` | enum | server | 7.3.5 |
| `notes` | string | no | ≤ 500 chars; never sent to ML, never logged |
| `source` | `manual`/`csv`/`demo_seed` | server | |
| `import_id` | UUID | server | set for CSV rows |
| `possible_duplicate_of` | UUID | server | 7.2.4 |
| `created_at`, `updated_at` | timestamptz | server | |
| `deleted_at` | — | — | not used; deletes are hard deletes |

#### 7.2.2 CRUD requirements

| ID | Requirement | Priority |
|---|---|---|
| FR-02.01 | Create, read, update (PATCH), delete transactions. Ownership enforced; another user's ID returns **404** (not 403) to avoid leaking existence | Must |
| FR-02.02 | List with filters: `date_from`, `date_to` (local dates, inclusive), `transaction_type`, `category` (multi), `payment_method` (multi), `q` (case-insensitive substring on description/merchant), `min_amount`, `max_amount`, `category_status` (e.g. `needs_review`), `possible_duplicate=true`. Sort: `transaction_date desc` (default) or `amount desc`. Cursor pagination (13.1.4), default 50, max 200 | Must |
| FR-02.03 | PATCH may change any user-editable field. Changing `amount`, `transaction_date`, `transaction_type`, or `merchant` emits `transaction.updated` (re-scoring). Changing category records feedback (FR-10) | Must |
| FR-02.04 | Delete emits `transaction.deleted`; related anomalies/predictions are deleted by cascade | Must |
| FR-02.05 | Bulk actions: bulk delete (≤ 200 IDs) and bulk set category (≤ 200 IDs) — atomic | Should |

#### 7.2.3 CSV import

| ID | Requirement | Priority |
|---|---|---|
| FR-02.06 | `POST /transactions/imports` (multipart, field `file`) creates a staged import and returns a **preview**: per-row status (`valid`, `invalid`, `duplicate`), normalized values, predicted category + decision for valid rows, and summary counts. Nothing is written to `transactions` | Must |
| FR-02.07 | `POST /transactions/imports/{import_id}/commit` with body `{ "mode": "strict" | "skip_invalid", "skip_duplicates": true, "category_overrides": { "<row_number>": "<category_slug>" } }`. `strict` fails with 422 if any row is invalid. All inserts happen in **one DB transaction**; on any error nothing is persisted | Must |
| FR-02.08 | Staged imports expire after 24 h (deleted by a cleanup job). Committing an expired or already-committed import returns 409 `IMPORT_NOT_COMMITTABLE` | Must |
| FR-02.09 | Re-uploading a file with the same SHA-256 as a previously **committed** import for that user returns the preview with warning `FILE_ALREADY_IMPORTED` (not an error) | Should |
| FR-02.10 | Limits: file ≤ 5 MB, ≤ 5,000 data rows, UTF-8 (BOM tolerated) — otherwise 413/422 with a clear message | Must |
| FR-02.11 | `GET /transactions/imports/template.csv` returns a template with headers and 3 example rows | Should |

**CSV format specification**

- Delimiter: auto-detect `,` or `;` from the header line. Quote char `"`. First row is the header.
- Headers are case-insensitive and trimmed; unknown columns are ignored with a warning.

| Column | Required | Accepted formats |
|---|---|---|
| `date` | yes | `YYYY-MM-DD`, `YYYY-MM-DD HH:MM`, `YYYY-MM-DD HH:MM:SS`, `DD/MM/YYYY`, `DD/MM/YYYY HH:MM`. Interpreted in the user's timezone. `MM/DD/YYYY` is **not** accepted (ambiguous) |
| `description` | yes | 1–200 chars |
| `amount` | yes | digits with optional `.` decimal and up to 2 dp (`25000`, `25000.50`); also accepted: optional `Rp`/`IDR` prefix, spaces, and **thousand separators** in the Indonesian style `25.000` / `1.500.000` **only when** the value has no decimal part and every group after the first has exactly 3 digits. A leading `-` is rejected with hint "use type=expense" |
| `type` | yes | `income`, `expense`, `transfer` (aliases: `in`/`credit` → income, `out`/`debit` → expense) |
| `payment_method` | no | 4.7 |
| `merchant` | no | ≤ 100 chars |
| `category` | no | category slug or display name (case-insensitive). If present and valid, it is used with `category_status = user_set` |
| `notes` | no | ≤ 500 chars |

- Row errors use machine-readable codes: `MISSING_FIELD`, `INVALID_DATE`, `FUTURE_DATE`, `INVALID_AMOUNT`, `AMOUNT_OUT_OF_RANGE`, `INVALID_TYPE`, `INVALID_PAYMENT_METHOD`, `UNKNOWN_CATEGORY`, `CATEGORY_TYPE_MISMATCH`, `FIELD_TOO_LONG`. Each error includes `row_number` (1-based, counting the header as row 1), `column`, `code`, `message`, and the offending value **truncated to 50 chars**.
- Empty lines are skipped silently. Rows with only whitespace count as empty.
- Formula-injection protection: when **exporting** CSV (FR-16), prefix cells beginning with `=`, `+`, `-`, `@`, tab, or CR with `'`.

Example (from v1.0, still valid):

```csv
date,description,amount,type,payment_method
2026-11-01,Kopi Kenangan,25000,expense,e-wallet
2026-11-02,Monthly Allowance,1500000,income,bank
2026-11-03,Grab Transport,18000,expense,e-wallet
2026-11-04,Netflix Subscription,65000,expense,card
```

#### 7.2.4 Duplicate detection

| ID | Requirement | Priority |
|---|---|---|
| FR-02.12 | A transaction is a **possible duplicate** of an existing one when all hold: same user, same `transaction_type`, same `amount`, same `merchant_key` (or, if empty, same normalized description), and `|Δ transaction_date|` ≤ 10 minutes when both `has_time = true`, otherwise same local date | Must |
| FR-02.13 | Manual create: duplicates are **saved** but flagged (`possible_duplicate_of` set) and the response includes warning `POSSIBLE_DUPLICATE`; UI shows a non-blocking banner with "Delete this" / "Not a duplicate" | Must |
| FR-02.14 | CSV preview: rows that duplicate an existing transaction or an earlier row in the same file get status `duplicate`. On commit they are skipped if `skip_duplicates = true` (default), else inserted with the flag | Must |
| FR-02.15 | "Not a duplicate" clears the flag and stores `duplicate_dismissed = true` so it is not re-flagged | Should |

### 7.3 FR-03 — Automatic categorization

#### 7.3.1 Requirements

| ID | Requirement | Priority |
|---|---|---|
| FR-03.01 | Every new transaction without a user-provided category gets a category via: (1) user merchant rule, else (2) ML model, else (3) `uncategorized` | Must |
| FR-03.02 | The ML service returns top-1 category, calibrated confidence, top-3 alternatives, decision, model version, feature version | Must |
| FR-03.03 | Each prediction is stored in `category_predictions` (even when overridden later) with model/feature version and latency | Must |
| FR-03.04 | Users can change the category of any transaction; this records feedback (FR-10) and may create a merchant rule (FR-03.08) | Must |
| FR-03.05 | Transactions with `suggest` or `needs_review` appear in a **Review queue** (Transactions page filter + dashboard badge with count) | Must |
| FR-03.06 | Confirming a suggestion sets `category_status = user_confirmed` (counts as positive feedback) | Must |
| FR-03.07 | `POST /transactions/categorize-preview` returns the prediction for a draft (used live in the add-transaction form after the user stops typing for 400 ms). It stores nothing except an anonymous metrics counter | Must |
| FR-03.08 | **Merchant memory**: when a user changes the category of a transaction whose `merchant_key` is non-empty, upsert `merchant_rules(user_id, merchant_key) → category_id`. Rule applies to future transactions immediately. The UI offers a checkbox "Also apply to N past transactions from this merchant" (default unchecked) | Must |
| FR-03.09 | `POST /transactions/{id}/recategorize` re-runs rule/model for one transaction unless its status is `user_set` or `user_confirmed` (then 409 `CATEGORY_LOCKED`, unless `force=true`) | Should |
| FR-03.10 | Type consistency: if the model's top category belongs to a different `transaction_type` than the transaction, choose the highest-ranked alternative with the correct type; if none in top-3, decision = `needs_review` | Must |

#### 7.3.2 Merchant normalization (`ml/preprocessing/merchant.py`)

`normalize_merchant(raw: str) -> str` MUST be deterministic, pure, and unit-tested with ≥ 30 cases. Steps in order:
1. Unicode NFKC; lowercase.
2. Remove payment prefixes/suffixes: `qris`, `qr`, `pos`, `edc`, `trf`, `transfer ke`, `pembayaran`, `payment`, `byr`, `debit`, `purchase`, `pmb`.
3. Remove known platform wrappers but keep the merchant: `gopay*kopi kenangan` → `kopi kenangan`, `shopeepay - x` → `x`, `ovo/x` → `x`, `dana x` → `x` (only when followed by another token).
4. Remove reference numbers: tokens with ≥ 4 digits, tokens like `#12345`, `inv/2026/...`, dates.
5. Remove location suffixes after ` - ` or ` @ ` and common branch tokens (`cab`, `cabang`, `outlet`, `store`, `branch`), city names from a small bundled list (Jakarta, Bandung, Surabaya, …).
6. Replace non-alphanumeric with space; collapse whitespace; strip.
7. Apply alias map (`config/merchant_aliases.yaml`, e.g. `indomart` → `indomaret`, `alfa mart` → `alfamart`, `gojek goride` → `gojek`).
8. Truncate to 64 chars. Empty result → `""`.

If `merchant` is not provided, `merchant` is set to a title-cased version of the first two tokens of the normalized description, and `merchant_key = normalize_merchant(description)` limited to the first 3 tokens.

#### 7.3.3 Description preprocessing for the classifier

`preprocess_description(text)`: NFKC, lowercase, strip reference numbers (same as step 4), collapse whitespace. Typos are **not** corrected (char n-grams handle them).

#### 7.3.4 Decision rules

Thresholds `t_high` and `t_low` come from the production model's metadata (`decision_thresholds`, Section 11.6). Defaults until calibration exists: `t_high = 0.85`, `t_low = 0.60`.

| Calibrated confidence | Decision | Stored `category_id` | `category_status` | UI |
|---|---|---|---|---|
| ≥ `t_high` | `auto_apply` | predicted | `auto` | Category shown normally, small "auto" icon |
| `t_low` ≤ c < `t_high` | `suggest` | predicted | `suggested` | Category shown with "Confirm?" chip; in review queue |
| < `t_low` | `needs_review` | `uncategorized` | `needs_review` | "Choose category" chip with top-3 as quick picks; in review queue |

Calibration procedure (pipeline, not runtime): on the validation split, choose `t_high` as the smallest threshold where precision of auto-applied predictions ≥ 0.95, and `t_low` as the smallest threshold where top-1 precision in [`t_low`, `t_high`) ≥ 0.70. If no threshold satisfies a constraint, use the defaults and flag it in the evaluation report.

Analytics treat `suggested` categories as the predicted category (they are shown with a badge). `uncategorized` appears as its own slice.

#### 7.3.5 Category status values

| Status | Set by | Locked against re-categorization |
|---|---|---|
| `auto` | model, auto_apply | No |
| `suggested` | model, suggest | No |
| `needs_review` | model low confidence or ML unavailable | No |
| `rule` | user merchant rule | No (but rule wins over model) |
| `user_set` | user chose a category (create, edit, CSV column, quick pick) | Yes |
| `user_confirmed` | user confirmed a suggestion | Yes |

### 7.4 FR-04 — Analytics dashboard

All figures are computed server-side from the user's transactions; the frontend MUST NOT sum transactions itself. Every number on the dashboard MUST equal what a direct SQL query over `transactions` returns (acceptance test with property-based checks).

| ID | Metric | Definition |
|---|---|---|
| FR-04.01 | Balance | `opening_balance + Σ income − Σ expense` over **all time** up to now (transfers excluded) |
| FR-04.02 | Income (period) | Σ `amount` where type = income, date ∈ selected period |
| FR-04.03 | Expenses (period) | Σ `amount` where type = expense, date ∈ selected period |
| FR-04.04 | Net cash flow | Income − Expenses for the period; savings rate = net ÷ income (null when income = 0) |
| FR-04.05 | Category breakdown | Expenses per category with amount, share %, transaction count; sorted desc; categories < 2% grouped into "Other" in charts only (API returns all) |
| FR-04.06 | Daily trend | Expenses per local day in the period, zero-filled for days without spending; plus cumulative line and, if a budget exists, the budget pace line (`limit × day_index ÷ days_in_period`) |
| FR-04.07 | Period-over-period | Same metrics for the previous period of equal type; % change = (cur − prev) ÷ prev; null when prev = 0. For an in-progress period, compare **PTD vs. same number of days of the previous period** (labelled "vs. same point last period") |
| FR-04.08 | Top merchants | Top 5 `merchant_key` by expense amount in the period, with display name (most recent `merchant` value), amount, count |
| FR-04.09 | Payment method split | Expense amount per payment method |
| FR-04.10 | Selectable range | Current period (default), previous period, last 3 periods, custom date range (max 366 days). Granularity auto: daily ≤ 62 days, weekly ≤ 183 days, else monthly |
| FR-04.11 | Empty states | With 0 transactions: show onboarding card (add transaction / import CSV / load sample data). Sample data (demo seeder for this user) is clearly labelled and removable in one click |
| FR-04.12 | Caching | Summary responses cached in Redis per (user, range) for 60 s and invalidated on any transaction write by that user. Without Redis, compute directly |

### 7.5 FR-05 — Budgets

| ID | Requirement | Priority |
|---|---|---|
| FR-05.01 | A budget is a **recurring monthly limit** on either overall expenses (`category_id = null`) or one expense category. At most one budget per (user, category or overall) | Must |
| FR-05.02 | Create, update (limit, thresholds), delete. Changes apply to the current and future periods | Must |
| FR-05.03 | Utilization = spent ÷ limit, where spent = Σ expense amount in the period for that category (overall: all expense categories, incl. `uncategorized` expenses). Limit > 0 | Must |
| FR-05.04 | Status (computed, never stored as truth): `healthy` < 50%; `normal` 50% – < 80%; `warning` 80% – < 100%; `exceeded` ≥ 100% | Must |
| FR-05.05 | Each budget has `alert_thresholds` (sorted unique integers in 1..200, default `[80, 100]`). When utilization first crosses a threshold in a period, create one notification (FR-14). Never notify twice for the same (budget, period, threshold) — enforced by a unique key | Must |
| FR-05.06 | Crossing is evaluated on every transaction create/update/delete affecting that budget and in the daily job. Deleting a transaction that lowers utilization does **not** delete past notifications | Must |
| FR-05.07 | Projected status: using FR-07 forecast for that category/overall, show "On track" / "May exceed" (exceed probability band medium or high) | Should |
| FR-05.08 | Period snapshot: at period close (daily job after the period ends, user tz), write `budget_period_snapshots(budget_id, period_id, limit, spent, utilization)` so history reflects the limit that applied then | Should |
| FR-05.09 | Sum of category budgets may exceed the overall budget; the UI shows a non-blocking warning | Should |
| FR-05.10 | A category budget on an income or transfer category is rejected (422 `CATEGORY_TYPE_MISMATCH`) | Must |

### 7.6 FR-06 — Spending anomaly detection

#### 7.6.1 Requirements

| ID | Requirement | Priority |
|---|---|---|
| FR-06.01 | Score every new or updated **expense** transaction asynchronously (FR-11). Income and transfers are not scored in this release | Must |
| FR-06.02 | Detect four anomaly types: `amount_spike` (transaction far above the user's usual for that category/merchant), `frequency_burst` (unusually many transactions in a category within 24 h), `new_merchant_high_value` (first-ever merchant for the user with a high amount), `category_surge` (7-day category spending far above the user's norm — a pattern anomaly, not tied to one transaction) | Must |
| FR-06.03 | Each anomaly has `anomaly_score` ∈ [0, 1], `severity` ∈ {`low`, `medium`, `high`}, `anomaly_type`, `reasons[]` computed from data, `model_version`, `feature_version`, `history_level` ∈ {`personal`, `limited`} | Must |
| FR-06.04 | Users can **confirm** ("Yes, unusual") or **dismiss** ("This is normal") an anomaly; optional dismiss reason: `expected_purchase`, `wrong_amount`, `not_mine`, `other`. Stored as feedback (FR-10) | Must |
| FR-06.05 | Dismissing with `expected_purchase` lowers future alerts for the same `merchant_key` for that user: the merchant is added to `anomaly_suppressions` for 90 days | Should |
| FR-06.06 | Unusually **low** amounts are computed (z ≤ −3.5) and stored as `low` severity for recurring-change detection only; they never create alerts | Should |
| FR-06.07 | Editing a transaction re-scores it (replaces its anomaly row). Deleting removes it | Must |
| FR-06.08 | Anomalies are listed in the Intelligence Center with filters (status, severity, type, period) | Must |

#### 7.6.2 Baseline detector (Tier A, required first)

For transaction *t* (user *u*, category *c*, amount *a*), using only transactions of *u* in category *c* **strictly before** *t* within the last 180 days (history *H*):

- `x = log1p(a)`; `m = median(log1p(H))`; `MAD = median(|log1p(H) − m|)`
- `MAD_floor = max(MAD, 0.05)` (prevents division by ~0 for very regular spenders)
- Modified z-score: `z = 0.6745 × (x − m) / MAD_floor` (Iglewicz–Hoaglin)
- Flag `amount_spike` when `z ≥ 3.5` **and** `a ≥ MIN_ALERT_AMOUNT` (config, default Rp50.000) **and** `a ≥ 2 × exp(m)` (at least double the typical amount).
- Score mapping: `score = clip((z − 2) / 6, 0, 1)` → z = 3.5 → 0.25, z = 5 → 0.5, z = 8 → 1.0. **Severity** for the baseline: `low` z < 3.5 (not flagged), `medium` 3.5 ≤ z < 5, `high` z ≥ 5.

`frequency_burst`: let λ = user's mean daily transaction count in *c* over the prior 56 days (min 0.1). Count *k* of transactions in *c* in the 24 h ending at *t* (incl. *t*). Flag if `k ≥ 3` and Poisson tail `P(X ≥ k | λ) < 0.001`. Score = `clip(−log10(p) / 6, 0, 1)`; severity high if p < 1e-5 else medium.

`new_merchant_high_value`: *t*'s `merchant_key` never seen before for *u* **and** `a ≥ max(Rp500.000, P95 of u's expense amounts over 180 days)`. Score 0.6 (medium); 0.9 (high) if `a ≥ 3 × P95`.

`category_surge` (daily job, not per transaction): for each (u, c), `S7` = spending in the last 7 days; `W` = weekly spending for each of the previous 8 full weeks. Flag if `S7 ≥ 2 × median(W)` and `S7 − median(W) ≥ Rp200.000` and at least 4 of the 8 weeks have spending > 0. One open surge anomaly per (u, c) at a time; refresh its values instead of duplicating.

#### 7.6.3 Model detector (Tier B)

Isolation Forest (and LOF for comparison) trained **across users** on user-relative features (11.2.2). Its raw score is mapped to [0, 1] by the empirical CDF of training scores. The flag threshold is chosen on validation to maximize precision subject to recall ≥ 0.50. The model replaces the baseline for `amount_spike` only if it beats the baseline on precision@recall≥0.50 (16.3). Rule-based `frequency_burst`, `new_merchant_high_value`, and `category_surge` remain rules.

#### 7.6.4 Cold start

If the user has < 30 prior transactions **in category c** (C6), use the category-level global prior: `m` and `MAD` computed across all users (training data) for that category and stored in model metadata. Set `history_level = limited`, cap severity at `medium`, and add reason "Based on typical spending for this category (limited personal history)". Users with < 7 days of history get no alerts at all (anomalies still stored).

#### 7.6.5 Reasons (explainability)

Reasons are generated from the top contributing features — never fixed text. Each reason object: `{ "code": str, "feature": str, "value": number, "reference": number, "message": str }`. Message templates (i18n keys, English shown):

| Code | Template | Example |
|---|---|---|
| `AMOUNT_VS_CATEGORY` | "{ratio}× your typical {category} spending ({typical})" | "4.2× your typical Food & Beverage spending (Rp45.000)" |
| `AMOUNT_PERCENTILE` | "Higher than {pct}% of your {category} transactions" | "Higher than 98% of your Food & Beverage transactions" |
| `AMOUNT_VS_MERCHANT` | "{ratio}× what you usually spend at {merchant}" | |
| `FREQUENCY_BURST` | "{count} {category} transactions in 24 hours (usually about {expected})" | |
| `NEW_MERCHANT` | "First time paying {merchant}, and the amount is high for you" | |
| `CATEGORY_SURGE` | "{category} spending in the last 7 days is {ratio}× your weekly norm" | |
| `LIMITED_HISTORY` | "Based on typical spending for this category (limited personal history)" | |

`typical` = `exp(m)` formatted as IDR. Up to 3 reasons, ordered by contribution. For the model detector, contribution = absolute standardized deviation of each user-relative feature.

#### 7.6.6 Alert budget

- Only `high` severity anomalies with `history_level = personal` (or `medium` for `new_merchant_high_value`) become **alerts** (notification + dashboard card).
- Max **3 alerts per user per budget period**. When the cap is reached, further anomalies are stored and listed in the Intelligence Center but create no notification. The cap is config (`ANOMALY_ALERTS_PER_PERIOD`).
- Never alert for a merchant in `anomaly_suppressions` or for transactions older than 7 days at scoring time (e.g. CSV back-fill); those are stored as `status = historical`.

#### 7.6.7 Anomaly status lifecycle

`open` → `confirmed` | `dismissed`; `historical` (back-filled, informational); `superseded` (transaction edited and re-scored). Only `open` alerts show the action buttons.

### 7.7 FR-07 — Expense forecasting

| ID | Requirement | Priority |
|---|---|---|
| FR-07.01 | Forecast total expenses for the **current budget period** (overall) and per expense category that has ≥ 60 days of history and ≥ 20 transactions | Must (overall) / Should (category) |
| FR-07.02 | Output: `spent_to_date`, `predicted_total` (P50), `interval_low` (P10), `interval_high` (P90), `predicted_remaining`, `method` (`run_rate`, `seasonal_naive`, `model`), `history_level`, `model_version`, `baseline_prediction` (run-rate), `generated_at` | Must |
| FR-07.03 | If a budget exists: `predicted_over_budget = predicted_total − limit` and `exceed_band` ∈ {`low`, `medium`, `high`} (7.7.4) | Must |
| FR-07.04 | Estimated period-end balance = current balance − `predicted_remaining` + expected remaining income (recurring income detected by FR-08 that is due before period end) | Should |
| FR-07.05 | Daily forecast curve for remaining days (P10/P50/P90 per day, cumulative) for the chart | Should |
| FR-07.06 | Forecasts are labeled in the UI as **estimates**, with the range and a "How is this calculated?" popover showing the method and the baseline value | Must |
| FR-07.07 | Forecasts are recomputed by the daily batch (see 15.1) and lazily on request when the cached forecast is older than 6 h **and** the user has added/edited transactions since | Must |

#### 7.7.1 Decomposition

`predicted_total = spent_to_date + expected_recurring_remaining + forecast_nonrecurring_remaining`

- `expected_recurring_remaining`: sum of `expected_amount` of active recurring expenses (FR-08, `confidence ≥ 0.7`) whose `next_expected_date` falls after today and within the period.
- `forecast_nonrecurring_remaining`: sum of daily forecasts of non-recurring spending for the remaining days. Non-recurring = expenses not linked to a recurring series.

This prevents rent on the 1st from inflating the run-rate for the rest of the month.

#### 7.7.2 Methods and minimum history

| History (days with any transactions since first transaction) | Method | `history_level` |
|---|---|---|
| < 14 | Not shown; UI says "Add at least 2 weeks of transactions to see a forecast" | — |
| 14 – 59 | Run-rate on non-recurring + recurring decomposition | `limited` ("rough estimate" label) |
| ≥ 60 | Model (if production model exists and beat baseline) else seasonal naive (same weekday average of last 4 weeks) | `personal` |

Run-rate (baseline): `spent_nonrecurring_to_date / days_elapsed × days_remaining`. Its interval: ± the 10th/90th percentile of historical daily non-recurring spend × days_remaining scaled by √days_remaining (documented heuristic; reported as such).

#### 7.7.3 Model (Tier B)

Global LightGBM trained across users on daily non-recurring spend with lag/calendar features (11.2.3), objective quantile at α = 0.1, 0.5, 0.9 (three models), or Exponential Smoothing per user as a comparison. Recursive multi-step forecasting is NOT used; use direct per-horizon features (`days_ahead`) to avoid error compounding. Quantile crossing is fixed by sorting the three predictions.

#### 7.7.4 Exceed band

Using P10/P50/P90 of `predicted_total` and budget limit *L*:
- `high` if *L* ≤ P50
- `medium` if P50 < *L* ≤ P90
- `low` if *L* > P90

No numeric probabilities are shown (avoids false precision).

### 7.8 FR-08 — Recurring expense detection

| ID | Requirement | Priority |
|---|---|---|
| FR-08.01 | Detect recurring series per user from expenses (and income, for salary/allowance) in the last 400 days | Must |
| FR-08.02 | Series output: `merchant_key`, display name, `category`, `frequency` (`weekly`, `biweekly`, `monthly`, `quarterly`, `yearly`), `median_interval_days`, `expected_amount` (median of last 3), `amount_variability` (CV), `last_date`, `next_expected_date`, `occurrences`, `confidence` ∈ [0,1], `status` (`active`, `paused`, `ended`, `user_confirmed`, `user_rejected`), `transaction_type` | Must |
| FR-08.03 | Flag **amount change** when the latest amount differs from `expected_amount` of the previous occurrences by > 10% and ≥ Rp5.000 → creates an insight (INS-08) | Should |
| FR-08.04 | Dedicated view: list sorted by next due date, monthly-equivalent total ("Your recurring costs ≈ Rp X per month"), upcoming in next 7 days | Must |
| FR-08.05 | User can confirm a series, reject it ("Not recurring" → never suggested again for that merchant_key), or edit expected amount | Should |
| FR-08.06 | Recompute nightly and when a transaction with a known recurring `merchant_key` is added | Should |

**Algorithm (rule-based first; ML only if rules prove insufficient):**
1. Group by (`merchant_key`, `transaction_type`); skip empty keys and groups with < 3 occurrences (< 2 for yearly is not detectable → skip).
2. Sort by date; take intervals in days between consecutive occurrences (same-day duplicates merged).
3. Match median interval to a frequency: weekly 7±1, biweekly 14±2, monthly 30±4 (28–34), quarterly 91±7, yearly 365±10.
4. Regularity: share of intervals within tolerance ≥ 0.7.
5. Amount stability: CV of amounts ≤ 0.25 (subscriptions) — series with higher CV (e.g. transport) are allowed only for weekly frequency and get confidence × 0.7.
6. `confidence = regularity × min(1, occurrences / 4) × (1 if CV ≤ 0.25 else 0.7)`. Show series with confidence ≥ 0.6.
7. `next_expected_date = last_date + median_interval`. Status `paused` if today > next_expected_date + tolerance; `ended` if > 2 × interval overdue.
8. Monthly-equivalent amount: weekly × 52/12, biweekly × 26/12, monthly × 1, quarterly ÷ 3, yearly ÷ 12.

### 7.9 FR-09 — Personalized insights

Insights are **deterministic and rule-based**. No LLM. Each insight MUST be reproducible from its `evidence` payload.

| ID | Requirement | Priority |
|---|---|---|
| FR-09.01 | Generate insights daily per user and on demand (`POST /intelligence/insights/refresh`, rate-limited 1/min) | Must |
| FR-09.02 | Each insight: `rule_id`, `rule_version`, `period_id`, `severity` (`info`, `positive`, `warning`), `title`, `message`, `evidence` (JSON: metric names, values, period boundaries, filters), `created_at`, `dismissed_at` | Must |
| FR-09.03 | One insight per (`rule_id`, period, subject) — upsert, never duplicate | Must |
| FR-09.04 | Users can dismiss an insight; dismissed insights do not reappear for the same subject and period | Should |
| FR-09.05 | Dashboard shows the top 3 insights by priority: warning > positive > info, then by magnitude | Must |

**Rule catalogue (initial):**

| Rule | Trigger (all conditions must hold) | Message template |
|---|---|---|
| INS-01 Category change | Previous period complete; category expense in cur PTD vs same-days prev: \|Δ%\| ≥ 20% **and** \|Δ\| ≥ Rp50.000 **and** prev ≥ Rp100.000 | "Your {category} spending is {up/down} {pct}% compared with the same point last period" |
| INS-02 Weekend vs weekday | ≥ 4 weekends in the last 8 weeks with data; avg daily spend weekend ÷ weekday ≥ 1.3 | "You spend {ratio}× more per day on weekends than on weekdays" |
| INS-03 Recurring share | Active recurring expense series exist; monthly-equivalent recurring ÷ average monthly expenses (last 3 periods) ≥ 10% | "Recurring payments make up {pct}% of your monthly spending (≈{amount})" |
| INS-04 Budget pace | Budget exists; forecast `exceed_band` ∈ {medium, high} | "At your current pace, you may exceed your {budget} budget by about {amount}" |
| INS-05 Top merchant | One merchant ≥ 15% of period expenses and ≥ 5 transactions | "{merchant} accounts for {pct}% of your spending this period ({count} transactions)" |
| INS-06 Small purchases | Transactions < Rp25.000 in the period: count ≥ 15 and sum ≥ 10% of expenses | "{count} small purchases under Rp25.000 added up to {amount} this period" |
| INS-07 Savings rate | Previous period complete with income > 0 | "You saved {pct}% of your income last period" (positive if ≥ 10%, warning if < 0) |
| INS-08 Price change | FR-08.03 amount change detected | "{merchant} charged {new} this time, up from {old}" |
| INS-09 Uncategorized backlog | ≥ 5 transactions in review queue | "{n} transactions need a category — reviewing them improves your insights" |

All thresholds above are config (`config/insights.yaml`) with `rule_version`. Percentages are rounded to integers; amounts formatted as IDR.

### 7.10 FR-10 — Feedback loop

| ID | Requirement | Priority |
|---|---|---|
| FR-10.01 | Store every category change on a model/rule-categorized transaction as `category_feedback`: `transaction_id`, `user_id`, `previous_category`, `new_category`, `previous_status`, `prediction_id`, `model_version`, `created_at`, `feedback_type` (`correction`, `confirmation`, `quick_pick`) | Must |
| FR-10.02 | Store anomaly confirm/dismiss as `anomaly_feedback` with `reason` | Must |
| FR-10.03 | Feedback never triggers immediate retraining | Must |
| FR-10.04 | A feedback item is **eligible for training** only if: user has `training_consent = true`; not reverted within 24 h; it is the latest label for that transaction; the user's labels for that `merchant_key` are consistent (no flip-flop: > 1 distinct category in 7 days → excluded); and per-user contribution is capped at 200 labels per training snapshot (prevents one user dominating / poisoning) | Must |
| FR-10.05 | Eligible feedback is exported daily to BigQuery `curated.category_labels` with a snapshot date; training snapshots reference this table by date | Should |
| FR-10.06 | Feedback statistics (correction rate per category, per model version) feed monitoring (Section 18) | Must |

Note: the public demo uses synthetic data only, so in practice FR-10.04 exports demo/synthetic feedback. The mechanism MUST still be implemented and tested.

### 7.11 FR-11 — Event-driven scoring

| ID | Requirement | Priority |
|---|---|---|
| FR-11.01 | Use the **transactional outbox** pattern: events are inserted into `outbox_events` in the same DB transaction as the change; a relay publishes them | Must |
| FR-11.02 | Relay: polls every 1 s (`SELECT … FOR UPDATE SKIP LOCKED LIMIT 100`), publishes, marks `published_at`. Runs as a background task in the worker service (and in-process in local dev) | Must |
| FR-11.03 | Consumers are idempotent: `processed_events(event_id, consumer)` primary key; duplicate deliveries are acked without reprocessing | Must |
| FR-11.04 | Ordering is not guaranteed. Consumers re-read the current transaction state from the DB and ignore events whose `transaction_version` is older than the stored `transactions.version` | Must |
| FR-11.05 | Retries: Pub/Sub push with exponential backoff (min 10 s, max 600 s), max 5 delivery attempts, then dead-letter topic `transaction-events-dlq`. A DLQ message count > 0 raises an alert | Must |
| FR-11.06 | Local development uses `EVENT_BUS=inmemory` (synchronous in-process dispatch after commit) or `EVENT_BUS=pubsub` with the Pub/Sub emulator in docker compose | Must |

Event schemas: Section 14.3.

### 7.12 FR-12 — ML pipeline, registry, promotion, monitoring

Specified in Sections 16 (MLOps) and 18 (monitoring).

### 7.13 FR-13 — Spending behavior clustering (Tier C)

| ID | Requirement | Priority |
|---|---|---|
| FR-13.01 | Weekly batch assigns each user with ≥ 2 complete periods to a behavior segment | Could |
| FR-13.02 | Features: 11.2.4. Standardized; category shares as compositional data (centered log-ratio transform) | Could |
| FR-13.03 | Segments get human-readable names and descriptions chosen after inspecting centroids (e.g. "Food-heavy frequent spender", "Subscription-heavy", "Steady saver"). Names stored in model metadata, not in code | Could |
| FR-13.04 | UI shows the user's segment and 2–3 defining traits ("You spend more on food delivery than 70% of similar users") — Intelligence Center only | Could |
| FR-13.05 | Report agreement with synthetic archetype labels only as a sanity check (ARI), not as a discovery claim | Must (if FR-13 built) |

### 7.14 FR-14 — In-app notifications

| ID | Requirement | Priority |
|---|---|---|
| FR-14.01 | Notification types: `budget_threshold`, `anomaly_alert`, `import_completed`, `recurring_due_soon` (payment due in ≤ 2 days, once per occurrence), `review_queue` (weekly, if ≥ 5 items) | Must (first two) / Should |
| FR-14.02 | Fields: `id`, `type`, `title`, `body`, `link` (frontend route), `payload` (JSON), `dedupe_key` (unique per user), `read_at`, `created_at` | Must |
| FR-14.03 | Bell icon with unread count; list with mark-as-read and mark-all-read; notifications older than 90 days are deleted by a job | Must |
| FR-14.04 | Frontend polls `GET /notifications/unread-count` every 60 s while the tab is visible (no websockets in this release) | Must |

### 7.15 FR-15 — Merchant rules management

| ID | Requirement | Priority |
|---|---|---|
| FR-15.01 | Settings page lists the user's merchant rules (merchant display name, category, times applied, last applied) | Should |
| FR-15.02 | User can change a rule's category or delete it. Deleting does not change past transactions | Should |
| FR-15.03 | Rules count: max 1,000 per user | Should |

### 7.16 FR-16 — Personal data export

| ID | Requirement | Priority |
|---|---|---|
| FR-16.01 | `GET /users/me/export` returns a ZIP with `transactions.csv`, `budgets.csv`, `profile.json`, generated synchronously for ≤ 50,000 transactions | Could |
| FR-16.02 | CSV cells are formula-injection-safe (7.2.3) | Must (if built) |

---

## 8. User experience and frontend specification

### 8.1 Pages and routes

| Route | Page | Auth | Main content |
|---|---|---|---|
| `/` | Landing | No | One-paragraph pitch, screenshot, "Try the demo" (logs in as demo user), Register, Login |
| `/register`, `/login` | Auth | No | Forms with inline validation |
| `/dashboard` | Dashboard | Yes | Balance, income, expenses, net, budget progress, category donut, daily trend with budget pace, period comparison, top merchants, top 3 insights, review-queue badge, active alerts |
| `/transactions` | Transactions | Yes | Filterable table (FR-02.02), add/edit drawer, bulk actions, review queue tab, duplicate banner |
| `/transactions/import` | CSV import | Yes | Upload → preview table with per-row status/errors and predicted categories (editable) → commit options → result summary |
| `/budgets` | Budgets | Yes | Overall + category budgets with utilization bar colored by status, projected status, thresholds editor, history (snapshots) |
| `/intelligence` | Intelligence Center | Yes | Tabs: Alerts (anomalies), Forecast (chart with range + method popover), Recurring, Insights, Segment (Tier C) |
| `/settings` | Settings | Yes | Profile, budget period start day, timezone, training consent toggle (explains what it means), merchant rules, export data, change password, delete account |
| `/notifications` | Notifications | Yes | Full list |

### 8.2 UX rules

- Every page has explicit **loading** (skeletons), **empty**, and **error** states. Error state shows `request_id` (from the API error) with a "Copy" button.
- Responsive from 360 px; the transaction table collapses into cards on mobile.
- Accessibility: WCAG 2.1 AA contrast, keyboard navigable forms, labels on all inputs, charts have a textual summary and a data table toggle. Status is never conveyed by color alone (icon + text: Healthy / Normal / Warning / Exceeded).
- Money input: accepts `25000` or `25.000`; shows formatted preview `Rp25.000`.
- Date input defaults to "now" in user tz; time optional (sets `has_time`).
- The add-transaction form shows the live categorization preview (FR-03.07) as a chip: "Food & Beverage · auto" or "Suggest: Groceries? (or choose)" with quick picks.
- Forecast and anomaly UI always show the method/model and a short "why" text; forecasts always show a range.
- Copy for estimates: "Estimate — not a guarantee".
- UI strings live in `frontend/src/messages/en.json` (i18n-ready; Indonesian later).
- Numbers use `Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 })`.

### 8.3 Frontend technical requirements

- Next.js (App Router) + TypeScript `strict`. Tailwind CSS + shadcn/ui components. TanStack Query for server state. React Hook Form + Zod for forms. Recharts for charts.
- API client generated from the backend OpenAPI (`openapi-typescript` + a thin fetch wrapper). Regeneration is a `make` target and checked in CI (diff must be empty).
- Access token kept **in memory only** (not localStorage). On 401, call refresh once, then retry; on refresh failure redirect to `/login`.
- The browser calls **same-origin** `/api/v1/*`; Next.js `rewrites` proxy these to `BACKEND_INTERNAL_URL`. Reason: frontend and backend run on different `*.run.app` hosts, which are different *sites*, so a `SameSite=Strict` refresh cookie would never be sent cross-origin. Same-origin proxying keeps the cookie working and removes the need for CORS. (If a custom domain with `app.` and `api.` subdomains is used later, this can change via ADR.)
- The backend still enforces CORS with an explicit allow-list (`CORS_ORIGINS`) for direct API use in development.
- Lint: ESLint + Prettier; tests: Vitest + Testing Library for components; Playwright for 3 E2E flows (register→add transaction→see dashboard; CSV import preview→commit; correct a category→rule applied to next transaction).

---

## 9. Machine learning design

### 9.1 Principle: baseline first, complex models must prove themselves

Every model has a simple baseline, stronger candidates, and a **written decision rule** decided before training. Candidates that lose to the baseline are documented as negative results in `MODEL_EVALUATION.md` — that is evidence of good judgment, not failure.

| Model | Baseline | Candidates | Ship rule |
|---|---|---|---|
| Transaction classifier | TF-IDF char 2–5-gram + word 1–2-gram on description and merchant + Logistic Regression (multinomial, `class_weight='balanced'`) | Calibrated Linear SVM; LightGBM on TF-IDF + numeric features; fine-tuned IndoBERT (`indobenchmark/indobert-base-p1` or a smaller distilled variant) in PyTorch | Macro F1 ≥ baseline + 2.0 points **and** P95 latency within SLO on the standard benchmark (16.3) |
| Anomaly detector | Robust modified z-score per user × category (7.6.2) | Isolation Forest, Local Outlier Factor on user-relative features | Precision@recall≥0.50 higher than baseline on the labeled synthetic test set |
| Forecaster | Run-rate; seasonal naive (same weekday, last 4 weeks) | Exponential Smoothing (per user, statsmodels); global LightGBM quantile | WAPE lower than run-rate at forecast days 5, 10, 15, and 20 **and** P10–P90 coverage within 70–90% |
| Behavior clusterer | K-Means, k ∈ 3..8 chosen by silhouette | Gaussian Mixture, DBSCAN | Silhouette ≥ 0.40, ARI across 5 seeds ≥ 0.80, segments nameable |

### 9.2 Model 1 — transaction classifier

- **Input**: `description`, `merchant`, `amount`, `payment_method`, `transaction_type`, local hour (if `has_time`), weekday.
- **Output**: probability over the 19 model labels (all slugs in 4.6 except `uncategorized`).
- **Why linear first**: descriptions are short, noisy, merchant-heavy; char n-gram TF-IDF is usually hard to beat and fast on CPU.
- **Calibration**: fit on the validation split with isotonic regression (one-vs-rest, then renormalize) or temperature scaling for the transformer. Report **expected calibration error** (ECE, 15 bins) before and after. Runtime confidence is always the calibrated top-1 probability.
- **Evaluation** (on locked temporal test and on unseen-merchant test): macro F1, weighted F1, per-class precision/recall, confusion matrix, **coverage–accuracy curve** (share auto-applied vs. precision as `t_high` varies), F1 on merchants unseen in training, ECE, and an error analysis of the 50 most confident mistakes.
- **IndoBERT experiment** (Tier C): same splits; report macro F1, CPU P95 latency on Cloud Run (2 vCPU), image size, RAM, cold start, and estimated monthly cost. Ship only by the rule in 9.1; report results regardless of decision. ONNX export + dynamic int8 quantization MAY be tried to meet latency.
- **Type consistency** is enforced after prediction (FR-03.10), not inside the model.

### 9.3 Model 2 — anomaly detector

- Data per user is small, so one model is trained **across users** on features **relative to each user's own history** (11.2.2).
- Labels from the generator are used **only for evaluation**, never for training the unsupervised model.
- Metrics: PR-AUC, precision at recall ≥ 0.50, recall per anomaly type, false positives per user per period (product metric; target ≤ 3), and the same metrics restricted to users with limited history.

### 9.4 Model 3 — forecaster

- Target: daily non-recurring expense total per user (7.7.1).
- Evaluation: rolling-origin per user (10.4). Metrics at forecast origin days 5/10/15/20 of each period: WAPE and MAE of the period total, MASE (scaled by seasonal-naive in-sample MAE, m = 7), and P10–P90 interval coverage. Report by archetype.

### 9.5 Model 4 — behavior clustering

- Features: 11.2.4. Choose k by silhouette on 3..8; stability by ARI across 5 seeds and across a 50/50 user split.
- Because synthetic users come from archetypes, clusters will tend to recover archetypes. Report ARI vs. archetype only as a sanity check.

### 9.6 Shared evaluation protocol

1. Fixed seeds; every run logs to MLflow with dataset version (hash), feature version, config, git commit.
2. Metrics reported overall **and** per archetype and per category (slices).
3. Every model has a model card (`docs/model_cards/<model>.md`, template in Appendix D).
4. `MODEL_EVALUATION.md` contains negative results and decisions, not only the winner.
5. Results on synthetic data and on any public dataset are reported **separately**, with limitations.
6. **Circularity check**: evaluate on a generator variant not used for training (different merchant list subset, noise level ×2, different seed and archetype mix — `config/generator/holdout_variant.yaml`). Report the drop.

---

## 10. Data

### 10.1 Synthetic transaction generator (`data_generator/`)

Primary data source. Real personal financial data MUST NOT be used; public Indonesian daily-transaction datasets are scarce. Public datasets are used only for comparison.

**Interface**

```bash
python -m data_generator generate --config config/generator/default.yaml --seed 42 --out data/synthetic/v1
```

Output (MUST be byte-identical for the same config + seed + generator version):
- `transactions.parquet` and `transactions.csv` with the **same columns as the product CSV import** plus: `transaction_id`, `user_id`, `archetype`, `true_category`, `true_merchant`, `is_anomaly`, `anomaly_type`, `anomaly_severity`, `recurring_series_id`, `has_time`.
- `users.parquet`: `user_id`, `archetype`, `income_profile`, `budget_period_start_day`, `created_at`.
- `manifest.json`: generator version, git commit, config (inlined), seed, row counts, SHA-256 of every output file.

**Specification**

| Component | Specification |
|---|---|
| Users | Default 2,000 users × 12 months. Archetype mix: student 35%, young professional 35%, freelancer 10%, impulsive spender 10%, subscription-heavy 10% |
| Income | Student: allowance ~Rp1.500.000 (σ 15%) on day 1 ± 1; Professional: salary ~Rp7.000.000 (σ 25%) on day 25 ± 1 (moves earlier if weekend); Freelancer: 1–4 irregular payments/month, log-normal amounts |
| Expenses | Category shares per archetype (YAML); daily transaction count ~ Poisson(λ_archetype × weekday_factor × payday_factor × end_of_period_factor); amount ~ log-normal per (archetype, category) |
| Time patterns | Weekend factor (food/entertainment ×1.4), payday effect (×1.5 spending in 3 days after income), end-of-period tightening (×0.7 in last 5 days for students), Ramadan/holiday factors optional (`calendar_effects: true`) |
| Time of day | Per-category hour distributions (lunch peak 11–13, dinner 18–20, commute 7–9 and 17–19); 15% of rows `has_time = false` |
| Merchants | `config/generator/merchants.yaml`: ≥ 15 merchants per category with popularity weights; each user samples a personal favourite subset (habit) |
| Text noise | Random case, typos (1 char edit, 5%), payment prefixes (`QRIS`, `POS`, `GOPAY*`), reference numbers, location suffixes (`- JKT SELATAN`), abbreviations (`indomrt`, `kpi knngn`) |
| Ambiguity | ~5% of descriptions intentionally ambiguous (e.g. Indomaret purchase labelled `groceries` vs `personal_care`; Shopee as `shopping` vs `food_beverage` for ShopeeFood) |
| Transfers | Top-ups to e-wallets 1–4 times/month (`transfer`) |
| Subscriptions | Fixed amount, monthly interval with 0–3 day jitter, 5% chance of price change per year, some cancelled mid-year |
| Labeled anomalies | Rate 1% of expense rows (config): `amount_spike` (×4–×15 of user typical), `frequency_burst` (4–8 extra transactions in 24 h), `new_merchant_high_value`, `category_surge` (7-day ×2.5–4); each with `anomaly_type` and severity |
| Duplicates | 0.3% exact duplicates injected to test FR-02.12 |
| Validation | Generator runs Pandera schema checks on its own output and fails on violation |

Example archetype config (initial values for the generator, **not** real behavioural statistics — the evaluation report MUST say so):

```yaml
archetype: student
weight: 0.35
monthly_income:
  kind: allowance
  amount: 1500000
  sigma_pct: 0.15
  day_of_month: 1
  jitter_days: 1
daily_tx_lambda: 2.2
category_share:
  food_beverage: 0.38
  transportation: 0.16
  entertainment: 0.12
  groceries: 0.14
  utilities: 0.08
  other_expense: 0.12
subscriptions: [streaming_video, music]
anomalies:
  rate: 0.01
  types: [amount_spike, frequency_burst, new_merchant_high_value, category_surge]
```

### 10.2 Public datasets

- Search Kaggle, UCI, and Hugging Face for transaction-description categorization and personal-finance datasets. Record source URL, license, size, language, label set, and limitations in `docs/DATA_SOURCES.md` **before** using any dataset.
- Only datasets whose license permits the intended use (including public portfolio display of derived metrics) are used.
- Map external labels to the taxonomy with an explicit mapping file (`config/label_maps/<dataset>.yaml`); unmapped labels are dropped and counted.
- Credit-card fraud data (e.g. ULB) MAY be used only to practice anomaly-detection techniques. It is **not** ground truth for unusual personal spending (fraud ≠ personal anomaly).
- Decision on which public dataset to use for generalization testing is made in Week 1 after EDA (Open question Q1).

### 10.3 Data validation

- API: Pydantic models (strict types) for every request.
- Pipeline: Pandera schemas in `ml/schemas/` for raw, curated, and feature tables. Checks: types, non-null, ranges (amount > 0), allowed enums, date bounds, category share sanity (no category > 80% of all rows), duplicate primary keys.
- Invalid rows go to a **quarantine** table/file with the failing check name — never silently dropped. Gate fails if quarantine > 1% (16.3).

### 10.4 Split protocol (locked before modeling)

Leakage is the largest evaluation risk. Splits are defined in `ml/evaluation/splits.py`, persisted as ID lists in `data_splits/<dataset_version>/` (committed) with a hash, and MUST NOT change after Week 1 without an ADR.

| Model | Split | Reason |
|---|---|---|
| Classifier | Per user, temporal: first 70% of each user's transactions → train, next 15% → validation, last 15% → test. Plus **unseen-merchant test**: hold out 15% of merchant_keys entirely (all their rows go to a separate test set) | Measures performance on future time and new merchants |
| Classifier (public data) | As provided, else stratified 70/15/15 | |
| Anomaly | Per user temporal (same cut points); labels only in evaluation | Unsupervised model must not see labels |
| Forecaster | Rolling-origin per user: origins at day 5/10/15/20 of each of the last 4 periods; train on all data strictly before origin | Mimics production usage |
| Clustering | 50/50 split **by user** for stability | Tests segment consistency |
| Generator holdout variant | Separate generated dataset, evaluation only | Circularity check (9.6, item 6) |

Global rule: **no user's future data may inform any feature used for that user's past** (point-in-time correctness, 11.1).

### 10.5 Storage layout

| Store | Content |
|---|---|
| Cloud SQL (PostgreSQL 16) | Product data (Section 12) |
| BigQuery dataset `raw` | Daily export of transactions (pseudonymized: `user_id` → HMAC-SHA256 with `EXPORT_PSEUDONYM_KEY`), synthetic datasets loaded from GCS |
| BigQuery `curated` | Cleaned tables, `category_labels` (eligible feedback), `anomaly_labels` |
| BigQuery `features` | Batch feature tables keyed by (`user_pseudo_id`, `transaction_id` or `date`, `feature_version`) |
| BigQuery `predictions` | Prediction logs via Cloud Logging sink (18.4) |
| Cloud Storage `gs://<project>-datasets` | Versioned synthetic datasets (`synthetic/v{n}/…` + manifest) |
| Cloud Storage `gs://<project>-mlflow` | MLflow artifacts (models, reports, plots) |
| Local equivalents | `data/` (gitignored) with Parquet files; DuckDB used to run the same SQL locally (`DATA_BACKEND=local`) |

Partitioning: BigQuery tables partitioned by `DATE(transaction_date)` (or `date`), clustered by `user_pseudo_id`. Table expiration for `raw` exports: 400 days.

---

## 11. Features and model artifacts

### 11.1 Rules

1. **One feature module** (`ml/preprocessing/` and `ml/features/`) is used by the training pipeline, by the backend (online features), and nowhere else duplicated.
2. **Point-in-time correctness**: every feature function takes `as_of: datetime` and the user's history, and MUST use only rows with `transaction_date < as_of` (strictly before; ties broken by `created_at`). A unit test injects future rows and asserts features are unchanged.
3. **Parity test**: for a fixed sample of transactions, batch features (pandas/SQL path) and online features (backend path) MUST match within 1e-6 (floats) / exactly (categoricals). Failing parity fails CI.
4. **Feature version**: `FEATURE_VERSION` constant (e.g. `features-1`) is bumped whenever any feature's semantics change. It is saved with each model; the ML service rejects requests whose `feature_version` differs from the loaded model's with 409 `FEATURE_VERSION_MISMATCH`.
5. Online feature computation in the backend uses the user's last 500 expense transactions (or 180 days, whichever is smaller) loaded with a single indexed query, cached in Redis (`feat:{user_id}:{category}` TTL 10 min, invalidated on any write by that user).

### 11.2 Feature definitions

#### 11.2.1 Classifier

| Feature | Definition |
|---|---|
| `desc_char_tfidf` | char_wb 2–5-gram TF-IDF of `preprocess_description(description)`; min_df 2; max_features 100k; sublinear tf |
| `desc_word_tfidf` | word 1–2-gram TF-IDF, same text |
| `merchant_char_tfidf` | char 2–4-gram TF-IDF of `merchant_key` |
| `log_amount` | `log1p(amount)` standardized |
| `payment_method` | one-hot |
| `transaction_type` | one-hot |
| `hour_bucket` | one-hot of {night 0–5, morning 6–10, midday 11–14, afternoon 15–17, evening 18–23, unknown} |
| `is_weekend` | 0/1 |

Leakage guard: no features derived from other users' labels on the same merchant during the test period.

#### 11.2.2 Anomaly

All computed from the user's history strictly before the transaction.

| Feature | Definition |
|---|---|
| `z_cat` | Modified z-score of log amount vs user's category history (7.6.2) |
| `z_merchant` | Same vs user's history at this `merchant_key` (NaN → 0 + `merchant_seen=0`) |
| `pct_rank_cat` | Percentile rank of amount within user's category history |
| `ratio_to_cat_median` | amount ÷ median category amount |
| `merchant_seen` | 0/1 |
| `merchant_count_180d` | count of prior transactions at merchant |
| `cat_count_24h`, `cat_count_7d` | counts in category in windows ending at the transaction |
| `cat_rate_56d` | mean daily count in category over prior 56 days |
| `cat_spend_7d_ratio` | category spend last 7 days ÷ median weekly spend previous 8 weeks |
| `hour_sin`, `hour_cos`, `hour_known` | cyclic hour; 0/0/0 if `has_time=false` |
| `dow_sin`, `dow_cos` | cyclic weekday |
| `days_since_income` | days since last income transaction |
| `history_n_cat` | number of prior transactions in category (for cold-start logic) |

#### 11.2.3 Forecasting

Per (user, local date): `y` = non-recurring expense total.

| Feature | Definition |
|---|---|
| `dow`, `dom`, `days_to_period_end`, `days_since_period_start` | calendar |
| `is_weekend`, `is_holiday` | holiday from a bundled Indonesian national holiday list for 2025–2027 (`config/holidays_id.yaml`); `is_holiday` only if the list covers the date, else 0 and `holiday_known=0` |
| `days_since_income` | |
| `lag_1, lag_7, lag_14, lag_28` | y shifted by k days (as of the forecast origin; for horizon h use lags ≥ h or origin-anchored values) |
| `roll_mean_7, roll_mean_28, roll_std_28` | computed up to the origin date, shifted by 1 day |
| `ptd_spend_ratio` | spent PTD ÷ average period spend (last 3 periods) |
| `days_ahead` | horizon h (direct multi-horizon model) |
| `archetype_prior` | **not used in production** (archetype is unknown for real users); only for analysis |

#### 11.2.4 Clustering (per user, last 3 complete periods)

`avg_tx_amount`, `monthly_expense`, `tx_per_day`, `category_share_*` (CLR-transformed), `weekend_spend_ratio`, `recurring_ratio`, `small_tx_ratio` (< Rp25.000), `income_regularity` (CV of income intervals), `savings_rate`.

### 11.3 Model artifact format

Each registered model version in MLflow contains:

```text
model/                      # MLflow pyfunc or sklearn flavor
metadata.json               # see 11.6
signature                   # MLflow input/output schema
requirements.txt            # pinned
evaluation/report.json      # all metrics incl. slices
evaluation/report.md        # human-readable
evaluation/plots/*.png      # confusion matrix, calibration, PR curve, coverage curve
model_card.md
data_manifest.json          # dataset version + hashes + split hash
```

### 11.4 Artifact integrity

- `metadata.json` includes SHA-256 of the serialized model file(s). The ML service verifies hashes at load; mismatch → refuse to load, `/readyz` stays 503, alert fires.
- Pickle/joblib artifacts are loaded only from the project's own GCS bucket / MLflow store (trusted origin). Transformer models use `safetensors`.

### 11.5 Model loading in the ML service

- At startup, resolve `models:/<name>@production` (and `@candidate` if `SHADOW_ENABLED=true`) from MLflow, download to local disk, verify, load into memory. `/readyz` returns 200 only when all **required** models are loaded (classifier required; others optional — endpoints return 503 `MODEL_NOT_AVAILABLE` if their model is missing).
- Poll MLflow every `MODEL_POLL_INTERVAL_S` (default 300 s); if the `production` alias points to a new version, load it in the background and swap atomically. Keep the previous version in memory until the swap completes.
- `GET /v1/models` lists loaded models, versions, aliases, loaded_at, feature_version, thresholds.
- For local dev without MLflow, `MODEL_SOURCE=local_dir` loads from `models/` (gitignored), produced by `make train-local`.

### 11.6 `metadata.json` (per model version)

```json
{
  "model_name": "transaction-classifier",
  "mlflow_version": "7",
  "semantic_version": "1.2.0",
  "feature_version": "features-1",
  "taxonomy_version": "taxonomy-1",
  "trained_at": "2026-12-01T03:00:00Z",
  "git_commit": "abc1234",
  "dataset": { "name": "synthetic", "version": "v3", "sha256": "…", "split_hash": "…" },
  "decision_thresholds": { "t_high": 0.87, "t_low": 0.58, "calibration": "isotonic" },
  "labels": ["food_beverage", "groceries", "…"],
  "metrics": { "macro_f1_test": 0.0, "ece_test": 0.0 },
  "priors": null,
  "artifact_sha256": { "model.joblib": "…" },
  "runtime": { "python": "3.12", "sklearn": "x.y.z" }
}
```

For the anomaly detector, `priors` holds per-category global median/MAD (cold start) and the score-to-[0,1] mapping; `decision_thresholds` holds the flag threshold and severity cut points. For clustering, `segments` maps cluster IDs to names/descriptions. Metric values above are placeholders — never copy them into docs.

---

## 12. Database design (PostgreSQL)

### 12.1 Conventions

- Migrations with Alembic only; never edit the DB by hand. Each migration is reversible (`downgrade` implemented) unless an ADR says otherwise.
- All user-owned tables have `user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE` and an index starting with `user_id`.
- Original user data and derived ML outputs live in separate tables (`transactions` vs `category_predictions`, `anomalies`, `forecasts`, …).
- `version INTEGER NOT NULL DEFAULT 1` on `transactions` (incremented on update) for event ordering (FR-11.04) and optimistic concurrency (`If-Match` optional).
- `updated_at` maintained by the application layer (not triggers) for testability.

### 12.2 Schema (DDL sketch — the Alembic migration is authoritative once written)

```sql
CREATE TABLE users (
  id UUID PRIMARY KEY,
  email TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  display_name TEXT NOT NULL CHECK (char_length(display_name) BETWEEN 1 AND 60),
  currency TEXT NOT NULL DEFAULT 'IDR' CHECK (currency = 'IDR'),
  timezone TEXT NOT NULL DEFAULT 'Asia/Jakarta',
  locale TEXT NOT NULL DEFAULT 'en' CHECK (locale IN ('en','id')),
  budget_period_start_day SMALLINT NOT NULL DEFAULT 1 CHECK (budget_period_start_day BETWEEN 1 AND 28),
  pending_period_start_day SMALLINT NULL CHECK (pending_period_start_day BETWEEN 1 AND 28),
  pending_period_start_effective DATE NULL,
  opening_balance NUMERIC(15,2) NOT NULL DEFAULT 0,
  training_consent BOOLEAN NOT NULL DEFAULT FALSE,
  is_demo BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL
);
CREATE UNIQUE INDEX ux_users_email ON users (lower(email));

CREATE TABLE refresh_tokens (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  family_id UUID NOT NULL,
  token_hash TEXT NOT NULL UNIQUE,          -- SHA-256 of the opaque token
  replaced_by UUID NULL,
  revoked_at TIMESTAMPTZ NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL,
  user_agent_hash TEXT NULL
);
CREATE INDEX ix_refresh_user ON refresh_tokens (user_id);
CREATE INDEX ix_refresh_family ON refresh_tokens (family_id);

CREATE TABLE categories (
  id UUID PRIMARY KEY,
  slug TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  transaction_type TEXT NOT NULL CHECK (transaction_type IN ('income','expense','transfer','any')),
  is_model_label BOOLEAN NOT NULL DEFAULT TRUE,
  sort_order SMALLINT NOT NULL
);  -- seeded by migration; uncategorized has transaction_type='any', is_model_label=false

CREATE TABLE transaction_imports (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  status TEXT NOT NULL CHECK (status IN ('previewed','committed','failed','expired')),
  file_sha256 TEXT NOT NULL,
  original_filename TEXT NOT NULL,          -- sanitized, ≤ 255 chars
  row_count INTEGER NOT NULL,
  valid_count INTEGER NOT NULL,
  invalid_count INTEGER NOT NULL,
  duplicate_count INTEGER NOT NULL,
  staged_rows JSONB NOT NULL,               -- normalized rows + per-row status/errors/predictions; cleared after commit/expiry
  committed_count INTEGER NULL,
  commit_mode TEXT NULL CHECK (commit_mode IN ('strict','skip_invalid')),
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL,
  committed_at TIMESTAMPTZ NULL
);
CREATE INDEX ix_imports_user ON transaction_imports (user_id, created_at DESC);
CREATE INDEX ix_imports_sha ON transaction_imports (user_id, file_sha256);

CREATE TABLE transactions (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  transaction_type TEXT NOT NULL CHECK (transaction_type IN ('income','expense','transfer')),
  amount NUMERIC(15,2) NOT NULL CHECK (amount > 0),
  description TEXT NOT NULL CHECK (char_length(description) BETWEEN 1 AND 200),
  merchant TEXT NULL CHECK (char_length(merchant) <= 100),
  merchant_key TEXT NOT NULL DEFAULT '',
  transaction_date TIMESTAMPTZ NOT NULL,
  has_time BOOLEAN NOT NULL DEFAULT TRUE,
  payment_method TEXT NOT NULL DEFAULT 'other'
    CHECK (payment_method IN ('cash','bank_transfer','debit_card','credit_card','e_wallet','qris','other')),
  category_id UUID NOT NULL REFERENCES categories(id),
  category_status TEXT NOT NULL
    CHECK (category_status IN ('auto','suggested','needs_review','rule','user_set','user_confirmed')),
  notes TEXT NULL CHECK (char_length(notes) <= 500),
  source TEXT NOT NULL CHECK (source IN ('manual','csv','demo_seed')),
  import_id UUID NULL REFERENCES transaction_imports(id) ON DELETE SET NULL,
  possible_duplicate_of UUID NULL REFERENCES transactions(id) ON DELETE SET NULL,
  duplicate_dismissed BOOLEAN NOT NULL DEFAULT FALSE,
  version INTEGER NOT NULL DEFAULT 1,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX ix_tx_user_date ON transactions (user_id, transaction_date DESC, id DESC);
CREATE INDEX ix_tx_user_cat_date ON transactions (user_id, category_id, transaction_date DESC);
CREATE INDEX ix_tx_user_merchant ON transactions (user_id, merchant_key, transaction_date DESC);
CREATE INDEX ix_tx_user_status ON transactions (user_id, category_status) WHERE category_status IN ('suggested','needs_review');
CREATE INDEX ix_tx_dup_lookup ON transactions (user_id, transaction_type, amount, merchant_key, transaction_date);

CREATE TABLE category_predictions (
  id UUID PRIMARY KEY,
  transaction_id UUID NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  source TEXT NOT NULL CHECK (source IN ('model','user_rule','fallback')),
  predicted_category_id UUID NOT NULL REFERENCES categories(id),
  confidence NUMERIC(5,4) NULL,
  decision TEXT NOT NULL CHECK (decision IN ('auto_apply','suggest','needs_review')),
  alternatives JSONB NOT NULL DEFAULT '[]',
  model_version TEXT NULL,
  feature_version TEXT NULL,
  latency_ms INTEGER NULL,
  ml_error TEXT NULL,                        -- 'timeout','unavailable','circuit_open', ...
  request_id TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX ix_pred_tx ON category_predictions (transaction_id, created_at DESC);
CREATE INDEX ix_pred_user ON category_predictions (user_id, created_at DESC);

CREATE TABLE merchant_rules (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  merchant_key TEXT NOT NULL CHECK (merchant_key <> ''),
  merchant_display TEXT NOT NULL,
  category_id UUID NOT NULL REFERENCES categories(id),
  times_applied INTEGER NOT NULL DEFAULT 0,
  last_applied_at TIMESTAMPTZ NULL,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL,
  UNIQUE (user_id, merchant_key)
);

CREATE TABLE category_feedback (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  transaction_id UUID NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
  prediction_id UUID NULL REFERENCES category_predictions(id) ON DELETE SET NULL,
  previous_category_id UUID NOT NULL REFERENCES categories(id),
  new_category_id UUID NOT NULL REFERENCES categories(id),
  previous_status TEXT NOT NULL,
  feedback_type TEXT NOT NULL CHECK (feedback_type IN ('correction','confirmation','quick_pick')),
  model_version TEXT NULL,
  merchant_key TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX ix_cfb_user ON category_feedback (user_id, created_at DESC);
CREATE INDEX ix_cfb_tx ON category_feedback (transaction_id, created_at DESC);

CREATE TABLE budgets (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  category_id UUID NULL REFERENCES categories(id),   -- NULL = overall
  limit_amount NUMERIC(15,2) NOT NULL CHECK (limit_amount > 0),
  alert_thresholds SMALLINT[] NOT NULL DEFAULT '{80,100}',
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL
);
CREATE UNIQUE INDEX ux_budget_user_cat ON budgets (user_id, COALESCE(category_id, '00000000-0000-0000-0000-000000000000'::uuid));

CREATE TABLE budget_period_snapshots (
  budget_id UUID NOT NULL REFERENCES budgets(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  period_id DATE NOT NULL,
  limit_amount NUMERIC(15,2) NOT NULL,
  spent NUMERIC(15,2) NOT NULL,
  utilization NUMERIC(7,4) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (budget_id, period_id)
);

CREATE TABLE anomalies (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  transaction_id UUID NULL REFERENCES transactions(id) ON DELETE CASCADE,  -- NULL for category_surge
  category_id UUID NULL REFERENCES categories(id),
  anomaly_type TEXT NOT NULL CHECK (anomaly_type IN ('amount_spike','frequency_burst','new_merchant_high_value','category_surge','amount_low')),
  anomaly_score NUMERIC(5,4) NOT NULL,
  severity TEXT NOT NULL CHECK (severity IN ('low','medium','high')),
  is_alert BOOLEAN NOT NULL DEFAULT FALSE,
  status TEXT NOT NULL CHECK (status IN ('open','confirmed','dismissed','historical','superseded')),
  history_level TEXT NOT NULL CHECK (history_level IN ('personal','limited')),
  reasons JSONB NOT NULL,
  model_version TEXT NOT NULL,
  feature_version TEXT NOT NULL,
  period_id DATE NOT NULL,
  transaction_version INTEGER NULL,
  feedback_reason TEXT NULL CHECK (feedback_reason IN ('expected_purchase','wrong_amount','not_mine','other')),
  feedback_at TIMESTAMPTZ NULL,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL
);
CREATE UNIQUE INDEX ux_anom_tx_type ON anomalies (transaction_id, anomaly_type) WHERE transaction_id IS NOT NULL AND status <> 'superseded';
CREATE UNIQUE INDEX ux_anom_surge_open ON anomalies (user_id, category_id) WHERE anomaly_type = 'category_surge' AND status = 'open';
CREATE INDEX ix_anom_user ON anomalies (user_id, created_at DESC);
CREATE INDEX ix_anom_alerts ON anomalies (user_id, period_id) WHERE is_alert;

CREATE TABLE anomaly_suppressions (
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  merchant_key TEXT NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (user_id, merchant_key)
);

CREATE TABLE forecasts (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  period_id DATE NOT NULL,
  category_id UUID NULL REFERENCES categories(id),   -- NULL = overall
  as_of TIMESTAMPTZ NOT NULL,
  spent_to_date NUMERIC(15,2) NOT NULL,
  predicted_total NUMERIC(15,2) NOT NULL,
  interval_low NUMERIC(15,2) NOT NULL,
  interval_high NUMERIC(15,2) NOT NULL,
  baseline_prediction NUMERIC(15,2) NOT NULL,
  expected_recurring_remaining NUMERIC(15,2) NOT NULL DEFAULT 0,
  method TEXT NOT NULL CHECK (method IN ('run_rate','seasonal_naive','model')),
  history_level TEXT NOT NULL CHECK (history_level IN ('personal','limited')),
  daily_curve JSONB NOT NULL DEFAULT '[]',
  model_version TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX ix_fc_lookup ON forecasts (user_id, period_id, category_id, as_of DESC);
-- Keep the latest 30 forecasts per (user, period, category); older ones pruned by job.
-- Period-close job writes actual totals to forecast_outcomes for monitoring.

CREATE TABLE forecast_outcomes (
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  period_id DATE NOT NULL,
  category_id UUID NULL,
  forecast_day SMALLINT NOT NULL,              -- 5,10,15,20
  predicted_total NUMERIC(15,2) NOT NULL,
  baseline_prediction NUMERIC(15,2) NOT NULL,
  actual_total NUMERIC(15,2) NOT NULL,
  model_version TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL
);
CREATE UNIQUE INDEX ux_fc_outcome ON forecast_outcomes (user_id, period_id, COALESCE(category_id,'00000000-0000-0000-0000-000000000000'::uuid), forecast_day);

CREATE TABLE recurring_series (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  merchant_key TEXT NOT NULL,
  merchant_display TEXT NOT NULL,
  transaction_type TEXT NOT NULL CHECK (transaction_type IN ('income','expense')),
  category_id UUID NOT NULL REFERENCES categories(id),
  frequency TEXT NOT NULL CHECK (frequency IN ('weekly','biweekly','monthly','quarterly','yearly')),
  median_interval_days NUMERIC(6,2) NOT NULL,
  expected_amount NUMERIC(15,2) NOT NULL,
  amount_cv NUMERIC(6,4) NOT NULL,
  last_date DATE NOT NULL,
  next_expected_date DATE NOT NULL,
  occurrences INTEGER NOT NULL,
  confidence NUMERIC(4,3) NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('active','paused','ended','user_confirmed','user_rejected')),
  user_expected_amount NUMERIC(15,2) NULL,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL,
  UNIQUE (user_id, merchant_key, transaction_type)
);
CREATE TABLE recurring_series_transactions (
  series_id UUID NOT NULL REFERENCES recurring_series(id) ON DELETE CASCADE,
  transaction_id UUID NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
  PRIMARY KEY (series_id, transaction_id)
);

CREATE TABLE insights (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  rule_id TEXT NOT NULL,
  rule_version TEXT NOT NULL,
  period_id DATE NOT NULL,
  subject_key TEXT NOT NULL DEFAULT '',        -- e.g. category slug or merchant_key
  severity TEXT NOT NULL CHECK (severity IN ('info','positive','warning')),
  priority NUMERIC(8,4) NOT NULL,
  title TEXT NOT NULL,
  message TEXT NOT NULL,
  message_key TEXT NOT NULL,                   -- i18n key
  message_params JSONB NOT NULL,
  evidence JSONB NOT NULL,
  dismissed_at TIMESTAMPTZ NULL,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL,
  UNIQUE (user_id, rule_id, period_id, subject_key)
);

CREATE TABLE user_segments (
  user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  segment_id TEXT NOT NULL,
  traits JSONB NOT NULL,
  model_version TEXT NOT NULL,
  computed_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE notifications (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  type TEXT NOT NULL CHECK (type IN ('budget_threshold','anomaly_alert','import_completed','recurring_due_soon','review_queue')),
  title TEXT NOT NULL,
  body TEXT NOT NULL,
  link TEXT NULL,
  payload JSONB NOT NULL DEFAULT '{}',
  dedupe_key TEXT NOT NULL,
  read_at TIMESTAMPTZ NULL,
  created_at TIMESTAMPTZ NOT NULL,
  UNIQUE (user_id, dedupe_key)
);
CREATE INDEX ix_notif_unread ON notifications (user_id, created_at DESC) WHERE read_at IS NULL;

CREATE TABLE idempotency_keys (
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  key TEXT NOT NULL CHECK (char_length(key) BETWEEN 8 AND 128),
  method TEXT NOT NULL,
  path TEXT NOT NULL,
  request_hash TEXT NOT NULL,
  response_status SMALLINT NULL,
  response_body JSONB NULL,
  created_at TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (user_id, key)
);   -- rows older than 24 h deleted by job

CREATE TABLE outbox_events (
  id UUID PRIMARY KEY,                          -- = event_id
  event_type TEXT NOT NULL,
  aggregate_id UUID NOT NULL,
  user_id UUID NOT NULL,                        -- no FK: events may outlive deleted users briefly
  payload JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL,
  published_at TIMESTAMPTZ NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  last_error TEXT NULL
);
CREATE INDEX ix_outbox_pending ON outbox_events (created_at) WHERE published_at IS NULL;

CREATE TABLE processed_events (
  event_id UUID NOT NULL,
  consumer TEXT NOT NULL,
  processed_at TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (event_id, consumer)
);   -- rows older than 14 days deleted by job

CREATE TABLE deletion_requests (
  user_pseudo_id TEXT PRIMARY KEY,              -- HMAC of user_id, used to purge BigQuery
  requested_at TIMESTAMPTZ NOT NULL,
  purged_at TIMESTAMPTZ NULL
);

CREATE TABLE job_runs (
  id UUID PRIMARY KEY,
  job_name TEXT NOT NULL,
  started_at TIMESTAMPTZ NOT NULL,
  finished_at TIMESTAMPTZ NULL,
  status TEXT NOT NULL CHECK (status IN ('running','succeeded','failed')),
  stats JSONB NOT NULL DEFAULT '{}',
  error TEXT NULL
);
```

Consumers of events whose user no longer exists MUST ack and drop the event.

### 12.3 Data retention

| Data | Retention |
|---|---|
| Transactions, budgets, rules, feedback | Until user deletes them or the account |
| Notifications | 90 days |
| Staged imports (`staged_rows`) | 24 h, then row kept with `staged_rows = '{}'` for audit counts |
| Idempotency keys | 24 h |
| Processed events | 14 days |
| Outbox (published) | 7 days |
| Forecast history | 30 most recent per (user, period, category); outcomes kept 400 days |
| BigQuery raw exports | 400 days (table expiration) |
| Prediction logs | 90 days in BigQuery |
| Demo account data | Reset nightly |

### 12.4 Data-access layer rules

- Repositories live in `services/backend/app/repositories/`. Every public method on a user-owned repository takes `user_id` as its **first required argument** and includes it in the `WHERE` clause.
- A test (`test_repository_scoping.py`) introspects all repository methods and fails if any user-owned table query lacks the `user_id` filter (checked via SQL echo in a test DB with two users).
- No ORM lazy loading in API handlers (`lazy="raise"`), to avoid N+1 queries.
- Aggregations for analytics are done in SQL (`GROUP BY`, `date_trunc` in user tz via `AT TIME ZONE`), not in Python loops.

---

## 13. Backend public API (`/api/v1`)

### 13.1 Cross-cutting rules

#### 13.1.1 Auth
- `Authorization: Bearer <access_token>` on all endpoints except register, login, refresh, health.
- JWT: HS256 with `JWT_SECRET` (≥ 32 random bytes) **or** RS256 if keys are provided; claims `sub` (user_id), `iat`, `exp` (15 min), `jti`, `typ=access`, and `sid` (refresh-token family of the login; lets "change password" keep the caller's own session, since the refresh cookie is not sent to `/users/*`). Clock skew tolerance 30 s. Password field error codes: `PASSWORD_TOO_SHORT`, `PASSWORD_TOO_LONG`, `PASSWORD_TOO_COMMON` (422 `VALIDATION_ERROR`).

#### 13.1.2 Errors — RFC 9457 `application/problem+json`

```json
{
  "type": "https://smart-expense.dev/problems/validation-error",
  "title": "Validation failed",
  "status": 422,
  "code": "VALIDATION_ERROR",
  "detail": "One or more fields are invalid.",
  "request_id": "01JD…",
  "errors": [ { "field": "amount", "code": "INVALID_AMOUNT", "message": "Amount must be greater than 0." } ]
}
```

| HTTP | `code` examples |
|---|---|
| 400 | `BAD_REQUEST`, `INVALID_CURSOR` |
| 401 | `UNAUTHENTICATED`, `TOKEN_EXPIRED`, `INVALID_CREDENTIALS` |
| 403 | `FORBIDDEN` (rare; ownership failures return 404) |
| 404 | `NOT_FOUND` |
| 409 | `CONFLICT`, `IDEMPOTENCY_KEY_REUSED`, `IMPORT_NOT_COMMITTABLE`, `CATEGORY_LOCKED`, `VERSION_CONFLICT`, `BUDGET_EXISTS` |
| 413 | `PAYLOAD_TOO_LARGE` |
| 415 | `UNSUPPORTED_MEDIA_TYPE` |
| 422 | `VALIDATION_ERROR` (+ field codes from 7.2.3), `CATEGORY_TYPE_MISMATCH` |
| 429 | `RATE_LIMITED` (+ `Retry-After`) |
| 500 | `INTERNAL_ERROR` (never leaks stack traces) |
| 503 | `SERVICE_UNAVAILABLE` |

#### 13.1.3 Request IDs and tracing
- Accept `X-Request-ID` if it matches `^[A-Za-z0-9-]{8,64}$`, otherwise generate a ULID. Return it in `X-Request-ID` and in every error body. Propagate to the ML service and into events and logs. Use W3C `traceparent` when OpenTelemetry is enabled.

#### 13.1.4 Pagination
- Cursor-based: `?limit=50&cursor=<opaque>`. Cursor = base64url of `(sort mode, sort_key, id, user_id)` signed with HMAC-SHA256 to prevent tampering; a cursor from another user or another sort mode is `INVALID_CURSOR`. Response: `{ "items": [...], "next_cursor": "…" | null }`. No total counts on large lists (a separate `GET /transactions/count` with the same filters exists).

#### 13.1.5 Idempotency
- `Idempotency-Key` header is **required** on `POST /transactions`, `POST /transactions/imports/{id}/commit`, and bulk endpoints; optional elsewhere. A missing required key → 400 `IDEMPOTENCY_KEY_REQUIRED`; keys are 8–128 characters and scoped per user. Same key + same request hash within 24 h → replay stored response (header `Idempotent-Replayed: true`). Same key + different body → 409 `IDEMPOTENCY_KEY_REUSED`. In-flight duplicate: the second request waits for the first to finish and then replays its response (the key is claimed inside the request's DB transaction); 409 `CONFLICT` with `Retry-After: 1` remains only for a claimed key with no stored response. Failed requests roll back and do not consume the key.

#### 13.1.6 Rate limits (per user unless stated; Redis token bucket, in-memory fallback)

| Scope | Limit |
|---|---|
| Login | 5 failed / 15 min per email; 20 / 15 min per IP |
| Register | 5 / hour per IP |
| Writes (POST/PATCH/DELETE) | 120 / min |
| Reads | 600 / min |
| CSV preview | 10 / hour |
| `categorize-preview` | 60 / min |
| Insight refresh | 1 / min |

#### 13.1.7 Money and dates in JSON
- Money: string with 2 decimals (`"25000.00"`). Requests also accept JSON numbers (converted via `Decimal(str(x))`); responses always strings.
- Datetimes: ISO 8601 with offset. Date-only filters (`date_from`) are local dates `YYYY-MM-DD`.

### 13.2 Endpoint catalogue

**Health**

| Method | Path | Description |
|---|---|---|
| GET | `/healthz` | Liveness (no dependencies) |
| GET | `/readyz` | DB reachable; migrations at head |

**Auth & user**

| Method | Path | Body / params | Response |
|---|---|---|---|
| POST | `/auth/register` | `{email, password, display_name}` | 201 `{user, access_token, expires_in}` + refresh cookie |
| POST | `/auth/login` | `{email, password}` | 200 `{user, access_token, expires_in}` + cookie |
| POST | `/auth/refresh` | cookie | 200 `{access_token, expires_in}` + rotated cookie |
| POST | `/auth/logout` | cookie | 204 |
| GET | `/users/me` | — | 200 user profile |
| PATCH | `/users/me` | any of FR-01.06 fields | 200 |
| POST | `/users/me/password` | `{current_password, new_password}` | 204 |
| DELETE | `/users/me` | `{password, confirm: "DELETE"}` | 204, cookie cleared |
| GET | `/users/me/export` | — | 200 `application/zip` (FR-16) |

**Categories**

| GET | `/categories` | — | list `{id, slug, name, transaction_type}` (cacheable, ETag) |
|---|---|---|---|

**Transactions**

| Method | Path | Notes |
|---|---|---|
| GET | `/transactions` | Filters FR-02.02; cursor pagination |
| GET | `/transactions/count` | Same filters → `{count}` |
| POST | `/transactions` | Create; `Idempotency-Key` required. Response includes `categorization: {decision, source, confidence, alternatives, model_version}` and `warnings: ["POSSIBLE_DUPLICATE"]` |
| GET | `/transactions/{id}` | Includes latest prediction and anomaly summary |
| PATCH | `/transactions/{id}` | Partial update; optional `If-Match: "<version>"` → 409 `VERSION_CONFLICT`. Body may include `apply_to_past_merchant_transactions: true` when changing category |
| DELETE | `/transactions/{id}` | 204 |
| POST | `/transactions/{id}/dismiss-duplicate` | "Not a duplicate" (FR-02.15): clears `possible_duplicate_of`, sets `duplicate_dismissed`; 200 transaction |
| POST | `/transactions/bulk-delete` | `{ids: [...] }` ≤ 200; atomic (any unknown id → 404, nothing deleted); 200 `{deleted: n}` |
| POST | `/transactions/bulk-categorize` | `{ids: [...], category: "<slug>"}` ≤ 200; atomic; 200 `{updated: n}` |
| POST | `/transactions/{id}/confirm-category` | Confirms suggestion → `user_confirmed`; 409 `NOT_A_SUGGESTION` otherwise |
| POST | `/transactions/{id}/recategorize` | `{force?: bool}` (FR-03.09); body optional; 200 with the `categorization` block, same shape as create |
| POST | `/transactions/{id}/not-duplicate` | FR-02.15 |
| POST | `/transactions/categorize-preview` | `{description, merchant?, amount?, payment_method?, transaction_type, transaction_date?}` → `{category, category_status, categorization}`, nothing stored or counted (rules' `times_applied` too); amount defaults to `PREVIEW_DEFAULT_AMOUNT` |
| GET | `/transactions/imports/template.csv` | Template with header and 3 example rows dated in the last days, so it imports as is |
| POST | `/transactions/imports` | multipart `file` → 201 preview `{import_id, status, filename, summary{row_count, valid, invalid, duplicate}, rows[], next_cursor, warnings[{code, message, columns?}], expires_at}`. A row is `{row_number, status, values, prediction, errors[], duplicate_of, duplicate_of_row}` (`values` null when invalid; `duplicate_of` an existing transaction, `duplicate_of_row` an earlier row of the file). The first 500 rows are inline; the rest via `GET /transactions/imports/{id}?cursor=`. Warnings: `UNKNOWN_COLUMNS`, `FILE_ALREADY_IMPORTED`. File errors: 413 `FILE_TOO_LARGE`; 422 `INVALID_ENCODING`, `EMPTY_FILE`, `MISSING_COLUMNS`, `TOO_MANY_ROWS`, `INVALID_CSV` |
| GET | `/transactions/imports/{id}?cursor=&limit=` | Preview/status; rows paginated by row number (max 500). After commit `rows` is empty and the counts remain |
| POST | `/transactions/imports/{id}/commit` | `{mode (default strict), skip_duplicates (default true), category_overrides}`; `Idempotency-Key` required → `{committed_count, skipped_invalid, skipped_duplicates}`. Errors: 409 `IMPORT_NOT_COMMITTABLE` (committed, discarded, expired), 422 `IMPORT_HAS_INVALID_ROWS` (strict mode), 422 `VALIDATION_ERROR` with field `category_overrides.<row>` (`UNKNOWN_ROW`, `UNKNOWN_CATEGORY`, `CATEGORY_TYPE_MISMATCH`). Emits one `transaction.created` per row plus `import.committed` |
| DELETE | `/transactions/imports/{id}` | Discard a previewed import (204); a committed import cannot be discarded (409) |

**Analytics**

| Method | Path | Params | Returns |
|---|---|---|---|
| GET | `/analytics/summary` | `range=current_period|previous_period|last_3_periods|custom`, `date_from`, `date_to` | balance, income, expenses, net, savings_rate, comparison block, review_queue_count, period boundaries |
| GET | `/analytics/categories` | same | category breakdown |
| GET | `/analytics/trends` | same + `granularity=auto|day|week|month` | series (zero-filled), cumulative, budget pace |
| GET | `/analytics/merchants` | same + `limit≤20` | top merchants |
| GET | `/analytics/payment-methods` | same | split |

**Budgets**

| Method | Path | Notes |
|---|---|---|
| GET | `/budgets` | Each with current `spent`, `utilization`, `status`, `projected` (exceed_band), `period` |
| POST | `/budgets` | `{category?: slug|null, limit_amount, alert_thresholds?}`; 409 `BUDGET_EXISTS` |
| PATCH | `/budgets/{id}` | |
| DELETE | `/budgets/{id}` | |
| GET | `/budgets/{id}/history` | snapshots |

**Intelligence**

| Method | Path | Notes |
|---|---|---|
| GET | `/intelligence/anomalies` | filters `status`, `severity`, `type`, `period_id`; pagination |
| GET | `/intelligence/anomalies/{id}` | |
| POST | `/intelligence/anomalies/{id}/feedback` | `{action: "confirm"|"dismiss", reason?}` |
| GET | `/intelligence/forecast` | `category?` → latest forecast (lazy recompute rule 7.7) or 200 `{available:false, reason:"INSUFFICIENT_HISTORY", days_needed}` |
| GET | `/intelligence/recurring` | list + monthly-equivalent total + upcoming 7 days |
| PATCH | `/intelligence/recurring/{id}` | `{status?: "user_confirmed"|"user_rejected", user_expected_amount?}` |
| GET | `/intelligence/insights` | `period_id?`, `include_dismissed?` |
| POST | `/intelligence/insights/{id}/dismiss` | |
| POST | `/intelligence/insights/refresh` | rate-limited |
| GET | `/intelligence/segment` | Tier C |

**Merchant rules, notifications**

| Method | Path |
|---|---|
| GET | `/merchant-rules` |
| PATCH | `/merchant-rules/{id}` `{category}` (past transactions unchanged; `uncategorized` refused) |
| DELETE | `/merchant-rules/{id}` |
| GET | `/notifications` (pagination, `unread_only`) |
| GET | `/notifications/unread-count` |
| POST | `/notifications/{id}/read` |
| POST | `/notifications/read-all` |

**Internal (not exposed through the public frontend proxy; worker service only; Pub/Sub OIDC or Cloud Scheduler OIDC token required, verified audience + service account email)**

| Method | Path | Caller |
|---|---|---|
| POST | `/internal/events/transaction` | Pub/Sub push (all `transaction.*` events) |
| POST | `/internal/jobs/{job_name}` | Cloud Scheduler: every job in 15.1 that runs in the worker, plus `recategorize-needs-review` (manual, after ML outages: re-runs categorization for `needs_review` rows created while `ml_error` was set) |
| POST | `/internal/batch-results/{kind}` | Pipelines writing batch outputs (segments) |

### 13.3 Example: create transaction

Request:

```http
POST /api/v1/transactions
Authorization: Bearer eyJ…
Idempotency-Key: 6c1f6c2e-7f5e-4b8f-9a9e-1d9b1c2a3b4c
Content-Type: application/json

{
  "transaction_type": "expense",
  "amount": "45000",
  "description": "STARBUCKS GRAND INDONESIA",
  "payment_method": "e_wallet",
  "transaction_date": "2026-11-18T12:30:00+07:00"
}
```

Response 201:

```json
{
  "id": "0193…",
  "transaction_type": "expense",
  "amount": "45000.00",
  "description": "STARBUCKS GRAND INDONESIA",
  "merchant": "Starbucks",
  "merchant_key": "starbucks",
  "transaction_date": "2026-11-18T05:30:00Z",
  "has_time": true,
  "payment_method": "e_wallet",
  "category": { "slug": "food_beverage", "name": "Food & Beverage" },
  "category_status": "auto",
  "categorization": {
    "decision": "auto_apply",
    "source": "model",
    "confidence": "0.9700",
    "alternatives": [ { "category": "entertainment", "confidence": "0.0200" } ],
    "model_version": "transaction-classifier@7"
  },
  "possible_duplicate_of": null,
  "warnings": [],
  "version": 1,
  "created_at": "2026-11-18T05:30:02Z",
  "updated_at": "2026-11-18T05:30:02Z"
}
```

---

## 14. ML service API and event contracts

### 14.1 ML service rules

- Private Cloud Run service (`--no-allow-unauthenticated`); only the backend and worker service accounts have `roles/run.invoker`. Requests carry a Google-signed ID token; locally, `ML_AUTH=none`.
- Stateless, no DB access, no user data persisted. Prediction logs exclude raw text (18.4).
- All endpoints accept `request_id`; responses include `model_version`, `feature_version`, `latency_ms`.
- Input validation via Pydantic; unknown fields rejected (`extra="forbid"`).
- Batch endpoints accept ≤ 500 items.
- Uvicorn workers: 1 per vCPU; models loaded once per process. Set `OMP_NUM_THREADS`/`MKL_NUM_THREADS` = 1 per worker to avoid oversubscription.

### 14.2 Endpoints

| Method | Path | Request | Response |
|---|---|---|---|
| POST | `/v1/classify` | `ClassifyRequest` | `ClassifyResponse` |
| POST | `/v1/classify/batch` | `{request_id, items: ClassifyRequest[]}` | `{items: ClassifyResponse[]}` (same order) |
| POST | `/v1/anomaly/score` | `AnomalyRequest` (features computed by backend) | `AnomalyResponse` |
| POST | `/v1/forecast` | `ForecastRequest` (daily history + calendar context) | `ForecastResponse` |
| POST | `/v1/cluster/assign` | `ClusterRequest` | `ClusterResponse` (Tier C) |
| GET | `/v1/models` | — | loaded models + metadata subset |
| GET | `/healthz`, `/readyz`, `/metrics` | — | probes; Prometheus metrics |

`ClassifyRequest`:

```json
{
  "request_id": "01JD…",
  "description": "STARBUCKS GRAND INDONESIA",
  "merchant_key": "starbucks",
  "amount": "45000.00",
  "payment_method": "e_wallet",
  "transaction_type": "expense",
  "local_hour": 12,
  "weekday": 2,
  "feature_version": "features-1"
}
```

Note: `user_id` is **not** sent (not needed for classification; reduces data exposure). `local_hour` is `null` when `has_time = false`.

Contract details (T-17): `local_hour` and `weekday` are required (`weekday` is Monday = 0 in the user's timezone; `local_hour` is an explicit `null` when the time is unknown); `amount` is a decimal string > 0; `merchant_key` is the backend's `resolve_merchant` key (may be empty); `description` is 1–500 chars and is normalized by the service with the shared `ml.features` code. `feature_version` must equal the loaded model's, else 422 `FEATURE_VERSION_MISMATCH`. A batch over `BATCH_MAX_ITEMS` (500) is 422 `BATCH_TOO_LARGE`. With no loaded classifier every `/v1/*` classify call is 503 `MODEL_NOT_AVAILABLE`. In a batch response each item's `latency_ms` is the time of the whole batch. `decision` is `auto_apply` when confidence ≥ `t_high`, `suggest` when ≥ `t_low`, else `needs_review`; `t_low == t_high` means there is no suggest band.

`ClassifyResponse`:

```json
{
  "predicted_category": "food_beverage",
  "confidence": 0.97,
  "decision": "auto_apply",
  "alternatives": [ { "category": "entertainment", "confidence": 0.02 }, { "category": "groceries", "confidence": 0.01 } ],
  "model_version": "transaction-classifier@7",
  "feature_version": "features-1",
  "thresholds": { "t_high": 0.87, "t_low": 0.58 },
  "latency_ms": 6,
  "shadow": null
}
```

`decision` already accounts for thresholds; the backend applies type consistency (FR-03.10) and may change the decision accordingly (recording `source`).

`AnomalyRequest`:

```json
{
  "request_id": "01JD…",
  "transaction_ref": "hmac-of-transaction-id",
  "category": "food_beverage",
  "amount": "250000.00",
  "features": { "z_cat": 6.1, "z_merchant": 0.0, "merchant_seen": 1, "pct_rank_cat": 0.99, "ratio_to_cat_median": 5.6, "cat_count_24h": 1, "cat_count_7d": 9, "cat_rate_56d": 1.3, "cat_spend_7d_ratio": 1.1, "hour_sin": 0.0, "hour_cos": -1.0, "hour_known": 1, "dow_sin": 0.78, "dow_cos": 0.62, "days_since_income": 17, "history_n_cat": 84 },
  "context": { "typical_amount": "45000.00", "merchant_display": "Warung Sate", "category_name": "Food & Beverage" },
  "feature_version": "features-1"
}
```

`AnomalyResponse`:

```json
{
  "is_anomaly": true,
  "anomaly_type": "amount_spike",
  "anomaly_score": 0.91,
  "severity": "high",
  "history_level": "personal",
  "reasons": [
    { "code": "AMOUNT_VS_CATEGORY", "feature": "ratio_to_cat_median", "value": 5.6, "reference": 1.0, "message": "5.6× your typical Food & Beverage spending (Rp45.000)" },
    { "code": "AMOUNT_PERCENTILE", "feature": "pct_rank_cat", "value": 0.99, "reference": 0.5, "message": "Higher than 99% of your Food & Beverage transactions" }
  ],
  "model_version": "anomaly-detector@3",
  "feature_version": "features-1",
  "latency_ms": 4
}
```

Rule-based anomaly types (`frequency_burst`, `new_merchant_high_value`, `category_surge`) are computed in the **shared `ml/anomaly_detection/rules.py`** and executed in the backend/worker (they need history counts already available there); only `amount_spike` scoring calls the ML service. The rules module is versioned with `feature_version`.

`ForecastRequest`: `{request_id, period_start, period_end, as_of_date, daily_history: [{date, nonrecurring_amount}] (≥ 14 days, ≤ 400), spent_to_date, expected_recurring_remaining, calendar: [{date, is_weekend, is_holiday, holiday_known}], feature_version}`.

`ForecastResponse`: `{method, predicted_remaining: {p10, p50, p90}, daily: [{date, p10, p50, p90}], baseline_remaining, model_version, feature_version, latency_ms}`. The backend adds `spent_to_date` and recurring to build the totals (7.7.1).

### 14.3 Events (Pub/Sub topic `transaction-events`)

Envelope (JSON, UTF-8), Pub/Sub attributes `event_type` and `schema_version` duplicated for filtering:

```json
{
  "event_id": "0193…",
  "event_type": "transaction.created",
  "schema_version": 1,
  "occurred_at": "2026-11-18T05:30:02Z",
  "request_id": "01JD…",
  "user_id": "0193…",
  "data": {
    "transaction_id": "0193…",
    "transaction_version": 1,
    "transaction_type": "expense",
    "source": "manual",
    "import_id": null
  }
}
```

| Event | Emitted when | Consumers |
|---|---|---|
| `transaction.created` | Create (manual, CSV commit — one per row) | anomaly scorer, budget threshold checker, recurring updater, cache invalidation |
| `transaction.updated` | Amount, date, type, merchant, or category changed (`data.changed_fields`) | anomaly re-scorer (if amount/date/merchant/type), budget checker, recurring updater |
| `transaction.deleted` | Delete | budget checker, recurring updater |
| `import.committed` | CSV commit | notification (`import_completed`), batch anomaly scoring with `status=historical` for rows older than 7 days |

Payloads contain IDs only — no descriptions or amounts (consumers read current state from the DB). Schema changes are additive within a `schema_version`; breaking changes bump it and consumers support both during migration.

Subscription settings: push to worker `/internal/events/transaction`, ack deadline 60 s, retry policy exponential 10–600 s, max delivery attempts 5, dead-letter topic `transaction-events-dlq` (with a pull subscription for inspection), message retention 7 days.

---

## 15. Batch jobs and scheduling

### 15.1 Job catalogue

All jobs are idempotent (safe to re-run for the same date), record a `job_runs` row, process users in chunks of 200, and continue on per-user errors (logging and counting them). Times are **Asia/Jakarta** (Cloud Scheduler time zone). Per-user local-date logic still uses each user's timezone.

| Job | Schedule | Runs in | What it does |
|---|---|---|---|
| `daily-budget-close` | 00:15 | worker | For users whose period ended yesterday (local): write budget snapshots, forecast outcomes (actuals), INS-07 inputs |
| `daily-forecast` | 01:00 | worker → ml-service | Recompute overall + category forecasts for active users (activity in last 60 days) |
| `category-surge` | 01:30 | worker | Rule `category_surge` for all active users |
| `recurring-refresh` | 02:00 | worker | Recompute recurring series |
| `daily-insights` | 03:00 | worker | Regenerate insights (after forecast and recurring) |
| `export-bigquery` | 03:30 | Cloud Run Job (pipelines image) | Incremental export of changed rows (by `updated_at`) to BigQuery `raw` with pseudonymized IDs |
| `feedback-export` | 03:45 | Cloud Run Job | Eligible feedback → `curated.category_labels` (FR-10.04) |
| `purge-deleted-users` | 04:00 | Cloud Run Job | Delete rows for `deletion_requests` pseudo-IDs from all BigQuery tables; set `purged_at` |
| `cleanup` | 04:30 | worker | Expire imports, prune idempotency keys, processed events, outbox, old notifications, old forecasts, expired anomaly suppressions |
| `recurring-due-soon` | 07:00 | worker | Notifications for payments due in ≤ 2 days |
| `review-queue-reminder` | Mon 08:00 | worker | Weekly reminder if ≥ 5 items |
| `demo-reset` | 05:00 | worker | Re-seed demo account (only when `DEMO_MODE=true`) |
| `training-weekly` | Sun 02:00 | Cloud Run Job (Prefect flow) | Training pipeline for all models (16.1) |
| `drift-report` | Daily 06:00 | Cloud Run Job | Evidently reports (18.3) |
| `shadow-evaluate` | Daily 06:30 | Cloud Run Job | Compare candidate vs production on shadow logs; promote if criteria met (16.4) |
| `clustering-weekly` | Sun 05:00 | Cloud Run Job | Assign segments (Tier C) |

Locally, `make jobs-run JOB=<name>` triggers any job; a Prefect local server MAY schedule them.

---

## 16. MLOps: pipeline, registry, promotion, rollback

### 16.1 Training pipeline (Prefect flow `train_model(model_name, dataset_version)`)

The pipeline MUST be runnable from a clean checkout with one command and reproduce metrics within 0.01:

```bash
make train MODEL=transaction-classifier DATASET=synthetic/v3
```

| Step | Task | Fails pipeline when |
|---|---|---|
| 1 | **Load data** — resolve dataset version (GCS/local), verify manifest hashes; optionally merge `curated.category_labels` snapshot (classifier) | Hash mismatch |
| 2 | **Validate** — Pandera schemas; write quarantine | Schema violation or quarantine > 1% |
| 3 | **Split** — load locked split IDs; verify split hash | Split hash mismatch |
| 4 | **Features** — shared feature module; record `feature_version` | Point-in-time check fails on a sample |
| 5 | **Train** — baseline + candidates from `config/train/<model>.yaml`; seeds fixed; log params, metrics, artifacts to MLflow (one parent run, child run per candidate) | Exception |
| 6 | **Calibrate & threshold** (classifier, anomaly) — on validation split only | — |
| 7 | **Evaluate** — test split(s), slices, plots, behavioural tests (21.4), latency benchmark (fixed 1,000-request replay on CPU, 2 threads) | — |
| 8 | **Gate** — 16.3 | Gate fails → run tagged `gate=failed`, not registered |
| 9 | **Register** — MLflow model version with `metadata.json`, model card, report; alias `candidate` | — |
| 10 | **Notify** — summary (markdown) attached to run; posted as a GitHub Actions job summary when run in CI | — |

Every MLflow run logs: model name, params, dataset name/version/hash, split hash, feature version, taxonomy version, metrics (overall + slices), training duration, git commit (dirty tree → run tagged `dirty=true` and **cannot be registered**), artifact URIs, environment (`pip freeze` snapshot).

### 16.2 Reproducibility controls

- Python deps locked (`uv.lock`); Docker image digest recorded for cloud runs.
- `PYTHONHASHSEED=0`, `numpy`/`random`/`torch` seeds set, LightGBM `deterministic=true`, `n_jobs` fixed.
- Re-run test in CI (weekly, or on changes to `ml/` or `pipelines/`): train baseline classifier twice on a small dataset; assert |Δ macro F1| ≤ 0.01.

### 16.3 Promotion gate (offline)

| Gate | Condition | On failure |
|---|---|---|
| Data quality | No schema violations; quarantine < 1% | Pipeline stops; data report produced |
| Beats baseline | Primary metric better than the baseline by the model's ship rule (9.1) | Logged, not registered |
| Beats production | Primary metric ≥ production model's metric on the **same** test split + margin (classifier: +0.5 macro-F1 point; others: not worse) — skipped when no production model exists | Logged, not registered |
| Slices | No archetype or category drops > 5 points vs production (or vs baseline if no production) | Registered with `gate=needs_review`; not auto-promoted |
| Calibration (classifier) | ECE ≤ 0.05 | Not registered |
| Behavioural tests | Golden set and invariance/directional tests pass (21.4) | Not registered |
| Latency | P95 on benchmark within SLO (5.3) | Not registered |
| Reproducibility | Run is clean (no dirty tree), seed recorded | Not registered |

The first ever production model is promoted manually after passing all gates (`make promote MODEL=… VERSION=…`).

### 16.4 Shadow and online promotion

1. Candidate loaded by ML service alongside production when `SHADOW_ENABLED=true`.
2. For each classify request, production answers; the candidate runs **after the response is sent** (background task) and its output is logged with `shadow=true`. Shadow MUST NOT add latency to the response path.
3. Shadow period: ≥ 7 days **and** ≥ 1,000 shadow predictions (demo traffic can be generated by the load-test replay of synthetic transactions; this is acknowledged in docs).
4. `shadow-evaluate` job promotes when: candidate–production agreement ≥ 85% on non-corrected items; on transactions later corrected by users, candidate accuracy ≥ production; candidate P95 latency within SLO; prediction distribution PSI vs production < 0.2; no errors > 0.1%.
5. Promotion = move MLflow alias `production` to the candidate version and set alias `previous` on the old one. ML service picks it up within `MODEL_POLL_INTERVAL_S`.

### 16.5 Rollback

```bash
make rollback MODEL=transaction-classifier   # moves @production to @previous
```

No image rebuild or redeploy. Rollback is logged (who, when, from, to, reason) in MLflow model version tags and `docs/ops/rollback-log.md`. A rollback drill is part of the Week 8 exit criteria and the demo video.

### 16.6 Retraining policy

- Scheduled weekly (`training-weekly`). Also triggered by: drift alert on a key feature (18.3) **combined with** a proxy-performance drop, or ≥ 500 new eligible feedback labels since the last training.
- Drift alone never triggers promotion; all gates still apply.
- Individual corrections never trigger retraining (FR-10.03).

### 16.7 Tooling

| Need | Choice | Notes |
|---|---|---|
| Orchestration | Prefect 3 (flows as Python; deployments run as Cloud Run Jobs) | Airflow documented as alternative in ADR-0004 |
| Tracking & registry | MLflow (server on Cloud Run, backend store Cloud SQL `mlflow` DB, artifacts in GCS) | Use model **aliases** (`production`, `candidate`, `previous`), not deprecated stages |
| Containers | Docker, one image per service (`frontend`, `backend` (also worker), `ml-service`, `pipelines`, `mlflow`) in Artifact Registry | Multi-stage builds, non-root user, slim base |
| CI | GitHub Actions: lint (ruff, eslint), type-check (mypy --strict on `ml/` and backend app, tsc), unit + integration tests, feature parity, contract tests, coverage gates, image build, Trivy scan, pip-audit, npm audit, gitleaks | Required on PRs |
| CD | GitHub Actions → Cloud Run with Workload Identity Federation (no JSON keys) | `main` → deploy to `demo` environment after tests |
| IaC | Terraform for all GCP resources | `terraform destroy` removes everything |
| Data validation | Pandera | |
| Drift | Evidently | |

---

## 17. Security and privacy

### 17.1 Controls

| Area | Control |
|---|---|
| Transport | HTTPS only (Cloud Run managed TLS); HSTS `max-age=31536000`; HTTP → HTTPS redirect |
| Passwords | Argon2id (`argon2-cffi`, time_cost=3, memory_cost=64 MiB, parallelism=1 — tune so hashing takes 200–500 ms on Cloud Run); rehash on login if parameters changed |
| Tokens | 13.1.1; refresh rotation + reuse detection; refresh tokens stored as SHA-256 hashes |
| Authorization | Every resource scoped by `user_id` (12.4); cross-user access returns 404; dedicated BOLA/IDOR test suite covers every endpoint with an ID |
| Service-to-service | ML service private; Cloud Run IAM invoker; internal endpoints verify Google OIDC tokens (audience + expected service account) |
| Secrets | Secret Manager mounted as env vars; none in repo/images; `.env.example` contains placeholders only; gitleaks in CI |
| Supply chain | Locked dependencies; `pip-audit`, `npm audit --audit-level=high`, Trivy image scan (fail on CRITICAL); Dependabot weekly |
| Least privilege | One service account per service with minimal roles (Terraform-defined): backend (Cloud SQL client, Pub/Sub publisher, run.invoker on ml-service, Secret accessor for its secrets), ml-service (GCS object viewer on models bucket, MLflow access), pipelines (BigQuery job user + data editor on its datasets, GCS read/write on datasets/mlflow buckets) |
| Rate limiting | 13.1.6 |
| Input hardening | Pydantic strict models; request body limit 1 MB (CSV 5 MB); filename sanitization; CSV parsed with the `csv` module (no `eval`); formula-injection-safe exports |
| HTTP headers | `Content-Security-Policy` (self + required chart/fonts only), `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy` minimal, `frame-ancestors 'none'` |
| CSRF | Refresh cookie is `SameSite=Strict` and used only on `/api/v1/auth/*`; all other endpoints require the bearer token (not a cookie), so CSRF does not apply to them |
| ML-specific | Feedback poisoning mitigations (FR-10.04); artifact hash verification (11.4); training configs versioned; model registry write access only for the pipelines service account |
| Demo | Demo deployment uses synthetic data only; registration on the demo is allowed but data is labelled "demo, may be wiped" and wiped every 30 days |

### 17.2 Privacy

- Do not store card numbers, bank credentials, or national ID numbers. If a description looks like it contains a 13–19 digit number, mask it to the last 4 digits **before** storage (`****1234`).
- Real personal financial data MUST NOT be used for training without explicit consent (`training_consent`) and defined retention. For this project: synthetic + public datasets only.
- Account deletion: FR-01.09 (DB cascade + BigQuery purge within 24 h).
- BigQuery and logs use pseudonymous IDs (HMAC-SHA256 with a secret key), never emails.
- A short privacy notice page explains what is stored, the consent toggle, and deletion.

### 17.3 Logging rules

- Structured JSON logs (`structlog`), one line per event, fields: `timestamp`, `severity`, `service`, `request_id`, `trace_id`, `user_pseudo_id` (never raw user_id or email), `route`, `status`, `latency_ms`, plus event-specific fields.
- MUST NOT log: description, merchant, notes, amounts tied to a user, emails, passwords, tokens, cookies, Authorization headers, raw CSV content.
- MAY log for debugging: description length, `sha256(description)[:12]`, `merchant_key` hash, category slug, model version, decision.
- A unit test runs the request pipeline with a sentinel description (`"SENTINEL-DO-NOT-LOG-7f3a"`) and asserts it never appears in captured logs.
- Exceptions are logged with stack traces server-side only; responses contain only `request_id`.

---

## 18. Monitoring, alerting, and runbooks

### 18.1 Three layers

Drift does not automatically mean the model got worse; performance is assessed with proxy labels and periodic evaluation, not drift alone.

| Layer | Measured | Tooling | Alerts |
|---|---|---|---|
| System | Latency P50/P95/P99 per route, throughput, error rate, CPU, memory, instance count, cold starts, DB pool usage, ML circuit state, Pub/Sub backlog and DLQ count, job success | Prometheus metrics (`/metrics`) + Grafana locally; Cloud Monitoring (Managed Service for Prometheus) in GCP | P95 over SLO for 10 min; 5xx > 2% for 5 min; DLQ > 0; job failed; circuit open > 5 min |
| Data | Missing/invalid values, quarantine counts, share of unseen `merchant_key`, feature distributions vs training reference, CSV import error rates | Pandera, Evidently (daily report to GCS + summary metrics to Prometheus pushgateway or Cloud Monitoring custom metrics) | Unseen-merchant share > 2× 28-day median; any key feature PSI > 0.25 |
| Model | Confidence distribution, decision mix, predicted category distribution, correction rate per category/model version, anomaly alert rate and confirmation rate, forecast WAPE on closed periods, shadow agreement | Prediction logs in BigQuery + Evidently + Grafana | Correction rate > 1.5× trailing 4-week rate; auto_apply share drops > 15 points; forecast WAPE on closed periods > 30%; alert confirmation rate < 0.3 (≥ 30 feedbacks) |

### 18.2 Metric names (Prometheus)

Backend:
- `http_requests_total{service,route,method,status}`
- `http_request_duration_seconds_bucket{service,route,method}`
- `ml_client_requests_total{endpoint,outcome}` (`ok|timeout|error|circuit_open`)
- `ml_client_duration_seconds_bucket{endpoint}`
- `ml_circuit_state`
- `categorization_decisions_total{decision,source}`
- `category_feedback_total{feedback_type,model_version}`
- `csv_imports_total{stage,outcome}`
- `events_published_total{event_type,outcome}`, `outbox_pending` (gauge), `outbox_oldest_age_seconds`
- `events_consumed_total{consumer,outcome}`
- `anomalies_total{type,severity,is_alert}`
- `jobs_runs_total{job,status}`, `job_duration_seconds{job}`

ML service:
- `inference_requests_total{model,endpoint,outcome}`
- `inference_duration_seconds_bucket{model,endpoint}`
- `prediction_confidence_bucket{model}`
- `predicted_category_total{model_version,category}`
- `model_loaded_info{model,version,alias}` (gauge = 1)
- `model_load_failures_total{model}`
- `shadow_agreement_total{model,agree}`

Label cardinality rule: never use user IDs, transaction IDs, or merchant names as labels.

### 18.3 Drift reports

- Reference = training dataset feature sample stored with the production model (10k rows).
- Current = last 7 days of production prediction logs (features, not raw text).
- Columns monitored: classifier `log_amount`, `payment_method`, `hour_bucket`, predicted category; anomaly features; forecast daily totals.
- Output: HTML report in `gs://<project>-reports/drift/YYYY-MM-DD/`, summary metrics, and a link in the Grafana "Data health" dashboard.

### 18.4 Prediction logs

Every inference (and shadow inference) emits one structured log line:

```json
{
  "event": "prediction",
  "model": "transaction-classifier",
  "model_version": "transaction-classifier@7",
  "feature_version": "features-1",
  "request_id": "01JD…",
  "input_hash": "sha256-12chars",
  "features_summary": { "log_amount": 10.71, "payment_method": "e_wallet", "hour_bucket": "midday" },
  "output": { "predicted_category": "food_beverage", "confidence": 0.97, "decision": "auto_apply" },
  "shadow": false,
  "latency_ms": 6
}
```

In GCP, a Log Router sink filters `jsonPayload.event="prediction"` into BigQuery `predictions.prediction_logs` (90-day partition expiration). Locally, logs go to stdout and `make logs-to-duckdb` loads them for analysis.

### 18.5 Proxy performance (labels arrive late or never)

- Classifier: correction rate within 30 days per model version and category.
- Anomaly: confirmation vs dismissal rate.
- Forecast: true error computed automatically when a period closes (`forecast_outcomes`).

These proxies are biased (users do not correct every mistake). Dashboards label them "proxy".

### 18.6 Dashboards (Grafana JSON in `monitoring/dashboards/`, provisioned automatically locally)

1. **Service health**: latency, traffic, errors, instances, cold starts, DB, circuit state.
2. **Model health**: confidence histogram, decision mix, correction rate, category distribution, active versions, shadow agreement.
3. **Data health**: latest drift summary, quarantine counts, unseen-merchant share, import errors.
4. **Pipelines & jobs**: last runs, durations, gate results, production model age, outbox/DLQ.

### 18.7 Alert routing

Alerts go to email of the owner (Cloud Monitoring notification channel) and optionally a Discord/Slack webhook (`ALERT_WEBHOOK_URL`). Every alert links to its runbook entry.

### 18.8 Runbook (`docs/RUNBOOK.md`)

Each entry: **Symptom → Check → Action → Escalate when**. Written so an engineer who did not build the model can follow it.

| Alert | Check | Action |
|---|---|---|
| Inference latency P95 high | Instance count, CPU, request size (batch), recently promoted version, cold starts | Raise min instances temporarily; rollback if correlated with a new version (16.5) |
| ML circuit open | ml-service `/readyz`, recent deploys, model load failures | Fix/redeploy or rollback model; transactions continue with `needs_review` — run `POST /internal/jobs/recategorize-needs-review` after recovery |
| Correction rate rising | Compare unseen-merchant share and top corrected categories with training data | Collect data, run training early, consider alias additions; update merchant alias map |
| Data-quality gate failed | Validation report, quarantine table | Fix source; re-run without lowering the gate |
| DLQ messages > 0 | Pull DLQ, inspect error | Fix bug; replay with `make dlq-replay` (re-publishes to main topic) |
| Outbox backlog growing | Relay logs, Pub/Sub permissions | Restart worker; check IAM; relay is idempotent |
| Job failed | `job_runs.error`, Cloud Run Job logs | Re-run job for the date (idempotent) |
| Model load failure / hash mismatch | MLflow version metadata vs GCS object | Re-register artifact or rollback alias; never bypass hash check |
| Forecast WAPE high on closed periods | By archetype/history level | Check recurring detection; retrain; consider falling back to run-rate via config flag `FORECAST_FORCE_BASELINE=true` |

Note: the target internship role monitors production ML services under senior guidance, so the runbook doubles as a collaboration document.

---

## 19. Infrastructure, environments, and configuration

### 19.1 Local development (no GCP account required)

`docker compose up` starts:

| Service | Image / notes |
|---|---|
| `postgres` | PostgreSQL 16 (app DB + `mlflow` DB) |
| `redis` | Redis 7 (optional; app works without it) |
| `pubsub-emulator` | `gcr.io/google.com/cloudsdktool/google-cloud-cli:emulators` (used when `EVENT_BUS=pubsub`) |
| `mlflow` | MLflow server, artifacts on a local volume |
| `ml-service` | `MODEL_SOURCE=mlflow` or `local_dir` |
| `backend` | FastAPI with hot reload; runs Alembic migrations on start (dev only) |
| `worker` | Same image as backend, `ROLE=worker` (runs relay + internal endpoints) |
| `frontend` | Next.js dev server |
| `prometheus`, `grafana` | Profile `observability` (`docker compose --profile observability up`) |

Make targets (all MUST work on a fresh clone after `make setup`):

| Target | Does |
|---|---|
| `make setup` | Install toolchains via `uv` and `pnpm`, pre-commit hooks, copy `.env.example` → `.env` |
| `make data` | Generate synthetic dataset v-current with default seed |
| `make train-local` | Train baseline models on local data, register to local MLflow, set aliases |
| `make up` / `make down` | Compose up/down |
| `make seed-demo` | Create demo user with 12 months of synthetic data |
| `make demo` | `data` + `train-local` + `up` + `seed-demo`, then prints URLs |
| `make test` | All unit tests |
| `make test-integration` | Integration tests (testcontainers) |
| `make check` | Lint + types + tests + coverage gates |
| `make openapi` | Regenerate OpenAPI specs and frontend client |
| `make train MODEL=… DATASET=…` | Full pipeline |
| `make promote` / `make rollback` | Alias management |
| `make loadtest` | k6/Locust scenario against local or `TARGET_URL` |
| `make jobs-run JOB=…` | Run a batch job |

### 19.2 Environments

| Env | Purpose | Data |
|---|---|---|
| `local` | Development | Synthetic |
| `ci` | Tests | Fixtures + small synthetic |
| `demo` | Public portfolio deployment on GCP | Synthetic + demo user |

There is no separate production environment in this project; `demo` is treated as production for SLOs and monitoring.

### 19.3 GCP resources (Terraform, `infrastructure/terraform/`)

- Region: `asia-southeast2` (Jakarta) for Cloud Run, Cloud SQL, GCS, Artifact Registry; BigQuery dataset location `asia-southeast2`.
- Cloud Run services: `frontend`, `backend` (public ingress), `worker` (ingress internal + Pub/Sub/Scheduler OIDC), `ml-service` (no unauthenticated), `mlflow` (IAM-protected; access via `gcloud run services proxy` locally).
- Cloud Run Jobs: `pipelines` (training, exports, drift).
- Cloud SQL PostgreSQL 16: smallest shared-core tier for demo, private IP or Cloud SQL connector; automated backups 7 days.
- Memorystore Redis is **not** provisioned by default (cost); `REDIS_URL` unset in demo → in-process cache. ADR notes the trade-off.
- Pub/Sub topics/subscriptions (14.3), Cloud Scheduler jobs (15.1), Secret Manager secrets, Artifact Registry repo, GCS buckets (`datasets`, `mlflow`, `reports`) with uniform access and lifecycle rules, BigQuery datasets (10.5), Log Router sink, monitoring alert policies + notification channel, service accounts and IAM bindings, Workload Identity Federation pool for GitHub.
- **Cost guardrails** (Day 1): billing budget with alerts at 50/90/100% of a monthly cap (`TF_VAR_monthly_budget_idr`); Cloud Run min instances 0 (except optionally `ml-service` = 1 during demos/recording); `max_instances` set on every service (≤ 3); BigQuery queries use partition filters (require_partition_filter = true on large tables); delete everything with `terraform destroy` after the portfolio period. Check current free tiers/credits before deploying (Open question Q4).

### 19.4 Configuration (environment variables)

All config via env vars parsed by Pydantic Settings; `.env.example` lists every variable with a safe placeholder and a comment.

| Variable | Service | Default | Notes |
|---|---|---|---|
| `APP_ENV` | all | `local` | `local|ci|demo` |
| `DATABASE_URL` | backend, worker | — | `postgresql+psycopg://…` |
| `REDIS_URL` | backend, worker | unset | optional |
| `JWT_SECRET` | backend | — | ≥ 32 bytes, secret |
| `ACCESS_TOKEN_TTL_S` | backend | `900` | |
| `REFRESH_TOKEN_TTL_S` | backend | `2592000` | |
| `CORS_ORIGINS` | backend | `http://localhost:3000` | |
| `ML_SERVICE_URL` | backend, worker | `http://ml-service:8080` | |
| `ML_TIMEOUT_MS` | backend | `300` | |
| `ML_AUTH` | backend, ml-service | `none` locally, `google_id_token` in GCP | |
| `EVENT_BUS` | backend, worker | `inmemory` | `inmemory|pubsub` |
| `PUBSUB_PROJECT_ID`, `PUBSUB_TOPIC` | backend, worker | — | |
| `PUBSUB_EMULATOR_HOST` | local | — | |
| `INTERNAL_OIDC_AUDIENCE`, `INTERNAL_ALLOWED_SA` | worker | — | |
| `MAX_TRANSACTION_AMOUNT` | backend | `1000000000` | |
| `MIN_ALERT_AMOUNT` | worker | `50000` | |
| `ANOMALY_ALERTS_PER_PERIOD` | worker | `3` | |
| `FORECAST_FORCE_BASELINE` | worker | `false` | kill switch |
| `EXPORT_PSEUDONYM_KEY` | backend, pipelines | — | secret |
| `CURSOR_SIGNING_KEY` | backend | — | secret |
| `MLFLOW_TRACKING_URI` | ml-service, pipelines | `http://mlflow:5000` | |
| `MODEL_SOURCE` | ml-service | `mlflow` | `mlflow|local_dir` |
| `MODEL_POLL_INTERVAL_S` | ml-service | `300` | |
| `SHADOW_ENABLED` | ml-service | `false` | |
| `REQUIRED_MODELS` | ml-service | `transaction-classifier` | comma list |
| `DATA_BACKEND` | pipelines | `local` | `local|bigquery` |
| `GCP_PROJECT_ID`, `GCS_DATASETS_BUCKET`, `GCS_REPORTS_BUCKET` | pipelines | — | |
| `DEMO_MODE`, `DEMO_USER_PASSWORD` | backend | `false` | |
| `LOG_LEVEL` | all | `INFO` | |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | all | unset | tracing optional |
| `ALERT_WEBHOOK_URL` | monitoring | unset | |
| `BACKEND_INTERNAL_URL` | frontend | `http://backend:8000` | Next.js rewrites target |

### 19.5 CI/CD workflows (`.github/workflows/`)

| Workflow | Trigger | Jobs |
|---|---|---|
| `ci.yml` | PR, push to main | Path-filtered: python lint/type/test (backend, ml, ml_service, pipelines, data_generator), frontend lint/type/test, integration tests (Postgres service container), feature parity, contract tests (OpenAPI diff), coverage gates, gitleaks, pip-audit, npm audit |
| `build.yml` | push to main | Build images, Trivy scan, push to Artifact Registry tagged with git SHA |
| `deploy.yml` | after `build` on main (manual approval environment `demo`) | Alembic migrate (Cloud Run Job), deploy services by image digest, smoke test (`/healthz`, login demo, create+delete transaction), auto-rollback Cloud Run revision on smoke failure |
| `ml-reproducibility.yml` | weekly + changes in `ml/`, `pipelines/` | Train baseline twice on small data, compare |
| `terraform.yml` | changes in `infrastructure/` | `fmt`, `validate`, `plan` on PR (comment), `apply` on main with approval |
| `e2e.yml` | nightly + PR label `e2e` | Playwright against compose stack |

Branching: trunk-based, short-lived branches, squash merge, Conventional Commits (`feat:`, `fix:`, `ml:`, `infra:`, `docs:`). PR template includes: requirement IDs touched, tests added, docs updated, screenshots for UI.

---

## 20. Delivery plan: 10 weeks, tiers, and cut lines

### 20.1 Assumptions

- 10–12 hours per week (~100–120 hours total), in parallel with university and other activities.
- Thin vertical slice first (transaction → categorization → dashboard), then models, then MLOps polish.
- If the application deadline is earlier than 10 weeks, apply with **Cut line A** completed and continue during the selection process.

### 20.2 Tiers

| Tier | Weeks | Contents | Cut line |
|---|---|---|---|
| A | 1–6 | Generator + EDA + locked splits; classifier (baseline + 2 candidates, calibration); backend (auth, CRUD, CSV, budgets, analytics, notifications); ML service; frontend core pages; anomaly + forecast **baselines**; feedback + merchant memory; MLflow + training pipeline + offline gate + rollback; Docker compose | **Cut line A**: portfolio-ready MVP runnable locally with `make demo` |
| B | 7–8 | GCP deploy via Terraform + CI/CD; Pub/Sub event path; monitoring dashboards + alerts + runbook; anomaly/forecast models vs baselines; recurring detection; insights; shadow mode | **Cut line B**: deployed, monitored, event-driven |
| C | 9–10 | IndoBERT experiment; clustering; load test vs SLO; data export; model cards; README, demo video, docs polish | **Cut line C**: complete v3.0 |

### 20.3 Weekly plan with exit criteria and task IDs

Each task ID is a unit of work suitable for one PR/agent session. Dependencies in brackets.

**Week 1 — Data foundation**
- T-01 Repo scaffold: structure (Section 22), `uv` workspace, pnpm, pre-commit, Makefile skeleton, CI lint job, ADR template, `.env.example`.
- T-02 Category taxonomy + merchant lists + alias map + holidays config. [T-01]
- T-03 Synthetic generator v1 with manifest and Pandera self-validation (10.1). [T-02]
- T-04 EDA notebook → `docs/EDA.md` (class balance, text length, amount distributions by archetype, ambiguity examples). [T-03]
- T-05 Split module + locked splits + hash (10.4). [T-03]
- T-06 Public dataset search → `docs/DATA_SOURCES.md` with licenses; decide Q1. [—]
- **Exit**: dataset regenerates byte-identically from seed; splits locked and documented.

**Week 2 — Classifier**
- T-07 `ml/preprocessing` (merchant normalization ≥ 30 tests, description preprocessing). [T-02]
- T-08 Feature module for classifier with point-in-time and parity test harness. [T-07]
- T-09 Baseline LR + Linear SVM (calibrated) + LightGBM; MLflow logging; evaluation report incl. coverage curve, unseen-merchant F1, ECE, error analysis. [T-05, T-08]
- T-10 Threshold calibration procedure (7.3.4). [T-09]
- **Exit**: baseline and ≥ 2 candidates evaluated on the same splits; error analysis written.

**Week 3 — Backend core**
- T-11 Backend scaffold: settings, logging (17.3), problem+json errors, request IDs, health. [T-01]
- T-12 DB schema + Alembic migrations + category seed + repository layer with scoping test. [T-11]
- T-13 Auth (register/login/refresh rotation/logout/password/delete) + rate limits. [T-12]
- T-14 Transactions CRUD + filters + cursor pagination + idempotency + duplicate detection. [T-12]
- T-15 CSV preview/commit (7.2.3) with all error codes. [T-14]
- T-16 BOLA/IDOR test suite. [T-13, T-14]
- **Exit**: register, login, CRUD, atomic CSV import; cross-user tests pass.

**Week 4 — ML service + frontend core**
- T-17 ML service: model loading (local_dir + MLflow), `/v1/classify`, batch, probes, metrics, hash verification. [T-09]
- T-18 Backend ML client with timeout, circuit breaker, fallback; categorization flow; merchant rules; feedback capture; categorize-preview. [T-14, T-17]
- T-19 Frontend scaffold: auth flow, layout, API client generation, transactions page (+ add/edit drawer with live preview), review queue, CSV import UI. [T-13, T-18]
- **Exit**: new transactions are auto-categorized; corrections stored as feedback and create merchant rules.

**Week 5 — Budgets, analytics, intelligence baselines**
- T-20 Analytics endpoints with SQL aggregations + property tests vs raw SQL. [T-14]
- T-21 Budgets + status + thresholds + notifications (FR-05, FR-14). [T-20]
- T-22 Dashboard + budgets pages. [T-20, T-21]
- T-23 Anomaly baseline (7.6.2) + rules + in-memory event path + anomalies API/UI + feedback. [T-18]
- T-24 Forecast run-rate + decomposition (recurring placeholder = 0 until T-30) + API/UI. [T-20]
- **Exit**: both intelligence baselines visible with reasons; dashboard aggregates match SQL.

**Week 6 — MLOps core**
- T-25 Prefect training flow (16.1) for classifier; MLflow registry, aliases, metadata.json, model card generation. [T-09]
- T-26 Offline gates (16.3) + behavioural tests + latency benchmark. [T-25]
- T-27 `make promote` / `make rollback`; ML service alias polling hot-swap. [T-25, T-17]
- T-28 Reproducibility CI job. [T-25]
- T-29 Docker images + full compose + `make demo`. [all above]
- **Exit**: pipeline re-run from clean commit within 0.01; gate works automatically; rollback in one command. **= Cut line A.**

**Week 7 — Deployment**
- T-30 Recurring detection (FR-08) + forecast decomposition with recurring. [T-24]
- T-31 Terraform for all GCP resources + budget alerts. [T-29]
- T-32 CI/CD build/deploy with WIF, migrations job, smoke tests, revision rollback. [T-31]
- **Exit**: images in Artifact Registry; CI/CD + Terraform produce the demo environment.

**Week 8 — Events and monitoring**
- T-33 Outbox + relay + Pub/Sub + worker push endpoint + DLQ + idempotent consumers. [T-23, T-31]
- T-34 Metrics instrumentation, Grafana dashboards, Cloud Monitoring alert policies, prediction log sink. [T-32]
- T-35 Evidently drift job + reports. [T-34]
- T-36 Runbook (≥ 3 entries, tested once each) + rollback drill. [T-34]
- T-37 Insights engine (FR-09) + batch jobs scheduler (15.1). [T-30]
- T-38 Anomaly model (IF/LOF) and forecast models (ETS, LightGBM quantile) vs baselines; record decisions. [T-23, T-24, T-25]
- T-39 Shadow mode + `shadow-evaluate`. [T-27, T-34]
- **Exit**: dashboards and alerts live; Pub/Sub events produce anomaly scores; runbook with 3 entries. **= Cut line B.**

**Week 9 — Depth**
- T-40 IndoBERT experiment with latency/cost report; ship decision documented. [T-26]
- T-41 Clustering (FR-13) + segment UI. [T-25]
- T-42 Settings page (merchant rules, consent, export, delete account). [T-19]
- **Exit**: IndoBERT decision documented; clustering and recurring detection run.

**Week 10 — Verification and release**
- T-43 Load test (k6) vs SLO incl. cold-start report; results in README + MODEL_EVALUATION. [T-32]
- T-44 E2E Playwright flows. [T-22, T-42]
- T-45 Docs set (Section 23), model cards, ADRs complete; demo video 3–5 min. [all]
- T-46 Final verification against Section 26 checklist by a reviewer who did not build it (fresh agent session with only this PRD + repo). [all]
- **Exit**: load test within SLO; model cards, README, demo video done. **= Cut line C.**

---

## 21. Testing strategy

### 21.1 Test layers

| Layer | Scope | Tooling | Target |
|---|---|---|---|
| Unit | Business rules (budgets, periods, decisions, duplicates), CSV parsing, merchant normalization, feature functions, insight rules, recurring algorithm | pytest, hypothesis | Backend ≥ 80% lines; `ml/` ≥ 70% |
| Integration | API with real PostgreSQL (testcontainers) and a stub or real ML service | pytest + httpx | Main flows pass in CI |
| Contract | OpenAPI schemas of backend and ML service; frontend client regenerated with no diff; event JSON schemas (`schemas/events/*.json`) validated in producer and consumer tests | schemathesis (smoke), jsonschema | Fail on unintended change |
| Data | Pandera schemas on generator output and pipeline tables | pandera | In pipeline + CI |
| Behavioural (model) | 21.4 | pytest | Regression fails gate |
| Leakage & parity | Future-row injection; batch vs online parity | pytest | Required in CI |
| Security | Cross-user access for every ID endpoint; auth flows (token reuse, expiry); sentinel log test; dependency/image scans | pytest, pip-audit, Trivy, gitleaks | No critical findings |
| Load | Classification + CRUD + dashboard mix | k6 (or Locust) | SLOs in 5.3 |
| E2E | 3 Playwright flows (8.3) | Playwright | Nightly green |

### 21.2 Required named test cases (minimum set)

- `test_fr_02_07_commit_is_atomic_on_db_error` — inject failure at row N, assert zero rows inserted.
- `test_fr_02_06_preview_writes_nothing`.
- `test_fr_02_12_duplicate_same_day_date_only` and `_within_10_minutes`.
- `test_period_boundaries_start_day_25_across_year_end`.
- `test_period_start_day_change_applies_next_period`.
- `test_fr_05_04_status_boundaries` at 49.99%, 50%, 79.99%, 80%, 99.99%, 100%.
- `test_fr_05_05_threshold_notification_once_per_period`.
- `test_ml_unavailable_transaction_still_saved_needs_review`.
- `test_fr_03_10_type_mismatch_picks_valid_alternative`.
- `test_merchant_rule_applied_before_model`.
- `test_transfer_excluded_from_income_and_expense`.
- `test_balance_equals_sql_ground_truth` (hypothesis-generated ledgers).
- `test_anomaly_mad_floor_no_division_by_zero`.
- `test_anomaly_alert_budget_cap`.
- `test_event_consumer_idempotent_duplicate_delivery` and `_out_of_order_version`.
- `test_account_delete_cascades_all_tables` (introspects all tables with `user_id`).
- `test_no_sensitive_fields_in_logs`.
- `test_every_endpoint_with_id_returns_404_for_other_user` (auto-discovers routes).
- `test_features_point_in_time_future_injection`.
- `test_features_batch_online_parity`.

### 21.3 Fixtures

- `tests/fixtures/ledgers/*.yaml`: small hand-written ledgers with expected analytics outputs (golden files).
- Factory functions (`factory_boy` or plain builders) for users/transactions; never share state between tests; each test uses its own user.
- Time is controlled with `time-machine`; no test depends on the real clock.

### 21.4 Behavioural tests for models (CheckList-style)

| Type | Example | Expectation |
|---|---|---|
| Invariance (typo) | "Kopi Kenangan" vs "kopi kenangn" | Same top-1 category |
| Invariance (prefix/reference) | "QRIS KOPI KENANGAN 839201" vs "Kopi Kenangan" | Same top-1 |
| Invariance (case/location) | "INDOMARET - BDG" vs "indomaret" | Same top-1 |
| Directional (anomaly) | Same features, amount ×5 | Score increases |
| Directional (forecast) | Higher PTD spending | P50 does not decrease |
| Golden set | `ml/tests/golden/classifier.yaml` ≥ 100 hand-labelled cases (common Indonesian merchants) | Accuracy ≥ 0.95; any regression vs production on golden set fails the gate |
| Minimum functionality | Each category has ≥ 3 golden cases | ≥ 2 of 3 correct per category |

---

## 22. Repository structure

```text
smart-expense-intelligence/
├── frontend/                       # Next.js + TypeScript
│   └── src/{app,components,features,lib,messages}/
├── services/
│   ├── backend/                    # FastAPI: auth, transactions, budgets, analytics, insights, worker role
│   │   ├── app/
│   │   │   ├── api/                # routers (v1, internal)
│   │   │   ├── core/               # settings, security, logging, errors, rate limiting
│   │   │   ├── models/             # SQLAlchemy models
│   │   │   ├── schemas/            # Pydantic request/response
│   │   │   ├── services/           # business logic (categorization, budgets, analytics, insights, recurring, anomalies, forecasts)
│   │   │   ├── repositories/       # user-scoped data access
│   │   │   ├── events/             # outbox, relay, bus (inmemory/pubsub), consumers
│   │   │   ├── jobs/               # batch jobs (15.1)
│   │   │   └── clients/            # ML service client + circuit breaker
│   │   ├── migrations/             # Alembic
│   │   ├── tests/{unit,integration,security}/
│   │   └── openapi.json            # generated
│   └── ml_service/                 # FastAPI: inference only
│       ├── ml_service/{api,loading,shadow,metrics}/   # import package; not `app`, which would collide with backend's `app` in the shared uv venv (see DECISIONS.md)
│       ├── tests/
│       └── openapi.json
├── ml/                             # installable library used by pipelines, backend, ml_service
│   ├── preprocessing/              # merchant + description normalization
│   ├── features/                   # point-in-time feature functions (shared)
│   ├── classification/
│   ├── anomaly_detection/          # baseline, models, rules.py
│   ├── forecasting/
│   ├── clustering/
│   ├── recurring/                  # rule-based detector (used by backend jobs)
│   ├── evaluation/                 # splits, metrics, reports, behavioural tests
│   ├── schemas/                    # Pandera schemas
│   └── tests/
├── data_generator/                 # synthetic generator (+ tests)
├── pipelines/                      # Prefect flows: train, evaluate, gate, register, promote, drift, exports
├── config/                         # generator/ (incl. merchants.yaml), train/, insights.yaml, merchant_aliases.yaml, holidays_id.yaml, cities_id.yaml, label_maps/
├── schemas/events/                 # JSON Schemas for events
├── monitoring/                     # Grafana dashboards, Prometheus config, alert rules, Evidently config
├── infrastructure/
│   ├── terraform/                  # GCP
│   └── docker/                     # Dockerfiles
├── loadtest/                       # k6 scripts
├── docs/
│   ├── PRD.md                      # this document
│   ├── ARCHITECTURE.md
│   ├── API.md
│   ├── ML_DOCUMENTATION.md
│   ├── MODEL_EVALUATION.md
│   ├── DATA_SOURCES.md
│   ├── EDA.md
│   ├── RUNBOOK.md
│   ├── DECISIONS.md
│   ├── PRIVACY.md
│   ├── model_cards/
│   ├── adr/
│   └── ops/
├── data/                           # gitignored (raw/, synthetic/, splits/ hashes are committed separately under data_splits/)
├── data_splits/                    # committed split ID hashes + small ID lists for the default dataset
├── models/                         # gitignored local artifacts
├── .github/workflows/
├── docker-compose.yml
├── Makefile
├── pyproject.toml                  # uv workspace
├── .env.example
└── README.md
```

`ml/` is a separate package so ML code is testable without a server, and `ml_service` stays small. Never commit large datasets or personal data: use `.gitignore`, reproducible synthetic data, and GCS.

---

## 23. Documentation set

| Document | Content | Reader |
|---|---|---|
| `README.md` | Problem in one paragraph, demo GIF/screenshot, live link + demo login, architecture diagram, results table (model vs baseline, with MLflow run IDs), `make demo`, repo map, limitations | Recruiter, new engineer |
| `docs/ARCHITECTURE.md` | Diagrams (components, request flows, data flow batch/stream), design rationale, trade-offs, scaling notes, future options | Engineers |
| `docs/API.md` | Overview of public + internal + ML APIs, auth, errors, pagination, idempotency, examples; links to generated OpenAPI | Cross-team engineers |
| `docs/ML_DOCUMENTATION.md` | Data, generator, features, models, calibration, decisions, retraining, how to add a category | Data scientists, MLEs |
| `docs/MODEL_EVALUATION.md` | Metrics with slices, calibration, coverage curve, negative results, circularity check, load-test results, limitations | Reviewers |
| `docs/model_cards/*.md` | One per model (Appendix D template) | Reviewers |
| `docs/DATA_SOURCES.md` | Every dataset: source, license, use, limitations, label mapping | Reviewers |
| `docs/EDA.md` | Exploration findings | DS/MLE |
| `docs/RUNBOOK.md` | 18.8 | On-call engineer |
| `docs/PRIVACY.md` | What is stored, consent, deletion, pseudonymization | Users, reviewers |
| `docs/adr/` | One file per decision (ADR-0001…0009 at minimum) | Anyone asking "why" |
| `docs/DECISIONS.md` | One-line log of smaller decisions | Agents, maintainers |

Docs are part of the Definition of Done for each task: a PR that changes behavior described in a doc updates that doc.

---

## 24. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Scope too large for the time available | Project unfinished before applying | Tiers and cut lines (20.2); Tier A alone is a complete portfolio; vertical slices first |
| Schedule competes with classes and organizations | Inconsistent progress | 10–12 h/week plan; small weekly tasks with visible outcomes; task IDs sized for single sessions |
| Synthetic data too clean | Over-optimistic metrics, low credibility | Text noise, ambiguity, unseen-merchant test, holdout generator variant, public dataset comparison, explicit limitations |
| Circular evaluation (generator and model share assumptions) | Results look good but mean little | Circularity check (9.6, item 6); report drops; don't claim discoveries from archetype recovery |
| Data leakage | Inflated evaluation | Locked temporal/per-user splits; point-in-time features; injection tests in CI |
| IndoBERT too slow/expensive on Cloud Run | SLO violation, cost | Ship rule (9.1); keep linear model; document negative result |
| GCP cost surprises | Unexpected bill | Budget alerts on day 1; min instances 0; max instances caps; no Memorystore by default; `terraform destroy` after demo period |
| Anomaly false positives | Users ignore alerts | Personal baselines, cold-start caps, alert budget, suppressions, feedback |
| Drift without real degradation | Unnecessary retraining | Promotion requires performance gates and proxies, not drift alone |
| Overengineering | Delays | Modular monolith, no Kafka/Kubernetes/feature store; ADRs for future options |
| Agent-generated code diverging from spec | Inconsistent system | Section 0 rules; requirement IDs in tests; contract tests; T-46 independent verification |
| Cross-site cookie issues between Cloud Run hosts | Broken login refresh | Same-origin proxy via Next.js rewrites (8.3) |
| Feedback poisoning | Degraded model | Eligibility rules FR-10.04; per-user caps; gates |
| Timezone/period bugs | Wrong budgets/forecasts | Single period utility with exhaustive tests; all computations in user tz |

---

## 25. Open questions

| ID | Question | Default if unanswered | Decide by |
|---|---|---|---|
| Q1 | Which public dataset is close enough for classifier generalization testing? | No public test; report synthetic + holdout variant only, state limitation | End of Week 1 (T-06) |
| Q2 | UI language: English only, or Indonesian too? | English UI, i18n-ready; Indonesian added only if time permits in Tier C | Week 4 |
| Q3 | Is IndoBERT base or a smaller distilled Indonesian model used for the DL experiment? | Smallest available Indonesian BERT-family model that fits 2 GiB RAM on Cloud Run | Week 9 |
| Q4 | Which GCP free tier/credits apply to the account at deploy time? | Assume none; keep within a small monthly budget cap and destroy after demo | Week 7 |
| Q5 | Application deadline for the internship | Assume ≥ 10 weeks; otherwise apply at Cut line A | Week 1 |

All other decisions in this PRD are final unless changed by an ADR.

---

## 26. Acceptance criteria and Definition of Done

### 26.1 Feature acceptance (Given / When / Then)

| Feature | Acceptance criteria |
|---|---|
| Authentication | Given two users A and B, when A requests any of B's resources by ID, then the API returns 404; refresh token reuse revokes the family; login rate limit returns 429 after 5 failures |
| Account deletion | Given a user with data in every table, when they delete the account, then no row with their `user_id` remains in PostgreSQL and a deletion request exists; after `purge-deleted-users`, no row with their pseudo-ID remains in BigQuery |
| Transaction CRUD | User can create, read, update, delete; validation errors use field codes; `Idempotency-Key` replay returns the same response and creates one row |
| CSV import | Preview writes nothing; `strict` commit with an invalid row returns 422 and inserts nothing; `skip_invalid` inserts exactly the valid, non-duplicate rows; an injected DB failure mid-commit leaves zero new rows |
| Duplicates | Same-day same-merchant same-amount transactions are flagged, not blocked |
| Categorization | Response includes category, calibrated confidence, decision, model version; ML service down → transaction saved as `needs_review` within the latency SLO |
| Correction & memory | Correcting a category stores feedback and creates a merchant rule; the next transaction with that merchant is categorized by the rule without calling the model |
| Analytics | For 20 hypothesis-generated ledgers, every dashboard figure equals a direct SQL computation; transfers are excluded from income/expenses |
| Budgets | Status boundaries exact; each threshold notifies once per period; periods respect start day and user timezone |
| Anomaly detection | Each anomaly has score, severity, type, ≥ 1 data-derived reason, model version; alert cap enforced; confirm/dismiss stored |
| Forecasting | Forecast returns P10/P50/P90, method, baseline value, model version; < 14 days history returns `INSUFFICIENT_HISTORY`; evaluation report compares with run-rate |
| Recurring | Synthetic subscriptions are detected with next due date; a price change produces INS-08 |
| Insights | Each insight's message can be recomputed from its evidence payload; no duplicate insight per rule/period/subject |
| Events | Duplicate and out-of-order deliveries produce exactly one current anomaly result; poison messages land in DLQ and alert |
| MLOps | `make train` from a clean commit registers a candidate only if gates pass; re-run differs ≤ 0.01; `make rollback` switches serving version without redeploy |
| Monitoring | Dashboards show system/model/data health; a simulated latency incident triggers an alert linked to a runbook entry |
| Security | No sensitive field in logs (sentinel test); Trivy/pip-audit/npm audit without critical findings; no secrets in repo (gitleaks) |

### 26.2 Definition of Done (v3.0)

- [ ] Users can register, record and import transactions, and correct predicted categories.
- [ ] Transactions are categorized by an ML model with calibrated confidence, decision thresholds from model metadata, and per-user merchant memory.
- [ ] Dashboard analytics come from actual data and match SQL ground truth.
- [ ] Budgets with status and threshold notifications work across custom period start days.
- [ ] Anomalies, forecasts, recurring expenses, and insights appear with traceable reasons/evidence.
- [ ] Every model has a baseline, locked-split evaluation, model card, and written decision (incl. negative results).
- [ ] Training pipeline reruns reproducibly; models are versioned, tracked, gated, shadowed, promotable, and rollbackable.
- [ ] Backend, worker, ML service, and frontend run in Docker locally (`make demo`) and on GCP via Terraform + CI/CD.
- [ ] Event-driven anomaly scoring via Pub/Sub with outbox, idempotent consumers, and DLQ.
- [ ] System, data, and model monitoring with alerts and a runbook.
- [ ] Load-test and evaluation results documented with limitations.
- [ ] Technical documentation (Section 23) and a 3–5 minute demo video are available.
- [ ] Independent verification (T-46) passed against 26.1.

---

## Appendix A — Mapping to the target role (ML Engineer intern)

Every role requirement has concrete evidence in the repository.

| Role requirement | Evidence in project | Section |
|---|---|---|
| Develop and ship AI/ML products | Four models served via API in a working product | 7, 9, 14 |
| Collaborate with engineers across teams | Written API/event contracts between backend and ML service; ADRs | 13, 14, 23 |
| Research recent technology | Bounded IndoBERT experiment vs baseline with latency/cost analysis | 9.2 |
| Write technical documentation | Model cards, ARCHITECTURE, API, RUNBOOK, ADRs | 23 |
| Monitor ML services in production | Grafana/Cloud Monitoring dashboards, Evidently drift, alerts, runbook | 18 |
| Software engineering / DevOps fundamentals | Docker, GitHub Actions CI/CD, coverage gates, Terraform, security scanning | 16.7, 19, 21 |
| ML pipelines / MLOps | Prefect pipeline, MLflow registry, gates, shadow, rollback | 16 |
| Cloud, especially GCP | Cloud Run, Cloud SQL, BigQuery, Pub/Sub, GCS, Artifact Registry, Scheduler, Secret Manager | 6, 19.3 |
| Batch and stream data processing | Batch training/forecast/exports from BigQuery; stream scoring via Pub/Sub | 6.3, 14.3, 15 |
| Understand goals and propose approaches | Problem framing, non-goals, baseline-first decisions | 1, 3, 9.1 |
| Python | Backend, ML, pipelines | all |
| TensorFlow / PyTorch | IndoBERT fine-tuning in PyTorch | 9.2 |
| Supervised, unsupervised, deep learning | Classifier (supervised), anomaly + clustering (unsupervised), IndoBERT (DL) | 9 |
| Communication and collaboration | README, demo video, readable evaluation report, ADRs | 23 |
| ≥ 6-month internship commitment | Not applicable to the project; consistency shown through 10 weeks of commit history | 20 |

## Appendix B — Portfolio packaging and interview preparation

**Package**
- README with problem paragraph, GIF, architecture diagram, results table (model vs baseline), `make demo`.
- Demo video (3–5 min): add a transaction → auto category → correct it → merchant rule applies → anomaly with reasons → forecast with range → monitoring dashboard → one model promotion or rollback.
- Public Cloud Run link with synthetic data and a demo login.
- One-page summary (CV/Notion) linking repo, demo, and model cards.
- Emphasize the bridge between existing backend/DevSecOps experience and ML — not just the models.

**CV bullet formulas** — fill numbers only from your own results, never from illustrative values:
- "Built an expense analytics platform with transaction classification, anomaly detection, and forecasting; the classifier reached macro F1 [X] vs. a [Y] baseline on a temporal split."
- "Designed an MLOps pipeline (MLflow, promotion gates, shadow deployment) on GCP Cloud Run with CI/CD and Terraform; models roll back in one command."
- "Monitored services with Prometheus, Grafana, and Evidently; set a P95 latency SLO of [Z] ms and wrote runbooks for three incident scenarios."

**Questions to be ready for**

| Question | Answer points | Evidence |
|---|---|---|
| Why not deep learning for classification? | Strong linear baseline on short noisy text; DL tested under a pre-written decision rule | 9.1, MODEL_EVALUATION |
| How did you prevent leakage? | Temporal/per-user splits, point-in-time features, future-injection tests | 10.4, 11.1 |
| How do you know the model degrades without labels? | Proxies (correction rate, alert confirmations), forecast error at period close, scheduled evaluation; drift alone is not enough | 18.5 |
| What happens when the ML service is down? | Transaction saved as `needs_review`; timeout + circuit breaker; recategorize job after recovery | 6.3, 6.4 |
| How are new models promoted safely? | Offline gates, shadow period, alias promotion, one-command rollback | 16 |
| What are the limitations? | Synthetic data, possible circularity, biased proxies — all documented | 9.6, 24 |
| What would change with real data? | Consent, pseudonymization, re-evaluation, stricter monitoring, possibly fine-tuning | 17.2 |
| A design decision you changed? | Prepare one real story from commit history/ADRs (e.g. C3 import semantics or the same-origin cookie fix) | adr/ |

After the project is complete, add real results to this table.

## Appendix C — ADR template (`docs/adr/0000-template.md`)

```markdown
# ADR-NNNN: <Title>

- Status: proposed | accepted | superseded by ADR-XXXX
- Date: YYYY-MM-DD
- PRD sections affected: <e.g. 7.2.3, 13.2>

## Context
<What problem or constraint forces a decision?>

## Options considered
1. <Option> — pros / cons
2. <Option> — pros / cons

## Decision
<What we chose and why.>

## Consequences
<Positive, negative, follow-up work, what would make us revisit.>
```

## Appendix D — Model card template (`docs/model_cards/<model>.md`)

```markdown
# Model card: <model name> (version <mlflow version>)

## Intended use
<What it does in the product; who sees the output.>

## Out-of-scope use
<Uses it must not be applied to (e.g. fraud detection, credit decisions).>

## Training data
<Dataset name/version/hash, generator config, public data, label mapping, known biases.>

## Features
<Feature version and list; point-in-time guarantees.>

## Evaluation
<Splits, metrics overall and by slice, calibration, baseline comparison, MLflow run IDs.>

## Decision thresholds
<Values, how they were chosen.>

## Limitations and risks
<Synthetic data, circularity, cold start, failure modes.>

## Monitoring
<Signals watched, alerts, retraining triggers.>

## Changelog
<Version history and promotion/rollback events.>
```

## Appendix E — Official technical references

| Technology | Documentation |
|---|---|
| FastAPI | https://fastapi.tiangolo.com/ |
| SQLAlchemy | https://docs.sqlalchemy.org/ |
| Alembic | https://alembic.sqlalchemy.org/ |
| Pydantic | https://docs.pydantic.dev/ |
| scikit-learn | https://scikit-learn.org/stable/ |
| LightGBM | https://lightgbm.readthedocs.io/ |
| statsmodels | https://www.statsmodels.org/ |
| PyTorch | https://pytorch.org/docs/stable/index.html |
| Hugging Face Transformers | https://huggingface.co/docs/transformers |
| MLflow | https://mlflow.org/docs/latest/ |
| Prefect | https://docs.prefect.io/ |
| Evidently | https://docs.evidentlyai.com/ |
| Pandera | https://pandera.readthedocs.io/ |
| Next.js | https://nextjs.org/docs |
| Docker | https://docs.docker.com/ |
| Terraform Google provider | https://registry.terraform.io/providers/hashicorp/google/latest/docs |
| Google Cloud Run | https://cloud.google.com/run/docs |
| Cloud SQL for PostgreSQL | https://cloud.google.com/sql/docs/postgres |
| Pub/Sub | https://cloud.google.com/pubsub/docs |
| BigQuery | https://cloud.google.com/bigquery/docs |
| RFC 9457 Problem Details | https://www.rfc-editor.org/rfc/rfc9457 |

---

**End of document — Smart Expense Intelligence PRD v3.0**

### Addendum T-18: categorization contract notes

- `categorization` block (create, recategorize, preview): `{decision, source (user|rule|model|fallback), confidence, alternatives[{category, confidence}], model_version, predicted_category, ml_error}`. `predicted_category` is the model's pick even when the row stays `uncategorized`; `ml_error` is one of `timeout|unavailable|circuit_open|bad_response|rejected|disabled`.
- `PATCH /transactions/{id}` accepts `apply_to_past_merchant_transactions` (only together with `category`) and returns `applied_to_past`. Only rows of the same merchant and compatible type with status `auto|suggested|needs_review|rule` change (status `rule`); user-chosen rows are never touched.
- CSV preview rows carry a `prediction` object (`predicted_category`, `alternatives`, `model_version`, `ml_error`, `rule_id`...); commit writes the `category_predictions` rows and counts rule use.

### Addendum T-19: frontend notes

- `services/backend/openapi.json` is committed; `make openapi` regenerates it and `frontend/src/api/schema.d.ts`; `make openapi-check` runs in CI.
- The mutating endpoints that require `Idempotency-Key` (13.1.4): create transaction, bulk delete, bulk categorize, import commit. The frontend sends a UUID per user action.

### Addendum T-20: analytics response contract

- Every response carries `period {range, start, end, period_id, days_in_period, days_elapsed, in_progress, timezone}` (`end` inclusive; `period_id` only for a single budget period).
- `summary`: `balance, income, expenses, net, savings_rate, income_count, expense_count, comparison{label, current, previous, change{income, expenses, net}}, review_queue_count`. `categories`: `total_expenses, items[{slug, name, amount, share, count}]` (all categories, sorted by amount). `trends`: `granularity, budget_limit, series[{start, end, expenses, cumulative, future, budget_pace}]`. `merchants`: `items[{merchant_key, name, amount, count}]`, `limit` 1..20 (default 5). `payment-methods`: `total_expenses, items[{payment_method, amount, share, count}]`.
- `trends` also takes `granularity=auto|day|week|month`; `month` means budget periods. Percentages are strings in percent with one decimal.
- Ranges, comparison rules and the change formula are fixed in `docs/DECISIONS.md` (T-20).

### Addendum T-21: budgets and notifications response contract

- `BudgetOut`: `id, category{id,slug,name}|null, limit_amount, alert_thresholds, spent, remaining, utilization (percent, 1 decimal), status, projected (null until T-24), period{start,end,period_id,days_in_period,days_elapsed}, created_at, updated_at`. `GET /budgets` returns `{items, category_limits_exceed_overall}`; `GET /budgets/{id}` returns one; `GET /budgets/{id}/history?limit=1..60` returns `{items[{period_id, limit_amount, spent, utilization}]}`, newest first.
- `PATCH /budgets/{id}` accepts `limit_amount` and `alert_thresholds` only. `POST` rejects non-expense categories with 422 `CATEGORY_TYPE_MISMATCH`.
- Notifications: `GET /notifications?unread_only&limit=1..100&cursor` returns `{items, next_cursor}`; `unread-count` returns `{count}`; `POST /notifications/read-all` returns `{updated}`; `POST /notifications/{id}/read` returns the notification. Threshold notifications use `dedupe_key = budget:{budget_id}:{period_id}:{threshold}` and a payload with `budget_id, category, period_id, threshold, spent, limit_amount, utilization`.

### Addendum T-23: anomaly API contract

- `GET /intelligence/anomalies`: filters `status` (repeatable; default open, confirmed, dismissed, historical), `severity`, `type`, `period_id`, `alerts_only`, `limit` 1..100, `cursor`; returns `{items, next_cursor}`, newest first. `GET /intelligence/anomalies/{id}`; `POST /intelligence/anomalies/{id}/feedback` `{action: confirm|dismiss, reason?}` (reason only with dismiss; 409 `ANOMALY_SUPERSEDED` on a replaced row).
- `AnomalyOut`: `id, anomaly_type, severity, status, is_alert, score (0..1), history_level, category|null, period_id, reasons[{code, message, feature, value, reference}], transaction{id, transaction_date, amount, merchant, description}|null, model_version, feedback_reason, feedback_at, created_at`.
- Thresholds: `config/anomaly.yaml`; cold-start priors: `config/anomaly_priors.yaml`. Event handling and alert rules: `docs/DECISIONS.md` (T-23).
