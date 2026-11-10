"""Worker configuration, read once from environment variables.

Every setting has a safe default for local development. Secrets (WORKER_TOKEN,
TURN_SECRET) have no default in production mode: the worker refuses to start
without them unless RC_DEV=1.
"""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


@dataclass(frozen=True)
class VideoSettings:
    width: int = _int("RC_VIDEO_WIDTH", 1280)
    height: int = _int("RC_VIDEO_HEIGHT", 720)
    fps: int = _int("RC_VIDEO_FPS", 30)
    bitrate_kbps: int = _int("RC_VIDEO_BITRATE_KBPS", 3000)
    # x264 speed preset: ultrafast | superfast | veryfast ... (slower = more CPU)
    x264_preset: str = os.environ.get("RC_X264_PRESET", "ultrafast")
    keyint: int = _int("RC_VIDEO_KEYINT", 60)


@dataclass(frozen=True)
class Settings:
    dev: bool = os.environ.get("RC_DEV", "0") == "1"
    bind: str = os.environ.get("RC_BIND", "127.0.0.1")
    port: int = _int("RC_PORT", 8080)
    data_dir: Path = Path(os.environ.get("RC_DATA_DIR", "/var/lib/retrocloud"))
    games_file: Path = Path(
        os.environ.get("RC_GAMES_FILE", str(Path(__file__).resolve().parent.parent / "config" / "games.json"))
    )
    systems_file: Path = Path(
        os.environ.get("RC_SYSTEMS_FILE", str(Path(__file__).resolve().parent.parent / "config" / "systems.json"))
    )
    roms_dir: Path = Path(os.environ.get("RC_ROMS_DIR", str(Path(__file__).resolve().parent.parent / "roms")))
    cores_dir: Path = Path(os.environ.get("RC_CORES_DIR", "/usr/lib/x86_64-linux-gnu/libretro"))
    web_dir: Path = Path(__file__).resolve().parent.parent / "web"
    worker_token: str = os.environ.get("RC_WORKER_TOKEN", "")
    max_sessions: int = _int("RC_MAX_SESSIONS", 2)
    display_base: int = _int("RC_DISPLAY_BASE", 100)
    # WebRTC / ICE
    stun_url: str = os.environ.get("RC_STUN_URL", "stun://stun.l.google.com:19302")
    turn_host: str = os.environ.get("RC_TURN_HOST", "")  # e.g. "34.1.2.3:3478"
    turn_secret: str = os.environ.get("RC_TURN_SECRET", "")
    public_ip: str = os.environ.get("RC_PUBLIC_IP", "")  # 1:1 NAT address (GCE external IP)
    rtp_port_min: int = _int("RC_RTP_PORT_MIN", 50000)
    rtp_port_max: int = _int("RC_RTP_PORT_MAX", 50100)
    video: VideoSettings = field(default_factory=VideoSettings)

    def validate(self) -> "Settings":
        if not self.worker_token:
            if not self.dev:
                raise SystemExit("RC_WORKER_TOKEN is required (set RC_DEV=1 for local development)")
            object.__setattr__(self, "worker_token", secrets.token_urlsafe(24))
        if len(self.worker_token) < 16 and not self.dev:
            raise SystemExit("RC_WORKER_TOKEN must be at least 16 characters")
        return self


settings = Settings().validate()
