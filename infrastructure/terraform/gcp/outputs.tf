output "external_ip" {
  description = "Ephemeral: changes after every stop/start. The VM refreshes RC_DOMAIN on boot."
  value       = google_compute_instance.worker.network_interface[0].access_config[0].nat_ip
}

output "ssh" {
  value = "ssh ${var.ssh_user}@${google_compute_instance.worker.network_interface[0].access_config[0].nat_ip}"
}

output "url" {
  value = "https://${replace(google_compute_instance.worker.network_interface[0].access_config[0].nat_ip, ".", "-")}.sslip.io"
}

output "instance_name" {
  value = google_compute_instance.worker.name
}

output "zone" {
  value = var.zone
}
