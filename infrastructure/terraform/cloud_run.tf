# Cloud Run services and jobs (PRD 19.3). Min instances 0 everywhere (ml-service optionally 1),
# max instances capped by var.max_instances. Images start as a placeholder and are replaced by the
# deploy workflow (T-32); `ignore_changes` keeps Terraform from reverting them.

locals {
  secret_envs_api = {
    DATABASE_URL         = "database-url"
    JWT_SECRET           = "jwt-secret"
    CURSOR_SIGNING_KEY   = "cursor-signing-key"
    EXPORT_PSEUDONYM_KEY = "export-pseudonym-key"
    DEMO_USER_PASSWORD   = "demo-user-password"
  }

  common_api_env = {
    APP_ENV           = "demo"
    LOG_LEVEL         = "INFO"
    COOKIE_SECURE     = "true"
    CORS_ORIGINS      = local.run_urls["frontend"]
    ML_SERVICE_URL    = local.run_urls["ml-service"]
    ML_AUTH           = var.ml_auth
    EVENT_BUS         = var.event_bus
    PUBSUB_PROJECT_ID = var.project_id
    PUBSUB_TOPIC      = "transaction-events"
    DEMO_MODE         = tostring(var.demo_mode)
  }

  backend_env = merge(local.common_api_env, { ROLE = "api" })

  worker_env = merge(local.common_api_env, {
    ROLE                   = "worker"
    INTERNAL_OIDC_AUDIENCE = local.run_urls["worker"]
    INTERNAL_ALLOWED_SA = join(",", [
      google_service_account.sa["scheduler"].email,
      google_service_account.sa["pubsub-push"].email,
    ])
  })

  ml_env = {
    APP_ENV               = "demo"
    LOG_LEVEL             = "INFO"
    ML_AUTH               = var.ml_auth
    MODEL_SOURCE          = "mlflow"
    MLFLOW_TRACKING_URI   = local.run_urls["mlflow"]
    CLASSIFIER_ALIAS      = "production"
    MODEL_POLL_INTERVAL_S = "300"
    SHADOW_ENABLED        = "false" # set true while a candidate is being shadowed (PRD 16.4)
    MODELS_DIR            = "/tmp/models"
  }

  frontend_env = {
    NODE_ENV             = "production"
    BACKEND_INTERNAL_URL = local.run_urls["backend"]
  }

  mlflow_env = {
    MLFLOW_DEFAULT_ARTIFACT_ROOT = "gs://${google_storage_bucket.mlflow.name}/artifacts"
  }

  pipelines_env = {
    APP_ENV             = "demo"
    LOG_LEVEL           = "INFO"
    DATA_BACKEND        = "bigquery"
    GCP_PROJECT_ID      = var.project_id
    GCS_DATASETS_BUCKET = google_storage_bucket.datasets.name
    GCS_REPORTS_BUCKET  = google_storage_bucket.reports.name
    MLFLOW_TRACKING_URI = local.run_urls["mlflow"]
  }

  pipelines_secret_envs = {
    DATABASE_URL         = "database-url"
    EXPORT_PSEUDONYM_KEY = "export-pseudonym-key"
  }
}

# -- frontend (public) ------------------------------------------------------------------------
resource "google_cloud_run_v2_service" "frontend" {
  name                = "frontend"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    service_account                  = google_service_account.sa["frontend"].email
    timeout                          = "60s"
    max_instance_request_concurrency = 80

    scaling {
      min_instance_count = 0
      max_instance_count = var.max_instances["frontend"]
    }

    containers {
      image = var.images.frontend
      ports {
        container_port = 3000
      }
      resources {
        limits            = { cpu = "1", memory = "512Mi" }
        cpu_idle          = true
        startup_cpu_boost = true
      }
      dynamic "env" {
        for_each = local.frontend_env
        content {
          name  = env.key
          value = env.value
        }
      }
      startup_probe {
        tcp_socket {
          port = 3000
        }
        period_seconds    = 5
        timeout_seconds   = 3
        failure_threshold = 24
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].containers[0].image, client, client_version]
  }

  depends_on = [google_project_service.enabled]
}

