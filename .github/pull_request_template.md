## Summary

<!-- What does this PR do, in 1–3 sentences? -->

## Task and requirements

- Task: T-NN
- Requirement IDs touched: <!-- e.g. FR-02.06, FR-02.07 -->
- PRD sections followed: <!-- e.g. §7.2.3, §13.2 -->

## Tests added / updated

<!-- Test names should reference requirement IDs, e.g. test_fr_02_07_commit_is_atomic_on_db_error -->
-

## Docs updated

- [ ] `docs/PROGRESS.md` (task status + handoff note)
- [ ] `docs/DECISIONS.md` / new ADR (if a decision was made)
- [ ] PRD section updated (if a contract changed: DB, API, event, ML request/response)
- [ ] Other: <!-- README, API.md, MODEL_EVALUATION.md, … -->

## Checklist (PRD §0.3)

- [ ] `make check` passes and `docker compose up` still starts
- [ ] No invented numbers — metrics come from a real run (MLflow run ID / test report) or say `[TBD after run]`
- [ ] No hardcoded ML thresholds in business code
- [ ] No sensitive data in logs (descriptions, merchants, amounts tied to a user, tokens, passwords)
- [ ] No secrets, real personal data, or large datasets committed
- [ ] Every user-scoped query filters by `user_id` (repository helpers)
- [ ] Money uses `Decimal` / `NUMERIC` / JSON strings — no floats
- [ ] Alembic migration added (if schema changed)
- [ ] No new library outside PRD §6.5 without a `DECISIONS.md` line
- [ ] Nothing from the non-goals list (PRD §3.2)

## Screenshots (UI changes)

<!-- optional -->
