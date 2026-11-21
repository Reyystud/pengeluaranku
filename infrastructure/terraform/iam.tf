# One service account per workload with the minimum roles (PRD 17.1, "Least privilege").

locals {
  service_accounts = {
    frontend      = "Frontend Cloud Run service"
    backend       = "Backend API and migration job"
    worker        = "Worker (internal endpoints, relay, batch jobs)"
    "ml-service"  = "ML inference service"
    mlflow        = "MLflow tracking server"
    pipelines     = "Training, export and drift Cloud Run job"
    scheduler     = "Cloud Scheduler caller"
    "pubsub-push" = "Pub/Sub push delivery to the worker"
    deployer      = "GitHub Actions deployer (Workload Identity Federation)"
  }

  # Secret Manager access per service account, at the level of one secret.
  secret_access = {
    backend   = ["jwt-secret", "cursor-signing-key", "export-pseudonym-key", "demo-user-password", "database-url"]
    worker    = ["jwt-secret", "cursor-signing-key", "export-pseudonym-key", "demo-user-password", "database-url"]
    mlflow    = ["mlflow-backend-store-uri"]
    pipelines = ["database-url", "export-pseudonym-key"]
  }

  secret_bindings = {
    for pair in flatten([
      for sa, names in local.secret_access : [for name in names : { sa = sa, name = name }]
    ]) : "${pair.sa}/${pair.name}" => pair
  }
}

resource "google_service_account" "sa" {
  for_each = local.service_accounts

  account_id   = "sei-${each.key}"
  display_name = each.value

  depends_on = [google_project_service.enabled]
}

# -- project level ----------------------------------------------------------------------------
resource "google_project_iam_member" "cloudsql_client" {
  for_each = toset(["backend", "worker", "mlflow", "pipelines"])

  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.sa[each.key].email}"
}

resource "google_project_iam_member" "metric_writer" {
  for_each = toset(["backend", "worker", "ml-service"])

  project = var.project_id
  role    = "roles/monitoring.metricWriter"
  member  = "serviceAccount:${google_service_account.sa[each.key].email}"
}

resource "google_project_iam_member" "bigquery_job_user" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.sa["pipelines"].email}"
}

resource "google_project_iam_member" "deployer_run_developer" {
  project = var.project_id
  role    = "roles/run.developer"
  member  = "serviceAccount:${google_service_account.sa["deployer"].email}"
}

# -- secrets ------------------------------------------------------------------------------------
resource "google_secret_manager_secret_iam_member" "access" {
  for_each = local.secret_bindings

  secret_id = google_secret_manager_secret.this[each.value.name].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.sa[each.value.sa].email}"
}

# -- data ---------------------------------------------------------------------------------------
resource "google_bigquery_dataset_iam_member" "pipelines_editor" {
  for_each = google_bigquery_dataset.datasets

  dataset_id = each.value.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.sa["pipelines"].email}"
}

resource "google_storage_bucket_iam_member" "pipelines_objects" {
  for_each = {
    datasets = google_storage_bucket.datasets.name
    mlflow   = google_storage_bucket.mlflow.name
    reports  = google_storage_bucket.reports.name
  }

  bucket = each.value
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.sa["pipelines"].email}"
}

resource "google_storage_bucket_iam_member" "mlflow_objects" {
  bucket = google_storage_bucket.mlflow.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.sa["mlflow"].email}"
}

resource "google_storage_bucket_iam_member" "ml_service_models" {
  bucket = google_storage_bucket.mlflow.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.sa["ml-service"].email}"
}

# -- deployer -----------------------------------------------------------------------------------
resource "google_artifact_registry_repository_iam_member" "deployer_writer" {
  repository = google_artifact_registry_repository.images.name
  location   = var.region
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.sa["deployer"].email}"
}

# Deploying a revision that runs as a service account needs `actAs` on it.
resource "google_service_account_iam_member" "deployer_act_as" {
  for_each = toset(["frontend", "backend", "worker", "ml-service", "mlflow", "pipelines"])

  service_account_id = google_service_account.sa[each.key].name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.sa["deployer"].email}"
}
