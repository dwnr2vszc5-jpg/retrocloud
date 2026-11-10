#!/usr/bin/env bash
# Manual VM control. Reads instance name/zone from Terraform outputs.
#   scripts/vm.sh start|stop|status|ssh|ip|logs
set -euo pipefail
TF_DIR="$(cd "$(dirname "$0")/../infrastructure/terraform/gcp" && pwd)"
out() { terraform -chdir="$TF_DIR" output -raw "$1"; }
NAME=$(out instance_name)
ZONE=$(out zone)

case "${1:-status}" in
  start)
    gcloud compute instances start "$NAME" --zone "$ZONE"
    echo "New URL (ephemeral IP changes on every start):"
    terraform -chdir="$TF_DIR" refresh -compact-warnings >/dev/null && out url && echo
    ;;
  stop)
    # STOPPED: vCPU/RAM not billed; disks (~$3-4/month for 30 GB pd-balanced) still are.
    gcloud compute instances stop "$NAME" --zone "$ZONE"
    ;;
  status)
    gcloud compute instances describe "$NAME" --zone "$ZONE" \
      --format="table(name,status,machineType.basename(),scheduling.provisioningModel,networkInterfaces[0].accessConfigs[0].natIP)"
    ;;
  ip)  gcloud compute instances describe "$NAME" --zone "$ZONE" --format="value(networkInterfaces[0].accessConfigs[0].natIP)" ;;
  ssh) exec ssh "$(terraform -chdir="$TF_DIR" output -raw ssh | cut -d' ' -f2)" ;;
  logs)
    gcloud logging read "resource.type=gce_instance AND resource.labels.instance_id=$(gcloud compute instances describe "$NAME" --zone "$ZONE" --format='value(id)')" \
      --limit 50 --freshness 1h --format="value(timestamp,jsonPayload.message,textPayload)"
    ;;
  *) echo "usage: $0 start|stop|status|ssh|ip|logs" >&2; exit 2 ;;
esac
