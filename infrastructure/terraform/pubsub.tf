# Transaction events (PRD 14.3): push to the worker, 60 s ack deadline, exponential retry 10-600 s,
# 5 delivery attempts, dead-letter topic with a pull subscription for inspection, 7 days retention.

resource "google_pubsub_topic" "events" {
  name                       = "transaction-events"
  message_retention_duration = "604800s"

  depends_on = [google_project_service.enabled]
}

resource "google_pubsub_topic" "events_dlq" {
  name                       = "transaction-events-dlq"
  message_retention_duration = "604800s"

  depends_on = [google_project_service.enabled]
}

resource "google_pubsub_subscription" "events_worker" {
  name                       = "transaction-events-worker"
  topic                      = google_pubsub_topic.events.id
  ack_deadline_seconds       = 60
  message_retention_duration = "604800s"

  push_config {
    push_endpoint = "${local.run_urls["worker"]}/internal/events/transaction"
    oidc_token {
      service_account_email = google_service_account.sa["pubsub-push"].email
      audience              = local.run_urls["worker"]
    }
  }

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.events_dlq.id
    max_delivery_attempts = 5
  }

  expiration_policy {
    ttl = "" # never expires
  }

  depends_on = [
    google_cloud_run_v2_service_iam_member.worker_callers,
    google_pubsub_topic_iam_member.dlq_publisher,
  ]
}

resource "google_pubsub_subscription" "events_dlq_inspect" {
  name                       = "transaction-events-dlq-inspect"
  topic                      = google_pubsub_topic.events_dlq.id
  ack_deadline_seconds       = 60
  message_retention_duration = "604800s"

  expiration_policy {
    ttl = ""
  }
}

# Dead-lettering is done by the Pub/Sub service agent: it publishes to the DLQ topic and
# acknowledges on the source subscription.
resource "google_project_service_identity" "pubsub" {
  provider = google-beta
  project  = var.project_id
  service  = "pubsub.googleapis.com"

  depends_on = [google_project_service.enabled]
}

resource "google_pubsub_topic_iam_member" "dlq_publisher" {
  topic  = google_pubsub_topic.events_dlq.name
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${google_project_service_identity.pubsub.email}"
}

resource "google_pubsub_subscription_iam_member" "dlq_subscriber" {
  subscription = google_pubsub_subscription.events_worker.name
  role         = "roles/pubsub.subscriber"
  member       = "serviceAccount:${google_project_service_identity.pubsub.email}"
}

resource "google_pubsub_topic_iam_member" "publishers" {
  for_each = toset(["backend", "worker"])

  topic  = google_pubsub_topic.events.name
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${google_service_account.sa[each.key].email}"
}
