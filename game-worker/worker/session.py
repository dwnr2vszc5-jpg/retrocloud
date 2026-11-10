"""Game session runtime: one isolated Xvfb + PulseAudio + RetroArch trio per player.

Isolation per session:
  * own X display (:N)            -> own framebuffer, own keyboard (see input.py)
  * own PulseAudio daemon/socket  -> own audio stream, nobody else can record it
  * own HOME / saves / states dir -> save files never shared
  * own process group             -> killing one session never touches another
In the container deployment each worker additionally runs as an unprivileged user
with cgroup CPU/memory limits (docker/compose.yaml).
"""
from __future__ import annotations

import asyncio
import logging
import os
import secrets
import shutil
import signal
import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import Settings
from .games import Catalog, Game
from .input import XInputInjector
from .metrics import ProcSampler

log = logging.getLogger("retrocloud.session")

RETROARCH_CFG = """\
# generated per session - do not edit
video_driver = "gl"
video_fullscreen = "true"
video_windowed_fullscreen = "true"
video_fullscreen_x = "{w}"
video_fullscreen_y = "{h}"
video_vsync = "false"
video_threaded = "false"
video_smooth = "false"
video_font_enable = "false"
video_shader_enable = "false"
menu_driver = "rgui"
menu_show_load_content_animation = "false"
notification_show_autoconfig = "false"
pause_nonactive = "false"
audio_driver = "pulse"
audio_latency = "64"
audio_sync = "true"
input_driver = "x"
input_joypad_driver = "null"
input_autodetect_enable = "false"
config_save_on_exit = "false"
savefile_directory = "{saves}"
savestate_directory = "{states}"
system_directory = "{system}"
log_verbosity = "false"
network_cmd_enable = "false"
# player 1 bindings (must match input.BUTTON_KEYSYMS)
input_player1_up = "up"
input_player1_down = "down"
input_player1_left = "left"
input_player1_right = "right"
input_player1_a = "x"
input_player1_b = "z"
input_player1_x = "s"
input_player1_y = "a"
input_player1_l = "q"
input_player1_r = "w"
input_player1_l2 = "e"
input_player1_r2 = "r"
input_player1_start = "enter"
input_player1_select = "rshift"
# hotkeys disabled: a remote player must not reach the menu, quit or touch state files
input_exit_emulator = "nul"
input_menu_toggle = "nul"
input_save_state = "nul"
input_load_state = "nul"
input_toggle_fullscreen = "nul"
input_screenshot = "nul"
input_pause_toggle = "nul"
input_toggle_fast_forward = "nul"
input_hold_fast_forward = "nul"
input_rewind = "nul"
input_audio_mute = "nul"
input_netplay_game_watch = "nul"
input_reset = "nul"
input_shader_next = "nul"
input_shader_prev = "nul"
input_state_slot_increase = "nul"
input_state_slot_decrease = "nul"
input_volume_up = "nul"
input_volume_down = "nul"
input_frame_advance = "nul"
input_game_focus_toggle = "nul"
input_desktop_menu_toggle = "nul"
input_ai_service = "nul"
input_cheat_toggle = "nul"
input_fps_toggle = "nul"
input_grab_mouse_toggle = "nul"
input_movie_record_toggle = "nul"
input_recording_toggle = "nul"
input_streaming_toggle = "nul"
input_close_content = "nul"
"""


@dataclass
class Session:
    id: str
    token: str
    game: Game
    owner: str
    display_num: int
    dir: Path
    created_at: float = field(default_factory=time.time)
    state: str = "starting"  # starting | running | stopping | stopped | failed
    procs: dict[str, asyncio.subprocess.Process] = field(default_factory=dict)
    injector: XInputInjector | None = None
    sampler: ProcSampler = field(default_factory=ProcSampler)
    viewer_connected: bool = False
    last_activity: float = field(default_factory=time.time)
    error: str | None = None

    @property
    def display(self) -> str:
        return f":{self.display_num}"

    @property
    def pulse_socket(self) -> Path:
        return self.dir / "pulse" / "native"

    def public(self) -> dict:
        return {
            "id": self.id,
            "game_id": self.game.id,
            "game_title": self.game.title,
            "owner": self.owner,
            "state": self.state,
            "created_at": self.created_at,
            "viewer_connected": self.viewer_connected,
            "error": self.error,
        }


