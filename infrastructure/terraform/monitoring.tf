# Cloud Monitoring alert policies for the system layer (PRD 18.1, 18.7) and the Log Router sink
# for prediction logs (PRD 18.4). Alerts email the channel defined in budget.tf. The application
# metrics (`/metrics`) are not scraped in GCP: Managed Service for Prometheus needs a collector
# sidecar, so the demo alerts on Cloud Run, Pub/Sub and log-based metrics only. Alerts on the
# outbox backlog, drift and model quality exist in the local Prometheus rules (monitoring/) and
# arrive in GCP with the batch jobs (T-35, T-37).

locals {
  alert_channels = [google_monitoring_notification_channel.email.id]

  # Latency SLOs in milliseconds (PRD 5.3): the backend's loosest (POST /transactions) and ML inference.
  latency_slo_ms = {
    backend      = 500
    "ml-service" = 200
  }
}

# -- 5xx share of all Cloud Run requests above 2 % for 5 minutes ---------------------------------
resource "google_monitoring_alert_policy" "http_5xx" {
  display_name          = "sei: 5xx rate above 2%"
  combiner              = "OR"
  notification_channels = local.alert_channels
  documentation {
    mime_type = "text/markdown"
    content   = "More than 2% of requests returned 5xx for 5 minutes. Runbook: docs/RUNBOOK.md#job-failed"
  }

  conditions {
    display_name = "5xx / all requests"
    condition_threshold {
      filter             = "resource.type=\"cloud_run_revision\" AND metric.type=\"run.googleapis.com/request_count\" AND metric.labels.response_code_class=\"5xx\""
      denominator_filter = "resource.type=\"cloud_run_revision\" AND metric.type=\"run.googleapis.com/request_count\""
      comparison         = "COMPARISON_GT"
      threshold_value    = 0.02
      duration           = "300s"

      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_RATE"
        cross_series_reducer = "REDUCE_SUM"
      }
      denominator_aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_RATE"
        cross_series_reducer = "REDUCE_SUM"
      }
    }
  }

  depends_on = [google_project_service.enabled]
}

# -- P95 request latency over the SLO for 10 minutes ---------------------------------------------
resource "google_monitoring_alert_policy" "latency_p95" {
  for_each = local.latency_slo_ms

  display_name          = "sei: ${each.key} P95 latency above ${each.value} ms"
  combiner              = "OR"
  notification_channels = local.alert_channels
  documentation {
    mime_type = "text/markdown"
    content   = "P95 latency of ${each.key} is above its SLO of ${each.value} ms for 10 minutes. Runbook: docs/RUNBOOK.md#inference-latency-p95-high"
  }

  conditions {
    display_name = "P95 request latency"
    condition_threshold {
      filter          = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${each.key}\" AND metric.type=\"run.googleapis.com/request_latencies\""
      comparison      = "COMPARISON_GT"
      threshold_value = each.value
      duration        = "600s"

      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_PERCENTILE_95"
      }
    }
  }

  depends_on = [google_project_service.enabled]
}

# -- any message in the dead-letter subscription -------------------------------------------------
resource "google_monitoring_alert_policy" "dlq" {
  display_name          = "sei: messages in the event dead-letter queue"
  combiner              = "OR"
  notification_channels = local.alert_channels
  documentation {
    mime_type = "text/markdown"
    content   = "transaction-events-dlq holds messages (an event failed 5 deliveries). Runbook: docs/RUNBOOK.md#dlq-messages--0"
  }

  conditions {
    display_name = "undelivered messages in the DLQ"
    condition_threshold {
      filter          = "resource.type=\"pubsub_subscription\" AND resource.labels.subscription_id=\"${google_pubsub_subscription.events_dlq_inspect.name}\" AND metric.type=\"pubsub.googleapis.com/subscription/num_undelivered_messages\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "60s"

      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_MAX"
      }
    }
  }

  depends_on = [google_project_service.enabled]
}

