terraform {
  required_version = ">= 1.6"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 8.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 8.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # State lives in a bucket you create once (see README "Bootstrap"). Partial configuration:
  #   terraform init -backend-config="bucket=<project>-tfstate"
  backend "gcs" {
    prefix = "sei/demo"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region

  # Billing budgets are charged to, and authorised against, this project's quota.
  user_project_override = true
  billing_project       = var.project_id
}

# Only for google_project_service_identity (creates the Pub/Sub service agent); GA lacks it.
provider "google-beta" {
  project               = var.project_id
  region                = var.region
  user_project_override = true
  billing_project       = var.project_id
}
