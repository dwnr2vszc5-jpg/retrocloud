locals {
  labels = { app = var.name, env = "mvp", managed-by = "terraform" }
  tag    = "${var.name}-worker"
}

data "google_project" "this" {}

resource "google_project_service" "apis" {
  for_each = toset(concat(
    ["compute.googleapis.com", "logging.googleapis.com", "monitoring.googleapis.com", "iam.googleapis.com", "cloudresourcemanager.googleapis.com"],
    var.billing_account_id != "" ? ["billingbudgets.googleapis.com"] : []
  ))
  service            = each.value
  disable_on_destroy = false
}

# ---------------- network: dedicated VPC, only the ports we need ----------------
resource "google_compute_network" "vpc" {
  name                    = "${var.name}-vpc"
  auto_create_subnetworks = false
  depends_on              = [google_project_service.apis]
}

resource "google_compute_subnetwork" "subnet" {
  name          = "${var.name}-subnet"
  ip_cidr_range = "10.10.0.0/24"
  region        = var.region
  network       = google_compute_network.vpc.id
}

resource "google_compute_firewall" "ssh" {
  name          = "${var.name}-allow-ssh-admin"
  network       = google_compute_network.vpc.name
  direction     = "INGRESS"
  source_ranges = var.admin_cidrs
  target_tags   = [local.tag]
  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
}

resource "google_compute_firewall" "web" {
  # 80 is only used by Let's Encrypt (HTTP-01) and Caddy's redirect to 443.
  name          = "${var.name}-allow-https"
  network       = google_compute_network.vpc.name
  direction     = "INGRESS"
  source_ranges = var.player_cidrs
  target_tags   = [local.tag]
  allow {
    protocol = "tcp"
    ports    = ["80", "443"]
  }
}

resource "google_compute_firewall" "webrtc" {
  name          = "${var.name}-allow-webrtc-udp"
  network       = google_compute_network.vpc.name
  direction     = "INGRESS"
  source_ranges = var.player_cidrs
  target_tags   = [local.tag]
  allow {
    protocol = "udp"
    ports    = ["${var.rtp_port_min}-${var.rtp_port_max}"]
  }
}

resource "google_compute_firewall" "turn" {
  count         = var.enable_turn ? 1 : 0
  name          = "${var.name}-allow-turn"
  network       = google_compute_network.vpc.name
  direction     = "INGRESS"
  source_ranges = var.player_cidrs
  target_tags   = [local.tag]
  allow {
    protocol = "udp"
    ports    = ["3478", "49160-49200"]
  }
  allow {
    protocol = "tcp"
    ports    = ["3478"]
  }
}
# Note: no rule for 2375/2376. The Docker daemon is never exposed.

# ---------------- identity: VM service account with log/metric write only ----------------
resource "google_service_account" "vm" {
  account_id   = "${var.name}-vm"
  display_name = "RetroCloud worker VM"
}

resource "google_project_iam_member" "vm_logs" {
  for_each = toset(["roles/logging.logWriter", "roles/monitoring.metricWriter"])
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.vm.email}"
}

# The instance-schedule policy acts through the Compute Engine service agent,
# which needs permission to stop instances (otherwise the schedule silently fails).
resource "google_project_iam_member" "scheduler_agent" {
  count      = var.nightly_stop_cron != "" ? 1 : 0
  project    = var.project_id
  role       = "roles/compute.instanceAdmin.v1"
  member     = "serviceAccount:service-${data.google_project.this.number}@compute-system.iam.gserviceaccount.com"
  depends_on = [google_project_service.apis]
}

# ---------------- storage: data disk survives VM re-creation ----------------
resource "google_compute_disk" "data" {
  name       = "${var.name}-data"
  type       = var.disk_type
  zone       = var.zone
  size       = var.data_disk_gb
  labels     = local.labels
  depends_on = [google_project_service.apis]
}

# ---------------- cost safety: nightly stop ----------------
resource "google_compute_resource_policy" "nightly_stop" {
  count  = var.nightly_stop_cron != "" ? 1 : 0
  name   = "${var.name}-nightly-stop"
  region = var.region
  instance_schedule_policy {
    vm_stop_schedule {
      schedule = var.nightly_stop_cron
    }
    time_zone = var.timezone
  }
}

# ---------------- the worker VM ----------------
resource "google_compute_instance" "worker" {
  name         = "${var.name}-worker-1"
  machine_type = var.machine_type
  zone         = var.zone
  tags         = [local.tag]
  labels       = local.labels

  boot_disk {
    initialize_params {
      image  = "ubuntu-os-cloud/ubuntu-2404-lts-amd64"
      size   = var.boot_disk_gb
      type   = var.disk_type
      labels = local.labels
    }
  }

  attached_disk {
    source      = google_compute_disk.data.id
    device_name = "rcdata"
  }

  network_interface {
    subnetwork = google_compute_subnetwork.subnet.id
    access_config {
      # Ephemeral IP: no charge while the VM is stopped (a reserved static IP is billed when idle).
      network_tier = var.network_tier
    }
  }

  scheduling {
    provisioning_model          = var.spot ? "SPOT" : "STANDARD"
    preemptible                 = var.spot
    automatic_restart           = var.spot ? false : true
    on_host_maintenance         = var.spot ? "TERMINATE" : "MIGRATE"
    instance_termination_action = (var.spot || var.max_run_hours > 0) ? "STOP" : null
    dynamic "max_run_duration" {
      for_each = var.max_run_hours > 0 ? [1] : []
      content {
        seconds = var.max_run_hours * 3600
      }
    }
  }

  shielded_instance_config {
    enable_secure_boot          = true
    enable_vtpm                 = true
    enable_integrity_monitoring = true
  }

  service_account {
    email  = google_service_account.vm.email
    scopes = ["https://www.googleapis.com/auth/logging.write", "https://www.googleapis.com/auth/monitoring.write"]
  }

  metadata = {
    ssh-keys               = "${var.ssh_user}:${trimspace(file(pathexpand(var.ssh_public_key_path)))}"
    block-project-ssh-keys = "true"
    enable-oslogin         = "FALSE"
    user-data = templatefile("${path.module}/cloud-init.yaml.tftpl", {
      ssh_user              = var.ssh_user
      idle_shutdown_minutes = var.idle_shutdown_minutes
      rtp_port_min          = var.rtp_port_min
      rtp_port_max          = var.rtp_port_max
    })
  }

  resource_policies = var.nightly_stop_cron != "" ? [google_compute_resource_policy.nightly_stop[0].id] : []

  # cloud-init only runs on first boot; changing it should not silently recreate the VM
  lifecycle {
    ignore_changes = [metadata["user-data"]]
  }

  depends_on = [google_project_iam_member.vm_logs, google_project_iam_member.scheduler_agent]
}
