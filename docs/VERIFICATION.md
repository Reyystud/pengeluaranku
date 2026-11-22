# Verification against PRD 26 (T-46)

**This is a self-check by the builder, not the independent verification T-46 asks for.** PRD 26.2 requires a reviewer who did not build the system (a fresh session with only the PRD and the repository). That has not happened; the last Definition-of-Done item stays open.

Status words: **covered** = named tests exist and pass in `make check` (result at the bottom); **partial** = part of the criterion is covered; **not verified** = nothing in this repository shows it.

## 26.1 Feature acceptance

| Feature | Status | Evidence / gap |
|---|---|---|
| Authentication | covered | `services/backend/tests/integration/test_auth_api.py` (refresh reuse, 429), `tests/security/test_bola.py`, `test_transactions_api.py` |
| Account deletion | partial | deletion and deletion request in `test_auth_api.py`; `purge-deleted-users` is not implemented (listed as "not here, on purpose" in `app/jobs/catalogue.py`), so the pseudonym-purge half is not covered |
| Transaction CRUD | covered | `test_transactions_api.py` (field codes, idempotent replay) |
| CSV import | covered | `test_imports_api.py` (preview writes nothing, strict/skip, atomic commit) |
| Duplicates | covered | `test_transactions_api.py`, `test_imports_api.py` |
| Categorization | partial | `test_categorization_api.py`, `test_ml_client.py` (ML down gives `needs_review`); the "within the latency SLO" part needs the load test, which has not been run |
| Correction & memory | covered | `test_categorization_api.py`; also the third Playwright flow |
| Analytics | covered | property tests in `test_analytics_properties.py` against SQL ground truth |
| Budgets | covered | `test_budgets_api.py` |
| Anomaly detection | covered | `ml/tests/test_anomaly_*.py`, `test_anomalies_api.py` |
| Forecasting | covered | `test_forecast_api.py` (`INSUFFICIENT_HISTORY`), `ml/tests/test_forecast_*.py`, MODEL_EVALUATION section 4 |
| Recurring | covered | `test_recurring_api.py`, `test_insight_rules.py` (price change) |
| Insights | covered | `test_insight_rules.py`, `test_insights_api.py` |
| Events | covered | `test_events_pubsub.py`, `test_events_bootstrap.py` (duplicates, DLQ) against the emulator-free test bus |
| MLOps | partial | gates, promotion, rollback and shadow have unit tests; no clean-commit `make train` re-run difference was measured here, and the `ml-reproducibility` workflow has not been seen green |
| Monitoring | partial | alert rule unit tests and dashboards exist (T-34 to T-36); a simulated latency incident was never fired in a running stack |
| Security | partial | sentinel log tests exist; gitleaks and Trivy are in CI. `pip-audit` and `npm audit` are not configured, so "without critical findings" is not shown |

## 26.2 Definition of Done

- Register, record, import, correct categories: **covered** (tests plus 3 local Playwright flows).
- ML categorization with calibrated confidence and merchant memory: **covered**; the baseline has not passed the promotion gates.
- Analytics match SQL: **covered**.
- Budgets across start days: **covered**.
- Traceable anomalies, forecasts, recurring, insights: **covered**.
- Every model has a baseline, locked-split evaluation, model card and written decision: **partial**; the classifier and clusterer have cards, anomaly and forecast have written results but no registered model or card.
- Reproducible training, tracked, gated, shadowed, promotable, rollbackable: **partial** (see MLOps above; shadow has never run on live traffic).
- Runs in Docker locally and on GCP via Terraform + CI/CD: **not verified**. `make demo` was not run end to end in this session and nothing has been deployed to GCP.
- Event-driven anomaly scoring: **covered** in tests; not deployed.
- Monitoring with alerts and a runbook: **partial** (see Monitoring).
- Load-test and evaluation results documented: **partial**; evaluation yes, load test `[TBD after run]`.
- Technical documentation: **done** (this task); **demo video: not recorded** (script in `DEMO_SCRIPT.md`).
- Independent verification: **open**.

## Known gaps worth fixing first

1. Run the load test and the cold-start scenario against a real stack.
2. Add `pip-audit` and `npm audit` to CI, and implement `purge-deleted-users`.
3. Run `make demo` end to end and the compose-based e2e workflow once.
4. Get an independent reviewer for T-46.
