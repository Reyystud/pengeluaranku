# ADR-0003: MLflow for experiment tracking and model registry

- Status: accepted
- Date: 2026-11-19
- PRD sections affected: 3.3 (C11), 11.3, 11.5, 16.1, 16.4, 16.5, 16.7

## Context
Every training run must be traceable (params, metrics, dataset hash, split hash, feature version, git commit) and models must be versioned, promoted, and rolled back without redeploying. PRD v2.0 left this open between MLflow and Vertex AI. The whole system must also run locally without a GCP account (PRD §0.3 rule 12).

## Options considered
1. **Vertex AI Experiments + Model Registry** — managed and GCP-native; but requires a GCP project for every local run, costs money, and locks the workflow to one cloud.
2. **MLflow (tracking server + registry)** — open source, runs in Docker locally and on Cloud Run (Cloud SQL backend store, GCS artifacts) in the demo; widely known in industry.
3. **Plain files / spreadsheets** — no real registry, aliases, or lineage.

## Decision
Option 2. MLflow is used for tracking and registry. Promotion and rollback use registered-model **aliases** (`production`, `candidate`, `previous`), not the deprecated stages. The ML service resolves `models:/<name>@production` and polls for alias changes to hot-swap. Vertex AI is documented as the managed alternative.

## Consequences
- Positive: identical workflow locally and in the cloud; free; rollback is an alias move (`make rollback`).
- Negative: we operate the MLflow server ourselves in the demo (Cloud Run + Cloud SQL DB + GCS bucket, IAM-protected).
- Negative: artifact integrity is our job — `metadata.json` carries SHA-256 hashes verified at load (PRD 11.4).
- Revisit if: the project moves fully onto Vertex AI pipelines or needs managed endpoints.
