variable "project_id" {
  description = "GCP project ID (create it first; link it to the free-trial billing account)."
  type        = string
}

variable "region" {
  description = "Region. europe-west3 (Frankfurt) is the lowest-latency EU region from Turkey in our estimate; europe-west1 (Belgium) is ~15% cheaper."
  type        = string
  default     = "europe-west3"
}

variable "zone" {
  type    = string
  default = "europe-west3-a"
}

variable "name" {
  description = "Prefix for all resources."
  type        = string
  default     = "retrocloud"
}

variable "machine_type" {
  description = "Phase 1 (1 player): e2-standard-4. Phase 2 (2 players): e2-standard-4 is enough per Phase 0 measurements; e2-standard-8 / c2d-standard-8 for headroom or PS1."
  type        = string
  default     = "e2-standard-4"
}

variable "spot" {
  description = "Spot VM: ~40-70% cheaper but GCP can stop it at any time (game session lost). Fine for testing."
  type        = bool
  default     = false
}

variable "max_run_hours" {
  description = "Hard cap: GCE stops the VM after this many hours of uptime (0 = off). Cost safety net."
  type        = number
  default     = 4
}

variable "nightly_stop_cron" {
  description = "Instance schedule: stop the VM every day at this time (cron, in var.timezone). Empty = off."
  type        = string
  default     = "0 2 * * *"
}

variable "timezone" {
  type    = string
  default = "Europe/Istanbul"
}

variable "idle_shutdown_minutes" {
  description = "In-VM watchdog: power off when no game session has run for this many minutes."
  type        = number
  default     = 30
}

variable "boot_disk_gb" {
  type    = number
  default = 20
}

variable "data_disk_gb" {
  description = "Separate persistent disk for ROMs, saves, TLS certs. Survives VM re-creation. Billed even when the VM is stopped."
  type        = number
  default     = 10
}

variable "disk_type" {
  type    = string
  default = "pd-balanced"
}

variable "network_tier" {
  description = "STANDARD: first 200 GiB/month internet egress free, then ~$0.085/GiB. PREMIUM: ~$0.12/GiB, slightly better routing. Streaming is egress-heavy, so STANDARD is the default."
  type        = string
  default     = "STANDARD"
}

variable "ssh_user" {
  type    = string
  default = "rcadmin"
}

variable "ssh_public_key_path" {
  type    = string
  default = "~/.ssh/id_ed25519.pub"
}

variable "admin_cidrs" {
  description = "Who may SSH in. Use your own public IP/32. Never 0.0.0.0/0."
  type        = list(string)
  validation {
    condition     = length(var.admin_cidrs) > 0 && !contains(var.admin_cidrs, "0.0.0.0/0")
    error_message = "Set admin_cidrs to your own IP (x.x.x.x/32); 0.0.0.0/0 is not allowed for SSH."
  }
}

variable "player_cidrs" {
  description = "Who may reach HTTPS + WebRTC UDP. Restrict to your home/office IPs during the MVP if possible."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "rtp_port_min" {
  type    = number
  default = 50000
}

variable "rtp_port_max" {
  type    = number
  default = 50100
}

variable "enable_turn" {
  description = "Open TURN ports (3478 + relay range) for the optional coturn container."
  type        = bool
  default     = false
}

variable "billing_account_id" {
  description = "Billing account ID (XXXXXX-XXXXXX-XXXXXX) for the budget alert. Empty = no budget resource (create it in the console instead)."
  type        = string
  default     = ""
}

variable "budget_amount" {
  description = "Monthly budget in the billing account's currency. Alerts at 50/90/100% and forecast 100%. Alerts DO NOT stop spending."
  type        = number
  default     = 25
}

variable "budget_alert_email" {
  description = "Optional extra e-mail for budget alerts (billing admins are always notified)."
  type        = string
  default     = ""
}
