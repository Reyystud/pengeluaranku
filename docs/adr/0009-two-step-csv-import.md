# ADR-0009: Two-step CSV import (preview → commit)

- Status: accepted
- Date: 2026-11-19
- PRD sections affected: 3.3 (C3), 6.3, 7.2.3, 7.2.4, 13.2

## Context
PRD v1.0 said "valid rows are imported, invalid rows get errors"; v2.0 said "one bad row fails the whole import". Both have problems: partial imports leave the ledger in an unclear state, and all-or-nothing without feedback frustrates users with a 500-row bank export containing one bad date.

## Options considered
1. **Best-effort single step** (insert valid rows, report invalid) — partial imports; re-uploading the fixed file creates duplicates.
2. **Strict single step** (any error fails all) — safe but gives no chance to review before committing.
3. **Two steps: `preview` validates and classifies every row and writes nothing to `transactions`; `commit` inserts atomically.**

## Decision
Option 3.
- `POST /transactions/imports` stores a staged import and returns per-row status (`valid` / `invalid` / `duplicate`), normalized values, predicted categories, and error codes.
- `POST /transactions/imports/{id}/commit` with `mode=strict` (default; 422 if any row invalid) or `mode=skip_invalid` (inserts only the rows valid at preview). All inserts happen in **one DB transaction**; any error persists nothing.
- Staged imports expire after 24 h; committing an expired or already-committed import returns 409 `IMPORT_NOT_COMMITTABLE`. Re-uploading a file with the same SHA-256 as a committed import returns a `FILE_ALREADY_IMPORTED` warning.

## Consequences
- Positive: the database never holds a partial import; users see and can fix problems (and override categories) before anything is saved.
- Positive: clear tests — `test_fr_02_06_preview_writes_nothing`, `test_fr_02_07_commit_is_atomic_on_db_error`.
- Negative: needs a staged-import table, a cleanup job, and two API calls / UI steps.
- Revisit if: imports become large enough that a single DB transaction is too long (currently capped at 5,000 rows / 5 MB).
