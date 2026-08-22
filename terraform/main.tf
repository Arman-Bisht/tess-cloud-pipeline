terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

variable "project_id" {
  type        = string
  description = "The GCP project ID"
}

variable "region" {
  type        = string
  default     = "us-central1"
  description = "The GCP region to deploy to"
}

variable "telegram_bot_token" {
  type        = string
  description = "Telegram bot token"
  sensitive   = true
}

variable "telegram_chat_id" {
  type        = string
  description = "Telegram chat ID"
}

# 1. Enable Required APIs
resource "google_project_service" "cloud_run" {
  service            = "run.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "scheduler" {
  service            = "cloudscheduler.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "secretmanager" {
  service            = "secretmanager.googleapis.com"
  disable_on_destroy = false
}

# 2. Secret Manager for Telegram Secrets
resource "google_secret_manager_secret" "telegram_token" {
  secret_id = "telegram-bot-token"
  replication {
    auto {}
  }
  depends_on = [google_project_service.secretmanager]
}

resource "google_secret_manager_secret_version" "telegram_token_version" {
  secret      = google_secret_manager_secret.telegram_token.id
  secret_data = var.telegram_bot_token
}

# 3. Cloud Storage Bucket for SQLite State
resource "google_storage_bucket" "state_bucket" {
  name          = "${var.project_id}-astrohunter-state"
  location      = "US"
  force_destroy = true
  uniform_bucket_level_access = true
  
  # Standard class fits Free Tier limits (5GB)
  storage_class = "STANDARD"
}

# 4. Service Account for Cloud Run
resource "google_service_account" "cloud_run_sa" {
  account_id   = "astrohunter-run-sa"
  display_name = "Service Account for Astrohunter Cloud Run"
}

resource "google_project_iam_member" "secret_accessor" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.cloud_run_sa.email}"
}

resource "google_storage_bucket_iam_member" "storage_admin" {
  bucket = google_storage_bucket.state_bucket.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.cloud_run_sa.email}"
}

# 5. Cloud Run Service (Serverless Entry Point)
resource "google_cloud_run_v2_service" "astrohunter_service" {
  name     = "astrohunter-service"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.cloud_run_sa.email
    timeout         = "3600s" # 1 hour max
    
    containers {
      image = "gcr.io/${var.project_id}/astrohunter:latest" # Assume image is built and pushed here
      
      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
      }

      env {
        name  = "GCS_BUCKET_NAME"
        value = google_storage_bucket.state_bucket.name
      }
      
      env {
        name  = "TELEGRAM_CHAT_ID"
        value = var.telegram_chat_id
      }
      
      env {
        name = "TELEGRAM_BOT_TOKEN"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.telegram_token.secret_id
            version = "latest"
          }
        }
      }
    }
  }

  depends_on = [
    google_project_service.cloud_run,
    google_secret_manager_secret_version.telegram_token_version
  ]
}

# 6. Cloud Scheduler Job (Triggers every 2 hours)
resource "google_service_account" "scheduler_sa" {
  account_id   = "astrohunter-sched-sa"
  display_name = "Service Account for Astrohunter Scheduler"
}

resource "google_cloud_run_service_iam_member" "invoker" {
  location = google_cloud_run_v2_service.astrohunter_service.location
  service  = google_cloud_run_v2_service.astrohunter_service.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler_sa.email}"
}

resource "google_cloud_scheduler_job" "cron_trigger" {
  name             = "astrohunter-cron"
  description      = "Triggers Astrohunter pipeline every 2 hours"
  schedule         = "0 */2 * * *"
  time_zone        = "UTC"
  attempt_deadline = "320s"
  
  retry_config {
    retry_count = 1
  }

  http_target {
    http_method = "POST"
    uri         = google_cloud_run_v2_service.astrohunter_service.uri
    body        = base64encode(jsonencode({"batch_size": 50}))
    headers = {
      "Content-Type" = "application/json"
    }

    oidc_token {
      service_account_email = google_service_account.scheduler_sa.email
    }
  }

  depends_on = [google_project_service.scheduler]
}