class SessionError(RuntimeError):
    pass


def _display_in_use(n: int) -> bool:
    return Path(f"/tmp/.X11-unix/X{n}").exists() or Path(f"/tmp/.X{n}-lock").exists()


class SessionManager:
    def __init__(self, settings: Settings, catalog: Catalog) -> None:
        self.s = settings
        self.catalog = catalog
        self.sessions: dict[str, Session] = {}
        self._lock = asyncio.Lock()

    # ---------- lifecycle ----------
    async def create(self, game_id: str, owner: str) -> Session:
        game = self.catalog.get(game_id)
        if game is None:
            raise SessionError("unknown game")
        rom, core = self.catalog.rom_path(game), self.catalog.core_path(game)
        if not rom.is_file() or not core.is_file():
            raise SessionError("game not installed on this worker")
        async with self._lock:
            active = [x for x in self.sessions.values() if x.state in ("starting", "running")]
            if len(active) >= self.s.max_sessions:
                raise SessionError("worker is at capacity")
            used = {x.display_num for x in active}
            num = next((n for n in range(self.s.display_base, self.s.display_base + 100)
                        if n not in used and not _display_in_use(n)), None)
            if num is None:
                raise SessionError("no free X display")
            sid = secrets.token_hex(8)
            sdir = self.s.data_dir / "sessions" / sid
            for sub in ("home", "saves", "states", "system", "pulse", "logs"):
                (sdir / sub).mkdir(parents=True, exist_ok=True)
            os.chmod(sdir, 0o700)
            self._link_bios(sdir / "system")
            sess = Session(sid, secrets.token_urlsafe(32), game, owner, num, sdir)
            self.sessions[sid] = sess
        try:
            await self._start(sess, rom, core)
            sess.state = "running"
        except Exception as e:  # noqa: BLE001 - report any start failure to the caller
            sess.state, sess.error = "failed", str(e)
            log.exception("session %s failed to start", sid)
            await self._kill(sess)
            raise SessionError(f"start failed: {e}") from e
        return sess

    def _link_bios(self, system_dir: Path) -> None:
        """Expose the user's BIOS files (RC_ROMS_DIR/bios, read-only) to the core via symlinks."""
        src = self.catalog.bios_dir()
        if not src.is_dir():
            return
        (system_dir / "fbneo").mkdir(exist_ok=True)   # FBNeo looks for neogeo.zip here
        for f in src.iterdir():
            if f.is_file() and not f.name.startswith("."):
                for d in (system_dir, system_dir / "fbneo"):
                    link = d / f.name
                    if not link.exists():
                        link.symlink_to(f.resolve())

    async def _spawn(self, sess: Session, name: str, argv: list[str], env: dict[str, str]) -> None:
        logf = open(sess.dir / "logs" / f"{name}.log", "ab")  # noqa: SIM115 - handed to child
        proc = await asyncio.create_subprocess_exec(
            *argv, env=env, stdout=logf, stderr=logf, stdin=asyncio.subprocess.DEVNULL, start_new_session=True
        )
        logf.close()
        sess.procs[name] = proc
        sess.sampler.track(name, proc.pid)

    async def _start(self, sess: Session, rom: Path, core: Path) -> None:
        v = self.s.video
        base_env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(sess.dir / "home"),
            "XDG_RUNTIME_DIR": str(sess.dir / "pulse"),
            "XDG_CONFIG_HOME": str(sess.dir / "home" / ".config"),
            "LANG": "C.UTF-8",
        }
        # 1) virtual screen
        await self._spawn(
            sess, "xvfb",
            ["Xvfb", sess.display, "-screen", "0", f"{v.width}x{v.height}x24", "-nolisten", "tcp", "-noreset"],
            base_env,
        )
        xvfb = sess.procs["xvfb"]
        # the socket must exist AND our own Xvfb must still be alive: if another server already
        # owned this display, ours exits and we must never attach the game to a foreign screen
        await self._wait_for(lambda: xvfb.returncode is not None or _display_in_use(sess.display_num), 10, "Xvfb")
        await asyncio.sleep(0.2)
        if xvfb.returncode is not None:
            raise SessionError(f"Xvfb exited ({xvfb.returncode}); display {sess.display} unavailable")
        # 2) private audio server with a null sink; we capture its monitor
        await self._spawn(
            sess, "pulse",
            ["pulseaudio", "-n", "--daemonize=no", "--exit-idle-time=-1", "--use-pid-file=no",
             "--disallow-module-loading", "--log-target=stderr",
             "-L", "module-null-sink sink_name=game rate=48000",
             "-L", f"module-native-protocol-unix auth-anonymous=1 socket={sess.pulse_socket}"],
            base_env,
        )
        await self._wait_for(sess.pulse_socket.exists, 10, "PulseAudio")
        # 3) the emulator
        cfg = sess.dir / "retroarch.cfg"
        cfg.write_text(RETROARCH_CFG.format(
            w=v.width, h=v.height, saves=sess.dir / "saves", states=sess.dir / "states", system=sess.dir / "system"))
        env = {**base_env, "DISPLAY": sess.display, "PULSE_SERVER": f"unix:{sess.pulse_socket}",
               "LIBGL_ALWAYS_SOFTWARE": "1", "GALLIUM_DRIVER": "llvmpipe",
               "LP_NUM_THREADS": os.environ.get("LP_NUM_THREADS", "2")}
        await self._spawn(sess, "retroarch", ["retroarch", "--config", str(cfg), "-L", str(core), str(rom)], env)
        sess.injector = XInputInjector(sess.display)
        ok = await self._wait_for(sess.injector.focus_first_window, 15, "RetroArch window")
        if not ok:
            raise SessionError("RetroArch window did not appear")
        if sess.procs["retroarch"].returncode is not None:
            raise SessionError("RetroArch exited during start")

    async def _wait_for(self, cond, timeout: float, what: str) -> bool:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if cond():
                return True
            await asyncio.sleep(0.1)
        raise SessionError(f"{what} did not become ready in {timeout}s")

    async def stop(self, sid: str, purge: bool = False) -> None:
        sess = self.sessions.get(sid)
        if not sess:
            return
        sess.state = "stopping"
        await self._kill(sess)
        sess.state = "stopped"
        if purge:
            shutil.rmtree(sess.dir, ignore_errors=True)
        self.sessions.pop(sid, None)

    async def _kill(self, sess: Session) -> None:
        if sess.injector:
            sess.injector.close()
            sess.injector = None
        for name in ("retroarch", "pulse", "xvfb"):
            p = sess.procs.get(name)
            if p and p.returncode is None:
                try:
                    os.killpg(p.pid, signal.SIGTERM)
                except ProcessLookupError:
                    continue
                try:
                    await asyncio.wait_for(p.wait(), 5)
                except asyncio.TimeoutError:
                    os.killpg(p.pid, signal.SIGKILL)
                    await p.wait()

    async def stop_all(self) -> None:
        for sid in list(self.sessions):
            await self.stop(sid)

    async def reap(self) -> None:
        """Mark sessions whose emulator died as failed (health check loop)."""
        for sess in list(self.sessions.values()):
            p = sess.procs.get("retroarch")
            if sess.state == "running" and p and p.returncode is not None:
                sess.state, sess.error = "failed", f"retroarch exited with {p.returncode}"
                await self._kill(sess)

    def get(self, sid: str) -> Session | None:
        return self.sessions.get(sid)

    def check_token(self, sid: str, token: str) -> Session | None:
        sess = self.sessions.get(sid)
        if sess and secrets.compare_digest(sess.token.encode(), token.encode()):
            return sess
        return None
