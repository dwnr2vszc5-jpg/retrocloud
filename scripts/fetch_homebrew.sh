#!/usr/bin/env bash
# Downloads freely licensed homebrew games from their authors' official GitHub releases
# into game-worker/roms/homebrew/ (git-ignored; deploy.sh copies them to the VM).
# Only add games whose license allows redistribution, and record it in config/games.json.
#   scripts/fetch_homebrew.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/game-worker/roms/homebrew"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$DEST"

# id | GitHub repo | ROM extension inside the release asset | license file in repo
GAMES=(
  "libbet|pinobatch/libbet|gb|LICENSE"
  "croom|pinobatch/croom-nes|nes|LICENSE.txt"
)

for entry in "${GAMES[@]}"; do
  IFS='|' read -r id repo ext lic <<<"$entry"
  echo "==> $id ($repo)"
  api="https://api.github.com/repos/$repo/releases/latest"
  urls=$(curl -fsSL "$api" | python3 -c 'import json,sys; [print(a["browser_download_url"]) for a in json.load(sys.stdin)["assets"]]')
  found=""
  for url in $urls; do
    f="$TMP/$id-$(basename "$url")"
    case "$url" in
      *."$ext")
        curl -fsSL -o "$f" "$url"; found="$f" ;;
      *.zip)
        curl -fsSL -o "$f" "$url"
        mkdir -p "$TMP/$id-x"
        unzip -qo "$f" -d "$TMP/$id-x"
        cand=$(find "$TMP/$id-x" -type f -name "*.$ext" | head -1)
        [ -n "$cand" ] && found="$cand" ;;
    esac
    [ -n "$found" ] && break
  done
  if [ -z "$found" ]; then
    echo "   !! no .$ext found in the latest release of $repo - skipping" >&2
    continue
  fi
  cp "$found" "$DEST/$id.$ext"
  curl -fsSL -o "$DEST/$id.LICENSE.txt" "https://raw.githubusercontent.com/$repo/HEAD/$lic" || true
  echo "   -> roms/homebrew/$id.$ext ($(wc -c <"$DEST/$id.$ext") bytes, from $(basename "$found"))"
done
ls -la "$DEST"
