# Rollback log

One row per promotion or rollback (PRD 16.5). Versions are MLflow registry versions.

| When (UTC) | Action | Model | From | To | Actor | Reason |
|---|---|---|---|---|---|---|
| 2026-11-22 08:42:29 | promote | transaction-classifier | - | 1 | drill | forced: T-36 drill: seed production |
| 2026-11-22 08:42:40 | promote | transaction-classifier | 1 | 2 | drill | forced: T-36 drill: promote newer |
| 2026-11-22 08:43:25 | rollback | transaction-classifier | 2 | 1 | drill | T-36 drill: simulated bad version |
| 2026-11-22 08:44:10 | rollback | transaction-classifier | 1 | 2 | drill | T-36 drill: undo the drill rollback |
