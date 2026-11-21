# Datasets of PRD 10.5. Tables are created by the export and feature jobs (partitioned by date,
# clustered by user_pseudo_id; `require_partition_filter` is set there, PRD 19.3).

locals {
  bigquery_datasets = {
    raw         = "Pseudonymized daily export of transactions and loaded synthetic datasets"
    curated     = "Cleaned tables, category_labels and anomaly_labels"
    features    = "Batch feature tables keyed by user_pseudo_id and feature_version"
    predictions = "Prediction logs from the Cloud Logging sink"
  }
}

resource "google_bigquery_dataset" "datasets" {
  for_each = local.bigquery_datasets

  dataset_id                 = each.key
  location                   = var.region
  description                = each.value
  delete_contents_on_destroy = var.force_destroy_storage

  # `raw` exports expire after 400 days (PRD 10.5).
  default_table_expiration_ms = each.key == "raw" ? 400 * 24 * 3600 * 1000 : null

  # Prediction logs keep 90 days of partitions (PRD 18.4).
  default_partition_expiration_ms = each.key == "predictions" ? 90 * 24 * 3600 * 1000 : null

  depends_on = [google_project_service.enabled]
}
