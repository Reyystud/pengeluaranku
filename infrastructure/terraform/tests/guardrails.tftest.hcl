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
      ["deployer/demo-user-password"],
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
    condition     = length(google_cloud_scheduler_job.worker) == 10 && length(google_cloud_scheduler_job.pipelines) == 6
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

run "pubsub_mode_keeps_the_relay_alive_and_inmemory_scales_to_zero" {
  command = plan

  variables {
    event_bus = "pubsub"
  }

  assert {
    condition     = google_cloud_run_v2_service.worker.template[0].scaling[0].min_instance_count == 1
    error_message = "the outbox relay needs one always-on worker instance when EVENT_BUS=pubsub"
  }

  assert {
    condition     = google_cloud_run_v2_service.worker.template[0].containers[0].resources[0].cpu_idle == false
    error_message = "the relay thread needs CPU outside requests"
  }

  assert {
    condition     = google_cloud_run_v2_service.backend.template[0].scaling[0].min_instance_count == 0
    error_message = "only the worker is kept warm"
  }
}

run "alerts_cover_the_system_layer_of_prd_18_1" {
  command = plan

  assert {
    condition     = google_monitoring_alert_policy.http_5xx.conditions[0].condition_threshold[0].threshold_value == 0.02 && google_monitoring_alert_policy.http_5xx.conditions[0].condition_threshold[0].duration == "300s"
    error_message = "5xx alert: more than 2 percent for 5 minutes"
  }

  assert {
    condition = alltrue([
      for name, p in google_monitoring_alert_policy.latency_p95 :
      p.conditions[0].condition_threshold[0].duration == "600s" && p.conditions[0].condition_threshold[0].threshold_value == (name == "backend" ? 500 : 200)
    ]) && toset(keys(google_monitoring_alert_policy.latency_p95)) == toset(["backend", "ml-service"])
    error_message = "P95 latency alerts: 10 minutes, SLO 500 ms backend and 200 ms ml-service"
  }

  assert {
    condition     = google_monitoring_alert_policy.dlq.conditions[0].condition_threshold[0].threshold_value == 0
    error_message = "any DLQ message alerts"
  }

  assert {
    condition     = google_monitoring_alert_policy.ml_circuit_open.conditions[0].condition_threshold[0].duration == "300s"
    error_message = "circuit open alert after 5 minutes"
  }

  assert {
    condition = alltrue([
      for p in concat(
        [google_monitoring_alert_policy.http_5xx, google_monitoring_alert_policy.dlq, google_monitoring_alert_policy.job_failed, google_monitoring_alert_policy.ml_circuit_open, google_monitoring_alert_policy.drift_detected],
        values(google_monitoring_alert_policy.latency_p95)
      ) : length(p.notification_channels) == 1 && strcontains(p.documentation[0].content, "docs/RUNBOOK.md#")
    ])
    error_message = "every alert notifies the email channel and links its runbook entry"
  }

  assert {
    condition     = strcontains(google_monitoring_alert_policy.http_5xx.documentation[0].content, "RUNBOOK.md#backend-5xx-rate-high") && strcontains(google_monitoring_alert_policy.job_failed.documentation[0].content, "RUNBOOK.md#job-failed")
    error_message = "the 5xx alert and the failed-job alert link to their own runbook entries"
  }
}

run "prediction_logs_go_to_a_partitioned_bigquery_table_for_90_days" {
  command = plan

  assert {
    condition     = google_logging_project_sink.predictions.filter == "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"ml-service\" AND jsonPayload.event=\"prediction\""
    error_message = "the sink selects only prediction log lines of ml-service"
  }

  assert {
    condition     = google_logging_project_sink.predictions.bigquery_options[0].use_partitioned_tables == true && google_logging_project_sink.predictions.unique_writer_identity == true
    error_message = "partitioned table and a dedicated writer identity"
  }

  assert {
    condition     = google_bigquery_dataset.datasets["predictions"].default_partition_expiration_ms == 7776000000 && google_bigquery_dataset.datasets["curated"].default_partition_expiration_ms == null
    error_message = "only prediction logs expire after 90 days"
  }
}

run "drift_alert_reads_the_drift_summary_log_line_of_the_pipelines_job" {
  command = plan

  assert {
    condition     = strcontains(google_logging_metric.drift_detected.filter, "jsonPayload.event=\"drift_summary\"") && strcontains(google_logging_metric.drift_detected.filter, "jsonPayload.status=\"drift\"") && strcontains(google_logging_metric.drift_detected.filter, "resource.labels.job_name=\"pipelines\"")
    error_message = "the metric counts drift_summary lines with status drift from the pipelines job"
  }

  assert {
    condition     = google_monitoring_alert_policy.drift_detected.conditions[0].condition_threshold[0].threshold_value == 0
    error_message = "any drift run alerts"
  }
}
