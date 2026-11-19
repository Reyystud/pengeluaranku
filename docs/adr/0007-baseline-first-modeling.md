# ADR-0007: Baseline-first modeling with pre-written ship rules

- Status: accepted
- Date: 2026-11-19
- PRD sections affected: 5.2, 9.1, 9.6, 16.3

## Context
It is tempting to jump to complex models (e.g. a fine-tuned IndoBERT for short transaction descriptions). Without a baseline there is no evidence that the complexity pays off in quality, latency, or cost. Results on synthetic data are also easy to over-interpret.

## Options considered
1. **Start with the most capable model** — may look impressive; no proof it beats something simpler, higher latency and cost.
2. **Baseline first; candidates must beat it under a decision rule written before training.**

## Decision
Option 2. Every model has a simple baseline and a ship rule fixed in PRD 9.1 before any training:
- Classifier: TF-IDF (char + word n-grams) + Logistic Regression. A candidate ships only with macro F1 ≥ baseline + 2.0 points **and** ≥ current production + 0.5 points, and P95 latency within SLO.
- Anomaly: robust modified z-score (MAD) per user × category.
- Forecast: run-rate and seasonal naive.
- Clustering: K-Means with k by silhouette.
Candidates that lose are recorded as negative results in `docs/MODEL_EVALUATION.md`. All numbers come from real runs on locked splits.

## Consequences
- Positive: decisions are defensible and explainable in interviews; prevents over-engineering.
- Positive: baselines double as fallbacks (e.g. `FORECAST_FORCE_BASELINE=true`).
- Negative: the final shipped model may be "boring" — that is acceptable and documented.
- Revisit if: a baseline turns out too weak to be a meaningful reference (record via a new ADR, not by moving the goalposts after seeing results).
