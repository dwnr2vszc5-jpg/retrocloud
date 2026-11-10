terraform {
  required_version = ">= 1.6"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 8.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
  zone    = var.zone
  # Billing Budgets API refuses user ADC credentials without a quota project;
  # bill API quota to this project instead of the gcloud client's default project.
  user_project_override = true
  billing_project       = var.project_id
}
