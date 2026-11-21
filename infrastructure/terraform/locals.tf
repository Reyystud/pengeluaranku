data "google_project" "this" {
  project_id = var.project_id
}

locals {
  project_number = data.google_project.this.number

  # Cloud Run's deterministic URL (https://<service>-<project number>.<region>.run.app). Using it
  # instead of the resource's `uri` avoids dependency cycles between the services that call each
  # other.
  run_urls = {
    for name in ["frontend", "backend", "worker", "ml-service", "mlflow"] :
    name => "https://${name}-${local.project_number}.${var.region}.run.app"
  }

  sql_connection = google_sql_database_instance.main.connection_name

  buckets = {
    datasets = "${var.project_id}-datasets"
    mlflow   = "${var.project_id}-mlflow"
    reports  = "${var.project_id}-reports"
  }
}
