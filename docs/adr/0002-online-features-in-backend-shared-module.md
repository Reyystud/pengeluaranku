# ADR-0002: Online features are computed in the backend with the shared `ml` package

- Status: accepted
- Date: 2026-11-19
- PRD sections affected: 6.1, 6.3, 11.1, 11.2, 14.1

## Context
Some models need user-history features (e.g. anomaly features relative to the user's own past spending). Those features need the user's data, which lives in the backend database. The ML service is meant to be stateless and DB-free (ADR-0001). Training/serving skew — different code computing "the same" feature offline and online — is one of the most common ML production bugs.

## Options considered
1. **ML service reads the database** — simple, but couples ML to the product schema, widens its permissions, and breaks statelessness.
2. **Managed / custom feature store** with an online serving layer — solves skew, but is heavy infrastructure for this scale (see ADR-0006).
3. **Backend computes online features using the same `ml/preprocessing` + `ml/features` package the training pipeline uses, and sends them in the inference request.**

## Decision
Option 3. There is exactly one feature code path (`ml/`), installed as a library by the pipelines and the backend. Every feature function takes `as_of` and uses only rows strictly before it (point-in-time). A `FEATURE_VERSION` constant is stored with each model; the ML service rejects requests with a mismatching version (409 `FEATURE_VERSION_MISMATCH`).

## Consequences
- Positive: ML service stays stateless; one implementation for training and serving.
- Positive: skew is testable — CI runs a batch-vs-online parity test (exact for categoricals, 1e-6 for floats) and a future-row injection test.
- Negative: the backend depends on the `ml` package; feature changes require a coordinated version bump and backend deploy.
- Negative: feature computation cost sits in the backend request path; must stay within the latency SLO.
- Revisit if: feature computation becomes expensive enough to need precomputed online features.
