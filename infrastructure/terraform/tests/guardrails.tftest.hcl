# Offline checks (no GCP credentials): the providers are mocked, `terraform test` only plans.
# They pin the guardrails of PRD 19.3 and 17.1 so a refactor cannot loosen them silently.

mock_provider "google" {
  mock_data "google_project" {
    defaults = {
      number = "123456789012"
    }
  }
}

mock_provider "google-beta" {}

variables {
  project_id         = "sei-test"
  billing_account_id = "000000-000000-000000"
  alert_email        = "alerts@example.com"
  github_repository  = "owner/repo"
  monthly_budget_idr = 1
}

run "cost_guardrails_hold_by_default" {
  command = plan

  assert {
    condition = alltrue([
      google_cloud_run_v2_service.frontend.template[0].scaling[0].max_instance_count <= 3,
      google_cloud_run_v2_service.backend.template[0].scaling[0].max_instance_count <= 3,
      google_cloud_run_v2_service.worker.template[0].scaling[0].max_instance_count <= 3,
      google_cloud_run_v2_service.ml_service.template[0].scaling[0].max_instance_count <= 3,
      google_cloud_run_v2_service.mlflow.template[0].scaling[0].max_instance_count <= 3,
    ])
    error_message = "every Cloud Run service must have max instances <= 3"
  }

  assert {
    condition = alltrue([
      google_cloud_run_v2_service.frontend.template[0].scaling[0].min_instance_count == 0,
      google_cloud_run_v2_service.backend.template[0].scaling[0].min_instance_count == 0,
      google_cloud_run_v2_service.worker.template[0].scaling[0].min_instance_count == 0,
      google_cloud_run_v2_service.ml_service.template[0].scaling[0].min_instance_count == 0,
      google_cloud_run_v2_service.mlflow.template[0].scaling[0].min_instance_count == 0,
    ])
    error_message = "min instances must be 0 by default"
  }

  assert {
    condition     = google_sql_database_instance.main.settings[0].tier == "db-f1-micro"
    error_message = "Cloud SQL must default to the smallest shared-core tier"
  }

  assert {
    condition     = google_sql_database_instance.main.settings[0].backup_configuration[0].backup_retention_settings[0].retained_backups == 7
    error_message = "Cloud SQL keeps 7 automated backups"
  }

  assert {
    condition     = alltrue([for t in google_billing_budget.monthly.threshold_rules : t.threshold_percent <= 1.0]) && length(google_billing_budget.monthly.threshold_rules) == 4
    error_message = "budget alerts at 50, 90 and 100 percent plus the forecast"
  }

  assert {
    condition     = toset([for t in google_billing_budget.monthly.threshold_rules : t.threshold_percent]) == toset([0.5, 0.9, 1.0])
    error_message = "budget thresholds must be 50, 90 and 100 percent"
  }

  assert {
    condition     = google_billing_budget.monthly.amount[0].specified_amount[0].units == "1" && google_billing_budget.monthly.amount[0].specified_amount[0].currency_code == "IDR"
    error_message = "the budget cap comes from monthly_budget_idr in IDR"
  }
}

run "access_is_least_privilege" {
  command = plan

  assert {
    condition     = google_cloud_run_v2_service.worker.ingress == "INGRESS_TRAFFIC_INTERNAL_ONLY"
    error_message = "the worker is internal-only"
  }

  assert {
    condition     = toset(keys(google_cloud_run_v2_service_iam_member.public)) == toset(["frontend", "backend"])
    error_message = "only frontend and backend are public"
  }

  assert {
    condition     = alltrue([for m in google_cloud_run_v2_service_iam_member.public : m.member == "allUsers"])
    error_message = "public services use allUsers invoker"
  }

  assert {
    condition = alltrue([
      for k, m in google_cloud_run_v2_service_iam_member.ml_service_callers : startswith(m.member, "serviceAccount:")
    ]) && toset(keys(google_cloud_run_v2_service_iam_member.ml_service_callers)) == toset(["backend", "worker"])
    error_message = "ml-service is callable by the backend and worker service accounts only"
  }

  assert {
    condition     = toset(keys(google_cloud_run_v2_service_iam_member.worker_callers)) == toset(["scheduler", "pubsub-push"])
    error_message = "the worker is callable by the scheduler and Pub/Sub push accounts only"
  }

  assert {
    condition     = !contains([for m in google_cloud_run_v2_service_iam_member.mlflow_callers : m.member], "allUsers")
    error_message = "mlflow must not be public"
  }

  assert {
    condition     = alltrue([for b in google_storage_bucket.datasets[*] : b.uniform_bucket_level_access && b.public_access_prevention == "enforced"])
    error_message = "buckets use uniform access and block public access"
  }

  assert {
    condition = toset(keys(google_secret_manager_secret_iam_member.access)) == toset(concat(
      [for n in ["jwt-secret", "cursor-signing-key", "export-pseudonym-key", "demo-user-password", "database-url"] : "backend/${n}"],
      [for n in ["jwt-secret", "cursor-signing-key", "export-pseudonym-key", "demo-user-password", "database-url"] : "worker/${n}"],
      ["mlflow/mlflow-backend-store-uri", "pipelines/database-url", "pipelines/export-pseudonym-key"],
    ))
    error_message = "secret access is per service account and per secret"
  }

  assert {
    condition     = google_iam_workload_identity_pool_provider.github.attribute_condition == "assertion.repository == \"owner/repo\" && assertion.ref == \"refs/heads/main\""
    error_message = "Workload Identity Federation is limited to the repository and the deploy branch"
  }
}

