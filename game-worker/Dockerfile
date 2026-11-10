# syntax=docker/dockerfile:1
# RetroCloud game worker: RetroArch + Mesa llvmpipe + Xvfb + PulseAudio + GStreamer WebRTC.
# CPU only. No GPU, no /dev/uinput, no privileged mode.

# ---- cores Ubuntu does not package: built from pinned upstream commits ----
FROM ubuntu:24.04 AS cores
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential git ca-certificates zlib1g-dev \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /src
# name repo full-commit-SHA build-dir extra-make-args ("-" = none); one core per line
ARG CORES="\
pcsx_rearmed https://github.com/libretro/pcsx_rearmed 9f8b6f248e073f03c530efda7c4cc60a7e2ecafc . -f:Makefile.libretro;\
stella2014 https://github.com/libretro/stella2014-libretro 7d1361e407e63f29e52892655069e5fb4096e691 . -;\
fbneo https://github.com/libretro/FBNeo a836e52198aa5ce1f54be7b050e44872a1223797 src/burner/libretro -"
RUN set -eu; mkdir -p /out; IFS=';'; \
    for spec in $CORES; do \
      IFS=' '; set -- $spec; name=$1 repo=$2 commit=$3 dir=$4 args=$5; \
      [ "$args" = "-" ] && args="" || args=$(echo "$args" | tr ':' ' '); \
      git init -q "$name"; \
      git -C "$name" fetch -q --depth 1 "$repo" "$commit"; \
      git -C "$name" checkout -q FETCH_HEAD; \
      git -C "$name" submodule update -q --init --depth 1; \
      make -C "$name/$dir" -j"$(nproc)" $args; \
      cp "$name/$dir/${name}_libretro.so" /out/; \
    done; ls -la /out

FROM ubuntu:24.04
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      retroarch libretro-nestopia libretro-gambatte libretro-snes9x libretro-genesisplusgx \
      libretro-mgba libretro-beetle-pce-fast libretro-beetle-wswan \
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

# One arch-independent cores directory: distro cores + the ones built above.
COPY --from=cores /out/ /opt/libretro/
RUN for f in /usr/lib/*-linux-gnu/libretro/*_libretro.so; do ln -s "$f" /opt/libretro/; done \
 && ls /opt/libretro

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
    RC_CORES_DIR=/opt/libretro \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

USER rc
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${RC_PORT}/health" || exit 1
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python3", "-m", "worker.app"]
