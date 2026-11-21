# PostgreSQL 16 for the product data and for the MLflow backend store (PRD 10.5, 19.3).
#
# Public IP with no authorised networks: nothing can reach it except through the Cloud SQL
# connector that Cloud Run mounts at /cloudsql (IAM `cloudsql.client` + TLS), so no VPC connector
# is needed. Trade-off against private IP: no connector cost, but the instance has an address.

resource "random_password" "database" {
  length  = 32
  special = false # the password goes into a URL
}

resource "google_sql_database_instance" "main" {
  name                = "sei-demo"
  region              = var.region
  database_version    = "POSTGRES_16"
  deletion_protection = var.database_deletion_protection

  settings {
    tier                        = var.database_tier
    edition                     = "ENTERPRISE"
    availability_type           = "ZONAL"
    disk_type                   = "PD_SSD"
    disk_size                   = 10
    disk_autoresize             = true
    disk_autoresize_limit       = 20
    deletion_protection_enabled = var.database_deletion_protection

    ip_configuration {
      ipv4_enabled = true
      ssl_mode     = "ENCRYPTED_ONLY"
    }

    backup_configuration {
      enabled    = true
      start_time = "20:00" # UTC, 03:00 in Jakarta
      backup_retention_settings {
        retained_backups = 7
        retention_unit   = "COUNT"
      }
    }

    maintenance_window {
      day  = 7
      hour = 20
    }
  }

  depends_on = [google_project_service.enabled]
}

resource "google_sql_database" "app" {
  name     = "sei"
  instance = google_sql_database_instance.main.name
}

resource "google_sql_database" "mlflow" {
  name     = "mlflow"
  instance = google_sql_database_instance.main.name
}

# The built-in `postgres` user owns both databases, so Alembic and MLflow can create tables in
# the public schema (PostgreSQL 15+ no longer lets other users). Narrower per-database roles need
# SQL grants that Terraform cannot run here; see DECISIONS T-31.
resource "google_sql_user" "postgres" {
  name     = "postgres"
  instance = google_sql_database_instance.main.name
  password = random_password.database.result
}
