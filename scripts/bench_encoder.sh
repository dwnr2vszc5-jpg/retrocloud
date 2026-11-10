#!/usr/bin/env bash
# Measures x264 software-encoding CPU cost separately from the emulator.
# Live 30 fps source for 10 s; CPU% = (user+sys seconds) / 10 s * 100 (100% = one vCPU).
#   scripts/bench_encoder.sh            -> table on stdout
set -euo pipefail
SECS=10
run() { # $1 pattern $2 WxH $3 preset $4 kbps
  local w=${2%x*} h=${2#*x}
  local t
  t=$( { /usr/bin/time -f "%U %S" gst-launch-1.0 -q videotestsrc is-live=true pattern="$1" num-buffers=$((SECS*30)) \
      ! video/x-raw,width="$w",height="$h",framerate=30/1 ! videoconvert ! video/x-raw,format=I420 \
      ! x264enc tune=zerolatency speed-preset="$3" bitrate="$4" key-int-max=60 bframes=0 threads=2 \
      ! fakesink sync=false >/dev/null; } 2>&1 | tail -1)
  awk -v u="${t% *}" -v s="${t#* }" -v p="$1" -v r="$2" -v pr="$3" -v k="$4" -v d=$SECS \
    'BEGIN{printf "%-6s %-9s %-10s %5s kbps  CPU %5.1f%%\n", p, r, pr, k, (u+s)/d*100}'
}
echo "content resolution preset    bitrate   encoder CPU (1 vCPU = 100%)"
for res in 1280x720 960x540 854x480; do
  for preset in ultrafast superfast veryfast; do
    run snow "$res" "$preset" 3000
  done
done
run ball 1280x720 ultrafast 3000
run smpte 1280x720 ultrafast 3000