# -- a Cloud Run job execution failed ------------------------------------------------------------
resource "google_monitoring_alert_policy" "job_failed" {
  display_name          = "sei: a Cloud Run job failed"
  combiner              = "OR"
  notification_channels = local.alert_channels
  documentation {
    mime_type = "text/markdown"
    content   = "A Cloud Run job execution (migrate or pipelines) failed. Runbook: docs/RUNBOOK.md#job-failed"
  }

  conditions {
    display_name = "failed job executions"
    condition_threshold {
      filter          = "resource.type=\"cloud_run_job\" AND metric.type=\"run.googleapis.com/job/completed_execution_count\" AND metric.labels.result=\"failed\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"

      aggregations {
        alignment_period     = "300s"
        per_series_aligner   = "ALIGN_DELTA"
        cross_series_reducer = "REDUCE_SUM"
      }
    }
  }

  depends_on = [google_project_service.enabled]
}

# -- ML circuit open for 5 minutes (log-based: the backend logs every skipped call) --------------
resource "google_logging_metric" "ml_circuit_open" {
  name        = "ml_circuit_open_skips"
  description = "Backend calls to the ML service skipped because the circuit breaker is open"
  filter      = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"backend\" AND jsonPayload.event:\"ml circuit open\""

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
  }

  depends_on = [google_project_service.enabled]
}

resource "google_monitoring_alert_policy" "ml_circuit_open" {
  display_name          = "sei: ML circuit open for 5 minutes"
  combiner              = "OR"
  notification_channels = local.alert_channels
  documentation {
    mime_type = "text/markdown"
    content   = "The backend skipped ML calls in every minute of the last 5: the circuit is open and transactions are saved as needs_review. Runbook: docs/RUNBOOK.md#ml-circuit-open"
  }

  conditions {
    display_name = "skipped ML calls"
    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.ml_circuit_open.name}\" AND resource.type=\"cloud_run_revision\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "300s"

      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_DELTA"
        cross_series_reducer = "REDUCE_SUM"
      }
      trigger {
        count = 1
      }
    }
  }
}

# -- prediction logs -> BigQuery (PRD 18.4) ------------------------------------------------------
# The sink creates a day-partitioned table named after the log (run_googleapis_com_stdout) in the
# `predictions` dataset; partitions expire after 90 days (bigquery.tf). The `prediction_logs` view
# of PRD 18.4 is created by the drift job (T-35) once that table exists.
resource "google_logging_project_sink" "predictions" {
  name                   = "prediction-logs"
  destination            = "bigquery.googleapis.com/projects/${var.project_id}/datasets/${google_bigquery_dataset.datasets["predictions"].dataset_id}"
  filter                 = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"ml-service\" AND jsonPayload.event=\"prediction\""
  unique_writer_identity = true

  bigquery_options {
    use_partitioned_tables = true
  }
}

resource "google_bigquery_dataset_iam_member" "prediction_sink_writer" {
  dataset_id = google_bigquery_dataset.datasets["predictions"].dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = google_logging_project_sink.predictions.writer_identity
}

# -- Data drift (PRD 18.1, 18.3): the drift-report job logs one `drift_summary` line per run -----
resource "google_logging_metric" "drift_detected" {
  name        = "drift_report_drift_detected"
  description = "Drift report runs that found PSI above the threshold or unseen merchants above 2x their median"
  filter      = "resource.type=\"cloud_run_job\" AND resource.labels.job_name=\"pipelines\" AND jsonPayload.event=\"drift_summary\" AND jsonPayload.status=\"drift\""

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
  }

  depends_on = [google_project_service.enabled]
}

resource "google_monitoring_alert_policy" "drift_detected" {
  display_name          = "sei: data drift detected"
  combiner              = "OR"
  notification_channels = local.alert_channels
  documentation {
    mime_type = "text/markdown"
    content   = "The daily drift report found a key feature with PSI above the configured threshold, or unseen merchants above 2x their 28-day median. The HTML report is in the reports bucket under drift/<date>/. Runbook: docs/RUNBOOK.md#data-drift"
  }

  conditions {
    display_name = "drift report flagged drift"
    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.drift_detected.name}\" AND resource.type=\"cloud_run_job\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"
      aggregations {
        alignment_period   = "3600s"
        per_series_aligner = "ALIGN_SUM"
      }
      trigger {
        count = 1
      }
    }
  }

  alert_strategy {
    auto_close = "86400s"
  }
}
