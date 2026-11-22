# Cloud Scheduler (PRD 15.1). Times are Asia/Jakarta. Jobs that run in the worker POST to
# /internal/jobs/{name} with an OIDC token; jobs that run as a Cloud Run job call the Run API for
# the `pipelines` job and pass the job name as its argument.
#
# They are created paused (var.enable_schedulers = false): the worker endpoint exists since T-37,
# but the pipelines entrypoint only handles `drift-report` locally (T-35), and `demo-reset` has no
# backend job yet; an unpaused scheduler would collect 404s and failed executions for those.
# The worker endpoint is synchronous and idempotent: a retry while a run is still going answers
# `skipped` (PostgreSQL advisory lock), so the 300 s attempt deadline cannot start a second run.

locals {
  worker_jobs = {
    "daily-budget-close"    = "15 0 * * *"
    "daily-forecast"        = "0 1 * * *"
    "category-surge"        = "30 1 * * *"
    "recurring-refresh"     = "0 2 * * *"
    "daily-insights"        = "0 3 * * *"
    "cleanup"               = "30 4 * * *"
    "demo-reset"            = "0 5 * * *"
    "recurring-due-soon"    = "0 7 * * *"
    "review-queue-reminder" = "0 8 * * 1"
    "clustering-weekly"     = "0 5 * * 0"
  }

  pipeline_jobs = {
    "export-bigquery"     = "30 3 * * *"
    "feedback-export"     = "45 3 * * *"
    "purge-deleted-users" = "0 4 * * *"
    "training-weekly"     = "0 2 * * 0"
    "drift-report"        = "0 6 * * *"
    "shadow-evaluate"     = "30 6 * * *"
  }

  # demo-reset only exists on the demo deployment (DEMO_MODE=true).
  active_worker_jobs = {
    for name, cron in local.worker_jobs : name => cron
    if name != "demo-reset" || var.demo_mode
  }
}

resource "google_cloud_scheduler_job" "worker" {
  for_each = local.active_worker_jobs

  name             = each.key
  region           = var.region
  schedule         = each.value
  time_zone        = "Asia/Jakarta"
  paused           = !var.enable_schedulers
  attempt_deadline = "300s"

  retry_config {
    retry_count          = 1
    min_backoff_duration = "30s"
  }

  http_target {
    http_method = "POST"
    uri         = "${local.run_urls["worker"]}/internal/jobs/${each.key}"
    oidc_token {
      service_account_email = google_service_account.sa["scheduler"].email
      audience              = local.run_urls["worker"]
    }
  }

  depends_on = [google_project_service.enabled]
}

resource "google_cloud_scheduler_job" "pipelines" {
  for_each = local.pipeline_jobs

  name             = each.key
  region           = var.region
  schedule         = each.value
  time_zone        = "Asia/Jakarta"
  paused           = !var.enable_schedulers
  attempt_deadline = "180s"

  retry_config {
    retry_count = 0 # the Cloud Run job has its own retry
  }

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.pipelines.name}:run"
    headers = {
      "Content-Type" = "application/json"
    }
    body = base64encode(jsonencode({
      overrides = {
        containerOverrides = [{ args = [each.key] }]
      }
    }))
    oauth_token {
      service_account_email = google_service_account.sa["scheduler"].email
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }

  depends_on = [google_project_service.enabled]
}
