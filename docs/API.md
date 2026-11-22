# API guide

The contract is the generated OpenAPI file, [`services/backend/openapi.json`](../services/backend/openapi.json) (56 operations today), regenerated with `make openapi` and checked by a unit test. The detailed rules are [PRD section 13](PRD.md); this page is a map.

Interactive docs: http://localhost:8000/docs when the stack is up.

## Public API (`/api/v1`)

| Area | Paths |
|---|---|
| auth | `/auth/register`, `/auth/login`, `/auth/refresh`, `/auth/logout` |
| users | `/users/me` (get, patch, delete), `/users/me/password` |
| transactions | `/transactions` (list, create), `/transactions/{id}`, `/transactions/count`, `/transactions/categorize-preview`, recategorize, confirm-category, dismiss-duplicate, bulk-categorize, bulk-delete, CSV import (`/transactions/imports...`, template) |
| categories, merchant-rules | `/categories`, `/merchant-rules`, `/merchant-rules/{id}` |
| budgets | `/budgets`, `/budgets/{id}`, `/budgets/{id}/history` |
| analytics | `/analytics/summary`, `/analytics/categories`, `/analytics/merchants`, and others |
| intelligence | `/intelligence/anomalies`, `/intelligence/forecast`, `/intelligence/recurring`, `/intelligence/insights`, `/intelligence/segment` |
| notifications | `/notifications` |
| health | `/healthz`, `/readyz` (outside `/api/v1`) |

## Rules that apply everywhere

- **Auth:** `Authorization: Bearer <access token>` (15 minutes). The refresh token is an HttpOnly `SameSite=Strict` cookie and rotates on every refresh.
- **Errors:** RFC 9457 `application/problem+json` with a stable `code`, a `request_id` and, for validation, `errors[]`. Another user's resource is `404`, never `403`.
- **Request id:** send `X-Request-ID` or one is generated; it is returned in the header and every error body.
- **Pagination:** `limit` and an opaque, signed `cursor`.
- **Idempotency:** `Idempotency-Key` is required on `POST /transactions`, CSV commit and bulk endpoints; the same key with the same body replays the first response.
- **Money:** strings with two decimals (`"25000.00"`); requests also accept numbers.
- **Dates:** ISO 8601 with offset; date filters are the user's local dates.
- **Rate limits:** register 5 per hour per IP (in memory per process), logins, writes and reads have their own limits (PRD 13.1.6); `429` carries `Retry-After`.

## Example

```bash
curl -s -X POST localhost:8000/api/v1/transactions \
  -H "Authorization: Bearer $TOKEN" -H "Idempotency-Key: $(uuidgen)" \
  -H "Content-Type: application/json" \
  -d '{"transaction_type":"expense","amount":"25000","description":"Kopi Kenangan","transaction_date":"2026-11-20T10:00:00+07:00"}'
```

The response includes the category decision (`category_status`: `rule`, `auto`, `suggested`, `needs_review`) and, when the ML service was unreachable, `ml_error`.

## Internal API (worker)

`/internal/*` is only for Pub/Sub push and Cloud Scheduler and is checked with an OIDC token (`INTERNAL_OIDC_AUDIENCE`; an empty value disables the check for local and CI use):

- `POST /internal/events/transaction`: event consumer, deduplicated by `event_id`.
- `POST /internal/jobs/{name}`: runs a batch job for all eligible users. Names: see `services/backend/app/jobs/catalogue.py` or `make jobs-run` with no argument.

## ML service (private)

| Method | Path | Purpose |
|---|---|---|
| POST | `/v1/classify` | One transaction: category, calibrated confidence, alternatives, model version |
| POST | `/v1/classify/batch` | Many, same order (CSV preview) |
| GET | `/v1/models` | Loaded model versions |
| GET | `/healthz`, `/readyz`, `/metrics` | Liveness, readiness, Prometheus |

The ML service never sees user ids or reads the user database; the backend sends the features. Events are described by the JSON Schemas in `schemas/events/`.
