resource "google_artifact_registry_repository" "images" {
  repository_id = "sei"
  location      = var.region
  format        = "DOCKER"
  description   = "Container images of the Smart Expense Intelligence services"

  # Keeps storage cost flat: the 10 newest versions stay, untagged ones go after a week.
  cleanup_policy_dry_run = false
  cleanup_policies {
    id     = "keep-recent"
    action = "KEEP"
    most_recent_versions {
      keep_count = 10
    }
  }
  cleanup_policies {
    id     = "delete-untagged"
    action = "DELETE"
    condition {
      tag_state  = "UNTAGGED"
      older_than = "604800s"
    }
  }

  depends_on = [google_project_service.enabled]
}