run "schedulers_start_paused_and_use_jakarta_time" {
  command = plan

  assert {
    condition     = alltrue([for j in google_cloud_scheduler_job.worker : j.paused && j.time_zone == "Asia/Jakarta"])
    error_message = "worker scheduler jobs start paused in Asia/Jakarta"
  }

  assert {
    condition     = alltrue([for j in google_cloud_scheduler_job.pipelines : j.paused && j.time_zone == "Asia/Jakarta"])
    error_message = "pipelines scheduler jobs start paused in Asia/Jakarta"
  }

  assert {
    condition     = length(google_cloud_scheduler_job.worker) == 9 && length(google_cloud_scheduler_job.pipelines) == 7
    error_message = "every job of PRD 15.1 is scheduled (demo-reset included in demo mode)"
  }
}

run "schedulers_can_be_unpaused" {
  command = plan

  variables {
    enable_schedulers = true
  }

  assert {
    condition     = alltrue([for j in google_cloud_scheduler_job.worker : !j.paused])
    error_message = "enable_schedulers = true unpauses the jobs"
  }
}

run "demo_reset_exists_only_in_demo_mode" {
  command = plan

  variables {
    demo_mode = false
  }

  assert {
    condition     = !contains(keys(google_cloud_scheduler_job.worker), "demo-reset")
    error_message = "demo-reset is scheduled only when DEMO_MODE is true"
  }
}

run "events_follow_prd_14_3" {
  command = plan

  assert {
    condition = alltrue([
      google_pubsub_subscription.events_worker.ack_deadline_seconds == 60,
      google_pubsub_subscription.events_worker.dead_letter_policy[0].max_delivery_attempts == 5,
      google_pubsub_subscription.events_worker.retry_policy[0].minimum_backoff == "10s",
      google_pubsub_subscription.events_worker.retry_policy[0].maximum_backoff == "600s",
      google_pubsub_subscription.events_worker.message_retention_duration == "604800s",
    ])
    error_message = "subscription settings follow PRD 14.3"
  }

  assert {
    condition     = google_pubsub_subscription.events_worker.push_config[0].push_endpoint == "https://worker-123456789012.asia-southeast2.run.app/internal/events/transaction"
    error_message = "events are pushed to the worker's internal endpoint"
  }
}

run "bigquery_raw_expires_after_400_days" {
  command = plan

  assert {
    condition     = google_bigquery_dataset.datasets["raw"].default_table_expiration_ms == 34560000000
    error_message = "raw exports expire after 400 days (PRD 10.5)"
  }

  assert {
    condition     = toset(keys(google_bigquery_dataset.datasets)) == toset(["raw", "curated", "features", "predictions"])
    error_message = "the four datasets of PRD 10.5"
  }
}

run "four_instances_are_rejected" {
  command = plan

  variables {
    max_instances = {
      frontend   = 4
      backend    = 3
      worker     = 2
      ml_service = 2
      mlflow     = 1
    }
  }

  expect_failures = [var.max_instances]
}

run "a_zero_budget_is_rejected" {
  command = plan

  variables {
    monthly_budget_idr = 0
  }

  expect_failures = [var.monthly_budget_idr]
}
