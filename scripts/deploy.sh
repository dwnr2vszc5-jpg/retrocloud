#!/usr/bin/env bash
# Copies the app to the VM over SSH and (re)starts the containers. Idempotent.
#   scripts/deploy.sh            # uses Terraform outputs for the address
# Requires: the VM is RUNNING and cloud-init has finished (/var/lib/retrocloud-bootstrap-done).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TF_DIR="$ROOT/infrastructure/terraform/gcp"
HOST=$(terraform -chdir="$TF_DIR" output -raw ssh | cut -d' ' -f2)
SSH=(ssh -o StrictHostKeyChecking=accept-new "$HOST")

echo "==> waiting for cloud-init on $HOST"
for _ in $(seq 1 60); do
  "${SSH[@]}" test -f /var/lib/retrocloud-bootstrap-done 2>/dev/null && break
  sleep 10
done

echo "==> syncing code"
# ROMs are NOT part of the app/image (they can be GBs): only the built-in TestPad goes with the code
rsync -az --delete --exclude '.git' --exclude '__pycache__' --exclude '.terraform*' --exclude 'node_modules' \
  --include '/game-worker/roms/testpad/***' --exclude '/game-worker/roms/*' \
  --exclude 'terraform.tfstate*' --exclude '*.tfvars' --exclude 'docker/.env' \
  "$ROOT/game-worker" "$ROOT/docker" "$HOST:/srv/retrocloud/app/"

echo "==> syncing ROM catalog (only legally redistributable content!)"
rsync -az "$ROOT/game-worker/config/games.json" "$HOST:/srv/retrocloud/roms/games.json"
"${SSH[@]}" 'mkdir -p /srv/retrocloud/roms/{nes,snes,gb,gbc,gba,sms,gg,md,segacd,psx,pce,ws,atari2600,arcade,neogeo,bios}'
# everything under game-worker/roms/ (per-system folders like roms/psx/, roms/bios/) except build sources
rsync -az --exclude '.*' --exclude '*.s' --exclude '*.cfg' --exclude '*.py' --exclude '*.chr' --exclude '*.o' \
  "$ROOT/game-worker/roms/" "$HOST:/srv/retrocloud/roms/"

echo "==> building and starting containers"
# sudo: .env links to the root-only secrets file (/srv/retrocloud/env, mode 0700)
"${SSH[@]}" 'cd /srv/retrocloud/app/docker && ln -sf /srv/retrocloud/env/worker.env .env && sudo docker compose build --pull worker && sudo systemctl restart retrocloud.service && sudo docker compose ps'

echo "==> health"
"${SSH[@]}" 'curl -fsS http://127.0.0.1:8080/health; echo'
URL=$(terraform -chdir="$TF_DIR" output -raw url)
echo
echo "Open $URL  (worker token: ssh $HOST sudo grep RC_WORKER_TOKEN /srv/retrocloud/env/worker.env)"
