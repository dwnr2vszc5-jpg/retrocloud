#!/usr/bin/env bash
# Removes EVERYTHING Terraform created (VM, data disk with saves, firewall, VPC, budget)
# and then lists anything billable that is still left in the project.
#   scripts/destroy.sh
set -euo pipefail
TF_DIR="$(cd "$(dirname "$0")/../infrastructure/terraform/gcp" && pwd)"
PROJECT=$(terraform -chdir="$TF_DIR" console <<<'var.project_id' | tr -d '"')

echo "This deletes the VM AND the data disk (saves, certificates) in project $PROJECT."
read -r -p "Type 'destroy' to continue: " ok
[ "$ok" = "destroy" ] || { echo "aborted"; exit 1; }

terraform -chdir="$TF_DIR" destroy

echo "==> leftover billable resources in $PROJECT (should all be empty):"
gcloud compute instances list --project "$PROJECT" --format="table(name,zone,status)"
gcloud compute disks list --project "$PROJECT" --format="table(name,zone,sizeGb)"
gcloud compute addresses list --project "$PROJECT" --format="table(name,region,status)"
gcloud compute snapshots list --project "$PROJECT" --format="table(name,diskSizeGb)"
gcloud compute images list --project "$PROJECT" --no-standard-images --format="table(name)"
echo "Tip: to stop ALL billing for the project: gcloud projects delete $PROJECT (30-day recovery window)."
