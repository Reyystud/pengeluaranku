output "service_urls" {
  description = "Cloud Run URLs. Open the frontend; mlflow and ml-service need an IAM identity."
  value       = local.run_urls
}

output "artifact_registry" {
  description = "Image repository the build workflow pushes to."
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}"
}

output "sql_connection_name" {
  description = "Cloud SQL connection name (mounted at /cloudsql in Cloud Run)."
  value       = local.sql_connection
}

output "buckets" {
  value = local.buckets
}

output "service_accounts" {
  description = "Runtime and automation service accounts."
  value       = { for name, sa in google_service_account.sa : name => sa.email }
}

output "github_workload_identity_provider" {
  description = "Value for the GitHub variable GCP_WORKLOAD_IDENTITY_PROVIDER."
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "github_deployer_service_account" {
  description = "Value for the GitHub variable GCP_DEPLOYER_SERVICE_ACCOUNT."
  value       = google_service_account.sa["deployer"].email
}

output "demo_user_password_secret" {
  description = "Read the demo account password with: gcloud secrets versions access latest --secret=<this>"
  value       = google_secret_manager_secret.this["demo-user-password"].secret_id
}

output "paused_schedulers" {
  description = "True while the scheduler jobs are created paused."
  value       = !var.enable_schedulers
}
