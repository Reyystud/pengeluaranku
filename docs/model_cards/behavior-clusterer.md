# Model card: behavior-clusterer (version clustering-1)

## Intended use
Assigns each user to one of four spending-style segments with 2 to 3 traits ("your savings rate is higher than 80% of similar users"). Shown only on the Intelligence page; computed weekly from the user's last complete budget periods.

## Out-of-scope use
Not for credit, pricing, marketing targeting or any decision about a person. Segments are descriptions of spending patterns, not of people.

## Training data
Synthetic dataset `synthetic/v1` (2,000 users with at least 2 complete periods). Features cover each user's last 3 complete periods. Archetypes from the generator are used only as a sanity check, never as a training label.

## Features
PRD 11.2.4: average purchase, monthly expense, purchases per day, expense category shares (centred log-ratio in model space), weekend share, recurring share, small-purchase share, income regularity, savings rate. Missing income features are imputed with the median; everything is standardized. Code: `ml/clustering/features.py`, shared by training and the backend.

## Evaluation
MLflow run `412782274ec04a02ac2f9b240653ee7e`. K-Means, k = 4 by silhouette 0.4355 (ship rule >= 0.40); mean ARI across 5 seeds 1.000 (rule >= 0.80); split-half ARI 1.000; ARI against generator archetypes 0.836 (sanity only). GMM and DBSCAN gave similar structure. Tables: `docs/MODEL_EVALUATION.md` section 6.

## Decision thresholds
Trait selection: a feature is a trait only if the user sits at least `trait_min_deviation` percentile points from the segment's median, at most `trait_count` shown (`config/clustering.yaml`).

## Limitations and risks
- The groups are crisp because the synthetic archetypes are well separated; stability on real data is unknown (`[TBD after run]`).
- Segment names were written by hand from the synthetic centroids and must be rechecked after any refit.
- Users with fewer than 2 complete periods get no segment.
- The artifact is a YAML file in `config/`, not an MLflow-registered model.

## Monitoring
None yet beyond the weekly job's `assigned`/`skipped` counts. Segment-size and centroid drift checks are not built.

## Changelog
- clustering-1: first fit on synthetic v1 (T-41).
