# Terraform: the `demo` deployment on GCP

Everything PRD 19.3 lists, in one root module with no child modules: Artifact Registry, Cloud SQL
(PostgreSQL 16), Cloud Run services (`frontend`, `backend`, `worker`, `ml-service`, `mlflow`) and
jobs (`migrate`, `pipelines`), Pub/Sub topics and subscriptions (PRD 14.3), Cloud Scheduler jobs
(PRD 15.1), Secret Manager, Cloud Storage buckets, BigQuery datasets (PRD 10.5), one service account
per workload, a Workload Identity Federation pool for GitHub, and a billing budget with email alerts.

**Status:** the configuration passes `terraform validate` and the offline tests
(`make terraform-check`). It has **not been applied to a real project** (no GCP account was used
while writing it), so expect small fixes on the first `terraform apply`.

## Cost guardrails (PRD 19.3)

- Cloud Run: min instances 0 (`ml_service_min_instances = 1` for a demo), max instances capped at
  3 per service by a validation rule.
- Cloud SQL: `db-f1-micro`, one zone, 10 GB SSD (autoresize limit 20 GB), 7 automated backups.
- No Memorystore (`REDIS_URL` stays unset; the app falls back to an in-process cache).
- No VPC connector: Cloud Run reaches Cloud SQL through the connector volume at `/cloudsql`.
- The budget alerts at 50 %, 90 % and 100 % of `monthly_budget_idr` (and on forecasted 100 %). **A
  budget does not stop spending.** Check free tiers and credits first (PRD Q4), choose the cap, and
  run `terraform destroy` when the demo is over.

## Bootstrap (once)

```bash
gcloud auth application-default login
export PROJECT=<your-project-id>
gcloud config set project $PROJECT

# State bucket: private, versioned. The state contains generated secrets, so keep it that way.
gcloud storage buckets create gs://$PROJECT-tfstate --location=asia-southeast2 \
  --uniform-bucket-level-access --public-access-prevention
gcloud storage buckets update gs://$PROJECT-tfstate --versioning

cd infrastructure/terraform
cp terraform.tfvars.example terraform.tfvars   # fill it in; it is gitignored
terraform init -backend-config="bucket=$PROJECT-tfstate"
terraform plan
terraform apply
```

You need `roles/owner` (or equivalent) on the project, and permission to create budgets on the
billing account (`roles/billing.costsManager`). `terraform apply` enables the APIs it needs.

## Variables

See `variables.tf`. Required: `project_id`, `billing_account_id`, `alert_email`,
`github_repository`, `monthly_budget_idr` (no default on purpose). `database_deletion_protection`
is off by default because PRD 19.3 ends with `terraform destroy` and the data is synthetic.

## How images get there

Cloud Run starts from Google's hello image. The deploy workflow (T-32) builds the images, pushes
them to the registry in the `artifact_registry` output and rolls revisions by digest; Terraform
ignores the image field afterwards (`lifecycle.ignore_changes`), so `apply` never reverts a deploy.

GitHub needs these repository variables: `GCP_PROJECT_ID`, optionally `GCP_REGION`, and from the
outputs `github_workload_identity_provider` and `github_deployer_service_account`:
`GCP_WORKLOAD_IDENTITY_PROVIDER` and `GCP_DEPLOYER_SERVICE_ACCOUNT`. Also create the `demo`
environment with required reviewers: it is the approval step of `deploy.yml`. Only this repository, on `deploy_branch`, can impersonate the
deployer, and no key file exists.

## Access

| Service | Who can call it |
|---|---|
| `frontend`, `backend` | everyone (`allUsers`); the backend authenticates every route itself |
| `worker` | ingress internal-only; Cloud Scheduler and Pub/Sub push service accounts (OIDC) |
| `ml-service` | the backend and worker service accounts |
| `mlflow` | the `ml-service` and `pipelines` accounts, plus `mlflow_invokers` |

Open MLflow from your machine with `gcloud run services proxy mlflow --region asia-southeast2`
after adding yourself to `mlflow_invokers`. Read the demo password with
`gcloud secrets versions access latest --secret=demo-user-password`.

If an organisation policy blocks `allUsers`, the public services need a load balancer instead.

## Contracts this configuration expects from the application

- Scheduler (paused until `enable_schedulers = true`): worker jobs call
  `POST /internal/jobs/{name}` (PRD 13.2) with an OIDC token whose audience is the worker URL;
  pipeline jobs run the `pipelines` Cloud Run job with the job name as its only argument
  (`python -m pipelines <name>`).
- Pub/Sub pushes `transaction.*` events to `POST /internal/events/transaction` on the worker.
- The `mlflow` image must read `MLFLOW_BACKEND_STORE_URI` and `MLFLOW_DEFAULT_ARTIFACT_ROOT`
  (PostgreSQL driver `psycopg2` and `google-cloud-storage` installed), and serve artifacts.
- Backend and worker read `DATABASE_URL` as `postgresql+psycopg://...@/sei?host=/cloudsql/<instance>`.

## Known gaps before the first real deploy

These belong to application tasks, not to this configuration:

1. `ML_AUTH=google_id_token`: the backend only implements `none`. Until it sends a Google ID token,
   calls to the private `ml-service` are refused and categorization falls back to `needs_review`.
   `var.ml_auth` stays `none` until then.
2. `ml-service` and `pipelines` call `mlflow` (IAM-protected) and need the same ID-token support.
3. A production `frontend` image: today's Dockerfile runs the Next.js dev server.
4. An `mlflow` image for Cloud Run (see the contract above) and a `pipelines` image target.
5. The worker `/internal/*` endpoints and the Pub/Sub relay (T-33, T-37).
6. Cloud SQL uses the built-in `postgres` user for both databases: PostgreSQL 15+ only lets a
   database's owner create tables in the public schema, and Terraform cannot run SQL grants for a
   narrower role.

## Plan and apply from CI

`.github/workflows/terraform.yml` always runs fmt, validate and the guardrail tests. Plan (pull
requests) and apply (main, approval environment `demo`) run only when the repository variable
`TF_STATE_BUCKET` is set, and then need `TF_WIF_PROVIDER`, `TF_SERVICE_ACCOUNT`, `GCP_PROJECT_ID`,
`GCP_BILLING_ACCOUNT_ID`, `MONTHLY_BUDGET_IDR` and `ALERT_EMAIL`. `TF_SERVICE_ACCOUNT` is a
high-privilege account you create and bind to the repository yourself; this configuration does not
create it. Those two jobs have not been run.

## Tests

`make terraform-check` needs Terraform 1.7 or newer and no credentials. `tests/guardrails.tftest.hcl`
plans against mocked providers and pins: max instances <= 3, min instances 0, smallest Cloud SQL
tier and 7 backups, budget thresholds, only `frontend` and `backend` public, the worker internal-only,
per-secret access, Workload Identity limited to this repository and branch, schedulers paused in
`Asia/Jakarta`, the Pub/Sub settings of PRD 14.3 and the 400-day expiry of `raw`.

## Destroy

```bash
terraform destroy
```

Buckets and datasets are removed with their contents (`force_destroy_storage`), and Cloud SQL if
`database_deletion_protection` is false. The state bucket is not managed here; delete it yourself.
