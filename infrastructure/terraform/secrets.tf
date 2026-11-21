# Secrets are generated here and stored in Secret Manager; Cloud Run reads them as env vars
# (PRD 17.1). Their values also sit in the Terraform state, so the state bucket must stay private
# (README "Bootstrap"). Rotate by tainting the matching random_password and applying.

resource "random_password" "jwt" {
  length  = 64
  special = false
}

resource "random_password" "cursor" {
  length  = 48
  special = false
}

resource "random_password" "pseudonym" {
  length  = 48
  special = false
}

resource "random_password" "demo_user" {
  length  = 24
  special = false
}

locals {
  secret_names = [
    "jwt-secret",
    "cursor-signing-key",
    "export-pseudonym-key",
    "demo-user-password",
    "database-url",
    "mlflow-backend-store-uri",
  ]

  secret_values = {
    "jwt-secret"               = random_password.jwt.result
    "cursor-signing-key"       = random_password.cursor.result
    "export-pseudonym-key"     = random_password.pseudonym.result
    "demo-user-password"       = random_password.demo_user.result
    "database-url"             = "postgresql+psycopg://postgres:${random_password.database.result}@/sei?host=/cloudsql/${local.sql_connection}"
    "mlflow-backend-store-uri" = "postgresql+psycopg2://postgres:${random_password.database.result}@/mlflow?host=/cloudsql/${local.sql_connection}"
  }
}

resource "google_secret_manager_secret" "this" {
  for_each = toset(local.secret_names)

  secret_id = each.key
  replication {
    auto {}
  }

  depends_on = [google_project_service.enabled]
}

resource "google_secret_manager_secret_version" "this" {
  for_each = toset(local.secret_names)

  secret      = google_secret_manager_secret.this[each.key].id
  secret_data = local.secret_values[each.key]
}
