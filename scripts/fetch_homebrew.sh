#!/usr/bin/env bash
# Downloads freely licensed homebrew games from their authors' official GitHub releases/repos
# into game-worker/roms/homebrew/ (git-ignored; deploy.sh copies them to the VM).
# Every file is pinned to a release tag or commit and checked against its SHA-256, and no
# GitHub API call is made (the anonymous API limit is 60 requests/hour).
# Only add games whose license allows redistribution, and record it in config/games.json.
#   scripts/fetch_homebrew.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/game-worker/roms/homebrew"
mkdir -p "$DEST"
GH=https://github.com
RAW=https://raw.githubusercontent.com

# file | sha256 | ROM url | license url
GAMES=(
  "libbet.gb|3607412031c8287cf878299ce96e581e85b852dde703806343b95576fa3ff1a9|$GH/pinobatch/libbet/releases/download/v0.08/libbet.gb|$RAW/pinobatch/libbet/v0.08/LICENSE"
  "croom.nes|2ce17df1ad66a8a0533c0a8739f5b5ebe275c264924bbe350c42c5ac0394f20e|$GH/pinobatch/croom-nes/releases/download/v0.02a/croom.nes|$RAW/pinobatch/croom-nes/v0.02a/LICENSE.txt"
  "gba240p.gba|47844f7140738a06f8f3bc09780da3ab095539a250b870f614feed561d9d6f34|$GH/pinobatch/240p-test-mini/releases/download/v0.23/240pee_mb.gba|$RAW/pinobatch/240p-test-mini/v0.23/LICENSE"
  "thwaite.nes|a2df24d9c9f72e56c2fdc4c703becc47a5700ad0158da8208247635ebeb3779c|$GH/pinobatch/thwaite-nes/releases/download/v0.04/thwaite.nes|$RAW/pinobatch/thwaite-nes/v0.04/README.md"
  "nova.nes|e4780e90b9d1587489bfb797d2ca395be21371ea9262fa9f87f99324ec6960ab|$GH/NovaSquirrel/NovaTheSquirrel/releases/download/v1.0.6a/nova.nes|$RAW/NovaSquirrel/NovaTheSquirrel/v1.0.6a/LICENSE.txt"
  "ucity.gbc|9422ee2ca7b7ea1d46b58b2a429fff3f354dfd3e732dee1e7ae6220f148ce6e0|$GH/AntonioND/ucity/releases/download/v1.3/ucity.gbc|$RAW/AntonioND/ucity/v1.3/readme.rst"
  "ucity-advance.gba|069230a67939896c15cba86f0bffe31d12655597e2ac4cfed5b832e216b57bff|$GH/AntonioND/ucity-advance/releases/download/v1.0.3/ucity-advance-v1.0.3.gba|$RAW/AntonioND/ucity-advance/v1.0.3/readme.rst"
  "miniplanets.bin|e8aee1b9fedca87b638a7624709d7f6e1a2aff8a5222083346d1cd63963acbe7|$RAW/sikthehedgehog/miniplanets/0ac9c395289cc5d0837c96d45e61a27300e8eebc/Miniplanets%20REMIX%20Ver%20(REV04).bin|$RAW/sikthehedgehog/miniplanets/0ac9c395289cc5d0837c96d45e61a27300e8eebc/LICENSE.txt"
)

sha256() { if command -v sha256sum >/dev/null; then sha256sum "$1" | cut -c1-64; else shasum -a 256 "$1" | cut -c1-64; fi; }

fail=0
for entry in "${GAMES[@]}"; do
  IFS='|' read -r file sum url lic <<<"$entry"
  out="$DEST/$file"
  if [ -f "$out" ] && [ "$(sha256 "$out")" = "$sum" ]; then
    echo "   ok   $file (already present)"; continue
  fi
  echo "==> $file"
  if ! curl -fsSL --retry 3 -o "$out.part" "$url"; then
    echo "   !! download failed: $url" >&2; rm -f "$out.part"; fail=1; continue
  fi
  if [ "$(sha256 "$out.part")" != "$sum" ]; then
    echo "   !! checksum mismatch for $file - not installed" >&2; rm -f "$out.part"; fail=1; continue
  fi
  mv "$out.part" "$out"
  curl -fsSL --retry 3 -o "$DEST/${file%.*}.LICENSE.txt" "$lic" || echo "   (license text not fetched: $lic)" >&2
  echo "   -> roms/homebrew/$file ($(wc -c <"$out" | tr -d ' ') bytes)"
done
ls -la "$DEST"
exit $fail
