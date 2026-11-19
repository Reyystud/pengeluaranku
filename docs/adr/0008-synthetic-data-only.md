# ADR-0008: Synthetic data only for training and the public demo

- Status: accepted
- Date: 2026-11-19
- PRD sections affected: 10.1, 10.2, 9.6, 17.2, 17.1 (Demo)

## Context
Personal financial transactions are highly sensitive. Public Indonesian daily-transaction datasets with categories are scarce. The project is public (repository and demo) and must be reproducible by anyone from a fresh clone.

## Options considered
1. **Use real personal transactions** (own or volunteers') — realistic; but a privacy and consent risk, not shareable, not reproducible.
2. **Public datasets only** — shareable; few exist for Indonesian merchants and the label sets rarely match the taxonomy.
3. **Seeded synthetic generator as the primary source; public datasets only for comparison.**

## Decision
Option 3. `data_generator/` produces byte-identical datasets for the same config + seed + generator version, with archetypes, Indonesian merchants, text noise, recurring series, and labelled anomalies. Public datasets are used only after their license is recorded in `docs/DATA_SOURCES.md`, and their results are reported separately. The demo deployment holds synthetic data only and is wiped every 30 days.

## Consequences
- Positive: no privacy risk; fully reproducible; can inject known anomalies for evaluation.
- Negative: synthetic data can be too clean and evaluation can become circular (model learns the generator's assumptions). Mitigations: text noise, unseen-merchant test, a holdout generator variant (circularity check, PRD 9.6), and explicit limitations in every model card.
- Revisit if: consented real data with defined retention becomes available (requires `training_consent` and pseudonymization, PRD 17.2).
