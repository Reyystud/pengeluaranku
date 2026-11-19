# ADR-0006: No managed feature store

- Status: accepted
- Date: 2026-11-19
- PRD sections affected: 3.2, 10.5, 11.1

## Context
Models need consistent features for training (batch) and serving (online). Feature stores (e.g. Vertex AI Feature Store, Feast) exist to solve exactly this, but add infrastructure, cost, and concepts. The data volume here is small (synthetic users, one demo deployment).

## Options considered
1. **Managed feature store** (Vertex AI Feature Store) — online/offline consistency out of the box; recurring cost and setup, GCP lock-in, no local equivalent.
2. **Self-hosted Feast** — portable, but another system to run and learn.
3. **BigQuery `features` tables for batch + the shared `ml/features` module for online (ADR-0002)**, with point-in-time and parity tests.

## Decision
Option 3. Batch features are written to BigQuery `features` tables (DuckDB/Parquet locally) keyed by `user_pseudo_id`, entity/date, and `feature_version`. Online features are computed by the backend with the same code. Consistency is enforced by tests, not by infrastructure.

## Consequences
- Positive: no extra service or cost; everything runs locally.
- Negative: no feature catalogue, no shared online store, no automatic backfills — acceptable at this scale.
- Revisit if: many models share many features, or online features must be precomputed for latency.
