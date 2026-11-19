# data_splits

Locked evaluation splits (PRD §10.4). **They must not change after week 1 without an ADR.**

Layout: `data_splits/<dataset_version>/`, e.g. `data_splits/synthetic/v1/`.

| File | Content |
|---|---|
| `splits.json` | Split version, parameters, dataset identity (generator version, seed, sha256 of `transactions.parquet`), counts per split, and the SHA-256 hashes (`split_hash` is the one to quote) |
| `heldout_merchants.csv` | Merchants whose rows all go to the `test_unseen_merchant` classifier split |
| `cluster_users.csv` | 50/50 user split (halves A/B) for clustering stability, stratified by archetype |
| `forecast_periods.csv` | Per user, the last 4 complete budget periods; origins are day 5/10/15/20 of each |
| `user_cuts.csv` | Per-user chronological cut counts (anomaly over all rows; classifier over non-held-out rows) |

The full per-transaction ID lists (`transaction_id`, `classifier_split`, `anomaly_split`) are derived,
not committed (about 2 million rows). `make splits` writes them to `data/splits/<dataset_version>/assignments.parquet`.

## Commands

```bash
make data              # generate data/synthetic/v1 (seed 42)
make splits            # compute + write splits; refuses to change already-locked splits
make verify-splits     # recompute and compare with the committed hashes (non-zero exit on change)
```

`pytest` also runs `ml/tests/test_locked_splits.py` when `data/synthetic/v1` exists.

## Rules in one place

- Classifier: held-out merchants first (15% per category, at least one, never all), then per-user chronological 70/15/15 over the remaining rows.
- Anomaly: per-user chronological 70/15/15 over all rows. Labels are used for evaluation only.
- Forecast: a forecast at origin day k may use only transactions dated on or before day k of that period.
- Clustering: users 50/50 by archetype-stratified hash order.
- Order inside a user is the local timestamp (date-only rows count as 12:00), ties broken by `transaction_id`.
- Selection uses SHA-256 ordering, not numpy random numbers, so results do not depend on library versions or row order.
