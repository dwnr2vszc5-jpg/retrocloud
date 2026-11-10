# syntax=docker/dockerfile:1
# RetroCloud game worker: RetroArch + Mesa llvmpipe + Xvfb + PulseAudio + GStreamer WebRTC.
# CPU only. No GPU, no /dev/uinput, no privileged mode.
FROM ubuntu:24.04

ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      retroarch libretro-nestopia libretro-gambatte libretro-snes9x libretro-genesisplusgx libretro-beetle-psx \
      libgl1-mesa-dri xvfb pulseaudio \
      gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-plugins-bad \
      gstreamer1.0-plugins-ugly gstreamer1.0-x gstreamer1.0-pulseaudio gstreamer1.0-nice \
      gir1.2-gst-plugins-bad-1.0 gir1.2-gst-plugins-base-1.0 \
      python3 python3-gi python3-aiohttp python3-xlib python3-pip curl tini ca-certificates \
 && rm -rf /var/lib/apt/lists/* /usr/share/doc/* /usr/share/man/*

# Optional build secret "pip_ca": CA bundle for TLS-intercepting corporate proxies.
#   docker build --secret id=pip_ca,src=/path/ca.crt .
RUN --mount=type=secret,id=pip_ca,required=false \
    if [ -s /run/secrets/pip_ca ]; then export PIP_CERT=/run/secrets/pip_ca; fi; \
    pip3 install --no-cache-dir --break-system-packages "pydantic>=2.6,<3" \
 && apt-get purge -y python3-pip && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /tmp/.X11-unix && chmod 1777 /tmp/.X11-unix \
 && useradd --uid 10001 --create-home --shell /usr/sbin/nologin rc \
 && mkdir -p /data /roms && chown rc:rc /data

WORKDIR /app
COPY worker ./worker
COPY web ./web
COPY config ./config
COPY roms ./roms-builtin

ENV RC_BIND=127.0.0.1 \
    RC_PORT=8080 \
    RC_DATA_DIR=/data \
    RC_ROMS_DIR=/app/roms-builtin \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

USER rc
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${RC_PORT}/health" || exit 1
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python3", "-m", "worker.app"]
