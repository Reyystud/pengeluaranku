# Model card: transaction-classifier (version 1, alias `candidate`)

## Intended use
Suggests a spending category for a transaction from its description, merchant, amount, payment method, type, and time of day. The user sees the suggestion (auto-applied, "Confirm?", or "Choose category") and can always change it.

## Out-of-scope use
Not for fraud detection, credit or lending decisions, tax categorization, or any decision about a person. Not validated on real bank data.

## Training data
Synthetic dataset `synthetic/v1` (generator 1.1.0, seed 42, 2,000 users, 12 months, 2,171,358 rows); split locked as `splits-1`, split_hash `cc7b019c3718c3b21f7756892314356fb0ae15eb603dc6b3c16046a19e8b1b3d`. Training used a per-class capped sample of the train split (313,760 rows). Labels are the generator's `true_category`, including about 5% intentionally ambiguous merchants. Known bias: merchants, noise patterns, and category shares are the generator's assumptions.

## Features
`features-1`: character and word TF-IDF of the preprocessed description, character TF-IDF of the merchant key, scaled `log1p(amount)`, payment method, transaction type, hour bucket, weekend flag. Per-transaction only, so there is no use of other rows or other users.

## Evaluation
Logistic Regression baseline, run `20261120-024213` (MLflow run `bbf88d539f9b40ccafb82b94492d98ff`): temporal test macro F1 0.9687, accuracy 0.9523, ECE 0.0007 after calibration; unseen-merchant macro F1 0.5231, accuracy 0.4543, ECE 0.3148. Full tables, baseline comparison and negative results: `docs/MODEL_EVALUATION.md`.

## Decision thresholds
Not set yet (`decision_thresholds` is null in `metadata.json`). The PRD defaults (`t_high` 0.85, `t_low` 0.60) apply until the calibration procedure runs (T-10).

## Limitations and risks
- Synthetic data only; real-world accuracy is unknown.
- Generalization to new merchants is poor (macro F1 0.52) and confidence is badly overstated for them (ECE 0.31). Treat unknown merchants as needing review.
- About 5% of rows are inherently ambiguous in this dataset; accuracy above about 95% on the temporal test is not attainable.
- The temporal test is saturated and cannot distinguish models. No circularity check yet (generator holdout variant not built).
- Trained on a capped sample; the effect of the cap was not measured.

## Monitoring
Planned (PRD 18): confidence distribution, share of `needs_review`, user correction rate, feature drift. Not implemented yet.

## Changelog
- 2026-11-20: version 1 registered with alias `candidate` (local MLflow). Not promoted.
