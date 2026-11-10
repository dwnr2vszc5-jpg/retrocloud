#!/usr/bin/env bash
# Runs the RetroCloud worker on this Mac (Docker Desktop, Apple Silicon or Intel) for play on
# the home network: phone, tablet, TV browser.
#   scripts/run_local_mac.sh            # build if needed, (re)start, print the address
#   scripts/run_local_mac.sh --build    # rebuild the image first
#   scripts/run_local_mac.sh --stop
#   scripts/run_local_mac.sh --token    # print the login token (do not paste it into chats)
# WebRTC needs the Mac's current LAN address. If the Wi-Fi gives the Mac a new IP (DHCP),
# video stops connecting: just run this script again (or reserve the IP in the router).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NAME=rc-local
IMAGE=retrocloud/game-worker:local
CONF="$HOME/.config/retrocloud"
DATA="$HOME/Library/Application Support/RetroCloud/sessions"
TOKEN_FILE="$CONF/worker_token"
PORT_MIN=50000 PORT_MAX=50010          # 2 sessions need far fewer than 11 UDP ports

mkdir -p "$CONF" "$DATA"
chmod 700 "$CONF"
if [ ! -s "$TOKEN_FILE" ]; then
  (umask 077; head -c 24 /dev/urandom | base64 | tr -d '/+=' >"$TOKEN_FILE")
fi

case "${1:-}" in
  --stop)  docker rm -f "$NAME" >/dev/null 2>&1 && echo "stopped"; exit 0 ;;
  --token) cat "$TOKEN_FILE"; echo; exit 0 ;;
esac

docker info >/dev/null 2>&1 || { open -a Docker; echo "waiting for Docker Desktop…"; until docker info >/dev/null 2>&1; do sleep 3; done; }

if [ "${1:-}" = "--build" ] || ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  docker build -t "$IMAGE" "$ROOT/game-worker"
fi

IP=""
for ifc in en0 en1 en2; do IP=$(ipconfig getifaddr "$ifc" 2>/dev/null || true); [ -n "$IP" ] && break; done
[ -n "$IP" ] || { echo "no LAN address found (Wi-Fi/Ethernet off?)" >&2; exit 1; }

# Tailscale (optional): also advertise the Mac's tailnet address so phones on the tailnet can
# play from anywhere (mobile data), and print the HTTPS name if `tailscale serve` is set up.
TS=""
for c in tailscale /Applications/Tailscale.app/Contents/MacOS/Tailscale; do command -v "$c" >/dev/null 2>&1 && TS=$c && break; done
TSIP=""; TSNAME=""
if [ -n "$TS" ]; then
  TSIP=$("$TS" ip -4 2>/dev/null | head -1 || true)
  TSNAME=$("$TS" status --json 2>/dev/null | python3 -c 'import json,sys;print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))' 2>/dev/null || true)
fi
ADVERTISE="$IP${TSIP:+,$TSIP}"

docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --name "$NAME" --restart unless-stopped \
  -p 8080:8080 -p "$PORT_MIN-$PORT_MAX:$PORT_MIN-$PORT_MAX/udp" \
  -e RC_BIND=0.0.0.0 -e RC_PUBLIC_IP="$ADVERTISE" -e RC_STUN_URL= \
  -e RC_RTP_PORT_MIN=$PORT_MIN -e RC_RTP_PORT_MAX=$PORT_MAX \
  -e RC_WORKER_TOKEN="$(cat "$TOKEN_FILE")" \
  -e RC_ROMS_DIR=/roms -e RC_GAMES_FILE=/app/config/games.json \
  -v "$ROOT/game-worker/roms:/roms:ro" -v "$DATA:/data" \
  --read-only --tmpfs /tmp:mode=1777,size=256m --cap-drop ALL --security-opt no-new-privileges \
  --user 10001:10001 "$IMAGE" >/dev/null

for _ in $(seq 1 60); do curl -sf -m 2 http://127.0.0.1:8080/health >/dev/null && break; sleep 2; done
curl -sf http://127.0.0.1:8080/health >/dev/null || { echo "worker did not become healthy; docker logs $NAME" >&2; exit 1; }
echo "RetroCloud is running."
echo "  On this network open:  http://$IP:8080"
if [ -n "$TSIP" ]; then
  echo "  Anywhere (Tailscale):   http://$TSIP:8080"
  [ -n "$TSNAME" ] && "$TS" serve status 2>/dev/null | grep -q 8080 && echo "  Anywhere, HTTPS:        https://$TSNAME"
fi
echo "  Token:                  scripts/run_local_mac.sh --token"
echo "  Games go in:            $ROOT/game-worker/roms/<system>/   (psx, snes, gba, megadrive, ...)"