# -- backend (public ingress; every route authenticates in the app) -----------------------------
resource "google_cloud_run_v2_service" "backend" {
  name                = "backend"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    service_account                  = google_service_account.sa["backend"].email
    timeout                          = "60s"
    max_instance_request_concurrency = 40

    scaling {
      min_instance_count = 0
      max_instance_count = var.max_instances["backend"]
    }

    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [local.sql_connection]
      }
    }

    containers {
      image = var.images.backend
      ports {
        container_port = 8000
      }
      resources {
        limits            = { cpu = "1", memory = "1Gi" } # Argon2id uses 64 MiB per hash (PRD 17.1)
        cpu_idle          = true
        startup_cpu_boost = true
      }
      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }
      dynamic "env" {
        for_each = local.backend_env
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = local.secret_envs_api
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.this[env.value].secret_id
              version = "latest"
            }
          }
        }
      }
      startup_probe {
        tcp_socket {
          port = 8000
        }
        period_seconds    = 5
        timeout_seconds   = 3
        failure_threshold = 24
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].containers[0].image, client, client_version]
  }

  depends_on = [google_secret_manager_secret_version.this, google_secret_manager_secret_iam_member.access]
}

# -- worker (internal ingress; Pub/Sub push and Cloud Scheduler call it with OIDC tokens) -------
resource "google_cloud_run_v2_service" "worker" {
  name                = "worker"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_INTERNAL_ONLY"
  deletion_protection = false

  template {
    service_account                  = google_service_account.sa["worker"].email
    timeout                          = "300s"
    max_instance_request_concurrency = 10

    scaling {
      # The outbox relay is a background thread: with EVENT_BUS=pubsub the worker must keep an
      # instance with CPU always allocated (PRD 7.11). With inmemory events it scales to zero.
      min_instance_count = var.event_bus == "pubsub" ? 1 : 0
      max_instance_count = var.max_instances["worker"]
    }

    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [local.sql_connection]
      }
    }

    containers {
      image = var.images.backend
      ports {
        container_port = 8000
      }
      resources {
        limits            = { cpu = "1", memory = "1Gi" }
        cpu_idle          = var.event_bus != "pubsub"
        startup_cpu_boost = true
      }
      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }
      dynamic "env" {
        for_each = local.worker_env
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = local.secret_envs_api
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.this[env.value].secret_id
              version = "latest"
            }
          }
        }
      }
      startup_probe {
        tcp_socket {
          port = 8000
        }
        period_seconds    = 5
        timeout_seconds   = 3
        failure_threshold = 24
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].containers[0].image, client, client_version]
  }

  depends_on = [google_secret_manager_secret_version.this, google_secret_manager_secret_iam_member.access]
}

# -- ml-service (private: IAM invoker only) -----------------------------------------------------
resource "google_cloud_run_v2_service" "ml_service" {
  name                = "ml-service"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    service_account                  = google_service_account.sa["ml-service"].email
    timeout                          = "30s"
    max_instance_request_concurrency = 20

    scaling {
      min_instance_count = var.ml_service_min_instances
      max_instance_count = var.max_instances["ml_service"]
    }

    containers {
      image = var.images.ml_service
      ports {
        container_port = 8080
      }
      resources {
        limits            = { cpu = "1", memory = "2Gi" } # PRD 9.1: the model must fit 2 GiB
        cpu_idle          = true
        startup_cpu_boost = true
      }
      dynamic "env" {
        for_each = local.ml_env
        content {
          name  = env.key
          value = env.value
        }
      }
      startup_probe {
        tcp_socket {
          port = 8080
        }
        period_seconds    = 5
        timeout_seconds   = 3
        failure_threshold = 36
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].containers[0].image, client, client_version]
  }

  depends_on = [google_project_service.enabled]
}

# -- mlflow (private; reach it with `gcloud run services proxy mlflow`) -------------------------
resource "google_cloud_run_v2_service" "mlflow" {
  name                = "mlflow"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    service_account                  = google_service_account.sa["mlflow"].email
    timeout                          = "300s"
    max_instance_request_concurrency = 20

    scaling {
      min_instance_count = 0
      max_instance_count = var.max_instances["mlflow"]
    }

    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [local.sql_connection]
      }
    }

    containers {
      image = var.images.mlflow
      ports {
        container_port = 5000
      }
      resources {
        limits            = { cpu = "1", memory = "1Gi" }
        cpu_idle          = true
        startup_cpu_boost = true
      }
      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }
      dynamic "env" {
        for_each = local.mlflow_env
        content {
          name  = env.key
          value = env.value
        }
      }
      env {
        name = "MLFLOW_BACKEND_STORE_URI"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.this["mlflow-backend-store-uri"].secret_id
            version = "latest"
          }
        }
      }
      startup_probe {
        tcp_socket {
          port = 5000
        }
        period_seconds    = 5
        timeout_seconds   = 3
        failure_threshold = 24
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].containers[0].image, client, client_version]
  }

  depends_on = [google_secret_manager_secret_version.this, google_secret_manager_secret_iam_member.access]
}

