# Inputs. Nothing here is a secret; secrets are generated in secrets.tf and live in Secret Manager.

variable "project_id" {
  description = "GCP project that holds everything (PRD 19.3). One project, one `demo` environment."
  type        = string
}

variable "region" {
  description = "Region for Cloud Run, Cloud SQL, Cloud Storage, Artifact Registry and BigQuery (PRD 19.3)."
  type        = string
  default     = "asia-southeast2"
}

variable "billing_account_id" {
  description = "Billing account of the project, like 0123AB-4567CD-89EF01. The budget is created on it."
  type        = string
}

variable "monthly_budget_idr" {
  description = "Monthly cost cap the budget alerts are measured against (PRD 19.3, TF_VAR_monthly_budget_idr). No default on purpose: you choose it after checking free tiers and credits (PRD Q4). Alerts do not stop spending."
  type        = number

  validation {
    condition     = var.monthly_budget_idr > 0
    error_message = "monthly_budget_idr must be positive."
  }
}

variable "budget_currency_code" {
  description = "Currency of the billing account. The budget API rejects a currency that differs from the account's."
  type        = string
  default     = "IDR"
}

variable "alert_email" {
  description = "Receives budget alerts and, later, monitoring alerts (notification channel)."
  type        = string
}

variable "github_repository" {
  description = "owner/name of the GitHub repository allowed to deploy through Workload Identity Federation."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "github_repository must look like owner/name."
  }
}

variable "deploy_branch" {
  description = "Only workflows running on this branch may impersonate the deployer service account."
  type        = string
  default     = "main"
}

variable "images" {
  description = "Container images. Defaults are Google's hello image so a first apply works before anything is built; the deploy workflow (T-32) replaces them by digest and Terraform ignores the change."
  type = object({
    frontend   = string
    backend    = string
    ml_service = string
    mlflow     = string
    pipelines  = string
  })
  default = {
    frontend   = "us-docker.pkg.dev/cloudrun/container/hello"
    backend    = "us-docker.pkg.dev/cloudrun/container/hello"
    ml_service = "us-docker.pkg.dev/cloudrun/container/hello"
    mlflow     = "us-docker.pkg.dev/cloudrun/container/hello"
    pipelines  = "us-docker.pkg.dev/cloudrun/container/hello"
  }
}

variable "max_instances" {
  description = "Cloud Run max instances per service. Cost guardrail (PRD 19.3): every service is capped at 3 or less."
  type        = map(number)
  default = {
    frontend   = 2
    backend    = 3
    worker     = 2
    ml_service = 2
    mlflow     = 1
  }

  validation {
    condition     = alltrue([for v in values(var.max_instances) : v >= 1 && v <= 3])
    error_message = "Every max_instances value must be between 1 and 3 (PRD 19.3)."
  }
}

variable "ml_service_min_instances" {
  description = "0 by default (scale to zero). Set 1 during demos or recordings to avoid cold starts."
  type        = number
  default     = 0

  validation {
    condition     = contains([0, 1], var.ml_service_min_instances)
    error_message = "ml_service_min_instances must be 0 or 1."
  }
}

variable "database_tier" {
  description = "Cloud SQL machine tier. Smallest shared-core tier for the demo (PRD 19.3)."
  type        = string
  default     = "db-f1-micro"
}

variable "database_deletion_protection" {
  description = "Blocks `terraform destroy` of the database. Off by default because the demo holds synthetic data only and PRD 19.3 ends with `terraform destroy`; turn it on if you keep real data there."
  type        = bool
  default     = false
}

variable "force_destroy_storage" {
  description = "Let `terraform destroy` delete non-empty buckets and BigQuery datasets (synthetic demo data)."
  type        = bool
  default     = true
}

variable "mlflow_invokers" {
  description = "Extra members allowed to call MLflow, like user:you@example.com. Needed to open it with `gcloud run services proxy mlflow`."
  type        = list(string)
  default     = []
}

variable "enable_schedulers" {
  description = "Cloud Scheduler jobs are created paused until every endpoint and job entrypoint they call exists (the worker jobs exist since T-37, except demo-reset; the pipelines jobs are not wired to GCP yet). Set true to unpause."
  type        = bool
  default     = false
}

variable "event_bus" {
  description = "EVENT_BUS for backend and worker. `pubsub` runs the outbox relay in the worker, which then keeps one always-on instance with CPU allocated (extra cost); `inmemory` drains in-process and scales to zero."
  type        = string
  default     = "inmemory"

  validation {
    condition     = contains(["inmemory", "pubsub"], var.event_bus)
    error_message = "event_bus must be inmemory or pubsub."
  }
}

variable "ml_auth" {
  description = "ML_AUTH for backend and ml-service. The backend only implements `none` today (see README, known gaps); `google_id_token` is the PRD target."
  type        = string
  default     = "none"
}

variable "demo_mode" {
  description = "DEMO_MODE: the demo account is re-seeded daily and registration is labelled as a demo (PRD 17.1)."
  type        = bool
  default     = true
}
