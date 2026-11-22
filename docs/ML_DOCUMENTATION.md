# ML documentation

Numbers live in [`MODEL_EVALUATION.md`](MODEL_EVALUATION.md) and in MLflow; this page explains how the pieces fit. All data is synthetic (ADR-0008), so no figure here says anything about real users.

## Data

- Generator: `data_generator/` (seeded, config in `config/generator/`). Dataset `synthetic/v1`: seed 42, 2,000 users, 12 months. Command: `make data`.
- Splits are ID lists in `data_splits/<dataset_version>/` with a hash; they do not change without an ADR. Evaluation uses a temporal split plus an unseen-merchant split.
- Sources and label maps: [`DATA_SOURCES.md`](DATA_SOURCES.md), `config/label_maps/`. EDA: [`EDA.md`](EDA.md).

## Models

| Model | Code | Status |
|---|---|---|
| transaction-classifier | `ml/classification/`, `pipelines/train_flow.py` | Logistic regression baseline, calibrated; registered, alias `candidate`; has not passed the promotion gates (see MODEL_EVALUATION) |
| IndoBERT classifier experiment | `ml/classification/indobert.py` | Experiment only; ship decision in MODEL_EVALUATION section 5 |
| anomaly detector | `ml/anomaly_detection/` | Rules plus Isolation Forest/LOF experiments (section 3); no model registered |
| expense forecaster | `ml/forecasting/` | Run-rate/seasonal baselines, ETS and LightGBM quantile experiments (section 4); no model registered |
| recurring detection | `ml/recurring/` | Rule based, `config/recurring.yaml` (section 2) |
| behavior clusterer | `ml/clustering/` | K-Means, artifact `config/clusterer_model.yaml` (section 6) |

## Features

Feature code is shared between training and serving (`ml/features/`, `ml/clustering/features.py`), and features are point-in-time: a row never uses data from after it. Money is a float only inside feature code (`log1p(amount)`).

## Thresholds and config

No ML threshold is hard-coded in business code. They are in model `metadata.json` (classifier `t_high`/`t_low`) or in versioned files under `config/` (`anomaly.yaml`, `forecast.yaml`, `shadow.yaml`, `clustering.yaml`, `train/*.yaml`). Ship rules are fixed in those files before an experiment is run.

## Calibration

The classifier's probabilities are calibrated (isotonic) on the validation split; ECE is reported per slice. Unseen merchants remain over-confident, which is why the auto-apply region is narrow.

## Retraining and release

`make train MODEL=... DATASET=...` runs the Prefect flow (train, evaluate, gate, register). `pipelines/promotion.py` moves aliases; shadow evaluation (`make shadow-evaluate`) compares the candidate with production on live traffic before promotion; `make rollback` restores `previous`. Drift is checked by `python -m pipelines drift-report`. Procedures: [`RUNBOOK.md`](RUNBOOK.md).

## How to add a category

Categories are fixed, seeded slugs (`taxonomy-1`). Adding one means a new taxonomy version: update `ml/taxonomy.py` and the label maps, add an Alembic migration for the seed, regenerate data and splits (which needs an ADR), and retrain. `uncategorized` is never a model label.

## Known limits

- Synthetic data only; circularity is not excluded (the generator defines the labels).
- Real-data results: `[TBD after run]`.
- Models other than the classifier baseline are not registered or deployed.