# -- Cloud Run jobs -----------------------------------------------------------------------------
# `migrate` runs Alembic with the backend image (T-32 runs it before each deploy).
resource "google_cloud_run_v2_job" "migrate" {
  name                = "migrate"
  location            = var.region
  deletion_protection = false

  template {
    template {
      service_account = google_service_account.sa["backend"].email
      timeout         = "600s"
      max_retries     = 0

      volumes {
        name = "cloudsql"
        cloud_sql_instance {
          instances = [local.sql_connection]
        }
      }

      containers {
        image   = var.images.backend
        command = ["sh", "-c", "alembic upgrade head"]
        resources {
          limits = { cpu = "1", memory = "512Mi" }
        }
        volume_mounts {
          name       = "cloudsql"
          mount_path = "/cloudsql"
        }
        env {
          name = "DATABASE_URL"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.this["database-url"].secret_id
              version = "latest"
            }
          }
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].template[0].containers[0].image, client, client_version]
  }

  depends_on = [google_secret_manager_secret_version.this, google_secret_manager_secret_iam_member.access]
}

# `pipelines` is one job for training, exports and drift: Cloud Scheduler overrides its args with
# the job name from PRD 15.1 (scheduler.tf).
resource "google_cloud_run_v2_job" "pipelines" {
  name                = "pipelines"
  location            = var.region
  deletion_protection = false

  template {
    template {
      service_account = google_service_account.sa["pipelines"].email
      timeout         = "3600s"
      max_retries     = 1

      volumes {
        name = "cloudsql"
        cloud_sql_instance {
          instances = [local.sql_connection]
        }
      }

      containers {
        image   = var.images.pipelines
        command = ["python", "-m", "pipelines"]
        resources {
          limits = { cpu = "2", memory = "4Gi" }
        }
        volume_mounts {
          name       = "cloudsql"
          mount_path = "/cloudsql"
        }
        dynamic "env" {
          for_each = local.pipelines_env
          content {
            name  = env.key
            value = env.value
          }
        }
        dynamic "env" {
          for_each = local.pipelines_secret_envs
          content {
            name = env.key
            value_source {
              secret_key_ref {
                secret  = google_secret_manager_secret.this[env.value].secret_id
                version = "latest"
              }
            }
          }
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].template[0].containers[0].image, client, client_version]
  }

  depends_on = [google_secret_manager_secret_version.this, google_secret_manager_secret_iam_member.access]
}

# -- who may call what --------------------------------------------------------------------------
resource "google_cloud_run_v2_service_iam_member" "public" {
  for_each = {
    frontend = google_cloud_run_v2_service.frontend.name
    backend  = google_cloud_run_v2_service.backend.name
  }

  name     = each.value
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service_iam_member" "ml_service_callers" {
  for_each = toset(["backend", "worker"])

  name     = google_cloud_run_v2_service.ml_service.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.sa[each.key].email}"
}

resource "google_cloud_run_v2_service_iam_member" "mlflow_callers" {
  # Static keys: the service account emails are only known after apply.
  for_each = merge(
    {
      "ml-service" = "serviceAccount:${google_service_account.sa["ml-service"].email}"
      "pipelines"  = "serviceAccount:${google_service_account.sa["pipelines"].email}"
    },
    { for member in var.mlflow_invokers : member => member },
  )

  name     = google_cloud_run_v2_service.mlflow.name
  location = var.region
  role     = "roles/run.invoker"
  member   = each.value
}

resource "google_cloud_run_v2_service_iam_member" "worker_callers" {
  for_each = toset(["scheduler", "pubsub-push"])

  name     = google_cloud_run_v2_service.worker.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.sa[each.key].email}"
}

resource "google_cloud_run_v2_job_iam_member" "scheduler_runs_pipelines" {
  name     = google_cloud_run_v2_job.pipelines.name
  location = var.region
  role     = "roles/run.jobsExecutorWithOverrides"
  member   = "serviceAccount:${google_service_account.sa["scheduler"].email}"
}
